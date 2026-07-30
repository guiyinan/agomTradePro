"""资产分析模块 - 资产筛选 API 视图。"""

import logging

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asset_analysis.application.interface_services import (
    build_asset_pool_context,
    screen_equity_assets,
    screen_fund_assets,
    summarize_asset_pool_counts,
)
from apps.asset_analysis.application.pool_service import AssetPoolManager
from apps.asset_analysis.application.repository_provider import (
    get_asset_pool_query_repository,
)
from shared.request_payload import request_data_mapping

logger = logging.getLogger(__name__)


class AssetPoolScreenAPIView(APIView):
    """
    资产池筛选 API

    POST /asset-analysis/api/screen/{asset_type}/
    """

    def post(self, request: Request, asset_type: str) -> Response:
        """
        筛选资产并分类到资产池

        URL参数:
            asset_type: 资产类型 (equity/fund/bond/wealth/commodity)
        """
        # 1. 获取筛选条件
        request_payload = request_data_mapping(request)
        regime = request_payload.get("regime")
        min_score = request_payload.get("min_score", 0)
        max_score = request_payload.get("max_score", 100)
        risk_level = request_payload.get("risk_level")
        pool_types = request_payload.get("pool_types", ["investable", "watch", "candidate"])

        # 2. 获取评分上下文
        try:
            context_payload = build_asset_pool_context(regime_override=regime)
        except Exception as exc:
            logger.error("获取资产池评分上下文失败: %s", type(exc).__name__)
            return Response(
                {
                    "success": False,
                    "error": "获取评分上下文失败",
                    "error_code": "ASSET_POOL_CONTEXT_FAILED",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if context_payload.sentiment_must_not_use_for_decision:
            return Response(
                {
                    "success": False,
                    "error": "当前情绪数据未通过新鲜度校验，资产筛选已阻断",
                    "error_code": "ASSET_POOL_SENTIMENT_STALE",
                    "must_not_use_for_decision": True,
                    "blocked_reason": context_payload.sentiment_blocked_reason,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 3. 根据资产类型执行筛选
        try:
            if asset_type == "equity":
                scored_assets = screen_equity_assets(
                    context_payload.score_context,
                    request_payload,
                )
            elif asset_type == "fund":
                scored_assets = screen_fund_assets(
                    context_payload.score_context,
                    request_payload,
                )
            else:
                return Response(
                    {"success": False, "error": f"暂不支持 {asset_type} 资产类型"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as exc:
            logger.error("资产池筛选失败: %s", type(exc).__name__)
            return Response(
                {
                    "success": False,
                    "error": "资产筛选失败",
                    "error_code": "ASSET_POOL_SCREEN_FAILED",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 4. 创建资产池
        # 将 AssetScore 转换为列表（如果需要）
        if not isinstance(scored_assets, list):
            scored_assets = list(scored_assets) if hasattr(scored_assets, "__iter__") else []

        # 创建资产池分类
        from apps.asset_analysis.domain.pool import PoolCategory

        category = PoolCategory.EQUITY if asset_type == "equity" else PoolCategory.FUND

        try:
            pool_configs = get_asset_pool_query_repository().list_active_pool_configs()
            pool_manager = AssetPoolManager(pool_configs)
            pools = pool_manager.create_pools(
                scored_assets,
                context_payload.score_context,
                category,
            )
        except (TypeError, ValueError) as exc:
            logger.error("资产池分类配置失败: %s", type(exc).__name__)
            return Response(
                {
                    "success": False,
                    "error": "资产池分类配置无效或缺失",
                    "error_code": "ASSET_POOL_CONFIG_INVALID",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 5. 过滤结果
        filtered_assets = []
        for pool_type, entries in pools.items():
            if pool_type.value in pool_types:
                filtered_assets.extend(entries)

        # 6. 应用评分过滤
        filtered_assets = [
            asset for asset in filtered_assets if min_score <= asset.total_score <= max_score
        ]

        # 7. 应用风险等级过滤
        if risk_level:
            filtered_assets = [asset for asset in filtered_assets if asset.risk_level == risk_level]

        # 8. 转换为字典返回
        assets_data = [asset.to_dict() for asset in filtered_assets]

        return Response(
            {
                "success": True,
                "asset_type": asset_type,
                "context": {
                    "regime": context_payload.current_regime,
                    "policy_level": context_payload.policy_level,
                    "sentiment_index": context_payload.sentiment_index,
                    "sentiment_observed_at": context_payload.sentiment_observed_at,
                    "sentiment_freshness_status": context_payload.sentiment_freshness_status,
                    "sentiment_must_not_use_for_decision": (
                        context_payload.sentiment_must_not_use_for_decision
                    ),
                    "sentiment_blocked_reason": context_payload.sentiment_blocked_reason,
                    "active_signals_count": len(context_payload.active_signals),
                },
                "pools_summary": pool_manager.get_pool_summary(pools),
                "assets": assets_data,
            },
            status=status.HTTP_200_OK,
        )


class AssetPoolSummaryAPIView(APIView):
    """
    资产池摘要 API

    GET /asset-analysis/api/pool-summary/
    """

    def get(self, request: Request) -> Response:
        """获取所有资产池的摘要信息"""
        asset_type = request.query_params.get("asset_type")

        try:
            summary = summarize_asset_pool_counts(asset_type)
            total = sum(summary.values())
            summary["total"] = total

            return Response(
                {
                    "success": True,
                    "asset_type": asset_type or "all",
                    "summary": summary,
                }
            )
        except Exception as exc:
            logger.error("查询资产池摘要失败: %s", type(exc).__name__)
            return Response(
                {
                    "success": False,
                    "error": "查询资产池摘要失败",
                    "error_code": "ASSET_POOL_SUMMARY_FAILED",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
