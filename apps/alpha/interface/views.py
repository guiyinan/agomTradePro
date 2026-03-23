"""
Alpha API Views

Django REST Framework 视图定义。
"""

import logging
from datetime import date

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.cache_utils import CACHE_TTL, cached_api

from ..application.services import AlphaService
from ..infrastructure.models import AlphaScoreCacheModel
from .serializers import (
    AlphaResultSerializer,
    GetStockScoresRequestSerializer,
    ProviderStatusSerializer,
    UploadScoresSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_stock_scores(request: Request) -> Response:
    """
    获取股票评分

    GET /api/alpha/scores/

    Query Parameters:
        universe: 股票池标识（默认 csi300）
        trade_date: 交易日期（ISO 格式，默认今天）
        top_n: 返回前 N 只（默认 30，最大 500）
        provider: 强制使用指定 Provider（qlib/cache/simple/etf），留空则自动降级

    Returns:
        {
            "success": true,
            "source": "cache",
            "status": "available",
            "stocks": [...],
            ...
        }
    """
    try:
        # 解析请求参数
        params = GetStockScoresRequestSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        universe = params.validated_data.get("universe", "csi300")
        trade_date = params.validated_data.get("trade_date", date.today())
        top_n = params.validated_data.get("top_n", 30)
        provider_filter = params.validated_data.get("provider", "")
        requested_user = request.user
        requested_user_id = params.validated_data.get("user_id")

        if requested_user_id is not None:
            if not request.user.is_staff:
                return Response(
                    {
                        "success": False,
                        "error": "只有管理员可以通过 user_id 查看其他用户的 Alpha 评分",
                        "source": "none",
                        "status": "forbidden",
                        "stocks": [],
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            requested_user = User.objects.filter(pk=requested_user_id).first()
            if requested_user is None:
                return Response(
                    {
                        "success": False,
                        "error": f"用户 {requested_user_id} 不存在",
                        "source": "none",
                        "status": "not_found",
                        "stocks": [],
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        # 获取评分（传入 user 实现用户隔离，provider_filter 实现强制指定 Provider）
        service = AlphaService()
        result = service.get_stock_scores(
            universe,
            trade_date,
            top_n,
            user=requested_user,
            provider_filter=provider_filter if provider_filter else None,
        )

        # 序列化响应
        serializer = AlphaResultSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"获取股票评分失败: {e}", exc_info=True)
        return Response(
            {
                "success": False,
                "error": str(e),
                "source": "none",
                "status": "error",
                "stocks": [],
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix="alpha_provider_status", ttl_seconds=60, method="GET")
def get_provider_status(request: Request) -> Response:
    """
    获取 Alpha Provider 状态

    GET /api/alpha/providers/status/

    用于诊断和监控，返回所有 Provider 的健康状态。

    Returns:
        {
            "cache": {
                "priority": 10,
                "status": "available",
                "max_staleness_days": 5
            },
            "simple": {
                "priority": 100,
                "status": "available",
                "max_staleness_days": 7
            },
            ...
        }
    """
    try:
        service = AlphaService()
        providers_status = service.get_provider_status()

        # 序列化每个 Provider 的状态
        result = {}
        for name, status_dict in providers_status.items():
            serializer = ProviderStatusSerializer(data=status_dict)
            serializer.is_valid()
            result[name] = serializer.validated_data

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"获取 Provider 状态失败: {e}", exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix="alpha_universes", ttl_seconds=3600, method="GET")
def get_available_universes(request: Request) -> Response:
    """
    获取支持的股票池列表

    GET /api/alpha/universes/

    Returns:
        {
            "universes": ["csi300", "csi500", "sse50", "csi1000"]
        }
    """
    try:
        service = AlphaService()
        universes = service.get_available_universes()

        return Response({"universes": universes}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"获取股票池列表失败: {e}", exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix="alpha_health", ttl_seconds=30, method="GET")
def health_check(request: Request) -> Response:
    """
    Alpha 服务健康检查

    GET /api/alpha/health/

    Returns:
        {
            "status": "healthy",
            "timestamp": "2026-02-05T10:30:00Z",
            "providers": {
                "available": 2,
                "total": 3
            }
        }
    """
    try:
        service = AlphaService()
        providers_status = service.get_provider_status()

        # 统计状态
        total = len(providers_status)
        available = sum(
            1 for s in providers_status.values() if s.get("status") in ["available", "degraded"]
        )

        health_status = "healthy" if available > 0 else "unhealthy"

        return Response(
            {
                "status": health_status,
                "timestamp": timezone.now().isoformat(),
                "providers": {
                    "available": available,
                    "total": total,
                },
            },
            status=status.HTTP_200_OK
            if health_status == "healthy"
            else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    except Exception as e:
        logger.error(f"健康检查失败: {e}", exc_info=True)
        return Response(
            {
                "status": "error",
                "error": str(e),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_scores(request: Request) -> Response:
    """
    上传本地 Qlib 推理结果

    POST /api/alpha/scores/upload/

    Body:
        universe_id: 股票池标识
        asof_date: 信号真实生成日期（ISO）
        intended_trade_date: 计划交易日期（ISO）
        model_id: 模型标识（默认 local_qlib）
        model_artifact_hash: 模型哈希（可选）
        scope: "user"（个人）或 "system"（全局，仅 admin）
        scores: [{code, score, rank, factors, confidence, source}, ...]

    Returns:
        {"success": true, "count": N, "scope": "user"|"system", "id": pk}
    """
    serializer = UploadScoresSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    scope = data.get("scope", "user")

    # 权限检查：只有 admin 能写系统级评分
    if scope == "system" and not request.user.is_staff:
        return Response(
            {"success": False, "error": "只有管理员可以上传系统级评分（scope=system）"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # 确定写入的 user：system 级别 user=None，否则 user=当前用户
    write_user = None if scope == "system" else request.user

    try:
        cache_obj, created = AlphaScoreCacheModel.objects.update_or_create(
            user=write_user,
            universe_id=data["universe_id"],
            intended_trade_date=data["intended_trade_date"],
            provider_source="qlib",
            model_artifact_hash=data.get("model_artifact_hash", "") or "",
            defaults={
                "asof_date": data["asof_date"],
                "model_id": data.get("model_id", "local_qlib"),
                "scores": data["scores"],
                "status": AlphaScoreCacheModel.STATUS_AVAILABLE,
            },
        )

        logger.info(
            f"上传评分成功: user={write_user}, universe={data['universe_id']}, "
            f"date={data['intended_trade_date']}, count={len(data['scores'])}, "
            f"created={created}"
        )

        return Response(
            {
                "success": True,
                "count": len(data["scores"]),
                "scope": scope,
                "id": cache_obj.pk,
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"上传评分失败: {e}", exc_info=True)
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
