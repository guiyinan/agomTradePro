"""Exercise automatic orders through the guarded current-reference ledger path."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, models
from django.db.models import Model

import apps.simulated_trading.application.auto_trading_engine as auto_engine_module
import apps.simulated_trading.application.facade as facade_module
import apps.simulated_trading.application.interface_services as interface_services
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.risk_center.application.trade_guard import PreTradeRiskCheckResult
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
from apps.risk_center.infrastructure.ashare_execution_rule_repository import (
    DjangoAShareExecutionRuleRepository,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
    FeePolicyVersionCommand,
)
from apps.simulated_trading.application.ports import PositionExitAdvice
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SimulatedSettlementPlanBindingV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.automatic_trading_invocation_models import (
    AutomaticTradingInvocationModel,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.strategy.application import execution_gateway
from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_clock_v2 import (
    advance_auto_uow_fixture_clocks,
    advance_auto_uow_fixture_read_clock,
    freeze_auto_uow_fixture_clocks_native,
)
from tests.support.ash03_auto_calendar_fixture import (
    FormalCalendarFixture,
    persist_auto_uow_formal_calendar,
)
from tests.support.ash03_auto_uow_fixture import (
    AutoCurrentReferenceUowFixture,
    build_auto_current_reference_uow_fixture,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
KNOWLEDGE_AT = datetime(2026, 10, 16, 1, 59, 50, tzinfo=UTC)
TRADE_DATE = date(2026, 10, 16)
ASSET_CODE = "600000.SH"
SOURCE_CODE = "600000.SH"
ASSET_NAME = "Fixture bank"
SECURITY_ID = "SH.ASH03.AUTO.CALLER"
RULE_SOURCE = "ash03-auto-caller-local-rule"
PRICE_SOURCE = "ash03-auto-caller-historical-bar"
BUY_INVOCATION_KEY = "ash03-auto-qualified-t1-buy"


@dataclass(frozen=True, slots=True)
class _QualifiedCallerContext:
    """Hold one persisted source selector, formal calendar, and account scope."""

    account: SimulatedAccountModel
    owner_id: int
    source: InstrumentReferenceSnapshotRecord
    calendar: FormalCalendarFixture
    uow: AutoCurrentReferenceUowFixture


@pytest.fixture(autouse=True)
def _freeze_auto_fixture_knowledge_clocks(
    monkeypatch: pytest.MonkeyPatch, django_db_use_migrations: bool
) -> None:
    """Freeze persisted fixture knowledge before source and account fixtures run."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("qualified automatic caller proof requires migrated native PostgreSQL")
    assert_native_postgres_test_database()
    assert freeze_auto_uow_fixture_clocks_native(monkeypatch) == KNOWLEDGE_AT


