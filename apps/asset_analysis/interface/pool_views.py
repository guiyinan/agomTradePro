"""
资产分析模块 - 资产筛选 API 视图
"""

from datetime import date

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asset_analysis.application.pool_service import AssetPoolManager
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.equity.application.services import EquityMultiDimScorer
from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
from apps.fund.application.services import FundMultiDimScorer
from apps.fund.infrastructure.repositories import DjangoFundAssetRepository
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from apps.sentiment.infrastructure.repositories import SentimentIndexRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository


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
            # Regime
            resolved_regime = resolve_current_regime()
            current_regime = regime or (resolved_regime.dominant_regime if resolved_regime else "Recovery")

            # Policy
            policy_repo = DjangoPolicyRepository()
            latest_policy = policy_repo.get_current_policy_level()
            policy_level = latest_policy.value if latest_policy else "P1"

            # Sentiment
            sentiment_repo = SentimentIndexRepository()
            latest_sentiment = sentiment_repo.get_latest()
            sentiment_index = latest_sentiment.composite_index if latest_sentiment else 0.0

            # Signals
            signal_repo = DjangoSignalRepository()
            active_signals = signal_repo.get_active_signals()

            context = ScoreContext(
                current_regime=current_regime,
                policy_level=policy_level,
                sentiment_index=sentiment_index,
                active_signals=active_signals,
            )

        except Exception as e:
            return Response({
                "success": False,
                "error": f"获取评分上下文失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 3. 根据资产类型执行筛选
        try:
            if asset_type == "equity":
                scored_assets = self._screen_equity(context, request.data)
            elif asset_type == "fund":
                scored_assets = self._screen_fund(context, request.data)
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

        pools = pool_manager.create_pools(scored_assets, context, category)

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
                "regime": current_regime,
                "policy_level": policy_level,
                "sentiment_index": sentiment_index,
                "active_signals_count": len(active_signals),
            },
            "pools_summary": pool_manager.get_pool_summary(pools),
            "assets": assets_data,
        }, status=status.HTTP_200_OK)

    def _screen_equity(self, context, filters):
        """筛选股票"""
        repo = DjangoEquityAssetRepository()
        scorer = EquityMultiDimScorer(repo)

        # 获取筛选条件
        sector = filters.get("sector")
        market = filters.get("market")
        min_market_cap = filters.get("min_market_cap")
        max_pe = filters.get("max_pe")

        # 构建过滤条件
        filter_dict = {}
        if sector:
            filter_dict["sector"] = sector
        if market:
            filter_dict["market"] = market
        if min_market_cap is not None:
            filter_dict["min_market_cap"] = min_market_cap
        if max_pe is not None:
            filter_dict["max_pe"] = max_pe

        assets = repo.get_assets_by_filter(asset_type="equity", filters=filter_dict)
        return scorer.score_batch(assets, context)

    def _screen_fund(self, context, filters):
        """筛选基金"""
        repo = DjangoFundAssetRepository()
        scorer = FundMultiDimScorer(repo)

        # 获取筛选条件
        fund_type = filters.get("fund_type")
        investment_style = filters.get("investment_style")
        min_scale = filters.get("min_scale")

        # 构建过滤条件
        filter_dict = {}
        if fund_type:
            filter_dict["fund_type"] = fund_type
        if investment_style:
            filter_dict["investment_style"] = investment_style
        if min_scale is not None:
            filter_dict["min_scale"] = min_scale

        assets = repo.get_assets_by_filter(asset_type="fund", filters=filter_dict)
        return scorer.score_batch(assets, context)


class AssetPoolSummaryAPIView(APIView):
    """
    资产池摘要 API

    GET /asset-analysis/api/pool-summary/
    """

    def get(self, request):
        """获取所有资产池的摘要信息"""
        asset_type = request.query_params.get("asset_type")

        from apps.asset_analysis.domain.pool import PoolType
        from apps.asset_analysis.infrastructure.models import AssetPoolEntry

        try:
            queryset = AssetPoolEntry._default_manager.filter(is_active=True)
            if asset_type:
                queryset = queryset.filter(asset_category=asset_type)

            summary = {}
            total = 0
            for pool_type in PoolType:
                count = queryset.filter(pool_type=pool_type.value).count()
                summary[pool_type.value] = count
                total += count
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
