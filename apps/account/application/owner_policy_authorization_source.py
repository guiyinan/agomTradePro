"""Validate the declaration document used as a single-owner source package.

The package preserves one explicitly supplied document as base64 bytes and
checks its SHA-256 content digest.  Its declaration is evidence about source
content only: it is not authentication, a completed approval, or an owner,
tenant, or execution grant.  A later publication flow must revalidate the
configured username against the current User/Profile and a real
authentication context.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NoReturn

OWNER_POLICY_AUTHORIZATION_SOURCE_KEY: Final[str] = (
    "account.single_owner_policy.authorization_source"
)
OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION: Final[str] = (
    "account.single_owner_policy.authorization_source.v1"
)
OWNER_POLICY_AUTHORIZATION_SOURCE_DOCUMENT_SCHEMA: Final[str] = (
    "sprint-owner-account-authorization.v1"
)
OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES: Final[int] = 64 * 1024

_SOURCE_KIND: Final[str] = "interactive_user_declaration"
_BINDING_BASIS: Final[str] = "explicit_user_designation"
_OWNER_ROLE: Final[str] = "project_owner_and_human_approver"
_PACKAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "source_id",
        "source_version",
        "content_hash",
        "document_base64",
    }
)


class OwnerPolicyAuthorizationSourceError(ValueError):
    """The source package or declaration document is invalid."""


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    """Require one exact bounded token without coercing external values."""

    if type(value) is not str:
        raise OwnerPolicyAuthorizationSourceError(f"{field_name} must be a bounded canonical token")
    if (
        not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise OwnerPolicyAuthorizationSourceError(f"{field_name} must be a bounded canonical token")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Require one explicit lowercase SHA-256 digest."""

    if type(value) is not str:
        raise OwnerPolicyAuthorizationSourceError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise OwnerPolicyAuthorizationSourceError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    """Require an exact positive integer and reject bool as an ID."""

    if type(value) is not int or value <= 0:
        raise OwnerPolicyAuthorizationSourceError(f"{field_name} must be an exact positive integer")
    return value


def _require_text(value: object, field_name: str) -> str:
    """Require one exact JSON string field."""

    if type(value) is not str:
        raise OwnerPolicyAuthorizationSourceError(f"{field_name} must be an exact string")
    return value


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build one JSON object while rejecting duplicate keys at every level."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OwnerPolicyAuthorizationSourceError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_json_number(value: str) -> NoReturn:
    """Reject Python's non-standard NaN and Infinity JSON extensions."""

    del value
    raise OwnerPolicyAuthorizationSourceError("document contains a non-finite JSON number")


def _mapping(value: object, field_name: str) -> dict[str, object]:
    """Narrow one decoded JSON object without accepting arbitrary mappings."""

    if type(value) is not dict:
        raise OwnerPolicyAuthorizationSourceError(f"{field_name} must be a JSON object")
    return value


def _aware_timestamp(value: object, field_name: str) -> datetime:
    """Parse one aware declaration timestamp without inventing a timezone."""

    text = _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise OwnerPolicyAuthorizationSourceError(
            f"{field_name} must be a valid timezone-aware timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OwnerPolicyAuthorizationSourceError(
            f"{field_name} must be a valid timezone-aware timestamp"
        )
    return parsed


def _decode_document(document_base64: object, content_hash: object) -> bytes:
    """Decode canonical base64, enforce size, hash, UTF-8, and JSON syntax."""

    encoded = _require_text(document_base64, "document_base64")
    if not encoded:
        raise OwnerPolicyAuthorizationSourceError("document_base64 must not be empty")
    try:
        encoded_bytes = encoded.encode("ascii")
        raw = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise OwnerPolicyAuthorizationSourceError(
            "document_base64 must be canonical base64"
        ) from error
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise OwnerPolicyAuthorizationSourceError("document_base64 must be canonical base64")
    if not raw or len(raw) > OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES:
        raise OwnerPolicyAuthorizationSourceError(
            "authorization document size is outside the supported limit"
        )
    expected_hash = _require_digest(content_hash, "content_hash")
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise OwnerPolicyAuthorizationSourceError(
            "content_hash does not match the authorization document"
        )
    try:
        text = raw.decode("utf-8-sig")
        decoded: object = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_nonfinite_json_number,
        )
    except OwnerPolicyAuthorizationSourceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise OwnerPolicyAuthorizationSourceError(
            "authorization document must be valid UTF-8 JSON"
        ) from error
    _validate_document(_mapping(decoded, "authorization document"))
    return raw


