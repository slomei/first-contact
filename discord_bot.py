"""
Discord bot for the chatbot.

Imports core logic from memory, models, tools — run with:
    export DISCORD_BOT_TOKEN="your-token"
    python discord_bot.py
"""

import asyncio
import json
import os
import re
import shutil
from datetime import datetime

import discord

import memory
import models
import tools

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
        self.active_project = "general"
        self.last_job_results = []
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


def sync_state(state):
    """Sync module globals with this channel's state before operations."""
    memory.active_project = state.active_project
    memory.active_persona = state.active_persona
    memory.memories = memory.load_memories()


def execute_tool_discord(name, tool_input):
    """Wraps tools.execute_tool but auto-approves (no confirm_fn = no terminal prompt)."""
    if name == "run_python":
        code = tool_input["code"]
        return tools.run_code_in_workspace(code)
    return tools.execute_tool(name, tool_input)


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
    sync_state(state)

    total_input = 0
    total_output = 0
    total_cost = 0.0

    for turn in range(10):
        response = await asyncio.to_thread(
            models.client.messages.create,
            model=state.active_model,
            max_tokens=4096,
            system=memory.build_system_prompt(memory.memories),
            messages=state.conversation_history,
            tools=tools.TOOLS,
        )

        # Track tokens/cost
        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        prices = models.PRICING.get(state.active_model, {"input": 0, "output": 0})
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
                    status = tools.tool_status_text(block.name, block.input)
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
        "`!remember <fact>` — Save a fact to memory\n"
        "`!forget <fact>` — Remove a fact from memory\n"
        "`!project` — List projects\n"
        "`!project <name>` — Switch project (creates if needed)\n"
        "`!watch <topic>` — Add a topic to the watchlist\n"
        "`!watch list` — Show watched topics\n"
        "`!watch remove <topic>` — Remove a watched topic\n"
        "`!digest` — Generate a digest from watched topics\n"
        "`!jobs search <query>` — Search job listings\n"
        "`!jobs save` — Save last search results\n"
        "`!jobs list` — Show saved listings\n"
        "`!jobs remove <#>` — Remove a saved listing\n"
        "`!jobs apply <#>` — Generate cover letter\n"
        "`!jobs track <#> <status>` — Set job status\n"
        "`!jobs status` — Show tracked jobs by status\n"
        "`!delegates` — Show specialist agents\n"
        "`!billing` — Show billing link\n"
        "`!conversations` — List saved conversations\n"
        "`!load <#>` — Load a previous conversation\n"
        "`!tokens` — Show conversation size\n"
        "`!web <query>` — Search web + get Claude's take\n"
        "`!new` — Reset conversation history\n\n"
        "Claude also uses tools autonomously (web search, file read/write, memory, code execution)."
    )


def build_persona_list(state):
    """Build a formatted persona list."""
    all_personas = list(memory.BUILTIN_PERSONAS.keys()) + [
        k for k in memory.custom_personas
        if k not in memory.BUILTIN_PERSONAS and "description" in memory.custom_personas[k]
    ]
    lines = ["**Available personas:**"]
    for name in all_personas:
        marker = " **<<**" if name == state.active_persona else ""
        source = (
            "custom"
            if name in memory.custom_personas and name not in memory.BUILTIN_PERSONAS
            else "built-in"
        )
        model_name = models.MODEL_SHORT_NAMES.get(
            memory.get_persona_model(name), memory.get_persona_model(name)
        )
        lines.append(f"`{name}` ({source}, {model_name}){marker}")
    return "\n".join(lines)


def build_memories_text(state):
    """Build formatted memories list."""
    sync_state(state)
    mems = memory.load_memories()
    if not mems:
        return f"No memories stored ({state.active_project})."
    lines = [f"**Stored memories ({state.active_project}):**"]
    for i, m in enumerate(mems, 1):
        lines.append(f"{i}. {m}")
    return "\n".join(lines)


def build_tokens_text(state):
    """Build token usage display."""
    total = 0
    for msg in state.conversation_history:
        content = msg["content"]
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            total += len(json.dumps(content)) // 4

    exchanges = models.group_into_exchanges(state.conversation_history)
    pct = min(100, int(total / models.TOKEN_THRESHOLD * 100))
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

    lines = [
        f"**Conversation:** ~{total:,} / {models.TOKEN_THRESHOLD:,} tokens ({pct}%)",
        f"`[{bar}]`",
        f"{len(exchanges)} exchanges, {len(state.conversation_history)} messages",
    ]
    if total >= models.TOKEN_THRESHOLD:
        lines.append("Warning: Above threshold — will compress on next response")
    return "\n".join(lines)


