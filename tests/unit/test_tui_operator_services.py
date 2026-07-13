from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import apps.terminal.application.tui_operator_services as operator_services


def _governance_row(
    *,
    severity: str,
    domain: str,
    title: str,
    target_screen: str,
    target_action_key: str,
    observed_at: datetime,
) -> dict[str, str]:
    return operator_services._governance_row(
        severity=severity,
        domain=domain,
        title=title,
        status=severity,
        blocking_reason=title,
        next_action="next",
        target_screen=target_screen,
        target_action_key=target_action_key,
        observed_at=observed_at,
    )


def test_operator_home_payload_exposes_fixed_sections_and_badges(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "_decision_queue_rows",
        lambda: [{"severity": "ok", "title": "today", "status": "CLEAR"}],
    )
    monkeypatch.setattr(
        operator_services,
        "_market_context_rows",
        lambda: [{"severity": "warning", "area": "Regime", "status": "WATCH"}],
    )
    monkeypatch.setattr(
        operator_services,
        "_account_signal_rows",
        lambda: [{"severity": "ok", "area": "Accounts", "status": "READY"}],
    )
    monkeypatch.setattr(
        operator_services,
        "build_operator_governance_queue_payload",
        lambda *, user, domain="": {
            "items": [
                _governance_row(
                    severity="blocked",
                    domain="runtime",
                    title="runtime blocked",
                    target_screen="api-library.runtime",
                    target_action_key="operator.governance.runtime_summary",
                    observed_at=datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc),
                ),
                _governance_row(
                    severity="warning",
                    domain="data-center",
                    title="freshness warning",
                    target_screen="api-library.data-center",
                    target_action_key="operator.governance.data_center_summary",
                    observed_at=datetime(2026, 7, 7, 8, 0, tzinfo=timezone.utc),
                ),
                _governance_row(
                    severity="warning",
                    domain="ai-provider",
                    title="provider warning",
                    target_screen="ai-ops.providers",
                    target_action_key="operator.governance.ai_provider_summary",
                    observed_at=datetime(2026, 7, 7, 7, 0, tzinfo=timezone.utc),
                ),
            ],
            "total": 3,
            "summary": {"blocked": 1, "warning": 2},
            "status": "blocked",
        },
    )

    payload = operator_services.build_operator_home_payload(user=SimpleNamespace())

    assert payload["status"] == "blocked"
    assert payload["decision_queue"]["total"] == 1
    assert payload["market_context"]["status"] == "warning"
    assert payload["account_signal_summary"]["status"] == "ok"
    assert payload["system_exception_summary"]["rows"][0]["target_screen"] == "api-library.runtime"
    assert payload["data_task_summary"]["badge"]["warning_count"] == 1
    assert payload["ai_config_summary"]["rows"][0]["target_action_key"] == (
        "operator.governance.ai_provider_summary"
    )


def test_operator_governance_queue_sorts_by_severity_then_recent(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "_runtime_governance_rows",
        lambda: [
            _governance_row(
                severity="warning",
                domain="runtime",
                title="runtime older",
                target_screen="api-library.runtime",
                target_action_key="operator.governance.runtime_summary",
                observed_at=datetime(2026, 7, 7, 8, 0, tzinfo=timezone.utc),
            ),
            _governance_row(
                severity="warning",
                domain="runtime",
                title="runtime newer",
                target_screen="api-library.runtime",
                target_action_key="operator.governance.runtime_summary",
                observed_at=datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc),
            ),
        ],
    )
    monkeypatch.setattr(
        operator_services,
        "_data_center_governance_rows",
        lambda: [
            _governance_row(
                severity="blocked",
                domain="data-center",
                title="freshness blocked",
                target_screen="api-library.data-center",
                target_action_key="operator.governance.data_center_summary",
                observed_at=datetime(2026, 7, 7, 7, 0, tzinfo=timezone.utc),
            )
        ],
    )
    monkeypatch.setattr(operator_services, "_ai_provider_governance_rows", lambda *, user: [])
    monkeypatch.setattr(operator_services, "_agent_runtime_governance_rows", lambda: [])
    monkeypatch.setattr(operator_services, "_account_settings_governance_rows", lambda: [])
    monkeypatch.setattr(operator_services, "_config_center_governance_rows", lambda *, user: [])

    payload = operator_services.build_operator_governance_queue_payload(user=SimpleNamespace())

    assert [item["title"] for item in payload["items"][:3]] == [
        "freshness blocked",
        "runtime newer",
        "runtime older",
    ]
    assert payload["summary"]["blocked"] == 1
    assert payload["summary"]["warning"] == 2


