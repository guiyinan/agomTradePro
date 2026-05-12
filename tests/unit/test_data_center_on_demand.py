from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.on_demand import OnDemandDataCenterService
from apps.data_center.domain.entities import FinancialFact, PriceBar, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType


class FakePriceRepo:
    def __init__(self, bars=None):
        self.bars = bars or []

    def get_bars(self, asset_code, start=None, end=None, limit=500):
        return [
            bar
            for bar in self.bars
            if bar.asset_code == asset_code
            and (start is None or bar.bar_date >= start)
            and (end is None or bar.bar_date <= end)
        ]


class FakeValuationRepo:
    def __init__(self, facts=None):
        self.facts = facts or []

    def get_series(self, asset_code, start=None, end=None):
        return [
            fact
            for fact in self.facts
            if fact.asset_code == asset_code
            and (start is None or fact.val_date >= start)
            and (end is None or fact.val_date <= end)
        ]


class FakeFinancialRepo:
    def __init__(self, facts=None):
        self.facts = facts or []

    def get_facts(self, asset_code, period_type=None, limit=20):
        return [fact for fact in self.facts if fact.asset_code == asset_code][:limit]


class FakeQuoteRepo:
    def __init__(self, quotes=None):
        self.quotes = quotes or []

    def get_series(self, asset_code, snapshot_date=None, limit=500):
        return [quote for quote in self.quotes if quote.asset_code == asset_code][:limit]


class FakeSyncUseCase:
    def __init__(self, *, stored_count=0, callback=None, exc=None):
        self.calls = []
        self.stored_count = stored_count
        self.callback = callback
        self.exc = exc

    def execute(self, request):
        self.calls.append(request)
        if self.exc is not None:
            raise self.exc
        if self.callback is not None:
            self.callback(request)
        return type("SyncResult", (), {"stored_count": self.stored_count})()


def _service(
    *,
    price_repo=None,
    valuation_repo=None,
    financial_repo=None,
    quote_repo=None,
    sync_price=None,
    sync_valuation=None,
    sync_financial=None,
    sync_quote=None,
    provider_ids=None,
):
    provider_ids = provider_ids or {"tushare": 1, "akshare": 2}
    return OnDemandDataCenterService(
        price_repo=price_repo or FakePriceRepo(),
        valuation_repo=valuation_repo or FakeValuationRepo(),
        financial_repo=financial_repo or FakeFinancialRepo(),
        quote_repo=quote_repo or FakeQuoteRepo(),
        sync_price_use_case=sync_price or FakeSyncUseCase(),
        sync_valuation_use_case=sync_valuation or FakeSyncUseCase(),
        sync_financial_use_case=sync_financial or FakeSyncUseCase(),
        sync_quote_use_case=sync_quote or FakeSyncUseCase(),
        provider_id_resolver=lambda source: provider_ids.get(source),
    )


def test_ensure_price_bars_hydrates_missing_data_from_tushare():
    price_repo = FakePriceRepo()

    def add_bars(request):
        price_repo.bars.append(
            PriceBar(
                asset_code=request.asset_code,
                bar_date=request.start,
                open=10,
                high=11,
                low=9,
                close=10.5,
                source="tushare",
            )
        )
        price_repo.bars.append(
            PriceBar(
                asset_code=request.asset_code,
                bar_date=request.end,
                open=10.5,
                high=12,
                low=10,
                close=11,
                source="tushare",
            )
        )

    sync_price = FakeSyncUseCase(stored_count=2, callback=add_bars)
    result = _service(price_repo=price_repo, sync_price=sync_price).ensure_price_bars(
        "600031.SH", date(2026, 5, 1), date(2026, 5, 8)
    )

    assert result.quality.status == "fresh"
    assert result.quality.hydrated is True
    assert result.quality.source == "tushare"
    assert len(result.records) == 2
    assert sync_price.calls[0].provider_id == 1


def test_ensure_valuations_marks_provider_failed_when_fallbacks_fail():
    sync_valuation = FakeSyncUseCase(exc=RuntimeError("provider down"))
    result = _service(sync_valuation=sync_valuation).ensure_valuations(
        "600031.SH", date(2026, 5, 1), date(2026, 5, 8)
    )

    assert result.quality.status == "provider_failed"
    assert result.quality.points_count == 0
    assert "provider down" in result.quality.errors[0]


def test_assess_price_bars_marks_sparse_without_hydrating():
    price_repo = FakePriceRepo(
        [
            PriceBar(
                asset_code="600031.SH",
                bar_date=date(2026, 1, 1),
                open=10,
                high=11,
                low=9,
                close=10,
                source="akshare",
            )
        ]
    )
    sync_price = FakeSyncUseCase()

    result = _service(price_repo=price_repo, sync_price=sync_price).assess_price_bars(
        "600031.SH", date(2026, 1, 1), date(2026, 5, 1)
    )

    assert result.quality.status == "sparse"
    assert result.quality.hydrated is False
    assert sync_price.calls == []


def test_ensure_financials_prefers_akshare_before_tushare():
    financial_repo = FakeFinancialRepo()

    def add_financials(request):
        financial_repo.facts.extend(
            [
                FinancialFact(
                    asset_code=request.asset_code,
                    period_end=date(2026, 3, 31),
                    period_type=FinancialPeriodType.QUARTERLY,
                    metric_code=f"metric_{idx}",
                    value=1.0,
                    source="akshare",
                )
                for idx in range(8)
            ]
        )

    sync_financial = FakeSyncUseCase(stored_count=8, callback=add_financials)
    result = _service(
        financial_repo=financial_repo,
        sync_financial=sync_financial,
    ).ensure_financials("600031.SH", periods=8)

    assert result.quality.status == "fresh"
    assert sync_financial.calls[0].provider_id == 2


@pytest.mark.parametrize(
    ("facts", "expected_status"),
    [
        ([], "missing"),
        (
            [
                ValuationFact(
                    asset_code="600031.SH",
                    val_date=date(2026, 5, 8),
                    pe_ttm=10,
                    pb=1,
                    source="akshare",
                    fetched_at=datetime(2026, 5, 8, tzinfo=UTC),
                ),
                ValuationFact(
                    asset_code="600031.SH",
                    val_date=date(2026, 5, 9),
                    pe_ttm=11,
                    pb=1.1,
                    source="akshare",
                    fetched_at=datetime(2026, 5, 9, tzinfo=UTC),
                ),
            ],
            "fresh",
        ),
    ],
)
def test_assess_valuations_reports_quality(facts, expected_status):
    result = _service(valuation_repo=FakeValuationRepo(facts)).assess_valuations(
        "600031.SH", date(2026, 5, 1), date(2026, 5, 9)
    )

    assert result.quality.status == expected_status