def build_project_list(state):
    """Build a formatted project list with active marker."""
    sync_state(state)
    projects = memory.list_projects()
    lines = ["**Projects:**"]
    for p in projects:
        marker = " **<<**" if p == state.active_project else ""
        lines.append(f"`{p}`{marker}")
    return "\n".join(lines)


def build_conversations_list(state):
    """Build a numbered conversation list."""
    sync_state(state)
    files = memory.list_conversations()
    if not files:
        return f"No saved conversations ({state.active_project})."
    lines = [f"**Previous conversations ({state.active_project}):**"]
    for i, filename in enumerate(files, 1):
        name = filename.removesuffix(".txt")
        parts = name.split("_", 1)
        if len(parts) == 2:
            date_part, title_slug = parts
            title = title_slug.replace("-", " ").title()
            lines.append(f"{i}. {date_part}  {title}")
        else:
            lines.append(f"{i}. {name}")
    return "\n".join(lines)


def build_delegates_text():
    """Build specialist agents display."""
    lines = ["**Specialist agents:**"]
    for name, spec in models.SPECIALISTS.items():
        lines.append(f"`{name}` — {spec['description']} ({spec['label']})")
    lines.append("\n*The director (Sonnet) routes tasks to specialists automatically.*")
    return "\n".join(lines)


def build_watchlist_text(state):
    """Build watched topics list."""
    sync_state(state)
    topics = memory.load_watchlist()
    if not topics:
        return f"No watched topics ({state.active_project}). Use `!watch <topic>` to add one."
    lines = [f"**Watched topics ({state.active_project}):**"]
    for i, t in enumerate(topics, 1):
        lines.append(f"{i}. {t}")
    return "\n".join(lines)


async def run_digest_discord(state, channel):
    """Run watchlist digest for Discord (sends progress messages)."""
    sync_state(state)
    topics = memory.load_watchlist()
    if not topics:
        return "No topics in watchlist. Use `!watch <topic>` to add one."

    await channel.send(f"*Generating digest for {len(topics)} topic(s)...*")

    all_results = []
    for topic in topics:
        await channel.send(f"*Searching: {topic}...*")
        try:
            results = await asyncio.to_thread(tools.web_search, topic, 3)
            if results:
                all_results.append(f"## {topic}\n{results}")
            else:
                all_results.append(f"## {topic}\nNo results found.")
        except Exception as e:
            all_results.append(f"## {topic}\nSearch failed: {e}")

    combined = "\n\n".join(all_results)

    await channel.send("*Summarizing findings...*")
    try:
        response = await asyncio.to_thread(
            models.client.messages.create,
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content":
                "You are a research digest writer. Summarize the following web search results "
                "into a clear, organized digest. Group by topic, highlight key developments, "
                "and note anything particularly notable. Be concise but thorough.\n\n" + combined}],
        )
        digest = response.content[0].text
    except Exception as e:
        digest = f"Summarization failed: {e}\n\n{combined}"

    # Save to workspace
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"digest-{date_str}.md"
    workspace = memory.get_workspace_dir()
    filepath = os.path.join(workspace, filename)

    header = f"# Digest — {date_str}\n\nTopics: {', '.join(topics)}\n\n---\n\n"
    with open(filepath, "w") as f:
        f.write(header + digest + "\n")

    return f"{digest}\n\n*Saved to {state.active_project}/workspace/{filename}*"


