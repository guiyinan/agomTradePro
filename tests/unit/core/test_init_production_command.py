"""Production initialization delegation and failure contracts."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management.base import CommandError

from core.management.commands import init_production as module


def test_init_production_executes_canonical_bootstrap_once(monkeypatch) -> None:
    """A successful compatibility call executes the real cold-start command."""

    calls: list[str] = []

    def _call(command_name: str, **kwargs: object) -> None:
        assert "stdout" in kwargs
        assert "stderr" in kwargs
        calls.append(command_name)

    monkeypatch.setattr(module, "call_command", _call)
    command = module.Command(stdout=StringIO(), stderr=StringIO())

    command.handle(dry_run=False, skip="")

    assert calls == ["bootstrap_cold_start"]
    assert "Production initialization complete" in command.stdout.getvalue()


def test_init_production_dry_run_has_no_side_effect(monkeypatch) -> None:
    """Dry-run reports the concrete delegate without importing legacy scripts."""

    monkeypatch.setattr(
        module,
        "call_command",
        lambda *_args, **_kwargs: pytest.fail("executed bootstrap"),
    )
    command = module.Command(stdout=StringIO())

    command.handle(dry_run=True, skip="")

    assert "python manage.py bootstrap_cold_start" in command.stdout.getvalue()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"dry_run": "false", "skip": ""}, "--dry-run"),
        ({"dry_run": False, "skip": None}, "--skip"),
        ({"dry_run": False, "skip": "indicators"}, "no longer supported"),
    ],
)
def test_init_production_rejects_unsafe_legacy_options_before_delegation(
    monkeypatch,
    options: dict[str, object],
    message: str,
) -> None:
    """Dynamic values and unmappable partial skips fail before any bootstrap call."""

    monkeypatch.setattr(
        module,
        "call_command",
        lambda *_args, **_kwargs: pytest.fail("executed bootstrap"),
    )

    with pytest.raises(CommandError, match=message):
        module.Command(stdout=StringIO()).handle(**options)


def test_init_production_propagates_bootstrap_failure_without_success(monkeypatch) -> None:
    """A required cold-start failure cannot be converted into initialization success."""

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise CommandError("required step failed")

    monkeypatch.setattr(module, "call_command", _fail)
    command = module.Command(stdout=StringIO())

    with pytest.raises(CommandError, match="required step failed"):
        command.handle(dry_run=False, skip="")

    assert "Production initialization complete" not in command.stdout.getvalue()
