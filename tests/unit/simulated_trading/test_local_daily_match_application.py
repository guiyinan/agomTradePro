"""Application DTO contracts for durable local daily matching."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    LocalDailyMatchEvidenceKind,
    LocalDailyMatchSourceReference,
    QualifiedLocalDailyMatchInput,
    RecordLocalDailyMatchUseCase,
    local_daily_match_request_hash,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
    LocalDailySimulationPolicyRuntimeProvenance,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchLimitState,
    LocalMatchObservation,
    LocalMatchOutcome,
    LocalMatchPriceAdjustment,
    LocalMatchTradingState,
    LocalMatchVolumeUnit,
    LocalOrderMatchResult,
)

_AS_OF = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
_RECORDED_AT = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)


def _policy_binding() -> LocalDailySimulationPolicyBinding:
    """Build one valid explicitly bound policy for DTO boundary tests."""

    activated_at = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    policy = LocalDailySimulationPolicy(
        schema_version="local-daily-simulation-policy.v1",
        purpose="historical_daily_simulation",
        policy_id="fixture",
        version="1",
        price_publication_key="equity.daily.close",
        provider_configuration_id=1,
        provider_name="fixture",
        instrument_snapshot_id=str(uuid4()),
        currency="CNY",
        frequency="1d",
        adjustment="none",
        volume_unit="shares",
        participation_rate=Decimal("0.1"),
        share_step=Decimal("1"),
        allowed_qmt_suspend_flags=(0, -1),
        currency_basis="same_session_stock_basic_capture",
        qmt_status_basis="owner_authenticated_normalized_daily_status",
        limit_price_basis="same_provider_cny_listing_native",
    )
    provenance = LocalDailySimulationPolicyRuntimeProvenance(
        runtime_environment="test",
        profile_id="profile-1",
        profile_key="profile-key",
        profile_version=1,
        profile_content_hash="a" * 64,
        profile_activated_at=activated_at,
        snapshot_id="snapshot-1",
        snapshot_content_hash="b" * 64,
        snapshot_generated_at=datetime(2026, 10, 28, 1, 0, tzinfo=UTC),
        snapshot_effective_from=activated_at,
        read_at=_AS_OF,
    )
    return LocalDailySimulationPolicyBinding(policy=policy, provenance=provenance)


def _observation() -> LocalMatchObservation:
    """Build one exact session observation without asserting its source qualification."""

    session_date = date(2026, 10, 28)
    return LocalMatchObservation(
        security_id="security-1",
        session_date=session_date,
        observation_id=stable_local_daily_observation_id("security-1", session_date),
        observed_at=datetime(2026, 10, 28, 7, 0, tzinfo=UTC),
        available_at=_RECORDED_AT,
        close_price=Decimal("10.00"),
        price_adjustment=LocalMatchPriceAdjustment.UNADJUSTED,
        traded_volume=Decimal("1000"),
        volume_unit=LocalMatchVolumeUnit.CANONICAL_SHARES,
        trading_state=LocalMatchTradingState.TRADING,
        limit_state=LocalMatchLimitState.BOUNDED,
        lower_limit_price=Decimal("9.00"),
        upper_limit_price=Decimal("11.00"),
    )


def test_observation_id_binds_only_security_session_and_fixed_purpose() -> None:
    first = stable_local_daily_observation_id("security-1", date(2026, 10, 28))

    assert first == stable_local_daily_observation_id("security-1", date(2026, 10, 28))
    assert first != stable_local_daily_observation_id("security-2", date(2026, 10, 28))
    assert first != stable_local_daily_observation_id("security-1", date(2026, 10, 29))


@pytest.mark.parametrize("value", ["qmt-binding-1", "\x00" + str(uuid4())])
def test_command_rejects_noncanonical_or_control_character_qmt_binding(value: str) -> None:
    with pytest.raises(ValueError, match="QMT_BINDING"):
        LocalDailyMatchCommand(
            account_id=7,
            user_id=8,
            order_idempotency_key="order-1",
            operation_key="operation-1",
            session_date=date(2026, 10, 28),
            qmt_binding_id=value,
        )


def test_qualified_input_sorts_and_deduplicates_kind_scoped_references() -> None:
    fact = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_FACT,
        identity="1",
        content_hash="a" * 64,
        recorded_at=_RECORDED_AT,
    )
    audit = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_AUDIT,
        identity="1",
        content_hash="b" * 64,
        recorded_at=_RECORDED_AT,
    )

    qualified = QualifiedLocalDailyMatchInput(
        as_of=_AS_OF,
        policy_binding=_policy_binding(),
        observation=_observation(),
        evidence=(fact, audit, fact),
    )

    assert qualified.evidence == (audit, fact)


def test_qualified_input_rejects_hash_conflict_for_same_kind_identity() -> None:
    first = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_FACT,
        identity="fact-1",
        content_hash="a" * 64,
        recorded_at=_RECORDED_AT,
    )
    conflict = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_FACT,
        identity="fact-1",
        content_hash="b" * 64,
        recorded_at=_RECORDED_AT,
    )

    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        QualifiedLocalDailyMatchInput(
            as_of=_AS_OF,
            policy_binding=_policy_binding(),
            observation=_observation(),
            evidence=(first, conflict),
        )


def test_qualified_input_revalidates_references_after_construction() -> None:
    reference = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_FACT,
        identity="fact-1",
        content_hash="a" * 64,
        recorded_at=_RECORDED_AT,
    )
    object.__setattr__(reference, "content_hash", "invalid")

    with pytest.raises(ValueError, match="EVIDENCE_HASH_INVALID"):
        QualifiedLocalDailyMatchInput(
            as_of=_AS_OF,
            policy_binding=_policy_binding(),
            observation=_observation(),
            evidence=(reference,),
        )


def test_exact_operation_replay_returns_before_context_clock_or_source_reads() -> None:
    command = LocalDailyMatchCommand(
        account_id=7,
        user_id=8,
        order_idempotency_key="order-1",
        operation_key="operation-1",
        session_date=date(2026, 10, 28),
        qmt_binding_id=str(uuid4()),
    )
    persisted = LocalDailyMatchDecision(
        command=command,
        request_hash=local_daily_match_request_hash(command),
        result=LocalOrderMatchResult(
            outcome=LocalMatchOutcome.NO_MATCH,
            reason_code="LIMIT_NOT_CROSSED",
            matched_quantity=Decimal("0.000000"),
            matched_price=None,
        ),
        event=None,
        replayed=False,
    )

    class Repository:
        """Return the exact stored operation without resolving mutable inputs."""

        def find_operation(
            self,
            *,
            command: LocalDailyMatchCommand,
            request_hash: str,
        ) -> LocalDailyMatchDecision | None:
            assert command == persisted.command
            assert request_hash == persisted.request_hash
            return persisted

        def resolve_order_context(self, *, command: LocalDailyMatchCommand) -> None:
            del command
            raise AssertionError("exact operation replay must precede current order reads")

        def record_decision(self, **kwargs: object) -> LocalDailyMatchDecision:
            del kwargs
            raise AssertionError("exact operation replay must not write again")

    class Reader:
        """Fail if replay consults the current source qualification."""

        def read(self, **kwargs: object) -> QualifiedLocalDailyMatchInput | None:
            del kwargs
            raise AssertionError("exact operation replay must precede source reads")

    class Clock:
        """Fail if replay consults the current wall clock."""

        def now(self) -> datetime:
            raise AssertionError("exact operation replay must precede clock reads")

    result = RecordLocalDailyMatchUseCase(
        repository=Repository(),
        qualification_reader=Reader(),
        clock=Clock(),
    ).execute(command)

    assert result.replayed is True
    assert result.result == persisted.result
