"""Tests for the persistent user model system."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# --- Storage tests ---

def test_load_profile_missing_file(isolated_env, monkeypatch):
    """load_profile returns empty list when file doesn't exist."""
    import user_model
    monkeypatch.setattr(user_model, "PROFILE_FILE", os.path.join(isolated_env, "user_profile.json"))
    assert user_model.load_profile() == []


def test_add_entry_creates_valid_entry(isolated_env, monkeypatch):
    """add_entry creates an entry with all required fields."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    entry = user_model.add_entry("facts", "User is a developer", 0.9, "conversation")

    assert entry["category"] == "facts"
    assert entry["text"] == "User is a developer"
    assert entry["confidence"] == 0.9
    assert entry["source"] == "conversation"
    assert "id" in entry
    assert "created" in entry
    assert "updated" in entry
    assert entry["supersedes"] is None


def test_save_load_roundtrip(isolated_env, monkeypatch):
    """save_profile and load_profile roundtrip correctly."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    entries = [
        {"id": "abc123", "category": "facts", "text": "Test fact", "confidence": 0.8,
         "source": "conversation", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None},
    ]
    user_model.save_profile(entries)
    loaded = user_model.load_profile()
    assert len(loaded) == 1
    assert loaded[0]["text"] == "Test fact"


def test_remove_entry_by_id(isolated_env, monkeypatch):
    """remove_entry removes the entry and returns True."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    entry = user_model.add_entry("facts", "To be removed", 0.5)
    assert user_model.remove_entry(entry["id"]) is True
    assert len(user_model.load_profile()) == 0


def test_remove_entry_not_found(isolated_env, monkeypatch):
    """remove_entry returns False for nonexistent ID."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    assert user_model.remove_entry("nonexistent") is False


def test_clear_profile(isolated_env, monkeypatch):
    """clear_profile empties the profile file."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    user_model.add_entry("facts", "Something", 0.8)
    user_model.clear_profile()
    assert user_model.load_profile() == []


# --- Extraction tests ---

def test_extract_from_conversation_parses_response(isolated_env, monkeypatch):
    """extract_from_conversation parses CATEGORY|CONFIDENCE|text lines."""
    import user_model
    import models

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    # Mock the API response
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="facts|0.9|User is a software engineer\npreferences|0.7|User prefers morning meetings")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 20

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    monkeypatch.setattr(models, "get_client", lambda: mock_client)
    monkeypatch.setattr(models, "get_tier", lambda t: "claude-haiku-4-5")
    monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

    history = [
        {"role": "user", "content": "I'm a software engineer"},
        {"role": "assistant", "content": "Nice!"},
        {"role": "user", "content": "I prefer morning meetings"},
        {"role": "assistant", "content": "Got it."},
    ]

    count = user_model.extract_from_conversation(history)
    assert count == 2

    entries = user_model.load_profile()
    assert len(entries) == 2
    categories = {e["category"] for e in entries}
    assert "facts" in categories
    assert "preferences" in categories


def test_extract_from_conversation_handles_nothing_new(isolated_env, monkeypatch):
    """extract_from_conversation returns 0 when model says NOTHING_NEW."""
    import user_model
    import models

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="NOTHING_NEW")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 5

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    monkeypatch.setattr(models, "get_client", lambda: mock_client)
    monkeypatch.setattr(models, "get_tier", lambda t: "claude-haiku-4-5")
    monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "What time is it?"},
        {"role": "assistant", "content": "I don't know."},
    ]

    count = user_model.extract_from_conversation(history)
    assert count == 0
    assert user_model.load_profile() == []


def test_maybe_extract_skips_short_conversations(isolated_env, monkeypatch):
    """maybe_extract doesn't start extraction for < 4 messages."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    with patch.object(user_model, "extract_from_conversation") as mock_extract:
        user_model.maybe_extract([{"role": "user", "content": "hi"}])
        mock_extract.assert_not_called()


def test_maybe_extract_respects_config_disabled(isolated_env, monkeypatch):
    """maybe_extract does nothing when extraction_enabled is false."""
    import user_model
    import memory

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(memory, "load_config", lambda: {"user_model": {"extraction_enabled": False}})

    with patch.object(user_model, "extract_from_conversation") as mock_extract:
        history = [{"role": "user", "content": f"msg {i}"} for i in range(6)]
        user_model.maybe_extract(history)
        mock_extract.assert_not_called()


