"""
Base Context Facade.

Provides degraded-but-structured data aggregation from multiple apps.
Each data source is fetched independently with error isolation -
a failure in one source does not block others.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceStatus:
    """Status of a single data source fetch."""
    available: bool
    fetched_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ContextSnapshotDTO:
    """
    Normalized context snapshot returned by all facades.

    Every field is always present. When the underlying source is
    unavailable, the value degrades to a structured placeholder.
    """
    domain: str
    generated_at: str
    regime_summary: Dict[str, Any] = field(default_factory=dict)
    policy_summary: Dict[str, Any] = field(default_factory=dict)
    portfolio_summary: Dict[str, Any] = field(default_factory=dict)
    active_signals_summary: Dict[str, Any] = field(default_factory=dict)
    open_decisions_summary: Dict[str, Any] = field(default_factory=dict)
    risk_alerts_summary: Dict[str, Any] = field(default_factory=dict)
    task_health_summary: Dict[str, Any] = field(default_factory=dict)
    data_freshness_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
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


def _unavailable(source_name: str, error: str) -> Dict[str, Any]:
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

    # ------------------------------------------------------------------
    # Individual data source fetchers (override in subclasses as needed)
    # ------------------------------------------------------------------

    def fetch_regime_summary(self) -> Dict[str, Any]:
        """Fetch current regime state."""
        try:
            from apps.regime.infrastructure.models import RegimeRecord
            latest = RegimeRecord.objects.order_by("-observed_at").first()
            if latest is None:
                return {"status": "no_data", "message": "No regime records found"}
            return {
                "status": "ok",
                "dominant_regime": latest.dominant_regime,
                "growth_level": latest.growth_level,
                "inflation_level": latest.inflation_level,
                "observed_at": str(latest.observed_at),
            }
        except Exception as e:
            logger.warning("Failed to fetch regime summary: %s", e)
            return _unavailable("regime", str(e))

    def fetch_policy_summary(self) -> Dict[str, Any]:
        """Fetch current policy gear status."""
        try:
            from apps.policy.infrastructure.models import PolicyEvent
            latest = PolicyEvent.objects.order_by("-event_date").first()
            if latest is None:
                return {"status": "no_data", "message": "No policy events found"}
            return {
                "status": "ok",
                "current_gear": getattr(latest, "gear", None),
                "event_date": str(latest.event_date),
                "description": getattr(latest, "description", ""),
            }
        except Exception as e:
            logger.warning("Failed to fetch policy summary: %s", e)
            return _unavailable("policy", str(e))

    def fetch_portfolio_summary(self) -> Dict[str, Any]:
        """Fetch portfolio overview."""
        try:
            from apps.account.infrastructure.models import Portfolio, Position
            portfolio = Portfolio.objects.first()
            if portfolio is None:
                return {"status": "no_data", "message": "No portfolio found"}
            open_positions = Position.objects.filter(
                portfolio=portfolio, is_closed=False
            ).count()
            return {
                "status": "ok",
                "portfolio_id": portfolio.id,
                "portfolio_name": portfolio.name,
                "position_count": open_positions,
            }
        except Exception as e:
            logger.warning("Failed to fetch portfolio summary: %s", e)
            return _unavailable("portfolio", str(e))

    def fetch_active_signals_summary(self) -> Dict[str, Any]:
        """Fetch active investment signals summary."""
        try:
            from apps.signal.infrastructure.models import InvestmentSignal
            active_qs = InvestmentSignal.objects.filter(is_active=True)
            total = active_qs.count()
            recent = list(
                active_qs.order_by("-created_at")[:5].values(
                    "id", "asset_code", "signal_type", "created_at"
                )
            )
            for item in recent:
                if item.get("created_at"):
                    item["created_at"] = item["created_at"].isoformat()
            return {
                "status": "ok",
                "active_count": total,
                "recent": recent,
            }
        except Exception as e:
            logger.warning("Failed to fetch active signals: %s", e)
            return _unavailable("signal", str(e))

    def fetch_open_decisions_summary(self) -> Dict[str, Any]:
        """Fetch open decision requests summary."""
        try:
            from apps.decision_rhythm.infrastructure.models import DecisionRequest
            pending = DecisionRequest.objects.filter(status="pending").count()
            return {
                "status": "ok",
                "pending_count": pending,
            }
        except Exception as e:
            logger.warning("Failed to fetch open decisions: %s", e)
            return _unavailable("decision_rhythm", str(e))

    def fetch_risk_alerts_summary(self) -> Dict[str, Any]:
        """Fetch risk-related alerts."""
        try:
            from apps.beta_gate.infrastructure.models import BetaGateConfig
            active_gates = BetaGateConfig.objects.filter(is_active=True).count()
            return {
                "status": "ok",
                "active_beta_gates": active_gates,
            }
        except Exception as e:
            logger.warning("Failed to fetch risk alerts: %s", e)
            return _unavailable("risk", str(e))

    def fetch_task_health_summary(self) -> Dict[str, Any]:
        """Fetch agent runtime task health."""
        try:
            from apps.agent_runtime.infrastructure.models import AgentTaskModel
            from apps.agent_runtime.domain.entities import TaskStatus

            total = AgentTaskModel._default_manager.count()
            active = AgentTaskModel._default_manager.exclude(
                status__in=[
                    TaskStatus.COMPLETED.value,
                    TaskStatus.CANCELLED.value,
                ]
            ).count()
            needs_human = AgentTaskModel._default_manager.filter(
                requires_human=True
            ).count()
            failed = AgentTaskModel._default_manager.filter(
                status=TaskStatus.FAILED.value
            ).count()
            return {
                "status": "ok",
                "total_tasks": total,
                "active_tasks": active,
                "needs_human": needs_human,
                "failed_tasks": failed,
            }
        except Exception as e:
            logger.warning("Failed to fetch task health: %s", e)
            return _unavailable("agent_runtime", str(e))

    def fetch_data_freshness_summary(self) -> Dict[str, Any]:
        """Fetch data freshness metrics across sources."""
        freshness: Dict[str, Any] = {"status": "ok", "sources": {}}
        # Regime freshness
        try:
            from apps.regime.infrastructure.models import RegimeRecord
            latest = RegimeRecord.objects.order_by("-observed_at").first()
            if latest:
                freshness["sources"]["regime"] = str(latest.observed_at)
        except Exception:
            freshness["sources"]["regime"] = "unavailable"

        # Macro freshness
        try:
            from apps.macro.infrastructure.models import MacroDataPoint
            latest = MacroDataPoint.objects.order_by("-data_date").first()
            if latest:
                freshness["sources"]["macro"] = str(latest.data_date)
        except Exception:
            freshness["sources"]["macro"] = "unavailable"

        return freshness

    # ------------------------------------------------------------------
    # Main aggregation
    # ------------------------------------------------------------------

    def build_snapshot(self) -> ContextSnapshotDTO:
        """
        Build a complete context snapshot for this domain.

        Each source is fetched independently. Failures produce
        structured degraded responses rather than exceptions.
        """
        now = datetime.now(timezone.utc).isoformat()
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
