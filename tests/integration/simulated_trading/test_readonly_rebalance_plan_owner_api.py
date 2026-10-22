"""Real owner-route coverage for the read-only daily rebalance preview."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS
from django.db.models import Model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.application.market_price_contracts import MarketPriceResult, PriceFreshness
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.risk_center.application.execution_settlement_v3 import ExecutionSettlementV3Unavailable
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
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    ExecutionCurrentReferenceSelectorItemV2,
    ExecutionCurrentReferenceSelectorV2,
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    AccountPositionValuationSnapshotModel,
    DailyInspectionReportModel,
    RebalanceProposalModel,
    UnifiedAccountCashFlowModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel

# These route/resource tests use one synchronous Django connection and do not
# assert cross-connection visibility of committed data. Rollback-backed TestCase
# isolation also avoids TRUNCATE against the migration-owned authority clock.
pytestmark = pytest.mark.django_db

ASSET_SELL = "600000.SH"
ASSET_BUY = "000001.SZ"
PRICE = 5.0
PRICE_SOURCE = "fixture:current-market-price"


class _FixturePriceReader:
    """Provide exact, typed market observations for one isolated API scenario."""

    def __init__(
        self,
        *,
        missing_codes: frozenset[str],
        observed_at: datetime,
        price_results: dict[str, MarketPriceResult | None] | None = None,
    ) -> None:
        self.missing_codes = missing_codes
        self.observed_at = observed_at
        self.price_results = dict(price_results or {})
        self.calls: list[tuple[str, date | None]] = []

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceResult | None:
        self.calls.append((asset_code, trade_date))
        if asset_code in self.missing_codes:
            return None
        if asset_code in self.price_results:
            return self.price_results[asset_code]
        return MarketPriceResult(
            normalized_code=asset_code,
            price=PRICE,
            as_of=trade_date,
            source=PRICE_SOURCE,
            freshness="realtime",
            is_fallback=False,
            observed_at=self.observed_at,
        )

    def clear_cache(self) -> None:
        """Satisfy the provider protocol without maintaining a cache."""


def _fixture_price_result(
    *,
    asset_code: str,
    freshness: PriceFreshness,
    as_of: date | None,
    source: str,
    is_fallback: bool,
    observed_at: datetime | None,
    price: float = PRICE,
) -> MarketPriceResult:
    """Construct one valid, explicit quote receipt for a price-boundary case."""

    return MarketPriceResult(
        normalized_code=asset_code,
        price=price,
        as_of=as_of,
        source=source,
        freshness=freshness,
        is_fallback=is_fallback,
        observed_at=observed_at,
    )


class _FixtureIdentityReader:
    """Return current-purpose V2 receipts while preserving restrictive V1 flags."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime]] = []
        self._evidence: dict[tuple[str, datetime], ExecutionInstrumentIdentityEvidenceV2] = {}

    def resolve_current_reference_identity(
        self,
        *,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2:
        self.calls.append((asset_code, as_of))
        cache_key = (asset_code, as_of)
        if cache_key in self._evidence:
            return self._evidence[cache_key]
        market = "SH" if asset_code.endswith(".SH") else "SZ"
        source_exchange = "SSE" if market == "SH" else "SZSE"
        profile_activated_at = as_of - timedelta(hours=4)
        runtime_generated_at = as_of - timedelta(hours=3)
        reference_completed_at = as_of - timedelta(hours=1)
        mapping_recorded_at = as_of - timedelta(minutes=30)
        snapshot_recorded_at = as_of - timedelta(minutes=20)
        window_end = reference_completed_at + timedelta(hours=2)
        source = ExecutionInstrumentIdentityEvidenceV1(
            security_id=f"fixture:{market}:{asset_code}",
            asset_code=asset_code,
            source_code=asset_code.split(".", maxsplit=1)[0],
            source_exchange=source_exchange,
            source_market=market,
            rule_market=market,
            board="MAIN",
            snapshot_id=uuid4(),
            snapshot_content_hash="sha256:" + "1" * 64,
            snapshot_record_digest="sha256:" + "2" * 64,
            first_seen_at=reference_completed_at,
            snapshot_recorded_at=snapshot_recorded_at,
            mapping_record_id=uuid4(),
            mapping_id=f"fixture-market-map-{market.lower()}",
            mapping_version="1",
            mapping_content_hash="sha256:" + "3" * 64,
            mapping_record_digest="sha256:" + "4" * 64,
            mapping_recorded_at=mapping_recorded_at,
            response_completed_at=reference_completed_at,
            source_observed_at=None,
            source_available_at=None,
            identity_valid_from=snapshot_recorded_at,
            identity_valid_until=window_end,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        security_id = f"fixture:{market}:{asset_code}"
        selector = _fixture_classification_selector(
            security_id=security_id,
            asset_code=asset_code,
            source=source,
            simulated_asset_type="equity",
        )
        selection = CurrentReferenceSelectionV1(
            purpose="normal_simulated_current_reference",
            profile_id=f"fixture-profile-{market.lower()}",
            profile_key="simulated-current-reference.v1",
            environment="test",
            profile_version=1,
            profile_content_hash="a" * 64,
            runtime_snapshot_id=f"fixture-runtime-{market.lower()}",
            runtime_snapshot_hash="b" * 64,
            selector_content_hash=selector.content_hash,
            profile_activated_at=profile_activated_at,
            runtime_snapshot_generated_at=runtime_generated_at,
            selected_at=as_of,
            max_local_reference_age_seconds=7200,
        )
        evidence = ExecutionInstrumentIdentityEvidenceV2(
            source_evidence=source,
            selection=selection,
            source_occurrence_id=uuid4(),
            reference_response_completed_at=reference_completed_at,
        )
        self._evidence[cache_key] = evidence
        return evidence


def _fixture_classification_selector(
    *,
    security_id: str,
    asset_code: str,
    source: ExecutionInstrumentIdentityEvidenceV1,
    simulated_asset_type: str,
) -> ExecutionCurrentReferenceSelectorV2:
    """Bind an explicit local type to every pin in the fixture's V2 identity."""

    item = ExecutionCurrentReferenceSelectorItemV2(
        security_id=security_id,
        asset_code=asset_code,
        source_code=source.source_code,
        snapshot_id=source.snapshot_id,
        snapshot_content_hash=source.snapshot_content_hash,
        snapshot_record_digest=source.snapshot_record_digest,
        mapping_record_id=source.mapping_record_id,
        mapping_id=source.mapping_id,
        mapping_version=source.mapping_version,
        mapping_content_hash=source.mapping_content_hash,
        mapping_record_digest=source.mapping_record_digest,
        simulated_asset_type=simulated_asset_type,
    )
    return ExecutionCurrentReferenceSelectorV2(
        purpose="normal_simulated_current_reference",
        max_local_reference_age_seconds=7200,
        items=(item,),
    )


class _FixtureClassificationReader:
    """Return only an explicitly configured type bound to the exact cached identity."""

    def __init__(
        self,
        *,
        identity_reader: _FixtureIdentityReader,
        asset_types: dict[str, str],
        missing_codes: frozenset[str],
    ) -> None:
        self.identity_reader = identity_reader
        self.asset_types = dict(asset_types)
        self.missing_codes = missing_codes
        self.calls: list[tuple[str, str, datetime]] = []

    def resolve_simulated_instrument_classification(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
        self.calls.append((security_id, asset_code, as_of))
        asset_type = self.asset_types.get(asset_code)
        if asset_code in self.missing_codes or asset_type is None:
            return None
        identity = self.identity_reader.resolve_current_reference_identity(
            asset_code=asset_code,
            as_of=as_of,
        )
        if identity.security_id != security_id:
            return None
        selector = _fixture_classification_selector(
            security_id=security_id,
            asset_code=asset_code,
            source=identity.source_evidence,
            simulated_asset_type=asset_type,
        )
        if identity.selection.selector_content_hash != selector.content_hash:
            return None
        return SimulatedInstrumentClassificationEvidenceV1(
            selector=selector,
            identity_evidence=identity,
            read_at=as_of,
        )


class _FixtureFeePolicyReader:
    """Return only a sealed FeeV2 policy with an exact market/board/side case."""

    def __init__(
        self,
        *,
        policy: SimulatedFeePolicyV2 | None,
        account_id: int,
        user_id: int,
    ) -> None:
        self.policy = policy
        self.account_id = account_id
        self.user_id = user_id
        self.calls: list[tuple[str, str, str, SimulatedTradeSide]] = []

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
        assert account_id == self.account_id
        assert user_id == self.user_id
        self.calls.append((asset_type, market, board, side))
        return self.policy


class _FixtureQuantityRuleReader:
    """Return complete Risk-owned V3 bundles with explicit A-share lot terms."""

    def __init__(self, *, missing_asset_codes: frozenset[str] = frozenset()) -> None:
        self.missing_asset_codes = missing_asset_codes
        self.calls: list[tuple[str, datetime]] = []

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        self.calls.append((security_id, as_of))
        asset_code = security_id.rsplit(":", maxsplit=1)[-1]
        if asset_code in self.missing_asset_codes:
            raise ExecutionSettlementV3Unavailable("fixture has no effective quantity rule")
        return _execution_rule_bundle(security_id=security_id, as_of=as_of)


class _FixtureReservationRuleReader:
    """Return the exact source-backed bundle used to establish one real hold."""

    def __init__(self, bundle: ExecutionSettlementBundleV3) -> None:
        self.bundle = bundle

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        rule = self.bundle.execution_submission_v2.execution_rule_v1
        assert security_id == rule.security_id
        assert self.bundle.source_available_at <= as_of < self.bundle.valid_until
        return self.bundle


class _FixtureReservationIdentityReader:
    """Bind a reservation intent to the exact market encoded by its fixture security."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Return complete typed identity evidence for one explicit A-share fixture."""

        market = asset_code.rsplit(".", maxsplit=1)[-1]
        assert market in {"SH", "SZ"}
        assert security_id == f"fixture:{market}:{asset_code}"
        response_completed_at = as_of - timedelta(hours=2)
        return ExecutionInstrumentIdentityEvidenceV1(
            security_id=security_id,
            asset_code=asset_code,
            source_code=asset_code.split(".", maxsplit=1)[0],
            source_exchange=market,
            source_market=market,
            rule_market=market,
            board="MAIN",
            snapshot_id=uuid4(),
            snapshot_content_hash="sha256:" + "1" * 64,
            snapshot_record_digest="sha256:" + "2" * 64,
            first_seen_at=response_completed_at,
            snapshot_recorded_at=as_of - timedelta(hours=1),
            mapping_record_id=uuid4(),
            mapping_id=f"m1-reservation-market-map-{market.lower()}",
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


class _FixtureReservationCalendarReader:
    """Return a validated publication-bound calendar for the reservation market."""

    def __init__(self, evidence: ExecutionCalendarEvidence) -> None:
        self.evidence = evidence

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence:
        """Require the requested market and validate the exact calendar cutoff."""

        del coverage_start
        assert exchange == self.evidence.snapshot.exchange
        self.evidence.validate_for(as_of)
        return self.evidence


def _install_preview_ports(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: SimulatedAccountModel,
    user_id: int,
    missing_prices: frozenset[str] = frozenset(),
    fee_policy_available: bool = True,
    missing_quantity_rule_codes: frozenset[str] = frozenset(),
    classification_asset_types: dict[str, str] | None = None,
    missing_classification_codes: frozenset[str] = frozenset(),
    price_results: dict[str, MarketPriceResult | None] | None = None,
    fee_min_commission: Decimal = Decimal("1.00"),
) -> tuple[
    _FixturePriceReader,
    _FixtureIdentityReader,
    _FixtureFeePolicyReader,
    _FixtureQuantityRuleReader,
]:
    """Replace only the preview's typed market, identity, fee and Risk readers."""

    from apps.simulated_trading.application.rebalance_plan_preview import (
        ReadOnlyRebalancePlanPreviewBuilder,
    )
    from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
        DjangoRebalanceResourceSnapshotRepository,
    )
    from apps.strategy.application.execution_gateway import get_strategy_execution_gateway

    observed_at = timezone.now().astimezone(UTC) - timedelta(minutes=5)
    price_reader = _FixturePriceReader(
        missing_codes=missing_prices,
        observed_at=observed_at,
        price_results=price_results,
    )
    identity_reader = _FixtureIdentityReader()
    policy = (
        _fee_policy(as_of=timezone.now(), min_commission=fee_min_commission)
        if fee_policy_available
        else None
    )
    fee_reader = _FixtureFeePolicyReader(
        policy=policy,
        account_id=account.pk,
        user_id=user_id,
    )
    quantity_rule_reader = _FixtureQuantityRuleReader(
        missing_asset_codes=missing_quantity_rule_codes
    )
    classification_reader = _FixtureClassificationReader(
        identity_reader=identity_reader,
        asset_types=classification_asset_types or {},
        missing_codes=missing_classification_codes,
    )
    builder = ReadOnlyRebalancePlanPreviewBuilder(
        price_reader=price_reader,
        identity_reader=identity_reader,
        classification_reader=classification_reader,
        fee_policy_reader=fee_reader,
        quantity_rule_reader=quantity_rule_reader,
        resource_snapshot_reader=DjangoRebalanceResourceSnapshotRepository(using=DEFAULT_DB_ALIAS),
        position_rule_evaluator=get_strategy_execution_gateway(),
    )

    def factory() -> ReadOnlyRebalancePlanPreviewBuilder:
        return builder

    factory_name = "build_readonly_rebalance_plan_preview_builder"
    for module_name in (
        "apps.simulated_trading.rebalance_plan_preview_composition",
        "apps.simulated_trading.application.interface_services",
        "apps.simulated_trading.application.daily_inspection_service",
    ):
        module = import_module(module_name)
        if hasattr(module, factory_name):
            monkeypatch.setattr(module, factory_name, factory)
    return price_reader, identity_reader, fee_reader, quantity_rule_reader


def _execution_rule_bundle(
    *,
    security_id: str,
    as_of: datetime,
    buy_minimum: Decimal = Decimal("100"),
    buy_step: Decimal = Decimal("100"),
    sell_minimum: Decimal = Decimal("100"),
    sell_step: Decimal = Decimal("100"),
    sell_odd_lot_mode: SellOddLotMode = SellOddLotMode.SELLABLE_BALANCE_TO_ZERO,
) -> ExecutionSettlementBundleV3:
    """Build an exact V3 bundle with source clocks and explicit share constraints."""

    market = security_id.split(":", maxsplit=2)[1]
    source_observed_at = as_of - timedelta(days=1)
    source_available_at = as_of - timedelta(hours=1)
    effective_from = as_of - timedelta(days=1)
    valid_until = as_of + timedelta(days=30)
    base = AShareExecutionRule(
        rule_id=f"fixture-{market.lower()}-execution-rule",
        rule_version="2026-10-fixture",
        security_id=security_id,
        market=market,
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=buy_minimum,
            step=buy_step,
            maximum=Decimal("100000"),
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=sell_minimum,
            step=sell_step,
            maximum=Decimal("100000"),
        ),
        sell_odd_lot_mode=sell_odd_lot_mode,
        price_tick=Decimal("0.01"),
        rule_source_id=f"fixture-{market.lower()}-exchange-source",
        rule_source_version="2026-10-fixture",
        rule_source_hash="a" * 64,
        source_observed_at=source_observed_at,
        source_available_at=source_available_at,
        effective_from=effective_from,
        valid_until=valid_until,
    )
    submission = ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
        price_submission_range=PriceSubmissionRangeRule(
            market=market,
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
    settlement = SettlementPolicyV1(
        policy_id=f"fixture-{market.lower()}-settlement-policy",
        policy_version="2026-10-fixture",
        security_id=security_id,
        market=market,
        board="MAIN",
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=submission.content_hash,
        source_id=f"fixture-{market.lower()}-settlement-source",
        source_version="2026-10-fixture",
        source_hash="b" * 64,
        source_observed_at=source_observed_at,
        source_available_at=source_available_at,
        effective_from=effective_from,
        valid_until=valid_until,
    )
    return ExecutionSettlementBundleV3(
        bundle_id=f"fixture-{market.lower()}-execution-settlement",
        bundle_version="2026-10-fixture",
        execution_submission_v2=submission,
        settlement_policy_v1=settlement,
    )


def _create_active_order_reservation(
    *,
    account: SimulatedAccountModel,
    user_id: int,
    side: SimulatedTradeSide,
    quantity: Decimal,
    price: Decimal,
    min_commission: Decimal,
    fee_budget: Decimal | None,
    asset_code: str = ASSET_SELL,
) -> SimulatedOrderReservationModel:
    """Create a valid active hold through the production reservation use case."""

    from tests.component.simulated_trading.test_execution_settlement_uow import (
        _calendar as reservation_calendar,
    )
    from tests.component.simulated_trading.test_execution_settlement_uow import (
        _Clock as ReservationClock,
    )

    now = timezone.now().astimezone(UTC)
    local_today = timezone.localdate(now)
    market = asset_code.rsplit(".", maxsplit=1)[-1]
    calendar_start = local_today - timedelta(days=10)
    calendar_end = local_today + timedelta(days=30)
    open_dates = {
        calendar_start + timedelta(days=offset)
        for offset in range((calendar_end - calendar_start).days + 1)
        if (calendar_start + timedelta(days=offset)).weekday() < 5
    }
    calendar = reservation_calendar(
        as_of=now,
        open_dates=open_dates,
        exchange=market,
        start=calendar_start,
        end=calendar_end,
    )
    assert type(account.pk) is int
    account_id = account.pk
    fee_policy_reader = _FixtureFeePolicyReader(
        policy=_fee_policy(as_of=now, min_commission=min_commission),
        account_id=account_id,
        user_id=user_id,
    )
    security_id = f"fixture:{market}:{asset_code}"
    bundle = _execution_rule_bundle(security_id=security_id, as_of=now)
    execution_repository = DjangoSimulatedTradeExecutionRepository(using=DEFAULT_DB_ALIAS)
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_FixtureReservationRuleReader(bundle),
        identity_reader=_FixtureReservationIdentityReader(),
        calendar_reader=_FixtureReservationCalendarReader(calendar),
        fee_policy_reader=fee_policy_reader,
        repository=execution_repository,
        clock=ReservationClock(now),
    )
    reservation_repository = DjangoSimulatedOrderReservationRepository(using=DEFAULT_DB_ALIAS)
    reserve = ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=reservation_repository,
        clock=ReservationClock(now),
    )
    intent = SimulatedTradeIntent(
        account_id=account_id,
        user_id=user_id,
        idempotency_key=f"m1-reservation-{uuid4().hex}",
        side=side,
        security_id=security_id,
        asset_code=asset_code,
        asset_name="Reservation fixture security",
        asset_type="equity",
        market=market,
        board="MAIN",
        quantity=quantity,
        price=price,
        reason="owner-route read-only preview fixture",
        signal_id=None,
    )
    reserve.execute(intent, fee_budget=fee_budget, as_of=now)
    return SimulatedOrderReservationModel.objects.get(
        account_id=account.pk,
        idempotency_key=intent.idempotency_key,
    )


def _fee_policy(
    *, as_of: datetime, min_commission: Decimal = Decimal("1.00")
) -> SimulatedFeePolicyV2:
    """Build a sealed fixture policy whose applicability is explicit for each row."""

    recorded_at = as_of - timedelta(days=1)
    schedule = ExecutionFeeSchedule(
        config_id=17,
        asset_type="equity",
        commission_rate_buy=Decimal.from_float(0.0003),
        commission_rate_sell=Decimal.from_float(0.0003),
        min_commission=min_commission,
        stamp_duty_rate=Decimal.from_float(0.001),
        transfer_fee_rate=Decimal.from_float(0.00002),
        min_transfer_fee=Decimal("0.00"),
        slippage_rate=Decimal.from_float(0.001),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market=market,
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=(
                FeeApplicability.APPLIES
                if side is SimulatedTradeSide.SELL
                else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=FeeApplicability.APPLIES,
        )
        for market in ("SH", "SZ")
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="m1-read-only-preview-fixture",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=recorded_at,
        valid_until=as_of + timedelta(days=30),
        recorded_at=recorded_at,
        transaction_cases=cases,
    )


def _create_owner_account(
    *,
    username: str,
    positions: tuple[tuple[str, str, bool], ...],
    cash: Decimal = Decimal("100000.00"),
    position_quantity: Decimal = Decimal("10000.000000"),
    position_price: Decimal = Decimal("5.0000"),
    position_quantities: dict[str, Decimal] | None = None,
    cost_basis_known: bool = True,
    max_position_pct: float = 20.0,
    max_total_position_pct: float = 95.0,
    stop_loss_pct: float | None = None,
) -> tuple[Any, SimulatedAccountModel]:
    """Create a valid simulated ledger, explicit owner profile and fixture holdings."""

    user = get_user_model().objects.create_user(
        username=f"{username}-{uuid4().hex[:8]}",
        password="unused",
    )
    AccountProfileModel.objects.get(user=user)
    market_value = Decimal("0.00")
    holding_rows: list[tuple[str, str, bool, Decimal, Decimal]] = []
    for asset_code, asset_name, available_known in positions:
        quantity = (position_quantities or {}).get(asset_code, position_quantity)
        value = (quantity * position_price).quantize(Decimal("0.01"))
        market_value += value
        holding_rows.append((asset_code, asset_name, available_known, quantity, value))
    total_value = cash + market_value
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"{username} account",
        account_type="simulated",
        initial_capital=total_value,
        current_cash=cash,
        current_market_value=market_value,
        total_value=total_value,
        is_active=True,
        max_position_pct=max_position_pct,
        max_total_position_pct=max_total_position_pct,
        stop_loss_pct=stop_loss_pct,
    )
    UnifiedAccountCashFlowModel.objects.create(
        account=account,
        flow_type="initial_capital",
        amount=total_value,
        flow_date=timezone.localdate(),
        source_app="simulated_trading",
        source_id=f"m1-fixture-{account.pk}",
        notes="Test-only owner-route preview fixture",
    )
    for asset_code, asset_name, available_known, quantity, value in holding_rows:
        total_cost = (quantity * Decimal("4.0000")).quantize(Decimal("0.01"))
        unrealized_pnl = value - total_cost
        position = PositionModel.objects.create(
            account=account,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type="equity",
            quantity=quantity,
            available_quantity=quantity,
            available_quantity_known=available_known,
            avg_cost=Decimal("4.0000"),
            total_cost=total_cost,
            cost_basis_known=cost_basis_known,
            current_price=position_price,
            market_value=value,
            valuation_known=True,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=(
                float(unrealized_pnl / total_cost * Decimal("100")) if total_cost > 0 else 0.0
            ),
            first_buy_date=timezone.localdate() - timedelta(days=10),
            first_buy_date_known=True,
        )
        AccountPositionValuationSnapshotModel.objects.create(
            account=account,
            record_date=timezone.localdate(),
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type="equity",
            quantity=quantity,
            avg_cost=Decimal("4.0000"),
            close_price=position_price,
            market_value=value,
            weight=float(value / total_value) if total_value else 0.0,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=(
                float(unrealized_pnl / total_cost * Decimal("100")) if total_cost > 0 else 0.0
            ),
        )
        assert position.account_id == account.pk
    return user, account


