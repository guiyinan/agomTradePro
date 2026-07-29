"""Unit contracts for M5 review snapshots and approval attestations."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import build_web_to_tui_review_snapshot as review_snapshot
from scripts import record_web_to_tui_cutover_approval as approval_evidence


def _evidence() -> dict[str, Any]:
    """Return a candidate-bound cutover evidence fixture."""

    return {
        "source_sha256": "a" * 64,
        "candidate": {
            "stable_version": "0.9.0-rc1",
            "candidate_commit": "b" * 40,
            "released_at": "2026-07-28",
            "observation_end": "2026-08-11",
        },
        "approvals": {"owner": None, "reviewer": None},
    }


def _readiness(*, failed_gate: str | None = None) -> SimpleNamespace:
    """Return a complete synthetic readiness result."""

    gates = [
        SimpleNamespace(
            key=key,
            passed=key != failed_gate,
            detail="verified synthetic gate",
        )
        for key in sorted(review_snapshot.REQUIRED_PRE_APPROVAL_GATES)
    ]
    gates.append(
        SimpleNamespace(
            key="cutover_approvals",
            passed=False,
            detail="awaiting owner and reviewer",
        )
    )
    return SimpleNamespace(
        as_of="2026-08-11",
        required_route_pages=108,
        required_tasks=101,
        gates=gates,
    )


def test_review_snapshot_requires_all_eight_preapproval_gates() -> None:
    """The review snapshot captures the exact passing non-approval gate set."""

    snapshot = review_snapshot.build_review_snapshot(
        evidence=_evidence(),
        readiness=_readiness(),
        reviewed_at=date(2026, 8, 11),
    )

    assert snapshot["version"] == review_snapshot.SNAPSHOT_VERSION
    assert snapshot["required_route_pages"] == 108
    assert snapshot["required_tasks"] == 101
    assert len(snapshot["gates"]) == 8
    assert all(gate["passed"] is True for gate in snapshot["gates"])


def test_review_snapshot_rejects_any_failed_preapproval_gate() -> None:
    """A review cannot begin while production telemetry or another gate fails."""

    with pytest.raises(review_snapshot.ReviewSnapshotError, match="not ready"):
        review_snapshot.build_review_snapshot(
            evidence=_evidence(),
            readiness=_readiness(failed_gate="production_telemetry"),
            reviewed_at=date(2026, 8, 11),
        )


def test_approval_attestation_binds_role_identity_candidate_and_snapshot() -> None:
    """One approval is an immutable projection of the reviewed candidate."""

    evidence = _evidence()
    snapshot = review_snapshot.build_review_snapshot(
        evidence=evidence,
        readiness=_readiness(),
        reviewed_at=date(2026, 8, 11),
    )
    attestation = approval_evidence.build_approval_attestation(
        evidence=evidence,
        review_snapshot=snapshot,
        review_reference="docs/plans/review.json",
        review_sha256="c" * 64,
        role="owner",
        name="terminal-owner",
        approved_at=date(2026, 8, 11),
        as_of=date(2026, 8, 11),
    )

    assert attestation["version"] == approval_evidence.ATTESTATION_VERSION
    assert attestation["role"] == "owner"
    assert attestation["candidate_commit"] == "b" * 40
    assert attestation["evidence_snapshot_sha256"] == "c" * 64


def test_reviewer_must_be_independent_and_follow_review() -> None:
    """One identity cannot self-approve or pre-approve the final evidence."""

    evidence = _evidence()
    evidence["approvals"]["owner"] = {"name": "same-person"}
    snapshot = review_snapshot.build_review_snapshot(
        evidence=evidence,
        readiness=_readiness(),
        reviewed_at=date(2026, 8, 11),
    )

    with pytest.raises(approval_evidence.ApprovalEvidenceError, match="independent"):
        approval_evidence.build_approval_attestation(
            evidence=evidence,
            review_snapshot=snapshot,
            review_reference="docs/plans/review.json",
            review_sha256="c" * 64,
            role="reviewer",
            name="same-person",
            approved_at=date(2026, 8, 11),
            as_of=date(2026, 8, 11),
        )

    with pytest.raises(approval_evidence.ApprovalEvidenceError, match="review window"):
        approval_evidence.build_approval_attestation(
            evidence=_evidence(),
            review_snapshot=snapshot,
            review_reference="docs/plans/review.json",
            review_sha256="c" * 64,
            role="reviewer",
            name="independent-reviewer",
            approved_at=date(2026, 8, 10),
            as_of=date(2026, 8, 11),
        )


def test_cli_writes_review_then_role_bound_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two dry-run-first CLIs atomically project their checked-in artifacts."""

    evidence_path = tmp_path / "cutover.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")
    review_path = tmp_path / "review.json"
    monkeypatch.setattr(review_snapshot, "ROOT", tmp_path)
    monkeypatch.setattr(
        review_snapshot.readiness_checker,
        "evaluate_readiness",
        lambda **_kwargs: _readiness(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_web_to_tui_review_snapshot.py",
            "--evidence",
            str(evidence_path),
            "--matrix",
            str(tmp_path / "matrix.csv"),
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--as-of",
            "2026-08-11",
            "--snapshot-output",
            str(review_path),
            "--write-evidence",
        ],
    )
    assert review_snapshot.main() == 0

    approval_path = tmp_path / "owner-approval.json"
    monkeypatch.setattr(approval_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_web_to_tui_cutover_approval.py",
            "--evidence",
            str(evidence_path),
            "--role",
            "owner",
            "--name",
            "terminal-owner",
            "--approved-at",
            "2026-08-11",
            "--as-of",
            "2026-08-11",
            "--attestation-output",
            str(approval_path),
            "--write-evidence",
        ],
    )
    assert approval_evidence.main() == 0

    updated = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert updated["review_snapshot"]["evidence"] == review_path.name
    assert updated["approvals"]["owner"]["evidence"] == approval_path.name
    assert updated["approvals"]["reviewer"] is None
