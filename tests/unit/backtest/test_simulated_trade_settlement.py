"""Same-input comparison: stock-selection backtest vs ordinary simulated prepare.

These tests wire the real StockSelectionBacktestEngine to the real
ExecuteSettlementBoundSimulatedTradeUseCase.prepare through in-memory typed
reader doubles. This is a shared-planner comparison only, not ledger or
PostgreSQL acceptance evidence.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.backtest.domain.stock_selection_backtest import (
    RebalanceFrequency,
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
)
from apps.backtest.domain.stock_trade_settlement import (
    SettlementSlippagePolicy,
    StockTradeSettlementContractError,
    StockTradeSettlementQuote,
    StockTradeSettlementRequest,
    StockTradeSide,
)
from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.equity.domain.entities import FinancialData, StockInfo, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule
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
    ExecutionFeeScheduleUnavailable,
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
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from core.integration.backtest_simulated_settlement import (
    BacktestSettlementScope,
    SimulatedSettlementBacktestAdapter,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
FAR_FUTURE = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
FRIDAY = date(2026, 10, 16)
SATURDAY = date(2026, 10, 17)
MONDAY = date(2026, 10, 19)
STOCK = "600000.SH"
PRICEY = "PRICEY.SH"
SECURITY_ID = "SH.UOW.SECURITY"


def _bundle() -> ExecutionSettlementBundleV3:
    """Build one explicit, isolated V3 rule fixture with settlement lag 1."""

    base = AShareExecutionRule(
        rule_id="uow-rule",
        rule_version="1",
        security_id=SECURITY_ID,
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
    submission = ExecutionSubmissionRuleV2(
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
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=submission.content_hash,
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
        execution_submission_v2=submission,
        settlement_policy_v1=policy,
    )


def _calendar() -> ExecutionCalendarEvidence:
    """Create one explicit weekend-spanning calendar; no weekday inference."""

    response_completed_at = AS_OF - timedelta(minutes=20)
    day_rows = (
        ExchangeCalendarDay("SSE", FRIDAY, True, date(2026, 10, 15)),
        ExchangeCalendarDay("SSE", SATURDAY, False, FRIDAY),
        ExchangeCalendarDay("SSE", date(2026, 10, 18), False, FRIDAY),
        ExchangeCalendarDay("SSE", MONDAY, True, FRIDAY),
    )
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", day_rows[0].calendar_date, day_rows[-1].calendar_date
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange="SSE",
        coverage_start=day_rows[0].calendar_date,
        coverage_end=day_rows[-1].calendar_date,
        days=day_rows,
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=AS_OF - timedelta(minutes=10),
        source_published_at=None,
    )
    publication = CalendarPublicationReference(
        publication_id="calendar-publication-202610",
        member_id=snapshot.snapshot_id,
        publication_hash="2" * 64,
        fact_content_hash="4" * 64,
        policy_hash="3" * 64,
        published_at=AS_OF - timedelta(minutes=5),
        recorded_at=AS_OF - timedelta(minutes=4),
        reference_valid_from=AS_OF - timedelta(days=1),
        reference_valid_until=FAR_FUTURE,
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _identity() -> ExecutionInstrumentIdentityEvidenceV1:
    """Create explicitly synthetic, source-clock-qualified identity evidence."""

    return ExecutionInstrumentIdentityEvidenceV1(
        security_id=SECURITY_ID,
        asset_code=STOCK,
        source_code=STOCK,
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
        identity_valid_until=FAR_FUTURE,
        must_not_use_for_decision=False,
        must_not_execute=False,
    )


def _fee_schedule() -> ExecutionFeeSchedule:
    """Build a fee snapshot with every source and calculation choice explicit."""

    return ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
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


def _fee_policy(*, slippage: FeeApplicability) -> SimulatedFeePolicyV2:
    """Build an explicit V2 fee policy for both exact sides."""

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
            stamp_duty=(
                applies if side is SimulatedTradeSide.SELL else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=slippage,
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


def _intent(*, side: SimulatedTradeSide, key: str) -> SimulatedTradeIntent:
    """Build the same exact intent the adapter would submit for 1000 @ 10.00."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key=key,
        side=side,
        security_id=SECURITY_ID,
        asset_code=STOCK,
        asset_name="test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("1000"),
        price=Decimal("10.00"),
        reason="backtest comparison",
        signal_id=None,
    )


class _FixedClock:
    def now(self) -> datetime:
        return AS_OF


