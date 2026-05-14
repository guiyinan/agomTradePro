from pathlib import Path


def test_high_risk_templates_use_shared_fetch_helpers():
    templates = [
        Path("core/templates/prompt/manage.html"),
        Path("core/templates/terminal/config.html"),
        Path("core/templates/equity/detail.html"),
        Path("core/templates/equity/pool.html"),
        Path("core/templates/equity/valuation_repair.html"),
        Path("core/templates/factor/calculate.html"),
        Path("core/templates/factor/portfolios.html"),
        Path("core/templates/backtest/create.html"),
        Path("core/templates/backtest/list.html"),
        Path("core/templates/backtest/detail.html"),
        Path("core/templates/decision/workspace.html"),
    ]

    banned_patterns = [
        "await response.json()",
        "await res.json()",
        "await resp.json()",
        ".then(r => r.json())",
    ]

    for template in templates:
        content = template.read_text(encoding="utf-8")
        assert "window.fetchJsonOrThrow" in content or "window.assertOkResponse" in content
        for pattern in banned_patterns:
            assert pattern not in content, f"{template} still contains unsafe JSON parsing pattern: {pattern}"


def test_exit_chain_templates_use_shared_dashboard_detail_urls():
    templates_with_expected_placeholders = {
        Path("core/templates/dashboard/main_workflow_panel.html"): "dashboard_detail_url",
        Path("core/templates/dashboard/alpha_history.html"): "current_exit_dashboard_url",
        Path("core/templates/decision/workspace.html"): "dashboard_detail_url",
    }

    banned_patterns = [
        "/dashboard/?alpha_scope=portfolio&exit_asset_code=",
        "/dashboard/?alpha_scope={{",
    ]

    for template, placeholder in templates_with_expected_placeholders.items():
        content = template.read_text(encoding="utf-8")
        assert placeholder in content, f"{template} should use shared dashboard detail url placeholder"
        for pattern in banned_patterns:
            assert pattern not in content, f"{template} still hardcodes dashboard exit detail link: {pattern}"


def test_workspace_entrypoints_use_canonical_bridge_params_and_keep_legacy_compat():
    alpha_trigger_content = Path(
        "apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html"
    ).read_text(encoding="utf-8")
    workspace_content = Path("core/templates/decision/workspace.html").read_text(
        encoding="utf-8"
    )

    assert "security_code: assetCode" in alpha_trigger_content
    assert "action: direction" in alpha_trigger_content
    assert "step: '6'" in alpha_trigger_content
    assert "execute_request=" not in alpha_trigger_content
    assert "asset_code=${assetCode}" not in alpha_trigger_content
    assert "direction=${direction}" not in alpha_trigger_content

    assert "workspaceParams.get('security_code') || workspaceParams.get('asset_code') || ''" in workspace_content
    assert "workspaceParams.get('action') || workspaceParams.get('direction') || ''" in workspace_content
    assert "workspaceParams.get('execute_request') ? 'alpha-trigger-execute' : ''" in workspace_content
    assert "getUserActionText(action, label = '')" in workspace_content
    assert "rec.user_action_label" in workspace_content
    assert "updated?.user_action_label" in workspace_content


def test_dashboard_and_equity_workspace_entrypoints_use_canonical_builders():
    main_workflow_content = Path(
        "core/templates/dashboard/main_workflow_panel.html"
    ).read_text(encoding="utf-8")
    alpha_ranking_content = Path(
        "core/templates/dashboard/alpha_ranking.html"
    ).read_text(encoding="utf-8")
    equity_screen_content = Path("core/templates/equity/screen.html").read_text(
        encoding="utf-8"
    )

    assert "decision_workspace_url" in main_workflow_content
    assert "decision_workspace_primary_url" in main_workflow_content
    assert "?source=dashboard-alpha&security_code=" not in main_workflow_content
    assert "?source=dashboard-workflow&security_code=" not in main_workflow_content
    assert "?source=dashboard-pending&security_code=" not in main_workflow_content

    assert "{{ stock.decision_workspace_url }}" in alpha_ranking_content
    assert "?source=dashboard-alpha&security_code=" not in alpha_ranking_content

    assert "function buildDecisionWorkspaceUrl(securityCode" in equity_screen_content
    assert "params.set('security_code'" in equity_screen_content
    assert "params.set('action'" in equity_screen_content
    assert "/decision/workspace/?source=equity-screen&security_code=${encodeURIComponent(item.code || '')}" not in equity_screen_content
    assert "&action=watch" not in equity_screen_content
    assert "&action=adopt" not in equity_screen_content


