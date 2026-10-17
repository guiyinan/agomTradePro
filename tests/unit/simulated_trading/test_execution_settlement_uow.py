"""Unit contracts for the settlement-bound simulated-trade ledger entry."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.domain.exchange_calendar import ExchangeCalendarDay as SourceCalendarDay
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarRawReference as SourceRawCalendarReference,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ExecutionCalendarUnavailable,
    ExecutionInstrumentIdentityUnavailable,
    ReleaseDueSimulatedSettlementsUseCase,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain import execution_settlement_uow as domain
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    PendingSettlementScopeV1,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    CalendarEvidenceValidationError,
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    RawCalendarReference,
    SettlementExecutionPlan,
    SimulatedSettlementContractError,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    calculate_trade_fees,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _bundle(*, lag: int = 1) -> ExecutionSettlementBundleV3:
    """Build one explicit, isolated V3 rule fixture for Application tests."""

    base = AShareExecutionRule(
        rule_id="uow-rule",
        rule_version="1",
        security_id="SH.UOW.SECURITY",
        market="SH",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=Decimal("100000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=Decimal("100000")
        ),
        sell_odd_lot_mode=SellOddLotMode.SELL_ODD_REMAINDER_ONCE,
        price_tick=Decimal("0.01"),
        rule_source_id="operator-rule-source",
        rule_source_version="2026-10",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=AS_OF - timedelta(minutes=30),
        valid_until=AS_OF + timedelta(days=30),
    )
    v2 = ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="MAIN",
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )
    policy = SettlementPolicyV1(
        policy_id="uow-settlement-policy",
        policy_version="1",
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=lag,
        bound_execution_rule_v2_hash=v2.content_hash,
        source_id="operator-settlement-source",
        source_version="2026-10",
        source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=base.effective_from,
        valid_until=base.valid_until,
    )
    return ExecutionSettlementBundleV3(
        bundle_id="uow-bundle",
        bundle_version="1",
        execution_submission_v2=v2,
        settlement_policy_v1=policy,
    )


def _calendar(
    *,
    as_of: datetime = AS_OF,
    days: tuple[ExchangeCalendarDay, ...] | None = None,
    exchange: str = "SH",
    published: bool = True,
    recorded_at: datetime | None = None,
) -> ExecutionCalendarEvidence:
    """Create a fully explicit test reference; no weekday inference is used."""

    response_completed_at = as_of - timedelta(minutes=20)
    day_rows = days or (
        ExchangeCalendarDay(exchange, date(2026, 10, 16), True, date(2026, 10, 15)),
        ExchangeCalendarDay(exchange, date(2026, 10, 17), False, date(2026, 10, 16)),
        ExchangeCalendarDay(exchange, date(2026, 10, 18), False, date(2026, 10, 16)),
        ExchangeCalendarDay(exchange, date(2026, 10, 19), True, date(2026, 10, 16)),
    )
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            exchange, day_rows[0].calendar_date, day_rows[-1].calendar_date
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange=exchange,
        coverage_start=day_rows[0].calendar_date,
        coverage_end=day_rows[-1].calendar_date,
        days=day_rows,
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=recorded_at or as_of - timedelta(minutes=10),
        source_published_at=None,
    )
    publication = (
        CalendarPublicationReference(
            publication_id="calendar-publication-202610",
            member_id=snapshot.snapshot_id,
            publication_hash="2" * 64,
            # Synthetic fact-row digest is independent of normalized snapshot content_hash.
            fact_content_hash="4" * 64,
            policy_hash="3" * 64,
            published_at=as_of - timedelta(minutes=5),
            recorded_at=as_of - timedelta(minutes=4),
            reference_valid_from=as_of - timedelta(days=1),
            reference_valid_until=as_of + timedelta(days=1),
            timezone_name="Asia/Shanghai",
        )
        if published
        else None
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _qualified_identity_evidence(
    **changes: object,
) -> ExecutionInstrumentIdentityEvidenceV1:
    """Create explicitly synthetic, source-clock-qualified identity evidence."""

    evidence = ExecutionInstrumentIdentityEvidenceV1(
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
        source_code="600000.SH",
        source_exchange="SSE",
        source_market="MAIN_BOARD",
        rule_market="SH",
        board="MAIN",
        snapshot_id=UUID("f418fc8b-8843-4cd8-9693-95b67834827b"),
        snapshot_content_hash="sha256:" + "a" * 64,
        snapshot_record_digest="sha256:" + "b" * 64,
        first_seen_at=AS_OF - timedelta(minutes=20),
        snapshot_recorded_at=AS_OF - timedelta(minutes=10),
        mapping_record_id=UUID("f618fc8b-8843-4cd8-9693-95b67834827b"),
        mapping_id="synthetic-mapping",
        mapping_version="test-v1",
        mapping_content_hash="sha256:" + "c" * 64,
        mapping_record_digest="sha256:" + "d" * 64,
        mapping_recorded_at=AS_OF - timedelta(minutes=30),
        response_completed_at=AS_OF - timedelta(minutes=20),
        source_observed_at=AS_OF - timedelta(hours=1),
        source_available_at=AS_OF - timedelta(minutes=30),
        identity_valid_from=AS_OF - timedelta(days=1),
        identity_valid_until=AS_OF + timedelta(days=1),
        must_not_use_for_decision=False,
        must_not_execute=False,
    )
    return replace(evidence, **changes)


def _intent(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    key: str = "intent-001",
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("10.00"),
) -> SimulatedTradeIntent:
    """Build one exact simulated trade intent."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key=key,
        side=side,
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
        asset_name="test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        price=price,
        reason="test order",
        signal_id=None,
    )


