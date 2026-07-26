"""Page views for the filter dashboard."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.filter.application.repository_provider import (
    DjangoFilterRepository,
    get_filter_repository,
)
from apps.filter.application.use_cases import (
    ApplyFilterRequest,
    ApplyFilterUseCase,
    GetFilterDataRequest,
    GetFilterDataResponse,
    GetFilterDataUseCase,
)
from apps.filter.domain.entities import FilterSeries, FilterType

logger = logging.getLogger(__name__)


def _get_available_indicators(
    repository: DjangoFilterRepository,
) -> list[dict[str, Any]]:
    """Return database-configured indicators available for filtering."""

    return [
        {str(key): value for key, value in item.items()}
        for item in repository.get_available_indicators()
        if isinstance(item, dict)
    ]


def _validated_numeric_series(values: list[float], *, field_name: str) -> list[float]:
    """Reject non-finite chart values instead of emitting invalid JSON."""

    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        raise ValueError(f"{field_name} contains invalid values")
    return [float(value) for value in values]


def _prepare_chart_data(
    *,
    dates: list[str],
    original_values: list[float],
    filtered_values: list[float],
    slopes: list[float | None],
) -> dict[str, Any]:
    """Prepare a finite, aligned chart payload."""

    if not (len(dates) == len(original_values) == len(filtered_values) == len(slopes)):
        raise ValueError("filter chart series lengths are inconsistent")
    normalized_original = _validated_numeric_series(
        original_values,
        field_name="original_values",
    )
    normalized_filtered = _validated_numeric_series(
        filtered_values,
        field_name="filtered_values",
    )
    normalized_slopes = [
        None if value is None else _validated_numeric_series([value], field_name="slopes")[0]
        for value in slopes
    ]
    return {
        "dates": dates,
        "original_values": normalized_original,
        "filtered_values": normalized_filtered,
        "slopes": normalized_slopes,
        "dates_json": json.dumps(dates, ensure_ascii=False, allow_nan=False),
        "original_values_json": json.dumps(normalized_original, allow_nan=False),
        "filtered_values_json": json.dumps(normalized_filtered, allow_nan=False),
        "slopes_json": json.dumps(normalized_slopes, allow_nan=False),
    }


def _chart_from_saved_response(response: GetFilterDataResponse) -> dict[str, Any]:
    return _prepare_chart_data(
        dates=response.dates,
        original_values=response.original_values,
        filtered_values=response.filtered_values,
        slopes=response.slopes,
    )


def _chart_from_series(series: FilterSeries) -> dict[str, Any]:
    return _prepare_chart_data(
        dates=[value.isoformat() for value in series.dates],
        original_values=series.original_values,
        filtered_values=series.filtered_values,
        slopes=series.slopes,
    )


@login_required(login_url="/account/login/")
def filter_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Render filter data without mutating persisted results from a GET request."""

    context: dict[str, Any] = {
        "current_indicator": "",
        "current_filter_type": "",
        "available_indicators": [],
        "error": None,
        "chart_data": None,
    }
    try:
        repository = get_filter_repository()
        available_indicators = _get_available_indicators(repository)
        context["available_indicators"] = available_indicators
        if not available_indicators:
            context["error"] = "当前没有可用指标，请先在数据中心配置并同步指标。"
            return render(request, "filter/dashboard.html", context)

        available_codes = {str(item.get("code") or "").strip() for item in available_indicators}
        available_codes.discard("")
        default_indicator = str(available_indicators[0].get("code") or "").strip()
        indicator = str(request.GET.get("indicator") or default_indicator).strip()
        if indicator not in available_codes:
            context["error"] = "请求的指标当前不可用。"
            return render(request, "filter/dashboard.html", context)

        filter_type_value = str(request.GET.get("filter_type") or "hp").strip().casefold()
        filter_type_map = {
            "hp": FilterType.HP,
            "kalman": FilterType.KALMAN,
        }
        filter_type = filter_type_map.get(filter_type_value)
        context["current_indicator"] = indicator
        context["current_filter_type"] = filter_type_value
        if filter_type is None:
            context["error"] = "不支持的滤波器类型。"
            return render(request, "filter/dashboard.html", context)

        get_response = GetFilterDataUseCase(repository).execute(
            GetFilterDataRequest(
                indicator_code=indicator,
                filter_type=filter_type,
            )
        )
        if get_response.success:
            context["chart_data"] = _chart_from_saved_response(get_response)
            return render(request, "filter/dashboard.html", context)

        apply_response = ApplyFilterUseCase(repository).execute(
            ApplyFilterRequest(
                indicator_code=indicator,
                filter_type=filter_type,
                save_results=False,
            )
        )
        if apply_response.success and apply_response.series is not None:
            context["chart_data"] = _chart_from_series(apply_response.series)
            context["warnings"] = apply_response.warnings
        else:
            logger.warning(
                "Filter dashboard calculation unavailable: indicator=%s type=%s error=%s",
                indicator,
                filter_type.value,
                apply_response.error,
            )
            context["error"] = "滤波计算暂不可用，请稍后重试。"
    except Exception:
        logger.exception("Failed to build filter dashboard")
        context["error"] = "滤波页面暂不可用，请稍后重试。"

    return render(request, "filter/dashboard.html", context)