def _create_strategy(
    *,
    user: Any,
    target_weights: dict[str, object],
    max_position_pct: float = 20.0,
    max_total_position_pct: float = 95.0,
    stop_loss_pct: float | None = None,
    buy_condition_expr: str = "current_price > 0",
    sell_condition_expr: str = "current_price > 0",
) -> StrategyModel:
    """Persist an active strategy and the actual rule metadata read by inspection."""

    strategy = StrategyModel.objects.create(
        name=f"M1 preview strategy {uuid4().hex[:8]}",
        description="Test-only explicit asset targets",
        strategy_type="rule_based",
        created_by=AccountProfileModel.objects.get(user=user),
        is_active=True,
        max_position_pct=max_position_pct,
        max_total_position_pct=max_total_position_pct,
        stop_loss_pct=stop_loss_pct,
    )
    PositionManagementRuleModel.objects.create(
        strategy=strategy,
        name="M1 preview position rule",
        buy_condition_expr=buy_condition_expr,
        sell_condition_expr=sell_condition_expr,
        buy_price_expr="current_price",
        sell_price_expr="current_price",
        stop_loss_expr="current_price * 0.9",
        take_profit_expr="current_price * 1.1",
        position_size_expr="0",
        metadata={
            "rebalance": {
                "target_weights": target_weights,
                "drift_threshold": 0.01,
            }
        },
    )
    return strategy


