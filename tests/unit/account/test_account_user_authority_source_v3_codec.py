from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
    root_claim_hash_for_account_user_authority_source_v3,
)
from apps.account.infrastructure.account_user_authority_source_v3_codec import (
    AccountUserAuthoritySourceV3CodecError,
    decode_account_user_authority_source_v3,
    encode_account_user_authority_source_v3,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _source() -> AccountUserAuthoritySourceV3:
    return AccountUserAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3("django-user-41", "v1"),
        clock=AccountAuthorityRawSourceClockV3(
            NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=2)
        ),
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id="django-user-41", user_id=41, actor_id="django-user:41"
            )
        ),
        user_id=41,
        actor_id="django-user:41",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        authority_state="current",
    )


def _changed(payload: dict[str, object], name: str, value: object) -> dict[str, object]:
    changed = deepcopy(payload)
    changed[name] = value
    return changed


def test_round_trip_preserves_complete_nested_canonical_payload() -> None:
    source = _source()
    payload = encode_account_user_authority_source_v3(source)

    assert decode_account_user_authority_source_v3(payload) == source
    assert payload == source.to_payload()
    assert payload["identity"] == {
        "source_id": "django-user-41",
        "source_version": "v1",
    }
    assert payload["clock"] == {
        "observed_at": "2026-08-14T09:59:00.000000Z",
        "recorded_at": "2026-08-14T10:00:00.000000Z",
        "valid_until": "2026-08-14T12:00:00.000000Z",
    }


@pytest.mark.parametrize("payload", [None, [], "source", 1, True])
def test_decode_rejects_non_exact_top_level_mapping(payload: object) -> None:
    with pytest.raises(AccountUserAuthoritySourceV3CodecError):
        decode_account_user_authority_source_v3(payload)


def test_unknown_missing_and_non_string_keys_fail_closed_at_every_level() -> None:
    payload = encode_account_user_authority_source_v3(_source())
    missing = deepcopy(payload)
    missing.pop("record_seal")
    unknown = {**payload, "secret": "forbidden"}
    non_string = cast(dict[object, object], deepcopy(payload))
    non_string[1] = non_string.pop("user_id")
    nested_unknown = deepcopy(payload)
    cast(dict[str, object], nested_unknown["identity"])["unknown"] = "x"
    nested_missing = deepcopy(payload)
    cast(dict[str, object], nested_missing["chain"]).pop("root_claim_hash")

    for changed in (missing, unknown, non_string, nested_unknown, nested_missing):
        with pytest.raises(AccountUserAuthoritySourceV3CodecError):
            decode_account_user_authority_source_v3(changed)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("user_id", True),
        ("is_active", 1),
        ("is_staff", 0),
        ("is_superuser", "false"),
        ("must_not_execute", 1),
        ("execution_allowed", 0),
    ],
)
def test_bool_integer_and_fixed_type_substitution_fails_closed(name: str, value: object) -> None:
    payload = encode_account_user_authority_source_v3(_source())
    with pytest.raises(AccountUserAuthoritySourceV3CodecError):
        decode_account_user_authority_source_v3(_changed(payload, name, value))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-14T10:00:00Z",
        "2026-08-14T10:00:00.000000+00:00",
        "2026-08-14T18:00:00.000000+08:00",
        "2026-08-14T10:00:00.00000Z",
        "2026-08-14 10:00:00.000000Z",
    ],
)
def test_clock_requires_exact_utc_z_microseconds(timestamp: str) -> None:
    payload = encode_account_user_authority_source_v3(_source())
    changed = deepcopy(payload)
    cast(dict[str, object], changed["clock"])["recorded_at"] = timestamp

    with pytest.raises(AccountUserAuthoritySourceV3CodecError):
        decode_account_user_authority_source_v3(changed)


@pytest.mark.parametrize(
    "name",
    [
        "identity_hash",
        "user_seal",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
    ],
)
def test_hash_and_seal_tampering_fails_domain_revalidation(name: str) -> None:
    payload = encode_account_user_authority_source_v3(_source())
    with pytest.raises(AccountUserAuthoritySourceV3CodecError):
        decode_account_user_authority_source_v3(_changed(payload, name, "f" * 64))


def test_nested_root_hash_and_fixed_header_tampering_fail_closed() -> None:
    payload = encode_account_user_authority_source_v3(_source())
    root_tamper = deepcopy(payload)
    cast(dict[str, object], root_tamper["chain"])["root_claim_hash"] = "a" * 64

    for changed in (
        root_tamper,
        _changed(payload, "owner", "shared"),
        _changed(payload, "permission", "execute"),
        _changed(payload, "status", "active"),
    ):
        with pytest.raises(AccountUserAuthoritySourceV3CodecError):
            decode_account_user_authority_source_v3(changed)


def test_encode_rejects_substituted_type() -> None:
    with pytest.raises(TypeError):
        encode_account_user_authority_source_v3(object())  # type: ignore[arg-type]
