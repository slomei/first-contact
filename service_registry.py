"""
Centralized service registry — answers "is X configured and working?" from one place.

Read-only: reports integration status but doesn't manage credentials.
All check functions use lazy imports to avoid circular dependencies.

Status values:
    UNCONFIGURED — required credentials/config not found
    CONFIGURED   — credentials exist but not fully validated
    HEALTHY      — credentials exist and fully set up
    ERROR        — check function raised an exception
"""

import os

# Status constants
UNCONFIGURED = "unconfigured"
CONFIGURED = "configured"
HEALTHY = "healthy"
ERROR = "error"

# Internal state
_registry = {}   # {name: check_fn}
_statuses = {}   # {name: status_string}


def register(name, check_fn):
    """Register a service with its check function."""
    _registry[name] = check_fn
    _statuses[name] = UNCONFIGURED


def check_all():
    """Run all check functions and update statuses. Returns {name: status}."""
    for name in _registry:
        check(name)
    return dict(_statuses)


def check(name):
    """Run one check function, update and return its status."""
    fn = _registry.get(name)
    if fn is None:
        return UNCONFIGURED
    try:
        _statuses[name] = fn()
    except Exception:
        _statuses[name] = ERROR
    return _statuses[name]


def get_status(name):
    """Return cached status for a service (no re-check)."""
    return _statuses.get(name, UNCONFIGURED)


def get_all_status():
    """Return {name: status} dict of all registered services."""
    return dict(_statuses)


def is_available(name):
    """True if service is CONFIGURED or HEALTHY."""
    return _statuses.get(name) in (CONFIGURED, HEALTHY)


def list_services():
    """Return list of registered service names."""
    return list(_registry.keys())


# ---------------------------------------------------------------------------
# Built-in check functions
# ---------------------------------------------------------------------------

def _check_discord():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return UNCONFIGURED
    user_id = os.environ.get("DISCORD_USER_ID")
    if user_id:
        return HEALTHY
    return CONFIGURED


def _check_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return UNCONFIGURED
    user_id = os.environ.get("TELEGRAM_USER_ID")
    if user_id:
        return HEALTHY
    return CONFIGURED


def _check_gmail():
    import memory
    config = memory.load_config()
    accounts = config.get("email_accounts", [])
    if not accounts:
        return UNCONFIGURED
    # Check if at least one credential file exists
    for account in accounts:
        cred_file = account.get("credentials_file", "")
        cred_path = os.path.join(memory.BASE_DIR, cred_file)
        if os.path.exists(cred_path):
            return HEALTHY
    return CONFIGURED


def _check_calendar():
    import memory
    cred_path = os.path.join(memory.BASE_DIR, "calendar_credentials.json")
    if os.path.exists(cred_path):
        return HEALTHY
    return UNCONFIGURED


def _check_web_search():
    return HEALTHY


def _check_job_search():
    return HEALTHY


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _register_builtins():
    """Register the six built-in services."""
    register("discord", _check_discord)
    register("telegram", _check_telegram)
    register("gmail", _check_gmail)
    register("calendar", _check_calendar)
    register("web_search", _check_web_search)
    register("job_search", _check_job_search)


def _reset():
    """Test-only: clear and re-register built-in services."""
    _registry.clear()
    _statuses.clear()
    _register_builtins()


# Register on import
_register_builtins()
