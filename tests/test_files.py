"""Tests for the files module — project file management."""

import os
import shutil
from unittest.mock import MagicMock, patch

import pytest

import files
import memory


class TestValidateExtension:
    def test_allowed_extensions(self):
        for ext in [".py", ".md", ".txt", ".json", ".csv", ".html", ".yaml",
                    ".pdf", ".docx", ".xlsx"]:
            ok, got_ext = files.validate_extension(f"test{ext}")
            assert ok, f"{ext} should be allowed"
            assert got_ext == ext

    def test_blocked_extensions(self):
        for ext in [".exe", ".zip", ".dll", ".so"]:
            ok, got_ext = files.validate_extension(f"test{ext}")
            assert not ok, f"{ext} should be blocked"
            assert got_ext == ext

    def test_no_extension(self):
        ok, ext = files.validate_extension("Makefile")
        assert not ok
        assert ext == ""

    def test_case_insensitive(self):
        ok, ext = files.validate_extension("README.MD")
        assert ok
        assert ext == ".md"


class TestCheckFileImportable:
    def test_valid_file(self, isolated_env):
        path = os.path.join(isolated_env, "test.py")
        with open(path, "w") as f:
            f.write("print('hello')")
        ok, err = files.check_file_importable(path)
        assert ok
        assert err is None

    def test_binary_file(self, isolated_env):
        path = os.path.join(isolated_env, "test.py")
        with open(path, "wb") as f:
            f.write(b"\x00\x01\x02\xff\xfe" * 100)
        ok, err = files.check_file_importable(path)
        assert not ok
        assert "binary" in err.lower()

    def test_bad_extension(self, isolated_env):
        path = os.path.join(isolated_env, "test.exe")
        with open(path, "w") as f:
            f.write("not really an exe")
        ok, err = files.check_file_importable(path)
        assert not ok
        assert ".exe" in err

    def test_not_found(self):
        ok, err = files.check_file_importable("/nonexistent/file.py")
        assert not ok
        assert "not found" in err.lower()

    def test_directory(self, isolated_env):
        ok, err = files.check_file_importable(isolated_env)
        assert not ok
        assert "directory" in err.lower()


class TestImportAndList:
    def test_import_and_list_roundtrip(self, isolated_env):
        # Create a source file
        src = os.path.join(isolated_env, "source.py")
        with open(src, "w") as f:
            f.write("x = 1\n")

        dest = files.import_file(src)
        assert os.path.isfile(dest)
        assert os.path.basename(dest) == "source.py"
        assert memory.get_files_dir() in dest

        listing = files.list_project_files()
        assert len(listing) == 1
        assert listing[0]["name"] == "source.py"
        assert listing[0]["size"] > 0

    def test_list_empty(self, isolated_env):
        listing = files.list_project_files()
        assert listing == []


class TestFileExistsInProject:
    def test_exists(self, isolated_env):
        path = os.path.join(memory.get_files_dir(), "test.md")
        with open(path, "w") as f:
            f.write("# Hello")
        assert files.file_exists_in_project("test.md")

    def test_not_exists(self, isolated_env):
        assert not files.file_exists_in_project("nope.md")


class TestRemoveFile:
    def test_remove_success(self, isolated_env):
        path = os.path.join(memory.get_files_dir(), "removeme.txt")
        with open(path, "w") as f:
            f.write("bye")
        ok, msg = files.remove_file("removeme.txt")
        assert ok
        assert "Removed" in msg
        assert not os.path.exists(path)

    def test_remove_not_found(self, isolated_env):
        ok, msg = files.remove_file("ghost.txt")
        assert not ok
        assert "not found" in msg.lower()


class TestClearAllFiles:
    def test_clear_populated(self, isolated_env):
        files_dir = memory.get_files_dir()
        for name in ["a.txt", "b.py", "c.md"]:
            with open(os.path.join(files_dir, name), "w") as f:
                f.write("data")
        count, msg = files.clear_all_files()
        assert count == 3
        assert "3 files" in msg
        assert os.listdir(files_dir) == []

    def test_clear_empty(self, isolated_env):
        count, msg = files.clear_all_files()
        assert count == 0
        assert "No files" in msg