def _post_inspection(
    *,
    client: APIClient,
    account_id: int,
    strategy_id: int,
) -> Any:
    """Invoke the real owner-scoped account inspection endpoint."""

    return client.post(
        f"/api/account/accounts/{account_id}/inspections/run/",
        {
            "strategy_id": strategy_id,
            "inspection_date": timezone.localdate().isoformat(),
            "auto_create_proposal": False,
        },
        format="json",
    )


def _table_snapshot(model: type[Model]) -> tuple[tuple[object, ...], ...]:
    """Capture every persisted field in deterministic primary-key order."""

    columns = tuple(field.attname for field in model._meta.concrete_fields)
    return tuple(tuple(row) for row in model._base_manager.order_by("pk").values_list(*columns))


def _financial_snapshot() -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Capture financial ledgers plus immutable reservation and fill evidence."""

    return tuple(
        _table_snapshot(model)
        for model in (
            SimulatedAccountModel,
            PositionModel,
            SimulatedTradeModel,
            UnifiedAccountCashFlowModel,
            AccountPositionValuationSnapshotModel,
            SimulatedOrderReservationModel,
            SimulatedOrderFillReceiptModel,
        )
    )


def _assert_no_financial_writes(
    *,
    before: tuple[tuple[tuple[object, ...], ...], ...],
    account: SimulatedAccountModel,
    report_count_before: int,
    proposal_count_before: int,
) -> None:
    """Keep plan output separate from expected inspection audit persistence."""

    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before + 1
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )


def test_owner_route_returns_actionable_sell_and_buy_without_financial_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real inspection request may preview known FeeV2-backed actions only."""

    user, account = _create_owner_account(
        username="m1-positive",
        positions=(
            (ASSET_SELL, "Fixture held asset to liquidate", True),
            (ASSET_BUY, "Fixture held asset to increase", True),
        ),
        max_position_pct=50.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.0, ASSET_BUY: 0.4033},
        max_position_pct=50.0,
    )
    prices, identities, fees, quantity_rules = _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    report = response.json()["reports"][0]
    plan = report["plan"]
    assert plan["plan_kind"] == "rebalance_preview"
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    assert plan["sell_before_buy"]["required"] is True
    assert plan["sell_before_buy"]["sequence"] == "sell_then_buy"
    assert plan["sell_before_buy"]["sell_asset_codes"] == [ASSET_SELL]
    assert plan["sell_before_buy"]["buy_asset_codes"] == [ASSET_BUY]
    assert plan["funding_status"] == "conditional"
    assert Decimal(plan["projected_cash_after_sells"]) == (
        Decimal(plan["cash_before"]) + Decimal(plan["estimated_sell_net"])
    )
    assert Decimal(plan["estimated_buy_total"]) > 0
    for allocation in plan["allocation_items"]:
        assert allocation["currency_unit"] is None
        assert allocation["current_quantity"] is None
        assert allocation["target_quantity"] is None
        assert allocation["suggested_quantity"] is None
        assert allocation["actionable_quantity"] is None
        assert allocation["sellable_quantity"] is None
    rows = {row["asset_code"]: row for row in plan["asset_items"]}
    assert set(rows) == {ASSET_SELL, ASSET_BUY}

    sell = rows[ASSET_SELL]
    buy = rows[ASSET_BUY]
    assert sell["action"] == "sell"
    assert Decimal(sell["target_weight"]) == Decimal("0")
    assert Decimal(sell["target_quantity"]) == Decimal("0")
    assert Decimal(sell["actionable_quantity"]) > 0
    assert Decimal(sell["sellable_quantity"]) == Decimal("10000.000000")
    assert Decimal(sell["actionable_quantity"]) % Decimal("100") == 0
    assert buy["action"] == "buy"
    assert buy["status"] == "conditional"
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in buy["reason_codes"]
    assert Decimal(buy["suggested_quantity"]) > 0
    assert buy["quantity_rule"]["buy"]["step"] == "100"
    assert buy["actionable_quantity"] is None
    assert buy["actionable_amount"] is None
    assert Decimal(buy["remaining_quantity"]) == Decimal(buy["suggested_quantity"])
    assert sell["status"] == "ready"
    assert all(row["quantity_unit"] == "shares" for row in (sell, buy))

    for row in (sell, buy):
        assert row["price_source"] == PRICE_SOURCE
        assert row["price_freshness"] == "realtime"
        assert row["price_as_of"] is None
        assert row["price_observed_at"] == prices.observed_at.isoformat()
        assert row["price_observed_at"] != plan["as_of"]
        assert row["identity"]["purpose"] == "normal_simulated_current_reference"
        assert row["identity"]["must_not_use_for_decision"] is True
        assert row["identity"]["must_not_execute"] is True
        assert row["identity"]["source_observed_at"] is None
        assert row["identity"]["source_available_at"] is None
        assert row["fee"]["policy_id"] == "m1-read-only-preview-fixture"
        assert row["fee"]["content_hash"]
        assert row["fee"]["transaction_case"]["asset_type"] == "equity"
        assert row["fee"]["transaction_case"]["market"] in {"SH", "SZ"}
        assert row["fee"]["transaction_case"]["board"] == "MAIN"
        assert row["fee"]["transaction_case"]["side"] == row["action"]
        assert Decimal(row["fee"]["total"]) >= 0
        assert row["quantity_rule"]["rule_id"].startswith("fixture-")
        assert row["quantity_rule"]["buy"]["minimum"] == "100"
        assert row["quantity_rule"]["buy"]["step"] == "100"
        assert row["quantity_rule"]["buy"]["maximum"] == "100000"
        assert row["quantity_rule"]["sell_odd_lot_mode"] == "SELLABLE_BALANCE_TO_ZERO"
    assert identities.calls
    assert fees.calls
    assert quantity_rules.calls
    assert all(trade_date is None for _, trade_date in prices.calls)

    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_account_position_cap_blocks_buy_even_when_strategy_cap_allows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account's 20% ceiling remains independent from a 100% Strategy cap."""

    user, account = _create_owner_account(
        username="m1-account-cap",
        positions=((ASSET_BUY, "Account-capped holding", True),),
        max_position_pct=20.0,
        max_total_position_pct=100.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.4},
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["action"] == "buy"
    assert row["status"] == "blocked"
    assert "ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED" in row["reason_codes"]
    assert "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED" not in row["reason_codes"]
    assert row["actionable_quantity"] is None
    assert Decimal(plan["risk_context"]["account_max_position_pct"]) == Decimal("20")
    assert Decimal(plan["risk_context"]["strategy_max_position_pct"]) == Decimal("100")
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_mixed_plan_withholds_buy_until_sell_reduces_total_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cash-funded BUY stays conditional when the held SELL must occur first."""

    user, account = _create_owner_account(
        username="m1-total-cap-sequence",
        positions=(
            (ASSET_SELL, "Ninety-percent position", True),
            (ASSET_BUY, "Existing one-percent position", True),
        ),
        cash=Decimal("10000.00"),
        position_price=Decimal("5.0000"),
        position_quantities={
            ASSET_SELL: Decimal("17800.000000"),
            ASSET_BUY: Decimal("200.000000"),
        },
        max_position_pct=100.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.69, ASSET_BUY: 0.09},
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    rows = {item["asset_code"]: item for item in plan["asset_items"]}
    sell = rows[ASSET_SELL]
    buy = rows[ASSET_BUY]
    assert Decimal(plan["portfolio_value"]) == Decimal("100000.00")
    assert Decimal(plan["cash_before"]) == Decimal("10000.00")
    assert Decimal(plan["available_cash_before"]) == Decimal("10000.00")
    assert Decimal(plan["risk_context"]["account_max_total_position_pct"]) == Decimal("95")
    assert Decimal(sell["current_weight"]) == Decimal("0.89")
    assert Decimal(sell["target_weight"]) == Decimal("0.69")
    assert Decimal(buy["current_weight"]) == Decimal("0.01")
    assert Decimal(buy["target_weight"]) == Decimal("0.09")
    assert plan["sell_before_buy"]["required"] is True
    assert plan["sell_before_buy"]["sequence"] == "sell_then_buy"
    assert sell["status"] == "ready"
    assert Decimal(sell["actionable_quantity"]) == Decimal("4000.000000")
    assert buy["status"] == "conditional"
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in buy["reason_codes"]
    assert Decimal(buy["suggested_quantity"]) > 0
    assert buy["actionable_quantity"] is None
    assert buy["actionable_amount"] is None
    assert Decimal(plan["estimated_buy_total"]) <= Decimal(plan["cash_before"])
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_account_stop_loss_remains_distinct_from_strategy_stop_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account stop-loss blocks a BUY without rewriting the Strategy threshold."""

    user, account = _create_owner_account(
        username="m1-account-stop-loss",
        positions=((ASSET_BUY, "Stop-loss holding", True),),
        position_quantity=Decimal("1000"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
        stop_loss_pct=5.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.5},
        max_position_pct=100.0,
        max_total_position_pct=100.0,
        stop_loss_pct=20.0,
    )
    loss_quote = _fixture_price_result(
        asset_code=ASSET_BUY,
        freshness="realtime",
        as_of=None,
        source=PRICE_SOURCE,
        is_fallback=False,
        observed_at=timezone.now().astimezone(UTC) - timedelta(minutes=5),
        price=3.5,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        price_results={ASSET_BUY: loss_quote},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["action"] == "buy"
    assert row["status"] == "blocked"
    assert "ACCOUNT_STOP_LOSS_TRIGGERED" in row["reason_codes"]
    assert "STRATEGY_STOP_LOSS_TRIGGERED" not in row["reason_codes"]
    assert row["actionable_quantity"] is None
    assert Decimal(plan["risk_context"]["account_stop_loss_pct"]) == Decimal("5")
    assert Decimal(plan["risk_context"]["strategy_stop_loss_pct"]) == Decimal("20")
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.parametrize(
    ("missing_prices", "fee_policy_available", "available_known", "expected_reason"),
    [
        (frozenset({ASSET_SELL}), True, True, "QUOTE_UNAVAILABLE"),
        (frozenset(), False, True, "FEE_POLICY_UNAVAILABLE"),
        (frozenset(), True, False, "SELLABLE_QUANTITY_UNKNOWN"),
    ],
    ids=("missing-quote", "missing-fee-v2", "unknown-sellable-quantity"),
)
def test_missing_evidence_blocks_only_unsupported_action_quantities(
    monkeypatch: pytest.MonkeyPatch,
    missing_prices: frozenset[str],
    fee_policy_available: bool,
    available_known: bool,
    expected_reason: str,
) -> None:
    """Unknown price, exact fees or sellability never become numeric permission."""

    user, account = _create_owner_account(
        username="m1-blocked",
        positions=((ASSET_SELL, "Fixture held asset", available_known),),
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.0})
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        missing_prices=missing_prices,
        fee_policy_available=fee_policy_available,
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    assert plan["read_only"] is True
    rows = plan["asset_items"]
    assert rows
    row = next(item for item in rows if item["asset_code"] == ASSET_SELL)
    assert expected_reason in row["reason_codes"]
    if expected_reason == "QUOTE_UNAVAILABLE":
        assert row["action"] == "sell"
        assert row["status"] == "blocked"
    else:
        assert row["action"] == "sell"
    assert row["actionable_quantity"] is None
    assert row["actionable_amount"] is None
    if not available_known:
        assert row["sellable_quantity"] is None
        assert row["suggested_quantity"] is not None

    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.parametrize(
    ("target_weights", "expected_reason"),
    [
        (
            {ASSET_SELL: 0.7, ASSET_BUY: 0.5},
            "TARGET_WEIGHT_SUM_EXCEEDS_ONE",
        ),
        (
            {ASSET_SELL: 0.2, ASSET_SELL.lower(): 0.3},
            "TARGET_DUPLICATE_NORMALIZED_ASSET",
        ),
    ],
    ids=("aggregate-weight-over-one", "normalized-duplicate-asset"),
)
def test_invalid_target_configuration_is_explicitly_blocked(
    monkeypatch: pytest.MonkeyPatch,
    target_weights: dict[str, object],
    expected_reason: str,
) -> None:
    """Overweight or duplicate normalized targets cannot silently select a winner."""

    user, account = _create_owner_account(
        username="m1-invalid-target",
        positions=(
            (ASSET_SELL, "Fixture held asset A", True),
            (ASSET_BUY, "Fixture held asset B", True),
        ),
    )
    strategy = _create_strategy(user=user, target_weights=target_weights)
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    report = response.json()["reports"][0]
    plan = report["plan"]
    config_rows = [
        check for check in report["checks"] if check.get("scope") == "asset_target_configuration"
    ]
    assert config_rows
    assert expected_reason in config_rows[0].get("reason_codes", [])
    assert plan["status"] == "blocked"
    assert expected_reason in plan["reason_codes"]
    assert all(item["actionable_quantity"] is None for item in plan["asset_items"])

    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_zero_holdings_without_explicit_asset_targets_does_not_invent_an_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real empty account and empty asset-target map remain an explicit no-target case."""

    user, account = _create_owner_account(username="m1-empty", positions=())
    strategy = _create_strategy(user=user, target_weights={})
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    assert plan["status"] == "no_explicit_asset_targets"
    assert plan["asset_items"] == []
    assert plan["sell_before_buy"]["sell_asset_codes"] == []
    assert plan["sell_before_buy"]["buy_asset_codes"] == []
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_empty_holdings_with_explicit_classification_can_preview_a_cash_funded_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real empty ledger can size a BUY only with explicit typed V2 classification."""

    user, account = _create_owner_account(
        username="m1-empty-buy-positive",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.1},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={ASSET_BUY: "equity"},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    plan = response.json()["reports"][0]["plan"]
    assert plan["status"] == "ready"
    assert plan["funding_status"] == "known"
    assert plan["sell_before_buy"]["required"] is False
    assert len(plan["asset_items"]) == 1
    row = plan["asset_items"][0]
    assert row["asset_code"] == ASSET_BUY
    assert row["asset_type"] == "equity"
    assert row["action"] == "buy"
    assert row["status"] == "ready"
    assert row["risk_rule_entry_price_basis"] == "prospective_current_quote"
    assert row["classification_evidence"]["simulated_asset_type"] == "equity"
    assert row["classification_evidence"]["must_not_use_for_decision"] is True
    assert row["classification_evidence"]["must_not_execute"] is True
    assert row["identity"]["must_not_use_for_decision"] is True
    assert row["identity"]["must_not_execute"] is True
    assert row["fee"] is not None
    assert row["quantity_rule"] is not None
    assert row["actionable_quantity"] is not None
    assert Decimal(row["actionable_quantity"]) > 0
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_empty_holdings_target_without_classification_blocks_only_that_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untyped target-only asset never inherits a guessed equity classification."""

    user, account = _create_owner_account(
        username="m1-empty-buy-unclassified",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.1},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        missing_classification_codes=frozenset({ASSET_BUY}),
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    row = plan["asset_items"][0]
    assert row["status"] == "blocked"
    assert "ASSET_TYPE_CLASSIFICATION_UNAVAILABLE" in row["reason_codes"]
    assert row["asset_type"] is None
    assert row["classification_evidence"] is None
    assert row["actionable_quantity"] is None
    assert row["fee"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_owner_route_denies_other_users_and_unknown_accounts_without_writes() -> None:
    """The actual account boundary remains in front of inspection and preview work."""

    owner, account = _create_owner_account(
        username="m1-owner-boundary",
        positions=((ASSET_SELL, "Fixture held asset", True),),
    )
    stranger = get_user_model().objects.create_user(
        username=f"m1-stranger-{uuid4().hex[:8]}",
        password="unused",
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=stranger)
    payload = {"inspection_date": timezone.localdate().isoformat()}

    forbidden = client.post(
        f"/api/account/accounts/{account.pk}/inspections/run/",
        payload,
        format="json",
    )
    unknown_id = max(SimulatedAccountModel.objects.values_list("pk", flat=True)) + 1
    not_found = client.post(
        f"/api/account/accounts/{unknown_id}/inspections/run/",
        payload,
        format="json",
    )

    assert forbidden.status_code == 403
    assert not_found.status_code == 404
    assert forbidden["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert not_found["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )
    assert owner.is_authenticated is True


def test_owner_route_invalid_inspection_date_returns_json_400_without_writes() -> None:
    """The API rejects a malformed date with its JSON error contract and no writes."""

    user, account = _create_owner_account(
        username="m1-invalid-date",
        positions=((ASSET_SELL, "Date validation holding", True),),
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.0})
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"/api/account/accounts/{account.pk}/inspections/run/",
        {
            "strategy_id": strategy.pk,
            "inspection_date": "not-a-date",
            "auto_create_proposal": False,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )


def test_zero_target_full_close_keeps_three_share_sell_and_fee_basis_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Money display rounding cannot turn an allowed odd-lot close into a partial sell."""

    user, account = _create_owner_account(
        username="m1-three-share-close",
        positions=((ASSET_SELL, "Three-share fixture holding", True),),
        cash=Decimal("1000000.00"),
        position_quantity=Decimal("3"),
        position_price=Decimal("7.333"),
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.0})
    now = timezone.now().astimezone(UTC)
    quote = _fixture_price_result(
        asset_code=ASSET_SELL,
        freshness="realtime",
        as_of=None,
        source="fixture:current-three-share-close",
        is_fallback=False,
        observed_at=now - timedelta(minutes=5),
        price=7.333,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        price_results={ASSET_SELL: quote},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_SELL)
    assert Decimal(row["drift_threshold"]) == Decimal("0.01")
    assert abs(Decimal(row["current_weight"])) < Decimal(row["drift_threshold"])
    assert row["action"] == "sell"
    assert row["status"] == "ready"
    assert row["quantity_rule"]["sell_odd_lot_mode"] == "SELLABLE_BALANCE_TO_ZERO"
    assert row["quantity_rule"]["sell"]["minimum"] == "100"
    assert row["quantity_rule"]["sell"]["step"] == "100"
    assert Decimal(row["current_quantity"]) == Decimal("3")
    assert Decimal(row["sellable_quantity"]) == Decimal("3")
    assert Decimal(row["target_quantity"]) == Decimal("0.000000")
    assert Decimal(row["suggested_quantity"]) == Decimal("3.000000")
    assert Decimal(row["actionable_quantity"]) == Decimal("3")
    assert Decimal(row["remaining_quantity"]) == Decimal("0")
    assert Decimal(row["actionable_amount"]) == Decimal("22.00")
    assert Decimal(row["fee"]["total"]) == sum(
        Decimal(row["fee"][key]) for key in ("commission", "transfer_fee", "stamp_duty", "slippage")
    )
    assert Decimal(plan["estimated_sell_gross"]) == Decimal("22.00")
    assert Decimal(plan["estimated_sell_fees"]) == Decimal(row["fee"]["total"])
    assert row["price_as_of"] is None
    assert row["price_observed_at"] == quote.observed_at.isoformat()
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_unknown_quantity_rule_blocks_only_its_asset_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One missing Risk rule cannot erase an independent supported SELL row."""

    user, account = _create_owner_account(
        username="m1-one-rule-missing",
        positions=(
            (ASSET_SELL, "Rule-backed sell holding", True),
            (ASSET_BUY, "Holding with missing rule", True),
        ),
        max_position_pct=50.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.0, ASSET_BUY: 0.4033},
        max_position_pct=50.0,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        missing_quantity_rule_codes=frozenset({ASSET_BUY}),
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    rows = {item["asset_code"]: item for item in plan["asset_items"]}
    assert rows[ASSET_SELL]["status"] == "ready"
    assert Decimal(rows[ASSET_SELL]["actionable_quantity"]) > 0
    assert rows[ASSET_BUY]["status"] == "blocked"
    assert "EXECUTION_QUANTITY_RULE_UNAVAILABLE" in rows[ASSET_BUY]["reason_codes"]
    assert rows[ASSET_BUY]["actionable_quantity"] is None
    assert rows[ASSET_BUY]["fee"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_inspection_risk_block_reason_prevents_ready_preview_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upstream risk-evaluation failure remains a blocker in the plan item."""

    user, account = _create_owner_account(
        username="m1-risk-rule-blocked",
        positions=((ASSET_SELL, "Unknown-cost-basis holding", True),),
        cost_basis_known=False,
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.6})
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    report = response.json()["reports"][0]
    row = next(item for item in report["plan"]["asset_items"] if item["asset_code"] == ASSET_SELL)
    assert row["risk_rule_reason_code"]
    assert row["risk_rule_reason_code"] in row["reason_codes"]
    assert row["status"] == "blocked"
    assert row["actionable_quantity"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.parametrize(
    ("quote_kind", "expected_reason"),
    [
        ("historical", "QUOTE_NOT_CURRENT"),
        ("future-realtime-observation", "QUOTE_OBSERVATION_IN_FUTURE"),
        ("stale-close-fallback", "QUOTE_OBSERVATION_STALE"),
    ],
    ids=("historical-price", "future-observation", "stale-close-fallback"),
)
def test_noncurrent_quote_never_supports_actionable_quantity_or_cash(
    monkeypatch: pytest.MonkeyPatch,
    quote_kind: str,
    expected_reason: str,
) -> None:
    """Historical, future and stale facts retain their source times and block sizing."""

    user, account = _create_owner_account(
        username=f"m1-{quote_kind}",
        positions=((ASSET_SELL, "Quote-bound holding", True),),
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.0})
    now = timezone.now().astimezone(UTC)
    if quote_kind == "historical":
        quote = _fixture_price_result(
            asset_code=ASSET_SELL,
            freshness="historical",
            as_of=timezone.localdate() - timedelta(days=2),
            source="fixture:historical-close",
            is_fallback=False,
            observed_at=now - timedelta(days=2),
        )
    elif quote_kind == "future-realtime-observation":
        quote = _fixture_price_result(
            asset_code=ASSET_SELL,
            freshness="realtime",
            as_of=None,
            source="fixture:future-realtime",
            is_fallback=False,
            observed_at=now + timedelta(minutes=5),
        )
    else:
        quote = _fixture_price_result(
            asset_code=ASSET_SELL,
            freshness="close_fallback",
            as_of=timezone.localdate() - timedelta(days=30),
            source="fixture:stale-close",
            is_fallback=True,
            observed_at=None,
        )
        preview_module = import_module(
            "apps.simulated_trading.application.rebalance_preview_valuation"
        )
        monkeypatch.setattr(
            preview_module,
            "latest_daily_market_observation_is_current",
            lambda **kwargs: False,
        )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        price_results={ASSET_SELL: quote},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_SELL)
    assert row["status"] == "blocked"
    assert expected_reason in row["reason_codes"]
    assert row["actionable_quantity"] is None
    assert row["actionable_amount"] is None
    assert plan["projected_cash_after_sells"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_valid_close_fallback_preserves_missing_observed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A date-backed close fallback stays eligible without inventing an observation time."""

    user, account = _create_owner_account(
        username="m1-valid-close-fallback",
        positions=((ASSET_SELL, "Close-fallback holding", True),),
    )
    strategy = _create_strategy(user=user, target_weights={ASSET_SELL: 0.0})
    fallback_date = timezone.localdate() - timedelta(days=1)
    quote = _fixture_price_result(
        asset_code=ASSET_SELL,
        freshness="close_fallback",
        as_of=fallback_date,
        source="fixture:current-close-fallback",
        is_fallback=True,
        observed_at=None,
    )
    preview_module = import_module("apps.simulated_trading.application.rebalance_preview_valuation")
    monkeypatch.setattr(
        preview_module,
        "latest_daily_market_observation_is_current",
        lambda **kwargs: True,
    )
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        price_results={ASSET_SELL: quote},
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    row = response.json()["reports"][0]["plan"]["asset_items"][0]
    assert row["price_freshness"] == "close_fallback"
    assert row["price_is_fallback"] is True
    assert row["price_as_of"] == fallback_date.isoformat()
    assert row["price_observed_at"] is None
    assert row["status"] == "ready"
    assert Decimal(row["actionable_quantity"]) == Decimal("10000")


def test_buy_depending_on_unsettled_sell_proceeds_is_conditional_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Estimated sale proceeds never become present cash or an actionable BUY."""

    user, account = _create_owner_account(
        username="m1-conditional-buy",
        positions=(
            (ASSET_SELL, "Planned sale", True),
            (ASSET_BUY, "Planned purchase", True),
        ),
        cash=Decimal("0.00"),
        position_quantity=Decimal("1000"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.0, ASSET_BUY: 0.8},
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    rows = {item["asset_code"]: item for item in plan["asset_items"]}
    assert Decimal(plan["cash_before"]) == Decimal("0.00")
    assert plan["funding_status"] == "conditional"
    assert Decimal(plan["projected_cash_after_sells"]) > Decimal(plan["cash_before"])
    assert rows[ASSET_SELL]["status"] == "ready"
    assert Decimal(rows[ASSET_SELL]["actionable_quantity"]) == Decimal("1000")
    buy = rows[ASSET_BUY]
    assert buy["action"] == "buy"
    assert buy["status"] == "conditional"
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in buy["reason_codes"]
    assert buy["actionable_quantity"] is None
    assert Decimal(buy["suggested_quantity"]) > 0
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_active_buy_hold_reduces_cash_available_to_owner_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real outstanding BUY hold cannot be spent again by a read-only plan."""

    user, account = _create_owner_account(
        username="m1-active-buy-hold",
        positions=(),
        cash=Decimal("1000.00"),
        max_position_pct=60.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.5},
        max_position_pct=60.0,
        max_total_position_pct=95.0,
    )
    reservation = _create_active_order_reservation(
        account=account,
        user_id=user.pk,
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100"),
        price=Decimal("5.00"),
        min_commission=Decimal("1.00"),
        fee_budget=Decimal("10.00"),
    )
    assert reservation.cash_reserved == Decimal("510.00")
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={ASSET_BUY: "equity"},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    assert Decimal(plan["cash_before"]) == Decimal("1000.00")
    assert Decimal(plan["reserved_cash"]) == reservation.cash_reserved
    assert Decimal(plan["available_cash_before"]) == (
        Decimal("1000.00") - reservation.cash_reserved
    )
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["action"] == "buy"
    assert row["status"] == "blocked"
    assert "CASH_SHORTFALL" in row["reason_codes"]
    assert row["actionable_quantity"] is None
    assert Decimal(row["suggested_quantity"]) > 0
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_active_sell_hold_reduces_sellable_shares_and_reserves_fee_deficit_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active SELL hold keeps both its shares and its fee-deficit cash committed."""

    user, account = _create_owner_account(
        username="m1-active-sell-fee-hold",
        positions=((ASSET_BUY, "Fee-deficit held security", True),),
        cash=Decimal("800.00"),
        position_quantity=Decimal("200.000000"),
        max_position_pct=50.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_BUY: 0.0},
        max_position_pct=50.0,
    )
    reservation = _create_active_order_reservation(
        account=account,
        user_id=user.pk,
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("100"),
        price=Decimal("5.00"),
        min_commission=Decimal("1000.00"),
        fee_budget=None,
        asset_code=ASSET_BUY,
    )
    assert reservation.fee_estimate > reservation.notional
    assert reservation.cash_reserved == reservation.fee_estimate - reservation.notional
    _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        fee_min_commission=Decimal("1000.00"),
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    plan = response.json()["reports"][0]["plan"]
    assert Decimal(plan["cash_before"]) == Decimal("800.00")
    assert Decimal(plan["reserved_cash"]) == reservation.cash_reserved
    assert Decimal(plan["available_cash_before"]) == (Decimal("800.00") - reservation.cash_reserved)
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert Decimal(row["current_quantity"]) == Decimal("200.000000")
    assert Decimal(row["reserved_sell_quantity"]) == Decimal("100.000000")
    assert Decimal(row["sellable_quantity"]) == Decimal("100.000000")
    assert Decimal(row["target_quantity"]) == Decimal("0")
    assert row["status"] == "blocked"
    assert "SELL_FEE_CASH_SHORTFALL" in row["reason_codes"]
    assert row["actionable_quantity"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_position_rule_is_reevaluated_with_the_current_preview_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh quote risk evaluation supersedes the inspection's stored-price result."""

    user, account = _create_owner_account(
        username="m1-fresh-rule-evaluation",
        positions=((ASSET_SELL, "Quote-sensitive holding", True),),
        cash=Decimal("10000.00"),
        position_quantity=Decimal("18000.000000"),
        position_price=Decimal("5.0000"),
        max_position_pct=90.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.6},
        max_position_pct=90.0,
        max_total_position_pct=95.0,
        buy_condition_expr="current_price < entry_price",
        sell_condition_expr="current_price > entry_price",
    )
    now = timezone.now().astimezone(UTC)
    quote = _fixture_price_result(
        asset_code=ASSET_SELL,
        freshness="realtime",
        as_of=None,
        source="fixture:current-lower-than-cost",
        is_fallback=False,
        observed_at=now - timedelta(minutes=5),
        price=3.5,
    )
    price_reader, _, _, _ = _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        price_results={ASSET_SELL: quote},
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    report = response.json()["reports"][0]
    stored_check = next(check for check in report["checks"] if check["asset_code"] == ASSET_SELL)
    assert stored_check["rule_eval"]["should_sell"] is True
    assert stored_check["rule_eval"]["should_buy"] is False
    plan = report["plan"]
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_SELL)
    assert price_reader.calls == [(ASSET_SELL, None)]
    assert Decimal(row["reference_price"]) == Decimal("3.5")
    assert row["risk_rule_result"]["should_buy"] is True
    assert row["risk_rule_result"]["should_sell"] is False
    assert row["risk_rule_reason_code"] is None
    assert "POSITION_RULE_SELL_NOT_TRIGGERED" in row["reason_codes"]
    assert row["action"] == "sell"
    assert row["status"] == "blocked"
    assert row["actionable_quantity"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.parametrize(
    "required_input",
    ("atr", "support_price"),
    ids=("unknown-atr", "unknown-support-price"),
)
def test_rule_requiring_unknown_market_input_cannot_produce_actionable_preview_quantity(
    monkeypatch: pytest.MonkeyPatch,
    required_input: str,
) -> None:
    """A missing source-backed risk input cannot be replaced with a fixture constant."""

    user, account = _create_owner_account(
        username=f"m1-unknown-{required_input}",
        positions=((ASSET_SELL, "ATR-dependent holding", True),),
        max_position_pct=60.0,
        max_total_position_pct=95.0,
    )
    strategy = _create_strategy(
        user=user,
        target_weights={ASSET_SELL: 0.5},
        max_position_pct=60.0,
        max_total_position_pct=95.0,
        buy_condition_expr=f"{required_input} > 0",
    )
    _install_preview_ports(monkeypatch, account=account, user_id=user.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = _post_inspection(client=client, account_id=account.pk, strategy_id=strategy.pk)

    assert response.status_code == 200
    report = response.json()["reports"][0]
    row = next(item for item in report["plan"]["asset_items"] if item["asset_code"] == ASSET_SELL)
    assert row["action"] == "buy"
    assert row["status"] == "blocked"
    assert row["risk_rule_reason_code"] == "STRATEGY_RULE_EVALUATION_UNAVAILABLE"
    assert row["risk_rule_reason_code"] in row["reason_codes"]
    assert row["actionable_quantity"] is None
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )
