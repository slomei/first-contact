"""
Background daemon for First Contact.

Runs scheduled tasks (briefing, email checks, job scans, reminders)
and routes results to configured notification channels.

Usage:
    python daemon.py           # Run in foreground
    python daemon.py --detach  # Run as background process

Stops gracefully on SIGTERM/SIGINT.
"""

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta

import memory

BASE_DIR = memory.BASE_DIR
PID_FILE = os.path.join(BASE_DIR, "daemon.pid")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "daemon.log")

# Defaults if config.json has no daemon section
DEFAULTS = {
    "enabled": True,
    "briefing_time": "07:00",
    "email_check_interval_minutes": 30,
    "scan_interval_hours": 12,
    "reminder_check_interval_minutes": 5,
    "heartbeat_interval_minutes": 30,
    "notify_channel": "discord",
}


def _get_config():
    """Load daemon config, merging defaults for missing keys."""
    cfg = memory.load_config().get("daemon", {})
    merged = dict(DEFAULTS)
    merged.update(cfg)
    return merged


def _setup_logging():
    """Configure logging to file + stderr."""
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    logger = logging.getLogger("daemon")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def _write_pid():
    """Write current PID to daemon.pid. Returns False if already running."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process is still alive
            os.kill(old_pid, 0)
            return False  # Another daemon is running
        except (OSError, ValueError):
            pass  # Stale PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def _remove_pid():
    """Remove PID file on shutdown."""
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


# --- Notification delivery ---

def _send_notification(text, log, channels=None):
    """Send a notification to all configured channels. Falls back to log-only."""
    if channels is None:
        channels = ["discord"]
    if isinstance(channels, str):
        channels = [channels]
    delivered = False
    for channel in channels:
        if channel == "discord":
            try:
                _send_discord_notification(text)
                delivered = True
            except Exception as e:
                log.warning("Discord notification failed: %s", e)
        elif channel == "telegram":
            try:
                _send_telegram_notification(text)
                delivered = True
            except Exception as e:
                log.warning("Telegram notification failed: %s", e)
        elif channel == "email":
            try:
                import notifications
                notifications.send_email_notification("First Contact Alert", text)
                delivered = True
            except Exception as e:
                log.warning("Email notification failed: %s", e)
    if not delivered:
        log.info("Notification (no delivery): %s", text[:200])


def _send_discord_notification(text):
    """Send a message to the Discord owner via webhook or REST API."""
    import requests
    token = os.environ.get("DISCORD_BOT_TOKEN")
    user_id = os.environ.get("DISCORD_USER_ID")
    if not token or not user_id:
        raise RuntimeError("DISCORD_BOT_TOKEN or DISCORD_USER_ID not set")
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    # Create DM channel
    r = requests.post(
        "https://discord.com/api/v10/users/@me/channels",
        headers=headers,
        json={"recipient_id": user_id},
        timeout=10,
    )
    r.raise_for_status()
    dm_channel = r.json()["id"]
    # Send message (truncate if needed)
    for chunk in [text[i:i+1900] for i in range(0, len(text), 1900)]:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{dm_channel}/messages",
            headers=headers,
            json={"content": chunk},
            timeout=10,
        )
        r.raise_for_status()


def _send_telegram_notification(text):
    """Send a message to the Telegram owner."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    user_id = os.environ.get("TELEGRAM_USER_ID")
    if not token or not user_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not set")
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": user_id, "text": chunk},
            timeout=10,
        )
        r.raise_for_status()


# --- Scheduled tasks ---

def _run_briefing(log, channels):
    """Generate and send the daily briefing."""
    import briefing
    log.info("Running daily briefing...")
    try:
        data = briefing.generate_briefing()
        email_data, calendar_data, tasks_data, jobs_data, reminders_data, watchlist_data, scan_data, cost = data
        text = briefing.format_briefing_discord(
            email_data, tasks_data, jobs_data, reminders_data, watchlist_data,
            cost, calendar_data=calendar_data, scan_data=scan_data,
        )
        _send_notification(text, log, channels)
        log.info("Briefing sent (cost: $%.4f)", cost)
        # Update last_sent in config so restarts don't re-fire today
        full_cfg = memory.load_config()
        full_cfg.setdefault("briefing", {})["last_sent"] = memory.local_now().strftime("%Y-%m-%d")
        memory.save_config(full_cfg)
    except Exception as e:
        log.error("Briefing failed: %s", e)


def _run_email_check(log, channels):
    """Check for new important emails and notify."""
    import notifications
    log.info("Checking email...")
    try:
        classified = notifications.check_new_emails()
        if classified.get("error"):
            log.warning("Email check error: %s", classified["error"])
            return
        high = classified.get("high", [])
        if high:
            for email_data, priority in high:
                text = notifications.format_notification_discord(email_data, priority)
                _send_notification(text, log, channels)
            log.info("Sent %d high-priority email notification(s)", len(high))
        else:
            log.info("No new high-priority emails")
    except Exception as e:
        log.error("Email check failed: %s", e)


