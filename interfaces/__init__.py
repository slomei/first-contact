"""Interface adapter pattern for First Contact.

New interfaces should subclass InterfaceAdapter from base_adapter.py.
Existing interfaces (chat.py, gui.py, discord_bot.py, telegram_bot.py)
predate this pattern and work independently.
"""

from interfaces.base_adapter import InterfaceAdapter

__all__ = ["InterfaceAdapter"]
