"""Pipeline definitions: validation with paths, the schema, round trips, YAML and JSON files."""

# pylint: disable=line-too-long  # an expected value is kept on one line
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from automation_file import ActionRegistry, exceptions
from automation_file.events import EventBus
from automation_file.exceptions import FileAutomationException, StorageTransientException
from automation_file.pipeline import (
    DEFAULT_RETRY_ON,
    PIPELINE_SCHEMA,
    RETRYABLE_EXCEPTIONS,
    SCHEMA_VERSION,
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineException,
    RetryPolicy,
    RunStatus,
    Schedule,
    load_definition,
    validate_definition,
    worker,
)
from automation_file.pipeline.substitution import render, render_key

NAME_RULE = "expected a non-empty string without whitespace, '.', '$', '{' or '}'"
SYNTAX = "(use ${params.<name>} or ${tasks.<id>.result})"

DOCUMENT: dict[str, Any] = {
    "schema_version": 1,
    "name": "daily-report",
    "max_workers": 4,
    "schedule": {"cron": "0 2 * * *", "timezone": "Asia/Taipei"},
    "params": {"date": "2026-10-08"},
    "tasks": {
        "download": {
            "action": [
                "FA_storage_copy",
                {"source": "s3://input/report.csv", "target": "local:///tmp/report.csv"},
            ]
        },
        "verify": {
            "action": [
                "FA_storage_verify",
                {"uri": "local:///tmp/report.csv", "expected": "sha256:abc"},
            ],
            "depends_on": ["download"],
            "retry": {
                "max_attempts": 3,
                "backoff": 2,
                "backoff_cap": 30,
                "on": ["StorageTransientException"],
            },
            "timeout": 120,
            "when": "on_success",
            "idempotency_key": "verify-${params.date}",
        },
    },
}

YAML_TEXT = """\
schema_version: 1
name: daily-report
max_workers: 4
schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
params: {date: "2026-10-08"}
tasks:
  download:
    action: ["FA_storage_copy", {"source": "s3://input/report.csv", "target": "local:///tmp/report.csv"}]
  verify:
    action: ["FA_storage_verify", {"uri": "local:///tmp/report.csv", "expected": "sha256:abc"}]
    depends_on: [download]
    retry: {max_attempts: 3, backoff: 2, backoff_cap: 30, on: [StorageTransientException]}
    timeout: 120
    when: on_success
    idempotency_key: "verify-${params.date}"
"""

_DELETE = object()


def changed(*path: Any, to: Any = _DELETE) -> dict[str, Any]:
    """Return the example document with the entry at ``path`` replaced (or removed)."""
    document = copy.deepcopy(DOCUMENT)
    node: Any = document
    for key in path[:-1]:
        node = node[key]
    if to is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = to
    return document


# ---------------------------------------------------------------------- validation


def test_the_example_definition_is_valid() -> None:
    assert validate_definition(DOCUMENT) == []
    assert validate_definition(copy.deepcopy(DOCUMENT)) == []


def test_a_minimal_definition_is_valid() -> None:
    assert (
        validate_definition(
            {
                "schema_version": 1,
                "name": "tiny",
                "tasks": {"only": {"action": ["FA_storage_schemes"]}},
            }
        )
        == []
    )


def test_task_ids_may_be_written_in_any_script() -> None:
    document = changed("tasks", "下載", to={"action": ["FA_storage_schemes"]})
    document["tasks"]["驗證"] = {"action": ["FA_storage_schemes"], "depends_on": ["下載"]}
    assert validate_definition(document) == []
    assert [task.task_id for task in Pipeline.from_dict(document).tasks][-2:] == ["下載", "驗證"]


@pytest.mark.parametrize(
    "document,problem",
    [
        ([], "document: expected a mapping, got list"),
        (None, "document: expected a mapping, got NoneType"),
        ("daily-report.yaml", "document: expected a mapping, got str"),
        (changed("schema_version"), "schema_version: required (supported: 1)"),
        (changed("schema_version", to=2), "schema_version: unsupported version 2 (supported: 1)"),
        (
            changed("schema_version", to="1"),
            "schema_version: unsupported version '1' (supported: 1)",
        ),
        (
            changed("schema_version", to=True),
            "schema_version: unsupported version True (supported: 1)",
        ),
    ],
)
def test_a_document_of_an_unknown_shape_or_version_is_rejected(document: Any, problem: str) -> None:
    assert validate_definition(document) == [problem]


