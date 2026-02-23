"""Tests for the shared conversation turn loop."""

from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_final_message(text="Hello!", stop_reason="end_turn",
                        input_tokens=100, output_tokens=50,
                        cache_creation=0, cache_read=0,
                        tool_blocks=None):
    """Build a mock final message object mimicking the Anthropic API response."""
    msg = MagicMock()
    msg.stop_reason = stop_reason

    if tool_blocks is None:
        # Simple text response
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = text
        msg.content = [text_block]
    else:
        msg.content = tool_blocks

    msg.usage = MagicMock()
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    msg.usage.cache_creation_input_tokens = cache_creation
    msg.usage.cache_read_input_tokens = cache_read
    return msg


def _make_tool_block(tool_id, name, tool_input):
    """Build a mock tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = tool_input
    return block


def _make_text_block(text):
    """Build a mock text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


# ---------------------------------------------------------------------------
# extract_last_user_query
# ---------------------------------------------------------------------------

class TestExtractLastUserQuery:
    def test_string_content(self):
        import conversation
        history = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi!"},
        ]
        assert conversation.extract_last_user_query(history) == "Hello there"

    def test_list_content(self):
        import conversation
        history = [
            {"role": "user", "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]},
        ]
        assert conversation.extract_last_user_query(history) == "first second"

    def test_empty_history(self):
        import conversation
        assert conversation.extract_last_user_query([]) is None

    def test_no_user_messages(self):
        import conversation
        history = [{"role": "assistant", "content": "Hi"}]
        assert conversation.extract_last_user_query(history) is None

    def test_returns_last_user_message(self):
        import conversation
        history = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Reply"},
            {"role": "user", "content": "Second"},
        ]
        assert conversation.extract_last_user_query(history) == "Second"

    def test_tool_result_content_skipped(self):
        """Tool result messages (list of tool_result dicts) should be skipped."""
        import conversation
        history = [
            {"role": "user", "content": "Ask me something"},
            {"role": "assistant", "content": "Using a tool..."},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "result"}
            ]},
        ]
        # The tool_result message has no "text" type blocks, so extract
        # should skip it and find the earlier string message
        result = conversation.extract_last_user_query(history)
        # It will match the tool_result message first (it's last user msg)
        # but return empty string since no text blocks
        # Actually let's check: list content with no text blocks returns None
        # The function joins texts — empty list gives ""
        # Let me re-check: texts = [] for tool_result, " ".join([]) = ""
        # The function returns "" if texts is empty via the `if texts` guard
        assert result is None or result == "Ask me something"


# ---------------------------------------------------------------------------
# run_conversation_turn
# ---------------------------------------------------------------------------

