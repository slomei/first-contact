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
from duckduckgo_search import DDGS

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

# Running session totals
session_input_tokens = 0
session_output_tokens = 0
session_cost = 0.0


CONVERSATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")

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
        "of humor and zero patience for fluff."
    )
    if memories:
        memory_block = "\n".join(f"- {m}" for m in memories)
        base += f"\n\nThings the user has asked you to remember:\n{memory_block}"
    return base

memories = load_memories()

def web_search(query, max_results=5):
    """Search the web using DuckDuckGo and return formatted results."""
    results = DDGS().text(query, max_results=max_results)
    if not results:
        return None
    lines = []
    for r in results:
        lines.append(f"- {r['title']}\n  {r['href']}\n  {r['body']}")
    return "\n".join(lines)

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
            f.write(f"{role}: {msg['content']}\n\n")
    print(f"Conversation saved to {filepath}")

# Show previous conversations if any exist
existing = sorted(os.listdir(CONVERSATIONS_DIR))
if existing:
    print("Previous conversations:")
    for filename in existing:
        # Display a readable version of the timestamp from the filename
        name = filename.removesuffix(".txt")
        print(f"  - {name}")
    print()

HELP_TEXT = f"""{DIM}Available commands:
  /help              Show this help message
  /read <path>       Load a file into the conversation
  /web <query>       Search the web and discuss results
  /remember <fact>   Save a fact to persistent memory
  /forget <fact>     Remove a fact from memory
  /memories          List all stored memories
  /opus              Switch to Claude Opus
  /sonnet            Switch to Claude Sonnet
  /haiku             Switch to Claude Haiku
  quit / exit        End the conversation{RESET}"""

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
        # Immediately get Claude's take on the results
        print(f"{CYAN}Claude:{RESET} ", end="", flush=True)
        with client.messages.stream(
            model=active_model,
            max_tokens=1024,
            system=build_system_prompt(memories),
            messages=conversation_history,
        ) as stream:
            response_text = ""
            for text in stream.text_stream:
                print(text, end="", flush=True)
                response_text += text
            final = stream.get_final_message()
            input_tokens = final.usage.input_tokens
            output_tokens = final.usage.output_tokens
        prices = PRICING.get(active_model, {"input": 0, "output": 0})
        msg_cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
        session_input_tokens += input_tokens
        session_output_tokens += output_tokens
        session_cost += msg_cost
        print(f"\n{DIM}  [{input_tokens} in / {output_tokens} out — ${msg_cost:.4f}]  "
              f"session: ${session_cost:.4f}{RESET}\n")
        conversation_history.append({"role": "assistant", "content": response_text})
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

    # Skip empty messages
    if not command:
        continue

    # Add the user's message to the conversation history
    conversation_history.append({"role": "user", "content": user_input})

    # Send the conversation to Claude and stream the response.
    # Streaming prints each word as it arrives instead of waiting for the full reply.
    print(f"\n{CYAN}Claude:{RESET} ", end="", flush=True)

    with client.messages.stream(
        model=active_model,
        max_tokens=1024,
        system=build_system_prompt(memories),
        messages=conversation_history,
    ) as stream:
        # Collect the full response so we can save it to history
        response_text = ""

        for text in stream.text_stream:
            # Print each chunk of text as it arrives
            print(text, end="", flush=True)
            response_text += text

        # Get token usage from the final message
        final = stream.get_final_message()
        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens

    # Calculate cost for this message
    prices = PRICING.get(active_model, {"input": 0, "output": 0})
    msg_cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    # Update session totals
    session_input_tokens += input_tokens
    session_output_tokens += output_tokens
    session_cost += msg_cost

    # Show cost in a dim line under the response
    print(f"\n{DIM}  [{input_tokens} in / {output_tokens} out — ${msg_cost:.4f}]  "
          f"session: ${session_cost:.4f}{RESET}\n")

    # Add Claude's response to the conversation history so it has
    # context for the next message
    conversation_history.append({"role": "assistant", "content": response_text})
