"""Persisted re-observation seals must survive exact, hostile JSON round trips."""

from copy import deepcopy
from typing import cast

import pytest

from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_codec import (
    CanonicalAccountOwnershipReobservationV1CodecError,
    decode_canonical_account_ownership_reobservation_v1,
    encode_canonical_account_ownership_reobservation_v1,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import _reobservation


def test_roundtrip_preserves_expired_binding_and_current_physical_seals() -> None:
    value = _reobservation()
    payload = encode_canonical_account_ownership_reobservation_v1(value)
    restored = decode_canonical_account_ownership_reobservation_v1(deepcopy(payload))
    assert restored == value
    assert restored.binding.to_payload() == value.binding.to_payload()
    assert restored.current_physical.to_payload() == value.current_physical.to_payload()
    assert restored.activation_available is False
    assert restored.must_not_execute is True


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("identity_hash", ""),
        ("content_hash", ""),
        ("content_hash", "A" * 64),
        ("content_hash", "a" * 64),
        ("observation_version", True),
        ("activation_available", 0),
        ("must_not_execute", 1),
        ("status", "active"),
        ("permission", "execute"),
        ("schema", "canonical-account-ownership-reobservation.v2"),
        ("recorded_at", "2026-08-10T12:00:00Z"),
        ("recorded_at", "2026-08-10T20:00:00.000000+08:00"),
        ("valid_until", "2026-08-12T12:00:00"),
    ],
)
def test_rejects_changed_fields(field: str, replacement: object) -> None:
    payload = _reobservation().to_payload()
    payload[field] = replacement
    with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
        decode_canonical_account_ownership_reobservation_v1(payload)


@pytest.mark.parametrize("nested", ["binding", "current_physical"])
@pytest.mark.parametrize("field", ["identity_hash", "content_hash"])
def test_rejects_missing_nested_seals(nested: str, field: str) -> None:
    payload = _reobservation().to_payload()
    cast(dict[str, object], payload[nested])[field] = ""
    with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
        decode_canonical_account_ownership_reobservation_v1(payload)


@pytest.mark.parametrize("replacement", [True, 99])
def test_rejects_nested_physical_user_substitution(replacement: object) -> None:
    payload = _reobservation().to_payload()
    cast(dict[str, object], payload["current_physical"])["row_user_id"] = replacement
    with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
        decode_canonical_account_ownership_reobservation_v1(payload)


def test_rejects_unknown_or_missing_keys() -> None:
    original = _reobservation().to_payload()
    for key in original:
        payload = deepcopy(original)
        del payload[key]
        with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
            decode_canonical_account_ownership_reobservation_v1(payload)
    original["extra"] = None
    with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
        decode_canonical_account_ownership_reobservation_v1(original)


@pytest.mark.parametrize("payload", [None, [], "{}", {1: "value"}])
def test_rejects_non_json_object_shape(payload: object) -> None:
    with pytest.raises(CanonicalAccountOwnershipReobservationV1CodecError):
        decode_canonical_account_ownership_reobservation_v1(payload)
