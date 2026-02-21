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


# --- Global memory layer tests ---

def test_load_global_memories_returns_list(isolated_env):
    mems = memory.load_global_memories()
    assert isinstance(mems, list)


def test_global_memories_roundtrip(isolated_env):
    test_mems = ["global fact one", "global fact two"]
    memory.save_global_memories(test_mems)
    loaded = memory.load_global_memories()
    assert loaded == test_mems


def test_load_all_memories_deduplicates(isolated_env):
    memory.get_project_dir()
    memory.save_global_memories(["shared fact", "global only"])
    memory.save_memories(["shared fact", "project only"])
    combined, global_mems, project_mems = memory.load_all_memories()
    assert global_mems == ["shared fact", "global only"]
    assert project_mems == ["shared fact", "project only"]
    assert combined == ["shared fact", "global only", "project only"]


def test_load_memories_no_root_fallback(isolated_env):
    """Verify load_memories does NOT fall back to root memory.json."""
    # Write to root memory.json
    root_path = os.path.join(memory.BASE_DIR, "memory.json")
    with open(root_path, "w") as f:
        json.dump(["root fact"], f)
    # load_memories should return empty (no project file exists)
    mems = memory.load_memories()
    assert mems == []


def test_build_system_prompt_includes_global_memories(isolated_env):
    memory.save_global_memories(["user is left-handed"])
    prompt = memory.build_system_prompt([])
    assert "Core facts" in prompt
    assert "user is left-handed" in prompt


def test_build_system_prompt_includes_resume_ref(isolated_env):
    resume_path = memory.get_resume_path()
    os.makedirs(os.path.dirname(resume_path), exist_ok=True)
    with open(resume_path, "w") as f:
        f.write("# Resume\nTest resume content")
    prompt = memory.build_system_prompt([])
    assert "Resume is available" in prompt
    assert resume_path in prompt


def test_get_cross_project_summary(isolated_env):
    # Create a project with tasks and conversations
    proj_dir = os.path.join(memory.PROJECTS_DIR, "side-project")
    os.makedirs(os.path.join(proj_dir, "conversations"), exist_ok=True)
    with open(os.path.join(proj_dir, "conversations", "test.txt"), "w") as f:
        f.write("test convo")
    tasks_data = {"tasks": [{"status": "open", "title": "do thing"}]}
    with open(os.path.join(proj_dir, "tasks.json"), "w") as f:
        json.dump(tasks_data, f)

    summary = memory.get_cross_project_summary()
    assert "side-project" in summary
    assert "1 open task" in summary
    assert "1 conversation" in summary
