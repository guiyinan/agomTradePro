"""Record candidate-bound, read-only AUD-03 operational observations.

The command consumes an external ``select_only`` envelope.  It never connects
to a VPS or database, runs migrations, claims/publishes audit events, invokes
Celery, or changes archive state.  Without ``--write`` it is a dry-run;
explicit output is append-only and content-addressed under a caller-selected
server-side directory.
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

from apps.audit.application.aud03_operational_observation_evidence import (
    aud03_operational_observation_artifact_sha256,
    parse_aud03_operational_observation,
    serialize_aud03_operational_observation,
)


@dataclass(frozen=True, slots=True)
class Aud03EvidenceRecording:
    """Deterministic result of one offline AUD-03 recording."""

    artifact_sha256: str
    source_payload_sha256: str
    missing_section_count: int
    archive_integrity_mismatch_count: int
    written: bool
    path: Path | None


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write one content-addressed artifact without overwriting existing bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "aud03-operational-observation" / digest[:2]).resolve()
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


def record_aud03_operational_observation(
    input_path: Path,
    *,
    output_root: Path | None = None,
    write: bool = False,
) -> Aud03EvidenceRecording:
    """Validate one external observation envelope and optionally append evidence."""

    source_payload = input_path.read_bytes()
    report = parse_aud03_operational_observation(source_payload)
    canonical_payload = serialize_aud03_operational_observation(report)
    artifact_digest = aud03_operational_observation_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _write_append_only(output_root, artifact_digest, canonical_payload)
    serialized = report.to_dict()
    checks = serialized["checks"]
    if not isinstance(checks, dict):
        raise RuntimeError("serialized AUD-03 checks are malformed")
    return Aud03EvidenceRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        missing_section_count=int(checks["missing_section_count"]),
        archive_integrity_mismatch_count=int(checks["archive_integrity_mismatch_count"]),
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="AUD-03 observation envelope JSON"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local root for content-addressed operational evidence",
    )
    parser.add_argument("--write", action="store_true", help="append canonical evidence")
    return parser


def main() -> int:
    """Validate one envelope and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_aud03_operational_observation(
        args.input,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "archive_integrity_mismatch_count": result.archive_integrity_mismatch_count,
        "artifact_sha256": result.artifact_sha256,
        "evidence_scope": "aud03_external_operational_observation",
        "missing_section_count": result.missing_section_count,
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
