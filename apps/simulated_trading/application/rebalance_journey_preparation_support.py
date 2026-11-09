"""Strict serialization and typed helper functions for rebalance preparation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal
from typing import cast

from apps.portfolio.domain.transition_plan_revision_basis import (
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanRiskBinding,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetInputs
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyBundle
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.risk_center.domain.portfolio_risk_snapshot import AccountSnapshot
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.domain.rebalance_preview_math import calculate_asset_adjustment


def _preparation_evidence(
    *,
    basis_values: dict[str, object],
    portfolio_resources: dict[str, object],
    decision_payload: dict[str, object],
    target_payload: dict[str, object],
    source_payloads: list[dict[str, object]],
) -> dict[str, object]:
    """Build the canonical, self-contained evidence block validated by Basis."""

    planning_policy = cast(TransitionPlanPolicyBinding, basis_values["planning_policy"])
    risk = cast(TransitionPlanRiskBinding, basis_values["risk"])
    fee_policy = cast(TransitionPlanPolicyBinding, basis_values["fee_policy"])
    quantity_rule = cast(TransitionPlanPolicyBinding, basis_values["quantity_rule"])
    settlement_rule = cast(TransitionPlanPolicyBinding, basis_values["settlement_rule"])
    execution_calendar = cast(TransitionPlanPolicyBinding, basis_values["execution_calendar"])
    current_positions = cast(
        tuple[TransitionPlanPositionBinding, ...], basis_values["current_positions"]
    )
    target_positions = cast(
        tuple[TransitionPlanPositionBinding, ...], basis_values["target_positions"]
    )
    business_date = cast(date, basis_values["business_date"])
    execution_session = cast(date, basis_values["execution_session"])
    return {
        "schema": "ash08.plan_preparation.v1",
        "portfolio_snapshot": {
            "id": basis_values["portfolio_snapshot_id"],
            "content_hash": basis_values["portfolio_snapshot_hash"],
            "source_evidence_hash": basis_values["portfolio_source_evidence_hash"],
            "as_of": _datetime_text(cast(datetime, basis_values["portfolio_snapshot_as_of"])),
            "resources": portfolio_resources,
        },
        "decision_snapshot": {
            "id": basis_values["decision_snapshot_id"],
            "content_hash": basis_values["decision_snapshot_hash"],
            "payload": decision_payload,
        },
        "target": {
            "id": basis_values["target_portfolio_id"],
            "content_hash": basis_values["target_content_hash"],
            "selection_id": basis_values["selection_id"],
            "selection_hash": basis_values["selection_hash"],
            "payload": target_payload,
        },
        "policy_bindings": {
            "planning_policy": planning_policy.to_payload(),
            "fee_policy": fee_policy.to_payload(),
            "quantity_rule": quantity_rule.to_payload(),
            "settlement_rule": settlement_rule.to_payload(),
            "execution_calendar": execution_calendar.to_payload(),
        },
        "risk": risk.to_payload(),
        "source_bindings": source_payloads,
        "positions": {
            "current": [item.to_payload() for item in current_positions],
            "target": [item.to_payload() for item in target_positions],
        },
        "business_date": business_date.isoformat(),
        "execution_session": execution_session.isoformat(),
        "prepared_at": _datetime_text(cast(datetime, basis_values["prepared_at"])),
    }


def _composite_policy_binding(
    *,
    kind: str,
    members: dict[str, dict[str, object]],
    clocks: list[tuple[datetime, datetime, datetime]],
    prepared_at: datetime,
) -> TransitionPlanPolicyBinding:
    """Bind a deterministic readonly set of real per-instrument policies."""

    ordered = [members[key] for key in sorted(members)]
    if not ordered or not clocks:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_POLICY_SET_EMPTY")
    effective = max(item[0] for item in clocks)
    known = max(item[1] for item in clocks)
    valid_until = min(item[2] for item in clocks)
    if effective > prepared_at or known > prepared_at or valid_until <= prepared_at:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_POLICY_SET_OUTSIDE_CUTOFF")
    content_hash = portfolio_risk_content_hash({"policy_members": ordered})
    return TransitionPlanPolicyBinding(
        kind=kind,
        status="qualified",
        reference_id=f"policy-set:{content_hash}",
        version="composite-policy-set",
        content_hash=content_hash,
        effective_at=effective,
        known_at=known,
        valid_until=valid_until,
    )


def _policy_payload(policy: PortfolioRiskPolicyBundle) -> dict[str, object]:
    """Retain the full actual ConfigCenter profile/snapshot identity and clocks."""

    return {
        "schema_version": policy.schema_version,
        "scope": policy.scope,
        "ledger_money_unit": policy.ledger_money_unit,
        "account_ids": list(policy.account_ids),
        "industry_policy": _json_safe(policy.industry_policy),
        "capacity_policy": _json_safe(policy.capacity_policy),
        "source_max_timestamp_age_seconds": policy.source_max_timestamp_age_seconds,
        "source_max_date_age_days": policy.source_max_date_age_days,
        "source_references": _json_safe(policy.source_references),
        "environment": policy.environment,
        "profile_id": policy.profile_id,
        "profile_key": policy.profile_key,
        "profile_version": policy.profile_version,
        "profile_content_hash": policy.profile_content_hash,
        "snapshot_id": policy.snapshot_id,
        "snapshot_hash": policy.snapshot_hash,
        "normalized_config_sha256": policy.normalized_config_sha256,
        "created_at": _datetime_text(policy.created_at),
        "known_at": _datetime_text(policy.known_at),
        "activated_at": _datetime_text(policy.activated_at),
        "snapshot_generated_at": _datetime_text(policy.snapshot_generated_at),
        "effective_at": _datetime_text(policy.effective_at),
        "business_date": policy.business_date.isoformat(),
        "as_of": _datetime_text(policy.as_of),
        "etf_report_policy": _json_safe(policy.etf_report_policy),
    }


def _asset_map(prepared: PreparedPortfolioRisk) -> dict[tuple[str, str], PortfolioRiskAssetInputs]:
    """Index source inputs by exact pair and reject ambiguous duplicate rows."""

    result: dict[tuple[str, str], PortfolioRiskAssetInputs] = {}
    for asset in prepared.assets.assets:
        if asset.security_id is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ASSET_SECURITY_UNKNOWN")
        key = (asset.asset_code, asset.security_id)
        if key in result:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ASSET_INPUT_AMBIGUOUS")
        result[key] = asset
    return result


def _asset_rows(preview: RebalancePlanPreview) -> tuple[RebalancePlanPreviewItem, ...]:
    """Select only instrument rows, excluding amount-only allocation rows."""

    rows = tuple(item for item in preview.asset_items if item.scope == "asset")
    if any(type(item) is not RebalancePlanPreviewItem for item in rows):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PREVIEW_ROW_INVALID")
    return rows


def _unique_rows_by_code(
    rows: tuple[RebalancePlanPreviewItem, ...],
) -> dict[str, RebalancePlanPreviewItem]:
    """Require the selected rebalance contract to be ticker-unique."""

    result: dict[str, RebalancePlanPreviewItem] = {}
    for row in rows:
        if row.asset_code in result:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PREVIEW_ASSET_AMBIGUOUS")
        result[row.asset_code] = row
    return result


def _identity_security_id(identity: dict[str, object] | None) -> str | None:
    """Narrow a captured M1 identity to its exact instrument security ID."""

    if identity is None:
        return None
    value = identity.get("security_id")
    return value if type(value) is str and value else None


def _json_safe(value: object) -> object:
    """Round-trip one exact typed object through the public lossless risk serializer."""

    decoded = json.loads(canonical_portfolio_risk_json({"value": value}))
    if type(decoded) is not dict:
        raise TypeError("canonical serializer did not return an object")
    return decoded["value"]


def _preview_evidence_json(preview: RebalancePlanPreview) -> object:
    """Retain the preview while tagging only its legacy pulse binary64 score."""

    pulse = preview.risk_context.pulse
    if pulse is None:
        return _json_safe(preview)
    score = pulse.get("composite_score")
    if type(score) is not float:
        return _json_safe(preview)
    if not math.isfinite(score):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PULSE_SCORE_INVALID")
    retained_pulse = dict(pulse)
    retained_pulse["composite_score"] = {
        "kind": "pulse_composite_score",
        "encoding": "python-float-hex-v1",
        "value": score.hex(),
    }
    retained_context = replace(
        preview.risk_context,
        pulse=retained_pulse,
    )
    return _json_safe(replace(preview, risk_context=retained_context))


def _json_object(value: object, name: str) -> dict[str, object]:
    """Narrow one M1 JSON boundary object without accepting arbitrary shapes."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise RebalanceJourneyUnavailable(
            code=f"REBALANCE_PLAN_{name.upper().replace(' ', '_')}_INVALID"
        )
    return cast(dict[str, object], value)


