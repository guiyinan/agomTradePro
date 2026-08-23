"""Keep the checked-in EVID-01 production inventory bound to its candidate."""

from __future__ import annotations

from pathlib import Path

from apps.research.application.evid_01_authority_inventory import (
    build_evid_01_authority_inventory_report,
    evid_01_authority_inventory_artifact_sha256,
    parse_evid_01_authority_inventory_snapshot,
    serialize_evid_01_authority_inventory_report,
)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = (
    ROOT / "docs" / "deployment" / "evid-01-authority-inventory-snapshot-2026-08-23-0810.json"
)
REPORT_PATH = (
    ROOT
    / "docs"
    / "deployment"
    / "evid-01-authority-inventory"
    / "39"
    / "3900c08b9054620f9b969f4bd5aab8097bb00ad1e3692e9aaeee66bda5cdf9b4.json"
)
REPORT_SHA_PATH = REPORT_PATH.with_suffix(".sha256")

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


def test_authority_inventory_is_read_only_zero_seed_and_content_addressed() -> None:
    """Validate the EVID-01 inventory without borrowing a Web-to-TUI candidate."""

    snapshot_payload = SNAPSHOT_PATH.read_bytes()
    snapshot = parse_evid_01_authority_inventory_snapshot(snapshot_payload)
    report = build_evid_01_authority_inventory_report(snapshot)
    report_payload = serialize_evid_01_authority_inventory_report(report)
    report_sha = evid_01_authority_inventory_artifact_sha256(report_payload)

    assert snapshot.candidate.stable_version == "20260822134658"
    assert snapshot.candidate.source_commit == "4cef9040cccc2127c3f8128c8d858bc7958df2a4"
    assert snapshot.read_only is True
    assert set(dict(snapshot.row_counts)) == set(EXPECTED_TABLES)
    assert all(count == 0 for _, count in snapshot.row_counts)
    assert report.outcome.value == "blocked_zero_seed_authority"
    assert report.production_claim is False
    assert report.production_ready is False
    assert report.authority_ready is False
    assert report.runtime_enablement == "not_authorized"
    assert report_sha == REPORT_PATH.stem
    assert REPORT_PATH.read_bytes() == report_payload
    assert REPORT_SHA_PATH.read_text(encoding="ascii") == f"{report_sha}\n"
