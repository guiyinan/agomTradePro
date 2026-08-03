from __future__ import annotations

from datetime import date

from apps.equity.application import query_services


class _StockRepository:
    def get_stock_master_rows(self, codes: list[str]) -> dict[str, dict[str, str]]:
        return {
            code: {
                "asset_code": code,
                "name": "平安银行",
                "sector": "银行",
                "market": "SZ",
            }
            for code in codes
        }


def _fresh_gate() -> dict[str, object]:
    return {
        "publication_id": "pub-1",
        "published_at": "2026-08-03T01:00:00+00:00",
        "observed_at": "2026-08-03T01:00:00+00:00",
        "freshness_status": "fresh",
        "must_not_use_for_decision": False,
        "blocked_reason": None,
    }


def test_published_stock_context_aggregates_same_financial_period(monkeypatch) -> None:
    monkeypatch.setattr(
        query_services,
        "get_equity_stock_repository",
        lambda: _StockRepository(),
    )
    monkeypatch.setattr(
        query_services,
        "get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "timestamp": "2026-08-01",
                    "close": 12.34,
                    "volume": 123456,
                }
            ],
            **_fresh_gate(),
        },
    )
    monkeypatch.setattr(
        query_services,
        "get_published_financial_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "period_end": "2026-06-30",
                    "report_date": "2026-07-31",
                    "metric_code": "roe",
                    "value": 12.3,
                },
                {
                    "period_end": "2026-06-30",
                    "report_date": "2026-07-31",
                    "metric_code": "debt_ratio",
                    "value": 80.0,
                },
                {
                    "period_end": "2026-03-31",
                    "report_date": "2026-04-30",
                    "metric_code": "roe",
                    "value": 99.0,
                },
            ],
            **_fresh_gate(),
        },
    )
    monkeypatch.setattr(
        query_services,
        "get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "val_date": "2026-08-01",
                    "pe_ttm": 5.6,
                    "pb": 0.72,
                    "ps_ttm": 1.34,
                    "dv_ratio": 4.5,
                }
            ],
            **_fresh_gate(),
        },
    )

    context = query_services.get_published_stock_context_map(["000001.SZ"])

    assert context["000001.SZ"]["trade_date"] == date(2026, 8, 1)
    assert context["000001.SZ"]["report_date"] == date(2026, 7, 31)
    assert context["000001.SZ"]["roe"] == 12.3
    assert context["000001.SZ"]["debt_ratio"] == 80.0
    assert context["000001.SZ"]["pe"] == 5.6
    assert context["000001.SZ"]["must_not_use_for_decision"] is False


def test_published_stock_context_drops_stale_rows_and_preserves_block_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        query_services,
        "get_equity_stock_repository",
        lambda: _StockRepository(),
    )
    stale_gate = {
        **_fresh_gate(),
        "freshness_status": "stale",
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_stale",
    }
    monkeypatch.setattr(
        query_services,
        "get_published_price_bar_series",
        lambda *args, **kwargs: {"rows": [{"timestamp": "2026-01-01", "close": 1}], **stale_gate},
    )
    monkeypatch.setattr(
        query_services,
        "get_published_financial_facts",
        lambda *args, **kwargs: {"rows": [{"metric_code": "roe", "value": 99}], **stale_gate},
    )
    monkeypatch.setattr(
        query_services,
        "get_published_valuation_facts",
        lambda *args, **kwargs: {"rows": [{"val_date": "2026-01-01", "pe_ttm": 1}], **stale_gate},
    )

    context = query_services.get_published_stock_context_map(["000001.SZ"])
    row = context["000001.SZ"]

    assert "close" not in row
    assert "roe" not in row
    assert "pe" not in row
    assert row["must_not_use_for_decision"] is True
    assert row["blocked_reason"] == "canonical_publication_stale"
    assert row["publication_gates"]["price"]["freshness_status"] == "stale"


def test_published_stock_context_blocks_missing_member_rows(monkeypatch) -> None:
    """A fresh gate with no selected member rows must remain unusable."""

    monkeypatch.setattr(
        query_services,
        "get_equity_stock_repository",
        lambda: _StockRepository(),
    )
    monkeypatch.setattr(
        query_services,
        "get_published_price_bar_series",
        lambda *args, **kwargs: {"rows": [], **_fresh_gate()},
    )
    monkeypatch.setattr(
        query_services,
        "get_published_financial_facts",
        lambda *args, **kwargs: {"rows": [], **_fresh_gate()},
    )
    monkeypatch.setattr(
        query_services,
        "get_published_valuation_facts",
        lambda *args, **kwargs: {"rows": [], **_fresh_gate()},
    )

    context = query_services.get_published_stock_context_map(["000001.SZ"])
    row = context["000001.SZ"]

    assert row["must_not_use_for_decision"] is True
    assert row["blocked_reason"] == "canonical_publication_members_missing"
    assert row["missing_datasets"] == ["financial", "valuation", "price"]
