"""Valuation-repair config management API viewset.

Owns `ValuationRepairConfigViewSet` (online parameter tuning with versioning,
effective dates, and audit). The compatibility facade in `views.py` remains the
stable import surface; do not import it here.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.equity.application.interface_services import (
    activate_valuation_repair_config,
    clear_valuation_repair_config_cache_payload,
    create_valuation_repair_config,
    delete_valuation_repair_config,
    get_active_valuation_repair_config_payload,
    get_valuation_repair_config_by_id,
    list_valuation_repair_configs,
    update_valuation_repair_config,
)

from .serializers import (
    ValuationRepairConfigCreateSerializer,
    ValuationRepairConfigSerializer,
)

# ============== 估值修复配置管理 API ==============


class ValuationRepairConfigViewSet(viewsets.ViewSet):
    """估值修复策略参数配置管理

    支持在线调参，包含版本控制、生效时间和审计。

    API 端点：
    - GET /api/equity/config/valuation-repair/ - 列出所有配置版本
    - GET /api/equity/config/valuation-repair/active/ - 获取当前激活的配置
    - POST /api/equity/config/valuation-repair/ - 创建新配置
    - POST /api/equity/config/valuation-repair/{id}/activate/ - 激活指定配置
    - POST /api/equity/config/valuation-repair/{id}/rollback/ - 回滚到指定版本
    """

    permission_classes = [IsAdminUser]

    def list(self, request):
        """GET /api/equity/config/valuation-repair/"""

        serializer = ValuationRepairConfigSerializer(
            list_valuation_repair_configs(),
            many=True,
        )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/equity/config/valuation-repair/{id}/"""

        config = self._get_config_or_404(pk)
        serializer = ValuationRepairConfigSerializer(config)
        return Response(serializer.data)

    def create(self, request):
        """POST /api/equity/config/valuation-repair/"""

        serializer = ValuationRepairConfigCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = create_valuation_repair_config(
            data=serializer.validated_data,
            created_by=self._get_created_by(),
        )
        return Response(
            ValuationRepairConfigSerializer(config).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
        """PUT /api/equity/config/valuation-repair/{id}/"""

        return self._update_config(request, pk=pk, partial=False)

    def partial_update(self, request, pk=None):
        """PATCH /api/equity/config/valuation-repair/{id}/"""

        return self._update_config(request, pk=pk, partial=True)

    def destroy(self, request, pk=None):
        """DELETE /api/equity/config/valuation-repair/{id}/"""

        config_id = self._parse_config_id(pk)
        deleted = delete_valuation_repair_config(config_id=config_id)
        if not deleted:
            raise NotFound("配置不存在")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="获取当前激活配置",
        description="返回当前生效中的估值修复策略参数",
        responses={200: ValuationRepairConfigSerializer},
    )
    @action(detail=False, methods=["get"])
    def active(self, request):
        """GET /api/equity/config/valuation-repair/active/

        获取当前激活的配置
        """
        payload = get_active_valuation_repair_config_payload()

        if payload["source"] == "database":
            data = ValuationRepairConfigSerializer(payload["data"]).data
        else:
            data = payload["data"]
        return Response(
            {
                "success": payload["success"],
                "source": payload["source"],
                "data": data,
            }
        )

    @extend_schema(
        summary="激活指定配置",
        description="将指定版本的配置设置为激活状态（同时停用其他配置）",
        responses={200: ValuationRepairConfigSerializer},
    )
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """POST /api/equity/config/valuation-repair/{id}/activate/

        激活指定配置
        """
        config = activate_valuation_repair_config(config_id=self._parse_config_id(pk))
        if config is None:
            raise NotFound("配置不存在")

        serializer = ValuationRepairConfigSerializer(config)
        return Response(
            {"success": True, "message": f"配置 v{config.version} 已激活", "data": serializer.data}
        )

    @extend_schema(
        summary="回滚到指定版本",
        description="激活指定版本的配置（activate 的别名）",
        responses={200: ValuationRepairConfigSerializer},
    )
    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        """POST /api/equity/config/valuation-repair/{id}/rollback/

        回滚到指定版本（等同于 activate）
        """
        return self.activate(request, pk)

    @extend_schema(
        summary="清除配置缓存",
        description="强制清除配置缓存，下次请求将从数据库或 settings 重新加载",
        responses={200: dict},
    )
    @action(detail=False, methods=["post"])
    def clear_cache(self, request):
        """POST /api/equity/config/valuation-repair/clear_cache/

        清除配置缓存
        """
        return Response(clear_valuation_repair_config_cache_payload())

    def _update_config(self, request, *, pk: str | None, partial: bool) -> Response:
        """Update one config via application service."""

        serializer = ValuationRepairConfigCreateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        config = update_valuation_repair_config(
            config_id=self._parse_config_id(pk),
            data=serializer.validated_data,
        )
        if config is None:
            raise NotFound("配置不存在")
        return Response(ValuationRepairConfigSerializer(config).data)

    def _get_config_or_404(self, pk: str | None):
        """Return one config or raise 404."""

        config = get_valuation_repair_config_by_id(config_id=self._parse_config_id(pk))
        if config is None:
            raise NotFound("配置不存在")
        return config

    def _parse_config_id(self, pk: str | None) -> int:
        """Parse config id from router params."""

        try:
            return int(pk or "")
        except (TypeError, ValueError) as exc:
            raise NotFound("配置不存在") from exc

    def _get_created_by(self) -> str:
        """Resolve actor name for audit fields."""

        if self.request.user.is_authenticated:
            return self.request.user.username
        return "api"


__all__ = ["ValuationRepairConfigViewSet"]
