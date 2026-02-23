"""Tests for the files module — project file management."""

import os

import pytest

import files
import memory


class TestValidateExtension:
    def test_allowed_extensions(self):
        for ext in [".py", ".md", ".txt", ".json", ".csv", ".html", ".yaml"]:
            ok, got_ext = files.validate_extension(f"test{ext}")
            assert ok, f"{ext} should be allowed"
            assert got_ext == ext

    def test_blocked_extensions(self):
        for ext in [".exe", ".zip", ".png", ".pdf", ".dll", ".so"]:
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
