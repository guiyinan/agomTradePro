"""Common Application primitives for Account actor-authority raw sources v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class AccountActorAuthorityRawSourceV3Unavailable(ValueError):
    """The requested exact or exact-current raw authority source is unavailable."""


class AccountActorAuthorityRawSourceV3Conflict(ValueError):
    """A raw authority winner, observation, or predecessor changed concurrently."""


class AccountActorAuthorityRawSourceV3Corruption(ValueError):
    """A raw authority provider or repository returned substituted evidence."""


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class AccountActorAuthorityRawSourceV3Selector:
    """Select one exact version for replay or exact-current head verification."""

    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact scalar identity, digest, and point-in-time cutoff."""

        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class AccountActorAuthorityRawSourceV3Recorder:
    """Identify the fixed Account service that records raw authority evidence."""

    service_id: str
    role: str = "account_actor_authority_raw_recorder"
    kind: str = "service"
    is_automated: bool = True

    def __post_init__(self) -> None:
        """Validate the service identity and fixed non-human recorder semantics."""

        _token(self.service_id, "service_id")
        if type(self.role) is not str or self.role != "account_actor_authority_raw_recorder":
            raise ValueError("raw authority recorder role is fixed")
        if type(self.kind) is not str or self.kind != "service":
            raise ValueError("raw authority recorder kind is fixed")
        if type(self.is_automated) is not bool or self.is_automated is not True:
            raise ValueError("raw authority recorder automation is fixed")


__all__ = [
    "AccountActorAuthorityRawSourceV3Conflict",
    "AccountActorAuthorityRawSourceV3Corruption",
    "AccountActorAuthorityRawSourceV3Recorder",
    "AccountActorAuthorityRawSourceV3Selector",
    "AccountActorAuthorityRawSourceV3Unavailable",
]
