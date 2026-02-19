"""
Simple terminal chatbot using the Anthropic API.

Prerequisites:
    pip install anthropic

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python chat.py
"""

import anthropic
import json
import os
from datetime import datetime
from ddgs import DDGS

# Create the Anthropic client.
# By default, it reads your API key from the ANTHROPIC_API_KEY environment variable.
client = anthropic.Anthropic()

# This list stores the full conversation history.
# The API is stateless, so we send the entire history with every request
# so Claude has context about what was said before.
conversation_history = []

# ANSI color codes for terminal output
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"

# Available models and their shorthand commands
MODELS = {
    "/opus":   "claude-opus-4-6",
    "/sonnet": "claude-sonnet-4-6",
    "/haiku":  "claude-haiku-4-5",
}

# Active model (default: sonnet)
active_model = "claude-sonnet-4-6"

# Pricing per million tokens (USD)
PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input": 0.80, "output": 4.00},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
}

# Reverse lookup: model ID -> short name
MODEL_SHORT_NAMES = {v: k.lstrip("/") for k, v in MODELS.items()}

# Context window compression threshold (estimated tokens)
TOKEN_THRESHOLD = 20_000

# Tool definitions for the Anthropic API
TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Use this when the user asks about "
            "current events, recent news, or anything you're unsure about that "
            "could benefit from up-to-date information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file from the local filesystem. Use this when "
            "the user references a file or asks about file contents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file in the workspace/ directory. Use this when "
            "the user asks you to create, save, or write a file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename relative to workspace/. Can include subdirectories.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a fact to persistent memory. Use this when the user shares a "
            "personal preference, important detail, or explicitly asks you to "
            "remember something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The fact to remember",
                },
            },
            "required": ["fact"],
        },
    },
    {
        "name": "forget",
        "description": (
            "Remove a fact from persistent memory. Use this when the user asks "
            "you to forget something previously remembered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The exact fact to forget (must match a stored memory)",
                },
            },
            "required": ["fact"],
        },
    },
    {
        "name": "list_memories",
        "description": (
            "List all facts stored in persistent memory. Use this when the user "
            "asks what you remember about them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# Running session totals
session_input_tokens = 0
session_output_tokens = 0
session_cost = 0.0


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONVERSATIONS_DIR = os.path.join(BASE_DIR, "conversations")
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")

def load_memories():
    """Load memories from the JSON file."""
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_memories(memories):
    """Save memories to the JSON file."""
    with open(MEMORY_FILE, "w") as f:
        json.dump(memories, f, indent=2)

def build_system_prompt(memories):
    """Build the system prompt, including any stored memories."""
    base = (
        "You are a blunt, witty collaborator. You give honest, direct answers "
        "without sugarcoating. You're not rude for the sake of it—you're just "
        "efficient and real. If something is a bad idea, you say so. If someone's "
        "on the right track, you tell them that too, briefly. You have a dry sense "
        "of humor and zero patience for fluff.\n\n"
        "You have tools available: web search, file read/write, and memory. "
        "Use them autonomously when appropriate. Search the web when asked about "
        "current events or when you're unsure about something factual. Read files "
        "when the user references them. Save facts to memory when the user shares "
        "personal preferences or important details. Don't ask permission—just "
        "use the tools."
    )
    if memories:
        memory_block = "\n".join(f"- {m}" for m in memories)
        base += f"\n\nThings the user has asked you to remember:\n{memory_block}"
    return base

memories = load_memories()

def get_last_response():
    """Get the last assistant response from conversation history."""
    for msg in reversed(conversation_history):
        if msg["role"] == "assistant":
            content = msg["content"]
            if isinstance(content, str):
                return content
            # List of content blocks — extract text
            texts = [b["text"] for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            return "\n".join(texts) if texts else None
    return None

def extract_code_block(text):
    """Extract the first fenced code block from text, or return the full text."""
    import re
    match = re.search(r"```(?:\w*\n)?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

def estimate_conversation_tokens():
    """Estimate total tokens in conversation history (~4 chars per token)."""
    total = 0
    for msg in conversation_history:
        content = msg["content"]
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            total += len(json.dumps(content)) // 4
    return total


def extract_text_from_message(msg):
    """Extract only conversational text from a message, stripping tool blocks."""
    content = msg["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
        return "\n".join(texts) if texts else None
    return None


def group_into_exchanges(messages):
    """Group conversation messages into exchanges.

    An exchange starts with a user text message and includes all subsequent
    messages (tool use rounds) until the next user text message.
    Returns list of (start_idx, end_idx) tuples (inclusive).
    """
    exchanges = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "user":
            content = msg["content"]
            is_tool_result = isinstance(content, list) and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if not is_tool_result:
                start = i
                i += 1
                while i < len(messages):
                    next_msg = messages[i]
                    if next_msg["role"] == "user":
                        next_content = next_msg["content"]
                        is_next_tool = isinstance(next_content, list) and all(
                            isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in next_content
                        )
                        if not is_next_tool:
                            break
                    i += 1
                exchanges.append((start, i - 1))
                continue
        i += 1
    return exchanges


def clean_exchange(messages, start, end):
    """Extract a clean user/assistant pair from an exchange, stripping tool blocks."""
    user_text = extract_text_from_message(messages[start])
    assistant_text = None
    for i in range(end, start - 1, -1):
        if messages[i]["role"] == "assistant":
            assistant_text = extract_text_from_message(messages[i])
            if assistant_text:
                break
    if user_text and assistant_text:
        return [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
    return []


def compress_conversation():
    """Compress conversation history when tokens exceed threshold.

    Keeps the first 3, middle 5, and last 5 exchanges (with tool blocks stripped),
    summarizes the rest using Haiku, and rebuilds the history.
    """
    global conversation_history, session_input_tokens, session_output_tokens, session_cost

    tokens = estimate_conversation_tokens()
    if tokens < TOKEN_THRESHOLD:
        return

    exchanges = group_into_exchanges(conversation_history)
    n = len(exchanges)
    if n <= 13:
        return

    # Determine which exchanges to keep
    first = set(range(3))
    last = set(range(n - 5, n))
    mid_center = n // 2
    mid_start = max(3, mid_center - 2)
    mid_end = min(n - 5, mid_start + 5)
    mid_start = max(3, mid_end - 5)
    middle = set(range(mid_start, mid_end))
    keep = first | middle | last
    remove = sorted(set(range(n)) - keep)

    if not remove:
        return

    # Collect text from removed exchanges for summarization
    summary_parts = []
    for i in remove:
        start, end = exchanges[i]
        for msg in conversation_history[start:end + 1]:
            text = extract_text_from_message(msg)
            if text:
                role = "User" if msg["role"] == "user" else "Assistant"
                if len(text) > 500:
                    text = text[:500] + "..."
                summary_parts.append(f"{role}: {text}")

    if not summary_parts:
        return

    # Summarize using Haiku
    combined = "\n\n".join(summary_parts)
    summary_response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content":
            "Summarize this conversation excerpt into 2-3 concise sentences. "
            "Capture key topics, decisions, and important context:\n\n" + combined}],
    )
    summary = summary_response.content[0].text

    # Track summary cost
    s_in = summary_response.usage.input_tokens
    s_out = summary_response.usage.output_tokens
    s_prices = PRICING.get("claude-haiku-4-5", {"input": 0.80, "output": 4.00})
    s_cost = (s_in * s_prices["input"] + s_out * s_prices["output"]) / 1_000_000
    session_input_tokens += s_in
    session_output_tokens += s_out
    session_cost += s_cost

    # Rebuild conversation history
    new_history = []
    summary_inserted = False

    for i in sorted(keep):
        # Insert summary at first gap between kept exchanges
        if not summary_inserted and i > min(keep) and (i - 1) not in keep:
            new_history.append({"role": "user",
                "content": f"[Summary of earlier conversation: {summary}]"})
            new_history.append({"role": "assistant",
                "content": "Understood, I have the context from our earlier conversation."})
            summary_inserted = True

        start, end = exchanges[i]
        cleaned = clean_exchange(conversation_history, start, end)
        new_history.extend(cleaned)

    # If summary wasn't inserted (no gap detected), prepend it
    if not summary_inserted:
        new_history.insert(0, {"role": "user",
            "content": f"[Summary of earlier conversation: {summary}]"})
        new_history.insert(1, {"role": "assistant",
            "content": "Understood, I have the context from our earlier conversation."})

    old_tokens = tokens
    conversation_history = new_history
    new_tokens = estimate_conversation_tokens()

    print(f"\n{DIM}⟡ Context compressed: ~{old_tokens:,} → ~{new_tokens:,} tokens "
          f"({len(remove)} exchanges summarized, {len(keep)} kept){RESET}")


def web_search(query, max_results=5):
    """Search the web using DuckDuckGo and return formatted results."""
    results = DDGS().text(query, max_results=max_results)
    if not results:
        return None
    lines = []
    for r in results:
        lines.append(f"- {r['title']}\n  {r['href']}\n  {r['body']}")
    return "\n".join(lines)

def execute_tool(name, tool_input):
    """Execute a tool and return (result_string, is_error)."""
    if name == "web_search":
        query = tool_input["query"]
        max_results = tool_input.get("max_results", 5)
        try:
            results = web_search(query, max_results)
            if results:
                return results, False
            return "No results found.", False
        except Exception as e:
            return f"Search failed: {e}", True

    elif name == "read_file":
        filepath = tool_input["path"]
        try:
            with open(filepath, "r") as f:
                contents = f.read()
            return contents, False
        except FileNotFoundError:
            return f"File not found: {filepath}", True
        except IsADirectoryError:
            return f"Path is a directory: {filepath}", True
        except UnicodeDecodeError:
            return f"Cannot read binary file: {filepath}", True

    elif name == "write_file":
        filename = tool_input["filename"]
        content = tool_input["content"]
        if ".." in filename or filename.startswith("/"):
            return "Filename must be relative and stay inside workspace/", True
        filepath = os.path.join(WORKSPACE_DIR, filename)
        os.makedirs(os.path.dirname(filepath) or WORKSPACE_DIR, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        return f"Wrote to workspace/{filename}", False

    elif name == "remember":
        fact = tool_input["fact"]
        memories.append(fact)
        save_memories(memories)
        return f"Remembered: {fact}", False

    elif name == "forget":
        fact = tool_input["fact"]
        if fact in memories:
            memories.remove(fact)
            save_memories(memories)
            return f"Forgot: {fact}", False
        return f"No matching memory found. Current memories: {memories}", True

    elif name == "list_memories":
        if memories:
            return "\n".join(f"- {m}" for m in memories), False
        return "No memories stored.", False

    return f"Unknown tool: {name}", True

def print_tool_status(name, tool_input):
    """Print a dim status line showing what tool Claude is using."""
    labels = {
        "web_search": f"Searching the web: \"{tool_input.get('query', '')}\"",
        "read_file": f"Reading file: {tool_input.get('path', '')}",
        "write_file": f"Writing file: workspace/{tool_input.get('filename', '')}",
        "remember": f"Remembering: \"{tool_input.get('fact', '')}\"",
        "forget": f"Forgetting: \"{tool_input.get('fact', '')}\"",
        "list_memories": "Listing memories",
    }
    label = labels.get(name, f"Using tool: {name}")
    print(f"\n{DIM}⟡ {label}{RESET}")

def chat_turn():
    """Run a chat turn with tool use support. Streams response, handles tool calls in a loop."""
    global session_input_tokens, session_output_tokens, session_cost

    total_input = 0
    total_output = 0
    total_cost = 0

    for turn in range(10):  # safety cap to prevent runaway loops
        if turn == 0:
            print(f"\n{CYAN}Claude:{RESET} ", end="", flush=True)

        with client.messages.stream(
            model=active_model,
            max_tokens=4096,
            system=build_system_prompt(memories),
            messages=conversation_history,
            tools=TOOLS,
        ) as stream:
            response_text = ""
            for text in stream.text_stream:
                print(text, end="", flush=True)
                response_text += text

            final = stream.get_final_message()

        # Accumulate costs
        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens
        prices = PRICING.get(active_model, {"input": 0, "output": 0})
        msg_cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
        total_input += input_tokens
        total_output += output_tokens
        total_cost += msg_cost

        if final.stop_reason == "tool_use":
            # Store assistant message with full content blocks (needed by API)
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
            conversation_history.append({"role": "assistant", "content": assistant_content})

            # Execute each tool, show status, collect results
            tool_results = []
            for block in final.content:
                if block.type == "tool_use":
                    print_tool_status(block.name, block.input)
                    result, is_error = execute_tool(block.name, block.input)
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)
            conversation_history.append({"role": "user", "content": tool_results})
            continue
        else:
            # end_turn or max_tokens — store final response as plain string
            conversation_history.append({"role": "assistant", "content": response_text})
            break

    # Update session totals
    session_input_tokens += total_input
    session_output_tokens += total_output
    session_cost += total_cost

    # Show cost
    print(f"\n{DIM}  [{total_input} in / {total_output} out — ${total_cost:.4f}]  "
          f"session: ${session_cost:.4f}{RESET}\n")

def print_session_summary():
    """Print a final cost summary for the session."""
    if session_input_tokens or session_output_tokens:
        print(f"{DIM}Session total: {session_input_tokens} in / {session_output_tokens} out — "
              f"${session_cost:.4f}{RESET}")

def save_conversation(history):
    """Save the conversation history to a timestamped text file."""
    if not history:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(CONVERSATIONS_DIR, f"{timestamp}.txt")
    with open(filepath, "w") as f:
        for msg in history:
            role = "You" if msg["role"] == "user" else "Claude"
            content = msg["content"]
            if isinstance(content, str):
                f.write(f"{role}: {content}\n\n")
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            args = json.dumps(block.get("input", {}))
                            parts.append(f"[tool call: {block['name']}({args})]")
                        elif block.get("type") == "tool_result":
                            snippet = block.get("content", "")
                            if len(snippet) > 200:
                                snippet = snippet[:200] + "..."
                            parts.append(f"[tool result: {snippet}]")
                if parts:
                    f.write(f"{role}: {' '.join(parts)}\n\n")
    print(f"Conversation saved to {filepath}")


def list_conversations():
    """Return sorted list of conversation filenames, or empty list."""
    files = [f for f in sorted(os.listdir(CONVERSATIONS_DIR)) if f.endswith(".txt")]
    return files


def print_conversations(files):
    """Print a numbered list of conversation files."""
    for i, filename in enumerate(files, 1):
        name = filename.removesuffix(".txt")
        print(f"  {i}. {name}")


def load_conversation(filepath):
    """Load a conversation file, summarize it with Haiku, and inject into history."""
    global session_input_tokens, session_output_tokens, session_cost

    with open(filepath, "r") as f:
        raw = f.read()

    if not raw.strip():
        print(f"{DIM}Conversation file is empty.{RESET}\n")
        return

    # Truncate if very long to stay within Haiku's context
    if len(raw) > 30_000:
        raw = raw[:30_000] + "\n...[truncated]"

    print(f"{DIM}Summarizing previous conversation...{RESET}")
    summary_response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content":
            "Summarize this conversation into a concise recap (3-5 sentences). "
            "Capture the key topics discussed, any decisions made, and important "
            "context that would help continue the conversation:\n\n" + raw}],
    )
    summary = summary_response.content[0].text

    # Track cost
    s_in = summary_response.usage.input_tokens
    s_out = summary_response.usage.output_tokens
    s_prices = PRICING.get("claude-haiku-4-5", {"input": 0.80, "output": 4.00})
    s_cost = (s_in * s_prices["input"] + s_out * s_prices["output"]) / 1_000_000
    session_input_tokens += s_in
    session_output_tokens += s_out
    session_cost += s_cost

    # Inject summary into conversation history
    conversation_history.append({"role": "user",
        "content": f"[Loaded previous conversation summary]\n{summary}"})
    conversation_history.append({"role": "assistant",
        "content": "Got it — I have context from our previous conversation. What would you like to pick up on?"})

    print(f"{DIM}⟡ Loaded conversation summary ({s_in} in / {s_out} out — ${s_cost:.4f}){RESET}")
    print(f"{DIM}{summary}{RESET}\n")


