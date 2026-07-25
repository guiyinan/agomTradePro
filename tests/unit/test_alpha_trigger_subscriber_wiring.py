"""Production wiring contracts for Alpha Trigger event subscribers."""

from pathlib import Path

import pytest

from apps.alpha_trigger.application import subscribers
from apps.alpha_trigger.application.handlers import AlphaTriggerEventHandler
from apps.alpha_trigger.application.use_cases import CreateAlphaTriggerUseCase


def test_alpha_trigger_handler_factory_uses_repository_provider(monkeypatch) -> None:
    """Build the signal handler with the canonical trigger repository provider."""

    repository = object()
    monkeypatch.setattr(
        subscribers,
        "get_alpha_trigger_repository",
        lambda: repository,
        raising=False,
    )

    handler = subscribers._create_alpha_trigger_handler()

    assert isinstance(handler, AlphaTriggerEventHandler)
    assert isinstance(handler.create_trigger_use_case, CreateAlphaTriggerUseCase)
    assert handler.create_trigger_use_case.trigger_repository is repository


def test_deploy_check_reports_alpha_trigger_factory_failure(monkeypatch) -> None:
    """Surface subscriber construction failures as a Django deploy error."""

    from apps.alpha_trigger import checks

    def fail_to_build_handler() -> None:
        raise RuntimeError("broken subscriber wiring")

    monkeypatch.setattr(checks, "_create_alpha_trigger_handler", fail_to_build_handler)

    errors = checks.check_alpha_trigger_subscriber_wiring(None)

    assert [error.id for error in errors] == ["alpha_trigger.E001"]
    assert "broken subscriber wiring" in errors[0].msg


def test_alpha_trigger_registration_failure_propagates(monkeypatch) -> None:
    """Do not report a healthy startup after registry writes fail."""

    class BrokenRegistry:
        def register(self, **_kwargs: object) -> None:
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        subscribers,
        "get_event_subscriber_registry",
        BrokenRegistry,
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        subscribers.register_subscribers()


def test_production_entrypoint_runs_deploy_checks_before_migrations() -> None:
    """Block container startup before migrations when deploy checks fail."""

    project_root = Path(__file__).resolve().parents[2]
    entrypoint = (project_root / "docker" / "entrypoint.prod.sh").read_text(encoding="utf-8")

    deploy_check_offset = entrypoint.index("python manage.py check --deploy")
    migrate_offset = entrypoint.index("python manage.py migrate --noinput")

    assert deploy_check_offset < migrate_offset
