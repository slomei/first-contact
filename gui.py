"""
Gradio web GUI for the chatbot.

Imports core logic from memory, models, tools — run with:
    python gui.py
"""

import json
import gradio as gr

import memory
import models
import tools


class SessionState:
    """Per-session state to avoid mutating module globals."""

    def __init__(self):
        self.conversation_history = []
        self.active_model = "claude-sonnet-4-6"
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0.0


def get_model_choices():
    """Return display-name -> model-id mapping for the dropdown."""
    return ["Sonnet", "Opus", "Haiku"]


MODEL_DISPLAY_TO_ID = {
    "Sonnet": "claude-sonnet-4-6",
    "Opus": "claude-opus-4-6",
    "Haiku": "claude-haiku-4-5",
}

MODEL_ID_TO_DISPLAY = {v: k for k, v in MODEL_DISPLAY_TO_ID.items()}


def format_memories():
    """Format current memories for sidebar display."""
    mems = memory.load_memories()
    if not mems:
        return "*No memories stored.*"
    return "\n".join(f"- {m}" for m in mems)


def execute_tool_gui(name, tool_input):
    """Wraps tools.execute_tool but auto-approves (no confirm_fn = no terminal prompt)."""
    if name == "run_python":
        code = tool_input["code"]
        return tools.run_code_in_workspace(code)
    return tools.execute_tool(name, tool_input)


def user_message(message, history, state):
    """Append the user message to history and return updated state."""
    if not message.strip():
        return "", history, state
    history = history + [{"role": "user", "content": message}]
    state.conversation_history.append({"role": "user", "content": message})
    return "", history, state


def bot_response(history, state):
    """Stream Claude's response, handling tool-use loops."""
    for turn in range(10):
        with models.get_client().messages.stream(
            model=state.active_model,
            max_tokens=4096,
            system=memory.build_system_prompt(memory.memories),
            messages=state.conversation_history,
            tools=tools.TOOLS,
        ) as stream:
            response_text = ""
            # Start a new assistant message for streaming
            history = history + [{"role": "assistant", "content": ""}]
            for text in stream.text_stream:
                response_text += text
                history[-1]["content"] = response_text
                yield history, state, format_cost(state), format_memories()

            final = stream.get_final_message()

        # Track tokens/cost
        inp = final.usage.input_tokens
        out = final.usage.output_tokens
        prices = models.PRICING.get(state.active_model, {"input": 0, "output": 0})
        msg_cost = (inp * prices["input"] + out * prices["output"]) / 1_000_000
        state.input_tokens += inp
        state.output_tokens += out
        state.cost += msg_cost

        if final.stop_reason == "tool_use":
            # Store assistant content blocks
            assistant_content = []
            for block in final.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            state.conversation_history.append({"role": "assistant", "content": assistant_content})

            # Execute tools and show status
            tool_results = []
            for block in final.content:
                if block.type == "tool_use":
                    status = tools.tool_status_text(block.name, block.input)
                    # Show tool status as italic text in the current assistant message
                    history[-1]["content"] = response_text + f"\n\n*{status}...*"
                    yield history, state, format_cost(state), format_memories()

                    result, is_error = execute_tool_gui(block.name, block.input)
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)

            state.conversation_history.append({"role": "user", "content": tool_results})
            # Remove the streaming message — the next loop iteration will add a fresh one
            history = history[:-1]
            continue
        else:
            # Final text response
            state.conversation_history.append({"role": "assistant", "content": response_text})
            yield history, state, format_cost(state), format_memories()
            return

    # Safety: if we hit 10 tool loops, yield what we have
    yield history, state, format_cost(state), format_memories()


def format_cost(state):
    """Format token/cost display for the sidebar."""
    return (
        f"**Tokens:** {state.input_tokens:,} in / {state.output_tokens:,} out\n\n"
        f"**Cost:** ${state.cost:.4f}\n\n"
        f"**Model:** {MODEL_ID_TO_DISPLAY.get(state.active_model, state.active_model)}"
    )


def on_model_change(model_display, state):
    """Handle model dropdown change."""
    state.active_model = MODEL_DISPLAY_TO_ID.get(model_display, "claude-sonnet-4-6")
    return state, format_cost(state)


def new_chat(state):
    """Reset conversation."""
    state.conversation_history = []
    state.input_tokens = 0
    state.output_tokens = 0
    state.cost = 0.0
    return [], state, format_cost(state)


def build_ui():
    """Build and return the Gradio Blocks app."""
    with gr.Blocks(title="Claude Chatbot") as app:
        state = gr.State(SessionState())

        with gr.Row():
            # --- Sidebar ---
            with gr.Column(scale=1, min_width=220):
                gr.Markdown("### Settings")
                model_dropdown = gr.Dropdown(
                    choices=get_model_choices(),
                    value="Sonnet",
                    label="Model",
                    interactive=True,
                )
                new_chat_btn = gr.Button("New Chat")
                cost_display = gr.Markdown(value=format_cost(SessionState()), label="Usage")
                gr.Markdown("### Memories")
                memories_display = gr.Markdown(value=format_memories())

            # --- Main chat area ---
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(
                    height=600,
                )
                msg_input = gr.Textbox(
                    placeholder="Type a message...",
                    show_label=False,
                    container=False,
                )

        # --- Event wiring ---
        msg_submit = msg_input.submit(
            fn=user_message,
            inputs=[msg_input, chatbot, state],
            outputs=[msg_input, chatbot, state],
        ).then(
            fn=bot_response,
            inputs=[chatbot, state],
            outputs=[chatbot, state, cost_display, memories_display],
        )

        model_dropdown.change(
            fn=on_model_change,
            inputs=[model_dropdown, state],
            outputs=[state, cost_display],
        )

        new_chat_btn.click(
            fn=new_chat,
            inputs=[state],
            outputs=[chatbot, state, cost_display],
        )

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(theme=gr.themes.Soft())
