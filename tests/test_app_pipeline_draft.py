"""The editable pipeline draft of the application layer."""

from __future__ import annotations

import json

import pytest

from automation_file.app import AppException, DraftTask, PipelineDraft, Problem
from automation_file.app.pipeline_draft import (
    CHANGE_HEADER,
    CHANGE_POSITION,
    CHANGE_STRUCTURE,
    CHANGE_TASK,
)
from automation_file.pipeline import Pipeline, validate_definition

COPY = "FA_storage_copy"
DELETE = "FA_storage_delete"


def _three_tasks() -> PipelineDraft:
    draft = PipelineDraft("nightly")
    draft.add_task(COPY, "download", arguments={"source": "memory://a/x", "target": "memory://b/x"})
    draft.add_task(COPY, "publish", arguments={"source": "memory://b/x", "target": "memory://c/x"})
    draft.add_task(DELETE, "tidy", arguments={"uri": "memory://b/x"})
    draft.connect("download", "publish")
    draft.connect("publish", "tidy")
    return draft


# ---------------------------------------------------------------------- tasks


def test_a_new_draft_is_empty_and_says_what_is_missing() -> None:
    draft = PipelineDraft()
    assert (draft.name, draft.max_workers, draft.tasks, draft.dirty) == ("pipeline", 4, (), False)
    assert [str(problem) for problem in draft.problems()] == [
        "tasks: at least one task is required"
    ]


def test_adding_a_task_derives_an_unused_id_from_the_action() -> None:
    draft = PipelineDraft()
    first = draft.add_task(COPY)
    second = draft.add_task(COPY)
    third = draft.add_task(COPY)
    blank = draft.add_task()
    assert [first.task_id, second.task_id, third.task_id, blank.task_id] == [
        "storage_copy",
        "storage_copy_2",
        "storage_copy_3",
        "task",
    ]
    assert draft.task_ids() == ("storage_copy", "storage_copy_2", "storage_copy_3", "task")
    assert draft.has_task("task") is True
    assert isinstance(draft.task("task"), DraftTask)


def test_a_task_id_must_be_valid_and_unused() -> None:
    draft = PipelineDraft()
    draft.add_task(COPY, "a")
    with pytest.raises(AppException, match="already has a task 'a'"):
        draft.add_task(COPY, "a")
    with pytest.raises(AppException, match="invalid task ID"):
        draft.add_task(COPY, "has space")
    with pytest.raises(AppException, match="invalid task ID"):
        draft.add_task(COPY, "a.b")
    with pytest.raises(AppException, match="no task 'missing'"):
        draft.task("missing")


def test_a_new_task_lands_below_the_lowest_one_unless_a_position_is_given() -> None:
    draft = PipelineDraft()
    first = draft.add_task(COPY, "a")
    second = draft.add_task(COPY, "b")
    third = draft.add_task(COPY, "c", position=(300, 12.5))
    assert (first.x, first.y) == (40.0, 40.0)
    assert (second.x, second.y) == (40.0, 150.0)
    assert (third.x, third.y) == (300.0, 12.5)


def test_removing_a_task_removes_the_edges_to_it() -> None:
    draft = _three_tasks()
    draft.remove_task("publish")
    assert draft.task_ids() == ("download", "tidy")
    assert draft.task("tidy").depends_on == []
    assert draft.edges() == []
    with pytest.raises(AppException):
        draft.remove_task("publish")


def test_renaming_keeps_the_order_the_edges_and_the_placeholders() -> None:
    draft = _three_tasks()
    draft.set_arguments(
        "tidy",
        {
            "uri": "${tasks.publish.result}",
            "note": ["${tasks.publish.result}", {"deep": "${tasks.publish.result}"}],
            "other": "${tasks.download.result}",
        },
    )
    renamed = draft.rename_task("publish", "upload")
    assert renamed.task_id == "upload"
    assert draft.task_ids() == ("download", "upload", "tidy")
    assert draft.edges() == [("download", "upload"), ("upload", "tidy")]
    assert draft.task("tidy").arguments == {
        "uri": "${tasks.upload.result}",
        "note": ["${tasks.upload.result}", {"deep": "${tasks.upload.result}"}],
        "other": "${tasks.download.result}",
    }
    assert draft.problems() == []
    assert draft.rename_task("upload", "upload").task_id == "upload"
    with pytest.raises(AppException, match="already has a task"):
        draft.rename_task("upload", "tidy")
    with pytest.raises(AppException, match="invalid task ID"):
        draft.rename_task("upload", "")


