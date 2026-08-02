"""Validate the versioned Data Center dataset/provider/publication manifests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "governance" / "dataset_contracts.json"
BINDINGS = ROOT / "governance" / "provider_bindings.json"
POLICIES = ROOT / "governance" / "publication_policies.json"
EXPECTED_DATASETS = {
    "asset.master",
    "equity.price.bar",
    "equity.quote.snapshot",
    "fund.nav",
    "macro.fact",
    "equity.financial.fact",
    "equity.valuation.fact",
    "sector.membership",
    "market.news",
    "market.capital_flow",
}


def _read(path: Path) -> dict[str, object]:
    """Read one manifest as a JSON object."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def validate() -> None:
    """Raise when a dataset lacks a contract, binding, or publication policy."""

    datasets = _read(DATASETS)
    bindings = _read(BINDINGS)
    policies = _read(POLICIES)
    dataset_keys = {str(item["dataset_key"]) for item in datasets["contracts"]}  # type: ignore[index]
    binding_keys = {str(item["dataset_key"]) for item in bindings["bindings"]}  # type: ignore[index]
    policy_keys = {str(item["dataset_key"]) for item in policies["policies"]}  # type: ignore[index]
    if dataset_keys != EXPECTED_DATASETS:
        raise ValueError(f"dataset contract keys differ: {sorted(dataset_keys ^ EXPECTED_DATASETS)}")
    if binding_keys != EXPECTED_DATASETS:
        raise ValueError(f"provider binding keys differ: {sorted(binding_keys ^ EXPECTED_DATASETS)}")
    if policy_keys != EXPECTED_DATASETS:
        raise ValueError(f"publication policy keys differ: {sorted(policy_keys ^ EXPECTED_DATASETS)}")
    for item in datasets["contracts"]:  # type: ignore[index]
        if not item.get("fields"):  # type: ignore[union-attr]
            raise ValueError(f"dataset {item['dataset_key']} has no fields")  # type: ignore[index]
    for item in policies["policies"]:  # type: ignore[index]
        if not item.get("required_evidence"):  # type: ignore[union-attr]
            raise ValueError(f"dataset {item['dataset_key']} has no evidence policy")  # type: ignore[index]


def main() -> int:
    """Validate manifests and print a compact deterministic summary."""

    validate()
    print(f"validated={len(EXPECTED_DATASETS)} datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
