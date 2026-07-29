"""
Interface Views for Regime Calculation.

DRF Views and page views for regime calculation.

重构说明 (2026-03-11):
- 使用 MacroRepositoryAdapter 替代直接导入 DataCenterMacroRepository
- 使用 DjangoDataSourceConfig 替代直接导入 macro 模块的 DataSourceConfig
- 保持 API 完全兼容
"""

import logging
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.regime.application.interface_services import (
    clear_regime_cache_payload,
    get_available_regime_sources,
    get_regime_dashboard_payload,
)

# API Cache layer
from core.cache_utils import cached_api

logger = logging.getLogger(__name__)


def _parse_as_of_date(value: str | None) -> date:
    """Parse one optional page date without re-parsing on failure paths."""

    return datetime.strptime(value, "%Y-%m-%d").date() if value else date.today()


@login_required
def regime_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Regime 判定仪表板页面（统一使用 V2 水平法）"""
    available_sources = get_available_regime_sources()

    try:
        default_source = available_sources[0].source_type if available_sources else "akshare"
        requested_source = request.GET.get("source")

        # 获取分析时点参数
        as_of_date = _parse_as_of_date(request.GET.get("as_of_date"))

        # 是否跳过缓存（force_refresh 参数）
        skip_cache = request.GET.get("force_refresh") == "1"

        context = get_regime_dashboard_payload(
            requested_source=requested_source,
            as_of_date=as_of_date,
            skip_cache=skip_cache,
        )

    except Exception as exc:
        logger.warning(
            "Regime dashboard payload unavailable; exception_type=%s",
            type(exc).__name__,
        )
        default_source = available_sources[0].source_type if available_sources else "akshare"
        data_source = request.GET.get("source", default_source)
        try:
            as_of_date = _parse_as_of_date(request.GET.get("as_of_date"))
        except ValueError:
            as_of_date = date.today()

        context = {
            "result_v2": None,
            "regime_result": None,
            "warnings": [],
            "error": "regime_dashboard_unavailable",
            "current_date": date.today(),
            "as_of_date": as_of_date,
            "raw_data": None,
            "raw_data_json": None,
            "current_source": data_source,
            "available_sources": available_sources,
        }

    return render(request, "regime/dashboard.html", context)


@require_http_methods(["POST"])
@cached_api(key_prefix="regime_clear_cache", ttl_seconds=0, method="POST")
def clear_regime_cache(request: HttpRequest) -> JsonResponse:
    """清除 Regime 缓存的 API 接口"""
    del request
    try:
        return JsonResponse(clear_regime_cache_payload())
    except Exception as exc:
        logger.warning(
            "Regime cache clear failed; exception_type=%s",
            type(exc).__name__,
        )
        return JsonResponse({"status": "error", "message": "regime_cache_clear_failed"}, status=500)
