from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from apps.equity.infrastructure import fundamentals_repository
from apps.equity.infrastructure.fundamentals_repository import StockFundamentalsRepositoryMixin


def _fresh_payload(
    dataset_key: str,
    publication_id: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "rows": rows,
        "dataset_key": dataset_key,
        "publication_key": "release-1",
        "publication_id": publication_id,
        "publication_hash": f"{publication_id:0<64}"[:64],
        "published_at": "2026-05-13T08:00:00+00:00",
        "as_of": "2026-05-12",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
    }


def test_repository_converts_only_selected_context_rows_and_keeps_dataset_identities(monkeypatch):
    fetched_at = "2026-05-13T08:00:00+00:00"
    observed_at = "2026-05-12T07:30:00+00:00"
    valuation_rows: list[dict[str, object]] = [
        {
            "asset_code": "002493.SZ",
            "val_date": "2026-04-30",
            "pe_ttm": 16.0,
            "pb": 2.8,
            "ps_ttm": 2.2,
            "market_cap": 900000000.0,
            "float_market_cap": 800000000.0,
            "dv_ratio": 1.1,
            "source": "published-test",
            "observed_at": observed_at,
            "fetched_at": fetched_at,
            "extra": {},
        },
        {
            "asset_code": "002493.SZ",
            "val_date": "2026-05-12",
            "pe_ttm": 18.5,
            "pb": 3.2,
            "ps_ttm": 2.4,
            "market_cap": 1000000000.0,
            "float_market_cap": 800000000.0,
            "dv_ratio": 1.2,
            "source": "published-test",
            "observed_at": observed_at,
            "fetched_at": fetched_at,
            "extra": {},
        },
    ]
    financial_rows = [
        {
            "asset_code": "002493.SZ",
            "period_end": "2025-12-31",
            "period_type": "annual",
            "metric_code": metric,
            "value": value,
            "unit": "CNY",
            "source": "published-test",
            "report_date": "2026-03-31",
            "available_at": "2026-03-31T08:00:00+00:00",
            "fetched_at": fetched_at,
            "extra": {},
        }
        for metric, value in (
            ("revenue", 100000000.0),
            ("net_profit", 10000000.0),
            ("total_assets", 500000000.0),
            ("total_liabilities", 200000000.0),
            ("equity", 300000000.0),
            ("roe", 14.8),
            ("debt_ratio", 40.0),
            ("revenue_growth", 12.5),
            ("net_profit_growth", 8.2),
            ("roa", 4.3),
        )
    ]
    price_rows = [
        {
            "asset_code": "002493.SZ",
            "bar_date": "2026-05-12",
            "close": 19.88,
            "fetched_at": fetched_at,
        }
    ]
    context = {
        "002493.SZ": {
            "price": _fresh_payload("equity.price.bar", "price-release", price_rows),
            "financial": _fresh_payload(
                "equity.financial.fact", "financial-release", financial_rows
            ),
            "valuation": _fresh_payload(
                "equity.valuation.fact", "valuation-release", valuation_rows
            ),
        }
    }
    calls: list[tuple[list[str], str, int]] = []

    def read_context(
        asset_codes: list[str], *, publication_key: str, valuation_limit: int
    ) -> dict[str, dict[str, dict[str, object]]]:
        calls.append((asset_codes, publication_key, valuation_limit))
        return context

    monkeypatch.setattr(
        fundamentals_repository,
        "get_published_equity_analysis_context_payloads",
        read_context,
    )
    repository = object.__new__(StockFundamentalsRepositoryMixin)

    result = repository.get_published_valuation_inputs(
        "002493.SZ",
        date(2026, 1, 1),
        date(2026, 5, 12),
        publication_key="release-1",
        valuation_limit=5000,
    )

    assert calls == [(["002493.SZ"], "release-1", 5000)]
    assert [item.trade_date for item in result.valuation_history] == [
        date(2026, 4, 30),
        date(2026, 5, 12),
    ]
    assert result.latest_financial is not None
    assert result.latest_financial.roe == 14.8
    latest_valuation = result.valuation_history[-1]
    assert latest_valuation.source_updated_at == datetime.fromisoformat(observed_at)
    assert latest_valuation.fetched_at == datetime.fromisoformat(fetched_at)
    assert result.daily_prices == ((date(2026, 5, 12), Decimal("19.88")),)
    assert {
        key: gate.publication_id if gate is not None else None
        for key, gate in result.publication_gates.items()
    } == {
        "equity.price.bar": "price-release",
        "equity.financial.fact": "financial-release",
        "equity.valuation.fact": "valuation-release",
    }
    valuation_gate = result.publication_gates["equity.valuation.fact"]
    assert valuation_gate is not None
    assert "rows" not in valuation_gate.to_public_payload()


