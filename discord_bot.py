"""
Discord bot for the chatbot.

Imports core logic from chat.py — run with:
    export DISCORD_BOT_TOKEN="your-token"
    python discord_bot.py
"""

import asyncio
import json
import os

import discord

import chat

# Only respond to this Discord user ID
ALLOWED_USER_ID = 000000000000000000

MODEL_DISPLAY_NAMES = {
    "claude-sonnet-4-6": "Sonnet",
    "claude-opus-4-6": "Opus",
    "claude-haiku-4-5": "Haiku",
}


class ChannelState:
    """Per-channel conversation state."""

    def __init__(self):
        self.conversation_history = []
        self.active_model = "claude-sonnet-4-6"
        self.active_persona = "default"
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0.0


# Per-channel state, keyed by channel ID
channel_states = {}


def get_state(channel_id):
    """Get or create state for a channel."""
    if channel_id not in channel_states:
        channel_states[channel_id] = ChannelState()
    return channel_states[channel_id]


def execute_tool_discord(name, tool_input):
    """Wraps chat.execute_tool but auto-approves run_python (no terminal prompt)."""
    if name == "run_python":
        code = tool_input["code"]
        return chat.run_code_in_workspace(code)
    return chat.execute_tool(name, tool_input)


def tool_status_text(name, tool_input):
    """Return a short status string for a tool call."""
    labels = {
        "web_search": f'Searching: "{tool_input.get("query", "")}"',
        "read_file": f'Reading: {tool_input.get("path", "")}',
        "write_file": f'Writing: workspace/{tool_input.get("filename", "")}',
        "remember": f'Remembering: "{tool_input.get("fact", "")}"',
        "forget": f'Forgetting: "{tool_input.get("fact", "")}"',
        "list_memories": "Listing memories",
        "run_python": "Running Python code",
    }
    return labels.get(name, f"Using tool: {name}")


