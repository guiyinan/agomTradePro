"""Behavior contracts for standalone backtest report generation."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from apps.backtest.application.report_generator import (
    BacktestReportGenerator,
    ReportConfig,
    generate_backtest_report,
)


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        name="Risk Aware",
        equity_curve=[
            {"date": "2026-01-01", "value": 100.0},
            {"date": "2026-01-02", "value": 120.0},
            {"date": "2026-01-03", "value": 90.0},
        ],
        trades=[
            {
                "trade_date": "2026-01-02",
                "asset_class": "equity",
                "action": "BUY",
                "shares": 100,
                "price": 12.3,
                "notional": 1230,
            }
        ],
        regime_history=["Recovery"],
        warnings=["insufficient benchmark history"],
        total_return=0.2,
        annualized_return=1.2,
        max_drawdown=-0.25,
        sharpe_ratio=1.5,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        initial_capital=100.0,
        final_capital=120.0,
    )


def test_report_generator_builds_auditable_html_artifact(tmp_path: Path) -> None:
    config = ReportConfig(output_dir=str(tmp_path))

    output_path = Path(generate_backtest_report(_result(), config))
    html = output_path.read_text(encoding="utf-8")

    assert output_path.parent == tmp_path
    assert output_path.name.startswith("Risk_Aware_7_")
    assert "Risk Aware - 回测报告" in html
    assert "insufficient benchmark history" in html
    assert "equity" in html
    assert "25.00%" in html


def test_report_helpers_cover_empty_and_zero_peak_boundaries(tmp_path: Path) -> None:
    generator = BacktestReportGenerator(
        ReportConfig(output_dir=str(tmp_path), include_trades=False)
    )

    assert generator._calculate_drawdowns([]) == []
    assert generator._calculate_drawdowns([0.0, 0.0]) == [
        {"date": 0, "drawdown": 0, "peak": 0.0, "value": 0.0},
        {"date": 1, "drawdown": 0, "peak": 0.0, "value": 0.0},
    ]
    assert generator._generate_warnings_html([]) == ""
    assert generator._generate_trades_html([]) == ""
    assert 'class="value positive"' in generator._generate_metric_html(
        "Return",
        "1.0%",
        True,
    )
    assert 'class="value negative"' in generator._generate_metric_html(
        "Return",
        "-1.0%",
        False,
    )
