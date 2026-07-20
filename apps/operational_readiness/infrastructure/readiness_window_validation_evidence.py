"""Evidence parsing and classification for readiness window validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from apps.operational_readiness.application.status_services import (
    classify_formal_risk_evidence,
)
from apps.operational_readiness.domain.evidence_contract import (
    classify_evidence_payload,
    decision_quote_freshness_status,
    get_decision_data,
    get_workspace_components,
    workspace_core_status,
)


@dataclass(frozen=True)
class _EvidenceRecord:
    path: Path
    target_date: date
    accepted: bool
    reason: str
    evidence_mode: str
    acceptance_candidate: bool
    trigger_source: str | None
    trigger_task_id: str | None
    trigger_task_name: str | None
    formal_workspace_core_record: bool
    formal_workspace_core_ok: bool
    formal_workspace_core_missing: bool
    formal_qlib_record: bool
    formal_qlib_ok: bool
    formal_qlib_missing: bool
    formal_qlib_blocked: bool
    formal_alpha_workspace_record: bool
    formal_alpha_workspace_ok: bool
    formal_alpha_workspace_missing: bool
    formal_decision_data_record: bool
    formal_decision_data_ok: bool
    formal_decision_data_missing: bool
    formal_decision_data_blocked: bool
    formal_quote_freshness_record: bool
    formal_quote_freshness_ok: bool
    formal_quote_freshness_missing: bool
    formal_quote_freshness_stale: bool
    formal_quote_freshness_blocked: bool
    formal_quote_pre_readiness_scheduler_record: bool
    formal_quote_pre_readiness_scheduler_ok: bool
    formal_quote_pre_readiness_scheduler_missing: bool
    formal_quote_pre_readiness_scheduler_blocked: bool
    formal_risk_account_count: int
    formal_risk_report_ok_account_count: int
    formal_risk_persisted_report_account_count: int
    formal_pre_trade_ok_account_count: int
    formal_pre_trade_missing_account_count: int
    formal_post_investment_ok_account_count: int
    formal_post_investment_missing_account_count: int
    formal_risk_evidence_status: str
    weekly_report_account_count: int
    weekly_report_persistence_ok_account_count: int
    weekly_report_persistence_missing_account_count: int
    weekly_report_persistence_warning_account_count: int
    weekly_report_persistence_status: str
    size_bytes: int
    sha256_hash: str


def _load_evidence_record(path: Path) -> _EvidenceRecord | None:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        target_date = date.fromisoformat(str(payload["target_date"]))
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    accepted, reason = _evaluate_payload(payload)
    classification = _classify_payload(payload)
    advisor_quality = _classify_auto_advisor_weekly_persistence(payload)
    workspace_quality = _classify_formal_workspace_core_evidence(payload)
    qlib_quality = _classify_formal_qlib_evidence(payload)
    alpha_quality = _classify_formal_alpha_workspace_evidence(payload)
    decision_quality = _classify_formal_decision_data_evidence(payload)
    quote_quality = _classify_formal_quote_freshness_evidence(payload)
    quote_pre_readiness_quality = _classify_formal_quote_pre_readiness_scheduler_evidence(payload)
    risk_quality = classify_formal_risk_evidence(
        payload=payload,
        classification=classification,
    )
    return _EvidenceRecord(
        path=path,
        target_date=target_date,
        accepted=accepted,
        reason=reason,
        evidence_mode=classification["evidence_mode"],
        acceptance_candidate=classification["acceptance_candidate"],
        trigger_source=classification["trigger_source"],
        trigger_task_id=classification["trigger_task_id"],
        trigger_task_name=classification["trigger_task_name"],
        formal_workspace_core_record=workspace_quality["formal_workspace_core_record"],
        formal_workspace_core_ok=workspace_quality["formal_workspace_core_ok"],
        formal_workspace_core_missing=workspace_quality["formal_workspace_core_missing"],
        formal_qlib_record=qlib_quality["formal_qlib_record"],
        formal_qlib_ok=qlib_quality["formal_qlib_ok"],
        formal_qlib_missing=qlib_quality["formal_qlib_missing"],
        formal_qlib_blocked=qlib_quality["formal_qlib_blocked"],
        formal_alpha_workspace_record=alpha_quality["formal_alpha_workspace_record"],
        formal_alpha_workspace_ok=alpha_quality["formal_alpha_workspace_ok"],
        formal_alpha_workspace_missing=alpha_quality["formal_alpha_workspace_missing"],
        formal_decision_data_record=decision_quality["formal_decision_data_record"],
        formal_decision_data_ok=decision_quality["formal_decision_data_ok"],
        formal_decision_data_missing=decision_quality["formal_decision_data_missing"],
        formal_decision_data_blocked=decision_quality["formal_decision_data_blocked"],
        formal_quote_freshness_record=quote_quality["formal_quote_freshness_record"],
        formal_quote_freshness_ok=quote_quality["formal_quote_freshness_ok"],
        formal_quote_freshness_missing=quote_quality["formal_quote_freshness_missing"],
        formal_quote_freshness_stale=quote_quality["formal_quote_freshness_stale"],
        formal_quote_freshness_blocked=quote_quality["formal_quote_freshness_blocked"],
        formal_quote_pre_readiness_scheduler_record=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_record"
        ],
        formal_quote_pre_readiness_scheduler_ok=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_ok"
        ],
        formal_quote_pre_readiness_scheduler_missing=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_missing"
        ],
        formal_quote_pre_readiness_scheduler_blocked=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_blocked"
        ],
        formal_risk_account_count=risk_quality["formal_risk_account_count"],
        formal_risk_report_ok_account_count=risk_quality["formal_risk_report_ok_account_count"],
        formal_risk_persisted_report_account_count=risk_quality[
            "formal_risk_persisted_report_account_count"
        ],
        formal_pre_trade_ok_account_count=risk_quality["formal_pre_trade_ok_account_count"],
        formal_pre_trade_missing_account_count=risk_quality[
            "formal_pre_trade_missing_account_count"
        ],
        formal_post_investment_ok_account_count=risk_quality[
            "formal_post_investment_ok_account_count"
        ],
        formal_post_investment_missing_account_count=risk_quality[
            "formal_post_investment_missing_account_count"
        ],
        formal_risk_evidence_status=risk_quality["formal_risk_evidence_status"],
        weekly_report_account_count=advisor_quality["weekly_report_account_count"],
        weekly_report_persistence_ok_account_count=advisor_quality[
            "weekly_report_persistence_ok_account_count"
        ],
        weekly_report_persistence_missing_account_count=advisor_quality[
            "weekly_report_persistence_missing_account_count"
        ],
        weekly_report_persistence_warning_account_count=advisor_quality[
            "weekly_report_persistence_warning_account_count"
        ],
        weekly_report_persistence_status=advisor_quality["weekly_report_persistence_status"],
        size_bytes=len(raw),
        sha256_hash=sha256(raw).hexdigest(),
    )


def _summarize_record(record: _EvidenceRecord) -> dict[str, Any]:
    return {
        "target_date": record.target_date.isoformat(),
        "path": str(record.path),
        "size_bytes": record.size_bytes,
        "sha256": record.sha256_hash,
        "evidence_mode": record.evidence_mode,
        "acceptance_candidate": record.acceptance_candidate,
        "trigger_source": record.trigger_source,
        "trigger_task_id": record.trigger_task_id,
        "trigger_task_name": record.trigger_task_name,
        "reason": record.reason,
    }


def _build_accepted_evidence_manifest(
    accepted_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "accepted-readiness-evidence-manifest.v1",
        "record_count": len(accepted_evidence),
        "target_dates": [str(record.get("target_date")) for record in accepted_evidence],
        "records": accepted_evidence,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": payload["schema_version"],
        "record_count": payload["record_count"],
        "target_dates": payload["target_dates"],
        "sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _build_accepted_evidence_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    return {
        "record_count": len(records),
        "start_date": records[0].target_date.isoformat() if records else None,
        "end_date": records[-1].target_date.isoformat() if records else None,
        "acceptance_candidate_record_count": sum(
            1 for record in records if record.acceptance_candidate
        ),
        "formal_record_count": sum(1 for record in records if record.evidence_mode == "formal"),
        "legacy_record_count": sum(
            1 for record in records if record.evidence_mode == "legacy_without_operation_context"
        ),
        "diagnostic_record_count": sum(1 for record in records if not record.acceptance_candidate),
        "scheduler_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "scheduler"
        ),
        "manual_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "manual"
        ),
        "unknown_trigger_record_count": sum(
            1 for record in records if record.trigger_source is None
        ),
        "task_provenance_record_count": sum(
            1 for record in records if record.trigger_task_id or record.trigger_task_name
        ),
        "missing_task_provenance_record_count": sum(
            1 for record in records if not record.trigger_task_id and not record.trigger_task_name
        ),
        "formal_workspace_core_record_count": sum(
            1 for record in records if record.formal_workspace_core_record
        ),
        "formal_workspace_core_ok_record_count": sum(
            1 for record in records if record.formal_workspace_core_ok
        ),
        "formal_workspace_core_missing_record_count": sum(
            1 for record in records if record.formal_workspace_core_missing
        ),
        "formal_qlib_record_count": sum(1 for record in records if record.formal_qlib_record),
        "formal_qlib_ok_record_count": sum(1 for record in records if record.formal_qlib_ok),
        "formal_qlib_missing_record_count": sum(
            1 for record in records if record.formal_qlib_missing
        ),
        "formal_qlib_blocked_record_count": sum(
            1 for record in records if record.formal_qlib_blocked
        ),
        "formal_alpha_workspace_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_record
        ),
        "formal_alpha_workspace_ok_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_ok
        ),
        "formal_alpha_workspace_missing_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_missing
        ),
        "formal_decision_data_record_count": sum(
            1 for record in records if record.formal_decision_data_record
        ),
        "formal_decision_data_ok_record_count": sum(
            1 for record in records if record.formal_decision_data_ok
        ),
        "formal_decision_data_missing_record_count": sum(
            1 for record in records if record.formal_decision_data_missing
        ),
        "formal_decision_data_blocked_record_count": sum(
            1 for record in records if record.formal_decision_data_blocked
        ),
        "formal_quote_freshness_record_count": sum(
            1 for record in records if record.formal_quote_freshness_record
        ),
        "formal_quote_freshness_ok_record_count": sum(
            1 for record in records if record.formal_quote_freshness_ok
        ),
        "formal_quote_freshness_missing_record_count": sum(
            1 for record in records if record.formal_quote_freshness_missing
        ),
        "formal_quote_freshness_stale_record_count": sum(
            1 for record in records if record.formal_quote_freshness_stale
        ),
        "formal_quote_freshness_blocked_record_count": sum(
            1 for record in records if record.formal_quote_freshness_blocked
        ),
        "formal_quote_pre_readiness_scheduler_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_record
        ),
        "formal_quote_pre_readiness_scheduler_ok_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_ok
        ),
        "formal_quote_pre_readiness_scheduler_missing_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_missing
        ),
        "formal_quote_pre_readiness_scheduler_blocked_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_blocked
        ),
        **_build_formal_risk_quality(records),
        **_build_weekly_report_quality(records),
        "evidence_modes": sorted({record.evidence_mode for record in records}),
        "trigger_sources": sorted(
            {record.trigger_source for record in records if record.trigger_source is not None}
        ),
        "trigger_task_names": sorted(
            {record.trigger_task_name for record in records if record.trigger_task_name is not None}
        ),
    }


def _classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    classification = classify_evidence_payload(payload)
    classification.pop("formal_evidence", None)
    return classification


def _build_weekly_report_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    record_groups = {
        "weekly_report": records,
        "scheduled_weekly_report": [
            record for record in records if record.target_date.weekday() == 4
        ],
    }
    quality: dict[str, Any] = {}
    for prefix, grouped_records in record_groups.items():
        quality.update(
            {
                f"{prefix}_record_count": sum(
                    1 for record in grouped_records if record.weekly_report_account_count > 0
                ),
                f"{prefix}_persistence_ok_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "ok"
                ),
                f"{prefix}_persistence_missing_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "missing"
                ),
                f"{prefix}_persistence_warning_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "warning"
                ),
                f"{prefix}_account_count": sum(
                    record.weekly_report_account_count for record in grouped_records
                ),
                f"{prefix}_persistence_ok_account_count": sum(
                    record.weekly_report_persistence_ok_account_count for record in grouped_records
                ),
                f"{prefix}_persistence_missing_account_count": sum(
                    record.weekly_report_persistence_missing_account_count
                    for record in grouped_records
                ),
                f"{prefix}_persistence_warning_account_count": sum(
                    record.weekly_report_persistence_warning_account_count
                    for record in grouped_records
                ),
            }
        )
    return quality


def _build_formal_risk_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    return {
        "formal_risk_record_count": sum(
            1 for record in records if record.formal_risk_account_count > 0
        ),
        "formal_risk_ok_record_count": sum(
            1 for record in records if record.formal_risk_evidence_status == "ok"
        ),
        "formal_risk_missing_record_count": sum(
            1
            for record in records
            if record.formal_risk_account_count > 0 and record.formal_risk_evidence_status != "ok"
        ),
        "formal_risk_account_count": sum(record.formal_risk_account_count for record in records),
        "formal_risk_report_ok_account_count": sum(
            record.formal_risk_report_ok_account_count for record in records
        ),
        "formal_risk_persisted_report_account_count": sum(
            record.formal_risk_persisted_report_account_count for record in records
        ),
        "formal_pre_trade_ok_account_count": sum(
            record.formal_pre_trade_ok_account_count for record in records
        ),
        "formal_pre_trade_missing_account_count": sum(
            record.formal_pre_trade_missing_account_count for record in records
        ),
        "formal_post_investment_ok_account_count": sum(
            record.formal_post_investment_ok_account_count for record in records
        ),
        "formal_post_investment_missing_account_count": sum(
            record.formal_post_investment_missing_account_count for record in records
        ),
    }


def _classify_auto_advisor_weekly_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    weekly_report_account_count = 0
    persistence_ok_count = 0
    persistence_missing_count = 0
    persistence_warning_count = 0

    for account in payload.get("accounts") or []:
        advisor = dict(account.get("auto_advisor") or {})
        if advisor.get("weekly_report") is None:
            continue
        weekly_report_account_count += 1
        persistence = advisor.get("weekly_report_persistence")
        if not isinstance(persistence, dict):
            persistence_missing_count += 1
            continue
        if persistence.get("status") == "ok":
            persistence_ok_count += 1
        else:
            persistence_warning_count += 1

    if weekly_report_account_count <= 0:
        status = "not_requested"
    elif persistence_missing_count > 0:
        status = "missing"
    elif persistence_warning_count > 0:
        status = "warning"
    elif persistence_ok_count == weekly_report_account_count:
        status = "ok"
    else:
        status = "partial"

    return {
        "weekly_report_account_count": weekly_report_account_count,
        "weekly_report_persistence_ok_account_count": persistence_ok_count,
        "weekly_report_persistence_missing_account_count": persistence_missing_count,
        "weekly_report_persistence_warning_account_count": persistence_warning_count,
        "weekly_report_persistence_status": status,
    }


def _classify_formal_decision_data_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_decision_data_record": False,
            "formal_decision_data_ok": False,
            "formal_decision_data_missing": False,
            "formal_decision_data_blocked": False,
        }

    decision_data = _get_decision_data(payload)
    if not decision_data:
        return {
            "formal_decision_data_record": True,
            "formal_decision_data_ok": False,
            "formal_decision_data_missing": True,
            "formal_decision_data_blocked": False,
        }

    must_not_use = decision_data.get("must_not_use_for_decision") is True
    ok = (
        decision_data.get("status") == "ok"
        and decision_data.get("readiness_status") == "ok"
        and not must_not_use
    )
    return {
        "formal_decision_data_record": True,
        "formal_decision_data_ok": ok,
        "formal_decision_data_missing": False,
        "formal_decision_data_blocked": must_not_use,
    }


def _classify_formal_quote_freshness_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_quote_freshness_record": False,
            "formal_quote_freshness_ok": False,
            "formal_quote_freshness_missing": False,
            "formal_quote_freshness_stale": False,
            "formal_quote_freshness_blocked": False,
        }

    decision_data = _get_decision_data(payload)
    status = _decision_quote_freshness_status(decision_data)
    return {
        "formal_quote_freshness_record": True,
        "formal_quote_freshness_ok": status == "ok",
        "formal_quote_freshness_missing": status == "missing",
        "formal_quote_freshness_stale": status == "stale",
        "formal_quote_freshness_blocked": status == "blocked",
    }


def _classify_formal_quote_pre_readiness_scheduler_evidence(
    payload: dict[str, Any],
) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_quote_pre_readiness_scheduler_record": False,
            "formal_quote_pre_readiness_scheduler_ok": False,
            "formal_quote_pre_readiness_scheduler_missing": False,
            "formal_quote_pre_readiness_scheduler_blocked": False,
        }

    scheduler_evidence = payload.get("scheduler_evidence")
    quote_pre_readiness_scheduler = (
        scheduler_evidence.get("quote_pre_readiness_scheduler")
        if isinstance(scheduler_evidence, dict)
        else None
    )
    status = _quote_pre_readiness_scheduler_evidence_status(
        quote_pre_readiness_scheduler,
        target_date=_parse_payload_target_date(payload),
    )
    return {
        "formal_quote_pre_readiness_scheduler_record": True,
        "formal_quote_pre_readiness_scheduler_ok": status == "ok",
        "formal_quote_pre_readiness_scheduler_missing": status == "missing",
        "formal_quote_pre_readiness_scheduler_blocked": status == "blocked",
    }


def _quote_pre_readiness_scheduler_evidence_status(
    value: Any,
    *,
    target_date: date | None,
) -> str:
    if not isinstance(value, dict) or not value:
        return "missing"
    if value.get("status") == "missing":
        return "missing"
    safety = value.get("safety")
    safety_status = safety.get("status") if isinstance(safety, dict) else None
    run_metadata = value.get("run_metadata")
    latest_run_date = _parse_iso_datetime_date(
        run_metadata.get("last_run_at") if isinstance(run_metadata, dict) else None
    )
    if (
        value.get("status") == "ok"
        and value.get("enabled") is True
        and safety_status == "ok"
        and target_date is not None
        and latest_run_date is not None
        and latest_run_date >= target_date
    ):
        return "ok"
    return "blocked"


def _parse_payload_target_date(payload: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(payload.get("target_date") or ""))
    except ValueError:
        return None


def _parse_iso_datetime_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _decision_quote_freshness_status(decision_data: dict[str, Any]) -> str:
    return decision_quote_freshness_status(decision_data)


def _classify_formal_workspace_core_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_workspace_core_record": False,
            "formal_workspace_core_ok": False,
            "formal_workspace_core_missing": False,
        }

    components = _get_workspace_components(payload)
    if not components:
        return {
            "formal_workspace_core_record": True,
            "formal_workspace_core_ok": False,
            "formal_workspace_core_missing": True,
        }
    ok = _workspace_core_status(components) == "ok"
    return {
        "formal_workspace_core_record": True,
        "formal_workspace_core_ok": ok,
        "formal_workspace_core_missing": False,
    }


def _classify_formal_qlib_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_qlib_record": False,
            "formal_qlib_ok": False,
            "formal_qlib_missing": False,
            "formal_qlib_blocked": False,
        }

    qlib = payload.get("qlib")
    if not isinstance(qlib, dict):
        return {
            "formal_qlib_record": True,
            "formal_qlib_ok": False,
            "formal_qlib_missing": True,
            "formal_qlib_blocked": False,
        }
    ok = _qlib_evidence_status(qlib) == "ok"
    return {
        "formal_qlib_record": True,
        "formal_qlib_ok": ok,
        "formal_qlib_missing": False,
        "formal_qlib_blocked": not ok,
    }


def _qlib_evidence_status(qlib: dict[str, Any]) -> str:
    if not qlib:
        return "missing"
    if qlib.get("status") != "ok":
        return str(qlib.get("status") or "blocked")
    if qlib.get("check_only") is not True:
        return "not_check_only"
    return "ok"


def _get_workspace_components(payload: dict[str, Any]) -> dict[str, Any]:
    return get_workspace_components(payload)


def _workspace_core_status(components: dict[str, Any]) -> str:
    return workspace_core_status(components)


def _classify_formal_alpha_workspace_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_alpha_workspace_record": False,
            "formal_alpha_workspace_ok": False,
            "formal_alpha_workspace_missing": False,
        }

    alpha_workspace = _get_alpha_workspace_consistency(payload)
    if not alpha_workspace:
        return {
            "formal_alpha_workspace_record": True,
            "formal_alpha_workspace_ok": False,
            "formal_alpha_workspace_missing": True,
        }
    ok = alpha_workspace.get("status") == "ok"
    return {
        "formal_alpha_workspace_record": True,
        "formal_alpha_workspace_ok": ok,
        "formal_alpha_workspace_missing": False,
    }


def _get_alpha_workspace_consistency(payload: dict[str, Any]) -> dict[str, Any]:
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    alpha_workspace = checks.get("alpha_workspace_consistency")
    return dict(alpha_workspace) if isinstance(alpha_workspace, dict) else {}


def _get_decision_data(payload: dict[str, Any]) -> dict[str, Any]:
    return get_decision_data(payload)


def _build_evidence_quality(
    *,
    records: list[_EvidenceRecord],
    trading_records: list[_EvidenceRecord],
) -> dict[str, Any]:
    trading_paths = {record.path for record in trading_records}
    return {
        "record_count": len(records),
        "trading_record_count": len(trading_records),
        "non_trading_record_count": len(records) - len(trading_records),
        "accepted_record_count": sum(1 for record in records if record.accepted),
        "rejected_record_count": sum(1 for record in records if not record.accepted),
        "acceptance_candidate_record_count": sum(
            1 for record in records if record.acceptance_candidate
        ),
        "formal_record_count": sum(1 for record in records if record.evidence_mode == "formal"),
        "legacy_record_count": sum(
            1 for record in records if record.evidence_mode == "legacy_without_operation_context"
        ),
        "diagnostic_record_count": sum(1 for record in records if not record.acceptance_candidate),
        "scheduler_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "scheduler"
        ),
        "manual_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "manual"
        ),
        "unknown_trigger_record_count": sum(
            1 for record in records if record.trigger_source is None
        ),
        "task_provenance_record_count": sum(
            1 for record in records if record.trigger_task_id or record.trigger_task_name
        ),
        "missing_task_provenance_record_count": sum(
            1 for record in records if not record.trigger_task_id and not record.trigger_task_name
        ),
        "formal_workspace_core_record_count": sum(
            1 for record in records if record.formal_workspace_core_record
        ),
        "formal_workspace_core_ok_record_count": sum(
            1 for record in records if record.formal_workspace_core_ok
        ),
        "formal_workspace_core_missing_record_count": sum(
            1 for record in records if record.formal_workspace_core_missing
        ),
        "formal_qlib_record_count": sum(1 for record in records if record.formal_qlib_record),
        "formal_qlib_ok_record_count": sum(1 for record in records if record.formal_qlib_ok),
        "formal_qlib_missing_record_count": sum(
            1 for record in records if record.formal_qlib_missing
        ),
        "formal_qlib_blocked_record_count": sum(
            1 for record in records if record.formal_qlib_blocked
        ),
        "formal_alpha_workspace_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_record
        ),
        "formal_alpha_workspace_ok_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_ok
        ),
        "formal_alpha_workspace_missing_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_missing
        ),
        "formal_decision_data_record_count": sum(
            1 for record in records if record.formal_decision_data_record
        ),
        "formal_decision_data_ok_record_count": sum(
            1 for record in records if record.formal_decision_data_ok
        ),
        "formal_decision_data_missing_record_count": sum(
            1 for record in records if record.formal_decision_data_missing
        ),
        "formal_decision_data_blocked_record_count": sum(
            1 for record in records if record.formal_decision_data_blocked
        ),
        "formal_quote_freshness_record_count": sum(
            1 for record in records if record.formal_quote_freshness_record
        ),
        "formal_quote_freshness_ok_record_count": sum(
            1 for record in records if record.formal_quote_freshness_ok
        ),
        "formal_quote_freshness_missing_record_count": sum(
            1 for record in records if record.formal_quote_freshness_missing
        ),
        "formal_quote_freshness_stale_record_count": sum(
            1 for record in records if record.formal_quote_freshness_stale
        ),
        "formal_quote_freshness_blocked_record_count": sum(
            1 for record in records if record.formal_quote_freshness_blocked
        ),
        "formal_quote_pre_readiness_scheduler_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_record
        ),
        "formal_quote_pre_readiness_scheduler_ok_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_ok
        ),
        "formal_quote_pre_readiness_scheduler_missing_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_missing
        ),
        "formal_quote_pre_readiness_scheduler_blocked_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_blocked
        ),
        **_build_formal_risk_quality(records),
        **_build_weekly_report_quality(records),
        "non_trading_dates": [
            record.target_date.isoformat() for record in records if record.path not in trading_paths
        ],
        "rejected_dates": [
            {
                "target_date": record.target_date.isoformat(),
                "reason": record.reason,
                "evidence_mode": record.evidence_mode,
            }
            for record in records
            if not record.accepted
        ],
    }


def _evaluate_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("status") != "ok":
        return False, f"overall status is {payload.get('status') or 'missing'}"

    operation_context = dict(payload.get("operation_context") or {})
    if operation_context:
        if operation_context.get("mode") != "formal":
            return False, f"operation_context mode is {operation_context.get('mode')}"
        if operation_context.get("target_date_closed") is not True:
            return False, "operation_context target_date_closed is not true"
        if operation_context.get("allow_unclosed_target_date") is True:
            return False, "operation_context allow_unclosed_target_date is true"

    summary = dict(payload.get("summary") or {})
    required_summary_statuses = {
        "system_status": "ok",
        "qlib_status": "ok",
        "workspace_status": "ok",
    }
    for key, expected in required_summary_statuses.items():
        actual = summary.get(key)
        if actual != expected:
            return False, f"{key} is {actual or 'missing'}"

    if int(summary.get("target_count") or 0) <= 0:
        return False, "target_count is zero"

    if operation_context:
        qlib = payload.get("qlib")
        if not isinstance(qlib, dict):
            return False, "qlib readiness evidence is missing"
        qlib_status = _qlib_evidence_status(qlib)
        if qlib_status != "ok":
            return False, f"qlib readiness evidence status is {qlib_status}"
        workspace_components = _get_workspace_components(payload)
        workspace_status = _workspace_core_status(workspace_components)
        if workspace_status != "ok":
            return False, f"workspace core evidence status is {workspace_status}"
        alpha_workspace = _get_alpha_workspace_consistency(payload)
        if not alpha_workspace:
            return False, "alpha_workspace_consistency evidence is missing"
        if alpha_workspace.get("status") != "ok":
            return (
                False,
                f"alpha_workspace_consistency status is "
                f"{alpha_workspace.get('status') or 'missing'}",
            )
        decision_data = _get_decision_data(payload)
        if not decision_data:
            return False, "decision_data readiness evidence is missing"
        if decision_data.get("status") != "ok":
            return False, f"decision_data status is {decision_data.get('status') or 'missing'}"
        if decision_data.get("readiness_status") != "ok":
            return (
                False,
                f"decision_data readiness_status is "
                f"{decision_data.get('readiness_status') or 'missing'}",
            )
        if decision_data.get("must_not_use_for_decision") is True:
            return False, "decision_data must_not_use_for_decision is true"
        quote_status = _decision_quote_freshness_status(decision_data)
        if quote_status != "ok":
            return False, f"decision quote freshness status is {quote_status}"

    accounts = list(payload.get("accounts") or [])
    if not accounts:
        return False, "accounts evidence is missing"

    for account in accounts:
        account_id = account.get("account_id") or "-"
        if account.get("status") != "ok":
            return False, f"account {account_id} status is {account.get('status')}"
        risk = dict(account.get("risk_center_daily_report") or {})
        if risk.get("status") != "ok":
            return False, f"account {account_id} risk status is {risk.get('status')}"
        if operation_context:
            pre_trade = dict(risk.get("pre_trade_check") or {})
            if pre_trade.get("status") != "ok":
                return (
                    False,
                    f"account {account_id} pre-trade risk status is "
                    f"{pre_trade.get('status') or 'missing'}",
                )
            post_investment = dict(risk.get("post_investment_check") or {})
            if post_investment.get("passed") is not True:
                return (
                    False,
                    f"account {account_id} post-investment risk passed is "
                    f"{post_investment.get('passed')}",
                )
        advisor = dict(account.get("auto_advisor") or {})
        if advisor.get("status") != "ok":
            return False, f"account {account_id} advisor status is {advisor.get('status')}"

    return True, "accepted"
