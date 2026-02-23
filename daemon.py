"""
Background daemon for First Contact — single entry point for all services.

Spawns and supervises web_ui, discord, and telegram as subprocesses
(auto-restart on crash). Also runs scheduled tasks (briefing, email
checks, job scans, reminders) and routes results to configured
notification channels.

Usage:
    python daemon.py                      # Run everything in foreground
    python daemon.py --detach             # Run everything as background process
    python daemon.py --hot-reload         # Auto-restart services on file changes
    python daemon.py --detach --hot-reload

Stops gracefully on SIGTERM/SIGINT (terminates all child services).
"""

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import signal
import subprocess
import sys
import threading
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
    "auto_start_web_ui": True,
    "auto_start_discord": True,
    "auto_start_telegram": True,
    "hot_reload": False,
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


# --- Service subprocess management ---

def _build_service_list(cfg):
    """Build list of services the daemon can auto-start."""
    import service_registry
    service_registry.check_all()
    return [
        {
            "name": "web_ui",
            "cmd": [sys.executable, os.path.join(BASE_DIR, "web_ui", "server.py")],
            "process": None,
            "enabled": cfg.get("auto_start_web_ui", True),
            "available": True,  # only needs ANTHROPIC_API_KEY, already validated
        },
        {
            "name": "discord",
            "cmd": [sys.executable, os.path.join(BASE_DIR, "discord_bot.py")],
            "process": None,
            "enabled": cfg.get("auto_start_discord", True),
            "available": service_registry.is_available("discord"),
        },
        {
            "name": "telegram",
            "cmd": [sys.executable, os.path.join(BASE_DIR, "telegram_bot.py")],
            "process": None,
            "enabled": cfg.get("auto_start_telegram", True),
            "available": service_registry.is_available("telegram"),
        },
    ]


def _start_service(svc, log, log_file):
    """Spawn a service subprocess with output going to the daemon log."""
    try:
        svc["process"] = subprocess.Popen(
            svc["cmd"],
            stdout=log_file,
            stderr=log_file,
        )
        log.info("Started %s (PID %d)", svc["name"], svc["process"].pid)
    except Exception as e:
        log.error("Failed to start %s: %s", svc["name"], e)


def _stop_services(services, log):
    """Terminate all running service subprocesses."""
    for svc in services:
        proc = svc["process"]
        if proc and proc.poll() is None:
            log.info("Stopping %s (PID %d)...", svc["name"], proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("Killing %s (PID %d)", svc["name"], proc.pid)
                proc.kill()
                proc.wait()


def _restart_service(svc, log, log_file):
    """Stop and restart a single service subprocess."""
    proc = svc["process"]
    if proc and proc.poll() is None:
        log.info("Stopping %s (PID %d) for restart...", svc["name"], proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("Killing %s (PID %d)", svc["name"], proc.pid)
            proc.kill()
            proc.wait()
    _start_service(svc, log, log_file)


def _check_services(services, log, log_file, running):
    """Restart any service that has exited unexpectedly."""
    if not running:
        return
    for svc in services:
        proc = svc["process"]
        if proc is None:
            continue
        rc = proc.poll()
        if rc is not None:
            log.warning("%s exited (code %d), restarting in 3s", svc["name"], rc)
            time.sleep(3)
            _start_service(svc, log, log_file)


# --- Hot reload (optional watchdog-based file watching) ---

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    Observer = None
    FileSystemEventHandler = object  # Allow class definition without watchdog

# Directories to ignore when watching for changes
_EXCLUDED_DIRS = {
    "__pycache__", ".git", "tests", "venv", "conversations",
    "projects", "logs", "workspace", "skills", "node_modules",
}


class FileChangeHandler(FileSystemEventHandler):
    """Debounced file change handler that restarts affected daemon services."""

    def __init__(self, services, log, log_file, base_dir):
        super().__init__()
        self.services = services
        self.log = log
        self.log_file = log_file
        self.base_dir = base_dir
        self._pending_files = set()
        self._timer = None
        self._lock = threading.Lock()

    def _is_excluded(self, path):
        """Check if path is in an excluded directory."""
        rel = os.path.relpath(path, self.base_dir)
        parts = rel.replace(os.sep, "/").split("/")
        return any(p in _EXCLUDED_DIRS for p in parts)

    def on_modified(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".py"):
            return
        if self._is_excluded(event.src_path):
            return
        rel = os.path.relpath(event.src_path, self.base_dir)
        with self._lock:
            self._pending_files.add(rel.replace(os.sep, "/"))
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(2.0, self._do_restarts)
            self._timer.daemon = True
            self._timer.start()

    on_created = on_modified

    def _determine_restarts(self, changed_files):
        """Map changed files to service names that need restarting."""
        restart = set()
        for f in changed_files:
            if f == "daemon.py":
                self.log.warning("daemon.py changed — manual restart required")
                continue
            if f.startswith("web_ui/"):
                restart.add("web_ui")
            elif f == "discord_bot.py":
                restart.add("discord")
            elif f == "telegram_bot.py":
                restart.add("telegram")
            elif f.startswith("plugins/"):
                # Plugin change affects all services
                for svc in self.services:
                    restart.add(svc["name"])
            else:
                # Core module change — restart all
                for svc in self.services:
                    restart.add(svc["name"])
        return restart

    def _do_restarts(self):
        """Debounce callback — restart affected services."""
        with self._lock:
            changed = set(self._pending_files)
            self._pending_files.clear()
            self._timer = None
        if not changed:
            return
        self.log.info("File changes detected: %s", ", ".join(sorted(changed)))
        restart_names = self._determine_restarts(changed)
        for svc in self.services:
            if svc["name"] in restart_names:
                proc = svc["process"]
                if proc and proc.poll() is None:
                    self.log.info("Hot-reloading %s...", svc["name"])
                    _restart_service(svc, self.log, self.log_file)


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


def run(hot_reload=False):
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

    # Start managed services (web_ui, discord, telegram)
    services = _build_service_list(cfg)
    log_fh = open(LOG_FILE, "a")
    for svc in services:
        if svc["enabled"] and svc["available"]:
            _start_service(svc, log, log_fh)
        elif svc["enabled"] and not svc["available"]:
            log.info("Skipping %s (credentials not configured)", svc["name"])

    # Hot reload — watch for file changes and restart affected services
    observer = None
    enable_hot_reload = hot_reload or cfg.get("hot_reload", False)
    if enable_hot_reload:
        if Observer is not None:
            handler = FileChangeHandler(services, log, log_fh, BASE_DIR)
            observer = Observer()
            observer.schedule(handler, BASE_DIR, recursive=True)
            observer.start()
            log.info("Hot reload enabled — watching for file changes")
        else:
            log.warning("Hot reload requested but watchdog not installed (pip install watchdog)")

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

        # Check managed services and restart any that crashed
        _check_services(services, log, log_fh, running)

        # Sleep 30 seconds between cycles
        for _ in range(30):
            if not running:
                break
            time.sleep(1)

    log.info("Daemon stopped.")
    if observer is not None:
        observer.stop()
        observer.join()
    _stop_services(services, log)
    log_fh.close()
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
    run(hot_reload="--hot-reload" in sys.argv)
