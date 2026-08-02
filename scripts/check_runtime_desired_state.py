"""Check the desired-state reconciliation manifest."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Return non-zero when a required runtime catalog family is absent."""

    payload = json.loads((ROOT / "governance" / "runtime_desired_state.json").read_text(encoding="utf-8"))
    families = {item.get("key") for item in payload.get("families", [])}
    required = {
        "data_center.provider_catalog",
        "celery.beat_schedule",
        "mcp.capability_catalog",
        "tui.metadata",
    }
    if required.difference(families):
        raise SystemExit(f"desired-state families missing: {sorted(required.difference(families))}")
    if payload.get("drift_policy", {}).get("missing") != "block_decision_readiness":
        raise SystemExit("missing desired-state entries must block readiness")
    print("runtime desired-state contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
