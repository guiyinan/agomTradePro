from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

import apps.terminal.application.tui_operator_services as operator_services


def _decision_source_fixture() -> dict[str, object]:
    """Synthetic owner evidence; these clocks are not live provider facts."""

    return {
        "status": "blocked",
        "must_not_use_for_decision": True,
        "blocked_reasons": [
            "510300.SH: quote_observation_from_future",
            "000300.SH: quote_fetch_from_future",
        ],
        "quotes": {
            "510300.SH": {
                "asset_code": "510300.SH",
                "snapshot_at": "2026-10-28T02:01:00+00:00",
                "fetched_at": "2026-10-28T02:02:00+00:00",
                "freshness_status": "future_observation",
                "must_not_use_for_decision": True,
                "blocked_reason": "quote_observation_from_future",
            },
            "000300.SH": {
                "asset_code": "000300.SH",
                "snapshot_at": "2026-10-28T01:58:00+00:00",
                "fetched_at": "2026-10-28T02:03:00+00:00",
                "freshness_status": "future_fetch",
                "must_not_use_for_decision": True,
                "blocked_reason": "quote_fetch_from_future",
            },
        },
        "market_thermometer": {
            "observed_at": "2026-10-27T07:00:00+00:00",
            "as_of_date": "2026-10-27",
            "snapshot_date": "2026-10-26",
        },
    }


@pytest.mark.parametrize("consumer", ["market", "governance"])
@pytest.mark.parametrize(
    ("observed_at", "expected_observation"),
    [
        (date(2026, 10, 27), "2026-10-27"),
        ("2026-10-27", "2026-10-27"),
        ("2026-10-27T07:00:00+00:00", "2026-10-27T07:00:00+00:00"),
    ],
)
def test_decision_consumers_keep_independent_owner_clocks_and_friendly_restrictions(
    monkeypatch: pytest.MonkeyPatch,
    consumer: str,
    observed_at: object,
    expected_observation: str,
) -> None:
    payload = _decision_source_fixture()
    payload["market_thermometer"] = {
        "observed_at": observed_at,
        "as_of_date": "2026-10-27",
        "snapshot_date": "2026-10-26",
    }
    checked_at = datetime(2026, 10, 28, 2, 0, tzinfo=UTC)
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)
    monkeypatch.setattr(operator_services.timezone, "now", lambda: checked_at)
    monkeypatch.setattr(operator_services, "get_active_stock_fact_coverage_payload", lambda: {})
    monkeypatch.setattr(operator_services, "get_market_thermometer_payload", lambda **kwargs: {})

    row = (
        operator_services._decision_data_market_row()
        if consumer == "market"
        else operator_services._data_center_governance_rows()[0]
    )

    assert row["must_not_use_for_decision"] is True
    assert row["observed_at"] == ""
    assert row["checked_at"] == checked_at.isoformat()
    assert row["thermometer_observed_at"] == expected_observation
    assert row["thermometer_as_of_date"] == "2026-10-27"
    assert row["thermometer_snapshot_date"] == "2026-10-26"
    assert row["blocked_reasons"] == payload["blocked_reasons"]
    assert row["quote_evidence"][0]["snapshot_at"] == "2026-10-28T02:01:00+00:00"
    assert row["quote_evidence"][1]["snapshot_at"] == "2026-10-28T01:58:00+00:00"
    assert row["quote_evidence"][1]["fetched_at"] == "2026-10-28T02:03:00+00:00"
    assert row["quote_evidence"][0]["blocked_reason"] == "quote_observation_from_future"
    assert row["quote_evidence"][1]["freshness_status"] == "future_fetch"
    assert "行情观测时间晚于本次判断时点" in row["blocking_reason"]
    assert "行情抓取时间晚于本次判断时点" in row["blocking_reason"]
    for key in ("blocking_reason", "quote_source_times"):
        assert "quote_observation_from_future" not in row[key]
        assert "quote_fetch_from_future" not in row[key]


