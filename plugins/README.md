# First Contact Plugins

Plugins let you add new tools to First Contact without modifying core code. Each plugin is a single Python file in this directory.

## Quick Start

1. Create a `.py` file in `plugins/` (e.g. `my_plugin.py`)
2. Define the required attributes (see below)
3. Restart First Contact or run `/plugins reload`
4. Your tools are now available to the agent

## Required Attributes

Every plugin file must define these four things:

```python
# Human-readable name
PLUGIN_NAME = "My Plugin"

# What the plugin does
PLUGIN_DESCRIPTION = "Adds a custom tool that does X"

# Tool definitions — same schema as tools.py
TOOLS = [
    {
        "name": "my_tool",
        "description": "Does something useful.",
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {"type": "string"},
            },
            "required": ["param"],
        },
    },
]

# Handler function — called when any of your tools are invoked
def execute(tool_name, tool_input, config, conversation_history):
    """
    Parameters:
        tool_name (str): Which tool was called
        tool_input (dict): Parameters from the model
        config (dict): Read-only copy of config.json
        conversation_history (list): Read-only copy of conversation

    Returns:
        (result_string, is_error) tuple
    """
    if tool_name == "my_tool":
        return f"Result: {tool_input['param']}", False
    return f"Unknown tool: {tool_name}", True
```

## Rules

- **File naming:** Any `.py` file works. Files starting with `_` are skipped.
- **Tool names:** Must be unique across all plugins and core tools. Conflicts will cause unpredictable routing.
- **No core access:** Plugins receive read-only copies of config and conversation history. They cannot modify core state.
- **Error isolation:** If your plugin raises an exception, it returns an error to the agent without crashing First Contact.
- **No subprocess isolation:** Plugins run in the same Python process. Don't load untrusted code.

## Available Commands

- `/plugins` — list installed plugins with name, description, and tool count
- `/plugins reload` — re-scan the directory and reload all plugins

## Example

See `example_plugin.py` for a complete working example (dice roller).
