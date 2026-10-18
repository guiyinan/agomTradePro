"""Encrypted, bounded codec for non-authorizing calendar preview tokens."""

from __future__ import annotations

import json
import re
from binascii import Error as Base64DecodeError
from datetime import UTC, date, datetime
from typing import NoReturn, cast

from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured

from apps.data_center.application.calendar_preview_token import (
    CALENDAR_PREVIEW_DATABASE_ALIAS,
    CalendarPreviewTokenCodec,
    CalendarPreviewTokenContent,
    CalendarPreviewTokenError,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreviewIdentity,
    ConfirmCalendarPublicationIntent,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)
from shared.config.secrets import get_secrets
from shared.infrastructure.crypto import FieldEncryptionService

PREVIEW_TOKEN_PURPOSE = "calendar-publication-preview-confirmation"
PREVIEW_TOKEN_SCHEMA = "calendar-publication-preview-token.v2"
MAX_PREVIEW_TOKEN_CONTENT_BYTES = 16_384
MAX_PREVIEW_TOKEN_CHARACTERS = 32_768
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ACTOR_USER_ID = (1 << 63) - 1

_TOP_LEVEL_KEYS = frozenset(
    {
        "purpose",
        "schema",
        "actor_user_id",
        "session_key_sha256",
        "database_alias",
        "first_seen_at",
        "previewed_at",
        "response_expires_at",
        "intent",
    }
)
_INTENT_KEYS = frozenset(
    {
        "snapshot_reference",
        "expected_identity",
        "expected_pointer",
        "activation_id",
        "expected_publication_hash",
        "preview_hash",
    }
)
_REFERENCE_KEYS = frozenset(
    {
        "snapshot_id",
        "exchange",
        "coverage_start",
        "coverage_end",
        "content_hash",
        "record_digest",
        "raw_payload_id",
        "raw_payload_hash",
        "raw_record_digest",
    }
)
_IDENTITY_KEYS = frozenset(
    {
        "dataset_key",
        "contract_version",
        "schema_version",
        "policy_identity",
        "policy_version",
        "calendar_response_max_age_seconds",
    }
)
_POINTER_KEYS = frozenset(
    {
        "dataset_key",
        "publication_key",
        "pointer_id",
        "publication_id",
        "publication_hash",
        "activation_id",
        "updated_at",
    }
)


class _DuplicateJsonKeyError(ValueError):
    """Internal signal raised when a JSON object repeats a key."""


