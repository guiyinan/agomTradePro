"""Unit contracts for authenticated owner/tenant Authority V3 records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.infrastructure.owner_tenant_authority_v3_record_codec import (
    OwnerTenantAuthorityV3RecordCodecError,
    decode_owner_tenant_authority_v3_record,
    decode_owner_tenant_authority_v3_revocation_record,
    encode_owner_tenant_authority_v3_record,
    encode_owner_tenant_authority_v3_revocation_record,
)
from tests.unit.account.test_owner_tenant_authority_v3 import _authority, _revocation


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Return an independent JSON-shaped payload for mutation tests."""

    return deepcopy(value)


def _authentication(
    *,
    actor_id: str,
    user_id: int,
    recorded_at: datetime,
    valid_until: datetime,
) -> CurrentAccountActorAuthorityV3:
    """Build exact current admin facts covering the requested event clocks."""

    return CurrentAccountActorAuthorityV3(
        principal_id="principal-owner-v3",
        user_id=user_id,
        authentication_context_hash="1" * 64,
        actor_id=actor_id,
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        source_id="account-authority-source-v3",
        source_version="v3.1",
        source_content_hash="2" * 64,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _root_record() -> PersistedOwnerTenantAuthorityV3:
    """Build a root with its exact approval-time authentication source."""

    authority = _authority()
    authentication = _authentication(
        actor_id=authority.actor_id,
        user_id=authority.actor_user_id,
        recorded_at=authority.assignment.recorded_at,
        valid_until=authority.valid_until + timedelta(days=1),
    )
    return PersistedOwnerTenantAuthorityV3(authority, authentication)


def _revocation_record() -> PersistedOwnerTenantAuthorityV3Revocation:
    """Build a revocation with fresh authentication at both event clocks."""

    revocation = _revocation()
    authentication = _authentication(
        actor_id=revocation.revoked_by.actor_id,
        user_id=revocation.revoked_by.user_id,
        recorded_at=revocation.revoked_at - timedelta(minutes=1),
        valid_until=revocation.recorded_at + timedelta(hours=1),
    )
    return PersistedOwnerTenantAuthorityV3Revocation(revocation, authentication)


def test_v3_record_roundtrips_preserve_complete_authentication() -> None:
    """Roundtrip root and revocation envelopes with all authentication fields."""

    root = _root_record()
    root_payload = encode_owner_tenant_authority_v3_record(root)
    assert set(root_payload) == {"authority", "authentication"}
    assert decode_owner_tenant_authority_v3_record(root_payload) == root

    revoked = _revocation_record()
    revoked_payload = encode_owner_tenant_authority_v3_revocation_record(revoked)
    assert set(revoked_payload) == {"revocation", "authentication"}
    assert decode_owner_tenant_authority_v3_revocation_record(revoked_payload) == revoked
    assert cast(dict[str, object], revoked_payload["authentication"])["is_superuser"] is True


@pytest.mark.parametrize("kind", ["root", "revocation"])
def test_v3_record_envelopes_require_closed_key_sets(kind: str) -> None:
    """Reject missing and extra keys in both top-level record envelopes."""

    if kind == "root":
        payload = encode_owner_tenant_authority_v3_record(_root_record())
        decoder = decode_owner_tenant_authority_v3_record
        required = "authority"
    else:
        payload = encode_owner_tenant_authority_v3_revocation_record(_revocation_record())
        decoder = decode_owner_tenant_authority_v3_revocation_record
        required = "revocation"
    missing = _copy(payload)
    missing.pop(required)
    extra = _copy(payload)
    extra["unexpected"] = {}
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="shape"):
        decoder(missing)
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="shape"):
        decoder(extra)


@pytest.mark.parametrize("field_name", ["user_id", "is_staff", "is_superuser"])
def test_v3_record_authentication_rejects_bool_integer_substitution(field_name: str) -> None:
    """Reject bool/int substitutions at the authentication boundary."""

    payload = _copy(encode_owner_tenant_authority_v3_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication[field_name] = True if field_name == "user_id" else 1
    payload["authentication"] = authentication
    expected = "integer" if field_name == "user_id" else "boolean"
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match=expected):
        decode_owner_tenant_authority_v3_record(payload)


def test_v3_record_authentication_requires_seals_and_canonical_clocks() -> None:
    """Reject blank source seals and noncanonical UTC timestamps."""

    payload = _copy(encode_owner_tenant_authority_v3_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication["source_content_hash"] = ""
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="seal"):
        decode_owner_tenant_authority_v3_record(payload)

    payload = _copy(encode_owner_tenant_authority_v3_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    recorded_at = cast(str, authentication["recorded_at"])
    authentication["recorded_at"] = recorded_at[:-7] + "Z"
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="canonical|microseconds"):
        decode_owner_tenant_authority_v3_record(payload)


@pytest.mark.parametrize("field_name", ["actor_id", "user_id"])
def test_v3_record_rejects_authentication_actor_scope_substitution(field_name: str) -> None:
    """Bind authentication to the exact owner actor sealed by Authority V3."""

    payload = _copy(encode_owner_tenant_authority_v3_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication[field_name] = "other-actor" if field_name == "actor_id" else 999
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="invalid"):
        decode_owner_tenant_authority_v3_record(payload)


def test_v3_revocation_record_rejects_cross_scope_authentication() -> None:
    """Apply the same exact actor binding to revocation authentication."""

    record = _revocation_record()
    payload = _copy(encode_owner_tenant_authority_v3_revocation_record(record))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication["user_id"] = record.revocation.revoked_by.user_id + 1
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="invalid"):
        decode_owner_tenant_authority_v3_revocation_record(payload)


def test_v3_record_revalidates_nested_authority_and_version() -> None:
    """Reject nested authority tampering and cross-version schema substitution."""

    payload = _copy(encode_owner_tenant_authority_v3_record(_root_record()))
    authority = _copy(cast(dict[str, object], payload["authority"]))
    authority["schema"] = "account.owner_tenant_authority.v2"
    payload["authority"] = authority
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError):
        decode_owner_tenant_authority_v3_record(payload)


def test_v3_record_encoders_require_exact_dto_types() -> None:
    """Keep record encode entry points closed to arbitrary DTO substitutions."""

    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="exact"):
        encode_owner_tenant_authority_v3_record(cast(PersistedOwnerTenantAuthorityV3, object()))
    with pytest.raises(OwnerTenantAuthorityV3RecordCodecError, match="exact"):
        encode_owner_tenant_authority_v3_revocation_record(
            cast(PersistedOwnerTenantAuthorityV3Revocation, object())
        )