@pytest.fixture
def qualified_caller_context(
    monkeypatch: pytest.MonkeyPatch,
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> _QualifiedCallerContext:
    """Persist exact local evidence and compose real readers without using providers."""

    source_repository, source_content = persisted_source_snapshot
    source_record = SaveInstrumentReferenceSnapshotUseCase(source_repository).execute(
        source_content
    )
    classification = source_content.classify_security(SOURCE_CODE)
    assert classification is not None
    assert classification.blocked_reason is None
    assert classification.rule_market is not None
    assert classification.board is not None

    account = _create_account()
    owner_id = account.user_id
    assert type(account.pk) is int
    assert type(owner_id) is int

    calendar = persist_auto_uow_formal_calendar(
        as_of=AS_OF,
        exchange=classification.source_exchange,
        timezone_name="Asia/Shanghai",
        advance_clock=lambda: advance_auto_uow_fixture_read_clock(monkeypatch, as_of=AS_OF),
    )
    assert calendar.market_session == TRADE_DATE
    assert calendar.next_open_session == date(2026, 10, 19)

    bundle = _seed_rule_bundle(
        security_id=SECURITY_ID,
        market=classification.rule_market,
        board=classification.board,
    )
    _seed_fee_policy(
        account_id=account.pk,
        market=classification.rule_market,
        board=classification.board,
    )
    _seed_historical_price()

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    runtime_environment = "production" if settings_module.endswith(".production") else "development"
    uow = build_auto_current_reference_uow_fixture(
        source_snapshot=source_record,
        account_id=account.pk,
        user_id=owner_id,
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        source_code=SOURCE_CODE,
        runtime_environment=runtime_environment,
        exchange_timezone="Asia/Shanghai",
        as_of=AS_OF,
    )
    assert uow.as_of == AS_OF
    identity = uow.read_identity_evidence()
    assert type(identity) is ExecutionInstrumentIdentityEvidenceV2
    identity.validate_at(as_of=AS_OF)
    assert identity.selection.purpose == "normal_simulated_current_reference"
    assert identity.source_evidence.source_observed_at is None
    assert identity.source_evidence.source_available_at is None
    assert identity.source_evidence.must_not_use_for_decision is True
    assert identity.source_evidence.must_not_execute is True
    assert uow.market_session == TRADE_DATE
    assert uow.rule_bundle.content_hash == bundle.content_hash

    advance_auto_uow_fixture_clocks(monkeypatch, as_of=AS_OF)
    return _QualifiedCallerContext(
        account=account,
        owner_id=owner_id,
        source=source_record,
        calendar=calendar,
        uow=uow,
    )


class _OneAssetPoolRepository:
    """Expose one synthetic candidate while keeping the production Engine caller."""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return one candidate only for the expected bounded equity query."""

        assert (asset_type, min_score, limit) == ("equity", 60.0, 20)
        return [
            {
                "asset_code": ASSET_CODE,
                "asset_name": ASSET_NAME,
                "asset_type": "equity",
                "score": 100.0,
            }
        ]

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        """Return the exact fixture-owned pool category."""

        assert asset_code == ASSET_CODE
        return "investable"

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        """Return the minimal summary consumed by the application service."""

        del asset_type
        return {"investable": 1, "prohibited": 0, "watch": 0, "candidate": 0}


class _NoCandidatePoolRepository:
    """Return no BUY work for the SELL rollback cases."""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return an empty owned pool for the exact Engine request."""

        assert (asset_type, min_score, limit) == ("equity", 60.0, 20)
        return []

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        """No candidate asset has a pool category in the SELL cases."""

        del asset_code
        return None

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        """Return a stable empty-pool summary."""

        del asset_type
        return {"investable": 0, "prohibited": 0, "watch": 0, "candidate": 0}


class _ValidSignalRepository:
    """Supply one explicit synthetic BUY signal to the actual pool query service."""

    def get_valid_signal_summaries(
        self,
        asset_codes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Return an exact signal for the requested fixture security."""

        if asset_codes is not None and ASSET_CODE not in asset_codes:
            return []
        return [{"asset_code": ASSET_CODE, "signal_id": 7201, "logic_desc": "fixture"}]

    def get_signal_snapshot(self, signal_id: int) -> dict[str, object] | None:
        """Return a valid row only for the fixture's signal id."""

        return {"signal_id": signal_id, "is_valid": True} if signal_id == 7201 else None

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]:
        """Report no invalidation for the exact owned signal."""

        assert signal_id == 7201
        return None, ""


class _EmptySignalRepository:
    """Keep the SELL cases free of any follow-up BUY candidate."""

    def get_valid_signal_summaries(
        self,
        asset_codes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Return no signals after the empty pool read."""

        del asset_codes
        return []

    def get_signal_snapshot(self, signal_id: int) -> dict[str, object] | None:
        """No signal snapshot exists in these SELL-only cases."""

        del signal_id
        return None

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]:
        """No signal invalidation exists in these SELL-only cases."""

        del signal_id
        return None, ""


class _PassingRiskPolicyReader:
    """Replace only the independent pre-trade policy result for one BUY case."""

    def execute(
        self,
        *,
        account_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        account_equity: float,
        total_position_value: float,
        cash_balance: float | None = None,
        current_symbol_position_value: float = 0.0,
    ) -> PreTradeRiskCheckResult:
        """Pass only the exact, predeclared fixture order and account snapshot."""

        assert account_id > 0
        assert symbol == ASSET_CODE
        assert side == "buy"
        assert quantity == 200.0
        assert price == 100.0
        assert account_equity == 100_000.0
        assert total_position_value == 0.0
        assert cash_balance == 100_000.0
        assert current_symbol_position_value == 0.0
        return PreTradeRiskCheckResult(passed=True)


class _StrategyBinding:
    """Represent a real account with either no strategy or one selected strategy."""

    def __init__(self, strategy_id: int | None) -> None:
        """Bind a deterministic strategy selection for the caller branch."""

        self._strategy_id = strategy_id

    def get_active_strategy_id(self, account_id: int) -> int | None:
        """Return the test's strategy choice for the persisted account."""

        assert account_id > 0
        return self._strategy_id


class _NeverSellAdvisor:
    """Keep the BUY caller case free of upstream exit advice."""

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]:
        """Return no exits for an account with no existing positions."""

        assert account_id > 0
        assert as_of_date == TRADE_DATE
        assert positions == []
        return []


class _AlwaysSellAdvisor:
    """Supply one exact legacy exit advice while leaving the Engine and writer real."""

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]:
        """Request the full existing fixture holding at the current run date."""

        assert account_id > 0
        assert as_of_date == TRADE_DATE
        assert positions
        return [
            PositionExitAdvice(
                asset_code=ASSET_CODE,
                should_exit=True,
                reason_code="ASH03_AUTO_SELL_ROLLBACK",
                reason_text="fixture-owned legacy sell advice",
                source="tests.component.simulated_trading",
            )
        ]