class EncryptedCalendarPreviewTokenCodec(CalendarPreviewTokenCodec):
    """Encrypt and validate short-lived calendar preview confirmation contents.

    The codec asks the shared cached secret accessor for the existing
    application field-encryption key on each operation. Key changes become
    visible after the shared cache is cleared or the process restarts. It stores
    neither an old-key ring nor token state; confirmation still requires live
    request authority and fresh publication CAS, TTL, and Audit checks.
    """

    def __init__(self) -> None:
        """Create a stateless codec that resolves keys through the shared cached accessor."""

    def encode(self, content: CalendarPreviewTokenContent) -> str:
        """Return a bounded opaque token for the exact validated preview content."""

        if type(content) is not CalendarPreviewTokenContent:
            _raise_token_error(
                "Preview token input must be the exact content DTO",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        content.validate()
        plaintext = _canonical_json(_content_payload(content))
        encoded = plaintext.encode("utf-8")
        if len(encoded) > MAX_PREVIEW_TOKEN_CONTENT_BYTES:
            _raise_token_error(
                "Preview token content exceeds the technical size limit",
                code="CALENDAR_PREVIEW_TOKEN_TOO_LARGE",
                status_code=413,
            )
        token = _encryption_service().encrypt(plaintext)
        if len(token) > MAX_PREVIEW_TOKEN_CHARACTERS:
            _raise_token_error(
                "Encrypted preview token exceeds the technical size limit",
                code="CALENDAR_PREVIEW_TOKEN_TOO_LARGE",
                status_code=413,
            )
        return token

    def decode(
        self,
        token: str,
        *,
        actor_user_id: int,
        session_key_sha256: str,
        database_alias: str,
        now: datetime,
    ) -> CalendarPreviewTokenContent:
        """Decode only exact, correctly bound contents before their original expiry."""

        _validate_expected_binding(
            actor_user_id=actor_user_id,
            session_key_sha256=session_key_sha256,
            database_alias=database_alias,
        )
        now_utc = _require_utc(now, "now")
        if type(token) is not str or not token:
            _raise_token_error(
                "Preview token must be non-empty text",
                code="CALENDAR_PREVIEW_TOKEN_INVALID",
            )
        if len(token) > MAX_PREVIEW_TOKEN_CHARACTERS:
            _raise_token_error(
                "Preview token exceeds the technical size limit",
                code="CALENDAR_PREVIEW_TOKEN_TOO_LARGE",
                status_code=413,
            )
        if not token.startswith(FieldEncryptionService.PREFIX):
            code = (
                "CALENDAR_PREVIEW_TOKEN_VERSION_UNSUPPORTED"
                if token.startswith("encrypted:")
                else "CALENDAR_PREVIEW_TOKEN_PREFIX_INVALID"
            )
            _raise_token_error(
                "Preview token must use the supported encrypted:v1 format",
                code=code,
            )
        if not token.isascii():
            _raise_token_error(
                "Preview token encoding is invalid",
                code="CALENDAR_PREVIEW_TOKEN_INVALID",
            )
        try:
            plaintext = _encryption_service().decrypt(token, suppress_warning=True)
            plaintext_bytes = plaintext.encode("utf-8")
        except (
            Base64DecodeError,
            InvalidToken,
            UnicodeDecodeError,
            ValueError,
            TypeError,
        ) as error:
            raise CalendarPreviewTokenError(
                "Preview token decryption failed",
                code="CALENDAR_PREVIEW_TOKEN_DECRYPT_FAILED",
            ) from error
        if len(plaintext_bytes) > MAX_PREVIEW_TOKEN_CONTENT_BYTES:
            _raise_token_error(
                "Decrypted preview content exceeds the technical size limit",
                code="CALENDAR_PREVIEW_TOKEN_TOO_LARGE",
                status_code=413,
            )

        payload = _parse_payload(plaintext)
        try:
            content = _content_from_payload(payload)
        except CalendarPreviewTokenError:
            raise
        except (
            AttributeError,
            CalendarPublicationOperationsError,
            TypeError,
            ValueError,
        ) as error:
            raise CalendarPreviewTokenError(
                "Preview token contents are invalid",
                code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
            ) from error
        if (
            content.actor_user_id != actor_user_id
            or content.session_key_sha256 != session_key_sha256
            or content.database_alias != database_alias
        ):
            _raise_token_error(
                "Preview token is bound to a different actor, session, or database",
                code="CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
                status_code=409,
            )
        if now_utc < content.previewed_at:
            _raise_token_error(
                "Server clock precedes the original preview time",
                code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
                status_code=409,
            )
        if now_utc >= content.response_expires_at:
            _raise_token_error(
                "Calendar response-age TTL has expired",
                code="CALENDAR_PREVIEW_TOKEN_EXPIRED",
                status_code=409,
            )
        return content


def _encryption_service() -> FieldEncryptionService:
    """Build a service from the existing env-only secret without settings fallback."""

    try:
        key = get_secrets(require_tushare_token=False).field_encryption_key
    except (OSError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Preview-token encryption key is unavailable",
            code="CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE",
            status_code=503,
        ) from error
    if type(key) is not str or not key.strip():
        _raise_token_error(
            "Preview-token encryption key is unavailable",
            code="CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE",
            status_code=503,
        )
    try:
        return FieldEncryptionService(encryption_key=key)
    except (ImproperlyConfigured, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Preview-token encryption key is invalid",
            code="CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE",
            status_code=503,
        ) from error


def _content_payload(content: CalendarPreviewTokenContent) -> dict[str, object]:
    """Serialize the exact claims with stable field names and UTC text."""

    intent = content.intent
    reference = intent.snapshot_reference
    identity = intent.expected_identity
    pointer = intent.expected_pointer
    return {
        "purpose": PREVIEW_TOKEN_PURPOSE,
        "schema": PREVIEW_TOKEN_SCHEMA,
        "actor_user_id": content.actor_user_id,
        "session_key_sha256": content.session_key_sha256,
        "database_alias": content.database_alias,
        "first_seen_at": _format_utc(content.first_seen_at),
        "previewed_at": _format_utc(content.previewed_at),
        "response_expires_at": _format_utc(content.response_expires_at),
        "intent": {
            "snapshot_reference": reference.to_payload(),
            "expected_identity": {
                "dataset_key": identity.dataset_key,
                "contract_version": identity.contract_version,
                "schema_version": identity.schema_version,
                "policy_identity": identity.policy_identity,
                "policy_version": identity.policy_version,
                "calendar_response_max_age_seconds": identity.calendar_response_max_age_seconds,
            },
            "expected_pointer": {
                "dataset_key": pointer.dataset_key,
                "publication_key": pointer.publication_key,
                "pointer_id": pointer.pointer_id,
                "publication_id": pointer.publication_id,
                "publication_hash": pointer.publication_hash,
                "activation_id": pointer.activation_id,
                "updated_at": _format_utc(pointer.updated_at) if pointer.updated_at else None,
            },
            "activation_id": intent.activation_id,
            "expected_publication_hash": intent.expected_publication_hash,
            "preview_hash": intent.preview_hash,
        },
    }


def _content_from_payload(payload: dict[str, object]) -> CalendarPreviewTokenContent:
    """Reconstruct the complete typed intent without coercing wire values."""

    root = _require_object(payload, _TOP_LEVEL_KEYS, "token payload")
    purpose = _expect_text(root["purpose"], "purpose")
    if purpose != PREVIEW_TOKEN_PURPOSE:
        _raise_token_error(
            "Preview token purpose is unsupported",
            code="CALENDAR_PREVIEW_TOKEN_PURPOSE_UNSUPPORTED",
        )
    if root["schema"] != PREVIEW_TOKEN_SCHEMA:
        _raise_token_error(
            "Preview token schema version is unsupported",
            code="CALENDAR_PREVIEW_TOKEN_VERSION_UNSUPPORTED",
        )
    actor_user_id = _expect_int(root["actor_user_id"], "actor_user_id")
    session_key_sha256 = _expect_text(root["session_key_sha256"], "session_key_sha256")
    database_alias = _expect_text(root["database_alias"], "database_alias")
    first_seen_at = _parse_utc(root["first_seen_at"], "first_seen_at")
    previewed_at = _parse_utc(root["previewed_at"], "previewed_at")
    response_expires_at = _parse_utc(root["response_expires_at"], "response_expires_at")
    intent_payload = _require_object(root["intent"], _INTENT_KEYS, "intent")

    reference_payload = _require_object(
        intent_payload["snapshot_reference"], _REFERENCE_KEYS, "snapshot_reference"
    )
    reference = ExchangeCalendarSnapshotReference(
        snapshot_id=_expect_text(reference_payload["snapshot_id"], "snapshot_id"),
        exchange=_expect_text(reference_payload["exchange"], "exchange"),
        coverage_start=_parse_date(reference_payload["coverage_start"], "coverage_start"),
        coverage_end=_parse_date(reference_payload["coverage_end"], "coverage_end"),
        content_hash=_expect_text(reference_payload["content_hash"], "content_hash"),
        record_digest=_expect_text(reference_payload["record_digest"], "record_digest"),
        raw_payload_id=_expect_text(reference_payload["raw_payload_id"], "raw_payload_id"),
        raw_payload_hash=_expect_text(reference_payload["raw_payload_hash"], "raw_payload_hash"),
        raw_record_digest=_expect_text(reference_payload["raw_record_digest"], "raw_record_digest"),
    )
    identity_payload = _require_object(
        intent_payload["expected_identity"], _IDENTITY_KEYS, "expected_identity"
    )
    identity = CalendarPublicationPreviewIdentity(
        dataset_key=_expect_text(identity_payload["dataset_key"], "dataset_key"),
        contract_version=_expect_text(identity_payload["contract_version"], "contract_version"),
        schema_version=_expect_text(identity_payload["schema_version"], "schema_version"),
        policy_identity=_expect_text(identity_payload["policy_identity"], "policy_identity"),
        policy_version=_expect_text(identity_payload["policy_version"], "policy_version"),
        calendar_response_max_age_seconds=_expect_int(
            identity_payload["calendar_response_max_age_seconds"],
            "calendar_response_max_age_seconds",
        ),
    )
    pointer_payload = _require_object(
        intent_payload["expected_pointer"], _POINTER_KEYS, "expected_pointer"
    )
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=_expect_text(pointer_payload["dataset_key"], "pointer.dataset_key"),
        publication_key=_expect_text(pointer_payload["publication_key"], "publication_key"),
        pointer_id=_expect_optional_text(pointer_payload["pointer_id"], "pointer_id"),
        publication_id=_expect_optional_text(pointer_payload["publication_id"], "publication_id"),
        publication_hash=_expect_optional_text(
            pointer_payload["publication_hash"], "publication_hash"
        ),
        activation_id=_expect_optional_text(pointer_payload["activation_id"], "activation_id"),
        updated_at=(
            _parse_utc(pointer_payload["updated_at"], "pointer.updated_at")
            if pointer_payload["updated_at"] is not None
            else None
        ),
    )
    intent = ConfirmCalendarPublicationIntent(
        snapshot_reference=reference,
        expected_identity=identity,
        expected_pointer=pointer,
        activation_id=_expect_text(intent_payload["activation_id"], "activation_id"),
        expected_publication_hash=_expect_text(
            intent_payload["expected_publication_hash"], "expected_publication_hash"
        ),
        preview_hash=_expect_text(intent_payload["preview_hash"], "preview_hash"),
    )
    try:
        return CalendarPreviewTokenContent(
            intent=intent,
            actor_user_id=actor_user_id,
            session_key_sha256=session_key_sha256,
            database_alias=database_alias,
            first_seen_at=first_seen_at,
            previewed_at=previewed_at,
            response_expires_at=response_expires_at,
        )
    except CalendarPreviewTokenError as error:
        raise CalendarPreviewTokenError(
            "Preview token contents are invalid",
            code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
        ) from error


