"""Pure tests for the EVID-02 read-only head audit contract."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.research.application.evid_02_head_audit import (
    EVID_02_HEAD_AUDIT_INPUT_FORMAT,
    EVID_02_SELECT_ONLY_SNAPSHOT_FORMAT,
    Evid02HeadAuditError,
    Evid02HeadAuditStatus,
    build_evid_02_select_only_head_audit_report,
    evid_02_head_audit_artifact_sha256,
    normalize_evid_02_select_only_snapshot,
    parse_evid_02_head_audit_snapshot,
    serialize_evid_02_head_audit_report,
)

_AS_OF = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_T0 = _AS_OF - timedelta(minutes=5)
_T1 = _AS_OF - timedelta(minutes=1)
_VALID_UNTIL = _AS_OF + timedelta(hours=1)


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _row(
    kind: str,
    seed: str,
    when: datetime,
    *,
    predecessor: str | None = None,
    approval_hash: str | None = None,
    operator_id: str = "operator.one",
    operator_version: str = "v1",
    definition_hash: str | None = None,
) -> dict[str, object]:
    return {
        "approval_hash": approval_hash,
        "content_hash": _digest(f"content:{seed}"),
        "definition_hash": definition_hash or _digest("definition:one"),
        "operator_id": operator_id,
        "operator_version": operator_version,
        "predecessor_hash": predecessor,
        "record_id": f"{kind}.record.{seed}",
        "record_version": "v1",
        "recorded_at": when.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "valid_until": _VALID_UNTIL.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }


def _snapshot(
    *,
    approval_rows: list[dict[str, object]] | None = None,
    activation_rows: list[dict[str, object]] | None = None,
    captured_at: datetime = _AS_OF,
    as_of: datetime = _AS_OF,
) -> bytes:
    return json.dumps(
        {
            "activation_rows": activation_rows or [],
            "approval_rows": approval_rows or [],
            "as_of": as_of.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "captured_at": captured_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "format": EVID_02_HEAD_AUDIT_INPUT_FORMAT,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _select_only_snapshot(
    *,
    approval_rows: list[dict[str, object]] | None = None,
    activation_rows: list[dict[str, object]] | None = None,
) -> bytes:
    """Build a strict external SELECT-only envelope for normalizer tests."""

    payload = json.loads(
        _snapshot(approval_rows=approval_rows, activation_rows=activation_rows).decode("utf-8")
    )
    payload["capture"] = {
        "candidate_commit": "a" * 40,
        "candidate_release": "20260823000100",
        "database_alias": "default",
        "environment": "production",
        "query_digest": _digest("evid-02-select-query-v1"),
        "read_mode": "select_only",
    }
    payload["format"] = EVID_02_SELECT_ONLY_SNAPSHOT_FORMAT
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_empty_ledgers_are_reported_without_production_claim() -> None:
    report = parse_evid_02_head_audit_snapshot(_snapshot())
    assert [summary.status for summary in report.summaries] == [
        Evid02HeadAuditStatus.EMPTY,
        Evid02HeadAuditStatus.EMPTY,
    ]
    payload = serialize_evid_02_head_audit_report(report)
    decoded = json.loads(payload)
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["human_approval_status"] == "not_collected"
    assert decoded["runtime_enablement"] == "not_authorized"


def test_linear_approval_and_activation_heads_are_reported() -> None:
    approval_root = _row("approval", "root", _T0)
    approval_head = _row("approval", "head", _T1, predecessor=approval_root["content_hash"])
    activation_root = _row("activation", "root", _T0, approval_hash=approval_root["content_hash"])
    activation_head = _row(
        "activation",
        "head",
        _T1,
        predecessor=activation_root["content_hash"],
        approval_hash=approval_head["content_hash"],
    )
    report = parse_evid_02_head_audit_snapshot(
        _snapshot(
            approval_rows=[approval_root, approval_head],
            activation_rows=[activation_root, activation_head],
        )
    )
    assert [summary.status for summary in report.summaries] == [
        Evid02HeadAuditStatus.OK,
        Evid02HeadAuditStatus.OK,
    ]
    assert report.summaries[0].head_hash == approval_head["content_hash"]
    assert report.summaries[1].head_hash == activation_head["content_hash"]


def test_activation_missing_approval_reference_is_corrupt() -> None:
    row = _row("activation", "root", _T0, approval_hash=_digest("missing"))
    report = parse_evid_02_head_audit_snapshot(_snapshot(activation_rows=[row]))
    assert report.summaries[1].status is Evid02HeadAuditStatus.CORRUPT
    assert "missing_approval_reference" in report.summaries[1].issues


def test_orphan_predecessor_is_corrupt() -> None:
    approval = _row("approval", "orphan", _T0, predecessor=_digest("missing"))
    report = parse_evid_02_head_audit_snapshot(_snapshot(approval_rows=[approval]))
    assert report.summaries[0].status is Evid02HeadAuditStatus.CORRUPT
    assert "orphan_predecessor" in report.summaries[0].issues


def test_fork_is_corrupt() -> None:
    root = _row("approval", "root", _T0)
    first = _row("approval", "first", _T1, predecessor=root["content_hash"])
    second = _row("approval", "second", _T1, predecessor=root["content_hash"])
    ordered = sorted(
        [root, first, second],
        key=lambda item: (str(item["recorded_at"]), str(item["content_hash"])),
    )
    report = parse_evid_02_head_audit_snapshot(_snapshot(approval_rows=ordered))
    assert report.summaries[0].status is Evid02HeadAuditStatus.CORRUPT
    assert "fork" in report.summaries[0].issues


def test_activation_approval_identity_drift_is_corrupt() -> None:
    approval = _row("approval", "approval", _T0)
    activation = _row(
        "activation",
        "activation",
        _T1,
        approval_hash=approval["content_hash"],
        operator_id="operator.two",
    )
    report = parse_evid_02_head_audit_snapshot(
        _snapshot(approval_rows=[approval], activation_rows=[activation])
    )
    assert report.summaries[1].status is Evid02HeadAuditStatus.CORRUPT
    assert "approval_identity_drift" in report.summaries[1].issues


def test_disconnected_root_is_corrupt() -> None:
    first = _row("approval", "first", _T0)
    second = _row("approval", "second", _T1)
    report = parse_evid_02_head_audit_snapshot(_snapshot(approval_rows=[first, second]))
    assert report.summaries[0].status is Evid02HeadAuditStatus.CORRUPT
    assert "root_count_invalid" in report.summaries[0].issues


def test_recorded_clock_regression_is_corrupt() -> None:
    root = _row("approval", "root", _T0)
    child = _row("approval", "child", _T0, predecessor=root["content_hash"])
    report = parse_evid_02_head_audit_snapshot(_snapshot(approval_rows=[root, child]))
    assert report.summaries[0].status is Evid02HeadAuditStatus.CORRUPT
    assert "recorded_clock_not_increasing" in report.summaries[0].issues


def test_future_row_is_rejected_before_selector_can_hide_it() -> None:
    future = _row("approval", "future", _AS_OF + timedelta(seconds=1))
    with pytest.raises(Evid02HeadAuditError, match="future row"):
        parse_evid_02_head_audit_snapshot(_snapshot(approval_rows=[future]))


def test_unknown_key_is_rejected() -> None:
    snapshot = json.loads(_snapshot())
    snapshot["unexpected"] = True
    with pytest.raises(Evid02HeadAuditError, match="key set"):
        parse_evid_02_head_audit_snapshot(json.dumps(snapshot).encode())


def test_secret_key_is_rejected_without_echoing_value() -> None:
    snapshot = json.loads(_snapshot())
    snapshot["approval_rows"] = [{"api_key": "do-not-echo"}]
    with pytest.raises(Evid02HeadAuditError, match="forbidden") as error:
        parse_evid_02_head_audit_snapshot(json.dumps(snapshot).encode())
    assert "do-not-echo" not in str(error.value)


def test_noncanonical_time_is_rejected() -> None:
    snapshot = json.loads(_snapshot())
    snapshot["captured_at"] = "2026-08-19T20:00:00+08:00"
    with pytest.raises(Evid02HeadAuditError, match="UTC-Z"):
        parse_evid_02_head_audit_snapshot(json.dumps(snapshot).encode())


def test_report_serialization_is_stable_and_content_addressed() -> None:
    report = parse_evid_02_head_audit_snapshot(_snapshot())
    first = serialize_evid_02_head_audit_report(report)
    second = serialize_evid_02_head_audit_report(report)
    assert first == second
    assert evid_02_head_audit_artifact_sha256(first) == hashlib.sha256(first).hexdigest()


def test_capture_time_before_as_of_is_rejected() -> None:
    with pytest.raises(Evid02HeadAuditError, match="captured_at"):
        parse_evid_02_head_audit_snapshot(_snapshot(captured_at=_T0, as_of=_AS_OF))


def test_select_only_snapshot_normalizes_to_strict_head_audit_input() -> None:
    payload = _select_only_snapshot()
    normalized = normalize_evid_02_select_only_snapshot(payload)
    report = parse_evid_02_head_audit_snapshot(normalized.canonical_payload)

    assert normalized.source_payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert report.source_payload_sha256 == hashlib.sha256(normalized.canonical_payload).hexdigest()
    assert normalized.capture.environment == "production"
    assert normalized.capture.read_mode == "select_only"
    assert [summary.status for summary in report.summaries] == [
        Evid02HeadAuditStatus.EMPTY,
        Evid02HeadAuditStatus.EMPTY,
    ]
    captured_report = build_evid_02_select_only_head_audit_report(normalized)
    captured_payload = json.loads(serialize_evid_02_head_audit_report(captured_report))
    assert captured_payload["source"]["payload_sha256"] == normalized.source_payload_sha256
    assert captured_payload["source"]["capture"]["candidate_commit"] == "a" * 40


@pytest.mark.parametrize("forbidden_key", ["mutation_performed", "human_approval_status"])
def test_select_only_snapshot_rejects_claim_or_mutation_fields(forbidden_key: str) -> None:
    payload = json.loads(_select_only_snapshot())
    payload[forbidden_key] = False if forbidden_key == "mutation_performed" else "not_collected"
    with pytest.raises(Evid02HeadAuditError, match="key set"):
        normalize_evid_02_select_only_snapshot(json.dumps(payload).encode())


def test_recorder_explicit_select_only_mode_is_dry_run_and_append_only(
    tmp_path, monkeypatch, capsys
) -> None:
    from scripts.record_evid_02_head_audit import main

    input_path = tmp_path / "select-only.json"
    input_path.write_bytes(_select_only_snapshot())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_evid_02_head_audit.py",
            "--input",
            str(input_path),
            "--input-format",
            "select-only",
        ],
    )
    assert main() == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["written"] is False
    assert dry_run["production_claim"] is False
    assert dry_run["capture"]["read_mode"] == "select_only"
    assert not (tmp_path / "evid-02-head-audit").exists()

    output_root = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_evid_02_head_audit.py",
            "--input",
            str(input_path),
            "--input-format",
            "select-only",
            "--output-root",
            str(output_root),
            "--write",
        ],
    )
    assert main() == 0
    written = json.loads(capsys.readouterr().out)
    assert written["written"] is True
    artifact_path = Path(written["path"])
    assert artifact_path.is_file()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert (
        artifact["source"]["payload_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    )
    assert artifact["source"]["capture"]["read_mode"] == "select_only"
