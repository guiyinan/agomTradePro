"""Record externally captured DATA-03 readiness observations.

The command consumes a candidate-bound ``http_get_read_only`` envelope.  It
never connects to a VPS, calls an HTTP endpoint, changes maintenance state, or
writes production data.  Without ``--write`` it is a dry-run; explicit output
is append-only and content-addressed under a caller-selected server-side root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Direct server-side CLI invocation starts with ``scripts`` on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.data_center.application.data03_readiness_evidence import (
    data03_readiness_artifact_sha256,
    parse_data03_readiness_snapshot,
    serialize_data03_readiness_evidence,
)


@dataclass(frozen=True, slots=True)
class Data03EvidenceRecording:
    """Deterministic result of one offline readiness recording."""

    artifact_sha256: str
    source_payload_sha256: str
    decision_blocker_count: int
    service_failure_count: int
    smoke_failure_count: int
    written: bool
    path: Path | None


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write one content-addressed artifact without overwriting existing bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "data03-readiness" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise ValueError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    digest_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise ValueError("content-addressed artifact collision")
        if digest_path.exists() and digest_path.read_text(encoding="ascii") != f"{digest}\n":
            raise ValueError("content-addressed digest sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as artifact_file:
        artifact_file.write(payload)
    with digest_path.open("xb") as digest_file:
        digest_file.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def record_data03_readiness_evidence(
    input_path: Path,
    *,
    output_root: Path | None = None,
    write: bool = False,
) -> Data03EvidenceRecording:
    """Validate one external probe envelope and optionally append local evidence."""

    source_payload = input_path.read_bytes()
    report = parse_data03_readiness_snapshot(source_payload)
    canonical_payload = serialize_data03_readiness_evidence(report)
    artifact_digest = data03_readiness_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _write_append_only(output_root, artifact_digest, canonical_payload)
    serialized = report.to_dict()
    checks = serialized["checks"]
    if not isinstance(checks, dict):
        raise RuntimeError("serialized DATA-03 checks are malformed")
    return Data03EvidenceRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        decision_blocker_count=int(checks["decision_blocker_count"]),
        service_failure_count=int(checks["service_failure_count"]),
        smoke_failure_count=int(checks["smoke_failure_count"]),
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="readiness envelope JSON path")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local root for content-addressed readiness artifacts",
    )
    parser.add_argument("--write", action="store_true", help="append canonical evidence")
    return parser


def main() -> int:
    """Validate one envelope and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_data03_readiness_evidence(
        args.input,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "artifact_sha256": result.artifact_sha256,
        "decision_blocker_count": result.decision_blocker_count,
        "evidence_scope": "data03_external_readiness_observation",
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "service_failure_count": result.service_failure_count,
        "smoke_failure_count": result.smoke_failure_count,
        "source_payload_sha256": result.source_payload_sha256,
        "written": result.written,
    }
    if result.path is not None:
        output["path"] = str(result.path)
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
