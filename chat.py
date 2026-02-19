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
import re
import subprocess
import tempfile
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

# Active persona (default: default)
active_persona = "default"

# Active project (default: general)
active_project = "general"

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
            "Write content to a file in the project's workspace/ directory. Use this when "
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
    {
        "name": "run_python",
        "description": (
            "Run Python code in the project's workspace/ directory. Use this when the user "
            "asks you to execute, run, or test code. The code runs in a sandboxed "
            "environment with a 30-second timeout."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute",
                },
            },
            "required": ["code"],
        },
    },
]

# Running session totals
session_input_tokens = 0
session_output_tokens = 0
session_cost = 0.0


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECTS_DIR = os.path.join(BASE_DIR, "projects")

PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")


def get_project_dir():
    """Return the directory for the active project, creating it if needed."""
    d = os.path.join(PROJECTS_DIR, active_project)
    os.makedirs(d, exist_ok=True)
    return d


def get_conversations_dir():
    """Return the conversations directory for the active project."""
    d = os.path.join(get_project_dir(), "conversations")
    os.makedirs(d, exist_ok=True)
    return d


def get_workspace_dir():
    """Return the workspace directory for the active project."""
    d = os.path.join(get_project_dir(), "workspace")
    os.makedirs(d, exist_ok=True)
    return d


def get_memory_file():
    """Return the memory file path for the active project."""
    return os.path.join(get_project_dir(), "memory.json")


def get_watchlist_file():
    """Return the watchlist file path for the active project."""
    return os.path.join(get_project_dir(), "watchlist.json")


BUILTIN_PERSONAS = {
    "default": (
        "You are a blunt, witty collaborator. You give honest, direct answers "
        "without sugarcoating. You're not rude for the sake of it—you're just "
        "efficient and real. If something is a bad idea, you say so. If someone's "
        "on the right track, you tell them that too, briefly. You have a dry sense "
        "of humor and zero patience for fluff."
    ),
    "writer": (
        "You are a screenplay collaborator. You focus on dialogue, structure, "
        "pacing, and character voice. You give feedback like a seasoned writer's "
        "room partner—direct, constructive, and always in service of the story. "
        "You think in terms of scenes, beats, and subtext."
    ),
    "coder": (
        "You are a coding partner. You explain concepts clearly, write clean "
        "and well-structured code, and think through edge cases. You prefer "
        "practical solutions over clever ones. When reviewing code, you focus "
        "on correctness, readability, and maintainability."
    ),
    "critic": (
        "You are a brutally honest critic. You don't sugarcoat anything. You "
        "find weaknesses, logical gaps, and mediocrity. Your feedback is harsh "
        "but always specific and actionable. You have high standards and zero "
        "tolerance for hand-waving or half-baked ideas."
    ),
}

# Default models for built-in personas
BUILTIN_PERSONA_MODELS = {
    "default": "claude-sonnet-4-6",
    "writer":  "claude-opus-4-6",
    "coder":   "claude-opus-4-6",
    "critic":  "claude-sonnet-4-6",
}

def load_personas():
    """Load custom personas from the JSON file.

    Supports both old format (string values) and new format (dict with
    'description' and optional 'model' keys).
    """
    if os.path.exists(PERSONAS_FILE):
        with open(PERSONAS_FILE, "r") as f:
            data = json.load(f)
        # Migrate old format: bare string values become {"description": string}
        migrated = {}
        for k, v in data.items():
            if isinstance(v, str):
                migrated[k] = {"description": v}
            else:
                migrated[k] = v
        return migrated
    return {}

def save_personas(personas):
    """Save custom personas to the JSON file."""
    with open(PERSONAS_FILE, "w") as f:
        json.dump(personas, f, indent=2)

custom_personas = load_personas()


