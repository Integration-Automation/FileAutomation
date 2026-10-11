"""The semantic pipeline tools: ``pipeline_create``, ``pipeline_run`` and ``pipeline_status``.

``pipeline_create`` validates a definition and stores it under a name;
``pipeline_run`` runs a stored definition, or plans it with ``dry_run``;
``pipeline_status`` reports recorded runs.

Definitions are JSON files ``<name>.json`` in the policy's ``pipeline_dir``, a
storage URI or a local directory. Without one they are kept in memory and are
gone when the server stops.

What a definition may call is checked twice, when it is created and again
when it is run, because the file may have been written by something else in
between. A run gets a registry of its own that holds only the allowed actions,
with the ``FA_storage_*`` ones replaced by their guarded versions
(:mod:`automation_file.server.mcp_pipeline_actions`), so the locations a task
touches are checked when the task runs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from automation_file.core.action_executor import executor
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import MCPServerException, StorageNotFoundException
from automation_file.pipeline.definition import validate_definition
from automation_file.pipeline.errors import PipelineDefinitionException
from automation_file.pipeline.model import PipelineRun, RunStatus
from automation_file.pipeline.pipeline import Pipeline
from automation_file.pipeline.store import default_run_store
from automation_file.server.action_acl import nested_action_names
from automation_file.server.mcp_pipeline_actions import (
    GUARDED_ACTIONS,
    GuardedStorageActions,
    default_pipeline_actions,
)
from automation_file.server.mcp_policy import (
    ACTION_NOT_ALLOWED,
    ALREADY_EXISTS,
    LIMIT_EXCEEDED,
    NOT_FOUND,
    MCPPermissionException,
    MCPToolException,
)
from automation_file.server.mcp_tool_model import (
    DRY_RUN_HELP,
    SemanticTool,
    ToolSession,
    arguments_schema,
    flag,
    text,
    whole,
)
from automation_file.storage.backend import StorageBackend, join_path
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.memory_storage import MemoryStorage

PIPELINE_CREATE = "pipeline_create"
PIPELINE_RUN = "pipeline_run"
PIPELINE_STATUS = "pipeline_status"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_NAME_RULE = (
    "a pipeline name is 1 to 100 characters: letters, digits, '.', '_' and '-', "
    "starting with a letter or a digit"
)
_SUFFIX = ".json"
_STATE_KEY = "pipeline_definitions"
_MEMORY_LOCATION = "memory (kept until the server stops)"
_DEFAULT_HISTORY = 5
_LISTED_NAMES = 20


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    built: dict[str, Any] = {}
    for key, value in pairs:
        if key in built:
            raise ValueError(f"duplicate key {key!r}")
        built[key] = value
    return built


class DefinitionStore:
    """Named pipeline definitions, one JSON file each, in one storage directory."""

    def __init__(
        self, backend: StorageBackend, base: str = "", location: str | None = None
    ) -> None:
        self._backend = backend
        self._base = base
        self._location = location

    @classmethod
    def for_session(cls, session: ToolSession) -> DefinitionStore:
        """Return the store the policy describes; a local directory is confined to itself."""
        directory = session.policy.pipeline_dir
        if directory is None:
            return cls(MemoryStorage("mcp-pipelines"))
        backend, path = session.guard.inner.resolve(directory)
        if isinstance(backend, LocalStorage):
            return cls(LocalStorage(backend.local_path(path)), "", str(directory))
        return cls(backend, path, str(directory))

    @property
    def location(self) -> str:
        """Where the definitions are kept, for reports."""
        return _MEMORY_LOCATION if self._location is None else self._location

    @property
    def persistent(self) -> bool:
        return self._location is not None

    def _path(self, name: str) -> str:
        return join_path(self._base, f"{name}{_SUFFIX}")

    def exists(self, name: str) -> bool:
        return self._backend.exists(self._path(name))

    def names(self) -> list[str]:
        """Return the stored names, sorted."""
        try:
            listing = self._backend.list_dir(self._base)
        except StorageNotFoundException:
            return []
        return sorted(
            info.name[: -len(_SUFFIX)]
            for info in listing
            if not info.is_dir and info.name.endswith(_SUFFIX)
        )

    def save(self, name: str, data: bytes, *, overwrite: bool) -> None:
        """Store the JSON text ``data`` as the definition ``name``."""
        self._backend.mkdir(self._base)
        self._backend.write_bytes(self._path(name), data, overwrite=overwrite)

    def load(self, name: str, max_bytes: int) -> dict[str, Any]:
        """Return the definition ``name`` as parsed, without validating it."""
        path = self._path(name)
        try:
            size = self._backend.stat(path).size
        except StorageNotFoundException as error:
            stored = ", ".join(self.names()[:_LISTED_NAMES]) or "none"
            raise MCPToolException(
                f"no pipeline named {name!r} is stored (stored: {stored})", NOT_FOUND
            ) from error
        if size is not None and size > max_bytes:
            raise MCPPermissionException(
                f"the definition of {name!r} is larger than {max_bytes} bytes (--max-write-bytes)",
                LIMIT_EXCEEDED,
            )
        try:
            document = json.loads(
                self._backend.read_bytes(path).decode("utf-8"), object_pairs_hook=_unique_keys
            )
        except (ValueError, RecursionError) as error:
            raise MCPToolException(
                f"the stored definition of {name!r} is not valid JSON"
            ) from error
        if not isinstance(document, dict):
            raise MCPToolException(f"the stored definition of {name!r} is not a mapping")
        return document


def definitions(session: ToolSession) -> DefinitionStore:
    """Return the session's definition store, creating it on first use."""
    store = session.state.get(_STATE_KEY)
    if store is None:
        store = session.state[_STATE_KEY] = DefinitionStore.for_session(session)
    return store


