"""Tests for memory.py — config, memories, projects, slugify."""

import json
import os

import memory


def test_load_config_has_default_keys():
    config = memory.load_config()
    assert "briefing" in config
    assert "email_notifications" in config
    assert "job_scan" in config
    assert "user_profile" in config
    assert "notification_channels" in config


def test_config_roundtrip(isolated_env):
    config = memory.load_config()
    config["test_key"] = "test_value"
    memory.save_config(config)

    reloaded = memory.load_config()
    assert reloaded["test_key"] == "test_value"


def test_get_user_profile_keys():
    profile = memory.get_user_profile()
    assert isinstance(profile, dict)
    assert "name" in profile
    assert "first_name" in profile
    assert "email" in profile
    assert "title" in profile


def test_load_memories_returns_list(isolated_env):
    mems = memory.load_memories()
    assert isinstance(mems, list)


def test_memories_roundtrip(isolated_env):
    # Ensure the project dir exists
    memory.get_project_dir()
    test_mems = ["fact one", "fact two"]
    memory.save_memories(test_mems)
    loaded = memory.load_memories()
    assert loaded == test_mems


def test_switch_project_creates_dirs(isolated_env):
    memory.switch_project("test-project")
    assert memory.active_project == "test-project"
    assert os.path.isdir(memory.get_conversations_dir())
    assert os.path.isdir(memory.get_workspace_dir())
    # Reset
    memory.switch_project("general")


def test_slugify_basic():
    assert memory.slugify("Hello World!") == "hello-world"


def test_slugify_empty():
    assert memory.slugify("") == ""


def test_slugify_special_chars():
    assert memory.slugify("  @#$  test---case  ") == "test-case"
