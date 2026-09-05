#!/usr/bin/env python
"""Reset a Web-to-TUI retained window after a candidate-bound restart."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import web_to_tui_retained_observation as retained  # noqa: E402

DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    value = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise retained.RetainedObservationError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], value)


def main() -> int:
    """Run the observation-reset binding CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-artifact", required=True, type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    try:
        evidence_path = args.evidence.resolve()
        prepared = retained.bind_observation_reset(
            _load_object(evidence_path),
            reset_artifact_path=args.reset_artifact.resolve(),
        )
        if args.write_evidence:
            retained._write_json_atomic(evidence_path, prepared)
        candidate = cast(dict[str, Any], prepared["candidate"])
        marker = retained.parse_observation_reset(candidate)
    except (OSError, ValueError, json.JSONDecodeError, retained.RetainedObservationError) as exc:
        print(f"Web-to-TUI observation reset: FAIL - {exc}")
        return 1
    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    print(
        f"Web-to-TUI observation reset: {mode} - "
        f"reset_at={retained.utc_text(marker.reset_at)} "
        f"reason={marker.reason_code} "
        f"new_sample_required=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
