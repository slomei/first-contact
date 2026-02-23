"""
Plugin loader — discovers and loads user-installable tool packages.

Scans the plugins/ directory for .py files, validates they have the required
attributes (PLUGIN_NAME, TOOLS, execute), and provides a unified interface
for the core to query and execute plugin tools.

Plugins cannot modify core state. They receive read-only copies of config
and conversation history when their execute() function is called.
"""

import copy
import importlib
import logging
import os
import sys

log = logging.getLogger("plugins")

# Internal state
_plugins = {}       # {module_name: module}
_tool_map = {}      # {tool_name: module}  — routes tool calls to the right plugin
_load_errors = []   # [(filename, error_string)]

REQUIRED_ATTRS = ("PLUGIN_NAME", "TOOLS", "execute")

PLUGINS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_plugins():
    """Scan plugins/ directory and import valid plugin modules.

    Skips __init__.py and files starting with _.
    Bad plugins log a warning but don't crash the system.
    """
    _plugins.clear()
    _tool_map.clear()
    _load_errors.clear()

    if not os.path.isdir(PLUGINS_DIR):
        return

    # Ensure plugins dir is importable
    if PLUGINS_DIR not in sys.path:
        sys.path.insert(0, PLUGINS_DIR)

    for filename in sorted(os.listdir(PLUGINS_DIR)):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue

        module_name = filename[:-3]
        try:
            # Import or reload the module
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)

            # Validate required attributes
            missing = [a for a in REQUIRED_ATTRS if not hasattr(mod, a)]
            if missing:
                err = f"missing required attributes: {', '.join(missing)}"
                _load_errors.append((filename, err))
                log.warning("Plugin %s skipped: %s", filename, err)
                continue

            if not isinstance(mod.TOOLS, list):
                err = "TOOLS must be a list"
                _load_errors.append((filename, err))
                log.warning("Plugin %s skipped: %s", filename, err)
                continue

            if not callable(mod.execute):
                err = "execute must be callable"
                _load_errors.append((filename, err))
                log.warning("Plugin %s skipped: %s", filename, err)
                continue

            # Register the plugin and map its tools
            _plugins[module_name] = mod
            for tool_def in mod.TOOLS:
                tool_name = tool_def.get("name")
                if tool_name:
                    _tool_map[tool_name] = mod

            log.info("Loaded plugin: %s (%d tools)", mod.PLUGIN_NAME, len(mod.TOOLS))

        except Exception as e:
            _load_errors.append((filename, str(e)))
            log.warning("Plugin %s failed to load: %s", filename, e)


def get_all_plugin_tools():
    """Return combined TOOLS list from all loaded plugins."""
    all_tools = []
    for mod in _plugins.values():
        all_tools.extend(mod.TOOLS)
    return all_tools


def execute_plugin_tool(tool_name, tool_input, config=None, conversation_history=None):
    """Route a tool call to the correct plugin's execute function.

    Passes read-only copies of config and conversation_history.
    Returns (result_string, is_error) or None if tool not found in any plugin.
    """
    mod = _tool_map.get(tool_name)
    if mod is None:
        return None

    # Pass read-only copies for sandboxing
    safe_config = copy.deepcopy(config) if config else {}
    safe_history = copy.deepcopy(conversation_history) if conversation_history else []

    try:
        return mod.execute(tool_name, tool_input, safe_config, safe_history)
    except Exception as e:
        return f"Plugin error ({mod.PLUGIN_NAME}): {e}", True


def list_plugins():
    """Return list of dicts with plugin info: name, description, tool_count, module."""
    result = []
    for module_name, mod in _plugins.items():
        result.append({
            "name": getattr(mod, "PLUGIN_NAME", module_name),
            "description": getattr(mod, "PLUGIN_DESCRIPTION", ""),
            "tool_count": len(mod.TOOLS),
            "module": module_name,
        })
    return result


def get_load_errors():
    """Return list of (filename, error_string) from last load."""
    return list(_load_errors)


def is_plugin_tool(tool_name):
    """True if tool_name belongs to a loaded plugin."""
    return tool_name in _tool_map


def reload_plugins():
    """Re-scan and reload all plugins."""
    load_plugins()


# Load plugins on import
load_plugins()
