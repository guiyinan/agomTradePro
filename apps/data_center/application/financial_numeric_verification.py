"""Application ports for independently verifying native financial decimals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef


@dataclass(frozen=True, slots=True)
class FinancialProviderIdentity:
    """Minimal non-secret identity for one persisted provider configuration."""

    provider_id: int
    name: str
    source_type: str
    is_active: bool

    def __post_init__(self) -> None:
        """Reject incomplete provider identity returned by Infrastructure."""

        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise ValueError("financial provider id must be a positive integer")
        for field_name, value in (("name", self.name), ("source_type", self.source_type)):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"financial provider {field_name} must be explicit text")
        if type(self.is_active) is not bool:
            raise ValueError("financial provider active state must be boolean")


class FinancialMetricSourceContractCatalogPort(Protocol):
    """Resolve one exact, versioned metric contract at a knowledge time."""

    def resolve_exact(
        self,
        identity: str,
        *,
        known_at: datetime,
    ) -> FinancialMetricSourceContract | None:
        """Return the approved contract version known by ``known_at``, if any."""
        ...


class FinancialNativeProviderIdentityPort(Protocol):
    """Read the persisted provider row that owns one RawAudit provider id."""

    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        """Return a minimal provider identity without resolving any credentials."""
        ...


class FinancialRetainedFinancialBodyPort(Protocol):
    """Read one retained financial body after independent audit/provider checks."""

    def read_verified_body(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Return exact original bytes or raise a stable verification error."""
        ...


class FinancialNumericEvidenceVerifier(Protocol):
    """Independently verify one v2 financial fact against its catalog and body."""

    def __call__(self, fact: FinancialFact) -> bool:
        """Return true only when retained native bytes reproduce the exact fact."""
        ...


__all__ = [
    "FinancialMetricSourceContractCatalogPort",
    "FinancialNativeProviderIdentityPort",
    "FinancialNumericEvidenceVerifier",
    "FinancialProviderIdentity",
    "FinancialRetainedFinancialBodyPort",
]
