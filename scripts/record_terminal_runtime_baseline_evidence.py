"""Record a validated offline TAR-01 baseline snapshot as content-addressed evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineCollector,
)
from apps.agent_runtime.application.terminal_runtime_baseline_evidence import (
    serialize_terminal_runtime_baseline_report,
    terminal_runtime_baseline_artifact_sha256,
)
from apps.agent_runtime.infrastructure.terminal_runtime_baseline_snapshot_observer import (
    JsonSnapshotSource,
    TerminalRuntimeBaselineSnapshotObserver,
)


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="v1 snapshot JSON path")
    parser.add_argument(
        "--output-root", type=Path, help="explicit root for content-addressed evidence"
    )
    parser.add_argument(
        "--source-kind", default="offline_snapshot", help="bounded source identity token"
    )
    parser.add_argument(
        "--write", action="store_true", help="append the artifact under --output-root"
    )
    return parser


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Write a content-addressed artifact without overwriting any bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "terminal-agent-baseline" / digest[:2]).resolve()
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


def main() -> int:
    """Parse, validate, and optionally append one evidence artifact."""

    args = _parser().parse_args()
    source = JsonSnapshotSource(args.input)
    observer = TerminalRuntimeBaselineSnapshotObserver(source)
    request = TerminalRuntimeBaselineCollectionRequest(
        environment=observer.environment,
        candidate_identity=observer.candidate,
    )
    report = TerminalRuntimeBaselineCollector(observer).collect(request)
    payload = serialize_terminal_runtime_baseline_report(
        report,
        source_kind=args.source_kind,
        source_payload_sha256=observer.source_payload_sha256,
    )
    artifact_digest = terminal_runtime_baseline_artifact_sha256(payload)
    output: dict[str, object] = {
        "artifact_sha256": artifact_digest,
        "computed_ready_for_capacity_gate": report.ready_for_capacity_gate,
        "evidence_scope": "offline_snapshot",
        "runtime_enablement": "not_authorized",
        "source_payload_sha256": observer.source_payload_sha256,
        "written": False,
    }
    if args.write:
        if args.output_root is None:
            raise ValueError("--output-root is required with --write")
        path, created = _write_append_only(args.output_root, artifact_digest, payload)
        output["path"] = str(path)
        output["written"] = created
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
