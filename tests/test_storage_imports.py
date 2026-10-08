"""The storage layer stays independent of the registry, the GUI and the backend SDKs.

It reads the module-level imports of every file under ``automation_file/storage``:
each one is either from the standard library or from the short list of first-party
modules below. An SDK imported lazily inside a function, or a name imported only
for type checking, is not a module-level import and stays allowed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

STORAGE_PACKAGE = Path(__file__).resolve().parent.parent / "automation_file" / "storage"
ALLOWED_FIRST_PARTY = (
    "automation_file.exceptions",
    "automation_file.logging_config",
    "automation_file.core.checksum",
    "automation_file.local.safe_paths",
    "automation_file.storage",
)
MODULES = sorted(STORAGE_PACKAGE.glob("*.py"))


def _module_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            names.append(node.module or "")
    return names


def _is_allowed(name: str) -> bool:
    top_level = name.partition(".")[0]
    if top_level == "automation_file":
        return any(
            name == allowed or name.startswith(f"{allowed}.") for allowed in ALLOWED_FIRST_PARTY
        )
    return top_level in sys.stdlib_module_names or name == "__future__"


def test_the_package_has_modules() -> None:
    assert len(MODULES) >= 9


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_module_level_imports_stay_inside_the_layer(path: Path) -> None:
    offending = [name for name in _module_level_imports(path) if not _is_allowed(name)]
    assert offending == []


def test_the_guard_recognises_what_it_must_refuse() -> None:
    assert _is_allowed("os.path") is True
    assert _is_allowed("automation_file.storage.uri") is True
    assert _is_allowed("automation_file.exceptions") is True
    assert _is_allowed("boto3") is False
    assert _is_allowed("PySide6.QtWidgets") is False
    assert _is_allowed("automation_file.core.action_registry") is False
    assert _is_allowed("automation_file.remote.s3.client") is False
    assert _is_allowed("automation_file.exceptions_extra") is False
