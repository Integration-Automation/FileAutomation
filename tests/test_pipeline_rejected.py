"""The pipeline runtime: what is rejected before anything runs."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

from automation_file import ActionRegistry
from automation_file.events import EventBus
from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineException,
)


def test_a_duplicate_task_id_is_rejected_when_it_is_added() -> None:
    pipeline = Pipeline("duplicates")
    pipeline.task("load", lambda ctx: None)
    with pytest.raises(PipelineDefinitionException) as raised:
        pipeline.task("load", lambda ctx: None)
    assert raised.value.problems == ("tasks.load: duplicate task ID",)
    assert [task.task_id for task in pipeline.tasks] == ["load"]


@pytest.mark.parametrize(
    "build,problem",
    [
        (
            lambda p: p.task("b", lambda ctx: None, depends_on=["missing"]),
            "tasks.b.depends_on[0]: unknown task 'missing'",
        ),
        (
            lambda p: p.task("b", lambda ctx: None, depends_on=["b"]),
            "tasks.b.depends_on[0]: a task cannot depend on itself",
        ),
        (
            lambda p: p.task("b", lambda ctx: None, depends_on=["a", "a"]),
            "tasks.b.depends_on[1]: 'a' is listed twice",
        ),
        (
            lambda p: (
                p.task("b", lambda ctx: None, depends_on=["c"]),
                p.task("c", lambda ctx: None, depends_on=["b"]),
            ),
            "tasks: dependency cycle: b -> c -> b",
        ),
        (
            lambda p: p.task("b", ["T_echo", {"x": "${tasks.a.result}"}]),
            "tasks.b.action[1].x: ${tasks.a.result}: 'a' is not an upstream task (see depends_on)",
        ),
        (
            lambda p: p.task("b", ["T_echo", ["see ${tasks.a.result}"]], depends_on=["a"]),
            "tasks.b.action[1][0]: ${tasks.a.result} must be the whole string",
        ),
        (
            lambda p: p.task("b", ["T_echo", {"x": "${params.}"}]),
            "tasks.b.action[1].x: malformed placeholder ${params.}"
            " (use ${params.<name>} or ${tasks.<id>.result})",
        ),
        (
            lambda p: p.task("b", ["T_echo", {"x": "${tasks.a}"}], depends_on=["a"]),
            "tasks.b.action[1].x: malformed placeholder ${tasks.a}"
            " (use ${params.<name>} or ${tasks.<id>.result})",
        ),
        (
            lambda p: p.task("b", ["T_echo", {"x": "${params.absent}"}]),
            "tasks.b.action[1].x: unknown parameter 'absent'",
        ),
        (
            lambda p: p.task("b", lambda ctx: None, idempotency_key="b-${params.absent}"),
            "tasks.b.idempotency_key: unknown parameter 'absent'",
        ),
    ],
)
def test_a_definition_problem_stops_the_run_before_any_task(
    build: Callable[[Pipeline], object], problem: str
) -> None:
    store, bus, registry = MemoryRunStore(), EventBus(), ActionRegistry()
    registry.register("T_echo", lambda *args, **kwargs: {"args": list(args), "kwargs": kwargs})
    ran: list[str] = []
    pipeline = Pipeline("rejected", registry=registry)
    pipeline.task("a", lambda ctx: ran.append("a"))
    build(pipeline)
    for launch in (pipeline.run, pipeline.start):
        with pytest.raises(PipelineDefinitionException) as raised:
            launch(store=store, bus=bus)
        assert problem in raised.value.problems
        assert problem in str(raised.value)
    assert ran == []
    assert store.list_runs() == []
    assert bus.recent() == []


def test_every_graph_problem_is_reported_at_once() -> None:
    pipeline = Pipeline("several")
    pipeline.task("a", lambda ctx: None, depends_on=["nowhere"])
    pipeline.task("b", lambda ctx: None, depends_on=["b"])
    assert pipeline.problems() == [
        "tasks.a.depends_on[0]: unknown task 'nowhere'",
        "tasks.b.depends_on[0]: a task cannot depend on itself",
    ]
    with pytest.raises(PipelineDefinitionException) as raised:
        pipeline.validate()
    assert len(raised.value.problems) == 2


def test_an_empty_pipeline_does_not_run() -> None:
    with pytest.raises(PipelineDefinitionException, match="at least one task"):
        Pipeline("empty").run()


@pytest.mark.parametrize(
    "arguments,problem",
    [
        (("bad id", lambda ctx: None), "tasks.bad id: invalid task ID"),
        (("a.b", lambda ctx: None), "tasks.a.b: invalid task ID"),
        (("", lambda ctx: None), "tasks.: invalid task ID"),
        (("t", "FA_storage_schemes"), "tasks.t.action: expected [name]"),
        (("t", []), "tasks.t.action: expected [name]"),
        (("t", [3]), "tasks.t.action[0]: expected an action name, got int"),
        (("t", ["FA_x", "text"]), "tasks.t.action[1]: expected a mapping or a list"),
        (("t", ["FA_x", {}, {}]), "tasks.t.action: expected a name and at most one argument set"),
        (("t", ["FA_x", {1: "x"}]), "tasks.t.action[1]: argument name 1 is not a string"),
    ],
)
def test_a_malformed_task_is_rejected_when_it_is_added(
    arguments: tuple[Any, Any], problem: str
) -> None:
    with pytest.raises(PipelineDefinitionException, match=re.escape(problem)):
        Pipeline("malformed").task(*arguments)


@pytest.mark.parametrize(
    "options,problem",
    [
        ({"timeout": 0}, "tasks.t.timeout: expected a number of seconds > 0, got 0"),
        ({"timeout": -1.5}, "tasks.t.timeout: expected a number of seconds > 0, got -1.5"),
        ({"timeout": True}, "tasks.t.timeout: expected a number of seconds > 0, got True"),
        ({"when": "sometimes"}, "tasks.t.when: expected one of on_success, on_failure, always"),
        ({"depends_on": [3]}, "tasks.t.depends_on[0]: expected a task ID, got int"),
        ({"idempotency_key": ""}, "tasks.t.idempotency_key: expected a non-empty string"),
        (
            {"idempotency_key": "k-${tasks.a.result}"},
            "tasks.t.idempotency_key: ${tasks.a.result}: only ${params.<name>} can be used here",
        ),
    ],
)
def test_a_malformed_option_is_rejected_when_the_task_is_added(
    options: dict[str, Any], problem: str
) -> None:
    with pytest.raises(PipelineDefinitionException) as raised:
        Pipeline("malformed").task("t", lambda ctx: None, **options)
    assert any(found.startswith(problem) for found in raised.value.problems)


@pytest.mark.parametrize(
    "options",
    [
        {"name": ""},
        {"name": "  "},
        {"max_workers": 0},
        {"max_workers": True},
        {"params": {"a b": 1}},
    ],
)
def test_a_malformed_pipeline_is_rejected(options: dict[str, Any]) -> None:
    arguments = {"name": "fine", **options}
    with pytest.raises(PipelineDefinitionException):
        Pipeline(**arguments)


def test_depends_on_takes_one_id_as_a_string() -> None:
    pipeline = Pipeline("single")
    pipeline.task("first", lambda ctx: None)
    assert pipeline.task("second", lambda ctx: None, depends_on="first").depends_on == ("first",)


def test_the_exceptions_belong_to_the_project_hierarchy() -> None:
    from automation_file.exceptions import FileAutomationException

    assert issubclass(PipelineException, FileAutomationException)
    assert issubclass(PipelineDefinitionException, PipelineException)
    assert PipelineDefinitionException("one problem").problems == ("one problem",)