def get_persona_model(name):
    """Get the default model for a persona.

    Checks for a user override in custom_personas first, then falls back
    to the built-in default, then to sonnet.
    """
    if name in custom_personas and "model" in custom_personas[name]:
        return custom_personas[name]["model"]
    return BUILTIN_PERSONA_MODELS.get(name, "claude-sonnet-4-6")


def load_memories():
    """Load memories from the active project's memory file."""
    path = get_memory_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def save_memories(memories):
    """Save memories to the active project's memory file."""
    path = get_memory_file()
    with open(path, "w") as f:
        json.dump(memories, f, indent=2)

def build_system_prompt(memories):
    """Build the system prompt, including any stored memories."""
    # Look up persona: built-in first, then custom, fall back to default
    if active_persona in BUILTIN_PERSONAS:
        personality = BUILTIN_PERSONAS[active_persona]
    elif active_persona in custom_personas and "description" in custom_personas[active_persona]:
        personality = custom_personas[active_persona]["description"]
    else:
        personality = BUILTIN_PERSONAS["default"]

    tools_paragraph = (
        "You have tools available: web search, file read/write, memory, and "
        "Python code execution. Use them autonomously when appropriate. Search "
        "the web when asked about current events or when you're unsure about "
        "something factual. Read files when the user references them. Save facts "
        "to memory when the user shares personal preferences or important details. "
        "Run Python code when the user asks you to execute, test, or demonstrate "
        "code. Don't ask permission—just use the tools."
    )

    base = personality + "\n\n" + tools_paragraph
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
    match = re.search(r"```(?:\w*\n)?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

def extract_python_block(text):
    """Extract a Python code block from text. Prefers ```python blocks, falls back to any fenced block.
    Returns None if no code block found."""
    # Try ```python first
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fall back to any fenced block
    match = re.search(r"```(?:\w*\n)?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

def run_code_in_workspace(code):
    """Run Python code in a temp file inside the project's workspace/."""
    workspace = get_workspace_dir()
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=workspace)
        with os.fdopen(fd, "w") as f:
            f.write(code)
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=30, cwd=workspace,
        )
        output = result.stdout
        if result.stderr:
            output += result.stderr
        output = output.strip()
        if not output:
            output = "(no output)"
        return output, result.returncode != 0
    except subprocess.TimeoutExpired:
        return "Execution timed out (30s limit).", True
    except Exception as e:
        return f"Execution failed: {e}", True
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

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
        workspace = get_workspace_dir()
        filepath = os.path.join(workspace, filename)
        os.makedirs(os.path.dirname(filepath) or workspace, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        return f"Wrote to {active_project}/workspace/{filename}", False

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

    elif name == "run_python":
        code = tool_input["code"]
        print(f"\n{CYAN}Code to execute:{RESET}")
        print(f"{CYAN}{code}{RESET}")
        try:
            confirm = input(f"\n{DIM}Run this code? [y/N]: {RESET}")
        except (EOFError, KeyboardInterrupt):
            print()
            return "User declined to run this code.", False
        if confirm.strip().lower() != "y":
            return "User declined to run this code.", False
        return run_code_in_workspace(code)

    return f"Unknown tool: {name}", True

def print_tool_status(name, tool_input):
    """Print a dim status line showing what tool Claude is using."""
    labels = {
        "web_search": f"Searching the web: \"{tool_input.get('query', '')}\"",
        "read_file": f"Reading file: {tool_input.get('path', '')}",
        "write_file": f"Writing file: {active_project}/workspace/{tool_input.get('filename', '')}",
        "remember": f"Remembering: \"{tool_input.get('fact', '')}\"",
        "forget": f"Forgetting: \"{tool_input.get('fact', '')}\"",
        "list_memories": "Listing memories",
        "run_python": "Running Python code",
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


def slugify(text):
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')[:60]


def generate_title(history):
    """Use Haiku to generate a short title for a conversation."""
    global session_input_tokens, session_output_tokens, session_cost

    parts = []
    for msg in history:
        text = extract_text_from_message(msg)
        if text:
            role = "User" if msg["role"] == "user" else "Assistant"
            snippet = text[:300] + "..." if len(text) > 300 else text
            parts.append(f"{role}: {snippet}")

    if not parts:
        return "untitled conversation"

    combined = "\n".join(parts[:20])
    if len(combined) > 5000:
        combined = combined[:5000] + "..."

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=30,
            messages=[{"role": "user", "content":
                "Generate a short descriptive title (5-8 words) for this conversation. "
                "Reply with ONLY the title, no quotes or punctuation:\n\n" + combined}],
        )
        title = response.content[0].text.strip().strip('"\'')

        s_in = response.usage.input_tokens
        s_out = response.usage.output_tokens
        s_prices = PRICING.get("claude-haiku-4-5", {"input": 0.80, "output": 4.00})
        s_cost = (s_in * s_prices["input"] + s_out * s_prices["output"]) / 1_000_000
        session_input_tokens += s_in
        session_output_tokens += s_out
        session_cost += s_cost

        return title
    except Exception:
        return "untitled conversation"


def save_conversation(history):
    """Save conversation with auto-generated title."""
    if not history:
        return

    print(f"{DIM}Generating conversation title...{RESET}")
    title = generate_title(history)
    slug = slugify(title)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}_{slug}.txt"

    conversations_dir = get_conversations_dir()
    filepath = os.path.join(conversations_dir, filename)

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

    print(f"Conversation saved: {title}")
    print(f"{DIM}  → {active_project}/conversations/{filename}{RESET}")


