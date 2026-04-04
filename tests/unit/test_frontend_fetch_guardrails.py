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


def test_equity_detail_uses_single_asset_realtime_endpoint_and_renders_price_timestamp():
    content = Path("core/templates/equity/detail.html").read_text(encoding="utf-8")

    assert 'id="detailPriceTimestamp"' in content
    assert 'fetchJsonOrThrowCompat(`/api/realtime/prices/${stockCode}/`)' in content
    assert "updatePriceTimestamp(price.timestamp, '实时价格时间')" in content
    assert "setFallbackClosePrice(latest.price, latest.trade_date)" in content
    assert "updatePriceTimestamp(tradeDate, '上一交易日收盘')" in content
    assert '上一交易日收盘不可用' in content
    assert '最新市价' in content
    assert "second: '2-digit'" in content
    assert "fetchJsonOrThrowCompat('/api/realtime/prices/', {" not in content
    assert "updatePriceTimestamp(latest.updated_at || latest.trade_date, '估值数据时间')" not in content
    assert '{% static \'js/echarts.min.js\' %}' in content
    assert Path("static/js/echarts.min.js").exists()
    assert 'data-technical-timeframe="intraday"' in content
    assert 'data-technical-timeframe="day"' in content
    assert 'id="technicalChart"' in content
    assert 'fetchJsonOrThrowCompat(`/api/equity/intraday/${stockCode}/`)' in content
    assert 'fetchJsonOrThrowCompat(' in content and '/api/equity/technical/${stockCode}/?timeframe=${timeframe}&lookback_days=540' in content
    assert "let technicalRequestToken = 0;" in content
    assert "const requestToken = ++technicalRequestToken;" in content
    assert "if (requestToken !== technicalRequestToken || timeframe !== activeTechnicalTimeframe)" in content


def test_wait_rsshub_exits_non_zero_on_timeout():
    content = Path("scripts/debug/wait_rsshub.ps1").read_text(encoding="utf-8")

    assert 'Write-Output "RSSHub did not start"' in content
    assert "exit 1" in content
