# Contributing to First Contact

Thanks for your interest. This is a personal project, but contributions are welcome.

## Adding a New Tool

Tools live in `tools.py`. To add one:

1. **Define the tool schema** — Add a dict to the `TOOLS` list with `name`, `description`, and `input_schema`. Follow the existing patterns.

2. **Implement the handler** — Add an `elif name == "your_tool":` block in `execute_tool()`. Return a tuple of `(result_string, is_error)`.

3. **Add a status label** — Add a case in `tool_status_text()` so users see what the agent is doing.

4. **Consider security** — If your tool touches external data, wrap it with untrusted content markers. If it writes anything, require confirmation via `confirm_fn`. If it has cost implications, add rate limiting.

## Adding a New Interface

New interfaces should subclass `InterfaceAdapter` from `interfaces/base_adapter.py`. This abstract base class defines the contract:

- `receive_input()` — get a message from the user
- `send_output(message)` — send a response
- `send_file(filepath, description)` — send a file
- `send_notification(message, priority)` — deliver background notifications
- `get_interface_name()` — return the interface name for logging
- `supports_rich_formatting()` — whether markdown is supported
- `confirm(prompt)` — yes/no confirmation for destructive operations

See `interfaces/example_adapter.py` for a commented reference implementation and `interfaces/README.md` for full details.

Your interface also needs to wire up the shared core:

- Build the system prompt via `memory.build_system_prompt()`
- Send messages through `models.get_client().messages.create()` with `tools=tools.TOOLS`
- Handle tool use loops (assistant requests tool → execute → return result → continue)
- Call `tools.execute_tool()` for tool execution
- Pass your `confirm` method as `confirm_fn` for destructive operations

Everything else — model routing, memory, tool logic — comes from the shared core. The existing interfaces (`chat.py`, `discord_bot.py`, `telegram_bot.py`, `web_ui/server.py`) predate this pattern and work independently.

## Code Style

- Python 3.10+
- No type hints enforced, but welcome
- Functions that touch the filesystem should handle missing files gracefully
- Errors should produce helpful messages, not tracebacks
- Keep imports at the top of files; lazy-import only to avoid circular dependencies (see `tools.py` → `models` pattern)

## Reporting Issues

Open a GitHub issue. Include:
- What you were doing
- What you expected
- What happened instead
- Your Python version and OS

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Test that all four interfaces still work (terminal at minimum)
- Don't commit `.env`, `config.json`, credentials, or personal data
