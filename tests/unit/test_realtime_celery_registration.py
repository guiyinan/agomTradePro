from core.celery import app


def test_realtime_application_tasks_are_registered_with_celery() -> None:
    """Application-layer realtime tasks should be autodiscovered by Celery workers."""
    app.loader.import_default_modules()

    assert "apps.realtime.application.tasks.poll_realtime_prices_task" in app.tasks
