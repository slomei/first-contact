"""Interface adapter pattern for First Contact.

InterfaceAdapter is the abstract base class. Each adapter wraps an
existing interface, providing a uniform API for notification dispatch,
daemon integration, and future shared logic.
"""

from interfaces.base_adapter import InterfaceAdapter
from interfaces.terminal_adapter import TerminalAdapter
from interfaces.discord_adapter import DiscordAdapter
from interfaces.telegram_adapter import TelegramAdapter
from interfaces.web_adapter import WebAdapter

__all__ = [
    "InterfaceAdapter",
    "TerminalAdapter",
    "DiscordAdapter",
    "TelegramAdapter",
    "WebAdapter",
]
