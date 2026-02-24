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


def test_get_cached_tools():
    """get_cached_tools adds cache_control to last tool without mutating TOOLS."""
    cached = tools.get_cached_tools()
    # Last tool has cache_control
    assert "cache_control" in cached[-1]
    assert cached[-1]["cache_control"] == {"type": "ephemeral"}
    # Other tools don't
    for t in cached[:-1]:
        assert "cache_control" not in t
    # Original TOOLS not mutated
    for t in tools.TOOLS:
        assert "cache_control" not in t


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


def test_save_attachment_in_tools():
    """save_attachment tool exists in TOOLS list with correct schema."""
    tool = next((t for t in tools.TOOLS if t["name"] == "save_attachment"), None)
    assert tool is not None, "save_attachment tool not found in TOOLS"
    assert "filename" in tool["input_schema"]["properties"]
    assert "destination" in tool["input_schema"]["properties"]
    assert "filename" in tool["input_schema"]["required"]


def test_tool_count():
    """TOOLS list has 28 core tools."""
    assert len(tools.TOOLS) == 28


def test_save_attachment_status_text():
    """save_attachment has a status text entry."""
    result = tools.tool_status_text("save_attachment", {"filename": "report.pdf"})
    assert "report.pdf" in result


def test_save_attachment_no_filename(isolated_env):
    """save_attachment returns error when filename is empty."""
    result, is_error = tools.execute_tool("save_attachment", {"filename": ""})
    assert is_error
    assert "required" in result.lower()


def test_save_attachment_no_attachments(isolated_env):
    """save_attachment returns error when no attachments available."""
    import files
    files._temp_attachments.clear()
    result, is_error = tools.execute_tool("save_attachment", {"filename": "test.pdf"})
    assert is_error
    assert "No attachments available" in result


def test_save_attachment_success(isolated_env):
    """save_attachment copies file to project files/ directory."""
    import files
    files._temp_attachments.clear()

    src = os.path.join(isolated_env, "report.pdf")
    with open(src, "wb") as f:
        f.write(b"%PDF-1.4 test content")
    files.store_temp_attachment("report.pdf", src, is_temp=True)

    result, is_error = tools.execute_tool("save_attachment", {"filename": "report.pdf"})
    assert not is_error
    assert "Saved" in result
    assert "report.pdf" in result
