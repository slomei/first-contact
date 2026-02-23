"""
Extensible skills system for specialist agents.

Loads .md skill files from the skills/ directory and injects matched
skill content into specialist system prompts during delegation.
"""

import os
import re

import memory

# --- Optional YAML support ---
try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    yaml = None
    _YAML_AVAILABLE = False

SKILLS_DIR = os.path.join(memory.BASE_DIR, "skills")

BUILTIN_SKILLS = {
    "cover_letter.md",
    "research.md",
    "code_review.md",
    "email_draft.md",
    "job_analysis.md",
    "researcher_base.md",
    "writer_base.md",
    "coder_base.md",
    "analyst_base.md",
}

# Lazy-loaded cache: {filename_stem: {name, description, specialist, model_preference, keywords, content, is_builtin}}
_skills_cache = {}
_loaded = False


def _parse_front_matter(text):
    """Parse YAML front matter from a skill file.

    Returns (metadata_dict, body_text). Falls back to regex parsing
    if yaml is not installed.
    """
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
    if not match:
        return {}, text

    front_raw = match.group(1)
    body = match.group(2)

    if _YAML_AVAILABLE:
        try:
            metadata = yaml.safe_load(front_raw) or {}
        except Exception:
            metadata = {}
    else:
        # Regex fallback for basic key: value and list items
        metadata = {}
        current_key = None
        current_list = None
        for line in front_raw.split('\n'):
            list_match = re.match(r'^\s+-\s+(.+)', line)
            if list_match and current_key:
                if current_list is None:
                    current_list = []
                current_list.append(list_match.group(1).strip())
                metadata[current_key] = current_list
                continue
            kv_match = re.match(r'^(\w+)\s*:\s*(.+)', line)
            if kv_match:
                if current_list is not None:
                    current_list = None
                current_key = kv_match.group(1)
                metadata[current_key] = kv_match.group(2).strip()
            elif re.match(r'^(\w+)\s*:\s*$', line):
                current_key = re.match(r'^(\w+)', line).group(1)
                current_list = []
                metadata[current_key] = current_list

    return metadata, body


def _load_skills():
    """Scan the skills directory and populate the cache."""
    global _skills_cache, _loaded
    _skills_cache = {}

    if not os.path.isdir(SKILLS_DIR):
        _loaded = True
        return

    for filename in os.listdir(SKILLS_DIR):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(SKILLS_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        except (OSError, IOError):
            continue

        metadata, body = _parse_front_matter(text)
        stem = filename[:-3]  # remove .md

        keywords = metadata.get('trigger_keywords', [])
        if isinstance(keywords, str):
            keywords = [keywords]

        default_val = metadata.get('default', False)
        if isinstance(default_val, str):
            default_val = default_val.lower() in ('true', 'yes', '1')

        _skills_cache[stem] = {
            'name': metadata.get('name', stem),
            'description': metadata.get('description', ''),
            'specialist': metadata.get('specialist', ''),
            'model_preference': metadata.get('model_preference', ''),
            'keywords': keywords,
            'content': body.strip(),
            'is_builtin': filename in BUILTIN_SKILLS,
            'default': bool(default_val),
        }

    _loaded = True


def _ensure_loaded():
    """Load skills if not already loaded."""
    if not _loaded:
        _load_skills()


def reload_skills():
    """Force re-scan of the skills directory."""
    global _loaded
    _loaded = False
    _load_skills()


def get_skill(name):
    """Get the full content of a skill by name. Returns string or None."""
    _ensure_loaded()
    skill = _skills_cache.get(name)
    if skill:
        return skill['content']
    return None


def list_skills():
    """List all loaded skills.

    Returns list of {name, description, specialist, is_builtin}.
    """
    _ensure_loaded()
    return [
        {
            'name': s['name'],
            'description': s['description'],
            'specialist': s['specialist'],
            'is_builtin': s['is_builtin'],
        }
        for s in _skills_cache.values()
    ]


def match_skill(user_message, specialist_name=None):
    """Find the best matching skill for a user message.

    Counts keyword hits in the message. If specialist_name is given,
    only skills for that specialist are considered.

    Returns the best matching skill dict or None.
    """
    _ensure_loaded()
    msg_lower = user_message.lower()
    best = None
    best_hits = 0

    for stem, skill in _skills_cache.items():
        # Filter by specialist if specified
        if specialist_name and skill['specialist'] and skill['specialist'] != specialist_name:
            continue

        hits = 0
        for kw in skill['keywords']:
            if kw.lower() in msg_lower:
                hits += 1

        if hits > best_hits:
            best_hits = hits
            best = skill

    return best if best_hits > 0 else None


def get_default_skill(specialist_name):
    """Return the default base skill for a specialist, or None."""
    _ensure_loaded()
    for skill in _skills_cache.values():
        if skill.get('default') and skill['specialist'] == specialist_name:
            return skill
    return None
