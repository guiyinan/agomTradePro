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