def test_calendar_uses_explicit_complete_open_sessions_for_release_date() -> None:
    evidence = _calendar()
    evidence.validate_for(AS_OF)

    current_session = evidence.current_open_session(AS_OF)
    release_session = evidence.release_session(current_session, lag_sessions=1)

    assert current_session == date(2026, 10, 16)
    assert release_session == date(2026, 10, 19)


def test_calendar_rejects_a_gap_inside_claimed_complete_coverage() -> None:
    incomplete_days = (
        ExchangeCalendarDay("SH", date(2026, 10, 16), True, date(2026, 10, 15)),
        ExchangeCalendarDay("SH", date(2026, 10, 18), False, date(2026, 10, 16)),
        ExchangeCalendarDay("SH", date(2026, 10, 19), True, date(2026, 10, 16)),
    )

    with pytest.raises(CalendarEvidenceValidationError):
        _calendar(days=incomplete_days)


def test_calendar_without_formal_publication_binding_is_not_executable() -> None:
    evidence = _calendar(published=False)

    with pytest.raises(CalendarEvidenceValidationError):
        evidence.validate_for(AS_OF)


def test_calendar_publication_binds_fact_row_hash_separately_from_snapshot_hash() -> None:
    evidence = _calendar()

    assert evidence.publication is not None
    assert evidence.publication.fact_content_hash == "4" * 64
    assert evidence.publication.fact_content_hash != evidence.snapshot.content_hash
    changed_publication = replace(evidence.publication, fact_content_hash="5" * 64)
    changed_evidence = replace(evidence, publication=changed_publication)
    assert evidence.evidence_hash != changed_evidence.evidence_hash

    with pytest.raises(CalendarEvidenceValidationError):
        replace(evidence.publication, fact_content_hash="sha256:" + "4" * 64)


def test_calendar_rejects_snapshot_recorded_after_the_knowledge_cutoff() -> None:
    evidence = _calendar(recorded_at=AS_OF + timedelta(seconds=1))

    with pytest.raises(CalendarEvidenceValidationError):
        evidence.validate_for(AS_OF)


def test_calendar_allows_absent_upstream_source_timestamps_without_faking_them() -> None:
    evidence = _calendar()

    evidence.validate_for(AS_OF)

    assert evidence.snapshot.source_published_at is None
    assert evidence.snapshot.first_seen_at == evidence.snapshot.raw_reference.response_completed_at


def test_calendar_adapter_hashes_match_the_data_center_snapshot_contract() -> None:
    coverage_start = date(2026, 10, 16)
    coverage_end = date(2026, 10, 19)
    response_completed_at = AS_OF - timedelta(minutes=20)
    source_raw = SourceRawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SH", coverage_start, coverage_end
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    source_days = (
        SourceCalendarDay("SH", coverage_start, True, date(2026, 10, 15)),
        SourceCalendarDay("SH", date(2026, 10, 17), False, coverage_start),
        SourceCalendarDay("SH", date(2026, 10, 18), False, coverage_start),
        SourceCalendarDay("SH", coverage_end, True, coverage_start),
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SH",
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=source_days,
        provider_name="fixture-provider",
        raw_reference=source_raw,
        first_seen_at=response_completed_at,
    )
    source_snapshot = make_exchange_calendar_snapshot(
        candidate,
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        recorded_at=AS_OF - timedelta(minutes=10),
    )
    simulated_evidence = _calendar()

    assert simulated_evidence.snapshot.content_hash == source_snapshot.content_hash
    assert simulated_evidence.snapshot.record_digest == source_snapshot.record_digest


def test_simulated_trade_intent_hash_is_exact_and_changes_with_intent() -> None:
    first = _intent()
    retry = _intent()
    alternate_decimal_scale = _intent(
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
    )
    changed = _intent(price=Decimal("10.01"))

    assert first.request_payload_hash == retry.request_payload_hash
    assert first.request_payload_hash == alternate_decimal_scale.request_payload_hash
    assert first.request_payload_hash != changed.request_payload_hash


def test_current_calendar_revision_uses_the_original_lag_not_a_new_policy() -> None:
    original = _calendar(
        days=(
            ExchangeCalendarDay("SH", date(2026, 10, 16), True, date(2026, 10, 15)),
            ExchangeCalendarDay("SH", date(2026, 10, 17), False, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 18), False, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 19), True, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 20), True, date(2026, 10, 19)),
            ExchangeCalendarDay("SH", date(2026, 10, 21), True, date(2026, 10, 20)),
        )
    )
    revised_as_of = AS_OF + timedelta(days=4)
    revised = _calendar(
        as_of=revised_as_of,
        days=(
            ExchangeCalendarDay("SH", date(2026, 10, 16), True, date(2026, 10, 15)),
            ExchangeCalendarDay("SH", date(2026, 10, 17), False, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 18), False, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 19), False, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 20), True, date(2026, 10, 16)),
            ExchangeCalendarDay("SH", date(2026, 10, 21), True, date(2026, 10, 20)),
        ),
    )

    original_release_date = original.release_session(date(2026, 10, 16), 2)
    current_session = revised.current_open_session(revised_as_of)
    settled_sessions = revised.elapsed_open_sessions(date(2026, 10, 16), current_session)

    assert original_release_date == date(2026, 10, 20)
    assert _bundle(lag=1).settlement_policy_v1.settlement_lag_sessions == 1
    assert revised.release_session(date(2026, 10, 16), 2) == date(2026, 10, 21)
    assert revised.release_session(date(2026, 10, 16), 1) == date(2026, 10, 20)
    assert settled_sessions == 1


