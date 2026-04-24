"""ORM-backed context snapshot repository for agent runtime facades."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(source_name: str, error: str) -> dict[str, Any]:
    """Return a degraded placeholder for an unavailable data source."""

    return {
        "status": "unavailable",
        "source": source_name,
        "error": str(error),
    }


class DjangoContextSnapshotRepository:
    """Read model for cross-app agent context snapshots."""

    def fetch_regime_summary(self) -> dict[str, Any]:
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

    def fetch_policy_summary(self) -> dict[str, Any]:
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

    def fetch_portfolio_summary(self) -> dict[str, Any]:
        """Fetch portfolio overview."""

        try:
            from apps.account.infrastructure.models import Portfolio, Position

            portfolio = Portfolio.objects.first()
            if portfolio is None:
                return {"status": "no_data", "message": "No portfolio found"}
            open_positions = Position.objects.filter(
                portfolio=portfolio,
                is_closed=False,
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

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Fetch active investment signals summary."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignal

            active_qs = InvestmentSignal.objects.filter(is_active=True)
            total = active_qs.count()
            recent = list(
                active_qs.order_by("-created_at")[:5].values(
                    "id",
                    "asset_code",
                    "signal_type",
                    "created_at",
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

    def fetch_open_decisions_summary(self) -> dict[str, Any]:
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

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
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

    def fetch_task_health_summary(self) -> dict[str, Any]:
        """Fetch agent runtime task health."""

        try:
            from apps.agent_runtime.domain.entities import TaskStatus
            from apps.agent_runtime.infrastructure.models import AgentTaskModel

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

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Fetch data freshness metrics across sources."""

        freshness: dict[str, Any] = {"status": "ok", "sources": {}}
        try:
            from apps.regime.infrastructure.models import RegimeRecord

            latest = RegimeRecord.objects.order_by("-observed_at").first()
            if latest:
                freshness["sources"]["regime"] = str(latest.observed_at)
        except Exception:
            freshness["sources"]["regime"] = "unavailable"

        try:
            from apps.macro.infrastructure.models import MacroDataPoint

            latest = MacroDataPoint.objects.order_by("-data_date").first()
            if latest:
                freshness["sources"]["macro"] = str(latest.data_date)
        except Exception:
            freshness["sources"]["macro"] = "unavailable"

        return freshness

    def fetch_event_bus_summary(self) -> dict[str, Any]:
        """Fetch event bus metrics used by ops-facing facades."""

        try:
            from apps.events.infrastructure.models import EventRecord

            return {
                "status": "ok",
                "total_event_records": EventRecord.objects.count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch event bus summary: %s", e)
            return _unavailable("events", str(e))

    def fetch_ai_provider_summary(self) -> dict[str, Any]:
        """Fetch AI provider availability metrics."""

        try:
            from apps.ai_provider.infrastructure.models import AIProvider

            return {
                "status": "ok",
                "ai_providers_active": AIProvider.objects.filter(is_active=True).count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch AI provider summary: %s", e)
            return _unavailable("ai_provider", str(e))

    def fetch_audit_freshness_summary(self) -> dict[str, Any]:
        """Fetch latest audit activity timestamp."""

        try:
            from apps.audit.infrastructure.models import AuditRecord

            latest_audit = AuditRecord.objects.order_by("-created_at").first()
            if latest_audit is None:
                return {"status": "no_data"}
            return {
                "status": "ok",
                "audit": latest_audit.created_at.isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch audit freshness summary: %s", e)
            return _unavailable("audit", str(e))

    def fetch_price_alert_summary(self) -> dict[str, Any]:
        """Fetch realtime price alert counts."""

        try:
            from apps.realtime.infrastructure.models import PriceAlert

            return {
                "status": "ok",
                "active_price_alerts": PriceAlert.objects.filter(is_active=True).count(),
                "triggered_price_alerts": PriceAlert.objects.filter(
                    is_active=True,
                    is_triggered=True,
                ).count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch price alert summary: %s", e)
            return _unavailable("realtime", str(e))

    def fetch_sentiment_freshness_summary(self) -> dict[str, Any]:
        """Fetch latest sentiment update timestamp."""

        try:
            from apps.sentiment.infrastructure.models import SentimentRecord

            latest = SentimentRecord.objects.order_by("-created_at").first()
            if latest is None:
                return {"status": "no_data"}
            return {"status": "ok", "sentiment": latest.created_at.isoformat()}
        except Exception as e:
            logger.warning("Failed to fetch sentiment freshness summary: %s", e)
            return _unavailable("sentiment", str(e))

    def fetch_decision_quota_summary(self) -> dict[str, Any]:
        """Fetch decision quota overview."""

        try:
            from apps.decision_rhythm.infrastructure.models import DecisionQuota

            return {
                "status": "ok",
                "quotas": list(
                    DecisionQuota.objects.values(
                        "decision_type",
                        "max_count",
                        "current_count",
                    )[:10]
                ),
            }
        except Exception as e:
            logger.warning("Failed to fetch decision quota summary: %s", e)
            return _unavailable("decision_rhythm", str(e))

    def fetch_pending_signal_summary(self) -> dict[str, Any]:
        """Fetch pending approval signal counts."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignal

            return {
                "status": "ok",
                "pending_approval": InvestmentSignal.objects.filter(
                    is_active=True,
                    status="pending_approval",
                ).count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch pending signal summary: %s", e)
            return _unavailable("signal", str(e))

    def fetch_portfolio_position_summary(self, portfolio_id: int) -> dict[str, Any]:
        """Fetch top open positions for a portfolio."""

        try:
            from apps.account.infrastructure.models import Position

            return {
                "status": "ok",
                "top_positions": list(
                    Position.objects.filter(
                        portfolio_id=portfolio_id,
                        is_closed=False,
                    ).values("asset_code", "shares", "avg_cost")[:10]
                ),
            }
        except Exception as e:
            logger.warning("Failed to fetch portfolio position summary: %s", e)
            return _unavailable("account", str(e))

    def fetch_simulated_account_summary(self) -> dict[str, Any]:
        """Fetch active simulated trading account counts."""

        try:
            from apps.simulated_trading.infrastructure.models import SimulatedAccount

            return {
                "status": "ok",
                "active_simulated_accounts": SimulatedAccount.objects.filter(
                    is_active=True
                ).count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch simulated account summary: %s", e)
            return _unavailable("simulated_trading", str(e))

    def fetch_regime_history_summary(self) -> dict[str, Any]:
        """Fetch regime history counts for research context."""

        try:
            from apps.regime.infrastructure.models import RegimeRecord

            return {
                "status": "ok",
                "history_records": RegimeRecord.objects.count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch regime history summary: %s", e)
            return _unavailable("regime", str(e))

    def fetch_signal_invalidation_summary(self) -> dict[str, Any]:
        """Fetch counts of signals carrying invalidation logic."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignal

            return {
                "status": "ok",
                "with_invalidation_logic": InvestmentSignal.objects.filter(
                    is_active=True,
                ).exclude(invalidation_logic="").count(),
            }
        except Exception as e:
            logger.warning("Failed to fetch signal invalidation summary: %s", e)
            return _unavailable("signal", str(e))
