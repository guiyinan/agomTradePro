"""Dashboard V1 API views."""

from __future__ import annotations

from datetime import date

from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.account.interface.authentication import MultiTokenAuthentication
from core.cache_utils import CACHE_TTL, cached_api


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="dashboard_summary",
    ttl_seconds=CACHE_TTL["dashboard_summary"],
    include_user=True,
)
def dashboard_summary_v1(request):
    """Summary endpoint for Streamlit dashboard."""

    dashboard_views = _dashboard_views()
    data = dashboard_views._build_dashboard_data(request.user.id)
    return Response(
        {
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "display_name": data.display_name,
            },
            "regime": {
                "current": data.current_regime,
                "confidence": data.regime_confidence,
                "date": data.regime_date.isoformat() if data.regime_date else None,
            },
            "portfolio": {
                "total_assets": data.total_assets,
                "initial_capital": data.initial_capital,
                "total_return": data.total_return,
                "total_return_pct": data.total_return_pct,
                "cash_balance": data.cash_balance,
                "invested_value": data.invested_value,
                "invested_ratio": data.invested_ratio,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="regime_quadrant",
    ttl_seconds=CACHE_TTL["regime_current"],
    include_user=False,
)
def regime_quadrant_v1(request):
    """Regime quadrant data for Streamlit visualization."""

    dashboard_views = _dashboard_views()
    data = dashboard_views._build_dashboard_data(request.user.id)
    return Response(
        {
            "current_regime": data.current_regime,
            "distribution": data.regime_distribution or {},
            "confidence": data.regime_confidence,
            "as_of_date": data.regime_date.isoformat() if data.regime_date else None,
            "macro": {
                "pmi": data.pmi_value,
                "cpi": data.cpi_value,
                "growth_momentum_z": data.growth_momentum_z,
                "inflation_momentum_z": data.inflation_momentum_z,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
def equity_curve_v1(request):
    """Equity curve data for Streamlit."""

    dashboard_views = _dashboard_views()
    requested_range = request.GET.get("range", "ALL").upper()
    data = dashboard_views._build_dashboard_data(request.user.id)
    series = data.performance_data if hasattr(data, "performance_data") else []

    if not series:
        # Defensive fallback for first-load or empty-history edge cases.
        series = [
            {
                "date": date.today().isoformat(),
                "portfolio_value": data.total_assets,
                "return_pct": data.total_return_pct,
            }
        ]

    return Response(
        {
            "range": requested_range,
            "has_history": bool(data.performance_data),
            "series": series,
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="signal_status",
    ttl_seconds=CACHE_TTL["signal_list"],
    vary_on=["limit"],
    include_user=True,
)
def signal_status_v1(request):
    """Signal status and recent signal list for Streamlit."""

    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), 200))
    except ValueError:
        limit = 50

    dashboard_views = _dashboard_views()
    data = dashboard_views._build_dashboard_data(request.user.id)
    signals = data.active_signals if data.active_signals else []
    return Response(
        {
            "stats": data.signal_stats,
            "signals": signals[:limit],
            "limit": limit,
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
def alpha_decision_chain_v1(request):
    """Unified Alpha ranking -> actionable -> pending chain for dashboard/MCP/SDK."""

    dashboard_views = _dashboard_views()
    try:
        top_n = dashboard_views._parse_positive_int_param(
            request.GET.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        max_candidates = dashboard_views._parse_positive_int_param(
            request.GET.get("max_candidates", 5),
            field_name="max_candidates",
            default=5,
        )
        max_pending = dashboard_views._parse_positive_int_param(
            request.GET.get("max_pending", 10),
            field_name="max_pending",
            default=10,
        )
    except ValueError as exc:
        return Response({"success": False, "error": str(exc)}, status=400)

    chain_data = dashboard_views._get_alpha_decision_chain_data(
        top_n=top_n,
        ic_days=30,
        max_candidates=max_candidates,
        max_pending=max_pending,
        user=request.user,
    )
    if chain_data is None:
        return Response(
            {"success": False, "error": "alpha_decision_chain_unavailable"},
            status=503,
        )

    return Response(
        {
            "success": True,
            "summary": chain_data.summary,
            "top_stocks": chain_data.top_stocks,
            "alpha_provider_status": chain_data.alpha_provider_status,
            "coverage_metrics": chain_data.coverage_metrics,
            "ic_trends": chain_data.ic_trends,
            "workflow": chain_data.workflow,
            "decision_readiness": chain_data.decision_readiness,
            "warnings": chain_data.warnings,
            "generated_at": chain_data.generated_at,
        }
    )
