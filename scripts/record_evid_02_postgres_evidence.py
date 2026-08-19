"""Record an offline EVID-02 PostgreSQL harness report.

The command only parses a result emitted by the explicitly isolated local
PostgreSQL harness.  It never connects to PostgreSQL, writes approval data,
queries production, or invents a human approval decision.  Use ``--write``
only when an immutable local evidence artifact is intentionally requested.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.research.application.evid_02_postgres_evidence import (
    Evid02EvidenceError,
    evid_02_artifact_sha256,
    parse_evid_02_run_payload,
    serialize_evid_02_report,
)


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="raw harness result JSON path")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="root for content-addressed local evidence artifacts",
    )
    parser.add_argument(
        "--source-kind",
        default="local_postgresql_harness",
        help="bounded source identity token",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="append the canonical artifact; default is a dry run",
    )
    return parser


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write one content-addressed artifact without overwriting existing bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "evid-02-postgres" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise Evid02EvidenceError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    digest_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise Evid02EvidenceError("content-addressed artifact collision")
        if digest_path.exists() and digest_path.read_text(encoding="ascii") != f"{digest}\n":
            raise Evid02EvidenceError("content-addressed digest sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as artifact_file:
        artifact_file.write(payload)
    with digest_path.open("xb") as digest_file:
        digest_file.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def main() -> int:
    """Validate one offline harness payload and optionally append its artifact."""

    args = _parser().parse_args()
    raw_payload = args.input.read_bytes()
    report = parse_evid_02_run_payload(raw_payload, source_kind=args.source_kind)
    canonical_payload = serialize_evid_02_report(report)
    artifact_digest = evid_02_artifact_sha256(canonical_payload)
    output: dict[str, object] = {
        "artifact_sha256": artifact_digest,
        "collection_status": report.collection_status.value,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "written": False,
    }
    if args.write:
        if args.output_root is None:
            raise Evid02EvidenceError("--output-root is required with --write")
        path, created = _write_append_only(args.output_root, artifact_digest, canonical_payload)
        output["path"] = str(path)
        output["written"] = created
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