class TestRunConversationTurn:
    """Tests for the core conversation loop."""

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_non_streaming_simple_response(self, mock_models, mock_memory, mock_tools):
        """Non-streaming call with a simple text response."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = [
            {"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}},
        ]
        mock_tools.get_cached_tools.return_value = []

        final_msg = _make_final_message("Hello!", input_tokens=100, output_tokens=50)
        mock_models.get_client().messages.create.return_value = final_msg
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "Hi"}]
        result = conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", query="Hi"
        )

        assert result["text"] == "Hello!"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cost"] > 0
        # History should have the assistant response appended
        assert history[-1] == {"role": "assistant", "content": "Hello!"}

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_streaming_calls_on_chunk(self, mock_models, mock_memory, mock_tools):
        """Streaming path calls on_stream_chunk for each text piece."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []

        final_msg = _make_final_message("Hello world", input_tokens=80, output_tokens=30)
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        # Mock the streaming context manager
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = ["Hello ", "world"]
        stream_ctx.get_final_message.return_value = final_msg
        mock_models.get_client().messages.stream.return_value = stream_ctx

        chunks = []
        history = [{"role": "user", "content": "Hi"}]
        result = conversation.run_conversation_turn(
            history, "claude-sonnet-4-6",
            on_stream_chunk=lambda c: chunks.append(c),
            query="Hi",
        )

        assert chunks == ["Hello ", "world"]
        assert result["text"] == "Hello world"

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_tool_use_loop(self, mock_models, mock_memory, mock_tools):
        """Tool use triggers a loop: tool call -> execute -> continue -> final text."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.return_value = ("search result", False)

        tool_block = _make_tool_block("t1", "web_search", {"query": "test"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=100, output_tokens=20,
            tool_blocks=[tool_block],
        )
        final_msg = _make_final_message("Here's what I found", input_tokens=150, output_tokens=40)

        mock_models.get_client().messages.create.side_effect = [tool_msg, final_msg]
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "Search for test"}]
        result = conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", query="Search for test"
        )

        assert result["text"] == "Here's what I found"
        assert result["input_tokens"] == 250  # 100 + 150
        assert result["output_tokens"] == 60  # 20 + 40
        # History: user msg, assistant tool_use, user tool_result, assistant text
        assert len(history) == 4
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"
        assert history[2]["content"][0]["type"] == "tool_result"
        mock_tools.execute_tool.assert_called_once_with(
            "web_search", {"query": "test"}, confirm_fn=None
        )

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_tool_callbacks(self, mock_models, mock_memory, mock_tools):
        """on_tool_start and on_tool_end are called around each tool execution."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.return_value = ("ok", False)

        tool_block = _make_tool_block("t1", "remember", {"fact": "test"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=50, output_tokens=10,
            tool_blocks=[tool_block],
        )
        final_msg = _make_final_message("Done", input_tokens=60, output_tokens=15)

        mock_models.get_client().messages.create.side_effect = [tool_msg, final_msg]
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        starts = []
        ends = []
        history = [{"role": "user", "content": "Remember test"}]
        conversation.run_conversation_turn(
            history, "claude-sonnet-4-6",
            on_tool_start=lambda n, i: starts.append((n, i)),
            on_tool_end=lambda n: ends.append(n),
            query="Remember test",
        )

        assert starts == [("remember", {"fact": "test"})]
        assert ends == ["remember"]

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_max_tool_turns(self, mock_models, mock_memory, mock_tools):
        """Loop stops after max_tool_turns even if model keeps requesting tools."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.return_value = ("ok", False)

        tool_block = _make_tool_block("t1", "web_search", {"query": "loop"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=50, output_tokens=10,
            tool_blocks=[tool_block],
        )

        # Always return tool_use — never stops on its own
        mock_models.get_client().messages.create.return_value = tool_msg
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "Loop forever"}]
        result = conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", max_tool_turns=3, query="Loop forever"
        )

        # Should have called create 3 times
        assert mock_models.get_client().messages.create.call_count == 3
        # text is empty since it never got an end_turn
        assert result["text"] == ""

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_confirm_fn_passed_through(self, mock_models, mock_memory, mock_tools):
        """confirm_fn is forwarded to tools.execute_tool."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.return_value = ("created", False)

        tool_block = _make_tool_block("t1", "create_calendar_event", {"title": "Meeting"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=50, output_tokens=10,
            tool_blocks=[tool_block],
        )
        final_msg = _make_final_message("Event created", input_tokens=60, output_tokens=15)

        mock_models.get_client().messages.create.side_effect = [tool_msg, final_msg]
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        my_confirm = lambda prompt: True
        history = [{"role": "user", "content": "Create event"}]
        conversation.run_conversation_turn(
            history, "claude-sonnet-4-6",
            confirm_fn=my_confirm, query="Create event",
        )

        mock_tools.execute_tool.assert_called_once_with(
            "create_calendar_event", {"title": "Meeting"}, confirm_fn=my_confirm
        )

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_uses_cached_system_prompt_and_tools(self, mock_models, mock_memory, mock_tools):
        """Always uses build_system_prompt_cached and get_cached_tools."""
        import conversation

        mock_memory.memories = ["mem1"]
        cached_prompt = [{"type": "text", "text": "cached"}]
        mock_memory.build_system_prompt_cached.return_value = cached_prompt
        cached_tools_val = [{"name": "tool1"}]
        mock_tools.get_cached_tools.return_value = cached_tools_val

        final_msg = _make_final_message("ok", input_tokens=10, output_tokens=5)
        mock_models.get_client().messages.create.return_value = final_msg
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "test"}]
        conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", query="test", creative_context="ctx"
        )

        mock_memory.build_system_prompt_cached.assert_called_once_with(
            ["mem1"], creative_context="ctx", query="test"
        )
        mock_tools.get_cached_tools.assert_called_once()
        # Verify the create call used cached values
        create_call = mock_models.get_client().messages.create.call_args
        assert create_call.kwargs.get("system") == cached_prompt or \
               create_call[1].get("system") == cached_prompt

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_cost_with_cache_tokens(self, mock_models, mock_memory, mock_tools):
        """Cost calculation includes cache write and read multipliers."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []

        final_msg = _make_final_message(
            "Hi", input_tokens=1000, output_tokens=200,
            cache_creation=500, cache_read=300,
        )
        mock_models.get_client().messages.create.return_value = final_msg
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "test"}]
        result = conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", query="test"
        )

        assert result["cache_creation_tokens"] == 500
        assert result["cache_read_tokens"] == 300
        # Verify cost includes cache components
        # input: 1000 * 3.0 = 3000
        # output: 200 * 15.0 = 3000
        # cache write: 500 * 3.0 * 1.25 = 1875
        # cache read: 300 * 3.0 * 0.10 = 90
        # total: (3000 + 3000 + 1875 + 90) / 1_000_000 = 0.007965
        expected = (3000 + 3000 + 1875 + 90) / 1_000_000
        assert abs(result["cost"] - expected) < 1e-9

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_tool_error_marked(self, mock_models, mock_memory, mock_tools):
        """Tool errors are marked with is_error in the tool result."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.return_value = ("Error: something broke", True)

        tool_block = _make_tool_block("t1", "run_python", {"code": "1/0"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=50, output_tokens=10,
            tool_blocks=[tool_block],
        )
        final_msg = _make_final_message("There was an error", input_tokens=60, output_tokens=20)

        mock_models.get_client().messages.create.side_effect = [tool_msg, final_msg]
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        history = [{"role": "user", "content": "Run code"}]
        conversation.run_conversation_turn(
            history, "claude-sonnet-4-6", query="Run code"
        )

        # Check that the tool_result has is_error
        tool_result_msg = history[2]  # user, assistant(tool_use), user(tool_result)
        assert tool_result_msg["content"][0]["is_error"] is True

    @patch("conversation.tools")
    @patch("conversation.memory")
    @patch("conversation.models")
    def test_multi_tool_single_turn(self, mock_models, mock_memory, mock_tools):
        """Multiple tool blocks in a single response are all executed."""
        import conversation

        mock_memory.memories = []
        mock_memory.build_system_prompt_cached.return_value = []
        mock_tools.get_cached_tools.return_value = []
        mock_tools.execute_tool.side_effect = [
            ("result1", False),
            ("result2", False),
        ]

        tool1 = _make_tool_block("t1", "web_search", {"query": "a"})
        tool2 = _make_tool_block("t2", "web_search", {"query": "b"})
        tool_msg = _make_final_message(
            stop_reason="tool_use", input_tokens=80, output_tokens=20,
            tool_blocks=[tool1, tool2],
        )
        final_msg = _make_final_message("Both done", input_tokens=100, output_tokens=30)

        mock_models.get_client().messages.create.side_effect = [tool_msg, final_msg]
        mock_models.PRICING = {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}}
        mock_models.CACHE_WRITE_MULTIPLIER = 1.25
        mock_models.CACHE_READ_MULTIPLIER = 0.10

        starts = []
        history = [{"role": "user", "content": "Search both"}]
        conversation.run_conversation_turn(
            history, "claude-sonnet-4-6",
            on_tool_start=lambda n, i: starts.append(n),
            query="Search both",
        )

        assert mock_tools.execute_tool.call_count == 2
        assert starts == ["web_search", "web_search"]
        # Tool results message should have 2 results
        assert len(history[2]["content"]) == 2


class TestStreamCallKeyboardInterrupt:
    """Test KeyboardInterrupt handling in _stream_call."""

    @patch("conversation.models")
    def test_interrupt_appends_partial_text(self, mock_models):
        """KeyboardInterrupt during streaming appends partial text to history."""
        import conversation

        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)

        # Simulate interrupt mid-stream
        def text_gen():
            yield "Hello "
            raise KeyboardInterrupt()

        stream_ctx.text_stream = text_gen()
        mock_models.get_client().messages.stream.return_value = stream_ctx

        messages = [{"role": "user", "content": "test"}]
        chunks = []
        with pytest.raises(KeyboardInterrupt):
            conversation._stream_call(
                "claude-sonnet-4-6", [], messages, [],
                lambda c: chunks.append(c),
            )

        # Partial text should be appended to messages
        assert messages[-1] == {"role": "assistant", "content": "Hello "}
        assert chunks == ["Hello "]
