"""Application-facing helpers for regime interface views."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.data_center.application.interface_services import get_active_provider_id_by_source
from apps.regime.application.current_regime import resolve_current_regime
from apps.regime.application.repository_provider import (
    get_default_macro_repository,
    get_macro_source_config_gateway,
    get_regime_repository,
)
from apps.regime.application.use_cases import CalculateRegimeV2Request, CalculateRegimeV2UseCase
from shared.infrastructure.cache_service import CacheService


def get_available_regime_sources() -> list[Any]:
    """Return active macro data sources for regime pages."""

    return get_macro_source_config_gateway().list_active_sources()


def get_regime_current_payload(*, as_of_date: date | None = None) -> dict[str, Any]:
    """Return the current regime API payload."""

    latest = resolve_current_regime(as_of_date=as_of_date or date.today())
    return {
        "success": True,
        "data": {
            "observed_at": latest.observed_at,
            "dominant_regime": latest.dominant_regime,
            "confidence": latest.confidence,
            "growth_momentum_z": 0.0,
            "inflation_momentum_z": 0.0,
            "distribution": latest.distribution or {},
            "source": latest.data_source,
            "is_fallback": latest.is_fallback,
            "warnings": latest.warnings,
        },
    }


def calculate_regime_payload(*, data: dict[str, Any]) -> dict[str, Any]:
    """Execute the V2 regime use case and return an API payload."""

    request_obj = CalculateRegimeV2Request(
        as_of_date=data.get("as_of_date", date.today()),
        use_pit=data.get("use_pit", True),
        growth_indicator=data.get("growth_indicator", "PMI"),
        inflation_indicator=data.get("inflation_indicator", "CPI"),
        data_source=data.get("data_source", "akshare"),
    )
    response = CalculateRegimeV2UseCase(get_default_macro_repository()).execute(request_obj)

    snapshot_data = None
    if response.success and response.result:
        snapshot_data = {
            "observed_at": request_obj.as_of_date,
            "dominant_regime": response.result.regime.value,
            "confidence": float(response.result.confidence),
            "growth_momentum_z": 0.0,
            "inflation_momentum_z": 0.0,
            "regime_distribution": response.result.distribution,
            "data_source": request_obj.data_source or "akshare",
            "created_at": timezone.now(),
        }

    return {
        "success": response.success,
        "snapshot": snapshot_data,
        "warnings": response.warnings or [],
        "error": response.error,
        "raw_data": response.raw_data,
        "intermediate_data": None,
    }


def get_regime_history_payload(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    regime: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return a history payload for the regime API."""

    data = get_regime_repository().list_history_payloads(
        start_date=start_date,
        end_date=end_date,
        regime=regime,
        limit=limit,
    )
    return {
        "success": True,
        "count": len(data),
        "data": data,
    }


