"""Tests for daemon hot-reload file watching."""

import os
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from daemon import FileChangeHandler, _EXCLUDED_DIRS


def _make_handler(base_dir, services=None):
    """Create a FileChangeHandler with mocked dependencies."""
    if services is None:
        services = [
            {"name": "web_ui", "process": MagicMock(poll=MagicMock(return_value=None))},
            {"name": "discord", "process": MagicMock(poll=MagicMock(return_value=None))},
            {"name": "telegram", "process": MagicMock(poll=MagicMock(return_value=None))},
        ]
    log = MagicMock()
    log_file = MagicMock()
    handler = FileChangeHandler(services, log, log_file, base_dir)
    return handler


def _make_event(path, is_directory=False):
    """Create a mock file system event."""
    return SimpleNamespace(src_path=path, is_directory=is_directory)


class TestFileFiltering:
    """Tests for file type and directory filtering."""

    def test_handler_filters_py_files_only(self, tmp_path):
        """Only .py files should be accumulated in _pending_files."""
        handler = _make_handler(str(tmp_path))
        # Disable timer so debounce doesn't fire
        with patch("daemon.threading.Timer") as mock_timer:
            mock_timer.return_value = MagicMock()
            handler.on_modified(_make_event(str(tmp_path / "tools.py")))
            handler.on_modified(_make_event(str(tmp_path / "readme.txt")))
            handler.on_modified(_make_event(str(tmp_path / "data.json")))
            handler.on_modified(_make_event(str(tmp_path / "models.py")))
        assert handler._pending_files == {"tools.py", "models.py"}

    def test_handler_ignores_excluded_dirs(self, tmp_path):
        """Files in excluded directories should be ignored."""
        handler = _make_handler(str(tmp_path))
        with patch("daemon.threading.Timer") as mock_timer:
            mock_timer.return_value = MagicMock()
            handler.on_modified(_make_event(str(tmp_path / "__pycache__" / "tools.cpython-310.pyc")))
            handler.on_modified(_make_event(str(tmp_path / "tests" / "test_foo.py")))
            handler.on_modified(_make_event(str(tmp_path / "venv" / "lib" / "site.py")))
            handler.on_modified(_make_event(str(tmp_path / ".git" / "hooks" / "pre-commit.py")))
            handler.on_modified(_make_event(str(tmp_path / "conversations" / "log.py")))
        assert handler._pending_files == set()

    def test_handler_ignores_directory_events(self, tmp_path):
        """Directory events should be ignored."""
        handler = _make_handler(str(tmp_path))
        handler.on_modified(_make_event(str(tmp_path / "web_ui"), is_directory=True))
        assert handler._pending_files == set()


class TestDebounce:
    """Tests for debounce behavior."""

    def test_debounce_collects_multiple_events(self, tmp_path):
        """Multiple rapid events should accumulate files, starting only one timer."""
        handler = _make_handler(str(tmp_path))
        timers = []
        with patch("daemon.threading.Timer") as mock_timer_cls:
            mock_instance = MagicMock()
            mock_timer_cls.return_value = mock_instance
            timers.append(mock_instance)

            handler.on_modified(_make_event(str(tmp_path / "tools.py")))
            handler.on_modified(_make_event(str(tmp_path / "memory.py")))
            handler.on_modified(_make_event(str(tmp_path / "models.py")))

        # All three files collected
        assert handler._pending_files == {"tools.py", "memory.py", "models.py"}
        # Timer was created 3 times (each event cancels previous and starts new)
        assert mock_timer_cls.call_count == 3
        # Previous timers were cancelled (first two)
        assert mock_instance.cancel.call_count == 2


class TestDetermineRestarts:
    """Tests for file-to-subprocess mapping logic."""

    def test_mapping_web_ui_file(self, tmp_path):
        """Changes in web_ui/ should only restart the web_ui service."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"web_ui/server.py"})
        assert result == {"web_ui"}

    def test_mapping_core_file_restarts_all(self, tmp_path):
        """Changes to core modules should restart all services."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"tools.py"})
        assert result == {"web_ui", "discord", "telegram"}

    def test_mapping_daemon_self(self, tmp_path):
        """Changes to daemon.py should return empty set and log a warning."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"daemon.py"})
        assert result == set()
        handler.log.warning.assert_called_once()

    def test_mapping_discord_bot(self, tmp_path):
        """Changes to discord_bot.py should only restart discord."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"discord_bot.py"})
        assert result == {"discord"}

    def test_mapping_telegram_bot(self, tmp_path):
        """Changes to telegram_bot.py should only restart telegram."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"telegram_bot.py"})
        assert result == {"telegram"}

    def test_mapping_plugin_restarts_all(self, tmp_path):
        """Changes in plugins/ should restart all services."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"plugins/my_plugin.py"})
        assert result == {"web_ui", "discord", "telegram"}

    def test_mapping_mixed_changes(self, tmp_path):
        """Multiple changed files combine their restart sets."""
        handler = _make_handler(str(tmp_path))
        result = handler._determine_restarts({"web_ui/server.py", "discord_bot.py"})
        assert result == {"web_ui", "discord"}
