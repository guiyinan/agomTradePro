"""Keep the checked-in EVID-01 production inventory bound to its candidate."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = ROOT / "docs" / "deployment" / "evid-01-authority-inventory-2026-08-16.json"
PREFLIGHT_PATH = (
    ROOT / "docs" / "deployment" / "web-to-tui-deployment-preflight-20260816004134.json"
)

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


def test_authority_inventory_is_read_only_zero_seed_and_candidate_bound() -> None:
    """Reject stale candidate, seeded rows, or an inventory that claims readiness."""

    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    release = preflight["release"]

    assert inventory["version"] == "evid-01-authority-inventory.v1"
    assert inventory["environment"] == "production"
    assert inventory["read_only"] is True
    assert inventory["outcome"] == "blocked_zero_seed_authority"
    assert inventory["candidate"] == {
        "stable_version": release["stable_version"],
        "source_commit": release["source_commit"],
        "release": f"agomtradepro-web:{release['stable_version']}",
    }
    assert set(inventory["row_counts"]) == set(EXPECTED_TABLES)
    assert all(inventory["row_counts"][table] == 0 for table in EXPECTED_TABLES)
    assert [item["name"] for item in inventory["database"]["migrations"]] == [
        "0050_account_owner_assignment_evidence_v3_ledgers",
        "0051_actor_authority_source_v3_ledgers",
        "0052_account_actor_authority_raw_source_v3_ledgers",
        "0053_account_rbac_authority_mutation_binding_v3",
    ]
