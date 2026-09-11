"""Unit contracts for the strict owner/tenant authority v3 codecs."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from apps.account.domain.owner_tenant_authority_v3 import (
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_codec import (
    encode_account_owner_assignment_evidence_v4,
)
from apps.account.infrastructure.owner_tenant_authority_v1_codec import (
    encode_owner_tenant_authority_v1,
)
from apps.account.infrastructure.owner_tenant_authority_v2_codec import (
    encode_owner_tenant_authority_v2,
)
from apps.account.infrastructure.owner_tenant_authority_v3_codec import (
    OwnerTenantAuthorityV3CodecError,
    decode_owner_tenant_authority_v3,
    decode_owner_tenant_authority_v3_revocation,
    encode_owner_tenant_authority_v3,
    encode_owner_tenant_authority_v3_revocation,
)
from tests.unit.account.test_account_owner_assignment_evidence_v4 import (
    _evidence as _v4_evidence,
)
from tests.unit.account.test_owner_tenant_authority_v1 import _authority as _v1_authority
from tests.unit.account.test_owner_tenant_authority_v2 import _authority as _v2_authority
from tests.unit.account.test_owner_tenant_authority_v3 import (
    _authority,
    _revocation,
    _successor,
)


def _copy(value: dict[str, object]) -> dict[str, object]:
    """Return an independent JSON-shaped payload for mutation tests."""

    return deepcopy(value)


def test_v3_root_and_revocation_roundtrip_preserve_the_complete_v5_graph() -> None:
    """Keep nested Evidence V5, Policy V1, derived scope, and seals intact."""

    authority = _authority()
    revocation = _revocation(authority)

    authority_payload = encode_owner_tenant_authority_v3(authority)
    revocation_payload = encode_owner_tenant_authority_v3_revocation(revocation)

    assert decode_owner_tenant_authority_v3(authority_payload) == authority
    assert decode_owner_tenant_authority_v3_revocation(revocation_payload) == revocation
    assert authority_payload["assignment"] == authority.assignment.to_payload()
    assert authority_payload["policy"] == authority.policy.to_payload()
    assert authority_payload["tenant_id"] == authority.tenant_id
    assert authority_payload["actor_user_id"] == authority.actor_user_id
    assert authority_payload["supersedes_content_hash"] is None
    assert revocation_payload["authority_content_hash"] == authority.content_hash
    assert revocation_payload["policy_content_hash"] == authority.policy.content_hash
    assert issubclass(OwnerTenantAuthorityV3CodecError, ValueError)


def test_v3_successor_roundtrip_preserves_predecessor_binding() -> None:
    """Keep the optional exact predecessor seal in the canonical root payload."""

    successor = _successor(_authority())
    payload = encode_owner_tenant_authority_v3(successor)

    assert payload["supersedes_content_hash"] == successor.supersedes_content_hash
    assert decode_owner_tenant_authority_v3(payload) == successor


def test_v3_codec_rejects_cross_version_root_payloads() -> None:
    """Do not accept V1, V2, or V4 values at the V3 boundary."""

    v3_payload = encode_owner_tenant_authority_v3(_authority())
    v1_payload = encode_owner_tenant_authority_v1(_v1_authority())
    v2_payload = encode_owner_tenant_authority_v2(_v2_authority())
    v4_assignment = encode_account_owner_assignment_evidence_v4(_v4_evidence())

    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(v1_payload)
    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(v2_payload)

    substituted = _copy(v3_payload)
    substituted["assignment"] = v4_assignment
    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(substituted)


def test_v3_root_codec_rejects_missing_and_extra_fields() -> None:
    """Require the root payload to use one exact closed-world key set."""

    payload = encode_owner_tenant_authority_v3(_authority())
    missing = _copy(payload)
    missing.pop("policy")
    extra = _copy(payload)
    extra["unexpected"] = "reject"

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="shape"):
        decode_owner_tenant_authority_v3(missing)
    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="shape"):
        decode_owner_tenant_authority_v3(extra)


def test_v3_revocation_codec_rejects_missing_and_extra_fields() -> None:
    """Require the revocation payload to use one exact closed-world key set."""

    payload = encode_owner_tenant_authority_v3_revocation(_revocation())
    missing = _copy(payload)
    missing.pop("reason")
    extra = _copy(payload)
    extra["unexpected"] = "reject"

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="shape"):
        decode_owner_tenant_authority_v3_revocation(missing)
    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="shape"):
        decode_owner_tenant_authority_v3_revocation(extra)


@pytest.mark.parametrize("field_name", ["activation_available", "must_not_execute"])
def test_v3_root_codec_rejects_integer_execution_flags(field_name: str) -> None:
    """Reject integer truthiness substitutions for fixed execution flags."""

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    payload[field_name] = 0 if field_name == "activation_available" else 1

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="boolean|fixed"):
        decode_owner_tenant_authority_v3(payload)


def test_v3_revocation_codec_rejects_integer_flags_and_actor_user_id() -> None:
    """Reject bool/int substitutions in fixed flags and actor identity."""

    payload = _copy(encode_owner_tenant_authority_v3_revocation(_revocation()))
    payload["activation_available"] = 0
    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="boolean|fixed"):
        decode_owner_tenant_authority_v3_revocation(payload)

    payload = _copy(encode_owner_tenant_authority_v3_revocation(_revocation()))
    revoked_by = _copy(cast(dict[str, object], payload["revoked_by"]))
    revoked_by["user_id"] = True
    payload["revoked_by"] = revoked_by
    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="integer"):
        decode_owner_tenant_authority_v3_revocation(payload)


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
def test_v3_root_codec_requires_nonblank_digest_fields(field_name: str) -> None:
    """Reject blank V3 root seals before Domain defaults can fill them."""

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    payload[field_name] = ""

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="seal"):
        decode_owner_tenant_authority_v3(payload)


def test_v3_root_codec_requires_nonblank_predecessor_seal() -> None:
    """Reject a blank predecessor selector instead of treating it as a root."""

    payload = _copy(encode_owner_tenant_authority_v3(_successor(_authority())))
    payload["supersedes_content_hash"] = ""

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="seal"):
        decode_owner_tenant_authority_v3(payload)


@pytest.mark.parametrize(
    "field_name",
    ["authority_content_hash", "policy_content_hash", "identity_hash", "content_hash"],
)
def test_v3_revocation_codec_requires_nonblank_digest_fields(field_name: str) -> None:
    """Reject blank revocation seals."""

    payload = _copy(encode_owner_tenant_authority_v3_revocation(_revocation()))
    payload[field_name] = ""

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="seal"):
        decode_owner_tenant_authority_v3_revocation(payload)


@pytest.mark.parametrize(
    "field_name",
    ["tenant_id", "owner_id", "account_namespace", "account_id", "actor_id"],
)
def test_v3_root_codec_rejects_derived_scope_substitution(field_name: str) -> None:
    """Require every derived scope value to agree with the sealed V5 graph."""

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    payload[field_name] = "substituted"

    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(payload)


@pytest.mark.parametrize("field_name", ["approved_at", "recorded_at", "valid_until"])
def test_v3_root_codec_rejects_noncanonical_clocks(field_name: str) -> None:
    """Require UTC Z timestamps with explicit microseconds."""

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    text = cast(str, payload[field_name])
    payload[field_name] = text[:-7] + "Z"

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="microseconds|canonical"):
        decode_owner_tenant_authority_v3(payload)


def test_v3_revocation_codec_rejects_noncanonical_clock_timezone() -> None:
    """Do not accept an offset timestamp at the persistence boundary."""

    payload = _copy(encode_owner_tenant_authority_v3_revocation(_revocation()))
    text = cast(str, payload["revoked_at"])
    payload["revoked_at"] = text[:-1] + "+00:00"

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="UTC|canonical"):
        decode_owner_tenant_authority_v3_revocation(payload)


def test_v3_codec_revalidates_nested_v5_evidence_and_policy() -> None:
    """Reject nested Subject/policy tampering before a V3 authority is returned."""

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    policy = _copy(cast(dict[str, object], payload["policy"]))
    policy["account_id"] = "account-substituted"
    payload["policy"] = policy
    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(payload)

    payload = _copy(encode_owner_tenant_authority_v3(_authority()))
    evidence = _copy(cast(dict[str, object], payload["assignment"]))
    evidence["evidence_version"] = "v4"
    payload["assignment"] = evidence
    with pytest.raises(OwnerTenantAuthorityV3CodecError):
        decode_owner_tenant_authority_v3(payload)


def test_v3_encoders_reject_substituted_domain_types() -> None:
    """Keep both encode entry points exact-type and fail closed."""

    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="exact"):
        encode_owner_tenant_authority_v3(cast(OwnerTenantAuthorityV3, object()))
    with pytest.raises(OwnerTenantAuthorityV3CodecError, match="exact"):
        encode_owner_tenant_authority_v3_revocation(
            cast(OwnerTenantAuthorityV3Revocation, object())
        )
