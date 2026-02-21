"""Shared fixtures for the test suite."""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _mock_anthropic(monkeypatch):
    """Mock the lazy-initialized Anthropic client so tests never hit the API."""
    mock_client = MagicMock()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    try:
        import models
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
    except Exception:
        pass


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test workspaces."""
    return tmp_path


@pytest.fixture
def clean_config():
    """Return a fresh copy of the default config dict."""
    import memory
    # Call load_config with a non-existent path to get defaults
    return memory.load_config()


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Monkeypatch memory.BASE_DIR and PROJECTS_DIR to temp dirs.

    Ensures tests never touch real user data.
    """
    import memory

    base = str(tmp_path / "first-contact")
    projects = os.path.join(base, "projects")
    os.makedirs(projects, exist_ok=True)

    monkeypatch.setattr(memory, "BASE_DIR", base)
    monkeypatch.setattr(memory, "PROJECTS_DIR", projects)

    # Reset active project so directory helpers use the new paths
    monkeypatch.setattr(memory, "active_project", "general")

    return base
