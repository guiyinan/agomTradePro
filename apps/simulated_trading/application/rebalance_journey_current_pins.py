"""Recheck versioned plan context using database and retained-reference ports only."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, tzinfo
from typing import NoReturn, cast

from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderBinding,
    TransitionPlanRevision,
)
from apps.risk_center.application.portfolio_baseline_risk import PortfolioBaselinePolicyReader
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyReader
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionFeePolicyReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
    PortfolioRiskCalendarReadRequest,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_journey_preparation_support import (
    bind_plan_execution_calendar,
)
from apps.simulated_trading.application.rebalance_journey_readers import JourneyRuleRecordReader
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide


class JourneyCurrentPolicyPinsValidator:
    """Check exact original policy/source versions without rerunning a plan in a lock.

    These ports are database or retained-reference readers. The ordinary manual
    submission still performs its own current market, risk, cash and quantity
    checks. A plan binding is additional context, never execution authority.
    """

    def __init__(
        self,
        *,
        risk_policy_reader: PortfolioRiskPolicyReader,
        baseline_reader: PortfolioBaselinePolicyReader,
        resource_reader: PortfolioRiskResourceSnapshotReaderProtocol,
        classification_reader: CurrentReferenceClassificationReader,
        calendar_reader: PortfolioRiskCalendarReader,
        fee_reader: ExecutionFeePolicyReader,
        rule_reader: JourneyRuleRecordReader,
        business_timezone: tzinfo,
    ) -> None:
        """Require explicit trusted read ports; accept no client policy facts."""

        self._risk = risk_policy_reader
        self._baseline = baseline_reader
        self._resources = resource_reader
        self._classifications = classification_reader
        self._calendars = calendar_reader
        self._fees = fee_reader
        self._rules = rule_reader
        self._timezone = business_timezone

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Reject drift/unknown while permitting actual balances to change after fills."""

        revision.__post_init__()
        if as_of < revision.basis.prepared_at or as_of >= revision.identity.valid_until:
            _blocked("TRANSITION_PLAN_CONTEXT_EXPIRED")
        evidence = _json_object(revision.basis.preparation_evidence_json)
        decision = _object(_object(evidence.get("decision_snapshot")).get("payload"))
        if decision.get("business_timezone") != str(self._timezone):
            _blocked("TRANSITION_PLAN_BUSINESS_TIMEZONE_CHANGED")
        risk = _object(decision.get("prepared_risk"))
        inputs = _json_object(_text(risk.get("input_snapshot_json")))
        self._verify_risk(revision, risk=risk, inputs=inputs, as_of=as_of)
        self._verify_calendar(revision, as_of=as_of)
        preview = _object(decision.get("preview"))
        rows = _objects(preview.get("asset_items"))
        members = _objects(risk.get("order_policy_members"))
        if len(members) != len(revision.orders):
            _blocked("TRANSITION_PLAN_ORDER_POLICY_MEMBERS_INVALID")
        for order in revision.orders:
            matches = [m for m in members if m.get("ordinal") == order.ordinal]
            if len(matches) != 1:
                _blocked("TRANSITION_PLAN_ORDER_POLICY_MEMBERS_INVALID")
            self._verify_order(revision, order=order, member=matches[0], as_of=as_of)
            matches = [row for row in rows if row.get("asset_code") == order.asset_code]
            if len(matches) != 1:
                _blocked("TRANSITION_PLAN_CLASSIFICATION_UNAVAILABLE")
            self._verify_classification(order=order, row=matches[0], as_of=as_of)

    def _verify_risk(
        self,
        revision: TransitionPlanRevision,
        *,
        risk: dict[str, object],
        inputs: dict[str, object],
        as_of: datetime,
    ) -> None:
        basis = revision.basis
        current = self._risk.read_policy(
            account_id=basis.account_id,
            as_of=as_of,
            business_date=as_of.astimezone(self._timezone).date(),
        ).policy
        original = _object(risk.get("policy"))
        if current is None:
            _blocked("TRANSITION_PLAN_RISK_POLICY_UNAVAILABLE")
        pins: dict[str, object] = {
            "profile_id": current.profile_id,
            "profile_key": current.profile_key,
            "profile_version": current.profile_version,
            "profile_content_hash": current.profile_content_hash,
            "normalized_config_sha256": current.normalized_config_sha256,
            "environment": current.environment,
            "ledger_money_unit": current.ledger_money_unit,
        }
        if any(original.get(key) != value for key, value in pins.items()):
            _blocked("TRANSITION_PLAN_RISK_POLICY_CHANGED")
        baseline = self._baseline.read_baseline_policy(
            account_id=basis.account_id, as_of=as_of
        ).policy
        original_baseline = _object(risk.get("baseline"))
        if baseline is None or baseline.content_sha256 != original_baseline.get("content_sha256"):
            _blocked("TRANSITION_PLAN_BASELINE_POLICY_CHANGED")
        resources = self._resources.read_account_snapshot(
            user_id=basis.owner_user_id,
            account_id=basis.account_id,
            execution_session=basis.execution_session,
            money_unit=basis.money_unit,
        )
        if (
            resources.snapshot is None
            or resources.scope is None
            or not resources.scope.can_write
            or resources.scope.owner_user_id != basis.owner_user_id
            or resources.snapshot.money_unit != basis.money_unit
            or resources.native_account_limits is None
            or resources.reason_codes
        ):
            _blocked("TRANSITION_PLAN_CURRENT_NATIVE_LIMITS_UNAVAILABLE")
        if "native_account_limits" not in inputs:
            _blocked("TRANSITION_PLAN_ORIGINAL_NATIVE_LIMITS_UNAVAILABLE")
        if portfolio_risk_content_hash(
            {"native_account_limits": resources.native_account_limits}
        ) != portfolio_risk_content_hash(
            {"native_account_limits": inputs["native_account_limits"]}
        ):
            _blocked("TRANSITION_PLAN_NATIVE_LIMITS_CHANGED")

    def _verify_calendar(self, revision: TransitionPlanRevision, *, as_of: datetime) -> None:
        basis = revision.basis
        assets: dict[str, PortfolioRiskAssetIdentity] = {}
        for position in (*basis.current_positions, *basis.target_positions):
            if position.security_id is None:
                _blocked("TRANSITION_PLAN_CALENDAR_IDENTITY_UNAVAILABLE")
            asset = PortfolioRiskAssetIdentity(position.asset_code, position.security_id)
            previous = assets.get(position.asset_code)
            if previous is not None and previous != asset:
                _blocked("TRANSITION_PLAN_CALENDAR_IDENTITY_CHANGED")
            assets[position.asset_code] = asset
        if not assets:
            _blocked("TRANSITION_PLAN_CALENDAR_IDENTITY_UNAVAILABLE")
        current = self._calendars.read_calendar(
            PortfolioRiskCalendarReadRequest(
                requested_assets=tuple(assets[key] for key in sorted(assets)),
                requested_session=basis.execution_session,
                as_of=as_of,
            )
        )
        binding = bind_plan_execution_calendar(
            current, prepared_at=as_of, expected_session=basis.execution_session
        )
        original = basis.execution_calendar
        if (
            binding.kind != original.kind
            or binding.content_hash != original.content_hash
            or binding.reference_id != original.reference_id
            or binding.version != original.version
            or binding.effective_at != original.effective_at
            or binding.known_at != original.known_at
        ):
            _blocked("TRANSITION_PLAN_CALENDAR_POLICY_CHANGED")

    def _verify_order(
        self,
        revision: TransitionPlanRevision,
        *,
        order: TransitionPlanOrderBinding,
        member: dict[str, object],
        as_of: datetime,
    ) -> None:
        if (member.get("asset_code"), member.get("security_id")) != (
            order.asset_code,
            order.security_id,
        ):
            _blocked("TRANSITION_PLAN_ORDER_POLICY_SCOPE_CHANGED")
        record = self._rules.execute_record(security_id=order.security_id, as_of=as_of)
        record.__post_init__()
        bundle = record.bundle
        if record.recorded_at > as_of or record.recorded_at != _clock(
            member.get("execution_settlement_recorded_at")
        ):
            _blocked("TRANSITION_PLAN_RULE_KNOWLEDGE_CHANGED")
        if not _same_json(bundle.to_payload(), member.get("execution_settlement_bundle")):
            _blocked("TRANSITION_PLAN_EXECUTION_RULE_CHANGED")
        rule = bundle.execution_submission_v2.execution_rule_v1
        if rule.security_id != order.security_id:
            _blocked("TRANSITION_PLAN_ORDER_POLICY_SCOPE_CHANGED")
        side = SimulatedTradeSide.BUY if order.side == "buy" else SimulatedTradeSide.SELL
        fee = self._fees.get_execution_fee_policy(
            account_id=revision.identity.account_id,
            user_id=revision.identity.owner_user_id,
            asset_type=order.asset_type,
            market=rule.market,
            board=rule.board,
            side=side,
            as_of=as_of,
        )
        if type(fee) is not SimulatedFeePolicyV2:
            _blocked("TRANSITION_PLAN_FEE_POLICY_UNAVAILABLE")
        fee.validate_at(as_of)
        fee.case_for(
            asset_type=order.asset_type,
            market=rule.market,
            board=rule.board,
            side=side,
            as_of=as_of,
        )
        if not _same_json(fee.to_payload(), member.get("fee_policy")):
            _blocked("TRANSITION_PLAN_FEE_POLICY_CHANGED")

    def _verify_classification(
        self, *, order: TransitionPlanOrderBinding, row: dict[str, object], as_of: datetime
    ) -> None:
        retained = _object(row.get("classification_evidence"))
        original = SimulatedInstrumentClassificationEvidenceV1.from_payload(
            retained.get("evidence")
        )
        original.validate_at(as_of=as_of)
        if (
            original.content_hash != retained.get("content_hash")
            or original.content_hash != order.classification_content_hash
            or original.simulated_asset_type != order.asset_type
            or original.identity_evidence.asset_code != order.asset_code
            or original.identity_evidence.security_id != order.security_id
        ):
            _blocked("TRANSITION_PLAN_ORIGINAL_CLASSIFICATION_INVALID")
        current = self._classifications.resolve_simulated_instrument_classification(
            security_id=order.security_id, asset_code=order.asset_code, as_of=as_of
        )
        if type(current) is not SimulatedInstrumentClassificationEvidenceV1:
            _blocked("TRANSITION_PLAN_CURRENT_CLASSIFICATION_UNAVAILABLE")
        current.validate_at(as_of=as_of)
        # Only these two local read clocks may differ. Original source clocks,
        # selector/mapping pins and the persisted original hash remain untouched.
        identity = replace(
            original.identity_evidence,
            selection=replace(
                original.identity_evidence.selection,
                selected_at=current.identity_evidence.selection.selected_at,
            ),
        )
        comparable = replace(original, identity_evidence=identity, read_at=current.read_at)
        if (
            comparable.to_payload() != current.to_payload()
            or current.simulated_asset_type != order.asset_type
        ):
            _blocked("TRANSITION_PLAN_CURRENT_CLASSIFICATION_CHANGED")


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _blocked("TRANSITION_PLAN_PREPARATION_EVIDENCE_INVALID")
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    if type(value) is not list:
        _blocked("TRANSITION_PLAN_PREPARATION_EVIDENCE_INVALID")
    return [_object(item) for item in cast(list[object], value)]


def _text(value: object) -> str:
    if type(value) is not str or not value:
        _blocked("TRANSITION_PLAN_PREPARATION_EVIDENCE_INVALID")
    return value


def _json_object(value: str) -> dict[str, object]:
    try:
        return _object(json.loads(value))
    except (TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            code="TRANSITION_PLAN_PREPARATION_EVIDENCE_INVALID"
        ) from error


def _same_json(left: object, right: object) -> bool:
    return canonical_portfolio_risk_json({"value": left}) == canonical_portfolio_risk_json(
        {"value": right}
    )


def _clock(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("clock must be aware")
        return result
    except (TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            code="TRANSITION_PLAN_RULE_KNOWLEDGE_UNKNOWN"
        ) from error


def _blocked(code: str) -> NoReturn:
    raise SimulatedTradeExecutionBlocked(code=code)
