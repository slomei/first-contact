"""
Simple terminal chatbot using the Anthropic API.

Prerequisites:
    pip install anthropic

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python chat.py
"""

import anthropic
import os
from datetime import datetime

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

# Model to use
MODEL = "claude-sonnet-4-5"

# Pricing per million tokens (USD)
PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input": 0.80, "output": 4.00},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
}

# Running session totals
session_input_tokens = 0
session_output_tokens = 0
session_cost = 0.0

# The system prompt sets Claude's behavior for the whole conversation.
system_prompt = (
    "You are a blunt, witty collaborator. You give honest, direct answers "
    "without sugarcoating. You're not rude for the sake of it—you're just "
    "efficient and real. If something is a bad idea, you say so. If someone's "
    "on the right track, you tell them that too, briefly. You have a dry sense "
    "of humor and zero patience for fluff."
)

CONVERSATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

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

print("Chatbot ready! Type your message and press Enter.")
print("Type 'quit' or 'exit' to end the conversation.\n")

while True:
    # Get input from the user
    try:
        user_input = input(f"{GREEN}You: {RESET}")
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

    # Skip empty messages
    if not user_input.strip():
        continue

    # Add the user's message to the conversation history
    conversation_history.append({"role": "user", "content": user_input})

    # Send the conversation to Claude and stream the response.
    # Streaming prints each word as it arrives instead of waiting for the full reply.
    print(f"\n{CYAN}Claude:{RESET} ", end="", flush=True)

    with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
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
    prices = PRICING.get(MODEL, {"input": 0, "output": 0})
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
