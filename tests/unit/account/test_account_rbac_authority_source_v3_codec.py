from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_rbac_authority_source_v3_codec import (
    AccountRbacAuthoritySourceV3CodecError,
    decode_account_rbac_authority_source_v3,
    encode_account_rbac_authority_source_v3,
)
from tests.unit.account.test_account_rbac_authority_source_v3 import _source


def _payload() -> dict[str, object]:
    return encode_account_rbac_authority_source_v3(_source())


def _nested(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    assert type(value) is dict
    return value


def test_roundtrip_preserves_complete_nested_source_and_microsecond_z_clock() -> None:
    source = _source()

    payload = encode_account_rbac_authority_source_v3(source)

    assert decode_account_rbac_authority_source_v3(payload) == source
    assert _nested(payload, "identity") == {
        "source_id": source.identity.source_id,
        "source_version": source.identity.source_version,
    }
    assert _nested(payload, "chain") == {
        "root_claim_hash": source.chain.root_claim_hash,
        "supersedes_content_hash": None,
    }
    assert _nested(payload, "clock")["recorded_at"] == "2026-08-14T10:00:00.000000Z"


@pytest.mark.parametrize("operation", ["unknown", "missing"])
@pytest.mark.parametrize("container", ["source", "identity", "clock", "chain"])
def test_rejects_unknown_and_missing_keys(operation: str, container: str) -> None:
    payload = deepcopy(_payload())
    target = payload if container == "source" else _nested(payload, container)
    if operation == "unknown":
        target["unexpected"] = "value"
    else:
        target.pop(next(iter(target)))

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("user_id",), True),
        (("user_id",), "41"),
        (("must_not_execute",), 1),
        (("execution_allowed",), 0),
        (("identity", "source_id"), 41),
        (("clock", "recorded_at"), 41),
        (("chain", "root_claim_hash"), False),
    ],
)
def test_rejects_non_exact_scalar_types(path: tuple[str, ...], value: object) -> None:
    payload = deepcopy(_payload())
    if len(path) == 1:
        payload[path[0]] = value
    else:
        _nested(payload, path[0])[path[1]] = value

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-14T10:00:00+00:00",
        "2026-08-14T10:00:00Z",
        "2026-08-14T10:00:00.000000+00:00",
        "2026-08-14 10:00:00.000000Z",
    ],
)
def test_rejects_noncanonical_clock(timestamp: str) -> None:
    payload = deepcopy(_payload())
    _nested(payload, "clock")["recorded_at"] = timestamp

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rbac_role", "administrator"),
        ("rbac_role", " Owner"),
        ("authority_state", "active"),
        ("owner", "rbac"),
        ("artifact_type", "account_rbac_authority_source_v2"),
        ("schema", "account.rbac_authority_source.v2"),
        ("permission", "execute"),
        ("status", "active"),
        ("must_not_execute", False),
        ("execution_allowed", True),
    ],
)
def test_rejects_noncanonical_roles_states_and_fixed_header(field: str, value: object) -> None:
    payload = deepcopy(_payload())
    payload[field] = value

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)


@pytest.mark.parametrize(
    "field",
    [
        "identity_hash",
        "rbac_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ],
)
@pytest.mark.parametrize("tamper", ["wrong_digest", "empty_autofill"])
def test_rejects_all_hash_and_seal_tampering(field: str, tamper: str) -> None:
    payload = deepcopy(_payload())
    payload[field] = "f" * 64 if tamper == "wrong_digest" else ""

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)


def test_rejects_invalid_chain_xor_and_non_mappings() -> None:
    payload = deepcopy(_payload())
    _nested(payload, "chain")["root_claim_hash"] = None

    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3(payload)
    with pytest.raises(AccountRbacAuthoritySourceV3CodecError):
        decode_account_rbac_authority_source_v3([])


def test_encode_requires_exact_domain_type() -> None:
    with pytest.raises(TypeError):
        encode_account_rbac_authority_source_v3(object())  # type: ignore[arg-type]