# --- Format tests ---

def test_format_for_prompt_groups_by_category(isolated_env, monkeypatch):
    """format_for_prompt groups entries by category."""
    import user_model
    import memory

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(memory, "load_config", lambda: {})

    user_model.save_profile([
        {"id": "a", "category": "facts", "text": "User is a developer", "confidence": 0.9,
         "source": "conversation", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None},
        {"id": "b", "category": "goals", "text": "Wants to learn Rust", "confidence": 0.7,
         "source": "conversation", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None},
    ])

    result = user_model.format_for_prompt()
    assert "Learned user profile:" in result
    assert "Facts:" in result
    assert "Goals:" in result
    assert "User is a developer" in result
    assert "Wants to learn Rust" in result


def test_format_for_prompt_empty(isolated_env, monkeypatch):
    """format_for_prompt returns empty string with no entries."""
    import user_model
    import memory

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(memory, "load_config", lambda: {})

    assert user_model.format_for_prompt() == ""


# --- Pattern detection tests ---

def test_detect_patterns_returns_tuple(isolated_env, monkeypatch):
    """detect_patterns returns (count, cost) tuple."""
    import user_model
    import models
    import memory

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(memory, "load_config", lambda: {})

    # Seed an existing entry so detect_patterns doesn't bail early
    user_model.save_profile([
        {"id": "seed1", "category": "facts", "text": "User is a developer", "confidence": 0.9,
         "source": "onboarding", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="patterns|0.8|User frequently works on web projects")]
    mock_response.usage.input_tokens = 200
    mock_response.usage.output_tokens = 30

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    monkeypatch.setattr(models, "get_client", lambda: mock_client)
    monkeypatch.setattr(models, "get_tier", lambda t: "claude-sonnet-4-6")
    monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.005)

    # Mock tasks module
    mock_tasks = MagicMock()
    mock_tasks.get_all_project_tasks.return_value = []
    monkeypatch.setitem(__import__("sys").modules, "tasks", mock_tasks)

    count, cost = user_model.detect_patterns()
    assert count == 1
    assert cost == 0.005


def test_detect_patterns_respects_config_disabled(isolated_env, monkeypatch):
    """detect_patterns returns (0, 0) when disabled."""
    import user_model
    import memory

    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(memory, "load_config", lambda: {"user_model": {"pattern_detection_enabled": False}})

    count, cost = user_model.detect_patterns()
    assert count == 0
    assert cost == 0


# --- Dedup/Prune tests ---

def test_deduplicate_merges_near_duplicates(isolated_env, monkeypatch):
    """_deduplicate merges entries with same category+text, keeps highest confidence."""
    import user_model

    entries = [
        {"id": "a", "category": "facts", "text": "User is a developer", "confidence": 0.7,
         "source": "conversation", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None},
        {"id": "b", "category": "facts", "text": "User is a developer", "confidence": 0.9,
         "source": "conversation", "created": "2026-01-02", "updated": "2026-01-02", "supersedes": None},
    ]

    result = user_model._deduplicate(entries)
    assert len(result) == 1
    assert result[0]["confidence"] == 0.9
    assert result[0]["supersedes"] == "a"


def test_prune_enforces_max_entries(isolated_env, monkeypatch):
    """_prune reduces entries to MAX_ENTRIES, keeping highest confidence."""
    import user_model
    monkeypatch.setattr(user_model, "MAX_ENTRIES", 5)

    entries = [
        {"id": str(i), "category": "facts", "text": f"Fact {i}", "confidence": i / 10.0,
         "source": "conversation", "created": "2026-01-01", "updated": "2026-01-01", "supersedes": None}
        for i in range(10)
    ]

    result = user_model._prune(entries)
    assert len(result) == 5
    # Highest confidence entries should be kept
    confidences = [e["confidence"] for e in result]
    assert min(confidences) >= 0.5


def test_add_entry_invalid_category(isolated_env, monkeypatch):
    """add_entry raises ValueError for invalid category."""
    import user_model
    profile_path = os.path.join(isolated_env, "user_profile.json")
    monkeypatch.setattr(user_model, "PROFILE_FILE", profile_path)

    with pytest.raises(ValueError, match="Invalid category"):
        user_model.add_entry("invalid_cat", "text", 0.5)
