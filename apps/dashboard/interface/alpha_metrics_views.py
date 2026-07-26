"""Dashboard Alpha metrics HTMX/API views."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.dashboard.application.queries import (
    AlphaVisualizationData,
    get_alpha_visualization_query,
)
from apps.dashboard.interface.api_auth import dashboard_api_view

logger = logging.getLogger(__name__)
_MAX_ALPHA_IC_DAYS = 3650


class AlphaMetricsQuery(Protocol):
    """Query capability required by the metrics-only dashboard path."""

    def execute_metrics(self, ic_days: int = 30) -> AlphaVisualizationData: ...


AlphaMetricsQueryFactory = Callable[[], AlphaMetricsQuery]


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
    if parsed > _MAX_ALPHA_IC_DAYS:
        raise ValueError(f"{field_name} must not exceed {_MAX_ALPHA_IC_DAYS}")
    return parsed


def _json_object(value: object) -> dict[str, Any]:
    """Normalize a dynamic payload to a string-key mapping."""

    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _json_rows(value: object) -> list[dict[str, Any]]:
    """Normalize a dynamic collection to JSON object rows."""

    if not isinstance(value, list):
        return []
    return [_json_object(item) for item in value if isinstance(item, Mapping)]


def get_empty_alpha_metrics_data() -> AlphaVisualizationData:
    """Return empty Alpha metrics for degraded dashboard rendering."""

    return AlphaVisualizationData(
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
    query_factory: AlphaMetricsQueryFactory | None = None,
) -> AlphaVisualizationData:
    """Return Alpha dashboard metrics without reloading stock recommendations."""

    try:
        factory = query_factory or get_alpha_visualization_query
        data = factory().execute_metrics(ic_days=ic_days)
        provider_status = _json_object(data.provider_status)
        coverage_metrics = _json_object(data.coverage_metrics)
        ic_trends = _json_rows(data.ic_trends)
        ic_trends_meta = _json_object(data.ic_trends_meta)
        if not provider_status or not coverage_metrics or not ic_trends_meta:
            raise ValueError("alpha_metrics_payload_invalid")
        return AlphaVisualizationData(
            stock_scores=_json_rows(data.stock_scores),
            stock_scores_meta=_json_object(data.stock_scores_meta),
            provider_status=provider_status,
            coverage_metrics=coverage_metrics,
            ic_trends=ic_trends,
            ic_trends_meta=ic_trends_meta,
        )
    except Exception as exc:
        logger.warning("Failed to get alpha metrics data: %s", exc)
        return get_empty_alpha_metrics_data()


def get_alpha_provider_status(
    *,
    user: object | None = None,
    query_factory: AlphaMetricsQueryFactory | None = None,
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
    user: object | None = None,
    query_factory: AlphaMetricsQueryFactory | None = None,
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
    user: object | None = None,
    query_factory: AlphaMetricsQueryFactory | None = None,
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
    user: object | None = None,
    query_factory: AlphaMetricsQueryFactory | None = None,
) -> list[dict[str, Any]]:
    """Return only the IC trend items."""

    items = get_alpha_ic_trends_payload(
        days=days,
        user=user,
        query_factory=query_factory,
    ).get("items")
    return _json_rows(items)


@dashboard_api_view(["GET"])
def alpha_provider_status_htmx(request: HttpRequest) -> HttpResponse:
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


@dashboard_api_view(["GET"])
def alpha_coverage_htmx(request: HttpRequest) -> HttpResponse:
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


@dashboard_api_view(["GET"])
def alpha_ic_trends_htmx(request: HttpRequest) -> HttpResponse:
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
