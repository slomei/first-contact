"""
Creative tools for the First Light project.

Parses the world bible PDF, extracts and indexes characters and locations
using Haiku for structured extraction. Provides lookup functions.

Imports memory (base module). Lazy-imports models inside functions that
call the API to avoid circular dependencies.
"""

import json
import os
import re
try:
    import pdfplumber
except ImportError:
    pdfplumber = None
from difflib import get_close_matches

import memory


FIRST_LIGHT_PROJECT = "first-light"


def _get_project_dir():
    """Return the first-light project directory."""
    return os.path.join(memory.PROJECTS_DIR, FIRST_LIGHT_PROJECT)


def get_bible_path():
    """Return the path to the current world bible PDF, or None."""
    bible_dir = os.path.join(_get_project_dir(), "bible")
    if not os.path.exists(bible_dir):
        return None
    # Find the first PDF matching the bible pattern
    for f in sorted(os.listdir(bible_dir), reverse=True):
        if f.startswith("First_Light_World_Bible_v") and f.endswith(".pdf"):
            return os.path.join(bible_dir, f)
    return None


def get_characters_path():
    """Return path to characters.json."""
    return os.path.join(_get_project_dir(), "characters.json")


def get_locations_path():
    """Return path to locations.json."""
    return os.path.join(_get_project_dir(), "locations.json")


