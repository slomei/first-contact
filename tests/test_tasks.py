"""Tests for tasks.py — task CRUD, reminders, date parsing."""

from datetime import datetime

import tasks


def test_add_task_returns_expected_keys(isolated_env):
    import memory
    memory.get_project_dir()  # Ensure project dir exists

    task = tasks.add_task("Test task")
    assert "id" in task
    assert "description" in task
    assert "status" in task
    assert "created_at" in task
    assert task["description"] == "Test task"
    assert task["status"] == "open"


def test_task_roundtrip(isolated_env):
    import memory
    memory.get_project_dir()

    task = tasks.add_task("Roundtrip task")
    tid = task["id"]

    # Verify it appears in open tasks
    open_tasks = tasks.get_open_tasks()
    assert any(t["id"] == tid for t in open_tasks)

    # Mark done
    done = tasks.complete_task(tid)
    assert done is not None
    assert done["status"] == "done"

    # Verify it's in done list
    done_tasks = tasks.get_done_tasks()
    assert any(t["id"] == tid for t in done_tasks)


def test_parse_natural_date_tomorrow():
    result = tasks.parse_natural_date("tomorrow")
    assert result is not None
    assert isinstance(result, datetime)
    assert result > datetime.now()


def test_parse_natural_date_in_n_days():
    result = tasks.parse_natural_date("in 3 days")
    assert result is not None
    assert isinstance(result, datetime)
    assert result > datetime.now()


def test_parse_natural_date_empty():
    assert tasks.parse_natural_date("") is None
    assert tasks.parse_natural_date(None) is None
