"""Safety regressions for Agent Runtime context snapshot persistence reads."""

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.agent_runtime.application.facades.base import BaseContextFacade
from apps.agent_runtime.application.facades.decision import DecisionTaskFacade
from apps.agent_runtime.application.facades.execution import ExecutionTaskFacade
from apps.agent_runtime.application.facades.monitoring import MonitoringTaskFacade
from apps.agent_runtime.application.facades.ops import OpsTaskFacade
from apps.agent_runtime.infrastructure.context_snapshot_repository import (
    DjangoContextSnapshotRepository,
)


def test_repository_failure_is_redacted_from_payload_and_log(monkeypatch, caplog) -> None:
    from apps.regime.infrastructure.models import RegimeLog

    def fail_query(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("postgresql://user:secret-password@host/db")

    monkeypatch.setattr(RegimeLog._default_manager, "order_by", fail_query)

    summary = DjangoContextSnapshotRepository().fetch_regime_summary()

    assert summary == {
        "status": "unavailable",
        "source": "regime",
        "error": "source_fetch_failed",
    }
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"


def test_active_signal_rows_are_projected_without_mutating_orm_values(monkeypatch) -> None:
    from apps.signal.infrastructure.models import InvestmentSignalModel

    created_at = datetime(2026, 7, 28, 9, 30, tzinfo=UTC)

    class FakeQuerySet:
        def count(self) -> int:
            return 1

        def order_by(self, *_fields: str) -> "FakeQuerySet":
            return self

        def __getitem__(self, _key: object) -> "FakeQuerySet":
            return self

        def values(self, *_fields: str) -> list[dict[str, object]]:
            return [
                {
                    "id": 7,
                    "asset_code": "000001.SZ",
                    "direction": "LONG",
                    "status": "approved",
                    "created_at": created_at,
                }
            ]

    monkeypatch.setattr(
        InvestmentSignalModel._default_manager,
        "filter",
        lambda **_kwargs: FakeQuerySet(),
    )

    summary = DjangoContextSnapshotRepository().fetch_active_signals_summary()

    assert summary["active_count"] == 1
    assert summary["recent"] == [
        {
            "id": 7,
            "asset_code": "000001.SZ",
            "direction": "LONG",
            "status": "approved",
            "created_at": "2026-07-28T09:30:00+00:00",
        }
    ]


def test_freshness_reports_degraded_when_one_source_fails(monkeypatch, caplog) -> None:
    from apps.macro.infrastructure.models import MacroIndicator
    from apps.regime.infrastructure.models import RegimeLog

    def fail_regime(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database password=secret-password")

    monkeypatch.setattr(RegimeLog._default_manager, "order_by", fail_regime)
    monkeypatch.setattr(
        MacroIndicator._default_manager,
        "order_by",
        lambda *_fields: SimpleNamespace(
            first=lambda: SimpleNamespace(published_at=date(2026, 7, 28))
        ),
    )

    summary = DjangoContextSnapshotRepository().fetch_data_freshness_summary()

    assert summary == {
        "status": "degraded",
        "sources": {"regime": "unavailable", "macro": "2026-07-28"},
    }
    assert "secret-password" not in caplog.text


@pytest.mark.parametrize("portfolio_id", [0, -1, True, "1", None])
def test_invalid_portfolio_id_is_rejected_before_orm(portfolio_id: object) -> None:
    summary = DjangoContextSnapshotRepository().fetch_portfolio_position_summary(portfolio_id)

    assert summary == {
        "status": "invalid_input",
        "source": "account",
        "error": "portfolio_id_invalid",
    }


def test_base_facade_exception_log_is_redacted(caplog) -> None:
    def fail_fetch() -> dict[str, object]:
        raise RuntimeError("database password=secret-password")

    summary = BaseContextFacade(context_repository=MagicMock())._safe_fetch(
        "regime",
        fail_fetch,
    )

    assert summary["error"] == "source_fetch_failed"
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"


@pytest.mark.parametrize(
    ("facade_type", "base_method", "detail_method", "facade_method"),
    [
        (
            OpsTaskFacade,
            "fetch_task_health_summary",
            "fetch_event_bus_summary",
            "fetch_task_health_summary",
        ),
        (
            MonitoringTaskFacade,
            "fetch_risk_alerts_summary",
            "fetch_price_alert_summary",
            "fetch_risk_alerts_summary",
        ),
        (
            ExecutionTaskFacade,
            "fetch_portfolio_summary",
            "fetch_portfolio_position_summary",
            "fetch_portfolio_summary",
        ),
        (
            ExecutionTaskFacade,
            "fetch_risk_alerts_summary",
            "fetch_simulated_account_summary",
            "fetch_risk_alerts_summary",
        ),
        (
            DecisionTaskFacade,
            "fetch_open_decisions_summary",
            "fetch_decision_quota_summary",
            "fetch_open_decisions_summary",
        ),
    ],
)
def test_specialized_facade_detail_failures_are_redacted(
    caplog,
    facade_type: type[BaseContextFacade],
    base_method: str,
    detail_method: str,
    facade_method: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    repository = MagicMock()
    base_payload = {"status": "ok"}
    if base_method == "fetch_portfolio_summary":
        base_payload["portfolio_id"] = 1
    getattr(repository, base_method).return_value = base_payload
    getattr(repository, detail_method).side_effect = RuntimeError(
        "redis://user:secret-password@host/0"
    )

    summary = getattr(facade_type(context_repository=repository), facade_method)()

    assert summary["status"] == "ok"
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"
