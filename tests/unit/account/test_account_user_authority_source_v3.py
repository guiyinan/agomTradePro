from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
    root_claim_hash_for_account_user_authority_source_v3,
    validate_account_user_authority_source_v3_successor,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _source(**changes: object) -> AccountUserAuthoritySourceV3:
    values: dict[str, object] = {
        "identity": AccountAuthorityRawSourceIdentityV3("django-user-41", "v1"),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=2)
        ),
        "chain": AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id="django-user-41", user_id=41, actor_id="django-user:41"
            )
        ),
        "user_id": 41,
        "actor_id": "django-user:41",
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
        "authority_state": "current",
    }
    values.update(changes)
    return AccountUserAuthoritySourceV3(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountUserAuthoritySourceV3, **changes: object
) -> AccountUserAuthoritySourceV3:
    values: dict[str, object] = {
        **previous.to_payload(),
        "identity": AccountAuthorityRawSourceIdentityV3(previous.identity.source_id, "v2"),
        "clock": AccountAuthorityRawSourceClockV3(
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=1),
            NOW + timedelta(hours=2),
        ),
        "chain": AccountAuthorityRawSourceChainV3(supersedes_content_hash=previous.content_hash),
    }
    for name in tuple(values):
        if name.endswith("_seal") or name in {"identity_hash", "content_hash"}:
            values[name] = ""
    values.update(changes)
    return AccountUserAuthoritySourceV3(**values)  # type: ignore[arg-type]


def test_current_root_is_canonical_frozen_inactive_attestation() -> None:
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
        "account_user_authority_source_v3",
        "account.user_authority_source.v3",
        "attestation_only",
        "inactive",
        True,
        False,
    )
    assert all(
        len(getattr(source, name)) == 64
        for name in (
            "identity_hash",
            "user_seal",
            "facts_seal",
            "clock_seal",
            "chain_seal",
            "fixed_authority_seal",
            "record_seal",
            "content_hash",
        )
    )
    with pytest.raises(FrozenInstanceError):
        source.user_id = 42  # type: ignore[misc]


@pytest.mark.parametrize("name", ["is_active", "is_staff", "is_superuser"])
def test_user_facts_require_exact_booleans(name: str) -> None:
    with pytest.raises(TypeError):
        _source(**{name: 1})


def test_state_requires_current_active_or_deactivated_inactive() -> None:
    with pytest.raises(ValueError):
        _source(is_active=False)
    with pytest.raises(ValueError):
        _source(authority_state="deactivated")
    with pytest.raises(ValueError):
        _source(authority_state="revoked")
    assert _source(authority_state="deactivated", is_active=False).authority_state == "deactivated"


def test_root_claim_locks_source_user_and_actor() -> None:
    root = root_claim_hash_for_account_user_authority_source_v3(
        source_id="django-user-41", user_id=41, actor_id="django-user:41"
    )

    assert root != root_claim_hash_for_account_user_authority_source_v3(
        source_id="django-user-42", user_id=41, actor_id="django-user:41"
    )
    assert root != root_claim_hash_for_account_user_authority_source_v3(
        source_id="django-user-41", user_id=42, actor_id="django-user:41"
    )
    assert root != root_claim_hash_for_account_user_authority_source_v3(
        source_id="django-user-41", user_id=41, actor_id="django-user:42"
    )
    with pytest.raises(ValueError):
        _source(chain=AccountAuthorityRawSourceChainV3(root_claim_hash="a" * 64))


def test_payload_is_nested_canonical_and_seals_detect_substitution() -> None:
    source = _source()
    payload = source.to_payload()

    assert payload["identity"] == {
        "source_id": "django-user-41",
        "source_version": "v1",
    }
    assert payload["clock"] == {
        "observed_at": "2026-08-14T09:59:00.000000Z",
        "recorded_at": "2026-08-14T10:00:00.000000Z",
        "valid_until": "2026-08-14T12:00:00.000000Z",
    }
    with pytest.raises(ValueError):
        _source(content_hash="f" * 64)


@pytest.mark.parametrize(
    "field",
    [
        "identity_hash",
        "user_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ],
)
def test_each_user_authority_seal_fails_closed_when_substituted(field: str) -> None:
    with pytest.raises(ValueError):
        _source(**{field: "0" * 64})


def test_successor_requires_exact_chain_identity_and_advancing_clock() -> None:
    root = _source()
    successor = _successor(root, is_staff=True)

    validate_account_user_authority_source_v3_successor(root, successor)
    for changed in (
        _successor(root, chain=AccountAuthorityRawSourceChainV3(supersedes_content_hash="a" * 64)),
        _successor(root, user_id=42),
        _successor(root, actor_id="django-user:42"),
        _successor(root, identity=AccountAuthorityRawSourceIdentityV3("other-source", "v2")),
        _successor(root, identity=AccountAuthorityRawSourceIdentityV3("django-user-41", "v1")),
    ):
        with pytest.raises(ValueError):
            validate_account_user_authority_source_v3_successor(root, changed)


def test_deactivated_is_terminal_and_temporal_methods_do_not_claim_headness() -> None:
    root = _source()
    terminal = _successor(root, authority_state="deactivated", is_active=False)
    validate_account_user_authority_source_v3_successor(root, terminal)

    assert not root.is_knowable_at(NOW - timedelta(microseconds=1))
    assert root.is_knowable_at(NOW + timedelta(days=1))
    assert root.is_temporally_current_at(NOW)
    assert not root.is_temporally_current_at(NOW + timedelta(hours=2))
    assert not terminal.is_temporally_current_at(terminal.clock.recorded_at)
    with pytest.raises(ValueError):
        validate_account_user_authority_source_v3_successor(terminal, _successor(terminal))


def test_module_is_pure_domain_and_has_no_secret_or_django_dependency() -> None:
    path = Path(__file__).parents[3] / "apps/account/domain/account_user_authority_source_v3.py"
    source = path.read_text(encoding="utf-8")
    imports = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(
            ("django", "requests", "numpy", "pandas", "apps.account.infrastructure")
        )
        for module in imports
    )
    assert all(secret not in source.lower() for secret in ("password", "session_key", "token_hash"))
