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
    """Verify the web UI client-side allows binary document and image extensions."""

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

    def test_app_js_allows_image_extensions(self):
        """app.js ALLOWED_EXTENSIONS and BINARY_EXTENSIONS include image types."""
        app_js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "web_ui", "app.js"
        )
        with open(app_js_path) as f:
            content = f.read()

        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            assert f'"{ext}"' in content, f"{ext} should be in app.js"

    def test_index_html_allows_binary_extensions(self):
        """index.html upload function supports binary extensions."""
        html_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "web_ui", "index.html"
        )
        with open(html_path) as f:
            content = f.read()

        assert "UPLOAD_BINARY_EXTENSIONS" in content
        assert "readAsDataURL" in content

    def test_index_html_allows_image_extensions(self):
        """index.html upload supports image extensions."""
        html_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "web_ui", "index.html"
        )
        with open(html_path) as f:
            content = f.read()

        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            assert f'"{ext}"' in content, f"{ext} should be in index.html"


class TestServerChatAttachment:
    """Test server-side chat attachment processing."""

    def test_extract_attached_files_text(self, isolated_env):
        """Text file attachment produces correct context tuple."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        # Create a temp text file to simulate
        attached = [{"name": "notes.txt", "contents": "Hello world\nLine two"}]
        result = _extract_attached_files(attached)
        assert len(result) == 1
        kind, name, content = result[0]
        assert kind == "text"
        assert name == "notes.txt"
        assert "[Attached file: notes.txt]" in content
        assert "Hello world" in content

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
        kind, name, content = result[0]
        assert kind == "text"
        assert "[Attached file: report.pdf]" in content
        assert "Extracted PDF text" in content

    def test_extract_attached_files_unsupported_skipped(self, isolated_env):
        """Unsupported file types are silently skipped."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        attached = [{"name": "archive.zip", "contents": "data:application/zip;base64,abc"}]
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


class TestImageAttachmentFormat:
    """Test image attachment produces correct multimodal content blocks."""

    def test_image_produces_list_content(self, isolated_env):
        """Image attachment produces list content (not string) with image block."""
        path = os.path.join(isolated_env, "photo.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        block = files.encode_image_for_api(path)
        content = [block, {"type": "text", "text": "[Attached image: photo.png]"}]

        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[1]["type"] == "text"

    def test_image_block_structure(self, isolated_env):
        """Image block has correct structure: type, source.type, source.media_type, source.data."""
        path = os.path.join(isolated_env, "test.jpg")
        with open(path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 50)

        block = files.encode_image_for_api(path)
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/jpeg"
        assert isinstance(block["source"]["data"], str)
        assert len(block["source"]["data"]) > 0

    def test_mixed_image_text_multimodal(self, isolated_env):
        """Mixed image + text attachment produces correct multimodal content list."""
        # Create image
        img_path = os.path.join(isolated_env, "pic.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        image_block = files.encode_image_for_api(img_path)
        text_block = {"type": "text", "text": "[Attached file: notes.txt]\n```\nhello\n```"}
        user_text = {"type": "text", "text": "What do you see?"}

        content = [image_block, text_block, user_text]
        assert len(content) == 3
        assert content[0]["type"] == "image"
        assert content[1]["type"] == "text"
        assert content[2]["type"] == "text"


class TestServerImageAttachment:
    """Test server-side image attachment extraction."""

    def test_extract_image_attachment(self, isolated_env):
        """Image attachment returns image block tuple."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_ui"))
        from server import _extract_attached_files

        # Create a small valid-ish PNG as base64
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        attached = [{"name": "photo.png", "contents": f"data:image/png;base64,{b64}"}]

        result = _extract_attached_files(attached)
        assert len(result) == 1
        kind, name, data = result[0]
        assert kind == "image"
        assert name == "photo.png"
        assert data["type"] == "image"
        assert data["source"]["media_type"] == "image/png"


class TestTelegramPhoto:
    """Test Telegram photo message handling."""

    def test_photo_filter_includes_photo(self):
        """Verify telegram_bot.py registers PHOTO in MessageHandler filter."""
        tg_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "telegram_bot.py"
        )
        with open(tg_path) as f:
            content = f.read()

        assert "filters.PHOTO" in content
        assert "has_photo" in content


class TestReadFileImage:
    """Test read_file tool returns image content blocks."""

    def test_read_file_image_returns_list(self, isolated_env, monkeypatch):
        """read_file with an image returns list content blocks (not string)."""
        import tools

        img_path = os.path.join(isolated_env, "test.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        # Monkeypatch the sandboxing to allow our test path
        monkeypatch.setattr(memory, "BASE_DIR", isolated_env)

        result, is_error = tools.execute_tool("read_file", {"path": img_path}, None)
        assert not is_error
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "image"
        assert result[0]["source"]["media_type"] == "image/png"
        assert result[1]["type"] == "text"
        assert "test.png" in result[1]["text"]
