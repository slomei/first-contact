"""Smoke tests: verify all core modules import without errors."""


def test_import_memory():
    import memory
    assert hasattr(memory, "BASE_DIR")


def test_import_models():
    import models
    assert hasattr(models, "MODELS")


def test_import_tools():
    import tools
    assert hasattr(tools, "TOOLS")


def test_import_tasks():
    import tasks
    assert hasattr(tasks, "add_task")


def test_import_briefing():
    import briefing
    assert hasattr(briefing, "run_briefing_discord")


def test_import_notifications():
    import notifications
    assert hasattr(notifications, "check_new_emails")


def test_import_documents():
    import documents


def test_import_job_scanner():
    import job_scanner


def test_import_onboarding():
    import onboarding
    assert hasattr(onboarding, "OnboardingWizard")


def test_import_help_data():
    import help_data
    assert hasattr(help_data, "HELP_CATEGORIES")
    assert hasattr(help_data, "fuzzy_match_category")


def test_import_creative():
    import creative
    assert hasattr(creative, "load_characters")


def test_import_sync():
    import sync


def test_import_skills_loader():
    import skills_loader
    assert hasattr(skills_loader, "list_skills")


def test_import_daemon():
    import daemon


def test_daemon_functions_exist():
    """Daemon task functions exist and are callable."""
    import daemon
    assert callable(daemon.run)
    assert callable(daemon._run_briefing)
    assert callable(daemon._run_email_check)
    assert callable(daemon._run_job_scan)
    assert callable(daemon._run_reminder_check)
    assert callable(daemon._get_config)
    assert callable(daemon._send_notification)


def test_daemon_config_loads():
    """Daemon config loads with defaults for missing keys."""
    import daemon
    cfg = daemon._get_config()
    assert isinstance(cfg, dict)
    assert "enabled" in cfg
    assert "briefing_time" in cfg
    assert "email_check_interval_minutes" in cfg
    assert "notify_channel" in cfg


def test_import_batch_api():
    import batch_api
    assert hasattr(batch_api, "submit_batch")
    assert hasattr(batch_api, "poll_until_done")
    assert hasattr(batch_api, "retrieve_results")
