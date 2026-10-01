"""Every GitHub Actions step pins its action to a commit SHA.

A tag such as ``@v4`` can be moved to new code at any time (the 2025
tj-actions/changed-files compromise rewrote tags), so each ``uses:`` names a
full 40-hex commit and carries the release it corresponds to as a comment,
which is what Dependabot reads and updates. Pinning also keeps Node 20 actions
from lingering unnoticed: GitHub removed Node 20 from its runners on 2026-09-23.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".github" / "workflows").is_dir())
_WORKFLOWS = sorted((_ROOT / ".github" / "workflows").glob("*.yml"))
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$")
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_LOCAL = re.compile(r"^\./")
_VERSION_COMMENT = re.compile(r"^\s+#\s*v\d+(\.\d+)*\s*$")


def _uses(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(line number, action reference, rest of line)`` for each remote ``uses:``."""
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = _USES.match(line)
        if match and not _LOCAL.match(match.group(1)):
            found.append((number, match.group(1), match.group(2)))
    return found


def test_workflows_exist():
    assert _WORKFLOWS


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_is_valid_yaml(workflow):
    # GitHub runs nothing from a workflow it cannot parse, and the checks below read the files as
    # text, so they would not notice. One way to get there: a one-line `run:` holding ": ", as in
    # pip's `--only-binary :all: -r`. Such a command needs a block (`run: |`).
    assert yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_with_its_version(workflow):
    bad = [
        f"{workflow.name}:{number} {ref}{rest}"
        for number, ref, rest in _uses(workflow)
        if not (_PINNED.match(ref) and _VERSION_COMMENT.match(rest))
    ]
    assert bad == []


def test_one_version_per_action():
    # The same action at two different commits means a partial upgrade.
    seen: dict[str, set[str]] = {}
    for workflow in _WORKFLOWS:
        for _number, ref, _rest in _uses(workflow):
            action, _, sha = ref.partition("@")
            seen.setdefault(action, set()).add(sha)
    assert {action: shas for action, shas in seen.items() if len(shas) > 1} == {}


def test_dependabot_keeps_pins_current_on_dev():
    # Pinned SHAs only stay current if something bumps them; every update
    # goes to dev because main is the release branch.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    ecosystems = {block.split()[0].strip("\"'") for block in blocks}
    assert {"pip", "github-actions"} <= ecosystems
    assert all(re.search(r"^\s*target-branch:\s*\"dev\"", block, re.MULTILINE) for block in blocks)


def test_dependabot_waits_a_week_before_proposing_a_release():
    # A compromised release is usually found and yanked within days. Dependabot's
    # own default wait is 3 days, and zizmor's dependabot-cooldown audit asks
    # for 7. The wait never delays security updates.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    days = [re.search(r"^\s*default-days:\s*(\d+)", block, re.MULTILINE) for block in blocks]
    assert blocks and all(match and int(match.group(1)) >= 7 for match in days)


def _checkout_steps(path: Path) -> list[tuple[int, str]]:
    """Return ``(line number, step text)`` for each ``actions/checkout`` step."""
    lines = path.read_text(encoding="utf-8").splitlines()
    steps = []
    for index, line in enumerate(lines):
        if not re.search(r"uses:\s*actions/checkout@", line):
            continue
        column = line.index("uses:")
        body = [line]
        for following in lines[index + 1 :]:
            indent = len(following) - len(following.lstrip())
            if following.strip() and (indent < column or following.lstrip().startswith("- ")):
                break
            body.append(following)
        steps.append((index + 1, "\n".join(body)))
    return steps


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_checkout_decides_on_persisted_credentials(workflow):
    # actions/checkout leaves the job token in .git/config unless told not
    # to, where every later step (and any uploaded workspace) can read it.
    # Only jobs that push keep it, and they say so.
    bad = [
        f"{workflow.name}:{number}"
        for number, step in _checkout_steps(workflow)
        if not re.search(r"^\s*persist-credentials:\s*(true|false)\b", step, re.MULTILINE)
    ]
    assert bad == []


