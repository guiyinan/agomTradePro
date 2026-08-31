"""Canonical serialization for offline TAR-01 baseline evidence.

This module serializes an already validated report.  It does not decide whether
the report is real production evidence and it cannot enable any runtime path.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Final

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineContractError,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineReport,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloMeasurement,
)

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_EVIDENCE_SCOPES: Final[frozenset[str]] = frozenset(
    {"offline_snapshot", "controlled_staging_observation"}
)


class TerminalRuntimeBaselineEvidenceError(ValueError):
    """Raised when an evidence artifact cannot be canonically serialized."""


def _utc_text(value: datetime) -> str:
    """Encode an aware timestamp as canonical UTC with microseconds."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeBaselineEvidenceError("evidence timestamps must be timezone-aware")
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _metric_payload(metric: TerminalRuntimeBaselineMetric) -> dict[str, object]:
    """Serialize one validated baseline metric."""

    return {
        "key": metric.key,
        "reason": metric.reason,
        "status": metric.status.value,
        "value": metric.value,
    }


def _slo_payload(measurement: TerminalRuntimeSloMeasurement) -> dict[str, object]:
    """Serialize one validated hard-SLO measurement."""

    return {
        "key": measurement.key,
        "reason": measurement.reason,
        "status": measurement.status.value,
        "value": measurement.value,
    }


def _validate_report(report: TerminalRuntimeBaselineReport) -> None:
    """Revalidate an untrusted report before serialization."""

    if type(report) is not TerminalRuntimeBaselineReport:
        raise TerminalRuntimeBaselineEvidenceError("report type is invalid")
    try:
        report.__post_init__()
    except (AttributeError, TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
        raise TerminalRuntimeBaselineEvidenceError("report failed canonical validation") from exc


def serialize_terminal_runtime_baseline_report(
    report: TerminalRuntimeBaselineReport,
    *,
    source_kind: str,
    source_payload_sha256: str,
    evidence_scope: str = "offline_snapshot",
) -> bytes:
    """Serialize a validated report into deterministic, non-enabling JSON bytes."""

    _validate_report(report)
    if type(source_kind) is not str or _TOKEN_RE.fullmatch(source_kind) is None:
        raise TerminalRuntimeBaselineEvidenceError("source_kind is invalid")
    if (
        type(source_payload_sha256) is not str
        or _SHA256_RE.fullmatch(source_payload_sha256) is None
    ):
        raise TerminalRuntimeBaselineEvidenceError("source_payload_sha256 is invalid")
    if evidence_scope not in _EVIDENCE_SCOPES:
        raise TerminalRuntimeBaselineEvidenceError("evidence_scope is invalid")
    candidate = report.samples[0].candidate_identity
    if candidate is None:
        raise TerminalRuntimeBaselineEvidenceError("capacity evidence must bind a candidate")
    slo_report = report.slo_report
    if slo_report is None:
        raise TerminalRuntimeBaselineEvidenceError("capacity evidence must include hard SLOs")
    payload: dict[str, object] = {
        "candidate": {
            "candidate_commit": candidate.candidate_commit,
            "candidate_release": candidate.candidate_release,
            "oci_revision": candidate.oci_revision,
            "runtime_manifest_digest": candidate.runtime_manifest_digest,
            "test_matrix_digest": candidate.test_matrix_digest,
        },
        "computed_ready_for_capacity_gate": report.ready_for_capacity_gate,
        "evidence_scope": evidence_scope,
        "format": "terminal-runtime-baseline-evidence.v1",
        "runtime_enablement": "not_authorized",
        "samples": [
            {
                "captured_at": _utc_text(sample.captured_at),
                "concurrency": sample.concurrency,
                "environment": sample.environment,
                "metrics": [_metric_payload(metric) for metric in sample.metrics],
                "sample_count": sample.sample_count,
            }
            for sample in sorted(report.samples, key=lambda item: item.concurrency)
        ],
        "slo_report": {
            "captured_at": _utc_text(slo_report.captured_at),
            "environment": slo_report.environment,
            "measurements": [_slo_payload(item) for item in slo_report.measurements],
        },
        "source": {
            "kind": source_kind,
            "payload_sha256": source_payload_sha256,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def terminal_runtime_baseline_artifact_sha256(payload: bytes) -> str:
    """Return the content address of a serialized evidence artifact."""

    if type(payload) is not bytes or not payload:
        raise TerminalRuntimeBaselineEvidenceError("artifact payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()