class _RuleReader:
    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        return _bundle()


class _IdentityReader:
    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        return _identity()


class _CalendarReader:
    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: date | None
    ) -> ExecutionCalendarEvidence:
        return _calendar()


class _FeeReader:
    def __init__(self, policy: SimulatedFeePolicyV2 | None) -> None:
        self._policy = policy

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
    ) -> SimulatedFeePolicyV2 | None:
        return self._policy


class _EmptyRepository:
    """Repository double whose pending-scope read is the only used member."""

    def find_idempotent_result(
        self, *, account_id: int, user_id: int, idempotency_key: str
    ) -> None:
        raise AssertionError("prepare never reads idempotent results")

    def get_pending_settlement_start(
        self, *, account_id: int, user_id: int, asset_code: str
    ) -> None:
        raise AssertionError("prepare never reads the legacy pending start")

    def get_pending_settlement_scope(
        self, *, account_id: int, user_id: int, asset_code: str
    ) -> PendingSettlementScopeV1 | None:
        return None

    def execute_trade(self, **kwargs: object) -> None:
        raise AssertionError("prepare never mutates the ledger")

    def release_due_settlements(self, **kwargs: object) -> int:
        raise AssertionError("prepare never releases settlements")


class _CutoffResolver:
    def cutoff_for(self, trade_date: date) -> datetime:
        return datetime(trade_date.year, trade_date.month, trade_date.day, 2, 0, tzinfo=UTC)


def _use_case(
    *, fee_policy: SimulatedFeePolicyV2 | None
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    return ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_RuleReader(),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(),
        fee_policy_reader=_FeeReader(fee_policy),
        repository=_EmptyRepository(),
        clock=_FixedClock(),
    )


def _scope() -> BacktestSettlementScope:
    return BacktestSettlementScope(
        account_id=7,
        user_id=11,
        security_id=SECURITY_ID,
        asset_name="test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        reason="backtest comparison",
        signal_id=None,
    )


def _adapter(
    *,
    fee_policy: SimulatedFeePolicyV2 | None,
    slippage_policy: SettlementSlippagePolicy,
) -> SimulatedSettlementBacktestAdapter:
    return SimulatedSettlementBacktestAdapter(
        prepare_capability=_use_case(fee_policy=fee_policy),
        scope=_scope(),
        cutoff_resolver=_CutoffResolver(),
        slippage_policy=slippage_policy,
    )


class _RecordingPort:
    """Settlement port wrapper capturing every request and quote."""

    def __init__(self, inner: SimulatedSettlementBacktestAdapter) -> None:
        self._inner = inner
        self.requests: list[StockTradeSettlementRequest] = []
        self.quotes: list[StockTradeSettlementQuote] = []

    def quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        quote = self._inner.quote(request)
        self.requests.append(request)
        self.quotes.append(quote)
        return quote


def _stock_entries(
    codes: list[str], as_of: date
) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]:
    """Build real screening entities that pass a default-permissive rule."""

    return [
        (
            StockInfo(
                stock_code=code,
                name=code,
                sector="test-sector",
                market="SH",
                list_date=None,
            ),
            FinancialData(
                stock_code=code,
                report_date=as_of,
                revenue=Decimal("100"),
                net_profit=Decimal("10"),
                revenue_growth=10.0,
                net_profit_growth=10.0,
                total_assets=Decimal("1000"),
                total_liabilities=Decimal("300"),
                equity=Decimal("700"),
                roe=15.0,
                roa=5.0,
                debt_ratio=30.0,
            ),
            ValuationMetrics(
                stock_code=code,
                trade_date=as_of,
                pe=10.0,
                pb=1.5,
                ps=1.0,
                total_mv=Decimal("5000000000"),
                circ_mv=Decimal("4000000000"),
                dividend_yield=1.0,
            ),
        )
        for code in codes
    ]


def _rules() -> dict[str, StockScreeningRule]:
    return {"Recovery": StockScreeningRule(regime="Recovery", name="test")}


def _engine(
    *,
    config: StockSelectionBacktestConfig,
    port: object,
    slippage_policy: SettlementSlippagePolicy,
    stock_reader: object,
) -> StockSelectionBacktestEngine:
    return StockSelectionBacktestEngine(
        config=config,
        get_regime_func=lambda as_of: "Recovery",
        get_stock_data_func=stock_reader,  # type: ignore[arg-type]
        get_price_func=lambda code, as_of: (
            Decimal("10.00") if code == STOCK else Decimal("999999.99")
        ),
        get_benchmark_price_func=lambda as_of: 100.0,
        stock_trade_settlement=port,  # type: ignore[arg-type]
        settlement_slippage_policy=slippage_policy,
    )


