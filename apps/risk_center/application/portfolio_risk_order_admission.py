"""Adapt report checks to the public direction-aware order-admission contract."""

from __future__ import annotations

from typing import Literal

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskOrderAdmissionPayload,
    PortfolioRiskOrderDecisionPayload,
    PortfolioRiskReportPayload,
)
from apps.risk_center.domain.portfolio_risk_order_admission import (
    PortfolioRiskAdmissionCheck,
    PortfolioRiskOrderAdmission,
    PortfolioRiskOrderAdmissionOutcome,
    PortfolioRiskOrderSide,
    assess_portfolio_risk_order_admission,
)


def build_portfolio_risk_order_admission(
    *,
    subjects: tuple[tuple[str, Literal["buy", "sell"]], ...],
    checks: tuple[PortfolioRiskCheckPayload, ...],
    must_not_use_for_decision: bool,
    subject_id: str | None = None,
) -> PortfolioRiskOrderAdmissionPayload:
    """Evaluate each proposal direction while preserving the shared report checks."""

    if (
        type(subjects) is not tuple
        or not subjects
        or any(
            type(order_id) is not str or not order_id.strip() or side not in {"buy", "sell"}
            for order_id, side in subjects
        )
    ):
        raise ValueError("subjects must bind order IDs to BUY or SELL")
    if subject_id is not None and (type(subject_id) is not str or not subject_id.strip()):
        raise ValueError("subject_id must be a nonempty string or None")
    domain_checks = _domain_checks(checks)
    decisions = tuple(
        assess_portfolio_risk_order_admission(
            side=side,
            checks=domain_checks,
            must_not_use_for_decision=must_not_use_for_decision,
        )
        for _order_id, side in subjects
    )
    item_payloads: list[PortfolioRiskOrderDecisionPayload] = [
        {
            "order_id": order_id,
            "side": side,
            "outcome": decision.outcome,
            "reason_codes": list(decision.reason_codes),
            "waived_reason_codes": list(decision.waived_reason_codes),
        }
        for (order_id, side), decision in zip(subjects, decisions, strict=True)
    ]
    aggregate = _aggregate_decisions(decisions)
    sides = {side for _order_id, side in subjects}
    admission_side: PortfolioRiskOrderSide = next(iter(sides)) if len(sides) == 1 else "mixed"
    return {
        "side": admission_side,
        "order_ids": [order_id for order_id, _side in subjects],
        "subject_id": subject_id,
        "outcome": aggregate.outcome,
        "reason_codes": list(aggregate.reason_codes),
        "waived_reason_codes": list(aggregate.waived_reason_codes),
        "decisions": item_payloads,
    }


def portfolio_risk_order_admission_is_effective(
    report: PortfolioRiskReportPayload,
    *,
    subject_id: str | None = None,
    side: Literal["buy", "sell"] | None = None,
    order_ids: tuple[str, ...] | None = None,
) -> bool:
    """Verify the public admission against its report checks and exact subject."""

    admission = report.get("order_admission")
    if (
        report.get("scope") != "simulation_only"
        or report.get("must_not_use_for_decision") is not False
        or report.get("outcome") not in {"allowed", "blocked"}
        or report.get("must_not_execute") is not True
        or not isinstance(admission, dict)
    ):
        return False
    if subject_id is not None and admission.get("subject_id") != subject_id:
        return False
    payload_subject_id = admission.get("subject_id")
    if payload_subject_id is not None and (
        type(payload_subject_id) is not str or not payload_subject_id.strip()
    ):
        return False

    checks_payload = report.get("checks")
    decisions_payload = admission.get("decisions")
    order_ids_payload = admission.get("order_ids")
    if (
        type(checks_payload) is not list
        or type(decisions_payload) is not list
        or not decisions_payload
        or type(order_ids_payload) is not list
    ):
        return False
    try:
        checks = _domain_checks(tuple(checks_payload))
        decisions = tuple(
            _verified_item_decision(item, checks, False) for item in decisions_payload
        )
    except (KeyError, TypeError, ValueError):
        return False

    if not decisions:
        return False
    report_outcome = report.get("outcome")
    if report_outcome == "allowed" and any(item.status != "allowed" for item in checks):
        return False
    if report_outcome == "blocked" and not any(item.status == "blocked" for item in checks):
        return False
    expected_order_ids = [item["order_id"] for item in decisions_payload]
    if (
        order_ids_payload != expected_order_ids
        or any(type(order_id) is not str or not order_id.strip() for order_id in order_ids_payload)
        or len(set(order_ids_payload)) != len(order_ids_payload)
    ):
        return False
    if order_ids is not None and order_ids_payload != list(order_ids):
        return False
    if side is not None and (len(decisions) != 1 or decisions_payload[0].get("side") != side):
        return False
    if subject_id is not None and len(decisions) != 1:
        return False

    aggregate = _aggregate_decisions(decisions)
    if (
        admission.get("side") != _summary_side(tuple(item["side"] for item in decisions_payload))
        or admission.get("outcome") != aggregate.outcome
        or admission.get("reason_codes") != list(aggregate.reason_codes)
        or admission.get("waived_reason_codes") != list(aggregate.waived_reason_codes)
    ):
        return False
    return aggregate.outcome == "allowed"


