"""
Email notification system — classification, formatting, logging, rate limiting.

Imports memory (base module) and tools (for Gmail access). No circular dependencies.
"""

import json
import os
import re
from datetime import datetime, timedelta

import memory


# --- Constants ---

NOTIFICATION_LOG = os.path.join(memory.BASE_DIR, "logs", "notifications.log")
SEEN_FILE = os.path.join(memory.BASE_DIR, "logs", "seen_emails.json")
RATE_LIMIT_PER_HOUR = 20


# --- Seen message tracking ---

def load_seen():
    """Load set of seen message IDs. Prunes entries older than 7 days."""
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Prune old entries (older than 7 days)
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    pruned = {k: v for k, v in data.items() if v > cutoff}
    return pruned


def save_seen(seen):
    """Save seen message IDs with timestamps."""
    log_dir = os.path.dirname(SEEN_FILE)
    os.makedirs(log_dir, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def mark_seen(seen, message_id):
    """Mark a message as seen."""
    seen[message_id] = datetime.now().isoformat()


# --- Classification ---

def _extract_domain(sender):
    """Extract domain from a sender string like 'Name <user@domain.com>'."""
    match = re.search(r'[\w.+-]+@([\w.-]+)', sender)
    return match.group(1).lower() if match else ""


def _extract_email(sender):
    """Extract full email from sender string."""
    match = re.search(r'[\w.+-]+@[\w.-]+', sender)
    return match.group(0).lower() if match else sender.lower()


def classify_email(email_data, config):
    """Classify an email as high, medium, or low priority.

    email_data: dict with 'sender', 'subject', 'snippet' keys
    config: the email_notifications config dict

    Returns 'high', 'medium', or 'low'.
    """
    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    snippet = email_data.get("snippet", "")
    sender_email = _extract_email(sender)
    sender_domain = _extract_domain(sender)

    # Check mute list first — muted = low
    mute_domains = config.get("mute_domains", [])
    for pattern in mute_domains:
        pattern_lower = pattern.lower()
        if "@" in pattern_lower:
            # Full or partial email match
            if pattern_lower in sender_email:
                return "low"
        else:
            # Domain match
            if sender_domain == pattern_lower or sender_domain.endswith("." + pattern_lower):
                return "low"

    # Check priority domains — domain match = high
    priority_domains = config.get("priority_domains", [])
    for domain in priority_domains:
        domain_lower = domain.lower()
        if sender_domain == domain_lower or sender_domain.endswith("." + domain_lower):
            return "high"

    # Check priority keywords in subject + snippet — keyword match = high
    priority_keywords = config.get("priority_keywords", [])
    searchable = f"{subject} {snippet}".lower()
    for keyword in priority_keywords:
        if keyword.lower() in searchable:
            return "high"

    # Everything else = medium
    return "medium"


# --- Rate limiting ---

def _load_rate_log():
    """Load notification timestamps from last hour for rate limiting."""
    if not os.path.exists(NOTIFICATION_LOG):
        return []
    cutoff = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    timestamps = []
    try:
        with open(NOTIFICATION_LOG, "r") as f:
            for line in f:
                # Lines start with [YYYY-MM-DD HH:MM:SS]
                match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
                if match:
                    ts = match.group(1)
                    if ts >= cutoff:
                        timestamps.append(ts)
    except OSError:
        pass
    return timestamps


def check_rate_limit():
    """Check if we're under the rate limit. Returns True if OK to send."""
    recent = _load_rate_log()
    return len(recent) < RATE_LIMIT_PER_HOUR


def get_rate_count():
    """Return how many notifications sent in the last hour."""
    return len(_load_rate_log())


# --- Logging ---

def log_notification(email_data, priority, action):
    """Log a notification to the audit log.

    action: 'sent', 'batched', 'skipped', 'rate_limited'
    """
    log_dir = os.path.dirname(NOTIFICATION_LOG)
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sender = email_data.get("sender", "Unknown")
    subject = email_data.get("subject", "(no subject)")
    entry = (
        f"[{timestamp}] priority={priority} action={action} "
        f"from={sender} subject={subject}\n"
    )
    with open(NOTIFICATION_LOG, "a") as f:
        f.write(entry)


# --- Formatting ---

def _format_sender(sender):
    """Extract a clean display name from 'Name <email>' format."""
    match = re.match(r'^"?([^"<]+)"?\s*<', sender)
    if match:
        return match.group(1).strip()
    return sender


def format_notification_discord(email_data, priority):
    """Format an email notification for Discord DM."""
    sender = _format_sender(email_data.get("sender", "Unknown"))
    subject = email_data.get("subject", "(no subject)")
    snippet = email_data.get("snippet", "")
    if len(snippet) > 150:
        snippet = snippet[:150] + "..."

    if priority == "high":
        header = "**\u26a0\ufe0f New Email [HIGH]**"
    else:
        header = "**New Email**"

    return (
        f"{header}\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"> {snippet}"
    )


def format_batch_discord(emails):
    """Format a batch of medium-priority emails for Discord."""
    if not emails:
        return ""
    lines = [f"**Email Summary** ({len(emails)} new)"]
    for e in emails[:10]:  # Cap at 10 per batch
        sender = _format_sender(e.get("sender", "Unknown"))
        subject = e.get("subject", "(no subject)")
        lines.append(f"- **{sender}**: {subject}")
    if len(emails) > 10:
        lines.append(f"*...and {len(emails) - 10} more*")
    return "\n".join(lines)


# --- Main check function ---

def check_new_emails():
    """Check Gmail for new unread emails and classify them.

    Returns a dict:
        {
            'high': [list of (email_data, 'high') tuples],
            'medium': [list of (email_data, 'medium') tuples],
            'low': [list of (email_data, 'low') tuples],
            'error': None or error string,
        }
    """
    import tools

    config = memory.load_config().get("email_notifications", {})
    if not config.get("enabled", True):
        return {"high": [], "medium": [], "low": [], "error": None}

    result = tools.gmail_check_all(max_results=20)
    if result is None:
        return {"high": [], "medium": [], "low": [], "error": "Gmail not authenticated"}
    if isinstance(result, str):
        return {"high": [], "medium": [], "low": [], "error": result}

    seen = load_seen()
    classified = {"high": [], "medium": [], "low": [], "error": None}

    for email_data in result:
        msg_id = email_data.get("id", "")
        if msg_id in seen:
            continue

        priority = classify_email(email_data, config)
        classified[priority].append((email_data, priority))
        mark_seen(seen, msg_id)

    save_seen(seen)

    # Update last_checked timestamp
    config_full = memory.load_config()
    config_full["email_notifications"]["last_checked"] = datetime.now().isoformat()
    memory.save_config(config_full)

    return classified


# --- Email channel delivery ---

def send_email_notification(subject, body):
    """Create a self-addressed Gmail draft with notification content.

    Uses the primary (first) account for draft creation.
    Returns draft_id or None.
    """
    import tools
    profile = memory.get_user_profile()
    email = profile.get("email", "")
    if not email or email == "you@example.com":
        return None
    services = tools.get_all_gmail_services()
    if not services:
        return None
    _label, svc = services[0]
    return tools.gmail_create_draft(email, subject, body, service=svc)
