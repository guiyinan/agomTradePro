"""Typed, fail-closed projection for current broker reconciliation runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

JsonObject = dict[str, object]

_RUN_STATUSES: Final = frozenset({"completed", "review_required", "resolved", "escalated"})
_DIMENSIONS: Final = ("order", "fill", "cash", "position")
_SEVERITIES: Final = frozenset({"P0", "P1"})
_DIFFERENCE_STATUSES: Final = frozenset({"open", "resolved", "escalated"})
_RESOLUTIONS: Final = frozenset(
    {"accept_broker_fact", "manual_adjustment", "verified_no_change", "escalate"}
)
_VALUE_FIELDS: Final[dict[str, frozenset[str]]] = {
    "order": frozenset({"client_order_id", "broker_order_id", "status"}),
    "fill": frozenset({"broker_trade_id"}),
    "cash": frozenset({"account_id", "cash_available"}),
    "position": frozenset({"quantity"}),
}
_MAX_DIFFERENCES: Final = 500


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("datetime is missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed.astimezone(UTC)


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("positive integer required")
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("non-negative count required")
    return value


def _bounded_text(value: object, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("text required")
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        raise ValueError("text is outside its bounded contract")
    return normalized


def _decimal_text(value: object) -> str:
    text = _bounded_text(value, maximum=64)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("decimal text required") from exc
    if not number.is_finite():
        raise ValueError("finite decimal required")
    return text


def _project_side(value: object, *, dimension: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError("difference side must be an object")
    allowed = _VALUE_FIELDS[dimension]
    keys = {str(key) for key in value}
    if keys - allowed:
        raise ValueError("difference side contains unknown fields")
    projected: JsonObject = {}
    for key in sorted(keys):
        raw = value.get(key)
        if key == "account_id":
            projected[key] = _positive_int(raw)
        elif key in {"cash_available", "quantity"}:
            projected[key] = _decimal_text(raw)
        else:
            projected[key] = _bounded_text(raw, maximum=160, allow_empty=True)
    return projected


def _project_difference(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError("difference must be an object")
    required = {
        "dimension",
        "difference_key",
        "severity",
        "expected",
        "actual",
        "reason",
        "status",
    }
    if {str(key) for key in value} != required:
        raise ValueError("difference schema is not exact")
    dimension = _bounded_text(value.get("dimension"), maximum=16)
    if dimension not in _DIMENSIONS:
        raise ValueError("difference dimension is invalid")
    severity = _bounded_text(value.get("severity"), maximum=8)
    if severity not in _SEVERITIES:
        raise ValueError("difference severity is invalid")
    status = _bounded_text(value.get("status"), maximum=16)
    if status not in _DIFFERENCE_STATUSES:
        raise ValueError("difference status is invalid")
    return {
        "dimension": dimension,
        "difference_key": _bounded_text(value.get("difference_key"), maximum=160),
        "severity": severity,
        "expected": _project_side(value.get("expected"), dimension=dimension),
        "actual": _project_side(value.get("actual"), dimension=dimension),
        "reason": _bounded_text(value.get("reason"), maximum=1000),
        "status": status,
    }


def _content_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerReconciliationProjection:
    """One display-only run that cannot authorize trading or decisions."""

    payload: JsonObject

    def to_payload(self) -> JsonObject:
        """Return a detached JSON-compatible projection."""

        return dict(self.payload)


def _blocked(
    raw: Mapping[str, object], *, evaluated_at: datetime, blocker: str
) -> BrokerReconciliationProjection:
    event_id = raw.get("id")
    account_id = raw.get("account_id")
    safe: JsonObject = {
        "id": event_id if isinstance(event_id, int) and not isinstance(event_id, bool) else None,
        "account_id": (
            account_id if isinstance(account_id, int) and not isinstance(account_id, bool) else None
        ),
        "status": "blocked",
        "evaluated_at": evaluated_at.isoformat(),
        "content_hash": None,
        "summary": {},
        "difference_counts": {},
        "differences": [],
        "blocker_codes": [blocker],
        "permission": "display_only",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    return BrokerReconciliationProjection(payload=safe)


def project_broker_reconciliation(
    raw: Mapping[str, object], *, evaluated_at: datetime
) -> BrokerReconciliationProjection:
    """Validate and project one repository row; malformed runs expose no raw details."""

    if type(evaluated_at) is not datetime or evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    evaluated = evaluated_at.astimezone(UTC)
    try:
        run_id = _positive_int(raw.get("id"))
        account_id = _positive_int(raw.get("account_id"))
        status = _bounded_text(raw.get("status"), maximum=32)
        if status not in _RUN_STATUSES:
            raise ValueError("run status is invalid")
        started = _aware_datetime(raw.get("started_at"))
        completed_raw = raw.get("completed_at")
        completed = _aware_datetime(completed_raw) if completed_raw is not None else None
        if started > evaluated or (completed is not None and not started <= completed <= evaluated):
            raise ValueError("run times are inverted or future")
        if (status in {"completed", "resolved"}) != (completed is not None):
            raise ValueError("run completion time contradicts status")

        summary_raw = raw.get("summary")
        if not isinstance(summary_raw, Mapping):
            raise ValueError("summary must be an object")
        summary_keys = {str(key) for key in summary_raw}
        base_keys = {
            "source",
            "snapshot_id",
            "snapshot_captured_at",
            "difference_count",
            "p0_auto_stop",
        }
        resolved_keys = base_keys | {"resolution", "resolution_reason", "resolved_by"}
        if summary_keys not in {frozenset(base_keys), frozenset(resolved_keys)}:
            raise ValueError("summary schema is not exact")
        source = _bounded_text(summary_raw.get("source"), maximum=64)
        if source != "qmt_snapshot_reconciliation":
            raise ValueError("summary source is invalid")
        captured = _aware_datetime(summary_raw.get("snapshot_captured_at"))
        if captured > started:
            raise ValueError("snapshot was captured after reconciliation started")
        difference_count = _count(summary_raw.get("difference_count"))
        p0_auto_stop = summary_raw.get("p0_auto_stop")
        if not isinstance(p0_auto_stop, bool):
            raise ValueError("p0_auto_stop must be boolean")
        summary: JsonObject = {
            "source": source,
            "snapshot_id": _positive_int(summary_raw.get("snapshot_id")),
            "snapshot_captured_at": captured.isoformat(),
            "difference_count": difference_count,
            "p0_auto_stop": p0_auto_stop,
        }
        if summary_keys == resolved_keys:
            resolution = _bounded_text(summary_raw.get("resolution"), maximum=32)
            if resolution not in _RESOLUTIONS:
                raise ValueError("resolution is invalid")
            if (status == "escalated") != (resolution == "escalate"):
                raise ValueError("resolution contradicts run status")
            summary["resolution"] = resolution
        elif status in {"resolved", "escalated"}:
            raise ValueError("closed run is missing resolution")

        rows_raw = raw.get("differences")
        if (
            not isinstance(rows_raw, Sequence)
            or isinstance(rows_raw, (str, bytes))
            or len(rows_raw) > _MAX_DIFFERENCES
        ):
            raise ValueError("differences must be a bounded list")
        differences = [_project_difference(row) for row in rows_raw]
        identities = [(row["dimension"], row["difference_key"]) for row in differences]
        if len(set(identities)) != len(identities):
            raise ValueError("difference identity is duplicated")
        counts = {
            dimension: _count(raw.get(f"{dimension}_difference_count")) for dimension in _DIMENSIONS
        }
        actual_counts = {
            dimension: sum(row["dimension"] == dimension for row in differences)
            for dimension in _DIMENSIONS
        }
        if counts != actual_counts or difference_count != len(differences):
            raise ValueError("difference counts do not conserve")
        if p0_auto_stop != any(row["severity"] == "P0" for row in differences):
            raise ValueError("p0_auto_stop contradicts differences")
        expected_difference_status = {
            "completed": None,
            "review_required": "open",
            "resolved": "resolved",
            "escalated": "escalated",
        }[status]
        if (expected_difference_status is None and differences) or (
            expected_difference_status is not None
            and any(row["status"] != expected_difference_status for row in differences)
        ):
            raise ValueError("difference statuses contradict run status")

        content: JsonObject = {
            "id": run_id,
            "account_id": account_id,
            "status": status,
            "summary": summary,
            "difference_counts": counts,
            "differences": differences,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat() if completed is not None else None,
        }
        payload = {
            **content,
            "evaluated_at": evaluated.isoformat(),
            "content_hash": _content_hash(content),
            "blocker_codes": [],
            "permission": "display_only",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        return BrokerReconciliationProjection(payload=payload)
    except (ArithmeticError, TypeError, ValueError):
        return _blocked(raw, evaluated_at=evaluated, blocker="broker_reconciliation_invalid")


__all__ = ["BrokerReconciliationProjection", "project_broker_reconciliation"]
