"""Tests for tools.py — tool definitions, execute_tool, path restrictions."""

import os

import tools
import memory


def test_tools_list_non_empty():
    assert len(tools.TOOLS) > 0


def test_every_tool_has_required_fields():
    for tool in tools.TOOLS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool {tool.get('name')} missing 'description'"
        assert "input_schema" in tool, f"Tool {tool.get('name')} missing 'input_schema'"


def test_tool_status_text_returns_string():
    result = tools.tool_status_text("web_search", {"query": "test"})
    assert isinstance(result, str)
    assert "test" in result


def test_tool_status_text_unknown_tool():
    result = tools.tool_status_text("nonexistent_tool", {})
    assert isinstance(result, str)


def test_read_file_allowed_inside_base_dir(isolated_env):
    """read_file should work for files inside BASE_DIR."""
    test_file = os.path.join(isolated_env, "test_readable.txt")
    with open(test_file, "w") as f:
        f.write("hello from test")

    result, is_error = tools.execute_tool("read_file", {"path": test_file})
    assert not is_error
    assert "hello from test" in result


def test_read_file_blocked_etc_passwd():
    """read_file should deny /etc/passwd."""
    result, is_error = tools.execute_tool("read_file", {"path": "/etc/passwd"})
    assert is_error
    assert "Access denied" in result


def test_read_file_blocked_ssh_key():
    """read_file should deny ~/.ssh/id_rsa."""
    result, is_error = tools.execute_tool("read_file", {"path": "~/.ssh/id_rsa"})
    assert is_error
    assert "Access denied" in result


def test_read_file_blocked_dotfile():
    """read_file should deny paths containing dotfiles."""
    result, is_error = tools.execute_tool("read_file", {"path": "/home/user/.bashrc"})
    assert is_error
    assert "Access denied" in result


def test_read_file_blocked_traversal(isolated_env):
    """read_file should deny path traversal outside BASE_DIR."""
    traversal_path = os.path.join(isolated_env, "..", "..", "etc", "passwd")
    result, is_error = tools.execute_tool("read_file", {"path": traversal_path})
    assert is_error
    assert "Access denied" in result


def test_tool_descriptions_are_concise():
    """Tool descriptions should not contain behavioral guidance phrases."""
    for tool in tools.TOOLS:
        desc = tool["description"].lower()
        assert "use this when" not in desc, (
            f"Tool '{tool['name']}' has verbose description: {tool['description']}"
        )
        assert "use when" not in desc, (
            f"Tool '{tool['name']}' has verbose description: {tool['description']}"
        )
