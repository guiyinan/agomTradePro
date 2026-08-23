#!/usr/bin/env python
"""Validate and optionally append a local STRAT-01 owner inventory report.

The command consumes an externally captured SELECT-only snapshot.  It never
connects to PostgreSQL, Django, a VPS, or a production writer.  Without
``--write`` it is a dry run; writing is append-only and content-addressed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.research.application.strat_01_owner_ledger_inventory import (  # noqa: E402
    Strat01OwnerLedgerInventoryError,
    build_strat_01_owner_ledger_report,
    parse_strat_01_owner_ledger_snapshot,
    serialize_strat_01_owner_ledger_report,
    strat_01_owner_ledger_artifact_sha256,
)


def _parser() -> argparse.ArgumentParser:
    """Build the offline recorder CLI parser."""

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
    """Append one canonical report without overwriting an existing address."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "strat-01-owner-ledger-inventory" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise Strat01OwnerLedgerInventoryError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    sidecar_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise Strat01OwnerLedgerInventoryError("content-addressed artifact collision")
        if sidecar_path.exists() and sidecar_path.read_text(encoding="ascii") != f"{digest}\n":
            raise Strat01OwnerLedgerInventoryError("digest sidecar collision")
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
    snapshot = parse_strat_01_owner_ledger_snapshot(args.input.read_bytes())
    report = build_strat_01_owner_ledger_report(snapshot)
    payload = serialize_strat_01_owner_ledger_report(report)
    digest = strat_01_owner_ledger_artifact_sha256(payload)
    result: dict[str, object] = {
        "artifact_sha256": digest,
        "outcome": report.outcome.value,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "written": False,
    }
    if args.write:
        if args.output_root is None:
            raise Strat01OwnerLedgerInventoryError("--output-root is required with --write")
        path, created = _append(args.output_root, digest, payload)
        result["path"] = str(path)
        result["written"] = created
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
