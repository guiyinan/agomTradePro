"""Dashboard V1 API views."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, cast

from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)
from apps.dashboard.application.auto_advisor_outputs import (
    ReportUserProtocol,
    persist_auto_advisor_weekly_report_outputs,
)
from apps.dashboard.application.query_services import (
    build_auto_advisor_console_payload,
    build_auto_advisor_notifications_payload,
    build_auto_advisor_query_payload,
    build_auto_advisor_weekly_report_history_payload,
    build_auto_advisor_weekly_report_payload,
)
from core.cache_utils import CACHE_TTL, cached_api
from shared.request_payload import request_data_mapping


class _DashboardViewsProtocol(Protocol):
    """Typed boundary for the legacy dashboard view helpers."""

    def _build_dashboard_data(self, user_id: object) -> Any: ...

    def _parse_positive_int_param(
        self,
        value: object,
        *,
        field_name: str,
        default: int,
    ) -> int: ...

    def _get_alpha_decision_chain_data(
        self,
        *,
        top_n: int,
        ic_days: int,
        max_candidates: int,
        max_pending: int,
        user: object,
    ) -> dict[str, Any]: ...


def _dashboard_views() -> _DashboardViewsProtocol:
    from apps.dashboard.interface import views as dashboard_views

    return cast(_DashboardViewsProtocol, dashboard_views)


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="dashboard_summary",
    ttl_seconds=CACHE_TTL["dashboard_summary"],
    include_user=True,
)
def dashboard_summary_v1(request: Request) -> Response:
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
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def auto_advisor_console(request: Request) -> Response:
    """Homepage auto-advisor console payload."""

    account_id = str(request.GET.get("account_id") or "").strip()
    if not account_id:
        return Response(
            {"success": False, "error": "account_id is required"},
            status=400,
        )
    try:
        payload = build_auto_advisor_console_payload(
            account_id=account_id,
            user=request.user,
        )
    except Exception as exc:
        return Response(
            {"success": False, "error": str(exc)},
            status=400,
        )
    return Response({"success": True, "data": payload})


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def auto_advisor_query(request: Request) -> Response:
    """Deterministic personal auto-advisor Q&A payload."""

    account_id = str(request.GET.get("account_id") or "").strip()
    question = str(
        request.GET.get("question") or request.GET.get("q") or request.GET.get("query") or ""
    ).strip()
    if not account_id:
        return Response(
            {"success": False, "error": "account_id is required"},
            status=400,
        )
    if not question:
        return Response(
            {"success": False, "error": "question is required"},
            status=400,
        )
    try:
        payload = build_auto_advisor_query_payload(
            account_id=account_id,
            user=request.user,
            question=question,
        )
    except Exception as exc:
        return Response(
            {"success": False, "error": str(exc)},
            status=400,
        )
    return Response({"success": True, "data": payload})


def _request_param(request: Request, key: str) -> object:
    if request.method == "POST":
        return request_data_mapping(request).get(key)
    return request.GET.get(key)


@api_view(["GET", "POST"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def auto_advisor_weekly_report(request: Request) -> Response:
    """Personal weekly auto-advisor report payload.

    GET is read-only and returns a generated report payload.
    POST generates the report and persists it with diary, notification, and audit outputs.
    """

    account_id = str(_request_param(request, "account_id") or "").strip()
    if not account_id:
        return Response(
            {"success": False, "error": "account_id is required"},
            status=400,
        )
    as_of_raw = str(_request_param(request, "as_of") or "").strip()
    try:
        as_of = date.fromisoformat(as_of_raw) if as_of_raw else None
    except ValueError:
        return Response(
            {"success": False, "error": "as_of must be YYYY-MM-DD"},
            status=400,
        )
    try:
        payload = build_auto_advisor_weekly_report_payload(
            account_id=account_id,
            user=request.user,
            as_of=as_of,
        )
        persisted = None
        if request.method == "POST":
            persisted = persist_auto_advisor_weekly_report_outputs(
                user=cast(ReportUserProtocol, request.user),
                report_payload=payload,
                audit_source="API",
                audit_tool_name="auto_advisor_weekly_report",
                audit_request_method="POST",
                audit_request_path="/api/dashboard/auto-advisor-weekly-report/",
            )
    except Exception as exc:
        return Response(
            {"success": False, "error": str(exc)},
            status=400,
        )
    response_data = dict(payload)
    response_payload = {"success": True, "data": response_data}
    if persisted is not None:
        response_data["persisted"] = persisted
        response_payload["persisted"] = persisted
    return Response(response_payload)


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def auto_advisor_weekly_report_history(request: Request) -> Response:
    """Persisted personal weekly auto-advisor report history."""

    account_id = str(request.GET.get("account_id") or "").strip() or None
    try:
        limit = int(request.GET.get("limit") or 20)
        payload = build_auto_advisor_weekly_report_history_payload(
            account_id=account_id,
            user=request.user,
            limit=limit,
        )
    except Exception as exc:
        return Response(
            {"success": False, "error": str(exc)},
            status=400,
        )
    return Response({"success": True, "data": payload})


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def auto_advisor_notifications(request: Request) -> Response:
    """Stored auto-advisor notification/output items."""

    account_id = str(request.GET.get("account_id") or "").strip() or None
    try:
        limit = int(request.GET.get("limit") or 20)
        payload = build_auto_advisor_notifications_payload(
            account_id=account_id,
            user=request.user,
            limit=limit,
        )
    except Exception as exc:
        return Response(
            {"success": False, "error": str(exc)},
            status=400,
        )
    return Response({"success": True, "data": payload})


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="regime_quadrant",
    ttl_seconds=CACHE_TTL["regime_current"],
    include_user=False,
)
def regime_quadrant_v1(request: Request) -> Response:
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
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def equity_curve_v1(request: Request) -> Response:
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
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
@cached_api(
    key_prefix="signal_status",
    ttl_seconds=CACHE_TTL["signal_list"],
    vary_on=["limit"],
    include_user=True,
)
def signal_status_v1(request: Request) -> Response:
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
@authentication_classes(
    [SessionAuthentication, TerminalInternalAuthentication, MultiTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def alpha_decision_chain_v1(request: Request) -> Response:
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

    overview = dict(chain_data.get("overview") or {})
    return Response(
        {
            "success": True,
            "summary": overview,
            "top_stocks": list(chain_data.get("top_stocks") or []),
            "actionable_candidates": list(chain_data.get("actionable_candidates") or []),
            "pending_requests": list(chain_data.get("pending_requests") or []),
            "alpha_provider_status": overview.get("alpha_provider_status", {}),
            "coverage_metrics": overview.get("coverage_metrics", {}),
            "ic_trends": overview.get("ic_trends", []),
            "workflow": overview.get("workflow", {}),
            "decision_readiness": overview.get("decision_readiness", {}),
            "warnings": overview.get("warnings", []),
            "generated_at": overview.get("generated_at"),
        }
    )
