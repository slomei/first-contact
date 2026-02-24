"""
Persistent user model — learns facts, preferences, patterns, and goals
from conversations over time.

Extraction happens post-conversation (fire-and-forget via background thread),
not per-turn. A separate daemon task does deeper pattern detection across
conversations, tasks, and memories.

Imports memory (base module). Lazy-imports models inside functions to avoid
circular deps.
"""

import json
import logging
import os
import uuid
from datetime import datetime

import memory

log = logging.getLogger("user_model")

PROFILE_FILE = os.path.join(memory.BASE_DIR, "user_profile.json")
MAX_ENTRIES = 100
VALID_CATEGORIES = {"facts", "preferences", "patterns", "goals"}

_EXTRACTION_SYSTEM_PROMPT = """You are extracting factual information about a user from their conversation.
Output 0-5 facts as lines in format: CATEGORY|CONFIDENCE|statement
Categories: facts, preferences, patterns, goals
Confidence: 0.0-1.0 (how certain this is true)
If nothing new, return exactly: NOTHING_NEW

Rules:
- Only extract concrete, specific information — not vague observations
- facts: name, job title, location, skills, tools, team, company, background
- preferences: communication style, scheduling, tools, workflows, food, media
- patterns: recurring behaviors, work habits, typical requests
- goals: stated objectives, career aims, project targets, things they want to accomplish
- Do NOT repeat anything already in the existing profile
- Confidence 0.9+ only for explicitly stated facts; 0.5-0.8 for inferred

Existing profile (avoid duplicates):
{existing}

Conversation:
{conversation}"""

_PATTERN_SYSTEM_PROMPT = """You are analyzing a user's data to detect behavioral patterns and goals that aren't captured in their existing profile.

Output 0-5 new entries as lines in format: CATEGORY|CONFIDENCE|statement
Categories: facts, preferences, patterns, goals
If nothing new, return exactly: NOTHING_NEW

Rules:
- Only surface patterns supported by concrete evidence in the data
- Look for: recurring themes across tasks, consistent preferences, unstated goals implied by actions
- Do NOT repeat anything already in the existing profile
- Confidence 0.7+ only for strong patterns; 0.5-0.6 for tentative ones

Existing profile:
{existing}

User data:
{data}"""


# --- Storage ---

def load_profile():
    """Load the user profile from disk. Returns empty list if missing."""
    if not os.path.exists(PROFILE_FILE):
        return []
    try:
        with open(PROFILE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, IOError):
        return []


