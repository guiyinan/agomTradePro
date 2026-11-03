"""Canonical public report construction for replayable Scenario pressure runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import cast

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    PortfolioPressureProjection,
)
from apps.risk_center.application.portfolio_risk_clock_report_codec import (
    is_source_clock_evidence_proof,
    source_clock_proof_matches_report,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskOutcome,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitPressureStatus,
    PortfolioExitPressureAssessment,
)
from apps.risk_center.domain.scenarios import ScenarioRevision

_REQUIRED_REPORT_KEYS = frozenset(
    {
        "account_id",
        "as_of",
        "outcome",
        "policy_version",
        "resource_snapshot_hash",
        "checks",
        "sources",
        "freshness",
        "reliability",
        "must_not_use_for_decision",
        "scope",
        "must_not_execute",
    }
)
_OPTIONAL_REPORT_KEYS = frozenset({"order_admission"})
_CHECK_KEYS = frozenset({"dimension", "status", "reason_codes", "summary", "details"})
_ORDER_ADMISSION_KEYS = frozenset(
    {
        "side",
        "order_ids",
        "subject_id",
        "outcome",
        "reason_codes",
        "waived_reason_codes",
        "decisions",
    }
)
_ORDER_DECISION_KEYS = frozenset(
    {"order_id", "side", "outcome", "reason_codes", "waived_reason_codes"}
)
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "source_record_id",
        "raw_payload_sha256",
        "observed_at",
        "observed_on",
        "observation_precision",
        "available_at",
        "known_at",
        "cutoff",
        "valid_until",
        "purpose",
        "restrictions",
        "must_not_use_for_decision",
        "coverage_fraction",
        "coverage_basis",
    }
)


def decode_portfolio_risk_report_json(value: str) -> PortfolioRiskReportPayload | None:
    """Decode only the complete public report contract from canonical JSON."""

    if type(value) is not str or not value:
        return None
    try:
        decoded: object = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not _is_report(decoded):
        return None
    mapping = cast(Mapping[str, object], decoded)
    if canonical_portfolio_risk_json(mapping) != value:
        return None
    return cast(PortfolioRiskReportPayload, decoded)


def build_portfolio_pressure_report_template(
    *,
    original_report_json: str,
    scenario_label: str,
    as_of_time: datetime,
    revision: ScenarioRevision,
    assessment: PortfolioExitPressureAssessment,
    projection: PortfolioPressureProjection,
    source_evidence_ids: tuple[str, ...],
    run_evidence_id: str,
) -> PortfolioRiskReportPayload:
    """Create the exact replayable public report before its evidence hash exists.

    ``run_evidence_result_hash`` is intentionally left out of the persisted
    template because the report itself participates in that evidence hash. The
    caller adds the immutable hash after evidence persistence or on replay.
    """

    base_report = decode_portfolio_risk_report_json(original_report_json)
    if base_report is None:
        raise ValueError("original portfolio risk report is unavailable")
    if (
        base_report["account_id"] != projection.account_snapshot.account_id
        or base_report["as_of"] != as_of_time.isoformat()
        or revision.revision_id != projection.scenario_revision_id
        or revision.content_hash != projection.scenario_revision_hash
    ):
        raise ValueError("original report does not match the exact pressure projection")
    pressure_status = _pressure_outcome(assessment.status)
    findings = [
        {
            "asset_code": item.asset_code,
            "status": item.status.value,
            "quantity_unit": item.quantity_unit,
            "current_quantity": _decimal_text(item.current_quantity),
            "pending_sell_quantity": _decimal_text(item.pending_sell_quantity),
            "hypothetical_exitable_quantity": _decimal_text(item.hypothetical_exitable_quantity),
            "stress_window_residual_quantity": _decimal_text(item.stress_window_residual_quantity),
            "exit_sessions_required": item.exit_sessions_required,
            "reason_codes": list(item.reason_codes),
            "source_evidence_ids": list(item.source_evidence_ids),
        }
        for item in assessment.findings
    ]
    windows = [
        {
            "asset_code": position.asset_code,
            "quantity_unit": position.quantity_unit,
            "windows": [
                {
                    "session_date": window.session_date.isoformat(),
                    "exitable_quantity": _decimal_text(window.exitable_quantity),
                    "reason_codes": list(window.reason_codes),
                    "source_evidence_ids": list(window.source_evidence_ids),
                }
                for window in position.capacity_windows
            ],
        }
        for position in projection.positions
    ]
    reasons = _ordered_unique(
        tuple(reason for item in assessment.findings for reason in item.reason_codes)
    )
    check = _pressure_check(
        status=pressure_status,
        reason_codes=reasons,
        summary=_pressure_summary(assessment.status),
        details={
            "scenario": {
                "label": scenario_label,
                "revision_id": revision.revision_id,
                "version": revision.version,
                "content_sha256": revision.content_hash,
            },
            "scenario_result_hash": assessment.scenario_result_hash,
            "pressure_result_hash": assessment.result_hash,
            "run_evidence_id": run_evidence_id,
            "run_evidence_persisted": True,
            "portfolio_snapshot_id": projection.portfolio_snapshot_id,
            "portfolio_snapshot_hash": assessment.portfolio_snapshot_hash,
            "capacity_findings": findings,
            "capacity_windows": windows,
            "source_evidence_ids": list(source_evidence_ids),
            "scope": "simulation_only",
            "must_not_execute": True,
            "execution_permitted": False,
        },
    )
    if any(item["dimension"] == "exit_pressure" for item in base_report["checks"]):
        raise ValueError("original report already contains an exit-pressure result")
    must_not_use = base_report["must_not_use_for_decision"] or pressure_status in {
        "unknown",
        "partial",
    }
    return {
        **base_report,
        "checks": [*base_report["checks"], check],
        "outcome": _combine_outcomes(base_report["outcome"], pressure_status),
        "must_not_use_for_decision": must_not_use,
        "scope": "simulation_only",
        "must_not_execute": True,
    }


def bind_portfolio_pressure_evidence_hash(
    report_template: PortfolioRiskReportPayload,
    result_hash: str,
) -> PortfolioRiskReportPayload:
    """Attach the saved evidence digest to its report template deterministically."""

    if (
        type(result_hash) is not str
        or len(result_hash) != 64
        or any(character not in "0123456789abcdef" for character in result_hash)
    ):
        raise ValueError("pressure evidence result hash must be SHA-256")
    checks: list[PortfolioRiskCheckPayload] = []
    pressure_count = 0
    for item in report_template["checks"]:
        if item["dimension"] != "exit_pressure":
            checks.append(item)
            continue
        pressure_count += 1
        details = dict(item["details"])
        existing = details.get("run_evidence_result_hash")
        if existing is not None and existing != result_hash:
            raise ValueError("pressure report is bound to different run evidence")
        details["run_evidence_result_hash"] = result_hash
        checks.append({**item, "details": details})
    if pressure_count != 1:
        raise ValueError("replayable pressure report requires exactly one pressure check")
    return {**report_template, "checks": checks}


def report_payload_from_object(value: object) -> PortfolioRiskReportPayload | None:
    """Narrow a decoded immutable snapshot value to the public report contract."""

    if not _is_report(value):
        return None
    return cast(PortfolioRiskReportPayload, value)


def _is_report(value: object) -> bool:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    mapping = cast(Mapping[str, object], value)
    keys = set(mapping)
    if not _REQUIRED_REPORT_KEYS.issubset(keys) or not keys.issubset(
        _REQUIRED_REPORT_KEYS | _OPTIONAL_REPORT_KEYS
    ):
        return False
    account_id = mapping.get("account_id")
    checks = mapping.get("checks")
    sources = mapping.get("sources")
    outcome = mapping.get("outcome")
    freshness = mapping.get("freshness")
    reliability = mapping.get("reliability")
    return (
        type(account_id) is int
        and account_id > 0
        and type(mapping.get("as_of")) is str
        and bool(mapping["as_of"])
        and type(outcome) is str
        and outcome in {"allowed", "blocked", "partial", "unknown"}
        and (mapping.get("policy_version") is None or type(mapping.get("policy_version")) is str)
        and _is_report_snapshot_hash(mapping.get("resource_snapshot_hash"))
        and type(checks) is list
        and all(_is_check(item) for item in checks)
        and type(sources) is list
        and all(_is_source(item) for item in sources)
        and type(freshness) is str
        and freshness in {"qualified_snapshot", "expired", "unknown"}
        and type(reliability) is str
        and reliability in {"source_bound", "partial", "unknown"}
        and type(mapping.get("must_not_use_for_decision")) is bool
        and mapping.get("scope") == "simulation_only"
        and mapping.get("must_not_execute") is True
        and ("order_admission" not in mapping or _is_order_admission(mapping["order_admission"]))
        and all(
            source_clock_proof_matches_report(
                source=item,
                as_of_text=cast(str, mapping["as_of"]),
                account_id=account_id,
                policy_version=mapping.get("policy_version"),
            )
            for item in cast(list[object], sources)
        )
    )


def _is_check(value: object) -> bool:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    mapping = cast(Mapping[str, object], value)
    status = mapping.get("status")
    return (
        set(mapping) == _CHECK_KEYS
        and type(mapping.get("dimension")) is str
        and type(status) is str
        and status in {"allowed", "blocked", "partial", "unknown"}
        and _is_string_list(mapping.get("reason_codes"))
        and type(mapping.get("summary")) is str
        and isinstance(mapping.get("details"), dict)
    )


def _is_order_admission(value: object) -> bool:
    """Validate the complete optional direction-aware admission contract."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    admission = cast(Mapping[str, object], value)
    if set(admission) != _ORDER_ADMISSION_KEYS:
        return False
    side = admission.get("side")
    outcome = admission.get("outcome")
    subject_id = admission.get("subject_id")
    order_ids = admission.get("order_ids")
    decisions = admission.get("decisions")
    if (
        type(side) is not str
        or side not in {"buy", "sell", "mixed"}
        or type(outcome) is not str
        or outcome not in {"allowed", "blocked", "unknown"}
        or (subject_id is not None and (type(subject_id) is not str or not subject_id.strip()))
        or type(order_ids) is not list
        or not order_ids
        or any(type(item) is not str or not item.strip() for item in order_ids)
        or len(order_ids) != len(set(order_ids))
        or type(decisions) is not list
        or not decisions
        or not _is_reason_list(admission.get("reason_codes"))
        or not _is_reason_list(admission.get("waived_reason_codes"))
        or any(not _is_order_decision(item) for item in decisions)
    ):
        return False

    decision_rows = cast(list[Mapping[str, object]], decisions)
    if order_ids != [item["order_id"] for item in decision_rows]:
        return False
    decision_sides = {item["side"] for item in decision_rows}
    expected_side = next(iter(decision_sides)) if len(decision_sides) == 1 else "mixed"
    decision_outcomes = {item["outcome"] for item in decision_rows}
    expected_outcome = (
        "unknown"
        if "unknown" in decision_outcomes
        else "blocked" if "blocked" in decision_outcomes else "allowed"
    )
    expected_reasons = tuple(
        dict.fromkeys(
            code for item in decision_rows for code in cast(list[str], item["reason_codes"])
        )
    )
    expected_waived = tuple(
        code
        for code in dict.fromkeys(
            code for item in decision_rows for code in cast(list[str], item["waived_reason_codes"])
        )
        if code not in expected_reasons
    )
    if expected_side != "sell":
        expected_waived = ()
    if expected_outcome == "allowed":
        expected_reasons = ()
    elif not expected_reasons:
        expected_reasons = ("PORTFOLIO_ORDER_ADMISSION_BLOCKED",)
    return (
        side == expected_side
        and outcome == expected_outcome
        and admission.get("reason_codes") == list(expected_reasons)
        and admission.get("waived_reason_codes") == list(expected_waived)
    )