def test_an_unknown_version_hides_every_other_finding() -> None:
    document = changed("schema_version", to=2)
    document["name"] = ""
    document["tasks"] = []
    assert validate_definition(document) == ["schema_version: unsupported version 2 (supported: 1)"]


@pytest.mark.parametrize(
    "document,problem",
    [
        (changed("name"), "name: required"),
        (changed("name", to=" "), "name: expected a non-empty string, got ' '"),
        (changed("name", to=5), "name: expected a non-empty string, got 5"),
        (changed("description", to=5), "description: expected a string, got int"),
        (changed("max_workers", to=0), "max_workers: expected an integer >= 1, got 0"),
        (changed("max_workers", to="4"), "max_workers: expected an integer >= 1, got '4'"),
        (changed("max_workers", to=True), "max_workers: expected an integer >= 1, got True"),
        (changed("max_workers", to=2.5), "max_workers: expected an integer >= 1, got 2.5"),
        (changed("owner", to="ops"), "owner: unknown key"),
        (changed("schedule", to="0 2 * * *"), "schedule: expected a mapping, got str"),
        (changed("schedule", to=None), "schedule: expected a mapping, got NoneType"),
        (changed("schedule", to={}), "schedule.cron: required"),
        (
            changed("schedule", "cron", to="every day"),
            "schedule.cron: expected 5 fields, got 2: 'every day'",
        ),
        (changed("schedule", "cron", to="61 2 * * *"), "schedule.cron: value 61 outside [0,59]"),
        (
            changed("schedule", "cron", to=5),
            "schedule.cron: expected a cron expression, got int",
        ),
        (
            changed("schedule", "timezone", to=""),
            "schedule.timezone: expected a time zone name, got ''",
        ),
        (changed("schedule", "jitter", to=1), "schedule.jitter: unknown key"),
        (changed("params", to=["date"]), "params: expected a mapping, got list"),
        (
            changed("params", to={"a b": 1, "fine": 2}),
            f"params.a b: invalid parameter name, {NAME_RULE}",
        ),
        (
            changed("params", "date", to=datetime.date(2026, 10, 8)),
            "params.date: expected a JSON value, got date (quote dates and times in YAML)",
        ),
        (changed("tasks"), "tasks: required"),
        (changed("tasks", to=[]), "tasks: expected a mapping of task ID to task, got list"),
        (changed("tasks", to={}), "tasks: at least one task is required"),
        (
            changed("tasks", "bad id", to={"action": ["FA_x"]}),
            f"tasks.bad id: invalid task ID, {NAME_RULE}",
        ),
        (
            changed("tasks", "a.b", to={"action": ["FA_x"]}),
            f"tasks.a.b: invalid task ID, {NAME_RULE}",
        ),
        (changed("tasks", 7, to={"action": ["FA_x"]}), f"tasks.7: invalid task ID, {NAME_RULE}"),
        (changed("tasks", "verify", to="FA_x"), "tasks.verify: expected a mapping, got str"),
        (changed("tasks", "verify", "priority", to=1), "tasks.verify.priority: unknown key"),
    ],
)
def test_a_problem_in_the_header_or_the_task_list_is_reported_with_its_path(
    document: Any, problem: str
) -> None:
    assert validate_definition(document) == [problem]


