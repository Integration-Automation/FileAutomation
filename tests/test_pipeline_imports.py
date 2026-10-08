"""What the pipeline package may import at module level, and what it exports.

``build_default_registry()`` runs while ``automation_file.core.action_executor``
is still being imported. For the ``FA_pipeline_*`` actions to be registered there,
no module of the package may import the executor at module level (the pipeline
reaches the shared registry inside a function), and nothing outside the standard
library and the project itself: PyYAML is imported where a YAML file is read.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import automation_file.pipeline as pipeline_package

PACKAGE = Path(pipeline_package.__file__).resolve().parent
MODULES = sorted(PACKAGE.glob("*.py"))
FORBIDDEN = ("automation_file.core.action_executor", "automation_file.ui", "automation_file.server")
PUBLIC_NAMES = [
    "DEFAULT_RETRY_ON",
    "PIPELINE_SCHEMA",
    "RETRYABLE_EXCEPTIONS",
    "SCHEMA_VERSION",
    "MemoryRunStore",
    "Pipeline",
    "PipelineDefinitionException",
    "PipelineException",
    "PipelineRun",
    "RetryPolicy",
    "RunStatus",
    "RunStore",
    "SQLiteRunStore",
    "Schedule",
    "Task",
    "TaskContext",
    "TaskRun",
    "TaskStatus",
    "default_run_store",
    "load_definition",
    "register_pipeline_ops",
    "set_default_run_store",
    "validate_definition",
]


def _module_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            names.append(node.module or "")
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _is_allowed(name: str) -> bool:
    top_level = name.partition(".")[0]
    if top_level == "automation_file":
        return not any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN)
    return top_level in sys.stdlib_module_names or name == "__future__"


def test_the_package_has_its_modules() -> None:
    assert {path.name for path in MODULES} >= {
        "__init__.py",
        "actions.py",
        "definition.py",
        "errors.py",
        "graph.py",
        "model.py",
        "pipeline.py",
        "reporting.py",
        "runner.py",
        "store.py",
        "substitution.py",
        "worker.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_module_level_imports_are_safe_while_the_registry_is_built(path: Path) -> None:
    offending = [name for name in _module_level_imports(path) if not _is_allowed(name)]
    assert offending == []


def test_the_guard_recognises_what_it_must_refuse() -> None:
    assert _is_allowed("threading") is True
    assert _is_allowed("automation_file.events") is True
    assert _is_allowed("automation_file.core.progress") is True
    assert _is_allowed("automation_file.core.action_executor") is False
    assert _is_allowed("automation_file.core.action_executor.executor") is False
    assert _is_allowed("automation_file.ui.launcher") is False
    assert _is_allowed("yaml") is False
    assert _is_allowed("jsonschema") is False


def test_the_package_exports_its_public_names() -> None:
    assert sorted(pipeline_package.__all__) == sorted(PUBLIC_NAMES)
    for name in PUBLIC_NAMES:
        assert hasattr(pipeline_package, name), name


def test_every_module_starts_with_the_future_import() -> None:
    for path in MODULES:
        assert "from __future__ import annotations" in path.read_text(encoding="utf-8"), path.name