class TestLargeFileDetection:
    def test_large(self, isolated_env):
        path = os.path.join(isolated_env, "big.txt")
        with open(path, "w") as f:
            f.write("x" * (files.LARGE_FILE_THRESHOLD + 1))
        assert files.file_is_large(path)

    def test_small(self, isolated_env):
        path = os.path.join(isolated_env, "small.txt")
        with open(path, "w") as f:
            f.write("tiny")
        assert not files.file_is_large(path)


class TestResolveFilePath:
    def test_project_first(self, isolated_env):
        # Put a file in project files/
        files_dir = memory.get_files_dir()
        with open(os.path.join(files_dir, "config.json"), "w") as f:
            f.write("{}")

        path, in_project = files.resolve_file_path("config.json")
        assert in_project
        assert path == os.path.join(files_dir, "config.json")

    def test_filesystem_fallback(self, isolated_env):
        # Create file outside project files/
        src = os.path.join(isolated_env, "outside.py")
        with open(src, "w") as f:
            f.write("pass")

        path, in_project = files.resolve_file_path(src)
        assert not in_project
        assert path == os.path.abspath(src)

    def test_not_found(self, isolated_env):
        path, in_project = files.resolve_file_path("nonexistent.py")
        assert path is None
        assert not in_project


class TestFormatFileForInjection:
    def test_format(self):
        msg, name, lines = files.format_file_for_injection("/a/b/test.py", "line1\nline2\n")
        assert name == "test.py"
        assert lines == 2
        assert "[File: test.py]" in msg
        assert "line1\nline2\n" in msg


class TestFormatFileSize:
    def test_bytes(self):
        assert files.format_file_size(500) == "500 B"

    def test_kilobytes(self):
        result = files.format_file_size(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = files.format_file_size(2 * 1024 * 1024)
        assert "MB" in result


class TestBinaryDocumentParsing:
    """Test binary document (PDF, DOCX, XLSX) import and read paths."""

    def test_pdf_importable(self, isolated_env, monkeypatch):
        """PDF passes import check when extraction succeeds."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".pdf"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Extracted PDF text")

        path = os.path.join(isolated_env, "report.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 fake pdf content")

        ok, err = files.check_file_importable(path)
        assert ok
        assert err is None

    def test_docx_importable(self, isolated_env, monkeypatch):
        """DOCX passes import check when extraction succeeds."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".docx"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Extracted DOCX text")

        path = os.path.join(isolated_env, "letter.docx")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 fake docx")

        ok, err = files.check_file_importable(path)
        assert ok
        assert err is None

    def test_xlsx_importable(self, isolated_env, monkeypatch):
        """XLSX passes import check when extraction succeeds."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".xlsx"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Col1\tCol2\nA\tB")

        path = os.path.join(isolated_env, "data.xlsx")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 fake xlsx")

        ok, err = files.check_file_importable(path)
        assert ok
        assert err is None

    def test_binary_extraction_failure_blocks_import(self, isolated_env, monkeypatch):
        """Failed extraction returns clear error and blocks import."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".pdf"))
        monkeypatch.setattr(parsers, "extract_text",
                            lambda p: (_ for _ in ()).throw(ValueError("Could not extract text from bad.pdf")))

        path = os.path.join(isolated_env, "bad.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 corrupt")

        ok, err = files.check_file_importable(path)
        assert not ok
        assert "Could not extract text" in err

    def test_missing_library_blocks_import(self, isolated_env, monkeypatch):
        """Missing library returns install instructions."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".pdf"))
        monkeypatch.setattr(parsers, "extract_text",
                            lambda p: (_ for _ in ()).throw(ImportError("pdfplumber is required")))

        path = os.path.join(isolated_env, "report.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4")

        ok, err = files.check_file_importable(path)
        assert not ok
        assert "pdfplumber" in err

    def test_read_file_contents_binary(self, isolated_env, monkeypatch):
        """read_file_contents routes binary docs through extraction."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".pdf"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Page 1 text\n\nPage 2 text")

        path = os.path.join(isolated_env, "doc.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 content")

        result = files.read_file_contents(path)
        assert "Page 1 text" in result
        assert "Page 2 text" in result

    def test_read_file_contents_text_unchanged(self, isolated_env):
        """Text files still read normally through read_file_contents."""
        path = os.path.join(isolated_env, "plain.txt")
        with open(path, "w") as f:
            f.write("hello world")

        result = files.read_file_contents(path)
        assert result == "hello world"


