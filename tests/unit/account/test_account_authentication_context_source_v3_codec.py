from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_authentication_context_source_v3_codec import (
    AccountAuthenticationContextSourceV3CodecError,
    decode_account_authentication_context_source_v3,
    encode_account_authentication_context_source_v3,
)
from tests.unit.account.test_account_authentication_context_source_v3 import _source


def test_complete_nested_canonical_roundtrip() -> None:
    source = _source()
    payload = encode_account_authentication_context_source_v3(source)

    assert decode_account_authentication_context_source_v3(payload) == source
    assert set(payload["identity"]) == {"source_id", "source_version"}  # type: ignore[arg-type]
    assert set(payload["clock"]) == {"observed_at", "recorded_at", "valid_until"}  # type: ignore[arg-type]
    assert set(payload["chain"]) == {"root_claim_hash", "supersedes_content_hash"}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path",
    [
        ("content_hash",),
        ("principal_seal",),
        ("facts_seal",),
        ("clock_seal",),
        ("chain_seal",),
        ("fixed_authority_seal",),
        ("record_seal",),
        ("identity_hash",),
        ("chain", "root_claim_hash"),
    ],
)
def test_hash_seal_or_nested_root_tamper_fails_closed(path: tuple[str, ...]) -> None:
    payload = deepcopy(encode_account_authentication_context_source_v3(_source()))
    target: dict[str, object] = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = "0" * 64
    with pytest.raises(AccountAuthenticationContextSourceV3CodecError):
        decode_account_authentication_context_source_v3(payload)


@pytest.mark.parametrize("location", ["root", "identity", "clock", "chain"])
def test_unknown_and_missing_nested_shapes_fail_closed(location: str) -> None:
    payload = deepcopy(encode_account_authentication_context_source_v3(_source()))
    target = payload if location == "root" else payload[location]
    target["unknown"] = True  # type: ignore[index]
    with pytest.raises(AccountAuthenticationContextSourceV3CodecError, match="shape"):
        decode_account_authentication_context_source_v3(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", True),
        ("is_authenticated", 1),
        ("must_not_execute", 1),
        ("execution_allowed", 0),
        ("actor_id", 7),
    ],
)
def test_exact_types_reject_bool_integer_and_string_substitution(field: str, value: object) -> None:
    payload = deepcopy(encode_account_authentication_context_source_v3(_source()))
    payload[field] = value
    with pytest.raises(AccountAuthenticationContextSourceV3CodecError):
        decode_account_authentication_context_source_v3(payload)


@pytest.mark.parametrize(
    "value",
    ["2026-08-14T10:00:00Z", "2026-08-14T10:00:00+00:00", "2026-08-14T18:00:00.000000+08:00", 1],
)
def test_noncanonical_time_fails_closed(value: object) -> None:
    payload = deepcopy(encode_account_authentication_context_source_v3(_source()))
    payload["authenticated_at"] = value
    with pytest.raises(AccountAuthenticationContextSourceV3CodecError):
        decode_account_authentication_context_source_v3(payload)


def test_nonmapping_and_encoder_type_fail_closed() -> None:
    with pytest.raises(AccountAuthenticationContextSourceV3CodecError, match="mapping"):
        decode_account_authentication_context_source_v3([])
    with pytest.raises(TypeError):
        encode_account_authentication_context_source_v3(object())  # type: ignore[arg-type]
