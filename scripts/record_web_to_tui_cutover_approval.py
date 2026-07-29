#!/usr/bin/env python
"""Record one candidate-bound M5 owner or reviewer approval attestation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
ATTESTATION_VERSION = "web-to-tui-cutover-approval-attestation.v1"

module_prefix = "scripts." if __package__ else ""
review_builder: Any = importlib.import_module(f"{module_prefix}build_web_to_tui_review_snapshot")


class ApprovalEvidenceError(RuntimeError):
    """Raised when an approval cannot bind to a verified review snapshot."""


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ApprovalEvidenceError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _parse_date(value: object, *, field: str) -> date:
    """Parse one required ISO date."""

    if not isinstance(value, str) or not value.strip():
        raise ApprovalEvidenceError(f"Missing date field: {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ApprovalEvidenceError(f"Invalid date field: {field}") from exc


def build_approval_attestation(
    *,
    evidence: dict[str, Any],
    review_snapshot: dict[str, Any],
    review_reference: str,
    review_sha256: str,
    role: str,
    name: str,
    approved_at: date,
    as_of: date,
) -> dict[str, Any]:
    """Return one approval bound to the exact verified candidate review."""

    if role not in {"owner", "reviewer"}:
        raise ApprovalEvidenceError("Approval role must be owner or reviewer")
    normalized_name = name.strip()
    if not normalized_name:
        raise ApprovalEvidenceError("Approval name is required")
    if review_snapshot.get("version") != review_builder.SNAPSHOT_VERSION:
        raise ApprovalEvidenceError("Unsupported review snapshot version")
    gates = review_snapshot.get("gates")
    if not isinstance(gates, list):
        raise ApprovalEvidenceError("Review snapshot gates must be a list")
    gate_values = [_mapping(value) for value in gates]
    gate_keys = {str(value.get("key") or "").strip() for value in gate_values}
    if gate_keys != review_builder.REQUIRED_PRE_APPROVAL_GATES or not all(
        value.get("passed") is True for value in gate_values
    ):
        raise ApprovalEvidenceError("Review snapshot does not contain eight passing gates")

    candidate = _mapping(evidence.get("candidate"))
    candidate_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    if (
        str(review_snapshot.get("candidate_version") or "").strip() != candidate_version
        or str(review_snapshot.get("candidate_commit") or "").strip() != candidate_commit
        or str(review_snapshot.get("source_sha256") or "").strip() != source_sha256
    ):
        raise ApprovalEvidenceError("Review snapshot is bound to a different candidate")

    observation_end = _parse_date(
        candidate.get("observation_end"), field="candidate.observation_end"
    )
    reviewed_at = _parse_date(
        review_snapshot.get("reviewed_at"), field="review_snapshot.reviewed_at"
    )
    if not observation_end <= reviewed_at <= approved_at <= as_of:
        raise ApprovalEvidenceError("Approval date is outside the post-observation review window")

    approvals = _mapping(evidence.get("approvals"))
    other_role = "reviewer" if role == "owner" else "owner"
    other = _mapping(approvals.get(other_role))
    if str(other.get("name") or "").strip() == normalized_name:
        raise ApprovalEvidenceError("Owner and reviewer must be independent identities")

    return {
        "version": ATTESTATION_VERSION,
        "role": role,
        "name": normalized_name,
        "decision": "approve",
        "approved_at": approved_at.isoformat(),
        "candidate_version": candidate_version,
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "review_snapshot": review_reference,
        "evidence_snapshot_sha256": review_sha256,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one JSON object on disk."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--role", choices=("owner", "reviewer"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--approved-at", required=True, type=date.fromisoformat)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--attestation-output", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write the attestation and update cutover evidence; default is a dry run.",
    )
    args = parser.parse_args()

    try:
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        review_projection = _mapping(evidence.get("review_snapshot"))
        review_reference = str(review_projection.get("evidence") or "").strip()
        review_sha256 = str(review_projection.get("sha256") or "").strip()
        review_path = (ROOT / review_reference).resolve()
        if (
            not review_reference
            or not review_path.is_relative_to(ROOT.resolve())
            or not review_path.is_file()
            or hashlib.sha256(review_path.read_bytes()).hexdigest() != review_sha256
        ):
            raise ApprovalEvidenceError("Review snapshot path or SHA-256 is invalid")
        review_snapshot = _load_object(review_path)
        attestation = build_approval_attestation(
            evidence=evidence,
            review_snapshot=review_snapshot,
            review_reference=review_reference,
            review_sha256=review_sha256,
            role=args.role,
            name=args.name,
            approved_at=args.approved_at,
            as_of=args.as_of,
        )

        output_path = args.attestation_output.resolve()
        root = ROOT.resolve()
        if not output_path.is_relative_to(root):
            raise ApprovalEvidenceError("Approval attestation must be inside the repository")
        if output_path.exists() and not args.replace:
            raise ApprovalEvidenceError(
                f"Refusing to overwrite approval attestation: {output_path}"
            )
        serialized = (
            json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        projection = dict(attestation)
        projection.pop("version")
        projection["evidence"] = output_path.relative_to(root).as_posix()
        projection["evidence_sha256"] = hashlib.sha256(serialized).hexdigest()

        prepared = copy.deepcopy(evidence)
        approvals = _mapping(prepared.get("approvals"))
        if approvals.get(args.role) is not None and not args.replace:
            raise ApprovalEvidenceError(f"Approval role is already recorded: {args.role}")
        approvals[args.role] = projection
        prepared["approvals"] = approvals
        if args.write_evidence:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(output_path, attestation)
            _write_json_atomic(evidence_path, prepared)
    except (OSError, ValueError, json.JSONDecodeError, ApprovalEvidenceError) as exc:
        print(f"Web-to-TUI cutover approval: FAIL - {exc}")
        return 1

    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    print(
        f"Web-to-TUI cutover approval: {mode} - "
        f"role={attestation['role']} name={attestation['name']} "
        f"snapshot_sha256={attestation['evidence_snapshot_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
