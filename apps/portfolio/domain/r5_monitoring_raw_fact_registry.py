"""Pure Portfolio-owned R5 monitoring raw-fact registry contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    _require_aware,
    _require_hash,
    _require_token,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)


@dataclass(frozen=True)
class PortfolioR5MonitoringRawFactDefinition:
    """Complete fact semantics supplied by a Portfolio owner definition source."""

    fact: R5PostPromotionMonitoringFact
    content_hash: str = field(init=False)

    @classmethod
    def from_fact(
        cls,
        fact: R5PostPromotionMonitoringFact,
    ) -> PortfolioR5MonitoringRawFactDefinition:
        """Copy one exact fact without accepting derived metric inputs."""

        return cls(fact)

    def __post_init__(self) -> None:
        if type(self.fact) is not R5PostPromotionMonitoringFact:
            raise TypeError("Portfolio R5 monitoring definition requires an exact fact")
        canonical = self.fact.validated_copy()
        if canonical != self.fact:
            raise ValueError("Portfolio R5 monitoring fact definition was substituted")
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "schema": "portfolio-r5-monitoring-raw-fact-definition.v1",
                    "fact": canonical,
                }
            ),
        )

    def validated_copy(self) -> PortfolioR5MonitoringRawFactDefinition:
        """Deeply rebuild the definition and complete raw fact."""

        copied = PortfolioR5MonitoringRawFactDefinition.from_fact(self.fact.validated_copy())
        if copied != self:
            raise ValueError("Portfolio R5 monitoring definition differs after replay")
        return copied


@dataclass(frozen=True)
class PortfolioR5MonitoringRawFactSourceReceipt:
    """Independent Portfolio receipt binding one exact raw-fact definition."""

    source_owner: str
    source_receipt_id: str
    source_receipt_version: str
    fact_id: str
    fact_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_owner: str,
        source_receipt_id: str,
        source_receipt_version: str,
        fact_id: str,
        fact_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
    ) -> PortfolioR5MonitoringRawFactSourceReceipt:
        """Create a content-addressed source receipt with no fabricated fact."""

        digest = _receipt_hash(
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            fact_id=fact_id,
            fact_version=fact_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
        )
        return cls(
            source_owner=source_owner,
            source_receipt_id=source_receipt_id,
            source_receipt_version=source_receipt_version,
            fact_id=fact_id,
            fact_version=fact_version,
            definition_hash=definition_hash,
            available_at=available_at,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.source_owner != "portfolio":
            raise ValueError("R5 monitoring raw facts must be Portfolio-owned")
        for label in (
            "source_owner",
            "source_receipt_id",
            "source_receipt_version",
            "fact_id",
            "fact_version",
        ):
            _require_token(getattr(self, label), f"Portfolio R5 raw fact {label}")
        _require_hash(self.definition_hash, "Portfolio R5 raw fact definition_hash")
        _require_hash(self.content_hash, "Portfolio R5 raw fact content_hash")
        _require_aware(self.available_at, "Portfolio R5 raw fact available_at")
        _require_aware(self.valid_until, "Portfolio R5 raw fact valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("Portfolio R5 raw fact source validity is empty")
        if self.content_hash != _receipt_hash(
            source_owner=self.source_owner,
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            fact_id=self.fact_id,
            fact_version=self.fact_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
        ):
            raise ValueError("Portfolio R5 raw fact source receipt hash differs")

    def validated_copy(self) -> PortfolioR5MonitoringRawFactSourceReceipt:
        """Rebuild the exact source receipt."""

        copied = PortfolioR5MonitoringRawFactSourceReceipt.create(
            source_owner=self.source_owner,
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            fact_id=self.fact_id,
            fact_version=self.fact_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
        )
        if copied != self:
            raise ValueError("Portfolio R5 raw fact source differs after replay")
        return copied


def _receipt_hash(
    *,
    source_owner: str,
    source_receipt_id: str,
    source_receipt_version: str,
    fact_id: str,
    fact_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
) -> str:
    return canonical_hash(
        {
            "schema": "portfolio-r5-monitoring-raw-fact-source-receipt.v1",
            "source": (source_owner, source_receipt_id, source_receipt_version),
            "fact": (fact_id, fact_version),
            "definition_hash": definition_hash,
            "window": (available_at, valid_until),
        }
    )


__all__ = [
    "PortfolioR5MonitoringRawFactDefinition",
    "PortfolioR5MonitoringRawFactSourceReceipt",
]
