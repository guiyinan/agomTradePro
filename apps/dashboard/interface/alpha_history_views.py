"""Dashboard Alpha recommendation history views."""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


def _parse_positive_int_param(
    raw_value,
    *,
    field_name: str,
    default: int,
) -> int:
    value = default if raw_value in (None, "") else raw_value
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _get_alpha_homepage_query():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views.get_alpha_homepage_query()


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


@login_required(login_url="/account/login/")
def alpha_history_page(request):
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
        user_id=request.user.id,
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


@login_required(login_url="/account/login/")
def alpha_history_list_api(request):
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
        user_id=request.user.id,
        portfolio_id=parsed_portfolio_id,
        stock_code=str(request.GET.get("stock_code") or "").strip().upper() or None,
        stage=str(request.GET.get("stage") or "").strip() or None,
        source=str(request.GET.get("source") or "").strip() or None,
        trade_date=trade_date_value,
    )
    return JsonResponse({"success": True, "data": runs})


@login_required(login_url="/account/login/")
def alpha_history_detail_api(request, run_id: int):
    """Return one historical recommendation run detail."""

    detail = _get_alpha_homepage_query().get_history_detail(user_id=request.user.id, run_id=run_id)
    if detail is None:
        return JsonResponse({"success": False, "error": "历史记录不存在"}, status=404)
    return JsonResponse({"success": True, "data": detail})
