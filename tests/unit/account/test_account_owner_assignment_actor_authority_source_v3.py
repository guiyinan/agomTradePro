from __future__ import annotations

import ast
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    root_claim_hash_for_actor_authority_source_v3,
    validate_account_owner_assignment_actor_authority_source_v3_successor,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _source(**changes: object) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    values: dict[str, object] = {
        "source_id": "authority-session-41",
        "source_version": "v1",
        "principal_id": "principal-41",
        "user_id": 41,
        "authentication_context_id": "session-abc",
        "authentication_context_version": "generation-1",
        "authentication_context_identity_hash": "a" * 64,
        "authentication_context_content_hash": "b" * 64,
        "user_source_id": "django-user-41",
        "user_source_version": "v7",
        "user_source_content_hash": "c" * 64,
        "rbac_source_id": "account-profile-41",
        "rbac_source_version": "v3",
        "rbac_source_content_hash": "d" * 64,
        "actor_id": "django-user:41",
        "is_authenticated": True,
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
        "rbac_role": "owner",
        "authority_state": "current",
        "principal_authenticated_at": NOW - timedelta(minutes=10),
        "principal_valid_until": NOW + timedelta(hours=4),
        "source_recorded_at": NOW - timedelta(minutes=5),
        "source_valid_until": NOW + timedelta(hours=3),
        "issued_at": NOW - timedelta(minutes=2),
        "recorded_at": NOW,
        "ttl_valid_until": NOW + timedelta(hours=2),
        "valid_until": NOW + timedelta(hours=2),
        "root_claim_hash": root_claim_hash_for_actor_authority_source_v3(
            source_id="authority-session-41",
            principal_id="principal-41",
            user_id=41,
            authentication_context_identity_hash="a" * 64,
            actor_id="django-user:41",
        ),
    }
    values.update(changes)
    return AccountOwnerAssignmentActorAuthoritySourceV3(**values)  # type: ignore[arg-type]


def _successor(**changes: object) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    previous = _source()
    values: dict[str, object] = {
        **{field.name: getattr(previous, field.name) for field in fields(previous)},
        "source_version": "v2",
        "user_source_version": "v8",
        "user_source_content_hash": "e" * 64,
        "source_recorded_at": NOW + timedelta(minutes=1),
        "issued_at": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=1),
        "root_claim_hash": None,
        "supersedes_content_hash": previous.content_hash,
    }
    for field in fields(previous):
        if field.name.endswith("_seal") or field.name in {"identity_hash", "content_hash"}:
            values[field.name] = ""
    values.update(changes)
    return AccountOwnerAssignmentActorAuthoritySourceV3(**values)  # type: ignore[arg-type]


def test_root_has_fixed_inactive_attestation_only_nonexecution_semantics() -> None:
    source = _source()

    assert (
        source.owner,
        source.permission,
        source.status,
        source.must_not_execute,
        source.execution_allowed,
    ) == (
        "account",
        "attestation_only",
        "inactive",
        True,
        False,
    )
    assert source.root_claim_hash is not None
    assert source.supersedes_content_hash is None
    assert source.is_knowable_at(NOW)
    assert source.is_temporally_current_at(NOW)


def test_complete_canonical_payload_and_seals_are_stable() -> None:
    source = _source()
    rebuilt = AccountOwnerAssignmentActorAuthoritySourceV3(
        **{field.name: getattr(source, field.name) for field in fields(source)}  # type: ignore[arg-type]
    )

    assert rebuilt == source
    assert rebuilt.content_hash == source.content_hash
    for name in (
        "identity_hash",
        "principal_seal",
        "authentication_context_seal",
        "user_seal",
        "rbac_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ):
        assert len(getattr(source, name)) == 64
    assert (
        len(
            {
                source.principal_seal,
                source.authentication_context_seal,
                source.user_seal,
                source.rbac_seal,
                source.facts_seal,
                source.clock_seal,
                source.chain_seal,
                source.fixed_authority_seal,
                source.record_seal,
                source.content_hash,
            }
        )
        == 10
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"authentication_context_content_hash": "0" * 64},
        {"user_source_content_hash": "0" * 64},
        {"rbac_source_content_hash": "0" * 64},
        {"is_staff": True},
        {"rbac_role": "admin"},
        {"ttl_valid_until": NOW + timedelta(hours=1), "valid_until": NOW + timedelta(hours=1)},
    ],
)
def test_each_authority_dimension_changes_content_hash(changes: dict[str, object]) -> None:
    assert _source(**changes).content_hash != _source().content_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": True},
        {"is_staff": 1},
        {"recorded_at": datetime(2026, 8, 14, 10)},
        {"valid_until": NOW + timedelta(hours=3)},
        {"root_claim_hash": "0" * 64},
        {"root_claim_hash": None},
        {"supersedes_content_hash": "f" * 64},
        {"authority_state": "revoked"},
        {"execution_allowed": True},
    ],
)
def test_exact_types_clocks_root_xor_and_terminal_facts_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _source(**changes)


