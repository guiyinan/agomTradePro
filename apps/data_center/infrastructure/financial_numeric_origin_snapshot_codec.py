"""Strict JSON codec for immutable financial numeric source-origin snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import TypeGuard, cast
from uuid import UUID

from apps.data_center.application.statutory_source_catalog import (
    decode_statutory_source_catalog_profile,
)
from apps.data_center.domain.financial_numeric_origin_snapshot import (
    FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA,
    FinancialNumericOriginProviderFacts,
    FinancialNumericOriginPublisherFacts,
    FinancialNumericSourceOriginSnapshot,
    origin_snapshot_sha256,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from core.exceptions import DataValidationError

_SNAPSHOT_FIELDS = frozenset(
    {
        "schema",
        "snapshot_id",
        "recorded_at",
        "numeric_capture",
        "provider",
        "publisher",
        "profile",
        "profile_content_sha256",
        "selected_rule_index",
        "configuration_sha256",
    }
)
_CAPTURE_FIELDS = frozenset({"reference", "dataset_key", "deployment_region"})
_PROVIDER_FIELDS = frozenset({"provider_id", "name", "source_type", "is_active", "updated_at"})
_PUBLISHER_FIELDS = frozenset(
    {"code", "canonical_name", "publisher_class", "website", "is_active", "updated_at"}
)


class FinancialNumericOriginSnapshotCodecError(DataValidationError):
    """Stored origin snapshot is missing, malformed, or fails its exact digest."""

    default_message = "Financial numeric origin snapshot is unavailable or invalid."
    default_code = "FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_INVALID"


def _invalid(message: str) -> FinancialNumericOriginSnapshotCodecError:
    """Return a stable codec failure without echoing JSON payload values."""

    return FinancialNumericOriginSnapshotCodecError(message)


def _object(value: object, *, fields: frozenset[str], name: str) -> dict[str, object]:
    """Require one exact JSON object with all and only declared string keys."""

    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise _invalid(f"{name} must be a JSON object")
    result = cast(dict[str, object], value)
    if frozenset(result) != fields:
        raise _invalid(f"{name} has missing or unknown fields")
    return result


def _string(value: object, *, name: str) -> str:
    """Require an exact JSON string."""

    if type(value) is not str:
        raise _invalid(f"{name} must be text")
    return value


def _exact_int(value: object, *, name: str) -> int:
    """Require an exact JSON integer, rejecting booleans and floats."""

    if type(value) is not int:
        raise _invalid(f"{name} must be an integer")
    return value


def _exact_bool(value: object, *, name: str) -> bool:
    """Require an exact JSON boolean."""

    if type(value) is not bool:
        raise _invalid(f"{name} must be a boolean")
    return value


def _instant(value: object, *, name: str) -> datetime:
    """Decode one exact canonical aware UTC ISO datetime."""

    text = _string(value, name=name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _invalid(f"{name} must be an aware UTC ISO datetime") from error
    offset = parsed.utcoffset()
    if (
        parsed.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
        or parsed.isoformat() != text
    ):
        raise _invalid(f"{name} must be a canonical aware UTC ISO datetime")
    return parsed


def _uuid(value: object, *, name: str) -> UUID:
    """Decode one canonical lowercase hyphenated UUID string."""

    text = _string(value, name=name)
    try:
        parsed = UUID(text)
    except (ValueError, AttributeError) as error:
        raise _invalid(f"{name} must be a canonical UUID") from error
    if str(parsed) != text:
        raise _invalid(f"{name} must be a canonical lowercase UUID")
    return parsed


def _is_string_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow the exact object shape accepted by the statutory catalog decoder."""

    return type(value) is dict and all(
        type(key) is str for key in cast(dict[object, object], value)
    )