def list_conversations():
    """Return sorted list of conversation filenames, or empty list."""
    conversations_dir = get_conversations_dir()
    files = [f for f in sorted(os.listdir(conversations_dir)) if f.endswith(".txt")]
    return files


def print_conversations(files):
    """Print a numbered list of conversation files with titles."""
    for i, filename in enumerate(files, 1):
        name = filename.removesuffix(".txt")
        # Parse "YYYY-MM-DD_title-slug" or "YYYY-MM-DD_HH-MM-SS" format
        parts = name.split("_", 1)
        if len(parts) == 2:
            date_part, title_slug = parts
            # Convert slug back to readable title
            title = title_slug.replace("-", " ").title()
            print(f"  {i}. {date_part}  {title}")
        else:
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


def load_watchlist():
    """Load watchlist from the active project's watchlist.json."""
    path = get_watchlist_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def save_watchlist(topics):
    """Save watchlist to the active project's watchlist.json."""
    path = get_watchlist_file()
    with open(path, "w") as f:
        json.dump(topics, f, indent=2)


def run_digest():
    """Search web for all watched topics and generate a digest."""
    global session_input_tokens, session_output_tokens, session_cost

    topics = load_watchlist()
    if not topics:
        print(f"{DIM}No topics in watchlist. Use /watch <topic> to add one.{RESET}\n")
        return

    print(f"{DIM}Generating digest for {len(topics)} topic(s)...{RESET}")

    all_results = []
    for topic in topics:
        print(f"{DIM}  Searching: {topic}...{RESET}")
        try:
            results = web_search(topic, max_results=3)
            if results:
                all_results.append(f"## {topic}\n{results}")
            else:
                all_results.append(f"## {topic}\nNo results found.")
        except Exception as e:
            all_results.append(f"## {topic}\nSearch failed: {e}")

    combined = "\n\n".join(all_results)

    print(f"{DIM}  Summarizing findings...{RESET}")
    cost_str = "$0.0000"
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content":
                "You are a research digest writer. Summarize the following web search results "
                "into a clear, organized digest. Group by topic, highlight key developments, "
                "and note anything particularly notable. Be concise but thorough.\n\n" + combined}],
        )
        digest = response.content[0].text

        s_in = response.usage.input_tokens
        s_out = response.usage.output_tokens
        s_prices = PRICING.get("claude-haiku-4-5", {"input": 0.80, "output": 4.00})
        s_cost = (s_in * s_prices["input"] + s_out * s_prices["output"]) / 1_000_000
        session_input_tokens += s_in
        session_output_tokens += s_out
        session_cost += s_cost
        cost_str = f"${s_cost:.4f}"
    except Exception as e:
        print(f"{DIM}Summarization failed: {e}{RESET}")
        digest = combined

    # Save to workspace
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"digest-{date_str}.md"
    workspace = get_workspace_dir()
    filepath = os.path.join(workspace, filename)

    header = f"# Digest — {date_str}\n\nTopics: {', '.join(topics)}\n\n---\n\n"
    with open(filepath, "w") as f:
        f.write(header + digest + "\n")

    print(f"\n{digest}")
    print(f"\n{DIM}Digest saved to {active_project}/workspace/{filename} ({cost_str}){RESET}\n")


