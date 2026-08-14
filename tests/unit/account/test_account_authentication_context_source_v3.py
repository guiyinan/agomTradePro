from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
    root_claim_hash_for_account_authentication_context_source_v3,
    validate_account_authentication_context_source_v3_successor,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _source(**changes: object) -> AccountAuthenticationContextSourceV3:
    values: dict[str, object] = {
        "identity": AccountAuthorityRawSourceIdentityV3("session-41", "v1"),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW, NOW + timedelta(minutes=1), NOW + timedelta(hours=2)
        ),
        "chain": AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_authentication_context_source_v3(
                source_id="session-41",
                principal_id="principal-41",
                user_id=41,
                actor_id="django-user:41",
            )
        ),
        "principal_id": "principal-41",
        "user_id": 41,
        "actor_id": "django-user:41",
        "is_authenticated": True,
        "authority_state": "authenticated",
        "authenticated_at": NOW - timedelta(minutes=5),
    }
    values.update(changes)
    return AccountAuthenticationContextSourceV3(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountAuthenticationContextSourceV3, **changes: object
) -> AccountAuthenticationContextSourceV3:
    values: dict[str, object] = {
        "identity": AccountAuthorityRawSourceIdentityV3("session-41", "v2"),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW + timedelta(minutes=2), NOW + timedelta(minutes=3), NOW + timedelta(hours=2)
        ),
        "chain": AccountAuthorityRawSourceChainV3(supersedes_content_hash=previous.content_hash),
        "principal_id": previous.principal_id,
        "user_id": previous.user_id,
        "actor_id": previous.actor_id,
        "is_authenticated": False,
        "authority_state": "revoked",
        "authenticated_at": previous.authenticated_at,
    }
    values.update(changes)
    return AccountAuthenticationContextSourceV3(**values)  # type: ignore[arg-type]


def test_fixed_secret_free_authenticated_root_and_canonical_hashes() -> None:
    source = _source()
    assert (
        source.owner,
        source.permission,
        source.status,
        source.must_not_execute,
        source.execution_allowed,
    ) == ("account", "attestation_only", "inactive", True, False)
    assert source.is_knowable_at(source.clock.recorded_at)
    assert source.is_temporally_current_at(source.clock.recorded_at)
    assert all(
        len(getattr(source, name)) == 64
        for name in (
            "identity_hash",
            "principal_seal",
            "facts_seal",
            "clock_seal",
            "chain_seal",
            "fixed_authority_seal",
            "record_seal",
            "content_hash",
        )
    )
    assert source.to_payload() == _source().to_payload()


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": True},
        {"is_authenticated": 1},
        {"authority_state": "revoked"},
        {"authenticated_at": NOW + timedelta(minutes=2)},
        {"execution_allowed": True},
    ],
)
def test_exact_types_fact_pair_clock_and_fixed_semantics_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _source(**changes)


@pytest.mark.parametrize(
    "field",
    [
        "identity_hash",
        "principal_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ],
)
def test_hash_or_seal_tamper_fails_closed(field: str) -> None:
    with pytest.raises(ValueError):
        replace(_source(), **{field: "0" * 64})


def test_revocation_successor_is_terminal_and_historical_no_fallback() -> None:
    first = _source()
    revoked = _successor(first)
    validate_account_authentication_context_source_v3_successor(first, revoked)
    assert revoked.is_knowable_at(revoked.clock.valid_until + timedelta(days=1))
    assert not revoked.is_temporally_current_at(revoked.clock.recorded_at)
    with pytest.raises(ValueError, match="terminal"):
        validate_account_authentication_context_source_v3_successor(revoked, _successor(revoked))


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": AccountAuthorityRawSourceIdentityV3("new-session", "v2")},
        {"principal_id": "other"},
        {"user_id": 42},
        {"actor_id": "django-user:42"},
        {"authenticated_at": NOW - timedelta(minutes=6)},
        {"identity": AccountAuthorityRawSourceIdentityV3("session-41", "v1")},
        {
            "clock": AccountAuthorityRawSourceClockV3(
                NOW + timedelta(minutes=1), NOW + timedelta(minutes=2), NOW + timedelta(hours=2)
            )
        },
    ],
)
def test_successor_rejects_new_session_identity_drift_or_nonadvance(
    changes: dict[str, object],
) -> None:
    first = _source()
    successor = _successor(first, **changes)
    with pytest.raises(ValueError):
        validate_account_authentication_context_source_v3_successor(first, successor)


def test_domain_imports_only_stdlib_and_account_domain_primitives_and_has_no_secret_fields() -> (
    None
):
    path = (
        Path(__file__).parents[3]
        / "apps/account/domain/account_authentication_context_source_v3.py"
    )
    source = path.read_text(encoding="utf-8")
    modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(
        module.startswith(
            ("__future__", "dataclasses", "datetime", "typing", "apps.account.domain")
        )
        for module in modules
    )
    assert set(AccountAuthenticationContextSourceV3.__dataclass_fields__).isdisjoint(
        {"secret", "cookie", "token", "password", "session_key"}
    )
