"""Strict codec coverage for canonical Account creation-consumption claims."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    encode_canonical_account_creation_allocation,
)
from apps.account.infrastructure.canonical_account_creation_consumption_codec import (
    CanonicalAccountCreationConsumptionCodecError,
    decode_canonical_account_creation_consumption_claim,
    encode_canonical_account_creation_consumption_claim,
)
from tests.unit.account.test_canonical_account_creation_consumption import _claim

Consumer = CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2


def _nested(payload: dict[str, object], *path: str) -> dict[str, object]:
    current = payload
    for key in path:
        value = current[key]
        assert type(value) is dict
        current = cast(dict[str, object], value)
    return current


@pytest.mark.parametrize("generation", ["v1", "v2"])
def test_complete_canonical_roundtrip_preserves_allocation_and_exact_consumer_ref(
    generation: str,
) -> None:
    claim = _claim(consumer_generation=generation)

    payload = encode_canonical_account_creation_consumption_claim(claim)
    restored = decode_canonical_account_creation_consumption_claim(
        payload,
        consumer=claim.consumer,
    )

    assert payload == claim.to_payload()
    assert set(payload) == _CLAIM_KEYS
    assert payload["allocation"] == encode_canonical_account_creation_allocation(claim.allocation)
    assert set(_nested(payload, "allocation")) == _ALLOCATION_KEYS
    assert payload["consumer_ref"] == {
        "owner": claim.consumer.owner,
        "artifact_type": claim.consumer.artifact_type,
        "schema": claim.consumer.schema,
        "consumer_id": claim.consumer.binding_id,
        "consumer_version": claim.consumer.binding_version,
        "identity_hash": claim.consumer.identity_hash,
        "content_hash": claim.consumer.content_hash,
    }
    assert set(_nested(payload, "consumer_ref")) == _CONSUMER_REF_KEYS
    assert "consumer" not in payload
    assert payload["recorded_at"] in {
        "2026-08-07T12:00:00Z",
        "2026-08-08T12:00:00Z",
    }
    assert restored == claim
    assert restored.consumer is claim.consumer
    assert encode_canonical_account_creation_consumption_claim(restored) == payload


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("allocation",),
        ("allocation", "requested_by"),
        ("allocation", "recorded_by"),
        ("consumer_ref",),
    ],
)
def test_unknown_and_missing_keys_at_every_boundary_fail_closed(
    path: tuple[str, ...],
) -> None:
    claim = _claim(consumer_generation="v2")
    payload = deepcopy(encode_canonical_account_creation_consumption_claim(claim))
    target = _nested(payload, *path)
    target["unknown"] = True

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )

    payload = deepcopy(encode_canonical_account_creation_consumption_claim(claim))
    target = _nested(payload, *path)
    target.pop(next(iter(target)))
    with pytest.raises(CanonicalAccountCreationConsumptionCodecError):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )


@pytest.mark.parametrize(
    ("path", "field_name", "replacement"),
    [
        ((), "claim_id", 7),
        ((), "underlying_unified_account_id", True),
        ((), "activation_available", 0),
        ((), "must_not_execute", 1),
        (("allocation",), "requested_row_user_id", True),
        (("allocation", "requested_by"), "is_authenticated", 1),
        (("consumer_ref",), "consumer_id", 7),
    ],
)
def test_exact_scalar_types_reject_bool_integer_aliasing(
    path: tuple[str, ...],
    field_name: str,
    replacement: object,
) -> None:
    claim = _claim(consumer_generation="v2")
    payload = deepcopy(encode_canonical_account_creation_consumption_claim(claim))
    _nested(payload, *path)[field_name] = replacement

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )


@pytest.mark.parametrize(
    "clock",
    [
        "2026-08-08T12:00:00+00:00",
        "2026-08-08T12:00:00.000000Z",
        "2026-08-08 12:00:00Z",
    ],
)
def test_recorded_at_requires_exact_utc_z_canonical_form(clock: str) -> None:
    claim = _claim(consumer_generation="v2")
    payload = encode_canonical_account_creation_consumption_claim(claim)
    payload["recorded_at"] = clock

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )


@pytest.mark.parametrize(
    ("path", "field_name", "replacement"),
    [
        (("allocation",), "canonical_account_id", "acct-tampered"),
        (("consumer_ref",), "consumer_id", "consumer-tampered"),
        (("consumer_ref",), "content_hash", "a" * 64),
        ((), "account_id", "acct-tampered"),
        ((), "physical_v2_content_hash", "b" * 64),
        ((), "physical_v3_root_content_hash", "c" * 64),
        ((), "account_claim_hash", "d" * 64),
        ((), "content_hash", "e" * 64),
    ],
)
def test_outer_allocation_consumer_ref_and_seal_tampering_fail_closed(
    path: tuple[str, ...],
    field_name: str,
    replacement: object,
) -> None:
    claim = _claim(consumer_generation="v2")
    payload = deepcopy(encode_canonical_account_creation_consumption_claim(claim))
    _nested(payload, *path)[field_name] = replacement

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )


def test_injected_consumer_must_match_generation_and_exact_reference() -> None:
    v1 = _claim()
    v2 = _claim(consumer_generation="v2")

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError, match="consumer_ref"):
        decode_canonical_account_creation_consumption_claim(
            encode_canonical_account_creation_consumption_claim(v1),
            consumer=v2.consumer,
        )
    with pytest.raises(CanonicalAccountCreationConsumptionCodecError, match="consumer_ref"):
        decode_canonical_account_creation_consumption_claim(
            encode_canonical_account_creation_consumption_claim(v2),
            consumer=v1.consumer,
        )


@pytest.mark.parametrize("payload", [None, [], "claim", 1, True])
def test_non_mapping_payloads_fail_closed(payload: object) -> None:
    claim = _claim()

    with pytest.raises(CanonicalAccountCreationConsumptionCodecError, match="mapping"):
        decode_canonical_account_creation_consumption_claim(
            payload,
            consumer=claim.consumer,
        )


def test_encode_requires_exact_domain_type() -> None:
    with pytest.raises(
        TypeError,
        match="exact CanonicalAccountCreationConsumptionClaim",
    ):
        encode_canonical_account_creation_consumption_claim(  # type: ignore[arg-type]
            cast(object, object())
        )


_CLAIM_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "claim_id",
    "claim_version",
    "allocation",
    "consumer_generation",
    "consumer_ref",
    "account_namespace",
    "account_id",
    "account_claim_hash",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "underlying_claim_hash",
    "physical_v2_content_hash",
    "physical_v3_root_content_hash",
    "recorded_at",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
    "activation_available",
    "must_not_execute",
}
_CONSUMER_REF_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "consumer_id",
    "consumer_version",
    "identity_hash",
    "content_hash",
}
_ALLOCATION_KEYS = {
    "allocation_id",
    "allocation_version",
    "canonical_account_namespace",
    "canonical_account_id",
    "requested_row_user_id",
    "requested_raw_account_type",
    "intended_underlying_unified_account_namespace",
    "request_fingerprint_hash",
    "requested_by",
    "allocated_at",
    "valid_until",
    "recorded_by",
    "identity_hash",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "intended_purpose",
    "permission",
    "status",
}