_JOB_HEAD = re.compile(r"^  [A-Za-z0-9_-]+:\s*(#.*)?$")


def _jobs(path: Path) -> list[tuple[str, str]]:
    """Return ``(job id, job text)`` for each job under ``jobs:`` in a workflow."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^jobs:\s*(#.*)?$", line))
    heads = [i for i in range(start + 1, len(lines)) if _JOB_HEAD.match(lines[i])]
    ends = [*heads[1:], len(lines)]
    return [
        (lines[i].strip().rstrip(":"), "\n".join(lines[i:end]))
        for i, end in zip(heads, ends, strict=True)
    ]


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_a_timeout(workflow):
    # Without timeout-minutes a hung job runs for GitHub's default six hours.
    # Each job sets about three times its slowest recent run, at least 15 minutes.
    bad = [
        name
        for name, body in _jobs(workflow)
        if "runs-on:" in body and not re.search(r"^\s*timeout-minutes:", body, re.MULTILINE)
    ]
    assert bad == []


_REQUIREMENTS = _ROOT / ".github" / "requirements"
_LOCKED_INSTALL = (
    "python -m pip install --require-hashes --only-binary :all: -r .github/requirements/publish.txt"
)
_PIP_INSTALL = re.compile(r"\bpip\d*\s+install\b")
_STEP_PREFIX = re.compile(r"^\s*(?:-\s*)?(?:run:\s*)?")
_TOOL = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", re.MULTILINE)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==", re.MULTILINE)


def _publish_jobs() -> list[tuple[str, str]]:
    """Return ``(workflow:job, job text)`` for each job that is given the PyPI token."""
    return [
        (f"{workflow.name}:{name}", body)
        for workflow in _WORKFLOWS
        for name, body in _jobs(workflow)
        if "secrets.PYPI_API_TOKEN" in body
    ]


def _pip_installs(job: str) -> list[str]:
    """Return each ``pip install`` command of a job, without its YAML key and any comment."""
    commands = []
    for line in job.splitlines():
        code = line.split("#", 1)[0]
        if _PIP_INSTALL.search(code):
            commands.append(_STEP_PREFIX.sub("", code).strip())
    return commands


def _normalised(names: list[str]) -> set[str]:
    """Return project names in the form PyPI compares them: lower case, runs of ``-_.`` as ``-``."""
    return {re.sub(r"[-_.]+", "-", name).lower() for name in names}


def test_the_publish_jobs_are_the_two_known_ones():
    # A new job that is given the token has to be looked at against the rule below.
    assert [name for name, _body in _publish_jobs()] == [
        "ci-dev.yml:publish-dev",
        "publish.yml:publish",
    ]


@pytest.mark.parametrize("job", _publish_jobs(), ids=lambda job: job[0])
def test_publish_jobs_install_only_hash_locked_tools(job):
    # What such a job installs runs beside the PyPI token and builds the files it uploads. Its one
    # install takes wheels whose hashes are in publish.txt: no `pip install --upgrade pip` and no
    # unpinned package, so a release published a minute ago cannot reach the job.
    _name, body = job
    assert _pip_installs(body) == [_LOCKED_INSTALL]


def test_publish_lock_pins_every_tool_in_publish_in():
    # A tool named in publish.in but not pinned in publish.txt means the lock was not regenerated.
    tools = _normalised(_TOOL.findall((_REQUIREMENTS / "publish.in").read_text(encoding="utf-8")))
    pinned = _normalised(_PIN.findall((_REQUIREMENTS / "publish.txt").read_text(encoding="utf-8")))
    assert tools and tools <= pinned


def test_dependabot_reads_the_publish_lock():
    # Locked versions only move when Dependabot is told which directory holds the lock.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    pip = [block for block in blocks if block.split()[0].strip("\"'") == "pip"]
    listed = re.compile(r"^\s*(?:-|directory:)\s*\"/\.github/requirements\"", re.MULTILINE)
    assert any(listed.search(block) for block in pip)
