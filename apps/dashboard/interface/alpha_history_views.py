"""Dashboard Alpha recommendation history views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from types import ModuleType
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery
from apps.dashboard.interface.api_auth import dashboard_api_view


def _parse_positive_int_param(
    raw_value: object,
    *,
    field_name: str,
    default: int,
) -> int:
    value = default if raw_value in (None, "") else raw_value
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _get_alpha_homepage_query() -> AlphaHomepageQuery:
    from apps.dashboard.interface import views as dashboard_views

    query_factory = cast(
        Callable[[], AlphaHomepageQuery],
        dashboard_views.get_alpha_homepage_query,
    )
    return query_factory()


def _dashboard_views() -> ModuleType:
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


def _authenticated_user_id(request: HttpRequest) -> int:
    """Return a persisted authenticated user ID or fail closed."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("authenticated_user_id_required")
    return user_id


@login_required(login_url="/account/login/")
def alpha_history_page(request: HttpRequest) -> HttpResponse:
    """Dashboard Alpha recommendation history page."""

    portfolio_id = request.GET.get("portfolio_id")
    stock_code = str(request.GET.get("stock_code") or "").strip().upper() or None
    stage = str(request.GET.get("stage") or "").strip() or None
    source = str(request.GET.get("source") or "").strip() or None
    try:
        parsed_portfolio_id = (
            _parse_positive_int_param(portfolio_id, field_name="portfolio_id", default=0)
            if portfolio_id not in (None, "")
            else None
        )
    except ValueError:
        parsed_portfolio_id = None

    runs = _get_alpha_homepage_query().list_history(
        user_id=_authenticated_user_id(request),
        portfolio_id=parsed_portfolio_id,
        stock_code=stock_code,
        stage=stage,
        source=source,
    )
    dashboard_views = _dashboard_views()
    current_alpha_payload = dashboard_views._get_alpha_stock_scores_payload(
        top_n=10,
        user=request.user,
        portfolio_id=parsed_portfolio_id,
        pool_mode=None,
        alpha_scope=dashboard_views.ALPHA_SCOPE_PORTFOLIO,
    )
    context = {
        "history_runs": runs,
        "current_exit_watchlist": dashboard_views._mark_alpha_exit_watchlist_selection(
            dashboard_views._annotate_alpha_exit_watchlist_navigation(
                current_alpha_payload.get("exit_watchlist", []),
                alpha_scope=dashboard_views.ALPHA_SCOPE_PORTFOLIO,
                portfolio_id=parsed_portfolio_id
                or current_alpha_payload.get("pool", {}).get("portfolio_id"),
            )
        ),
        "current_exit_watch_summary": current_alpha_payload.get("exit_watch_summary", {}),
        "current_exit_dashboard_url": dashboard_views._build_dashboard_exit_detail_url(
            asset_code="",
            alpha_scope=dashboard_views.ALPHA_SCOPE_PORTFOLIO,
            portfolio_id=parsed_portfolio_id
            or current_alpha_payload.get("pool", {}).get("portfolio_id"),
        ),
        "current_exit_portfolio_id": parsed_portfolio_id
        or current_alpha_payload.get("pool", {}).get("portfolio_id"),
        "current_exit_alpha_scope": dashboard_views.ALPHA_SCOPE_PORTFOLIO,
        "filters": {
            "portfolio_id": parsed_portfolio_id,
            "stock_code": stock_code or "",
            "stage": stage or "",
            "source": source or "",
        },
    }
    return render(request, "dashboard/alpha_history.html", context)


@dashboard_api_view(["GET"])
def alpha_history_list_api(request: HttpRequest) -> HttpResponse:
    """Return recommendation history list for the current user."""

    portfolio_id = request.GET.get("portfolio_id")
    trade_date_raw = request.GET.get("trade_date")
    try:
        parsed_portfolio_id = (
            _parse_positive_int_param(portfolio_id, field_name="portfolio_id", default=0)
            if portfolio_id not in (None, "")
            else None
        )
        trade_date_value = date.fromisoformat(trade_date_raw) if trade_date_raw else None
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    runs = _get_alpha_homepage_query().list_history(
        user_id=_authenticated_user_id(request),
        portfolio_id=parsed_portfolio_id,
        stock_code=str(request.GET.get("stock_code") or "").strip().upper() or None,
        stage=str(request.GET.get("stage") or "").strip() or None,
        source=str(request.GET.get("source") or "").strip() or None,
        trade_date=trade_date_value,
    )
    return JsonResponse({"success": True, "data": runs})


@dashboard_api_view(["GET"])
def alpha_history_detail_api(request: HttpRequest, run_id: int) -> HttpResponse:
    """Return one historical recommendation run detail."""

    if run_id <= 0:
        return JsonResponse(
            {"success": False, "error": "run_id must be a positive integer"},
            status=400,
        )
    detail = _get_alpha_homepage_query().get_history_detail(
        user_id=_authenticated_user_id(request),
        run_id=run_id,
    )
    if detail is None:
        return JsonResponse({"success": False, "error": "历史记录不存在"}, status=404)
    return JsonResponse({"success": True, "data": detail})
