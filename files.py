"""
Project file management — import, list, remove, and inject files into conversations.

Shared core module. All interfaces call these functions and format output themselves.
"""

import base64
import os
import shutil

import memory
import parsers

# Temp attachment store — maps display name to {path, is_temp}
_temp_attachments = {}

BINARY_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}


def store_temp_attachment(name, path, is_temp=True):
    """Register a file for later binary retrieval via save_attachment."""
    _temp_attachments[name] = {"path": path, "is_temp": is_temp}


def get_temp_attachment(name):
    """Get file path for a named attachment, or None."""
    entry = _temp_attachments.get(name)
    if entry and os.path.isfile(entry["path"]):
        return entry["path"]
    return None


def list_temp_attachments():
    """Return names of available temp attachments."""
    return [n for n, e in _temp_attachments.items() if os.path.isfile(e["path"])]


def save_temp_attachment(name, dest_dir="files"):
    """Copy a temp attachment to project files/ or workspace/. Returns dest path or None."""
    entry = _temp_attachments.get(name)
    if not entry or not os.path.isfile(entry["path"]):
        return None
    if dest_dir == "workspace":
        dest = os.path.join(memory.get_workspace_dir(), name)
    else:
        dest = os.path.join(memory.get_files_dir(), name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(entry["path"], dest)
    if entry["is_temp"]:
        try:
            os.unlink(entry["path"])
        except OSError:
            pass
    del _temp_attachments[name]
    return dest


def cleanup_temp_attachments():
    """Remove all temp attachment files and clear the store."""
    for name, entry in list(_temp_attachments.items()):
        if entry["is_temp"]:
            try:
                os.unlink(entry["path"])
            except OSError:
                pass
    _temp_attachments.clear()


ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".css",
    ".yml", ".yaml", ".toml", ".cfg", ".log", ".xml", ".sh", ".bat",
    ".sql", ".r", ".dart", ".pdf", ".docx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Max image size for chat attachments (5MB)
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# Files larger than this get a warning before injection
LARGE_FILE_THRESHOLD = 50 * 1024  # 50 KB


def validate_extension(filename):
    """Check if a filename has an allowed extension.

    Returns (ok, ext) where ext is the lowercase extension including dot.
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    return ext in ALLOWED_EXTENSIONS, ext


def is_image_file(filepath):
    """True if the file extension is a supported image format."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in IMAGE_EXTENSIONS


def encode_image_for_api(filepath):
    """Encode an image file as an Anthropic API image content block.

    Returns {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}.
    Raises ValueError if file is too large or unsupported format.
    """
    _, ext = os.path.splitext(filepath)
    ext = ext.lower()
    media_type = IMAGE_MEDIA_TYPES.get(ext)
    if not media_type:
        raise ValueError(f"Unsupported image format: {ext}")

    size = os.path.getsize(filepath)
    if size > MAX_IMAGE_SIZE:
        raise ValueError(f"Image too large ({size // 1024}KB). Maximum: {MAX_IMAGE_SIZE // (1024 * 1024)}MB")

    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        },
    }


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

    # Image files — binary, validated by extension only
    if is_image_file(filepath):
        size = os.path.getsize(filepath)
        if size > MAX_IMAGE_SIZE:
            return False, f"Image too large ({size // 1024}KB). Maximum: {MAX_IMAGE_SIZE // (1024 * 1024)}MB"
        return True, None

    # Binary document formats — validate via extraction
    if parsers.is_binary_document(filepath):
        try:
            text = parsers.extract_text(filepath)
            return True, None
        except ImportError as e:
            return False, str(e)
        except (ValueError, Exception) as e:
            return False, str(e)

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
    """Read and return the text contents of a file.

    Binary document formats (PDF, DOCX, XLSX) are extracted to plain text.
    """
    if parsers.is_binary_document(filepath):
        return parsers.extract_text(filepath)
    with open(filepath, "r") as f:
        return f.read()


def format_file_for_injection(filepath, contents, preserved=False):
    """Format file contents for conversation history injection.

    Returns (message_str, filename, line_count).
    If preserved=True, adds a note that the original binary is available via save_attachment.
    """
    filename = os.path.basename(filepath)
    line_count = contents.count("\n") + (1 if contents and not contents.endswith("\n") else 0)
    tag = f"[File: {filename}]"
    if preserved:
        tag += " (original binary attached — use save_attachment to save)"
    message = f"{tag}\n```\n{contents}\n```"
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


def write_binary_file_contents(filename, raw_bytes):
    """Write binary bytes to a file in the project files/ directory.

    Used by the web upload path for PDF/DOCX/XLSX files.
    Returns the destination path.
    """
    files_dir = memory.get_files_dir()
    filepath = os.path.join(files_dir, filename)
    with open(filepath, "wb") as f:
        f.write(raw_bytes)
    return filepath


def extract_file_for_chat(filepath):
    """Extract file content for temporary chat injection (not persisted).

    Returns (formatted_message, filename, line_count) or raises ValueError.
    Validates extension and reads content (binary files routed through parsers).
    """
    ok, ext = validate_extension(os.path.basename(filepath))
    if not ok:
        raise ValueError(f"Unsupported file type: {ext or '(no extension)'}")

    contents = read_file_contents(filepath)
    return format_file_for_injection(filepath, contents)
