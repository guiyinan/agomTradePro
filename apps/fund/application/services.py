"""
Fund 模块 - Application 层服务（资产分析框架集成）

本模块提供基金多维度评分的服务，集成通用资产分析框架。
"""

from dataclasses import replace
from datetime import date
from typing import Dict, List, Optional

from apps.asset_analysis.domain.entities import AssetType
from apps.asset_analysis.domain.services import (
    PolicyMatcher,
    RegimeMatcher,
    SentimentMatcher,
    SignalMatcher,
)
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.fund.domain.entities import FundAssetScore, FundInfo
from apps.fund.application.repository_provider import DjangoFundAssetRepository


class FundMultiDimScorer:
    """
    基金多维度评分服务

    整合通用资产分析框架和基金特有的评分逻辑。
    """

    def __init__(self, asset_repository: DjangoFundAssetRepository):
        """
        初始化评分服务

        Args:
            asset_repository: 基金资产仓储
        """
        self.asset_repo = asset_repository

    def score_batch(
        self,
        funds: list[FundAssetScore],
        context: ScoreContext,
    ) -> list[FundAssetScore]:
        """
        批量评分基金

        Args:
            funds: 基金资产评分实体列表
            context: 评分上下文

        Returns:
            评分后的基金列表（已排序并设置排名）
        """
        # 1. 计算每个基金的通用维度得分
        scored_funds = []
        for fund in funds:
            # 转换为通用 AssetScore 格式计算
            asset_score = self._to_asset_score(fund)

            # 计算四大维度得分
            regime_score = RegimeMatcher.match(asset_score, context.current_regime)
            policy_score = PolicyMatcher.match(asset_score, context.policy_level)
            sentiment_score = SentimentMatcher.match(asset_score, context.sentiment_index)
            signal_score = SignalMatcher.match(asset_score, context.active_signals)

            # 计算综合得分（使用基金默认权重）
            total_score = (
                regime_score * 0.35  # fund 专用权重
                + policy_score * 0.25
                + sentiment_score * 0.25
                + signal_score * 0.15
            )

            # 更新基金得分
            scored_fund = replace(
                fund,
                regime_score=regime_score,
                policy_score=policy_score,
                sentiment_score=sentiment_score,
                signal_score=signal_score,
                total_score=total_score,
            )
            scored_funds.append(scored_fund)

        # 2. 按综合得分排序
        scored_funds.sort(key=lambda x: x.total_score, reverse=True)

        # 3. 设置排名和推荐比例
        for rank, fund in enumerate(scored_funds, start=1):
            # 计算推荐比例
            if rank <= 3:
                allocation = 20.0
            elif rank <= 10:
                allocation = 10.0
            else:
                allocation = 0.0

            # 计算风险等级
            risk_level = self._calculate_risk_level(fund)

            scored_funds[rank - 1] = replace(
                fund,
                rank=rank,
                allocation_percent=allocation,
                risk_level=risk_level,
            )

        return scored_funds

    def screen_funds(
        self,
        filters: dict,
        context: ScoreContext,
        max_count: int = 30,
    ) -> dict:
        """
        多维度筛选基金

        Args:
            filters: 过滤条件
            context: 评分上下文
            max_count: 最大返回数量

        Returns:
            筛选结果字典
        """
        # 1. 获取符合条件的基金
        funds = self.asset_repo.get_assets_by_filter(
            asset_type="fund",
            filters=filters,
            max_count=max_count * 2,  # 多取一些，筛选后再截断
        )

        if not funds:
            return {
                "success": False,
                "message": "未找到符合条件的基金",
                "funds": [],
            }

        # 2. 批量评分
        scored_funds = self.score_batch(funds, context)

        # 3. 截取前 N 名
        scored_funds = scored_funds[:max_count]

        # 4. 转换为响应格式
        return {
            "success": True,
            "count": len(scored_funds),
            "funds": [fund.to_dict() for fund in scored_funds],
        }

    @staticmethod
    def _to_asset_score(fund: FundAssetScore):
        """将 FundAssetScore 转换为通用 AssetScore 格式"""
        from apps.asset_analysis.domain.entities import AssetScore, AssetSize, AssetStyle

        # 映射风格
        style_map = {
            "growth": AssetStyle.GROWTH,
            "value": AssetStyle.VALUE,
            "blend": AssetStyle.BLEND,
            "defensive": AssetStyle.DEFENSIVE,
        }
        style = style_map.get(fund.style) if fund.style else None

        # 映射规模
        size_map = {
            "large": AssetSize.LARGE_CAP,
            "mid": AssetSize.MID_CAP,
            "small": AssetSize.SMALL_CAP,
        }
        size = size_map.get(fund.size) if fund.size else None

        return AssetScore(
            asset_type=AssetType.FUND,
            asset_code=fund.fund_code,
            asset_name=fund.fund_name,
            style=style,
            size=size,
            sector=fund.sector,
            custom_scores=fund.get_custom_scores(),
        )

    @staticmethod
    def _calculate_risk_level(fund: FundAssetScore) -> str:
        """
        根据基金属性计算风险等级

        Args:
            fund: 基金资产评分实体

        Returns:
            风险等级字符串
        """
        # 根据基金类型判断
        risk_by_type = {
            "货币型": "低风险",
            "债券型": "中低风险",
            "混合型": "中风险",
            "指数型": "中高风险",
            "股票型": "高风险",
            "QDII": "高风险",
            "商品型": "高风险",
        }

        base_risk = risk_by_type.get(fund.fund_type, "中风险")

        # 根据投资风格调整
        if fund.investment_style == "稳健":
            if base_risk == "高风险":
                base_risk = "中高风险"
            elif base_risk == "中风险":
                base_risk = "中低风险"

        return base_risk


def screen_fund_assets_for_pool(context, filters: dict) -> list[FundAssetScore]:
    """Screen and score fund assets for the shared asset-pool workflow."""
    repo = DjangoFundAssetRepository()
    scorer = FundMultiDimScorer(repo)

    filter_dict: dict = {}
    if filters.get("fund_type"):
        filter_dict["fund_type"] = filters["fund_type"]
    if filters.get("investment_style"):
        filter_dict["investment_style"] = filters["investment_style"]
    if filters.get("min_scale") is not None:
        filter_dict["min_scale"] = filters["min_scale"]

    assets = repo.get_assets_by_filter(asset_type="fund", filters=filter_dict)
    return scorer.score_batch(assets, context)