def _fee_schedule(
    *,
    min_commission: Decimal = Decimal("5"),
    slippage_rate: Decimal = Decimal("0.001"),
) -> ExecutionFeeSchedule:
    """Build a fee snapshot with every source and calculation choice explicit."""

    return ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        min_commission=min_commission,
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=slippage_rate,
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )


def test_fee_snapshot_hash_captures_binary64_source_and_calculation_semantics() -> None:
    exact_stored_float = Decimal.from_float(0.1)
    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=exact_stored_float,
        commission_rate_sell=Decimal("0.0003"),
        min_commission=Decimal("5"),
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )

    assert schedule.to_payload()["commission_rate_buy"] == str(exact_stored_float)
    assert schedule.to_payload()["precision_basis"] == "database_binary64"
    assert schedule.to_payload()["calculation_purpose"] == "normal_sim_estimated"
    assert len(schedule.content_hash) == 64


def test_fee_rounding_sums_component_cents_and_exposes_aggregate_difference() -> None:
    schedule = _fee_schedule(min_commission=Decimal("0.005"), slippage_rate=Decimal("0.005"))
    result = calculate_trade_fees(
        schedule,
        side=SimulatedTradeSide.BUY,
        amount=Decimal("1.00"),
        market="SZ",
    )

    assert result.commission == Decimal("0.00")
    assert result.slippage == Decimal("0.00")
    assert result.total_fee == Decimal("0.00")
    assert (Decimal("0.005") + Decimal("0.005")).quantize(Decimal("0.01")) == Decimal("0.01")


@pytest.mark.parametrize("quantity", [100.0, Decimal("NaN"), Decimal("Infinity"), Decimal("0")])
def test_simulated_trade_intent_rejects_inexact_or_nonpositive_quantity(
    quantity: object,
) -> None:
    with pytest.raises(ValueError):
        _intent(quantity=quantity)  # type: ignore[arg-type]


class _FixedClock:
    def now(self) -> datetime:
        return AS_OF


class _RuleReader:
    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        assert security_id == "SH.UOW.SECURITY"
        assert as_of == AS_OF
        return _bundle()


class _CalendarReader:
    def __init__(
        self,
        evidence: ExecutionCalendarEvidence | None,
        *,
        expected_exchange: str = "SH",
    ) -> None:
        self.evidence = evidence
        self.expected_exchange = expected_exchange
        self.calls: list[str] = []
        self.coverage_starts: list[date | None] = []

    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: date | None
    ) -> ExecutionCalendarEvidence | None:
        self.calls.append(exchange)
        self.coverage_starts.append(coverage_start)
        assert exchange == self.expected_exchange
        assert as_of == AS_OF
        return self.evidence


class _IdentityReader:
    def __init__(
        self,
        evidence: ExecutionInstrumentIdentityEvidenceV1 | None,
    ) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str, datetime]] = []

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1 | None:
        self.calls.append((security_id, asset_code, as_of))
        return self.evidence


class _FeeReader:
    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> SimulatedFeePolicyV2:
        assert account_id > 0
        assert user_id > 0
        assert asset_type == "equity"
        assert market == "SH"
        assert board == "MAIN"
        assert as_of == AS_OF
        return _fee_policy()


def _fee_policy() -> SimulatedFeePolicyV2:
    """Build an explicit V2 fee policy for both exact sides in UoW unit tests."""

    start = AS_OF - timedelta(days=1)
    applies = FeeApplicability.APPLIES
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=applies,
            transfer_fee=applies,
            stamp_duty=applies,
            slippage=applies,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=_fee_schedule(),
        policy_id="unit-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=start,
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=start,
        transaction_cases=cases,
    )


