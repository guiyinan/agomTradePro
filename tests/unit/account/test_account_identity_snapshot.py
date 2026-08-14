"""Pure contract coverage for Account-owned account identity snapshots."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_identity_snapshot import (
    ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE,
    ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS,
    ACCOUNT_IDENTITY_SNAPSHOT_OWNER,
    ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION,
    ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA,
    ACCOUNT_IDENTITY_SNAPSHOT_STATUS,
    ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE,
    ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER,
    AccountIdentitySnapshot,
    validate_account_identity_snapshot_successor,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


def _snapshot(**changes: object) -> AccountIdentitySnapshot:
    values: dict[str, object] = {
        "source_id": "account-identity-source-7",
        "source_version": "account-identity-source.v1",
        "account_namespace": "portfolio.transition_plan_account",
        "account_id": "portfolio-account-7",
        "underlying_unified_account_namespace": "simulated_trading.unified_account",
        "underlying_unified_account_id": 7,
        "owner_user_id": 19,
        "provenance_kind": "authoritative",
        "legacy_default_user_assignment": False,
        "underlying_source_id": "simulated-account-row-7",
        "underlying_source_version": "simulated-account-row.v17",
        "underlying_source_content_hash": "7" * 64,
        "underlying_source_recorded_at": NOW - timedelta(minutes=2),
        "underlying_source_valid_until": NOW + timedelta(hours=2),
        "ttl_valid_until": NOW + timedelta(hours=1),
        "issued_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return AccountIdentitySnapshot(**values)  # type: ignore[arg-type]


def _manual_snapshot(**changes: object) -> AccountIdentitySnapshot:
    values: dict[str, object] = {
        "provenance_kind": "manual_reclaim",
        "legacy_default_user_assignment": True,
        "reclaim_receipt_owner": ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER,
        "reclaim_receipt_artifact_type": ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE,
        "reclaim_receipt_id": "account-owner-reclaim-7",
        "reclaim_receipt_version": "account-owner-reclaim.v1",
        "reclaim_receipt_content_hash": "a" * 64,
    }
    values.update(changes)
    return _snapshot(**values)


def test_authoritative_snapshot_preserves_namespaces_without_casting_identity() -> None:
    snapshot = _snapshot()

    assert snapshot.owner == ACCOUNT_IDENTITY_SNAPSHOT_OWNER
    assert snapshot.artifact_type == ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE
    assert snapshot.schema == ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA
    assert snapshot.account_namespace == "portfolio.transition_plan_account"
    assert type(snapshot.account_id) is str
    assert snapshot.account_id == "portfolio-account-7"
    assert snapshot.underlying_unified_account_namespace == ("simulated_trading.unified_account")
    assert type(snapshot.underlying_unified_account_id) is int
    assert snapshot.underlying_unified_account_id == 7
    assert snapshot.owner_user_id == 19
    assert snapshot.underlying_source_id == "simulated-account-row-7"
    assert snapshot.underlying_source_version == "simulated-account-row.v17"
    assert snapshot.underlying_source_content_hash == "7" * 64
    assert snapshot.account_type == "real"
    assert snapshot.is_active is True
    assert len(snapshot.identity_hash) == 64
    assert len(snapshot.content_hash) == 64


def test_snapshot_is_inactive_identity_evidence_only() -> None:
    snapshot = _snapshot()
    payload = snapshot.to_payload()

    assert snapshot.permission == ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION
    assert snapshot.status == ACCOUNT_IDENTITY_SNAPSHOT_STATUS
    assert snapshot.blocker_codes == ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS
    assert snapshot.activation_available is False
    assert snapshot.must_not_execute is True
    assert payload["permission"] == "identity_evidence_only"
    assert payload["status"] == "inactive"
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
    assert snapshot.is_knowable_at(NOW)
    assert not snapshot.is_knowable_at(snapshot.valid_until)


def test_legacy_default_user_assignment_requires_exact_manual_reclaim_receipt() -> None:
    snapshot = _manual_snapshot()

    assert snapshot.provenance_kind == "manual_reclaim"
    assert snapshot.legacy_default_user_assignment is True
    assert snapshot.reclaim_receipt_owner == "account"
    assert snapshot.reclaim_receipt_artifact_type == "account_owner_reclaim_receipt"
    assert snapshot.reclaim_receipt_id == "account-owner-reclaim-7"
    assert snapshot.reclaim_receipt_version == "account-owner-reclaim.v1"
    assert snapshot.reclaim_receipt_content_hash == "a" * 64


@pytest.mark.parametrize(
    "changes",
    [
        {"provenance_kind": "authoritative", "legacy_default_user_assignment": True},
        {"reclaim_receipt_id": None},
        {"reclaim_receipt_version": "receipt version"},
        {"reclaim_receipt_content_hash": "A" * 64},
        {"reclaim_receipt_owner": "simulated_trading"},
        {"reclaim_receipt_artifact_type": "generic_receipt"},
    ],
)
def test_manual_reclaim_rejects_missing_or_untrusted_receipt(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _manual_snapshot(**changes)


def test_legacy_manual_reclaim_without_any_receipt_reference_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires an exact reclaim receipt"):
        _snapshot(
            provenance_kind="manual_reclaim",
            legacy_default_user_assignment=True,
            reclaim_receipt_owner=None,
            reclaim_receipt_artifact_type=None,
            reclaim_receipt_id=None,
            reclaim_receipt_version=None,
            reclaim_receipt_content_hash=None,
        )


def test_authoritative_provenance_rejects_reclaim_receipt_injection() -> None:
    with pytest.raises(ValueError, match="cannot carry"):
        _snapshot(
            reclaim_receipt_owner="account",
            reclaim_receipt_artifact_type="account_owner_reclaim_receipt",
            reclaim_receipt_id="receipt-1",
            reclaim_receipt_version="receipt.v1",
            reclaim_receipt_content_hash="b" * 64,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": 7},
        {"account_id": " 7"},
        {"underlying_unified_account_id": "7"},
        {"underlying_unified_account_id": True},
        {"owner_user_id": 0},
        {"owner_user_id": True},
        {"legacy_default_user_assignment": 1},
        {"underlying_source_id": "source 7"},
        {"underlying_source_version": ""},
        {"underlying_source_content_hash": "A" * 64},
        {"account_type": "simulated"},
        {"is_active": False},
        {"permission": "execute"},
        {"status": "active"},
        {"blocker_codes": ()},
        {"owner": "simulated_trading"},
        {"artifact_type": "account_projection"},
        {"schema": "account-identity-snapshot.v2"},
    ],
)
def test_snapshot_rejects_casts_mutable_account_upgrade_and_authority_tamper(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _snapshot(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"underlying_source_recorded_at": NOW},
        {"issued_at": NOW + timedelta(seconds=1)},
        {"recorded_at": NOW + timedelta(hours=1)},
        {"valid_until": NOW},
        {"valid_until": NOW + timedelta(minutes=30)},
        {"valid_until": NOW + timedelta(hours=3)},
        {"recorded_at": datetime(2026, 8, 13, 8)},
    ],
)
def test_snapshot_clock_is_server_recorded_and_cannot_outlive_underlying_source(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _snapshot(**changes)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("account_namespace", "account.other_namespace"),
        ("account_id", "portfolio-account-8"),
        ("underlying_unified_account_namespace", "account.unified_account"),
        ("underlying_unified_account_id", 8),
        ("owner_user_id", 20),
        ("provenance_kind", "manual_reclaim"),
        ("underlying_source_id", "simulated-account-row-8"),
        ("underlying_source_version", "simulated-account-row.v18"),
        ("underlying_source_content_hash", "6" * 64),
        ("underlying_source_valid_until", NOW + timedelta(hours=3)),
        ("ttl_valid_until", NOW + timedelta(minutes=30)),
        ("supersedes_content_hash", "c" * 64),
    ],
)
def test_every_material_fact_participates_in_content_hash(
    field_name: str,
    replacement: object,
) -> None:
    original = _snapshot()
    changes: dict[str, object] = {field_name: replacement}
    if field_name == "provenance_kind":
        changes.update(
            {
                "reclaim_receipt_owner": ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER,
                "reclaim_receipt_artifact_type": (ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE),
                "reclaim_receipt_id": "reclaim-7",
                "reclaim_receipt_version": "reclaim.v1",
                "reclaim_receipt_content_hash": "d" * 64,
            }
        )
    if field_name == "ttl_valid_until":
        changes["valid_until"] = replacement
    changed = _snapshot(**changes)

    assert changed.content_hash != original.content_hash


def test_identity_and_content_hashes_reject_caller_substitution() -> None:
    snapshot = _snapshot()

    assert _snapshot(identity_hash=snapshot.identity_hash) == snapshot
    assert _snapshot(source_version="account-identity-source.v2").identity_hash != (
        snapshot.identity_hash
    )
    with pytest.raises(ValueError, match="identity_hash"):
        _snapshot(identity_hash="9" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _snapshot(content_hash="8" * 64)


def test_valid_until_is_exact_minimum_of_underlying_source_and_ttl() -> None:
    ttl_limited = _snapshot(
        ttl_valid_until=NOW + timedelta(minutes=30),
        valid_until=NOW + timedelta(minutes=30),
    )
    source_limited = _snapshot(
        underlying_source_valid_until=NOW + timedelta(minutes=20),
        ttl_valid_until=NOW + timedelta(minutes=30),
        valid_until=NOW + timedelta(minutes=20),
    )

    assert ttl_limited.valid_until == ttl_limited.ttl_valid_until
    assert source_limited.valid_until == source_limited.underlying_source_valid_until


def test_successor_preserves_exact_account_identity_and_advances_version() -> None:
    previous = _snapshot()
    successor = _snapshot(
        source_version="account-identity-source.v2",
        underlying_source_recorded_at=NOW + timedelta(seconds=10),
        issued_at=NOW + timedelta(seconds=20),
        recorded_at=NOW + timedelta(seconds=30),
        supersedes_content_hash=previous.content_hash,
    )

    validate_account_identity_snapshot_successor(previous, successor)


@pytest.mark.parametrize(
    "changes",
    [
        {"supersedes_content_hash": "0" * 64},
        {"source_id": "other-source"},
        {"source_version": "account-identity-source.v1"},
        {"account_namespace": "account.other"},
        {"account_id": "portfolio-account-8"},
        {"underlying_unified_account_namespace": "account.unified"},
        {"underlying_unified_account_id": 8},
        {"owner_user_id": 20},
        {
            "recorded_at": NOW,
            "issued_at": NOW - timedelta(minutes=1),
            "underlying_source_recorded_at": NOW - timedelta(minutes=2),
        },
    ],
)
def test_successor_rejects_forked_or_changed_identity(changes: dict[str, object]) -> None:
    previous = _snapshot()
    values: dict[str, object] = {
        "source_version": "account-identity-source.v2",
        "underlying_source_recorded_at": NOW + timedelta(seconds=10),
        "issued_at": NOW + timedelta(seconds=20),
        "recorded_at": NOW + timedelta(seconds=30),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    successor = _snapshot(**values)

    with pytest.raises(ValueError):
        validate_account_identity_snapshot_successor(previous, successor)


def test_domain_contract_has_no_cross_app_or_external_dependency() -> None:
    source_path = (
        Path(__file__).parents[3] / "apps" / "account" / "domain" / "account_identity_snapshot.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith("apps.") for name in imported)
    assert imported <= {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
