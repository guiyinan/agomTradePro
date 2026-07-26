"""Dashboard portfolio and holdings interaction views."""

from __future__ import annotations

from types import ModuleType
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from apps.dashboard.interface.api_auth import dashboard_api_view
from shared.numeric import safe_float


def _dashboard_views() -> ModuleType:
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


def _generate_allocation_from_positions(
    positions: list[dict[str, Any]],
) -> dict[str, float]:
    """Generate allocation chart data from position dicts, grouped by asset class."""

    allocation: dict[str, float] = {}
    for pos in positions:
        raw_asset_class = pos.get("asset_class_display") or pos.get("asset_class")
        asset_class = (
            raw_asset_class.strip()
            if isinstance(raw_asset_class, str) and raw_asset_class.strip()
            else "其他"
        )
        market_value = safe_float(pos.get("market_value"))
        if market_value is None or market_value < 0:
            raise ValueError("position_market_value_invalid")
        allocation[asset_class] = allocation.get(asset_class, 0.0) + market_value
    return allocation


@dashboard_api_view(["GET"])
def position_detail_htmx(request: HttpRequest, asset_code: str) -> HttpResponse:
    """Render one position detail modal for HTMX requests."""

    context = (
        _dashboard_views()
        .get_dashboard_detail_query()
        .get_position_detail(
            user_id=request.user.id,
            asset_code=asset_code,
        )
    )
    return render(request, "dashboard/partials/position_detail.html", context)


@dashboard_api_view(["GET"])
def positions_list_htmx(request: HttpRequest) -> HttpResponse:
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
        positions.sort(
            key=lambda p: p.get("asset_code", "") if isinstance(p, dict) else p.asset_code
        )
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
            key=lambda p: (
                p.get("market_value", 0) if isinstance(p, dict) else (p.market_value or 0)
            ),
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


@dashboard_api_view(["GET"])
def positions_json(request: HttpRequest) -> HttpResponse:
    """Return the authenticated user's persisted simulated positions as JSON."""
    positions = _dashboard_views()._load_simulated_positions_fallback(request.user.id)
    return JsonResponse(
        {
            "success": True,
            "data": {
                "positions": positions,
                "total_count": len(positions),
            },
        }
    )


@dashboard_api_view(["GET"])
def allocation_chart_htmx(request: HttpRequest) -> HttpResponse:
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
    try:
        allocation = _generate_allocation_from_positions(positions)
    except ValueError:
        dashboard_views.logger.error(
            "Dashboard allocation unavailable because a position has invalid market value: "
            "user_id=%s account_id=%s",
            request.user.id,
            account_id,
        )
        return JsonResponse(
            {
                "success": False,
                "error": "资产配置数据暂不可用，请先检查持仓市值。",
                "error_code": "allocation_data_unavailable",
                "must_not_use_for_decision": True,
            },
            status=503,
        )
    return JsonResponse(
        {
            "success": True,
            "data": allocation,
        }
    )


@dashboard_api_view(["GET"])
def performance_chart_htmx(request: HttpRequest) -> HttpResponse:
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
