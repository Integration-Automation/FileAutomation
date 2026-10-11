"""Every GitHub Actions step pins its action to a commit SHA.

A tag such as ``@v4`` can be moved to new code at any time (the 2025
tj-actions/changed-files compromise rewrote tags), so each ``uses:`` names a
full 40-hex commit and carries the release it corresponds to as a comment,
which is what Dependabot reads and updates. Pinning also keeps Node 20 actions
from lingering unnoticed: GitHub removed Node 20 from its runners on 2026-09-23.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # declared in *.toml for Python<3.11

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
_BUILD = re.compile(r"\bpython\S*\s+-m\s+build\b|\bpyproject-build\b")
_STEP_PREFIX = re.compile(r"^\s*(?:-\s*)?(?:run:\s*)?")
_TOOL = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", re.MULTILINE)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==(\S+)", re.MULTILINE)
# The metadata the publish jobs build from: each writes one of these to pyproject.toml.
_METADATA = ["stable.toml", "dev.toml"]


def _publish_jobs() -> list[tuple[str, str]]:
    """Return ``(workflow:job, job text)`` for each job that is given the PyPI token."""
    return [
        (f"{workflow.name}:{name}", body)
        for workflow in _WORKFLOWS
        for name, body in _jobs(workflow)
        if "secrets.PYPI_API_TOKEN" in body
    ]


def _commands(job: str, pattern: re.Pattern[str]) -> list[str]:
    """Return each command of a job that ``pattern`` finds, without its YAML key and any comment."""
    commands = []
    for line in job.splitlines():
        code = line.split("#", 1)[0]
        if pattern.search(code):
            commands.append(_STEP_PREFIX.sub("", code).strip())
    return commands


def _pins() -> dict[str, str]:
    """Return ``{name: version}`` for each pin in ``publish.txt``, names as PyPI compares them."""
    text = (_REQUIREMENTS / "publish.txt").read_text(encoding="utf-8")
    return {canonicalize_name(name): version for name, version in _PIN.findall(text)}


def _build_requires(metadata: str) -> list[Requirement]:
    """Return ``build-system.requires`` of a metadata file in the repository root."""
    with (_ROOT / metadata).open("rb") as handle:
        return [Requirement(item) for item in tomllib.load(handle)["build-system"]["requires"]]


def _is_locked(requirement: Requirement, pins: dict[str, str]) -> bool:
    """Tell whether ``pins`` holds a version of the package that ``requirement`` accepts."""
    version = pins.get(canonicalize_name(requirement.name))
    return version is not None and requirement.specifier.contains(version)


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
    assert _commands(body, _PIP_INSTALL) == [_LOCKED_INSTALL]


@pytest.mark.parametrize("job", _publish_jobs(), ids=lambda job: job[0])
def test_publish_jobs_build_with_the_locked_backend(job):
    # An isolated build downloads the newest setuptools of that minute, outside publish.txt, and runs
    # it beside the token. --no-isolation builds with the backend the locked install put in the job.
    _name, body = job
    builds = _commands(body, _BUILD)
    assert builds and all("--no-isolation" in build.split() for build in builds)


def test_publish_lock_pins_every_tool_in_publish_in():
    # A tool named in publish.in but not pinned in publish.txt means the lock was not regenerated.
    listed = _TOOL.findall((_REQUIREMENTS / "publish.in").read_text(encoding="utf-8"))
    tools = {canonicalize_name(name) for name in listed}
    assert tools and tools <= set(_pins())


@pytest.mark.parametrize("metadata", _METADATA)
def test_publish_lock_satisfies_build_system_requires(metadata):
    # --no-isolation checks build-system.requires against what is installed and installs nothing, so
    # a backend that is not locked, or a floor raised without regenerating publish.txt, has to fail
    # here and not in the publish job.
    pins = _pins()
    requires = _build_requires(metadata)
    assert requires and [str(item) for item in requires if not _is_locked(item, pins)] == []


def test_dependabot_reads_the_publish_lock():
    # Locked versions only move when Dependabot is told which directory holds the lock.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    pip = [block for block in blocks if block.split()[0].strip("\"'") == "pip"]
    listed = re.compile(r"^\s*(?:-|directory:)\s*\"/\.github/requirements\"", re.MULTILINE)
    assert any(listed.search(block) for block in pip)
