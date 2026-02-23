# Interface Adapters

This directory contains the base class and adapter implementations for all First Contact interfaces.

## Architecture

`InterfaceAdapter` (in `base_adapter.py`) is an abstract base class that defines the contract every interface must fulfill:

| Method | Purpose |
|--------|---------|
| `receive_input()` | Get a message from the user |
| `send_output(message)` | Send a response to the user |
| `send_file(filepath, description)` | Send a file to the user |
| `send_notification(message, priority)` | Deliver a background notification |
| `get_interface_name()` | Return the interface name (for logging) |
| `supports_rich_formatting()` | Whether markdown rendering is supported |
| `confirm(prompt)` | Yes/no confirmation for destructive operations |
| `on_startup()` | Optional setup hook |
| `on_shutdown()` | Optional cleanup hook |

All business logic — model routing, tool execution, memory, tasks, notifications — lives in the shared core modules. Adapters only handle I/O.

## Existing Adapters

| Adapter | Wraps | Notes |
|---------|-------|-------|
| `TerminalAdapter` | `chat.py` | Synchronous I/O via stdin/stdout |
| `DiscordAdapter` | `discord_bot.py` | Requires discord.py client + DM channel |
| `TelegramAdapter` | `telegram_bot.py` | Requires python-telegram-bot Bot + chat_id |
| `WebAdapter` | `web_ui/server.py` | Requires active WebSocket connection |

The standalone interface files (`chat.py`, `discord_bot.py`, `telegram_bot.py`, `web_ui/server.py`) continue to work independently. The adapters provide a uniform API for systems that need to interact with interfaces generically — notification dispatch, daemon integration, and future shared logic.

## Creating a New Interface

1. Create a new file (e.g., `interfaces/voice_adapter.py`)
2. Subclass `InterfaceAdapter` and implement all abstract methods
3. Wire up the shared core: `memory.build_system_prompt()`, `models.get_client().messages.create()`, `tools.execute_tool()`
4. Add a main loop that receives input, sends it to the model, handles tool use, and sends output

See `example_adapter.py` for a minimal commented reference.

## Example

```python
from interfaces import InterfaceAdapter

class VoiceAdapter(InterfaceAdapter):
    async def receive_input(self) -> str:
        return transcribed_text

    async def send_output(self, message: str) -> None:
        synthesize_and_play(message)

    async def send_file(self, filepath: str, description: str = "") -> None:
        announce(f"File ready: {filepath}")

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        play_notification_sound()
        announce(message)

    def get_interface_name(self) -> str:
        return "voice"

    def supports_rich_formatting(self) -> bool:
        return False

    def confirm(self, prompt: str) -> bool:
        return listen_for_yes_or_no()
```