# ---------------------------------------------------------------------- what a pipeline may call


def allowed_actions(session: ToolSession) -> frozenset[str]:
    """Return the actions a pipeline may name: the policy's list, or its permissions' default."""
    explicit = session.policy.pipeline_actions
    if explicit is None:
        return default_pipeline_actions(session.policy)
    return frozenset(explicit)


def check_pipeline_actions(session: ToolSession) -> None:
    """Refuse a policy whose pipeline allow list names an action the server does not have."""
    missing = sorted(
        name
        for name in allowed_actions(session)
        if name not in GUARDED_ACTIONS and session.registry.resolve(name) is None
    )
    if missing:
        raise MCPServerException(
            "the pipeline allow list names action(s) this server does not expose: "
            + ", ".join(missing)
        )


def pipeline_registry(session: ToolSession) -> ActionRegistry:
    """Return the registry a pipeline runs with: the allowed actions and nothing else."""
    guarded = GuardedStorageActions(session).commands()
    registry = ActionRegistry()
    for name in sorted(allowed_actions(session)):
        command = guarded.get(name) or session.registry.resolve(name)
        if command is not None:
            registry.register(name, command)
    return registry


def action_refusals(
    session: ToolSession, document: Mapping[str, Any], params: Mapping[str, Any] | None
) -> list[str]:
    """Return what a valid definition (and the parameters of a run) may not call.

    An action named inside the arguments of another one would be run by the
    shared executor, outside the policy. It is accepted only when the policy
    lists it by name and it is not one of the guarded storage actions.
    """
    allowed = allowed_actions(session)
    nestable = frozenset(session.policy.pipeline_actions or ()) - GUARDED_ACTIONS
    known = {*executor.registry.event_dict, *session.registry.event_dict, *GUARDED_ACTIONS}
    refusals: list[str] = []
    for task_id, spec in document["tasks"].items():
        action = spec["action"]
        if action[0] not in allowed:
            refusals.append(f"tasks.{task_id}.action[0]: {action[0]} is not allowed in a pipeline")
        refusals.extend(
            f"tasks.{task_id}.action: its arguments name the action {name}"
            for name in sorted(set(nested_action_names(action[1:], known)) - nestable)
        )
    given = [document.get("params"), dict(params or {})]
    refusals.extend(
        f"params: a parameter names the action {name}"
        for name in sorted(set(nested_action_names(given, known)) - nestable)
    )
    return refusals


