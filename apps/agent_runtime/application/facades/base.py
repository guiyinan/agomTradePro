"""
Base Context Facade.

Provides degraded-but-structured data aggregation from multiple apps.
Each data source is fetched independently with error isolation -
a failure in one source does not block others.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceStatus:
    """Status of a single data source fetch."""
    available: bool
    fetched_at: str | None = None
    error: str | None = None


@dataclass
class ContextSnapshotDTO:
    """
    Normalized context snapshot returned by all facades.

    Every field is always present. When the underlying source is
    unavailable, the value degrades to a structured placeholder.
    """
    domain: str
    generated_at: str
    regime_summary: dict[str, Any] = field(default_factory=dict)
    policy_summary: dict[str, Any] = field(default_factory=dict)
    portfolio_summary: dict[str, Any] = field(default_factory=dict)
    active_signals_summary: dict[str, Any] = field(default_factory=dict)
    open_decisions_summary: dict[str, Any] = field(default_factory=dict)
    risk_alerts_summary: dict[str, Any] = field(default_factory=dict)
    task_health_summary: dict[str, Any] = field(default_factory=dict)
    data_freshness_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "domain": self.domain,
            "generated_at": self.generated_at,
            "regime_summary": self.regime_summary,
            "policy_summary": self.policy_summary,
            "portfolio_summary": self.portfolio_summary,
            "active_signals_summary": self.active_signals_summary,
            "open_decisions_summary": self.open_decisions_summary,
            "risk_alerts_summary": self.risk_alerts_summary,
            "task_health_summary": self.task_health_summary,
            "data_freshness_summary": self.data_freshness_summary,
        }


def _unavailable(source_name: str, error: str) -> dict[str, Any]:
    """Return a degraded placeholder for an unavailable data source."""
    return {
        "status": "unavailable",
        "source": source_name,
        "error": str(error),
    }


class BaseContextFacade:
    """
    Base facade for context snapshot aggregation.

    Subclasses may override individual fetch methods to customize
    which data is included or how it is summarized for their domain.
    """

    domain: str = "base"

    def __init__(self, context_repository=None):
        if context_repository is None:
            from apps.agent_runtime.application.repository_provider import (
                get_context_snapshot_repository,
            )

            context_repository = get_context_snapshot_repository()
        self.context_repository = context_repository

    # ------------------------------------------------------------------
    # Individual data source fetchers (override in subclasses as needed)
    # ------------------------------------------------------------------

    def fetch_regime_summary(self) -> dict[str, Any]:
        """Fetch current regime state."""
        return self.context_repository.fetch_regime_summary()

    def fetch_policy_summary(self) -> dict[str, Any]:
        """Fetch current policy gear status."""
        return self.context_repository.fetch_policy_summary()

    def fetch_portfolio_summary(self) -> dict[str, Any]:
        """Fetch portfolio overview."""
        return self.context_repository.fetch_portfolio_summary()

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Fetch active investment signals summary."""
        return self.context_repository.fetch_active_signals_summary()

    def fetch_open_decisions_summary(self) -> dict[str, Any]:
        """Fetch open decision requests summary."""
        return self.context_repository.fetch_open_decisions_summary()

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Fetch risk-related alerts."""
        return self.context_repository.fetch_risk_alerts_summary()

    def fetch_task_health_summary(self) -> dict[str, Any]:
        """Fetch agent runtime task health."""
        return self.context_repository.fetch_task_health_summary()

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Fetch data freshness metrics across sources."""
        return self.context_repository.fetch_data_freshness_summary()

    # ------------------------------------------------------------------
    # Main aggregation
    # ------------------------------------------------------------------

    def build_snapshot(self) -> ContextSnapshotDTO:
        """
        Build a complete context snapshot for this domain.

        Each source is fetched independently. Failures produce
        structured degraded responses rather than exceptions.
        """
        now = datetime.now(UTC).isoformat()
        return ContextSnapshotDTO(
            domain=self.domain,
            generated_at=now,
            regime_summary=self.fetch_regime_summary(),
            policy_summary=self.fetch_policy_summary(),
            portfolio_summary=self.fetch_portfolio_summary(),
            active_signals_summary=self.fetch_active_signals_summary(),
            open_decisions_summary=self.fetch_open_decisions_summary(),
            risk_alerts_summary=self.fetch_risk_alerts_summary(),
            task_health_summary=self.fetch_task_health_summary(),
            data_freshness_summary=self.fetch_data_freshness_summary(),
        )
