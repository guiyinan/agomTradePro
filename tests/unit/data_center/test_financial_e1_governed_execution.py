"""No-DB tests for the DATA02 actor and simulated-account binding guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.data_center.application.data02_task_authority import Data02AuthorityRevalidation
from apps.data_center.infrastructure import financial_e1_governed_execution as _guard_module
from core.integration import financial_e1_simulated_account_owner as _binding_module


def test_real_command_imports_and_refuses_execution_before_reading_a_plan() -> None:
    """Load the real builder, then reject missing execute before DB or egress."""

    with pytest.raises(CommandError, match="--execute is required"):
        call_command(
            "run_financial_e1_discovery",
            plan_file="missing-e1-plan.json",
            plan_sha256="a" * 64,
            operator="django-user:7",
            execute=False,
        )


def _authority(*, actor_id: str = "django-user:7", user_id: int = 7) -> SystemAuditReaderContext:
    """Build an issued staff context bound to one current server actor."""

    return SystemAuditReaderContext._from_authority(
        authority_source_id="system-audit-owner-test",
        authority_source_version="v1",
        actor_id=actor_id,
        user_id=user_id,
        tenant_id="tenant-test",
        owner_id="owner-test",
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="owner",
        authority_state="active",
        authority_recorded_at=datetime(2026, 11, 16, tzinfo=UTC),
        authority_valid_until=datetime(2026, 11, 17, tzinfo=UTC),
    )


def _observation(
    *,
    account_id: int = 631,
    owner_user_id: int = 7,
    is_simulated: bool = True,
    is_active: bool = True,
) -> object:
    """Build the bridge's typed actual simulated-account query result."""

    return _binding_module.FinancialE1SimulatedAccountBindingObservation(
        account_id=account_id,
        owner_user_id=owner_user_id,
        is_simulated=is_simulated,
        is_active=is_active,
    )


def test_bridge_uses_owner_scoped_simulated_account_query_not_legacy_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same integer in the legacy Portfolio table is never an account binding."""

    calls: list[tuple[int, int]] = []

    def get_binding(*, owner_user_id: int, account_id: int) -> dict[str, object]:
        calls.append((owner_user_id, account_id))
        return {
            "owner_user_id": owner_user_id,
            "account_id": account_id,
            "account_type": "simulated",
            "is_active": True,
        }

    monkeypatch.setattr(_binding_module, "get_account_binding_identity", get_binding)

    observation = _binding_module.resolve_financial_e1_simulated_account_binding(
        user_id=7,
        account_id=631,
    )

    assert calls == [(7, 631)]
    assert type(observation) is _binding_module.FinancialE1SimulatedAccountBindingObservation
    assert observation.account_id == 631
    assert observation.owner_user_id == 7
    assert observation.is_simulated is True
    assert observation.is_active is True


def test_missing_simulated_binding_blocks_even_if_legacy_portfolio_uses_same_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy-only id collision cannot pass the actual simulated-account query."""

    monkeypatch.setattr(_binding_module, "get_account_binding_identity", lambda **kwargs: None)

    with pytest.raises(_guard_module.DataValidationError):
        _guard_module.DjangoFinancialE1ActorSimulatedAccountGuard(
            _authority(),
            simulated_account_id=631,
        )


def test_bridge_does_not_promote_a_real_account_to_simulated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual account_type field controls namespace eligibility."""

    monkeypatch.setattr(
        _binding_module,
        "get_account_binding_identity",
        lambda **kwargs: {
            "owner_user_id": kwargs["owner_user_id"],
            "account_id": kwargs["account_id"],
            "account_type": "real",
            "is_active": True,
        },
    )
    observation = _binding_module.resolve_financial_e1_simulated_account_binding(
        user_id=7,
        account_id=631,
    )

    assert type(observation) is _binding_module.FinancialE1SimulatedAccountBindingObservation
    assert observation.account_id == 631
    assert observation.is_simulated is False


def test_guard_rechecks_existing_authority_and_exact_simulated_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every boundary rereads DATA02 and the owner/type/active account binding."""

    rechecks: list[datetime] = []
    account_reads: list[tuple[int, int]] = []

    def current_authority(*args: object, **kwargs: object) -> Data02AuthorityRevalidation:
        del args
        rechecks.append(kwargs["as_of"])
        return Data02AuthorityRevalidation(True, "authority_current", 1)

    def current_account(*, user_id: int, account_id: int) -> object:
        account_reads.append((user_id, account_id))
        return _observation(account_id=account_id, owner_user_id=user_id)

    monkeypatch.setattr(
        "apps.data_center.application.data02_task_authority.revalidate_data02_task_authority",
        current_authority,
    )
    monkeypatch.setattr(
        _guard_module,
        "resolve_financial_e1_simulated_account_binding",
        current_account,
    )
    guard = _guard_module.DjangoFinancialE1ActorSimulatedAccountGuard(
        _authority(),
        simulated_account_id=631,
    )

    guard.assert_current()
    guard.assert_current()

    assert len(rechecks) == 2
    assert all(value.tzinfo is not None and value.utcoffset() == timedelta(0) for value in rechecks)
    assert account_reads == [(7, 631), (7, 631), (7, 631)]


@pytest.mark.parametrize(
    ("actor_id", "user_id", "account_id", "owner_user_id", "is_simulated", "is_active"),
    (
        ("other-actor", 7, 631, 7, True, True),
        ("django-user:7", 7, 631, 8, True, True),
        ("django-user:7", 7, 632, 7, True, True),
        ("django-user:7", 7, 631, 7, False, True),
        ("django-user:7", 7, 631, 7, True, False),
    ),
)
def test_guard_fails_closed_for_wrong_owner_namespace_type_or_state(
    monkeypatch: pytest.MonkeyPatch,
    actor_id: str,
    user_id: int,
    account_id: int,
    owner_user_id: int,
    is_simulated: bool,
    is_active: bool,
) -> None:
    """Numeric id equality cannot replace simulated type, active state, or owner."""

    monkeypatch.setattr(
        _guard_module,
        "resolve_financial_e1_simulated_account_binding",
        lambda **kwargs: _observation(
            account_id=account_id,
            owner_user_id=owner_user_id,
            is_simulated=is_simulated,
            is_active=is_active,
        ),
    )

    with pytest.raises((ValueError, _guard_module.DataValidationError)):
        _guard_module.DjangoFinancialE1ActorSimulatedAccountGuard(
            _authority(actor_id=actor_id, user_id=user_id),
            simulated_account_id=631,
        )


def test_guard_latches_a_revoked_data02_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed existing DATA02 revalidation blocks subsequent boundaries."""

    monkeypatch.setattr(
        "apps.data_center.application.data02_task_authority.revalidate_data02_task_authority",
        lambda *args, **kwargs: Data02AuthorityRevalidation(False, "authority_revoked", 1),
    )
    monkeypatch.setattr(
        _guard_module,
        "resolve_financial_e1_simulated_account_binding",
        lambda **kwargs: _observation(),
    )
    guard = _guard_module.DjangoFinancialE1ActorSimulatedAccountGuard(
        _authority(),
        simulated_account_id=631,
    )

    with pytest.raises(_guard_module.DataValidationError):
        guard.assert_current()
    with pytest.raises(_guard_module.DataValidationError):
        guard.assert_current()
