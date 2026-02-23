"""Tests for the onboarding wizard, focused on the calibration phase."""

import os
from unittest.mock import MagicMock, patch

import pytest

import onboarding
from onboarding import OnboardingWizard, STEPS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step_keys():
    """Return just the key names from STEPS."""
    return [s[0] for s in STEPS]


def _advance_to_calibration(wiz, is_terminal=False):
    """Fast-forward the wizard through all structured questions up to calibration.

    Returns the prompt that includes the calibration intro.
    """
    # welcome (auto-advance) + name
    prompt, done = wiz.advance("", is_terminal)
    assert not done
    # name
    prompt, done = wiz.advance("Jane Doe", is_terminal)
    # work
    prompt, done = wiz.advance("Software engineer", is_terminal)
    # use_case
    prompt, done = wiz.advance("Personal assistant", is_terminal)
    # comm_style
    prompt, done = wiz.advance("2", is_terminal)
    # tech_level
    prompt, done = wiz.advance("3", is_terminal)
    # email
    prompt, done = wiz.advance("skip", is_terminal)
    # location
    prompt, done = wiz.advance("skip", is_terminal)
    # discord
    prompt, done = wiz.advance("skip", is_terminal)
    # telegram
    prompt, done = wiz.advance("skip", is_terminal)
    # gmail
    prompt, done = wiz.advance("skip", is_terminal)
    # calendar
    prompt, done = wiz.advance("skip", is_terminal)
    # search_provider
    prompt, done = wiz.advance("skip", is_terminal)
    # notify_prefs
    prompt, done = wiz.advance("1", is_terminal)
    # At this point, _next_prompt should have auto-advanced through
    # calibration_intro and returned the intro + calibration_1 prompt
    return prompt, done


