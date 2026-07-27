"""Confidence configuration bootstrap safety contracts."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError

from apps.audit.infrastructure.models import ConfidenceConfigModel


@pytest.mark.django_db
def test_confidence_seed_is_derived_from_model_defaults(monkeypatch) -> None:
    """Changing the schema default changes bootstrap without editing the command."""

    field = ConfidenceConfigModel._meta.get_field("base_confidence")
    monkeypatch.setattr(field, "default", 0.55)

    call_command("init_confidence_config", stdout=StringIO())

    config = ConfidenceConfigModel._default_manager.get(is_active=True)
    assert config.base_confidence == 0.55


@pytest.mark.django_db
def test_confidence_command_rejects_multiple_active_rows() -> None:
    """Ambiguous runtime truth fails closed instead of refreshing an arbitrary row."""

    ConfidenceConfigModel._default_manager.create(description="first")
    ConfidenceConfigModel._default_manager.create(description="second")
    output = StringIO()

    with pytest.raises(CommandError, match="Multiple active"):
        call_command("init_confidence_config", refresh=True, stdout=output)

    assert "initialized successfully" not in output.getvalue()


@pytest.mark.django_db(transaction=True)
def test_confidence_refresh_rolls_back_and_redacts_database_failure(monkeypatch) -> None:
    """A post-write database failure restores the governed row and hides raw details."""

    config = ConfidenceConfigModel._default_manager.create(
        base_confidence=0.91,
        description="governed",
    )
    original_save = ConfidenceConfigModel.save

    def failing_save(self: ConfidenceConfigModel, *args: object, **kwargs: object) -> None:
        original_save(self, *args, **kwargs)
        raise DatabaseError("credential=secret")

    monkeypatch.setattr(ConfidenceConfigModel, "save", failing_save)
    output = StringIO()

    with pytest.raises(CommandError, match=r"failed \(DatabaseError\)") as exc_info:
        call_command("init_confidence_config", refresh=True, stdout=output)

    config.refresh_from_db()
    combined = f"{exc_info.value}\n{output.getvalue()}"
    assert config.base_confidence == 0.91
    assert config.description == "governed"
    assert "secret" not in combined
    assert "initialized successfully" not in combined


def test_confidence_command_rejects_non_boolean_refresh_before_seed(monkeypatch) -> None:
    """Dynamic callers cannot use truthy strings to overwrite governed configuration."""

    from apps.audit.management.commands import init_confidence_config

    command = init_confidence_config.Command(stdout=StringIO())
    seed_calls: list[bool] = []
    monkeypatch.setattr(
        init_confidence_config,
        "_build_default_config",
        lambda: seed_calls.append(True),
    )

    with pytest.raises(CommandError, match="refresh must be a boolean"):
        command.handle(refresh="yes")

    assert seed_calls == []
