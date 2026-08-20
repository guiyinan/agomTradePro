#!/usr/bin/env python
"""Validate an authenticated TAR-01 reserved-route observation artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

# Keep direct ``python scripts/...`` invocation equivalent to ``python -m``.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ``apps.agent_runtime.application`` has a legacy eager ``__init__`` that
# imports Django-backed use cases.  This validator is deliberately offline;
# when invoked as a file, provide a package shell so only the pure module is
# imported.  Normal package imports (including pytest) keep the real package.
if __package__ in (None, "") and "apps.agent_runtime.application" not in sys.modules:
    application_package = ModuleType("apps.agent_runtime.application")
    application_package.__path__ = [str(REPO_ROOT / "apps" / "agent_runtime" / "application")]
    sys.modules["apps.agent_runtime.application"] = application_package

from apps.agent_runtime.application.terminal_runtime_reserved_route_evidence import (
    TerminalRuntimeReservedRouteEvidenceError,
    validate_terminal_runtime_reserved_route_evidence,
)


def _parser() -> argparse.ArgumentParser:
    """Build the evidence validation CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="reserved-route evidence JSON")
    return parser


def main() -> int:
    """Load and validate an evidence artifact, then print a stable summary."""

    args = _parser().parse_args()
    try:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TerminalRuntimeReservedRouteEvidenceError("evidence root must be an object")
        report = validate_terminal_runtime_reserved_route_evidence(cast(dict[str, object], payload))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TerminalRuntimeReservedRouteEvidenceError,
    ) as exc:
        print(f"invalid reserved-route evidence: {exc}")
        return 1
    print(
        json.dumps(
            {
                "candidate_commit": report.candidate_commit,
                "candidate_release": report.candidate_release,
                "image_id": report.image_id,
                "level_count": report.level_count,
                "health_stable": report.health_stable,
                "side_effects_observed": report.side_effects_observed,
                "capacity_ready": report.capacity_ready,
                "runtime_enablement": "not_authorized",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