def test_repository_preserves_a_selected_dataset_block_reason(monkeypatch):
    blocked_payload = _fresh_payload("equity.valuation.fact", "valuation-release", [])
    blocked_payload.update(
        must_not_use_for_decision=True,
        blocked_reason="valuation_source_data_unavailable",
    )
    context = {
        "002493.SZ": {
            "price": _fresh_payload("equity.price.bar", "price-release", []),
            "financial": _fresh_payload("equity.financial.fact", "financial-release", []),
            "valuation": blocked_payload,
        }
    }
    monkeypatch.setattr(
        fundamentals_repository,
        "get_published_equity_analysis_context_payloads",
        lambda *_args, **_kwargs: context,
    )
    repository = object.__new__(StockFundamentalsRepositoryMixin)

    result = repository.get_published_valuation_inputs(
        "002493.SZ", date(2026, 1, 1), date(2026, 5, 12), publication_key="release-1"
    )

    gate = result.publication_gates["equity.valuation.fact"]
    assert gate is not None
    assert gate.must_not_use_for_decision is True
    assert gate.blocked_reason == "valuation_source_data_unavailable"
    assert gate.publication_id == "valuation-release"


def test_repository_does_not_treat_unusable_selected_member_as_fresh_history(monkeypatch):
    valuation_payload = _fresh_payload(
        "equity.valuation.fact",
        "valuation-release",
        [
            {
                "asset_code": "002493.SZ",
                "val_date": "2026-05-12",
                "pe_ttm": 18.5,
                "pb": None,
                "market_cap": 1000000000.0,
                "source": "published-test",
                "observed_at": "2026-05-12T07:30:00+00:00",
                "fetched_at": "2026-05-13T08:00:00+00:00",
                "extra": {},
            }
        ],
    )
    context = {
        "002493.SZ": {
            "price": _fresh_payload("equity.price.bar", "price-release", []),
            "financial": _fresh_payload("equity.financial.fact", "financial-release", []),
            "valuation": valuation_payload,
        }
    }
    monkeypatch.setattr(
        fundamentals_repository,
        "get_published_equity_analysis_context_payloads",
        lambda *_args, **_kwargs: context,
    )
    repository = object.__new__(StockFundamentalsRepositoryMixin)

    result = repository.get_published_valuation_inputs(
        "002493.SZ", date(2026, 1, 1), date(2026, 5, 12), publication_key="release-1"
    )

    gate = result.publication_gates["equity.valuation.fact"]
    assert gate is not None
    assert gate.publication_id == "valuation-release"
    assert gate.must_not_use_for_decision is False
    assert result.valuation_history == ()


def test_repository_fails_closed_when_publication_scope_identity_is_missing(monkeypatch):
    valuation_payload = _fresh_payload(
        "equity.valuation.fact",
        "valuation-release",
        [],
    )
    valuation_payload.pop("dataset_key")
    context = {
        "002493.SZ": {
            "price": _fresh_payload("equity.price.bar", "price-release", []),
            "financial": _fresh_payload("equity.financial.fact", "financial-release", []),
            "valuation": valuation_payload,
        }
    }
    monkeypatch.setattr(
        fundamentals_repository,
        "get_published_equity_analysis_context_payloads",
        lambda *_args, **_kwargs: context,
    )
    repository = object.__new__(StockFundamentalsRepositoryMixin)

    result = repository.get_published_valuation_inputs(
        "002493.SZ", date(2026, 1, 1), date(2026, 5, 12), publication_key="release-1"
    )

    gate = result.publication_gates["equity.valuation.fact"]
    assert gate is not None
    assert gate.must_not_use_for_decision is True
    assert gate.blocked_reason == "publication_scope_mismatch"
