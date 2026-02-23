"""Tests for interface adapter classes."""

import pytest
from interfaces import (
    InterfaceAdapter,
    TerminalAdapter,
    DiscordAdapter,
    TelegramAdapter,
    WebAdapter,
)


def test_all_adapters_are_interface_adapter_subclasses():
    """Every adapter subclasses InterfaceAdapter."""
    for cls in (TerminalAdapter, DiscordAdapter, TelegramAdapter, WebAdapter):
        assert issubclass(cls, InterfaceAdapter)


def test_terminal_adapter_interface_name():
    adapter = TerminalAdapter()
    assert adapter.get_interface_name() == "terminal"
    assert adapter.supports_rich_formatting() is False


def test_discord_adapter_interface_name():
    adapter = DiscordAdapter()
    assert adapter.get_interface_name() == "discord"
    assert adapter.supports_rich_formatting() is True


def test_telegram_adapter_interface_name():
    adapter = TelegramAdapter()
    assert adapter.get_interface_name() == "telegram"
    assert adapter.supports_rich_formatting() is False


def test_web_adapter_interface_name():
    adapter = WebAdapter()
    assert adapter.get_interface_name() == "web"
    assert adapter.supports_rich_formatting() is True


def test_adapters_confirm_defaults_to_false():
    """All adapters default to denying confirmation (safe default)."""
    for cls in (DiscordAdapter, TelegramAdapter, WebAdapter):
        assert cls().confirm("Delete everything?") is False


def test_discord_receive_input_raises():
    """Discord adapter's receive_input raises NotImplementedError (event-driven)."""
    import asyncio
    adapter = DiscordAdapter()
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.receive_input())


def test_telegram_receive_input_raises():
    """Telegram adapter's receive_input raises NotImplementedError (event-driven)."""
    import asyncio
    adapter = TelegramAdapter()
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.receive_input())
