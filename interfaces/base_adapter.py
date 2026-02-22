"""Abstract base class for First Contact interface adapters.

New interfaces should subclass InterfaceAdapter and implement all
abstract methods. Existing interfaces (terminal, web GUI, Discord,
Telegram) predate this pattern and work independently. They may be
migrated in a future update.

See interfaces/example_adapter.py for a minimal reference implementation.
"""

from abc import ABC, abstractmethod


class InterfaceAdapter(ABC):
    """Base class for First Contact interfaces.

    An interface adapter handles all I/O between the user and the agent.
    All business logic (model routing, tool execution, memory, etc.) lives
    in the shared core modules — the adapter only needs to move messages
    in and out.

    Subclasses must implement all abstract methods below.
    """

    @abstractmethod
    async def receive_input(self) -> str:
        """Receive a message from the user.

        Block until input is available. Return the raw text.
        """
        pass

    @abstractmethod
    async def send_output(self, message: str) -> None:
        """Send a response to the user.

        The message may contain markdown formatting. Strip or convert
        as appropriate for your interface.
        """
        pass

    @abstractmethod
    async def send_file(self, filepath: str, description: str = "") -> None:
        """Send a file to the user.

        filepath: absolute path to the file on disk.
        description: optional human-readable description of the file.
        """
        pass

    @abstractmethod
    async def send_notification(self, message: str, priority: str = "normal") -> None:
        """Send a background notification to the user.

        priority: "high", "normal", or "low". High-priority notifications
        should be delivered immediately; low-priority can be batched.
        """
        pass

    @abstractmethod
    def get_interface_name(self) -> str:
        """Return the name of this interface (e.g., 'terminal', 'discord').

        Used for logging and interface-specific formatting decisions.
        """
        pass

    @abstractmethod
    def supports_rich_formatting(self) -> bool:
        """Whether this interface supports markdown/rich text.

        Return True if the interface can render markdown (bold, italic,
        code blocks, etc.). Return False for plain-text-only interfaces.
        """
        pass

    async def on_startup(self) -> None:
        """Called once when the interface starts. Override for setup logic."""
        pass

    async def on_shutdown(self) -> None:
        """Called once when the interface shuts down. Override for cleanup."""
        pass

    def confirm(self, prompt: str) -> bool:
        """Ask the user for yes/no confirmation.

        Used as the confirm_fn for destructive operations (calendar events,
        file overwrites). Default implementation returns False (deny).
        Override to implement actual confirmation for your interface.
        """
        return False