async def load_conversation_discord(state, filepath, channel):
    """Load a conversation file, summarize it, and inject into channel state."""
    sync_state(state)

    with open(filepath, "r") as f:
        raw = f.read()

    if not raw.strip():
        return "*Conversation file is empty.*"

    if len(raw) > 30_000:
        raw = raw[:30_000] + "\n...[truncated]"

    await channel.send("*Summarizing previous conversation...*")
    try:
        summary_response = await asyncio.to_thread(
            models.client.messages.create,
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content":
                "Summarize this conversation into a concise recap (3-5 sentences). "
                "Capture the key topics discussed, any decisions made, and important "
                "context that would help continue the conversation:\n\n" + raw}],
        )
        summary = summary_response.content[0].text
    except Exception as e:
        return f"*Failed to summarize conversation: {e}*"

    state.conversation_history.append({"role": "user",
        "content": f"[Loaded previous conversation summary]\n{summary}"})
    state.conversation_history.append({"role": "assistant",
        "content": "Got it — I have context from our previous conversation. What would you like to pick up on?"})

    return f"*Loaded conversation summary:*\n{summary}"


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
            persona_exists = name in memory.BUILTIN_PERSONAS or (
                name in memory.custom_personas
                and "description" in memory.custom_personas[name]
            )
            if persona_exists:
                state.active_persona = name
                state.active_model = memory.get_persona_model(name)
                model_name = MODEL_DISPLAY_NAMES.get(
                    state.active_model, state.active_model
                )
                await message.channel.send(
                    f"*Switched to persona: {name} (model: {model_name})*"
                )
            else:
                available = list(memory.BUILTIN_PERSONAS.keys()) + [
                    k
                    for k in memory.custom_personas
                    if k not in memory.BUILTIN_PERSONAS
                    and "description" in memory.custom_personas[k]
                ]
                await message.channel.send(
                    f"Unknown persona: `{name}`\n"
                    f"Available: {', '.join(f'`{p}`' for p in available)}"
                )
        return

    if command_lower == "!memories":
        await message.channel.send(build_memories_text(state))
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
                results = await asyncio.to_thread(tools.web_search, query)
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

    # --- Project management ---
    if command_lower == "!project" or command_lower.startswith("!project "):
        arg = content[8:].strip() if len(content) > 8 else ""
        if not arg or arg.lower() == "list":
            await message.channel.send(build_project_list(state))
        else:
            name = re.sub(r'[^\w-]', '-', arg.lower()).strip('-')
            if not name:
                await message.channel.send("*Invalid project name.*")
            else:
                state.active_project = name
                sync_state(state)
                memory.switch_project(name)
                mems = memory.load_memories()
                mem_note = f"\nLoaded {len(mems)} memor{'y' if len(mems) == 1 else 'ies'}." if mems else ""
                await message.channel.send(f"*Switched to project: {name}*{mem_note}")
        return

    # --- Remember / Forget ---
    if command_lower.startswith("!remember "):
        fact = content[10:].strip()
        if not fact:
            await message.channel.send("*Usage: `!remember <fact>`*")
            return
        sync_state(state)
        memory.memories.append(fact)
        memory.save_memories(memory.memories)
        await message.channel.send(f"*Remembered: {fact}*")
        return

    if command_lower.startswith("!forget "):
        fact = content[8:].strip()
        sync_state(state)
        if fact in memory.memories:
            memory.memories.remove(fact)
            memory.save_memories(memory.memories)
            await message.channel.send(f"*Forgot: {fact}*")
        else:
            await message.channel.send("*No matching memory found. Use `!memories` to see stored facts.*")
        return

    # --- Watchlist ---
    if command_lower == "!watch" or command_lower.startswith("!watch "):
        arg = content[6:].strip() if len(content) > 6 else ""
        if not arg or arg.lower() == "list":
            await message.channel.send(build_watchlist_text(state))
        elif arg.lower().startswith("remove "):
            topic = arg[7:].strip()
            sync_state(state)
            topics = memory.load_watchlist()
            if topic in topics:
                topics.remove(topic)
                memory.save_watchlist(topics)
                await message.channel.send(f"*Removed: {topic}*")
            else:
                await message.channel.send(f"*Not found: {topic}. Use `!watch list` to see topics.*")
        else:
            topic = arg.strip()
            sync_state(state)
            topics = memory.load_watchlist()
            if topic in topics:
                await message.channel.send(f"*Already watching: {topic}*")
            else:
                topics.append(topic)
                memory.save_watchlist(topics)
                await message.channel.send(f"*Now watching: {topic}*")
        return

    # --- Digest ---
    if command_lower == "!digest":
        async with message.channel.typing():
            result = await run_digest_discord(state, message.channel)
        for chunk in split_message(result):
            await message.channel.send(chunk)
        return

    # --- Billing ---
    if command_lower == "!billing":
        await message.channel.send(
            "**Check your balance and add credits:**\n"
            "https://platform.claude.com/settings/billing"
        )
        return

    # --- Delegates ---
    if command_lower == "!delegates":
        await message.channel.send(build_delegates_text())
        return

    # --- Conversations ---
    if command_lower == "!conversations":
        await message.channel.send(build_conversations_list(state))
        return

    # --- Load conversation ---
    if command_lower.startswith("!load "):
        num_str = content[6:].strip()
        try:
            idx = int(num_str) - 1
        except ValueError:
            await message.channel.send("*Usage: `!load <#>` — use `!conversations` to see the list.*")
            return
        sync_state(state)
        files = memory.list_conversations()
        if not files:
            await message.channel.send(f"*No saved conversations ({state.active_project}).*")
            return
        if idx < 0 or idx >= len(files):
            await message.channel.send(f"*Invalid number. Use `!conversations` to see the list (1-{len(files)}).*")
            return
        filepath = os.path.join(memory.get_conversations_dir(), files[idx])
        async with message.channel.typing():
            result = await load_conversation_discord(state, filepath, message.channel)
        for chunk in split_message(result):
            await message.channel.send(chunk)
        return

    if command_lower == "!load":
        await message.channel.send("*Usage: `!load <#>` — use `!conversations` to see the list.*")
        return

    # --- Jobs ---
    if command_lower == "!jobs" or command_lower.startswith("!jobs "):
        arg = content[5:].strip() if len(content) > 5 else ""
        arg_lower = arg.lower()

        if not arg:
            await message.channel.send(
                "**Usage:**\n"
                "`!jobs search <query>` — Search job listings\n"
                "`!jobs save` — Save last search results\n"
                "`!jobs list` — Show saved listings\n"
                "`!jobs remove <#>` — Remove a saved listing\n"
                "`!jobs apply <#>` — Generate cover letter\n"
                "`!jobs track <#> <status>` — Set job status\n"
                "`!jobs status` — Show tracked jobs by status"
            )
            return

        if arg_lower.startswith("search "):
            query = arg[7:].strip()
            if not query:
                await message.channel.send("*Usage: `!jobs search <query>`*")
                return
            async with message.channel.typing():
                await message.channel.send(f"*Searching jobs: {query}...*")
                try:
                    results = await asyncio.to_thread(tools.search_jobs, query)
                    state.last_job_results = list(results)
                except Exception as e:
                    await message.channel.send(f"*Search failed: {e}*")
                    return
                if not results:
                    await message.channel.send("*No results found.*")
                    return
                lines = []
                for i, r in enumerate(results, 1):
                    lines.append(f"**{i}. {r['title']}**\n{r['url']}\n{r['body'][:200]}")
                reply = "\n\n".join(lines)
                reply += f"\n\n*Found {len(results)} result(s). Use `!jobs save` to save these.*"
            for chunk in split_message(reply):
                await message.channel.send(chunk)

        elif arg_lower == "save":
            if not state.last_job_results:
                await message.channel.send("*No search results to save. Run `!jobs search <query>` first.*")
                return
            jobs = memory.load_jobs()
            existing_urls = {j["url"] for j in jobs}
            added = 0
            for r in state.last_job_results:
                if r["url"] not in existing_urls:
                    job_entry = {
                        "title": r["title"],
                        "url": r["url"],
                        "body": r["body"],
                        "saved_at": datetime.now().strftime("%Y-%m-%d"),
                        "status": None,
                        "folder": None,
                    }
                    memory.init_job_folder(job_entry)
                    jobs.append(job_entry)
                    added += 1
            memory.save_jobs(jobs)
            msg = f"*Saved {added} new listing(s) to job-search project ({len(jobs)} total).*"
            if added:
                msg += "\n*Job folders: job-search/workspace/jobs/*"
            await message.channel.send(msg)

        elif arg_lower == "list":
            jobs = memory.load_jobs()
            if not jobs:
                await message.channel.send("*No saved jobs. Use `!jobs search <query>` then `!jobs save`.*")
                return
            lines = [f"**Saved job listings ({len(jobs)}):**"]
            for i, j in enumerate(jobs, 1):
                status_tag = f" [{j['status']}]" if j.get("status") else ""
                has_letter = ""
                if j.get("folder"):
                    cl_path = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT,
                                           "workspace", "jobs", j["folder"], "cover-letter.md")
                    if os.path.exists(cl_path):
                        has_letter = " [cover letter]"
                folder_tag = f"  ->  jobs/{j['folder']}/" if j.get("folder") else ""
                lines.append(
                    f"**{i}. {j['title']}**{status_tag}{has_letter}\n"
                    f"{j['url']}\n"
                    f"Saved: {j['saved_at']}{folder_tag}"
                )
            reply = "\n\n".join(lines)
            for chunk in split_message(reply):
                await message.channel.send(chunk)

        elif arg_lower.startswith("remove "):
            num_str = arg[7:].strip()
            try:
                idx = int(num_str) - 1
                jobs = memory.load_jobs()
                if idx < 0 or idx >= len(jobs):
                    raise ValueError
                removed = jobs.pop(idx)
                if removed.get("folder"):
                    folder_path = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT,
                                               "workspace", "jobs", removed["folder"])
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)
                memory.save_jobs(jobs)
                await message.channel.send(f"*Removed: {removed['title']}*")
            except ValueError:
                await message.channel.send("*Invalid number. Use `!jobs list` to see listings.*")

        elif arg_lower.startswith("apply "):
            num_str = arg[6:].strip()
            try:
                idx = int(num_str) - 1
                jobs = memory.load_jobs()
                if idx < 0 or idx >= len(jobs):
                    raise ValueError
            except ValueError:
                await message.channel.send("*Invalid number. Use `!jobs list` to see listings.*")
                return
            job = jobs[idx]

            async with message.channel.typing():
                await message.channel.send(
                    f"**{job['title']}**\n{job['url']}\n\n*Generating cover letter (Opus)...*"
                )
                # Gather memories from current project + general + job-search
                sync_state(state)
                all_memories = list(memory.memories)
                if state.active_project != "general":
                    general_mem = os.path.join(memory.PROJECTS_DIR, "general", "memory.json")
                    if os.path.exists(general_mem):
                        with open(general_mem, "r") as f:
                            all_memories.extend(json.load(f))
                js_mem = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "memory.json")
                if js_mem != memory.get_memory_file() and os.path.exists(js_mem):
                    with open(js_mem, "r") as f:
                        all_memories.extend(json.load(f))
                all_memories = list(dict.fromkeys(all_memories))

                try:
                    letter, cost = await asyncio.to_thread(
                        models.generate_cover_letter, job, all_memories
                    )

                    # Save cover letter to job folder
                    folder = memory.get_job_folder(job)
                    cl_path = os.path.join(folder, "cover-letter.md")
                    with open(cl_path, "w") as f:
                        f.write(f"# Cover Letter — {job['title']}\n\n")
                        f.write(f"**Position:** {job['title']}\n")
                        f.write(f"**URL:** {job['url']}\n")
                        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n")
                        f.write(letter + "\n")

                    # Update listing.json
                    listing_path = os.path.join(folder, "listing.json")
                    with open(listing_path, "w") as f:
                        json.dump({
                            "title": job["title"],
                            "url": job["url"],
                            "description": job["body"],
                            "saved_at": job.get("saved_at"),
                            "status": job.get("status"),
                            "cover_letter_generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }, f, indent=2)

                    memory.save_jobs(jobs)

                    reply = (
                        f"**Cover Letter — {job['title']}**\n\n"
                        f"{letter}\n\n"
                        f"*Saved to: jobs/{job['folder']}/cover-letter.md [${cost:.4f}]*"
                    )
                except Exception as e:
                    reply = f"*Failed to generate cover letter: {e}*"

            for chunk in split_message(reply):
                await message.channel.send(chunk)

        elif arg_lower.startswith("track "):
            parts = arg[6:].strip().split(None, 1)
            if len(parts) != 2:
                await message.channel.send(
                    "*Usage: `!jobs track <#> <status>`*\n"
                    "*Statuses: applied, interviewing, rejected, offer*"
                )
                return
            num_str, status = parts
            try:
                idx = int(num_str) - 1
                jobs = memory.load_jobs()
                if idx < 0 or idx >= len(jobs):
                    raise ValueError
            except ValueError:
                await message.channel.send("*Invalid number. Use `!jobs list` to see listings.*")
                return
            jobs[idx]["status"] = status.lower()
            memory.save_jobs(jobs)
            await message.channel.send(f"*Updated: {jobs[idx]['title']} -> {status.lower()}*")

        elif arg_lower == "status":
            jobs = memory.load_jobs()
            tracked = [j for j in jobs if j.get("status")]
            if not tracked:
                await message.channel.send("*No tracked jobs. Use `!jobs track <#> <status>` to set a status.*")
                return
            groups = {}
            for j in tracked:
                s = j["status"]
                if s not in groups:
                    groups[s] = []
                groups[s].append(j)
            lines = ["**Tracked jobs:**"]
            for status in sorted(groups.keys()):
                lines.append(f"\n**{status.upper()}**")
                for j in groups[status]:
                    lines.append(f"  {j['title']}\n  {j['url']}")
            reply = "\n".join(lines)
            for chunk in split_message(reply):
                await message.channel.send(chunk)

        else:
            await message.channel.send(
                f"*Unknown subcommand: {arg}*\n"
                "*Use: search, save, list, remove, apply, track, status*"
            )
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