def _parse_payload(plaintext: str) -> dict[str, object]:
    """Decode canonical duplicate-free JSON with no floating-point values."""

    try:
        parsed: object = cast(
            object,
            json.loads(
                plaintext,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
                parse_float=_reject_json_float,
            ),
        )
    except (
        _DuplicateJsonKeyError,
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as error:
        raise CalendarPreviewTokenError(
            "Preview token JSON is invalid",
            code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
        ) from error
    payload = _require_object(parsed, _TOP_LEVEL_KEYS, "token payload")
    if _canonical_json(payload) != plaintext:
        _raise_json_error("Preview token JSON is not canonical")
    return payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object only when its key list contains no duplicates."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError("duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    """Reject non-standard NaN and Infinity JSON literals."""

    raise ValueError(f"unsupported JSON constant: {value}")


def _reject_json_float(value: str) -> NoReturn:
    """Reject floating-point JSON tokens because the schema has no float fields."""

    raise ValueError(f"unsupported JSON number: {value}")


def _require_object(
    value: object,
    expected_keys: frozenset[str],
    field_name: str,
) -> dict[str, object]:
    """Require an object with exactly the expected string keys."""

    if type(value) is not dict:
        _raise_json_error(f"Preview token {field_name} must be a JSON object")
    untyped = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in untyped.items():
        if type(key) is not str:
            _raise_json_error(f"Preview token {field_name} has an invalid object key")
        result[key] = item
    if frozenset(result) != expected_keys:
        _raise_json_error(f"Preview token {field_name} has missing or unknown fields")
    return result


def _expect_text(value: object, field_name: str) -> str:
    """Require exact JSON string type without trimming or normalization."""

    if type(value) is not str:
        _raise_json_error(f"Preview token {field_name} must be text")
    return value


def _expect_optional_text(value: object, field_name: str) -> str | None:
    """Require either exact JSON string text or a JSON null value."""

    if value is None:
        return None
    return _expect_text(value, field_name)


def _expect_int(value: object, field_name: str) -> int:
    """Require exact JSON integer type and reject booleans."""

    if type(value) is not int:
        _raise_json_error(f"Preview token {field_name} must be an integer")
    return value


def _parse_date(value: object, field_name: str) -> date:
    """Parse a canonical ISO date without accepting a datetime or alternate form."""

    text = _expect_text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} is invalid",
            code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
        ) from error
    if parsed.isoformat() != text:
        _raise_json_error(f"Preview token {field_name} is not canonical")
    return parsed