@pytest.mark.parametrize("observed_at", ["2026-10-27T07:00:00", datetime(2026, 10, 27, 7)])
def test_thermometer_naive_datetime_is_not_downgraded_to_date(observed_at: object) -> None:
    from apps.terminal.application.tui_decision_data_presentation import (
        build_decision_data_evidence,
    )

    payload = _decision_source_fixture()
    payload["market_thermometer"] = {"observed_at": observed_at}
    result = build_decision_data_evidence(payload, checked_at=datetime(2026, 10, 28, tzinfo=UTC))
    assert result["thermometer_observed_at"] is None


def test_decision_evidence_keeps_missing_clocks_and_owner_provenance_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _decision_source_fixture()
    payload["quotes"] = {
        "510300.SH": {
            "snapshot_at": None,
            "fetched_at": None,
            "freshness_status": "unverified_observation",
            "must_not_use_for_decision": True,
            "blocked_reason": "行情缺少可验证的源观测与抓取时间，不得用于决策。",
        }
    }
    payload["market_thermometer"] = {"as_of_date": "2026-10-27"}
    payload["blocked_reasons"] = ["行情缺少可验证的源观测与抓取时间，不得用于决策。"]
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)

    row = operator_services._decision_data_market_row()

    assert row["quote_evidence"][0]["snapshot_at"] is None
    assert row["quote_evidence"][0]["fetched_at"] is None
    assert row["quote_evidence"][0]["freshness_status"] == "unverified_observation"
    assert row["thermometer_observed_at"] is None
    assert row["thermometer_as_of_date"] == "2026-10-27"
    assert "行情缺少可验证" in row["blocking_reason"]
    assert "未提供" in row["quote_source_times"]


@pytest.mark.parametrize("flag", [None, "false", 0])
def test_decision_consumer_does_not_advertise_malformed_owner_gate_as_reliable(
    monkeypatch: pytest.MonkeyPatch, flag: object
) -> None:
    payload = _decision_source_fixture()
    payload.update(status="ok", must_not_use_for_decision=flag, blocked_reasons=[])
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)

    row = operator_services._decision_data_market_row()

    assert row["must_not_use_for_decision"] is True
    assert row["severity"] == "blocked"
    assert "可靠" != row["reliability"]


@pytest.mark.parametrize("unknown_code", ["unrecognized_source_restriction", "E42", "future-code"])
def test_decision_unknown_reason_is_retained_but_not_used_as_user_copy(
    monkeypatch: pytest.MonkeyPatch,
    unknown_code: str,
) -> None:
    payload = _decision_source_fixture()
    payload["blocked_reasons"] = [f"510300.SH: {unknown_code}"]
    payload["quotes"] = {
        "510300.SH": {
            "must_not_use_for_decision": True,
            "blocked_reason": unknown_code,
        }
    }
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)
    row = operator_services._decision_data_market_row()
    assert row["quote_evidence"][0]["blocked_reason"] == unknown_code
    assert unknown_code not in row["blocking_reason"]
    assert "不可用于决策" in row["blocking_reason"]


def test_checked_at_sorting_is_explicit_and_legacy_domains_keep_their_clock() -> None:
    rows = [
        {"severity": "warning", "title": "legacy", "observed_at": "2026-10-28T01:00:00Z"},
        {
            "severity": "warning",
            "title": "decision",
            "observed_at": "",
            "checked_at": "2026-10-28T02:00:00Z",
        },
        {"severity": "blocked", "title": "blocked", "observed_at": "2026-10-27T01:00:00Z"},
    ]
    assert [r["title"] for r in sorted(rows, key=operator_services._governance_sort_key)] == [
        "blocked",
        "decision",
        "legacy",
    ]


@pytest.mark.parametrize(
    "clock", ["2026-10-28", "2026-10-28T02:01:00", datetime(2026, 10, 28, 2, 1)]
)
def test_decision_actual_source_clocks_require_timezone_without_fabrication(
    monkeypatch: pytest.MonkeyPatch,
    clock: object,
) -> None:
    payload = _decision_source_fixture()
    payload.update(status="ok", must_not_use_for_decision=False, blocked_reasons=[])
    payload["quotes"] = {
        "510300.SH": {
            "snapshot_at": clock,
            "fetched_at": "2026-10-28T02:02:00+00:00",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        }
    }
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)
    row = operator_services._decision_data_market_row()
    assert row["must_not_use_for_decision"] is True
    assert row["quote_evidence"][0]["snapshot_at"] is None
    assert row["thermometer_as_of_date"] == "2026-10-27"