# Show previous conversations if any exist
existing = list_conversations()
if existing:
    print("Previous conversations:")
    print_conversations(existing)
    print()

HELP_TEXT = f"""{DIM}Available commands:
  /help              Show this help message
  /read <path>       Load a file into the conversation
  /web <query>       Search the web and discuss results
  /write <file>      Save last response to workspace/<file>
  /remember <fact>   Save a fact to persistent memory
  /forget <fact>     Remove a fact from memory
  /memories          List all stored memories
  /load              Load a previous conversation into context
  /conversations     List previous conversations
  /tokens            Show conversation size and compression status
  /opus              Switch to Claude Opus
  /sonnet            Switch to Claude Sonnet
  /haiku             Switch to Claude Haiku
  quit / exit        End the conversation

Claude also uses tools autonomously (web search, file read/write, memory).{RESET}"""

if memories:
    print(f"Loaded {len(memories)} memor{'y' if len(memories) == 1 else 'ies'} from memory.json")
print("Chatbot ready! Type your message and press Enter.")
print("Type /help to see available commands.\n")

while True:
    # Get input from the user
    short_name = MODEL_SHORT_NAMES.get(active_model, active_model)
    try:
        user_input = input(f"{GREEN}You {DIM}[{short_name}]{RESET}{GREEN}: {RESET}")
    except (EOFError, KeyboardInterrupt):
        # Handle Ctrl+D or Ctrl+C gracefully
        print()
        print_session_summary()
        save_conversation(conversation_history)
        print("Goodbye!")
        break

    # Check if the user wants to quit
    if user_input.strip().lower() in ("quit", "exit"):
        print_session_summary()
        save_conversation(conversation_history)
        print("Goodbye!")
        break

    # Check for commands
    command = user_input.strip()
    command_lower = command.lower()

    if command_lower == "/help":
        print(HELP_TEXT)
        continue

    if command_lower in MODELS:
        active_model = MODELS[command_lower]
        print(f"{DIM}Switched to {active_model}{RESET}\n")
        continue

    if command_lower.startswith("/read "):
        filepath = command[6:].strip()  # preserve original case for path
        try:
            with open(filepath, "r") as f:
                contents = f.read()
            line_count = contents.count("\n") + (1 if contents and not contents.endswith("\n") else 0)
            filename = os.path.basename(filepath)
            print(f"{DIM}Loaded {filename} ({line_count} lines){RESET}\n")
            file_message = f"[File: {filepath}]\n```\n{contents}\n```"
            conversation_history.append({"role": "user", "content": file_message})
        except FileNotFoundError:
            print(f"{DIM}File not found: {filepath}{RESET}\n")
        except IsADirectoryError:
            print(f"{DIM}Path is a directory: {filepath}{RESET}\n")
        except UnicodeDecodeError:
            print(f"{DIM}Cannot read binary file: {filepath}{RESET}\n")
        continue

    if command_lower.startswith("/web "):
        query = command[5:].strip()
        if not query:
            print(f"{DIM}Usage: /web <search query>{RESET}\n")
            continue
        print(f"{DIM}Searching: {query}...{RESET}")
        try:
            results = web_search(query)
        except Exception as e:
            print(f"{DIM}Search failed: {e}{RESET}\n")
            continue
        if not results:
            print(f"{DIM}No results found.{RESET}\n")
            continue
        print(f"{DIM}{results}{RESET}\n")
        search_message = f"[Web search: {query}]\n{results}\n\nUsing these search results, answer my question: {query}"
        conversation_history.append({"role": "user", "content": search_message})
        # Get Claude's take on the results
        chat_turn()
        compress_conversation()
        continue

    if command_lower.startswith("/write "):
        filename = command[7:].strip()
        if not filename:
            print(f"{DIM}Usage: /write <filename>{RESET}\n")
            continue
        # Prevent path traversal outside workspace
        if ".." in filename or filename.startswith("/"):
            print(f"{DIM}Filename must be relative and stay inside workspace/{RESET}\n")
            continue
        filepath = os.path.join(WORKSPACE_DIR, filename)
        # Create subdirectories if the filename includes them
        os.makedirs(os.path.dirname(filepath) or WORKSPACE_DIR, exist_ok=True)
        # Check for overwrite
        if os.path.exists(filepath):
            try:
                confirm = input(f"{DIM}workspace/{filename} already exists. Overwrite? [y/N]: {RESET}")
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}Cancelled.{RESET}\n")
                continue
            if confirm.strip().lower() != "y":
                print(f"{DIM}Cancelled.{RESET}\n")
                continue
        # Get content from last Claude response
        last = get_last_response()
        if not last:
            print(f"{DIM}No Claude response to save yet.{RESET}\n")
            continue
        content = extract_code_block(last)
        with open(filepath, "w") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        line_count = content.count("\n") + 1
        print(f"{DIM}Wrote {line_count} lines to workspace/{filename}{RESET}\n")
        continue

    if command_lower.startswith("/remember "):
        fact = command[10:].strip()
        if fact:
            memories.append(fact)
            save_memories(memories)
            print(f"{DIM}Remembered: {fact}{RESET}\n")
        else:
            print(f"{DIM}Usage: /remember <fact>{RESET}\n")
        continue

    if command_lower.startswith("/forget "):
        fact = command[8:].strip()
        if fact in memories:
            memories.remove(fact)
            save_memories(memories)
            print(f"{DIM}Forgot: {fact}{RESET}\n")
        else:
            print(f"{DIM}No matching memory found. Use /memories to see stored facts.{RESET}\n")
        continue

    if command_lower == "/memories":
        if memories:
            print(f"{DIM}Stored memories:")
            for i, m in enumerate(memories, 1):
                print(f"  {i}. {m}")
            print(RESET)
        else:
            print(f"{DIM}No memories stored. Use /remember <fact> to add one.{RESET}\n")
        continue

    if command_lower == "/conversations":
        files = list_conversations()
        if files:
            print(f"{DIM}Previous conversations:")
            print_conversations(files)
            print(RESET)
        else:
            print(f"{DIM}No saved conversations yet.{RESET}\n")
        continue

    if command_lower == "/load":
        files = list_conversations()
        if not files:
            print(f"{DIM}No saved conversations to load.{RESET}\n")
            continue
        print(f"{DIM}Previous conversations:")
        print_conversations(files)
        print(RESET)
        try:
            choice = input(f"{DIM}Load conversation #: {RESET}")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Cancelled.{RESET}\n")
            continue
        try:
            idx = int(choice.strip()) - 1
            if idx < 0 or idx >= len(files):
                raise ValueError
        except ValueError:
            print(f"{DIM}Invalid choice.{RESET}\n")
            continue
        filepath = os.path.join(CONVERSATIONS_DIR, files[idx])
        load_conversation(filepath)
        continue

    if command_lower == "/tokens":
        tokens = estimate_conversation_tokens()
        exchanges = group_into_exchanges(conversation_history)
        pct = min(100, int(tokens / TOKEN_THRESHOLD * 100))
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"{DIM}Conversation: ~{tokens:,} / {TOKEN_THRESHOLD:,} tokens ({pct}%)")
        print(f"  [{bar}]")
        print(f"  {len(exchanges)} exchanges, {len(conversation_history)} messages")
        if tokens >= TOKEN_THRESHOLD:
            print(f"  ⚠ Above threshold — will compress on next response")
        print(RESET)
        continue

    # Skip empty messages
    if not command:
        continue

    # Add the user's message to the conversation history
    conversation_history.append({"role": "user", "content": user_input})

    # Send the conversation to Claude with tool use support
    chat_turn()
    compress_conversation()
