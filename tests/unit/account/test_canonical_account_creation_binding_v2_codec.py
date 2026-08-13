"""Strict codec coverage for durable Account creation bindings v2."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    CanonicalAccountCreationBindingV2CodecError,
    decode_canonical_account_creation_binding_v2,
    encode_canonical_account_creation_binding_v2,
)
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _nested(payload: dict[str, object], *path: str) -> dict[str, object]:
    current = payload
    for key in path:
        value = current[key]
        assert type(value) is dict
        current = cast(dict[str, object], value)
    return current


def test_complete_nested_canonical_roundtrip_preserves_every_upstream_value() -> None:
    binding = _binding()

    payload = encode_canonical_account_creation_binding_v2(binding)
    restored = decode_canonical_account_creation_binding_v2(payload)

    assert payload == binding.to_payload()
    assert payload["recorded_at"] == "2026-08-08T12:00:00Z"
    assert payload["allocation"] == binding.allocation.to_payload() | {
        "identity_hash": binding.allocation.identity_hash,
        "content_hash": binding.allocation.content_hash,
    }
    assert payload["creation_root"] == binding.creation_root.to_payload()
    physical = _nested(payload, "creation_root", "physical_observation")
    assert physical == binding.creation_root.physical_observation.to_payload()
    assert physical["source_content_hash"] == (
        binding.creation_root.physical_observation.source_content_hash
    )
    assert physical["raw_observation_content_hash"] == (
        binding.creation_root.physical_observation.raw_observation_content_hash
    )
    assert restored == binding
    assert restored.allocation == binding.allocation
    assert restored.creation_root == binding.creation_root
    assert restored.creation_root.physical_observation == (
        binding.creation_root.physical_observation
    )
    assert encode_canonical_account_creation_binding_v2(restored) == payload


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("allocation",),
        ("recorded_by",),
        ("creation_root",),
        ("creation_root", "allocation"),
        ("creation_root", "physical_observation"),
    ],
)
def test_unknown_keys_at_every_nested_boundary_fail_closed(path: tuple[str, ...]) -> None:
    payload = deepcopy(encode_canonical_account_creation_binding_v2(_binding()))
    _nested(payload, *path)["unknown"] = True

    with pytest.raises(CanonicalAccountCreationBindingV2CodecError):
        decode_canonical_account_creation_binding_v2(payload)


@pytest.mark.parametrize(
    ("path", "field_name"),
    [
        ((), "binding_id"),
        (("allocation",), "allocation_id"),
        (("recorded_by",), "service_id"),
        (("creation_root",), "observation_id"),
        (("creation_root", "allocation"), "allocation_id"),
        (("creation_root", "physical_observation"), "observation_id"),
    ],
)
def test_missing_keys_at_every_nested_boundary_fail_closed(
    path: tuple[str, ...],
    field_name: str,
) -> None:
    payload = deepcopy(encode_canonical_account_creation_binding_v2(_binding()))
    _nested(payload, *path).pop(field_name)

    with pytest.raises(CanonicalAccountCreationBindingV2CodecError):
        decode_canonical_account_creation_binding_v2(payload)


@pytest.mark.parametrize(
    ("path", "field_name", "replacement"),
    [
        ((), "underlying_unified_account_id_claim", True),
        (("allocation",), "requested_row_user_id", True),
        (("recorded_by",), "is_automated", 1),
        (("creation_root",), "activation_available", 0),
        (("creation_root", "allocation"), "requested_row_user_id", True),
        (("creation_root", "physical_observation"), "row_user_id", True),
        (("creation_root", "physical_observation"), "must_not_execute", 1),
    ],
)
def test_exact_scalar_types_reject_bool_pseudo_integers_and_integer_booleans(
    path: tuple[str, ...],
    field_name: str,
    replacement: object,
) -> None:
    payload = deepcopy(encode_canonical_account_creation_binding_v2(_binding()))
    _nested(payload, *path)[field_name] = replacement

    with pytest.raises(CanonicalAccountCreationBindingV2CodecError):
        decode_canonical_account_creation_binding_v2(payload)


@pytest.mark.parametrize(
    ("path", "field_name"),
    [
        ((), "recorded_at"),
        (("allocation",), "allocated_at"),
        (("creation_root",), "recorded_at"),
        (("creation_root", "allocation"), "allocated_at"),
        (("creation_root", "physical_observation"), "recorded_at"),
    ],
)
@pytest.mark.parametrize(
    "clock",
    [
        "2026-08-08T12:00:00+00:00",
        "2026-08-08T12:00:00.000000Z",
        "2026-08-08 12:00:00Z",
    ],
)
def test_all_nested_clocks_require_exact_utc_z_canonical_form(
    path: tuple[str, ...],
    field_name: str,
    clock: str,
) -> None:
    payload = deepcopy(encode_canonical_account_creation_binding_v2(_binding()))
    _nested(payload, *path)[field_name] = clock

    with pytest.raises(CanonicalAccountCreationBindingV2CodecError):
        decode_canonical_account_creation_binding_v2(payload)


@pytest.mark.parametrize(
    ("path", "field_name", "replacement"),
    [
        ((), "account_id_claim", "acct-tampered"),
        ((), "content_hash", "a" * 64),
        (("allocation",), "canonical_account_id", "acct-tampered"),
        (("creation_root",), "content_hash", "b" * 64),
        (("creation_root", "allocation"), "canonical_account_id", "acct-tampered"),
        (
            ("creation_root", "physical_observation"),
            "account_id",
            "acct-tampered",
        ),
        (
            ("creation_root", "physical_observation"),
            "source_content_hash",
            "c" * 64,
        ),
    ],
)
def test_outer_and_complete_nested_tampering_fails_closed(
    path: tuple[str, ...],
    field_name: str,
    replacement: object,
) -> None:
    payload = deepcopy(encode_canonical_account_creation_binding_v2(_binding()))
    _nested(payload, *path)[field_name] = replacement

    with pytest.raises(CanonicalAccountCreationBindingV2CodecError):
        decode_canonical_account_creation_binding_v2(payload)


@pytest.mark.parametrize("payload", [None, [], "binding", 1, True])
def test_non_mapping_payloads_fail_closed(payload: object) -> None:
    with pytest.raises(CanonicalAccountCreationBindingV2CodecError, match="mapping"):
        decode_canonical_account_creation_binding_v2(payload)


def test_encode_requires_the_exact_domain_type() -> None:
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        encode_canonical_account_creation_binding_v2(cast(object, object()))  # type: ignore[arg-type]
