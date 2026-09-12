"""Typed settings for publishing one single-owner policy source snapshot.

This value is configuration evidence only.  It does not publish a policy,
authenticate an owner, or grant any owner, tenant, or execution permission.
The configured username remains a server-side lookup hint and must be
revalidated against the real User record by a later Application boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY: Final[str] = (
    "account.single_owner_policy.publication_settings"
)
SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION: Final[str] = (
    "account.single_owner_policy.publication_settings.v1"
)

_SETTINGS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "owner_username",
        "tenant_id",
        "owner_id",
        "authorization_source_id",
        "authorization_source_version",
        "authorization_content_hash",
        "ttl_seconds",
    }
)


class SingleOwnerPolicyPublicationSettingsError(ValueError):
    """The value is not one complete single-owner policy settings snapshot."""


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    """Require one bounded exact token without coercing runtime JSON values."""

    if type(value) is not str:
        raise SingleOwnerPolicyPublicationSettingsError(
            f"{field_name} must be a bounded canonical token"
        )
    if (
        not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise SingleOwnerPolicyPublicationSettingsError(
            f"{field_name} must be a bounded canonical token"
        )
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Require one complete lowercase SHA-256 source-content digest."""

    if type(value) is not str:
        raise SingleOwnerPolicyPublicationSettingsError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SingleOwnerPolicyPublicationSettingsError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _require_ttl_seconds(value: object) -> int:
    """Require a positive exact integer representable as a timedelta."""

    if type(value) is not int or value <= 0:
        raise SingleOwnerPolicyPublicationSettingsError(
            "ttl_seconds must be an exact positive integer"
        )
    try:
        timedelta(seconds=value)
    except OverflowError as error:
        raise SingleOwnerPolicyPublicationSettingsError(
            "ttl_seconds is outside the supported timedelta range"
        ) from error
    return value


def _validate_values(
    *,
    schema_version: object,
    owner_username: object,
    tenant_id: object,
    owner_id: object,
    authorization_source_id: object,
    authorization_source_version: object,
    authorization_content_hash: object,
    ttl_seconds: object,
) -> None:
    """Validate constructor values shared by construction and decoding."""

    if _require_token(schema_version, "schema_version") != (
        SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION
    ):
        raise SingleOwnerPolicyPublicationSettingsError("schema_version is unsupported")
    _require_token(owner_username, "owner_username", maximum=150)
    for field_name, value in (
        ("tenant_id", tenant_id),
        ("owner_id", owner_id),
        ("authorization_source_id", authorization_source_id),
        ("authorization_source_version", authorization_source_version),
    ):
        _require_token(value, field_name)
    _require_digest(authorization_content_hash, "authorization_content_hash")
    _require_ttl_seconds(ttl_seconds)


@dataclass(frozen=True, slots=True)
class SingleOwnerPolicyPublicationSettings:
    """One immutable source configuration snapshot for later policy publication.

    owner_username is a server-side configuration hint, while
    authorization_content_hash identifies the declaration source.  Neither
    field authenticates a user or grants policy authority.
    """

    schema_version: str
    owner_username: str
    tenant_id: str
    owner_id: str
    authorization_source_id: str
    authorization_source_version: str
    authorization_content_hash: str
    ttl_seconds: int

    def __post_init__(self) -> None:
        """Reject malformed settings before they enter a runtime profile."""

        _validate_values(
            schema_version=self.schema_version,
            owner_username=self.owner_username,
            tenant_id=self.tenant_id,
            owner_id=self.owner_id,
            authorization_source_id=self.authorization_source_id,
            authorization_source_version=self.authorization_source_version,
            authorization_content_hash=self.authorization_content_hash,
            ttl_seconds=self.ttl_seconds,
        )

    def as_timedelta(self) -> timedelta:
        """Return the validated TTL as a safe standard-library duration."""

        return timedelta(seconds=_require_ttl_seconds(self.ttl_seconds))

    def deadline_at(self, cutoff: datetime) -> datetime:
        """Return this settings snapshot's deadline at one aware server cutoff.

        A TTL may fit in timedelta while still overflowing a datetime near its
        calendar boundary.  The concrete cutoff is therefore validated at the
        point where a consumer creates an expiration timestamp.
        """

        if type(cutoff) is not datetime or cutoff.utcoffset() is None:
            raise SingleOwnerPolicyPublicationSettingsError(
                "deadline cutoff must be an exact aware datetime"
            )
        try:
            return cutoff + self.as_timedelta()
        except OverflowError as error:
            raise SingleOwnerPolicyPublicationSettingsError(
                "ttl_seconds cannot produce a datetime deadline"
            ) from error

    def to_payload(self) -> dict[str, object]:
        """Return the complete closed JSON object for runtime storage."""

        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "owner_username": self.owner_username,
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "authorization_source_id": self.authorization_source_id,
            "authorization_source_version": self.authorization_source_version,
            "authorization_content_hash": self.authorization_content_hash,
            "ttl_seconds": self.ttl_seconds,
        }


def decode_single_owner_policy_publication_settings(
    value: object,
) -> SingleOwnerPolicyPublicationSettings:
    """Decode exactly one complete settings object without applying defaults."""

    if type(value) is not dict:
        raise TypeError("single-owner policy publication settings must be an exact JSON object")
    if set(value) != _SETTINGS_KEYS:
        raise SingleOwnerPolicyPublicationSettingsError(
            "single-owner policy publication settings fields are incomplete or unknown"
        )
    return SingleOwnerPolicyPublicationSettings(
        schema_version=value["schema_version"],
        owner_username=value["owner_username"],
        tenant_id=value["tenant_id"],
        owner_id=value["owner_id"],
        authorization_source_id=value["authorization_source_id"],
        authorization_source_version=value["authorization_source_version"],
        authorization_content_hash=value["authorization_content_hash"],
        ttl_seconds=value["ttl_seconds"],
    )


__all__ = [
    "SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY",
    "SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION",
    "SingleOwnerPolicyPublicationSettings",
    "SingleOwnerPolicyPublicationSettingsError",
    "decode_single_owner_policy_publication_settings",
]