def _parse_mapping(value: str, name: str) -> dict[str, object]:
    """Decode one canonical JSON document and require an object root."""

    try:
        decoded: object = json.loads(value)
    except (TypeError, ValueError) as error:
        raise RebalanceJourneyUnavailable(
            code=f"REBALANCE_PLAN_{name.upper().replace(' ', '_')}_INVALID"
        ) from error
    return _json_object(decoded, name)


def _string(value: object, name: str) -> str:
    """Require one nonempty trimmed token from a typed payload boundary."""

    if type(value) is not str or not value or value.strip() != value:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVIDENCE_FIELD_INVALID")
    return value


def _required_digest(value: str, name: str) -> str:
    """Require an unprefixed lowercase SHA-256 digest."""

    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVIDENCE_DIGEST_INVALID")
    return value


def _required_unit(value: str | None, name: str) -> str:
    """Keep configured units explicit and reject missing unit evidence."""

    if value is None or not value or value.strip() != value:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_UNIT_UNKNOWN")
    return value


def _decimal(value: str, name: str) -> Decimal:
    """Parse one finite exact decimal string without accepting floats."""

    try:
        result = Decimal(value)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_DECIMAL_INVALID") from error
    if not result.is_finite():
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_DECIMAL_INVALID")
    return result


@dataclass(frozen=True, slots=True)
class _WholeShareTargetQuantity:
    """Retain an exact theoretical target difference and its whole-share derivation."""

    suggested_quantity: Decimal
    requested_quantity: int
    fractional_remainder: Decimal

    def to_payload(self) -> dict[str, object]:
        """Return the exact derivation for inclusion in the immutable plan evidence."""

        return {
            "basis": "theoretical_target_difference",
            "suggested_quantity": str(self.suggested_quantity),
            "requested_whole_share_quantity": self.requested_quantity,
            "fractional_remainder": str(self.fractional_remainder),
            "rounding_rule": "floor_to_whole_share",
        }