def test_data_center_governance_rows_map_freshness_and_coverage(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "get_active_stock_fact_coverage_payload",
        lambda: {
            "status": "warning",
            "universe_quality": {"issues": ["coverage gap"]},
            "domains": {},
        },
    )
    monkeypatch.setattr(
        operator_services,
        "get_decision_data_readiness_payload",
        lambda: {
            "status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reasons": ["freshness expired"],
        },
    )
    monkeypatch.setattr(
        operator_services,
        "load_market_thermometer_payload",
        lambda **kwargs: {
            "status": "warning",
            "must_not_use_for_decision": True,
            "blocked_reason": "thermometer stale",
        },
    )

    rows = operator_services._data_center_governance_rows()

    assert rows[0]["severity"] == "blocked"
    assert rows[0]["target_screen"] == "api-library.data-center"
    assert rows[0]["target_action_key"] == "operator.governance.data_center_summary"
    assert rows[0]["blocking_reason"] == "freshness expired"
    assert rows[1]["blocking_reason"] == "coverage gap"
    assert rows[2]["severity"] == "warning"


def test_ai_provider_governance_rows_map_provider_failures_and_quota(monkeypatch):
    class FakeListProvidersUseCase:
        def execute(self, **kwargs):
            return []

    class FakeOverallStatsUseCase:
        def execute(self):
            return SimpleNamespace(total_providers=2)

    class FakeUsageLogsUseCase:
        def execute(self, **kwargs):
            return [
                SimpleNamespace(
                    provider_name="deepseek",
                    created_at=datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc),
                )
            ]

    class FakeFallbackQuotaUseCase:
        def execute(self, **kwargs):
            return SimpleNamespace(is_active=True, daily_remaining=0, monthly_remaining=2)

    monkeypatch.setattr(operator_services, "ListProvidersUseCase", FakeListProvidersUseCase)
    monkeypatch.setattr(operator_services, "GetOverallStatsUseCase", FakeOverallStatsUseCase)
    monkeypatch.setattr(operator_services, "ListUsageLogsUseCase", FakeUsageLogsUseCase)
    monkeypatch.setattr(operator_services, "GetUserFallbackQuotaUseCase", FakeFallbackQuotaUseCase)
    monkeypatch.setattr(
        operator_services,
        "get_ai_capability_surface_status_payload",
        lambda: {"status": "incomplete", "detail": "mcp missing"},
    )

    rows = operator_services._ai_provider_governance_rows(
        user=SimpleNamespace(is_authenticated=True)
    )

    provider_row = next(row for row in rows if row["title"] == "AI 服务商可用性")
    failure_row = next(row for row in rows if row["title"] == "AI 调用失败摘要")
    quota_row = next(row for row in rows if row["title"] == "AI 配额与兜底额度")
    capability_row = next(row for row in rows if row["domain"] == "ai-capability")

    assert provider_row["severity"] == "blocked"
    assert provider_row["target_screen"] == "ai-ops.providers"
    assert failure_row["severity"] == "warning"
    assert "deepseek" in failure_row["blocking_reason"]
    assert quota_row["severity"] == "warning"
    assert capability_row["target_action_key"] == "auto.api.get.api.prompt.chat.providers"


def test_config_center_governance_rows_use_lightweight_runtime_summary(monkeypatch):
    class FakeModelRegistryRepository:
        def get_active_model(self):
            return SimpleNamespace(model_name="qlib-demo")

    monkeypatch.setattr(
        operator_services,
        "get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": "/tmp/qlib"},
    )
    monkeypatch.setattr(
        operator_services,
        "get_qlib_model_registry_repository",
        lambda: FakeModelRegistryRepository(),
    )
    monkeypatch.setattr(
        operator_services,
        "inspect_latest_trade_date",
        lambda provider_uri: date(2026, 7, 1),
    )
    monkeypatch.setattr(
        operator_services.timezone,
        "localdate",
        lambda: date(2026, 7, 8),
    )
    monkeypatch.setattr(operator_services, "has_qlib_training_runs", lambda: False)

    rows = operator_services._config_center_governance_rows(
        user=SimpleNamespace(is_staff=True, is_superuser=False)
    )

    assert len(rows) == 2
    assert rows[0]["severity"] == "ok"
    assert rows[0]["target_action_key"] == "config_center.qlib_runtime"
    assert rows[1]["severity"] == "warning"
    assert rows[1]["blocking_reason"] == "本地 Qlib 数据滞后 7 天。"
