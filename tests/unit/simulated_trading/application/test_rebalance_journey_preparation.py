"""Exercise the real plan mapper with typed, explicitly synthetic risk inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from zoneinfo import ZoneInfo

import pytest

from apps.portfolio.application.transition_plan_lifecycle import TransitionPlanRevisionRequest
from apps.portfolio.domain.transition_plan_revision import build_transition_plan_revision
from apps.risk_center.application.execution_settlement_v3 import ExecutionSettlementV3ReadRecord
from apps.risk_center.application.portfolio_risk_serialization import portfolio_risk_content_hash
from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionQuantityConstraint,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeSide,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadRequest,
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_current_pins import (
    JourneyCurrentPolicyPinsValidator,
)
from apps.simulated_trading.application.rebalance_journey_preparation import (
    PortfolioJourneyPreparationProvider,
)
from apps.simulated_trading.application.rebalance_journey_preparation_support import (
    _derive_whole_share_target_quantity,
    _preview_evidence_json,
    _whole_share_quantity,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.application.rebalance_journey_readers import (
    ServerRebalanceJourneyReads,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    RebalancePlanRiskContext,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.rebalance_preview_math import calculate_asset_adjustment
from tests.unit.risk_center import test_execution_settlement_v3 as settlement_fixtures
from tests.unit.simulated_trading import test_execution_fee_policy_v2 as fee_fixtures
from tests.unit.simulated_trading import (
    test_execution_instrument_classification as classification_fixtures,
)
from tests.unit.simulated_trading import test_portfolio_risk_service as risk_fixtures

_AS_OF = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
_PREPARED_AT = _AS_OF + timedelta(seconds=10)
_ASSET_CODE = "600036.SH"
_SECURITY_ID = "SSE:600036"
_TARGET_TEXT = "600036.SH,20"


class _UnusedPreviewBuilderFactory:
    """Make accidental live preview calls visible in this synthetic unit case."""

    def __call__(
        self, *, reference_price_basis: Literal["market", "published_close"]
    ) -> ReadOnlyRebalancePlanPreviewBuilder:
        """Fail because the typed preview is already the captured producer result."""

        raise AssertionError(f"unexpected preview rebuild for {reference_price_basis}")


class _FeeReader:
    """Return one explicit synthetic V2 fee contract for the typed test row."""

    def __init__(self, policy: SimulatedFeePolicyV2, *, expected_side: SimulatedTradeSide) -> None:
        self.policy = policy
        self.expected_side = expected_side

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
        """Expose the test's exact owner/market/side case and no other schedule."""

        if (account_id, user_id, asset_type, market, board, side) != (
            risk_fixtures._ACCOUNT_ID,
            risk_fixtures._OWNER_ID,
            "equity",
            "SSE",
            "MAIN",
            self.expected_side,
        ) or as_of != _AS_OF:
            return None
        return self.policy


