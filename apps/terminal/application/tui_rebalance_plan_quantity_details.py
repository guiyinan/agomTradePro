"""Project exact whole-share derivations retained in saved plan evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from typing import TypedDict, cast

from apps.terminal.application.tui_account_inspection_result import _REASON_LABELS


class PlanQuantityDetailField(TypedDict):
    """Carry one formatted, safe plan quantity detail into a TUI result."""

    key: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class _QuantityDerivation:
    """Hold a derivation only after its exact revision, order and arithmetic match."""

    theoretical_text: str
    requested_quantity: int
    remainder_text: str
    remainder: Decimal


def project_plan_quantity_detail_fields(
    plan: Mapping[str, object],
    order: Mapping[str, object],
    *,
    field_index: int,
) -> list[PlanQuantityDetailField]:
    """Render a saved order's exact derivation or a bounded unknown marker.

    The helper reads only the canonical preparation evidence embedded in the
    immutable plan basis. It never recomputes a target from positions or changes
    an order quantity, status, or execution capability.
    """

    basis = _mapping(plan.get("basis"))
    ordinal = _integer(order.get("ordinal"))
    derivation = (
        _validated_derivation(basis, order, ordinal=ordinal)
        if basis is not None and ordinal is not None
        else None
    )
    if derivation is None:
        return [
            _field(
                f"order_{field_index}_quantity_derivation",
                "目标差量与整股请求",
                "未知；本版本没有可匹配的取整证据。",
            )
        ]

    unit = _string(order.get("quantity_unit")) or "数量单位未知"
    result = [
        _field(
            f"order_{field_index}_theoretical_quantity",
            "原理论差量（取整前）",
            f"{derivation.theoretical_text} {unit}",
        ),
        _field(
            f"order_{field_index}_whole_share_request",
            "整股请求",
            f"{derivation.requested_quantity} {unit}",
        ),
        _field(
            f"order_{field_index}_fractional_remainder",
            "非整股余差",
            f"{derivation.remainder_text} {unit}",
        ),
    ]
    explanation = _rounding_explanation(order, derivation, unit)
    if explanation is not None:
        result.append(_field(f"order_{field_index}_quantity_rounding", "差量说明", explanation))
    return result


def _validated_derivation(
    basis: Mapping[str, object], order: Mapping[str, object], *, ordinal: int
) -> _QuantityDerivation | None:
    evidence_text = basis.get("preparation_evidence_json")
    if type(evidence_text) is not str or not evidence_text:
        return None
    try:
        decoded: object = json.loads(evidence_text)
    except (TypeError, ValueError):
        return None
    evidence = _mapping(decoded)
    if evidence is None or evidence.get("schema") != "ash08.plan_preparation.v1":
        return None
    try:
        canonical = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    if canonical != evidence_text:
        return None

    decision = _mapping(basis.get("decision"))
    evidence_decision = _mapping(evidence.get("decision_snapshot"))
    decision_id = _string(decision.get("id")) if decision else None
    decision_hash = _sha256(decision.get("content_hash")) if decision else None
    evidence_decision_id = _string(evidence_decision.get("id")) if evidence_decision else None
    evidence_decision_hash = (
        _sha256(evidence_decision.get("content_hash")) if evidence_decision else None
    )
    if (
        decision is None
        or evidence_decision is None
        or decision_id is None
        or decision_hash is None
        or evidence_decision_id is None
        or evidence_decision_hash is None
        or evidence_decision_id != decision_id
        or evidence_decision_hash != decision_hash
    ):
        return None
    payload = _mapping(evidence_decision.get("payload"))
    prepared_risk = _mapping(payload.get("prepared_risk")) if payload else None
    members = prepared_risk.get("order_policy_members") if prepared_risk else None
    if not isinstance(members, list):
        return None
    ordinal_members = tuple(
        member
        for member in members
        if (candidate := _mapping(member)) is not None
        and type(candidate.get("ordinal")) is int
        and candidate.get("ordinal") == ordinal
    )
    if len(ordinal_members) != 1:
        return None
    member = _mapping(ordinal_members[0])
    asset_code = _string(order.get("asset_code"))
    security_id = _string(order.get("security_id"))
    side = order.get("side")
    if (
        member is None
        or type(order.get("ordinal")) is not int
        or order.get("ordinal") != ordinal
        or asset_code is None
        or security_id is None
        or type(side) is not str
        or side not in {"buy", "sell"}
        or member.get("ordinal") != ordinal
        or member.get("asset_code") != asset_code
        or member.get("security_id") != security_id
        or member.get("side") != side
    ):
        return None
    raw_derivation = _mapping(member.get("target_quantity_derivation"))
    if raw_derivation is None:
        return None

    requested = raw_derivation.get("requested_whole_share_quantity")
    ordered_requested = order.get("requested_quantity")
    approved = order.get("approved_quantity")
    unapproved = order.get("unapproved_quantity")
    if (
        raw_derivation.get("basis") != "theoretical_target_difference"
        or raw_derivation.get("rounding_rule") != "floor_to_whole_share"
        or type(requested) is not int
        or requested < 0
        or type(ordered_requested) is not int
        or type(approved) is not int
        or type(unapproved) is not int
        or approved < 0
        or unapproved < 0
        or requested != ordered_requested
        or ordered_requested != approved + unapproved
    ):
        return None
    suggested_text = raw_derivation.get("suggested_quantity")
    remainder_text = raw_derivation.get("fractional_remainder")
    suggested = _finite_nonnegative_decimal(suggested_text)
    remainder = _finite_nonnegative_decimal(remainder_text)
    if suggested is None or remainder is None or remainder >= Decimal("1"):
        return None
    try:
        if suggested.to_integral_value(rounding=ROUND_FLOOR) != Decimal(requested):
            return None
        precision = max(
            28,
            len(suggested.as_tuple().digits)
            + len(remainder.as_tuple().digits)
            + len(str(requested))
            + 8,
        )
        with localcontext() as context:
            context.prec = precision
            if suggested - Decimal(requested) != remainder:
                return None
    except (InvalidOperation, ValueError, OverflowError):
        return None
    if not Decimal(0) <= remainder < Decimal(1):
        return None
    return _QuantityDerivation(
        theoretical_text=cast(str, suggested_text),
        requested_quantity=requested,
        remainder_text=cast(str, remainder_text),
        remainder=remainder,
    )


def _rounding_explanation(
    order: Mapping[str, object], derivation: _QuantityDerivation, unit: str
) -> str | None:
    side = order.get("side")
    reason = (
        "SELL_QUANTITY_STEP_ROUNDED_DOWN"
        if side == "sell"
        else "BUY_QUANTITY_STEP_ROUNDED_DOWN" if side == "buy" else None
    )
    reasons = order.get("reason_codes")
    label = (
        _REASON_LABELS.get(reason)
        if reason is not None and isinstance(reasons, list) and reason in reasons
        else None
    )
    unapproved = order.get("unapproved_quantity")
    if derivation.remainder > 0:
        if unapproved == 0:
            remainder_note = (
                f"整股未办理量为 0，但非整股余差仍有 {derivation.remainder_text} {unit}；"
                "这不表示目标已完成。"
            )
        else:
            remainder_note = (
                f"本版本尚有 {unapproved} {unit} 整股未办理量，另有非整股余差 "
                f"{derivation.remainder_text} {unit}；目标仍需按当前事实核对。"
            )
        return f"{label}；{remainder_note}" if label is not None else remainder_note
    return label


def _finite_nonnegative_decimal(value: object) -> Decimal | None:
    if type(value) is not str or not value or len(value) > 512:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed.is_signed() or str(parsed) != value:
        return None
    return parsed


def _mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _integer(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _string(value: object) -> str | None:
    return value if type(value) is str and value.strip() == value and value else None


def _sha256(value: object) -> str | None:
    text = _string(value)
    if (
        text is None
        or len(text) != 64
        or any(character not in "0123456789abcdef" for character in text)
    ):
        return None
    return text


def _field(key: str, label: str, value: str) -> PlanQuantityDetailField:
    return {"key": key, "label": label, "value": value}