def encode_origin_snapshot(
    snapshot: FinancialNumericSourceOriginSnapshot,
) -> tuple[dict[str, object], str]:
    """Encode one validated snapshot and its canonical content digest."""

    if type(snapshot) is not FinancialNumericSourceOriginSnapshot:
        raise TypeError("snapshot must use the exact origin snapshot Domain type")
    payload = snapshot.to_payload()
    return payload, origin_snapshot_sha256(payload)


def decode_origin_snapshot(
    value: object,
    digest: object,
) -> FinancialNumericSourceOriginSnapshot:
    """Decode and verify an exact origin snapshot without live-config fallback."""

    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise _invalid("origin snapshot digest must be lowercase SHA-256")
    payload = _object(value, fields=_SNAPSHOT_FIELDS, name="origin snapshot")
    if origin_snapshot_sha256(payload) != digest:
        raise _invalid("origin snapshot digest does not match its stored payload")
    if _string(payload["schema"], name="schema") != FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA:
        raise _invalid("origin snapshot schema is unsupported")
    capture_payload = _object(
        payload["numeric_capture"], fields=_CAPTURE_FIELDS, name="numeric_capture"
    )
    provider_payload = _object(payload["provider"], fields=_PROVIDER_FIELDS, name="provider")
    publisher_payload = _object(payload["publisher"], fields=_PUBLISHER_FIELDS, name="publisher")
    profile_payload = payload["profile"]
    if not _is_string_object(profile_payload):
        raise _invalid("profile must be an exact JSON object")
    try:
        profile = decode_statutory_source_catalog_profile(profile_payload)
        capture_reference = FinancialNumericSourceDocumentCaptureReference.from_payload(
            capture_payload["reference"]
        )
        snapshot = FinancialNumericSourceOriginSnapshot(
            snapshot_id=_uuid(payload["snapshot_id"], name="snapshot_id"),
            recorded_at=_instant(payload["recorded_at"], name="recorded_at"),
            capture_reference=capture_reference,
            dataset_key=_string(capture_payload["dataset_key"], name="dataset_key"),
            deployment_region=_string(
                capture_payload["deployment_region"], name="deployment_region"
            ),
            provider=FinancialNumericOriginProviderFacts(
                provider_id=_exact_int(provider_payload["provider_id"], name="provider_id"),
                name=_string(provider_payload["name"], name="provider.name"),
                source_type=_string(provider_payload["source_type"], name="provider.source_type"),
                is_active=_exact_bool(provider_payload["is_active"], name="provider.is_active"),
                updated_at=_instant(provider_payload["updated_at"], name="provider.updated_at"),
            ),
            publisher=FinancialNumericOriginPublisherFacts(
                code=_string(publisher_payload["code"], name="publisher.code"),
                canonical_name=_string(
                    publisher_payload["canonical_name"], name="publisher.canonical_name"
                ),
                publisher_class=_string(
                    publisher_payload["publisher_class"], name="publisher.publisher_class"
                ),
                website=_string(publisher_payload["website"], name="publisher.website"),
                is_active=_exact_bool(publisher_payload["is_active"], name="publisher.is_active"),
                updated_at=_instant(publisher_payload["updated_at"], name="publisher.updated_at"),
            ),
            profile=profile,
            selected_rule_index=_exact_int(
                payload["selected_rule_index"], name="selected_rule_index"
            ),
            configuration_sha256=_string(
                payload["configuration_sha256"], name="configuration_sha256"
            ),
        )
    except (DataValidationError, TypeError, ValueError) as error:
        if isinstance(error, FinancialNumericOriginSnapshotCodecError):
            raise
        raise _invalid("origin snapshot failed strict Domain validation") from error
    if _string(payload["profile_content_sha256"], name="profile_content_sha256") != (
        snapshot.profile_content_sha256
    ):
        raise _invalid("profile content digest differs from the decoded full profile")
    if snapshot.to_payload() != payload:
        raise _invalid("origin snapshot does not round-trip exactly")
    return snapshot


__all__ = [
    "FinancialNumericOriginSnapshotCodecError",
    "decode_origin_snapshot",
    "encode_origin_snapshot",
]
