"""High-risk boundary tests for backtest Domain entities and engines."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from apps.backtest.domain.alpha_backtest import (
    RunAlphaBacktestRequest,
    RunAlphaBacktestUseCase,
)
from apps.backtest.domain.entities import (
    AttributionEntry,
    AttributionReport,
    BacktestConfig,
    BacktestResult,
    DataVersion,
    DataVersionHistory,
    PITDataConfig,
    PortfolioState,
    RebalanceResult,
    Trade,
)
from apps.backtest.domain.stock_selection_backtest import (
    RebalanceFrequency,
    RebalanceRecord,
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
)


def _base_config(**overrides: Any) -> BacktestConfig:
    """Build a valid BacktestConfig with optional explicit overrides."""
    values: dict[str, Any] = {
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 4, 1),
        "initial_capital": 100_000.0,
        "rebalance_frequency": "monthly",
        "use_pit_data": False,
    }
    values.update(overrides)
    return BacktestConfig(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"transaction_cost_bps": -1}, "transaction_cost_bps must be non-negative"),
        ({"trust_status": "unknown"}, "trust_status must be one of"),
        (
            {"trust_status": "pit_verified"},
            "pit_verified backtests must enable PIT data",
        ),
        (
            {"trust_status": "pit_verified", "use_pit_data": True},
            "pit_verified backtests require data_manifest_id",
        ),
        (
            {
                "trust_status": "pit_verified",
                "use_pit_data": True,
                "data_manifest_id": "manifest",
            },
            "pit_verified backtests require config, code and engine versions",
        ),
        (
            {
                "trust_status": "pit_verified",
                "use_pit_data": True,
                "data_manifest_id": "manifest",
                "config_hash": "config",
                "code_commit": "commit",
            },
            "pit_verified backtests require research_trial_id",
        ),
        (
            {
                "trust_status": "pit_verified",
                "use_pit_data": True,
                "data_manifest_id": "manifest",
                "config_hash": "config",
                "code_commit": "commit",
                "research_trial_id": "trial",
            },
            "pit_verified backtests require decision_snapshot_id",
        ),
    ],
)
def test_backtest_config_rejects_unverifiable_research_claims(
    overrides: dict[str, Any],
    message: str,
) -> None:
    """A PIT-verified label requires the complete reproducibility evidence chain."""
    with pytest.raises(ValueError, match=message):
        _base_config(**overrides)


def test_backtest_entities_project_stable_audit_payloads() -> None:
    """Entity projections retain dates, copied mappings, and audit counts."""
    config = _base_config(
        trust_status="pit_verified",
        use_pit_data=True,
        data_manifest_id="manifest",
        config_hash="config",
        code_commit="commit",
        research_trial_id="trial",
        decision_snapshot_id="snapshot",
    )
    trade = Trade(date(2024, 1, 1), "gold", "buy", 2, 10, 20, 0.1)
    portfolio = PortfolioState(date(2024, 1, 1), 80, {"gold": 2}, 100)
    result = BacktestResult(config, 110_000, 0.1, 0.46, 1.2, 0.05, [trade])
    rebalance = RebalanceResult(
        date(2024, 1, 1),
        "Recovery",
        0.8,
        {"cash": 1.0},
        {"gold": 0.2},
        [trade],
        100_000,
    )
    entry = AttributionEntry(date(2024, 1, 1), "Recovery", 0.02, 0.03, 0.01, 0.02)
    report = AttributionReport(config, 0.1, 0.04, 0.06, {"Recovery": {"active": 0.02}}, [entry])

    assert portfolio.get_position_value("gold", 12) == 24
    assert portfolio.get_position_value("missing", 12) == 0
    assert portfolio.to_dict()["as_of_date"] == "2024-01-01"
    assert result.to_summary_dict()["num_trades"] == 1
    assert result.get_win_rate() is None
    assert BacktestResult(config, 100_000, 0, 0, None, 0).get_win_rate() is None
    assert rebalance.to_dict()["num_trades"] == 1
    assert report.to_dict() == {
        "total_return": 0.1,
        "benchmark_return": 0.04,
        "active_return": 0.06,
        "regime_attribution": {"Recovery": {"active": 0.02}},
        "num_entries": 1,
    }


def test_pit_lags_and_data_versions_respect_as_of_time() -> None:
    """PIT helpers never expose a version before its publication date."""
    lags = PITDataConfig()
    lags.add_lag("GDP", 30)
    initial = DataVersion("GDP", date(2023, 12, 31), 5.0, 1, date(2024, 1, 31))
    revision = DataVersion("GDP", date(2023, 12, 31), 5.1, 2, date(2024, 2, 29))
    final = DataVersion(
        "GDP",
        date(2023, 12, 31),
        5.2,
        3,
        date(2024, 3, 31),
        is_final=True,
    )
    history = DataVersionHistory("GDP", date(2023, 12, 31), (initial, revision, final))

    assert lags.get_lag("GDP") == timedelta(days=30)
    assert lags.get_lag("PMI") == timedelta(0)
    assert initial.version_type == "初值"
    assert revision.version_type == "修订值1"
    assert final.version_type == "最终值"
    assert not initial.is_available_on(date(2024, 1, 30))
    assert history.get_version_on(date(2024, 1, 1)) is None
    assert history.get_version_on(date(2024, 3, 1)) is revision
    assert history.get_final_value() is final
    assert DataVersionHistory("GDP", date(2023, 12, 31), (initial,)).get_final_value() is None


def _stock_engine(
    *,
    frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY,
    position_method: str = "equal_weight",
    market_cap_reader: Any | None = None,
) -> StockSelectionBacktestEngine:
    """Build a deterministic stock-selection engine."""
    return StockSelectionBacktestEngine(
        config=StockSelectionBacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 1),
            initial_capital=Decimal("10000"),
            rebalance_frequency=frequency,
            max_positions=2,
            position_method=position_method,
            commission_rate=0.001,
            slippage_rate=0.001,
        ),
        get_regime_func=lambda as_of: "Recovery",
        get_stock_data_func=lambda as_of: [object()],
        get_price_func=lambda code, as_of: Decimal("10") if code != "MISSING" else None,
        get_benchmark_price_func=lambda as_of: 100.0 if as_of.month == 1 else 110.0,
        get_market_cap_func=market_cap_reader,
    )


def test_stock_selection_run_covers_buy_sell_cost_and_final_liquidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changing selection realizes trades, fees, and final positions deterministically."""
    selections = iter([["AAA", "BBB"], ["BBB", "CCC"], ["CCC"]])

    def screen(*args: Any, **kwargs: Any) -> list[str]:
        return next(selections)

    monkeypatch.setattr(
        "apps.backtest.domain.stock_selection_backtest.StockScreener.screen",
        screen,
    )
    engine = _stock_engine()
    result = engine.run({"Recovery": object()})

    assert len(result.rebalance_records) == 3
    assert result.rebalance_records[1].sold_stocks[0][0] == "AAA"
    assert result.total_trades >= 3
    assert result.stock_performances
    assert result.benchmark_return == pytest.approx(0.1)
    assert result.turnover_rate > 0