def _make_sonnet_response(text):
    """Build a mock Anthropic response object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


# ---------------------------------------------------------------------------
# Step structure tests
# ---------------------------------------------------------------------------

class TestCalibrationSteps:
    def test_calibration_steps_in_correct_position(self):
        keys = _step_keys()
        # calibration steps appear after notify_prefs and before review
        notify_idx = keys.index("notify_prefs")
        review_idx = keys.index("review")
        cal_keys = keys[notify_idx + 1 : review_idx]
        assert cal_keys == [
            "calibration_intro",
            "calibration_1",
            "calibration_2",
            "calibration_3",
            "calibration_analyze",
        ]

    def test_calibration_intro_is_auto_advance(self):
        for key, prompt, notes in STEPS:
            if key == "calibration_intro":
                assert notes == "auto-advance"
                assert prompt is None

    def test_calibration_1_has_prompt(self):
        for key, prompt, notes in STEPS:
            if key == "calibration_1":
                assert notes == "calibration"
                assert "working on" in prompt.lower() or "excited" in prompt.lower()

    def test_calibration_2_3_have_no_prompt(self):
        for key, prompt, notes in STEPS:
            if key in ("calibration_2", "calibration_3"):
                assert notes == "calibration"
                assert prompt is None

    def test_calibration_analyze_is_auto_advance(self):
        for key, prompt, notes in STEPS:
            if key == "calibration_analyze":
                assert notes == "auto-advance"
                assert prompt is None


# ---------------------------------------------------------------------------
# Flow tests
# ---------------------------------------------------------------------------

class TestCalibrationFlow:
    def test_calibration_intro_auto_advances(self):
        """After notify_prefs, the wizard should auto-advance past calibration_intro
        and show the intro message + calibration_1 prompt."""
        wiz = OnboardingWizard()
        prompt, done = _advance_to_calibration(wiz)
        assert not done
        assert "Agent:" in prompt
        assert "how you communicate" in prompt.lower()
        assert "working on" in prompt.lower() or "excited" in prompt.lower()

    def test_calibration_exchanges_initialized(self):
        """After calibration_intro auto-advances, calibration_exchanges should be
        initialized with the first assistant message."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)
        exchanges = wiz.data.get("calibration_exchanges", [])
        assert len(exchanges) == 1
        assert exchanges[0]["role"] == "assistant"

    def test_calibration_1_stores_user_response(self):
        """User's answer to calibration_1 should be stored in exchanges."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        # Mock Sonnet for follow-up generation
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_sonnet_response(
            "That sounds interesting! What draws you to that?"
        )
        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("I'm building a game engine", False)

        assert not done
        exchanges = wiz.data["calibration_exchanges"]
        # Should have: assistant (cal_1 prompt), user (response), assistant (follow-up)
        assert len(exchanges) == 3
        assert exchanges[1]["role"] == "user"
        assert exchanges[1]["content"] == "I'm building a game engine"
        assert exchanges[2]["role"] == "assistant"

    def test_calibration_follow_up_uses_agent_prefix(self):
        """Generated follow-up prompts should be prefixed with 'Agent:'."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_sonnet_response(
            "What part of that excites you the most?"
        )
        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("Working on a side project", False)

        assert prompt.startswith("Agent:")

    def test_full_calibration_flow(self):
        """Walk through the entire calibration: 3 user responses, analysis, then review."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        # Call 1: Sonnet follow-up for calibration_2
        # Call 2: Sonnet follow-up for calibration_3
        # Call 3: Opus analysis
        # Call 4: Haiku review check (from _run_review_check)
        mock_client.messages.create.side_effect = [
            _make_sonnet_response("What draws you to that?"),
            _make_sonnet_response("How did you get started with that?"),
            _make_sonnet_response("Jane communicates directly and efficiently."),
            _make_sonnet_response("CONSISTENT"),  # review check
        ]

        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            # calibration_1 response
            prompt, done = wiz.advance("Building a game engine", False)
            assert not done
            assert "Agent:" in prompt

            # calibration_2 response
            prompt, done = wiz.advance("I love the creative challenge", False)
            assert not done
            assert "Agent:" in prompt

            # calibration_3 response — triggers analysis + review
            prompt, done = wiz.advance("Started with Unity, moved to custom", False)
            assert not done

        # Check exchanges
        exchanges = wiz.data["calibration_exchanges"]
        user_msgs = [e for e in exchanges if e["role"] == "user"]
        assert len(user_msgs) == 3

        # Check analysis result
        assert wiz.data.get("calibration_profile") == "Jane communicates directly and efficiently."

    def test_calibration_accepts_empty_input(self):
        """Empty user input should be stored as '(no response)', not rejected."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_sonnet_response("Tell me more?")
        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("", False)

        assert not done
        exchanges = wiz.data["calibration_exchanges"]
        assert exchanges[1]["role"] == "user"
        assert exchanges[1]["content"] == "(no response)"

    def test_calibration_accepts_single_word(self):
        """Single-word answers are valid calibration data."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_sonnet_response("Nice! What kind?")
        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("stuff", False)

        exchanges = wiz.data["calibration_exchanges"]
        assert exchanges[1]["content"] == "stuff"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestCalibrationErrors:
    def test_sonnet_failure_skips_calibration(self):
        """If Sonnet fails to generate a follow-up, skip remaining calibration."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception("API error"),  # Sonnet fails for calibration_2
            _make_sonnet_response("CONSISTENT"),  # review check
        ]

        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("I'm building stuff", False)
            # Should skip to review, not crash
            assert not done

        # Should not have a calibration profile since analysis was skipped
        assert "calibration_profile" not in wiz.data

    def test_opus_failure_skips_profile(self):
        """If Opus analysis fails, proceed to review without calibration_profile."""
        wiz = OnboardingWizard()
        _advance_to_calibration(wiz)

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _make_sonnet_response("What draws you to that?"),     # cal_2 follow-up
            _make_sonnet_response("How did you get started?"),     # cal_3 follow-up
            Exception("Opus API error"),                           # analysis fails
            _make_sonnet_response("CONSISTENT"),                   # review check
        ]

        with patch.object(onboarding.models, "get_client", return_value=mock_client):
            prompt, done = wiz.advance("Building a game", False)
            prompt, done = wiz.advance("Love the challenge", False)
            prompt, done = wiz.advance("Started years ago", False)
            assert not done

        # Exchanges should exist but no profile
        assert len(wiz.data["calibration_exchanges"]) > 0
        assert "calibration_profile" not in wiz.data


# ---------------------------------------------------------------------------
# Claude.md generation tests
# ---------------------------------------------------------------------------