def _validate_document(document: dict[str, object]) -> None:
    """Validate only the declaration facts needed by the source contract."""

    if _require_text(document.get("schema"), "document.schema") != (
        OWNER_POLICY_AUTHORIZATION_SOURCE_DOCUMENT_SCHEMA
    ):
        raise OwnerPolicyAuthorizationSourceError("document.schema is unsupported")
    _aware_timestamp(document.get("recorded_at"), "document.recorded_at")

    source = _mapping(document.get("source"), "document.source")
    if _require_text(source.get("kind"), "source.kind") != _SOURCE_KIND:
        raise OwnerPolicyAuthorizationSourceError("source.kind is unsupported")
    answer = _require_text(source.get("account_binding_answer"), "source.account_binding_answer")
    if not answer.strip():
        raise OwnerPolicyAuthorizationSourceError("source.account_binding_answer must be non-empty")

    owner_account = _mapping(document.get("owner_account"), "document.owner_account")
    username = _require_token(
        owner_account.get("username"),
        "owner_account.username",
        maximum=150,
    )
    del username
    _require_positive_integer(owner_account.get("user_id"), "owner_account.user_id")
    if _require_text(owner_account.get("binding_basis"), "owner_account.binding_basis") != (
        _BINDING_BASIS
    ):
        raise OwnerPolicyAuthorizationSourceError("owner_account.binding_basis is unsupported")
    if _require_text(owner_account.get("role"), "owner_account.role") != _OWNER_ROLE:
        raise OwnerPolicyAuthorizationSourceError("owner_account.role is unsupported")


def _document_facts(raw: bytes) -> tuple[str, int, datetime]:
    """Return the three declaration facts exposed by the public source API."""

    try:
        decoded: object = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_nonfinite_json_number,
        )
    except OwnerPolicyAuthorizationSourceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise OwnerPolicyAuthorizationSourceError(
            "authorization document must be valid UTF-8 JSON"
        ) from error
    document = _mapping(decoded, "authorization document")
    _validate_document(document)
    source = _mapping(document["owner_account"], "document.owner_account")
    username = _require_token(source["username"], "owner_account.username", maximum=150)
    declared_user_id = _require_positive_integer(
        source["user_id"],
        "owner_account.user_id",
    )
    declared_at = _aware_timestamp(document["recorded_at"], "document.recorded_at")
    return username, declared_user_id, declared_at


@dataclass(frozen=True, slots=True)
class OwnerPolicyAuthorizationSource:
    """Immutable raw declaration package with no authentication conclusion."""

    source_id: str
    source_version: str
    content_hash: str
    document_base64: str

    def __post_init__(self) -> None:
        """Validate the explicit package seal and required declaration facts."""

        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _decode_document(self.document_base64, self.content_hash)

    @property
    def schema_version(self) -> str:
        """Return the fixed package schema identifier."""

        return OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION

    @property
    def owner_username(self) -> str:
        """Return the declared username from the preserved source document."""

        raw = _decode_document(self.document_base64, self.content_hash)
        return _document_facts(raw)[0]

    @property
    def declared_user_id(self) -> int:
        """Return the declared user ID without treating it as authenticated."""

        raw = _decode_document(self.document_base64, self.content_hash)
        return _document_facts(raw)[1]

    @property
    def declared_at(self) -> datetime:
        """Return the declaration recording time from the preserved document."""

        raw = _decode_document(self.document_base64, self.content_hash)
        return _document_facts(raw)[2]

    def to_payload(self) -> dict[str, object]:
        """Return the complete closed five-field source package."""

        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "document_base64": self.document_base64,
        }


def decode_owner_policy_authorization_source(
    value: object,
) -> OwnerPolicyAuthorizationSource:
    """Decode one exact five-field source package without filling defaults."""

    if type(value) is not dict:
        raise OwnerPolicyAuthorizationSourceError(
            "authorization source package must be an exact JSON object"
        )
    if set(value) != _PACKAGE_KEYS:
        raise OwnerPolicyAuthorizationSourceError(
            "authorization source package fields are incomplete or unknown"
        )
    schema_version = _require_text(value["schema_version"], "schema_version")
    if schema_version != OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION:
        raise OwnerPolicyAuthorizationSourceError("schema_version is unsupported")
    source_id = _require_token(value["source_id"], "source_id")
    source_version = _require_token(value["source_version"], "source_version")
    content_hash = _require_digest(value["content_hash"], "content_hash")
    document_base64 = _require_text(value["document_base64"], "document_base64")
    return OwnerPolicyAuthorizationSource(
        source_id=source_id,
        source_version=source_version,
        content_hash=content_hash,
        document_base64=document_base64,
    )


__all__ = [
    "OWNER_POLICY_AUTHORIZATION_SOURCE_DOCUMENT_SCHEMA",
    "OWNER_POLICY_AUTHORIZATION_SOURCE_KEY",
    "OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES",
    "OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION",
    "OwnerPolicyAuthorizationSource",
    "OwnerPolicyAuthorizationSourceError",
    "decode_owner_policy_authorization_source",
]