def _is_order_decision(value: object) -> bool:
    """Validate one per-order typed outcome before retaining it in a report."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    decision = cast(Mapping[str, object], value)
    order_id = decision.get("order_id")
    side = decision.get("side")
    outcome = decision.get("outcome")
    reasons = decision.get("reason_codes")
    waived = decision.get("waived_reason_codes")
    if (
        set(decision) != _ORDER_DECISION_KEYS
        or type(order_id) is not str
        or not order_id.strip()
        or type(side) is not str
        or side not in {"buy", "sell"}
        or type(outcome) is not str
        or outcome not in {"allowed", "blocked", "unknown"}
        or not _is_reason_list(reasons)
        or not _is_reason_list(waived)
        or set(cast(list[str], reasons)).intersection(cast(list[str], waived))
        or (side != "sell" and cast(list[str], waived))
        or (outcome == "allowed" and cast(list[str], reasons))
        or (outcome != "allowed" and not cast(list[str], reasons))
    ):
        return False
    return True


def _is_reason_list(value: object) -> bool:
    """Require a JSON list of unique, nonblank reason-code strings."""

    return (
        type(value) is list
        and all(
            type(item) is str
            and bool(item)
            and item.strip() == item
            and not any(character.isspace() for character in item)
            for item in value
        )
        and len(value) == len(set(value))
    )


def _is_source(value: object) -> bool:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    mapping = cast(Mapping[str, object], value)
    nullable_strings = (
        "raw_payload_sha256",
        "observed_at",
        "observed_on",
        "available_at",
        "known_at",
        "valid_until",
        "coverage_fraction",
    )
    keys = set(mapping)
    proof_present = "clock_evidence_proof" in mapping
    proof = mapping.get("clock_evidence_proof")
    return (
        keys in (_SOURCE_KEYS, _SOURCE_KEYS | {"clock_evidence_proof"})
        and all(
            type(mapping.get(key)) is str and bool(mapping[key])
            for key in (
                "source_id",
                "source_record_id",
                "observation_precision",
                "cutoff",
                "purpose",
                "coverage_basis",
            )
        )
        and all(
            mapping.get(key) is None or type(mapping.get(key)) is str for key in nullable_strings
        )
        and _is_string_list(mapping.get("restrictions"))
        and type(mapping.get("must_not_use_for_decision")) is bool
        and (not proof_present or is_source_clock_evidence_proof(proof, mapping))
    )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_prefixed_sha256(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("sha256:")
        and _is_sha256(value.removeprefix("sha256:"))
    )


def _is_token(value: object) -> bool:
    """Validate one public canonical token without coercing or cleaning it."""

    return (
        type(value) is str
        and bool(value)
        and value.strip() == value
        and not any(character.isspace() for character in value)
    )


def _is_report_snapshot_hash(value: object) -> bool:
    """Accept both producer formats without rewriting the retained hash text."""

    return _is_sha256(value) or _is_prefixed_sha256(value)


def _is_string_list(value: object) -> bool:
    return type(value) is list and all(type(item) is str for item in value)


def _pressure_check(
    *,
    status: PortfolioRiskOutcome,
    reason_codes: tuple[str, ...],
    summary: str,
    details: dict[str, object],
) -> PortfolioRiskCheckPayload:
    return {
        "dimension": "exit_pressure",
        "status": status,
        "reason_codes": list(_ordered_unique(reason_codes)),
        "summary": summary,
        "details": details,
    }


def _pressure_outcome(status: ExitPressureStatus) -> PortfolioRiskOutcome:
    outcomes: dict[ExitPressureStatus, PortfolioRiskOutcome] = {
        ExitPressureStatus.EXITABLE: "allowed",
        ExitPressureStatus.LIMITED: "partial",
        ExitPressureStatus.BLOCKED: "blocked",
        ExitPressureStatus.UNKNOWN: "unknown",
    }
    return outcomes[status]


def _pressure_summary(status: ExitPressureStatus) -> str:
    return {
        ExitPressureStatus.EXITABLE: "已审批情景下的模拟退出容量覆盖当前持仓",
        ExitPressureStatus.LIMITED: "已审批情景下仍有部分持仓无法按假设退出",
        ExitPressureStatus.BLOCKED: "已审批情景包含无法退出的明确假设",
        ExitPressureStatus.UNKNOWN: "来源、日历或身份资料不足，无法确认退出容量",
    }[status]


def _combine_outcomes(
    first: PortfolioRiskOutcome,
    second: PortfolioRiskOutcome,
) -> PortfolioRiskOutcome:
    for status in ("blocked", "unknown", "partial"):
        if first == status or second == status:
            return status
    return "allowed"


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "bind_portfolio_pressure_evidence_hash",
    "build_portfolio_pressure_report_template",
    "decode_portfolio_risk_report_json",
    "report_payload_from_object",
]