@pytest.mark.parametrize(
    "path,value,problem",
    [
        (
            ("action",),
            "FA_x",
            "tasks.verify.action: expected [name], [name, {kwargs}] or [name, [args]], got str",
        ),
        (
            ("action",),
            [],
            "tasks.verify.action: expected [name], [name, {kwargs}] or [name, [args]],"
            " got an empty list",
        ),
        (("action",), [5], "tasks.verify.action[0]: expected an action name, got int"),
        (("action",), [""], "tasks.verify.action[0]: expected an action name, got str"),
        (
            ("action",),
            ["FA_x", "y"],
            "tasks.verify.action[1]: expected a mapping or a list of arguments, got str",
        ),
        (
            ("action",),
            ["FA_x", {}, {}],
            "tasks.verify.action: expected a name and at most one argument set, got 3",
        ),
        (
            ("action",),
            ["FA_x", {3: "x"}],
            "tasks.verify.action[1]: argument name 3 is not a string",
        ),
        (
            ("action",),
            ["FA_x", {"since": datetime.date(2026, 1, 1)}],
            "tasks.verify.action[1].since: expected a JSON value, got date"
            " (quote dates and times in YAML)",
        ),
        (
            ("action",),
            ["FA_x", {"a": "${tasks.nope.result}"}],
            "tasks.verify.action[1].a: ${tasks.nope.result}:"
            " 'nope' is not an upstream task (see depends_on)",
        ),
        (
            ("action",),
            ["FA_x", {"a": "see ${tasks.download.result}"}],
            "tasks.verify.action[1].a: ${tasks.download.result} must be the whole string",
        ),
        (
            ("action",),
            ["FA_x", [{"deep": ["${params.}"]}]],
            f"tasks.verify.action[1][0].deep[0]: malformed placeholder ${{params.}} {SYNTAX}",
        ),
        (
            ("action",),
            ["FA_x", {"a": "${tasks.download}"}],
            f"tasks.verify.action[1].a: malformed placeholder ${{tasks.download}} {SYNTAX}",
        ),
        (
            ("depends_on",),
            "download",
            "tasks.verify.depends_on: expected a list of task IDs, got str",
        ),
        (("depends_on",), ["x"], "tasks.verify.depends_on[0]: unknown task 'x'"),
        (
            ("depends_on",),
            ["download", 3],
            "tasks.verify.depends_on[1]: expected a task ID, got int",
        ),
        (("depends_on",), ["verify"], "tasks.verify.depends_on[0]: a task cannot depend on itself"),
        (
            ("depends_on",),
            ["download", "download"],
            "tasks.verify.depends_on[1]: 'download' is listed twice",
        ),
        (("retry",), 3, "tasks.verify.retry: expected a mapping, got int"),
        (
            ("retry", "max_attempts"),
            0,
            "tasks.verify.retry.max_attempts: expected an integer >= 1, got 0",
        ),
        (
            ("retry", "max_attempts"),
            1.5,
            "tasks.verify.retry.max_attempts: expected an integer >= 1, got 1.5",
        ),
        (
            ("retry", "backoff"),
            -1,
            "tasks.verify.retry.backoff: expected a number of seconds >= 0, got -1",
        ),
        (
            ("retry", "backoff_cap"),
            "30",
            "tasks.verify.retry.backoff_cap: expected a number of seconds >= 0, got '30'",
        ),
        (
            ("retry", "on"),
            "StorageTransientException",
            "tasks.verify.retry.on: expected a list of exception names, got str",
        ),
        (("retry", "on"), ["Exception"], "tasks.verify.retry.on[0]: unknown exception 'Exception'"),
        (
            ("retry", "on"),
            ["OSError", "ValueError"],
            "tasks.verify.retry.on[1]: unknown exception 'ValueError'",
        ),
        (("retry", "on"), [3], "tasks.verify.retry.on[0]: unknown exception 3"),
        (("retry", "jitter"), 1, "tasks.verify.retry.jitter: unknown key"),
        (
            ("retry",),
            {"max_attempts": 2, True: ["OSError"]},
            'tasks.verify.retry.True: unknown key (YAML reads a bare on as true; write "on")',
        ),
        (("timeout",), 0, "tasks.verify.timeout: expected a number of seconds > 0, got 0"),
        (("timeout",), "120", "tasks.verify.timeout: expected a number of seconds > 0, got '120'"),
        (
            ("timeout",),
            float("inf"),
            "tasks.verify.timeout: expected a number of seconds > 0, got inf",
        ),
        (
            ("when",),
            "sometimes",
            "tasks.verify.when: expected one of on_success, on_failure, always, got 'sometimes'",
        ),
        (
            ("when",),
            None,
            "tasks.verify.when: expected one of on_success, on_failure, always, got None",
        ),
        (
            ("idempotency_key",),
            "",
            "tasks.verify.idempotency_key: expected a non-empty string, got ''",
        ),
        (
            ("idempotency_key",),
            5,
            "tasks.verify.idempotency_key: expected a non-empty string, got 5",
        ),
        (
            ("idempotency_key",),
            "k-${tasks.download.result}",
            "tasks.verify.idempotency_key: ${tasks.download.result}:"
            " only ${params.<name>} can be used here",
        ),
        (
            ("idempotency_key",),
            "k-${params.a b}",
            f"tasks.verify.idempotency_key: malformed placeholder ${{params.a b}} {SYNTAX}",
        ),
    ],
)
def test_a_problem_in_a_task_is_reported_with_its_path(
    path: tuple[str, ...], value: Any, problem: str
) -> None:
    assert validate_definition(changed("tasks", "verify", *path, to=value)) == [problem]