def test_equity_detail_uses_single_asset_realtime_endpoint_and_renders_price_timestamp():
    content = Path("core/templates/equity/detail.html").read_text(encoding="utf-8")

    assert 'id="detailPriceTimestamp"' in content
    assert "loadRealtimePrice()" in content
    assert "/api/data-center/prices/quotes/?asset_code=${encodeURIComponent(stockCode)}" in content
    assert "updatePriceTimestamp(quote.snapshot_at || quote.timestamp, '行情快照时间')" in content
    assert "document.getElementById('detailPriceTimestamp').textContent = '实时价格不可用'" in content
    assert "setFallbackClosePrice(latest.price, latest.trade_date)" in content
    assert "updatePriceTimestamp(tradeDate, '上一交易日收盘')" in content
    assert '上一交易日收盘不可用' in content
    assert '最新市价' in content
    assert "second: '2-digit'" in content
    assert "fetchJsonOrThrowCompat('/api/realtime/prices/', {" not in content
    assert 'fetchJsonOrThrowCompat(`/api/realtime/prices/${stockCode}/`)' not in content
    assert "updatePriceTimestamp(latest.updated_at || latest.trade_date, '估值数据时间')" not in content
    assert '{% static \'js/echarts.min.js\' %}' in content
    assert Path("static/js/echarts.min.js").exists()
    assert 'data-technical-timeframe="intraday"' in content
    assert 'data-technical-timeframe="day"' in content
    assert 'id="technicalChart"' in content
    assert "function buildTechnicalRequest(timeframe)" in content
    assert '/api/equity/intraday/${stockCode}/' in content
    assert '/api/equity/technical/${stockCode}/?timeframe=${timeframe}&lookback_days=${technicalLookbackDays[timeframe] || technicalLookbackDays.day}' in content
    assert "let technicalRequestToken = 0;" in content
    assert "let technicalRequestController = null;" in content
    assert "const technicalChartCache = new Map();" in content
    assert "const requestToken = ++technicalRequestToken;" in content
    assert "const cachedPayload = getCachedTechnicalPayload(timeframe);" in content
    assert "technicalRequestController.abort();" in content
    assert "function warmTechnicalChartCache()" in content
    assert "if (requestToken !== technicalRequestToken || timeframe !== activeTechnicalTimeframe)" in content
    assert '{{ market_session_profile|json_script:"equity-detail-market-session" }}' in content
    assert "const marketSessionProfile = JSON.parse(" in content
    assert "function isMarketTradingSession(profile, now = new Date())" in content
    assert "function resolveInitialTechnicalTimeframe(profile, now = new Date())" in content
    assert "return profile.default_timeframe_out_of_session || 'intraday';" in content
    assert "activeTechnicalTimeframe = resolveInitialTechnicalTimeframe(marketSessionProfile);" in content
    assert 'class="btn btn-secondary technical-timeframe-btn active" data-technical-timeframe="intraday"' not in content
    assert "timeZone: 'Asia/Shanghai'" not in content


def test_equity_detail_bootstraps_after_dom_ready_and_guards_chartjs_loading():
    content = Path("core/templates/equity/detail.html").read_text(encoding="utf-8")

    assert "function initializeDetailPage()" in content
    assert "document.addEventListener('DOMContentLoaded', initializeDetailPage, { once: true });" in content
    assert "const ChartConstructor = window.Chart;" in content
    assert "Chart.js 未就绪，跳过估值分位图渲染:" in content


def test_equity_detail_loads_regime_correlation_from_dedicated_api():
    content = Path("core/templates/equity/detail.html").read_text(encoding="utf-8")

    assert 'fetchJsonOrThrowCompat(`/api/equity/regime-correlation/${stockCode}/`)' in content
    assert "function loadRegimeCorrelation()" in content
    assert "function renderRegimeCorrelationMessage(message)" in content
    assert "loadRegimeCorrelation();" in content
    assert "<th>Beta</th>" in content
    assert "<th>样本天数</th>" in content


def test_equity_detail_loads_pulse_context_from_dedicated_api():
    content = Path("core/templates/equity/detail.html").read_text(encoding="utf-8")

    assert "Pulse 战术环境" in content
    assert "function loadPulseContext()" in content
    assert "function updatePulseCard(data)" in content
    assert "function renderPulseMessage(message)" in content
    assert "fetchJsonOrThrowCompat('/api/pulse/current/')" in content
    assert "loadPulseContext();" in content


def test_wait_rsshub_exits_non_zero_on_timeout():
    content = Path("scripts/debug/wait_rsshub.ps1").read_text(encoding="utf-8")

    assert 'Write-Output "RSSHub did not start"' in content
    assert "exit 1" in content
