"""Dashboard Alpha metrics HTMX/API views."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Callable

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from apps.dashboard.application.queries import get_alpha_visualization_query

logger = logging.getLogger(__name__)


def _parse_positive_int_param(
    raw_value: Any,
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


def get_empty_alpha_metrics_data() -> SimpleNamespace:
    """Return empty Alpha metrics for degraded dashboard rendering."""

    return SimpleNamespace(
        stock_scores=[],
        stock_scores_meta={},
        provider_status={
            "providers": {},
            "metrics": {},
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "provider_status_unavailable",
        },
        coverage_metrics={
            "coverage_ratio": 0.0,
            "total_requests": 0,
            "cache_hit_rate": 0.0,
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "coverage_metrics_unavailable",
        },
        ic_trends=[],
        ic_trends_meta={
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        },
    )


def get_alpha_metrics_data(
    *,
    ic_days: int = 30,
    query_factory: Callable[[], Any] | None = None,
):
    """Return Alpha dashboard metrics without reloading stock recommendations."""

    try:
        factory = query_factory or get_alpha_visualization_query
        query = factory()
        if hasattr(query, "execute_metrics"):
            return query.execute_metrics(ic_days=ic_days)
        return query.execute(top_n=0, ic_days=ic_days, user=None)
    except Exception as exc:
        logger.warning("Failed to get alpha metrics data: %s", exc)
        return get_empty_alpha_metrics_data()


def get_alpha_provider_status(
    *,
    user=None,
    query_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return dashboard Alpha provider status payload."""

    try:
        data = get_alpha_metrics_data(ic_days=30, query_factory=query_factory)
        return data.provider_status
    except Exception as exc:
        logger.warning("Failed to get alpha provider status: %s", exc)
        return get_empty_alpha_metrics_data().provider_status


def get_alpha_coverage_metrics(
    *,
    user=None,
    query_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return dashboard Alpha coverage metrics."""

    try:
        data = get_alpha_metrics_data(ic_days=30, query_factory=query_factory)
        return data.coverage_metrics
    except Exception as exc:
        logger.warning("Failed to get alpha coverage metrics: %s", exc)
        return get_empty_alpha_metrics_data().coverage_metrics


def get_alpha_ic_trends_payload(
    *,
    days: int = 30,
    user=None,
    query_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return dashboard Alpha IC trend payload."""

    try:
        data = get_alpha_metrics_data(ic_days=days, query_factory=query_factory)
        return {
            "items": data.ic_trends,
            "status": data.ic_trends_meta.get("status", "available"),
            "data_source": data.ic_trends_meta.get("data_source", "live"),
            "warning_message": data.ic_trends_meta.get("warning_message"),
        }
    except Exception as exc:
        logger.warning("Failed to get alpha IC trends: %s", exc)
        return {
            "items": [],
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        }


def get_alpha_ic_trends(
    *,
    days: int = 30,
    user=None,
    query_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Return only the IC trend items."""

    return get_alpha_ic_trends_payload(days=days, user=user, query_factory=query_factory)["items"]


@login_required(login_url="/account/login/")
def alpha_provider_status_htmx(request):
    """Return provider health for the dashboard Alpha panel."""

    provider_status = get_alpha_provider_status(user=request.user)
    return JsonResponse(
        {
            "success": True,
            "data": provider_status,
            "status": provider_status.get("status", "available"),
            "data_source": provider_status.get("data_source", "live"),
            "warning_message": provider_status.get("warning_message"),
        }
    )


@login_required(login_url="/account/login/")
def alpha_coverage_htmx(request):
    """Return coverage metrics for the dashboard Alpha panel."""

    coverage = get_alpha_coverage_metrics(user=request.user)
    return JsonResponse(
        {
            "success": True,
            "data": coverage,
            "status": coverage.get("status", "available"),
            "data_source": coverage.get("data_source", "live"),
            "warning_message": coverage.get("warning_message"),
        }
    )


@login_required(login_url="/account/login/")
def alpha_ic_trends_htmx(request):
    """Return IC trend series for the dashboard Alpha panel."""

    try:
        days = _parse_positive_int_param(
            request.GET.get("days", 30),
            field_name="days",
            default=30,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    payload = get_alpha_ic_trends_payload(days=days, user=request.user)
    return JsonResponse(
        {
            "success": True,
            "data": payload["items"],
            "status": payload["status"],
            "data_source": payload["data_source"],
            "warning_message": payload["warning_message"],
        }
    )
