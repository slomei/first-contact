"""Tests for prompt caching in daemon-triggered API calls.

Verifies that job scanner, briefing watchlist, and digest summarization
calls include cache_control in their system parameters.
"""

import json
import os
from unittest.mock import MagicMock, patch


def _mock_api_response(text="ok", input_tokens=50, output_tokens=20,
                       cache_creation=10, cache_read=40):
    """Build a mock Anthropic API response object."""
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    msg.usage = MagicMock()
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    msg.usage.cache_creation_input_tokens = cache_creation
    msg.usage.cache_read_input_tokens = cache_read
    return msg


# ---------------------------------------------------------------------------
# job_scanner._assess_fit_batch — cache_control on system parameter
# ---------------------------------------------------------------------------

class TestAssessFitBatchCaching:
    """_assess_fit_batch passes cache_control in the system parameter."""

    @patch("job_scanner._build_fit_prompt", return_value="Assess this job.")
    def test_system_has_cache_control(self, _mock_prompt):
        import job_scanner
        import models

        models.get_client().messages.create.return_value = _mock_api_response(
            text='{"score": 7, "reason": "good", "title": "Dev", "company": "Co", "location": "NYC"}'
        )

        jobs = [{"title": "Dev", "url": "http://x.com", "body": "Job description"}]
        with patch.object(models, "track_usage", return_value=0.001):
            job_scanner._assess_fit_batch(jobs)

        call_kwargs = models.get_client().messages.create.call_args
        system_param = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")

        # System should be a list with one block containing cache_control
        assert isinstance(system_param, list)
        assert len(system_param) == 1
        assert system_param[0]["cache_control"] == {"type": "ephemeral"}
        assert "Assess this job" in system_param[0]["text"]

    @patch("job_scanner._build_fit_prompt", return_value="Assess this job.")
    def test_tracks_cache_tokens(self, _mock_prompt):
        """track_usage receives cache token counts from the API response."""
        import job_scanner
        import models

        models.get_client().messages.create.return_value = _mock_api_response(
            text='{"score": 5, "reason": "ok", "title": "Dev", "company": "Co", "location": "NYC"}',
            cache_creation=100, cache_read=500,
        )

        jobs = [{"title": "Dev", "url": "http://x.com", "body": "Body"}]
        with patch.object(models, "track_usage", return_value=0.001) as mock_track:
            job_scanner._assess_fit_batch(jobs)

        assert mock_track.call_args.kwargs.get("cache_creation_input_tokens") == 100
        assert mock_track.call_args.kwargs.get("cache_read_input_tokens") == 500


# ---------------------------------------------------------------------------
# briefing._gather_watchlist — cache_control on summarization call
# ---------------------------------------------------------------------------

class TestGatherWatchlistCaching:
    """_gather_watchlist passes cache_control in the system parameter."""

    @patch("briefing.tools")
    def test_system_has_cache_control(self, mock_tools, isolated_env):
        import briefing
        import memory
        import models

        # Create a watchlist file so _gather_watchlist finds topics
        project_dir = os.path.join(memory.PROJECTS_DIR, "general")
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, "watchlist.json"), "w") as f:
            json.dump(["AI news"], f)

        mock_tools.web_search.return_value = "Some search results"
        models.get_client().messages.create.return_value = _mock_api_response(
            text="- AI is advancing"
        )

        with patch.object(models, "track_usage", return_value=0.001):
            result = briefing._gather_watchlist()

        call_kwargs = models.get_client().messages.create.call_args
        system_param = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")

        assert isinstance(system_param, list)
        assert len(system_param) == 1
        assert system_param[0]["cache_control"] == {"type": "ephemeral"}
        assert "Summarize" in system_param[0]["text"]
        assert result["ok"] is True
        assert result["has_topics"] is True

    @patch("briefing.tools")
    def test_tracks_cache_tokens(self, mock_tools, isolated_env):
        """track_usage receives cache token counts from the response."""
        import briefing
        import memory
        import models

        project_dir = os.path.join(memory.PROJECTS_DIR, "general")
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, "watchlist.json"), "w") as f:
            json.dump(["topic"], f)

        mock_tools.web_search.return_value = "results"
        models.get_client().messages.create.return_value = _mock_api_response(
            cache_creation=50, cache_read=200,
        )

        with patch.object(models, "track_usage", return_value=0.001) as mock_track:
            briefing._gather_watchlist()

        assert mock_track.call_args.kwargs.get("cache_creation_input_tokens") == 50
        assert mock_track.call_args.kwargs.get("cache_read_input_tokens") == 200


# ---------------------------------------------------------------------------
# tools.run_digest — cache_control on summarization call
# ---------------------------------------------------------------------------

