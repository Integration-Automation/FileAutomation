"""The Pipelines service of the application layer, on a private store, registry and bus."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from automation_file.app import (
    MASK,
    AppException,
    PipelineDraft,
    PipelineService,
    layout_path,
)
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import EventBus
from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineException,
    SQLiteRunStore,
    default_run_store,
    set_default_run_store,
)

WAIT = 10.0


class _Workshop:
    """The actions the pipelines of these tests call."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.calls: list[str] = []
        self.broken = True

    def echo(self, value: Any = None) -> Any:
        self.calls.append(f"echo:{value!r}")
        return value

    def fail(self) -> None:
        self.calls.append("fail")
        raise ValueError("it broke")

    def flaky(self) -> str:
        self.calls.append("flaky")
        if self.broken:
            raise ConnectionError("not yet")
        return "repaired"

    def hold(self) -> str:
        self.entered.set()
        self.gate.wait(WAIT)
        return "released"

    def registry(self) -> ActionRegistry:
        return ActionRegistry(
            {"T_echo": self.echo, "T_fail": self.fail, "T_flaky": self.flaky, "T_hold": self.hold}
        )


@pytest.fixture(name="workshop")
def _workshop() -> _Workshop:
    return _Workshop()


@pytest.fixture(name="bus")
def _bus() -> EventBus:
    return EventBus()


@pytest.fixture(name="service")
def _service(workshop: _Workshop, bus: EventBus) -> PipelineService:
    return PipelineService(MemoryRunStore(), registry=workshop.registry(), bus=bus)


def _draft(*tasks: tuple[str, str, Any]) -> PipelineDraft:
    """Build a chain: each ``(task ID, action, arguments)`` depends on the one before it."""
    draft = PipelineDraft("chain")
    previous: str | None = None
    for task_id, action, arguments in tasks:
        draft.add_task(action, task_id, arguments=arguments)
        if previous is not None:
            draft.connect(previous, task_id)
        previous = task_id
    return draft


def _finished(service: PipelineService, run_id: str) -> dict[str, Any]:
    assert service.wait(run_id, WAIT) is True
    return service.status(run_id)


# ---------------------------------------------------------------------- actions


def test_the_registered_actions_are_listed_and_described(service: PipelineService) -> None:
    assert service.action_names() == ["T_echo", "T_fail", "T_flaky", "T_hold"]
    info = service.describe_action("T_echo")
    assert (info.known, info.signature) == (True, "T_echo(value=None)")
    assert service.describe_action("T_missing").known is False


def test_the_shared_registry_is_the_default() -> None:
    names = PipelineService(MemoryRunStore()).action_names()
    assert "FA_storage_copy" in names
    assert names == sorted(names)


# ---------------------------------------------------------------------- validation, dry run


def test_validation_returns_every_problem_with_its_path(service: PipelineService) -> None:
    draft = _draft(("a", "T_echo", {"value": 1}), ("b", "T_missing", None))
    draft.set_timeout("a", 0)
    found = {str(problem): problem.task for problem in service.validate(draft)}
    assert found == {
        "tasks.a.timeout: expected a number of seconds > 0, got 0": "a",
        "tasks.b.action[0]: unknown action 'T_missing'": "b",
    }
    draft.set_timeout("a", None)
    draft.set_action("b", "T_echo")
    assert service.validate(draft) == []
    assert service.validate(draft.to_definition()) == []


def test_validation_takes_a_document_that_is_not_a_definition(service: PipelineService) -> None:
    assert [str(problem) for problem in service.validate({"name": "x"})] == [
        "schema_version: required (supported: 1)"
    ]
    with pytest.raises(AppException, match="PipelineDraft or a definition mapping"):
        service.validate("text")  # type: ignore[arg-type]


def test_a_dry_run_plans_without_running(service: PipelineService, workshop: _Workshop) -> None:
    draft = _draft(("a", "T_echo", {"value": "${params.word}"}), ("b", "T_echo", None))
    plan = service.dry_run(draft, {"word": "hi"})
    assert (plan["status"], plan["dry_run"], plan["active"]) == ("succeeded", True, False)
    assert [(task, state["status"], state["level"]) for task, state in plan["tasks"].items()] == [
        ("a", "planned", 0),
        ("b", "planned", 1),
    ]
    missing = service.dry_run(draft)
    assert missing["status"] == "failed"
    assert "unknown parameter 'word'" in missing["tasks"]["a"]["error"]
    assert workshop.calls == []
    assert service.history() == []


def test_a_dry_run_of_an_invalid_definition_raises_with_the_problems(
    service: PipelineService,
) -> None:
    with pytest.raises(PipelineDefinitionException) as caught:
        service.dry_run(PipelineDraft("empty"))
    assert caught.value.problems == ("tasks: at least one task is required",)


# ---------------------------------------------------------------------- runs


def test_a_run_starts_in_the_background_and_is_followed(
    service: PipelineService, workshop: _Workshop, bus: EventBus
) -> None:
    draft = _draft(("hold", "T_hold", None), ("after", "T_echo", {"value": "${params.word}"}))
    started = service.start(draft, {"word": "hi"})
    run_id = started["run_id"]
    assert started["active"] is True
    assert workshop.entered.wait(WAIT)
    live = service.status(run_id)
    assert (live["status"], live["active"]) == ("running", True)
    assert live["tasks"]["hold"]["status"] == "running"
    assert [run["run_id"] for run in service.running()] == [run_id]
    workshop.gate.set()
    done = _finished(service, run_id)
    assert (done["status"], done["active"]) == ("succeeded", False)
    assert done["tasks"]["after"]["result"] == "hi"
    assert service.running() == []
    followed = service.follow(run_id)
    assert followed["run"]["status"] == "succeeded"
    assert [event["type"] for event in followed["events"]] == [
        "pipeline.started",
        "task.started",
        "task.completed",
        "task.started",
        "task.completed",
        "pipeline.completed",
    ]
    assert {event["correlation_id"] for event in followed["events"]} == {run_id}
    assert len(bus.recent(100)) == 6


def test_a_failed_task_does_not_raise_and_shows_in_the_status(service: PipelineService) -> None:
    draft = _draft(("bad", "T_fail", None), ("after", "T_echo", None))
    done = _finished(service, service.start(draft)["run_id"])
    assert done["status"] == "failed"
    assert done["tasks"]["bad"]["error"] == "ValueError: it broke"
    assert (done["tasks"]["after"]["status"], done["tasks"]["after"]["reason"]) == (
        "skipped",
        "upstream_failed",
    )


def test_starting_an_invalid_definition_raises_before_anything_runs(
    service: PipelineService, workshop: _Workshop
) -> None:
    with pytest.raises(PipelineDefinitionException):
        service.start(_draft(("a", "T_echo", {"value": "${params.absent}"})))
    assert workshop.calls == []
    assert service.history() == []


def test_a_running_run_can_be_cancelled(service: PipelineService, workshop: _Workshop) -> None:
    draft = _draft(("hold", "T_hold", None), ("after", "T_echo", None))
    run_id = service.start(draft)["run_id"]
    assert workshop.entered.wait(WAIT)
    assert service.cancel(run_id) is True
    workshop.gate.set()
    done = _finished(service, run_id)
    assert done["status"] == "cancelled"
    assert done["tasks"]["after"]["status"] == "cancelled"
    assert service.cancel(run_id) is False
    assert service.cancel("no-such-run") is False
    assert service.wait("no-such-run", 0.01) is True


def test_history_is_newest_first_and_filters_by_pipeline(service: PipelineService) -> None:
    first = _draft(("a", "T_echo", None))
    second = _draft(("a", "T_echo", None))
    second.set_name("other")
    ids = [
        _finished(service, service.start(first)["run_id"])["run_id"],
        _finished(service, service.start(second)["run_id"])["run_id"],
        _finished(service, service.start(first)["run_id"])["run_id"],
    ]
    assert [run["run_id"] for run in service.history()] == list(reversed(ids))
    assert [run["run_id"] for run in service.history("chain")] == [ids[2], ids[0]]
    assert [run["run_id"] for run in service.history(limit=1)] == [ids[2]]
    assert all(run["active"] is False for run in service.history())


def test_the_status_of_an_unknown_run_raises(service: PipelineService) -> None:
    with pytest.raises(PipelineException, match="unknown run 'nope'"):
        service.status("nope")


def test_a_run_recorded_by_someone_else_is_read_from_the_store(bus: EventBus) -> None:
    store = MemoryRunStore()
    pipeline = Pipeline("external")
    pipeline.task("only", lambda _context: "done")
    run = pipeline.run(store=store, bus=bus)
    service = PipelineService(store, bus=bus)
    status = service.status(run.run_id)
    assert (status["status"], status["active"]) == ("succeeded", False)
    assert [entry["run_id"] for entry in service.history("external")] == [run.run_id]
    assert service.running() == []


def test_a_run_the_store_says_is_running_counts_as_running(bus: EventBus) -> None:
    store = MemoryRunStore()
    pipeline = Pipeline("interrupted")
    pipeline.task("only", lambda _context: None)
    run = pipeline.run(dry_run=True)
    run.status = type(run.status)("running")
    store.save_run(run)
    listed = PipelineService(store, bus=bus).running()
    assert [(entry["run_id"], entry["active"]) for entry in listed] == [(run.run_id, False)]


def test_secrets_in_the_parameters_are_masked_in_every_view(service: PipelineService) -> None:
    draft = _draft(("a", "T_echo", {"value": "${params.word}"}))
    params = {"word": "hi", "password": "hunter2"}
    started = service.start(draft, params)
    assert started["params"] == {"word": "hi", "password": MASK}
    done = _finished(service, started["run_id"])
    assert done["params"] == {"word": "hi", "password": MASK}
    assert "hunter2" not in json.dumps(service.history())
    assert "hunter2" not in json.dumps(service.follow(started["run_id"]))


# ---------------------------------------------------------------------- resume and retry


def test_resume_keeps_what_succeeded_and_runs_the_rest(
    service: PipelineService, workshop: _Workshop
) -> None:
    draft = _draft(("first", "T_echo", {"value": "kept"}), ("second", "T_flaky", None))
    failed = _finished(service, service.start(draft)["run_id"])
    assert failed["status"] == "failed"
    workshop.broken = False
    resumed = service.resume(failed["run_id"], draft)
    assert (resumed["run_id"], resumed["active"]) == (failed["run_id"], True)
    done = _finished(service, failed["run_id"])
    assert (done["status"], done["active"]) == ("succeeded", False)
    assert done["tasks"]["second"]["result"] == "repaired"
    assert workshop.calls.count("echo:'kept'") == 1
    assert workshop.calls.count("flaky") == 2
    again = service.resume(failed["run_id"], draft)
    assert (again["status"], again["active"]) == ("succeeded", False)


def test_resume_refuses_what_cannot_be_resumed(
    service: PipelineService, workshop: _Workshop
) -> None:
    draft = _draft(("bad", "T_fail", None))
    failed = _finished(service, service.start(draft)["run_id"])
    with pytest.raises(PipelineException, match="unknown run"):
        service.resume("nope", draft)
    other = _draft(("bad", "T_fail", None))
    other.set_name("other")
    with pytest.raises(PipelineException, match="belongs to pipeline 'chain'"):
        service.resume(failed["run_id"], other)
    needs_param = _draft(("bad", "T_echo", {"value": "${params.absent}"}))
    with pytest.raises(PipelineDefinitionException, match="unknown parameter 'absent'"):
        service.resume(failed["run_id"], needs_param)
    with pytest.raises(PipelineDefinitionException):
        service.resume(failed["run_id"], PipelineDraft("chain"))
    assert workshop.calls == ["fail"]


def test_a_run_that_is_still_executing_cannot_be_resumed(
    service: PipelineService, workshop: _Workshop
) -> None:
    draft = _draft(("hold", "T_hold", None))
    run_id = service.start(draft)["run_id"]
    assert workshop.entered.wait(WAIT)
    with pytest.raises(AppException, match="still executing"):
        service.resume(run_id, draft)
    workshop.gate.set()
    assert _finished(service, run_id)["status"] == "succeeded"


def test_retry_starts_a_new_run_with_the_same_parameters(service: PipelineService) -> None:
    draft = _draft(("a", "T_echo", {"value": "${params.word}"}))
    first = _finished(service, service.start(draft, {"word": "again"})["run_id"])
    second = service.retry(first["run_id"], draft)
    assert second["run_id"] != first["run_id"]
    assert _finished(service, second["run_id"])["tasks"]["a"]["result"] == "again"
    with pytest.raises(PipelineException, match="unknown run"):
        service.retry("nope", draft)


# ---------------------------------------------------------------------- testing one task


def test_one_task_is_tested_alone_with_stand_ins_for_its_upstream(
    service: PipelineService, workshop: _Workshop, bus: EventBus
) -> None:
    draft = _draft(
        ("first", "T_fail", None),
        ("second", "T_echo", {"value": "${tasks.first.result}"}),
        ("third", "T_fail", None),
    )
    outcome = service.test_task(draft, "second", results={"first": {"rows": 3}})
    run = outcome["run"]
    assert run["status"] == "succeeded"
    assert list(run["tasks"]) == ["second"]
    assert run["tasks"]["second"]["result"] == {"rows": 3}
    assert [event["type"] for event in outcome["events"]][-1] == "pipeline.completed"
    assert workshop.calls == ["echo:{'rows': 3}"]
    assert service.history() == []
    assert bus.recent(10) == []
    assert service.test_task(draft, "second")["run"]["tasks"]["second"]["result"] is None


def test_a_tested_task_that_fails_reports_its_error(service: PipelineService) -> None:
    draft = _draft(("bad", "T_fail", None))
    run = service.test_task(draft, "bad")["run"]
    assert run["status"] == "failed"
    assert run["tasks"]["bad"]["error"] == "ValueError: it broke"


def test_a_tested_task_uses_its_retry_policy_and_the_given_parameters(
    service: PipelineService, workshop: _Workshop
) -> None:
    draft = _draft(("flaky", "T_flaky", None), ("say", "T_echo", {"value": "${params.word}"}))
    draft.set_retry("flaky", max_attempts=2, on=["ConnectionError"])
    assert service.test_task(draft, "flaky")["run"]["tasks"]["flaky"]["attempts"] == 2
    assert service.test_task(draft, "say", {"word": "hi"})["run"]["tasks"]["say"]["result"] == "hi"
    assert workshop.calls.count("flaky") == 2


def test_a_task_with_problems_or_an_unknown_task_cannot_be_tested(
    service: PipelineService,
) -> None:
    draft = _draft(("a", "T_missing", None))
    with pytest.raises(PipelineDefinitionException, match="unknown action 'T_missing'"):
        service.test_task(draft, "a")
    with pytest.raises(AppException, match="no task 'ghost'"):
        service.test_task(draft, "ghost")


# ---------------------------------------------------------------------- files


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_a_draft_is_saved_and_loaded_with_its_layout_next_to_it(
    service: PipelineService, tmp_path: Path, suffix: str
) -> None:
    draft = _draft(("a", "T_echo", {"value": "${params.word}"}), ("b", "T_flaky", None))
    draft.set_retry("b", max_attempts=3, on=["ConnectionError"])
    draft.set_params({"word": "hi"})
    draft.set_position("b", 321.0, 123.0)
    path = tmp_path / f"chain{suffix}"
    assert service.save(draft, path) == str(path)
    assert draft.dirty is False
    sidecar = layout_path(path)
    assert sidecar.name == f"chain{suffix}.layout.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["positions"]["b"] == [321.0, 123.0]
    assert "321" not in path.read_text(encoding="utf-8")
    assert Pipeline.from_file(path).name == "chain"
    loaded = service.load(path)
    assert loaded.to_definition() == draft.to_definition()
    assert loaded.positions() == draft.positions()
    assert (loaded.dirty, loaded.load_notes) == (False, ())


def test_a_definition_without_a_layout_is_laid_out_and_a_broken_layout_is_ignored(
    service: PipelineService, tmp_path: Path
) -> None:
    path = tmp_path / "plain.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "plain",
                "tasks": {
                    "a": {"action": ["T_echo"]},
                    "b": {"action": ["T_echo"], "depends_on": ["a"]},
                },
            }
        ),
        encoding="utf-8",
    )
    expected = {"a": (40.0, 40.0), "b": (280.0, 40.0)}
    assert service.load(path).positions() == expected
    layout_path(path).write_text("{not json", encoding="utf-8")
    assert service.load(path).positions() == expected
    layout_path(path).write_text("[]", encoding="utf-8")
    assert service.load(path).positions() == expected


def test_saving_and_loading_report_what_they_cannot_do(
    service: PipelineService, tmp_path: Path
) -> None:
    draft = _draft(("a", "T_echo", None))
    with pytest.raises(AppException, match=r"\.yaml, \.yml or \.json"):
        service.save(draft, tmp_path / "chain.txt")
    with pytest.raises(PipelineDefinitionException, match="cannot read the definition"):
        service.load(tmp_path / "missing.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("tasks: [unclosed", encoding="utf-8")
    with pytest.raises(PipelineDefinitionException, match="invalid YAML"):
        service.load(broken)


def test_an_invalid_definition_file_opens_with_its_notes(
    service: PipelineService, tmp_path: Path
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schema_version: 1\nname: x\ntasks:\n  a: {action: []}\n", encoding="utf-8")
    draft = service.load(path)
    assert draft.task_ids() == ("a",)
    assert any("tasks.a.action" in note for note in draft.load_notes)


def test_a_new_draft_carries_the_given_name(service: PipelineService) -> None:
    assert service.new_draft("nightly").name == "nightly"
    assert service.new_draft().name == "pipeline"


# ---------------------------------------------------------------------- the default store


def test_without_a_store_the_default_run_store_is_used_at_every_call(
    workshop: _Workshop, bus: EventBus, tmp_path: Path
) -> None:
    service = PipelineService(registry=workshop.registry(), bus=bus)
    previous = default_run_store()
    replacement = SQLiteRunStore(tmp_path / "runs.db")
    set_default_run_store(replacement)
    try:
        done = _finished(service, service.start(_draft(("a", "T_echo", None)))["run_id"])
        assert replacement.get_run(done["run_id"]) is not None
        assert previous.get_run(done["run_id"]) is None
    finally:
        set_default_run_store(previous)
