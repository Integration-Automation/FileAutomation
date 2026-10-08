"""``dev.toml`` describes the same package as ``stable.toml`` under another name.

CI installs and tests ``dev.toml``, and the dev channel (``automation_file_dev``) is built from it,
while the stable release is built from ``stable.toml``. A dependency, an entry point or a packaging
rule on one side only ships a package that differs from the one the tests ran against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # declared in *.toml for Python<3.11

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    with (REPO_ROOT / name).open("rb") as handle:
        return tomllib.load(handle)


STABLE_FILE = _load("stable.toml")
DEV_FILE = _load("dev.toml")
STABLE = STABLE_FILE["project"]
DEV = DEV_FILE["project"]


def test_package_names_differ():
    assert STABLE["name"] == "automation_file"
    assert DEV["name"] == "automation_file_dev"


def test_runtime_dependencies_match():
    assert sorted(DEV["dependencies"]) == sorted(STABLE["dependencies"])


def test_python_floor_matches():
    assert DEV["requires-python"] == STABLE["requires-python"]


def test_optional_dependency_groups_match():
    assert DEV.get("optional-dependencies", {}) == STABLE.get("optional-dependencies", {})


@pytest.mark.parametrize("table", ["scripts", "gui-scripts", "entry-points"])
def test_entry_points_match(table):
    assert DEV.get(table, {}) == STABLE.get(table, {})


def test_shipped_files_match():
    # Package discovery and package data decide which files reach the wheel.
    assert DEV_FILE["tool"]["setuptools"] == STABLE_FILE["tool"]["setuptools"]


@pytest.mark.parametrize("metadata", [STABLE_FILE, DEV_FILE], ids=["stable.toml", "dev.toml"])
def test_only_the_library_is_packaged(metadata):
    # ``tests`` has an ``__init__.py``; discovery without ``include`` installs it as a
    # top-level package next to ``automation_file``.
    find = metadata["tool"]["setuptools"]["packages"]["find"]
    assert find["include"] == ["automation_file", "automation_file.*"]
    assert find["namespaces"] is False


def test_build_backend_matches():
    assert DEV_FILE["build-system"] == STABLE_FILE["build-system"]
