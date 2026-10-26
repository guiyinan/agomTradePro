"""Dashboard history must not present unknown fee-correction values as current."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.simulated_trading.application import query_services


def _install_repositories(monkeypatch, accounts, records_by_account):
    account_repo = Mock()
    account_repo.get_by_user.return_value = accounts
    daily_repo = Mock()
    daily_repo.list_daily_records.side_effect = lambda account_id, **kwargs: records_by_account[
        account_id
    ]
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(
        query_services, "get_simulated_daily_net_value_repository", lambda: daily_repo
    )
    return account_repo, daily_repo


def test_single_account_keeps_original_but_hides_uncovered_effective_values(monkeypatch):
    today = date.today()
    _install_repositories(
        monkeypatch,
        [SimpleNamespace(account_id=3, initial_capital=100)],
        {
            3: [
                {
                    "record_date": today,
                    "net_value": 95.0,
                    "original_net_value": 100.0,
                    "cumulative_return": -5.0,
                    "original_cumulative_return": 0.0,
                    "cash": 90.0,
                    "market_value": 5.0,
                    "positions_count": 1,
                    "correction_coverage_known": False,
                    "effective_metrics_reason_code": "FEE_CORRECTION_COVERAGE_UNKNOWN",
                }
            ]
        },
    )

    row = query_services.get_user_performance_payload(user_id=17, account_id=3, days=None)[0]

    assert row["portfolio_value"] is None
    assert row["return_pct"] is None
    assert row["cash_balance"] is None
    assert row["original_portfolio_value"] == 100.0
    assert row["original_return_pct"] == 0.0
    assert row["performance_known"] is False
    assert row["performance_reason_code"] == "FEE_CORRECTION_COVERAGE_UNKNOWN"


def test_aggregate_blocks_effective_values_when_any_account_coverage_is_unknown(monkeypatch):
    today = date.today()
    _install_repositories(
        monkeypatch,
        [
            SimpleNamespace(account_id=3, initial_capital=100),
            SimpleNamespace(account_id=4, initial_capital=200),
        ],
        {
            account_id: [
                {
                    "record_date": today,
                    "net_value": account_id * 100,
                    "original_net_value": account_id * 101,
                    "cash": 50.0,
                    "market_value": 10.0,
                    "positions_count": 1,
                    "correction_coverage_known": account_id == 3,
                }
            ]
            for account_id in (3, 4)
        },
    )

    row = query_services.get_user_performance_payload(user_id=17, account_id=None, days=None)[0]

    assert row["portfolio_value"] is None
    assert row["return_pct"] is None
    assert row["cash_balance"] is None
    assert row["original_portfolio_value"] == 707.0
    assert row["performance_known"] is False
    assert row["performance_reason_code"] == "FEE_CORRECTION_COVERAGE_UNKNOWN"


def test_aggregate_known_coverage_preserves_real_zero_return(monkeypatch):
    today = date.today()
    _install_repositories(
        monkeypatch,
        [SimpleNamespace(account_id=3, initial_capital=100)],
        {
            3: [
                {
                    "record_date": today,
                    "net_value": 100.0,
                    "original_net_value": 100.0,
                    "cash": 90.0,
                    "market_value": 10.0,
                    "positions_count": 1,
                    "correction_coverage_known": True,
                }
            ]
        },
    )

    row = query_services.get_user_performance_payload(user_id=17, account_id=None, days=None)[0]

    assert row["return_pct"] == 0.0
    assert row["original_return_pct"] == 0.0
    assert row["performance_known"] is True
    assert row["performance_reason_code"] is None


def test_user_account_totals_recompute_effective_return_and_keep_cached_original(monkeypatch):
    account = SimpleNamespace(
        account_id=3,
        initial_capital=100.0,
        total_value=95.0,
        current_cash=90.0,
        current_market_value=5.0,
        total_return=20.0,
        cash_known=True,
        cash_reconciliation_status=SimpleNamespace(value="simulated_ledger"),
    )
    account_repo = Mock()
    account_repo.get_by_user.return_value = [account]
    position_repo = Mock()
    position_repo.get_by_account.return_value = [SimpleNamespace(quantity=1, valuation_known=True)]
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(query_services, "get_simulated_position_repository", lambda: position_repo)

    totals = query_services.get_user_account_totals(17)

    assert totals is not None
    assert totals["total_assets"] == 95.0
    assert totals["total_return"] == -5.0
    assert totals["total_return_pct"] == -5.0
    assert totals["original_total_return"] == 20.0
    assert totals["original_total_return_pct"] == 20.0
    assert totals["performance_reason_code"] is None


def test_user_account_totals_do_not_zero_fill_unknown_accounts(monkeypatch):
    account_repo = Mock()
    account_repo.get_by_user.return_value = [
        SimpleNamespace(
            account_id=3,
            initial_capital=100.0,
            total_value=95.0,
            current_cash=90.0,
            current_market_value=5.0,
            total_return=20.0,
            cash_known=True,
            cash_reconciliation_status=SimpleNamespace(value="simulated_ledger"),
        ),
        SimpleNamespace(
            account_id=4,
            initial_capital=200.0,
            total_value=180.0,
            current_cash=170.0,
            current_market_value=10.0,
            total_return=5.0,
            cash_known=False,
            cash_reconciliation_status=SimpleNamespace(value="unverified"),
        ),
    ]
    position_repo = Mock()
    position_repo.get_by_account.return_value = [SimpleNamespace(quantity=1, valuation_known=True)]
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(query_services, "get_simulated_position_repository", lambda: position_repo)

    totals = query_services.get_user_account_totals(17)

    assert totals is not None
    assert totals["total_assets"] is None
    assert totals["cash_balance"] is None
    assert totals["total_return"] is None
    assert totals["total_return_pct"] is None
    assert totals["original_total_return"] == 25.0
    assert totals["performance_reason_code"] == "ACCOUNT_CASH_UNKNOWN"


@pytest.mark.parametrize(
    ("cash_known", "valuation_known", "expected_return", "expected_reason"),
    [
        (True, True, -5.0, None),
        (False, True, None, "ACCOUNT_CASH_UNKNOWN"),
        (True, False, None, "POSITION_VALUATION_UNKNOWN"),
    ],
)
def test_dashboard_account_cards_label_stored_return_and_use_effective_equity(
    monkeypatch, cash_known, valuation_known, expected_return, expected_reason
):
    account_repo = Mock()
    account_repo.get_by_user.return_value = [
        SimpleNamespace(
            account_id=3,
            account_name="Correction account",
            account_type="simulated",
            initial_capital=100.0,
            total_value=95.0,
            current_cash=90.0,
            current_market_value=5.0,
            total_return=20.0,
            cash_known=cash_known,
            cash_reconciliation_status=SimpleNamespace(value="simulated_ledger"),
            is_active=True,
        )
    ]
    position_repo = Mock()
    position_repo.get_by_account.return_value = [
        SimpleNamespace(quantity=1, valuation_known=valuation_known)
    ]
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(query_services, "get_simulated_position_repository", lambda: position_repo)

    row = query_services.list_dashboard_account_payloads(17)[0]

    assert row["total_return"] == expected_return
    assert row["original_total_return"] == 20.0
    assert row["performance_metrics_known"] is (expected_return is not None)
    assert row["performance_reason_code"] == expected_reason
