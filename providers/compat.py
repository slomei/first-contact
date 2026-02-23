"""Anthropic-compatible wrapper types for non-Anthropic providers.

These dataclass-like objects mimic the Anthropic SDK response surface so that
conversation.py, briefing.py, job_scanner.py, and every other caller continues
working unchanged when a different provider is active.
"""


class Usage:
    """Token usage, matching anthropic.types.Usage."""

    def __init__(self, input_tokens, output_tokens, *,
                 cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class TextBlock:
    """A text content block, matching anthropic.types.TextBlock."""

    def __init__(self, text):
        self.type = "text"
        self.text = text


class ToolUseBlock:
    """A tool use content block, matching anthropic.types.ToolUseBlock."""

    def __init__(self, id, name, input):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class Message:
    """A complete response, matching anthropic.types.Message."""

    def __init__(self, content, stop_reason, usage):
        self.content = content          # list of TextBlock / ToolUseBlock
        self.stop_reason = stop_reason  # "end_turn" or "tool_use"
        self.usage = usage              # Usage instance


class StreamWrapper:
    """Context manager wrapping a streaming response.

    Mimics the anthropic stream context manager with .text_stream
    and .get_final_message().
    """

    def __init__(self, chunk_iter, finalize_fn):
        """
        chunk_iter: iterable yielding text strings
        finalize_fn: callable returning a Message after stream ends
        """
        self._chunk_iter = chunk_iter
        self._finalize_fn = finalize_fn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        """Yield text chunks, matching anthropic stream.text_stream."""
        return self._chunk_iter

    def get_final_message(self):
        """Return the complete Message after streaming finishes."""
        return self._finalize_fn()


class MessagesNamespace:
    """Mimics client.messages with .create() and .stream()."""

    def __init__(self, create_fn, stream_fn, batches_ns=None):
        self._create_fn = create_fn
        self._stream_fn = stream_fn
        self.batches = batches_ns

    def create(self, **kwargs):
        """Send a messages request and return a Message."""
        return self._create_fn(**kwargs)

    def stream(self, **kwargs):
        """Send a streaming request and return a StreamWrapper context manager."""
        return self._stream_fn(**kwargs)


class AnthropicCompatClient:
    """Top-level client wrapper with .messages namespace."""

    def __init__(self, messages_ns):
        self.messages = messages_ns
