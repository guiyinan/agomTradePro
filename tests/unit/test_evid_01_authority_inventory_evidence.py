"""Keep the checked-in EVID-01 production inventory bound to its candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "active_plan_registry.json"
CUTOVER_PATH = ROOT / "config" / "tui" / "migration" / "web_to_tui_cutover_evidence.v1.json"
DEPLOYMENT_DIR = ROOT / "docs" / "deployment"

EXPECTED_TABLES = (
    "account_auth_context_source_v3_anchor",
    "account_auth_context_source_v3_ledger",
    "account_user_authority_source_v3_anchor",
    "account_user_authority_source_v3_ledger",
    "account_rbac_authority_source_v3_anchor",
    "account_rbac_authority_source_v3_ledger",
    "account_actor_authority_source_v3_root_lock",
    "account_actor_authority_source_v3_ledger",
    "research_evidence_scope_source_v1",
    "account_owner_assignment_subject_v3_ledger",
    "account_owner_assignment_evidence_v3_ledger",
    "account_owner_assignment_provenance_receipt_v3_ledger",
)


def _load(path: Path) -> dict[str, Any]:
    """Load a checked-in JSON object for the static evidence guard."""

    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _find_candidate_artifact(
    *, pattern: str, candidate_version: str, candidate_commit: str, identity_key: str
) -> tuple[Path, dict[str, Any]]:
    """Find exactly one artifact whose declared candidate matches the active release."""

    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(DEPLOYMENT_DIR.glob(pattern)):
        payload = _load(path)
        candidate = payload.get(identity_key)
        if not isinstance(candidate, dict):
            continue
        if (
            str(candidate.get("stable_version")) == candidate_version
            and str(candidate.get("source_commit")) == candidate_commit
        ):
            matches.append((path, payload))
    assert len(matches) == 1, f"expected one {pattern} artifact, got {matches}"
    return matches[0]


def test_authority_inventory_is_read_only_zero_seed_and_candidate_bound() -> None:
    """Reject stale candidate, seeded rows, or an inventory that claims readiness."""

    registry = _load(REGISTRY_PATH)
    cutover = _load(CUTOVER_PATH)
    workstream = next(item for item in registry["workstreams"] if item["id"] == "web-to-tui-m5")
    cutover_candidate = cast(dict[str, Any], cutover["candidate"])
    candidate_version = str(cutover_candidate["stable_version"])
    candidate_commit = str(cutover_candidate["candidate_commit"])
    assert candidate_commit in str(workstream["next_gate"])
    assert candidate_version in str(workstream["next_gate"])

    preflight_path, preflight = _find_candidate_artifact(
        pattern="web-to-tui-deployment-preflight-*.json",
        candidate_version=candidate_version,
        candidate_commit=candidate_commit,
        identity_key="release",
    )
    _, runtime = _find_candidate_artifact(
        pattern="vps-runtime-verification-*.json",
        candidate_version=candidate_version,
        candidate_commit=candidate_commit,
        identity_key="candidate",
    )
    _, inventory = _find_candidate_artifact(
        pattern="evid-01-authority-inventory-*.json",
        candidate_version=candidate_version,
        candidate_commit=candidate_commit,
        identity_key="candidate",
    )
    release = cast(dict[str, Any], preflight["release"])
    runtime_candidate = cast(dict[str, Any], runtime["candidate"])
    deployment_binding = cast(dict[str, Any], cutover_candidate["deployment_preflight"])

    assert inventory["version"] == "evid-01-authority-inventory.v1"
    assert inventory["environment"] == "production"
    assert inventory["read_only"] is True
    assert inventory["outcome"] == "blocked_zero_seed_authority"
    assert inventory["candidate"] == {
        "stable_version": release["stable_version"],
        "source_commit": release["source_commit"],
        "release": f"agomtradepro-web:{release['stable_version']}",
    }
    assert release["stable_version"] == candidate_version
    assert release["source_commit"] == candidate_commit
    assert preflight["oci_image"]["revision"] == candidate_commit
    assert deployment_binding["evidence"] == preflight_path.relative_to(ROOT).as_posix()
    assert (
        deployment_binding["evidence_sha256"]
        == hashlib.sha256(preflight_path.read_bytes()).hexdigest()
    )
    assert runtime["version"] == "vps-runtime-verification.v1"
    assert runtime["environment"] == "production"
    assert runtime["read_only"] is True
    assert runtime["outcome"] == "runtime_verified_candidate"
    assert runtime_candidate["stable_version"] == candidate_version
    assert runtime_candidate["source_commit"] == candidate_commit
    assert runtime_candidate["release"] == f"agomtradepro-web:{candidate_version}"
    assert runtime_candidate["image_id"] == preflight["oci_image"]["image_id"]
    runtime_authority_inventory = cast(dict[str, Any], runtime["checks"]["authority_inventory"])
    assert runtime_authority_inventory["outcome"] == inventory["outcome"]
    assert runtime_authority_inventory["all_expected_rows"] == 0
    assert runtime_authority_inventory["migrations"] == "0050 through 0053 present"
    assert set(inventory["row_counts"]) == set(EXPECTED_TABLES)
    assert all(inventory["row_counts"][table] == 0 for table in EXPECTED_TABLES)
    assert [item["name"] for item in inventory["database"]["migrations"]] == [
        "0050_account_owner_assignment_evidence_v3_ledgers",
        "0051_actor_authority_source_v3_ledgers",
        "0052_account_actor_authority_raw_source_v3_ledgers",
        "0053_account_rbac_authority_mutation_binding_v3",
    ]