def _derive_whole_share_target_quantity(value: Decimal | None) -> _WholeShareTargetQuantity:
    """Floor a finite nonnegative theoretical difference and retain its exact remainder."""

    if value is None or type(value) is not Decimal or not value.is_finite() or value < 0:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_UNKNOWN")
    whole_share_quantity = int(value.to_integral_value(rounding=ROUND_DOWN))
    remainder = value - Decimal(whole_share_quantity)
    return _WholeShareTargetQuantity(
        suggested_quantity=value,
        requested_quantity=whole_share_quantity,
        fractional_remainder=remainder,
    )


def _whole_share_quantity(value: Decimal | None, name: str) -> int:
    """Require exact nonnegative whole shares; never truncate a fractional request."""

    if value is None or type(value) is not Decimal or not value.is_finite() or value < 0:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_UNKNOWN")
    if value != value.to_integral_value():
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_NOT_WHOLE")
    return int(value)


def _parse_datetime(value: object, name: str) -> datetime:
    """Decode one explicit aware publication timestamp without date coercion."""

    if type(value) is not str:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_CLOCK_UNKNOWN")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_CLOCK_INVALID") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_CLOCK_UNKNOWN")
    return result


def _minimum_deadline(values: tuple[datetime | None, ...]) -> datetime | None:
    """Return the earliest explicit deadline while preserving absent ends."""

    concrete = tuple(value for value in values if value is not None)
    if not concrete:
        return None
    return min(concrete)


