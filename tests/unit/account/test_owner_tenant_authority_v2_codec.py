"""Unit contracts for the strict owner/tenant authority v2 codecs."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from apps.account.domain.owner_tenant_authority_v2 import (
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    encode_account_owner_assignment_evidence_v3,
)
from apps.account.infrastructure.owner_tenant_authority_v1_codec import (
    decode_owner_tenant_authority_v1,
    encode_owner_tenant_authority_v1,
)
from apps.account.infrastructure.owner_tenant_authority_v2_codec import (
    OwnerTenantAuthorityV2CodecError,
    decode_owner_tenant_authority_v2,
    decode_owner_tenant_authority_v2_revocation,
    encode_owner_tenant_authority_v2,
    encode_owner_tenant_authority_v2_revocation,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence as _v3_evidence
from tests.unit.account.test_owner_tenant_authority_v1 import _authority as _v1_authority
from tests.unit.account.test_owner_tenant_authority_v2 import (
    _authority,
    _revocation,
)


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Return an independent JSON-shaped payload for mutation tests."""

    return deepcopy(value)


def test_v2_root_and_revocation_roundtrip_preserve_the_complete_graph() -> None:
    """Keep nested V4 assignment, V1 policy, derived scope, and seals intact."""

    authority = _authority()
    revocation = _revocation(authority)

    authority_payload = encode_owner_tenant_authority_v2(authority)
    revocation_payload = encode_owner_tenant_authority_v2_revocation(revocation)

    assert decode_owner_tenant_authority_v2(authority_payload) == authority
    assert decode_owner_tenant_authority_v2_revocation(revocation_payload) == revocation
    assert authority_payload["assignment"] == authority.assignment.to_payload()
    assert authority_payload["policy"] == authority.policy.to_payload()
    assert authority_payload["tenant_id"] == authority.tenant_id
    assert authority_payload["actor_user_id"] == authority.actor_user_id
    assert revocation_payload["authority_content_hash"] == authority.content_hash
    assert revocation_payload["policy_content_hash"] == authority.policy.content_hash
    assert issubclass(OwnerTenantAuthorityV2CodecError, ValueError)


def test_v2_codec_rejects_cross_version_root_payloads() -> None:
    """Do not accept the historical V1 artifact at the V2 boundary."""

    legacy_payload = encode_owner_tenant_authority_v1(_v1_authority())
    v2_payload = encode_owner_tenant_authority_v2(_authority())

    with pytest.raises(OwnerTenantAuthorityV2CodecError):
        decode_owner_tenant_authority_v2(legacy_payload)
    with pytest.raises(ValueError):
        decode_owner_tenant_authority_v1(v2_payload)


def test_v2_root_codec_rejects_missing_and_extra_fields() -> None:
    """Require the root envelope to remain closed-world."""

    payload = encode_owner_tenant_authority_v2(_authority())
    missing = _copy(payload)
    missing.pop("policy")
    extra = _copy(payload)
    extra["unexpected"] = "reject"

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="shape"):
        decode_owner_tenant_authority_v2(missing)
    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="shape"):
        decode_owner_tenant_authority_v2(extra)


def test_v2_revocation_codec_rejects_missing_and_extra_fields() -> None:
    """Require the revocation envelope to remain closed-world."""

    payload = encode_owner_tenant_authority_v2_revocation(_revocation())
    missing = _copy(payload)
    missing.pop("reason")
    extra = _copy(payload)
    extra["unexpected"] = "reject"

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="shape"):
        decode_owner_tenant_authority_v2_revocation(missing)
    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="shape"):
        decode_owner_tenant_authority_v2_revocation(extra)


@pytest.mark.parametrize("field_name", ["activation_available", "must_not_execute"])
def test_v2_root_codec_rejects_integer_execution_flags(field_name: str) -> None:
    """Reject 0/1 values even though Python considers them equal to booleans."""

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    payload[field_name] = 0 if field_name == "activation_available" else 1

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="boolean|fixed"):
        decode_owner_tenant_authority_v2(payload)


