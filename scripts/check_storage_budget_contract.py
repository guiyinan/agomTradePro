"""Validate the storage-budget governance manifest and fail-closed port."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance" / "storage_budget_contracts.json"
PORT = ROOT / "apps" / "config_center" / "application" / "storage_budget.py"


def main() -> int:
    """Return non-zero when the storage policy contract drifts."""

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "source_of_truth",
        "fail_closed_when_missing",
        "initialization_profiles",
        "required_fields",
        "consumers",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise SystemExit(f"storage budget manifest missing keys: {missing}")
    if payload["source_of_truth"] != "config_center_storage_budget_policy":
        raise SystemExit("storage budget source_of_truth must be Config Center")
    if payload["fail_closed_when_missing"] is not True:
        raise SystemExit("storage budget must fail closed when no active policy exists")
    if "production-90g" not in {item.get("profile_key") for item in payload["initialization_profiles"]}:
        raise SystemExit("production-90g initialization projection is required")
    required_fields = set(payload["required_fields"])
    if not {"configured_capacity_bytes", "active", "warning_ratio", "critical_ratio"}.issubset(required_fields):
        raise SystemExit("storage budget required fields are incomplete")
    port_text = PORT.read_text(encoding="utf-8")
    for marker in ("class StorageBudgetQueryPort", "class StoragePressureGuard", "policy_missing_or_inactive"):
        if marker not in port_text:
            raise SystemExit(f"storage budget application port missing marker: {marker}")
    print("storage budget contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
