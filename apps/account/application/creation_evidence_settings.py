"""Typed runtime settings for the Account creation-evidence recorder chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY: Final[str] = "account.creation_evidence.settings"
ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION: Final[str] = (
    "account.creation_evidence.settings.v1"
)

_SETTINGS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "ttl_seconds",
        "allocation_recorder_service_id",
        "physical_v2_recorder_service_id",
        "allocated_v3_recorder_service_id",
        "binding_recorder_service_id",
    }
)


class CanonicalAccountCreationEvidenceSettingsError(ValueError):
    """The runtime value is not one complete creation-evidence settings package."""


def _require_token(value: object, field_name: str) -> str:
    """Require one bounded token without coercing untrusted JSON values."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise CanonicalAccountCreationEvidenceSettingsError(
            f"{field_name} must be a bounded canonical token"
        )
    return value


def _require_ttl_seconds(value: object) -> int:
    """Require a positive integer that Python can represent as a timedelta."""

    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationEvidenceSettingsError(
            "ttl_seconds must be an exact positive integer"
        )
    try:
        timedelta(seconds=value)
    except OverflowError as error:
        raise CanonicalAccountCreationEvidenceSettingsError(
            "ttl_seconds is outside the supported timedelta range"
        ) from error
    return value


def _validate_values(
    *,
    schema_version: object,
    ttl_seconds: object,
    allocation_recorder_service_id: object,
    physical_v2_recorder_service_id: object,
    allocated_v3_recorder_service_id: object,
    binding_recorder_service_id: object,
) -> None:
    """Validate constructor values shared by construction and JSON decoding."""

    if _require_token(schema_version, "schema_version") != (
        ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION
    ):
        raise CanonicalAccountCreationEvidenceSettingsError("schema_version is unsupported")
    _require_ttl_seconds(ttl_seconds)
    for field_name, value in (
        ("allocation_recorder_service_id", allocation_recorder_service_id),
        ("physical_v2_recorder_service_id", physical_v2_recorder_service_id),
        ("allocated_v3_recorder_service_id", allocated_v3_recorder_service_id),
        ("binding_recorder_service_id", binding_recorder_service_id),
    ):
        _require_token(value, field_name)


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationEvidenceSettings:
    """One complete, immutable recorder configuration snapshot.

    The service identifiers are explicit bindings for the four recorder stages.
    This value carries no namespace, permission, or domain-schema defaults;
    those contracts remain fixed by their owning applications.
    """

    schema_version: str
    ttl_seconds: int
    allocation_recorder_service_id: str
    physical_v2_recorder_service_id: str
    allocated_v3_recorder_service_id: str
    binding_recorder_service_id: str

    def __post_init__(self) -> None:
        """Reject malformed values before they can enter a runtime profile."""

        _validate_values(
            schema_version=self.schema_version,
            ttl_seconds=self.ttl_seconds,
            allocation_recorder_service_id=self.allocation_recorder_service_id,
            physical_v2_recorder_service_id=self.physical_v2_recorder_service_id,
            allocated_v3_recorder_service_id=self.allocated_v3_recorder_service_id,
            binding_recorder_service_id=self.binding_recorder_service_id,
        )

    def as_timedelta(self) -> timedelta:
        """Return the validated TTL as a safe standard-library duration."""

        return timedelta(seconds=_require_ttl_seconds(self.ttl_seconds))

    def deadline_at(self, cutoff: datetime) -> datetime:
        """Return the TTL deadline for one aware server-clock cutoff.

        A duration can be representable by :class:`datetime.timedelta` while
        still being impossible to add to a particular datetime near the
        calendar boundary.  Consumers that turn this setting into an
        expiration timestamp must use this method so that such a boundary is
        rejected as a settings error instead of leaking ``OverflowError``.
        """

        if type(cutoff) is not datetime or cutoff.utcoffset() is None:
            raise CanonicalAccountCreationEvidenceSettingsError(
                "deadline cutoff must be an exact aware datetime"
            )
        try:
            return cutoff + self.as_timedelta()
        except OverflowError as error:
            raise CanonicalAccountCreationEvidenceSettingsError(
                "ttl_seconds cannot produce a datetime deadline"
            ) from error

    def to_payload(self) -> dict[str, object]:
        """Return the complete JSON object accepted by the runtime decoder."""

        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "ttl_seconds": self.ttl_seconds,
            "allocation_recorder_service_id": self.allocation_recorder_service_id,
            "physical_v2_recorder_service_id": self.physical_v2_recorder_service_id,
            "allocated_v3_recorder_service_id": self.allocated_v3_recorder_service_id,
            "binding_recorder_service_id": self.binding_recorder_service_id,
        }


def decode_canonical_account_creation_evidence_settings(
    value: object,
) -> CanonicalAccountCreationEvidenceSettings:
    """Decode exactly one complete JSON settings object without applying defaults."""

    if type(value) is not dict:
        raise TypeError("creation evidence settings must be an exact JSON object")
    if set(value) != _SETTINGS_KEYS:
        raise CanonicalAccountCreationEvidenceSettingsError(
            "creation evidence settings fields are incomplete or unknown"
        )
    return CanonicalAccountCreationEvidenceSettings(
        schema_version=value["schema_version"],
        ttl_seconds=value["ttl_seconds"],
        allocation_recorder_service_id=value["allocation_recorder_service_id"],
        physical_v2_recorder_service_id=value["physical_v2_recorder_service_id"],
        allocated_v3_recorder_service_id=value["allocated_v3_recorder_service_id"],
        binding_recorder_service_id=value["binding_recorder_service_id"],
    )


__all__ = [
    "ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY",
    "ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION",
    "CanonicalAccountCreationEvidenceSettings",
    "CanonicalAccountCreationEvidenceSettingsError",
    "decode_canonical_account_creation_evidence_settings",
]