def _datetime_text(value: datetime | None) -> str | None:
    """Serialize a real aware instant while preserving unknown as null."""

    if value is None:
        return None
    _require_aware(value, "datetime")
    return value.isoformat()


def _require_aware(value: datetime, name: str) -> None:
    """Reject naive times at every public Application boundary."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CLOCK_UNKNOWN")


def _portfolio_resources(
    preview: RebalancePlanPreview,
    prepared: PreparedPortfolioRisk,
) -> dict[str, object]:
    """Retain the real account resource snapshot and both independent read clocks."""

    return {
        "scope": "simulation_only",
        "account_snapshot": _json_safe(prepared.snapshot),
        "resource_read_result": _json_safe(prepared.resources),
        "identity_bindings": _json_safe(prepared.identity_bindings),
        "preview_financial_snapshot_read_at": _datetime_text(preview.financial_snapshot_read_at),
        "risk_snapshot_read_at": _datetime_text(prepared.snapshot.read_at),
    }


def _decision_payload(
    *,
    preview: RebalancePlanPreview,
    prepared: PreparedPortfolioRisk,
    business_timezone: str,
    portfolio_snapshot_id: str,
    portfolio_snapshot_hash: str,
    target_portfolio_id: str,
    target_content_hash: str,
    selection_id: str,
    selection_hash: str,
    source_payloads: list[dict[str, object]],
    order_policy_members: list[dict[str, object]],
    order_specifications: list[dict[str, object]],
    positions: dict[str, object],
    risk_binding: dict[str, object],
    calendar_binding: dict[str, object],
    policy_bindings: dict[str, object],
) -> dict[str, object]:
    """Retain complete captured preview/risk inputs under exact target pins."""

    policy = prepared.policy
    if policy is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_POLICY_MISSING")
    return {
        "scope": "simulation_only",
        "business_timezone": business_timezone,
        "portfolio_snapshot_id": portfolio_snapshot_id,
        "portfolio_snapshot_hash": portfolio_snapshot_hash,
        "target_portfolio_id": target_portfolio_id,
        "target_content_hash": target_content_hash,
        "selection_id": selection_id,
        "selection_hash": selection_hash,
        "preview": _preview_evidence_json(preview),
        "prepared_risk": {
            "input_snapshot_json": prepared.input_snapshot_json,
            "report": _json_safe(prepared.report),
            "assessment": _json_safe(prepared.assessment),
            "source_bindings": source_payloads,
            "policy": _policy_payload(policy),
            "baseline": _json_safe(prepared.baseline_source.policy),
            "calendar": _json_safe(prepared.calendar),
            "order_policy_members": order_policy_members,
            "order_specifications": order_specifications,
            "positions": positions,
            "risk_binding": risk_binding,
            "calendar_binding": calendar_binding,
            "policy_bindings": policy_bindings,
        },
    }


def build_plan_risk_binding(
    prepared: PreparedPortfolioRisk,
    source_payloads: list[dict[str, object]],
) -> TransitionPlanRiskBinding:
    """Bind one qualified report to the exact policy, native caps, baseline, and sources."""

    policy = prepared.policy
    baseline = prepared.baseline_source.policy
    if policy is None or baseline is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_POLICY_MISSING")
    report_payload = cast(dict[str, object], _json_safe(prepared.report))
    report_hash = portfolio_risk_content_hash(report_payload)
    binding_hash = portfolio_risk_content_hash(
        {
            "policy": _policy_payload(policy),
            "policy_binding_sha256": prepared.policy_binding_sha256,
            "native_limits_sha256": prepared.native_limits_sha256,
            "risk_input_hash": prepared.report.get("resource_snapshot_hash"),
            "baseline": _json_safe(baseline),
            "source_bindings": source_payloads,
            "report_hash": report_hash,
        }
    )
    return TransitionPlanRiskBinding(
        report_content_hash=report_hash,
        binding_hash=binding_hash,
        outcome="allowed",
        must_not_use_for_decision=False,
    )


def verify_preview_asset_math(
    preview: RebalancePlanPreview,
    code_to_asset: dict[str, PortfolioRiskAssetInputs],
) -> None:
    """Require qualified source prices to reproduce captured M1 numeric rows."""

    for row in _asset_rows(preview):
        asset = code_to_asset.get(row.asset_code)
        if asset is None:
            continue
        # The preview uses a display label while Risk stores the canonical unit.
        preview_quantity_unit = (
            "share"
            if row.asset_type == "equity" and row.quantity_unit == "shares"
            else row.quantity_unit
        )
        if (
            asset.price is None
            or asset.price_unit is None
            or row.reference_price is None
            or row.reference_price != asset.price
            or preview_quantity_unit != asset.quantity_unit
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_REFERENCE_BASIS_MISMATCH")
        adjustment = calculate_asset_adjustment(
            current_quantity=row.current_quantity,
            reference_price=asset.price,
            portfolio_value=row.portfolio_value,
            target_weight=row.target_weight,
            drift_threshold=row.drift_threshold,
        )
        if adjustment is None:
            if any(
                value is not None
                for value in (
                    row.current_amount,
                    row.current_weight,
                    row.target_amount,
                    row.target_quantity,
                    row.suggested_amount,
                    row.suggested_quantity,
                )
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PREVIEW_MATH_MISMATCH")
            continue
        if (
            adjustment.current_amount != row.current_amount
            or adjustment.current_weight != row.current_weight
            or adjustment.target_amount != row.target_amount
            or adjustment.target_quantity != row.target_quantity
            or adjustment.suggested_amount != row.suggested_amount
            or adjustment.suggested_quantity != row.suggested_quantity
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PREVIEW_MATH_MISMATCH")


def bind_plan_execution_calendar(
    calendar: PortfolioRiskCalendarReadResult,
    *,
    prepared_at: datetime,
    expected_session: date | None = None,
) -> TransitionPlanPolicyBinding:
    """Bind one qualified published calendar using its original member clocks."""

    _require_aware(prepared_at, "prepared_at")
    if (
        not calendar.requested_session_qualified
        or calendar.reason_codes
        or calendar.open_sessions is None
        or calendar.canonical_evidence_json is None
        or calendar.evidence_hash is None
        or calendar.valid_until is None
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_EVIDENCE_MISSING")
    document = _parse_mapping(calendar.canonical_evidence_json, "calendar evidence")
    if (
        hashlib.sha256(calendar.canonical_evidence_json.encode("utf-8")).hexdigest()
        != calendar.evidence_hash
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_HASH_MISMATCH")
    as_of = _parse_datetime(document.get("as_of"), "calendar cutoff")
    requested_session_value = document.get("requested_session")
    if type(requested_session_value) is not str:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_SESSION_UNKNOWN")
    try:
        requested_session = date.fromisoformat(requested_session_value)
    except ValueError as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_SESSION_INVALID") from error
    if requested_session.isoformat() != requested_session_value:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_SESSION_INVALID")
    if expected_session is not None and requested_session != expected_session:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_SESSION_MISMATCH")
    if requested_session not in calendar.open_sessions or calendar.valid_until <= prepared_at:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_SESSION_UNQUALIFIED")
    if as_of > prepared_at:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_CLOCK_INVALID")
    rows = document.get("calendar_evidence")
    if type(rows) is not list or not rows:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_PUBLICATION_MISSING")
    members: list[dict[str, object]] = []
    known: list[datetime] = []
    effective: list[datetime] = []
    expiries: list[datetime] = []
    for value in cast(list[object], rows):
        member = _json_object(value, "calendar evidence member")
        publication = _json_object(member.get("publication"), "calendar publication")
        snapshot = _json_object(member.get("snapshot"), "calendar snapshot")
        publication_id = _string(publication.get("publication_id"), "calendar publication ID")
        _string(publication.get("member_id"), "calendar member ID")
        _required_digest(
            _string(publication.get("policy_hash"), "calendar policy hash"),
            "calendar policy hash",
        )
        member_evidence_hash = _required_digest(
            _string(member.get("evidence_hash"), "calendar member evidence hash"),
            "calendar member evidence hash",
        )
        timezone_name = _string(publication.get("timezone_name"), "calendar timezone")
        published_at = _parse_datetime(publication.get("published_at"), "published_at")
        recorded_at = _parse_datetime(publication.get("recorded_at"), "recorded_at")
        reference_from = _parse_datetime(
            publication.get("reference_valid_from"), "reference_valid_from"
        )
        reference_until = _parse_datetime(
            publication.get("reference_valid_until"), "reference_valid_until"
        )
        if published_at > recorded_at or reference_from > as_of or recorded_at > as_of:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_CLOCK_INVALID")
        if reference_until <= prepared_at:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_EXPIRED")
        requested_exchange = member.get("requested_exchange")
        if type(requested_exchange) is not str or snapshot.get("exchange") != requested_exchange:
            raise RebalanceJourneyUnavailable(
                code="REBALANCE_PLAN_CALENDAR_MEMBER_IDENTITY_MISSING"
            )
        members.append(
            {
                "publication": publication,
                "snapshot": snapshot,
                "requested_exchange": requested_exchange,
                "evidence_hash": member_evidence_hash,
                "timezone_name": timezone_name,
            }
        )
        known.append(recorded_at)
        effective.append(reference_from)
        expiries.append(reference_until)
        _string(publication_id, "calendar publication ID")
    group_hash = portfolio_risk_content_hash(
        {
            "requested_session": requested_session.isoformat(),
            "published_calendar_members": members,
        }
    )
    valid_until = (
        min((*expiries, calendar.valid_until))
        if calendar.valid_until is not None
        else min(expiries)
    )
    if valid_until <= prepared_at:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CALENDAR_EXPIRED")
    return TransitionPlanPolicyBinding(
        kind="published_execution_calendar_set",
        status="qualified",
        reference_id=f"calendar-set:{group_hash}",
        version="published-reference-set",
        content_hash=group_hash,
        effective_at=max(effective),
        known_at=max(known),
        valid_until=valid_until,
    )


def verify_preview_resources(
    preview: RebalancePlanPreview,
    snapshot: AccountSnapshot,
) -> None:
    """Compare distinct preview and risk reads by exact cash and quantities."""

    if preview.cash_before is None or preview.cash_before != snapshot.cash:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CASH_READ_MISMATCH")
    holdings_by_code: dict[str, list[Decimal]] = {}
    for holding in snapshot.holdings:
        holdings_by_code.setdefault(holding.asset_code, []).append(holding.quantity)
    for row in _asset_rows(preview):
        quantities = holdings_by_code.get(row.asset_code, [])
        if len(quantities) > 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_HOLDING_IDENTITY_AMBIGUOUS")
        expected = quantities[0] if quantities else Decimal("0")
        if row.current_quantity is None or row.current_quantity != expected:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_POSITION_READ_MISMATCH")


def resolve_plan_target_assets(
    *,
    prepared: PreparedPortfolioRisk,
    rows: tuple[RebalancePlanPreviewItem, ...],
    asset_by_pair: dict[tuple[str, str], PortfolioRiskAssetInputs],
    targets: dict[str, str],
    source_payloads: list[dict[str, object]],
) -> dict[str, PortfolioRiskAssetInputs]:
    """Resolve every target ticker to a single source-bound security identity."""

    output: dict[str, PortfolioRiskAssetInputs] = {}
    identity_by_code: dict[str, list[PortfolioRiskIdentityBinding]] = {}
    for binding in prepared.identity_bindings:
        identity_by_code.setdefault(binding.asset_code, []).append(binding)
    requested_codes = set(targets)
    requested_codes.update(holding.asset_code for holding in prepared.snapshot.holdings)
    requested_codes.update(
        row.asset_code
        for row in rows
        if row.action in {"buy", "sell"}
        and row.suggested_quantity is not None
        and row.suggested_quantity > 0
    )
    for code in sorted(requested_codes):
        matching_rows = [row for row in rows if row.asset_code == code]
        if not matching_rows and code in targets:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_ASSET_MISSING")
        direct_ids = {
            security_id
            for row in matching_rows
            if (security_id := _identity_security_id(row.identity)) is not None
        }
        pinned_ids = {binding.source_security_id for binding in identity_by_code.get(code, [])}
        held_ids = {
            holding.security_id
            for holding in prepared.snapshot.holdings
            if holding.asset_code == code and holding.security_id is not None
        }
        if len(direct_ids) > 1 or len(pinned_ids) > 1 or len(held_ids) > 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_AMBIGUOUS")
        identity_candidates = direct_ids | pinned_ids | held_ids
        if len(identity_candidates) > 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_CONFLICT")
        candidate_id = next(iter(identity_candidates), None)
        candidates = [
            asset
            for (asset_code, _), asset in asset_by_pair.items()
            if asset_code == code and (candidate_id is None or asset.security_id == candidate_id)
        ]
        if len(candidates) != 1 or candidates[0].security_id is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_UNRESOLVED")
        selected = candidates[0]
        exact_bindings = [
            binding
            for binding in identity_by_code.get(code, [])
            if binding.source_security_id == selected.security_id
        ]
        matching_holdings = [
            holding for holding in prepared.snapshot.holdings if holding.asset_code == code
        ]
        if matching_holdings and len(exact_bindings) != 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_UNBOUND")
        if matching_holdings:
            holding = matching_holdings[0]
            binding = exact_bindings[0]
            expected_basis = (
                "ledger" if holding.security_id is not None else "pinned_policy_source_mapping"
            )
            if (
                binding.basis != expected_basis
                or binding.ledger_security_id != holding.security_id
                or binding.source_security_id != selected.security_id
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_UNBOUND")
        elif not matching_rows:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_IDENTITY_UNBOUND")
        if selected.price is None or selected.price <= 0 or not selected.price_unit:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_UNKNOWN")
        policy = prepared.policy
        if policy is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_POLICY_MISSING")
        if selected.price_unit != policy.ledger_money_unit:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_UNIT_MISMATCH")
        evidence = selected.valuation_evidence
        if evidence is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_SOURCE_MISSING")
        code_valuation_refs = [
            reference
            for reference in prepared.assets.source_reference_bindings
            if reference.kind == "valuation" and reference.asset_code == code
        ]
        if (
            len(code_valuation_refs) != 1
            or code_valuation_refs[0].security_id != selected.security_id
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_REFERENCE_AMBIGUOUS")
        valuation = [
            source
            for source in prepared.assets.all_source_evidence
            if source.source_record_id == evidence.source_record_id
        ]
        if selected.valuation_evidence is None or len(valuation) != 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_SOURCE_MISSING")
        valuation_refs = [
            reference
            for reference in prepared.assets.source_reference_bindings
            if reference.kind == "valuation"
            and reference.asset_code == code
            and reference.security_id == selected.security_id
        ]
        if (
            len(valuation_refs) != 1
            or valuation_refs[0].source_record_id != evidence.source_record_id
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_REFERENCE_MISMATCH")
        bound_valuation = [
            source
            for source in source_payloads
            if source.get("kind") == "valuation"
            and source.get("asset_code") == code
            and source.get("security_id") == selected.security_id
        ]
        if (
            len(bound_valuation) != 1
            or bound_valuation[0].get("source_record_id") != evidence.source_record_id
            or bound_valuation[0].get("source_id") != evidence.source_id
            or bound_valuation[0].get("body_sha256") != evidence.original_payload_sha256
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_BODY_BINDING_MISMATCH")
        for row in matching_rows:
            if row.reference_price is not None and row.reference_price != selected.price:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_REFERENCE_PRICE_MISMATCH")
        output[code] = selected
    return output