class _OneSellStrategyGateway:
    """Return one typed strategy SELL signal for the alternate actual Engine path."""

    def execute_for_account(
        self,
        *,
        strategy_id: int,
        account_id: int,
        as_of_date: date,
    ) -> ExecutionResult:
        """Return one full-position signal for the fixture strategy and session."""

        assert strategy_id == 91
        assert account_id > 0
        assert as_of_date == TRADE_DATE
        return ExecutionResult(
            success=True,
            signals=[
                SignalInfo(
                    signal_id=None,
                    asset_code=ASSET_CODE,
                    asset_name=ASSET_NAME,
                    action="sell",
                    quantity=1000,
                    confidence=1.0,
                    reason="fixture strategy sell",
                )
            ],
        )


def _build_real_auto_caller(
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_buy_candidate: bool,
    strategy_id: int | None,
    legacy_exit: bool,
) -> None:
    """Replace upstream pool, signal, risk, and advice reads only."""

    pool_factory: Callable[[], object] = (
        _OneAssetPoolRepository if include_buy_candidate else _NoCandidatePoolRepository
    )
    signal_factory: Callable[[], object] = (
        _ValidSignalRepository if include_buy_candidate else _EmptySignalRepository
    )
    monkeypatch.setattr(interface_services, "get_asset_pool_query_repository", pool_factory)
    monkeypatch.setattr(interface_services, "get_signal_repository", signal_factory)
    monkeypatch.setattr(auto_engine_module, "EvaluatePreTradeRiskUseCase", _PassingRiskPolicyReader)
    monkeypatch.setattr(
        facade_module,
        "get_simulated_trading_facade",
        lambda: _StrategyBinding(strategy_id),
    )
    monkeypatch.setattr(
        interface_services,
        "build_decision_rhythm_exit_advisor",
        lambda: _AlwaysSellAdvisor() if legacy_exit else _NeverSellAdvisor(),
    )
    if strategy_id is not None:
        monkeypatch.setattr(
            execution_gateway,
            "get_strategy_execution_gateway",
            lambda: _OneSellStrategyGateway(),
        )


def _create_account(
    *,
    current_market_value: Decimal = Decimal("0.00"),
    total_value: Decimal = Decimal("100000.00"),
) -> SimulatedAccountModel:
    """Create one complete simulated account for real repository and owner reads."""

    owner = get_user_model()._default_manager.create_user(username=f"ash03-auto-{uuid4().hex}")
    account = SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=f"ASH03 Auto {uuid4().hex[:12]}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
        current_market_value=current_market_value,
        total_value=total_value,
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        auto_trading_enabled=True,
        is_active=True,
    )
    assert account.cash_known is True
    assert account.cash_reconciliation_status == "simulated_ledger"
    return account


class _FixedRiskClock:
    """Return the fixture's exact Risk V3 knowledge-write timestamp."""

    def now(self) -> datetime:
        """Return the UTC instant preceding the execution cutoff."""

        return KNOWLEDGE_AT


def _seed_rule_bundle(*, security_id: str, market: str, board: str) -> ExecutionSettlementBundleV3:
    """Persist an exact effective Risk V3 settlement and quantity-rule bundle."""

    rule_id = f"ash03-auto-rule-{uuid4().hex}"
    source_available_at = AS_OF - timedelta(hours=1)
    effective_from = AS_OF - timedelta(minutes=30)
    valid_until = AS_OF + timedelta(days=30)
    base_rule = AShareExecutionRule(
        rule_id=rule_id,
        rule_version="1",
        security_id=security_id,
        market=market,
        board=board,
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id=RULE_SOURCE,
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(hours=2),
        source_available_at=source_available_at,
        effective_from=effective_from,
        valid_until=valid_until,
    )
    submission_rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=base_rule,
        price_submission_range=PriceSubmissionRangeRule(
            market=market,
            board=board,
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
        policy_id=f"{rule_id}-settlement",
        policy_version="1",
        security_id=security_id,
        market=market,
        board=board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=submission_rule.content_hash,
        source_id=f"{rule_id}-source",
        source_version="fixture-v1",
        source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(hours=2),
        source_available_at=source_available_at,
        effective_from=effective_from,
        valid_until=valid_until,
    )
    bundle = ExecutionSettlementBundleV3(
        bundle_id=f"{rule_id}-bundle",
        bundle_version="1",
        execution_submission_v2=submission_rule,
        settlement_policy_v1=policy,
    )
    imported = DjangoAShareExecutionRuleRepository(
        clock=_FixedRiskClock()
    ).import_settlement_bundles(bundles=(bundle,))
    assert imported.inserted_count == 1
    return bundle


