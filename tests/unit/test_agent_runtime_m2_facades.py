"""
Unit tests for Agent Runtime M2 - Domain Facade Layer.

WP-M2-02: Tests for facade aggregation with complete and partial data.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from apps.agent_runtime.application.facades import get_facade
from apps.agent_runtime.application.facades.base import (
    BaseContextFacade,
    ContextSnapshotDTO,
    _unavailable,
)
from apps.agent_runtime.application.facades.decision import DecisionTaskFacade
from apps.agent_runtime.application.facades.execution import ExecutionTaskFacade
from apps.agent_runtime.application.facades.monitoring import MonitoringTaskFacade
from apps.agent_runtime.application.facades.ops import OpsTaskFacade
from apps.agent_runtime.application.facades.research import ResearchTaskFacade


class TestGetFacade:
    """Test the facade factory function."""

    def test_get_research_facade(self):
        facade = get_facade("research")
        assert isinstance(facade, ResearchTaskFacade)
        assert facade.domain == "research"

    def test_get_monitoring_facade(self):
        facade = get_facade("monitoring")
        assert isinstance(facade, MonitoringTaskFacade)
        assert facade.domain == "monitoring"

    def test_get_decision_facade(self):
        facade = get_facade("decision")
        assert isinstance(facade, DecisionTaskFacade)
        assert facade.domain == "decision"

    def test_get_execution_facade(self):
        facade = get_facade("execution")
        assert isinstance(facade, ExecutionTaskFacade)
        assert facade.domain == "execution"

    def test_get_ops_facade(self):
        facade = get_facade("ops")
        assert isinstance(facade, OpsTaskFacade)
        assert facade.domain == "ops"

    def test_get_unknown_domain_raises(self):
        with pytest.raises(ValueError, match="Unknown domain"):
            get_facade("invalid_domain")


class TestContextSnapshotDTO:
    """Test ContextSnapshotDTO serialization."""

    def test_to_dict_has_all_fields(self):
        dto = ContextSnapshotDTO(
            domain="research",
            generated_at="2026-03-16T12:00:00+00:00",
        )
        d = dto.to_dict()
        assert d["domain"] == "research"
        assert d["generated_at"] == "2026-03-16T12:00:00+00:00"
        assert "regime_summary" in d
        assert "policy_summary" in d
        assert "portfolio_summary" in d
        assert "active_signals_summary" in d
        assert "open_decisions_summary" in d
        assert "risk_alerts_summary" in d
        assert "task_health_summary" in d
        assert "data_freshness_summary" in d

    def test_to_dict_preserves_data(self):
        dto = ContextSnapshotDTO(
            domain="ops",
            generated_at="2026-03-16T12:00:00+00:00",
            regime_summary={"status": "ok", "dominant_regime": "Recovery"},
        )
        d = dto.to_dict()
        assert d["regime_summary"]["dominant_regime"] == "Recovery"


class TestUnavailablePlaceholder:
    """Test the _unavailable helper."""

    def test_returns_structured_placeholder(self):
        result = _unavailable("regime", "connection timeout")
        assert result["status"] == "unavailable"
        assert result["source"] == "regime"
        assert result["error"] == "connection timeout"


class TestBaseContextFacade:
    """Test BaseContextFacade with mocked data sources."""

    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_regime_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_policy_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_portfolio_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_active_signals_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_open_decisions_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_risk_alerts_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_task_health_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_data_freshness_summary")
    def test_build_snapshot_all_ok(
        self,
        mock_freshness, mock_task, mock_risk, mock_decisions,
        mock_signals, mock_portfolio, mock_policy, mock_regime,
    ):
        """Snapshot is built when all sources succeed."""
        mock_regime.return_value = {"status": "ok", "dominant_regime": "Recovery"}
        mock_policy.return_value = {"status": "ok", "current_gear": "neutral"}
        mock_portfolio.return_value = {"status": "ok", "position_count": 5}
        mock_signals.return_value = {"status": "ok", "active_count": 3}
        mock_decisions.return_value = {"status": "ok", "pending_count": 1}
        mock_risk.return_value = {"status": "ok", "active_beta_gates": 2}
        mock_task.return_value = {"status": "ok", "active_tasks": 4}
        mock_freshness.return_value = {"status": "ok", "sources": {}}

        facade = BaseContextFacade()
        facade.domain = "test"
        snapshot = facade.build_snapshot()

        assert snapshot.domain == "test"
        assert snapshot.regime_summary["dominant_regime"] == "Recovery"
        assert snapshot.active_signals_summary["active_count"] == 3
        assert snapshot.generated_at is not None

    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_regime_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_policy_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_portfolio_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_active_signals_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_open_decisions_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_risk_alerts_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_task_health_summary")
    @patch("apps.agent_runtime.application.facades.base.BaseContextFacade.fetch_data_freshness_summary")
    def test_build_snapshot_partial_failure(
        self,
        mock_freshness, mock_task, mock_risk, mock_decisions,
        mock_signals, mock_portfolio, mock_policy, mock_regime,
    ):
        """Snapshot degrades gracefully when some sources fail."""
        mock_regime.return_value = {"status": "ok", "dominant_regime": "Recovery"}
        mock_policy.return_value = _unavailable("policy", "connection refused")
        mock_portfolio.return_value = _unavailable("portfolio", "db error")
        mock_signals.return_value = {"status": "ok", "active_count": 2}
        mock_decisions.return_value = _unavailable("decision_rhythm", "timeout")
        mock_risk.return_value = {"status": "ok", "active_beta_gates": 0}
        mock_task.return_value = {"status": "ok", "active_tasks": 1}
        mock_freshness.return_value = {"status": "ok", "sources": {}}

        facade = BaseContextFacade()
        facade.domain = "test"
        snapshot = facade.build_snapshot()

        # Successful sources
        assert snapshot.regime_summary["status"] == "ok"
        assert snapshot.active_signals_summary["status"] == "ok"
        # Degraded sources
        assert snapshot.policy_summary["status"] == "unavailable"
        assert snapshot.portfolio_summary["status"] == "unavailable"
        assert snapshot.open_decisions_summary["status"] == "unavailable"
        # Still returns a valid DTO
        d = snapshot.to_dict()
        assert d["domain"] == "test"


class TestResearchFacade:
    """Test ResearchTaskFacade specific behavior."""

    def test_domain_is_research(self):
        assert ResearchTaskFacade().domain == "research"

    def test_fetch_regime_summary_adds_history_count(self):
        repository = MagicMock()
        repository.fetch_regime_summary.return_value = {
            "status": "ok",
            "dominant_regime": "Recovery",
        }
        repository.fetch_regime_history_summary.return_value = {
            "status": "ok",
            "history_records": 128,
        }

        facade = ResearchTaskFacade(context_repository=repository)

        summary = facade.fetch_regime_summary()

        assert summary["history_records"] == 128

    def test_fetch_active_signals_summary_adds_invalidation_count(self):
        repository = MagicMock()
        repository.fetch_active_signals_summary.return_value = {
            "status": "ok",
            "active_count": 6,
        }
        repository.fetch_signal_invalidation_summary.return_value = {
            "status": "ok",
            "with_invalidation_logic": 5,
        }

        facade = ResearchTaskFacade(context_repository=repository)

        summary = facade.fetch_active_signals_summary()

        assert summary["with_invalidation_logic"] == 5


class TestMonitoringFacade:
    """Test MonitoringTaskFacade specific behavior."""

    def test_domain_is_monitoring(self):
        assert MonitoringTaskFacade().domain == "monitoring"

    def test_fetch_risk_alerts_summary_adds_price_alerts(self):
        repository = MagicMock()
        repository.fetch_risk_alerts_summary.return_value = {"status": "ok"}
        repository.fetch_price_alert_summary.return_value = {
            "status": "ok",
            "active_price_alerts": 5,
            "triggered_price_alerts": 2,
        }

        facade = MonitoringTaskFacade(context_repository=repository)

        summary = facade.fetch_risk_alerts_summary()

        assert summary["active_price_alerts"] == 5
        assert summary["triggered_price_alerts"] == 2

    def test_fetch_data_freshness_summary_adds_sentiment_timestamp(self):
        repository = MagicMock()
        repository.fetch_data_freshness_summary.return_value = {
            "status": "ok",
            "sources": {"macro": "2026-03-16"},
        }
        repository.fetch_sentiment_freshness_summary.return_value = {
            "status": "ok",
            "sentiment": "2026-03-16T13:00:00+00:00",
        }

        facade = MonitoringTaskFacade(context_repository=repository)

        summary = facade.fetch_data_freshness_summary()

        assert summary["sources"]["sentiment"] == "2026-03-16T13:00:00+00:00"


class TestDecisionFacade:
    """Test DecisionTaskFacade specific behavior."""

    def test_domain_is_decision(self):
        assert DecisionTaskFacade().domain == "decision"

    def test_fetch_open_decisions_summary_adds_quotas(self):
        repository = MagicMock()
        repository.fetch_open_decisions_summary.return_value = {
            "status": "ok",
            "pending_count": 1,
        }
        repository.fetch_decision_quota_summary.return_value = {
            "status": "ok",
            "quotas": [{"decision_type": "macro", "max_count": 3, "current_count": 1}],
        }

        facade = DecisionTaskFacade(context_repository=repository)

        summary = facade.fetch_open_decisions_summary()

        assert summary["quotas"][0]["decision_type"] == "macro"

    def test_fetch_active_signals_summary_adds_pending_approval(self):
        repository = MagicMock()
        repository.fetch_active_signals_summary.return_value = {
            "status": "ok",
            "active_count": 4,
        }
        repository.fetch_pending_signal_summary.return_value = {
            "status": "ok",
            "pending_approval": 2,
        }

        facade = DecisionTaskFacade(context_repository=repository)

        summary = facade.fetch_active_signals_summary()

        assert summary["pending_approval"] == 2


class TestExecutionFacade:
    """Test ExecutionTaskFacade specific behavior."""

    def test_domain_is_execution(self):
        assert ExecutionTaskFacade().domain == "execution"

    def test_fetch_portfolio_summary_adds_top_positions(self):
        repository = MagicMock()
        repository.fetch_portfolio_summary.return_value = {
            "status": "ok",
            "portfolio_id": 7,
        }
        repository.fetch_portfolio_position_summary.return_value = {
            "status": "ok",
            "top_positions": [{"asset_code": "000001.SH", "shares": 100}],
        }

        facade = ExecutionTaskFacade(context_repository=repository)

        summary = facade.fetch_portfolio_summary()

        assert summary["top_positions"][0]["asset_code"] == "000001.SH"

    def test_fetch_risk_alerts_summary_adds_simulated_account_count(self):
        repository = MagicMock()
        repository.fetch_risk_alerts_summary.return_value = {"status": "ok"}
        repository.fetch_simulated_account_summary.return_value = {
            "status": "ok",
            "active_simulated_accounts": 3,
        }

        facade = ExecutionTaskFacade(context_repository=repository)

        summary = facade.fetch_risk_alerts_summary()

        assert summary["active_simulated_accounts"] == 3


class TestOpsFacade:
    """Test OpsTaskFacade specific behavior."""

    def test_domain_is_ops(self):
        assert OpsTaskFacade().domain == "ops"

    def test_fetch_task_health_summary_adds_event_bus_metrics(self):
        repository = MagicMock()
        repository.fetch_task_health_summary.return_value = {
            "status": "ok",
            "active_tasks": 2,
        }
        repository.fetch_event_bus_summary.return_value = {
            "status": "ok",
            "total_event_records": 42,
        }

        facade = OpsTaskFacade(context_repository=repository)

        summary = facade.fetch_task_health_summary()

        assert summary["active_tasks"] == 2
        assert summary["total_event_records"] == 42

    def test_fetch_data_freshness_summary_adds_provider_and_audit_metrics(self):
        repository = MagicMock()
        repository.fetch_data_freshness_summary.return_value = {
            "status": "ok",
            "sources": {"regime": "2026-03-16T12:00:00+00:00"},
        }
        repository.fetch_ai_provider_summary.return_value = {
            "status": "ok",
            "ai_providers_active": 3,
        }
        repository.fetch_audit_freshness_summary.return_value = {
            "status": "ok",
            "audit": "2026-03-16T13:00:00+00:00",
        }

        facade = OpsTaskFacade(context_repository=repository)

        summary = facade.fetch_data_freshness_summary()

        assert summary["sources"]["regime"] == "2026-03-16T12:00:00+00:00"
        assert summary["sources"]["ai_providers_active"] == 3
        assert summary["sources"]["audit"] == "2026-03-16T13:00:00+00:00"
