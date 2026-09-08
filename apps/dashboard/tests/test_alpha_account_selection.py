"""Account isolation and selection contracts for the Alpha candidate page."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import RequestFactory

from apps.account.application import alpha_account_selection as selection
from apps.dashboard.interface import alpha_stock_views, views
from core.exceptions import AuthorizationError, ValidationError


def test_alpha_account_resolves_owned_active_portfolio(monkeypatch):
    monkeypatch.setattr(
        selection, "list_investment_account_options", lambda user_id: [{"value": 7}]
    )
    repository = Mock()
    repository.get_portfolio_for_account.return_value = SimpleNamespace(
        id=12, user_id=1, is_active=True
    )
    monkeypatch.setattr(selection, "get_portfolio_api_repository", lambda: repository)
    assert selection.resolve_alpha_account_portfolio(user_id=1, account_id=7) == 12
    repository.get_portfolio_for_account.assert_called_once_with(7)


def test_alpha_account_rejects_other_users_before_mapping_read(monkeypatch):
    monkeypatch.setattr(
        selection, "list_investment_account_options", lambda user_id: [{"value": 7}]
    )
    repository = Mock()
    monkeypatch.setattr(selection, "get_portfolio_api_repository", lambda: repository)
    with pytest.raises(AuthorizationError):
        selection.resolve_alpha_account_portfolio(user_id=1, account_id=8)
    repository.get_portfolio_for_account.assert_not_called()


@pytest.mark.parametrize(
    "portfolio,error",
    [
        (None, ValidationError),
        (SimpleNamespace(id=12, user_id=1, is_active=False), ValidationError),
        (SimpleNamespace(id=12, user_id=2, is_active=True), AuthorizationError),
    ],
)
def test_alpha_account_rejects_missing_inactive_or_foreign_mapping(monkeypatch, portfolio, error):
    monkeypatch.setattr(
        selection, "list_investment_account_options", lambda user_id: [{"value": 7}]
    )
    repository = Mock()
    repository.get_portfolio_for_account.return_value = portfolio
    monkeypatch.setattr(selection, "get_portfolio_api_repository", lambda: repository)
    with pytest.raises(error):
        selection.resolve_alpha_account_portfolio(user_id=1, account_id=7)


def test_alpha_account_and_count_reach_query_without_general_fallback(monkeypatch):
    resolve = Mock(return_value=12)
    monkeypatch.setattr(alpha_stock_views, "resolve_alpha_account_portfolio", resolve)
    load = Mock(
        return_value={
            "items": [{"code": f"stock-{i}"} for i in range(20)],
            "meta": {},
            "pool": {},
            "actionable_candidates": [],
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": None,
        }
    )
    monkeypatch.setattr(views, "_get_alpha_stock_scores_payload", load)
    monkeypatch.setattr(views, "_should_render_alpha_top_candidates", lambda **kwargs: True)
    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "account_id": 7, "top_n": 20, "alpha_scope": "general"},
    )
    request.user = SimpleNamespace(pk=1, id=1, is_authenticated=True, is_active=True)
    response = alpha_stock_views.alpha_stocks_htmx(request)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = json.loads(response.content)["data"]
    assert data["count"] == data["top_n"] == 20
    assert data["alpha_scope"] == "portfolio"
    assert load.call_args.kwargs["portfolio_id"] == 12
    assert load.call_args.kwargs["top_n"] == 20
    resolve.assert_called_once_with(user_id=1, account_id=7)


@pytest.mark.parametrize(
    "error,status",
    [(AuthorizationError("账户不可用"), 403), (ValidationError("尚未关联组合"), 400)],
)
def test_alpha_account_failures_never_load_general_candidates(monkeypatch, error, status):
    monkeypatch.setattr(
        alpha_stock_views, "resolve_alpha_account_portfolio", Mock(side_effect=error)
    )
    load = Mock()
    monkeypatch.setattr(views, "_get_alpha_stock_scores_payload", load)
    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/", {"format": "json", "account_id": 7}
    )
    request.user = SimpleNamespace(pk=1, id=1, is_authenticated=True, is_active=True)
    response = alpha_stock_views.alpha_stocks_htmx(request)
    assert response.status_code == status
    assert response["Content-Type"].startswith("application/json")
    load.assert_not_called()
