"""T5 success and degradation contracts for context snapshot persistence reads."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apps.agent_runtime.infrastructure.context_snapshot_repository import (
    DjangoContextSnapshotRepository,
    _invalid_input,
    _unavailable,
)


def _model_module(model_name: str, manager: MagicMock) -> SimpleNamespace:
    """Build a synthetic infrastructure module with one ORM model."""
    return SimpleNamespace(**{model_name: SimpleNamespace(_default_manager=manager)})


def test_context_snapshot_primary_summaries_cover_data_and_empty_states() -> None:
    """Core regime, policy, portfolio, signal, decision, risk, and task reads work."""
    repository = DjangoContextSnapshotRepository()
    observed_at = datetime(2026, 7, 25, tzinfo=UTC)

    manager = MagicMock()
    manager.order_by.return_value.first.return_value = SimpleNamespace(
        dominant_regime="recovery",
        growth_momentum_z=0.5,
        inflation_momentum_z=-0.2,
        distribution={"recovery": 0.8},
        observed_at=observed_at,
    )
    with patch.dict(
        sys.modules,
        {"apps.regime.infrastructure.models": _model_module("RegimeLog", manager)},
    ):
        assert repository.fetch_regime_summary()["dominant_regime"] == "recovery"
        manager.order_by.return_value.first.return_value = None
        assert repository.fetch_regime_summary()["status"] == "no_data"

    manager = MagicMock()
    manager.order_by.return_value.first.return_value = SimpleNamespace(
        level="P1",
        event_date=observed_at.date(),
        description="observe",
    )
    with patch.dict(
        sys.modules,
        {"apps.policy.infrastructure.models": _model_module("PolicyLog", manager)},
    ):
        assert repository.fetch_policy_summary()["current_gear"] == "P1"
        manager.order_by.return_value.first.return_value = None
        assert repository.fetch_policy_summary()["status"] == "no_data"

    portfolio_manager = MagicMock()
    portfolio_manager.filter.return_value.first.return_value = SimpleNamespace(
        id=7,
        name="main",
    )
    position_manager = MagicMock()
    position_manager.filter.return_value.count.return_value = 3
    with patch.dict(
        sys.modules,
        {
            "apps.account.infrastructure.models": SimpleNamespace(
                PortfolioModel=SimpleNamespace(_default_manager=portfolio_manager),
                PositionModel=SimpleNamespace(_default_manager=position_manager),
            )
        },
    ):
        assert repository.fetch_portfolio_summary()["position_count"] == 3
        portfolio_manager.filter.return_value.first.return_value = None
        assert repository.fetch_portfolio_summary()["status"] == "no_data"

    signal_manager = MagicMock()
    active = signal_manager.filter.return_value
    active.count.return_value = 2
    active.order_by.return_value.__getitem__.return_value.values.return_value = [
        {
            "id": 1,
            "asset_code": "A",
            "direction": "long",
            "status": "pending",
            "created_at": observed_at,
        }
    ]
    with patch.dict(
        sys.modules,
        {
            "apps.signal.infrastructure.models": _model_module(
                "InvestmentSignalModel",
                signal_manager,
            )
        },
    ):
        result = repository.fetch_active_signals_summary()
        assert result["active_count"] == 2
        assert result["recent"][0]["created_at"].startswith("2026-07-25")

    decision_manager = MagicMock()
    decision_manager.filter.return_value.count.return_value = 4
    with patch.dict(
        sys.modules,
        {
            "apps.decision_rhythm.infrastructure.models": _model_module(
                "DecisionRequestModel",
                decision_manager,
            )
        },
    ):
        assert repository.fetch_open_decisions_summary()["pending_count"] == 4

    gate_manager = MagicMock()
    gate_manager.filter.return_value.count.return_value = 2
    with patch.dict(
        sys.modules,
        {
            "apps.beta_gate.infrastructure.models": _model_module(
                "GateConfigModel",
                gate_manager,
            )
        },
    ):
        assert repository.fetch_risk_alerts_summary()["active_beta_gates"] == 2

    task_manager = MagicMock()
    task_manager.count.return_value = 10
    task_manager.exclude.return_value.count.return_value = 3
    task_manager.filter.return_value.count.side_effect = [1, 2]
    with patch.dict(
        sys.modules,
        {
            "apps.agent_runtime.infrastructure.models": _model_module(
                "AgentTaskModel",
                task_manager,
            )
        },
    ):
        result = repository.fetch_task_health_summary()
        assert result == {
            "status": "ok",
            "total_tasks": 10,
            "active_tasks": 3,
            "needs_human": 1,
            "failed_tasks": 2,
        }


def test_context_snapshot_extended_summaries_cover_all_supported_sources() -> None:
    """Ops, monitoring, decision, and research summary reads expose stable shapes."""
    repository = DjangoContextSnapshotRepository()
    observed_at = datetime(2026, 7, 25, tzinfo=UTC)

    regime_manager = MagicMock()
    regime_manager.order_by.return_value.first.return_value = SimpleNamespace(
        observed_at=observed_at
    )
    published_macro_values = [{"reporting_period": "2026-07-25"}]
    with patch.dict(
        sys.modules,
        {
            "apps.regime.infrastructure.models": _model_module(
                "RegimeLog",
                regime_manager,
            ),
        },
    ):
        with patch(
            "apps.data_center.application.public.list_latest_published_macro_values",
            return_value=published_macro_values,
        ):
            freshness = repository.fetch_data_freshness_summary()
        assert freshness["sources"]["regime"].startswith("2026-07-25")
        assert freshness["sources"]["macro"].startswith("2026-07-25")

    count_sources = [
        (
            "apps.events.infrastructure.event_store",
            "StoredEventModel",
            repository.fetch_event_bus_summary,
            "total_event_records",
        ),
        (
            "apps.ai_provider.infrastructure.models",
            "AIProviderConfig",
            repository.fetch_ai_provider_summary,
            "ai_providers_active",
        ),
        (
            "apps.simulated_trading.infrastructure.models",
            "SimulatedAccountModel",
            repository.fetch_simulated_account_summary,
            "active_simulated_accounts",
        ),
        (
            "apps.regime.infrastructure.models",
            "RegimeLog",
            repository.fetch_regime_history_summary,
            "history_records",
        ),
    ]
    for module_name, model_name, fetch, result_key in count_sources:
        manager = MagicMock()
        manager.count.return_value = 6
        manager.filter.return_value.count.return_value = 6
        with patch.dict(sys.modules, {module_name: _model_module(model_name, manager)}):
            assert fetch()[result_key] == 6

    audit_manager = MagicMock()
    audit_manager.order_by.return_value.first.return_value = SimpleNamespace(timestamp=observed_at)
    with patch.dict(
        sys.modules,
        {
            "apps.audit.infrastructure.models": _model_module(
                "OperationLogModel",
                audit_manager,
            )
        },
    ):
        assert repository.fetch_audit_freshness_summary()["audit"].startswith("2026-07-25")
        audit_manager.order_by.return_value.first.return_value = None
        assert repository.fetch_audit_freshness_summary()["status"] == "no_data"

    alert_manager = MagicMock()
    alert_manager.filter.return_value.count.side_effect = [4, 2]
    with patch.dict(
        sys.modules,
        {
            "apps.realtime.infrastructure.models": _model_module(
                "PriceAlertModel",
                alert_manager,
            )
        },
    ):
        result = repository.fetch_price_alert_summary()
        assert result["active_price_alerts"] == 4
        assert result["triggered_price_alerts"] == 2

    sentiment_manager = MagicMock()
    sentiment_manager.order_by.return_value.first.return_value = SimpleNamespace(
        created_at=observed_at
    )
    with patch.dict(
        sys.modules,
        {
            "apps.sentiment.infrastructure.models": _model_module(
                "SentimentIndexModel",
                sentiment_manager,
            )
        },
    ):
        assert repository.fetch_sentiment_freshness_summary()["sentiment"].startswith("2026-07-25")
        sentiment_manager.order_by.return_value.first.return_value = None
        assert repository.fetch_sentiment_freshness_summary()["status"] == "no_data"


def test_context_snapshot_lists_and_degradation_contracts() -> None:
    """Quota, position, signal, and unavailable sources must fail closed."""
    repository = DjangoContextSnapshotRepository()

    quota_manager = MagicMock()
    quota_manager.values.return_value.__getitem__.return_value = [{"quota_id": "q1"}]
    with patch.dict(
        sys.modules,
        {
            "apps.decision_rhythm.infrastructure.models": _model_module(
                "DecisionQuotaModel",
                quota_manager,
            )
        },
    ):
        assert repository.fetch_decision_quota_summary()["quotas"] == [{"quota_id": "q1"}]

    signal_manager = MagicMock()
    signal_manager.filter.return_value.count.return_value = 3
    signal_manager.filter.return_value.exclude.return_value.count.return_value = 2
    with patch.dict(
        sys.modules,
        {
            "apps.signal.infrastructure.models": _model_module(
                "InvestmentSignalModel",
                signal_manager,
            )
        },
    ):
        assert repository.fetch_pending_signal_summary()["pending_approval"] == 3
        assert repository.fetch_signal_invalidation_summary()["with_invalidation_logic"] == 2

    position_manager = MagicMock()
    position_manager.filter.return_value.values.return_value.__getitem__.return_value = [
        {"asset_code": "A", "shares": 10, "avg_cost": 2}
    ]
    with patch.dict(
        sys.modules,
        {
            "apps.account.infrastructure.models": _model_module(
                "PositionModel",
                position_manager,
            )
        },
    ):
        assert (
            repository.fetch_portfolio_position_summary(7)["top_positions"][0]["asset_code"] == "A"
        )

    assert _unavailable("source") == {
        "status": "unavailable",
        "source": "source",
        "error": "source_fetch_failed",
    }
    assert _invalid_input("source", "identifier_invalid")["status"] == "invalid_input"
    with patch.dict(sys.modules, {"apps.regime.infrastructure.models": SimpleNamespace()}):
        degraded = repository.fetch_regime_summary()
    assert degraded["status"] == "unavailable"
    assert degraded["source"] == "regime"
