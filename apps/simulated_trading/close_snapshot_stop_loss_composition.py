"""Bind close-only source capture and strict locked stop-loss audit to the normal UoW."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from apps.risk_center.application.close_snapshot_simulation import CloseSnapshotSimulationUseCase
from apps.risk_center.application.execution_settlement_v3 import (
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationMarket,
    CloseSnapshotSimulationStatus,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_trading_constraints import ExecutionOrder
from apps.simulated_trading.application.execution_settlement_uow import (
    AutomaticTradeStopLossMarketObservation,
    AutomaticTradeStopLossMarketQuote,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.close_snapshot_submission_composition import CloseSnapshotMarketFactory
from apps.simulated_trading.domain.close_snapshot_execution_market_audit import (
    CloseSnapshotExecutionMarketAuditV1,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_primitives import _utc_text


def _canonical_json(value: dict[str, object]) -> str:
    """Encode one exact JSON envelope without accepting nonfinite values."""
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def capture_close_stop_loss_observation(
    *,
    factory: CloseSnapshotMarketFactory,
    rule_reader: ReadEffectiveExecutionSettlementV3UseCase,
    clock: SimulatedTradeExecutionClock,
    account_id: int,
    identity: ExecutionInstrumentIdentityEvidenceV2,
    calendar_evidence: ExecutionCalendarEvidence,
    as_of: datetime,
) -> AutomaticTradeStopLossMarketObservation:
    """Capture the real public response once, then qualify at actual response availability."""
    identity.validate_at(as_of=as_of)
    calendar_evidence.validate_for(as_of)
    retained = factory.capture_for_security(
        account_id=account_id,
        security_id=identity.security_id,
        asset_code=identity.asset_code,
        as_of=as_of,
    )
    captured_at = clock.now()
    identity.validate_at(as_of=captured_at)
    calendar_evidence.validate_for(captured_at)
    bundle = rule_reader.execute(security_id=identity.security_id, as_of=captured_at)
    selected = retained.read_market_for_stop_loss(
        account_id=account_id,
        identity=identity,
        calendar_evidence=calendar_evidence,
        execution_bundle=bundle,
        as_of=captured_at,
    )
    close = selected.close_bundle
    if close is None:
        raise SimulatedTradeExecutionBlocked("收盘快照模拟原件不可用")
    source = close.market.market_evidence_v1
    evidence_json = _canonical_json(
        {
            "retained_source": retained.export_retained_source(),
            "market_bundle": close.to_payload(),
        }
    )
    observation = AutomaticTradeStopLossMarketObservation(
        security_id=identity.security_id,
        asset_code=identity.asset_code,
        market=close.market,
        reader=retained,
        retained_evidence_json=evidence_json,
        retained_evidence_hash=hashlib.sha256(evidence_json.encode("utf-8")).hexdigest(),
        source_id=source.market_source_id,
        source_version=source.market_source_version,
        source_hash=close.capture.body_sha256,
        source_observed_at=source.market_observed_at,
        source_available_at=source.market_available_at,
        source_valid_until=source.market_valid_until,
        policy_id=close.policy.policy_id,
        policy_version=close.policy.policy_version,
        policy_hash=close.policy.content_hash,
        market_hash=close.market.content_hash,
        market_bundle_hash=close.content_hash,
        rule_hash=close.execution_rule_content_hash,
        calendar_hash=close.calendar.content_hash,
        close_bundle=close,
    )
    observation.__post_init__()
    return observation


def build_close_stop_loss_audit(
    *,
    plan: SettlementExecutionPlanV3,
    execution_bundle: ExecutionSettlementBundleV3,
    quote: AutomaticTradeStopLossMarketQuote,
    market: CloseSnapshotSimulationMarket,
    order: ExecutionOrder,
    locked_position: dict[str, object],
    as_of: datetime,
) -> CloseSnapshotExecutionMarketAuditV1:
    """Require independent close qualification after all common locked stop-loss checks."""
    observation = quote.observation
    close = observation.close_bundle
    if close is None or close.market != market or close.policy.account_id != plan.intent.account_id:
        raise SimulatedTradeExecutionBlocked("收盘快照止损的账户、价格或原件不一致")
    decision = CloseSnapshotSimulationUseCase().evaluate_order(
        rule=execution_bundle.execution_submission_v2,
        bundle=close,
        order=order,
        as_of=as_of,
    )
    if decision.status is not CloseSnapshotSimulationStatus.QUALIFIED:
        raise SimulatedTradeExecutionBlocked(
            "收盘快照使用期限、价格或可卖量不允许本次模拟止损",
            code="AUTO_STOP_LOSS_MARKET_RISK_BLOCKED",
        )
    evidence: dict[str, object] = {
        "schema": "close-snapshot-simulated-market-audit.v1",
        "purpose": "close_snapshot_simulation",
        "retained_source": json.loads(observation.retained_evidence_json)["retained_source"],
        "market_bundle": close.to_payload(),
        "close_qualification": decision.to_payload(),
        "close_evaluated_at": _utc_text(as_of),
        "locked_position": locked_position,
        "qualification": {
            "purpose": "close_snapshot_simulation",
            "decision_scope": "automatic_account_stop_loss",
            "local_simulation_qualified": True,
            "freshness": "close_snapshot",
            "reliability": "vendor_reported_close_snapshot",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "execution_authority": False,
            "global_identity_restrictions": {
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            },
            "local_market_permission": {
                "purpose": "close_snapshot_simulation",
                "qualified": True,
                "must_not_execute": True,
                "execution_authority": False,
            },
            "market_available_at_basis": "local_response_completed_at_not_vendor_published_at",
        },
    }
    intent = plan.intent
    return CloseSnapshotExecutionMarketAuditV1(
        account_id=intent.account_id,
        user_id=intent.user_id,
        idempotency_key=intent.idempotency_key,
        request_payload_hash=intent.request_payload_hash,
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        execution_price=intent.price,
        source_id=observation.source_id,
        source_version=observation.source_version,
        source_hash=observation.source_hash,
        source_observed_at=observation.source_observed_at,
        source_available_at=observation.source_available_at,
        source_valid_until=observation.source_valid_until,
        policy_id=observation.policy_id,
        policy_version=observation.policy_version,
        policy_hash=observation.policy_hash,
        market_hash=observation.market_hash,
        market_bundle_hash=observation.market_bundle_hash,
        rule_hash=observation.rule_hash,
        calendar_hash=observation.calendar_hash,
        close_qualification_hash=decision.content_hash,
        close_evaluated_at=as_of,
        evidence_json=_canonical_json(evidence),
    )
