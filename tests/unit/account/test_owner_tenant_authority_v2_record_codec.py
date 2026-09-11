"""Unit contracts for authenticated owner/tenant authority v2 records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    PersistedOwnerTenantAuthorityV2,
    PersistedOwnerTenantAuthorityV2Revocation,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from apps.account.infrastructure.owner_tenant_authority_v1_codec import (
    encode_owner_tenant_authority_v1,
)
from apps.account.infrastructure.owner_tenant_authority_v2_record_codec import (
    OwnerTenantAuthorityV2RecordCodecError,
    decode_owner_tenant_authority_v2_record,
    decode_owner_tenant_authority_v2_revocation_record,
    encode_owner_tenant_authority_v2_record,
    encode_owner_tenant_authority_v2_revocation_record,
)
from tests.unit.account.test_owner_tenant_authority_v1 import _authority as _v1_authority
from tests.unit.account.test_owner_tenant_authority_v2 import (
    _at,
    _authority,
    _revocation,
)


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Return an independent JSON-shaped payload for mutation tests."""

    return deepcopy(value)


def _authentication(
    *,
    actor_id: str,
    user_id: int,
    recorded_at: datetime,
    valid_until: datetime,
    **changes: object,
) -> CurrentAccountActorAuthorityV3:
    """Build an exact current admin source covering the requested decision clocks."""

    values: dict[str, object] = {
        "principal_id": "principal-owner-v2",
        "user_id": user_id,
        "authentication_context_hash": "1" * 64,
        "actor_id": actor_id,
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "rbac_role": "admin",
        "source_id": "account-authority-v3",
        "source_version": "v3.1",
        "source_content_hash": "2" * 64,
        "recorded_at": recorded_at,
        "valid_until": valid_until,
    }
    values.update(changes)
    return CurrentAccountActorAuthorityV3(**values)  # type: ignore[arg-type]


def _root_record() -> PersistedOwnerTenantAuthorityV2:
    """Build one root whose decision validity intentionally outlives auth freshness."""

    authority = _authority()
    authentication = _authentication(
        actor_id=authority.actor_id,
        user_id=authority.actor_user_id,
        recorded_at=_at(8, 17),
        valid_until=_at(8, 20),
    )
    return PersistedOwnerTenantAuthorityV2(authority, authentication)


def _revocation_record() -> PersistedOwnerTenantAuthorityV2Revocation:
    """Build one revocation record with fresh authentication at both event clocks."""

    revocation = _revocation()
    authentication = _authentication(
        actor_id=revocation.revoked_by.actor_id,
        user_id=revocation.revoked_by.user_id,
        recorded_at=_at(14, 11),
        valid_until=_at(14, 13),
    )
    return PersistedOwnerTenantAuthorityV2Revocation(revocation, authentication)


def test_root_record_roundtrip_preserves_all_authentication_fields() -> None:
    """Keep the nested root and all fourteen approval-time source fields."""

    record = _root_record()
    payload = encode_owner_tenant_authority_v2_record(record)

    assert set(payload) == {"authority", "authentication"}
    assert decode_owner_tenant_authority_v2_record(payload) == record
    assert payload["authority"] == record.authority.to_payload()
    assert record.authority.valid_until > record.authentication.valid_until
    assert cast(dict[str, object], payload["authentication"])["is_superuser"] is False


def test_revocation_record_roundtrip_preserves_event_authentication() -> None:
    """Keep the revocation event separate from the root record envelope."""

    record = _revocation_record()
    payload = encode_owner_tenant_authority_v2_revocation_record(record)

    assert set(payload) == {"revocation", "authentication"}
    assert decode_owner_tenant_authority_v2_revocation_record(payload) == record
    assert payload["revocation"] == record.revocation.to_payload()
    assert cast(dict[str, object], payload["authentication"])["source_version"] == "v3.1"


def test_record_envelopes_reject_missing_and_extra_fields() -> None:
    """Require distinct closed two-key envelopes for roots and revocations."""

    root_payload = encode_owner_tenant_authority_v2_record(_root_record())
    root_missing = _copy(root_payload)
    root_missing.pop("authority")
    root_extra = _copy(root_payload)
    root_extra["revocation"] = {}

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="shape"):
        decode_owner_tenant_authority_v2_record(root_missing)
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="shape"):
        decode_owner_tenant_authority_v2_record(root_extra)

    revocation_payload = encode_owner_tenant_authority_v2_revocation_record(_revocation_record())
    revocation_missing = _copy(revocation_payload)
    revocation_missing.pop("revocation")
    revocation_extra = _copy(revocation_payload)
    revocation_extra["authority"] = {}

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="shape"):
        decode_owner_tenant_authority_v2_revocation_record(revocation_missing)
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="shape"):
        decode_owner_tenant_authority_v2_revocation_record(revocation_extra)


