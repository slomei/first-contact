"""Example interface adapter — reference implementation.

This is NOT a functional interface. It's a commented reference showing
how to build a new interface using the InterfaceAdapter base class.

To create a real interface:
1. Copy this file and rename it
2. Implement each method for your platform
3. Add the main loop at the bottom
4. Wire up the shared core (memory, models, tools)
"""

# from interfaces import InterfaceAdapter
# import memory
# import models
# import tools
#
#
# class MyAdapter(InterfaceAdapter):
#     """Minimal interface adapter example."""
#
#     def __init__(self):
#         self.conversation_history = []
#
#     async def receive_input(self) -> str:
#         # Read input from your platform
#         # Terminal: input(), Discord: wait for message event, etc.
#         return ""
#
#     async def send_output(self, message: str) -> None:
#         # Send the agent's response to the user
#         # Terminal: print(), Discord: channel.send(), etc.
#         pass
#
#     async def send_file(self, filepath: str, description: str = "") -> None:
#         # Send a file to the user
#         # Terminal: print path, Discord: send as attachment, etc.
#         pass
#
#     async def send_notification(self, message: str, priority: str = "normal") -> None:
#         # Deliver a background notification
#         # Discord: DM the user, Telegram: send message, etc.
#         pass
#
#     def get_interface_name(self) -> str:
#         return "my_interface"
#
#     def supports_rich_formatting(self) -> bool:
#         # True if your interface renders markdown
#         return False
#
#     def confirm(self, prompt: str) -> bool:
#         # Ask the user for yes/no confirmation
#         # This is passed as confirm_fn to tools.execute_tool()
#         return False
#
#
# # --- Main loop skeleton ---
# #
# # async def main():
# #     adapter = MyAdapter()
# #     await adapter.on_startup()
# #
# #     mems = memory.load_all_memories()
# #     system_prompt = memory.build_system_prompt(mems)
# #
# #     while True:
# #         user_input = await adapter.receive_input()
# #         if not user_input:
# #             break
# #
# #         adapter.conversation_history.append({
# #             "role": "user", "content": user_input
# #         })
# #
# #         response = models.get_client().messages.create(
# #             model=models.active_model,
# #             max_tokens=4096,
# #             system=system_prompt,
# #             tools=tools.TOOLS,
# #             messages=adapter.conversation_history,
# #         )
# #
# #         # Handle tool use loop (see chat.py for full implementation)
# #         # ...
# #
# #         await adapter.send_output(response.content[0].text)
# #
# #     await adapter.on_shutdown()