def save_profile(entries):
    """Write profile entries to disk."""
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    with open(PROFILE_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def add_entry(category, text, confidence, source="conversation"):
    """Add a new entry to the profile. Returns the new entry dict."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    confidence = max(0.0, min(1.0, float(confidence)))

    entry = {
        "id": uuid.uuid4().hex[:12],
        "category": category,
        "text": text,
        "confidence": confidence,
        "source": source,
        "created": memory.local_now().isoformat(),
        "updated": memory.local_now().isoformat(),
        "supersedes": None,
    }

    entries = load_profile()
    entries.append(entry)
    entries = _deduplicate(entries)
    entries = _prune(entries)
    save_profile(entries)
    return entry


def remove_entry(entry_id):
    """Remove an entry by ID. Returns True if found and removed."""
    entries = load_profile()
    original_len = len(entries)
    entries = [e for e in entries if e.get("id") != entry_id]
    if len(entries) < original_len:
        save_profile(entries)
        return True
    return False


def update_entry(entry_id, **kwargs):
    """Update fields on an existing entry. Returns True if found."""
    entries = load_profile()
    for entry in entries:
        if entry.get("id") == entry_id:
            for k, v in kwargs.items():
                if k in ("category", "text", "confidence", "source", "supersedes"):
                    entry[k] = v
            entry["updated"] = memory.local_now().isoformat()
            save_profile(entries)
            return True
    return False


def clear_profile():
    """Remove all profile entries."""
    save_profile([])


def get_entries(category=None):
    """Get profile entries, optionally filtered by category."""
    entries = load_profile()
    if category:
        entries = [e for e in entries if e.get("category") == category]
    return entries


# --- Formatting ---

def format_for_prompt():
    """Format profile entries for system prompt injection.

    Returns empty string if disabled or no entries.
    """
    config = memory.load_config()
    if not config.get("user_model", {}).get("enabled", True):
        return ""

    entries = load_profile()
    if not entries:
        return ""

    # Group by category
    groups = {}
    for e in entries:
        cat = e.get("category", "facts")
        groups.setdefault(cat, []).append(e)

    lines = ["Learned user profile:"]
    category_order = ["facts", "preferences", "patterns", "goals"]
    labels = {"facts": "Facts", "preferences": "Preferences", "patterns": "Patterns", "goals": "Goals"}

    for cat in category_order:
        items = groups.get(cat, [])
        if not items:
            continue
        # Sort by confidence descending
        items.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        lines.append(f"  {labels[cat]}:")
        for item in items:
            lines.append(f"    - {item['text']}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


# --- Deduplication & Pruning ---

def _deduplicate(entries):
    """Merge near-duplicate entries, keeping the highest confidence version.

    Two entries are considered duplicates if they share a category and their
    text is identical after lowering and stripping.
    """
    seen = {}  # (category, normalized_text) -> index
    result = []

    for entry in entries:
        key = (entry.get("category", ""), entry.get("text", "").strip().lower())
        if key in seen:
            existing = result[seen[key]]
            # Keep the higher-confidence version
            if entry.get("confidence", 0) > existing.get("confidence", 0):
                entry["supersedes"] = existing.get("id")
                result[seen[key]] = entry
        else:
            seen[key] = len(result)
            result.append(entry)

    return result


def _prune(entries):
    """Enforce MAX_ENTRIES cap by removing oldest low-confidence entries."""
    if len(entries) <= MAX_ENTRIES:
        return entries

    # Sort: high confidence first, then by recency
    entries.sort(key=lambda e: (e.get("confidence", 0), e.get("updated", "")), reverse=True)
    return entries[:MAX_ENTRIES]


# --- Extraction ---

def _build_conversation_text(history, max_exchanges=10):
    """Extract text from the last N exchanges of conversation history."""
    import models

    # Take last max_exchanges*2 messages (user + assistant pairs)
    recent = history[-(max_exchanges * 2):]
    lines = []
    for msg in recent:
        role = msg.get("role", "unknown")
        text = models.extract_text_from_message(msg)
        if text:
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {text[:500]}")  # Cap per-message length

    return "\n".join(lines)


def extract_from_conversation(history):
    """Extract user facts from conversation history.

    Called post-conversation. Makes one fast-tier API call.
    Returns number of entries added.
    """
    import models

    conversation_text = _build_conversation_text(history)
    if not conversation_text.strip():
        return 0

    existing = load_profile()
    existing_text = "\n".join(f"- [{e['category']}] {e['text']}" for e in existing) or "(empty)"

    prompt = _EXTRACTION_SYSTEM_PROMPT.format(
        existing=existing_text,
        conversation=conversation_text,
    )

    try:
        model = models.get_tier("fast")
        response = models.get_client().messages.create(
            model=model,
            max_tokens=500,
            system=prompt,
            messages=[{"role": "user", "content": "Extract any new user facts from this conversation."}],
        )
        models.track_usage(
            response.usage.input_tokens,
            response.usage.output_tokens,
            model,
        )

        response_text = response.content[0].text.strip()
        if response_text == "NOTHING_NEW":
            return 0

        return _parse_and_add_entries(response_text, source="conversation")
    except Exception as e:
        log.error("Extraction failed: %s", e)
        return 0


def _parse_and_add_entries(response_text, source="conversation"):
    """Parse CATEGORY|CONFIDENCE|statement lines and add entries.

    Returns count of entries added.
    """
    entries = load_profile()
    count = 0

    for line in response_text.strip().splitlines():
        line = line.strip()
        if not line or line == "NOTHING_NEW":
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue

        category = parts[0].strip().lower()
        if category not in VALID_CATEGORIES:
            continue

        try:
            confidence = float(parts[1].strip())
        except ValueError:
            continue

        text = parts[2].strip()
        if not text:
            continue

        confidence = max(0.0, min(1.0, confidence))

        entry = {
            "id": uuid.uuid4().hex[:12],
            "category": category,
            "text": text,
            "confidence": confidence,
            "source": source,
            "created": memory.local_now().isoformat(),
            "updated": memory.local_now().isoformat(),
            "supersedes": None,
        }
        entries.append(entry)
        count += 1

    if count:
        entries = _deduplicate(entries)
        entries = _prune(entries)
        save_profile(entries)

    return count


# --- Pattern Detection ---

def detect_patterns():
    """Analyze user data for behavioral patterns.

    Called by daemon (24hr interval). Returns (count_added, cost).
    """
    import models
    import tasks as task_mod

    config = memory.load_config()
    if not config.get("user_model", {}).get("pattern_detection_enabled", True):
        return (0, 0)

    existing = load_profile()
    existing_text = "\n".join(f"- [{e['category']}] {e['text']}" for e in existing) or "(empty)"

    # Gather data
    data_parts = []

    # Tasks from all projects
    try:
        open_tasks = task_mod.get_all_project_tasks(filter_status="open")
        if open_tasks:
            lines = ["## Open Tasks"]
            for t in open_tasks:
                desc = t.get("description", "")
                project = t.get("project", "")
                tag = f"[{project}] " if project else ""
                lines.append(f"- {tag}{desc}")
            data_parts.append("\n".join(lines))
    except Exception:
        pass

    # Recent memories
    try:
        global_mems = memory.load_global_memories()
        if global_mems:
            lines = ["## Global Memories"]
            for m in global_mems[-20:]:
                lines.append(f"- {m}")
            data_parts.append("\n".join(lines))
    except Exception:
        pass

    if not data_parts and not existing:
        return (0, 0)

    data_text = "\n\n".join(data_parts) if data_parts else "(no additional data)"

    prompt = _PATTERN_SYSTEM_PROMPT.format(
        existing=existing_text,
        data=data_text,
    )

    try:
        model = models.get_tier("standard")
        response = models.get_client().messages.create(
            model=model,
            max_tokens=500,
            system=prompt,
            messages=[{"role": "user", "content": "Analyze the user data for behavioral patterns."}],
        )
        cost = models.track_usage(
            response.usage.input_tokens,
            response.usage.output_tokens,
            model,
        )

        response_text = response.content[0].text.strip()
        if response_text == "NOTHING_NEW":
            return (0, cost)

        count = _parse_and_add_entries(response_text, source="pattern_detection")
        return (count, cost)
    except Exception as e:
        log.error("Pattern detection failed: %s", e)
        return (0, 0)


# --- Fire-and-forget wrapper ---

def maybe_extract(history):
    """Fire-and-forget extraction in background thread. Never blocks caller."""
    import threading

    config = memory.load_config()
    if not config.get("user_model", {}).get("extraction_enabled", True):
        return

    if len(history) < 4:
        return

    # Copy history to avoid race conditions
    history_copy = list(history)
    t = threading.Thread(target=extract_from_conversation, args=(history_copy,), daemon=True)
    t.start()
