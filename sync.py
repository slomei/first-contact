"""
File sync system for keeping project files in sync with Windows source paths.

Reads sync_sources.json for source/destination mappings. Scans Windows paths
via glob, resolves version conflicts, and copies the latest file.

Imports memory (base module). No circular dependencies.
"""

import glob
import json
import os
import re
import shutil
from datetime import datetime

import memory


SYNC_CONFIG = os.path.join(memory.BASE_DIR, "sync_sources.json")


def load_sources():
    """Load sync source mappings from sync_sources.json."""
    if not os.path.exists(SYNC_CONFIG):
        return {}
    with open(SYNC_CONFIG, "r") as f:
        return json.load(f)


def _extract_version(filename, pattern):
    """Extract version number from a filename using the pattern.

    The pattern uses {version} as a placeholder for the version number.
    Returns the version as an integer, or None if no match.
    """
    # Convert pattern to regex: escape dots, replace {version} with capture group
    regex = re.escape(pattern).replace(r"\{version\}", r"(\d+)")
    match = re.search(regex, filename)
    if match:
        return int(match.group(1))
    return None


def _scan_source(source_glob):
    """Scan a glob pattern and return list of (filepath, version, mtime) tuples."""
    files = glob.glob(source_glob)
    return files


def get_latest(key, prompt_fn=None):
    """Get the latest version of a synced file.

    Scans the Windows source path, determines the latest version, syncs it
    to the destination, and returns the path to the synced file.

    prompt_fn(message, choices) -> int: callback to ask the user to pick
    from a numbered list. Returns 0-based index. None means auto-pick.

    Returns (dest_path, synced) where synced is True if a new copy was made,
    False if the destination was already up to date. Returns None if no
    source files were found.
    """
    sources = load_sources()
    if key not in sources:
        return None

    config = sources[key]
    source_glob = config["source"]
    destination = os.path.join(memory.BASE_DIR, config["destination"])
    pattern = config["pattern"]

    # Scan source files
    source_files = glob.glob(source_glob)
    if not source_files:
        return None

    # Extract version and mtime for each file
    candidates = []
    for filepath in source_files:
        filename = os.path.basename(filepath)
        version = _extract_version(filename, pattern)
        if version is None:
            continue
        mtime = os.path.getmtime(filepath)
        candidates.append({
            "path": filepath,
            "filename": filename,
            "version": version,
            "mtime": mtime,
            "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
        })

    if not candidates:
        return None

    # Sort by version descending
    candidates.sort(key=lambda c: c["version"], reverse=True)

    chosen = None

    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        highest_version = candidates[0]
        newest_by_date = max(candidates, key=lambda c: c["mtime"])

        # Check for conflicts
        has_conflict = False

        # Conflict: highest version is not the newest by date
        if highest_version["path"] != newest_by_date["path"]:
            has_conflict = True

        # Conflict: multiple files with same highest version
        same_version = [c for c in candidates if c["version"] == highest_version["version"]]
        if len(same_version) > 1:
            has_conflict = True

        if has_conflict and prompt_fn is not None:
            # Show user a list and ask which to use
            lines = []
            for i, c in enumerate(candidates, 1):
                lines.append(f"  {i}. v{c['version']}  ({c['date']})  {c['filename']}")
            message = "Multiple versions found — which one should I use?\n" + "\n".join(lines)
            idx = prompt_fn(message, len(candidates))
            if idx is not None and 0 <= idx < len(candidates):
                chosen = candidates[idx]
            else:
                chosen = highest_version
        else:
            chosen = highest_version

    if chosen is None:
        return None

    # Check if destination already has this exact file
    dest_path = os.path.join(destination, chosen["filename"])
    if os.path.exists(dest_path):
        dest_mtime = os.path.getmtime(dest_path)
        # Same filename and same modification time — already up to date
        if int(dest_mtime) == int(chosen["mtime"]):
            return (dest_path, False)

    # Ensure destination directory exists
    os.makedirs(destination, exist_ok=True)

    # Remove old files matching the pattern in destination
    dest_pattern = pattern.replace("{version}", "*")
    for old_file in glob.glob(os.path.join(destination, dest_pattern)):
        os.remove(old_file)

    # Copy the chosen file to destination
    shutil.copy2(chosen["path"], dest_path)

    return (dest_path, True)


def sync_status(key):
    """Check sync status for a key without syncing.

    Returns a dict with source info, or None if key not found.
    """
    sources = load_sources()
    if key not in sources:
        return None

    config = sources[key]
    source_glob = config["source"]
    destination = os.path.join(memory.BASE_DIR, config["destination"])
    pattern = config["pattern"]

    source_files = glob.glob(source_glob)
    candidates = []
    for filepath in source_files:
        filename = os.path.basename(filepath)
        version = _extract_version(filename, pattern)
        if version is not None:
            mtime = os.path.getmtime(filepath)
            candidates.append({
                "version": version,
                "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                "filename": filename,
            })

    # Check what's currently in destination
    dest_pattern = pattern.replace("{version}", "*")
    current_files = glob.glob(os.path.join(destination, dest_pattern))
    current = None
    if current_files:
        current_name = os.path.basename(current_files[0])
        current_version = _extract_version(current_name, pattern)
        current = {"filename": current_name, "version": current_version}

    return {
        "key": key,
        "source_count": len(candidates),
        "candidates": sorted(candidates, key=lambda c: c["version"], reverse=True),
        "current": current,
    }


def sync_all(prompt_fn=None, progress_fn=None):
    """Sync all configured sources.

    Returns list of (key, result) tuples where result is the return value
    of get_latest: (dest_path, synced) or None.
    """
    sources = load_sources()
    results = []
    for key in sources:
        if progress_fn:
            progress_fn(f"Syncing {key}...")
        dest = get_latest(key, prompt_fn=prompt_fn)
        results.append((key, dest))
    return results
