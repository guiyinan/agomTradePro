"""Dashboard portfolio and holdings interaction views."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


def _generate_allocation_from_positions(positions: list[dict]) -> dict[str, float]:
    """Generate allocation chart data from position dicts, grouped by asset class."""

    allocation: dict[str, float] = {}
    for pos in positions:
        asset_class = pos.get("asset_class_display") or pos.get("asset_class", "其他")
        allocation[asset_class] = allocation.get(asset_class, 0) + pos.get("market_value", 0)
    return allocation


@login_required(login_url="/account/login/")
def position_detail_htmx(request, asset_code: str):
    """Render one position detail modal for HTMX requests."""

    context = _dashboard_views().get_dashboard_detail_query().get_position_detail(
        user_id=request.user.id,
        asset_code=asset_code,
    )
    return render(request, "dashboard/partials/position_detail.html", context)


@login_required(login_url="/account/login/")
def positions_list_htmx(request):
    """Render the holdings table partial with optional account and sort filters."""

    dashboard_views = _dashboard_views()
    if "HX-Request" not in request.headers:
        return redirect("dashboard:index")

    try:
        account_id = dashboard_views._parse_positive_int_param(
            request.GET.get("account_id", ""),
            field_name="account_id",
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    positions = dashboard_views._load_simulated_positions_fallback(
        request.user.id,
        account_id=account_id,
    )
    if not positions and not account_id:
        data = dashboard_views._build_dashboard_data(request.user.id)
        data = dashboard_views._ensure_dashboard_positions(data, request.user.id)
        positions = list(data.positions)

    sort_by = request.GET.get("sort", "market_value")
    if sort_by == "code":
        positions.sort(key=lambda p: p.get("asset_code", "") if isinstance(p, dict) else p.asset_code)
    elif sort_by == "pnl_pct":
        positions.sort(
            key=lambda p: (
                p.get("unrealized_pnl_pct", 0)
                if isinstance(p, dict)
                else (p.unrealized_pnl_pct or 0)
            ),
            reverse=True,
        )
    elif sort_by == "market_value":
        positions.sort(
            key=lambda p: p.get("market_value", 0) if isinstance(p, dict) else (p.market_value or 0),
            reverse=True,
        )

    return render(
        request,
        "dashboard/partials/positions_table.html",
        {
            "positions": positions,
            "show_account": not account_id,
        },
    )


@login_required(login_url="/account/login/")
def allocation_chart_htmx(request):
    """Return allocation chart payload for one account or the aggregated portfolio."""

    dashboard_views = _dashboard_views()
    try:
        account_id = dashboard_views._parse_positive_int_param(
            request.GET.get("account_id", ""),
            field_name="account_id",
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    positions = dashboard_views._load_simulated_positions_fallback(
        request.user.id,
        account_id=account_id,
    )
    return JsonResponse(
        {
            "success": True,
            "data": _generate_allocation_from_positions(positions),
        }
    )


@login_required(login_url="/account/login/")
def performance_chart_htmx(request):
    """Return performance chart payload for one account or the aggregated portfolio."""

    dashboard_views = _dashboard_views()
    try:
        account_id = dashboard_views._parse_positive_int_param(
            request.GET.get("account_id", ""),
            field_name="account_id",
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    performance_data = dashboard_views.dashboard_interface_services.build_performance_chart_data(
        user_id=request.user.id,
        account_id=account_id,
    )
    return JsonResponse(
        {
            "success": True,
            "data": performance_data,
        }
    )