@pytest.mark.parametrize("field_name", ["user_id", "is_staff", "is_superuser"])
def test_record_authentication_rejects_bool_integer_substitution(field_name: str) -> None:
    """Reject True/0/1 substitutions at the authentication boundary."""

    payload = _copy(encode_owner_tenant_authority_v2_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication[field_name] = True if field_name == "user_id" else 1
    payload["authentication"] = authentication

    expected_message = "integer" if field_name == "user_id" else "boolean"
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match=expected_message):
        decode_owner_tenant_authority_v2_record(payload)


def test_record_authentication_rejects_blank_hash_and_noncanonical_clock() -> None:
    """Require non-empty source seals and UTC microsecond timestamps."""

    payload = _copy(encode_owner_tenant_authority_v2_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication["source_content_hash"] = ""
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="seal"):
        decode_owner_tenant_authority_v2_record(payload)

    payload = _copy(encode_owner_tenant_authority_v2_record(_root_record()))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    clock = cast(str, authentication["recorded_at"])
    authentication["recorded_at"] = clock[:-7] + "Z"
    payload["authentication"] = authentication
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="canonical|microseconds"):
        decode_owner_tenant_authority_v2_record(payload)


@pytest.mark.parametrize("field_name", ["actor_id", "user_id"])
def test_record_rejects_authentication_actor_scope_substitution(field_name: str) -> None:
    """Require authentication to identify the exact owner actor sealed by the decision."""

    record = _root_record()
    payload = _copy(encode_owner_tenant_authority_v2_record(record))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication[field_name] = "other-actor" if field_name == "actor_id" else 999
    payload["authentication"] = authentication

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="invalid|authentication"):
        decode_owner_tenant_authority_v2_record(payload)


def test_record_rejects_authentication_expired_at_decision_recording() -> None:
    """Require approval-time authentication to cover both approval and recording clocks."""

    record = _root_record()
    payload = _copy(encode_owner_tenant_authority_v2_record(record))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication["valid_until"] = record.authority.recorded_at.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    payload["authentication"] = authentication

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="invalid"):
        decode_owner_tenant_authority_v2_record(payload)


def test_record_revalidates_nested_authority_and_rejects_v1_root() -> None:
    """Use the V2 codec for the nested decision and keep V1 structurally separate."""

    payload = _copy(encode_owner_tenant_authority_v2_record(_root_record()))
    authority = _copy(cast(dict[str, object], payload["authority"]))
    policy = _copy(cast(dict[str, object], authority["policy"]))
    policy["account_id"] = "account-substituted"
    authority["policy"] = policy
    payload["authority"] = authority
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError):
        decode_owner_tenant_authority_v2_record(payload)

    root = _root_record()
    v1_payload = encode_owner_tenant_authority_v1(_v1_authority())
    cross_version = {
        "authority": v1_payload,
        "authentication": encode_owner_tenant_authority_v2_record(root)["authentication"],
    }
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError):
        decode_owner_tenant_authority_v2_record(cross_version)


def test_revocation_record_rejects_cross_scope_authentication() -> None:
    """Apply the same actor binding to the revocation-time authentication source."""

    record = _revocation_record()
    payload = _copy(encode_owner_tenant_authority_v2_revocation_record(record))
    authentication = _copy(cast(dict[str, object], payload["authentication"]))
    authentication["user_id"] = record.revocation.revoked_by.user_id + 1
    payload["authentication"] = authentication

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="invalid|authentication"):
        decode_owner_tenant_authority_v2_revocation_record(payload)


def test_record_encoders_reject_substituted_dto_types() -> None:
    """Keep encode entry points exact-type and fail closed."""

    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="exact"):
        encode_owner_tenant_authority_v2_record(cast(PersistedOwnerTenantAuthorityV2, object()))
    with pytest.raises(OwnerTenantAuthorityV2RecordCodecError, match="exact"):
        encode_owner_tenant_authority_v2_revocation_record(
            cast(PersistedOwnerTenantAuthorityV2Revocation, object())
        )


def test_record_codec_exports_exact_domain_type_contracts() -> None:
    """Document the two DTO/domain pairings used by the persistence boundary."""

    assert isinstance(_root_record().authority, OwnerTenantAuthorityV2)
    assert isinstance(_revocation_record().revocation, OwnerTenantAuthorityV2Revocation)
