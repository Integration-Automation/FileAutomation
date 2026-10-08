"""Pipelines: tasks with dependencies, run in order with retry, timeout, resume and history.

* :class:`Pipeline` holds the tasks; ``run`` executes them in the calling thread,
  ``start`` in the background, ``resume`` continues a stored run.
* A task is a callable taking a :class:`TaskContext`, or an ``FA_*`` action.
  :class:`RetryPolicy`, a timeout, a ``when`` condition and an idempotency key
  say how it runs.
* A :class:`PipelineRun` and its :class:`TaskRun` entries say what happened. A
  :class:`RunStore` records them: :class:`MemoryRunStore` or :class:`SQLiteRunStore`.
* :func:`validate_definition`, :data:`PIPELINE_SCHEMA` and ``Pipeline.from_file``
  cover pipelines written as YAML or JSON.
* :func:`register_pipeline_ops` adds the ``FA_pipeline_*`` actions to a registry.

A run reports only through events on the bus (``pipeline.*`` and ``task.*``, all
carrying the run ID as their correlation ID).
"""

from __future__ import annotations

from automation_file.pipeline.actions import register_pipeline_ops
from automation_file.pipeline.definition import (
    PIPELINE_SCHEMA,
    RETRYABLE_EXCEPTIONS,
    SCHEMA_VERSION,
    load_definition,
    validate_definition,
)
from automation_file.pipeline.errors import PipelineDefinitionException, PipelineException
from automation_file.pipeline.model import (
    DEFAULT_RETRY_ON,
    PipelineRun,
    RetryPolicy,
    RunStatus,
    Schedule,
    Task,
    TaskContext,
    TaskRun,
    TaskStatus,
)
from automation_file.pipeline.pipeline import Pipeline
from automation_file.pipeline.store import (
    MemoryRunStore,
    RunStore,
    SQLiteRunStore,
    default_run_store,
    set_default_run_store,
)

__all__ = [
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