def test_the_action_and_its_arguments() -> None:
    draft = PipelineDraft()
    draft.add_task(COPY, "a")
    assert draft.task("a").to_spec() == {"action": [COPY]}
    draft.set_action("a", f"  {DELETE}  ")
    draft.set_arguments("a", {"uri": "memory://x/a"})
    assert draft.task("a").to_spec() == {"action": [DELETE, {"uri": "memory://x/a"}]}
    draft.set_arguments("a", ["memory://x/a", True])
    assert draft.task("a").to_spec() == {"action": [DELETE, ["memory://x/a", True]]}
    draft.set_arguments("a", None)
    assert draft.task("a").arguments is None
    with pytest.raises(AppException, match="mapping, a list or nothing"):
        draft.set_arguments("a", "text")  # type: ignore[arg-type]


def test_arguments_are_copied_in_and_out() -> None:
    draft = PipelineDraft()
    given = {"paths": ["a"]}
    draft.add_task(COPY, "a", arguments=given)
    given["paths"].append("b")
    assert draft.task("a").arguments == {"paths": ["a"]}
    spec = draft.to_definition()["tasks"]["a"]
    spec["action"][1]["paths"].append("c")
    assert draft.task("a").arguments == {"paths": ["a"]}


def test_retry_timeout_condition_and_idempotency_key() -> None:
    draft = PipelineDraft()
    draft.add_task(COPY, "a")
    draft.set_retry("a", max_attempts=3, backoff=1.5, on=["ConnectionError"])
    draft.set_timeout("a", 30)
    draft.set_condition("a", "always")
    draft.set_idempotency_key("a", "copy-${params.date}")
    assert draft.task("a").to_spec() == {
        "action": [COPY],
        "retry": {"max_attempts": 3, "backoff": 1.5, "on": ["ConnectionError"]},
        "timeout": 30,
        "when": "always",
        "idempotency_key": "copy-${params.date}",
    }
    draft.set_retry("a", backoff_cap=10)
    assert draft.task("a").retry == {"max_attempts": 1, "backoff_cap": 10}
    draft.set_retry("a")
    draft.set_timeout("a", None)
    draft.set_condition("a", "on_success")
    draft.set_idempotency_key("a", "")
    assert draft.task("a").to_spec() == {"action": [COPY]}
    with pytest.raises(AppException, match="when must be one of"):
        draft.set_condition("a", "sometimes")


def test_a_wrong_value_is_kept_and_reported_with_its_path() -> None:
    draft = PipelineDraft()
    draft.add_task(COPY, "a")
    draft.set_timeout("a", -1)
    draft.set_retry("a", max_attempts=0)
    found = {problem.path: problem for problem in draft.problems()}
    assert found["tasks.a.timeout"].task == "a"
    assert "seconds > 0" in found["tasks.a.timeout"].message
    assert found["tasks.a.retry.max_attempts"].task == "a"


# ---------------------------------------------------------------------- edges


def test_connecting_and_disconnecting() -> None:
    draft = _three_tasks()
    assert draft.edges() == [("download", "publish"), ("publish", "tidy")]
    assert draft.connect("download", "tidy") is True
    assert draft.connect("download", "tidy") is False
    assert draft.task("tidy").depends_on == ["publish", "download"]
    assert draft.disconnect("download", "tidy") is True
    assert draft.disconnect("download", "tidy") is False
    assert draft.to_definition()["tasks"]["tidy"]["depends_on"] == ["publish"]


def test_an_edge_to_itself_a_cycle_and_an_unknown_task_are_refused() -> None:
    draft = _three_tasks()
    with pytest.raises(AppException, match="cannot depend on itself"):
        draft.connect("tidy", "tidy")
    with pytest.raises(AppException, match="dependency cycle"):
        draft.connect("tidy", "download")
    with pytest.raises(AppException, match="no task 'ghost'"):
        draft.connect("ghost", "tidy")
    with pytest.raises(AppException, match="no task 'ghost'"):
        draft.connect("tidy", "ghost")
    assert draft.edges() == [("download", "publish"), ("publish", "tidy")]


def test_the_whole_dependency_list_of_a_task_can_be_replaced() -> None:
    draft = _three_tasks()
    changes: list[str] = []
    draft.add_listener(changes.append)
    draft.set_dependencies("tidy", ["download", "download"])
    assert draft.task("tidy").depends_on == ["download"]
    assert changes == [CHANGE_STRUCTURE]
    with pytest.raises(AppException, match="dependency cycle"):
        draft.set_dependencies("download", ["tidy"])


def test_an_edge_to_a_missing_task_is_not_an_edge_but_is_a_problem() -> None:
    draft = PipelineDraft.from_definition(
        {
            "schema_version": 1,
            "name": "p",
            "tasks": {"a": {"action": [COPY], "depends_on": ["ghost"]}},
        }
    )
    assert draft.edges() == []
    assert [str(problem) for problem in draft.problems()] == [
        "tasks.a.depends_on[0]: unknown task 'ghost'"
    ]


