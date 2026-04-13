import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def admin_client(db):
    from django.contrib.auth import get_user_model
    from django.test import Client

    user = get_user_model().objects.create_user(
        username="adminuser",
        password="testpass123",
        email="admin@example.com",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_dashboard_alpha_stocks_json_endpoint_returns_contract(authenticated_client, monkeypatch):
    from apps.dashboard.interface import views

    monkeypatch.setattr(
        views,
        "_get_alpha_visualization_data",
        lambda top_n=10, ic_days=30, user=None: SimpleNamespace(
            stock_scores_meta={"provider_source": "cache"},
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_decision_plane_data",
        lambda max_candidates=5, max_pending=10: SimpleNamespace(
            actionable_candidates=[],
            pending_requests=[],
            alpha_actionable_count=0,
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_alpha_decision_chain_data",
        lambda top_n=10, ic_days=30, max_candidates=5, max_pending=10, user=None, alpha_visualization_data=None, decision_plane_data=None: SimpleNamespace(
            top_stocks=[
                {
                    "code": "600519.SH",
                    "name": "贵州茅台",
                    "score": 0.95,
                    "rank": 1,
                    "confidence": 0.91,
                    "source": "cache",
                    "asof_date": "2026-03-22",
                    "workflow_stage": "top_ranked",
                    "workflow_stage_label": "仅在 Alpha Top 排名",
                }
            ],
            overview={"top_ranked_count": 1},
        ),
    )

    response = authenticated_client.get("/api/dashboard/alpha/stocks/?format=json&top_n=5")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")

    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["top_n"] == 5
    assert payload["data"]["items"][0]["code"] == "600519.SH"


@pytest.mark.django_db
def test_equity_screen_page_contains_dashboard_alpha_navigation(authenticated_client):
    response = authenticated_client.get("/equity/screen/?source=dashboard-alpha")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/api/dashboard/alpha/stocks/?format=json&top_n=10" in content
    assert "系统自动推荐" in content
    assert "手动二次筛选" in content
    assert "/decision/workspace/?source=equity-screen&security_code=" in content


@pytest.mark.django_db
def test_dashboard_alpha_partial_contains_decision_workspace_actions(authenticated_client, monkeypatch):
    from apps.dashboard.interface import views

    monkeypatch.setattr(
        views,
        "_get_alpha_stock_scores_payload",
        lambda top_n=10, user=None: {
            "items": [
                {
                    "code": "600519.SH",
                    "name": "贵州茅台",
                    "score": 0.95,
                    "rank": 1,
                    "confidence": 0.91,
                    "source": "cache",
                    "asof_date": "2026-03-22",
                }
            ],
            "meta": {"provider_source": "cache"},
        },
    )

    response = authenticated_client.get("/dashboard/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/decision/workspace/?source=dashboard-alpha&security_code=" in content
    assert "加入观察" in content


@pytest.mark.django_db
def test_equity_screen_api_returns_displayable_items(authenticated_client, monkeypatch):
    from apps.equity.application import use_cases

    monkeypatch.setattr(
        use_cases.ScreenStocksUseCase,
        "execute",
        lambda self, request: use_cases.ScreenStocksResponse(
            success=True,
            regime="Recovery",
            stock_codes=["600519.SH"],
            items=[
                {
                    "rank": 1,
                    "code": "600519.SH",
                    "name": "贵州茅台",
                    "sector": "食品饮料",
                    "roe": 32.1,
                    "pe": 28.5,
                    "pb": 9.3,
                    "revenue_growth": 15.2,
                    "profit_growth": 17.8,
                    "score": None,
                    "source": "screen",
                }
            ],
            screening_criteria={"rule_name": "test"},
        ),
    )

    response = authenticated_client.post(
        "/api/equity/screen/",
        data={"regime": "Recovery", "max_count": 10},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["items"][0]["name"] == "贵州茅台"
    assert payload["items"][0]["sector"] == "食品饮料"


@pytest.mark.django_db
def test_equity_detail_page_uses_single_percentile_chart(authenticated_client):
    response = authenticated_client.get("/equity/detail/000001.SZ/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "createPercentileChart" in content
    assert "type: 'doughnut'" in content
    assert "cutout: '76%'" in content
    assert "peChartInstance.destroy" in content
    assert "valuation-chart-shell" in content
    assert "sortedRows = [...result.data].sort" in content
    assert "sortedNews = [...result.data].sort" in content
    assert 'fetchJsonOrThrowCompat(`/api/equity/regime-correlation/${stockCode}/`)' in content
    assert "loadRegimeCorrelation();" in content
    assert "fetchJsonOrThrowCompat('/api/pulse/current/')" in content
    assert "loadPulseContext();" in content
    assert "Pulse 战术环境" in content
    assert "Beta" in content
    assert "样本天数" in content
    assert "data.dcf_value.upside > 0 ? 'text-rise' : 'text-fall'" in content
    assert "const cls = v => v >= 0 ? 'text-inflow' : 'text-outflow';" in content
    assert "data-market-color-convention=" in content


@pytest.mark.django_db
def test_system_settings_page_contains_market_color_switch(admin_client):
    response = admin_client.get("/account/admin/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'name="market_color_convention"' in content
    assert "A股红涨绿跌" in content
    assert "美股绿涨红跌" in content
    assert "当前生效" in content


@pytest.mark.django_db
def test_system_settings_page_saves_market_color_convention(admin_client):
    from apps.account.infrastructure.models import SystemSettingsModel

    settings = SystemSettingsModel.get_settings()

    response = admin_client.post(
        "/account/admin/settings/",
        data={
            **({"require_user_approval": "on"} if settings.require_user_approval else {}),
            **({"auto_approve_first_admin": "on"} if settings.auto_approve_first_admin else {}),
            **({"default_mcp_enabled": "on"} if settings.default_mcp_enabled else {}),
            **({"allow_token_plaintext_view": "on"} if settings.allow_token_plaintext_view else {}),
            "market_color_convention": "us_market",
            "user_agreement_content": settings.user_agreement_content,
            "risk_warning_content": settings.risk_warning_content,
            "notes": settings.notes,
            "benchmark_code_map": "{}" if not settings.benchmark_code_map else json.dumps(settings.benchmark_code_map, ensure_ascii=False),
            "asset_proxy_code_map": "{}" if not settings.asset_proxy_code_map else json.dumps(settings.asset_proxy_code_map, ensure_ascii=False),
            "macro_index_catalog": "[]" if not settings.macro_index_catalog else json.dumps(settings.macro_index_catalog, ensure_ascii=False),
        },
    )

    assert response.status_code == 302
    settings.refresh_from_db()
    assert settings.market_color_convention == "us_market"


@pytest.mark.django_db
def test_equity_pool_page_uses_market_semantic_classes(authenticated_client):
    response = authenticated_client.get("/equity/pool/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "text-rise" in content
    assert "text-green" not in content


def test_market_visual_tokens_are_used_in_frontend_styles():
    target_files = [
        Path("static/css/design-tokens.css"),
        Path("static/css/equity.css"),
        Path("static/css/decision-workspace.css"),
        Path("static/css/main-workflow.css"),
        Path("core/templates/decision/workspace.html"),
        Path("core/templates/dashboard/index.html"),
        Path("core/templates/account/settings.html"),
        Path("core/templates/simulated_trading/my_trades.html"),
    ]

    expected_tokens = [
        "var(--color-rise)",
        "var(--color-fall)",
        "var(--color-rise-soft)",
        "var(--color-fall-soft)",
    ]

    for path in target_files:
        content = path.read_text(encoding="utf-8")
        assert any(token in content for token in expected_tokens), f"{path} should use market visual tokens"