class TestWriteBinaryFileContents:
    def test_writes_bytes(self, isolated_env):
        data = b"\x00\x01\x02\xff\xfe"
        filepath = files.write_binary_file_contents("test.pdf", data)
        assert os.path.isfile(filepath)
        with open(filepath, "rb") as f:
            assert f.read() == data

    def test_path_in_project(self, isolated_env):
        filepath = files.write_binary_file_contents("doc.docx", b"PK\x03\x04")
        assert memory.get_files_dir() in filepath
        assert os.path.basename(filepath) == "doc.docx"


class TestExtractFileForChat:
    def test_text_file(self, isolated_env):
        path = os.path.join(isolated_env, "readme.txt")
        with open(path, "w") as f:
            f.write("Hello world\nLine two\n")
        msg, filename, line_count = files.extract_file_for_chat(path)
        assert filename == "readme.txt"
        assert line_count == 2
        assert "[File: readme.txt]" in msg
        assert "Hello world" in msg

    def test_unsupported_extension(self, isolated_env):
        path = os.path.join(isolated_env, "data.exe")
        with open(path, "w") as f:
            f.write("nope")
        with pytest.raises(ValueError, match="Unsupported file type"):
            files.extract_file_for_chat(path)

    def test_binary_file(self, isolated_env, monkeypatch):
        """Binary files route through parsers for extraction."""
        import parsers
        monkeypatch.setattr(parsers, "is_binary_document", lambda p: p.endswith(".docx"))
        monkeypatch.setattr(parsers, "extract_text", lambda p: "Extracted DOCX content")

        path = os.path.join(isolated_env, "letter.docx")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 fake docx")

        msg, filename, line_count = files.extract_file_for_chat(path)
        assert filename == "letter.docx"
        assert "Extracted DOCX content" in msg


class TestParsersModule:
    """Test parsers.py directly."""

    def test_is_binary_document(self):
        import parsers
        assert parsers.is_binary_document("report.pdf")
        assert parsers.is_binary_document("LETTER.DOCX")
        assert parsers.is_binary_document("data.xlsx")
        assert not parsers.is_binary_document("code.py")
        assert not parsers.is_binary_document("notes.txt")

    def test_extract_text_unsupported_format(self):
        import parsers
        with pytest.raises(ValueError, match="Unsupported binary format"):
            parsers.extract_text("file.zip")

    def test_pdf_extraction(self, isolated_env, monkeypatch):
        """PDF extraction joins pages with double newlines."""
        import parsers

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(parsers, "pdfplumber", MagicMock())
        parsers.pdfplumber.open.return_value = mock_pdf

        path = os.path.join(isolated_env, "test.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF")

        result = parsers.extract_text(path)
        assert "Page one content" in result
        assert "Page two content" in result
        assert "\n\n" in result

    def test_docx_extraction(self, isolated_env, monkeypatch):
        """DOCX extraction joins paragraphs with double newlines."""
        import parsers

        mock_para1 = MagicMock()
        mock_para1.text = "First paragraph"
        mock_para2 = MagicMock()
        mock_para2.text = "Second paragraph"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para2]

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_doc
        monkeypatch.setattr(parsers, "_docx", mock_docx_module)

        path = os.path.join(isolated_env, "test.docx")
        with open(path, "wb") as f:
            f.write(b"PK")

        result = parsers.extract_text(path)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_xlsx_extraction(self, isolated_env, monkeypatch):
        """XLSX extraction formats as tab-separated rows."""
        import parsers

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [("Name", "Age"), ("Alice", 30)]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = lambda s, k: mock_ws

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb
        monkeypatch.setattr(parsers, "openpyxl", mock_openpyxl)

        path = os.path.join(isolated_env, "test.xlsx")
        with open(path, "wb") as f:
            f.write(b"PK")

        result = parsers.extract_text(path)
        assert "Name\tAge" in result
        assert "Alice\t30" in result

    def test_empty_pdf_raises(self, isolated_env, monkeypatch):
        """Empty extraction raises ValueError."""
        import parsers

        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(parsers, "pdfplumber", MagicMock())
        parsers.pdfplumber.open.return_value = mock_pdf

        path = os.path.join(isolated_env, "empty.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF")

        with pytest.raises(ValueError, match="Could not extract text"):
            parsers.extract_text(path)

    def test_missing_pdfplumber_raises(self, monkeypatch):
        """Missing pdfplumber gives clear install instructions."""
        import parsers
        monkeypatch.setattr(parsers, "pdfplumber", None)

        with pytest.raises(ImportError, match="pdfplumber"):
            parsers.extract_text("test.pdf")

    def test_missing_docx_raises(self, monkeypatch):
        """Missing python-docx gives clear install instructions."""
        import parsers
        monkeypatch.setattr(parsers, "_docx", None)

        with pytest.raises(ImportError, match="python-docx"):
            parsers.extract_text("test.docx")

    def test_missing_openpyxl_raises(self, monkeypatch):
        """Missing openpyxl gives clear install instructions."""
        import parsers
        monkeypatch.setattr(parsers, "openpyxl", None)

        with pytest.raises(ImportError, match="openpyxl"):
            parsers.extract_text("test.xlsx")


