#!/usr/bin/env python
"""Validate a candidate-bound TAR-01 capacity observation artifact."""

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

from apps.agent_runtime.application.terminal_runtime_capacity_evidence import (
    TerminalRuntimeCapacityEvidenceBinding,
    TerminalRuntimeCapacityEvidenceError,
    validate_terminal_runtime_capacity_evidence,
)

DEFAULT_CONTRACT = REPO_ROOT / "governance" / "terminal_agent_runtime_contracts.json"


def _parser() -> argparse.ArgumentParser:
    """Build the evidence validation CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="candidate-bound capacity evidence JSON")
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
        help="TAR-01 contract used to bind the candidate identity",
    )
    return parser


def _expected_candidate(contract_path: Path) -> TerminalRuntimeCapacityEvidenceBinding:
    """Load the candidate identity from the TAR-01 runtime observation."""

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise TerminalRuntimeCapacityEvidenceError("contract root must be an object")
    observation = contract.get("runtime_observation")
    if not isinstance(observation, dict):
        raise TerminalRuntimeCapacityEvidenceError("contract runtime_observation must be an object")
    values = {
        "candidate_commit": observation.get("candidate_commit"),
        "release": observation.get("release"),
        "image": observation.get("image"),
    }
    if any(type(value) is not str for value in values.values()):
        raise TerminalRuntimeCapacityEvidenceError("contract candidate identity is incomplete")
    return TerminalRuntimeCapacityEvidenceBinding(
        candidate_commit=cast(str, values["candidate_commit"]),
        release=cast(str, values["release"]),
        image=cast(str, values["image"]),
    )


def main() -> int:
    """Load and validate an evidence file, then print a stable summary."""

    args = _parser().parse_args()
    try:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TerminalRuntimeCapacityEvidenceError("evidence root must be an object")
        expected = _expected_candidate(args.contract)
        report = validate_terminal_runtime_capacity_evidence(
            cast(dict[str, object], payload),
            expected_candidate=expected,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TerminalRuntimeCapacityEvidenceError,
    ) as exc:
        print(f"invalid TAR-01 capacity evidence: {exc}")
        return 1
    print(
        json.dumps(
            {
                "candidate_commit": report.candidate_commit,
                "candidate_release": report.candidate_release,
                "image_id": report.image_id,
                "accepted_runs": report.accepted_runs,
                "rejected_runs": report.rejected_runs,
                "level_count": report.level_count,
                "idempotency_verified": report.idempotency_verified,
                "worker_recovery_verified": report.worker_recovery_verified,
                "sse_verified": report.sse_verified,
                "cleanup_verified": report.cleanup_verified,
                "decision": report.decision,
                "safety_ready": report.safety_ready,
                "capacity_ready": report.capacity_ready,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
