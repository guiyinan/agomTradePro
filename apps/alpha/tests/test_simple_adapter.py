from datetime import UTC, date, datetime

from django.utils import timezone

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider


def test_simple_provider_scores_scope_from_fresh_quotes_when_fundamentals_missing(
    monkeypatch,
):
    now = timezone.now()
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_published_quote_payloads",
        lambda _codes: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "snapshot_at": now,
                    "current_price": "11.20",
                    "open": "11.00",
                    "high": "11.30",
                    "low": "10.90",
                    "prev_close": "10.95",
                    "volume": "500000",
                },
                {
                    "asset_code": "000002.SZ",
                    "snapshot_at": datetime.now(UTC),
                    "current_price": "8.90",
                    "open": "8.95",
                    "high": "9.05",
                    "low": "8.80",
                    "prev_close": "9.00",
                    "volume": "200000",
                },
            ],
            "must_not_use_for_decision": False,
            "freshness_status": "fresh",
        },
    )
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ", "000002.SZ"),
        selection_reason="test",
        trade_date=date(2026, 4, 24),
        display_label="默认组合 · 价格覆盖池",
    )

    result = SimpleAlphaProvider().get_stock_scores(
        universe_id=scope.universe_id,
        intended_trade_date=timezone.localdate(),
        top_n=10,
        pool_scope=scope,
    )

    assert result.success is True
    assert result.source == "simple"
    assert result.status == "available"
    assert len(result.scores) == 2
    assert result.metadata["factor_basis"] == "quote_momentum"
    assert result.metadata["data_quality"]["price_momentum_count"] == 2
    assert result.scores[0].rank == 1
    assert (
        result.scores[0].factors["intraday_return"] >= result.scores[1].factors["intraday_return"]
    )
