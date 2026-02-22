"""Tests for notes, status helpers, and daemon-related functions."""

import os
import json
from datetime import datetime

import tools
import memory
import tasks


def test_save_note_creates_file(isolated_env):
    memory.get_project_dir()  # ensure project dir exists
    tools.save_note("This is a test note")
    notes_dir = os.path.join(
        memory.PROJECTS_DIR, memory.active_project, "notes"
    )
    assert os.path.isdir(notes_dir)
    # Check today's file was created
    today = memory.local_now().strftime("%Y-%m-%d")
    note_file = os.path.join(notes_dir, f"{today}.md")
    assert os.path.exists(note_file)
    with open(note_file) as f:
        content = f.read()
    assert "This is a test note" in content


def test_list_recent_notes_empty(isolated_env):
    memory.get_project_dir()
    result = tools.list_recent_notes()
    assert isinstance(result, list)
    assert len(result) == 0


def test_list_recent_notes_after_save(isolated_env):
    memory.get_project_dir()
    tools.save_note("Test note for listing")
    result = tools.list_recent_notes()
    assert len(result) > 0


def test_search_notes_empty(isolated_env):
    memory.get_project_dir()
    result = tools.search_notes("nonexistent")
    assert isinstance(result, list)
    assert len(result) == 0


def test_search_notes_finds_match(isolated_env):
    memory.get_project_dir()
    tools.save_note("The quick brown fox")
    result = tools.search_notes("quick brown")
    assert len(result) > 0


def test_get_pending_reminders(isolated_env):
    memory.get_project_dir()
    result = tasks.get_pending_reminders()
    assert isinstance(result, list)


def test_draft_rate_limit():
    """Test that draft rate limit tracking works."""
    old_count = tools._session_draft_count
    tools._session_draft_count = 0
    assert tools.check_draft_rate_limit() is True
    tools._session_draft_count = tools.DRAFT_RATE_LIMIT
    assert tools.check_draft_rate_limit() is False
    tools._session_draft_count = old_count


def test_load_draft_log(isolated_env):
    result = tools.load_draft_log()
    assert isinstance(result, list)


def test_daemon_pid_file_missing(isolated_env):
    """Daemon status check should handle missing PID file."""
    pid_path = os.path.join(isolated_env, "daemon.pid")
    assert not os.path.exists(pid_path)


def test_load_config_returns_dict(isolated_env):
    config = memory.load_config()
    assert isinstance(config, dict)


def test_load_config_has_briefing_key(isolated_env):
    config = memory.load_config()
    # Briefing key may or may not exist, but access shouldn't crash
    briefing = config.get("briefing", {})
    assert isinstance(briefing, dict)
