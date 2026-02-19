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
RESET = "\033[0m"

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
        save_conversation(conversation_history)
        print("Goodbye!")
        break

    # Check if the user wants to quit
    if user_input.strip().lower() in ("quit", "exit"):
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
        model="claude-sonnet-4-5",
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

    # Print a newline after the response is done
    print("\n")

    # Add Claude's response to the conversation history so it has
    # context for the next message
    conversation_history.append({"role": "assistant", "content": response_text})