class _RecordingRepository:
    def __init__(
        self,
        *,
        pending_scope: PendingSettlementScopeV1 | None = None,
        previous: SimulatedTradeExecutionReceipt | None = None,
        result: object | None = None,
    ) -> None:
        self.plans: list[object] = []
        self.pending_scope = pending_scope
        self.previous = previous
        self.result = result
        self.pending_scope_reads = 0
        self.release_calls: list[ExecutionCalendarEvidence] = []

    def find_idempotent_result(
        self, *, account_id: int, user_id: int, idempotency_key: str
    ) -> SimulatedTradeExecutionReceipt | None:
        return self.previous

    def get_pending_settlement_start(
        self, *, account_id: int, user_id: int, asset_code: str
    ) -> None:
        return None

    def get_pending_settlement_scope(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> PendingSettlementScopeV1 | None:
        self.pending_scope_reads += 1
        return self.pending_scope

    def execute_trade(self, *, plan: object, clock: object) -> object:
        self.plans.append(plan)
        return self.result if self.result is not None else plan

    def release_due_settlements(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
        calendar_evidence: ExecutionCalendarEvidence,
        clock: object,
    ) -> int:
        self.release_calls.append(calendar_evidence)
        return 1


def test_application_blocks_missing_calendar_before_repository_mutation() -> None:
    repository = _RecordingRepository()
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(_qualified_identity_evidence()),
        calendar_reader=_CalendarReader(None, expected_exchange="SSE"),
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(ExecutionCalendarUnavailable):
        use_case.execute(_intent())

    assert repository.plans == []


def test_application_rejects_calendar_scope_mismatch_before_repository_mutation() -> None:
    repository = _RecordingRepository()
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(_qualified_identity_evidence()),
        calendar_reader=_CalendarReader(_calendar(exchange="SZ"), expected_exchange="SSE"),
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(_intent())

    assert repository.plans == []


def test_execute_uses_source_exchange_without_replacing_rule_or_fee_market() -> None:
    intent = _intent()
    expected_receipt = _receipt(request_payload_hash=intent.request_payload_hash)
    repository = _RecordingRepository(result=expected_receipt)
    identity_reader = _IdentityReader(_qualified_identity_evidence())
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    receipt = use_case.execute(intent)

    assert receipt == expected_receipt
    assert identity_reader.calls == [("SH.UOW.SECURITY", "600000.SH", AS_OF)]
    assert calendar_reader.calls == ["SSE"]
    assert len(repository.plans) == 1
    plan = repository.plans[0]
    assert type(plan) is SettlementExecutionPlanV2
    assert plan.intent.market == "SH"
    assert plan.calendar_evidence.snapshot.exchange == "SSE"
    assert plan.identity_evidence.source_exchange == "SSE"


def test_execute_blocks_pending_scope_from_another_source_exchange() -> None:
    repository = _RecordingRepository(
        pending_scope=PendingSettlementScopeV1(
            earliest_session=date(2026, 10, 16),
            source_exchange="SZSE",
        )
    )
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(_qualified_identity_evidence()),
        calendar_reader=calendar_reader,
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(_intent())

    assert repository.pending_scope_reads == 1
    assert calendar_reader.calls == []
    assert repository.plans == []


def _assert_identity_blocks_before_calendar_or_ledger(
    evidence: ExecutionInstrumentIdentityEvidenceV1,
) -> None:
    repository = _RecordingRepository()
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(evidence),
        calendar_reader=calendar_reader,
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(_intent())

    assert calendar_reader.calls == []
    assert repository.plans == []


def test_execute_blocks_identity_with_unknown_source_clocks_before_calendar_or_ledger() -> None:
    _assert_identity_blocks_before_calendar_or_ledger(
        _qualified_identity_evidence(source_observed_at=None, source_available_at=None)
    )


def test_execute_blocks_identity_with_forbidden_reference_flags_before_calendar_or_ledger() -> None:
    _assert_identity_blocks_before_calendar_or_ledger(
        _qualified_identity_evidence(must_not_use_for_decision=True)
    )
    _assert_identity_blocks_before_calendar_or_ledger(
        _qualified_identity_evidence(must_not_execute=True)
    )


def test_execute_blocks_identity_known_after_cutoff_before_calendar_or_ledger() -> None:
    _assert_identity_blocks_before_calendar_or_ledger(
        _qualified_identity_evidence(snapshot_recorded_at=AS_OF + timedelta(seconds=1))
    )


def test_execute_blocks_identity_at_half_open_expiry_before_calendar_or_ledger() -> None:
    _assert_identity_blocks_before_calendar_or_ledger(
        _qualified_identity_evidence(identity_valid_until=AS_OF)
    )


def test_execute_blocks_identity_security_market_or_board_mismatch_before_calendar_or_ledger() -> (
    None
):
    for change in (
        {"security_id": "OTHER.SECURITY"},
        {"asset_code": "000001.SZ"},
        {"rule_market": "SZ"},
        {"board": "STAR"},
        {"source_market": None},
    ):
        _assert_identity_blocks_before_calendar_or_ledger(_qualified_identity_evidence(**change))


def test_execute_blocks_missing_identity_before_calendar_or_ledger() -> None:
    repository = _RecordingRepository()
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(None),
        calendar_reader=calendar_reader,
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(ExecutionInstrumentIdentityUnavailable):
        use_case.execute(_intent())

    assert calendar_reader.calls == []
    assert repository.plans == []


def test_release_uses_stored_pending_source_exchange_and_original_start() -> None:
    original_start = date(2026, 10, 16)
    repository = _RecordingRepository(
        pending_scope=PendingSettlementScopeV1(
            earliest_session=original_start,
            source_exchange="SSE",
        )
    )
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"), expected_exchange="SSE")
    use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=calendar_reader,
        repository=repository,
        clock=_FixedClock(),
    )

    released = use_case.execute(
        account_id=7,
        user_id=11,
        asset_code="600000.SH",
        exchange="SSE",
    )

    assert released == 1
    assert calendar_reader.calls == ["SSE"]
    assert calendar_reader.coverage_starts == [original_start]
    assert len(repository.release_calls) == 1
    assert repository.release_calls[0].snapshot.exchange == "SSE"


def test_release_exchange_argument_is_only_an_exact_pending_scope_assertion() -> None:
    repository = _RecordingRepository(
        pending_scope=PendingSettlementScopeV1(
            earliest_session=date(2026, 10, 16),
            source_exchange="SSE",
        )
    )
    calendar_reader = _CalendarReader(None)
    use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=calendar_reader,
        repository=repository,
        clock=_FixedClock(),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(
            account_id=7,
            user_id=11,
            asset_code="600000.SH",
            exchange="SH",
        )

    assert calendar_reader.calls == []
    assert repository.release_calls == []


def test_release_without_pending_scope_does_not_read_calendar() -> None:
    repository = _RecordingRepository()
    calendar_reader = _CalendarReader(None)
    use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=calendar_reader,
        repository=repository,
        clock=_FixedClock(),
    )

    released = use_case.execute(
        account_id=7,
        user_id=11,
        asset_code="600000.SH",
        exchange="SH",
    )

    assert released == 0
    assert calendar_reader.calls == []
    assert repository.release_calls == []


