from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.mark.django_db
def test_published_pool_uses_publication_member_context_instead_of_legacy_latest_reads(
    authenticated_client,
) -> None:
    """Published stock-pool metrics must come from the selected publication members."""

    fresh_publication = {
        "publication_id": "equity-facts-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-08-03",
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
    }
    stock_info = SimpleNamespace(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
    )
    published_context = {
        "000001.SZ": {
            "roe": 12.5,
            "revenue_growth": 8.0,
            "profit_growth": 6.0,
            "pe": 7.2,
            "pb": 0.8,
            "must_not_use_for_decision": False,
        }
    }

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-08-03"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[fresh_publication, fresh_publication],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value=published_context,
        ) as context_reader,
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            return_value=stock_info,
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_valuation_history",
            side_effect=AssertionError("published pool must not read unbound valuations"),
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_latest_financial_data",
            side_effect=AssertionError("published pool must not read unbound financials"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["mode"] == "published"
    assert payload["stocks"][0]["roe"] == 12.5
    assert payload["stocks"][0]["pe"] == 7.2
    context_reader.assert_called_once_with(
        ["000001.SZ"],
        publication_key="current",
        include_price=False,
    )


@pytest.mark.django_db
def test_published_pool_blocks_when_publication_member_context_is_missing(
    authenticated_client,
) -> None:
    """A fresh dataset gate cannot hide an absent member fact for a pool asset."""

    fresh_publication = {
        "publication_id": "equity-facts-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-08-03",
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
    }
    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-08-03"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[fresh_publication, fresh_publication],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value={
                "000001.SZ": {
                    "must_not_use_for_decision": True,
                    "blocked_reason": "canonical_publication_members_missing",
                }
            },
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=AssertionError("memberless pool must block before metadata reads"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["stocks"] == []
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "canonical_publication_members_missing"
