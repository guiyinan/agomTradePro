from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
    domain_hash,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    ACCOUNT_RBAC_AUTHORITY_ROLES,
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
    validate_account_rbac_authority_source_v3_successor,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _source(**changes: object) -> AccountRbacAuthoritySourceV3:
    source_id = changes.pop("source_id", "rbac-user-41")
    source_version = changes.pop("source_version", "v1")
    user_id = changes.pop("user_id", 41)
    actor_id = changes.pop("actor_id", "django-user:41")
    root = root_claim_hash_for_account_rbac_authority_source_v3(
        source_id=source_id,  # type: ignore[arg-type]
        user_id=user_id,  # type: ignore[arg-type]
        actor_id=actor_id,  # type: ignore[arg-type]
    )
    values: dict[str, object] = {
        "identity": AccountAuthorityRawSourceIdentityV3(
            source_id,
            source_version,  # type: ignore[arg-type]
        ),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=1)
        ),
        "chain": AccountAuthorityRawSourceChainV3(root_claim_hash=root),
        "user_id": user_id,
        "actor_id": actor_id,
        "rbac_role": "owner",
        "authority_state": "current",
    }
    values.update(changes)
    return AccountRbacAuthoritySourceV3(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountRbacAuthoritySourceV3, **changes: object
) -> AccountRbacAuthoritySourceV3:
    values: dict[str, object] = {
        "identity": AccountAuthorityRawSourceIdentityV3(previous.identity.source_id, "v2"),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=1),
            NOW + timedelta(hours=1),
        ),
        "chain": AccountAuthorityRawSourceChainV3(supersedes_content_hash=previous.content_hash),
        "user_id": previous.user_id,
        "actor_id": previous.actor_id,
        "rbac_role": "admin",
        "authority_state": "current",
    }
    values.update(changes)
    return AccountRbacAuthoritySourceV3(**values)  # type: ignore[arg-type]


def test_fixed_inactive_rbac_attestation_and_canonical_seals() -> None:
    source = _source()

    assert (
        source.owner,
        source.artifact_type,
        source.schema,
        source.permission,
        source.status,
        source.must_not_execute,
        source.execution_allowed,
    ) == (
        "account",
        "account_rbac_authority_source_v3",
        "account.rbac_authority_source.v3",
        "attestation_only",
        "inactive",
        True,
        False,
    )
    for name in (
        "identity_hash",
        "rbac_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ):
        assert len(getattr(source, name)) == 64
    assert source.to_payload()["identity"] == {
        "source_id": "rbac-user-41",
        "source_version": "v1",
    }


@pytest.mark.parametrize(
    "field",
    [
        "identity_hash",
        "rbac_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ],
)
def test_each_rbac_authority_seal_fails_closed_when_substituted(field: str) -> None:
    with pytest.raises(ValueError):
        _source(**{field: "0" * 64})


@pytest.mark.parametrize("role", sorted(ACCOUNT_RBAC_AUTHORITY_ROLES))
def test_accepts_only_the_closed_canonical_account_role_set(role: str) -> None:
    assert _source(rbac_role=role).rbac_role == role


@pytest.mark.parametrize("role", ["administrator", "ADMIN", "read-only", "unknown", ""])
def test_rejects_role_aliases_or_unknown_values(role: str) -> None:
    with pytest.raises(ValueError):
        _source(rbac_role=role)


def test_root_claim_binds_source_user_actor_and_account_namespace() -> None:
    root = root_claim_hash_for_account_rbac_authority_source_v3(
        source_id="rbac-user-41", user_id=41, actor_id="django-user:41"
    )

    assert root != root_claim_hash_for_account_rbac_authority_source_v3(
        source_id="rbac-user-42", user_id=41, actor_id="django-user:41"
    )
    assert root != root_claim_hash_for_account_rbac_authority_source_v3(
        source_id="rbac-user-41", user_id=42, actor_id="django-user:41"
    )
    assert root != domain_hash(
        "other-owner/root-claim",
        {
            "source_id": "rbac-user-41",
            "user_id": 41,
            "actor_id": "django-user:41",
        },
    )


def test_role_state_and_clock_tampering_changes_content_hash() -> None:
    original = _source()

    assert _source(rbac_role="admin").content_hash != original.content_hash
    assert _source(authority_state="revoked").content_hash != original.content_hash
    assert (
        _source(
            clock=AccountAuthorityRawSourceClockV3(
                NOW, NOW + timedelta(minutes=1), NOW + timedelta(hours=1)
            )
        ).content_hash
        != original.content_hash
    )


def test_valid_successor_binds_exact_predecessor_and_advances_clock() -> None:
    previous = _source()
    successor = _successor(previous)

    validate_account_rbac_authority_source_v3_successor(previous, successor)


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": AccountAuthorityRawSourceIdentityV3("other-root", "v2")},
        {"identity": AccountAuthorityRawSourceIdentityV3("rbac-user-41", "v1")},
        {"user_id": 42},
        {"actor_id": "django-user:42"},
        {"chain": AccountAuthorityRawSourceChainV3(supersedes_content_hash="f" * 64)},
        {
            "clock": AccountAuthorityRawSourceClockV3(
                NOW, NOW + timedelta(minutes=1), NOW + timedelta(hours=1)
            )
        },
    ],
)
def test_successor_rejects_cross_root_version_clock_or_predecessor(
    changes: dict[str, object],
) -> None:
    previous = _source()
    successor = _successor(previous, **changes)

    with pytest.raises(ValueError):
        validate_account_rbac_authority_source_v3_successor(previous, successor)


def test_revoked_authority_is_terminal_and_never_temporally_current() -> None:
    revoked = _source(authority_state="revoked")

    assert revoked.is_knowable_at(revoked.clock.valid_until + timedelta(days=1))
    assert not revoked.is_temporally_current_at(revoked.clock.recorded_at)
    with pytest.raises(ValueError, match="revoked"):
        validate_account_rbac_authority_source_v3_successor(revoked, _successor(revoked))


def test_temporal_currentness_is_local_and_history_survives_expiry() -> None:
    source = _source()

    assert source.is_temporally_current_at(source.clock.recorded_at)
    assert not source.is_temporally_current_at(source.clock.valid_until)
    assert source.is_knowable_at(source.clock.valid_until + timedelta(days=1))
    assert not source.is_knowable_at(source.clock.recorded_at - timedelta(microseconds=1))


def test_exact_types_nested_primitives_and_fixed_boundary_fail_closed() -> None:
    with pytest.raises(ValueError):
        _source(user_id=True)
    with pytest.raises(TypeError):
        _source(identity=object())
    with pytest.raises(TypeError):
        _source(clock=object())
    with pytest.raises(TypeError):
        _source(chain=object())
    with pytest.raises(ValueError):
        _source(execution_allowed=True)


def test_domain_imports_only_stdlib_and_same_account_domain_primitives() -> None:
    path = Path(__file__).parents[3] / "apps/account/domain/account_rbac_authority_source_v3.py"
    source = path.read_text(encoding="utf-8")
    imports = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imports <= {
        "__future__",
        "dataclasses",
        "datetime",
        "typing",
        "apps.account.domain.account_actor_authority_raw_source_primitives_v3",
    }
    assert "normalize_role" not in source
