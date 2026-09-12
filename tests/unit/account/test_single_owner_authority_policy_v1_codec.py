"""Untrusted policy payloads must preserve exact sealed identity and source time."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    SingleOwnerAuthorityPolicyV1CodecError,
    decode_single_owner_authority_policy_v1,
    encode_single_owner_authority_policy_v1,
)


def _policy():
    observed_at = datetime(2026, 9, 10, 12, tzinfo=UTC)
    return SingleOwnerAuthorityPolicyV1(
        policy_id="owner-policy",
        policy_version="1",
        tenant_id="tenant-a",
        owner_id="owner-a",
        account_namespace="account",
        account_id="account-a",
        owner_user_id=42,
        authorization_content_hash="a" * 64,
        observed_at=observed_at,
        valid_from=observed_at - timedelta(minutes=5),
        valid_until=observed_at + timedelta(hours=1),
    )


def test_canonical_roundtrip_preserves_all_source_facts_and_seals():
    policy = _policy()
    payload = encode_single_owner_authority_policy_v1(policy)
    decoded = decode_single_owner_authority_policy_v1(payload)
    assert decoded == policy
    assert decoded.to_payload() == payload
    assert decoded.observed_at == policy.observed_at
    assert not decoded.is_current_at(policy.observed_at - timedelta(seconds=1))


@pytest.mark.parametrize(
    "key,value",
    [
        ("owner_user_id", True),
        ("owner_user_id", "42"),
        ("identity_hash", ""),
        ("content_hash", None),
        ("content_hash", "0" * 64),
        ("authorization_content_hash", "b" * 64),
        ("tenant_id", "tenant-b"),
        ("mode", "multi_owner"),
        ("observed_at", "2026-09-10T12:00:00Z"),
        ("observed_at", "2026-09-10T20:00:00.000000+08:00"),
        ("valid_until", "2026-09-10T13:00:00.000000"),
    ],
)
def test_wrong_types_noncanonical_clocks_and_tampered_seals_are_rejected(key, value):
    payload = _policy().to_payload()
    payload[key] = value
    with pytest.raises(SingleOwnerAuthorityPolicyV1CodecError):
        decode_single_owner_authority_policy_v1(payload)


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_payload_shape_is_closed(mutation):
    payload = _policy().to_payload()
    if mutation == "extra":
        payload["is_superuser"] = True
    else:
        del payload["authorization_content_hash"]
    with pytest.raises(SingleOwnerAuthorityPolicyV1CodecError):
        decode_single_owner_authority_policy_v1(payload)


def test_string_subclass_is_not_a_canonical_boundary_value():
    class Token(str):
        pass

    payload = _policy().to_payload()
    payload["tenant_id"] = Token("tenant-a")
    with pytest.raises(SingleOwnerAuthorityPolicyV1CodecError):
        decode_single_owner_authority_policy_v1(payload)


def test_encoder_rejects_untyped_policy():
    with pytest.raises(SingleOwnerAuthorityPolicyV1CodecError):
        encode_single_owner_authority_policy_v1(_policy().to_payload())
