"""Tests for the proactive insights engine."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# --- TestGatherSources ---

class TestGatherSources:
    """Test individual data-gathering functions."""

    def test_gather_tasks_returns_open_tasks(self, isolated_env):
        """Only open tasks are returned."""
        import insights

        # Create a project with tasks
        proj_dir = os.path.join(isolated_env, "projects", "general")
        os.makedirs(proj_dir, exist_ok=True)
        tasks_data = {
            "tasks": [
                {"id": 1, "description": "Open task", "status": "open"},
                {"id": 2, "description": "Done task", "status": "done"},
            ]
        }
        with open(os.path.join(proj_dir, "tasks.json"), "w") as f:
            json.dump(tasks_data, f)

        result = insights._gather_tasks()
        assert result["ok"] is True
        # Only the open task should be returned
        open_tasks = [t for t in result["tasks"] if t.get("status") == "open"]
        assert len(open_tasks) == 1
        assert open_tasks[0]["description"] == "Open task"

    def test_gather_email_unconfigured(self, monkeypatch):
        """Returns ok=False when Gmail is not available."""
        import insights
        import service_registry
        monkeypatch.setattr(service_registry, "is_available",
                            lambda name: False)

        result = insights._gather_email()
        assert result["ok"] is False

    def test_gather_calendar_configured(self, monkeypatch):
        """Returns ok=True with events when calendar is available."""
        import insights
        import service_registry
        import tools

        monkeypatch.setattr(service_registry, "is_available",
                            lambda name: name == "calendar")
        mock_events = [{"title": "Standup", "start": "9:00 AM", "all_day": False}]
        monkeypatch.setattr(tools, "calendar_get_events",
                            lambda d: mock_events)

        result = insights._gather_calendar()
        assert result["ok"] is True
        # today + tomorrow both return same mock, so events doubled
        assert len(result["events"]) == 2

    def test_gather_jobs_from_local_files(self, monkeypatch):
        """Jobs are loaded from local JSON files."""
        import insights
        import job_scanner

        monkeypatch.setattr(
            "memory.load_jobs",
            lambda: [{"title": "Engineer", "company": "Acme"}],
        )
        monkeypatch.setattr(job_scanner, "load_scan_results", lambda: None)

        result = insights._gather_jobs()
        assert result["ok"] is True
        assert len(result["saved_jobs"]) == 1


# --- TestSourceCounting ---

class TestSourceCounting:
    """Test the minimum-source gate."""

    def test_single_source_skips_model(self, monkeypatch):
        """With only 1 source with data, returns (None, 0) without API call."""
        import insights

        # Patch all gatherers: only tasks has data
        monkeypatch.setattr(insights, "_gather_tasks",
                            lambda: {"ok": True, "tasks": [{"id": 1}]})
        monkeypatch.setattr(insights, "_gather_reminders",
                            lambda: {"ok": True, "reminders": []})
        monkeypatch.setattr(insights, "_gather_email",
                            lambda: {"ok": False, "error": "not configured"})
        monkeypatch.setattr(insights, "_gather_calendar",
                            lambda: {"ok": False, "error": "not configured"})
        monkeypatch.setattr(insights, "_gather_jobs",
                            lambda: {"ok": True, "saved_jobs": [], "scan_results": None})
        monkeypatch.setattr(insights, "_gather_profile",
                            lambda: {"ok": True, "profile": {}})

        text, cost = insights.generate_insights()
        assert text is None
        assert cost == 0

    def test_two_sources_calls_model(self, monkeypatch):
        """With 2+ sources, the model is called."""
        import insights
        import models

        # Tasks + reminders both have data
        monkeypatch.setattr(insights, "_gather_tasks",
                            lambda: {"ok": True, "tasks": [{"id": 1, "description": "Test"}]})
        monkeypatch.setattr(insights, "_gather_reminders",
                            lambda: {"ok": True, "reminders": [{"description": "Call", "remind_at": "2026-02-24T10:00:00"}]})
        monkeypatch.setattr(insights, "_gather_email",
                            lambda: {"ok": False, "error": "not configured"})
        monkeypatch.setattr(insights, "_gather_calendar",
                            lambda: {"ok": False, "error": "not configured"})
        monkeypatch.setattr(insights, "_gather_jobs",
                            lambda: {"ok": True, "saved_jobs": [], "scan_results": None})
        monkeypatch.setattr(insights, "_gather_profile",
                            lambda: {"ok": True, "profile": {}})

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NO_INSIGHTS")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=10)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
        monkeypatch.setattr(models, "get_tier", lambda t: f"mock-{t}")
        monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

        text, cost = insights.generate_insights()
        # Model was called
        mock_client.messages.create.assert_called_once()


# --- TestModelCall ---

class TestModelCall:
    """Test API call configuration."""

    def _setup_two_sources(self, monkeypatch):
        """Helper: patch gatherers so 2 sources have data."""
        import insights
        monkeypatch.setattr(insights, "_gather_tasks",
                            lambda: {"ok": True, "tasks": [{"id": 1}]})
        monkeypatch.setattr(insights, "_gather_reminders",
                            lambda: {"ok": True, "reminders": [{"description": "X", "remind_at": "2026-03-01"}]})
        monkeypatch.setattr(insights, "_gather_email",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_calendar",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_jobs",
                            lambda: {"ok": True, "saved_jobs": [], "scan_results": None})
        monkeypatch.setattr(insights, "_gather_profile",
                            lambda: {"ok": True, "profile": {}})

    def test_uses_standard_tier(self, monkeypatch):
        """Model call uses 'standard' tier, not 'fast'."""
        import insights
        import models

        self._setup_two_sources(monkeypatch)

        tier_calls = []
        original_get_tier = models.get_tier

        def mock_get_tier(t):
            tier_calls.append(t)
            return "mock-standard-model"

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NO_INSIGHTS")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=10)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
        monkeypatch.setattr(models, "get_tier", mock_get_tier)
        monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

        insights.generate_insights()
        assert "standard" in tier_calls

    def test_system_prompt_passed(self, monkeypatch):
        """System prompt is passed to the API call."""
        import insights
        import models

        self._setup_two_sources(monkeypatch)

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NO_INSIGHTS")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=10)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
        monkeypatch.setattr(models, "get_tier", lambda t: "mock-model")
        monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

        insights.generate_insights()
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("system") == insights._INSIGHTS_SYSTEM_PROMPT


# --- TestResponseParsing ---

class TestResponseParsing:
    """Test parsing of model responses."""

    def _run_with_response(self, monkeypatch, response_text):
        """Helper: run generate_insights with a mocked model response."""
        import insights
        import models

        monkeypatch.setattr(insights, "_gather_tasks",
                            lambda: {"ok": True, "tasks": [{"id": 1}]})
        monkeypatch.setattr(insights, "_gather_reminders",
                            lambda: {"ok": True, "reminders": [{"description": "X", "remind_at": "2026-03-01"}]})
        monkeypatch.setattr(insights, "_gather_email",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_calendar",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_jobs",
                            lambda: {"ok": True, "saved_jobs": [], "scan_results": None})
        monkeypatch.setattr(insights, "_gather_profile",
                            lambda: {"ok": True, "profile": {}})

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_text)]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=10)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
        monkeypatch.setattr(models, "get_tier", lambda t: "mock-model")
        monkeypatch.setattr(models, "track_usage", lambda *a, **kw: 0.001)

        return insights.generate_insights()

    def test_no_insights_returns_none(self, monkeypatch):
        """NO_INSIGHTS response → (None, cost)."""
        text, cost = self._run_with_response(monkeypatch, "NO_INSIGHTS")
        assert text is None
        assert cost == 0.001

    def test_insight_text_includes_header(self, monkeypatch):
        """Actual insight text gets the **Insights** header."""
        text, cost = self._run_with_response(
            monkeypatch,
            "You have a meeting with Acme tomorrow and an unanswered email from their recruiter.",
        )
        assert text is not None
        assert "**Insights**" in text
        assert "Acme" in text


# --- TestErrorHandling ---

class TestErrorHandling:
    """Test graceful failure modes."""

    def test_api_error_returns_none(self, monkeypatch):
        """If the API call raises, returns (None, 0) without crashing."""
        import insights
        import models

        monkeypatch.setattr(insights, "_gather_tasks",
                            lambda: {"ok": True, "tasks": [{"id": 1}]})
        monkeypatch.setattr(insights, "_gather_reminders",
                            lambda: {"ok": True, "reminders": [{"description": "X", "remind_at": "2026-03-01"}]})
        monkeypatch.setattr(insights, "_gather_email",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_calendar",
                            lambda: {"ok": False, "error": "n/a"})
        monkeypatch.setattr(insights, "_gather_jobs",
                            lambda: {"ok": True, "saved_jobs": [], "scan_results": None})
        monkeypatch.setattr(insights, "_gather_profile",
                            lambda: {"ok": True, "profile": {}})

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API down")
        monkeypatch.setattr(models, "get_client", lambda: mock_client)
        monkeypatch.setattr(models, "get_tier", lambda t: "mock-model")

        text, cost = insights.generate_insights()
        assert text is None
        assert cost == 0