@pytest.mark.parametrize("missing_field", ["quotes", "market_thermometer"])
@pytest.mark.parametrize("empty", [True, False])
def test_decision_missing_owner_evidence_cannot_advertise_reliability(
    monkeypatch: pytest.MonkeyPatch,
    missing_field: str,
    empty: bool,
) -> None:
    payload = _decision_source_fixture()
    payload.update(status="ok", must_not_use_for_decision=False, blocked_reasons=[])
    payload["quotes"] = {
        "510300.SH": {
            "snapshot_at": "2026-10-28T01:58:00+00:00",
            "fetched_at": "2026-10-28T01:59:00+00:00",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        }
    }
    if empty:
        payload[missing_field] = {}
    else:
        payload.pop(missing_field)
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)
    row = operator_services._decision_data_market_row()
    assert row["must_not_use_for_decision"] is True
    assert row["reliability"] == "不可用于决策"


def test_cached_decision_evidence_does_not_refresh_check_or_source_clocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_services.cache.clear()
    monkeypatch.setattr(
        operator_services, "get_decision_data_readiness_payload", _decision_source_fixture
    )
    monkeypatch.setattr(
        operator_services.timezone, "now", lambda: datetime(2026, 10, 28, 2, 0, tzinfo=UTC)
    )
    first = operator_services._cached_operator_payload(
        cache_key="test", builder=operator_services._decision_data_market_row
    )
    monkeypatch.setattr(
        operator_services.timezone, "now", lambda: datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
    )
    second = operator_services._cached_operator_payload(
        cache_key="test", builder=operator_services._decision_data_market_row
    )
    assert second == first
    assert second["checked_at"] == "2026-10-28T02:00:00+00:00"
    operator_services.cache.clear()


