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

    def __init__(self, policy: SimulatedFeePolicyV2) -> None:
        self.policy = policy

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
            SimulatedTradeSide.BUY,
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
    ) -> None:
        super().__init__(
            preview_builder_factory=_UnusedPreviewBuilderFactory(),
            fee_reader=_FeeReader(fee),
            quantity_rule_reader=_RuleReader(rule_record),
            using="default",
        )
        self._preview = preview
        self._prepared = prepared

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
        assert target_weights == _TARGET_TEXT
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


def _fee_policy() -> SimulatedFeePolicyV2:
    """Bind the exact synthetic equity/SSE/MAIN/BUY V2 fee case and its clocks."""

    base = fee_fixtures._policy(
        fee_fixtures._case(
            asset_type="equity",
            market="SSE",
            board="MAIN",
            side=SimulatedTradeSide.BUY,
        )
    )
    return replace(
        base,
        effective_from=_AS_OF - timedelta(days=1),
        recorded_at=_AS_OF - timedelta(days=1),
        valid_until=_AS_OF + timedelta(hours=1),
        content_hash="",
    )


def _rule_record() -> ExecutionSettlementV3ReadRecord:
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
            minimum=Decimal("1"), step=Decimal("1"), maximum=Decimal("100000")
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


def _classification_evidence() -> SimulatedInstrumentClassificationEvidenceV1:
    """Build exact typed synthetic classification with supplier clocks left unknown."""

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
        must_not_use_for_decision=False,
        must_not_execute=False,
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
    fee: SimulatedFeePolicyV2, record: ExecutionSettlementV3ReadRecord
) -> RebalancePlanPreview:
    """Build one exact typed BUY row whose math is reproduced by the domain helper."""

    adjustment = calculate_asset_adjustment(
        current_quantity=Decimal("100"),
        reference_price=Decimal("10"),
        portfolio_value=Decimal("11000"),
        target_weight=Decimal("0.20"),
        drift_threshold=Decimal("0.01"),
    )
    assert adjustment is not None and adjustment.action == "buy"
    classification_evidence = _classification_evidence()
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
    row = RebalancePlanPreviewItem(
        scope="asset",
        action="buy",
        asset_code=_ASSET_CODE,
        asset_name="Synthetic Shanghai Equity",
        asset_type="equity",
        currency_unit=None,
        quantity_unit="share",
        current_weight=adjustment.current_weight,
        target_weight=Decimal("0.20"),
        portfolio_value=Decimal("11000"),
        current_amount=adjustment.current_amount,
        target_amount=adjustment.target_amount,
        suggested_amount=adjustment.suggested_amount,
        actionable_amount=adjustment.suggested_amount,
        current_quantity=Decimal("100"),
        target_quantity=adjustment.target_quantity,
        suggested_quantity=adjustment.suggested_quantity,
        actionable_quantity=adjustment.suggested_quantity,
        remaining_quantity=Decimal("0"),
        sellable_quantity=Decimal("90"),
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
        status="ready",
        reason_codes=(),
        quantity_rule={"bundle": record.bundle.to_payload()},
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
        status="ready",
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


def _request() -> TransitionPlanRevisionRequest:
    """Build only the user-authored selection and idempotency data."""

    targets = parse_temporary_security_targets(_TARGET_TEXT)
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
) -> tuple[PortfolioJourneyPreparationProvider, RebalancePlanPreview]:
    """Compose the real risk application over explicit synthetic typed inputs."""

    monkeypatch.setattr(risk_fixtures, "_ASSET_CODE", _ASSET_CODE)
    monkeypatch.setattr(risk_fixtures._CalendarReader, "read_calendar", _calendar_result)
    harness = risk_fixtures._harness(source_mode=source_mode)
    fee = _fee_policy()
    record = _rule_record()
    preview = _preview(fee, record)
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
    reads = _Reads(preview=preview, prepared=prepared, fee=selected_fee, rule_record=record)
    return (
        PortfolioJourneyPreparationProvider(
            reads,
            target_weights=_TARGET_TEXT,
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
