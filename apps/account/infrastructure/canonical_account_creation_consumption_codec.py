"""Strict canonical codec for Account creation-consumption claims."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
)

CanonicalAccountCreationConsumer = (
    CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2
)


class CanonicalAccountCreationConsumptionCodecError(ValueError):
    """A creation-consumption claim payload is malformed or non-canonical."""


def encode_canonical_account_creation_consumption_claim(
    value: CanonicalAccountCreationConsumptionClaim,
) -> dict[str, object]:
    """Encode one complete claim with its allocation and exact consumer reference."""

    if type(value) is not CanonicalAccountCreationConsumptionClaim:
        raise TypeError("value must be exact CanonicalAccountCreationConsumptionClaim")
    CanonicalAccountCreationConsumptionClaim.__post_init__(value)
    return value.to_payload()


def decode_canonical_account_creation_consumption_claim(
    payload: object,
    *,
    consumer: CanonicalAccountCreationConsumer,
) -> CanonicalAccountCreationConsumptionClaim:
    """Decode a claim after its exact referenced consumer has been loaded."""

    data = _mapping(payload, "consumption claim")
    _exact_keys(data, _CLAIM_KEYS, "consumption claim")
    try:
        allocation = decode_canonical_account_creation_allocation(data["allocation"])
        _validate_consumer_ref(data["consumer_ref"], consumer)
        _fixed_boolean(data["activation_available"], False, "activation_available")
        _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
        value = CanonicalAccountCreationConsumptionClaim(
            claim_id=_string(data["claim_id"]),
            claim_version=_string(data["claim_version"]),
            allocation=allocation,
            consumer_generation=_string(data["consumer_generation"]),
            consumer=consumer,
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            underlying_unified_account_namespace=_string(
                data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(data["underlying_unified_account_id"]),
            physical_v2_content_hash=_string(data["physical_v2_content_hash"]),
            physical_v3_root_content_hash=_optional_string(data["physical_v3_root_content_hash"]),
            recorded_at=_datetime(data["recorded_at"]),
            account_claim_hash=_string(data["account_claim_hash"]),
            underlying_claim_hash=_string(data["underlying_claim_hash"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
        )
    except (
        CanonicalAccountCreationConsumptionCodecError,
        CanonicalAccountCreationCodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, CanonicalAccountCreationConsumptionCodecError):
            raise
        raise CanonicalAccountCreationConsumptionCodecError(
            "creation-consumption claim payload is invalid"
        ) from error
    if encode_canonical_account_creation_consumption_claim(value) != payload:
        raise CanonicalAccountCreationConsumptionCodecError(
            "creation-consumption claim payload is non-canonical"
        )
    return value


def _validate_consumer_ref(
    payload: object,
    consumer: CanonicalAccountCreationConsumer,
) -> None:
    data = _mapping(payload, "consumer_ref")
    _exact_keys(data, _CONSUMER_REF_KEYS, "consumer_ref")
    for field_name in _CONSUMER_REF_KEYS:
        _string(data[field_name])
    if type(consumer) not in {
        CanonicalAccountCreationBinding,
        CanonicalAccountCreationBindingV2,
    }:
        raise CanonicalAccountCreationConsumptionCodecError(
            "consumer must be an exact canonical creation binding"
        )
    consumer.__post_init__()
    expected: dict[str, object] = {
        "owner": consumer.owner,
        "artifact_type": consumer.artifact_type,
        "schema": consumer.schema,
        "consumer_id": consumer.binding_id,
        "consumer_version": consumer.binding_version,
        "identity_hash": consumer.identity_hash,
        "content_hash": consumer.content_hash,
    }
    if data != expected:
        raise CanonicalAccountCreationConsumptionCodecError(
            "consumer_ref does not match the exact consumer"
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


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise CanonicalAccountCreationConsumptionCodecError(
            f"{field_name} must be an exact mapping"
        )
    return cast(dict[str, object], value)


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise CanonicalAccountCreationConsumptionCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise CanonicalAccountCreationConsumptionCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise CanonicalAccountCreationConsumptionCodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise CanonicalAccountCreationConsumptionCodecError("expected an exact boolean")
    return value


def _fixed_boolean(value: object, expected: bool, field_name: str) -> None:
    if _boolean(value) is not expected:
        raise CanonicalAccountCreationConsumptionCodecError(f"{field_name} is fixed")


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise CanonicalAccountCreationConsumptionCodecError(
            "datetime must use canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise CanonicalAccountCreationConsumptionCodecError("datetime is invalid") from error
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise CanonicalAccountCreationConsumptionCodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "CanonicalAccountCreationConsumptionCodecError",
    "decode_canonical_account_creation_consumption_claim",
    "encode_canonical_account_creation_consumption_claim",
]
