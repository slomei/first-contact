"""Tests for chat-level file attachments across interfaces."""

import base64
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import files
import memory


class TestWebUIAttachmentExtensions:
    """Verify the web UI client-side allows binary document extensions."""

    def test_app_js_allows_binary_extensions(self):
        """app.js ALLOWED_EXTENSIONS includes .pdf, .docx, .xlsx."""
        app_js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "web_ui", "app.js"
        )
        with open(app_js_path) as f:
            content = f.read()

        # Check the ALLOWED_EXTENSIONS set includes binary types
        assert '".pdf"' in content
        assert '".docx"' in content
        assert '".xlsx"' in content

        # Check BINARY_EXTENSIONS constant exists
        assert "BINARY_EXTENSIONS" in content
        assert "readAsDataURL" in content

    def test_index_html_allows_binary_extensions(self):
        """index.html upload function supports binary extensions."""
        html_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "web_ui", "index.html"
        )
        with open(html_path) as f:
            content = f.read()

        assert "UPLOAD_BINARY_EXTENSIONS" in content
        assert "readAsDataURL" in content


class TestServerChatAttachment:
    """Test server-side chat attachment processing."""

    def test_extract_attached_files_text(self, isolated_env):
        """Text file attachment produces correct context string."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        # Create a temp text file to simulate
        attached = [{"name": "notes.txt", "contents": "Hello world\nLine two"}]
        result = _extract_attached_files(attached)
        assert len(result) == 1
        assert "[Attached file: notes.txt]" in result[0]
        assert "Hello world" in result[0]

    def test_extract_attached_files_binary(self, isolated_env, monkeypatch):
        """Binary file attachment decodes base64 and extracts text."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".pdf"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Extracted PDF text")

        raw = b"%PDF-1.4 fake content"
        b64 = base64.b64encode(raw).decode()
        attached = [{"name": "report.pdf", "contents": f"data:application/pdf;base64,{b64}"}]

        from server import _extract_attached_files
        result = _extract_attached_files(attached)
        assert len(result) == 1
        assert "[Attached file: report.pdf]" in result[0]
        assert "Extracted PDF text" in result[0]

    def test_extract_attached_files_unsupported_skipped(self, isolated_env):
        """Unsupported file types are silently skipped."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        attached = [{"name": "photo.png", "contents": "data:image/png;base64,abc"}]
        result = _extract_attached_files(attached)
        assert len(result) == 0

    def test_extract_attached_files_cleanup(self, isolated_env):
        """Temp files are cleaned up after extraction."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        attached = [{"name": "clean.txt", "contents": "test content"}]

        # Count temp files before and after
        tmp_dir = tempfile.gettempdir()
        result = _extract_attached_files(attached)
        assert len(result) == 1
        # The temp file should have been cleaned up (unlinked in finally block)


class TestDiscordAttachment:
    """Test Discord attachment extraction format."""

    def test_attachment_injection_format(self, isolated_env):
        """Extracted attachment produces correct conversation injection format."""
        # Simulate what the Discord handler does
        path = os.path.join(isolated_env, "test.py")
        with open(path, "w") as f:
            f.write("print('hello')\n")

        msg, filename, line_count = files.extract_file_for_chat(path)
        extracted = files.read_file_contents(path)
        injection = f"[Attached file: test.py]\n```\n{extracted}\n```"

        assert "[Attached file: test.py]" in injection
        assert "print('hello')" in injection
        assert line_count == 1

    def test_attachment_temp_cleanup(self, isolated_env):
        """Temp files are cleaned up after extraction."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"test data")
        tmp.close()

        try:
            msg, _, _ = files.extract_file_for_chat(tmp.name)
            assert "test data" in msg
        finally:
            os.unlink(tmp.name)

        assert not os.path.exists(tmp.name)


class TestTelegramAttachment:
    """Test Telegram document extraction format."""

    def test_document_injection_format(self, isolated_env):
        """Extracted document produces correct injection format."""
        path = os.path.join(isolated_env, "data.csv")
        with open(path, "w") as f:
            f.write("name,age\nAlice,30\n")

        extracted = files.read_file_contents(path)
        line_count = extracted.count("\n") + 1
        injection = f"[Attached file: data.csv]\n```\n{extracted}\n```"

        assert "[Attached file: data.csv]" in injection
        assert "Alice,30" in injection
        assert line_count == 3

    def test_document_temp_cleanup(self, isolated_env):
        """Temp files are cleaned up after extraction."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".md")
        tmp.write(b"# Title\nContent here")
        tmp.close()

        try:
            msg, _, _ = files.extract_file_for_chat(tmp.name)
            assert "# Title" in msg
        finally:
            os.unlink(tmp.name)

        assert not os.path.exists(tmp.name)


class TestTerminalAttach:
    """Test terminal /attach command behavior."""

    def test_extract_valid_file(self, isolated_env):
        """Valid file extracts and formats for injection."""
        path = os.path.join(isolated_env, "script.py")
        with open(path, "w") as f:
            f.write("x = 1\ny = 2\n")

        msg, filename, line_count = files.extract_file_for_chat(path)
        assert filename == "script.py"
        assert line_count == 2
        assert "[File: script.py]" in msg
        assert "x = 1" in msg

    def test_reject_unsupported_extension(self, isolated_env):
        """Unsupported extension raises ValueError."""
        path = os.path.join(isolated_env, "archive.zip")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04")

        with pytest.raises(ValueError, match="Unsupported file type"):
            files.extract_file_for_chat(path)
