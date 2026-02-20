"""
Simple terminal chatbot using the Anthropic API.

Prerequisites:
    pip install anthropic

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python chat.py
"""

import json
import os
import re
import shutil
from datetime import datetime
import pdfplumber

import memory
import models
import tools
import sync
import creative


# --- Terminal-specific helpers ---

def terminal_confirm(prompt):
    """Wrap input() for execute_tool's confirm_fn."""
    try:
        confirm = input(f"\n{memory.CYAN}{prompt}{memory.RESET}")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return confirm.strip().lower() == "y"


def print_tool_status(name, tool_input):
    """Print a dim status line showing what tool Claude is using."""
    label = tools.tool_status_text(name, tool_input)
    print(f"\n{memory.DIM}\u27e1 {label}{memory.RESET}")


def print_session_summary():
    """Print a final cost summary for the session."""
    if models.session_input_tokens or models.session_output_tokens:
        print(f"{memory.DIM}Session total: {models.session_input_tokens} in / "
              f"{models.session_output_tokens} out \u2014 "
              f"${models.session_cost:.4f}{memory.RESET}")


def print_conversations(files):
    """Print a numbered list of conversation files with titles."""
    for i, filename in enumerate(files, 1):
        name = filename.removesuffix(".txt")
        parts = name.split("_", 1)
        if len(parts) == 2:
            date_part, title_slug = parts
            title = title_slug.replace("-", " ").title()
            print(f"  {i}. {date_part}  {title}")
        else:
            print(f"  {i}. {name}")


def chat_turn():
    """Run a chat turn with tool use support. Streams response, handles tool calls in a loop."""
    total_input = 0
    total_output = 0
    total_cost = 0

    # Inject creative context when first-light project is active
    creative_ctx = ""
    if memory.active_project == "first-light":
        creative_ctx = creative.get_creative_context()

    for turn in range(10):
        if turn == 0:
            print(f"\n{memory.CYAN}Claude:{memory.RESET} ", end="", flush=True)

        with models.client.messages.stream(
            model=models.active_model,
            max_tokens=4096,
            system=memory.build_system_prompt(memory.memories, creative_context=creative_ctx),
            messages=models.conversation_history,
            tools=tools.TOOLS,
        ) as stream:
            response_text = ""
            for text in stream.text_stream:
                print(text, end="", flush=True)
                response_text += text

            final = stream.get_final_message()

        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens
        prices = models.PRICING.get(models.active_model, {"input": 0, "output": 0})
        msg_cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
        total_input += input_tokens
        total_output += output_tokens
        total_cost += msg_cost

        if final.stop_reason == "tool_use":
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
            models.conversation_history.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in final.content:
                if block.type == "tool_use":
                    print_tool_status(block.name, block.input)
                    result, is_error = tools.execute_tool(block.name, block.input, confirm_fn=terminal_confirm)
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)
            models.conversation_history.append({"role": "user", "content": tool_results})
            continue
        else:
            models.conversation_history.append({"role": "assistant", "content": response_text})
            break

    # Update session totals
    models.session_input_tokens += total_input
    models.session_output_tokens += total_output
    models.session_cost += total_cost

    print(f"\n{memory.DIM}  [{total_input} in / {total_output} out \u2014 ${total_cost:.4f}]  "
          f"session: ${models.session_cost:.4f}{memory.RESET}\n")