def test_a_task_without_an_action_is_reported() -> None:
    assert validate_definition(changed("tasks", "verify", "action")) == [
        "tasks.verify.action: required"
    ]


def test_a_cycle_is_reported_with_its_tasks() -> None:
    document = changed("tasks", "download", "depends_on", to=["verify"])
    assert validate_definition(document) == [
        "tasks: dependency cycle: download -> verify -> download"
    ]


def test_every_problem_is_reported_at_once() -> None:
    document = changed("name", to="")
    document["max_workers"] = 0
    document["tasks"]["download"]["action"] = ["FA_x", {"a": "${params.}"}]
    document["tasks"]["verify"]["depends_on"] = ["missing"]
    document["tasks"]["verify"]["retry"] = {"max_attempts": 0, "on": ["Nope"]}
    document["tasks"]["verify"]["timeout"] = -5
    assert validate_definition(document) == [
        "name: expected a non-empty string, got ''",
        "max_workers: expected an integer >= 1, got 0",
        "tasks.verify.retry.max_attempts: expected an integer >= 1, got 0",
        "tasks.verify.retry.on[0]: unknown exception 'Nope'",
        "tasks.verify.timeout: expected a number of seconds > 0, got -5",
        "tasks.verify.depends_on[0]: unknown task 'missing'",
        f"tasks.download.action[1].a: malformed placeholder ${{params.}} {SYNTAX}",
    ]


# ---------------------------------------------------------------------- the schema


def test_the_schema_is_a_json_schema_document_for_version_1() -> None:
    assert SCHEMA_VERSION == 1
    assert json.loads(json.dumps(PIPELINE_SCHEMA)) == PIPELINE_SCHEMA
    assert PIPELINE_SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert PIPELINE_SCHEMA["type"] == "object"
    assert PIPELINE_SCHEMA["required"] == ["schema_version", "name", "tasks"]
    assert PIPELINE_SCHEMA["properties"]["schema_version"] == {"const": 1}
    assert PIPELINE_SCHEMA["additionalProperties"] is False


def test_the_schema_names_the_keys_the_validator_accepts() -> None:
    definitions = PIPELINE_SCHEMA["$defs"]
    assert set(PIPELINE_SCHEMA["properties"]) == set(DOCUMENT) | {"description"}
    assert set(definitions["task"]["properties"]) == set(DOCUMENT["tasks"]["verify"])
    assert definitions["task"]["required"] == ["action"]
    assert set(definitions["retry"]["properties"]) == set(DOCUMENT["tasks"]["verify"]["retry"])
    assert set(definitions["schedule"]["properties"]) == set(DOCUMENT["schedule"])
    assert definitions["task"]["properties"]["when"]["enum"] == [
        "on_success",
        "on_failure",
        "always",
    ]
    assert definitions["retry"]["properties"]["on"]["items"]["enum"] == list(RETRYABLE_EXCEPTIONS)
    assert definitions["action"]["maxItems"] == 2
    for part in ("task", "retry", "schedule"):
        assert definitions[part]["additionalProperties"] is False
    every_reference = json.dumps(PIPELINE_SCHEMA).count('"$ref"')
    assert every_reference == 4
    for name in ("schedule", "action", "retry", "task"):
        assert f'"#/$defs/{name}"' in json.dumps(PIPELINE_SCHEMA)


