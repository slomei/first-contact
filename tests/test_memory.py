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


# --- Semantic memory tests ---

def test_memory_format_migration(isolated_env):
    """Old list-of-strings format migrates to new dict format on save."""
    memory.get_project_dir()
    path = memory.get_memory_file()
    # Write old format directly
    with open(path, "w") as f:
        json.dump(["old fact one", "old fact two"], f)
    # Load (reads old format)
    loaded = memory.load_memories()
    assert loaded == ["old fact one", "old fact two"]
    # Save (writes new format)
    memory.save_memories(loaded)
    # Verify new format on disk
    with open(path, "r") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert "memories" in data
    assert len(data["memories"]) == 2
    assert data["memories"][0]["text"] == "old fact one"


def test_new_format_roundtrip(isolated_env):
    """Save/load in new format preserves text."""
    memory.get_project_dir()
    test_mems = ["alpha", "beta", "gamma"]
    memory.save_memories(test_mems)
    loaded = memory.load_memories()
    assert loaded == test_mems


def test_retrieve_relevant_memories_fallback(isolated_env):
    """Without semantic, retrieve_relevant_memories returns all memories."""
    memory.get_project_dir()
    memory.save_global_memories(["global one", "global two"])
    memory.save_memories(["project one"])
    result = memory.retrieve_relevant_memories("anything", top_k=10)
    # Should return all since SEMANTIC_AVAILABLE is False in test env
    assert "global one" in result
    assert "global two" in result
    assert "project one" in result


def test_retrieve_returns_all_when_under_topk(isolated_env):
    """When count <= top_k, returns all memories."""
    memory.get_project_dir()
    memory.save_memories(["only one"])
    memory.save_global_memories([])
    result = memory.retrieve_relevant_memories("query", top_k=10)
    assert result == ["only one"]


def test_save_preserves_metadata(isolated_env):
    """Adding a memory preserves existing created timestamps."""
    memory.get_project_dir()
    memory.save_memories(["first fact"])
    # Load to populate cache
    memory.load_memories()
    # Check cache has a created timestamp
    assert "first fact" in memory._project_memory_cache
    created = memory._project_memory_cache["first fact"].get("created")
    assert created is not None
    # Save with an additional memory
    memory.save_memories(["first fact", "second fact"])
    memory.load_memories()
    # First fact should still have same created timestamp
    assert memory._project_memory_cache["first fact"]["created"] == created


def test_forget_removes_from_cache(isolated_env):
    """Removing a memory cleans up internal state."""
    memory.get_project_dir()
    memory.save_memories(["keep this", "forget this"])
    memory.load_memories()
    assert "forget this" in memory._project_memory_cache
    # Remove one
    memory.save_memories(["keep this"])
    assert "forget this" not in memory._project_memory_cache
    assert "keep this" in memory._project_memory_cache


def test_get_semantic_status():
    """Returns a string containing 'Memory:'."""
    status = memory.get_semantic_status()
    assert "Memory:" in status


def test_build_system_prompt_with_query(isolated_env):
    """Query param accepted without error."""
    memory.save_global_memories(["user likes Python"])
    prompt = memory.build_system_prompt(["project fact"], query="tell me about Python")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_system_prompt_cached_returns_list(isolated_env):
    """build_system_prompt_cached returns two blocks: stable (cached) and dynamic."""
    result = memory.build_system_prompt_cached([])
    assert isinstance(result, list)
    assert len(result) == 2
    # Block 0: stable, has cache_control
    stable = result[0]
    assert stable["type"] == "text"
    assert "cache_control" in stable
    assert stable["cache_control"] == {"type": "ephemeral"}
    assert "Calibrate your honesty" in stable["text"]
    assert "Current time:" not in stable["text"]
    # Block 1: dynamic, no cache_control
    dynamic = result[1]
    assert dynamic["type"] == "text"
    assert "cache_control" not in dynamic
    assert "Current time:" in dynamic["text"]


def test_custom_prompt_roundtrip(isolated_env):
    """get/set custom prompt persists via config."""
    assert memory.get_custom_prompt() == ""
    memory.set_custom_prompt("Always respond in haiku form.")
    assert memory.get_custom_prompt() == "Always respond in haiku form."
    # Verify it appears in system prompt
    prompt = memory.build_system_prompt([])
    assert "Always respond in haiku form." in prompt
    assert "Custom instructions from the user:" in prompt
    # Clear
    memory.set_custom_prompt("")
    assert memory.get_custom_prompt() == ""
    prompt2 = memory.build_system_prompt([])
    assert "Custom instructions" not in prompt2


def test_custom_prompt_stored_in_config_key(isolated_env):
    """Custom prompt is stored under 'custom_prompt' key in config.json."""
    memory.set_custom_prompt("Be concise.")
    cfg = memory.load_config()
    assert cfg["custom_prompt"] == "Be concise."
    memory.set_custom_prompt("")


def test_custom_prompt_clear_removes_text(isolated_env):
    """Setting custom prompt to empty string clears it from config."""
    memory.set_custom_prompt("Something")
    assert memory.get_custom_prompt() == "Something"
    memory.set_custom_prompt("")
    assert memory.get_custom_prompt() == ""
    cfg = memory.load_config()
    assert cfg["custom_prompt"] == ""


def test_custom_prompt_layers_on_top(isolated_env):
    """Custom prompt is added on top of the core template, not replacing it."""
    base_prompt = memory.build_system_prompt([])
    memory.set_custom_prompt("Special user instruction.")
    custom_prompt = memory.build_system_prompt([])
    # Custom prompt should contain everything the base has, plus the custom text
    assert "Special user instruction." in custom_prompt
    assert "Custom instructions from the user:" in custom_prompt
    # Core template content is still present — check for a known stable element
    # (the base prompt always contains the identity/behavioral section)
    assert len(custom_prompt) > len(base_prompt)
    memory.set_custom_prompt("")


def test_custom_prompt_default_empty(isolated_env):
    """Default custom prompt is empty string when not set."""
    assert memory.get_custom_prompt() == ""


def test_custom_prompt_in_cached_version(isolated_env):
    """build_system_prompt_cached includes custom prompt in the stable block."""
    memory.set_custom_prompt("Cached custom instruction.")
    blocks = memory.build_system_prompt_cached([])
    # Stable block is first, has cache_control
    stable = blocks[0]
    assert stable["cache_control"] == {"type": "ephemeral"}
    assert "Cached custom instruction." in stable["text"]
    assert "Custom instructions from the user:" in stable["text"]
    memory.set_custom_prompt("")