def test_backtest_and_prepare_agree_on_buy_sell_fees_cash_and_sessions() -> None:
    """Same BUY/SELL input yields identical quantity, fees, cash, and sessions."""

    policy = _fee_policy(slippage=FeeApplicability.APPLIES)
    port = _RecordingPort(
        _adapter(fee_policy=policy, slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT)
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=MONDAY,
        initial_capital=Decimal("20000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
    )

    def stock_reader(as_of: date) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]:
        if as_of < MONDAY:
            return _stock_entries([STOCK, PRICEY], as_of)
        return _stock_entries([PRICEY], as_of)

    result = _engine(
        config=config,
        port=port,
        slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        stock_reader=stock_reader,
    ).run(_rules())

    # Independent exercise of the existing ordinary prepare path, same inputs.
    independent = _use_case(fee_policy=policy)
    buy_prepared = independent.prepare(
        _intent(side=SimulatedTradeSide.BUY, key="independent-buy"), as_of=AS_OF
    )
    sell_prepared = independent.prepare(
        _intent(side=SimulatedTradeSide.SELL, key="independent-sell"),
        as_of=_CutoffResolver().cutoff_for(MONDAY),
    )

    buy_fees = buy_prepared.plan.fee_breakdown
    assert buy_prepared.plan.amount == Decimal("10000.00")
    assert buy_fees.commission == Decimal("5.00")
    assert buy_fees.transfer_fee == Decimal("0.20")
    assert buy_fees.stamp_duty == Decimal("0.00")
    assert buy_fees.slippage == Decimal("10.00")
    assert buy_prepared.plan.market_session == FRIDAY
    assert buy_prepared.plan.settlement_release_date == MONDAY

    sell_fees = sell_prepared.plan.fee_breakdown
    assert sell_prepared.plan.amount == Decimal("10000.00")
    assert sell_fees.commission == Decimal("5.00")
    assert sell_fees.transfer_fee == Decimal("0.20")
    assert sell_fees.stamp_duty == Decimal("10.00")
    assert sell_fees.slippage == Decimal("10.00")
    assert sell_prepared.plan.market_session == MONDAY
    assert sell_prepared.plan.settlement_release_date is None

    # The engine path observed exactly the same quantities, fees, cash, sessions.
    assert [request.side.value for request in port.requests] == ["buy", "sell"]
    buy_quote, sell_quote = port.quotes
    assert buy_quote.executed_quantity == 1000
    assert buy_quote.executed_price == Decimal("10.00")
    assert buy_quote.commission == buy_fees.commission
    assert buy_quote.transfer_fee == buy_fees.transfer_fee
    assert buy_quote.stamp_duty == buy_fees.stamp_duty
    assert buy_quote.slippage == buy_fees.slippage
    assert buy_quote.cash_delta == Decimal("-10015.20")
    assert buy_quote.market_session == FRIDAY
    assert buy_quote.release_session == MONDAY
    assert sell_quote.executed_quantity == 1000
    assert sell_quote.cash_delta == Decimal("9974.80")
    assert sell_quote.market_session == MONDAY
    assert sell_quote.release_session is None

    assert result.total_trades == 2
    assert result.equity_curve[-1] == (MONDAY, Decimal("19959.60"))


