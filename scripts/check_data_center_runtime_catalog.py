"""Verify active Data Center Catalog rows match reviewed governance projections."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import django

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _manifest_rows(filename: str, key: str) -> list[dict[str, object]]:
    """Return object rows from one governance projection."""

    payload = json.loads((PROJECT_ROOT / "governance" / filename).read_text(encoding="utf-8"))
    rows = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{filename} must contain {key}")
    return [row for row in rows if isinstance(row, dict)]


def _manifest_keys(filename: str, key: str) -> set[str]:
    """Return dataset keys from one governance projection."""

    return {str(row.get("dataset_key")) for row in _manifest_rows(filename, key)}


def main() -> int:
    """Fail closed when the runtime catalog is absent or incomplete."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    if not os.environ.get("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL must be set for runtime catalog verification")
    django.setup()
    from apps.data_center.application.public import (
        list_active_data_owner_registrations,
        list_active_dataset_contracts,
        list_active_provider_bindings,
        list_active_publication_policies,
    )

    contract_rows = _manifest_rows("dataset_contracts.json", "contracts")
    binding_rows = _manifest_rows("provider_bindings.json", "bindings")
    policy_rows = _manifest_rows("publication_policies.json", "policies")
    owner_rows = _manifest_rows("data_ownership_contracts.json", "datasets")
    expected = {str(row.get("dataset_key")) for row in contract_rows}
    expected_bindings = {str(row.get("dataset_key")) for row in binding_rows}
    expected_policies = {str(row.get("dataset_key")) for row in policy_rows}
    expected_owners = expected & {str(row.get("dataset_key")) for row in owner_rows}
    expected_contract_versions = {
        (
            str(row.get("dataset_key")),
            str(row.get("contract_version")),
            str(row.get("schema_version")),
        )
        for row in contract_rows
    }
    expected_binding_capabilities = {
        (str(row.get("dataset_key")), str(row.get("provider")), str(row.get("capability")))
        for row in binding_rows
    }
    expected_owner_roles = {
        (
            str(row.get("dataset_key")),
            str(row.get("owner")),
            str(row.get("business_owner")),
            str(row.get("acceptance_owner")),
        )
        for row in owner_rows
        if str(row.get("dataset_key")) in expected
    }
    contracts = list_active_dataset_contracts()
    bindings = list_active_provider_bindings()
    owners = list_active_data_owner_registrations()
    policies = list_active_publication_policies()
    actual = {contract.key.value for contract in contracts}
    actual_bindings = {binding.dataset.value for binding in bindings}
    actual_policies = {policy.dataset.value for policy in policies}
    owner_keys = {owner.dataset_key for owner in owners}
    actual_contract_versions = {
        (contract.key.value, contract.key.contract_version, contract.key.schema_version)
        for contract in contracts
    }
    actual_binding_capabilities = {
        (binding.dataset.value, binding.provider, binding.capability) for binding in bindings
    }
    actual_owner_roles = {
        (
            owner.dataset_key,
            owner.data_platform_owner,
            owner.business_owner,
            owner.acceptance_owner,
        )
        for owner in owners
    }
    failures = {
        "contracts": sorted(expected - actual),
        "bindings": sorted(expected_bindings - actual_bindings),
        "policies": sorted(expected_policies - actual_policies),
        "owners": sorted(expected_owners - owner_keys),
        "contract_versions": sorted(expected_contract_versions - actual_contract_versions),
        "binding_capabilities": sorted(expected_binding_capabilities - actual_binding_capabilities),
        "owner_roles": sorted(expected_owner_roles - actual_owner_roles),
    }
    failures = {key: value for key, value in failures.items() if value}
    if len(bindings) != len(binding_rows):
        failures["binding_count"] = [f"expected={len(binding_rows)} actual={len(bindings)}"]
    if len(policies) != len(policy_rows):
        failures["policy_count"] = [f"expected={len(policy_rows)} actual={len(policies)}"]
    if len(owners) != len(expected_owners):
        failures["owner_count"] = [f"expected={len(expected_owners)} actual={len(owners)}"]
    if failures:
        print(json.dumps(failures, ensure_ascii=False, sort_keys=True))
        return 1
    print(
        "Runtime Data Center catalog verified: "
        f"contracts={len(contracts)}, bindings={len(bindings)}, owners={len(owners)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
