# First Contact Plugin Directory

A curated registry of plugins for First Contact. Official plugins ship with the project; community plugins are maintained by their authors.

## Official Plugins

| Plugin | Description | Author | Link |
|--------|-------------|--------|------|
| example_plugin | Demonstrates the plugin API (dice roller) | First Contact | Built-in |

## Community Plugins

| Plugin | Description | Author | Link |
|--------|-------------|--------|------|
<!-- Add your plugin here via pull request -->

## How to Submit Your Plugin

**Note:** Plugins run with full process access. Submissions to this directory will be reviewed for safety before listing.

1. Create your plugin using `python plugin_generator.py your_plugin`
2. Test it locally (restart First Contact or `/plugins reload`)
3. Host it on GitHub (or similar)
4. Submit a pull request adding a row to the Community Plugins table above

Your PR should include:
- Plugin name and description
- Your name or GitHub handle
- Link to the plugin repository

## Plugin Development Guide

- Plugins live in the `plugins/` directory as single `.py` files or packages (directories with `__init__.py`)
- Required exports: `PLUGIN_NAME`, `TOOLS`, `execute()`
- Optional exports: `PLUGIN_DESCRIPTION`, `PLUGIN_VERSION`
- Plugins run in a sandboxed context: read-only config, copied conversation history
- Tool names must be unique across all plugins and core tools
- See `plugins/example_plugin.py` for a single-file reference
- Use `python plugin_generator.py <name>` to scaffold a new package-based plugin with metadata and documentation
- See `plugins/README.md` for the full API contract