def _run_job_scan(log, channels):
    """Run a job scan and notify on strong matches."""
    import job_scanner
    log.info("Running job scan...")
    try:
        results = job_scanner.run_scan(scan_type="auto")
        if not results["ok"]:
            log.warning("Scan skipped: %s", results["error"])
            return
        high = results.get("high", [])
        if high:
            text = job_scanner.format_scan_notification_discord(results)
            if text:
                _send_notification(text, log, channels)
        log.info("Scan complete: %d strong, %d possible (cost: $%.4f)",
                 len(high), len(results.get("medium", [])), results["cost"])
    except Exception as e:
        log.error("Job scan failed: %s", e)


def _run_reminder_check(log, channels):
    """Check for due reminders and send notifications."""
    import tasks as task_mod
    try:
        triggered = task_mod.check_due_reminders()
        for r in triggered:
            text = f"**Reminder:** {r['description']}"
            _send_notification(text, log, channels)
        if triggered:
            log.info("Delivered %d reminder(s)", len(triggered))
    except Exception as e:
        log.error("Reminder check failed: %s", e)


# --- Main loop ---

def _next_occurrence(now, hour, minute):
    """Return the next datetime at hour:minute from now (today or tomorrow)."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def run():
    """Main daemon loop."""
    log = _setup_logging()

    if not _write_pid():
        log.error("Daemon already running (PID file exists and process alive). Exiting.")
        sys.exit(1)

    # Graceful shutdown
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        log.info("Received signal %s, shutting down...", signum)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    cfg = _get_config()
    if not cfg.get("enabled", True):
        log.info("Daemon disabled in config. Exiting.")
        _remove_pid()
        sys.exit(0)

    # Bug fix: read ALL configured notification channels, not just one
    full_cfg = memory.load_config()
    channels = full_cfg.get("notification_channels", [])
    if not channels:
        # Fallback to legacy single-channel setting
        channels = [cfg.get("notify_channel", "discord")]
    log.info("Daemon started (PID %d, channels=%s)", os.getpid(), ",".join(channels))

    # Parse scheduled briefing time
    briefing_hour, briefing_min = 7, 0
    try:
        parts = cfg["briefing_time"].split(":")
        briefing_hour, briefing_min = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        pass

    email_interval = timedelta(minutes=cfg.get("email_check_interval_minutes", 30))
    scan_interval = timedelta(hours=cfg.get("scan_interval_hours", 12))
    reminder_interval = timedelta(minutes=cfg.get("reminder_check_interval_minutes", 5))
    heartbeat_interval = timedelta(minutes=cfg.get("heartbeat_interval_minutes", 30))

    now = memory.local_now()

    # Bug fix: initialize last-run times to NOW so interval tasks wait one
    # full cycle before first execution — no more fire-on-startup.
    last_email = now
    last_scan = now
    last_reminder = now
    last_heartbeat = now

    # Bug fix: compute next briefing time instead of firing retroactively.
    # If briefing was already sent today (per config), push to tomorrow.
    next_briefing = _next_occurrence(now, briefing_hour, briefing_min)
    last_sent_str = full_cfg.get("briefing", {}).get("last_sent")
    if last_sent_str:
        try:
            last_sent_date = datetime.strptime(last_sent_str, "%Y-%m-%d").date()
            if last_sent_date == now.date() and next_briefing.date() == now.date():
                next_briefing += timedelta(days=1)
        except ValueError:
            pass
    log.info("Next briefing scheduled for %s", next_briefing.strftime("%Y-%m-%d %H:%M"))

    # Check for API key early
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    api_available = bool(api_key)
    if not api_available:
        log.warning("ANTHROPIC_API_KEY not set — API-dependent tasks (briefing, scan) disabled")

    while running:
        now = memory.local_now()

        # Daily briefing — fire only when the scheduled time arrives
        if api_available and now >= next_briefing:
            _run_briefing(log, channels)
            next_briefing = _next_occurrence(now, briefing_hour, briefing_min)
            log.info("Next briefing scheduled for %s", next_briefing.strftime("%Y-%m-%d %H:%M"))

        # Email check
        if now - last_email >= email_interval:
            _run_email_check(log, channels)
            last_email = now

        # Job scan
        if api_available and now - last_scan >= scan_interval:
            _run_job_scan(log, channels)
            last_scan = now

        # Reminder check
        if now - last_reminder >= reminder_interval:
            _run_reminder_check(log, channels)
            last_reminder = now

        # Heartbeat
        if now - last_heartbeat >= heartbeat_interval:
            log.info("Heartbeat — daemon alive (PID %d)", os.getpid())
            last_heartbeat = now

        # Sleep 30 seconds between cycles
        for _ in range(30):
            if not running:
                break
            time.sleep(1)

    log.info("Daemon stopped.")
    _remove_pid()


if __name__ == "__main__":
    if "--detach" in sys.argv:
        # Fork into background
        pid = os.fork()
        if pid > 0:
            print(f"Daemon started (PID {pid})")
            sys.exit(0)
        # Child: detach from terminal
        os.setsid()
        # Redirect stdout/stderr to log
        os.makedirs(LOG_DIR, exist_ok=True)
        sys.stdout = open(LOG_FILE, "a")
        sys.stderr = sys.stdout
    run()
