"""Pure contract tests for Broker-owned account identity snapshots."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.domain.broker_account_identity_snapshot import (
    AccountIdentitySourceRef,
    BrokerAccountIdentitySnapshot,
    KeyedBrokerAccountReferenceDigest,
    validate_broker_account_identity_snapshot_successor,
)

NOW = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _account_source(**changes: object) -> AccountIdentitySourceRef:
    values: dict[str, object] = {
        "source_id": "account-42",
        "source_version": "v1",
        "content_hash": HASH_A,
        "account_namespace": "unified_account",
        "account_id": "account-42",
        "owner_user_id": 7,
        "account_type": "real",
        "is_active": True,
        "recorded_at": NOW - timedelta(hours=2),
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return AccountIdentitySourceRef(**values)  # type: ignore[arg-type]


def _qmt_digest(**changes: object) -> KeyedBrokerAccountReferenceDigest:
    values: dict[str, object] = {
        "algorithm": "hmac-sha256",
        "key_id": "broker-account-ref-key-v1",
        "digest": HASH_B,
    }
    values.update(changes)
    return KeyedBrokerAccountReferenceDigest(**values)  # type: ignore[arg-type]


def _snapshot(**changes: object) -> BrokerAccountIdentitySnapshot:
    values: dict[str, object] = {
        "snapshot_id": "broker-account-snapshot-1",
        "snapshot_version": "v1",
        "broker_account_namespace": "broker_execution.account",
        "broker_account_id": 42,
        "owner_user_id": 7,
        "account_type": "real",
        "is_active": True,
        "account_source_ref": _account_source(),
        "binding_revision": 3,
        "binding_owner_user_id": 7,
        "binding_content_hash": HASH_B,
        "agent_id": "qmt-agent-1",
        "agent_version": "v4",
        "agent_owner_user_id": 7,
        "agent_content_hash": HASH_C,
        "qmt_account_ref_digest": _qmt_digest(),
        "broker_account_category": "STOCK",
        "issued_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "ttl_valid_until": NOW + timedelta(days=7),
        "valid_until": NOW + timedelta(days=7),
    }
    values.update(changes)
    return BrokerAccountIdentitySnapshot(**values)  # type: ignore[arg-type]


def test_snapshot_is_content_addressed_identity_evidence_only() -> None:
    snapshot = _snapshot()

    assert len(snapshot.identity_hash) == 64
    assert len(snapshot.content_hash) == 64
    assert snapshot.authority_scope == "identity_evidence_only"
    assert snapshot.permission == "inactive"
    assert snapshot.activation_available is False
    assert snapshot.must_not_execute is True
    assert snapshot.is_knowable_at(NOW) is True

    payload = snapshot.to_payload()
    assert payload["owner"] == "broker_execution"
    assert payload["artifact_type"] == "broker_account_identity_snapshot"
    assert payload["schema"] == "broker-account-identity-snapshot.v1"
    assert payload["qmt_account_ref_digest"] == {
        "algorithm": "hmac-sha256",
        "key_id": "broker-account-ref-key-v1",
        "digest": HASH_B,
    }


def test_account_source_authority_is_fixed() -> None:
    source = _account_source()
    assert source.owner == "account"
    assert source.artifact_type == "account_identity_snapshot"
    assert source.to_payload()["account_id"] == "account-42"
    assert type(source.account_id) is str

    with pytest.raises(ValueError, match="owner"):
        replace(source, owner="broker_execution")
    with pytest.raises(ValueError, match="artifact_type"):
        replace(source, artifact_type="portfolio_account")


def test_account_source_requires_hash_and_aware_valid_window() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        _account_source(content_hash="bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        _account_source(recorded_at=datetime(2026, 8, 13))
    with pytest.raises(ValueError, match="validity window"):
        _account_source(valid_until=NOW - timedelta(days=3))


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"account_namespace": ""},
        {"account_id": 42},
        {"owner_user_id": 0},
        {"account_type": "simulated"},
        {"is_active": False},
        {"is_active": 1},
    ],
)
def test_account_source_requires_exact_active_real_identity(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _account_source(**changes)


@pytest.mark.parametrize(  # type: ignore[misc]
    "algorithm", ["sha256", "SHA-256", "blake2b", "hmac_sha256"]
)
def test_qmt_reference_rejects_plain_or_unknown_digest_algorithms(algorithm: str) -> None:
    with pytest.raises(ValueError, match="keyed digest algorithm"):
        _qmt_digest(algorithm=algorithm)


def test_qmt_reference_requires_key_id_and_exact_digest() -> None:
    with pytest.raises(ValueError, match="key_id"):
        _qmt_digest(key_id="")
    with pytest.raises(ValueError, match="digest"):
        _qmt_digest(digest="plaintext-account-reference")


def test_snapshot_has_no_plain_qmt_reference_heartbeat_or_credential_fields() -> None:
    names = {field.name for field in fields(BrokerAccountIdentitySnapshot)}

    assert "broker_account_ref" not in names
    assert "qmt_account_ref" not in names
    assert "heartbeat" not in " ".join(names)
    assert "credential" not in " ".join(names)
    payload = _snapshot().to_payload()
    assert "broker_account_ref" not in payload
    assert "credential" not in str(payload).lower()
    assert "heartbeat" not in str(payload).lower()


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"account_type": "simulated"},
        {"is_active": False},
        {"is_active": 1},
        {"broker_account_id": True},
        {"broker_account_id": 0},
    ],
)
def test_snapshot_requires_exact_active_real_account(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _snapshot(**changes)


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"binding_owner_user_id": 8},
        {"agent_owner_user_id": 8},
        {"owner_user_id": 8},
    ],
)
def test_binding_and_agent_owner_must_equal_account_owner(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="owner"):
        _snapshot(**changes)


def test_account_source_owner_must_equal_snapshot_owner() -> None:
    with pytest.raises(ValueError, match="Account source owner"):
        _snapshot(account_source_ref=_account_source(owner_user_id=8))


def test_account_source_identity_replacement_changes_snapshot_content() -> None:
    snapshot = _snapshot()
    replacement = _account_source(
        source_id="account-99",
        account_namespace="account_ledger",
        account_id="portfolio-account-99",
        content_hash="d" * 64,
    )
    changed = _snapshot(account_source_ref=replacement)

    assert changed.identity_hash == snapshot.identity_hash
    assert changed.content_hash != snapshot.content_hash
    assert changed.account_source_ref.account_id == "portfolio-account-99"
    assert changed.broker_account_id == 42


def test_snapshot_requires_positive_binding_revision_and_exact_hashes() -> None:
    with pytest.raises(ValueError, match="binding_revision"):
        _snapshot(binding_revision=0)
    with pytest.raises(ValueError, match="binding_content_hash"):
        _snapshot(binding_content_hash="bad")
    with pytest.raises(ValueError, match="agent_content_hash"):
        _snapshot(agent_content_hash="bad")


def test_valid_until_is_strict_minimum_of_account_source_and_ttl() -> None:
    assert _snapshot().valid_until == NOW + timedelta(days=7)

    source = _account_source(valid_until=NOW + timedelta(days=2))
    earlier_source = _snapshot(
        account_source_ref=source,
        valid_until=NOW + timedelta(days=2),
    )
    assert earlier_source.valid_until == source.valid_until

    with pytest.raises(ValueError, match="strict minimum"):
        _snapshot(valid_until=NOW + timedelta(days=6))


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"issued_at": NOW + timedelta(seconds=1)},
        {"recorded_at": NOW + timedelta(days=8)},
        {"ttl_valid_until": NOW},
    ],
)
def test_snapshot_rejects_invalid_clock_sequence(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="clock"):
        _snapshot(**changes)


def test_snapshot_rejects_account_source_not_knowable_at_recording() -> None:
    source = _account_source(
        recorded_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(days=30),
    )
    with pytest.raises(ValueError, match="source is not knowable"):
        _snapshot(account_source_ref=source)


def test_authoritative_change_changes_content_but_not_identity_hash() -> None:
    snapshot = _snapshot()
    changed = _snapshot(binding_revision=4)

    assert changed.identity_hash == snapshot.identity_hash
    assert changed.content_hash != snapshot.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(snapshot, binding_revision=4)


def test_successor_binds_same_account_owner_and_advances_clock() -> None:
    previous = _snapshot()
    successor = _snapshot(
        snapshot_id="broker-account-snapshot-2",
        snapshot_version="v2",
        binding_revision=4,
        issued_at=NOW + timedelta(minutes=59),
        recorded_at=NOW + timedelta(hours=1),
        supersedes_snapshot_hash=previous.content_hash,
    )

    validate_broker_account_identity_snapshot_successor(previous, successor)

    with pytest.raises(ValueError, match="account identity"):
        validate_broker_account_identity_snapshot_successor(
            previous,
            _snapshot(
                snapshot_id="broker-account-snapshot-3",
                snapshot_version="v3",
                broker_account_id=43,
                issued_at=NOW + timedelta(minutes=59),
                recorded_at=NOW + timedelta(hours=1),
                supersedes_snapshot_hash=previous.content_hash,
            ),
        )


def test_domain_module_has_no_framework_or_cross_app_imports() -> None:
    source = Path("apps/broker_execution/domain/broker_account_identity_snapshot.py").read_text(
        encoding="utf-8"
    )

    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