def _seed_fee_policy(*, account_id: int, market: str, board: str) -> None:
    """Persist one exact BUY and SELL Fee V2 policy through its public use case."""

    applicability = FeeApplicability.APPLIES
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market=market,
            board=board,
            side=side,
            commission=applicability,
            transfer_fee=applicability,
            stamp_duty=(
                applicability
                if side is SimulatedTradeSide.SELL
                else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=applicability,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    token = uuid4().hex
    command = FeePolicyVersionCommand(
        config_name=f"ASH03 auto Fee {token[:20]}",
        asset_type="equity",
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00002,
        min_transfer_fee=0.0,
        slippage_rate=0.001,
        policy_id=f"ash03-auto-fee-{token}",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=30),
        transaction_cases=cases,
        description="fixture-owned exact cases for a qualified automatic caller",
    )
    policy = CreateFeePolicyVersionUseCase(
        repository=DjangoFeePolicyV2Repository(using="default"),
    ).execute(command)
    assert policy.policy_id == command.policy_id
    assert policy.recorded_at <= AS_OF
    assert account_id > 0


def _seed_historical_price() -> None:
    """Persist an exact same-session historical bar used by the real price service."""

    PriceBarModel._default_manager.create(
        asset_code=ASSET_CODE,
        bar_date=TRADE_DATE,
        freq="1d",
        adjustment="none",
        open=Decimal("100.0000"),
        high=Decimal("100.0000"),
        low=Decimal("100.0000"),
        close=Decimal("100.0000"),
        volume=Decimal("1000000.00"),
        amount=Decimal("100000000.00"),
        source=PRICE_SOURCE,
        quality_status="accepted",
    )


def _persist_sell_position(account: SimulatedAccountModel) -> PositionModel:
    """Create a fully known, exactly sellable prior holding for rollback cases."""

    return PositionModel._default_manager.create(
        account=account,
        asset_code=ASSET_CODE,
        asset_name=ASSET_NAME,
        asset_type="equity",
        quantity=Decimal("1000.000000"),
        available_quantity=Decimal("1000.000000"),
        available_quantity_known=True,
        avg_cost=Decimal("90.0000"),
        total_cost=Decimal("90000.00"),
        cost_basis_known=True,
        current_price=Decimal("100.0000"),
        market_value=Decimal("100000.00"),
        valuation_known=True,
        unrealized_pnl=Decimal("10000.00"),
        unrealized_pnl_pct=11.1111,
        first_buy_date=TRADE_DATE - timedelta(days=1),
        first_buy_date_known=True,
    )


