"""Behavior tests for the optimized pure-Domain equity screener."""

from datetime import date, timedelta
from decimal import Decimal

from apps.equity.domain.optimized_screener import (
    IncrementalScreeningEngine,
    OptimizedStockScreener,
    ScreeningCacheManager,
    cached_sector_filter,
)
from apps.equity.domain.rules import StockScreeningRule
from tests.factories.domain_factories import (
    make_financial_data,
    make_stock_info,
    make_valuation_metrics,
)


def _rule(**overrides: object) -> StockScreeningRule:
    values: dict[str, object] = {
        "regime": "Recovery",
        "name": "optimized",
        "min_roe": 0.1,
        "min_revenue_growth": 0.0,
        "min_profit_growth": 0.0,
        "max_debt_ratio": 1.0,
        "max_pe": 30.0,
        "max_pb": 5.0,
        "min_market_cap": Decimal("100"),
        "sector_preference": ["金融"],
        "max_count": 2,
    }
    values.update(overrides)
    return StockScreeningRule(**values)


def _stock(
    code: str,
    *,
    sector: str = "金融",
    roe: float = 0.2,
    pe: float = 10.0,
    pb: float = 1.0,
    total_mv: Decimal = Decimal("1000"),
) -> tuple[object, object, object]:
    return (
        make_stock_info(stock_code=code, name=code, sector=sector),
        make_financial_data(
            stock_code=code,
            roe=roe,
            revenue_growth=0.2,
            net_profit_growth=0.2,
            debt_ratio=0.2,
        ),
        make_valuation_metrics(
            stock_code=code,
            pe=pe,
            pb=pb,
            total_mv=total_mv,
        ),
    )


def test_optimized_screener_prefilters_scores_sorts_and_limits() -> None:
    stocks = [
        _stock("PASS-LOW", roe=0.11, pe=20.0),
        _stock("PASS-HIGH", roe=0.3, pe=8.0),
        _stock("WRONG-SECTOR", sector="科技"),
        _stock("HIGH-PE", pe=31.0),
        _stock("NEGATIVE-PE", pe=-1.0),
        _stock("HIGH-PB", pb=6.0),
        _stock("NEGATIVE-PB", pb=-1.0),
        _stock("SMALL", total_mv=Decimal("99")),
        _stock("LOW-ROE", roe=0.09),
    ]

    result = OptimizedStockScreener().screen(stocks, _rule(), batch_size=1)

    assert set(result) == {"PASS-HIGH", "PASS-LOW"}
    assert result[0] == "PASS-HIGH"


def test_incremental_engine_handles_initial_rule_change_and_incremental_runs() -> None:
    engine = IncrementalScreeningEngine()
    first_rule = _rule(max_count=1)
    changed_rule = _rule(max_count=2)
    stocks = [_stock("A"), _stock("B", roe=0.3)]
    today = date(2026, 7, 24)

    initial = engine.incremental_screen(stocks, first_rule, today)
    engine._update_rule_hash(first_rule)
    changed = engine.incremental_screen(
        stocks,
        changed_rule,
        today + timedelta(days=1),
        {"A"},
    )
    incremental = engine.incremental_screen(
        stocks,
        changed_rule,
        today + timedelta(days=2),
        {"B"},
    )

    assert len(initial) == 1
    assert set(changed) == {"A", "B"}
    assert set(incremental) == {"A", "B"}
    assert engine.last_screening_date == today + timedelta(days=2)


def test_screening_cache_lifecycle_and_sector_filter_contract() -> None:
    cache = ScreeningCacheManager()
    rule = _rule()
    key = cache.generate_rule_key(rule)
    today = date(2026, 7, 24)

    assert cache.get(key, today) is None
    cache.set(key, today, ["A"])
    assert cache.get(key, today) == ["A"]
    assert cache.get(key, today + timedelta(days=1)) is None
    cache.invalidate("missing")
    cache.invalidate(key)
    assert cache.get(key, today) is None
    cache.set(key, today, ["A"])
    cache.invalidate()
    assert cache.get(key, today) is None

    cached_sector_filter.cache_clear()
    assert cached_sector_filter("A", ("金融",), "金融") is True
    assert cached_sector_filter("", ("金融",), "金融") is False
    assert cached_sector_filter("A", (), "金融") is False
    assert cached_sector_filter("A", ("金融",), None) is False