def extract_bible_text(bible_path=None):
    """Extract all text from the world bible PDF.

    Returns a list of (page_number, text) tuples.
    """
    if bible_path is None:
        bible_path = get_bible_path()
    if bible_path is None or not os.path.exists(bible_path):
        return []
    if pdfplumber is None:
        return []

    pages = []
    with pdfplumber.open(bible_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((i, text))
    return pages


def _extract_characters_via_haiku(bible_text):
    """Send bible text to Haiku and extract character data as structured JSON."""
    import models

    prompt = (
        "You are extracting character data from a sci-fi world bible document.\n\n"
        "Extract ALL named characters from this text. For each character, return:\n"
        "- name: Their full name (include nickname in quotes if given)\n"
        "- role: Their role/title in the story\n"
        "- description: 2-3 sentence summary of who they are\n"
        "- key_traits: List of 3-5 defining personality traits\n"
        "- relationships: List of key relationships (format: 'Name - relationship')\n"
        "- first_appearance_section: Which section of the bible they first appear in\n\n"
        "Return ONLY valid JSON — an array of character objects. No markdown, no explanation.\n\n"
        "World Bible Text:\n\n" + bible_text
    )

    fast_model = models.get_tier("fast")
    response = models.get_client().messages.create(
        model=fast_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    cost = models.track_usage(
        response.usage.input_tokens,
        response.usage.output_tokens,
        fast_model,
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    try:
        characters = json.loads(text)
    except json.JSONDecodeError:
        characters = []

    return characters, cost


def _extract_locations_via_haiku(bible_text):
    """Send bible text to Haiku and extract location data as structured JSON."""
    import models

    prompt = (
        "You are extracting location data from a sci-fi world bible document.\n\n"
        "Extract ALL named locations from this text. For each location, return:\n"
        "- name: The location name\n"
        "- description: 2-3 sentence summary of the location\n"
        "- rules_physics: Any special rules, physics, or technology specific to this location\n"
        "- significance: Why this location matters to the story\n"
        "- first_appearance_section: Which section of the bible it first appears in\n\n"
        "Return ONLY valid JSON — an array of location objects. No markdown, no explanation.\n\n"
        "World Bible Text:\n\n" + bible_text
    )

    fast_model = models.get_tier("fast")
    response = models.get_client().messages.create(
        model=fast_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    cost = models.track_usage(
        response.usage.input_tokens,
        response.usage.output_tokens,
        fast_model,
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    try:
        locations = json.loads(text)
    except json.JSONDecodeError:
        locations = []

    return locations, cost


def rebuild_indexes(bible_path=None, progress_fn=None):
    """Parse the bible and rebuild characters.json and locations.json.

    progress_fn(msg): callback for status updates.
    Returns (characters_count, locations_count, total_cost) or None on failure.
    """
    if bible_path is None:
        bible_path = get_bible_path()
    if bible_path is None:
        return None

    if progress_fn:
        progress_fn("Extracting text from world bible...")

    pages = extract_bible_text(bible_path)
    if not pages:
        return None

    # Combine all text
    full_text = "\n\n".join(text for _, text in pages)
    total_cost = 0.0

    # Extract characters
    if progress_fn:
        progress_fn("Extracting characters via Haiku...")
    characters, char_cost = _extract_characters_via_haiku(full_text)
    total_cost += char_cost

    # Extract locations
    if progress_fn:
        progress_fn("Extracting locations via Haiku...")
    locations, loc_cost = _extract_locations_via_haiku(full_text)
    total_cost += loc_cost

    # Save indexes
    project_dir = _get_project_dir()
    os.makedirs(project_dir, exist_ok=True)

    char_path = get_characters_path()
    with open(char_path, "w") as f:
        json.dump(characters, f, indent=2)

    loc_path = get_locations_path()
    with open(loc_path, "w") as f:
        json.dump(locations, f, indent=2)

    if progress_fn:
        progress_fn(f"Indexed {len(characters)} characters and {len(locations)} locations.")

    return (len(characters), len(locations), total_cost)


def load_characters():
    """Load characters from the index. Returns list of character dicts."""
    path = get_characters_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    return []


def load_locations():
    """Load locations from the index. Returns list of location dicts."""
    path = get_locations_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    return []


def find_character(name):
    """Fuzzy-match a character by name. Returns the character dict or None."""
    characters = load_characters()
    if not characters:
        return None

    # Build name lookup
    names = [c["name"] for c in characters]
    name_lower = name.lower()

    # Exact match first
    for c in characters:
        if c["name"].lower() == name_lower:
            return c

    # Partial match (name contains query or query contains name part)
    for c in characters:
        c_name = c["name"].lower()
        # Check if query matches any part of the name
        name_parts = re.split(r'[\s"()]+', c_name)
        for part in name_parts:
            if part and (part == name_lower or name_lower in part or part in name_lower):
                return c

    # Fuzzy match via difflib
    matches = get_close_matches(name_lower, [n.lower() for n in names], n=1, cutoff=0.5)
    if matches:
        for c in characters:
            if c["name"].lower() == matches[0]:
                return c

    return None


def find_location(name):
    """Fuzzy-match a location by name. Returns the location dict or None."""
    locations = load_locations()
    if not locations:
        return None

    name_lower = name.lower()

    # Exact match first
    for loc in locations:
        if loc["name"].lower() == name_lower:
            return loc

    # Partial match
    for loc in locations:
        loc_name = loc["name"].lower()
        name_parts = re.split(r'[\s\-]+', loc_name)
        for part in name_parts:
            if part and (part == name_lower or name_lower in part or part in name_lower):
                return loc

    # Fuzzy match
    loc_names = [loc["name"] for loc in locations]
    matches = get_close_matches(name_lower, [n.lower() for n in loc_names], n=1, cutoff=0.5)
    if matches:
        for loc in locations:
            if loc["name"].lower() == matches[0]:
                return loc

    return None


def format_character(char):
    """Format a character dict for display."""
    lines = [f"  {char['name']}"]
    if char.get("role"):
        lines.append(f"  Role: {char['role']}")
    if char.get("description"):
        lines.append(f"  {char['description']}")
    if char.get("key_traits"):
        traits = ", ".join(char["key_traits"])
        lines.append(f"  Traits: {traits}")
    if char.get("relationships"):
        lines.append("  Relationships:")
        for rel in char["relationships"]:
            lines.append(f"    - {rel}")
    if char.get("first_appearance_section"):
        lines.append(f"  First appears: {char['first_appearance_section']}")
    return "\n".join(lines)


def format_location(loc):
    """Format a location dict for display."""
    lines = [f"  {loc['name']}"]
    if loc.get("description"):
        lines.append(f"  {loc['description']}")
    if loc.get("rules_physics"):
        lines.append(f"  Physics/Rules: {loc['rules_physics']}")
    if loc.get("significance"):
        lines.append(f"  Significance: {loc['significance']}")
    if loc.get("first_appearance_section"):
        lines.append(f"  First appears: {loc['first_appearance_section']}")
    return "\n".join(lines)


def get_creative_context(character_names=None, location_names=None):
    """Build context string for injecting into system prompt during creative work.

    Loads specified characters and locations (or all if None) and returns
    a formatted block suitable for system prompt injection.
    """
    parts = []

    characters = load_characters()
    locations = load_locations()

    if characters:
        if character_names:
            chars = [c for c in characters if any(
                n.lower() in c["name"].lower() for n in character_names
            )]
        else:
            chars = characters
        if chars:
            parts.append("FIRST LIGHT — Characters in this scene:")
            for c in chars:
                parts.append(format_character(c))

    if locations:
        if location_names:
            locs = [l for l in locations if any(
                n.lower() in l["name"].lower() for n in location_names
            )]
        else:
            locs = locations
        if locs:
            parts.append("\nFIRST LIGHT — Locations in this scene:")
            for l in locs:
                parts.append(format_location(l))

    return "\n".join(parts) if parts else ""
