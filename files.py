"""
Project file management — import, list, remove, and inject files into conversations.

Shared core module. All interfaces call these functions and format output themselves.
"""

import os
import shutil

import memory

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".css",
    ".yml", ".yaml", ".toml", ".cfg", ".log", ".xml", ".sh", ".bat",
    ".sql", ".r", ".dart",
}

# Files larger than this get a warning before injection
LARGE_FILE_THRESHOLD = 50 * 1024  # 50 KB


def validate_extension(filename):
    """Check if a filename has an allowed extension.

    Returns (ok, ext) where ext is the lowercase extension including dot.
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    return ext in ALLOWED_EXTENSIONS, ext


def resolve_file_path(path_or_name):
    """Resolve a path — check project files/ first, then filesystem.

    Returns (resolved_path, in_project) where in_project is True if found
    in the project files/ directory.
    """
    # Check project files/ first (bare filename or relative path)
    files_dir = memory.get_files_dir()
    candidate = os.path.join(files_dir, os.path.basename(path_or_name))
    if os.path.isfile(candidate):
        return candidate, True

    # Then check the literal path
    expanded = os.path.expanduser(path_or_name)
    if os.path.isfile(expanded):
        return os.path.abspath(expanded), False

    return None, False


def check_file_importable(filepath):
    """Validate that a file can be imported.

    Returns (ok, error_message). error_message is None when ok is True.
    """
    if not os.path.exists(filepath):
        return False, f"File not found: {filepath}"

    if os.path.isdir(filepath):
        return False, f"Path is a directory: {filepath}"

    ok, ext = validate_extension(os.path.basename(filepath))
    if not ok:
        return False, f"Unsupported file type: {ext or '(no extension)'}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    # Check it's readable as text
    try:
        with open(filepath, "r") as f:
            f.read(1024)
    except UnicodeDecodeError:
        return False, f"Cannot read binary file: {filepath}"
    except PermissionError:
        return False, f"Permission denied: {filepath}"

    return True, None


def file_is_large(filepath):
    """Return True if the file exceeds LARGE_FILE_THRESHOLD."""
    try:
        return os.path.getsize(filepath) > LARGE_FILE_THRESHOLD
    except OSError:
        return False


def file_exists_in_project(filename):
    """Check if a file with this name already exists in the project files/ dir."""
    return os.path.isfile(os.path.join(memory.get_files_dir(), filename))


def import_file(source_path):
    """Copy a file into the project files/ directory.

    Returns the destination path.
    """
    files_dir = memory.get_files_dir()
    dest = os.path.join(files_dir, os.path.basename(source_path))
    shutil.copy2(source_path, dest)
    return dest


def read_file_contents(filepath):
    """Read and return the text contents of a file."""
    with open(filepath, "r") as f:
        return f.read()


def format_file_for_injection(filepath, contents):
    """Format file contents for conversation history injection.

    Returns (message_str, filename, line_count).
    """
    filename = os.path.basename(filepath)
    line_count = contents.count("\n") + (1 if contents and not contents.endswith("\n") else 0)
    message = f"[File: {filename}]\n```\n{contents}\n```"
    return message, filename, line_count


def list_project_files():
    """List files in the project files/ directory.

    Returns list of dicts with name, size, modified, path — sorted newest first.
    """
    files_dir = memory.get_files_dir()
    result = []
    try:
        entries = os.listdir(files_dir)
    except OSError:
        return result

    for name in entries:
        path = os.path.join(files_dir, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        result.append({
            "name": name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "path": path,
        })

    result.sort(key=lambda f: f["modified"], reverse=True)
    return result


def format_file_size(size_bytes):
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def remove_file(filename):
    """Remove a file from the project files/ directory.

    Returns (ok, message).
    """
    filepath = os.path.join(memory.get_files_dir(), filename)
    if not os.path.isfile(filepath):
        return False, f"File not found: {filename}"
    os.remove(filepath)
    return True, f"Removed {filename}"


def clear_all_files():
    """Remove all files from the project files/ directory.

    Returns (count, message).
    """
    files_dir = memory.get_files_dir()
    count = 0
    try:
        for name in os.listdir(files_dir):
            path = os.path.join(files_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                count += 1
    except OSError:
        pass
    if count == 0:
        return 0, "No files to remove."
    return count, f"Removed {count} file{'s' if count != 1 else ''}."


def write_file_contents(filename, contents):
    """Write text contents to a file in the project files/ directory.

    Used by the web upload path. Returns the destination path.
    """
    files_dir = memory.get_files_dir()
    filepath = os.path.join(files_dir, filename)
    with open(filepath, "w") as f:
        f.write(contents)
    return filepath
