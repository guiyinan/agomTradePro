"""资产分析模块 - 资产筛选 API 视图。"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asset_analysis.application.interface_services import (
    build_asset_pool_context,
    screen_equity_assets,
    screen_fund_assets,
    summarize_asset_pool_counts,
)
from apps.asset_analysis.application.pool_service import AssetPoolManager


class AssetPoolScreenAPIView(APIView):
    """
    资产池筛选 API

    POST /asset-analysis/api/screen/{asset_type}/
    """

    def post(self, request, asset_type: str):
        """
        筛选资产并分类到资产池

        URL参数:
            asset_type: 资产类型 (equity/fund/bond/wealth/commodity)
        """
        # 1. 获取筛选条件
        regime = request.data.get("regime")
        min_score = request.data.get("min_score", 0)
        max_score = request.data.get("max_score", 100)
        risk_level = request.data.get("risk_level")
        pool_types = request.data.get("pool_types", ["investable", "watch", "candidate"])

        # 2. 获取评分上下文
        try:
            context_payload = build_asset_pool_context(regime_override=regime)
        except Exception as e:
            return Response({
                "success": False,
                "error": f"获取评分上下文失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 3. 根据资产类型执行筛选
        try:
            if asset_type == "equity":
                scored_assets = screen_equity_assets(context_payload.score_context, request.data)
            elif asset_type == "fund":
                scored_assets = screen_fund_assets(context_payload.score_context, request.data)
            else:
                return Response({
                    "success": False,
                    "error": f"暂不支持 {asset_type} 资产类型"
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "success": False,
                "error": f"筛选失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 4. 创建资产池
        pool_manager = AssetPoolManager()

        # 将 AssetScore 转换为列表（如果需要）
        if not isinstance(scored_assets, list):
            scored_assets = list(scored_assets) if hasattr(scored_assets, '__iter__') else []

        # 创建资产池分类
        from apps.asset_analysis.domain.pool import PoolCategory
        category = PoolCategory.EQUITY if asset_type == "equity" else PoolCategory.FUND

        pools = pool_manager.create_pools(scored_assets, context_payload.score_context, category)

        # 5. 过滤结果
        filtered_assets = []
        for pool_type, entries in pools.items():
            if pool_type.value in pool_types:
                filtered_assets.extend(entries)

        # 6. 应用评分过滤
        filtered_assets = [
            asset for asset in filtered_assets
            if min_score <= asset.total_score <= max_score
        ]

        # 7. 应用风险等级过滤
        if risk_level:
            filtered_assets = [
                asset for asset in filtered_assets
                if asset.risk_level == risk_level
            ]

        # 8. 转换为字典返回
        assets_data = [asset.to_dict() for asset in filtered_assets]

        return Response({
            "success": True,
            "asset_type": asset_type,
            "context": {
                "regime": context_payload.current_regime,
                "policy_level": context_payload.policy_level,
                "sentiment_index": context_payload.sentiment_index,
                "active_signals_count": len(context_payload.active_signals),
            },
            "pools_summary": pool_manager.get_pool_summary(pools),
            "assets": assets_data,
        }, status=status.HTTP_200_OK)


class AssetPoolSummaryAPIView(APIView):
    """
    资产池摘要 API

    GET /asset-analysis/api/pool-summary/
    """

    def get(self, request):
        """获取所有资产池的摘要信息"""
        asset_type = request.query_params.get("asset_type")

        try:
            summary = summarize_asset_pool_counts(asset_type)
            total = sum(summary.values())
            summary["total"] = total

            return Response({
                "success": True,
                "asset_type": asset_type or "all",
                "summary": summary,
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": f"查询资产池摘要失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
