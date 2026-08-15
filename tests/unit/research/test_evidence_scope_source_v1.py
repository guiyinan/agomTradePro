"""Pure contract tests for the dormant owner/tenant scope source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
    validate_evidence_scope_source_v1_successor,
)

AS_OF = datetime(2026, 8, 15, 10, tzinfo=UTC)


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _root(**changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": "scope-source-1",
        "source_version": "v1",
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "actor_id": "actor-1",
        "artifact": _artifact(),
        "status": "active",
        "recorded_at": AS_OF - timedelta(minutes=1),
        "valid_until": AS_OF + timedelta(hours=1),
        "root_claim_hash": "",
        "supersedes_content_hash": None,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    if values["root_claim_hash"] == "":
        values["root_claim_hash"] = root_claim_hash_for_evidence_scope_source_v1(
            source_id=values["source_id"],
            owner_id=values["owner_id"],
            tenant_id=values["tenant_id"],
            account_id=values["account_id"],
            actor_id=values["actor_id"],
            artifact=values["artifact"],
        )
    return EvidenceScopeSourceV1(**values)  # type: ignore[arg-type]


def _successor(previous: EvidenceScopeSourceV1, **changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": previous.source_id,
        "source_version": "v2",
        "owner_id": previous.owner_id,
        "tenant_id": previous.tenant_id,
        "account_id": previous.account_id,
        "actor_id": previous.actor_id,
        "artifact": previous.artifact,
        "status": "active",
        "recorded_at": previous.recorded_at + timedelta(minutes=1),
        "valid_until": previous.valid_until + timedelta(minutes=1),
        "root_claim_hash": None,
        "supersedes_content_hash": previous.content_hash,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    return EvidenceScopeSourceV1(**values)  # type: ignore[arg-type]


def test_root_source_is_fixed_secret_free_and_temporally_bounded() -> None:
    source = _root()

    assert source.permission == "read_only"
    assert source.must_not_execute is True
    assert source.execution_allowed is False
    assert source.is_knowable_at(AS_OF)
    assert source.is_temporally_current_at(AS_OF)
    payload = source.to_payload()
    assert not any(
        secret in payload for secret in ("session_key", "cookie", "csrf", "password", "token")
    )


def test_root_claim_binds_all_scope_identity_fields() -> None:
    source = _root()
    expected = root_claim_hash_for_evidence_scope_source_v1(
        source_id=source.source_id,
        owner_id=source.owner_id,
        tenant_id=source.tenant_id,
        account_id=source.account_id,
        actor_id=source.actor_id,
        artifact=source.artifact,
    )
    assert source.root_claim_hash == expected

    with pytest.raises(ValueError):
        _root(tenant_id="tenant-other", root_claim_hash=source.root_claim_hash)


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "other"},
        {"permission": "execute"},
        {"must_not_execute": False},
        {"execution_allowed": True},
        {"status": "unknown"},
        {"recorded_at": AS_OF + timedelta(hours=2)},
        {"valid_until": AS_OF - timedelta(minutes=2)},
    ],
)
def test_invalid_fixed_semantics_or_clock_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _root(**changes)


def test_successor_binds_exact_predecessor_and_advances_clock() -> None:
    previous = _root()
    successor = _successor(previous)

    validate_evidence_scope_source_v1_successor(previous, successor)
    assert successor.predecessor_content_hash == previous.content_hash
    assert successor.is_knowable_at(AS_OF)
    assert successor.is_temporally_current_at(AS_OF)


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "tenant-other"},
        {"account_id": "account-other"},
        {"actor_id": "actor-other"},
        {"supersedes_content_hash": "b" * 64},
        {"recorded_at": AS_OF - timedelta(minutes=1)},
        {"source_version": "v1"},
    ],
)
def test_successor_substitution_or_clock_regression_is_rejected(
    changes: dict[str, object],
) -> None:
    previous = _root()
    successor = _successor(previous, **changes)

    with pytest.raises((TypeError, ValueError)):
        validate_evidence_scope_source_v1_successor(previous, successor)


def test_revoked_head_is_terminal_and_never_current() -> None:
    previous = _root()
    revoked = _successor(previous, status="revoked")

    assert not revoked.is_temporally_current_at(AS_OF)
    with pytest.raises(ValueError):
        validate_evidence_scope_source_v1_successor(revoked, _successor(revoked))


def test_hash_tamper_is_detected_by_revalidation() -> None:
    source = _root()
    object.__setattr__(source, "tenant_id", "tenant-tampered")

    with pytest.raises(ValueError):
        source.__post_init__()