def switch_project(name):
    """Switch to a project, creating it if needed."""
    global active_project, memories
    active_project = name
    # Ensure project directories exist
    get_conversations_dir()
    get_workspace_dir()
    # Reload memories for this project
    memories = load_memories()


def list_projects():
    """List all project names."""
    if not os.path.exists(PROJECTS_DIR):
        return ["general"]
    projects = sorted([
        d for d in os.listdir(PROJECTS_DIR)
        if os.path.isdir(os.path.join(PROJECTS_DIR, d))
    ])
    return projects if projects else ["general"]


if __name__ == "__main__":
    # Initialize project system
    switch_project("general")

    # Show previous conversations if any exist
    existing = list_conversations()
    if existing:
        print(f"Previous conversations ({active_project}):")
        print_conversations(existing)
        print()

    HELP_TEXT = f"""{DIM}Available commands:
      /help              Show this help message
      /read <path>       Load a file into the conversation
      /web <query>       Search the web and discuss results
      /write <file>      Save last response to workspace/<file>
      /run               Run the code block from Claude's last response
      /remember <fact>   Save a fact to persistent memory
      /forget <fact>     Remove a fact from memory
      /memories          List all stored memories
      /persona           List available personas
      /persona <name>    Switch persona (default, writer, coder, critic)
      /persona custom <desc>  Create a custom persona
      /persona model <name> <model>  Set a persona's default model
      /project           Create a new project (prompts for name)
      /project <name>    Switch to a project (creates if needed)
      /project list      List all projects
      /watch <topic>     Add a topic to the watchlist
      /watch list        Show all watched topics
      /watch remove <topic>  Remove a topic from the watchlist
      /digest            Search web for watched topics and save a digest
      /load              Load a previous conversation into context
      /conversations     List previous conversations
      /tokens            Show conversation size and compression status
      /opus              Switch to Claude Opus
      /sonnet            Switch to Claude Sonnet
      /haiku             Switch to Claude Haiku
      quit / exit        End the conversation

    Claude also uses tools autonomously (web search, file read/write, memory, code execution).{RESET}"""

    if memories:
        print(f"Loaded {len(memories)} memor{'y' if len(memories) == 1 else 'ies'} from {active_project}/memory.json")
    print("Chatbot ready! Type your message and press Enter.")
    print("Type /help to see available commands.\n")

    while True:
        # Get input from the user
        short_name = MODEL_SHORT_NAMES.get(active_model, active_model)
        persona_tag = f"/{active_persona}" if active_persona != "default" else ""
        try:
            user_input = input(f"{GREEN}You {DIM}[{short_name}{persona_tag}/{active_project}]{RESET}{GREEN}: {RESET}")
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
            workspace = get_workspace_dir()
            filepath = os.path.join(workspace, filename)
            # Create subdirectories if the filename includes them
            os.makedirs(os.path.dirname(filepath) or workspace, exist_ok=True)
            # Check for overwrite
            if os.path.exists(filepath):
                try:
                    confirm = input(f"{DIM}{active_project}/workspace/{filename} already exists. Overwrite? [y/N]: {RESET}")
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
            print(f"{DIM}Wrote {line_count} lines to {active_project}/workspace/{filename}{RESET}\n")
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
                print(f"{DIM}Stored memories ({active_project}):")
                for i, m in enumerate(memories, 1):
                    print(f"  {i}. {m}")
                print(RESET)
            else:
                print(f"{DIM}No memories stored. Use /remember <fact> to add one.{RESET}\n")
            continue

        if command_lower == "/persona" or command_lower.startswith("/persona "):
            arg = command[8:].strip()  # everything after "/persona"
            if not arg:
                # List all personas, highlight active
                print(f"{DIM}Available personas:")
                all_personas = list(BUILTIN_PERSONAS.keys()) + [
                    k for k in custom_personas if k not in BUILTIN_PERSONAS
                    and "description" in custom_personas[k]
                ]
                for name in all_personas:
                    marker = " ←" if name == active_persona else ""
                    source = "custom" if name in custom_personas and name not in BUILTIN_PERSONAS else "built-in"
                    model_name = MODEL_SHORT_NAMES.get(get_persona_model(name), get_persona_model(name))
                    print(f"  {name} ({source}, {model_name}){marker}")
                print(RESET)
            elif arg.lower().startswith("model "):
                # Set a persona's default model: /persona model <name> <model>
                parts = arg[6:].strip().split()
                model_map = {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
                if len(parts) != 2:
                    print(f"{DIM}Usage: /persona model <name> <opus|sonnet|haiku>{RESET}\n")
                else:
                    pname = parts[0].lower()
                    model_arg = parts[1].lower()
                    persona_exists = (pname in BUILTIN_PERSONAS or
                        (pname in custom_personas and "description" in custom_personas[pname]))
                    if model_arg not in model_map:
                        print(f"{DIM}Unknown model: {model_arg}. Use opus, sonnet, or haiku.{RESET}\n")
                    elif not persona_exists:
                        print(f"{DIM}Unknown persona: {pname}{RESET}\n")
                    else:
                        if pname not in custom_personas:
                            custom_personas[pname] = {}
                        custom_personas[pname]["model"] = model_map[model_arg]
                        save_personas(custom_personas)
                        if pname == active_persona:
                            active_model = model_map[model_arg]
                        print(f"{DIM}Set {pname}'s default model to {model_arg}.{RESET}\n")
            elif arg.lower().startswith("custom "):
                # Create/overwrite the "custom" persona
                description = arg[7:].strip()
                if not description:
                    print(f"{DIM}Usage: /persona custom <description>{RESET}\n")
                else:
                    # Preserve existing model preference if any
                    existing_model = custom_personas.get("custom", {}).get("model")
                    custom_personas["custom"] = {"description": description}
                    if existing_model:
                        custom_personas["custom"]["model"] = existing_model
                    save_personas(custom_personas)
                    active_persona = "custom"
                    active_model = get_persona_model("custom")
                    model_name = MODEL_SHORT_NAMES.get(active_model, active_model)
                    print(f"{DIM}Custom persona set and activated (model: {model_name}).{RESET}\n")
            else:
                # Switch to a named persona
                name = arg.lower()
                persona_exists = (name in BUILTIN_PERSONAS or
                    (name in custom_personas and "description" in custom_personas[name]))
                if persona_exists:
                    active_persona = name
                    active_model = get_persona_model(name)
                    model_name = MODEL_SHORT_NAMES.get(active_model, active_model)
                    print(f"{DIM}Switched to persona: {name} (model: {model_name}){RESET}\n")
                else:
                    available = list(BUILTIN_PERSONAS.keys()) + [
                        k for k in custom_personas if k not in BUILTIN_PERSONAS
                        and "description" in custom_personas[k]
                    ]
                    print(f"{DIM}Unknown persona: {name}")
                    print(f"  Available: {', '.join(available)}{RESET}\n")
            continue

        if command_lower == "/project" or command_lower.startswith("/project "):
            arg = command[8:].strip() if len(command) > 8 else ""
            if not arg:
                # No argument — prompt for a new project name
                try:
                    name = input(f"{DIM}New project name: {RESET}").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{DIM}Cancelled.{RESET}\n")
                    continue
                if not name:
                    print(f"{DIM}Cancelled.{RESET}\n")
                    continue
                name = re.sub(r'[^\w-]', '-', name).strip('-')
                if not name:
                    print(f"{DIM}Invalid project name.{RESET}\n")
                    continue
                switch_project(name)
                print(f"{DIM}Switched to project: {active_project}{RESET}")
                if memories:
                    print(f"{DIM}Loaded {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}{RESET}")
                print()
            elif arg.lower() == "list":
                projects = list_projects()
                print(f"{DIM}Projects:")
                for p in projects:
                    marker = " ←" if p == active_project else ""
                    print(f"  {p}{marker}")
                print(RESET)
            else:
                # Switch to named project
                name = re.sub(r'[^\w-]', '-', arg.lower()).strip('-')
                if not name:
                    print(f"{DIM}Invalid project name.{RESET}\n")
                    continue
                switch_project(name)
                print(f"{DIM}Switched to project: {active_project}{RESET}")
                if memories:
                    print(f"{DIM}Loaded {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}{RESET}")
                print()
            continue

        if command_lower == "/watch" or command_lower.startswith("/watch "):
            arg = command[6:].strip() if len(command) > 6 else ""
            if not arg:
                print(f"{DIM}Usage: /watch <topic> | /watch list | /watch remove <topic>{RESET}\n")
                continue
            if arg.lower() == "list":
                topics = load_watchlist()
                if topics:
                    print(f"{DIM}Watched topics ({active_project}):")
                    for i, t in enumerate(topics, 1):
                        print(f"  {i}. {t}")
                    print(RESET)
                else:
                    print(f"{DIM}No watched topics. Use /watch <topic> to add one.{RESET}\n")
            elif arg.lower().startswith("remove "):
                topic = arg[7:].strip()
                topics = load_watchlist()
                if topic in topics:
                    topics.remove(topic)
                    save_watchlist(topics)
                    print(f"{DIM}Removed: {topic}{RESET}\n")
                else:
                    print(f"{DIM}Not found: {topic}. Use /watch list to see topics.{RESET}\n")
            else:
                # Add a topic
                topic = arg.strip()
                topics = load_watchlist()
                if topic in topics:
                    print(f"{DIM}Already watching: {topic}{RESET}\n")
                else:
                    topics.append(topic)
                    save_watchlist(topics)
                    print(f"{DIM}Now watching: {topic}{RESET}\n")
            continue

        if command_lower == "/digest":
            run_digest()
            continue

        if command_lower == "/conversations":
            files = list_conversations()
            if files:
                print(f"{DIM}Previous conversations ({active_project}):")
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
            print(f"{DIM}Previous conversations ({active_project}):")
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
            filepath = os.path.join(get_conversations_dir(), files[idx])
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

        if command_lower == "/run":
            last = get_last_response()
            if not last:
                print(f"{DIM}No Claude response to extract code from.{RESET}\n")
                continue
            code = extract_python_block(last)
            if not code:
                print(f"{DIM}No code block found in last response.{RESET}\n")
                continue
            print(f"{CYAN}Running:{RESET}")
            print(f"{CYAN}{code}{RESET}\n")
            output, is_error = run_code_in_workspace(code)
            if is_error:
                print(f"{DIM}Error:{RESET}\n{output}\n")
            else:
                print(f"{output}\n")
            continue

        # Skip empty messages
        if not command:
            continue

        # Add the user's message to the conversation history
        conversation_history.append({"role": "user", "content": user_input})

        # Send the conversation to Claude with tool use support
        chat_turn()
        compress_conversation()
