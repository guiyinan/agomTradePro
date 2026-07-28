"""Canonical numeric-boundary regressions for the Tushare unified provider."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.domain.entities import (
    FinancialFact,
    FundNavFact,
    MacroFact,
    ProviderConfig,
    ValuationFact,
)
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure import _provider_adapter_tushare as adapter_module
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)


def _config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-key",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


@pytest.mark.parametrize("invalid_value", [True, "1.0", float("nan"), float("inf")])
def test_canonical_financial_facts_reject_nonfinite_or_non_numeric_values(
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError, match="finite"):
        MacroFact(
            indicator_code="CN_TEST",
            reporting_period=date(2026, 7, 28),
            value=invalid_value,
            unit="点",
            source="test",
        )
    with pytest.raises(ValueError, match="finite"):
        FinancialFact(
            asset_code="000001.SZ",
            period_end=date(2026, 6, 30),
            period_type=FinancialPeriodType.QUARTERLY,
            metric_code="revenue",
            value=invalid_value,
            source="test",
        )
    with pytest.raises(ValueError, match="finite"):
        ValuationFact(
            asset_code="000001.SZ",
            val_date=date(2026, 7, 28),
            pe_ttm=invalid_value,
            source="test",
        )


@pytest.mark.parametrize("invalid_value", [True, float("nan"), float("inf"), 0.0, -1.0])
def test_fund_accumulated_nav_rejects_invalid_values(invalid_value: object) -> None:
    with pytest.raises(ValueError):
        FundNavFact(
            fund_code="110011",
            nav_date=date(2026, 7, 28),
            nav=1.25,
            acc_nav=invalid_value,
            source="test",
        )


def test_valuation_market_caps_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ValuationFact(
            asset_code="000001.SZ",
            val_date=date(2026, 7, 28),
            market_cap=-1.0,
            source="test",
        )


def test_macro_adapter_skips_nonfinite_provider_points(monkeypatch) -> None:
    monkeypatch.setattr(adapter_module, "TushareAdapter", lambda **_kwargs: object())
    monkeypatch.setattr(
        adapter_module,
        "_fetch_macro_points",
        lambda *_args: [
            SimpleNamespace(
                observed_at=date(2026, 7, 1),
                value=float("nan"),
                unit="点",
                published_at=date(2026, 7, 2),
            ),
            SimpleNamespace(
                observed_at=date(2026, 7, 2),
                value="42.5",
                unit="点",
                published_at=date(2026, 7, 3),
            ),
        ],
    )

    facts = TushareUnifiedProviderAdapter(_config()).fetch_macro_series(
        "CN_TEST",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    assert [fact.value for fact in facts] == [42.5]


def test_quote_adapter_isolates_bad_prices_and_optional_amounts(monkeypatch) -> None:
    class FakeGateway:
        def get_quote_snapshots(self, _asset_codes: list[str]) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    stock_code="000001.SZ",
                    fetched_at=datetime(2026, 7, 28, tzinfo=UTC),
                    price=float("nan"),
                    open=None,
                    high=None,
                    low=None,
                    pre_close=None,
                    volume=None,
                    amount=None,
                ),
                SimpleNamespace(
                    stock_code="000002.SZ",
                    fetched_at=datetime(2026, 7, 28, tzinfo=UTC),
                    price="10.5",
                    open="10",
                    high="11",
                    low="9",
                    pre_close="10.2",
                    volume=-1,
                    amount=float("inf"),
                ),
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.TushareGateway",
        FakeGateway,
    )

    facts = TushareUnifiedProviderAdapter(_config()).fetch_quote_snapshots(
        ["000001.SZ", "000002.SZ"]
    )

    assert len(facts) == 1
    assert facts[0].asset_code == "000002.SZ"
    assert facts[0].current_price == 10.5
    assert facts[0].volume is None
    assert facts[0].amount is None


def test_fund_nav_adapter_skips_invalid_primary_nav(monkeypatch) -> None:
    frame = pd.DataFrame(
        [
            {"trade_date": pd.Timestamp("2026-07-28"), "unit_nav": float("nan")},
            {
                "trade_date": pd.Timestamp("2026-07-29"),
                "unit_nav": "1.25",
                "accum_nav": float("inf"),
            },
        ]
    )
    monkeypatch.setattr(
        adapter_module,
        "build_tushare_fund_adapter",
        lambda **_kwargs: SimpleNamespace(fetch_fund_daily=lambda **_call_kwargs: frame),
    )

    facts = TushareUnifiedProviderAdapter(_config()).fetch_fund_nav(
        "110011",
        date(2026, 7, 28),
        date(2026, 7, 29),
    )

    assert len(facts) == 1
    assert facts[0].nav == 1.25
    assert facts[0].acc_nav is None


def test_financial_and_valuation_adapters_drop_nonfinite_fields(monkeypatch) -> None:
    financial_record = SimpleNamespace(
        stock_code="000001.SZ",
        report_date=date(2026, 6, 30),
        report_type="quarterly",
        revenue="100",
        net_profit=float("nan"),
        total_assets="500",
        total_liabilities=float("inf"),
        equity="300",
        roe="8.5",
        debt_ratio="40",
        roa=None,
        revenue_growth=float("-inf"),
        net_profit_growth="5.2",
    )
    valuation_record = SimpleNamespace(
        stock_code="000001.SZ",
        trade_date=date(2026, 7, 28),
        pe=float("nan"),
        pb="1.2",
        ps=float("inf"),
        total_mv=-1,
        circ_mv="5000",
        dividend_yield="2.5",
    )
    monkeypatch.setattr(
        adapter_module,
        "build_tushare_financial_gateway",
        lambda **_kwargs: SimpleNamespace(
            fetch=lambda *_args, **_call_kwargs: SimpleNamespace(records=[financial_record])
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "build_tushare_valuation_gateway",
        lambda **_kwargs: SimpleNamespace(
            fetch=lambda *_args, **_call_kwargs: SimpleNamespace(records=[valuation_record])
        ),
    )
    adapter = TushareUnifiedProviderAdapter(_config())

    financials = adapter.fetch_financials("000001.SZ")
    valuations = adapter.fetch_valuations(
        "000001.SZ",
        date(2026, 7, 28),
        date(2026, 7, 28),
    )

    assert {fact.metric_code for fact in financials} == {
        "revenue",
        "total_assets",
        "equity",
        "roe",
        "debt_ratio",
        "net_profit_growth",
    }
    assert len(valuations) == 1
    assert valuations[0].pe_ttm is None
    assert valuations[0].pb == 1.2
    assert valuations[0].ps_ttm is None
    assert valuations[0].market_cap is None
    assert valuations[0].float_market_cap == 5000.0


def test_turnover_failure_log_does_not_expose_provider_exception(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("https://token:secret-password@provider.example")
        ),
    )

    facts = TushareUnifiedProviderAdapter(_config()).fetch_macro_series(
        "CN_A_TOTAL_TURNOVER",
        date(2026, 7, 28),
        date(2026, 7, 28),
    )

    assert facts == []
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"
