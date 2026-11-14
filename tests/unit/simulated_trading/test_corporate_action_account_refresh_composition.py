"""Owner account refresh rejects unsafe callers before ledger access."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    CanonicalAccountCreationEvidenceSettings,
)
from apps.simulated_trading.application.current_account_ownership import CurrentAccountOwnership
from apps.simulated_trading.corporate_action_account_refresh_composition import (
    CorporateActionAccountRefreshResult,
    refresh_owner_simulated_account_evidence,
)
from apps.simulated_trading.domain.entities import AccountType
from core.exceptions import AuthorizationError, BusinessLogicError

_NOW = datetime(2026, 11, 13, 1, tzinfo=UTC)


def _settings() -> CanonicalAccountCreationEvidenceSettings:
    """Return one explicit, finite account-evidence recorder configuration."""

    return CanonicalAccountCreationEvidenceSettings(
        schema_version=ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        ttl_seconds=300,
        allocation_recorder_service_id="test-allocation",
        physical_v2_recorder_service_id="test-physical",
        allocated_v3_recorder_service_id="test-allocated",
        binding_recorder_service_id="test-binding",
    )


def _request(*, user_id: int | None, authenticated: bool = True) -> SimpleNamespace:
    """Build a narrow test request carrying the Session-authenticated user shape."""

    return SimpleNamespace(
        user=SimpleNamespace(is_authenticated=authenticated, pk=user_id),
    )


@contextmanager
def _atomic(**_: object) -> Iterator[None]:
    """Avoid opening a database for the branch-only composition checks."""

    yield


def test_refresh_rejects_unauthenticated_owner_before_runtime_or_database(monkeypatch):
    request = _request(user_id=None, authenticated=False)
    runtime_calls: list[str] = []

    def runtime_environment() -> str:
        runtime_calls.append("read")
        return "test"

    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.get_simulated_execution_runtime_environment",
        runtime_environment,
    )

    with pytest.raises(AuthorizationError):
        refresh_owner_simulated_account_evidence(request, account_id=5)

    assert runtime_calls == []


def test_refresh_requires_current_explicit_settings_before_database(monkeypatch):
    database_calls: list[str] = []
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.get_simulated_execution_runtime_environment",
        lambda: "test",
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.get_active_account_creation_evidence_settings",
        lambda environment: None,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.connections",
        {"default": database_calls},
    )

    with pytest.raises(BusinessLogicError, match="active account-evidence settings"):
        refresh_owner_simulated_account_evidence(_request(user_id=7), account_id=5)

    assert database_calls == []


@pytest.mark.parametrize(
    "row",
    [
        CurrentAccountOwnership(5, 7, AccountType.REAL, True, _NOW - timedelta(days=1), _NOW, _NOW),
        CurrentAccountOwnership(
            5, 8, AccountType.SIMULATED, True, _NOW - timedelta(days=1), _NOW, _NOW
        ),
        CurrentAccountOwnership(
            5, 7, AccountType.SIMULATED, False, _NOW - timedelta(days=1), _NOW, _NOW
        ),
    ],
    ids=["real-account", "foreign-owner", "inactive-account"],
)
def test_refresh_rejects_non_owned_or_non_simulated_row_before_reading_evidence(monkeypatch, row):
    @contextmanager
    def eligibility(**_: object) -> Iterator[None]:
        yield

    class Reader:
        def read_locked(self, *, row_pk: int) -> CurrentAccountOwnership:
            assert row_pk == 5
            return row

    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.get_simulated_execution_runtime_environment",
        lambda: "test",
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.get_active_account_creation_evidence_settings",
        lambda environment: _settings(),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.connections",
        {"default": SimpleNamespace(vendor="postgresql", in_atomic_block=True)},
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.transaction.atomic",
        _atomic,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.locked_simulated_action_trading_eligibility",
        eligibility,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.build_current_account_ownership_reader",
        lambda *, using: Reader(),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_account_refresh_composition.DjangoSimulatedAccountRowSourceV2Repository",
        lambda **_: pytest.fail("owner/source evidence must not be read for a rejected row"),
    )

    with pytest.raises(AuthorizationError):
        refresh_owner_simulated_account_evidence(_request(user_id=7), account_id=5)


def test_refresh_result_never_claims_financial_or_market_authority():
    result = CorporateActionAccountRefreshResult(
        account_id=5,
        row_updated_at=_NOW,
        source_observed_at=_NOW + timedelta(seconds=1),
        source_recorded_at=_NOW + timedelta(seconds=2),
        account_recorded_at=_NOW + timedelta(seconds=3),
        checked_at=_NOW + timedelta(seconds=4),
        valid_until=_NOW + timedelta(minutes=5),
    )
    assert result.freshness == "fresh"
    assert result.reliability == "owner_row_observed"
    assert result.must_not_use_for_decision is True
    assert result.blocking_reason == "account_ownership_evidence_only"

    with pytest.raises(ValueError, match="ownership evidence only"):
        CorporateActionAccountRefreshResult(
            account_id=5,
            row_updated_at=_NOW,
            source_observed_at=_NOW + timedelta(seconds=1),
            source_recorded_at=_NOW + timedelta(seconds=2),
            account_recorded_at=_NOW + timedelta(seconds=3),
            checked_at=_NOW + timedelta(seconds=4),
            valid_until=_NOW + timedelta(minutes=5),
            must_not_use_for_decision=False,
        )


@pytest.mark.parametrize("late_change", ["expiry", "backwards", "row"])
def test_refresh_finishes_only_after_role_exit_checks(monkeypatch, late_change):
    """Controlled ports expose a late boundary; they do not prove DB persistence."""
    from dataclasses import replace

    from apps.simulated_trading import corporate_action_account_refresh_composition as module
    from apps.simulated_trading.application.current_account_ownership import (
        CurrentAccountOwnershipUnavailable,
    )

    row = CurrentAccountOwnership(
        5,
        7,
        AccountType.SIMULATED,
        True,
        _NOW - timedelta(days=1),
        _NOW - timedelta(seconds=1),
        _NOW,
    )
    current_row = [row]
    current_time = [_NOW]
    source = SimpleNamespace(
        account_namespace="account",
        account_id="owner-account",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=5,
    )
    raw = SimpleNamespace(observation_id="raw-owner", observation_version="original")
    refreshed_raw = SimpleNamespace(
        valid_until=_NOW + timedelta(seconds=5), row_updated_at=row.row_updated_at, observed_at=_NOW
    )
    refreshed_source = SimpleNamespace(
        valid_until=refreshed_raw.valid_until,
        row_updated_at=row.row_updated_at,
        account_id=source.account_id,
        recorded_at=_NOW,
        is_current_at=lambda cutoff: True,
    )
    refreshed_account = SimpleNamespace(
        valid_until=refreshed_raw.valid_until,
        row_updated_at=row.row_updated_at,
        account_id=source.account_id,
        recorded_at=_NOW,
        is_current_at=lambda cutoff: True,
    )

    @contextmanager
    def eligibility(**kwargs):
        try:
            yield
        finally:
            if late_change == "expiry":
                current_time[0] = _NOW + timedelta(seconds=6)
            elif late_change == "backwards":
                current_time[0] = _NOW - timedelta(seconds=1)
            else:
                current_row[0] = replace(row, row_updated_at=_NOW)

    class Pipeline:
        def __init__(self, **kwargs):
            pass

        def record_update(self, mutation, reference):
            return SimpleNamespace(
                raw=refreshed_raw, source_v2=refreshed_source, account_v2=refreshed_account
            )

    monkeypatch.setattr(module, "get_simulated_execution_runtime_environment", lambda: "test")
    monkeypatch.setattr(
        module, "get_active_account_creation_evidence_settings", lambda environment: _settings()
    )
    monkeypatch.setattr(
        module,
        "connections",
        {"default": SimpleNamespace(vendor="postgresql", in_atomic_block=True)},
    )
    monkeypatch.setattr(module.transaction, "atomic", _atomic)
    monkeypatch.setattr(module.timezone, "now", lambda: current_time[0])
    monkeypatch.setattr(module, "locked_simulated_action_trading_eligibility", eligibility)
    monkeypatch.setattr(
        module,
        "build_current_account_ownership_reader",
        lambda **kwargs: SimpleNamespace(read_locked=lambda **kw: current_row[0]),
    )
    monkeypatch.setattr(
        module,
        "DjangoSimulatedAccountRowSourceV2Repository",
        lambda **kwargs: SimpleNamespace(
            lock_current_sources_for_read=lambda: None,
            get_physical_account_heads=lambda **kw: (SimpleNamespace(source=source),),
        ),
    )
    monkeypatch.setattr(
        module,
        "DjangoSimulatedAccountRawObservationRepository",
        lambda **kwargs: SimpleNamespace(
            get_physical_row_head=lambda **kw: SimpleNamespace(observation=raw)
        ),
    )
    monkeypatch.setattr(module, "_require_existing_source_chain", lambda **kwargs: None)
    monkeypatch.setattr(module, "build_existing_account_reobserver", lambda **kwargs: object())
    monkeypatch.setattr(
        module,
        "build_simulated_account_creation_stages",
        lambda **kwargs: SimpleNamespace(database_alias="default", source_capture=object()),
    )
    monkeypatch.setattr(
        module,
        "build_canonical_account_creation_stages",
        lambda **kwargs: SimpleNamespace(database_alias="default", physical_capture=object()),
    )
    monkeypatch.setattr(module, "build_account_physical_row_v2_provider", lambda **kwargs: object())
    monkeypatch.setattr(module, "SimulatedAccountEvidencePipeline", Pipeline)
    expected = CurrentAccountOwnershipUnavailable if late_change == "row" else BusinessLogicError
    with pytest.raises(expected):
        refresh_owner_simulated_account_evidence(_request(user_id=7), account_id=5)