class _RuleReader:
    """Return the exact synthetic v3 rule record selected for the row."""

    def __init__(self, record: ExecutionSettlementV3ReadRecord) -> None:
        self.record = record

    def execute_record(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord:
        """Return only the requested exact identity at the supplied cutoff."""

        if security_id != _SECURITY_ID or as_of != _AS_OF:
            raise RebalanceJourneyUnavailable(code="TEST_RULE_SCOPE_MISMATCH")
        return self.record


class _Reads(ServerRebalanceJourneyReads):
    """Use the real typed read contract while supplying one captured synthetic result."""

    def __init__(
        self,
        *,
        preview: RebalancePlanPreview,
        prepared: PreparedPortfolioRisk,
        fee: SimulatedFeePolicyV2,
        rule_record: ExecutionSettlementV3ReadRecord,
        target_weights: str,
    ) -> None:
        super().__init__(
            preview_builder_factory=_UnusedPreviewBuilderFactory(),
            fee_reader=_FeeReader(
                fee,
                expected_side=(
                    SimulatedTradeSide.BUY
                    if preview.asset_items[0].action == "buy"
                    else SimulatedTradeSide.SELL
                ),
            ),
            quantity_rule_reader=_RuleReader(rule_record),
            using="default",
        )
        self._preview = preview
        self._prepared = prepared
        self._target_weights = target_weights

    def read_preview(
        self,
        *,
        user_id: int,
        account_id: int,
        target_weights: str,
        reference_price_basis: Literal["market", "published_close"],
    ) -> RebalancePlanPreview:
        """Return this test's one captured preview without rebuilding market facts."""

        assert user_id == risk_fixtures._OWNER_ID
        assert account_id == risk_fixtures._ACCOUNT_ID
        assert target_weights == self._target_weights
        assert reference_price_basis == "market"
        return self._preview

    def read_risk(
        self, *, user_id: int, account_id: int, preview: RebalancePlanPreview
    ) -> PreparedPortfolioRisk:
        """Return the separately prepared result from the real synthetic risk service."""

        assert user_id == risk_fixtures._OWNER_ID
        assert account_id == risk_fixtures._ACCOUNT_ID
        assert preview is self._preview
        return self._prepared


def _calendar_result(
    _reader: object,
    request: PortfolioRiskCalendarReadRequest,
) -> PortfolioRiskCalendarReadResult:
    """Create an explicitly synthetic but fully clocked published-session member."""

    published_at = request.as_of - timedelta(minutes=5)
    member: dict[str, object] = {
        "requested_exchange": "SSE",
        "snapshot": {"exchange": "SSE", "sessions": [request.requested_session.isoformat()]},
        "evidence_hash": "a" * 64,
        "publication": {
            "publication_id": "synthetic-calendar-publication",
            "member_id": "synthetic-calendar-member",
            "policy_hash": "b" * 64,
            "timezone_name": "Asia/Shanghai",
            "published_at": published_at.isoformat(),
            "recorded_at": published_at.isoformat(),
            "reference_valid_from": (request.as_of - timedelta(days=1)).isoformat(),
            "reference_valid_until": (request.as_of + timedelta(hours=2)).isoformat(),
        },
    }
    document = {
        "as_of": request.as_of.isoformat(),
        "requested_session": request.requested_session.isoformat(),
        "calendar_evidence": [member],
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PortfolioRiskCalendarReadResult(
        requested_session_qualified=True,
        open_sessions=(request.requested_session,),
        reason_codes=(),
        canonical_evidence_json=encoded,
        evidence_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        valid_until=request.as_of + timedelta(hours=1),
    )


def _fee_policy(
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
) -> SimulatedFeePolicyV2:
    """Bind one exact synthetic equity/SSE/MAIN side fee case and its clocks."""

    base = fee_fixtures._policy(
        fee_fixtures._case(
            asset_type="equity",
            market="SSE",
            board="MAIN",
            side=side,
        )
    )
    return replace(
        base,
        effective_from=_AS_OF - timedelta(days=1),
        recorded_at=_AS_OF - timedelta(days=1),
        valid_until=_AS_OF + timedelta(hours=1),
        content_hash="",
    )


def _rule_record(*, sell_step: Decimal = Decimal("1")) -> ExecutionSettlementV3ReadRecord:
    """Bind an exact typed V3 bundle and its separate local-known clock."""

    base = settlement_fixtures._rule_v1()
    rule = replace(
        base,
        rule_id="synthetic-ash08-equity-rule",
        rule_version="synthetic-1",
        security_id=_SECURITY_ID,
        market="SSE",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=Decimal("100000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=sell_step, maximum=Decimal("100000")
        ),
        source_observed_at=_AS_OF - timedelta(days=1),
        source_available_at=_AS_OF - timedelta(hours=1),
        effective_from=_AS_OF - timedelta(minutes=30),
        valid_until=_AS_OF + timedelta(hours=1),
        content_hash="",
    )
    v2 = ExecutionSubmissionRuleV2(
        execution_rule_v1=rule,
        price_submission_range=PriceSubmissionRangeRule(
            market="SSE",
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
        policy_id="synthetic-ash08-settlement",
        policy_version="synthetic-1",
        security_id=_SECURITY_ID,
        market="SSE",
        board="MAIN",
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=v2.content_hash,
        source_id="synthetic-ash08-settlement-source",
        source_version="synthetic-1",
        source_hash="c" * 64,
        source_observed_at=_AS_OF - timedelta(days=1),
        source_available_at=_AS_OF - timedelta(hours=1),
        effective_from=_AS_OF - timedelta(minutes=30),
        valid_until=_AS_OF + timedelta(hours=1),
    )
    bundle = ExecutionSettlementBundleV3(
        bundle_id="synthetic-ash08-bundle",
        bundle_version="synthetic-1",
        execution_submission_v2=v2,
        settlement_policy_v1=settlement,
    )
    return ExecutionSettlementV3ReadRecord(
        bundle=bundle,
        recorded_at=_AS_OF - timedelta(minutes=20),
    )


def _classification_evidence(
    *, source_restricted: bool = False
) -> SimulatedInstrumentClassificationEvidenceV1:
    """Build typed synthetic classification and preserve supplier restrictions."""

    template_selector = classification_fixtures._selector()
    selector_item = replace(
        template_selector.items[0],
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        source_code=_ASSET_CODE,
        simulated_asset_type="equity",
    )
    selector = replace(template_selector, items=(selector_item,))
    template_identity = classification_fixtures._identity(template_selector)
    reference_completed_at = _AS_OF - timedelta(minutes=5)
    snapshot_recorded_at = _AS_OF - timedelta(minutes=4)
    mapping_recorded_at = _AS_OF - timedelta(minutes=20)
    profile_activated_at = _AS_OF - timedelta(hours=2)
    selection = replace(
        template_identity.selection,
        selector_content_hash=selector.content_hash,
        profile_activated_at=profile_activated_at,
        runtime_snapshot_generated_at=_AS_OF - timedelta(hours=1),
        selected_at=_AS_OF,
    )
    source = replace(
        template_identity.source_evidence,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        source_code=_ASSET_CODE,
        source_exchange="SSE",
        source_market="SSE",
        rule_market="SSE",
        board="MAIN",
        first_seen_at=reference_completed_at,
        snapshot_recorded_at=snapshot_recorded_at,
        mapping_recorded_at=mapping_recorded_at,
        response_completed_at=reference_completed_at,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(
            profile_activated_at,
            snapshot_recorded_at,
            mapping_recorded_at,
        ),
        identity_valid_until=reference_completed_at
        + timedelta(seconds=selection.max_local_reference_age_seconds),
        must_not_use_for_decision=source_restricted,
        must_not_execute=source_restricted,
    )
    identity: ExecutionInstrumentIdentityEvidenceV2 = replace(
        template_identity,
        source_evidence=source,
        selection=selection,
        reference_response_completed_at=reference_completed_at,
    )
    evidence = SimulatedInstrumentClassificationEvidenceV1(
        selector=selector,
        identity_evidence=identity,
        read_at=_AS_OF,
    )
    evidence.__post_init__()
    return evidence


def _preview(
    fee: SimulatedFeePolicyV2,
    record: ExecutionSettlementV3ReadRecord,
    *,
    target_weight: Decimal = Decimal("0.20"),
    actionable_quantity: Decimal | None = None,
    row_status: str = "ready",
    row_reason_codes: tuple[str, ...] = (),
    classification_source_restricted: bool = False,
    classification_outer_flags: bool | None = None,
    classification_purpose: str | None = None,
) -> RebalancePlanPreview:
    """Build one exact typed row whose math is reproduced by the domain helper."""

    adjustment = calculate_asset_adjustment(
        current_quantity=Decimal("100"),
        reference_price=Decimal("10"),
        portfolio_value=Decimal("11000"),
        target_weight=target_weight,
        drift_threshold=Decimal("0.01"),
    )
    assert adjustment is not None and adjustment.action in {"buy", "sell"}
    selected_actionable_quantity = (
        adjustment.suggested_quantity if actionable_quantity is None else actionable_quantity
    )
    remaining_quantity = (
        adjustment.suggested_quantity - selected_actionable_quantity
        if adjustment.suggested_quantity is not None and selected_actionable_quantity is not None
        else adjustment.suggested_quantity
    )
    snapshot = risk_fixtures._snapshot()
    matching_sell_reservations = tuple(
        order.remaining_quantity
        for order in snapshot.active_orders
        if order.side == "sell"
        and order.asset_code == _ASSET_CODE
        and order.security_id == _SECURITY_ID
    )
    reserved_sell_quantity = (
        None
        if not snapshot.active_orders_complete
        or any(quantity is None for quantity in matching_sell_reservations)
        else sum(
            (quantity for quantity in matching_sell_reservations if quantity is not None),
            Decimal("0"),
        )
    )
    available_sell_quantities = tuple(
        holding.available_quantity
        for holding in snapshot.holdings
        if holding.asset_code == _ASSET_CODE and holding.security_id == _SECURITY_ID
    )
    sellable_quantity = (
        None
        if not available_sell_quantities
        or any(quantity is None for quantity in available_sell_quantities)
        or reserved_sell_quantity is None
        else sum(
            (quantity for quantity in available_sell_quantities if quantity is not None),
            Decimal("0"),
        )
        - reserved_sell_quantity
    )
    classification_evidence = _classification_evidence(
        source_restricted=classification_source_restricted
    )
    identity_evidence = classification_evidence.identity_evidence
    identity = {
        "asset_code": _ASSET_CODE,
        "security_id": _SECURITY_ID,
        "identity_hash": identity_evidence.content_hash,
        "rule_market": "SSE",
        "board": "MAIN",
    }
    classification = {
        "simulated_asset_type": classification_evidence.simulated_asset_type,
        "must_not_use_for_decision": (identity_evidence.source_evidence.must_not_use_for_decision),
        "must_not_execute": identity_evidence.source_evidence.must_not_execute,
        "purpose": identity_evidence.selection.purpose,
        "read_at": classification_evidence.read_at.isoformat(),
        "evidence": classification_evidence.to_payload(),
        "content_hash": classification_evidence.content_hash,
    }
    if classification_outer_flags is not None:
        classification["must_not_use_for_decision"] = classification_outer_flags
        classification["must_not_execute"] = classification_outer_flags
    if classification_purpose is not None:
        classification["purpose"] = classification_purpose
    row = RebalancePlanPreviewItem(
        scope="asset",
        action=adjustment.action,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic Shanghai Equity",
        asset_type="equity",
        currency_unit=None,
        quantity_unit="share",
        current_weight=adjustment.current_weight,
        target_weight=target_weight,
        portfolio_value=Decimal("11000"),
        current_amount=adjustment.current_amount,
        target_amount=adjustment.target_amount,
        suggested_amount=adjustment.suggested_amount,
        actionable_amount=(
            selected_actionable_quantity * Decimal("10")
            if selected_actionable_quantity is not None
            else None
        ),
        current_quantity=Decimal("100"),
        target_quantity=adjustment.target_quantity,
        suggested_quantity=adjustment.suggested_quantity,
        actionable_quantity=selected_actionable_quantity,
        remaining_quantity=remaining_quantity,
        sellable_quantity=sellable_quantity,
        reference_price=Decimal("10"),
        price_source="synthetic-qualified-risk-valuation",
        price_as_of=None,
        price_freshness="qualified_snapshot",
        price_is_fallback=False,
        price_observed_at=_AS_OF - timedelta(minutes=1),
        identity=identity,
        fee={"total": "500", "content_hash": fee.content_hash},
        drift_threshold=Decimal("0.01"),
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status=row_status,
        reason_codes=row_reason_codes,
        quantity_rule={"bundle": record.bundle.to_payload()},
        reserved_sell_quantity=reserved_sell_quantity,
        classification_evidence=classification,
        target_mode="user_target_difference",
    )
    risk_context = RebalancePlanRiskContext(
        strategy_id=None,
        position_rule_id=None,
        strategy_name=None,
        strategy_type=None,
        strategy_version=None,
        rule_name=None,
        risk_profile=None,
        macro_regime=None,
        policy_gear=None,
        max_position_pct=None,
        max_total_position_pct=None,
        stop_loss_pct=None,
        account_max_position_pct=None,
        account_max_total_position_pct=None,
        account_stop_loss_pct=None,
        target_allocation=None,
        pulse=None,
        rule_version=None,
        rule_effective_from=None,
        rule_effective_until=None,
        strategy_selection_state="confirmed_unconfigured",
        strategy_policy_applicability="not_applicable",
        reference_price_basis="market",
    )
    return RebalancePlanPreview(
        status=row_status,
        reason_codes=(),
        as_of=_AS_OF - timedelta(seconds=1),
        financial_snapshot_read_at=_AS_OF - timedelta(seconds=2),
        portfolio_value=Decimal("11000"),
        cash_before=Decimal("10000"),
        reserved_cash=Decimal("25"),
        available_cash_before=Decimal("9975"),
        projected_cash_after_sells=None,
        estimated_sell_gross=None,
        estimated_sell_fees=None,
        estimated_sell_net=None,
        estimated_buy_gross=Decimal("1200"),
        estimated_buy_fees=Decimal("156"),
        estimated_buy_total=Decimal("1356"),
        projected_cash_after_buys=Decimal("8644"),
        funding_status="known",
        sell_before_buy={"status": "not_required"},
        risk_context=risk_context,
        allocation_items=(),
        asset_items=(row,),
        portfolio_risk=None,
    )


def _request(target_weights: str = _TARGET_TEXT) -> TransitionPlanRevisionRequest:
    """Build only the user-authored selection and idempotency data."""

    targets = parse_temporary_security_targets(target_weights)
    target_payload = {
        "weights": targets.exact_weight_strings(),
        "residual_cash_weight": str(targets.residual_cash_weight),
    }
    return TransitionPlanRevisionRequest(
        actor_user_id=risk_fixtures._OWNER_ID,
        account_id=risk_fixtures._ACCOUNT_ID,
        target_portfolio_id=portfolio_risk_content_hash(target_payload),
        selection_id="temporary_security_targets:market",
        expected_selection_hash=portfolio_risk_content_hash(
            {"target": target_payload, "reference_price_basis": "market"}
        ),
        idempotency_key="synthetic-ash08-plan-create",
    )


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_mode: str = "complete",
    fee_mismatch: bool = False,
    target_weights: str = _TARGET_TEXT,
    target_weight: Decimal = Decimal("0.20"),
    fee_side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    sell_step: Decimal = Decimal("1"),
    actionable_quantity: Decimal | None = None,
    row_status: str = "ready",
    row_reason_codes: tuple[str, ...] = (),
    classification_source_restricted: bool = False,
    classification_outer_flags: bool | None = None,
    classification_purpose: str | None = None,
) -> tuple[PortfolioJourneyPreparationProvider, RebalancePlanPreview]:
    """Compose the real risk application over explicit synthetic typed inputs."""

    monkeypatch.setattr(risk_fixtures, "_ASSET_CODE", _ASSET_CODE)
    monkeypatch.setattr(risk_fixtures._CalendarReader, "read_calendar", _calendar_result)
    harness = risk_fixtures._harness(source_mode=source_mode)
    fee = _fee_policy(fee_side)
    record = _rule_record(sell_step=sell_step)
    preview = _preview(
        fee,
        record,
        target_weight=target_weight,
        actionable_quantity=actionable_quantity,
        row_status=row_status,
        row_reason_codes=row_reason_codes,
        classification_source_restricted=classification_source_restricted,
        classification_outer_flags=classification_outer_flags,
        classification_purpose=classification_purpose,
    )
    prepared = harness.service.prepare_plan_context(
        user_id=risk_fixtures._OWNER_ID,
        account_id=risk_fixtures._ACCOUNT_ID,
        preview=preview,
    )
    selected_fee = (
        replace(fee, policy_version=fee.policy_version + 1, content_hash="")
        if fee_mismatch
        else fee
    )
    reads = _Reads(
        preview=preview,
        prepared=prepared,
        fee=selected_fee,
        rule_record=record,
        target_weights=target_weights,
    )
    return (
        PortfolioJourneyPreparationProvider(
            reads,
            target_weights=target_weights,
            reference_price_basis="market",
            business_timezone=ZoneInfo("Asia/Shanghai"),
        ),
        preview,
    )


def test_prepare_maps_one_typed_preview_and_qualified_risk_result_to_immutable_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The producer seals exact source/risk/policy evidence without granting execution."""

    provider, _preview_result = _provider(monkeypatch)

    result = provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)

    assert result.plan.status == "DRAFT"
    assert len(result.plan.orders) == 1
    assert result.plan.orders[0].side == "buy"
    assert result.plan.orders[0].quantity == 120
    assert result.plan.orders[0].remaining_quantity == 0
    assert result.order_specifications[0].asset_type == "equity"
    assert result.order_specifications[0].approved_limit_price is None
    assert result.basis.money_unit == "CNY"
    assert result.basis.preparation_evidence_json is not None
    assert result.basis.risk.must_not_use_for_decision is False
    assert result.basis.planning_policy.status == "not_applicable"
    assert result.basis.execution_calendar.status == "qualified"


def test_fractional_buy_suggestion_is_floored_and_exact_remainder_is_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fractional target difference yields whole shares without losing its evidence."""

    target_weights = "600036.SH,20.01"
    provider, preview = _provider(
        monkeypatch,
        target_weights=target_weights,
        target_weight=Decimal("0.2001"),
        actionable_quantity=Decimal("120"),
        row_status="partial",
        row_reason_codes=("BUY_QUANTITY_STEP_ROUNDED_DOWN",),
    )

    result = provider.prepare(_request(target_weights), prepared_at=_PREPARED_AT, parent=None)

    order = result.plan.orders[0]
    assert preview.asset_items[0].suggested_quantity == Decimal("120.110000")
    assert result.basis.target_positions[0].target_quantity == Decimal("220.110000")
    assert order.side == "buy"
    assert order.quantity == 120
    assert order.remaining_quantity == 0
    assert order.quantity + order.remaining_quantity == 120
    assert result.order_specifications[0].asset_code == _ASSET_CODE
    evidence = json.loads(result.basis.preparation_evidence_json)
    risk_payload = evidence["decision_snapshot"]["payload"]["prepared_risk"]
    member = risk_payload["order_policy_members"][0]
    assert member["side"] == "buy"
    assert member["target_quantity_derivation"] == {
        "basis": "theoretical_target_difference",
        "suggested_quantity": "120.110000",
        "requested_whole_share_quantity": 120,
        "fractional_remainder": "0.110000",
        "rounding_rule": "floor_to_whole_share",
    }


def test_fractional_sell_suggestion_is_floored_below_the_step_limited_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step-limited SELL stays within the whole-share target request and retains residue."""

    target_weights = "600036.SH,4.59"
    provider, preview = _provider(
        monkeypatch,
        target_weights=target_weights,
        target_weight=Decimal("0.0459"),
        fee_side=SimulatedTradeSide.SELL,
        sell_step=Decimal("10"),
        actionable_quantity=Decimal("40"),
        row_status="partial",
        row_reason_codes=("SELL_QUANTITY_LIMITED_BY_RULE",),
    )

    result = provider.prepare(_request(target_weights), prepared_at=_PREPARED_AT, parent=None)

    order = result.plan.orders[0]
    assert preview.asset_items[0].action == "sell"
    assert preview.asset_items[0].suggested_quantity == Decimal("49.510000")
    assert result.basis.target_positions[0].target_quantity == Decimal("50.490000")
    assert order.side == "sell"
    assert order.quantity == 40
    assert order.quantity <= 49
    assert order.remaining_quantity == 9
    assert order.quantity + order.remaining_quantity == 49
    evidence = json.loads(result.basis.preparation_evidence_json)
    risk_payload = evidence["decision_snapshot"]["payload"]["prepared_risk"]
    member = risk_payload["order_policy_members"][0]
    assert member["side"] == "sell"
    assert member["target_quantity_derivation"] == {
        "basis": "theoretical_target_difference",
        "suggested_quantity": "49.510000",
        "requested_whole_share_quantity": 49,
        "fractional_remainder": "0.510000",
        "rounding_rule": "floor_to_whole_share",
    }


@pytest.mark.parametrize(
    "value",
    (None, Decimal("-0.1"), Decimal("Infinity"), Decimal("NaN")),
)
def test_target_quantity_derivation_blocks_unknown_negative_and_nonfinite_values(
    value: Decimal | None,
) -> None:
    """Target-driven rounding never manufactures a quantity from invalid inputs."""

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        _derive_whole_share_target_quantity(value)

    assert error.value.code == "REBALANCE_PLAN_ORDER_QUANTITY_UNKNOWN"


def test_explicit_actionable_quantity_keeps_strict_whole_share_validation() -> None:
    """Fractional theoretical suggestions do not relax explicit execution quantities."""

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        _whole_share_quantity(Decimal("120.11"), "actionable_quantity")

    assert error.value.code == "REBALANCE_PLAN_ORDER_QUANTITY_NOT_WHOLE"


def test_current_pins_replays_the_exact_typed_classification_from_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retained selector/source DTO is consumable by the real current-pin check."""

    provider, preview = _provider(monkeypatch)
    prepared = cast(_Reads, provider._reads)._prepared
    preparation = provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)
    revision = build_transition_plan_revision(preparation)
    assert preparation.plan.as_of_time == prepared.snapshot.read_at
    assert preparation.basis.portfolio_snapshot_as_of == prepared.snapshot.read_at
    assert preparation.basis.preparation_evidence_json is not None
    stored = json.loads(preparation.basis.preparation_evidence_json)
    portfolio_snapshot = stored["portfolio_snapshot"]
    resources = portfolio_snapshot["resources"]
    assert resources["preview_financial_snapshot_read_at"] == (
        preview.financial_snapshot_read_at.isoformat()
    )
    assert resources["risk_snapshot_read_at"] == prepared.snapshot.read_at.isoformat()
    decision = stored["decision_snapshot"]["payload"]
    assert decision["preview"]["financial_snapshot_read_at"] == (
        preview.financial_snapshot_read_at.isoformat()
    )
    preview_payload = decision["preview"]
    rows = preview_payload["asset_items"]
    row = next(item for item in rows if item["asset_code"] == _ASSET_CODE)
    evidence_payload = row["classification_evidence"]["evidence"]
    retained = SimulatedInstrumentClassificationEvidenceV1.from_payload(evidence_payload)
    assert retained.simulated_asset_type == revision.orders[0].asset_type
    assert retained.identity_evidence.asset_code == revision.orders[0].asset_code
    assert retained.identity_evidence.security_id == _SECURITY_ID
    assert retained.read_at == _AS_OF
    assert retained.identity_evidence.source_evidence.source_observed_at is None
    assert retained.identity_evidence.source_evidence.source_available_at is None

    class _ClassificationReader:
        """Return only the sealed classification for its exact account target."""

        def resolve_simulated_instrument_classification(
            self, *, security_id: str, asset_code: str, as_of: datetime
        ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
            if (security_id, asset_code, as_of) != (_SECURITY_ID, _ASSET_CODE, _AS_OF):
                return None
            return retained

    validator = JourneyCurrentPolicyPinsValidator.__new__(JourneyCurrentPolicyPinsValidator)
    validator._classifications = _ClassificationReader()
    validator._verify_classification(
        order=revision.orders[0],
        row=row,
        as_of=_AS_OF,
    )


def test_prepare_preserves_reference_only_classification_restrictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local identity classification is retained without granting plan authority."""

    provider, _preview_result = _provider(
        monkeypatch,
        classification_source_restricted=True,
    )
    prepared = cast(_Reads, provider._reads)._prepared
    preparation = provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)

    assert preparation.plan.status == "DRAFT"
    assert len(preparation.plan.orders) == 1
    assert prepared.report["must_not_use_for_decision"] is False
    assert prepared.report["must_not_execute"] is True
    assert preparation.basis.preparation_evidence_json is not None
    evidence_document = json.loads(preparation.basis.preparation_evidence_json)
    preview = evidence_document["decision_snapshot"]["payload"]["preview"]
    classification = preview["asset_items"][0]["classification_evidence"]
    retained = SimulatedInstrumentClassificationEvidenceV1.from_payload(classification["evidence"])

    assert classification["purpose"] == "normal_simulated_current_reference"
    assert classification["must_not_use_for_decision"] is True
    assert classification["must_not_execute"] is True
    assert retained.identity_evidence.source_evidence.source_observed_at is None
    assert retained.identity_evidence.source_evidence.source_available_at is None
    assert retained.identity_evidence.source_evidence.must_not_use_for_decision is True
    assert retained.identity_evidence.source_evidence.must_not_execute is True


@pytest.mark.parametrize(
    ("classification_outer_flags", "classification_purpose"),
    [(False, None), (None, "decision_qualified")],
)
def test_prepare_rejects_classification_envelope_that_upgrades_or_relabels_source(
    monkeypatch: pytest.MonkeyPatch,
    classification_outer_flags: bool | None,
    classification_purpose: str | None,
) -> None:
    """Outer metadata cannot erase source limits or relabel the local selector."""

    provider, _preview_result = _provider(
        monkeypatch,
        classification_source_restricted=True,
        classification_outer_flags=classification_outer_flags,
        classification_purpose=classification_purpose,
    )

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)

    assert error.value.code == "REBALANCE_PLAN_CLASSIFICATION_UNQUALIFIED"


def test_prepare_rejects_unknown_source_evidence_before_creating_a_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed preview cannot upgrade a risk context with unknown source clocks."""

    provider, _preview_result = _provider(monkeypatch, source_mode="unknown")

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)

    assert error.value.code == "REBALANCE_PLAN_RISK_NOT_QUALIFIED"


def test_prepare_rejects_fee_policy_mismatch_with_captured_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed V2 fee version cannot be silently rebound after preview capture."""

    provider, _preview_result = _provider(monkeypatch, fee_mismatch=True)

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        provider.prepare(_request(), prepared_at=_PREPARED_AT, parent=None)

    assert error.value.code == "REBALANCE_PLAN_FEE_POLICY_CHANGED"


def _preview_with_pulse(
    score: object,
    *,
    additional_pulse_values: dict[str, object] | None = None,
    fee_total: object = "500",
) -> RebalancePlanPreview:
    """Build the normal typed preview with one explicitly controlled legacy pulse value."""

    preview = _preview(_fee_policy(), _rule_record())
    pulse: dict[str, object] = {
        "available": True,
        "observed_at": _AS_OF.date().isoformat(),
        "composite_score": score,
        "regime_strength": "weak",
        "transition_warning": True,
        "transition_direction": "risk_off",
        "data_source": "calculated",
        "stale_indicator_count": 1,
    }
    if additional_pulse_values is not None:
        pulse.update(additional_pulse_values)
    risk_context = replace(preview.risk_context, pulse=pulse)
    item = replace(
        preview.asset_items[0],
        fee={"total": fee_total, "content_hash": "d" * 64},
    )
    return replace(preview, risk_context=risk_context, asset_items=(item,))


@pytest.mark.parametrize("score", (0.0, -0.0, 0.125))
def test_preview_evidence_tags_only_the_exact_pulse_score_losslessly(score: float) -> None:
    """Internal evidence tags the binary64 score while public preview keeps its float."""

    preview = _preview_with_pulse(score)
    evidence = cast(dict[str, object], _preview_evidence_json(preview))
    risk_context = cast(dict[str, object], evidence["risk_context"])
    pulse = cast(dict[str, object], risk_context["pulse"])

    assert pulse == {
        "available": True,
        "observed_at": _AS_OF.date().isoformat(),
        "composite_score": {
            "kind": "pulse_composite_score",
            "encoding": "python-float-hex-v1",
            "value": score.hex(),
        },
        "regime_strength": "weak",
        "transition_warning": True,
        "transition_direction": "risk_off",
        "data_source": "calculated",
        "stale_indicator_count": 1,
    }
    assert preview.risk_context.pulse is not None
    assert preview.risk_context.pulse["composite_score"] == score
    public_context = cast(dict[str, object], preview.to_payload()["risk_context"])
    public_pulse = cast(dict[str, object], public_context["pulse"])
    public_score = public_pulse["composite_score"]
    assert type(public_score) is float
    assert cast(float, public_score).hex() == score.hex()


def test_preview_evidence_preserves_the_unavailable_pulse_default() -> None:
    """The actual unavailable-pulse shape keeps its explicit zero and unknown state."""

    preview = _preview_with_pulse(
        0.0,
        additional_pulse_values={
            "available": False,
            "observed_at": None,
            "regime_strength": "unknown",
            "transition_warning": False,
            "transition_direction": None,
            "data_source": "unavailable",
            "stale_indicator_count": 0,
        },
    )
    evidence = cast(dict[str, object], _preview_evidence_json(preview))
    context = cast(dict[str, object], evidence["risk_context"])
    pulse = cast(dict[str, object], context["pulse"])

    assert pulse == {
        "available": False,
        "observed_at": None,
        "composite_score": {
            "kind": "pulse_composite_score",
            "encoding": "python-float-hex-v1",
            "value": (0.0).hex(),
        },
        "regime_strength": "unknown",
        "transition_warning": False,
        "transition_direction": None,
        "data_source": "unavailable",
        "stale_indicator_count": 0,
    }


@pytest.mark.parametrize(
    ("score", "expected"),
    ((None, None), (0, 0), (Decimal("0.125"), "0.125")),
)
def test_preview_evidence_preserves_nonfloat_pulse_values_by_existing_serializer(
    score: object,
    expected: object,
) -> None:
    """Non-float scores keep the unchanged canonical serializer's prior behavior."""

    evidence = cast(
        dict[str, object],
        _preview_evidence_json(_preview_with_pulse(score)),
    )
    context = cast(dict[str, object], evidence["risk_context"])
    pulse = cast(dict[str, object], context["pulse"])

    assert pulse["composite_score"] == expected


@pytest.mark.parametrize("score", (float("nan"), float("inf"), float("-inf")))
def test_preview_evidence_rejects_nonfinite_pulse_score(score: float) -> None:
    """A non-finite legacy Pulse value cannot enter immutable journey evidence."""

    with pytest.raises(RebalanceJourneyUnavailable) as error:
        _preview_evidence_json(_preview_with_pulse(score))

    assert error.value.code == "REBALANCE_PLAN_PULSE_SCORE_INVALID"


def test_preview_evidence_keeps_other_pulse_floats_outside_the_exception() -> None:
    """Only pulse.composite_score has the explicitly tagged legacy-float encoding."""

    preview = _preview_with_pulse(0.25, additional_pulse_values={"dimension_score": 0.5})

    with pytest.raises(TypeError, match="floating-point financial values"):
        _preview_evidence_json(preview)


def test_preview_evidence_rejects_float_in_a_financial_fee_field() -> None:
    """A fee amount remains subject to the unchanged exact Decimal serializer."""

    preview = _preview_with_pulse(0.25, fee_total=0.1)

    with pytest.raises(TypeError, match="floating-point financial values"):
        _preview_evidence_json(preview)


def test_preview_evidence_rejects_float_in_a_financial_cash_field() -> None:
    """The raw preview dataclass reaches the strict serializer without Decimal laundering."""

    preview = _preview_with_pulse(0.25)
    malformed_preview = replace(preview, cash_before=cast(Decimal, 0.1))

    with pytest.raises(TypeError, match="floating-point financial values"):
        _preview_evidence_json(malformed_preview)