# ---------------------------------------------------------------------- layout


def test_positions_are_editor_metadata_and_never_reach_the_definition() -> None:
    draft = _three_tasks()
    draft.set_position("download", 512.5, 77)
    assert draft.positions()["download"] == (512.5, 77.0)
    definition = draft.to_definition()
    text = json.dumps(definition)
    assert "512.5" not in text
    assert "position" not in text
    assert "layout" not in text
    assert validate_definition(definition) == []
    assert Pipeline.from_dict(definition).name == "nightly"
    assert draft.task("download").to_dict()["position"] == [512.5, 77.0]


def test_the_layout_round_trips_apart_from_the_definition() -> None:
    draft = _three_tasks()
    draft.set_position("tidy", 9, 8)
    layout = draft.layout()
    assert layout["layout_version"] == 1
    assert layout["pipeline"] == "nightly"
    assert layout["positions"]["tidy"] == [9.0, 8.0]
    again = PipelineDraft.from_definition(draft.to_definition(), json.loads(json.dumps(layout)))
    assert again.positions() == draft.positions()


def test_a_layout_with_wrong_entries_places_what_it_can() -> None:
    draft = _three_tasks()
    placed = draft.apply_layout(
        {"positions": {"tidy": [1, 2], "ghost": [3, 4], "publish": "no", "download": [True, 1]}}
    )
    assert placed == 1
    assert draft.positions()["tidy"] == (1.0, 2.0)
    with pytest.raises(AppException, match="no 'positions' mapping"):
        draft.apply_layout({"positions": []})
    with pytest.raises(AppException, match="no 'positions' mapping"):
        draft.apply_layout("nonsense")


def test_the_automatic_layout_puts_each_dependency_depth_in_a_column() -> None:
    draft = _three_tasks()
    draft.add_task(DELETE, "side")
    draft.auto_layout()
    positions = draft.positions()
    assert positions["download"] == (40.0, 40.0)
    assert positions["side"] == (40.0, 150.0)
    assert positions["publish"] == (280.0, 40.0)
    assert positions["tidy"] == (520.0, 40.0)


def test_the_automatic_layout_survives_a_cycle() -> None:
    draft = PipelineDraft.from_definition(
        {
            "schema_version": 1,
            "name": "loop",
            "tasks": {
                "a": {"action": [COPY], "depends_on": ["b"]},
                "b": {"action": [COPY], "depends_on": ["a"]},
            },
        }
    )
    assert set(draft.positions()) == {"a", "b"}
    assert any("dependency cycle" in str(problem) for problem in draft.problems())


# ---------------------------------------------------------------------- header, listeners


def test_the_header_fields() -> None:
    draft = PipelineDraft()
    draft.set_name("  daily-report ")
    draft.set_description("Fetch and publish")
    draft.set_max_workers(2)
    draft.set_params({"date": "2026-10-08"})
    draft.set_schedule("0 2 * * *", "Asia/Taipei")
    draft.add_task(COPY, "a")
    assert draft.to_definition() == {
        "schema_version": 1,
        "name": "daily-report",
        "description": "Fetch and publish",
        "max_workers": 2,
        "schedule": {"cron": "0 2 * * *", "timezone": "Asia/Taipei"},
        "params": {"date": "2026-10-08"},
        "tasks": {"a": {"action": [COPY]}},
    }
    assert draft.problems() == []
    draft.set_schedule(None)
    draft.set_params(None)
    assert draft.schedule is None
    assert draft.params == {}
    with pytest.raises(AppException, match="max_workers"):
        draft.set_max_workers(0)
    with pytest.raises(AppException, match="params must be a mapping"):
        draft.set_params(["a"])  # type: ignore[arg-type]


def test_params_and_schedule_are_handed_out_as_copies() -> None:
    draft = PipelineDraft()
    draft.set_params({"list": [1]})
    draft.set_schedule("* * * * *")
    draft.params["list"].append(2)
    schedule = draft.schedule
    assert schedule is not None
    schedule["cron"] = "changed"
    assert draft.params == {"list": [1]}
    assert draft.schedule == {"cron": "* * * * *"}