if __name__ == "__main__":
    # Initialize project system
    memory.switch_project("general")

    # Show previous conversations if any exist
    existing = memory.list_conversations()
    if existing:
        print(f"Previous conversations ({memory.active_project}):")
        print_conversations(existing)
        print()

    HELP_TEXT = f"""{memory.DIM}Available commands:
      /help              Show this help message
      /read <path>       Load a file into the conversation
      /web <query>       Search the web and discuss results
      /write <file>      Save last response to workspace/<file>
      /run               Run the code block from Claude's last response
      /remember <fact>   Save a fact to persistent memory
      /forget <fact>     Remove a fact from memory
      /memories          List all stored memories
      /challenge on|off  Toggle devil's advocate mode
      /project           Create a new project (prompts for name)
      /project <name>    Switch to a project (creates if needed)
      /project list      List all projects
      /watch <topic>     Add a topic to the watchlist
      /watch list        Show all watched topics
      /watch remove <topic>  Remove a topic from the watchlist
      /digest            Search web for watched topics and save a digest
      /jobs search <q>   Search for job listings
      /jobs save         Save last search results to job-search project
      /jobs list         Show all saved job listings
      /jobs remove <#>   Remove a saved listing
      /jobs apply <#>    Open listing + generate cover letter to jobs/<slug>/
      /jobs track <#> <status>  Set status (applied, interviewing, rejected, offer)
      /jobs status       Show tracked jobs grouped by status
      /resume              Show loaded resume status
      /resume <path>       Load a resume file (txt, md, pdf, docx)
      /email setup         Authenticate with Gmail (OAuth2)
      /email check         Show recent unread emails
      /email read <#>      Read full email by number
      /email search <q>    Search emails by keyword
      /update [key]      Sync files from Windows source (all keys if omitted)
      /characters        List all indexed characters (first-light only)
      /character <name>  Show character details (first-light only)
      /locations         List all indexed locations (first-light only)
      /location <name>   Show location details (first-light only)
      /delegates         Show specialist agents and their models
      /billing           Show billing link for API credits
      /load              Load a previous conversation into context
      /conversations     List previous conversations
      /tokens            Show conversation size and compression status
      /opus              Switch to Claude Opus
      /sonnet            Switch to Claude Sonnet
      /haiku             Switch to Claude Haiku
      quit / exit        End the conversation

    Claude also uses tools autonomously (web search, file read/write, memory, code execution).{memory.RESET}"""

    if memory.memories:
        print(f"Loaded {len(memory.memories)} memor{'y' if len(memory.memories) == 1 else 'ies'} from {memory.active_project}/memory.json")
    print("Chatbot ready! Type your message and press Enter.")
    print("Type /help to see available commands.\n")

    while True:
        short_name = models.MODEL_SHORT_NAMES.get(models.active_model, models.active_model)
        challenge_tag = " challenge" if memory.challenge_mode else ""
        try:
            user_input = input(f"{memory.GREEN}You {memory.DIM}[{short_name}/{memory.active_project}{challenge_tag}]{memory.RESET}{memory.GREEN}: {memory.RESET}")
        except (EOFError, KeyboardInterrupt):
            print()
            print_session_summary()
            result = models.save_conversation(models.conversation_history)
            if result:
                title, filepath = result
                print(f"Conversation saved: {title}")
                print(f"{memory.DIM}  \u2192 {filepath}{memory.RESET}")
            print("Goodbye!")
            break

        if user_input.strip().lower() in ("quit", "exit"):
            print_session_summary()
            result = models.save_conversation(models.conversation_history)
            if result:
                title, filepath = result
                print(f"Conversation saved: {title}")
                print(f"{memory.DIM}  \u2192 {filepath}{memory.RESET}")
            print("Goodbye!")
            break

        command = user_input.strip()
        command_lower = command.lower()

        if command_lower == "/help":
            print(HELP_TEXT)
            continue

        if command_lower in models.MODELS:
            models.active_model = models.MODELS[command_lower]
            print(f"{memory.DIM}Switched to {models.active_model}{memory.RESET}\n")
            continue

        if command_lower.startswith("/read "):
            filepath = command[6:].strip()
            try:
                with open(filepath, "r") as f:
                    contents = f.read()
                line_count = contents.count("\n") + (1 if contents and not contents.endswith("\n") else 0)
                filename = os.path.basename(filepath)
                print(f"{memory.DIM}Loaded {filename} ({line_count} lines){memory.RESET}\n")
                file_message = f"[File: {filepath}]\n```\n{contents}\n```"
                models.conversation_history.append({"role": "user", "content": file_message})
            except FileNotFoundError:
                print(f"{memory.DIM}File not found: {filepath}{memory.RESET}\n")
            except IsADirectoryError:
                print(f"{memory.DIM}Path is a directory: {filepath}{memory.RESET}\n")
            except UnicodeDecodeError:
                print(f"{memory.DIM}Cannot read binary file: {filepath}{memory.RESET}\n")
            continue

        if command_lower.startswith("/web "):
            query = command[5:].strip()
            if not query:
                print(f"{memory.DIM}Usage: /web <search query>{memory.RESET}\n")
                continue
            print(f"{memory.DIM}Searching: {query}...{memory.RESET}")
            try:
                results = tools.web_search(query)
            except Exception as e:
                print(f"{memory.DIM}Search failed: {e}{memory.RESET}\n")
                continue
            if not results:
                print(f"{memory.DIM}No results found.{memory.RESET}\n")
                continue
            print(f"{memory.DIM}{results}{memory.RESET}\n")
            search_message = f"[Web search: {query}]\n{results}\n\nUsing these search results, answer my question: {query}"
            models.conversation_history.append({"role": "user", "content": search_message})
            chat_turn()
            result = models.compress_conversation()
            if result:
                old_tokens, new_tokens, removed, kept = result
                print(f"\n{memory.DIM}\u27e1 Context compressed: ~{old_tokens:,} \u2192 ~{new_tokens:,} tokens "
                      f"({removed} exchanges summarized, {kept} kept){memory.RESET}")
            continue

        if command_lower.startswith("/write "):
            filename = command[7:].strip()
            if not filename:
                print(f"{memory.DIM}Usage: /write <filename>{memory.RESET}\n")
                continue
            if ".." in filename or filename.startswith("/"):
                print(f"{memory.DIM}Filename must be relative and stay inside workspace/{memory.RESET}\n")
                continue
            workspace = memory.get_workspace_dir()
            filepath = os.path.join(workspace, filename)
            os.makedirs(os.path.dirname(filepath) or workspace, exist_ok=True)
            if os.path.exists(filepath):
                try:
                    confirm = input(f"{memory.DIM}{memory.active_project}/workspace/{filename} already exists. Overwrite? [y/N]: {memory.RESET}")
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{memory.DIM}Cancelled.{memory.RESET}\n")
                    continue
                if confirm.strip().lower() != "y":
                    print(f"{memory.DIM}Cancelled.{memory.RESET}\n")
                    continue
            last = models.get_last_response()
            if not last:
                print(f"{memory.DIM}No Claude response to save yet.{memory.RESET}\n")
                continue
            content = tools.extract_code_block(last)
            with open(filepath, "w") as f:
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
            line_count = content.count("\n") + 1
            print(f"{memory.DIM}Wrote {line_count} lines to {memory.active_project}/workspace/{filename}{memory.RESET}\n")
            continue

        if command_lower.startswith("/remember "):
            fact = command[10:].strip()
            if fact:
                memory.memories.append(fact)
                memory.save_memories(memory.memories)
                print(f"{memory.DIM}Remembered: {fact}{memory.RESET}\n")
            else:
                print(f"{memory.DIM}Usage: /remember <fact>{memory.RESET}\n")
            continue

        if command_lower.startswith("/forget "):
            fact = command[8:].strip()
            if fact in memory.memories:
                memory.memories.remove(fact)
                memory.save_memories(memory.memories)
                print(f"{memory.DIM}Forgot: {fact}{memory.RESET}\n")
            else:
                print(f"{memory.DIM}No matching memory found. Use /memories to see stored facts.{memory.RESET}\n")
            continue

        if command_lower == "/memories":
            if memory.memories:
                print(f"{memory.DIM}Stored memories ({memory.active_project}):")
                for i, m in enumerate(memory.memories, 1):
                    print(f"  {i}. {m}")
                print(memory.RESET)
            else:
                print(f"{memory.DIM}No memories stored. Use /remember <fact> to add one.{memory.RESET}\n")
            continue

        if command_lower in ("/challenge on", "/challenge off"):
            memory.challenge_mode = command_lower == "/challenge on"
            status = "ON" if memory.challenge_mode else "OFF"
            print(f"{memory.DIM}Challenge mode: {status}{memory.RESET}\n")
            continue

        if command_lower == "/project" or command_lower.startswith("/project "):
            arg = command[8:].strip() if len(command) > 8 else ""
            if not arg:
                try:
                    name = input(f"{memory.DIM}New project name: {memory.RESET}").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{memory.DIM}Cancelled.{memory.RESET}\n")
                    continue
                if not name:
                    print(f"{memory.DIM}Cancelled.{memory.RESET}\n")
                    continue
                name = re.sub(r'[^\w-]', '-', name).strip('-')
                if not name:
                    print(f"{memory.DIM}Invalid project name.{memory.RESET}\n")
                    continue
                memory.switch_project(name)
                print(f"{memory.DIM}Switched to project: {memory.active_project}{memory.RESET}")
                if memory.memories:
                    print(f"{memory.DIM}Loaded {len(memory.memories)} memor{'y' if len(memory.memories) == 1 else 'ies'}{memory.RESET}")
                print()
            elif arg.lower() == "list":
                projects = memory.list_projects()
                print(f"{memory.DIM}Projects:")
                for p in projects:
                    marker = " \u2190" if p == memory.active_project else ""
                    print(f"  {p}{marker}")
                print(memory.RESET)
            else:
                name = re.sub(r'[^\w-]', '-', arg.lower()).strip('-')
                if not name:
                    print(f"{memory.DIM}Invalid project name.{memory.RESET}\n")
                    continue
                memory.switch_project(name)
                print(f"{memory.DIM}Switched to project: {memory.active_project}{memory.RESET}")
                if memory.memories:
                    print(f"{memory.DIM}Loaded {len(memory.memories)} memor{'y' if len(memory.memories) == 1 else 'ies'}{memory.RESET}")
                print()
            continue

        if command_lower == "/watch" or command_lower.startswith("/watch "):
            arg = command[6:].strip() if len(command) > 6 else ""
            if not arg:
                print(f"{memory.DIM}Usage: /watch <topic> | /watch list | /watch remove <topic>{memory.RESET}\n")
                continue
            if arg.lower() == "list":
                topics = memory.load_watchlist()
                if topics:
                    print(f"{memory.DIM}Watched topics ({memory.active_project}):")
                    for i, t in enumerate(topics, 1):
                        print(f"  {i}. {t}")
                    print(memory.RESET)
                else:
                    print(f"{memory.DIM}No watched topics. Use /watch <topic> to add one.{memory.RESET}\n")
            elif arg.lower().startswith("remove "):
                topic = arg[7:].strip()
                topics = memory.load_watchlist()
                if topic in topics:
                    topics.remove(topic)
                    memory.save_watchlist(topics)
                    print(f"{memory.DIM}Removed: {topic}{memory.RESET}\n")
                else:
                    print(f"{memory.DIM}Not found: {topic}. Use /watch list to see topics.{memory.RESET}\n")
            else:
                topic = arg.strip()
                topics = memory.load_watchlist()
                if topic in topics:
                    print(f"{memory.DIM}Already watching: {topic}{memory.RESET}\n")
                else:
                    topics.append(topic)
                    memory.save_watchlist(topics)
                    print(f"{memory.DIM}Now watching: {topic}{memory.RESET}\n")
            continue

        if command_lower == "/digest":
            def digest_progress(msg):
                print(f"{memory.DIM}  {msg}{memory.RESET}")
            result = tools.run_digest(progress_fn=digest_progress)
            if result is None:
                print(f"{memory.DIM}No topics in watchlist. Use /watch <topic> to add one.{memory.RESET}\n")
            else:
                digest, filename, cost_str = result
                print(f"\n{digest}")
                print(f"\n{memory.DIM}Digest saved to {memory.active_project}/workspace/{filename} ({cost_str}){memory.RESET}\n")
            continue

        if command_lower == "/billing":
            print(f"\n{memory.CYAN}Check your balance and add credits:{memory.RESET}")
            print(f"  \033[4mhttps://platform.claude.com/settings/billing\033[0m\n")
            continue

        if command_lower == "/delegates":
            print(f"\n{memory.CYAN}Specialist agents:{memory.RESET}")
            for name, spec in models.SPECIALISTS.items():
                print(f"  {memory.CYAN}{name:<12}{memory.RESET} {spec['description']}")
                print(f"  {memory.DIM}{'':12} model: {spec['model']} ({spec['label']}){memory.RESET}")
            print(f"\n{memory.DIM}The director (Sonnet) routes tasks to specialists automatically.{memory.RESET}\n")
            continue

        if command_lower == "/email" or command_lower.startswith("/email "):
            email_arg = command[6:].strip() if len(command) > 6 else ""
            email_arg_lower = email_arg.lower()

            if not email_arg:
                print(f"{memory.DIM}Usage: /email setup | /email check | /email read <#> | /email search <query>{memory.RESET}\n")
                continue

            if email_arg_lower == "setup":
                if not os.path.exists(memory.GMAIL_CLIENT_SECRET):
                    print(f"{memory.DIM}Missing {memory.GMAIL_CLIENT_SECRET}")
                    print("Download OAuth client credentials from Google Cloud Console")
                    print(f"and save as gmail_client_secret.json in the project root.{memory.RESET}\n")
                elif tools.gmail_setup():
                    print(f"{memory.DIM}Gmail authenticated successfully. Token saved to {memory.GMAIL_CREDENTIALS}{memory.RESET}\n")
                else:
                    print(f"{memory.DIM}Gmail setup failed.{memory.RESET}\n")

            elif email_arg_lower == "check":
                service = tools.get_gmail_service()
                if not service:
                    print(f"{memory.DIM}Gmail not authenticated. Run /email setup first.{memory.RESET}\n")
                    continue
                print(f"{memory.DIM}Checking inbox...{memory.RESET}")
                result = tools.gmail_check()
                if isinstance(result, str):
                    print(f"{memory.DIM}{result}{memory.RESET}\n")
                    continue
                if result is None:
                    print(f"{memory.DIM}Gmail not authenticated. Run /email setup first.{memory.RESET}\n")
                    continue
                tools._last_email_results.clear()
                tools._last_email_results.extend(result)
                if not result:
                    print(f"{memory.DIM}No unread emails.{memory.RESET}\n")
                    continue
                for i, e in enumerate(result, 1):
                    print(f"\n  {memory.CYAN}{i}. {e['subject']}{memory.RESET}")
                    print(f"     {memory.DIM}From: {e['sender']}")
                    print(f"     Date: {e['date']}")
                    print(f"     {e['snippet'][:150]}{memory.RESET}")
                print(f"\n{memory.DIM}Found {len(result)} unread email(s). Use /email read <#> to read one.{memory.RESET}\n")

            elif email_arg_lower.startswith("read "):
                num_str = email_arg[5:].strip()
                try:
                    idx = int(num_str) - 1
                    if idx < 0 or idx >= len(tools._last_email_results):
                        raise ValueError
                except ValueError:
                    print(f"{memory.DIM}Invalid number. Use /email check or /email search first.{memory.RESET}\n")
                    continue
                msg = tools._last_email_results[idx]
                print(f"{memory.DIM}Reading: {msg['subject']}...{memory.RESET}")
                body = tools.gmail_read(msg["id"])
                if body is None:
                    print(f"{memory.DIM}Gmail not authenticated. Run /email setup first.{memory.RESET}\n")
                    continue
                tools._email_content_loaded = True
                print(f"\n{memory.CYAN}From:{memory.RESET} {msg['sender']}")
                print(f"{memory.CYAN}Subject:{memory.RESET} {msg['subject']}")
                print(f"{memory.CYAN}Date:{memory.RESET} {msg['date']}")
                print(f"\n{body}\n")
                models.conversation_history.append({"role": "user", "content":
                    f"[Email loaded]\nFrom: {msg['sender']}\nSubject: {msg['subject']}\n"
                    f"Date: {msg['date']}\n\n{body}"})

            elif email_arg_lower.startswith("search "):
                query = email_arg[7:].strip()
                if not query:
                    print(f"{memory.DIM}Usage: /email search <query>{memory.RESET}\n")
                    continue
                service = tools.get_gmail_service()
                if not service:
                    print(f"{memory.DIM}Gmail not authenticated. Run /email setup first.{memory.RESET}\n")
                    continue
                print(f"{memory.DIM}Searching emails: {query}...{memory.RESET}")
                result = tools.gmail_search(query)
                if isinstance(result, str):
                    print(f"{memory.DIM}{result}{memory.RESET}\n")
                    continue
                if result is None:
                    print(f"{memory.DIM}Gmail not authenticated. Run /email setup first.{memory.RESET}\n")
                    continue
                tools._last_email_results.clear()
                tools._last_email_results.extend(result)
                if not result:
                    print(f"{memory.DIM}No emails found matching: {query}{memory.RESET}\n")
                    continue
                for i, e in enumerate(result, 1):
                    print(f"\n  {memory.CYAN}{i}. {e['subject']}{memory.RESET}")
                    print(f"     {memory.DIM}From: {e['sender']}")
                    print(f"     Date: {e['date']}")
                    print(f"     {e['snippet'][:150]}{memory.RESET}")
                print(f"\n{memory.DIM}Found {len(result)} email(s). Use /email read <#> to read one.{memory.RESET}\n")

            else:
                print(f"{memory.DIM}Unknown /email subcommand: {email_arg}")
                print(f"  Use: setup, check, read <#>, search <query>{memory.RESET}\n")
            continue

        if command_lower == "/resume" or command_lower.startswith("/resume "):
            resume_arg = command[7:].strip() if len(command) > 7 else ""
            resume_path = memory.get_resume_path()

            if not resume_arg:
                if os.path.exists(resume_path):
                    with open(resume_path, "r") as f:
                        content = f.read()
                    lines = content.splitlines()
                    print(f"{memory.DIM}Resume loaded: {resume_path} ({len(lines)} lines)")
                    preview = "\n".join(lines[:10])
                    print(f"\nPreview:\n{preview}")
                    if len(lines) > 10:
                        print(f"  ... ({len(lines) - 10} more lines)")
                    print(f"{memory.RESET}\n")
                else:
                    print(f"{memory.DIM}No resume loaded. Use /resume <path> to load one.{memory.RESET}\n")
                continue

            src = os.path.expanduser(resume_arg)
            if not os.path.exists(src):
                print(f"{memory.DIM}File not found: {src}{memory.RESET}\n")
                continue

            ext = os.path.splitext(src)[1].lower()
            try:
                if ext == ".pdf":
                    with pdfplumber.open(src) as pdf:
                        text = "\n\n".join(
                            page.extract_text() or "" for page in pdf.pages
                        )
                elif ext == ".docx":
                    import zipfile
                    import xml.etree.ElementTree as ET
                    with zipfile.ZipFile(src) as z:
                        xml_content = z.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    paragraphs = tree.findall(".//w:p", ns)
                    text = "\n".join(
                        "".join(node.text or "" for node in p.findall(".//w:t", ns))
                        for p in paragraphs
                    )
                elif ext in (".txt", ".md"):
                    with open(src, "r") as f:
                        text = f.read()
                else:
                    print(f"{memory.DIM}Unsupported format: {ext}. Use .txt, .md, .pdf, or .docx{memory.RESET}\n")
                    continue

                text = text.strip()
                if not text:
                    print(f"{memory.DIM}No text could be extracted from {src}{memory.RESET}\n")
                    continue

                os.makedirs(os.path.dirname(resume_path), exist_ok=True)
                with open(resume_path, "w") as f:
                    f.write(text)

                line_count = text.count("\n") + 1
                print(f"{memory.DIM}Resume saved to {resume_path} ({line_count} lines){memory.RESET}\n")

            except Exception as e:
                print(f"{memory.DIM}Error loading resume: {e}{memory.RESET}\n")
            continue

        if command_lower == "/jobs" or command_lower.startswith("/jobs "):
            arg = command[5:].strip() if len(command) > 5 else ""
            arg_lower = arg.lower()

            if not arg:
                print(f"{memory.DIM}Usage: /jobs search <query> | /jobs save | /jobs list | /jobs remove <#>")
                print(f"       /jobs apply <#> | /jobs track <#> <status> | /jobs status{memory.RESET}\n")
                continue

            if arg_lower.startswith("search "):
                query = arg[7:].strip()
                if not query:
                    print(f"{memory.DIM}Usage: /jobs search <query>{memory.RESET}\n")
                    continue
                print(f"{memory.DIM}Searching jobs: {query}...{memory.RESET}")
                try:
                    results = tools.search_jobs(query)
                    tools.last_job_results.clear()
                    tools.last_job_results.extend(results)
                except Exception as e:
                    print(f"{memory.DIM}Search failed: {e}{memory.RESET}\n")
                    continue
                if not results:
                    print(f"{memory.DIM}No results found.{memory.RESET}\n")
                    continue
                for i, r in enumerate(results, 1):
                    print(f"\n  {memory.CYAN}{i}. {r['title']}{memory.RESET}")
                    print(f"     {memory.DIM}{r['url']}{memory.RESET}")
                    print(f"     {r['body'][:200]}")
                print(f"\n{memory.DIM}Found {len(results)} result(s). Use /jobs save to save these.{memory.RESET}\n")

            elif arg_lower == "save":
                if not tools.last_job_results:
                    print(f"{memory.DIM}No search results to save. Run /jobs search <query> first.{memory.RESET}\n")
                    continue
                jobs = memory.load_jobs()
                existing_urls = {j["url"] for j in jobs}
                added = 0
                for r in tools.last_job_results:
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
                print(f"{memory.DIM}Saved {added} new listing(s) to job-search project ({len(jobs)} total).")
                if added:
                    print(f"  Job folders: job-search/workspace/jobs/{memory.RESET}\n")
                else:
                    print(memory.RESET)

            elif arg_lower == "list":
                jobs = memory.load_jobs()
                if not jobs:
                    print(f"{memory.DIM}No saved jobs. Use /jobs search <query> then /jobs save.{memory.RESET}\n")
                    continue
                print(f"{memory.DIM}Saved job listings ({len(jobs)}):{memory.RESET}")
                for i, j in enumerate(jobs, 1):
                    status_tag = f" [{j['status']}]" if j.get("status") else ""
                    has_letter = ""
                    if j.get("folder"):
                        cl_path = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "workspace", "jobs", j["folder"], "cover-letter.md")
                        if os.path.exists(cl_path):
                            has_letter = " [cover letter]"
                    print(f"  {memory.CYAN}{i}. {j['title']}{memory.RESET}{memory.DIM}{status_tag}{has_letter}")
                    print(f"     {j['url']}")
                    folder_tag = f"  \u2192  jobs/{j['folder']}/" if j.get("folder") else ""
                    print(f"     Saved: {j['saved_at']}{folder_tag}{memory.RESET}")
                print()

            elif arg_lower.startswith("remove "):
                num_str = arg[7:].strip()
                try:
                    idx = int(num_str) - 1
                    jobs = memory.load_jobs()
                    if idx < 0 or idx >= len(jobs):
                        raise ValueError
                    removed = jobs.pop(idx)
                    if removed.get("folder"):
                        folder_path = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "workspace", "jobs", removed["folder"])
                        if os.path.exists(folder_path):
                            shutil.rmtree(folder_path)
                    memory.save_jobs(jobs)
                    print(f"{memory.DIM}Removed: {removed['title']}{memory.RESET}\n")
                except ValueError:
                    print(f"{memory.DIM}Invalid number. Use /jobs list to see listings.{memory.RESET}\n")

            elif arg_lower.startswith("apply "):
                num_str = arg[6:].strip()
                try:
                    idx = int(num_str) - 1
                    jobs = memory.load_jobs()
                    if idx < 0 or idx >= len(jobs):
                        raise ValueError
                except ValueError:
                    print(f"{memory.DIM}Invalid number. Use /jobs list to see listings.{memory.RESET}\n")
                    continue
                job = jobs[idx]

                print(f"{memory.DIM}Opening: {job['url']}{memory.RESET}")
                try:
                    memory.open_url(job["url"])
                except Exception:
                    print(f"{memory.DIM}  (Could not open browser \u2014 copy the URL above){memory.RESET}")

                print(f"{memory.DIM}Using Opus for cover letter generation{memory.RESET}")
                print(f"{memory.DIM}Generating cover letter for: {job['title']}...{memory.RESET}")
                all_memories = list(memory.memories)
                root_mem = os.path.join(memory.BASE_DIR, "memory.json")
                if os.path.exists(root_mem):
                    with open(root_mem, "r") as f:
                        all_memories.extend(json.load(f))
                if memory.active_project != "general":
                    general_mem = os.path.join(memory.PROJECTS_DIR, "general", "memory.json")
                    if os.path.exists(general_mem):
                        with open(general_mem, "r") as f:
                            all_memories.extend(json.load(f))
                js_mem = os.path.join(memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "memory.json")
                if js_mem != memory.get_memory_file() and os.path.exists(js_mem):
                    with open(js_mem, "r") as f:
                        all_memories.extend(json.load(f))
                all_memories = list(dict.fromkeys(all_memories))
                resume_path = memory.get_resume_path()
                resume_text = ""
                if os.path.exists(resume_path):
                    with open(resume_path, "r") as f:
                        resume_text = f.read()
                try:
                    letter, cost = models.generate_cover_letter(job, all_memories, resume_text=resume_text)

                    folder = memory.get_job_folder(job)
                    cl_path = os.path.join(folder, "cover-letter.md")
                    with open(cl_path, "w") as f:
                        f.write(f"# Cover Letter \u2014 {job['title']}\n\n")
                        f.write(f"**Position:** {job['title']}\n")
                        f.write(f"**URL:** {job['url']}\n")
                        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n")
                        f.write(letter + "\n")

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

                    print(f"\n{memory.CYAN}Cover Letter \u2014 {job['title']}{memory.RESET}\n")
                    print(letter)
                    print(f"\n{memory.DIM}  Saved to: jobs/{job['folder']}/cover-letter.md")
                    print(f"  [${cost:.4f}] session: ${models.session_cost:.4f}{memory.RESET}\n")
                except Exception as e:
                    print(f"{memory.DIM}Failed to generate cover letter: {e}{memory.RESET}\n")

            elif arg_lower.startswith("track "):
                parts = arg[6:].strip().split(None, 1)
                if len(parts) != 2:
                    print(f"{memory.DIM}Usage: /jobs track <#> <status>{memory.RESET}")
                    print(f"{memory.DIM}  Statuses: applied, interviewing, rejected, offer{memory.RESET}\n")
                    continue
                num_str, status = parts
                try:
                    idx = int(num_str) - 1
                    jobs = memory.load_jobs()
                    if idx < 0 or idx >= len(jobs):
                        raise ValueError
                except ValueError:
                    print(f"{memory.DIM}Invalid number. Use /jobs list to see listings.{memory.RESET}\n")
                    continue
                jobs[idx]["status"] = status.lower()
                memory.save_jobs(jobs)
                print(f"{memory.DIM}Updated: {jobs[idx]['title']} \u2192 {status.lower()}{memory.RESET}\n")

            elif arg_lower == "status":
                jobs = memory.load_jobs()
                tracked = [j for j in jobs if j.get("status")]
                if not tracked:
                    print(f"{memory.DIM}No tracked jobs. Use /jobs track <#> <status> to set a status.{memory.RESET}\n")
                    continue
                groups = {}
                for j in tracked:
                    s = j["status"]
                    if s not in groups:
                        groups[s] = []
                    groups[s].append(j)
                print(f"{memory.DIM}Tracked jobs:{memory.RESET}")
                for status in sorted(groups.keys()):
                    print(f"\n  {memory.CYAN}{status.upper()}{memory.RESET}")
                    for j in groups[status]:
                        print(f"    {j['title']}")
                        print(f"    {memory.DIM}{j['url']}{memory.RESET}")
                print()

            else:
                print(f"{memory.DIM}Unknown /jobs subcommand: {arg}")
                print(f"  Use: search, save, list, remove, apply, track, status{memory.RESET}\n")
            continue

        if command_lower == "/conversations":
            files = memory.list_conversations()
            if files:
                print(f"{memory.DIM}Previous conversations ({memory.active_project}):")
                print_conversations(files)
                print(memory.RESET)
            else:
                print(f"{memory.DIM}No saved conversations yet.{memory.RESET}\n")
            continue

        if command_lower == "/load":
            files = memory.list_conversations()
            if not files:
                print(f"{memory.DIM}No saved conversations to load.{memory.RESET}\n")
                continue
            print(f"{memory.DIM}Previous conversations ({memory.active_project}):")
            print_conversations(files)
            print(memory.RESET)
            try:
                choice = input(f"{memory.DIM}Load conversation #: {memory.RESET}")
            except (EOFError, KeyboardInterrupt):
                print(f"\n{memory.DIM}Cancelled.{memory.RESET}\n")
                continue
            try:
                idx = int(choice.strip()) - 1
                if idx < 0 or idx >= len(files):
                    raise ValueError
            except ValueError:
                print(f"{memory.DIM}Invalid choice.{memory.RESET}\n")
                continue
            filepath = os.path.join(memory.get_conversations_dir(), files[idx])
            print(f"{memory.DIM}Summarizing previous conversation...{memory.RESET}")
            result = models.load_conversation(filepath)
            if result is None:
                print(f"{memory.DIM}Conversation file is empty.{memory.RESET}\n")
            else:
                summary, cost = result
                print(f"{memory.DIM}\u27e1 Loaded conversation summary (${cost:.4f}){memory.RESET}")
                print(f"{memory.DIM}{summary}{memory.RESET}\n")
            continue

        if command_lower == "/tokens":
            tokens = models.estimate_conversation_tokens()
            exchanges = models.group_into_exchanges(models.conversation_history)
            pct = min(100, int(tokens / models.TOKEN_THRESHOLD * 100))
            bar_len = 20
            filled = int(bar_len * pct / 100)
            bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
            print(f"{memory.DIM}Conversation: ~{tokens:,} / {models.TOKEN_THRESHOLD:,} tokens ({pct}%)")
            print(f"  [{bar}]")
            print(f"  {len(exchanges)} exchanges, {len(models.conversation_history)} messages")
            if tokens >= models.TOKEN_THRESHOLD:
                print(f"  \u26a0 Above threshold \u2014 will compress on next response")
            print(memory.RESET)
            continue

        if command_lower == "/run":
            last = models.get_last_response()
            if not last:
                print(f"{memory.DIM}No Claude response to extract code from.{memory.RESET}\n")
                continue
            code = tools.extract_python_block(last)
            if not code:
                print(f"{memory.DIM}No code block found in last response.{memory.RESET}\n")
                continue
            print(f"{memory.CYAN}Running:{memory.RESET}")
            print(f"{memory.CYAN}{code}{memory.RESET}\n")
            output, is_error = tools.run_code_in_workspace(code)
            if is_error:
                print(f"{memory.DIM}Error:{memory.RESET}\n{output}\n")
            else:
                print(f"{output}\n")
            continue

        if command_lower == "/update" or command_lower.startswith("/update "):
            update_arg = command[7:].strip() if len(command) > 7 else ""

            def sync_prompt(message, num_choices):
                """Prompt user to pick from a numbered list."""
                print(f"\n{memory.DIM}{message}{memory.RESET}")
                try:
                    choice = input(f"{memory.DIM}Pick #: {memory.RESET}")
                    idx = int(choice.strip()) - 1
                    if 0 <= idx < num_choices:
                        return idx
                except (ValueError, EOFError, KeyboardInterrupt):
                    pass
                return None

            if update_arg:
                key = update_arg.lower()
                sources = sync.load_sources()
                if key not in sources:
                    print(f"{memory.DIM}Unknown sync key: {key}. Available: {', '.join(sources.keys())}{memory.RESET}\n")
                    continue
                print(f"{memory.DIM}Syncing {key}...{memory.RESET}")
                dest = sync.get_latest(key, prompt_fn=sync_prompt)
                if dest:
                    print(f"{memory.DIM}Synced: {os.path.basename(dest)}{memory.RESET}")
                    if key == "bible":
                        print(f"{memory.DIM}Rebuilding character/location indexes...{memory.RESET}")
                        result = creative.rebuild_indexes(
                            bible_path=dest,
                            progress_fn=lambda msg: print(f"{memory.DIM}  {msg}{memory.RESET}"),
                        )
                        if result:
                            chars, locs, cost = result
                            print(f"{memory.DIM}Indexed {chars} characters and {locs} locations (${cost:.4f}){memory.RESET}")
                else:
                    print(f"{memory.DIM}No source files found for {key}.{memory.RESET}")
                print()
            else:
                print(f"{memory.DIM}Syncing all sources...{memory.RESET}")
                results = sync.sync_all(
                    prompt_fn=sync_prompt,
                    progress_fn=lambda msg: print(f"{memory.DIM}  {msg}{memory.RESET}"),
                )
                for key, dest in results:
                    if dest:
                        print(f"{memory.DIM}  {key}: {os.path.basename(dest)}{memory.RESET}")
                        if key == "bible":
                            print(f"{memory.DIM}  Rebuilding character/location indexes...{memory.RESET}")
                            result = creative.rebuild_indexes(
                                bible_path=dest,
                                progress_fn=lambda msg: print(f"{memory.DIM}    {msg}{memory.RESET}"),
                            )
                            if result:
                                chars, locs, cost = result
                                print(f"{memory.DIM}    Indexed {chars} characters and {locs} locations (${cost:.4f}){memory.RESET}")
                    else:
                        print(f"{memory.DIM}  {key}: no source files found{memory.RESET}")
                print()
            continue

        if command_lower == "/characters":
            if memory.active_project != "first-light":
                print(f"{memory.DIM}Switch to the first-light project first: /project first-light{memory.RESET}\n")
                continue
            characters = creative.load_characters()
            if not characters:
                print(f"{memory.DIM}No characters indexed. Run /update bible to build the index.{memory.RESET}\n")
                continue
            print(f"{memory.DIM}Characters ({len(characters)}):")
            for i, c in enumerate(characters, 1):
                role = f" — {c['role']}" if c.get('role') else ""
                print(f"  {i}. {memory.CYAN}{c['name']}{memory.RESET}{memory.DIM}{role}")
            print(memory.RESET)
            continue

        if command_lower.startswith("/character "):
            if memory.active_project != "first-light":
                print(f"{memory.DIM}Switch to the first-light project first: /project first-light{memory.RESET}\n")
                continue
            name = command[11:].strip()
            if not name:
                print(f"{memory.DIM}Usage: /character <name>{memory.RESET}\n")
                continue
            char = creative.find_character(name)
            if char is None:
                print(f"{memory.DIM}No character found matching: {name}{memory.RESET}\n")
                continue
            print(f"\n{memory.CYAN}{creative.format_character(char)}{memory.RESET}\n")
            continue

        if command_lower == "/locations":
            if memory.active_project != "first-light":
                print(f"{memory.DIM}Switch to the first-light project first: /project first-light{memory.RESET}\n")
                continue
            locations = creative.load_locations()
            if not locations:
                print(f"{memory.DIM}No locations indexed. Run /update bible to build the index.{memory.RESET}\n")
                continue
            print(f"{memory.DIM}Locations ({len(locations)}):")
            for i, loc in enumerate(locations, 1):
                print(f"  {i}. {memory.CYAN}{loc['name']}{memory.RESET}")
            print(memory.RESET)
            continue

        if command_lower.startswith("/location "):
            if memory.active_project != "first-light":
                print(f"{memory.DIM}Switch to the first-light project first: /project first-light{memory.RESET}\n")
                continue
            name = command[10:].strip()
            if not name:
                print(f"{memory.DIM}Usage: /location <name>{memory.RESET}\n")
                continue
            loc = creative.find_location(name)
            if loc is None:
                print(f"{memory.DIM}No location found matching: {name}{memory.RESET}\n")
                continue
            print(f"\n{memory.CYAN}{creative.format_location(loc)}{memory.RESET}\n")
            continue

        # Skip empty messages
        if not command:
            continue

        # Add the user's message to the conversation history
        models.conversation_history.append({"role": "user", "content": user_input})

        # Route: let the director decide if a specialist should handle this
        routing = models.route_message(user_input)
        if routing.get("action") == "delegate":
            specialist_name = routing["specialist"]
            task = routing.get("task", user_input)
            spec = models.SPECIALISTS[specialist_name]
            print(f"\n{memory.DIM}\u25c7 Delegating to {specialist_name} ({spec['label']})...{memory.RESET}")
            specialist_result, s_in, s_out, s_cost = models.delegate_to_specialist(specialist_name, task)
            print(f"{memory.DIM}  \u21b3 {specialist_name} finished [{s_in} in / {s_out} out \u2014 ${s_cost:.4f}]{memory.RESET}")

            models.conversation_history[-1]["content"] = (
                f"{user_input}\n\n"
                f"[Specialist result from {specialist_name}:]\n\n"
                f"{specialist_result}\n\n"
                f"[Synthesize this specialist output into your response. "
                f"Present it naturally \u2014 add context or framing as needed, "
                f"or present it as-is if it's already well-formatted.]"
            )

        chat_turn()
        result = models.compress_conversation()
        if result:
            old_tokens, new_tokens, removed, kept = result
            print(f"\n{memory.DIM}\u27e1 Context compressed: ~{old_tokens:,} \u2192 ~{new_tokens:,} tokens "
                  f"({removed} exchanges summarized, {kept} kept){memory.RESET}")