def _require_allowed(
    session: ToolSession, document: Mapping[str, Any], params: Mapping[str, Any] | None
) -> None:
    refusals = action_refusals(session, document, params)
    if refusals:
        allowed = ", ".join(sorted(allowed_actions(session))) or "none"
        raise MCPPermissionException(
            f"{'; '.join(refusals)}. A pipeline run through this server may call: {allowed}",
            ACTION_NOT_ALLOWED,
        )


def _checked_name(name: str) -> str:
    if _NAME.fullmatch(name) is None:
        raise MCPToolException(_NAME_RULE)
    return name


def _valid_document(document: Mapping[str, Any], name: str) -> None:
    """Raise unless ``document`` is a valid definition that names itself ``name``."""
    problems = validate_definition(document)
    if problems:
        raise PipelineDefinitionException(problems)
    if document["name"] != name:
        raise MCPToolException(
            f"the definition names itself {str(document['name'])[:100]!r}; its name must be "
            f"{name!r}, the name it is stored under"
        )


def run_view(session: ToolSession, run: PipelineRun) -> dict[str, Any]:
    """Return a run as JSON data, with a task result left out when it is too large to return."""
    limit = session.policy.max_read_bytes
    document = run.to_dict()
    for state in document["tasks"].values():
        size = len(json.dumps(state["result"], default=str))
        if size > limit:
            state["result"] = None
            state["result_omitted"] = f"{size} bytes, more than the {limit} this server returns"
    return document


# ---------------------------------------------------------------------- the tools