def test_the_exceptions_a_definition_may_name() -> None:
    project = {
        name
        for name, member in vars(exceptions).items()
        if isinstance(member, type) and issubclass(member, FileAutomationException)
    }
    assert set(RETRYABLE_EXCEPTIONS) == project | {"TimeoutError", "ConnectionError", "OSError"}
    assert RETRYABLE_EXCEPTIONS["StorageTransientException"] is StorageTransientException
    assert RETRYABLE_EXCEPTIONS["OSError"] is OSError
    assert "Exception" not in RETRYABLE_EXCEPTIONS
    assert "ValueError" not in RETRYABLE_EXCEPTIONS
    assert list(RETRYABLE_EXCEPTIONS) == sorted(RETRYABLE_EXCEPTIONS)
    with pytest.raises(TypeError):
        RETRYABLE_EXCEPTIONS["Exception"] = Exception  # type: ignore[index]


# ---------------------------------------------------------------------- from_dict and to_dict


def test_from_dict_builds_the_pipeline() -> None:
    pipeline = Pipeline.from_dict(DOCUMENT)
    assert pipeline.name == "daily-report"
    assert pipeline.description == ""
    assert pipeline.max_workers == 4
    assert pipeline.schedule == Schedule(cron="0 2 * * *", timezone="Asia/Taipei")
    assert pipeline.params == {"date": "2026-10-08"}
    download, verify = pipeline.tasks
    assert download.task_id == "download"
    assert download.action_name == "FA_storage_copy"
    assert download.depends_on == ()
    assert download.retry == RetryPolicy()
    assert download.timeout is None
    assert download.when == "on_success"
    assert download.idempotency_key is None
    assert verify.depends_on == ("download",)
    assert verify.retry == RetryPolicy(
        max_attempts=3, backoff_base=2, backoff_cap=30, retry_on=(StorageTransientException,)
    )
    assert verify.timeout == 120
    assert verify.idempotency_key == "verify-${params.date}"
    assert pipeline.problems() == []


def test_from_dict_fills_in_the_defaults() -> None:
    pipeline = Pipeline.from_dict(
        {
            "schema_version": 1,
            "name": "tiny",
            "description": "one task",
            "tasks": {"only": {"action": ["FA_x"], "retry": {"max_attempts": 2}}},
        }
    )
    assert pipeline.description == "one task"
    assert pipeline.max_workers == 4
    assert pipeline.schedule is None
    assert pipeline.params == {}
    assert pipeline.tasks[0].retry == RetryPolicy(max_attempts=2)
    assert pipeline.tasks[0].retry.retry_on is DEFAULT_RETRY_ON


def test_an_empty_retry_list_never_retries() -> None:
    document = changed("tasks", "verify", "retry", "on", to=[])
    assert validate_definition(document) == []
    policy = Pipeline.from_dict(document).tasks[1].retry
    assert policy.retry_on == ()
    assert policy.retries(StorageTransientException("throttled")) is False


def test_from_dict_raises_with_every_problem() -> None:
    document = changed("tasks", "verify", "depends_on", to=["x"])
    document["max_workers"] = 0
    with pytest.raises(PipelineDefinitionException) as raised:
        Pipeline.from_dict(document)
    assert raised.value.problems == (
        "max_workers: expected an integer >= 1, got 0",
        "tasks.verify.depends_on[0]: unknown task 'x'",
    )
    assert str(raised.value) == "; ".join(raised.value.problems)
    assert isinstance(raised.value, PipelineException)


def test_a_definition_round_trip() -> None:
    canonical = changed("tasks", "verify", "when")  # on_success is the default and is left out
    written = Pipeline.from_dict(DOCUMENT).to_dict()
    assert written == canonical
    assert list(written) == ["schema_version", "name", "max_workers", "schedule", "params", "tasks"]
    assert validate_definition(written) == []
    assert Pipeline.from_dict(written).to_dict() == written
    assert json.loads(json.dumps(written)) == written