class TestRunDigestCaching:
    """tools.run_digest passes cache_control in the system parameter."""

    @patch("tools.web_search", return_value="Search results here")
    @patch("tools.memory")
    def test_system_has_cache_control(self, mock_memory, _mock_search):
        import tools
        import models

        mock_memory.load_watchlist.return_value = ["AI advances"]
        mock_memory.local_now.return_value = MagicMock(
            strftime=MagicMock(return_value="2026-02-23")
        )
        mock_memory.get_workspace_dir.return_value = "/tmp"

        models.get_client().messages.create.return_value = _mock_api_response(
            text="Digest summary"
        )

        tools.run_digest()

        call_kwargs = models.get_client().messages.create.call_args
        system_param = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")

        assert isinstance(system_param, list)
        assert len(system_param) == 1
        assert system_param[0]["cache_control"] == {"type": "ephemeral"}
        assert "digest" in system_param[0]["text"].lower()


# ---------------------------------------------------------------------------
# models.track_usage — cache token accounting
# ---------------------------------------------------------------------------

class TestTrackUsageCacheAccounting:
    """track_usage correctly accounts for cache_creation and cache_read tokens."""

    def test_cache_creation_updates_session(self):
        import models

        orig_cc = models.session_cache_creation_tokens
        orig_cr = models.session_cache_read_tokens
        orig_cost = models.session_cost
        try:
            models.track_usage(
                100, 50, "claude-sonnet-4-6",
                cache_creation_input_tokens=200,
                cache_read_input_tokens=0,
            )
            assert models.session_cache_creation_tokens == orig_cc + 200
        finally:
            models.session_cache_creation_tokens = orig_cc
            models.session_cache_read_tokens = orig_cr
            models.session_cost = orig_cost

    def test_cache_read_updates_session(self):
        import models

        orig_cc = models.session_cache_creation_tokens
        orig_cr = models.session_cache_read_tokens
        orig_cost = models.session_cost
        try:
            models.track_usage(
                100, 50, "claude-sonnet-4-6",
                cache_creation_input_tokens=0,
                cache_read_input_tokens=300,
            )
            assert models.session_cache_read_tokens == orig_cr + 300
        finally:
            models.session_cache_creation_tokens = orig_cc
            models.session_cache_read_tokens = orig_cr
            models.session_cost = orig_cost

    def test_cache_write_costs_more_than_base_input(self):
        """Cache write multiplier (1.25x) makes creation tokens cost more than regular input."""
        import models

        orig = (models.session_input_tokens, models.session_output_tokens,
                models.session_cost, models.session_cache_creation_tokens,
                models.session_cache_read_tokens)
        try:
            # 1000 regular input tokens
            cost_regular = models.track_usage(1000, 0, "claude-sonnet-4-6")
            # Reset
            (models.session_input_tokens, models.session_output_tokens,
             models.session_cost, models.session_cache_creation_tokens,
             models.session_cache_read_tokens) = orig
            # 1000 cache creation tokens (no regular input)
            cost_cache_write = models.track_usage(
                0, 0, "claude-sonnet-4-6",
                cache_creation_input_tokens=1000,
            )
            assert cost_cache_write > cost_regular
        finally:
            (models.session_input_tokens, models.session_output_tokens,
             models.session_cost, models.session_cache_creation_tokens,
             models.session_cache_read_tokens) = orig

    def test_cache_read_costs_less_than_base_input(self):
        """Cache read multiplier (0.10x) makes read tokens much cheaper than regular input."""
        import models

        orig = (models.session_input_tokens, models.session_output_tokens,
                models.session_cost, models.session_cache_creation_tokens,
                models.session_cache_read_tokens)
        try:
            cost_regular = models.track_usage(1000, 0, "claude-sonnet-4-6")
            (models.session_input_tokens, models.session_output_tokens,
             models.session_cost, models.session_cache_creation_tokens,
             models.session_cache_read_tokens) = orig
            cost_cache_read = models.track_usage(
                0, 0, "claude-sonnet-4-6",
                cache_read_input_tokens=1000,
            )
            assert cost_cache_read < cost_regular
        finally:
            (models.session_input_tokens, models.session_output_tokens,
             models.session_cost, models.session_cache_creation_tokens,
             models.session_cache_read_tokens) = orig

    def test_combined_cache_tokens_in_cost(self):
        """Cost includes both cache creation and cache read components."""
        import models

        orig = (models.session_input_tokens, models.session_output_tokens,
                models.session_cost, models.session_cache_creation_tokens,
                models.session_cache_read_tokens)
        try:
            cost = models.track_usage(
                1000, 200, "claude-sonnet-4-6",
                cache_creation_input_tokens=500,
                cache_read_input_tokens=300,
            )
            # Manual calculation:
            # input: 1000 * 3.0 = 3000
            # output: 200 * 15.0 = 3000
            # cache write: 500 * 3.0 * 1.25 = 1875
            # cache read: 300 * 3.0 * 0.10 = 90
            # total: (3000 + 3000 + 1875 + 90) / 1_000_000 = 0.007965
            expected = (3000 + 3000 + 1875 + 90) / 1_000_000
            assert abs(cost - expected) < 1e-9
        finally:
            (models.session_input_tokens, models.session_output_tokens,
             models.session_cost, models.session_cache_creation_tokens,
             models.session_cache_read_tokens) = orig