def test_exact_idempotency_replay_does_not_read_identity_again() -> None:
    class _UnexpectedIdentityReader:
        def get_execution_instrument_identity(
            self,
            *,
            security_id: str,
            asset_code: str,
            as_of: datetime,
        ) -> ExecutionInstrumentIdentityEvidenceV1 | None:
            raise AssertionError("exact idempotency replay must not reread identity evidence")

    intent = _intent()
    original = _receipt(request_payload_hash=intent.request_payload_hash)
    repository = _RecordingRepository(previous=original)
    calendar_reader = _CalendarReader(None)
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_UnexpectedIdentityReader(),
        calendar_reader=calendar_reader,
        fee_policy_reader=_FeeReader(),
        repository=repository,
        clock=_FixedClock(),
    )

    replay = use_case.execute(intent)

    assert replay.replayed is True
    assert replay.trade_id == original.trade_id
    assert calendar_reader.calls == []
    assert repository.plans == []


class _BrokenTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        raise ValueError("invalid test timezone")

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "broken"


def test_domain_canonical_helpers_reject_unbounded_and_malformed_values() -> None:
    with pytest.raises(SimulatedSettlementContractError):
        domain._require_token("bad token", "token")
    with pytest.raises(SimulatedSettlementContractError):
        domain._require_hash("sha256:" + "a" * 64, "hash")
    with pytest.raises(CalendarEvidenceValidationError):
        domain._require_calendar_hash("a" * 64, "calendar_hash")
    with pytest.raises(CalendarEvidenceValidationError):
        domain._require_calendar_fact_hash("sha256:" + "a" * 64, "fact_hash")
    with pytest.raises(SimulatedSettlementContractError):
        domain._require_aware(datetime(2026, 1, 1), "as_of")
    with pytest.raises(SimulatedSettlementContractError):
        domain._require_aware(datetime(2026, 1, 1, tzinfo=_BrokenTimezone()), "as_of")
    with pytest.raises(CalendarEvidenceValidationError):
        domain._require_utc(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))), "time")
    with pytest.raises(SimulatedSettlementContractError):
        domain._hash_payload({"bad": object()})
    with pytest.raises(CalendarEvidenceValidationError):
        domain._hash_calendar_payload({"bad": float("nan")})
    with pytest.raises(SimulatedSettlementContractError):
        domain._seal_hash({}, object(), "hash")
    with pytest.raises(SimulatedSettlementContractError):
        domain._seal_hash({}, "a" * 64, "hash")


def test_domain_decimal_helpers_enforce_exact_column_and_wire_limits() -> None:
    for validator, value in (
        (validate_ledger_money, Decimal("-0.01")),
        (validate_ledger_money, Decimal("0.001")),
        (validate_ledger_money, Decimal("10000000000000")),
        (validate_ledger_quantity, Decimal("0.0000001")),
        (validate_ledger_price, Decimal("1.00001")),
        (validate_ledger_price, Decimal("1000000")),
    ):
        with pytest.raises(ValueError):
            validator(value, "value")
    with pytest.raises(ValueError):
        validate_ledger_money(Decimal("0"), "money", allow_zero=False)
    with pytest.raises(ValueError):
        domain._decimal_text(Decimal("NaN"))
    with pytest.raises(ValueError):
        domain._decimal_text(Decimal("1" + "0" * 128))
    with pytest.raises(ValueError):
        domain._decimal_numeric_text(Decimal("1e65"))
    with pytest.raises(ValueError):
        domain._decimal_numeric_text(Decimal("1" + "0" * 64))
    for wire in ("", "01", "NaN", "1e999", "1" * 258):
        with pytest.raises(ValueError):
            domain._decimal_from_text(wire, "amount")


def test_exact_decimal_storage_rejects_float_precision_and_database_bounds() -> None:
    for value in (
        0.1,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e65"),
        Decimal("1.0000001"),
        Decimal("-1"),
    ):
        with pytest.raises(ValueError):
            domain._require_decimal_storage(
                value,
                "quantity",
                quantum=Decimal("0.000001"),
                exclusive_maximum=Decimal("100000000000000"),
            )
    with pytest.raises(ValueError):
        domain._require_decimal_storage(
            Decimal("9" * 64 + "e64"),
            "money",
            quantum=Decimal("0.01"),
            exclusive_maximum=Decimal("1e100"),
        )


def test_utc_text_rejects_unrepresentable_boundary_and_hash_helpers_accept_valid_values() -> None:
    assert domain._utc_text(AS_OF) == "2026-10-16T02:00:00Z"
    assert len(domain._hash_payload({"stable": "value"})) == 64
    assert domain._seal_hash({"stable": "value"}, "", "hash") == domain._hash_payload(
        {"stable": "value"}
    )
    with pytest.raises(ValueError):
        domain._utc_text(datetime.min.replace(tzinfo=timezone(timedelta(hours=1))))


def test_raw_calendar_reference_rejects_bad_identity_hashes_and_unverified_retention() -> None:
    raw = _calendar().snapshot.raw_reference
    invalid_changes: tuple[dict[str, object], ...] = (
        {"payload_id": "not-a-uuid"},
        {"payload_hash": "a" * 64},
        {"record_digest": "a" * 64},
        {"body_sha256": "bad"},
        {"retained_content_sha256": "f" * 64},
        {"original_body_retained": False},
        {"response_completed_at": datetime(2026, 10, 16, 2)},
        {"provider_name": "bad provider"},
        {"transport": "vendor"},
    )

    for change in invalid_changes:
        with pytest.raises(ValueError):
            replace(raw, **change)

    assert raw.to_payload()["response_time_semantics"] == "local_response_body_completion"