def pipeline_create(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Validate a definition and store it under ``name`` for ``pipeline_run``."""
    policy = session.policy
    policy.require_write(PIPELINE_CREATE)
    name = _checked_name(args["name"])
    document = {"name": name, **args["definition"]}
    _valid_document(document, name)
    if "schedule" in document:
        raise MCPPermissionException(
            "a pipeline created through MCP cannot carry a schedule: when a pipeline runs "
            "by itself is decided by whoever operates the server",
            ACTION_NOT_ALLOWED,
        )
    _require_allowed(session, document, None)
    data = json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")
    if len(data) > policy.max_write_bytes:
        raise MCPPermissionException(
            f"the definition is {len(data)} bytes and this server stores at most "
            f"{policy.max_write_bytes} (--max-write-bytes)",
            LIMIT_EXCEEDED,
        )
    store = definitions(session)
    replaces = store.exists(name)
    if replaces and not args["overwrite"]:
        raise MCPToolException(
            f"a pipeline named {name!r} is already stored; pass overwrite=true to replace it",
            ALREADY_EXISTS,
        )
    if replaces:
        policy.require_overwrite(PIPELINE_CREATE)
    if not args["dry_run"]:
        store.save(name, data, overwrite=replaces)
    return {
        "name": name,
        "location": store.location,
        "persistent": store.persistent,
        "tasks": list(document["tasks"]),
        "actions": sorted({spec["action"][0] for spec in document["tasks"].values()}),
        "overwrites": replaces,
        "dry_run": args["dry_run"],
        "stored": not args["dry_run"],
    }


def pipeline_run(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Run a stored definition; ``dry_run`` plans it, ``background`` returns at once."""
    policy = session.policy
    policy.require_write(PIPELINE_RUN)
    name = _checked_name(args["name"])
    params = args.get("params") or {}
    document = definitions(session).load(name, policy.max_write_bytes)
    _valid_document(document, name)
    _require_allowed(session, document, params)
    pipeline = Pipeline.from_dict(document, registry=pipeline_registry(session))
    if args["dry_run"]:
        run = pipeline.run(params, dry_run=True)
    elif args["background"]:
        run = pipeline.start(params)
    else:
        run = pipeline.run(params)
    return {
        "name": name,
        "run_id": run.run_id,
        "status": run.status.value,
        "dry_run": args["dry_run"],
        "background": bool(args["background"]) and not args["dry_run"],
        "ok": run.status in (RunStatus.SUCCEEDED, RunStatus.RUNNING),
        "run": run_view(session, run),
    }


def pipeline_status(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Report one recorded run by its ID, or the latest runs of one pipeline or of all."""
    store = default_run_store()
    run_id = args.get("run_id")
    if run_id is None:
        limit = session.policy.clamp_results(args.get("limit", _DEFAULT_HISTORY))
        runs = store.list_runs(args.get("name"), limit)
    else:
        found = store.get_run(run_id)
        if found is None:
            raise MCPToolException(
                f"pipeline_status: no run {run_id[:64]!r} is recorded", NOT_FOUND
            )
        runs = [found]
    return {"runs": [run_view(session, run) for run in runs], "count": len(runs)}


_NAME_ARGUMENT = text(f"The name the definition is stored under: {_NAME_RULE}.", minLength=1)
_DEFINITION_HELP = (
    'A pipeline definition, schema_version 1: {"schema_version": 1, "tasks": {"<task id>": '
    '{"action": ["FA_storage_copy", {"source": "s3://in/${params.date}.csv", "target": '
    '"sftp://host/in/${params.date}.csv"}], "depends_on": ["<task id>"], "retry": '
    '{"max_attempts": 3, "backoff": 2}, "timeout": 300, "when": "on_success"}}}. '
    "Optional top-level keys: description, max_workers, params (defaults). An action is "
    "[name], [name, {arguments}] or [name, [arguments]]; ${params.<name>} and "
    "${tasks.<id>.result} are filled in when the task runs. Only the actions this server "
    "allows may be named, and the storage actions stay inside the allowed locations."
)

TOOLS: tuple[SemanticTool, ...] = (
    SemanticTool(
        PIPELINE_CREATE,
        "Validate a pipeline definition and store it under a name, where pipeline_run "
        "finds it. Nothing is run. Needs a server that allows writing. Every problem of "
        "the definition is reported with the path of the entry it is about.",
        arguments_schema(
            {
                "name": _NAME_ARGUMENT,
                "definition": {"type": "object", "description": _DEFINITION_HELP},
                "overwrite": flag(
                    "Replace a definition already stored under this name. The server must "
                    "allow overwriting as well."
                ),
                "dry_run": flag("When true, validate and report, but store nothing."),
            },
            required=("name", "definition"),
        ),
        pipeline_create,
        changes=True,
    ),
    SemanticTool(
        PIPELINE_RUN,
        "Run a pipeline stored with pipeline_create and return the run: its run_id, its "
        "status and every task with its result or error. With dry_run=true nothing is "
        "executed and the tasks come back 'planned', in order. Needs a server that allows "
        "writing. The run_id is also the correlation ID of everything the run does.",
        arguments_schema(
            {
                "name": _NAME_ARGUMENT,
                "params": {
                    "type": "object",
                    "description": "Parameters of this run; they fill ${params.<name>} and "
                    "override the definition's defaults. Do not put secrets here: they are "
                    "recorded with the run.",
                },
                "dry_run": flag(DRY_RUN_HELP),
                "background": flag(
                    "Return at once with status 'running' and poll pipeline_status with the "
                    "run_id. Use it for a run that takes long."
                ),
            },
            required=("name",),
        ),
        pipeline_run,
        changes=True,
    ),
    SemanticTool(
        PIPELINE_STATUS,
        "Report pipeline runs: one run by its run_id, or the latest recorded runs of one "
        "pipeline (name) or of all. Each run has its status and the state of every task.",
        arguments_schema(
            {
                "run_id": text("The run to report, as pipeline_run returned it.", minLength=1),
                "name": text("Without run_id: only the runs of this pipeline.", minLength=1),
                "limit": whole(
                    f"Without run_id: how many runs, newest first. Default {_DEFAULT_HISTORY}."
                ),
            }
        ),
        pipeline_status,
    ),
)
