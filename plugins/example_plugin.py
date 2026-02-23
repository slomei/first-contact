"""
Example plugin — dice roll tool.

This file demonstrates the plugin pattern for First Contact. Drop any .py file
into the plugins/ directory with the required attributes below, and it will be
auto-discovered and loaded on startup.

Required attributes:
    PLUGIN_NAME (str)        — Human-readable name
    PLUGIN_DESCRIPTION (str) — What the plugin does
    TOOLS (list)             — Tool definitions (same schema as tools.py)
    execute(tool_name, tool_input, config, conversation_history) — Handler
"""

import random

# --- Required: Plugin metadata ---

PLUGIN_NAME = "Dice Roller"
PLUGIN_DESCRIPTION = "Roll dice with standard RPG notation (e.g. 2d6, 1d20+5)"

# --- Required: Tool definitions ---
# Same schema as tools.py TOOLS list — name, description, input_schema.

TOOLS = [
    {
        "name": "roll_dice",
        "description": "Roll dice using standard notation (e.g. 2d6, 1d20+5).",
        "input_schema": {
            "type": "object",
            "properties": {
                "notation": {
                    "type": "string",
                    "description": "Dice notation like '2d6', '1d20+5', '4d8-2'",
                },
            },
            "required": ["notation"],
        },
    },
]


# --- Required: Execute function ---
# Called when any tool defined in TOOLS is invoked.
# Returns (result_string, is_error).
#
# Parameters:
#   tool_name  — which tool was called (useful if your plugin defines multiple)
#   tool_input — dict of parameters from the model
#   config     — read-only copy of the user's config.json
#   conversation_history — read-only copy of the current conversation

def execute(tool_name, tool_input, config, conversation_history):
    if tool_name == "roll_dice":
        return _roll_dice(tool_input)
    return f"Unknown tool: {tool_name}", True


def _roll_dice(tool_input):
    """Parse dice notation and roll."""
    notation = tool_input.get("notation", "1d6").strip().lower()

    # Parse NdS+M format
    import re
    match = re.match(r'^(\d+)d(\d+)([+-]\d+)?$', notation)
    if not match:
        return f"Invalid dice notation: '{notation}'. Use format like 2d6, 1d20+5, 4d8-2.", True

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count < 1 or count > 100:
        return "Roll 1-100 dice at a time.", True
    if sides < 2 or sides > 1000:
        return "Dice must have 2-1000 sides.", True

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    # Format result
    parts = [f"Rolling {notation}:"]
    if count <= 20:
        parts.append(f"  Rolls: {rolls}")
    if modifier:
        parts.append(f"  Sum: {sum(rolls)} {'+' if modifier > 0 else ''}{modifier} = {total}")
    else:
        parts.append(f"  Total: {total}")

    return "\n".join(parts), False
