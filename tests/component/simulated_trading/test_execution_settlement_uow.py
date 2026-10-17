"""Targeted database tests for the explicit simulated settlement UoW."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, models, transaction

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
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
    ExecutionFeeScheduleUnavailable,
    ReleaseDueSimulatedSettlementsUseCase,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
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
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SimulatedSettlementPlanBindingV1,
    SimulatedSettlementPlanBindingV2,
    bind_settlement_execution_plan_v2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
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
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class _SequenceClock:
    def __init__(self, values: tuple[datetime, ...]) -> None:
        self.values = list(values)

    def now(self) -> datetime:
        if not self.values:
            raise AssertionError("test clock sequence was exhausted")
        return self.values.pop(0)


class _BarrierClock:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.first_read = True

    def now(self) -> datetime:
        if self.first_read:
            self.first_read = False
            self.barrier.wait(timeout=20)
        return AS_OF


class _ReleaseBarrierClock:
    def __init__(self, barrier: Barrier, now: datetime) -> None:
        self.barrier = barrier
        self.current = now
        self.first_read = True

    def now(self) -> datetime:
        if self.first_read:
            self.first_read = False
            self.barrier.wait(timeout=20)
        return self.current


class _RuleReader:
    def __init__(self, bundle: ExecutionSettlementBundleV3) -> None:
        self.bundle = bundle
        self.reads = 0

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        self.reads += 1
        assert security_id == "SH.UOW.SECURITY"
        assert self.bundle.source_available_at <= as_of < self.bundle.valid_until
        return self.bundle


class _CalendarReader:
    def __init__(self, evidence: ExecutionCalendarEvidence | None) -> None:
        self.evidence = evidence
        self.coverage_requests: list[date | None] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        assert exchange == "SH"
        self.coverage_requests.append(coverage_start)
        if self.evidence is not None:
            self.evidence.validate_for(as_of)
        return self.evidence


class _IdentityReader:
    def __init__(self, source_exchange: str = "SH") -> None:
        self.source_exchange = source_exchange
        self.reads = 0

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        self.reads += 1
        response_completed_at = as_of - timedelta(hours=2)
        return ExecutionInstrumentIdentityEvidenceV1(
            security_id=security_id,
            asset_code=asset_code,
            source_code="600000",
            source_exchange=self.source_exchange,
            source_market="SH",
            rule_market="SH",
            board="MAIN",
            snapshot_id=uuid4(),
            snapshot_content_hash="sha256:" + "1" * 64,
            snapshot_record_digest="sha256:" + "2" * 64,
            first_seen_at=response_completed_at,
            snapshot_recorded_at=as_of - timedelta(hours=1),
            mapping_record_id=uuid4(),
            mapping_id="component-test-market-exchange-map",
            mapping_version="1",
            mapping_content_hash="sha256:" + "3" * 64,
            mapping_record_digest="sha256:" + "4" * 64,
            mapping_recorded_at=as_of - timedelta(hours=1, minutes=30),
            response_completed_at=response_completed_at,
            source_observed_at=as_of - timedelta(hours=4),
            source_available_at=as_of - timedelta(hours=3),
            identity_valid_from=as_of - timedelta(days=1),
            identity_valid_until=as_of + timedelta(days=1),
            must_not_use_for_decision=False,
            must_not_execute=False,
        )


class _MissingFeePolicyReader:
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
    ) -> None:
        return None


@pytest.fixture
def ledger(request: pytest.FixtureRequest) -> object:
    """Create only the account/position/trade/fee tables used by this component."""

    user_model = get_user_model()
    with isolated_schema(
        (
            user_model,
            AccountProfileModel,
            SimulatedAccountModel,
            PositionModel,
            SimulatedTradeModel,
            FeeConfigModel,
        )
    ):
        user = user_model.objects.create_user(username="uow-owner", password="unused")
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="uow-account",
            account_type="simulated",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("100000.00"),
            current_market_value=Decimal("0.00"),
            total_value=Decimal("100000.00"),
            is_active=True,
        )
        _seed_fee_policy(
            FeeConfigModel.objects.create(
                config_name="uow-equity-fees",
                asset_type="equity",
                commission_rate_buy=0.0003,
                commission_rate_sell=0.0003,
                min_commission=float(getattr(request, "param", 1.0)),
                stamp_duty_rate=0.001,
                transfer_fee_rate=0.00002,
                min_transfer_fee=0.0,
                slippage_rate=0.001,
                is_default=False,
                is_active=False,
            )
        )
        yield user, account


def _seed_fee_policy(row: FeeConfigModel) -> None:
    """Construct a fixed-clock strict policy fixture without simulating a writer journey."""

    recorded_at = AS_OF - timedelta(days=20)
    FeeConfigModel.objects.filter(pk=row.pk).update(created_at=recorded_at)
    row.refresh_from_db()
    schedule = ExecutionFeeSchedule(
        config_id=row.pk,
        asset_type=row.asset_type,
        commission_rate_buy=Decimal.from_float(row.commission_rate_buy),
        commission_rate_sell=Decimal.from_float(row.commission_rate_sell),
        min_commission=Decimal.from_float(row.min_commission),
        stamp_duty_rate=Decimal.from_float(row.stamp_duty_rate),
        transfer_fee_rate=Decimal.from_float(row.transfer_fee_rate),
        min_transfer_fee=Decimal.from_float(row.min_transfer_fee),
        slippage_rate=Decimal.from_float(row.slippage_rate),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    applies = FeeApplicability.APPLIES
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=applies,
            transfer_fee=applies,
            stamp_duty=(
                applies if side is SimulatedTradeSide.SELL else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=applies,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    policy = SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="component-uow-fees",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=recorded_at,
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=recorded_at,
        transaction_cases=cases,
    )
    fixture_shell = models.QuerySet(FeeConfigModel, using="default").filter(
        pk=row.pk,
        fee_policy_id__isnull=True,
    )
    changed = models.QuerySet.update(
        fixture_shell,
        fee_policy_id=policy.policy_id,
        fee_policy_version=policy.policy_version,
        fee_policy_account_scope=policy.account_scope.value,
        fee_policy_effective_from=policy.effective_from,
        fee_policy_valid_until=policy.valid_until,
        fee_policy_transaction_cases=[case.to_payload() for case in policy.transaction_cases],
        fee_policy_content_hash=policy.content_hash,
    )
    assert changed == 1


def _bundle(*, as_of: datetime = AS_OF, lag: int = 2) -> ExecutionSettlementBundleV3:
    """Create a source-backed v3 bundle active at the supplied clock."""

    base = AShareExecutionRule(
        rule_id="sim-uow-rule",
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
        rule_source_id="sim-uow-source",
        rule_source_version="2026-10",
        rule_source_hash="a" * 64,
        source_observed_at=as_of - timedelta(days=2),
        source_available_at=as_of - timedelta(hours=1),
        effective_from=as_of - timedelta(days=1),
        valid_until=as_of + timedelta(days=30),
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
        policy_id="sim-uow-policy",
        policy_version="1",
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=lag,
        bound_execution_rule_v2_hash=v2.content_hash,
        source_id="sim-uow-policy-source",
        source_version="2026-10",
        source_hash="b" * 64,
        source_observed_at=as_of - timedelta(days=2),
        source_available_at=as_of - timedelta(hours=1),
        effective_from=base.effective_from,
        valid_until=base.valid_until,
    )
    return ExecutionSettlementBundleV3(
        bundle_id="sim-uow-bundle",
        bundle_version="1",
        execution_submission_v2=v2,
        settlement_policy_v1=policy,
    )


def _calendar(
    *,
    as_of: datetime,
    open_dates: set[date],
    exchange: str = "SH",
    start: date = date(2026, 10, 16),
    end: date = date(2026, 10, 21),
) -> ExecutionCalendarEvidence:
    """Build a synthetic publication-bound fixture, not a publication journey."""

    rows: list[ExchangeCalendarDay] = []
    previous_open = start - timedelta(days=1)
    for offset in range((end - start).days + 1):
        current = start + timedelta(days=offset)
        is_open = current in open_dates
        rows.append(ExchangeCalendarDay(exchange, current, is_open, previous_open))
        if is_open:
            previous_open = current
    response_completed = as_of - timedelta(hours=2)
    raw = RawCalendarReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(exchange, start, end),
        original_body_retained=True,
        response_completed_at=response_completed,
        provider_name="fixture-calendar",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id=str(uuid4()),
        exchange=exchange,
        coverage_start=start,
        coverage_end=end,
        days=tuple(rows),
        provider_name="fixture-calendar",
        raw_reference=raw,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed,
        recorded_at=as_of - timedelta(hours=1),
        source_published_at=None,
    )
    publication = CalendarPublicationReference(
        publication_id="uow-calendar-publication",
        member_id=snapshot.snapshot_id,
        publication_hash="2" * 64,
        # This fixture binds the independent canonical fact-row digest.
        fact_content_hash="4" * 64,
        policy_hash="3" * 64,
        published_at=as_of - timedelta(minutes=30),
        recorded_at=as_of - timedelta(minutes=20),
        reference_valid_from=as_of - timedelta(days=10),
        reference_valid_until=as_of + timedelta(days=10),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _v2_plan(
    *,
    repository: DjangoSimulatedTradeExecutionRepository,
    intent: SimulatedTradeIntent,
    as_of: datetime,
    source_exchange: str,
) -> SettlementExecutionPlanV2:
    """Build a fully synthetic V2 plan with separate rule-market and exchange identities."""

    bundle = _bundle(as_of=as_of)
    evidence = _calendar(
        as_of=as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        exchange=source_exchange,
    )
    fee_policy = repository.get_execution_fee_policy(
        account_id=intent.account_id,
        user_id=intent.user_id,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        as_of=as_of,
    )
    assert fee_policy is not None
    identity = _IdentityReader(source_exchange).get_execution_instrument_identity(
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        as_of=as_of,
    )
    market_session = evidence.current_open_session(as_of)
    lag = bundle.settlement_policy_v1.settlement_lag_sessions
    return SettlementExecutionPlanV2(
        intent=intent,
        market_session=market_session,
        pre_read_at=as_of,
        settlement_lag_sessions=lag,
        settlement_release_date=evidence.release_session(market_session, lag),
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
        calendar_evidence=evidence,
        fee_policy_v2=fee_policy,
        identity_evidence=identity,
    )


def _v1_plan(
    *,
    repository: DjangoSimulatedTradeExecutionRepository,
    intent: SimulatedTradeIntent,
    as_of: datetime,
) -> SettlementExecutionPlan:
    """Build an exact legacy V1 plan for historical repository compatibility tests."""

    bundle = _bundle(as_of=as_of)
    evidence = _calendar(
        as_of=as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        exchange=intent.market,
    )
    fee_policy = repository.get_execution_fee_policy(
        account_id=intent.account_id,
        user_id=intent.user_id,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        as_of=as_of,
    )
    assert fee_policy is not None
    market_session = evidence.current_open_session(as_of)
    lag = bundle.settlement_policy_v1.settlement_lag_sessions
    return SettlementExecutionPlan(
        intent=intent,
        market_session=market_session,
        pre_read_at=as_of,
        settlement_lag_sessions=lag,
        settlement_release_date=evidence.release_session(market_session, lag),
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
        calendar_evidence=evidence,
        fee_policy_v2=fee_policy,
    )


def _intent(
    *,
    user_id: int,
    account_id: int,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    key: str = "normal-buy-001",
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("10.00"),
) -> SimulatedTradeIntent:
    """Create an exact account-scoped caller intent."""

    return SimulatedTradeIntent(
        account_id=account_id,
        user_id=user_id,
        idempotency_key=key,
        side=side,
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        price=price,
        reason="component test",
        signal_id=None,
    )


def _execute_use_case(
    *,
    account_id: int,
    user_id: int,
    as_of: datetime,
    evidence: ExecutionCalendarEvidence,
    lag: int = 2,
) -> tuple[ExecuteSettlementBoundSimulatedTradeUseCase, _RuleReader, _CalendarReader]:
    """Compose the public use case with explicit test-owned ports."""

    bundle = _bundle(as_of=as_of, lag=lag)
    rule_reader = _RuleReader(bundle)
    calendar_reader = _CalendarReader(evidence)
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=_IdentityReader(),
        calendar_reader=calendar_reader,
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(as_of),
    )
    return use_case, rule_reader, calendar_reader


def test_new_buy_is_pending_and_add_buy_preserves_existing_available_quantity(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_market_value = Decimal("900.00")
    account.total_value = Decimal("100900.00")
    account.save(update_fields=["current_market_value", "total_value"])
    position = PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("60.000000"),
        avg_cost=Decimal("9.0000"),
        total_cost=Decimal("900.00"),
        current_price=Decimal("9.0000"),
        market_value=Decimal("900.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk, key="add-buy-001"))
    position.refresh_from_db()
    account.refresh_from_db()
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)

    assert receipt.settlement_status == "pending"
    assert receipt.settlement_release_date == date(2026, 10, 20)
    assert position.quantity == Decimal("200.000000")
    assert position.available_quantity == Decimal("60.000000")
    assert trade.settlement_lag_sessions == 2
    assert trade.settlement_bundle_id == "sim-uow-bundle"
    assert trade.settlement_policy_id == "sim-uow-policy"
    assert trade.fee_precision_basis == "database_binary64"
    assert trade.transfer_fee == Decimal("0.02")
    assert trade.slippage == Decimal("1.00")
    assert account.current_cash == Decimal("98997.98")


def test_created_buy_starts_with_zero_sellable_quantity_and_exact_retry_is_idempotent(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, rule_reader, calendar_reader = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )
    intent = _intent(user_id=user.pk, account_id=account.pk)

    first = use_case.execute(intent)
    first_trade = SimulatedTradeModel.objects.get(pk=first.trade_id)
    assert first_trade.settlement_plan_binding_version == 2
    assert first_trade.settlement_plan_binding_payload is not None
    assert first_trade.settlement_plan_binding_hash is not None
    first_binding = SimulatedSettlementPlanBindingV2.from_payload(
        first_trade.settlement_plan_binding_payload
    )
    assert first_binding.content_hash == first_trade.settlement_plan_binding_hash
    assert first_binding.common_binding.executed_at == first_trade.execution_time
    assert first_binding.identity_evidence.source_exchange == "SH"
    assert first_trade.settlement_market == "SH"
    assert first_trade.settlement_exchange == "SH"

    second = use_case.execute(intent)
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    account.refresh_from_db()

    assert first.trade_id == second.trade_id
    assert second.replayed is True
    second_trade = SimulatedTradeModel.objects.get(pk=second.trade_id)
    assert (
        second_trade.settlement_plan_binding_payload == first_trade.settlement_plan_binding_payload
    )
    assert second_trade.settlement_plan_binding_hash == first_trade.settlement_plan_binding_hash
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")
    assert account.current_cash == Decimal("98997.98")
    assert rule_reader.reads == 1
    assert len(calendar_reader.coverage_requests) == 1

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        use_case.execute(_intent(user_id=user.pk, account_id=account.pk, price=Decimal("10.01")))

    account.refresh_from_db()
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1
    assert account.current_cash == Decimal("98997.98")


def test_v2_trade_persists_rule_market_separately_from_source_exchange(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    intent = _intent(user_id=user.pk, account_id=account.pk, key="market-exchange-001")
    plan = _v2_plan(
        repository=repository,
        intent=intent,
        as_of=AS_OF,
        source_exchange="SSE",
    )

    receipt = repository.execute_trade(plan=plan, clock=_Clock(AS_OF))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    binding = SimulatedSettlementPlanBindingV2.from_payload(trade.settlement_plan_binding_payload)

    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_market == "SH"
    assert trade.settlement_exchange == "SSE"
    assert binding.content_hash == trade.settlement_plan_binding_hash
    assert binding.identity_evidence.source_exchange == trade.settlement_exchange
    assert binding.common_binding.calendar_snapshot.exchange == trade.settlement_exchange
    assert repository.get_pending_settlement_scope(
        account_id=account.pk,
        user_id=user.pk,
        asset_code=intent.asset_code,
    ) == PendingSettlementScopeV1(date(2026, 10, 16), "SSE")


def test_v1_historical_repository_receipt_and_release_remain_readable(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    intent = _intent(user_id=user.pk, account_id=account.pk, key="historical-v1-001")
    plan = _v1_plan(repository=repository, intent=intent, as_of=AS_OF)

    receipt = repository.execute_trade(plan=plan, clock=_Clock(AS_OF))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    original_payload = trade.settlement_plan_binding_payload
    original_hash = trade.settlement_plan_binding_hash
    assert trade.settlement_plan_binding_version == 1
    assert trade.settlement_exchange is None
    assert original_payload is not None
    assert original_hash is not None
    v1_binding = SimulatedSettlementPlanBindingV1.from_payload(original_payload)
    assert v1_binding.content_hash == original_hash
    assert repository.get_pending_settlement_scope(
        account_id=account.pk,
        user_id=user.pk,
        asset_code=intent.asset_code,
    ) == PendingSettlementScopeV1(date(2026, 10, 16), "SH")

    replay = repository.find_idempotent_result(
        account_id=account.pk,
        user_id=user.pk,
        idempotency_key=intent.idempotency_key,
    )
    assert replay is not None
    assert replay.trade_id == receipt.trade_id
    assert replay.replayed is False

    release_time = AS_OF + timedelta(days=5)
    release_count = repository.release_due_settlements(
        account_id=account.pk,
        user_id=user.pk,
        asset_code=intent.asset_code,
        calendar_evidence=_calendar(
            as_of=release_time,
            open_dates={
                date(2026, 10, 16),
                date(2026, 10, 19),
                date(2026, 10, 20),
                date(2026, 10, 21),
            },
        ),
        clock=_Clock(release_time),
    )

    trade.refresh_from_db()
    position = PositionModel.objects.get(account=account, asset_code=intent.asset_code)
    assert release_count == 1
    assert trade.settlement_plan_binding_version == 1
    assert trade.settlement_exchange is None
    assert trade.settlement_plan_binding_payload == original_payload
    assert trade.settlement_plan_binding_hash == original_hash
    assert trade.settlement_status == "released"
    assert position.available_quantity == Decimal("100.000000")


def test_v1_receipt_rejects_resealed_calendar_exchange_detached_from_market(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """The unchanged V1 receipt must bind its calendar exchange to its rule market."""

    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    intent = _intent(user_id=user.pk, account_id=account.pk, key="historical-v1-exchange-tamper")
    plan = _v1_plan(repository=repository, intent=intent, as_of=AS_OF)
    receipt = repository.execute_trade(plan=plan, clock=_Clock(AS_OF))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    payload = dict(trade.settlement_plan_binding_payload)
    snapshot = dict(payload["calendar_snapshot"])
    snapshot["exchange"] = "SZSE"
    payload["calendar_snapshot"] = snapshot
    resealed_hash = SimulatedSettlementPlanBindingV1.from_payload(payload).content_hash
    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
        settlement_plan_binding_payload=payload,
        settlement_plan_binding_hash=resealed_hash,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        repository.find_idempotent_result(
            account_id=account.pk,
            user_id=user.pk,
            idempotency_key=intent.idempotency_key,
        )


def test_mixed_pending_source_exchanges_block_release_without_any_writes(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """A corrupted mixed-exchange batch cannot partially release its first row."""

    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    original_intent = _intent(user_id=user.pk, account_id=account.pk, key="mixed-exchange-sse")
    original_plan = _v2_plan(
        repository=repository,
        intent=original_intent,
        as_of=AS_OF,
        source_exchange="SSE",
    )
    original_receipt = repository.execute_trade(plan=original_plan, clock=_Clock(AS_OF))
    original_trade = SimulatedTradeModel.objects.get(pk=original_receipt.trade_id)

    alternate_intent = _intent(user_id=user.pk, account_id=account.pk, key="mixed-exchange-szse")
    alternate_plan = _v2_plan(
        repository=repository,
        intent=alternate_intent,
        as_of=AS_OF,
        source_exchange="SZSE",
    )
    alternate_binding = bind_settlement_execution_plan_v2(
        alternate_plan,
        executed_at=AS_OF,
    )
    alternate_calendar = alternate_plan.calendar_evidence
    alternate_snapshot = alternate_calendar.snapshot
    alternate_publication = alternate_calendar.publication
    assert alternate_publication is not None

    # Seed a second internally consistent, test-only pending row to represent
    # mixed legacy/source data. This does not claim a second real trade journey.
    alternate_trade = SimulatedTradeModel.objects.get(pk=original_trade.pk)
    alternate_trade.pk = None
    alternate_trade._state.adding = True
    alternate_trade.idempotency_key = alternate_intent.idempotency_key
    alternate_trade.request_payload_hash = alternate_intent.request_payload_hash
    alternate_trade.settlement_plan_binding_version = 2
    alternate_trade.settlement_plan_binding_payload = alternate_binding.to_payload()
    alternate_trade.settlement_plan_binding_hash = alternate_binding.content_hash
    alternate_trade.settlement_exchange = "SZSE"
    alternate_trade.execution_time = AS_OF
    alternate_trade.order_date = alternate_plan.market_session
    alternate_trade.execution_date = alternate_plan.market_session
    alternate_trade.settlement_market_session = alternate_plan.market_session
    alternate_trade.settlement_lag_sessions = alternate_plan.settlement_lag_sessions
    alternate_trade.settlement_release_date = alternate_plan.settlement_release_date
    alternate_trade.settlement_calendar_snapshot_id = str(alternate_snapshot.snapshot_id)
    alternate_trade.settlement_calendar_content_hash = alternate_snapshot.content_hash
    alternate_trade.settlement_calendar_record_digest = alternate_snapshot.record_digest
    alternate_trade.settlement_calendar_publication_id = alternate_publication.publication_id
    alternate_trade.settlement_calendar_publication_hash = alternate_publication.publication_hash
    alternate_trade.settlement_calendar_policy_hash = alternate_publication.policy_hash
    alternate_trade.settlement_calendar_evidence_hash = alternate_calendar.evidence_hash
    alternate_trade.settlement_calendar_timezone = alternate_publication.timezone_name
    alternate_trade.save(force_insert=True)
    SimulatedTradeModel._base_manager.filter(pk=alternate_trade.pk).update(execution_time=AS_OF)

    position = PositionModel.objects.get(account=account, asset_code=original_intent.asset_code)
    account.refresh_from_db()
    before_account = (account.current_cash, account.current_market_value, account.total_value)
    before_position = (position.quantity, position.available_quantity, position.total_cost)
    before_rows = tuple(
        SimulatedTradeModel.objects.filter(account=account)
        .order_by("pk")
        .values_list(
            "pk",
            "settlement_status",
            "settlement_released_at",
            "settlement_plan_binding_version",
            "settlement_exchange",
        )
    )

    release_time = AS_OF + timedelta(days=5)
    with pytest.raises(SimulatedTradeExecutionBlocked):
        repository.release_due_settlements(
            account_id=account.pk,
            user_id=user.pk,
            asset_code=original_intent.asset_code,
            calendar_evidence=_calendar(
                as_of=release_time,
                open_dates={
                    date(2026, 10, 16),
                    date(2026, 10, 19),
                    date(2026, 10, 20),
                    date(2026, 10, 21),
                },
                exchange="SSE",
            ),
            clock=_Clock(release_time),
        )

    account.refresh_from_db()
    position.refresh_from_db()
    after_rows = tuple(
        SimulatedTradeModel.objects.filter(account=account)
        .order_by("pk")
        .values_list(
            "pk",
            "settlement_status",
            "settlement_released_at",
            "settlement_plan_binding_version",
            "settlement_exchange",
        )
    )
    assert (
        account.current_cash,
        account.current_market_value,
        account.total_value,
    ) == before_account
    assert (position.quantity, position.available_quantity, position.total_cost) == before_position
    assert after_rows == before_rows


def test_legacy_v1_fee_snapshot_receipt_replays_after_policy_window_expires(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )
    original = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=original.trade_id)
    v2_snapshot = SimulatedFeePolicyV2.from_payload(trade.fee_schedule_snapshot)
    later_cutoff = v2_snapshot.valid_until + timedelta(microseconds=1)
    with pytest.raises(ValueError):
        v2_snapshot.validate_at(later_cutoff)

    # Test-fixture conversion recreates a historical V1 receipt on this persisted row.
    v1_schedule = v2_snapshot.fee_schedule_v1
    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
        fee_schedule_snapshot=v1_schedule.to_payload(),
        fee_schedule_hash=v1_schedule.content_hash,
        settlement_plan_binding_version=0,
        settlement_plan_binding_payload=None,
        settlement_plan_binding_hash=None,
        settlement_exchange=None,
    )

    replayed = DjangoSimulatedTradeExecutionRepository(using="default").find_idempotent_result(
        account_id=account.pk,
        user_id=user.pk,
        idempotency_key=trade.idempotency_key,
    )

    assert replayed is not None
    assert replayed.trade_id == original.trade_id
    assert replayed.total_cost == original.total_cost
    assert replayed.request_payload_hash == original.request_payload_hash


def test_trade_replay_and_mutation_are_scoped_to_the_account_owner(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    owner_use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(_bundle()),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )
    original = owner_use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    stranger = get_user_model().objects.create_user(username="uow-stranger", password="unused")

    assert (
        repository.find_idempotent_result(
            account_id=account.pk,
            user_id=stranger.pk,
            idempotency_key=original.idempotency_key,
        )
        is None
    )
    stranger_use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(_bundle()),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        stranger_use_case.execute(
            _intent(user_id=stranger.pk, account_id=account.pk, key=original.idempotency_key)
        )

    later_as_of = AS_OF + timedelta(days=5)
    later_calendar = _calendar(
        as_of=later_as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    stranger_release = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(later_calendar),
        repository=repository,
        clock=_Clock(later_as_of),
    )
    assert (
        stranger_release.execute(
            account_id=account.pk,
            user_id=stranger.pk,
            asset_code="600000.SH",
            exchange="SH",
        )
        == 0
    )

    account.refresh_from_db()
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1
    assert account.current_cash == Decimal("98997.98")
    assert SimulatedTradeModel.objects.get(pk=original.trade_id).settlement_status == "pending"


def test_locked_clock_cannot_move_before_the_external_evidence_cutoff(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(_bundle()),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_SequenceClock((AS_OF, AS_OF - timedelta(minutes=1))),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(_intent(user_id=user.pk, account_id=account.pk))

    account.refresh_from_db()
    assert account.current_cash == Decimal("100000.00")

    assert SimulatedTradeModel.objects.filter(account=account).count() == 0
    assert PositionModel.objects.filter(account=account).count() == 0


def test_account_market_value_tracks_position_revaluation_without_losing_other_assets(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_market_value = Decimal("1500.00")
    account.total_value = Decimal("101500.00")
    account.save(update_fields=["current_market_value", "total_value"])
    target = PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("1000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    PositionModel.objects.create(
        account=account,
        asset_code="000001.SZ",
        asset_name="Other security",
        asset_type="equity",
        quantity=Decimal("50.000000"),
        available_quantity=Decimal("50.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("500.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("500.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            key="reprice-add-buy",
            quantity=Decimal("100"),
            price=Decimal("11.0000"),
        )
    )

    target.refresh_from_db()
    account.refresh_from_db()
    assert target.market_value == Decimal("2200.00")
    assert PositionModel.objects.get(
        account=account, asset_code="000001.SZ"
    ).market_value == Decimal("500.00")
    assert account.current_market_value == Decimal("2700.00")
    assert account.total_value == Decimal("101597.88")


def test_profitable_full_sell_reconciles_account_market_value_to_zero(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_market_value = Decimal("1000.00")
    account.total_value = Decimal("101000.00")
    account.save(update_fields=["current_market_value", "total_value"])
    PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("1000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    receipt = use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            side=SimulatedTradeSide.SELL,
            key="profitable-full-sell",
            quantity=Decimal("100"),
            price=Decimal("11.0000"),
        )
    )

    account.refresh_from_db()
    assert receipt.side is SimulatedTradeSide.SELL
    assert account.current_market_value == Decimal("0.00")
    assert account.total_value == account.current_cash
    assert PositionModel.objects.filter(account=account, asset_code="600000.SH").count() == 0


def test_partial_then_final_sell_conserves_the_stored_position_cost_basis(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_market_value = Decimal("3300.00")
    account.total_value = Decimal("103300.00")
    account.save(update_fields=["current_market_value", "total_value"])
    PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("300.000000"),
        available_quantity=Decimal("300.000000"),
        avg_cost=Decimal("10.0167"),
        total_cost=Decimal("3005.00"),
        current_price=Decimal("11.0000"),
        market_value=Decimal("3300.00"),
        unrealized_pnl=Decimal("295.00"),
        unrealized_pnl_pct=9.8,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    first = use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            side=SimulatedTradeSide.SELL,
            key="partial-cost-sell",
            quantity=Decimal("100"),
            price=Decimal("11.0000"),
        )
    )
    remaining = PositionModel.objects.get(account=account, asset_code="600000.SH")
    first_trade = SimulatedTradeModel.objects.get(pk=first.trade_id)
    assert first_trade.realized_pnl == Decimal("1100.00") - first_trade.total_cost - Decimal(
        "1001.67"
    )
    assert remaining.total_cost == Decimal("2003.33")
    assert first_trade.realized_pnl is not None

    final = use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            side=SimulatedTradeSide.SELL,
            key="final-cost-sell",
            quantity=Decimal("200"),
            price=Decimal("11.0000"),
        )
    )
    final_trade = SimulatedTradeModel.objects.get(pk=final.trade_id)
    assert final_trade.realized_pnl == Decimal("2200.00") - final_trade.total_cost - Decimal(
        "2003.33"
    )
    assert first_trade.realized_pnl + final_trade.realized_pnl == (
        Decimal("3300.00") - first_trade.total_cost - final_trade.total_cost - Decimal("3005.00")
    )
    assert PositionModel.objects.filter(account=account, asset_code="600000.SH").count() == 0


@pytest.mark.parametrize("ledger", [5.0], indirect=True)
def test_sell_fee_above_gross_proceeds_consumes_cash_and_clears_the_position(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_cash = Decimal("4.00")
    account.current_market_value = Decimal("1.00")
    account.total_value = Decimal("5.00")
    account.save(update_fields=["current_cash", "current_market_value", "total_value"])
    PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("1.000000"),
        available_quantity=Decimal("1.000000"),
        avg_cost=Decimal("1.0000"),
        total_cost=Decimal("1.00"),
        current_price=Decimal("1.0000"),
        market_value=Decimal("1.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    receipt = use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            side=SimulatedTradeSide.SELL,
            key="minimum-fee-closeout",
            quantity=Decimal("1"),
            price=Decimal("1.0000"),
        )
    )

    account.refresh_from_db()
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    assert trade.amount == Decimal("1.00")
    assert trade.commission == Decimal("5.00")
    assert account.current_cash == Decimal("0.00")
    assert account.current_market_value == Decimal("0.00")
    assert account.total_value == Decimal("0.00")
    assert PositionModel.objects.filter(account=account, asset_code="600000.SH").count() == 0


@pytest.mark.parametrize("ledger", [5.0], indirect=True)
def test_sell_fee_above_gross_proceeds_cannot_overdraw_and_rolls_back(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_cash = Decimal("3.99")
    account.current_market_value = Decimal("1.00")
    account.total_value = Decimal("4.99")
    account.save(update_fields=["current_cash", "current_market_value", "total_value"])
    position = PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("1.000000"),
        available_quantity=Decimal("1.000000"),
        avg_cost=Decimal("1.0000"),
        total_cost=Decimal("1.00"),
        current_price=Decimal("1.0000"),
        market_value=Decimal("1.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(
            _intent(
                user_id=user.pk,
                account_id=account.pk,
                side=SimulatedTradeSide.SELL,
                key="minimum-fee-no-overdraft",
                quantity=Decimal("1"),
                price=Decimal("1.0000"),
            )
        )

    account.refresh_from_db()
    position.refresh_from_db()
    assert account.current_cash == Decimal("3.99")
    assert account.current_market_value == Decimal("1.00")
    assert position.quantity == Decimal("1.000000")
    assert SimulatedTradeModel.objects.filter(account=account, action="sell").count() == 0


def test_sell_cannot_use_pending_shares_and_release_uses_stored_lag_with_revised_calendar(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    original = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=original
    )
    buy = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))

    revised_as_of = AS_OF + timedelta(days=4)
    revised = _calendar(
        as_of=revised_as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 20), date(2026, 10, 21)},
    )
    release_use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(revised),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_Clock(revised_as_of),
    )
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    original_release_date = SimulatedTradeModel.objects.get(pk=buy.trade_id).settlement_release_date

    released_early = release_use_case.execute(
        account_id=account.pk,
        user_id=user.pk,
        asset_code="600000.SH",
        exchange="SH",
    )
    position.refresh_from_db()
    assert released_early == 0
    assert position.available_quantity == Decimal("0.000000")
    blocked_sell, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=revised_as_of,
        evidence=revised,
        lag=1,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        blocked_sell.execute(
            _intent(
                user_id=user.pk,
                account_id=account.pk,
                side=SimulatedTradeSide.SELL,
                key="too-early-sell",
            )
        )
    assert SimulatedTradeModel.objects.filter(account=account, action="sell").count() == 0

    later_as_of = AS_OF + timedelta(days=5)
    later_calendar = _calendar(
        as_of=later_as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 20), date(2026, 10, 21)},
    )
    release_use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(later_calendar),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_Clock(later_as_of),
    )
    released = release_use_case.execute(
        account_id=account.pk,
        user_id=user.pk,
        asset_code="600000.SH",
        exchange="SH",
    )
    position.refresh_from_db()
    trade = SimulatedTradeModel.objects.get(pk=buy.trade_id)

    assert released == 1
    assert position.available_quantity == Decimal("100.000000")
    assert trade.settlement_status == "released"
    assert trade.settlement_lag_sessions == 2
    assert trade.settlement_release_date == original_release_date == date(2026, 10, 20)
    assert trade.settlement_release_session == date(2026, 10, 21)
    assert (
        trade.settlement_calendar_evidence_hash != trade.settlement_release_calendar_evidence_hash
    )

    sell_use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=later_as_of,
        evidence=later_calendar,
        lag=1,
    )
    sell = sell_use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            side=SimulatedTradeSide.SELL,
            key="after-release-sell",
        )
    )
    account.refresh_from_db()

    assert sell.side is SimulatedTradeSide.SELL
    assert sell.settlement_status is None
    assert PositionModel.objects.filter(account=account, asset_code="600000.SH").count() == 0
    assert account.current_cash == Decimal("99994.96")


def test_release_blocks_when_persisted_lag_differs_from_original_policy_binding(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
        lag=2,
    )
    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    original_policy_hash = trade.settlement_policy_hash

    assert trade.settlement_lag_sessions == 2
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")

    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(settlement_lag_sessions=0)

    release_use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(evidence),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_Clock(AS_OF),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        release_use_case.execute(
            account_id=account.pk,
            user_id=user.pk,
            asset_code="600000.SH",
            exchange="SH",
        )

    position.refresh_from_db()
    trade.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")
    assert trade.settlement_status == "pending"
    assert trade.settlement_released_at is None
    assert trade.settlement_lag_sessions == 0
    assert trade.settlement_policy_hash == original_policy_hash


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("settlement_lag_sessions", 1),
        ("settlement_policy_hash", "f" * 64),
        ("settlement_exchange", "SZSE"),
        ("settlement_calendar_snapshot_id", "00000000-0000-4000-8000-000000000001"),
        ("settlement_calendar_publication_hash", "9" * 64),
        ("execution_time", AS_OF + timedelta(minutes=1)),
    ],
)
def test_bound_plan_rejects_shape_valid_trade_column_drift(
    ledger: tuple[object, SimulatedAccountModel],
    field_name: str,
    changed_value: object,
) -> None:
    """A valid-looking scalar edit cannot detach the stored plan from its trade."""

    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_plan_binding_hash is not None

    changed = SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
        **{field_name: changed_value}
    )
    assert changed == 1

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    with pytest.raises(SimulatedTradeExecutionBlocked):
        repository.find_idempotent_result(
            account_id=account.pk,
            user_id=user.pk,
            idempotency_key=trade.idempotency_key,
        )


@pytest.mark.parametrize("tampered_status", ["cancelled", "failed"])
@pytest.mark.parametrize("operation", ["replay", "release"])
def test_bound_pending_buy_rejects_execution_status_drift(
    ledger: tuple[object, SimulatedAccountModel],
    tampered_status: str,
    operation: str,
) -> None:
    """A pending settlement cannot disappear from checks through a changed order status."""

    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(status=tampered_status)

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    if operation == "replay":
        with pytest.raises(SimulatedTradeExecutionBlocked):
            repository.find_idempotent_result(
                account_id=account.pk,
                user_id=user.pk,
                idempotency_key=trade.idempotency_key,
            )
    elif operation == "release":
        release_time = AS_OF + timedelta(days=5)
        release_evidence = _calendar(
            as_of=release_time,
            open_dates={
                date(2026, 10, 16),
                date(2026, 10, 19),
                date(2026, 10, 20),
                date(2026, 10, 21),
            },
        )
        release = ReleaseDueSimulatedSettlementsUseCase(
            calendar_reader=_CalendarReader(release_evidence),
            repository=repository,
            clock=_Clock(release_time),
        )
        with pytest.raises(SimulatedTradeExecutionBlocked):
            release.execute(
                account_id=account.pk,
                user_id=user.pk,
                asset_code="600000.SH",
                exchange="SH",
            )
    else:
        raise AssertionError(f"unhandled test operation {operation!r}")

    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    trade.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")
    assert trade.status == tampered_status
    assert trade.settlement_status == "pending"
    assert trade.settlement_released_at is None


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_key",
        "extra_key",
        "unknown_schema",
        "wrong_hash",
        "resealed_policy",
        "resealed_identity",
    ],
)
def test_bound_plan_rejects_malformed_or_resealed_payload(
    ledger: tuple[object, SimulatedAccountModel],
    corruption: str,
) -> None:
    """Strict decoding and row binding reject damaged or independently resealed payloads."""

    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    payload = dict(trade.settlement_plan_binding_payload)
    binding_hash = trade.settlement_plan_binding_hash
    assert binding_hash is not None

    if corruption == "missing_key":
        payload.pop("identity_evidence")
    elif corruption == "extra_key":
        payload["unrecognized_binding_field"] = "must be rejected"
    elif corruption == "unknown_schema":
        payload["schema"] = "simulated-settlement-plan-binding.unknown"
    elif corruption == "wrong_hash":
        binding_hash = "0" * 64
    elif corruption == "resealed_policy":
        common_binding = dict(payload["common_binding"])
        common_binding["settlement_policy_hash"] = "f" * 64
        payload["common_binding"] = common_binding
        binding_hash = SimulatedSettlementPlanBindingV2.from_payload(payload).content_hash
    elif corruption == "resealed_identity":
        identity = dict(payload["identity_evidence"])
        identity["security_id"] = "SZ.UOW.SECURITY"
        payload["identity_evidence"] = identity
        binding_hash = SimulatedSettlementPlanBindingV2.from_payload(payload).content_hash
    else:
        raise AssertionError(f"unhandled test corruption {corruption!r}")

    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
        settlement_plan_binding_payload=payload,
        settlement_plan_binding_hash=binding_hash,
    )

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    with pytest.raises(SimulatedTradeExecutionBlocked):
        repository.find_idempotent_result(
            account_id=account.pk,
            user_id=user.pk,
            idempotency_key=trade.idempotency_key,
        )


def test_corrupt_member_blocks_entire_pending_release_batch(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """One damaged plan prevents any pending row from releasing available shares."""

    user, account = ledger
    source_evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=source_evidence,
    )
    first = use_case.execute(
        _intent(user_id=user.pk, account_id=account.pk, key="batch-binding-first")
    )
    second = use_case.execute(
        _intent(user_id=user.pk, account_id=account.pk, key="batch-binding-second")
    )
    trades = list(SimulatedTradeModel.objects.filter(pk__in=[first.trade_id, second.trade_id]))
    assert len(trades) == 2
    original_binding = {
        trade.pk: (trade.settlement_plan_binding_payload, trade.settlement_plan_binding_hash)
        for trade in trades
    }
    damaged_trade = max(trades, key=lambda trade: trade.pk)
    SimulatedTradeModel._base_manager.filter(pk=damaged_trade.pk).update(
        settlement_plan_binding_hash="0" * 64
    )

    release_time = AS_OF + timedelta(days=5)
    release_evidence = _calendar(
        as_of=release_time,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    release = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(release_evidence),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_Clock(release_time),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        release.execute(
            account_id=account.pk,
            user_id=user.pk,
            asset_code="600000.SH",
            exchange="SH",
        )

    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    assert position.available_quantity == Decimal("0.000000")
    for trade in SimulatedTradeModel.objects.filter(pk__in=[first.trade_id, second.trade_id]):
        trade.refresh_from_db()
        assert trade.settlement_status == "pending"
        assert trade.settlement_released_at is None
        assert trade.settlement_plan_binding_version == 2
        assert trade.settlement_plan_binding_payload == original_binding[trade.pk][0]
        expected_hash = "0" * 64 if trade.pk == damaged_trade.pk else original_binding[trade.pk][1]
        assert trade.settlement_plan_binding_hash == expected_hash


def test_legacy_version_zero_replays_receipt_but_cannot_release_pending_shares(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """Unbound V1-fee history remains readable but cannot authorize a new release."""

    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    intent = _intent(user_id=user.pk, account_id=account.pk, key="legacy-v0-replay")
    original = use_case.execute(intent)
    trade = SimulatedTradeModel.objects.get(pk=original.trade_id)
    v2_policy = SimulatedFeePolicyV2.from_payload(trade.fee_schedule_snapshot)
    v1_schedule = v2_policy.fee_schedule_v1
    SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
        fee_schedule_snapshot=v1_schedule.to_payload(),
        fee_schedule_hash=v1_schedule.content_hash,
        settlement_plan_binding_version=0,
        settlement_plan_binding_payload=None,
        settlement_plan_binding_hash=None,
        settlement_exchange=None,
    )

    replay = use_case.execute(intent)
    assert replay.trade_id == original.trade_id
    assert replay.replayed is True
    assert SimulatedTradeModel.objects.get(pk=trade.pk).settlement_plan_binding_version == 0

    release_time = AS_OF + timedelta(days=5)
    release_evidence = _calendar(
        as_of=release_time,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    release = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(release_evidence),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_Clock(release_time),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        release.execute(
            account_id=account.pk,
            user_id=user.pk,
            asset_code="600000.SH",
            exchange="SH",
        )

    trade.refresh_from_db()
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    assert trade.settlement_status == "pending"
    assert position.available_quantity == Decimal("0.000000")


def test_legacy_model_create_defaults_to_unbound_version_zero(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """Existing non-UoW model writers keep creating explicit legacy rows."""

    _user, account = ledger
    trade = SimulatedTradeModel.objects.create(
        account=account,
        asset_code="LEGACY.TEST",
        asset_name="Legacy import fixture",
        asset_type="equity",
        action="buy",
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("10.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("10.00"),
        order_date=date(2026, 10, 16),
        execution_date=date(2026, 10, 16),
        status="executed",
    )

    assert trade.settlement_plan_binding_version == 0
    assert trade.settlement_plan_binding_payload is None
    assert trade.settlement_plan_binding_hash is None


@pytest.mark.parametrize(
    "changes",
    [
        {
            "settlement_plan_binding_payload": None,
            "settlement_plan_binding_hash": None,
        },
        {"settlement_plan_binding_payload": None},
        {"settlement_plan_binding_hash": None},
        {"settlement_exchange": None},
        {"settlement_plan_binding_version": 3},
    ],
    ids=["clear-pair", "clear-payload", "clear-hash", "missing-exchange", "unknown-version"],
)
def test_version_two_binding_database_constraint_rejects_incomplete_state(
    ledger: tuple[object, SimulatedAccountModel],
    changes: dict[str, object],
) -> None:
    """Version two rows require both seals and the exchange, with no unknown version."""

    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    receipt = use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_plan_binding_payload is not None
    assert trade.settlement_plan_binding_hash is not None
    original_payload = trade.settlement_plan_binding_payload
    original_hash = trade.settlement_plan_binding_hash

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(**changes)

    trade.refresh_from_db()
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_plan_binding_payload == original_payload
    assert trade.settlement_plan_binding_hash == original_hash


def test_missing_formal_calendar_blocks_without_writing_a_trade(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(_bundle()),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(None),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )

    with pytest.raises(ExecutionCalendarUnavailable):
        use_case.execute(_intent(user_id=user.pk, account_id=account.pk))

    assert SimulatedTradeModel.objects.filter(account=account).count() == 0
    assert PositionModel.objects.filter(account=account).count() == 0


def test_missing_explicit_fee_schedule_blocks_without_defaulting_rates(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(_bundle()),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=_MissingFeePolicyReader(),
        repository=repository,
        clock=_Clock(AS_OF),
    )

    with pytest.raises(ExecutionFeeScheduleUnavailable):
        use_case.execute(_intent(user_id=user.pk, account_id=account.pk))

    assert SimulatedTradeModel.objects.filter(account=account).count() == 0
    assert PositionModel.objects.filter(account=account).count() == 0


def test_trade_insert_failure_rolls_back_account_and_position_writes(
    ledger: tuple[object, SimulatedAccountModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk, user_id=user.pk, as_of=AS_OF, evidence=evidence
    )
    original_save = SimulatedTradeModel.save

    def fail_insert(self: SimulatedTradeModel, *args: object, **kwargs: object) -> None:
        if self.idempotency_key is not None:
            raise RuntimeError("injected trade insert failure")
        original_save(self, *args, **kwargs)

    monkeypatch.setattr(SimulatedTradeModel, "save", fail_insert)
    with pytest.raises(RuntimeError, match="injected trade insert failure"):
        use_case.execute(_intent(user_id=user.pk, account_id=account.pk))
    account.refresh_from_db()

    assert account.current_cash == Decimal("100000.00")
    assert account.total_trades == 0
    assert PositionModel.objects.filter(account=account).count() == 0
    assert SimulatedTradeModel.objects.filter(account=account).count() == 0


def _run_racing_submissions(
    *,
    user_id: int,
    account_id: int,
    evidence: ExecutionCalendarEvidence,
    keys: tuple[str, str],
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
) -> list[tuple[str, bool]]:
    """Synchronize callers after evidence reads so PostgreSQL serializes UoWs."""

    barrier = Barrier(len(keys))

    def submit(key: str) -> tuple[str, bool]:
        connections.close_all()
        try:
            repository = DjangoSimulatedTradeExecutionRepository(using="default")
            use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
                rule_reader=_RuleReader(_bundle()),
                identity_reader=_IdentityReader(),
                calendar_reader=_CalendarReader(evidence),
                fee_policy_reader=repository,
                repository=repository,
                clock=_BarrierClock(barrier),
            )
            try:
                receipt = use_case.execute(
                    _intent(user_id=user_id, account_id=account_id, key=key, side=side)
                )
                return "success", receipt.replayed
            except SimulatedTradeExecutionBlocked:
                return "blocked", False
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(keys)) as executor:
        futures = [executor.submit(submit, key) for key in keys]
        return [future.result(timeout=30) for future in futures]


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock concurrency semantics are verified on PostgreSQL",
)
def test_concurrent_exact_idempotency_replay_writes_one_trade(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )

    outcomes = _run_racing_submissions(
        user_id=user.pk,
        account_id=account.pk,
        evidence=evidence,
        keys=("same-exact-request", "same-exact-request"),
    )

    assert [outcome[0] for outcome in outcomes] == ["success", "success"]
    assert sorted(outcome[1] for outcome in outcomes) == [False, True]
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1
    trade = SimulatedTradeModel.objects.get(account=account)
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_exchange == "SH"
    account.refresh_from_db()
    assert account.current_cash == Decimal("98997.98")


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock concurrency semantics are verified on PostgreSQL",
)
def test_concurrent_buys_cannot_spend_the_same_cash_twice(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_cash = Decimal("1002.02")
    account.total_value = Decimal("1002.02")
    account.save(update_fields=["current_cash", "total_value"])
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )

    outcomes = _run_racing_submissions(
        user_id=user.pk,
        account_id=account.pk,
        evidence=evidence,
        keys=("buy-race-a", "buy-race-b"),
    )

    assert sorted(outcome[0] for outcome in outcomes) == ["blocked", "success"]
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1
    trade = SimulatedTradeModel.objects.get(account=account)
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_exchange == "SH"
    account.refresh_from_db()
    assert account.current_cash == Decimal("0.00")


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock concurrency semantics are verified on PostgreSQL",
)
def test_concurrent_sells_cannot_consume_the_same_available_position_twice(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    user, account = ledger
    account.current_market_value = Decimal("1000.00")
    account.total_value = Decimal("101000.00")
    account.save(update_fields=["current_market_value", "total_value"])
    PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("1000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )

    outcomes = _run_racing_submissions(
        user_id=user.pk,
        account_id=account.pk,
        evidence=evidence,
        keys=("sell-race-a", "sell-race-b"),
        side=SimulatedTradeSide.SELL,
    )

    assert sorted(outcome[0] for outcome in outcomes) == ["blocked", "success"]
    assert SimulatedTradeModel.objects.filter(account=account, action="sell").count() == 1
    trade = SimulatedTradeModel.objects.get(account=account, action="sell")
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_exchange == "SH"
    assert not PositionModel.objects.filter(account=account, asset_code="600000.SH").exists()
    account.refresh_from_db()
    assert account.total_trades == 1
    assert account.current_cash == Decimal("100996.98")
    assert account.current_market_value == Decimal("0.00")
    assert account.total_value == account.current_cash


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock release semantics are verified on PostgreSQL",
)
def test_concurrent_releases_add_original_pending_shares_once_and_preserve_binding(
    ledger: tuple[object, SimulatedAccountModel],
) -> None:
    """Two release callers serialize one immutable pending buy without double-crediting."""

    user, account = ledger
    original_evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=AS_OF,
        evidence=original_evidence,
    )
    receipt = use_case.execute(
        _intent(user_id=user.pk, account_id=account.pk, key="release-plan-race")
    )
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    original_payload = trade.settlement_plan_binding_payload
    original_hash = trade.settlement_plan_binding_hash
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_exchange == "SH"
    assert original_payload is not None
    assert original_hash is not None

    release_time = AS_OF + timedelta(days=5)
    release_evidence = _calendar(
        as_of=release_time,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    barrier = Barrier(2)

    def release_once() -> int:
        connections.close_all()
        try:
            repository = DjangoSimulatedTradeExecutionRepository(using="default")
            release_use_case = ReleaseDueSimulatedSettlementsUseCase(
                calendar_reader=_CalendarReader(release_evidence),
                repository=repository,
                clock=_ReleaseBarrierClock(barrier, release_time),
            )
            return release_use_case.execute(
                account_id=account.pk,
                user_id=user.pk,
                asset_code="600000.SH",
                exchange="SH",
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(release_once) for _ in range(2)]
        released_counts = [future.result(timeout=30) for future in futures]

    assert sorted(released_counts) == [0, 1]
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    trade.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("100.000000")
    assert trade.settlement_status == "released"
    assert trade.settlement_plan_binding_version == 2
    assert trade.settlement_exchange == "SH"
    assert trade.settlement_plan_binding_payload == original_payload
    assert trade.settlement_plan_binding_hash == original_hash
