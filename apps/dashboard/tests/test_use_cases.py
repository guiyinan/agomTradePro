import logging
from datetime import date
from types import SimpleNamespace

from apps.account.domain import services as account_services
from apps.dashboard.application.use_cases import (
    GetDashboardDataUseCase,
    _normalize_regime_distribution,
)


def test_normalize_regime_distribution_returns_zeroes_without_real_distribution():
    distribution = _normalize_regime_distribution("Deflation", None)

    assert distribution["Deflation"] == 0.0
    assert distribution["Recovery"] == 0.0
    assert distribution["Overheat"] == 0.0
    assert distribution["Stagflation"] == 0.0


def test_normalize_regime_distribution_preserves_existing_values():
    distribution = _normalize_regime_distribution(
        "Deflation",
        {
            "Recovery": 0.1,
            "Overheat": 0.2,
            "Deflation": 0.3,
            "Stagflation": 0.4,
        },
    )

    assert distribution == {
        "Recovery": 0.1,
        "Overheat": 0.2,
        "Deflation": 0.3,
        "Stagflation": 0.4,
    }


class _FakeProfile:
    display_name = "Admin"
    initial_capital = 100000.0
    risk_tolerance = SimpleNamespace(value="moderate")


class _FakeSnapshot:
    initial_capital = 100000.0
    total_value = 120000.0
    cash_balance = 20000.0
    invested_value = 100000.0
    total_return = 20000.0
    total_return_pct = 20.0
    positions: list = []

    def get_invested_ratio(self) -> float:
        return 100000.0 / 120000.0


class _FakeAccountRepo:
    def get_by_user_id(self, user_id: int):
        return _FakeProfile()

    def create_default_profile(self, user_id: int):
        raise AssertionError("profile should already exist in this test")

    def get_or_create_default_portfolio(self, user_id: int) -> int:
        return 11


class _FakePortfolioRepo:
    def get_portfolio_snapshot(self, portfolio_id: int):
        return _FakeSnapshot()


class _FakeOverviewRepo:
    def get_user_simulated_account_totals(self, user_id: int):
        return {
            "total_assets": 120000.0,
            "initial_capital": 100000.0,
            "cash_balance": 20000.0,
            "invested_value": 100000.0,
            "invested_ratio": 100000.0 / 120000.0,
            "total_return": 20000.0,
            "total_return_pct": 20.0,
        }

    def get_simulated_positions(self, user_id: int):
        return []


class _FakeSignalRepo:
    def get_user_signals(self, user_id: int, status: str | None = None, limit: int | None = None):
        return []


def test_get_dashboard_data_use_case_logs_step_timings(monkeypatch, caplog):
    use_case = GetDashboardDataUseCase(
        account_repo=_FakeAccountRepo(),
        portfolio_repo=_FakePortfolioRepo(),
        position_repo=object(),
        regime_repo=object(),
        signal_repo=_FakeSignalRepo(),
        overview_repo=_FakeOverviewRepo(),
    )

    monkeypatch.setattr(
        "apps.regime.application.current_regime.resolve_current_regime",
        lambda as_of_date: SimpleNamespace(
            dominant_regime="Recovery",
            confidence=0.91,
            distribution={"Recovery": 1.0},
        ),
    )
    monkeypatch.setattr(
        account_services.PositionService,
        "calculate_regime_match_score",
        staticmethod(
            lambda positions, current_regime: SimpleNamespace(
                total_match_score=88.0,
                recommendations=["保持进攻仓位纪律"],
                hostile_assets=[],
            )
        ),
    )
    monkeypatch.setattr(
        use_case,
        "_assess_macro_data_health",
        lambda growth_indicator, inflation_indicator, as_of_date: {
            "is_healthy": True,
            "warnings": [],
        },
    )
    monkeypatch.setattr(use_case, "_get_latest_macro_values", lambda: (50.1, 1.2))
    monkeypatch.setattr(use_case, "_get_user_signals", lambda user_id: [])
    monkeypatch.setattr(
        use_case,
        "_calculate_signal_stats",
        lambda user_id: {"total": 0, "approved": 0, "pending": 0, "rejected": 0},
    )
    monkeypatch.setattr(
        use_case,
        "_get_policy_environment",
        lambda user_id: ("P1", date(2026, 5, 14), 0, []),
    )
    monkeypatch.setattr(
        use_case,
        "_generate_ai_insights",
        lambda current_regime, snapshot, match_analysis, active_signals, policy_level: ["保持纪律"],
    )
    monkeypatch.setattr(
        use_case,
        "_generate_allocation_advice",
        lambda current_regime, policy_level, profile, total_assets, positions: None,
    )
    monkeypatch.setattr(use_case, "_generate_performance_chart_data", lambda user_id=None: [])

    with caplog.at_level(logging.INFO):
        data = use_case.execute(7)

    assert data.current_regime == "Recovery"

    records = [record for record in caplog.records if record.message == "Dashboard data aggregation completed"]
    assert records

    record = records[-1]
    assert record.user_id == 7
    assert record.duration_ms >= 0
    assert record.position_count == 0
    assert record.signal_count == 0
    assert record.ai_insight_count == 1
    assert record.used_simulated_positions is False
    assert "profile" in record.step_durations_ms
    assert "macro_health" in record.step_durations_ms
    assert "charts" in record.step_durations_ms
