#!/usr/bin/env python
"""Record a read-only EVID-02 current-head audit report.

The command consumes an externally captured snapshot only.  With the explicit
``--input-format select-only`` mode it first normalizes a SELECT-only capture
to the strict audit input.  It never opens a database or writes
approval/activation rows.  Without ``--write`` it prints the content address
and remains a dry run; writing is append-only and content-addressed under the
caller-provided local evidence root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.research.application.evid_02_head_audit import (
    Evid02HeadAuditError,
    Evid02SelectOnlySnapshot,
    build_evid_02_select_only_head_audit_report,
    evid_02_head_audit_artifact_sha256,
    normalize_evid_02_select_only_snapshot,
    parse_evid_02_head_audit_snapshot,
    serialize_evid_02_head_audit_report,
)


def _parser() -> argparse.ArgumentParser:
    """Build the strict read-only recorder CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="captured snapshot JSON path")
    parser.add_argument(
        "--input-format",
        choices=("canonical", "select-only"),
        default="canonical",
        help="input contract; select-only normalizes an external SELECT capture first",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local content-addressed evidence root; required with --write",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="append the report locally; default is a dry run",
    )
    return parser


def _load_snapshot(path: Path, input_format: str) -> tuple[bytes, Evid02SelectOnlySnapshot | None]:
    """Load either the strict snapshot or an explicit SELECT-only envelope."""

    payload = path.read_bytes()
    if input_format == "canonical":
        return payload, None
    if input_format == "select-only":
        normalized = normalize_evid_02_select_only_snapshot(payload)
        return normalized.canonical_payload, normalized
    raise Evid02HeadAuditError("input format is unsupported")


def _append(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Append one report without overwriting an existing content address."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "evid-02-head-audit" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise Evid02HeadAuditError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    sidecar_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise Evid02HeadAuditError("content-addressed artifact collision")
        if sidecar_path.exists() and sidecar_path.read_text(encoding="ascii") != f"{digest}\n":
            raise Evid02HeadAuditError("digest sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as handle:
        handle.write(payload)
    with sidecar_path.open("xb") as handle:
        handle.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def main() -> int:
    """Validate one snapshot and optionally append a local report."""

    args = _parser().parse_args()
    canonical_payload, normalized = _load_snapshot(args.input, args.input_format)
    report = (
        build_evid_02_select_only_head_audit_report(normalized)
        if normalized is not None
        else parse_evid_02_head_audit_snapshot(canonical_payload)
    )
    payload = serialize_evid_02_head_audit_report(report)
    digest = evid_02_head_audit_artifact_sha256(payload)
    result: dict[str, object] = {
        "artifact_sha256": digest,
        "human_approval_status": report.human_approval_status,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "written": False,
    }
    if normalized is not None:
        result["input_payload_sha256"] = normalized.source_payload_sha256
        result["capture"] = {
            "candidate_commit": normalized.capture.candidate_commit,
            "candidate_release": normalized.capture.candidate_release,
            "database_alias": normalized.capture.database_alias,
            "environment": normalized.capture.environment,
            "query_digest": normalized.capture.query_digest,
            "read_mode": normalized.capture.read_mode,
        }
    if args.write:
        if args.output_root is None:
            raise Evid02HeadAuditError("--output-root is required with --write")
        path, created = _append(args.output_root, digest, payload)
        result["path"] = str(path)
        result["written"] = created
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
