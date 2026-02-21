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