class TestCalibrationInClaudeMd:
    def test_calibration_profile_in_claude_md(self):
        """When calibration_profile exists, it should appear in Claude.md output."""
        wiz = OnboardingWizard()
        wiz.data = {
            "name": "Jane Doe",
            "first_name": "Jane",
            "work": "Engineer",
            "use_case": "Assistant",
            "comm_style": "2",
            "tech_level": "3",
            "calibration_profile": "Jane is direct, uses technical vocabulary, and has a dry sense of humor.",
        }
        md = wiz._build_claude_md()
        assert "## PERSONALITY CALIBRATION" in md
        assert "Jane is direct" in md
        assert "updates as the agent learns more about you" in md

    def test_calibration_section_after_comm_style(self):
        """PERSONALITY CALIBRATION should appear after HOW TO TALK TO ME."""
        wiz = OnboardingWizard()
        wiz.data = {
            "name": "Jane Doe",
            "first_name": "Jane",
            "comm_style": "1",
            "tech_level": "2",
            "calibration_profile": "Test profile.",
        }
        md = wiz._build_claude_md()
        talk_idx = md.index("## HOW TO TALK TO ME")
        cal_idx = md.index("## PERSONALITY CALIBRATION")
        pro_idx = md.index("## PROFESSIONAL BACKGROUND")
        assert talk_idx < cal_idx < pro_idx

    def test_no_calibration_section_without_profile(self):
        """When calibration_profile is absent, no calibration section in Claude.md."""
        wiz = OnboardingWizard()
        wiz.data = {
            "name": "Jane Doe",
            "first_name": "Jane",
            "comm_style": "2",
            "tech_level": "3",
        }
        md = wiz._build_claude_md()
        assert "## PERSONALITY CALIBRATION" not in md


# ---------------------------------------------------------------------------
# get_current_prompt tests
# ---------------------------------------------------------------------------

class TestGetCurrentPrompt:
    def test_get_current_prompt_calibration_with_prompt(self):
        """For calibration_1 (has a prompt), get_current_prompt should use Agent: prefix."""
        wiz = OnboardingWizard()
        keys = _step_keys()
        wiz.step = keys.index("calibration_1")
        prompt = wiz.get_current_prompt()
        assert prompt.startswith("Agent:")
        assert "working on" in prompt.lower() or "excited" in prompt.lower()

    def test_get_current_prompt_calibration_generated(self):
        """For calibration_2/3 (generated prompt), should return last assistant exchange."""
        wiz = OnboardingWizard()
        keys = _step_keys()
        wiz.step = keys.index("calibration_2")
        wiz.data["calibration_exchanges"] = [
            {"role": "assistant", "content": "Tell me about something..."},
            {"role": "user", "content": "I like cats"},
            {"role": "assistant", "content": "What kind of cats?"},
        ]
        prompt = wiz.get_current_prompt()
        assert prompt == "Agent: What kind of cats?"


# ---------------------------------------------------------------------------
# get_suggested_workflows tests
# ---------------------------------------------------------------------------

class TestGetSuggestedWorkflows:
    def test_returns_non_empty_list(self, tmp_path, monkeypatch):
        """Always returns at least one suggestion."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {})
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_fallback_when_nothing_configured(self, tmp_path, monkeypatch):
        """With no integrations, returns universal fallback suggestions."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {})
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        texts = " ".join(result)
        assert "/remember" in texts
        assert "/web" in texts
        assert "/task" in texts

    def test_email_suggestion_when_accounts_set(self, tmp_path, monkeypatch):
        """Email suggestion appears when email_accounts is configured."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {
            "email_accounts": [{"label": "main", "credentials_file": "creds.json"}]
        })
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        assert any("/email" in s for s in result)

    def test_job_suggestion_when_target_roles_set(self, tmp_path, monkeypatch):
        """Job suggestion appears when target_roles is configured."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {
            "user_profile": {"target_roles": ["Engineer"]}
        })
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        assert any("/scan" in s for s in result)

    def test_job_suggestion_when_scan_queries_set(self, tmp_path, monkeypatch):
        """Job suggestion appears when job_scan queries are configured."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {
            "job_scan": {"queries": ["python developer"]}
        })
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        assert any("/scan" in s for s in result)

    def test_notification_suggestion_when_discord_token_set(self, tmp_path, monkeypatch):
        """Daemon suggestion appears when DISCORD_BOT_TOKEN is set."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {})
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = onboarding.get_suggested_workflows()
        assert any("daemon" in s for s in result)

    def test_calendar_suggestion_when_credentials_exist(self, tmp_path, monkeypatch):
        """Calendar suggestion appears when calendar_credentials.json exists."""
        monkeypatch.setattr(onboarding.memory, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(onboarding.memory, "load_config", lambda: {})
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        (tmp_path / "calendar_credentials.json").write_text("{}")
        result = onboarding.get_suggested_workflows()
        assert any("/cal" in s for s in result)