def test_to_dict_writes_what_differs_from_the_defaults() -> None:
    pipeline = Pipeline("built", description="made in Python", max_workers=2)
    pipeline.task("first", ["FA_a"])
    pipeline.task(
        "second",
        ["FA_b", ["${tasks.first.result}"]],
        depends_on="first",
        retry=RetryPolicy(max_attempts=2),
        when="always",
    )
    pipeline.task(
        "third",
        ["FA_c", {"x": 1}],
        depends_on=["first", "second"],
        retry=RetryPolicy(max_attempts=4, backoff_base=0.5, retry_on=(OSError, TimeoutError)),
        timeout=1.5,
        when="on_failure",
        idempotency_key="third",
    )
    assert pipeline.to_dict() == {
        "schema_version": 1,
        "name": "built",
        "description": "made in Python",
        "max_workers": 2,
        "tasks": {
            "first": {"action": ["FA_a"]},
            "second": {
                "action": ["FA_b", ["${tasks.first.result}"]],
                "depends_on": ["first"],
                "retry": {"max_attempts": 2},
                "when": "always",
            },
            "third": {
                "action": ["FA_c", {"x": 1}],
                "depends_on": ["first", "second"],
                "retry": {"max_attempts": 4, "backoff": 0.5, "on": ["OSError", "TimeoutError"]},
                "timeout": 1.5,
                "when": "on_failure",
                "idempotency_key": "third",
            },
        },
    }
    assert validate_definition(pipeline.to_dict()) == []
    assert Pipeline.from_dict(pipeline.to_dict()).to_dict() == pipeline.to_dict()


def test_to_dict_hands_out_a_copy() -> None:
    pipeline = Pipeline.from_dict(DOCUMENT)
    written = pipeline.to_dict()
    written["tasks"]["download"]["action"][1]["source"] = "changed"
    written["params"]["date"] = "changed"
    assert pipeline.to_dict() == changed("tasks", "verify", "when")


@pytest.mark.parametrize(
    "options,problem",
    [
        (
            {"work": lambda ctx: None},
            "tasks.t: a Python callable cannot be written to a definition",
        ),
        (
            {"when": lambda ctx: True},
            "tasks.t.when: a Python callable cannot be written to a definition",
        ),
        (
            {"retry": RetryPolicy(max_attempts=2, retry_on=(KeyError,))},
            "tasks.t.retry.on: KeyError cannot be named in a definition",
        ),
    ],
)
def test_to_dict_refuses_what_a_document_cannot_hold(options: dict[str, Any], problem: str) -> None:
    pipeline = Pipeline("python-only")
    work = options.pop("work", ["FA_a"])
    pipeline.task("t", work, **options)
    with pytest.raises(PipelineDefinitionException) as raised:
        pipeline.to_dict()
    assert raised.value.problems == (problem,)


def test_a_schedule_without_a_time_zone() -> None:
    document = changed("schedule", to={"cron": "*/5 * * * *"})
    pipeline = Pipeline.from_dict(document)
    assert pipeline.schedule == Schedule("*/5 * * * *")
    assert pipeline.schedule.timezone is None
    assert pipeline.to_dict()["schedule"] == {"cron": "*/5 * * * *"}


# ---------------------------------------------------------------------- files


def test_a_yaml_and_a_json_file_give_the_same_pipeline(tmp_path: Path) -> None:
    yaml_file = tmp_path / "daily-report.yaml"
    yml_file = tmp_path / "daily-report.YML"
    json_file = tmp_path / "daily-report.json"
    yaml_file.write_text(YAML_TEXT, encoding="utf-8")
    yml_file.write_text(YAML_TEXT, encoding="utf-8")
    json_file.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    assert load_definition(yaml_file) == DOCUMENT
    assert load_definition(str(yml_file)) == DOCUMENT
    assert load_definition(json_file) == DOCUMENT
    expected = Pipeline.from_dict(DOCUMENT).to_dict()
    for path in (yaml_file, yml_file, json_file):
        assert Pipeline.from_file(path).to_dict() == expected
    assert Pipeline.from_file(str(yaml_file)).schedule == Schedule("0 2 * * *", "Asia/Taipei")


