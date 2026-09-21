"""Canonical evidence validation for coordinated current Publication rebuilds."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def publication_evidence_hash_from_result(
    result: object,
    expected_asset_count: int,
) -> str:
    """Hash exact four-Publication identity, policy and asset coverage evidence."""

    if (
        isinstance(expected_asset_count, bool)
        or not isinstance(expected_asset_count, int)
        or expected_asset_count <= 0
    ):
        raise ValueError("expected Publication asset count must be positive")

    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        raise ValueError("publication rebuild result must expose canonical evidence")
    payload = to_dict()
    if not isinstance(payload, Mapping):
        raise ValueError("publication rebuild evidence must be a mapping")
    raw_datasets = payload.get("datasets")
    if not isinstance(raw_datasets, list) or len(raw_datasets) != 4:
        raise ValueError("publication rebuild must commit exactly four datasets")
    expected_datasets = {
        "equity.quote.snapshot",
        "equity.price.bar",
        "equity.valuation.fact",
        "equity.financial.fact",
    }
    normalized: list[dict[str, object]] = []
    normalized_member_total = 0
    for raw_dataset in raw_datasets:
        if not isinstance(raw_dataset, Mapping):
            raise ValueError("publication dataset evidence must be a mapping")
        dataset_key = raw_dataset.get("dataset_key")
        publication_id = raw_dataset.get("publication_id")
        publication_hash = raw_dataset.get("publication_hash")
        member_count = raw_dataset.get("member_count")
        covered_asset_count = raw_dataset.get("covered_asset_count")
        policy_identity = raw_dataset.get("policy_identity")
        if not isinstance(dataset_key, str) or dataset_key not in expected_datasets:
            raise ValueError("publication dataset evidence is unexpected")
        if not isinstance(publication_id, str) or not publication_id.strip():
            raise ValueError("publication id evidence is missing")
        if (
            not isinstance(publication_hash, str)
            or len(publication_hash) != 64
            or any(character not in "0123456789abcdef" for character in publication_hash)
        ):
            raise ValueError("publication hash evidence is invalid")
        if isinstance(member_count, bool) or not isinstance(member_count, int) or member_count <= 0:
            raise ValueError("publication member-count evidence is invalid")
        if (
            isinstance(covered_asset_count, bool)
            or not isinstance(covered_asset_count, int)
            or covered_asset_count != expected_asset_count
        ):
            raise ValueError("publication covered-asset-count evidence is incomplete")
        if not isinstance(policy_identity, str):
            raise ValueError("publication policy identity evidence is missing")
        policy_parts = policy_identity.split(":")
        if (
            len(policy_parts) != 3
            or policy_parts[0] != "p2"
            or not policy_parts[1]
            or len(policy_parts[2]) != 64
            or any(character not in "0123456789abcdef" for character in policy_parts[2])
        ):
            raise ValueError("publication policy identity evidence is invalid")
        normalized_member_total += member_count
        normalized.append(
            {
                "covered_asset_count": covered_asset_count,
                "dataset_key": dataset_key,
                "member_count": member_count,
                "policy_identity": policy_identity,
                "publication_hash": publication_hash,
                "publication_id": publication_id,
            }
        )
    if {item["dataset_key"] for item in normalized} != expected_datasets:
        raise ValueError("publication rebuild evidence is incomplete")
    for field_name in ("publication_id", "publication_hash"):
        values = [str(item[field_name]) for item in normalized]
        if len(set(values)) != len(values):
            raise ValueError(f"publication {field_name} evidence must be unique")
    published_count = payload.get("published_count")
    if (
        isinstance(published_count, bool)
        or not isinstance(published_count, int)
        or published_count != normalized_member_total
    ):
        raise ValueError("publication published-count evidence is inconsistent")
    if getattr(result, "published_count", None) != published_count:
        raise ValueError("publication result count differs from canonical evidence")
    encoded = json.dumps(
        sorted(normalized, key=lambda item: str(item["dataset_key"])),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["publication_evidence_hash_from_result"]
