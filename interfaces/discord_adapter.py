"""Discord interface adapter — wraps discord_bot.py functionality.

Provides the InterfaceAdapter API for the Discord interface.
The standalone discord_bot.py continues to work independently; this adapter
enables uniform dispatch from systems like notifications and daemon.
"""

from interfaces.base_adapter import InterfaceAdapter


class DiscordAdapter(InterfaceAdapter):
    """Adapter for the Discord (discord_bot.py) interface.

    Requires an initialized discord.py client and a target DM channel.
    Typically constructed by discord_bot.py when it starts up.
    """

    def __init__(self, dm_channel=None):
        self._dm_channel = dm_channel

    async def receive_input(self) -> str:
        # Discord uses event-driven input via on_message — not polled here
        raise NotImplementedError("Discord uses event-driven input via on_message")

    async def send_output(self, message: str) -> None:
        if self._dm_channel:
            # Discord has a 2000-char limit per message
            while message:
                chunk, message = message[:2000], message[2000:]
                await self._dm_channel.send(chunk)

    async def send_file(self, filepath: str, description: str = "") -> None:
        if self._dm_channel:
            import discord
            await self._dm_channel.send(
                content=description or None,
                file=discord.File(filepath),
            )

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        await self.send_output(message)

    def get_interface_name(self) -> str:
        return "discord"

    def supports_rich_formatting(self) -> bool:
        return True  # Discord supports markdown

    def confirm(self, prompt: str) -> bool:
        # Discord bot auto-approves (same as discord_bot.py confirm_fn=None)
        return False
