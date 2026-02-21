"""Tests for help_data.py — shared help system."""

import help_data


def test_help_categories_non_empty():
    assert len(help_data.HELP_CATEGORIES) > 0


def test_every_category_has_required_fields():
    for name, cat in help_data.HELP_CATEGORIES.items():
        assert "desc" in cat, f"Category '{name}' missing 'desc'"
        assert "commands" in cat, f"Category '{name}' missing 'commands'"
        assert len(cat["commands"]) > 0, f"Category '{name}' has no commands"
        for cmd, desc in cat["commands"]:
            assert isinstance(cmd, str) and cmd, f"Empty command in '{name}'"
            assert isinstance(desc, str) and desc, f"Empty desc for '{cmd}' in '{name}'"


def test_fuzzy_match_exact():
    result = help_data.fuzzy_match_category("chat")
    assert result is not None
    assert result[0] == "chat"


def test_fuzzy_match_prefix():
    result = help_data.fuzzy_match_category("ema")
    assert result is not None
    assert result[0] == "email"


def test_fuzzy_match_none():
    result = help_data.fuzzy_match_category("zzzzz")
    assert result is None


def test_format_terminal_overview():
    colors = {"CYAN": "", "BOLD": "", "DIM": "", "RESET": ""}
    text = help_data.format_terminal_overview(colors)
    assert "HELP" in text
    assert "/help" in text


def test_format_terminal_category():
    colors = {"CYAN": "", "BOLD": "", "DIM": "", "RESET": ""}
    text = help_data.format_terminal_category("chat", colors)
    assert text is not None
    assert "CHAT" in text


def test_format_terminal_category_not_found():
    colors = {"CYAN": "", "BOLD": "", "DIM": "", "RESET": ""}
    assert help_data.format_terminal_category("zzzzz", colors) is None


def test_format_terminal_error():
    colors = {"RED": "", "DIM": "", "RESET": ""}
    text = help_data.format_terminal_error("zzz", colors)
    assert "Unknown category" in text


def test_format_discord_overview():
    text = help_data.format_discord_overview()
    assert "!help" in text
    assert "command categories" in text.lower()


def test_format_discord_category():
    text = help_data.format_discord_category("email")
    assert text is not None
    assert "EMAIL" in text


def test_format_discord_error():
    text = help_data.format_discord_error("zzz")
    assert "Unknown category" in text


def test_format_telegram_overview():
    text = help_data.format_telegram_overview()
    assert "/help" in text


def test_format_telegram_category():
    text = help_data.format_telegram_category("tasks")
    assert text is not None
    assert "TASKS" in text


def test_format_telegram_error():
    text = help_data.format_telegram_error("zzz")
    assert "Unknown category" in text


def test_format_gui_overview():
    text = help_data.format_gui_overview()
    assert "/help" in text
    assert "| Category |" in text


def test_format_gui_category():
    text = help_data.format_gui_category("jobs")
    assert text is not None
    assert "JOBS" in text
    assert "| Command |" in text


def test_format_gui_error():
    text = help_data.format_gui_error("zzz")
    assert "Unknown category" in text
