"""Tests for the files module — project file management."""

import os
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
        for ext in [".exe", ".zip", ".png", ".dll", ".so"]:
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