def test_valid_until_is_minimum_of_principal_source_and_ttl_bounds() -> None:
    assert _source().valid_until == _source().ttl_valid_until
    principal = _source(
        principal_valid_until=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1),
    )
    source = _source(
        source_valid_until=NOW + timedelta(minutes=30),
        valid_until=NOW + timedelta(minutes=30),
    )
    assert principal.valid_until == principal.principal_valid_until
    assert source.valid_until == source.source_valid_until


def test_historical_knowability_survives_expiry_but_current_does_not() -> None:
    source = _source()

    assert source.is_knowable_at(source.valid_until + timedelta(days=1))
    assert not source.is_temporally_current_at(source.valid_until)
    assert not source.is_knowable_at(source.recorded_at - timedelta(microseconds=1))


def test_same_session_successor_can_change_user_rbac_facts_and_revoke_terminally() -> None:
    previous = _source()
    successor = _successor(
        is_authenticated=False,
        is_active=False,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        authority_state="revoked",
    )

    validate_account_owner_assignment_actor_authority_source_v3_successor(previous, successor)
    assert not successor.is_temporally_current_at(successor.recorded_at)
    later_values: dict[str, object] = {
        field.name: getattr(successor, field.name) for field in fields(successor)
    }
    later_values.update(
        source_version="v3",
        recorded_at=successor.recorded_at + timedelta(minutes=1),
        issued_at=successor.issued_at + timedelta(minutes=1),
        source_recorded_at=successor.source_recorded_at + timedelta(minutes=1),
        supersedes_content_hash=successor.content_hash,
    )
    for field in fields(successor):
        if field.name.endswith("_seal") or field.name in {"identity_hash", "content_hash"}:
            later_values[field.name] = ""
    later = AccountOwnerAssignmentActorAuthoritySourceV3(**later_values)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="terminal"):
        validate_account_owner_assignment_actor_authority_source_v3_successor(
            successor,
            later,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"principal_id": "new-principal"},
        {"authentication_context_id": "new-session"},
        {"authentication_context_identity_hash": "f" * 64},
        {"actor_id": "django-user:42"},
        {"source_id": "new-source"},
        {"user_id": 42},
        {"supersedes_content_hash": "0" * 64},
        {"source_version": "v1"},
        {"recorded_at": NOW},
        {"source_recorded_at": NOW},
    ],
)
def test_successor_rejects_new_session_fork_or_nonadvancing_version(
    changes: dict[str, object],
) -> None:
    previous = _source()

    with pytest.raises(ValueError):
        successor = _successor(**changes)
        validate_account_owner_assignment_actor_authority_source_v3_successor(previous, successor)


def test_domain_has_only_stdlib_and_no_secret_bearing_fields() -> None:
    path = (
        Path(__file__).parents[3]
        / "apps/account/domain/account_owner_assignment_actor_authority_source_v3.py"
    )
    source = path.read_text(encoding="utf-8")
    imports = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    names = {field.name for field in fields(AccountOwnerAssignmentActorAuthoritySourceV3)}

    assert all(
        not module.startswith(("apps.", "django", "requests", "numpy", "pandas"))
        for module in imports
    )
    assert names.isdisjoint({"secret", "password", "cookie", "token", "session_key"})
