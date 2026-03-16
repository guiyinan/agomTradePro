"""
Unit tests for Agent Runtime M2 - Domain Facade Layer.

WP-M2-02: Tests for facade aggregation with complete and partial data.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from apps.agent_runtime.application.facades import get_facade
from apps.agent_runtime.application.facades.base import (
    BaseContextFacade,
    ContextSnapshotDTO,
    _unavailable,
)
from apps.agent_runtime.application.facades.research import ResearchTaskFacade
from apps.agent_runtime.application.facades.monitoring import MonitoringTaskFacade
from apps.agent_runtime.application.facades.decision import DecisionTaskFacade
from apps.agent_runtime.application.facades.execution import ExecutionTaskFacade
from apps.agent_runtime.application.facades.ops import OpsTaskFacade


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


class TestMonitoringFacade:
    """Test MonitoringTaskFacade specific behavior."""

    def test_domain_is_monitoring(self):
        assert MonitoringTaskFacade().domain == "monitoring"


class TestDecisionFacade:
    """Test DecisionTaskFacade specific behavior."""

    def test_domain_is_decision(self):
        assert DecisionTaskFacade().domain == "decision"


class TestExecutionFacade:
    """Test ExecutionTaskFacade specific behavior."""

    def test_domain_is_execution(self):
        assert ExecutionTaskFacade().domain == "execution"


class TestOpsFacade:
    """Test OpsTaskFacade specific behavior."""

    def test_domain_is_ops(self):
        assert OpsTaskFacade().domain == "ops"
