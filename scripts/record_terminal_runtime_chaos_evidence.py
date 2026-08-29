"""Record a validated offline TAR-05 chaos snapshot as evidence.

The recorder only reads a caller-supplied JSON snapshot.  It never starts a
worker, contacts Redis/Celery/Docker, sends HTTP traffic, or injects a fault.
Without ``--write`` it is a dry-run; when writing is requested the artifact is
append-only and content-addressed under the supplied local output root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

# The application package has a legacy eager ``__init__`` that imports
# Django-backed use cases.  Keep this recorder offline when invoked directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if __package__ in (None, "") and "apps.agent_runtime.application" not in sys.modules:
    application_package = ModuleType("apps.agent_runtime.application")
    application_package.__path__ = [str(REPO_ROOT / "apps" / "agent_runtime" / "application")]
    sys.modules["apps.agent_runtime.application"] = application_package

from apps.agent_runtime.application.terminal_runtime_chaos_evidence import (
    TerminalRuntimeChaosCandidate,
    serialize_terminal_runtime_chaos_evidence,
    terminal_runtime_chaos_artifact_sha256,
    validate_terminal_runtime_chaos_evidence,
)


@dataclass(frozen=True, slots=True)
class ChaosEvidenceRecording:
    """Deterministic result of validating one offline chaos snapshot."""

    artifact_sha256: str
    source_payload_sha256: str
    ready_for_chaos_gate: bool
    candidate_binding_verified: bool
    written: bool
    path: Path | None


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded JSON object without accepting non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _load_json(path: Path) -> tuple[bytes, Mapping[str, object]]:
    """Read one UTF-8 JSON object and retain its exact source bytes."""

    source_payload = path.read_bytes()
    try:
        decoded = json.loads(source_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("input must be valid UTF-8 JSON") from exc
    return source_payload, _mapping(decoded, "input")


def _load_expected_candidate(path: Path | None) -> TerminalRuntimeChaosCandidate | None:
    """Load an optional independently supplied candidate identity."""

    if path is None:
        return None
    _, decoded = _load_json(path)
    expected = _mapping(decoded, "expected_candidate")
    expected_keys = {
        "candidate_commit",
        "candidate_release",
        "oci_revision",
        "test_matrix_digest",
    }
    if set(expected) != expected_keys:
        raise ValueError("expected_candidate has unexpected keys")

    def _string(field_name: str) -> str:
        value = expected[field_name]
        if type(value) is not str:
            raise ValueError(f"expected_candidate.{field_name} must be a string")
        return value

    return TerminalRuntimeChaosCandidate(
        candidate_commit=_string("candidate_commit"),
        candidate_release=_string("candidate_release"),
        oci_revision=_string("oci_revision"),
        test_matrix_digest=_string("test_matrix_digest"),
    )


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write a content-addressed artifact without overwriting existing bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "terminal-agent-chaos" / digest[:2]).resolve()
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


def record_terminal_runtime_chaos_evidence(
    input_path: Path,
    *,
    expected_candidate_path: Path | None = None,
    output_root: Path | None = None,
    write: bool = False,
) -> ChaosEvidenceRecording:
    """Validate and optionally append one offline chaos evidence artifact."""

    source_payload, decoded = _load_json(input_path)
    expected_candidate = _load_expected_candidate(expected_candidate_path)
    report = validate_terminal_runtime_chaos_evidence(
        decoded,
        expected_candidate=expected_candidate,
    )
    canonical_payload = serialize_terminal_runtime_chaos_evidence(report)
    artifact_digest = terminal_runtime_chaos_artifact_sha256(canonical_payload)
    artifact_path: Path | None = None
    written = False
    if write:
        if output_root is None:
            raise ValueError("output_root is required when write is true")
        artifact_path, written = _write_append_only(output_root, artifact_digest, canonical_payload)
    return ChaosEvidenceRecording(
        artifact_sha256=artifact_digest,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        ready_for_chaos_gate=report.ready_for_chaos_gate,
        candidate_binding_verified=expected_candidate is not None,
        written=written,
        path=artifact_path,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="chaos evidence JSON snapshot")
    parser.add_argument(
        "--expected-candidate",
        type=Path,
        help="optional independent candidate identity JSON for exact binding",
    )
    parser.add_argument(
        "--output-root", type=Path, help="local root for content-addressed evidence"
    )
    parser.add_argument("--write", action="store_true", help="append the artifact")
    return parser


def main() -> int:
    """Validate one snapshot and print a stable dry-run/write summary."""

    args = _parser().parse_args()
    result = record_terminal_runtime_chaos_evidence(
        args.input,
        expected_candidate_path=args.expected_candidate,
        output_root=args.output_root,
        write=args.write,
    )
    output: dict[str, object] = {
        "artifact_sha256": result.artifact_sha256,
        "candidate_binding_verified": result.candidate_binding_verified,
        "computed_ready_for_chaos_gate": result.ready_for_chaos_gate,
        "evidence_scope": "offline_chaos_observation",
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
