"""Tests for task and reminder tool integration.

Verifies that the agent's tools read/write the same data files
the daemon and terminal slash commands use.
"""

import json
import os

import pytest


@pytest.fixture
def task_env(isolated_env, monkeypatch):
    """Set up an isolated environment with tasks module ready."""
    import memory
    import tasks

    # Ensure project dir exists
    os.makedirs(os.path.join(memory.PROJECTS_DIR, "general"), exist_ok=True)
    return isolated_env


def test_list_tasks_returns_open_tasks(task_env):
    """Add 2 tasks, complete 1, list open -> sees only the open one."""
    import tasks
    import tools

    tasks.add_task("Buy groceries")
    tasks.add_task("Fix the bug")
    tasks.complete_task(1)

    result, is_error = tools.execute_tool("list_tasks", {})
    assert not is_error
    assert "Fix the bug" in result
    assert "Buy groceries" not in result


def test_list_tasks_done_filter(task_env):
    """Add task, complete it, list done -> sees it."""
    import tasks
    import tools

    tasks.add_task("Finish report")
    tasks.complete_task(1)

    result, is_error = tools.execute_tool("list_tasks", {"filter": "done"})
    assert not is_error
    assert "Finish report" in result
    assert "[done]" in result


def test_list_tasks_all_projects(task_env):
    """Add tasks in two projects, list all_projects -> sees both with project labels."""
    import memory
    import tasks
    import tools

    # Add task in general
    tasks.add_task("General task")

    # Switch to another project and add a task
    memory.switch_project("work")
    tasks.add_task("Work task")

    # Switch back
    memory.switch_project("general")

    result, is_error = tools.execute_tool("list_tasks", {"all_projects": True})
    assert not is_error
    assert "[general]" in result
    assert "[work]" in result
    assert "General task" in result
    assert "Work task" in result


def test_list_tasks_empty(task_env):
    """List tasks with no tasks -> returns 'No ... tasks'."""
    import tools

    result, is_error = tools.execute_tool("list_tasks", {})
    assert not is_error
    assert "No" in result
    assert "tasks" in result


def test_complete_task_tool(task_env):
    """Complete a task via tool, verify open list is empty."""
    import tasks
    import tools

    tasks.add_task("Only task")

    result, is_error = tools.execute_tool("complete_task", {"task_id": 1})
    assert not is_error
    assert "completed" in result

    # Verify open list is empty
    result2, _ = tools.execute_tool("list_tasks", {})
    assert "No" in result2


def test_complete_task_not_found(task_env):
    """Complete nonexistent ID -> is_error=True."""
    import tools

    result, is_error = tools.execute_tool("complete_task", {"task_id": 999})
    assert is_error
    assert "not found" in result


def test_edit_task_tool(task_env):
    """Edit description, verify persisted."""
    import tasks
    import tools

    tasks.add_task("Old description")

    result, is_error = tools.execute_tool("edit_task", {"task_id": 1, "description": "New description"})
    assert not is_error
    assert "updated" in result

    # Verify via list
    result2, _ = tools.execute_tool("list_tasks", {})
    assert "New description" in result2


def test_remove_task_tool(task_env):
    """Remove task, verify gone."""
    import tasks
    import tools

    tasks.add_task("Temporary task")

    result, is_error = tools.execute_tool("remove_task", {"task_id": 1})
    assert not is_error
    assert "removed" in result

    result2, _ = tools.execute_tool("list_tasks", {})
    assert "No" in result2


def test_add_task_note_tool(task_env):
    """Add note, verify in task data."""
    import tasks
    import tools

    tasks.add_task("Task with note")

    result, is_error = tools.execute_tool("add_task_note", {"task_id": 1, "note": "Important detail"})
    assert not is_error
    assert "Note added" in result

    # Verify via list
    result2, _ = tools.execute_tool("list_tasks", {})
    assert "Important detail" in result2


def test_list_reminders_tool(task_env):
    """Add reminder, list -> sees it."""
    import tasks
    import tools

    tasks.add_reminder("Follow up with recruiter", "in 2 hours")

    result, is_error = tools.execute_tool("list_reminders", {})
    assert not is_error
    assert "Follow up with recruiter" in result


def test_cancel_reminder_tool(task_env):
    """Add reminder, cancel, verify gone."""
    import tasks
    import tools

    reminder = tasks.add_reminder("Temp reminder", "in 1 hour")
    assert reminder is not None

    result, is_error = tools.execute_tool("cancel_reminder", {"reminder_id": reminder["id"]})
    assert not is_error
    assert "cancelled" in result

    result2, _ = tools.execute_tool("list_reminders", {})
    assert "No pending" in result2


def test_daemon_and_agent_share_task_data(task_env):
    """Create via tool, read via tool AND read same file directly (the daemon path)."""
    import memory
    import tasks
    import tools

    # Create via tool
    result, is_error = tools.execute_tool("create_task", {"description": "Shared task"})
    assert not is_error
    assert "Shared task" in result

    # Read via tool (agent path)
    result2, _ = tools.execute_tool("list_tasks", {})
    assert "Shared task" in result2

    # Read via file directly (daemon path)
    tasks_path = os.path.join(memory.PROJECTS_DIR, "general", "tasks.json")
    with open(tasks_path, "r") as f:
        data = json.load(f)
    task_descs = [t["description"] for t in data.get("tasks", [])]
    assert "Shared task" in task_descs