def test_a_bare_on_in_a_yaml_file_is_the_retry_key(tmp_path: Path) -> None:
    import yaml

    assert (
        True in yaml.safe_load(YAML_TEXT)["tasks"]["verify"]["retry"]
    )  # what YAML 1.1 makes of it
    for spelling in ("on", '"on"', "'on'"):
        path = tmp_path / "retry.yaml"
        path.write_text(
            YAML_TEXT.replace("on: [Storage", f"{spelling}: [Storage"), encoding="utf-8"
        )
        retry = load_definition(path)["tasks"]["verify"]["retry"]
        assert list(retry) == ["max_attempts", "backoff", "backoff_cap", "on"]
        assert Pipeline.from_file(path).tasks[1].retry.retry_on == (StorageTransientException,)
    shared = tmp_path / "shared.yaml"
    shared.write_text(
        "schema_version: 1\nname: shared\ntasks:\n"
        "  a: &task {action: [FA_a], retry: {max_attempts: 2, on: [OSError]}}\n"
        "  b: *task\n",
        encoding="utf-8",
    )
    assert [task.retry.retry_on for task in Pipeline.from_file(shared).tasks] == [(OSError,)] * 2


def test_a_file_may_use_yaml_anchors_and_any_script(tmp_path: Path) -> None:
    path = tmp_path / "anchors.yaml"
    path.write_text(
        "schema_version: 1\n"
        "name: 每日報表\n"
        "tasks:\n"
        "  下載: &base {action: [FA_storage_schemes], timeout: 5}\n"
        "  備份: *base\n",
        encoding="utf-8",
    )
    pipeline = Pipeline.from_file(path)
    assert pipeline.name == "每日報表"
    assert [(task.task_id, task.timeout) for task in pipeline.tasks] == [("下載", 5), ("備份", 5)]


@pytest.mark.parametrize(
    "name,content,message",
    [
        ("pipeline.txt", YAML_TEXT, "expected a .yaml, .yml or .json file"),
        ("pipeline", YAML_TEXT, "expected a .yaml, .yml or .json file"),
        ("broken.yaml", "name: [unclosed\n", "invalid YAML: "),
        ("two.yaml", "a: 1\n---\nb: 2\n", "invalid YAML: "),
        ("broken.json", '{"name": }', "invalid JSON: Expecting value at line 1, column 10"),
        ("binary.yaml", b"\xff\xfe\x00name", "cannot read the definition"),
        (
            "twice.yaml",
            "schema_version: 1\nname: x\ntasks:\n  load: {action: [FA_a]}\n  load: {action: [FA_b]}\n",
            "duplicate key 'load' at line 5",
        ),
        (
            "twice.json",
            '{"schema_version": 1, "tasks": {"load": {}, "load": {}}}',
            "duplicate key 'load'",
        ),
        ("endless.yaml", "a: &a [*a]\n", "the definition is too large or refers to itself"),
        (
            "bomb.yaml",
            "a: &a [x, x, x, x, x, x, x, x, x, x]\n"
            + "".join(
                f"{name}: &{name} [{', '.join([f'*{previous}'] * 10)}]\n"
                for previous, name in zip("abcde", "bcdef", strict=True)
            ),
            "the definition is too large or refers to itself",
        ),
    ],
)
def test_a_file_that_cannot_be_loaded_says_why(
    tmp_path: Path, name: str, content: str | bytes, message: str
) -> None:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(PipelineDefinitionException) as raised:
        load_definition(path)
    assert str(raised.value).startswith(f"{path}: {message}")
    with pytest.raises(PipelineDefinitionException):
        Pipeline.from_file(path)


def test_a_file_nested_too_deeply_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    def too_deep(*_args: object, **_kwargs: object) -> None:
        raise RecursionError("maximum recursion depth exceeded")

    json_file = tmp_path / "deep.json"
    json_file.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    yaml_file = tmp_path / "deep.yaml"
    yaml_file.write_text("[[[[]]]]", encoding="utf-8")
    monkeypatch.setattr(yaml, "compose", too_deep)  # what PyYAML's composer does past the limit
    for path in (json_file, yaml_file):
        with pytest.raises(PipelineDefinitionException) as raised:
            load_definition(path)
        assert str(raised.value) == f"{path}: the definition is nested too deeply"


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(PipelineDefinitionException, match="cannot read the definition"):
        load_definition(tmp_path / "absent.yaml")


