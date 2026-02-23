"""Telegram interface adapter — wraps telegram_bot.py functionality.

Provides the InterfaceAdapter API for the Telegram interface.
The standalone telegram_bot.py continues to work independently; this adapter
enables uniform dispatch from systems like notifications and daemon.
"""

from interfaces.base_adapter import InterfaceAdapter


class TelegramAdapter(InterfaceAdapter):
    """Adapter for the Telegram (telegram_bot.py) interface.

    Requires an initialized python-telegram-bot Bot instance and a chat_id.
    Typically constructed by telegram_bot.py when it starts up.
    """

    def __init__(self, bot=None, chat_id=None):
        self._bot = bot
        self._chat_id = chat_id

    async def receive_input(self) -> str:
        # Telegram uses event-driven input via update handlers — not polled here
        raise NotImplementedError("Telegram uses event-driven input via update handlers")

    async def send_output(self, message: str) -> None:
        if self._bot and self._chat_id:
            # Telegram has a 4096-char limit per message
            while message:
                chunk, message = message[:4096], message[4096:]
                await self._bot.send_message(chat_id=self._chat_id, text=chunk)

    async def send_file(self, filepath: str, description: str = "") -> None:
        if self._bot and self._chat_id:
            with open(filepath, "rb") as f:
                await self._bot.send_document(
                    chat_id=self._chat_id,
                    document=f,
                    caption=description or None,
                )

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        await self.send_output(message)

    def get_interface_name(self) -> str:
        return "telegram"

    def supports_rich_formatting(self) -> bool:
        return False  # Telegram plain text by default

    def confirm(self, prompt: str) -> bool:
        # Telegram bot auto-approves (same as telegram_bot.py confirm_fn=None)
        return False
