from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_codec import (
    AccountOwnerAssignmentActorAuthoritySourceV3CodecError,
    decode_account_owner_assignment_actor_authority_source_v3,
    encode_account_owner_assignment_actor_authority_source_v3,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3 import (
    _source,
)


def test_complete_canonical_roundtrip_restores_every_field_and_seal() -> None:
    source = _source()
    payload = encode_account_owner_assignment_actor_authority_source_v3(source)
    restored = decode_account_owner_assignment_actor_authority_source_v3(payload)

    assert restored == source
    assert encode_account_owner_assignment_actor_authority_source_v3(restored) == payload
    assert set(payload) == set(source.__dataclass_fields__)


@pytest.mark.parametrize(
    "field",
    [
        "authentication_context_content_hash",
        "user_source_content_hash",
        "rbac_source_content_hash",
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
    ],
)
def test_tampered_hash_or_seal_fails_closed(field: str) -> None:
    payload = deepcopy(encode_account_owner_assignment_actor_authority_source_v3(_source()))
    payload[field] = "0" * 64

    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3CodecError):
        decode_account_owner_assignment_actor_authority_source_v3(payload)


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_unknown_or_missing_key_fails_closed(mutation: str) -> None:
    payload = deepcopy(encode_account_owner_assignment_actor_authority_source_v3(_source()))
    if mutation == "unknown":
        payload["secret"] = "forbidden"
    else:
        del payload["actor_id"]

    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3CodecError, match="shape"):
        decode_account_owner_assignment_actor_authority_source_v3(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", True),
        ("is_authenticated", 1),
        ("is_staff", 0),
        ("execution_allowed", 0),
        ("source_id", 7),
        ("root_claim_hash", False),
    ],
)
def test_exact_scalar_types_reject_bool_integer_and_string_substitution(
    field: str, value: object
) -> None:
    payload = deepcopy(encode_account_owner_assignment_actor_authority_source_v3(_source()))
    payload[field] = value

    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3CodecError):
        decode_account_owner_assignment_actor_authority_source_v3(payload)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-14T10:00:00+00:00",
        "2026-08-14T10:00:00Z",
        "2026-08-14T18:00:00.000000+08:00",
        1,
    ],
)
def test_noncanonical_datetime_fails_closed(value: object) -> None:
    payload = deepcopy(encode_account_owner_assignment_actor_authority_source_v3(_source()))
    payload["recorded_at"] = value

    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3CodecError):
        decode_account_owner_assignment_actor_authority_source_v3(payload)


def test_nonmapping_and_encoder_type_substitution_fail_closed() -> None:
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3CodecError, match="mapping"):
        decode_account_owner_assignment_actor_authority_source_v3([])
    with pytest.raises(TypeError):
        encode_account_owner_assignment_actor_authority_source_v3(object())  # type: ignore[arg-type]
