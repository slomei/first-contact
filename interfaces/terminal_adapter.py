"""Terminal interface adapter — wraps chat.py functionality.

Provides the InterfaceAdapter API for the terminal interface.
The standalone chat.py continues to work independently; this adapter
enables uniform dispatch from systems like notifications and daemon.
"""

from interfaces.base_adapter import InterfaceAdapter


class TerminalAdapter(InterfaceAdapter):
    """Adapter for the terminal (chat.py) interface."""

    async def receive_input(self) -> str:
        try:
            return input("> ")
        except (EOFError, KeyboardInterrupt):
            return ""

    async def send_output(self, message: str) -> None:
        print(message)

    async def send_file(self, filepath: str, description: str = "") -> None:
        label = f" — {description}" if description else ""
        print(f"File: {filepath}{label}")

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        # Terminal notifications just print — no background delivery
        print(f"[Notification] {message}")

    def get_interface_name(self) -> str:
        return "terminal"

    def supports_rich_formatting(self) -> bool:
        return False

    def confirm(self, prompt: str) -> bool:
        try:
            answer = input(f"{prompt} (y/n): ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False
