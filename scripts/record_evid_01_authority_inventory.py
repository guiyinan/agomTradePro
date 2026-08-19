#!/usr/bin/env python
"""Validate and optionally append a local EVID-01 inventory report.

The command accepts an externally captured snapshot only.  It never connects
to PostgreSQL, Django, a VPS, or a production writer.  Without ``--write`` it
is a dry run; writing is append-only and content-addressed under the supplied
local evidence root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.research.application.evid_01_authority_inventory import (
    Evid01AuthorityInventoryError,
    build_evid_01_authority_inventory_report,
    evid_01_authority_inventory_artifact_sha256,
    parse_evid_01_authority_inventory_snapshot,
    serialize_evid_01_authority_inventory_report,
)


def _parser() -> argparse.ArgumentParser:
    """Build the read-only inventory recorder CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="captured snapshot JSON path")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="local content-addressed evidence root; required with --write",
    )
    parser.add_argument("--write", action="store_true", help="append locally; default is dry-run")
    return parser


def _append(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Append one report without overwriting an existing content address."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "evid-01-authority-inventory" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise Evid01AuthorityInventoryError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    sidecar_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise Evid01AuthorityInventoryError("content-addressed artifact collision")
        if sidecar_path.exists() and sidecar_path.read_text(encoding="ascii") != f"{digest}\n":
            raise Evid01AuthorityInventoryError("digest sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as handle:
        handle.write(payload)
    with sidecar_path.open("xb") as handle:
        handle.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def main() -> int:
    """Validate one snapshot and optionally write a local report."""

    args = _parser().parse_args()
    snapshot = parse_evid_01_authority_inventory_snapshot(args.input.read_bytes())
    report = build_evid_01_authority_inventory_report(snapshot)
    payload = serialize_evid_01_authority_inventory_report(report)
    digest = evid_01_authority_inventory_artifact_sha256(payload)
    result: dict[str, object] = {
        "artifact_sha256": digest,
        "authority_ready": False,
        "outcome": report.outcome.value,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "written": False,
    }
    if args.write:
        if args.output_root is None:
            raise Evid01AuthorityInventoryError("--output-root is required with --write")
        path, created = _append(args.output_root, digest, payload)
        result["path"] = str(path)
        result["written"] = created
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