@pytest.mark.parametrize(
    ("frequency", "expected_count"),
    [
        (RebalanceFrequency.DAILY, 61),
        (RebalanceFrequency.WEEKLY, 9),
        (RebalanceFrequency.QUARTERLY, 1),
    ],
)
def test_stock_selection_rebalance_frequency_boundaries(
    frequency: RebalanceFrequency,
    expected_count: int,
) -> None:
    """Every declared rebalance frequency advances monotonically without lookahead."""
    assert len(_stock_engine(frequency=frequency)._generate_rebalance_dates()) == expected_count


def test_stock_selection_helper_fallbacks_are_explicit() -> None:
    """Invalid market caps and empty statistics use documented deterministic fallbacks."""
    caps = {"A": None, "B": "bad", "C": -1, "D": 4}
    engine = _stock_engine(
        position_method="market_cap_weight",
        market_cap_reader=lambda code, as_of: caps[code],
    )

    assert engine._calculate_weights([], date(2024, 1, 1)) == {}
    assert engine._calculate_weights(["A", "B", "C"], date(2024, 1, 1)) == pytest.approx(
        {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    )
    assert engine._load_market_caps(["A", "B", "C", "D"], date(2024, 1, 1)) == {"D": Decimal("4")}
    assert engine._calculate_risk_metrics(
        [
            (date(2024, 1, 1), Decimal("0")),
            (date(2024, 1, 2), Decimal("0")),
        ],
        0.1,
    ) == (0.0, 0.0, 0.0)
    volatility, drawdown, sharpe = engine._calculate_risk_metrics(
        [
            (date(2024, 1, 1), Decimal("100")),
            (date(2024, 1, 2), Decimal("110")),
            (date(2024, 1, 3), Decimal("99")),
        ],
        0.2,
    )
    assert volatility > 0
    assert drawdown == pytest.approx(0.1)
    assert sharpe != 0
    assert engine._calculate_win_loss_stats({"A": [{"return": 0.2}, {"return": -0.1}]}) == (
        0.5,
        0.2,
        -0.1,
    )
    assert engine._calculate_avg_holding_period([]) == 0.0
    empty_record = RebalanceRecord(
        date(2024, 1, 1),
        "Recovery",
        [],
        [],
        [],
        Decimal("100"),
    )
    assert engine._calculate_turnover_rate([empty_record]) == 0.0
    assert (
        engine._organize_stock_performances({"A": [{"entry_date": None, "exit_date": None}]}) == []
    )


class RepositoryFake:
    """In-memory repository fake for the Alpha backtest use case."""

    def __init__(self, *, fail_save: bool = False) -> None:
        self.statuses: list[tuple[Any, ...]] = []
        self.fail_save = fail_save

    def create_backtest(self, name: str, config: Any) -> SimpleNamespace:
        """Return a persisted identity."""
        return SimpleNamespace(id=7)

    def update_status(self, *args: Any) -> None:
        """Record status changes."""
        self.statuses.append(args)

    def save_result(self, backtest_id: int, result: Any) -> None:
        """Persist or deterministically fail."""
        if self.fail_save:
            raise RuntimeError("save failed")


def _alpha_result() -> SimpleNamespace:
    """Build the public result contract consumed by the use case."""
    return SimpleNamespace(
        total_return=0.1,
        annualized_return=0.2,
        benchmark_return=0.03,
        excess_return=0.07,
        volatility=0.1,
        max_drawdown=0.05,
        sharpe_ratio=1.2,
        calmar_ratio=4.0,
        total_rebalances=2,
        total_trades=3,
        avg_positions=2,
        win_rate=0.5,
        avg_ic=0.04,
        avg_rank_ic=0.05,
        icir=0.8,
        coverage_ratio=0.9,
        provider_usage={"fake": 2},
        equity_curve=[(date(2024, 1, 1), Decimal("10000"))],
    )


def _request() -> RunAlphaBacktestRequest:
    """Build a valid Alpha backtest request."""
    return RunAlphaBacktestRequest("alpha", date(2024, 1, 1), date(2024, 3, 1))


def test_alpha_backtest_use_case_handles_unavailable_success_and_persistence_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The use case maps dependency absence and persistence failure without losing identity."""
    unavailable = RunAlphaBacktestUseCase(
        RepositoryFake(),
        lambda as_of: "Recovery",
        lambda code, as_of: Decimal("10"),
        lambda as_of: 100.0,
    )
    assert unavailable.execute(_request()).errors == ["Alpha 服务不可用"]

    monkeypatch.setattr(
        "apps.backtest.domain.alpha_backtest.AlphaBacktestEngine.run",
        lambda self: _alpha_result(),
    )
    repository = RepositoryFake()
    successful = RunAlphaBacktestUseCase(
        repository,
        lambda as_of: "Recovery",
        lambda code, as_of: Decimal("10"),
        lambda as_of: 100.0,
        alpha_service_factory=object,
    ).execute(_request())
    assert successful.status == "completed"
    assert successful.result is not None
    assert successful.result["equity_curve"] == [{"date": "2024-01-01", "value": 10000.0}]
    assert repository.statuses == [(7, "running")]

    failing_repository = RepositoryFake(fail_save=True)
    failed = RunAlphaBacktestUseCase(
        failing_repository,
        lambda as_of: "Recovery",
        lambda code, as_of: Decimal("10"),
        lambda as_of: 100.0,
        alpha_service_factory=object,
    ).execute(_request())
    assert failed.status == "failed"
    assert failed.backtest_id == 7
    assert failing_repository.statuses[-1] == (
        7,
        "failed",
        "Alpha backtest execution failed.",
    )
    assert failed.errors == ["Alpha backtest execution failed."]


def test_alpha_service_import_failure_is_cached() -> None:
    """An unavailable optional Alpha runtime degrades once and remains unavailable."""
    use_case = RunAlphaBacktestUseCase(
        RepositoryFake(),
        lambda as_of: "Recovery",
        lambda code, as_of: Decimal("10"),
        lambda as_of: 100.0,
        alpha_service_factory=lambda: (_ for _ in ()).throw(ImportError("optional")),
    )

    assert use_case.alpha_service is None
    assert use_case.alpha_service is None
