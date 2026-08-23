"""Record a validated DATA-01 isolated restore snapshot as local evidence.

This command only reads a JSON snapshot produced by an already completed,
isolated restore.  It never connects to PostgreSQL/VPS, runs ``pg_restore``,
creates a database, enters maintenance, or changes production state.  Without
``--write`` it is a dry-run; writing is append-only and content-addressed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Direct script invocation places ``scripts`` rather than the repository root
# on ``sys.path``.  Keep this recorder usable as the documented server-side
# command without requiring package installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.data_center.application.data01_restore_evidence import (
    data01_restore_artifact_sha256,
    parse_data01_restore_snapshot,
    serialize_data01_restore_evidence,
)


@dataclass(frozen=True, slots=True)
class Data01EvidenceRecording:
    """Deterministic result of one offline restore-evidence recording."""

    artifact_sha256: str
    source_payload_sha256: str
    isolated_restore_verified: bool
    written: bool
    path: Path | None


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write canonical evidence without overwriting existing bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "data01-isolated-restore" / digest[:2]).resolve()
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


def record_data01_restore_evidence(
    input_path: Path,
    *,
    output_root: Path | None = None,
    write: bool = False,
) -> Data01EvidenceRecording:
    """Validate one restore snapshot and optionally append canonical evidence."""

    source_payload = input_path.read_bytes()
    report = parse_data01_restore_snapshot(source_payload)
    canonical_payload = serialize_data01_restore_evidence(report)
    artifact_digest = data01_restore_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _write_append_only(output_root, artifact_digest, canonical_payload)
    return Data01EvidenceRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        isolated_restore_verified=report.isolated_restore_verified,
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="restore snapshot JSON path")
    parser.add_argument(
        "--output-root", type=Path, help="local root for content-addressed evidence"
    )
    parser.add_argument("--write", action="store_true", help="append canonical evidence")
    return parser


def main() -> int:
    """Validate one snapshot and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_data01_restore_evidence(
        args.input,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "artifact_sha256": result.artifact_sha256,
        "evidence_scope": "isolated_restore_only",
        "isolated_restore_verified": result.isolated_restore_verified,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "source_payload_sha256": result.source_payload_sha256,
        "written": result.written,
    }
    if result.path is not None:
        output["path"] = str(result.path)
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
