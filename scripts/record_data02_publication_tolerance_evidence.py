"""Record an offline DATA-02 four-Publication numeric tolerance snapshot.

The command only consumes a caller-provided ``select_only`` JSON envelope.
It performs no database, provider, network, deployment or Publication write.
Without ``--write`` it is a dry-run; explicit writing is append-only and
content-addressed under a caller-selected local directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_REGISTRY = REPO_ROOT / "governance" / "data02_numeric_tolerance_policies.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.data_center.application.data02_publication_tolerance_evidence import (
    data02_publication_tolerance_artifact_sha256,
    parse_data02_publication_tolerance_snapshot,
    serialize_data02_publication_tolerance_evidence,
)


@dataclass(frozen=True, slots=True)
class Data02PublicationToleranceRecording:
    """Deterministic result of one offline tolerance evidence recording."""

    artifact_sha256: str
    source_payload_sha256: str
    policy_registry_sha256: str
    reconciliation_passed: bool
    breach_count: int
    written: bool
    path: Path | None


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write content-addressed bytes without replacing an existing artifact."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "data02-four-publication-tolerance" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise ValueError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    digest_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise ValueError("content-addressed artifact collision")
        if not digest_path.exists():
            raise ValueError("content-addressed digest sidecar is missing")
        if digest_path.read_text(encoding="ascii") != f"{digest}\n":
            raise ValueError("content-addressed digest sidecar collision")
        return artifact_path, False
    if digest_path.exists():
        raise ValueError("content-addressed artifact is missing")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as artifact_file:
        artifact_file.write(payload)
    with digest_path.open("xb") as digest_file:
        digest_file.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def record_data02_publication_tolerance_evidence(
    input_path: Path,
    *,
    output_root: Path | None = None,
    write: bool = False,
) -> Data02PublicationToleranceRecording:
    """Validate against the repository policy truth and optionally append evidence."""

    source_payload = input_path.read_bytes()
    policy_registry_payload = DEFAULT_POLICY_REGISTRY.read_bytes()
    report = parse_data02_publication_tolerance_snapshot(
        source_payload,
        policy_registry_payload=policy_registry_payload,
    )
    canonical_payload = serialize_data02_publication_tolerance_evidence(report)
    artifact_digest = data02_publication_tolerance_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _write_append_only(output_root, artifact_digest, canonical_payload)
    return Data02PublicationToleranceRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        policy_registry_sha256=hashlib.sha256(policy_registry_payload).hexdigest(),
        reconciliation_passed=report.reconciliation_passed,
        breach_count=report.breach_count,
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="four-Publication numeric tolerance snapshot JSON path",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local root for content-addressed evidence artifacts",
    )
    parser.add_argument("--write", action="store_true", help="append canonical evidence")
    return parser


def main() -> int:
    """Validate one snapshot and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_data02_publication_tolerance_evidence(
        args.input,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "artifact_sha256": result.artifact_sha256,
        "breach_count": result.breach_count,
        "evidence_scope": "data02_four_publication_numeric_tolerance",
        "production_claim": False,
        "production_ready": False,
        "policy_registry_sha256": result.policy_registry_sha256,
        "reconciliation_passed": result.reconciliation_passed,
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
