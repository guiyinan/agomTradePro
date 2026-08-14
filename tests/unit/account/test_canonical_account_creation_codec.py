from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
    decode_canonical_account_creation_binding,
    encode_canonical_account_creation_allocation,
    encode_canonical_account_creation_binding,
)
from tests.unit.account.test_canonical_account_creation import _allocation, _binding


def test_allocation_complete_canonical_roundtrip() -> None:
    value = _allocation()
    payload = encode_canonical_account_creation_allocation(value)

    assert payload["requested_by"] == value.requested_by.to_payload()
    assert payload["recorded_by"] == value.recorded_by.to_payload()
    assert payload["identity_hash"] == value.identity_hash
    assert payload["content_hash"] == value.content_hash
    assert payload["allocated_at"] == "2026-08-01T12:00:00Z"
    restored = decode_canonical_account_creation_allocation(payload)
    assert restored == value
    assert encode_canonical_account_creation_allocation(restored) == payload


def test_binding_embeds_complete_allocation_and_physical_canonical_values() -> None:
    value = _binding()
    payload = encode_canonical_account_creation_binding(value)

    assert payload["allocation"] == encode_canonical_account_creation_allocation(value.allocation)
    physical = payload["physical_observation"]
    assert type(physical) is dict
    assert physical["observation_id"] == value.physical_observation.observation_id
    assert physical["source_content_hash"] == value.physical_observation.source_content_hash
    assert physical["raw_observation_content_hash"] == (
        value.physical_observation.raw_observation_content_hash
    )
    assert physical["content_hash"] == value.physical_observation.content_hash
    restored = decode_canonical_account_creation_binding(payload)
    assert restored == value
    assert encode_canonical_account_creation_binding(restored) == payload


@pytest.mark.parametrize("target", ["allocation", "binding"])
def test_unknown_or_missing_keys_fail_closed(target: str) -> None:
    payload = (
        encode_canonical_account_creation_allocation(_allocation())
        if target == "allocation"
        else encode_canonical_account_creation_binding(_binding())
    )
    decoder = (
        decode_canonical_account_creation_allocation
        if target == "allocation"
        else decode_canonical_account_creation_binding
    )
    extra = deepcopy(payload)
    extra["unknown"] = True
    with pytest.raises(CanonicalAccountCreationCodecError, match="shape"):
        decoder(extra)
    missing = deepcopy(payload)
    missing.pop(next(iter(missing)))
    with pytest.raises(CanonicalAccountCreationCodecError, match="shape"):
        decoder(missing)


def test_exact_scalar_types_are_required() -> None:
    allocation = encode_canonical_account_creation_allocation(_allocation())
    allocation["requested_row_user_id"] = True
    with pytest.raises(CanonicalAccountCreationCodecError):
        decode_canonical_account_creation_allocation(allocation)

    binding = encode_canonical_account_creation_binding(_binding())
    binding["underlying_unified_account_id_claim"] = True
    with pytest.raises(CanonicalAccountCreationCodecError):
        decode_canonical_account_creation_binding(binding)


@pytest.mark.parametrize(
    "clock",
    [
        "2026-08-01T12:00:00+00:00",
        "2026-08-01T12:00:00.000000Z",
        "2026-08-01 12:00:00Z",
    ],
)
def test_noncanonical_allocation_clocks_fail_closed(clock: str) -> None:
    payload = encode_canonical_account_creation_allocation(_allocation())
    payload["allocated_at"] = clock
    with pytest.raises(CanonicalAccountCreationCodecError):
        decode_canonical_account_creation_allocation(payload)


def test_nested_allocation_tampering_fails_closed() -> None:
    payload = encode_canonical_account_creation_binding(_binding())
    allocation = payload["allocation"]
    assert type(allocation) is dict
    allocation["canonical_account_id"] = "acct-tampered"
    with pytest.raises(CanonicalAccountCreationCodecError):
        decode_canonical_account_creation_binding(payload)


def test_nested_physical_tampering_fails_closed() -> None:
    payload = encode_canonical_account_creation_binding(_binding())
    physical = payload["physical_observation"]
    assert type(physical) is dict
    physical["account_id"] = "acct-tampered"
    with pytest.raises(CanonicalAccountCreationCodecError, match="physical"):
        decode_canonical_account_creation_binding(payload)


def test_binding_claim_and_seal_tampering_fail_closed() -> None:
    for field_name, replacement in (
        ("account_id_claim", "acct-tampered"),
        ("account_claim_hash", "a" * 64),
        ("content_hash", "b" * 64),
    ):
        payload = encode_canonical_account_creation_binding(_binding())
        payload[field_name] = replacement
        with pytest.raises(CanonicalAccountCreationCodecError):
            decode_canonical_account_creation_binding(payload)


def test_non_mapping_payloads_fail_closed() -> None:
    for payload in (None, [], "allocation"):
        with pytest.raises(CanonicalAccountCreationCodecError, match="mapping"):
            decode_canonical_account_creation_allocation(payload)
        with pytest.raises(CanonicalAccountCreationCodecError, match="mapping"):
            decode_canonical_account_creation_binding(payload)
