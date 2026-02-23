"""Tests for the centralized service registry."""

import os

import pytest

import service_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry to clean state before each test."""
    service_registry._reset()


# ---------------------------------------------------------------------------
# Built-in registration
# ---------------------------------------------------------------------------

class TestBuiltinServices:
    def test_builtin_services_registered(self):
        """list_services() includes all 6 built-in services."""
        names = service_registry.list_services()
        assert set(names) == {"discord", "telegram", "gmail", "calendar", "web_search", "job_search"}

    def test_check_all_updates_statuses(self, tmp_path, monkeypatch):
        """After check_all(), no status stays at default unconfigured for always-healthy services."""
        import memory
        monkeypatch.setattr(memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(memory, "load_config", lambda: {})
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_USER_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
        result = service_registry.check_all()
        assert result["web_search"] == "healthy"
        assert result["job_search"] == "healthy"
        # Others should be unconfigured without credentials
        assert result["discord"] == "unconfigured"
        assert result["telegram"] == "unconfigured"


# ---------------------------------------------------------------------------
# Always-healthy services
# ---------------------------------------------------------------------------

class TestAlwaysHealthy:
    def test_web_search_always_healthy(self):
        status = service_registry.check("web_search")
        assert status == "healthy"

    def test_job_search_always_healthy(self):
        status = service_registry.check("job_search")
        assert status == "healthy"


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

class TestDiscord:
    def test_discord_unconfigured_without_token(self, monkeypatch):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_USER_ID", raising=False)
        assert service_registry.check("discord") == "unconfigured"

    def test_discord_configured_with_token_only(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        monkeypatch.delenv("DISCORD_USER_ID", raising=False)
        assert service_registry.check("discord") == "configured"

    def test_discord_healthy_with_both(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("DISCORD_USER_ID", "123456")
        assert service_registry.check("discord") == "healthy"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

class TestTelegram:
    def test_telegram_unconfigured_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
        assert service_registry.check("telegram") == "unconfigured"


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

class TestGmail:
    def test_gmail_unconfigured_without_accounts(self, tmp_path, monkeypatch):
        import memory
        monkeypatch.setattr(memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(memory, "load_config", lambda: {})
        assert service_registry.check("gmail") == "unconfigured"

    def test_gmail_healthy_with_accounts_and_creds(self, tmp_path, monkeypatch):
        import memory
        monkeypatch.setattr(memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(memory, "load_config", lambda: {
            "email_accounts": [{"label": "main", "credentials_file": "gmail_credentials.json"}]
        })
        (tmp_path / "gmail_credentials.json").write_text("{}")
        assert service_registry.check("gmail") == "healthy"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

class TestCalendar:
    def test_calendar_healthy_with_creds(self, tmp_path, monkeypatch):
        import memory
        monkeypatch.setattr(memory, "BASE_DIR", str(tmp_path))
        (tmp_path / "calendar_credentials.json").write_text("{}")
        assert service_registry.check("calendar") == "healthy"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_is_available_true_for_healthy_false_for_unconfigured(self, monkeypatch):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        service_registry.check("discord")
        assert not service_registry.is_available("discord")

        service_registry.check("web_search")
        assert service_registry.is_available("web_search")


# ---------------------------------------------------------------------------
# Custom registration and error handling
# ---------------------------------------------------------------------------

class TestCustomAndErrors:
    def test_custom_service_registration(self):
        service_registry.register("my_service", lambda: "healthy")
        assert "my_service" in service_registry.list_services()
        assert service_registry.check("my_service") == "healthy"
        assert service_registry.is_available("my_service")

    def test_check_fn_exception_sets_error(self):
        def bad_check():
            raise RuntimeError("boom")
        service_registry.register("broken", bad_check)
        assert service_registry.check("broken") == "error"
        assert not service_registry.is_available("broken")