def test_listeners_hear_every_change_with_its_kind() -> None:
    draft = PipelineDraft()
    changes: list[str] = []
    draft.add_listener(changes.append)
    draft.add_listener(changes.append)
    draft.add_task(COPY, "a")
    draft.add_task(COPY, "b")
    draft.connect("a", "b")
    draft.set_action("a", DELETE)
    draft.set_position("a", 5, 5)
    draft.set_position("a", 5, 5)
    draft.set_name("x")
    assert changes == [
        CHANGE_STRUCTURE,
        CHANGE_STRUCTURE,
        CHANGE_STRUCTURE,
        CHANGE_TASK,
        CHANGE_POSITION,
        CHANGE_HEADER,
    ]
    draft.remove_listener(changes.append)
    draft.set_name("y")
    assert len(changes) == 6


def test_a_batch_reports_each_kind_of_change_once_at_its_end() -> None:
    draft = PipelineDraft()
    draft.add_task(COPY, "a")
    changes: list[str] = []
    draft.add_listener(changes.append)
    with draft.batch():
        draft.set_action("a", DELETE)
        draft.set_timeout("a", 5)
        with draft.batch():
            draft.set_name("x")
        assert changes == []
    assert changes == [CHANGE_TASK, CHANGE_HEADER]


def test_the_revision_grows_and_dirty_follows_the_saved_state() -> None:
    draft = PipelineDraft()
    assert draft.revision == 0
    draft.add_task(COPY, "a")
    assert (draft.revision, draft.dirty) == (1, True)
    draft.mark_saved()
    assert draft.dirty is False
    draft.set_position("a", 1, 1)
    assert draft.dirty is True


# ---------------------------------------------------------------------- documents


def test_a_definition_round_trips_through_a_draft() -> None:
    definition = {
        "schema_version": 1,
        "name": "daily-report",
        "description": "Fetch and publish",
        "max_workers": 3,
        "schedule": {"cron": "0 2 * * *"},
        "params": {"date": "2026-10-08"},
        "tasks": {
            "download": {
                "action": [COPY, {"source": "s3://in/${params.date}.csv", "target": "local:///x"}],
                "retry": {"max_attempts": 5, "backoff": 2, "on": ["ConnectionError"]},
                "timeout": 300,
            },
            "withdraw": {
                "action": [DELETE, ["azure://reports/x", False, True]],
                "depends_on": ["download"],
                "when": "on_failure",
                "idempotency_key": "withdraw-${params.date}",
            },
            "bare": {"action": ["FA_storage_schemes"]},
        },
    }
    draft = PipelineDraft.from_definition(definition)
    assert draft.load_notes == ()
    assert draft.dirty is False
    assert draft.to_definition() == definition
    assert draft.task("bare").arguments is None


def test_a_broken_definition_still_opens_and_keeps_what_validation_said() -> None:
    draft = PipelineDraft.from_definition(
        {
            "schema_version": 1,
            "name": "",
            "max_workers": 0,
            "params": "nope",
            "tasks": {
                "ok": {"action": [COPY, "not arguments"], "depends_on": "ok", "timeout": "soon"},
                "bad id": {"action": [COPY]},
                "no-mapping": 3,
                "empty": {"action": []},
            },
        }
    )
    assert draft.name == "pipeline"
    assert draft.max_workers == 4
    assert draft.task_ids() == ("ok", "empty")
    assert draft.task("ok").arguments is None
    assert draft.task("ok").timeout is None
    assert draft.task("empty").action == ""
    assert any(note.startswith("max_workers:") for note in draft.load_notes)
    assert any("invalid task ID" in note for note in draft.load_notes)
    assert [problem.path for problem in draft.problems()] == ["tasks.empty.action[0]"]


def test_a_definition_must_be_a_mapping() -> None:
    with pytest.raises(AppException, match="is a mapping, got list"):
        PipelineDraft.from_definition([])


def test_a_problem_knows_its_task_and_its_text() -> None:
    ids = ("a", "a[0]", "verify")
    assert Problem.parse("tasks.verify.depends_on[0]: unknown task 'x'", ids) == Problem(
        "tasks.verify.depends_on[0]", "unknown task 'x'", "verify"
    )
    assert Problem.parse("tasks.a[0].action: wrong", ids).task == "a[0]"
    assert Problem.parse("tasks.a: duplicate task ID", ids).task == "a"
    assert Problem.parse("tasks.gone.action: wrong", ids).task == "gone"
    assert Problem.parse("tasks: dependency cycle: a -> b -> a", ids).task is None
    assert Problem.parse("max_workers: expected an integer", ids).task is None
    plain = Problem.parse("no path at all")
    assert (plain.path, plain.message, str(plain)) == ("", "no path at all", "no path at all")
    problem = Problem.parse("tasks.a.timeout: wrong", ids)
    assert str(problem) == "tasks.a.timeout: wrong"
    assert problem.to_dict() == {"path": "tasks.a.timeout", "message": "wrong", "task": "a"}
