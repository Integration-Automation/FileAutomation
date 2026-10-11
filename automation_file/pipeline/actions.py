"""``FA_pipeline_*`` actions: pipelines for JSON action lists.

Each function takes a definition as a mapping or as the path of a YAML / JSON
file and returns JSON-friendly values, so the same call works from Python, an
action file, the CLI, the TCP and HTTP action servers and as an MCP tool:

.. code-block:: json

    [
        ["FA_pipeline_validate", {"definition": "pipelines/daily-report.yaml"}],
        ["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml",
                             "params": {"date": "2026-10-08"}}]
    ]

Runs are recorded in the default run store (:func:`set_default_run_store`), which
is where ``FA_pipeline_status``, ``FA_pipeline_history`` and ``FA_pipeline_resume``
look them up.

A definition names the actions its tasks call, so ``FA_pipeline_run`` and
``FA_pipeline_resume`` can reach every registered action. On an action server
allow them only for clients that may call all of those.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from automation_file.pipeline.definition import load_definition, validate_definition
from automation_file.pipeline.errors import PipelineDefinitionException, PipelineException
from automation_file.pipeline.pipeline import Pipeline
from automation_file.pipeline.store import default_run_store

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

Definition = Mapping[str, Any] | str | os.PathLike[str]


def _document(definition: Definition) -> Any:
    """Return the definition document: the mapping itself, or the content of the file."""
    if isinstance(definition, Mapping):
        return definition
    if isinstance(definition, (str, os.PathLike)):
        return load_definition(definition)
    raise PipelineDefinitionException(
        f"definition: expected a mapping or a file path, got {type(definition).__name__}"
    )


def pipeline_run(
    definition: Definition,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a pipeline definition (a mapping or a YAML/JSON file path) and return the run.

    A failed task does not raise: read ``status`` and ``tasks`` of the result.
    ``dry_run`` plans the run without executing or recording anything.
    """
    pipeline = Pipeline.from_dict(_document(definition))
    return pipeline.run(params=params, dry_run=dry_run).to_dict()


def pipeline_validate(definition: Definition) -> dict[str, Any]:
    """Check a pipeline definition and return ``{"valid": ..., "errors": [...]}``.

    A file that cannot be read or parsed is reported the same way instead of raising.
    """
    try:
        errors = validate_definition(_document(definition))
    except PipelineDefinitionException as error:
        errors = list(error.problems)
    return {"valid": not errors, "errors": errors}


def pipeline_status(run_id: str) -> dict[str, Any]:
    """Return the recorded state of the run ``run_id`` and of its tasks."""
    run = default_run_store().get_run(run_id)
    if run is None:
        raise PipelineException(f"unknown run {run_id!r}")
    return run.to_dict()


def pipeline_history(pipeline: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Return the latest recorded runs, newest first, of one pipeline or of all."""
    return [run.to_dict() for run in default_run_store().list_runs(pipeline, limit)]


def pipeline_resume(run_id: str, definition: Definition) -> dict[str, Any]:
    """Continue the recorded run ``run_id``: keep what succeeded and run the rest."""
    pipeline = Pipeline.from_dict(_document(definition))
    return pipeline.resume(run_id).to_dict()


def pipeline_commands() -> dict[str, Callable[..., Any]]:
    """Return every ``FA_pipeline_*`` action by name."""
    return {
        "FA_pipeline_run": pipeline_run,
        "FA_pipeline_validate": pipeline_validate,
        "FA_pipeline_status": pipeline_status,
        "FA_pipeline_history": pipeline_history,
        "FA_pipeline_resume": pipeline_resume,
    }


def register_pipeline_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_pipeline_*`` command into ``registry``."""
    registry.register_many(pipeline_commands())