def test_unknown_fee_policy_blocks_the_backtest_trade() -> None:
    """A missing exact fee policy blocks instead of settling with zero fees."""

    port = _RecordingPort(
        _adapter(fee_policy=None, slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT)
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=FRIDAY,
        initial_capital=Decimal("20000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
    )
    with pytest.raises(ExecutionFeeScheduleUnavailable):
        _engine(
            config=config,
            port=port,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
            stock_reader=lambda as_of: _stock_entries([STOCK, PRICEY], as_of),
        ).run(_rules())


def test_in_price_slippage_is_not_charged_twice() -> None:
    """In-price slippage reprices execution and forbids any slippage fee."""

    policy = _fee_policy(slippage=FeeApplicability.NOT_APPLICABLE)
    port = _RecordingPort(
        _adapter(fee_policy=policy, slippage_policy=SettlementSlippagePolicy.ALREADY_IN_PRICE)
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=MONDAY,
        initial_capital=Decimal("20000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
        slippage_rate=0.001,
    )
    result = _engine(
        config=config,
        port=port,
        slippage_policy=SettlementSlippagePolicy.ALREADY_IN_PRICE,
        stock_reader=lambda as_of: _stock_entries([STOCK, PRICEY], as_of),
    ).run(_rules())

    buy_quote = port.quotes[0]
    assert buy_quote.executed_price == Decimal("10.01")
    assert buy_quote.executed_quantity == 999
    assert buy_quote.slippage == Decimal("0.00")
    sell_quote = port.quotes[-1]
    assert sell_quote.executed_price == Decimal("9.99")
    assert sell_quote.slippage == Decimal("0.00")

    independent = _use_case(fee_policy=policy)
    buy_prepared = independent.prepare(
        replace(
            _intent(side=SimulatedTradeSide.BUY, key="in-price-buy"),
            quantity=Decimal("999"),
            price=Decimal("10.01"),
        ),
        as_of=AS_OF,
    )
    assert buy_prepared.plan.amount == buy_quote.amount
    assert buy_prepared.plan.fee_breakdown.total_fee == (
        buy_quote.commission + buy_quote.transfer_fee + buy_quote.stamp_duty
    )
    assert result.total_trades >= 2


def test_in_price_slippage_rejects_a_prepared_slippage_fee() -> None:
    """A nonzero prepared slippage fee under in-price policy is a hard block."""

    adapter = _adapter(
        fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES),
        slippage_policy=SettlementSlippagePolicy.ALREADY_IN_PRICE,
    )
    request = StockTradeSettlementRequest(
        stock_code=STOCK,
        side=StockTradeSide.BUY,
        quantity=1000,
        price=Decimal("10.01"),
        trade_date=FRIDAY,
        available_cash=Decimal("20000"),
    )
    with pytest.raises(StockTradeSettlementContractError):
        adapter.quote(request)


class _TamperingPort:
    """Port double returning a damaged quote from the real adapter."""

    def __init__(self, inner: SimulatedSettlementBacktestAdapter, **changes: object) -> None:
        self._inner = inner
        self._changes = changes

    def quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        return replace(self._inner.quote(request), **self._changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"executed_quantity": 50},
        {"stock_code": "OTHER.SH"},
        {"cash_delta": Decimal("0")},
        {"release_session": None},
        {"executed_price": Decimal("9.99")},
    ],
)
def test_engine_rejects_invalid_adapter_outputs(changes: dict[str, object]) -> None:
    """Partial quantities, rewritten identity, or broken cash arithmetic block."""

    port = _TamperingPort(
        _adapter(
            fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        ),
        **changes,
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=FRIDAY,
        initial_capital=Decimal("20000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
    )
    with pytest.raises(StockTradeSettlementContractError):
        _engine(
            config=config,
            port=port,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
            stock_reader=lambda as_of: _stock_entries([STOCK, PRICEY], as_of),
        ).run(_rules())


def test_same_session_sell_before_release_is_denied() -> None:
    """A SELL before the exact prepared release session raises, even at liquidation."""

    port = _RecordingPort(
        _adapter(
            fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=SATURDAY,
        initial_capital=Decimal("20000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
    )

    def stock_reader(as_of: date) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]:
        if as_of == FRIDAY:
            return _stock_entries([STOCK, PRICEY], as_of)
        return []

    with pytest.raises(StockTradeSettlementContractError, match="precedes its release session"):
        _engine(
            config=config,
            port=port,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
            stock_reader=stock_reader,
        ).run(_rules())
    assert len(port.quotes) == 1
    assert port.quotes[0].release_session == MONDAY


def test_unaffordable_candidate_is_rejected_without_negative_cash() -> None:
    """An exact quote that would drive cash negative skips the BUY candidate."""

    port = _RecordingPort(
        _adapter(
            fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )
    )
    config = StockSelectionBacktestConfig(
        start_date=FRIDAY,
        end_date=FRIDAY,
        initial_capital=Decimal("10000"),
        rebalance_frequency=RebalanceFrequency.DAILY,
        max_positions=2,
    )
    result = _engine(
        config=config,
        port=port,
        slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        stock_reader=lambda as_of: _stock_entries([STOCK], as_of),
    ).run(_rules())

    assert result.total_trades == 0
    assert result.equity_curve[-1] == (FRIDAY, Decimal("10000"))
