#!/usr/bin/env python
"""Validate and optionally append a DATA-02 successor checkpoint.

The command consumes an externally captured, candidate-bound, SELECT-only
checkpoint.  It never connects to PostgreSQL/VPS, runs a backfill, changes a
publication, or enables decision runtime.  Without ``--write`` it is a dry
run; explicit output is append-only and content-addressed under a caller-
selected local/server-side root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.data_center.application.data02_successor_checkpoint import (  # noqa: E402
    Data02SuccessorCheckpoint,
    data02_successor_checkpoint_artifact_sha256,
    parse_data02_successor_checkpoint,
    serialize_data02_successor_checkpoint,
)


@dataclass(frozen=True, slots=True)
class Data02SuccessorCheckpointRecording:
    """Deterministic result of one offline checkpoint recording."""

    artifact_sha256: str
    source_payload_sha256: str
    data02_execution_ready: bool
    data02_exit_gate_complete: bool
    publication_identity_count: int
    written: bool
    path: Path | None


def _append(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Append canonical bytes without overwriting an existing address."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "data02-successor-checkpoint" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise ValueError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    sidecar_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise ValueError("content-addressed artifact collision")
        if sidecar_path.exists() and sidecar_path.read_text(encoding="ascii") != f"{digest}\n":
            raise ValueError("content-addressed digest sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as handle:
        handle.write(payload)
    with sidecar_path.open("xb") as handle:
        handle.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def _publication_identity_count(report: Data02SuccessorCheckpoint) -> int:
    """Return the number of validated immutable publication identities."""

    datasets = report.publication_rebuild_dry_run["datasets"]
    if not isinstance(datasets, dict):
        raise RuntimeError("validated publication datasets are malformed")
    return len(datasets)


def record_data02_successor_checkpoint(
    input_path: Path,
    *,
    output_root: Path | None = None,
    write: bool = False,
) -> Data02SuccessorCheckpointRecording:
    """Validate one checkpoint and optionally append local evidence."""

    source_payload = input_path.read_bytes()
    report = parse_data02_successor_checkpoint(source_payload)
    canonical_payload = serialize_data02_successor_checkpoint(report)
    artifact_digest = data02_successor_checkpoint_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _append(output_root, artifact_digest, canonical_payload)
    gate = report.gate
    return Data02SuccessorCheckpointRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        data02_execution_ready=bool(gate["data02_execution_ready"]),
        data02_exit_gate_complete=bool(gate["data02_exit_gate_complete"]),
        publication_identity_count=_publication_identity_count(report),
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="checkpoint JSON path")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local content-addressed evidence root; required with --write",
    )
    parser.add_argument("--write", action="store_true", help="append locally; default is dry-run")
    return parser


def main() -> int:
    """Validate one checkpoint and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_data02_successor_checkpoint(
        args.input,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "artifact_sha256": result.artifact_sha256,
        "data02_execution_ready": result.data02_execution_ready,
        "data02_exit_gate_complete": result.data02_exit_gate_complete,
        "evidence_scope": "data02_successor_production_readonly_checkpoint",
        "production_claim": False,
        "production_ready": False,
        "publication_identity_count": result.publication_identity_count,
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
