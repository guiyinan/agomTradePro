"""Operator boundary contracts for full-universe publication rebuilds."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from apps.audit.application.system_audit_composition import (
    SystemAuditCompositionUnavailable,
)
from core.exceptions import MissingConfigError

COMMAND_MODULE = "apps.data_center.management.commands.rebuild_active_a_share_core_publications"


def _authority(actor_id: str = "django-user:7") -> SimpleNamespace:
    return SimpleNamespace(
        actor_id=actor_id,
        tenant_id="tenant:primary",
        owner_id="owner:data",
    )


def test_rebuild_command_is_dry_run_by_default(mocker) -> None:
    coordinator = mocker.Mock()
    coordinator.preview.return_value = SimpleNamespace(
        ready=True,
        to_dict=lambda: {"ready": True, "member_count": 6},
    )
    factory = mocker.patch(
        f"{COMMAND_MODULE}.make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "600000.SH"],
    )
    authority_preflight = mocker.patch(f"{COMMAND_MODULE}.preflight_data_reliability_audit_runtime")
    stdout = StringIO()

    call_command("rebuild_active_a_share_core_publications", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["ready"] is True
    coordinator.preview.assert_called_once()
    coordinator.execute.assert_not_called()
    authority_preflight.assert_not_called()
    factory.assert_called_once_with(created_by="ops.current_publication_rebuild.preview")


def test_rebuild_command_requires_operator_for_execute() -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            stdout=StringIO(),
        )


def test_rebuild_command_executes_with_explicit_operator(mocker) -> None:
    result = SimpleNamespace(
        published_count=6,
        to_dict=lambda: {
            "published_count": 6,
            "publication_ids": ["price", "valuation", "financial"],
        },
    )
    coordinator = mocker.Mock()
    coordinator.execute.return_value = result
    factory = mocker.patch(
        f"{COMMAND_MODULE}.make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "600000.SH"],
    )
    authority_preflight = mocker.patch(
        f"{COMMAND_MODULE}.preflight_data_reliability_audit_runtime",
        return_value=_authority(),
    )
    stdout = StringIO()

    call_command(
        "rebuild_active_a_share_core_publications",
        "--execute",
        "--operator",
        "django-user:7",
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "execute"
    assert payload["operator"] == "django-user:7"
    assert payload["published_count"] == 6
    coordinator.execute.assert_called_once()
    factory.assert_called_once_with(created_by="ops.current_publication_rebuild:django-user:7")
    authority_preflight.assert_called_once()


def test_rebuild_command_rejects_operator_not_bound_to_current_actor(mocker) -> None:
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ"],
    )
    mocker.patch(
        f"{COMMAND_MODULE}.preflight_data_reliability_audit_runtime",
        return_value=_authority(),
    )
    factory = mocker.patch(f"{COMMAND_MODULE}.make_core_current_publication_rebuild_use_case")

    with pytest.raises(CommandError, match="current server-issued actor"):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            "--operator",
            "different-operator",
            stdout=StringIO(),
        )

    factory.assert_not_called()


def test_rebuild_command_reports_stable_authority_preflight_denial(mocker) -> None:
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ"],
    )
    mocker.patch(
        f"{COMMAND_MODULE}.preflight_data_reliability_audit_runtime",
        side_effect=SystemAuditCompositionUnavailable(
            "authority unavailable",
            reason_code="authority_unavailable",
        ),
    )

    with pytest.raises(
        CommandError,
        match="audit authority preflight failed: authority_unavailable",
    ):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            "--operator",
            "django-user:7",
            stdout=StringIO(),
        )


def test_rebuild_command_reports_missing_universe_config(mocker) -> None:
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        side_effect=MissingConfigError("coverage universe is not initialized"),
    )

    with pytest.raises(CommandError, match="not initialized"):
        call_command("rebuild_active_a_share_core_publications", stdout=StringIO())


@pytest.mark.parametrize("operator", [" ", "x" * 101, "line\nbreak"])
def test_rebuild_command_rejects_invalid_operator(operator: str) -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            "--operator",
            operator,
            stdout=StringIO(),
        )