def get_regime_distribution_payload(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Return distribution stats for the regime API."""

    payload = get_regime_repository().get_distribution_payload(
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "success": True,
        "total": payload["total"],
        "distribution": payload["distribution"],
    }


def get_regime_health_payload() -> dict[str, Any]:
    """Return the regime health endpoint payload."""

    return {
        "status": "healthy",
        "service": "regime",
        "records_count": get_regime_repository().get_snapshot_count(),
    }


def clear_regime_cache_payload() -> dict[str, str]:
    """Clear regime cache surfaces and return the response payload."""

    cache.clear()
    CacheService.invalidate_regime()
    return {
        "status": "success",
        "message": "Regime 缓存已清除，请刷新页面查看最新数据",
    }


def get_regime_dashboard_payload(
    *,
    requested_source: str | None,
    as_of_date: date,
    skip_cache: bool,
) -> dict[str, Any]:
    """Build the regime dashboard template context."""

    available_sources = get_available_regime_sources()
    default_source = available_sources[0].source_type if available_sources else "akshare"
    data_source = requested_source or default_source

    use_case = CalculateRegimeV2UseCase(get_default_macro_repository())
    response, effective_source, auto_warnings = _resolve_dashboard_response(
        use_case=use_case,
        available_sources=available_sources,
        requested_source=requested_source,
        as_of_date=as_of_date,
        skip_cache=skip_cache,
    )
    available_sources = _append_source_option(available_sources, effective_source)
    data_source = effective_source or data_source

    result_v2 = response.result if response and response.success else None
    raw_data_json = json.dumps(response.raw_data) if response and response.raw_data else None
    regime_result = None

    if result_v2:
        growth_series = (response.raw_data or {}).get("growth", []) or []
        inflation_series = (response.raw_data or {}).get("inflation", []) or []

        growth_tail = growth_series[-12:]
        inflation_tail = inflation_series[-12:]

        def _safe_float(value: Any, default: float = 0.0) -> float:
            if value in (None, ""):
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        growth_values = [_safe_float(item.get("value")) for item in growth_tail]
        inflation_values = [_safe_float(item.get("value")) for item in inflation_tail]

        def _trend(values: list[float]) -> str:
            if len(values) < 2:
                return "flat"
            if values[-1] > values[-2]:
                return "up"
            if values[-1] < values[-2]:
                return "down"
            return "flat"

        regime_result = {
            "quadrant": result_v2.regime.value,
            "confidence": round(float(result_v2.confidence), 4),
            "distribution": dict(result_v2.distribution or {}),
            "pmi_value": round(float(result_v2.growth_level), 2),
            "cpi_value": round(float(result_v2.inflation_level), 2),
            "pmi_trend": _trend(growth_values),
            "cpi_trend": _trend(inflation_values),
            "growth_dates": json.dumps([item.get("date") for item in growth_tail], ensure_ascii=False),
            "growth_values": json.dumps(growth_values, ensure_ascii=False),
            "inflation_dates": json.dumps([item.get("date") for item in inflation_tail], ensure_ascii=False),
            "inflation_values": json.dumps(inflation_values, ensure_ascii=False),
        }

    return {
        "result_v2": result_v2,
        "regime_result": regime_result,
        "warnings": ((response.warnings if response and response.success else []) + auto_warnings),
        "error": response.error if response and not response.success else None,
        "current_date": date.today(),
        "as_of_date": as_of_date,
        "raw_data": response.raw_data if response and response.success else None,
        "raw_data_json": raw_data_json,
        "current_source": data_source,
        "current_source_provider_id": get_active_provider_id_by_source(data_source) if data_source else None,
        "available_sources": available_sources,
    }


def _build_regime_v2_response(
    *,
    use_case: CalculateRegimeV2UseCase,
    as_of_date: date,
    data_source: str | None,
    skip_cache: bool,
):
    """Execute the V2 regime use case with a consistent request payload."""

    request_obj = CalculateRegimeV2Request(
        as_of_date=as_of_date,
        use_pit=True,
        growth_indicator="PMI",
        inflation_indicator="CPI",
        data_source=data_source,
        skip_cache=skip_cache,
    )
    return use_case.execute(request_obj)


def _append_source_option(
    available_sources: list[Any],
    source_type: str | None,
) -> list[Any]:
    """Ensure the effective source is visible in the selector."""

    if not source_type:
        return available_sources

    if any(getattr(source, "source_type", None) == source_type for source in available_sources):
        return available_sources

    fallback_names = {
        "akshare": "AKShare",
        "tushare": "Tushare Pro",
    }
    return [
        *available_sources,
        SimpleNamespace(source_type=source_type, name=fallback_names.get(source_type, source_type)),
    ]


def _resolve_dashboard_response(
    *,
    use_case: CalculateRegimeV2UseCase,
    available_sources: list[Any],
    requested_source: str | None,
    as_of_date: date,
    skip_cache: bool,
):
    """Resolve the effective source for dashboard rendering."""

    candidate_sources: list[str | None] = []
    explicit_source = bool(requested_source)

    if explicit_source:
        candidate_sources.append(requested_source)
    else:
        candidate_sources.extend(
            getattr(source, "source_type", None)
            for source in available_sources
            if getattr(source, "source_type", None)
        )
        candidate_sources.extend(["akshare", "tushare", None])

    deduped_candidates: list[str | None] = []
    seen: set[str | None] = set()
    for candidate in candidate_sources:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped_candidates.append(candidate)

    last_response = None
    selected_source = requested_source
    warnings: list[str] = []
    primary_source = deduped_candidates[0] if deduped_candidates else None

    for candidate in deduped_candidates:
        response = _build_regime_v2_response(
            use_case=use_case,
            as_of_date=as_of_date,
            data_source=candidate,
            skip_cache=skip_cache,
        )
        last_response = response
        if response.success and response.result is not None:
            selected_source = candidate
            if not explicit_source and primary_source and candidate != primary_source:
                warnings.append(
                    f"默认数据源 {primary_source} 暂无 Regime 所需数据，已自动切换到 {candidate or 'all'}。"
                )
            return response, selected_source, warnings

    return last_response, selected_source, warnings