def test_v2_revocation_codec_rejects_integer_flags_and_actor_user_id() -> None:
    """Reject bool/int substitutions in both fixed flags and actor identity."""

    payload = _copy(encode_owner_tenant_authority_v2_revocation(_revocation()))
    payload["activation_available"] = 0
    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="boolean|fixed"):
        decode_owner_tenant_authority_v2_revocation(payload)

    payload = _copy(encode_owner_tenant_authority_v2_revocation(_revocation()))
    revoked_by = _copy(cast(dict[str, object], payload["revoked_by"]))
    revoked_by["user_id"] = True
    payload["revoked_by"] = revoked_by
    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="integer"):
        decode_owner_tenant_authority_v2_revocation(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "assignment_identity_hash",
        "policy_identity_hash",
        "assignment_evidence_content_hash",
        "identity_hash",
        "content_hash",
    ],
)
def test_v2_root_codec_requires_nonblank_digest_fields(field_name: str) -> None:
    """Reject blank root seals before a Domain object can fill omitted defaults."""

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    payload[field_name] = ""

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="seal"):
        decode_owner_tenant_authority_v2(payload)


@pytest.mark.parametrize(
    "field_name",
    ["authority_content_hash", "policy_content_hash", "identity_hash", "content_hash"],
)
def test_v2_revocation_codec_requires_nonblank_digest_fields(field_name: str) -> None:
    """Reject blank revocation seals."""

    payload = _copy(encode_owner_tenant_authority_v2_revocation(_revocation()))
    payload[field_name] = ""

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="seal"):
        decode_owner_tenant_authority_v2_revocation(payload)


@pytest.mark.parametrize(
    "field_name",
    ["tenant_id", "owner_id", "account_namespace", "account_id", "actor_id"],
)
def test_v2_root_codec_rejects_derived_scope_substitution(field_name: str) -> None:
    """Require every derived scope value to agree with the sealed graph."""

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    payload[field_name] = "substituted"

    with pytest.raises(OwnerTenantAuthorityV2CodecError):
        decode_owner_tenant_authority_v2(payload)


@pytest.mark.parametrize("field_name", ["approved_at", "recorded_at", "valid_until"])
def test_v2_root_codec_rejects_noncanonical_clocks(field_name: str) -> None:
    """Require UTC Z timestamps with explicit microseconds."""

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    text = cast(str, payload[field_name])
    payload[field_name] = text[:-7] + "Z"

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="microseconds|canonical"):
        decode_owner_tenant_authority_v2(payload)


def test_v2_revocation_codec_rejects_noncanonical_clock_timezone() -> None:
    """Do not accept an offset timestamp at the persistence boundary."""

    payload = _copy(encode_owner_tenant_authority_v2_revocation(_revocation()))
    text = cast(str, payload["revoked_at"])
    payload["revoked_at"] = text[:-1] + "+00:00"

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="UTC|canonical"):
        decode_owner_tenant_authority_v2_revocation(payload)


def test_v2_codec_revalidates_nested_v4_assignment_and_v1_policy() -> None:
    """Reject source graph tampering and a V3 assignment substituted into V2."""

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    policy = _copy(cast(dict[str, object], payload["policy"]))
    policy["account_id"] = "account-substituted"
    payload["policy"] = policy
    with pytest.raises(OwnerTenantAuthorityV2CodecError):
        decode_owner_tenant_authority_v2(payload)

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    assignment = _copy(cast(dict[str, object], payload["assignment"]))
    assignment["evidence_version"] = "v3"
    payload["assignment"] = assignment
    with pytest.raises(OwnerTenantAuthorityV2CodecError):
        decode_owner_tenant_authority_v2(payload)

    payload = _copy(encode_owner_tenant_authority_v2(_authority()))
    payload["assignment"] = encode_account_owner_assignment_evidence_v3(_v3_evidence())
    with pytest.raises(OwnerTenantAuthorityV2CodecError):
        decode_owner_tenant_authority_v2(payload)


def test_v2_encoders_reject_substituted_domain_types() -> None:
    """Keep encode entry points exact-type and fail closed."""

    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="exact"):
        encode_owner_tenant_authority_v2(cast(OwnerTenantAuthorityV2, object()))
    with pytest.raises(OwnerTenantAuthorityV2CodecError, match="exact"):
        encode_owner_tenant_authority_v2_revocation(
            cast(OwnerTenantAuthorityV2Revocation, object())
        )