def test_an_invalid_yaml_file_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("schema_version: 1\nname: x\ntasks:\n  a: {action: [FA_a\n", encoding="utf-8")
    with pytest.raises(
        PipelineDefinitionException, match=r"invalid YAML: .* at line \d+, column \d+"
    ):
        load_definition(path)


def test_an_empty_file_is_not_a_definition(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert load_definition(path) is None
    with pytest.raises(PipelineDefinitionException, match="document: expected a mapping"):
        Pipeline.from_file(path)


def test_an_unquoted_yaml_date_is_pointed_out(tmp_path: Path) -> None:
    path = tmp_path / "dated.yaml"
    path.write_text(
        YAML_TEXT.replace('{date: "2026-10-08"}', "{date: 2026-10-08}"), encoding="utf-8"
    )
    with pytest.raises(PipelineDefinitionException) as raised:
        Pipeline.from_file(path)
    assert raised.value.problems == (
        "params.date: expected a JSON value, got date (quote dates and times in YAML)",
    )


# ---------------------------------------------------------------------- a definition at work


def test_a_definition_runs_with_its_retry_and_its_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "pause", lambda _token, _seconds: False)
    calls: list[str] = []

    def fetch(source: str) -> dict[str, str]:
        calls.append(source)
        if len(calls) < 3:
            raise StorageTransientException("throttled")
        return {"path": f"/tmp/{source.rsplit('/', 1)[-1]}"}  # nosec B108  # a path that is never opened

    registry = ActionRegistry()
    registry.register("T_fetch", fetch)
    registry.register("T_report", lambda fetched, day: f"{fetched['path']} for {day}")
    pipeline = Pipeline.from_dict(
        {
            "schema_version": 1,
            "name": "from-a-document",
            "params": {"date": "2026-01-01"},
            "tasks": {
                "fetch": {
                    "action": ["T_fetch", {"source": "s3://in/${params.date}.csv"}],
                    "retry": {"max_attempts": 3, "on": ["StorageTransientException"]},
                },
                "report": {
                    "action": ["T_report", ["${tasks.fetch.result}", "${params.date}"]],
                    "depends_on": ["fetch"],
                },
            },
        },
        registry=registry,
    )
    run = pipeline.run(params={"date": "2026-10-08"}, store=MemoryRunStore(), bus=EventBus())
    assert run.status is RunStatus.SUCCEEDED
    assert calls == ["s3://in/2026-10-08.csv"] * 3
    assert run.tasks["fetch"].attempts == 3
    assert run.tasks["report"].result == "/tmp/2026-10-08.csv for 2026-10-08"  # nosec B108  # a path that is never opened


# ---------------------------------------------------------------------- substitution


def test_render_replaces_parameters_and_results() -> None:
    params = {"date": "2026-10-08", "limit": 20, "flag": False}
    results = {"load": {"rows": 3}}
    assert render("${params.limit}", params, results) == 20
    assert render("${params.flag}", params, results) is False
    assert render("limit=${params.limit} on ${params.date}", params, results) == (
        "limit=20 on 2026-10-08"
    )
    assert render("${params.date}${params.limit}", params, results) == "2026-10-0820"
    assert render("${tasks.load.result}", params, results) is results["load"]
    assert render("${tasks.absent.result}", params, results) is None
    assert render(["${params.limit}", {"k": "${params.date}"}, 7, None], params, results) == [
        20,
        {"k": "2026-10-08"},
        7,
        None,
    ]
    assert render({"${params.date}": "key stays"}, params, results) == {
        "${params.date}": "key stays"
    }
    assert render("plain ${HOME} ${env:X} $5", params, results) == "plain ${HOME} ${env:X} $5"


def test_render_raises_for_what_it_cannot_resolve() -> None:
    with pytest.raises(PipelineException, match="unknown parameter 'absent'"):
        render("x-${params.absent}", {}, {})
    with pytest.raises(PipelineException, match="malformed placeholder"):
        render("${tasks.load}", {}, {"load": 1})


def test_render_key_is_always_text() -> None:
    assert render_key("batch-${params.number}", {"number": 5}) == "batch-5"
    assert render_key("${params.number}", {"number": 5}) == "5"
    assert render_key("fixed", {}) == "fixed"
