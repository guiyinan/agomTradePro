from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
    canonical_utc_z,
    domain_hash,
    validate_account_authority_raw_source_fixed_header_v3,
)

NOW = datetime(2026, 8, 14, 10, 0, 0, 123456, tzinfo=UTC)


def test_identity_and_clock_are_exact_frozen_value_objects() -> None:
    identity = AccountAuthorityRawSourceIdentityV3("raw-user-41", "v1")
    clock = AccountAuthorityRawSourceClockV3(NOW, NOW, NOW + timedelta(hours=1))

    assert (identity.source_id, identity.source_version) == ("raw-user-41", "v1")
    assert clock.observed_at == clock.recorded_at
    with pytest.raises(FrozenInstanceError):
        identity.source_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        (datetime(2026, 8, 14, 10), NOW, NOW + timedelta(hours=1)),
        (NOW + timedelta(microseconds=1), NOW, NOW + timedelta(hours=1)),
        (NOW, NOW, NOW),
    ],
)
def test_clock_rejects_naive_backwards_or_empty_windows(
    values: tuple[datetime, datetime, datetime],
) -> None:
    with pytest.raises(ValueError):
        AccountAuthorityRawSourceClockV3(*values)


def test_canonical_utc_z_normalizes_offsets_and_rejects_non_datetime() -> None:
    offset = NOW.astimezone(timezone(timedelta(hours=8)))

    assert canonical_utc_z(offset) == "2026-08-14T10:00:00.123456Z"
    with pytest.raises(ValueError):
        canonical_utc_z("2026-08-14")  # type: ignore[arg-type]


def test_domain_hash_is_stable_and_domain_separated() -> None:
    left = domain_hash("account-auth/raw-user", {"user_id": 41, "active": True})
    reordered = domain_hash("account-auth/raw-user", {"active": True, "user_id": 41})
    other_domain = domain_hash("account-auth/raw-rbac", {"user_id": 41, "active": True})

    assert left == reordered
    assert left != other_domain
    assert len(left) == 64
    with pytest.raises(TypeError):
        domain_hash("account-auth/raw-user", [])  # type: ignore[arg-type]


def test_chain_requires_exactly_one_exact_digest_anchor() -> None:
    assert AccountAuthorityRawSourceChainV3(root_claim_hash="a" * 64).root_claim_hash
    assert AccountAuthorityRawSourceChainV3(
        supersedes_content_hash="b" * 64
    ).supersedes_content_hash
    for values in (
        {},
        {"root_claim_hash": "a" * 64, "supersedes_content_hash": "b" * 64},
        {"root_claim_hash": "A" * 64},
        {"supersedes_content_hash": 1},
    ):
        with pytest.raises(ValueError):
            AccountAuthorityRawSourceChainV3(**values)  # type: ignore[arg-type]


def test_fixed_header_accepts_only_exact_inactive_nonexecution_semantics() -> None:
    values: dict[str, object] = {
        "owner": "account",
        "artifact_type": "account_user_authority_source_v3",
        "schema": "account.user_authority_source.v3",
        "permission": "attestation_only",
        "status": "inactive",
        "must_not_execute": True,
        "execution_allowed": False,
        "expected_artifact_type": "account_user_authority_source_v3",
        "expected_schema": "account.user_authority_source.v3",
    }

    validate_account_authority_raw_source_fixed_header_v3(**values)  # type: ignore[arg-type]
    for name, replacement in (
        ("owner", "shared"),
        ("permission", "execute"),
        ("status", "active"),
        ("must_not_execute", False),
        ("execution_allowed", True),
    ):
        changed = {**values, name: replacement}
        with pytest.raises(ValueError):
            validate_account_authority_raw_source_fixed_header_v3(
                **changed  # type: ignore[arg-type]
            )
    with pytest.raises(TypeError):
        validate_account_authority_raw_source_fixed_header_v3(
            **{**values, "execution_allowed": 0}  # type: ignore[arg-type]
        )


def test_identity_rejects_noncanonical_or_non_string_tokens() -> None:
    for values in ((" raw", "v1"), ("raw", "v 1"), ("raw", 1), (True, "v1")):
        with pytest.raises(ValueError):
            AccountAuthorityRawSourceIdentityV3(*values)  # type: ignore[arg-type]


def test_module_is_stdlib_only_and_contains_no_business_artifact_discriminator() -> None:
    path = (
        Path(__file__).parents[3]
        / "apps/account/domain/account_actor_authority_raw_source_primitives_v3.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(("apps.", "shared.", "django", "requests", "numpy", "pandas"))
        for module in imports
    )
    assert "authority_kind" not in source