def _domain_checks(
    checks: tuple[PortfolioRiskCheckPayload, ...],
) -> tuple[PortfolioRiskAdmissionCheck, ...]:
    """Convert public checks to validated Domain values before reuse."""

    return tuple(
        PortfolioRiskAdmissionCheck(
            dimension=check["dimension"],
            status=check["status"],
            reason_codes=tuple(check["reason_codes"]),
        )
        for check in checks
    )


def _verified_item_decision(
    item: PortfolioRiskOrderDecisionPayload,
    checks: tuple[PortfolioRiskAdmissionCheck, ...],
    must_not_use_for_decision: bool,
) -> PortfolioRiskOrderAdmission:
    """Recompute one serialized order result instead of trusting its claim."""

    if type(item["order_id"]) is not str or not item["order_id"].strip():
        raise ValueError("order admission must bind a nonempty order ID")
    side = item["side"]
    if side not in {"buy", "sell"}:
        raise ValueError("order admission must bind BUY or SELL")
    expected = assess_portfolio_risk_order_admission(
        side=side,
        checks=checks,
        must_not_use_for_decision=must_not_use_for_decision,
    )
    if (
        item["outcome"] != expected.outcome
        or item["reason_codes"] != list(expected.reason_codes)
        or item["waived_reason_codes"] != list(expected.waived_reason_codes)
    ):
        raise ValueError("order admission differs from its exact report checks")
    return expected


def _aggregate_decisions(
    decisions: tuple[PortfolioRiskOrderAdmission, ...],
) -> PortfolioRiskOrderAdmission:
    """Summarize order results without losing any per-order blocker."""

    if not decisions:
        raise ValueError("at least one order decision is required")
    statuses = {item.outcome for item in decisions}
    outcome: PortfolioRiskOrderAdmissionOutcome = (
        "unknown" if "unknown" in statuses else "blocked" if "blocked" in statuses else "allowed"
    )
    reasons = tuple(dict.fromkeys(code for item in decisions for code in item.reason_codes))
    waived = tuple(
        code
        for code in dict.fromkeys(code for item in decisions for code in item.waived_reason_codes)
        if code not in reasons
    )
    sides = {item.side for item in decisions}
    side: PortfolioRiskOrderSide = next(iter(sides)) if len(sides) == 1 else "mixed"
    if side != "sell":
        waived = ()
    if outcome == "allowed":
        reasons = ()
    elif not reasons:
        reasons = ("PORTFOLIO_ORDER_ADMISSION_BLOCKED",)
    return PortfolioRiskOrderAdmission(
        side=side,
        outcome=outcome,
        reason_codes=reasons,
        waived_reason_codes=waived,
    )


def _summary_side(sides: tuple[Literal["buy", "sell"], ...]) -> PortfolioRiskOrderSide:
    """Name one uniform side or an explicitly mixed proposal set."""

    unique = set(sides)
    if not unique:
        raise ValueError("at least one order side is required")
    if not unique.issubset({"buy", "sell"}):
        raise ValueError("unsupported order side in admission payload")
    if unique == {"buy"}:
        return "buy"
    if unique == {"sell"}:
        return "sell"
    return "mixed"