def test_calendar_day_requires_explicit_date_open_flag_and_prior_open_date() -> None:
    day = ExchangeCalendarDay("SH", date(2026, 10, 16), True, date(2026, 10, 15))
    for changes in (
        {"exchange": "SH "},
        {"calendar_date": datetime(2026, 10, 16)},
        {"is_open": 1},
        {"previous_open_date": datetime(2026, 10, 15)},
        {"previous_open_date": date(2026, 10, 16)},
    ):
        with pytest.raises(ValueError):
            replace(day, **changes)

    assert day.to_payload() == {
        "exchange": "SH",
        "calendar_date": "2026-10-16",
        "is_open": True,
        "previous_open_date": "2026-10-15",
    }


def test_calendar_snapshot_revalidates_identity_coverage_source_and_both_hashes() -> None:
    snapshot = _calendar().snapshot
    invalid_changes: tuple[dict[str, object], ...] = (
        {"snapshot_id": "not-a-uuid"},
        {"exchange": ""},
        {"coverage_start": datetime(2026, 10, 16)},
        {"coverage_start": date(2026, 10, 20)},
        {"coverage_end": date(2026, 10, 18)},
        {"days": ()},
        {"days": (object(),)},
        {"raw_reference": object()},
        {"first_seen_at": datetime(2026, 10, 16, 2)},
        {"source_published_at": datetime(2026, 10, 16, 2)},
        {"first_seen_at": snapshot.first_seen_at + timedelta(seconds=1)},
        {"provider_name": "different-provider"},
        {"recorded_at": snapshot.first_seen_at - timedelta(seconds=1)},
        {"coverage_start": date(2026, 10, 17)},
        {"coverage_end": date(2026, 10, 20)},
        {"days": snapshot.days[:-1]},
        {
            "days": (
                snapshot.days[0],
                replace(snapshot.days[1], exchange="SZ"),
                *snapshot.days[2:],
            )
        },
        {
            "days": (
                snapshot.days[0],
                replace(snapshot.days[1], previous_open_date=date(2026, 10, 15)),
                *snapshot.days[2:],
            )
        },
        {"content_hash": "sha256:" + "f" * 64},
        {"record_digest": "sha256:" + "f" * 64},
    )

    for change in invalid_changes:
        with pytest.raises(ValueError):
            replace(snapshot, **change)

    payload = snapshot.to_payload()
    assert payload["content_hash"] == snapshot.content_hash
    assert payload["record_digest"] == snapshot.record_digest
    assert payload["raw_reference"] == snapshot.raw_reference.to_payload()


def test_calendar_publication_rejects_bad_digest_clock_window_and_timezone() -> None:
    publication = _calendar().publication
    assert publication is not None
    for changes in (
        {"publication_id": ""},
        {"member_id": "bad member"},
        {"publication_hash": "sha256:" + "2" * 64},
        {"fact_content_hash": "sha256:" + "4" * 64},
        {"policy_hash": "sha256:" + "3" * 64},
        {"published_at": datetime(2026, 10, 16, 2)},
        {"recorded_at": publication.published_at - timedelta(seconds=1)},
        {"reference_valid_from": publication.reference_valid_until},
        {"timezone_name": "Unknown/Zone"},
    ):
        with pytest.raises(ValueError):
            replace(publication, **changes)

    assert publication.to_payload()["fact_content_hash"] == "4" * 64


def test_calendar_evidence_rejects_wrong_types_damage_and_nonmatching_member_ids() -> None:
    evidence = _calendar()
    assert evidence.publication is not None
    with pytest.raises(CalendarEvidenceValidationError):
        ExecutionCalendarEvidence(snapshot=object(), publication=None)  # type: ignore[arg-type]
    with pytest.raises(CalendarEvidenceValidationError):
        replace(evidence, publication=object())  # type: ignore[arg-type]
    with pytest.raises(CalendarEvidenceValidationError):
        replace(
            evidence,
            publication=replace(evidence.publication, member_id="different-snapshot"),
        )

    damaged_snapshot = _calendar().snapshot
    object.__setattr__(damaged_snapshot, "exchange", None)
    with pytest.raises(CalendarEvidenceValidationError):
        ExecutionCalendarEvidence(snapshot=damaged_snapshot, publication=None)

    damaged_publication = replace(evidence.publication)
    object.__setattr__(damaged_publication, "published_at", "not-a-datetime")
    with pytest.raises(CalendarEvidenceValidationError):
        replace(evidence, publication=damaged_publication)


def test_calendar_cutoffs_block_future_source_publication_and_expired_binding() -> None:
    evidence = _calendar()
    assert evidence.publication is not None
    future_source_snapshot = replace(
        evidence.snapshot,
        source_published_at=AS_OF + timedelta(seconds=1),
        content_hash="",
        record_digest="",
    )
    future_source = ExecutionCalendarEvidence(
        snapshot=future_source_snapshot,
        publication=evidence.publication,
    )
    with pytest.raises(CalendarEvidenceValidationError):
        future_source.validate_for(AS_OF)

    future_publication = replace(
        evidence.publication,
        published_at=AS_OF + timedelta(seconds=1),
        recorded_at=AS_OF + timedelta(seconds=2),
    )
    with pytest.raises(CalendarEvidenceValidationError):
        replace(evidence, publication=future_publication).validate_for(AS_OF)

    with pytest.raises(CalendarEvidenceValidationError):
        evidence.validate_for(evidence.publication.reference_valid_until)
    with pytest.raises(SimulatedSettlementContractError):
        evidence.validate_for(datetime(AS_OF.year, AS_OF.month, AS_OF.day, AS_OF.hour))