class TestImageFile:
    """Test image file detection and encoding."""

    def test_is_image_file_positive(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            assert files.is_image_file(f"photo{ext}"), f"{ext} should be detected as image"

    def test_is_image_file_negative(self):
        for ext in [".py", ".txt", ".pdf", ".docx", ".html"]:
            assert not files.is_image_file(f"file{ext}"), f"{ext} should not be detected as image"

    def test_encode_image_for_api(self, isolated_env):
        """Encoding returns valid API block with correct media type."""
        path = os.path.join(isolated_env, "test.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        block = files.encode_image_for_api(path)
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        assert len(block["source"]["data"]) > 0

    def test_encode_image_rejects_oversized(self, isolated_env):
        """Files exceeding MAX_IMAGE_SIZE are rejected."""
        path = os.path.join(isolated_env, "huge.jpg")
        with open(path, "wb") as f:
            f.write(b"\xff" * (files.MAX_IMAGE_SIZE + 1))

        with pytest.raises(ValueError, match="too large"):
            files.encode_image_for_api(path)

    def test_image_extensions_in_allowed(self):
        """All image extensions are in ALLOWED_EXTENSIONS."""
        for ext in files.IMAGE_EXTENSIONS:
            assert ext in files.ALLOWED_EXTENSIONS, f"{ext} should be in ALLOWED_EXTENSIONS"

    def test_check_importable_image(self, isolated_env):
        """Image files pass import check."""
        path = os.path.join(isolated_env, "photo.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        ok, err = files.check_file_importable(path)
        assert ok
        assert err is None

    def test_check_importable_oversized_image(self, isolated_env):
        """Oversized images fail import check."""
        path = os.path.join(isolated_env, "huge.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG" + b"\x00" * (files.MAX_IMAGE_SIZE + 1))

        ok, err = files.check_file_importable(path)
        assert not ok
        assert "too large" in err.lower()


class TestTempAttachments:
    """Tests for binary attachment preservation (temp attachment store)."""

    def setup_method(self):
        """Clear temp attachments before each test."""
        files._temp_attachments.clear()

    def teardown_method(self):
        """Clean up any leftover temp files."""
        files.cleanup_temp_attachments()

    def test_store_and_get(self, isolated_env):
        """store_temp_attachment registers a file, get_temp_attachment retrieves it."""
        path = os.path.join(isolated_env, "test.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 content")
        files.store_temp_attachment("test.pdf", path)
        assert files.get_temp_attachment("test.pdf") == path

    def test_get_missing(self):
        """get_temp_attachment returns None for unregistered names."""
        assert files.get_temp_attachment("nonexistent.pdf") is None

    def test_get_deleted_file(self, isolated_env):
        """get_temp_attachment returns None if the file was deleted from disk."""
        path = os.path.join(isolated_env, "gone.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF")
        files.store_temp_attachment("gone.pdf", path)
        os.unlink(path)
        assert files.get_temp_attachment("gone.pdf") is None

    def test_list_temp_attachments(self, isolated_env):
        """list_temp_attachments returns names of files that exist on disk."""
        p1 = os.path.join(isolated_env, "a.pdf")
        p2 = os.path.join(isolated_env, "b.png")
        for p in [p1, p2]:
            with open(p, "wb") as f:
                f.write(b"data")
        files.store_temp_attachment("a.pdf", p1)
        files.store_temp_attachment("b.png", p2)
        result = files.list_temp_attachments()
        assert "a.pdf" in result
        assert "b.png" in result

    def test_save_temp_attachment_to_files(self, isolated_env):
        """save_temp_attachment copies to project files/ directory."""
        src = os.path.join(isolated_env, "report.pdf")
        with open(src, "wb") as f:
            f.write(b"%PDF-1.4 report data")
        files.store_temp_attachment("report.pdf", src, is_temp=True)

        dest = files.save_temp_attachment("report.pdf", "files")
        assert dest is not None
        assert os.path.isfile(dest)
        assert memory.get_files_dir() in dest
        with open(dest, "rb") as f:
            assert f.read() == b"%PDF-1.4 report data"
        # Temp source should be deleted
        assert not os.path.isfile(src)
        # Should be removed from store
        assert "report.pdf" not in files._temp_attachments

    def test_save_temp_attachment_to_workspace(self, isolated_env):
        """save_temp_attachment copies to project workspace/ directory."""
        src = os.path.join(isolated_env, "data.xlsx")
        with open(src, "wb") as f:
            f.write(b"PK\x03\x04 xlsx data")
        files.store_temp_attachment("data.xlsx", src, is_temp=True)

        dest = files.save_temp_attachment("data.xlsx", "workspace")
        assert dest is not None
        assert os.path.isfile(dest)
        assert memory.get_workspace_dir() in dest

    def test_save_preserves_permanent_source(self, isolated_env):
        """save_temp_attachment with is_temp=False does not delete the original."""
        src = os.path.join(isolated_env, "photo.png")
        with open(src, "wb") as f:
            f.write(b"\x89PNG image data")
        files.store_temp_attachment("photo.png", src, is_temp=False)

        dest = files.save_temp_attachment("photo.png", "files")
        assert dest is not None
        assert os.path.isfile(dest)
        # Original should still exist
        assert os.path.isfile(src)

    def test_save_nonexistent_returns_none(self):
        """save_temp_attachment returns None for unknown filenames."""
        result = files.save_temp_attachment("ghost.pdf")
        assert result is None

    def test_cleanup_removes_temp_only(self, isolated_env):
        """cleanup_temp_attachments removes temp files but not permanent ones."""
        temp_path = os.path.join(isolated_env, "temp.pdf")
        perm_path = os.path.join(isolated_env, "perm.png")
        for p in [temp_path, perm_path]:
            with open(p, "wb") as f:
                f.write(b"data")
        files.store_temp_attachment("temp.pdf", temp_path, is_temp=True)
        files.store_temp_attachment("perm.png", perm_path, is_temp=False)

        files.cleanup_temp_attachments()
        assert not os.path.isfile(temp_path)
        assert os.path.isfile(perm_path)
        assert len(files._temp_attachments) == 0

    def test_binary_attachment_extensions(self):
        """BINARY_ATTACHMENT_EXTENSIONS contains expected formats."""
        for ext in [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            assert ext in files.BINARY_ATTACHMENT_EXTENSIONS

    def test_format_file_for_injection_preserved(self):
        """format_file_for_injection with preserved=True includes save note."""
        msg, name, lines = files.format_file_for_injection(
            "/a/b/report.pdf", "Extracted text content", preserved=True
        )
        assert "save_attachment" in msg
        assert "original binary attached" in msg
        assert name == "report.pdf"

    def test_format_file_for_injection_not_preserved(self):
        """format_file_for_injection without preserved flag has no save note."""
        msg, name, lines = files.format_file_for_injection(
            "/a/b/readme.txt", "Hello world"
        )
        assert "save_attachment" not in msg
        assert "original binary attached" not in msg
