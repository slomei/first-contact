"""Tests for the plugin system."""

import os
import sys
import types

import pytest

import plugins


@pytest.fixture(autouse=True)
def _clean_plugins(tmp_path, monkeypatch):
    """Point plugin loader at a temp directory and reload for isolation."""
    monkeypatch.setattr(plugins, "PLUGINS_DIR", str(tmp_path))
    plugins.load_plugins()
    yield
    plugins.load_plugins()


def _write_plugin(tmp_path, filename, content):
    """Write a plugin file to the temp plugins directory."""
    path = tmp_path / filename
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestPluginDiscovery:
    def test_discovers_valid_plugin(self, tmp_path):
        _write_plugin(tmp_path, "good.py", '''
PLUGIN_NAME = "Good Plugin"
PLUGIN_DESCRIPTION = "A test plugin"
TOOLS = [{"name": "good_tool", "description": "Does good", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    return "good", False
''')
        plugins.load_plugins()
        names = [p["name"] for p in plugins.list_plugins()]
        assert "Good Plugin" in names

    def test_skips_invalid_plugin_without_crashing(self, tmp_path):
        _write_plugin(tmp_path, "bad.py", '''
PLUGIN_NAME = "Bad Plugin"
# Missing TOOLS and execute
''')
        plugins.load_plugins()
        assert len(plugins.list_plugins()) == 0
        errors = plugins.get_load_errors()
        assert len(errors) == 1
        assert "bad.py" in errors[0][0]

    def test_skips_underscore_files(self, tmp_path):
        _write_plugin(tmp_path, "_hidden.py", '''
PLUGIN_NAME = "Hidden"
TOOLS = []
def execute(n, i, c, h): pass
''')
        plugins.load_plugins()
        assert len(plugins.list_plugins()) == 0
        assert len(plugins.get_load_errors()) == 0

    def test_skips_non_python_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("not a plugin")
        plugins.load_plugins()
        assert len(plugins.list_plugins()) == 0

    def test_empty_directory(self, tmp_path):
        plugins.load_plugins()
        assert plugins.list_plugins() == []
        assert plugins.get_all_plugin_tools() == []


# ---------------------------------------------------------------------------
# Tool merging
# ---------------------------------------------------------------------------

class TestToolMerging:
    def test_plugin_tools_in_combined_list(self, tmp_path):
        _write_plugin(tmp_path, "toolplugin.py", '''
PLUGIN_NAME = "Tool Plugin"
PLUGIN_DESCRIPTION = "Has tools"
TOOLS = [
    {"name": "alpha_tool", "description": "Alpha", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "beta_tool", "description": "Beta", "input_schema": {"type": "object", "properties": {}, "required": []}},
]
def execute(tool_name, tool_input, config, history):
    return f"ran {tool_name}", False
''')
        plugins.load_plugins()
        all_tools = plugins.get_all_plugin_tools()
        tool_names = [t["name"] for t in all_tools]
        assert "alpha_tool" in tool_names
        assert "beta_tool" in tool_names

    def test_is_plugin_tool(self, tmp_path):
        _write_plugin(tmp_path, "checker.py", '''
PLUGIN_NAME = "Checker"
PLUGIN_DESCRIPTION = "Check"
TOOLS = [{"name": "check_tool", "description": "Check", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    return "ok", False
''')
        plugins.load_plugins()
        assert plugins.is_plugin_tool("check_tool")
        assert not plugins.is_plugin_tool("web_search")


# ---------------------------------------------------------------------------
# Execution routing
# ---------------------------------------------------------------------------

class TestExecution:
    def test_routes_to_correct_plugin(self, tmp_path):
        _write_plugin(tmp_path, "router.py", '''
PLUGIN_NAME = "Router"
PLUGIN_DESCRIPTION = "Routes"
TOOLS = [{"name": "routed_tool", "description": "Route", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    return f"routed:{tool_name}", False
''')
        plugins.load_plugins()
        result = plugins.execute_plugin_tool("routed_tool", {})
        assert result == ("routed:routed_tool", False)

    def test_returns_none_for_unknown_tool(self):
        result = plugins.execute_plugin_tool("nonexistent_tool", {})
        assert result is None

    def test_exception_in_execute_returns_error(self, tmp_path):
        _write_plugin(tmp_path, "crasher.py", '''
PLUGIN_NAME = "Crasher"
PLUGIN_DESCRIPTION = "Crashes"
TOOLS = [{"name": "crash_tool", "description": "Crash", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    raise RuntimeError("boom")
''')
        plugins.load_plugins()
        result = plugins.execute_plugin_tool("crash_tool", {})
        assert isinstance(result, tuple)
        assert result[1] is True  # is_error
        assert "boom" in result[0]

    def test_config_is_read_only_copy(self, tmp_path):
        _write_plugin(tmp_path, "mutator.py", '''
PLUGIN_NAME = "Mutator"
PLUGIN_DESCRIPTION = "Tries to mutate"
TOOLS = [{"name": "mutate_tool", "description": "Mutate", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    config["injected"] = True
    history.append({"role": "hacker"})
    return "mutated", False
''')
        plugins.load_plugins()
        original_config = {"key": "value"}
        original_history = [{"role": "user", "content": "hi"}]
        plugins.execute_plugin_tool("mutate_tool", {}, original_config, original_history)
        # Originals should be untouched
        assert "injected" not in original_config
        assert len(original_history) == 1


# ---------------------------------------------------------------------------
# Plugin info
# ---------------------------------------------------------------------------

class TestPluginInfo:
    def test_list_plugins_returns_info(self, tmp_path):
        _write_plugin(tmp_path, "info.py", '''
PLUGIN_NAME = "Info Plugin"
PLUGIN_DESCRIPTION = "Has info"
TOOLS = [{"name": "info_tool", "description": "Info", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    return "info", False
''')
        plugins.load_plugins()
        loaded = plugins.list_plugins()
        assert len(loaded) == 1
        p = loaded[0]
        assert p["name"] == "Info Plugin"
        assert p["description"] == "Has info"
        assert p["tool_count"] == 1

    def test_reload_picks_up_new_plugins(self, tmp_path):
        plugins.load_plugins()
        assert len(plugins.list_plugins()) == 0

        _write_plugin(tmp_path, "late.py", '''
PLUGIN_NAME = "Late Arrival"
PLUGIN_DESCRIPTION = "Added after initial load"
TOOLS = [{"name": "late_tool", "description": "Late", "input_schema": {"type": "object", "properties": {}, "required": []}}]
def execute(tool_name, tool_input, config, history):
    return "late", False
''')
        plugins.reload_plugins()
        assert len(plugins.list_plugins()) == 1
