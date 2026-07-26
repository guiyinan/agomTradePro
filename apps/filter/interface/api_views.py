"""
DRF API Views for Filter Operations.

REST API endpoints for filter operations.
"""

from typing import Any, cast

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    IsAdminUser,
    IsAuthenticated,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.repository_provider import DjangoFilterRepository as ApplicationFilterRepository
from ..application.repository_provider import (
    get_filter_repository,
)
from ..application.use_cases import (
    ApplyFilterRequest,
    ApplyFilterUseCase,
    CompareFiltersRequest,
    CompareFiltersUseCase,
    GetFilterDataRequest,
    GetFilterDataUseCase,
)
from ..domain.entities import FilterSeries, FilterType
from .deprecation import FilterDeprecationHeaderMixin
from .serializers import (
    ApplyFilterRequestSerializer,
    CompareFiltersRequestSerializer,
    FilterConfigSerializer,
    GetFilterDataRequestSerializer,
    UpdateFilterConfigRequestSerializer,
)

_FILTER_PUBLIC_ERRORS: dict[str, tuple[str, int]] = {
    "FILTER_DATA_NOT_FOUND": (
        "No data available for the requested indicator.",
        status.HTTP_404_NOT_FOUND,
    ),
    "FILTER_RESULT_NOT_FOUND": (
        "No saved filter data.",
        status.HTTP_404_NOT_FOUND,
    ),
    "UNSUPPORTED_FILTER_TYPE": (
        "Unsupported filter type.",
        status.HTTP_400_BAD_REQUEST,
    ),
    "FILTER_EXECUTION_FAILED": (
        "Filter calculation failed.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
    "FILTER_QUERY_FAILED": (
        "Filter data query failed.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
    "FILTER_COMPARISON_FAILED": (
        "Filter comparison failed.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
    "FILTER_EMPTY_RESULT": (
        "Filter calculation returned no series.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
}


def _filter_failure_response(
    error_code: str | None,
    *,
    fallback_code: str,
) -> Response:
    """Return one stable Filter API failure without exposing internal details."""

    public_code = error_code if error_code in _FILTER_PUBLIC_ERRORS else fallback_code
    message, http_status = _FILTER_PUBLIC_ERRORS[public_code]
    return Response(
        {
            "success": False,
            "error": message,
            "error_code": public_code,
        },
        status=http_status,
    )


def _normalize_indicator_code(indicator_code: str | None) -> str:
    """Validate one path indicator code against the persisted field contract."""

    if indicator_code is None:
        raise ValidationError({"indicator_code": ["This field is required."]})
    normalized = indicator_code.strip()
    if not normalized:
        raise ValidationError({"indicator_code": ["This field may not be blank."]})
    if len(normalized) > 50:
        raise ValidationError(
            {"indicator_code": ["Ensure this field has no more than 50 characters."]}
        )
    return normalized


class DjangoFilterRepository:
    """Compatibility wrapper kept for legacy interface tests."""

    def __init__(self) -> None:
        self._repository = get_filter_repository()

    def get_filter_config(self, indicator_code: str) -> dict[str, Any]:
        return self._repository.get_filter_config(indicator_code)

    def update_filter_config(
        self,
        indicator_code: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._repository.update_filter_config(indicator_code, payload)

    def delete_filter_config(self, indicator_code: str) -> bool:
        return self._repository.delete_filter_config(indicator_code)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._repository, item)


class FilterViewSet(FilterDeprecationHeaderMixin, viewsets.ViewSet):
    """
    滤波器 API ViewSet

    提供：
    - apply: 应用滤波器
    - get_data: 获取已保存的滤波数据
    - compare: 对比 HP 和 Kalman 滤波
    - indicators: 获取可用指标列表
    """

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.repository = DjangoFilterRepository()
        repository = cast(ApplicationFilterRepository, self.repository)
        self.apply_use_case = ApplyFilterUseCase(repository)
        self.get_use_case = GetFilterDataUseCase(repository)
        self.compare_use_case = CompareFiltersUseCase(self.apply_use_case)

    def list(self, request: Request) -> Response:
        """
        获取 Filter API 根信息

        GET /api/filter/
        """
        return Response(
            {
                "success": True,
                "service": "Filter API",
                "endpoints": {
                    "apply": {"method": "POST", "path": "/api/filter/"},
                    "get_data": {"method": "POST", "path": "/api/filter/get-data/"},
                    "compare": {"method": "POST", "path": "/api/filter/compare/"},
                    "indicators": {"method": "GET", "path": "/api/filter/indicators/"},
                    "health": {"method": "GET", "path": "/api/filter/health/"},
                },
            }
        )

    def create(self, request: Request) -> Response:
        """
        应用滤波器

        POST /api/filter/
        {
            "indicator_code": "PMI",
            "filter_type": "HP",
            "limit": 200,
            "save_results": true
        }
        """
        serializer = ApplyFilterRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        if data.get("save_results", True) and not request.user.is_staff:
            return Response(
                {
                    "success": False,
                    "error": "Administrator access is required to persist filter results.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        filter_type = FilterType.HP if data["filter_type"] == "HP" else FilterType.KALMAN

        req = ApplyFilterRequest(
            indicator_code=data["indicator_code"],
            filter_type=filter_type,
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            limit=data.get("limit", 200),
            save_results=data.get("save_results", True),
        )

        response = self.apply_use_case.execute(req)

        if response.success:
            if response.series is None:
                return _filter_failure_response(
                    "FILTER_EMPTY_RESULT",
                    fallback_code="FILTER_EMPTY_RESULT",
                )
            response_data = {
                "success": True,
                "series": _serialize_series(response.series),
                "warnings": response.warnings,
            }
            return Response(response_data)
        return _filter_failure_response(
            response.error_code,
            fallback_code="FILTER_EXECUTION_FAILED",
        )

    @action(detail=False, methods=["POST"], url_path="get-data")
    def get_data(self, request: Request) -> Response:
        """
        获取已保存的滤波数据

        POST /api/filter/get-data/
        {
            "indicator_code": "PMI",
            "filter_type": "HP"
        }
        """
        serializer = GetFilterDataRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        filter_type = FilterType.HP if data["filter_type"] == "HP" else FilterType.KALMAN

        req = GetFilterDataRequest(
            indicator_code=data["indicator_code"],
            filter_type=filter_type,
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )

        response = self.get_use_case.execute(req)

        if response.success:
            return Response(
                {
                    "success": True,
                    "dates": response.dates,
                    "original_values": response.original_values,
                    "filtered_values": response.filtered_values,
                    "slopes": response.slopes,
                }
            )
        return _filter_failure_response(
            response.error_code,
            fallback_code="FILTER_QUERY_FAILED",
        )

    @action(detail=False, methods=["POST"], url_path="compare")
    def compare(self, request: Request) -> Response:
        """
        对比 HP 和 Kalman 滤波

        POST /api/filter/compare/
        {
            "indicator_code": "PMI",
            "limit": 200
        }
        """
        serializer = CompareFiltersRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        req = CompareFiltersRequest(
            indicator_code=data["indicator_code"],
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            limit=data.get("limit", 200),
        )

        response = self.compare_use_case.execute(req)

        if response.success:
            return Response(
                {
                    "success": True,
                    "hp_results": response.hp_results,
                    "kalman_results": response.kalman_results,
                }
            )
        return _filter_failure_response(
            response.error_code,
            fallback_code="FILTER_COMPARISON_FAILED",
        )

    @action(detail=False, methods=["GET"], url_path="indicators")
    def indicators(self, request: Request) -> Response:
        """
        获取可用指标列表

        GET /api/filter/indicators/
        """
        indicators = self.repository.get_available_indicators()
        return Response(
            {
                "success": True,
                "indicators": indicators,
            }
        )

    @action(detail=False, methods=["GET"], url_path="config/(?P<indicator_code>[^/]+)")
    def config(
        self,
        request: Request,
        indicator_code: str | None = None,
    ) -> Response:
        """
        获取滤波器配置

        GET /api/filter/config/PMI/
        """
        indicator_code = _normalize_indicator_code(indicator_code)

        config = self.repository.get_filter_config(indicator_code)
        config["indicator_code"] = indicator_code
        return Response(
            {
                "success": True,
                "config": config,
            }
        )


class FilterHealthView(FilterDeprecationHeaderMixin, APIView):
    """滤波器健康检查"""

    permission_classes: list[type[BasePermission]] = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "status": "healthy",
                "service": "Filter API",
                "filters_available": ["HP", "Kalman"],
            }
        )


class FilterConfigDetailView(FilterDeprecationHeaderMixin, APIView):
    """Canonical filter-config detail endpoint by indicator code."""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.repository = DjangoFilterRepository()

    def get_permissions(self) -> list[BasePermission]:
        """Require administrators for persisted configuration mutations."""

        if self.request.method in {"PATCH", "DELETE"}:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get(self, request: Request, indicator_code: str) -> Response:
        indicator_code = _normalize_indicator_code(indicator_code)
        config = self.repository.get_filter_config(indicator_code)
        config["indicator_code"] = indicator_code
        serializer = FilterConfigSerializer(config)
        return Response({"success": True, "config": serializer.data})

    def patch(self, request: Request, indicator_code: str) -> Response:
        indicator_code = _normalize_indicator_code(indicator_code)
        serializer = UpdateFilterConfigRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = self.repository.update_filter_config(indicator_code, serializer.validated_data)
        response_serializer = FilterConfigSerializer(config)
        return Response({"success": True, "config": response_serializer.data})

    def delete(self, request: Request, indicator_code: str) -> Response:
        indicator_code = _normalize_indicator_code(indicator_code)
        deleted = self.repository.delete_filter_config(indicator_code)
        if not deleted:
            return Response(
                {"success": False, "error": f"Filter config not found: {indicator_code}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "indicator_code": indicator_code})


def _serialize_series(series: FilterSeries) -> dict[str, object]:
    """序列化滤波序列"""
    return {
        "indicator_code": series.indicator_code,
        "filter_type": series.filter_type.value,
        "params": series.params,
        "dates": [r.date.isoformat() for r in series.results],
        "original_values": [r.original_value for r in series.results],
        "filtered_values": [r.filtered_value for r in series.results],
        "slopes": [r.slope for r in series.results],
        "calculated_at": series.calculated_at.isoformat(),
    }
