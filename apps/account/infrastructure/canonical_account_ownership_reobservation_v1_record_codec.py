"""Strict persisted envelope for canonical ownership re-observation v1."""

from typing import cast

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_codec import (
    decode_canonical_account_ownership_reobservation_v1,
    encode_canonical_account_ownership_reobservation_v1,
)


class CanonicalAccountOwnershipReobservationV1RecordCodecError(ValueError):
    """A persisted envelope has an altered shape or invalid nested evidence."""


def encode_canonical_account_ownership_reobservation_v1_record(
    value: PersistedCanonicalAccountOwnershipReobservationV1,
) -> dict[str, object]:
    """Encode the complete immutable re-observation record."""

    if type(value) is not PersistedCanonicalAccountOwnershipReobservationV1:
        raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
            "expected exact ownership re-observation record"
        )
    try:
        value.__post_init__()
        return {
            "reobservation": encode_canonical_account_ownership_reobservation_v1(
                value.reobservation
            ),
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "record_seal": value.record_seal,
            "ledger_seal": value.ledger_seal,
        }
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
            "ownership re-observation record cannot be encoded"
        ) from error


def decode_canonical_account_ownership_reobservation_v1_record(
    payload: object,
) -> PersistedCanonicalAccountOwnershipReobservationV1:
    """Decode only the exact envelope and verify a canonical round trip."""

    try:
        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
                "expected an exact JSON object"
            )
        data = cast(dict[str, object], payload)
        if set(data) != {
            "reobservation",
            "identity_hash",
            "content_hash",
            "record_seal",
            "ledger_seal",
        }:
            raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
                "invalid ownership re-observation record shape"
            )
        value = PersistedCanonicalAccountOwnershipReobservationV1(
            reobservation=decode_canonical_account_ownership_reobservation_v1(
                data["reobservation"]
            ),
            identity_hash=_text(data["identity_hash"]),
            content_hash=_text(data["content_hash"]),
            record_seal=_text(data["record_seal"]),
            ledger_seal=_text(data["ledger_seal"]),
        )
        if encode_canonical_account_ownership_reobservation_v1_record(value) != data:
            raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
                "noncanonical ownership re-observation record"
            )
        return value
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CanonicalAccountOwnershipReobservationV1RecordCodecError):
            raise
        raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
            "invalid ownership re-observation record"
        ) from error


def _text(value: object) -> str:
    if type(value) is not str:
        raise CanonicalAccountOwnershipReobservationV1RecordCodecError(
            "record seals must be exact strings"
        )
    return value


__all__ = [
    "CanonicalAccountOwnershipReobservationV1RecordCodecError",
    "decode_canonical_account_ownership_reobservation_v1_record",
    "encode_canonical_account_ownership_reobservation_v1_record",
]