def test_calendar_session_and_interval_methods_fail_closed_on_gaps_and_closed_dates() -> None:
    evidence = _calendar()
    assert evidence.publication is not None
    expanded_publication = replace(
        evidence.publication,
        reference_valid_until=AS_OF + timedelta(days=5),
    )
    expanded_evidence = replace(evidence, publication=expanded_publication)
    with pytest.raises(CalendarEvidenceValidationError):
        expanded_evidence.current_open_session(datetime(2026, 10, 18, 2, tzinfo=UTC))
    with pytest.raises(CalendarEvidenceValidationError):
        expanded_evidence.current_open_session(datetime(2026, 10, 20, 2, tzinfo=UTC))

    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(datetime(2026, 10, 16), 1)
    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(date(2026, 10, 16), True)
    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(date(2026, 10, 16), -1)
    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(date(2026, 10, 17), 1)
    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(date(2026, 10, 20), 1)
    assert evidence.release_session(date(2026, 10, 16), 0) == date(2026, 10, 16)
    with pytest.raises(CalendarEvidenceValidationError):
        evidence.release_session(date(2026, 10, 19), 2)

    for trade_session, through_session in (
        (datetime(2026, 10, 16), date(2026, 10, 19)),
        (date(2026, 10, 19), date(2026, 10, 16)),
        (date(2026, 10, 15), date(2026, 10, 16)),
        (date(2026, 10, 16), date(2026, 10, 20)),
        (date(2026, 10, 17), date(2026, 10, 19)),
        (date(2026, 10, 16), date(2026, 10, 17)),
    ):
        with pytest.raises(CalendarEvidenceValidationError):
            evidence.elapsed_open_sessions(trade_session, through_session)  # type: ignore[arg-type]


def _plan(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("10.00"),
) -> SettlementExecutionPlan:
    """Build one valid exact plan for public plan-boundary tests."""

    intent = _intent(side=side, quantity=quantity, price=price)
    bundle = _bundle()
    lag = bundle.settlement_policy_v1.settlement_lag_sessions
    calendar = _calendar()
    return SettlementExecutionPlan(
        intent=intent,
        market_session=date(2026, 10, 16),
        pre_read_at=AS_OF,
        settlement_lag_sessions=lag,
        settlement_release_date=(
            calendar.release_session(date(2026, 10, 16), lag)
            if side is SimulatedTradeSide.BUY
            else None
        ),
        settlement_bundle_id=bundle.bundle_id,
        settlement_bundle_version=bundle.bundle_version,
        settlement_bundle_hash=bundle.content_hash,
        settlement_policy_id=bundle.settlement_policy_v1.policy_id,
        settlement_policy_version=bundle.settlement_policy_v1.policy_version,
        settlement_policy_hash=bundle.settlement_policy_v1.content_hash,
        execution_rule_v2_hash=bundle.execution_submission_v2.content_hash,
        bundle_source_observed_at=bundle.latest_source_observed_at,
        bundle_source_available_at=bundle.source_available_at,
        bundle_effective_from=bundle.effective_from,
        bundle_valid_until=bundle.valid_until,
        calendar_evidence=calendar,
        fee_policy_v2=_fee_policy(),
    )


def test_settlement_plan_revalidates_buy_sell_release_clock_and_scope_relations() -> None:
    plan = _plan()
    assert plan.amount == Decimal("1000.00")
    assert plan.fee_breakdown.total_fee >= Decimal("0.00")
    assert plan.settlement_calendar_reference.endswith(plan.calendar_evidence.snapshot.snapshot_id)
    assert plan.settlement_calendar_evidence_hash == plan.calendar_evidence.evidence_hash
    plan.validate_at(AS_OF + timedelta(seconds=1))

    for changes in (
        {"intent": object()},
        {"market_session": datetime(2026, 10, 16)},
        {"pre_read_at": datetime(2026, 10, 16, 2)},
        {"settlement_lag_sessions": True},
        {"settlement_lag_sessions": -1},
        {"settlement_bundle_id": ""},
        {"settlement_bundle_hash": "sha256:" + "a" * 64},
        {"bundle_valid_until": plan.bundle_effective_from},
        {"calendar_evidence": object()},
        {"fee_policy_v2": object()},
        {"settlement_release_date": None},
        {"settlement_release_date": date(2026, 10, 20)},
    ):
        with pytest.raises(ValueError):
            replace(plan, **changes)

    with pytest.raises(ValueError):
        replace(plan, intent=replace(plan.intent, market="SZ"))
    with pytest.raises(ValueError):
        replace(plan, market_session=date(2026, 10, 19))
    with pytest.raises(ValueError):
        plan.validate_at(plan.pre_read_at - timedelta(seconds=1))
    with pytest.raises(ValueError):
        plan.validate_at(plan.bundle_valid_until)

    sell_plan = _plan(side=SimulatedTradeSide.SELL)
    with pytest.raises(ValueError):
        replace(sell_plan, settlement_release_date=date(2026, 10, 19))


def test_settlement_plan_amount_is_bounded_and_sell_plan_has_no_release_date() -> None:
    sell_plan = _plan(side=SimulatedTradeSide.SELL)
    assert sell_plan.settlement_release_date is None
    huge = _plan(
        quantity=Decimal("99999999999999.999999"),
        price=Decimal("999999.9999"),
    )
    with pytest.raises(ValueError):
        _ = huge.amount