def test_auto_caller_new_buy_uses_real_uow_and_keeps_t1_shares_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    qualified_caller_context: _QualifiedCallerContext,
) -> None:
    """Run the real guarded Engine caller and retain T+1 settlement in its ledger."""

    account = qualified_caller_context.account
    account_id = account.pk
    assert type(account_id) is int
    _build_real_auto_caller(
        monkeypatch,
        include_buy_candidate=True,
        strategy_id=None,
        legacy_exit=False,
    )
    outcome = interface_services.run_auto_trading_for_scope(
        trade_date=TRADE_DATE,
        account_ids=(account_id,),
        invocation_key=BUY_INVOCATION_KEY,
    )

    account_outcome = outcome.accounts[0]
    assert outcome.requested_account_ids == (account_id,)
    assert account_outcome.buy_count == 1
    assert account_outcome.sell_count == 0
    assert account_outcome.confirmed_trade_count == 1
    assert account_outcome.stored == 1

    invocation = AutomaticTradingInvocationModel._default_manager.get(
        namespace="internal:simulated-auto",
        invocation_key=BUY_INVOCATION_KEY,
    )
    assert invocation.state == AutomaticTradingInvocationModel.STATE_FINISHED
    assert invocation.account_ids == [account_id]
    assert invocation.trade_date == TRADE_DATE

    trade = SimulatedTradeModel._default_manager.get(account_id=account_id)
    assert trade.action == "buy"
    assert trade.status == "executed"
    assert trade.asset_code == ASSET_CODE
    assert trade.quantity == Decimal("200.000000")
    assert trade.execution_date == TRADE_DATE
    assert trade.idempotency_key == f"auto:{invocation.invocation_id.hex}:1:buy"
    assert trade.fee_amounts_known is True
    assert trade.cost_basis_known is True
    assert trade.settlement_plan_binding_version == 3
    assert trade.settlement_status == "pending"
    assert trade.settlement_market_session == TRADE_DATE
    assert trade.settlement_lag_sessions == 1
    assert trade.settlement_release_date == date(2026, 10, 19)

    position = PositionModel._default_manager.get(account_id=account_id, asset_code=ASSET_CODE)
    assert position.quantity == Decimal("200.000000")
    assert position.available_quantity_known is True
    assert position.available_quantity == Decimal("0.000000")

    binding = SimulatedSettlementPlanBindingV3.from_payload(trade.settlement_plan_binding_payload)
    source_evidence = binding.identity_evidence.source_evidence
    assert binding.identity_evidence.selection.purpose == "normal_simulated_current_reference"
    assert source_evidence.source_observed_at is None
    assert source_evidence.source_available_at is None
    assert source_evidence.must_not_use_for_decision is True
    assert source_evidence.must_not_execute is True


@pytest.mark.parametrize("caller", ["legacy", "strategy"])
def test_auto_caller_sell_account_write_failure_rolls_back_real_uow(
    monkeypatch: pytest.MonkeyPatch,
    qualified_caller_context: _QualifiedCallerContext,
    caller: str,
) -> None:
    """Fail the actual account-row write and retain the whole prior SELL ledger."""

    account = qualified_caller_context.account
    account_id = account.pk
    assert type(account_id) is int
    account.current_market_value = Decimal("100000.00")
    account.total_value = Decimal("200000.00")
    account.save(update_fields=("current_market_value", "total_value"))
    position = _persist_sell_position(account)

    strategy_id = 91 if caller == "strategy" else None
    _build_real_auto_caller(
        monkeypatch,
        include_buy_candidate=False,
        strategy_id=strategy_id,
        legacy_exit=caller == "legacy",
    )
    invocation_key = f"ash03-auto-qualified-sell-{caller}"
    attempted_account_writes: list[int] = []
    failure_injected = False
    original_save_base = cast(Callable[..., None], models.Model.save_base)

    def fail_target_account_save(
        instance: Model,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Raise at the true account ORM write after the UoW starts its transaction."""

        nonlocal failure_injected
        if isinstance(instance, SimulatedAccountModel) and instance.pk == account_id:
            if not failure_injected:
                attempted_account_writes.append(account_id)
                failure_injected = True
                raise DatabaseError("injected automatic SELL account-row failure")
        original_save_base(instance, *args, **kwargs)

    monkeypatch.setattr(Model, "save_base", fail_target_account_save)
    before_trade_count = SimulatedTradeModel._default_manager.filter(account_id=account_id).count()

    outcome = interface_services.run_auto_trading_for_scope(
        trade_date=TRADE_DATE,
        account_ids=(account_id,),
        invocation_key=invocation_key,
    )

    account_outcome = outcome.accounts[0]
    assert attempted_account_writes == [account_id]
    assert account_outcome.sell_count == 0
    assert account_outcome.confirmed_trade_count == 0
    assert SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == (
        before_trade_count
    )
    assert not SimulatedTradeModel._default_manager.filter(
        account_id=account_id,
        asset_code=ASSET_CODE,
        action="sell",
    ).exists()

    position.refresh_from_db()
    assert position.quantity == Decimal("1000.000000")
    assert position.available_quantity == Decimal("1000.000000")
    assert position.total_cost == Decimal("90000.00")
    assert position.market_value == Decimal("100000.00")
    account.refresh_from_db()
    assert account.current_cash == Decimal("100000.00")
    assert account.current_market_value == Decimal("100000.00")
    assert account.total_value == Decimal("200000.00")

    invocation = AutomaticTradingInvocationModel._default_manager.get(
        namespace="internal:simulated-auto",
        invocation_key=invocation_key,
    )
    assert invocation.state == AutomaticTradingInvocationModel.STATE_FINISHED
    assert invocation.account_ids == [account_id]
