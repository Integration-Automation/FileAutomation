"""The stable release helper: which version a push to ``main`` publishes."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "stable_release.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"


def _load_script():
    spec = importlib.util.spec_from_file_location("stable_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stable_release = _load_script()


def _metadata(root: Path, stable: str, dev: str) -> None:
    (root / "stable.toml").write_text(
        f'[project]\nname = "automation_file"\nversion = "{stable}"\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    (root / "dev.toml").write_text(
        f'[project]\nname = "automation_file_dev"\nversion = "{dev}"\n', encoding="utf-8"
    )


def _versions(root: Path) -> tuple[str, str]:
    stable = (root / "stable.toml").read_text(encoding="utf-8")
    dev = (root / "dev.toml").read_text(encoding="utf-8")
    return (
        re.search(r'^version = "([^"]+)"', stable, re.MULTILINE).group(1),
        re.search(r'^version = "([^"]+)"', dev, re.MULTILINE).group(1),
    )


@pytest.mark.parametrize(
    "tags,expected",
    [
        (["v0.0.9", "v0.0.51", "v0.0.10"], (0, 0, 51)),
        (["v1.2.0", "v1.10.0", "v1.9.9"], (1, 10, 0)),
        (["v0.0.51\n", "release-1", "v2", "v1.0.0rc1", "1.0.0"], (0, 0, 51)),
        ([], None),
    ],
)
def test_the_newest_release_is_the_highest_plain_tag(tags, expected):
    assert stable_release.newest_release(tags) == expected


@pytest.mark.parametrize(
    "current,released,expected",
    [
        ((0, 0, 51), (0, 0, 51), (0, 0, 52)),  # the usual patch release
        ((0, 0, 33), (0, 0, 51), (0, 0, 34)),  # dev.toml is a floor of its own
        ((1, 0, 0), (0, 0, 51), (1, 0, 0)),  # MAJOR was raised: published as written
        ((1, 1, 0), (1, 0, 7), (1, 1, 0)),  # MINOR was raised
        ((1, 1, 0), (1, 1, 0), (1, 1, 1)),  # the release after it is a patch again
        ((0, 0, 5), None, (0, 0, 6)),  # no tag to compare with
    ],
)
def test_the_next_version_is_a_patch_unless_major_or_minor_was_raised(current, released, expected):
    assert stable_release.next_version(current, released) == expected


def test_bump_writes_a_patch_release_into_both_files(tmp_path):
    _metadata(tmp_path, "0.0.51", "0.0.33")
    assert stable_release.bump(tmp_path, (0, 0, 51)) == ((0, 0, 52), (0, 0, 34))
    assert _versions(tmp_path) == ("0.0.52", "0.0.34")
    assert 'requires-python = ">=3.10"' in (tmp_path / "stable.toml").read_text(encoding="utf-8")


def test_bump_keeps_a_raised_major_or_minor_as_written(tmp_path):
    _metadata(tmp_path, "1.0.0", "1.0.0")
    assert stable_release.bump(tmp_path, (0, 0, 51)) == ((1, 0, 0), (1, 0, 0))
    assert _versions(tmp_path) == ("1.0.0", "1.0.0")
    _metadata(tmp_path, "1.1.0", "1.0.4")
    assert stable_release.bump(tmp_path, (1, 0, 3)) == ((1, 1, 0), (1, 0, 5))


def test_bump_refuses_a_version_that_is_not_above_the_newest_tag(tmp_path):
    _metadata(tmp_path, "0.0.40", "0.0.33")
    with pytest.raises(
        stable_release.ReleaseError, match=r"0\.0\.41, which is not above .* v0\.0\.51"
    ):
        stable_release.bump(tmp_path, (0, 0, 51))
    assert _versions(tmp_path) == ("0.0.40", "0.0.33")


def test_a_file_without_a_version_is_an_error(tmp_path):
    _metadata(tmp_path, "0.0.51", "0.0.33")
    (tmp_path / "dev.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(stable_release.ReleaseError, match="has no version"):
        stable_release.bump(tmp_path, (0, 0, 51))
    # Nothing is written unless both files can be: stable.toml keeps its version.
    assert 'version = "0.0.51"' in (tmp_path / "stable.toml").read_text(encoding="utf-8")


def test_main_reads_the_tags_and_writes_what_the_workflow_reads(tmp_path, monkeypatch, capsys):
    _metadata(tmp_path, "0.0.51", "0.0.33")
    output = tmp_path / "github_output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(stable_release, "git_tags", lambda root: ["v0.0.50", "v0.0.51"])
    assert stable_release.main(["bump"]) == 0
    assert output.read_text(encoding="utf-8") == "new_version=0.0.52\ndev_version=0.0.34\n"
    assert "stable.toml -> 0.0.52" in capsys.readouterr().out


def test_main_stops_the_job_when_the_release_cannot_be_made(tmp_path, monkeypatch, capsys):
    _metadata(tmp_path, "0.0.40", "0.0.33")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(stable_release, "git_tags", lambda root: ["v0.0.51"])
    assert stable_release.main(["bump"]) == 1
    assert "not above the newest tag" in capsys.readouterr().err
    assert stable_release.main(["release"]) == 2


def test_git_tags_lists_the_tags_of_this_checkout():
    tags = stable_release.git_tags(REPO_ROOT)
    assert all(tag.startswith("v") for tag in tags)


def test_the_workflow_picks_the_version_before_it_builds_and_has_every_tag():
    job = WORKFLOW.read_text(encoding="utf-8")
    pick = job.index("python scripts/stable_release.py bump")
    assert pick < job.index("cp stable.toml pyproject.toml") < job.index("python -m build")
    assert "id: bump" in job
    # The newest tag decides between a patch and a raised version, so the checkout needs them all.
    assert "fetch-depth: 0" in job
    assert "steps.bump.outputs.new_version" in job
