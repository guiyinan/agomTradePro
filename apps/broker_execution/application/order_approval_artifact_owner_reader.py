"""ID-only Broker owner reader for inactive order approval artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.broker_execution.domain.order_approval_artifact import (
    BROKER_ORDER_APPROVAL_ARTIFACT_OWNER,
    BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA,
    BROKER_ORDER_APPROVAL_ARTIFACT_TYPE,
)

BROKER_ORDER_APPROVAL_ARTIFACT_PERMISSION = "approval_evidence_only"
BROKER_ORDER_APPROVAL_ARTIFACT_STATUS = "inactive"


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be an exact positive integer")
    return value


class BrokerOrderApprovalArtifactOwnerReaderCorruption(ValueError):
    """The Broker owner repository returned a substituted identity winner."""


@dataclass(frozen=True, slots=True)
class BrokerOrderApprovalArtifactIdentityWinner:
    """Owner-derived immutable approval artifact projection with its record clock."""

    artifact_id: str
    artifact_version: str
    identity_hash: str
    content_hash: str
    account_id: int
    order_version: int
    approval_digest: str
    risk_policy_version: str
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = BROKER_ORDER_APPROVAL_ARTIFACT_OWNER
    artifact_type: str = BROKER_ORDER_APPROVAL_ARTIFACT_TYPE
    schema: str = BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA
    permission: str = BROKER_ORDER_APPROVAL_ARTIFACT_PERMISSION
    status: str = BROKER_ORDER_APPROVAL_ARTIFACT_STATUS
    activation_available: bool = False
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        try:
            canonical_artifact_id = str(UUID(self.artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("artifact_id must be a canonical UUID") from error
        if canonical_artifact_id != self.artifact_id:
            raise ValueError("artifact_id must be a canonical UUID")
        _require_positive_integer(self.account_id, "account_id")
        _require_positive_integer(self.order_version, "order_version")
        expected_version = f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.{self.order_version}"
        if self.artifact_version != expected_version:
            raise ValueError("artifact_version must bind the exact order_version")
        for field_name in ("identity_hash", "content_hash", "approval_digest"):
            _require_hash(getattr(self, field_name), field_name)
        _require_token(self.risk_policy_version, "risk_policy_version")
        for field_name in ("approved_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.approved_at <= self.recorded_at < self.valid_until:
            raise ValueError("Broker order approval artifact clock sequence is invalid")
        if self.owner != BROKER_ORDER_APPROVAL_ARTIFACT_OWNER:
            raise ValueError("Broker order approval artifact owner is fixed")
        if self.artifact_type != BROKER_ORDER_APPROVAL_ARTIFACT_TYPE:
            raise ValueError("Broker order approval artifact artifact_type is fixed")
        if self.schema != BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA:
            raise ValueError("Broker order approval artifact schema is fixed")
        if self.permission != BROKER_ORDER_APPROVAL_ARTIFACT_PERMISSION:
            raise ValueError("Broker order approval artifact permission is fixed")
        if (
            self.status != BROKER_ORDER_APPROVAL_ARTIFACT_STATUS
            or self.activation_available is not False
            or self.must_not_execute is not True
        ):
            raise ValueError("Broker order approval artifact must remain inactive")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this identity winner is recorded and unexpired at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class GetBrokerOrderApprovalArtifactByIdentity:
    """ID-only query; hashes and artifact semantics remain owner-derived."""

    artifact_id: str
    artifact_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        try:
            canonical_artifact_id = str(UUID(self.artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("artifact_id must be a canonical UUID") from error
        if canonical_artifact_id != self.artifact_id:
            raise ValueError("artifact_id must be a canonical UUID")
        _require_token(self.artifact_version, "artifact_version")
        _require_aware(self.as_of, "as_of")


class BrokerOrderApprovalArtifactIdentityWinnerRepository(Protocol):
    """Broker owner port returning one immutable artifact identity winner."""

    def get_identity_winner(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> BrokerOrderApprovalArtifactIdentityWinner | None:
        """Return the owner-derived identity winner knowable at the cutoff."""


class BrokerOrderApprovalArtifactOwnerReader:
    """Read an inactive Broker approval artifact by owner identity only."""

    def __init__(
        self,
        repository: BrokerOrderApprovalArtifactIdentityWinnerRepository,
    ) -> None:
        self._repository = repository

    def execute(
        self,
        query: GetBrokerOrderApprovalArtifactByIdentity,
    ) -> BrokerOrderApprovalArtifactIdentityWinner | None:
        """Return the exact recorded, unexpired identity winner without activation."""

        if type(query) is not GetBrokerOrderApprovalArtifactByIdentity:
            raise TypeError("query must be an exact GetBrokerOrderApprovalArtifactByIdentity")
        GetBrokerOrderApprovalArtifactByIdentity.__post_init__(query)
        value = self._repository.get_identity_winner(
            artifact_id=query.artifact_id,
            artifact_version=query.artifact_version,
            as_of=query.as_of,
        )
        if value is None:
            return None
        if type(value) is not BrokerOrderApprovalArtifactIdentityWinner:
            raise BrokerOrderApprovalArtifactOwnerReaderCorruption(
                "Broker order approval artifact identity winner type substitution"
            )
        try:
            BrokerOrderApprovalArtifactIdentityWinner.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerOrderApprovalArtifactOwnerReaderCorruption(
                "Broker order approval artifact identity winner is malformed"
            ) from error
        if (
            value.artifact_id != query.artifact_id
            or value.artifact_version != query.artifact_version
        ):
            raise BrokerOrderApprovalArtifactOwnerReaderCorruption(
                "Broker order approval artifact identity substitution"
            )
        return value if value.is_knowable_at(query.as_of) else None


__all__ = [
    "BROKER_ORDER_APPROVAL_ARTIFACT_PERMISSION",
    "BROKER_ORDER_APPROVAL_ARTIFACT_STATUS",
    "BrokerOrderApprovalArtifactIdentityWinner",
    "BrokerOrderApprovalArtifactIdentityWinnerRepository",
    "BrokerOrderApprovalArtifactOwnerReader",
    "BrokerOrderApprovalArtifactOwnerReaderCorruption",
    "GetBrokerOrderApprovalArtifactByIdentity",
]
