"""Application contract for publishing authenticated Account raw authority facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class AccountActorAuthorityRawSourceSelectorV3:
    """Identify one immutable raw-source version without carrying raw facts."""

    source_id: str
    source_version: str
    content_hash: str

    def __post_init__(self) -> None:
        """Validate the exact content-addressed selector returned to callers."""

        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.content_hash, "content_hash")

    def to_payload(self) -> dict[str, str]:
        """Return the selector as a secret-free JSON-compatible mapping."""

        return {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class AccountActorAuthorityRawSourcePublicationReceiptV3:
    """Describe one authenticated raw attestation publication."""

    authentication_context: AccountActorAuthorityRawSourceSelectorV3
    user: AccountActorAuthorityRawSourceSelectorV3
    rbac: AccountActorAuthorityRawSourceSelectorV3
    actor: AccountActorAuthorityRawSourceSelectorV3
    user_id: int
    principal_id: str
    observed_at: datetime
    valid_until: datetime
    outcome: str = "success"
    status: str = "attestation_only"

    def __post_init__(self) -> None:
        """Validate the receipt and keep it outside owner/scope/approval semantics."""

        for name in ("authentication_context", "user", "rbac", "actor"):
            value = getattr(self, name)
            if type(value) is not AccountActorAuthorityRawSourceSelectorV3:
                raise TypeError(f"{name} must be an exact raw-source selector")
            value.__post_init__()
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _token(self.principal_id, "principal_id")
        observed_at = _aware(self.observed_at, "observed_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if observed_at >= valid_until:
            raise ValueError("raw-source validity window is invalid")
        if self.outcome != "success":
            raise ValueError("publication outcome is fixed")
        if self.status != "attestation_only":
            raise ValueError("publication status is fixed")

    def to_payload(self) -> dict[str, object]:
        """Return only exact selectors and non-secret observation metadata."""

        self.__post_init__()
        return {
            "outcome": self.outcome,
            "status": self.status,
            "user_id": self.user_id,
            "principal_id": self.principal_id,
            "observed_at": self.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "valid_until": self.valid_until.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "authentication_context": self.authentication_context.to_payload(),
            "user": self.user.to_payload(),
            "rbac": self.rbac.to_payload(),
            "actor": self.actor.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class PublishAccountActorAuthorityRawSourceV3Command:
    """Represent the explicit no-input publication request."""


class AccountActorAuthorityRawSourcePublisherGatewayV3(Protocol):
    """Publish server-derived authenticated facts through the infrastructure boundary."""

    def publish(self) -> AccountActorAuthorityRawSourcePublicationReceiptV3:
        """Publish or replay the exact authenticated raw-source attestation."""


class PublishAccountActorAuthorityRawSourceV3:
    """Expose one typed Application use case for authenticated raw publication."""

    def __init__(self, gateway: AccountActorAuthorityRawSourcePublisherGatewayV3) -> None:
        """Store the injected server-side publisher gateway."""

        if gateway is None:
            raise TypeError("publisher gateway is required")
        self._gateway = gateway

    def execute(
        self, command: PublishAccountActorAuthorityRawSourceV3Command
    ) -> AccountActorAuthorityRawSourcePublicationReceiptV3:
        """Publish facts from the authenticated runtime without accepting client facts."""

        if type(command) is not PublishAccountActorAuthorityRawSourceV3Command:
            raise TypeError("command must be an exact empty publication command")
        receipt = self._gateway.publish()
        if type(receipt) is not AccountActorAuthorityRawSourcePublicationReceiptV3:
            raise AccountActorAuthorityRawSourceV3Corruption("publisher receipt type substitution")
        try:
            receipt.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "publisher receipt is corrupt"
            ) from error
        return receipt


__all__ = [
    "AccountActorAuthorityRawSourcePublisherGatewayV3",
    "AccountActorAuthorityRawSourcePublicationReceiptV3",
    "AccountActorAuthorityRawSourceSelectorV3",
    "AccountActorAuthorityRawSourceV3Conflict",
    "AccountActorAuthorityRawSourceV3Corruption",
    "AccountActorAuthorityRawSourceV3Unavailable",
    "PublishAccountActorAuthorityRawSourceV3",
    "PublishAccountActorAuthorityRawSourceV3Command",
]