def test_decision_source_clock_does_not_reflect_non_clock_secret_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _decision_source_fixture()
    payload["quotes"] = {
        "510300.SH": {
            "snapshot_at": "https://user:secret@example.test/?api_key=private-token",
            "fetched_at": None,
            "freshness_status": "unverified_observation",
            "must_not_use_for_decision": True,
            "blocked_reason": "unknown_reason api_key=private-token",
        }
    }
    monkeypatch.setattr(operator_services, "get_decision_data_readiness_payload", lambda: payload)
    row = operator_services._decision_data_market_row()
    assert row["quote_evidence"][0]["snapshot_at"] is None
    assert "private-token" not in str(row)
    assert "example.test" not in str(row)


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
    operator_services.cache.clear()
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
        "_operator_home_preview_rows",
        lambda *, user, market_context: {
            "runtime": [
                _governance_row(
                    severity="blocked",
                    domain="runtime",
                    title="runtime blocked",
                    target_screen="api-library.runtime",
                    target_action_key="operator.governance.runtime_summary",
                    observed_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
                )
            ],
            "data-center": [
                _governance_row(
                    severity="warning",
                    domain="data-center",
                    title="freshness warning",
                    target_screen="api-library.data-center",
                    target_action_key="operator.governance.data_center_summary",
                    observed_at=datetime(2026, 7, 7, 8, 0, tzinfo=UTC),
                )
            ],
            "ai-provider": [
                _governance_row(
                    severity="warning",
                    domain="ai-provider",
                    title="provider warning",
                    target_screen="ai-ops.providers",
                    target_action_key="operator.governance.ai_provider_summary",
                    observed_at=datetime(2026, 7, 7, 7, 0, tzinfo=UTC),
                )
            ],
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


def test_regime_market_row_preserves_stale_decision_block(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "get_regime_current_payload",
        lambda **kwargs: {
            "data": {
                "dominant_regime": "Recovery",
                "confidence": 0.36,
                "observed_at": "2026-06-30",
                "is_stale": True,
                "must_not_use_for_decision": True,
                "blocked_reason": "宏观观测已超过允许时效。",
                "warnings": ["数据过期"],
            }
        },
    )

    row = operator_services._regime_market_row()

    assert row["area"] == "宏观象限"
    assert row["severity"] == "blocked"
    assert row["freshness"] == "已过期"
    assert row["reliability"] == "不可用于决策"
    assert row["observed_at"] == "2026-06-30"
    assert row["summary"] == "宏观观测已超过允许时效。"
    assert row["must_not_use_for_decision"] is True


def test_operator_home_area_labels_use_canonical_user_vocabulary(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "get_regime_current_payload",
        lambda **kwargs: {
            "data": {
                "dominant_regime": "Recovery",
                "confidence": 0.8,
                "observed_at": "2026-08-27",
            }
        },
    )
    monkeypatch.setattr(
        operator_services,
        "get_policy_status_payload",
        lambda **kwargs: {"current_level": "P0", "as_of_date": "2026-08-27"},
    )
    monkeypatch.setattr(
        operator_services,
        "GetLatestPulseUseCase",
        lambda: SimpleNamespace(execute=lambda **kwargs: None),
    )
    monkeypatch.setattr(
        operator_services,
        "get_decision_data_readiness_payload",
        lambda: {"status": "ready", "must_not_use_for_decision": False},
    )
    monkeypatch.setattr(
        operator_services,
        "get_account_diagnostic_summary",
        lambda: {"open_position_count": 0, "portfolio_count": 0},
    )
    monkeypatch.setattr(
        operator_services,
        "get_signal_diagnostic_summary",
        lambda: {"active_count": 0, "invalidated_count": 0},
    )

    market_rows = operator_services._market_context_rows()
    assert [row["area"] for row in market_rows] == [
        "宏观象限",
        "政策",
        "脉搏",
        "决策数据",
    ]
    assert market_rows[0]["status"] == "复苏"
    assert market_rows[0]["status_code"] == "Recovery"
    assert market_rows[0]["freshness"] == "阈值内"
    assert [row["area"] for row in operator_services._account_signal_rows()] == [
        "账户",
        "信号",
    ]


def test_policy_market_row_presents_evaluation_date_without_claiming_freshness(monkeypatch):
    previous_date = date.today() - timedelta(days=1)
    monkeypatch.setattr(
        operator_services,
        "get_policy_status_payload",
        lambda **kwargs: {
            "current_level": "P0",
            "is_intervention_active": False,
            "as_of_date": previous_date.isoformat(),
        },
    )

    row = operator_services._policy_market_row()

    assert row["freshness"] == "历史截面"
    assert row["reliability"] == "状态可用"
    assert row["observed_at"] == previous_date.isoformat()
    assert "新鲜" not in str(row)


def test_pulse_market_row_blocks_snapshot_beyond_owned_age_threshold(monkeypatch):
    stale_snapshot = SimpleNamespace(
        observed_at=date.today() - timedelta(days=9),
        regime_strength="strong",
        transition_warning=False,
        is_reliable=True,
        data_source="calculated",
        stale_indicator_count=0,
    )
    monkeypatch.setattr(
        operator_services,
        "GetLatestPulseUseCase",
        lambda: SimpleNamespace(execute=lambda **kwargs: stale_snapshot),
    )

    row = operator_services._pulse_market_row()

    assert row["severity"] == "blocked"
    assert row["freshness"] == "已过期"
    assert row["reliability"] == "不可用于决策"
    assert row["must_not_use_for_decision"] is True
    assert "仅供诊断" in row["summary"]


def test_pulse_market_row_blocks_current_snapshot_with_stale_source_indicators(monkeypatch):
    """A current aggregate date cannot reheat stale Pulse source indicators."""

    stale_source_snapshot = SimpleNamespace(
        observed_at=date.today(),
        regime_strength="moderate",
        transition_warning=False,
        is_reliable=True,
        data_source="calculated",
        stale_indicator_count=1,
    )
    monkeypatch.setattr(
        operator_services,
        "GetLatestPulseUseCase",
        lambda: SimpleNamespace(execute=lambda **kwargs: stale_source_snapshot),
    )

    row = operator_services._pulse_market_row()

    assert row["severity"] == "blocked"
    assert row["freshness"] == "源指标过期"
    assert row["reliability"] == "不可用于决策"
    assert row["must_not_use_for_decision"] is True


def test_regime_market_row_translates_machine_blocking_reason(monkeypatch):
    monkeypatch.setattr(
        operator_services,
        "get_regime_current_payload",
        lambda **kwargs: {
            "data": {
                "dominant_regime": "Unknown",
                "is_stale": True,
                "must_not_use_for_decision": True,
                "blocked_reason": "regime_data_unavailable",
            }
        },
    )

    row = operator_services._regime_market_row()

    assert row["status"] == "未知"
    assert row["status_code"] == "Unknown"
    assert row["summary"] == "当前没有可用的宏观象限数据。"
    assert row["blocking_reason"] == "当前没有可用的宏观象限数据。"
    assert row["blocking_reason_code"] == "regime_data_unavailable"


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
                observed_at=datetime(2026, 7, 7, 8, 0, tzinfo=UTC),
            ),
            _governance_row(
                severity="warning",
                domain="runtime",
                title="runtime newer",
                target_screen="api-library.runtime",
                target_action_key="operator.governance.runtime_summary",
                observed_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
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
                observed_at=datetime(2026, 7, 7, 7, 0, tzinfo=UTC),
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


def test_operator_governance_queue_prefers_stale_global_badges(monkeypatch):
    """Global badge polling must not synchronously rebuild an expensive stale queue."""

    operator_services.cache.clear()
    user = SimpleNamespace(pk=42)
    cache_key = operator_services._operator_governance_cache_key(user=user, domain="")
    stale_payload = {
        "status": "warning",
        "items": [{"severity": "warning", "title": "cached warning"}],
        "total": 1,
        "summary": {"warning": 1},
    }
    operator_services.cache.set(
        f"{cache_key}:stale",
        stale_payload,
        operator_services.OPERATOR_GOVERNANCE_STALE_TTL_SECONDS,
    )
    monkeypatch.setattr(
        operator_services,
        "_runtime_governance_rows",
        lambda: (_ for _ in ()).throw(AssertionError("stale badges should be returned")),
    )

    payload = operator_services.build_operator_governance_queue_payload(user=user)

    assert payload == stale_payload


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
            "quotes": {},
            "market_thermometer": {},
        },
    )
    monkeypatch.setattr(
        operator_services,
        "get_market_thermometer_payload",
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


def test_operator_reason_redacts_credentials() -> None:
    """Operator-facing failure reasons never publish provider credentials."""

    reason = operator_services._first_text(
        "provider failed dsn=postgresql://user:secret@database.internal/runtime"
    )

    assert "secret" not in reason
    assert "***" in reason


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
                    created_at=datetime(2026, 7, 7, 10, 0, tzinfo=UTC),
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
        "get_active_runtime_profile",
        lambda environment: SimpleNamespace(environment=environment),
    )
    monkeypatch.setattr(
        operator_services,
        "get_active_storage_budget",
        lambda: SimpleNamespace(),
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

    assert len(rows) == 3
    assert rows[0]["title"] == "Runtime Profile 与容量策略"
    assert rows[0]["severity"] == "ok"
    assert rows[0]["target_action_key"] == "operator.governance.config_center_summary"
    assert rows[1]["title"] == "Qlib Runtime 与当前模型"
    assert rows[1]["severity"] == "ok"
    assert rows[1]["target_action_key"] == "config_center.qlib_runtime"
    assert rows[2]["title"] == "训练记录与本地数据滞后"
    assert rows[2]["severity"] == "warning"
    assert rows[2]["blocking_reason"] == "本地 Qlib 数据滞后 7 天。"
