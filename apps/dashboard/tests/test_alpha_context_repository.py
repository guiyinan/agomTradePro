from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.dashboard.infrastructure.repositories import (
    DashboardAlphaContextRepository,
    DashboardOverviewRepository,
    DashboardQueryRepository,
)


def _build_gateway(**overrides):
    defaults = {
        "get_stock_context_map": lambda codes: {},
        "resolve_asset": lambda code: None,
        "query_latest_quote": lambda asset_code: None,
        "list_actionable_alpha_candidates": lambda *, limit: [],
        "list_pending_execution_requests": lambda *, limit: [],
        "get_manual_override_trigger_ids": lambda: set(),
        "get_valuation_repair_snapshot_map": lambda codes: {},
        "get_policy_state": lambda: {"gate_level": "L0", "effective": False},
        "get_user_account_totals": lambda user_id: None,
        "list_user_positions": lambda **kwargs: [],
        "list_dashboard_accounts": lambda user_id: [],
        "get_user_performance_payload": lambda **kwargs: [],
        "get_alpha_ic_trends": lambda days: [],
        "get_latest_macro_indicator_value": lambda indicator_code: None,
        "get_position_detail_payload": lambda user_id, asset_code: None,
        "list_active_signal_payloads_by_asset": lambda **kwargs: [],
        "get_candidate_generation_context": lambda *, limit: {},
        "get_policy_environment": lambda user_id: (None, None, 0, []),
        "get_growth_series": lambda **kwargs: [],
        "get_inflation_series": lambda **kwargs: [],
        "get_primary_system_ai_provider_payload": lambda: None,
        "list_global_investment_rule_payloads": lambda: [],
        "get_portfolio_snapshot_performance_data": lambda portfolio_id: [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.django_db
def test_dashboard_alpha_context_loads_asset_and_quote_from_gateway():
    captured: dict[str, list[str]] = {"asset_codes": [], "quote_codes": []}

    class FakeResolveAssetUseCase:
        def execute(self, request):
            captured["asset_codes"].append(request.code)
            if request.code == "000001.SZ":
                return SimpleNamespace(
                    short_name="平安银行",
                    name="平安银行",
                    sector="银行",
                    industry="金融",
                    exchange="SZ",
                )
            return None

    class FakeQuoteUseCase:
        def execute(self, request):
            captured["quote_codes"].append(request.asset_code)
            if request.asset_code == "000001.SZ":
                return SimpleNamespace(
                    current_price=12.34,
                    volume=123456.0,
                    snapshot_at=datetime(2026, 4, 30, 9, 35, tzinfo=timezone.utc),
                    source="akshare",
                )
            return None

    gateway = _build_gateway(
        resolve_asset=lambda code: FakeResolveAssetUseCase().execute(SimpleNamespace(code=code)),
        query_latest_quote=(
            lambda asset_code: FakeQuoteUseCase().execute(SimpleNamespace(asset_code=asset_code))
        ),
    )

    context = DashboardAlphaContextRepository(gateway).load_stock_context(["000001.SZ"])

    assert context["000001.SZ"]["name"] == "平安银行"
    assert context["000001.SZ"]["sector"] == "银行"
    assert context["000001.SZ"]["market"] == "SZ"
    assert context["000001.SZ"]["close"] == pytest.approx(12.34)
    assert context["000001.SZ"]["volume"] == pytest.approx(123456.0)
    assert context["000001.SZ"]["quote_source"] == "akshare"
    assert "000001.SZ" in captured["asset_codes"]
    assert set(captured["asset_codes"]).issubset({"000001", "000001.SZ"})
    assert "000001.SZ" in captured["quote_codes"]
    assert set(captured["quote_codes"]).issubset({"000001", "000001.SZ"})


def test_dashboard_alpha_context_uses_gateway_for_valuation_repairs():
    repo = DashboardAlphaContextRepository(
        _build_gateway(
            get_valuation_repair_snapshot_map=lambda codes: {
                "000001.SZ": {
                    "phase": "repairing",
                    "signal": "watch",
                    "composite_percentile": 0.21,
                    "repair_progress": 0.65,
                    "repair_speed_per_30d": 0.12,
                    "estimated_days_to_target": 28,
                }
            },
        )
    )

    repair_map = repo._load_valuation_repair_map(["000001.SZ", ""])

    assert repair_map["000001.SZ"]["phase"] == "repairing"
    assert repair_map["000001.SZ"]["estimated_days_to_target"] == 28


def test_dashboard_alpha_context_uses_gateway_for_local_stock_context():
    gateway = _build_gateway(
        get_stock_context_map=lambda codes: {
            "000001.SZ": {
                "name": "平安银行",
                "sector": "银行",
                "market": "SZ",
                "trade_date": None,
                "report_date": None,
                "close": 11.11,
                "volume": 321.0,
                "roe": 12.3,
                "debt_ratio": 80.0,
                "revenue_growth": 15.6,
                "profit_growth": 18.2,
                "pe": 5.6,
                "pb": 0.72,
                "ps": 1.34,
                "dividend_yield": 4.5,
                "valuation_trade_date": None,
            }
        }
    )

    context = DashboardAlphaContextRepository(gateway).load_stock_context(["000001.SZ"])

    assert context["000001.SZ"]["name"] == "平安银行"
    assert context["000001.SZ"]["close"] == pytest.approx(11.11)
    assert context["000001.SZ"]["volume"] == pytest.approx(321.0)
    assert context["000001.SZ"]["roe"] == pytest.approx(12.3)
    assert context["000001.SZ"]["revenue_growth"] == pytest.approx(15.6)
    assert context["000001.SZ"]["profit_growth"] == pytest.approx(18.2)
    assert context["000001.SZ"]["pe"] == pytest.approx(5.6)
    assert context["000001.SZ"]["pb"] == pytest.approx(0.72)


def test_dashboard_alpha_context_uses_gateway_for_actionable_map():
    captured: dict[str, object] = {}

    actionable_map = DashboardAlphaContextRepository(
        _build_gateway(
            list_actionable_alpha_candidates=lambda *, limit: captured.update({"limit": limit})
            or [
                SimpleNamespace(asset_code="000001.SZ", confidence=0.91),
                SimpleNamespace(asset_code="600519.SH", confidence=0.88),
            ]
        )
    ).load_actionable_map()

    assert captured == {"limit": 200}
    assert set(actionable_map.keys()) == {"000001.SZ", "600519.SH"}


def test_dashboard_alpha_context_uses_gateway_for_pending_map():
    captured: dict[str, object] = {}

    pending_map = DashboardAlphaContextRepository(
        _build_gateway(
            list_pending_execution_requests=lambda *, limit: captured.update({"limit": limit})
            or [
                SimpleNamespace(asset_code="000001.SZ", request_id="req-1"),
                SimpleNamespace(asset_code="000001.SZ", request_id="req-2"),
                SimpleNamespace(asset_code="600519.SH", request_id="req-3"),
            ]
        )
    ).load_pending_map()

    assert captured == {"limit": 200}
    assert pending_map["000001.SZ"].request_id == "req-1"
    assert pending_map["600519.SH"].request_id == "req-3"


def test_dashboard_alpha_context_uses_gateway_for_policy_state():
    policy_state = DashboardAlphaContextRepository(
        _build_gateway(
            get_policy_state=lambda: {
                "gate_level": "L2",
                "effective": True,
                "event_date": "2026-04-30",
                "title": "政策强化",
                "policy_level": "P2",
            }
        )
    ).load_policy_state()

    assert policy_state == {
        "gate_level": "L2",
        "effective": True,
        "event_date": "2026-04-30",
        "title": "政策强化",
        "policy_level": "P2",
    }


def test_dashboard_overview_uses_gateway():
    repo = DashboardOverviewRepository(
        _build_gateway(
            get_user_account_totals=lambda user_id: {"total_assets": 100.0, "cash_balance": 20.0},
            list_dashboard_accounts=lambda user_id: [{"id": 1, "name": "主账户"}],
            list_user_positions=lambda **kwargs: [{"asset_code": "000001.SZ"}],
            get_user_performance_payload=lambda **kwargs: [
                {"date": "2026-04-30", "portfolio_value": 100.0}
            ],
        )
    )

    assert repo.get_user_simulated_account_totals(1) == {
        "total_assets": 100.0,
        "cash_balance": 20.0,
    }
    assert repo.get_dashboard_accounts(1) == [{"id": 1, "name": "主账户"}]
    assert repo.get_simulated_positions(1) == [{"asset_code": "000001.SZ"}]
    assert repo.get_simulated_positions_for_dashboard(1, account_id=1) == [
        {"asset_code": "000001.SZ"}
    ]
    assert repo.get_simulated_performance_data(user_id=1, account_id=None, days=30) == [
        {"date": "2026-04-30", "portfolio_value": 100.0}
    ]


def test_dashboard_query_repository_uses_gateway():
    repo = DashboardQueryRepository(
        _build_gateway(
            get_alpha_ic_trends=lambda days: [{"date": "2026-04-30", "ic": 0.12}],
            get_latest_macro_indicator_value=lambda indicator_code: 51.2,
            get_position_detail_payload=lambda user_id, asset_code: {
                "asset_code": asset_code,
                "quantity": 10.0,
            },
            list_active_signal_payloads_by_asset=lambda **kwargs: [
                {"direction": "LONG", "logic_desc": "test"}
            ],
            get_candidate_generation_context=lambda *, limit: {
                "active_triggers": [],
                "existing_trigger_ids": set(),
                "actionable_count": 2,
            },
        )
    )

    assert repo.get_alpha_ic_trends(30) == [{"date": "2026-04-30", "ic": 0.12}]
    assert repo.get_latest_macro_indicator_value("PMI") == 51.2
    assert repo.get_position_detail(1, "000001.SZ")["related_signals"] == [
        {"direction": "LONG", "logic_desc": "test"}
    ]
    assert repo.load_alpha_candidate_generation_context()["actionable_count"] == 2
