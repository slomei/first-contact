# Interface Adapters

This directory contains the base class and scaffolding for building new First Contact interfaces.

## Status

The four existing interfaces (`chat.py`, `gui.py`, `discord_bot.py`, `telegram_bot.py`) predate this pattern and work independently as standalone modules in the project root. They are not subclasses of `InterfaceAdapter`. They may be migrated in a future update, but for now they work as-is.

**New interfaces should use this pattern.** Future plans include a Tauri desktop app, a mobile app, and a voice interface — all good candidates for the adapter pattern.

## How It Works

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

All business logic — model routing, tool execution, memory, tasks, notifications — lives in the shared core modules. The adapter only handles I/O.

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
        # Transcribe audio via Whisper
        return transcribed_text

    async def send_output(self, message: str) -> None:
        # Synthesize speech and play it
        pass

    async def send_file(self, filepath: str, description: str = "") -> None:
        # Announce the file path via speech
        pass

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        # Play a notification sound + speak the message
        pass

    def get_interface_name(self) -> str:
        return "voice"

    def supports_rich_formatting(self) -> bool:
        return False

    def confirm(self, prompt: str) -> bool:
        # Ask via speech, listen for "yes" or "no"
        return False
```