def split_message(text, limit=2000):
    """Split text into chunks that fit within Discord's message limit.

    Splits at newline boundaries when possible.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Find the last newline within the limit
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # No good newline break — split at limit
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def format_cost(inp, out, msg_cost, state):
    """Format cost footer line."""
    return (
        f"*[{inp} in / {out} out — ${msg_cost:.4f} | "
        f"session: ${state.cost:.4f}]*"
    )


async def get_response(state, channel):
    """Get a full response from Claude, handling tool-use loops.

    Returns the final text response with cost footer appended.
    """
    chat.active_persona = state.active_persona

    total_input = 0
    total_output = 0
    total_cost = 0.0

    for turn in range(10):
        response = await asyncio.to_thread(
            chat.client.messages.create,
            model=state.active_model,
            max_tokens=4096,
            system=chat.build_system_prompt(chat.memories),
            messages=state.conversation_history,
            tools=chat.TOOLS,
        )

        # Track tokens/cost
        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        prices = chat.PRICING.get(state.active_model, {"input": 0, "output": 0})
        msg_cost = (inp * prices["input"] + out * prices["output"]) / 1_000_000
        total_input += inp
        total_output += out
        total_cost += msg_cost

        if response.stop_reason == "tool_use":
            # Store assistant content blocks
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            state.conversation_history.append(
                {"role": "assistant", "content": assistant_content}
            )

            # Execute tools, send status messages
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    status = tool_status_text(block.name, block.input)
                    await channel.send(f"*{status}...*")

                    result, is_error = await asyncio.to_thread(
                        execute_tool_discord, block.name, block.input
                    )
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)

            state.conversation_history.append(
                {"role": "user", "content": tool_results}
            )
            continue
        else:
            # Final text response
            response_text = ""
            for block in response.content:
                if block.type == "text":
                    response_text += block.text

            state.conversation_history.append(
                {"role": "assistant", "content": response_text}
            )

            state.input_tokens += total_input
            state.output_tokens += total_output
            state.cost += total_cost

            cost_line = format_cost(total_input, total_output, total_cost, state)
            return f"{response_text}\n\n{cost_line}"

    # Safety: hit 10 tool loops
    state.input_tokens += total_input
    state.output_tokens += total_output
    state.cost += total_cost
    cost_line = format_cost(total_input, total_output, total_cost, state)
    return f"*(Stopped after 10 tool rounds.)*\n\n{cost_line}"


def build_help_text():
    """Build the help message."""
    return (
        "**Available commands:**\n"
        "`!help` — Show this help message\n"
        "`!opus` / `!sonnet` / `!haiku` — Switch model\n"
        "`!persona` — List available personas\n"
        "`!persona <name>` — Switch persona\n"
        "`!memories` — List stored memories\n"
        "`!tokens` — Show conversation size\n"
        "`!web <query>` — Search web + get Claude's take\n"
        "`!new` — Reset conversation history\n\n"
        "Claude also uses tools autonomously (web search, file read/write, memory, code execution)."
    )


def build_persona_list(state):
    """Build a formatted persona list."""
    all_personas = list(chat.BUILTIN_PERSONAS.keys()) + [
        k for k in chat.custom_personas
        if k not in chat.BUILTIN_PERSONAS and "description" in chat.custom_personas[k]
    ]
    lines = ["**Available personas:**"]
    for name in all_personas:
        marker = " **<<**" if name == state.active_persona else ""
        source = (
            "custom"
            if name in chat.custom_personas and name not in chat.BUILTIN_PERSONAS
            else "built-in"
        )
        model_name = chat.MODEL_SHORT_NAMES.get(
            chat.get_persona_model(name), chat.get_persona_model(name)
        )
        lines.append(f"`{name}` ({source}, {model_name}){marker}")
    return "\n".join(lines)


def build_memories_text():
    """Build formatted memories list."""
    mems = chat.load_memories()
    if not mems:
        return "No memories stored."
    lines = ["**Stored memories:**"]
    for i, m in enumerate(mems, 1):
        lines.append(f"{i}. {m}")
    return "\n".join(lines)


def build_tokens_text(state):
    """Build token usage display."""
    # Estimate tokens from this channel's history
    total = 0
    for msg in state.conversation_history:
        content = msg["content"]
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            total += len(json.dumps(content)) // 4

    exchanges = chat.group_into_exchanges(state.conversation_history)
    pct = min(100, int(total / chat.TOKEN_THRESHOLD * 100))
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

    lines = [
        f"**Conversation:** ~{total:,} / {chat.TOKEN_THRESHOLD:,} tokens ({pct}%)",
        f"`[{bar}]`",
        f"{len(exchanges)} exchanges, {len(state.conversation_history)} messages",
    ]
    if total >= chat.TOKEN_THRESHOLD:
        lines.append("Warning: Above threshold — will compress on next response")
    return "\n".join(lines)


# Set up Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    print(f"Discord bot connected as {bot.user}")


@bot.event
async def on_message(message):
    # Ignore own messages
    if message.author == bot.user:
        return

    # Only respond to allowed user
    if message.author.id != ALLOWED_USER_ID:
        return

    # Only respond to messages starting with ! or in DMs
    content = message.content.strip()
    if not content:
        return

    state = get_state(message.channel.id)

    # --- Commands ---
    command_lower = content.lower()

    if command_lower == "!help":
        await message.channel.send(build_help_text())
        return

    if command_lower == "!new":
        state.conversation_history = []
        state.input_tokens = 0
        state.output_tokens = 0
        state.cost = 0.0
        await message.channel.send("*Conversation reset.*")
        return

    if command_lower in ("!opus", "!sonnet", "!haiku"):
        model_map = {
            "!opus": "claude-opus-4-6",
            "!sonnet": "claude-sonnet-4-6",
            "!haiku": "claude-haiku-4-5",
        }
        state.active_model = model_map[command_lower]
        name = MODEL_DISPLAY_NAMES[state.active_model]
        await message.channel.send(f"*Switched to {name}.*")
        return

    if command_lower == "!persona" or command_lower.startswith("!persona "):
        arg = content[8:].strip()
        if not arg:
            await message.channel.send(build_persona_list(state))
        else:
            name = arg.lower()
            persona_exists = name in chat.BUILTIN_PERSONAS or (
                name in chat.custom_personas
                and "description" in chat.custom_personas[name]
            )
            if persona_exists:
                state.active_persona = name
                state.active_model = chat.get_persona_model(name)
                model_name = MODEL_DISPLAY_NAMES.get(
                    state.active_model, state.active_model
                )
                await message.channel.send(
                    f"*Switched to persona: {name} (model: {model_name})*"
                )
            else:
                available = list(chat.BUILTIN_PERSONAS.keys()) + [
                    k
                    for k in chat.custom_personas
                    if k not in chat.BUILTIN_PERSONAS
                    and "description" in chat.custom_personas[k]
                ]
                await message.channel.send(
                    f"Unknown persona: `{name}`\n"
                    f"Available: {', '.join(f'`{p}`' for p in available)}"
                )
        return

    if command_lower == "!memories":
        await message.channel.send(build_memories_text())
        return

    if command_lower == "!tokens":
        await message.channel.send(build_tokens_text(state))
        return

    if command_lower.startswith("!web "):
        query = content[5:].strip()
        if not query:
            await message.channel.send("*Usage: `!web <search query>`*")
            return

        async with message.channel.typing():
            await message.channel.send(f"*Searching: {query}...*")
            try:
                results = await asyncio.to_thread(chat.web_search, query)
            except Exception as e:
                await message.channel.send(f"*Search failed: {e}*")
                return
            if not results:
                await message.channel.send("*No results found.*")
                return

            search_message = (
                f"[Web search: {query}]\n{results}\n\n"
                f"Using these search results, answer my question: {query}"
            )
            state.conversation_history.append(
                {"role": "user", "content": search_message}
            )

            reply = await get_response(state, message.channel)

        for chunk in split_message(reply):
            await message.channel.send(chunk)
        return

    # --- Regular message (not a command) ---
    if content.startswith("!"):
        # Unknown command — ignore to avoid treating as chat
        return

    state.conversation_history.append({"role": "user", "content": content})

    async with message.channel.typing():
        reply = await get_response(state, message.channel)

    for chunk in split_message(reply):
        await message.channel.send(chunk)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: Set DISCORD_BOT_TOKEN environment variable.")
        raise SystemExit(1)
    bot.run(token)