def _parse_utc(value: object, field_name: str) -> datetime:
    """Parse only canonical UTC timestamps with a trailing ``Z`` marker."""

    text = _expect_text(value, field_name)
    if not text.endswith("Z"):
        _raise_json_error(f"Preview token {field_name} must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
    except ValueError as error:
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} is invalid",
            code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
        ) from error
    if _format_utc(parsed) != text:
        _raise_json_error(f"Preview token {field_name} is not canonical")
    return parsed


def _format_utc(value: datetime) -> str:
    """Format an aware UTC datetime without dropping its microsecond precision."""

    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Preview token time is invalid",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        ) from error
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
    ):
        _raise_token_error(
            "Preview token time must be aware UTC",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an exact aware UTC datetime at the codec boundary."""

    if type(value) is not datetime or value.tzinfo is None:
        _raise_token_error(
            f"Preview token {field_name} must be an aware UTC datetime",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        )
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} must be an aware UTC datetime",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        ) from error
    if offset is None or offset.total_seconds() != 0:
        _raise_token_error(
            f"Preview token {field_name} must use UTC",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        )
    return value.astimezone(UTC)


def _canonical_json(payload: dict[str, object]) -> str:
    """Serialize exactly with sorted keys, compact separators, and finite values."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Preview token contents cannot be canonically encoded",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        ) from error


def _validate_expected_binding(
    *,
    actor_user_id: int,
    session_key_sha256: str,
    database_alias: str,
) -> None:
    """Reject caller binding inputs outside the exact owner/session/default scope."""

    if (
        type(actor_user_id) is not int
        or actor_user_id < 1
        or actor_user_id > _MAX_ACTOR_USER_ID
        or type(session_key_sha256) is not str
        or _SHA256_RE.fullmatch(session_key_sha256) is None
        or type(database_alias) is not str
        or database_alias != CALENDAR_PREVIEW_DATABASE_ALIAS
    ):
        _raise_token_error(
            "Expected preview-token binding is invalid",
            code="CALENDAR_PREVIEW_TOKEN_BINDING_INVALID",
        )


def _raise_json_error(message: str) -> NoReturn:
    """Raise one stable error for a malformed or non-canonical JSON payload."""

    _raise_token_error(message, code="CALENDAR_PREVIEW_TOKEN_JSON_INVALID")


def _raise_token_error(
    message: str,
    *,
    code: str,
    status_code: int = 400,
) -> NoReturn:
    """Raise a token error without attaching secret or caller-provided material."""

    raise CalendarPreviewTokenError(message, code=code, status_code=status_code)