def test_intent_rejects_invalid_identity_scope_text_and_optional_signal_values() -> None:
    intent = _intent()
    invalid_changes: tuple[dict[str, object], ...] = (
        {"account_id": True},
        {"user_id": 0},
        {"idempotency_key": "bad key"},
        {"idempotency_key": "x" * 129},
        {"side": "buy"},
        {"security_id": "SH.SECURITY "},
        {"asset_code": ""},
        {"asset_type": "bad type"},
        {"market": "SH "},
        {"board": ""},
        {"asset_name": ""},
        {"asset_name": "x" * 101},
        {"reason": 1},
        {"reason": "x" * 201},
        {"signal_id": True},
    )

    for change in invalid_changes:
        with pytest.raises(ValueError):
            replace(intent, **change)

    assert len(intent.request_payload_hash) == 64


def test_fee_schedule_snapshot_round_trips_and_rejects_tampered_payloads() -> None:
    schedule = _fee_schedule()
    assert ExecutionFeeSchedule.from_payload(schedule.to_payload()) == schedule
    payload = schedule.to_payload()
    invalid_payloads: tuple[object, ...] = (
        [],
        {key: value for key, value in payload.items() if key != "config_id"},
        {**payload, "unknown": "field"},
        {**payload, "config_id": True},
        {**payload, "asset_type": 7},
        {**payload, "precision_basis": 7},
        {**payload, "commission_rate_buy": "NaN"},
        {**payload, "commission_rate_buy": "01"},
        {**payload, "precision_basis": "unknown"},
        {**payload, "content_hash": "0" * 64},
    )
    for invalid_payload in invalid_payloads:
        with pytest.raises(ValueError):
            ExecutionFeeSchedule.from_payload(invalid_payload)


def test_fee_schedule_rejects_unscoped_or_unrepresentable_database_values() -> None:
    schedule = _fee_schedule()
    for changes in (
        {"config_id": True},
        {"asset_type": "preferred"},
        {"precision_basis": "database_binary64"},
        {"calculation_purpose": "normal_sim_estimated"},
        {"rounding_policy": "component_half_even_cents_v1"},
        {"commission_rate_buy": Decimal("-0.1")},
        {"commission_rate_sell": Decimal("1.1")},
        {"min_commission": Decimal("NaN")},
        {"stamp_duty_rate": Decimal("1.01")},
        {"content_hash": "0" * 64},
    ):
        with pytest.raises(ValueError):
            replace(schedule, **changes)


def test_fee_calculation_handles_both_sides_and_rejects_untyped_requests() -> None:
    schedule = _fee_schedule()
    sell = calculate_trade_fees(
        schedule,
        side=SimulatedTradeSide.SELL,
        amount=Decimal("1000.00"),
        market="SH",
    )
    non_sh = calculate_trade_fees(
        replace(schedule, asset_type="fund", content_hash=""),
        side=SimulatedTradeSide.SELL,
        amount=Decimal("1000.00"),
        market="SZ",
    )
    assert sell.stamp_duty == Decimal("1.00")
    assert sell.transfer_fee > Decimal("0.00")
    assert non_sh.stamp_duty == Decimal("0.00")
    assert non_sh.transfer_fee == Decimal("0.00")

    with pytest.raises(ValueError):
        calculate_trade_fees(object(), side=SimulatedTradeSide.BUY, amount=Decimal("1.00"), market="SH")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        calculate_trade_fees(schedule, side="buy", amount=Decimal("1.00"), market="SH")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        calculate_trade_fees(
            schedule, side=SimulatedTradeSide.BUY, amount=Decimal("0"), market="SH"
        )


def _receipt(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    request_payload_hash: str = "a" * 64,
) -> SimulatedTradeExecutionReceipt:
    """Build one exact successful receipt for the Domain result contract."""

    is_buy = side is SimulatedTradeSide.BUY
    return SimulatedTradeExecutionReceipt(
        trade_id=1,
        account_id=7,
        idempotency_key="intent-001",
        request_payload_hash=request_payload_hash,
        side=side,
        asset_code="600000.SH",
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        amount=Decimal("1000.00"),
        commission=Decimal("0.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("1000.00") if is_buy else Decimal("0.00"),
        settlement_status="pending" if is_buy else None,
        settlement_release_date=date(2026, 10, 19) if is_buy else None,
        replayed=False,
    )


def test_execution_receipt_reconciles_buy_and_sell_state_and_rejects_tampering() -> None:
    buy = _receipt()
    sell = _receipt(side=SimulatedTradeSide.SELL)
    assert buy.total_cost == Decimal("1000.00")
    assert sell.total_cost == Decimal("0.00")

    for changes in (
        {"trade_id": 0},
        {"account_id": 0},
        {"idempotency_key": "bad key"},
        {"request_payload_hash": "bad"},
        {"side": "buy"},
        {"asset_code": ""},
        {"quantity": Decimal("0")},
        {"price": Decimal("0")},
        {"amount": Decimal("-1.00")},
        {"commission": Decimal("-0.01")},
        {"settlement_status": "unknown"},
        {"settlement_release_date": None},
        {"total_cost": Decimal("1001.00")},
        {"replayed": 1},
    ):
        with pytest.raises(ValueError):
            replace(buy, **changes)
    with pytest.raises(ValueError):
        replace(sell, settlement_status="pending")
