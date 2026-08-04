"""ORM-backed context snapshot repository for agent runtime facades."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(source_name: str) -> dict[str, Any]:
    """Return a degraded placeholder for an unavailable data source."""

    return {
        "status": "unavailable",
        "source": source_name,
        "error": "source_fetch_failed",
    }


def _invalid_input(source_name: str, error_code: str) -> dict[str, Any]:
    """Return a stable placeholder for a rejected repository input."""

    return {
        "status": "invalid_input",
        "source": source_name,
        "error": error_code,
    }


def _log_source_failure(message: str, exc: BaseException) -> None:
    """Log source failure metadata without exposing exception text or credentials."""

    logger.warning(message, extra={"exception_type": type(exc).__name__})


def _to_iso(value: date | datetime | None) -> str | None:
    """Serialize a governed ORM date value for agent context."""

    return value.isoformat() if value is not None else None


class DjangoContextSnapshotRepository:
    """Read model for cross-app agent context snapshots."""

    def fetch_regime_summary(self) -> dict[str, Any]:
        """Fetch current regime state."""

        try:
            from apps.regime.application.current_regime import resolve_current_regime

            current = resolve_current_regime()
            status = "blocked" if current.must_not_use_for_decision else "ok"
            return {
                "status": status,
                "dominant_regime": current.dominant_regime,
                "growth_momentum_z": current.growth_momentum_z,
                "inflation_momentum_z": current.inflation_momentum_z,
                "distribution": current.distribution,
                "observed_at": _to_iso(current.observed_at),
                "data_source": current.data_source,
                "freshness_status": "stale" if current.is_stale else "fresh",
                "must_not_use_for_decision": current.must_not_use_for_decision,
                "blocked_reason": current.blocked_reason,
                "warnings": list(current.warnings),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch regime summary", exc)
            return _unavailable("regime")

    def fetch_policy_summary(self) -> dict[str, Any]:
        """Fetch current policy gear status."""

        try:
            from apps.policy.application.query_services import (
                get_policy_status_payload,
                get_recent_policy_event_summary,
            )

            status_payload = get_policy_status_payload()
            latest = get_recent_policy_event_summary(limit=1).get("latest")
            if not isinstance(latest, dict):
                return {"status": "no_data", "message": "No policy events found"}
            return {
                "status": "ok",
                "current_gear": status_payload.get("current_level"),
                "event_date": str(latest.get("event_date") or status_payload.get("as_of_date")),
                "description": str(latest.get("title") or ""),
                "is_intervention_active": bool(status_payload.get("is_intervention_active")),
                "observed_at": str(latest.get("event_date") or ""),
                "freshness_status": "effective",
                "must_not_use_for_decision": False,
                "blocked_reason": "",
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch policy summary", exc)
            return _unavailable("policy")

    def fetch_portfolio_summary(self) -> dict[str, Any]:
        """Fetch portfolio overview."""

        try:
            from apps.account.infrastructure.models import PortfolioModel, PositionModel

            portfolio = PortfolioModel._default_manager.filter(is_active=True).first()
            if portfolio is None:
                return {"status": "no_data", "message": "No portfolio found"}
            open_positions = PositionModel._default_manager.filter(
                portfolio=portfolio,
                is_closed=False,
            ).count()
            return {
                "status": "ok",
                "portfolio_id": portfolio.id,
                "portfolio_name": portfolio.name,
                "position_count": open_positions,
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch portfolio summary", exc)
            return _unavailable("portfolio")

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Fetch active investment signals summary."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignalModel

            active_qs = InvestmentSignalModel._default_manager.filter(
                status__in=("pending", "approved")
            )
            total = active_qs.count()
            recent_rows = list(
                active_qs.order_by("-created_at")[:5].values(
                    "id",
                    "asset_code",
                    "direction",
                    "status",
                    "created_at",
                )
            )
            recent: list[dict[str, Any]] = [
                {
                    "id": item["id"],
                    "asset_code": item["asset_code"],
                    "direction": item["direction"],
                    "status": item["status"],
                    "created_at": _to_iso(item["created_at"]),
                }
                for item in recent_rows
            ]
            return {
                "status": "ok",
                "active_count": total,
                "recent": recent,
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch active signals", exc)
            return _unavailable("signal")

    def fetch_open_decisions_summary(self) -> dict[str, Any]:
        """Fetch open decision requests summary."""

        try:
            from apps.decision_rhythm.infrastructure.models import DecisionRequestModel

            pending = DecisionRequestModel._default_manager.filter(
                execution_status="pending"
            ).count()
            return {
                "status": "ok",
                "pending_count": pending,
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch open decisions", exc)
            return _unavailable("decision_rhythm")

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Fetch risk-related alerts."""

        try:
            from apps.beta_gate.infrastructure.models import GateConfigModel

            active_gates = GateConfigModel._default_manager.filter(is_active=True).count()
            return {
                "status": "ok",
                "active_beta_gates": active_gates,
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch risk alerts", exc)
            return _unavailable("risk")

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
            needs_human = AgentTaskModel._default_manager.filter(requires_human=True).count()
            failed = AgentTaskModel._default_manager.filter(status=TaskStatus.FAILED.value).count()
            return {
                "status": "ok",
                "total_tasks": total,
                "active_tasks": active,
                "needs_human": needs_human,
                "failed_tasks": failed,
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch task health", exc)
            return _unavailable("agent_runtime")

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Fetch data freshness metrics across sources."""

        sources: dict[str, str] = {}
        failed_sources: list[str] = []
        regime_summary = self.fetch_regime_summary()
        observed_regime = regime_summary.get("observed_at")
        if isinstance(observed_regime, str) and observed_regime:
            sources["regime"] = observed_regime
        if regime_summary.get("status") in {"unavailable", "blocked"} or not observed_regime:
            sources["regime"] = "unavailable"
            failed_sources.append("regime")

        try:
            from apps.data_center.application.public import list_latest_published_macro_values

            macro_values = list_latest_published_macro_values(limit=500)
            observed_periods = [
                str(row.get("reporting_period"))
                for row in macro_values
                if row.get("reporting_period")
            ]
            if observed_periods:
                sources["macro"] = max(observed_periods)
            else:
                sources["macro"] = "unavailable"
                failed_sources.append("macro")
        except Exception as exc:
            _log_source_failure("Failed to fetch macro freshness", exc)
            sources["macro"] = "unavailable"
            failed_sources.append("macro")

        status = "degraded" if failed_sources else ("ok" if sources else "no_data")
        return {"status": status, "sources": sources}

    def fetch_event_bus_summary(self) -> dict[str, Any]:
        """Fetch event bus metrics used by ops-facing facades."""

        try:
            from apps.events.infrastructure.event_store import StoredEventModel

            return {
                "status": "ok",
                "total_event_records": StoredEventModel._default_manager.count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch event bus summary", exc)
            return _unavailable("events")

    def fetch_ai_provider_summary(self) -> dict[str, Any]:
        """Fetch AI provider availability metrics."""

        try:
            from apps.ai_provider.infrastructure.models import AIProviderConfig

            return {
                "status": "ok",
                "ai_providers_active": AIProviderConfig._default_manager.filter(
                    is_active=True
                ).count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch AI provider summary", exc)
            return _unavailable("ai_provider")

    def fetch_audit_freshness_summary(self) -> dict[str, Any]:
        """Fetch latest audit activity timestamp."""

        try:
            from apps.audit.infrastructure.models import OperationLogModel

            latest_audit = OperationLogModel._default_manager.order_by("-timestamp").first()
            if latest_audit is None:
                return {"status": "no_data"}
            return {
                "status": "ok",
                "audit": latest_audit.timestamp.isoformat(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch audit freshness summary", exc)
            return _unavailable("audit")

    def fetch_price_alert_summary(self) -> dict[str, Any]:
        """Fetch realtime price alert counts."""

        try:
            from apps.realtime.infrastructure.models import PriceAlertModel

            return {
                "status": "ok",
                "active_price_alerts": PriceAlertModel._default_manager.filter(
                    status="active"
                ).count(),
                "triggered_price_alerts": PriceAlertModel._default_manager.filter(
                    status="triggered"
                ).count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch price alert summary", exc)
            return _unavailable("realtime")

    def fetch_sentiment_freshness_summary(self) -> dict[str, Any]:
        """Fetch latest sentiment update timestamp."""

        try:
            from apps.sentiment.infrastructure.models import SentimentIndexModel

            latest = SentimentIndexModel._default_manager.order_by("-created_at").first()
            if latest is None:
                return {"status": "no_data"}
            return {"status": "ok", "sentiment": latest.created_at.isoformat()}
        except Exception as exc:
            _log_source_failure("Failed to fetch sentiment freshness summary", exc)
            return _unavailable("sentiment")

    def fetch_decision_quota_summary(self) -> dict[str, Any]:
        """Fetch decision quota overview."""

        try:
            from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel

            return {
                "status": "ok",
                "quotas": list(
                    DecisionQuotaModel._default_manager.values(
                        "quota_id",
                        "period",
                        "max_decisions",
                        "used_decisions",
                    )[:10]
                ),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch decision quota summary", exc)
            return _unavailable("decision_rhythm")

    def fetch_pending_signal_summary(self) -> dict[str, Any]:
        """Fetch pending approval signal counts."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignalModel

            return {
                "status": "ok",
                "pending_approval": InvestmentSignalModel._default_manager.filter(
                    status="pending",
                ).count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch pending signal summary", exc)
            return _unavailable("signal")

    def fetch_portfolio_position_summary(self, portfolio_id: int) -> dict[str, Any]:
        """Fetch top open positions for a portfolio."""

        if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int) or portfolio_id < 1:
            return _invalid_input("account", "portfolio_id_invalid")

        try:
            from apps.account.infrastructure.models import PositionModel

            return {
                "status": "ok",
                "top_positions": list(
                    PositionModel._default_manager.filter(
                        portfolio_id=portfolio_id,
                        is_closed=False,
                    ).values("asset_code", "shares", "avg_cost")[:10]
                ),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch portfolio position summary", exc)
            return _unavailable("account")

    def fetch_simulated_account_summary(self) -> dict[str, Any]:
        """Fetch active simulated trading account counts."""

        try:
            from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

            return {
                "status": "ok",
                "active_simulated_accounts": SimulatedAccountModel._default_manager.filter(
                    is_active=True
                ).count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch simulated account summary", exc)
            return _unavailable("simulated_trading")

    def fetch_regime_history_summary(self) -> dict[str, Any]:
        """Fetch regime history counts for research context."""

        try:
            from apps.regime.infrastructure.models import RegimeLog

            return {
                "status": "ok",
                "history_records": RegimeLog._default_manager.count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch regime history summary", exc)
            return _unavailable("regime")

    def fetch_signal_invalidation_summary(self) -> dict[str, Any]:
        """Fetch counts of signals carrying invalidation logic."""

        try:
            from apps.signal.infrastructure.models import InvestmentSignalModel

            return {
                "status": "ok",
                "with_invalidation_logic": InvestmentSignalModel._default_manager.filter(
                    status__in=("pending", "approved")
                )
                .exclude(invalidation_logic="")
                .count(),
            }
        except Exception as exc:
            _log_source_failure("Failed to fetch signal invalidation summary", exc)
            return _unavailable("signal")
