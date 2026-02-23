"""Web UI interface adapter — wraps web_ui/server.py functionality.

Provides the InterfaceAdapter API for the WebSocket-based web UI.
The standalone web_ui/server.py continues to work independently; this adapter
enables uniform dispatch from systems like notifications and daemon.
"""

from interfaces.base_adapter import InterfaceAdapter


class WebAdapter(InterfaceAdapter):
    """Adapter for the Web UI (web_ui/server.py) interface.

    Requires an active WebSocket connection. Typically constructed
    per-connection by web_ui/server.py.
    """

    def __init__(self, websocket=None):
        self._ws = websocket

    async def receive_input(self) -> str:
        if self._ws:
            import json
            raw = await self._ws.recv()
            data = json.loads(raw)
            return data.get("message", "")
        raise NotImplementedError("No WebSocket connection")

    async def send_output(self, message: str) -> None:
        if self._ws:
            import json
            await self._ws.send(json.dumps({"type": "message", "content": message}))

    async def send_file(self, filepath: str, description: str = "") -> None:
        # Web UI doesn't support file push — send as a link/path
        await self.send_output(f"File available: {filepath}" + (f" — {description}" if description else ""))

    async def send_notification(self, message: str, priority: str = "normal") -> None:
        await self.send_output(message)

    def get_interface_name(self) -> str:
        return "web"

    def supports_rich_formatting(self) -> bool:
        return True  # Web UI renders markdown

    def confirm(self, prompt: str) -> bool:
        # Web UI auto-approves (same as web_ui/server.py confirm_fn=None)
        return False
