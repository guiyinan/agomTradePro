"""
Account Application - Volatility Control Use Cases

波动率目标控制用例编排。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from apps.account.domain.services import (
    VolatilityAdjustmentResult,
    VolatilityCalculator,
    VolatilityMetrics,
    VolatilityTargetService,
)
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PortfolioSnapshotRepository,
    PositionRepository,
)


@dataclass
class VolatilityAnalysisOutput:
    """波动率分析输出"""
    portfolio_id: int
    current_volatility_30d: float     # 30天波动率
    current_volatility_60d: float     # 60天波动率
    current_volatility_90d: float     # 90天波动率
    target_volatility: float          # 目标波动率
    adjustment_result: VolatilityAdjustmentResult
    volatility_history: list[VolatilityMetrics]  # 历史波动率序列


class VolatilityAnalysisUseCase:
    """
    波动率分析用例

    分析投资组合的波动率，评估是否需要调整仓位。
    """

    def __init__(
        self,
        portfolio_repo: PortfolioRepository = None,
        account_repo: AccountRepository = None,
        snapshot_repo: PortfolioSnapshotRepository = None,
    ):
        self.portfolio_repo = portfolio_repo or PortfolioRepository()
        self.account_repo = account_repo or AccountRepository()
        self.snapshot_repo = snapshot_repo or PortfolioSnapshotRepository()

    def analyze_portfolio_volatility(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAnalysisOutput:
        """
        分析投资组合波动率

        Args:
            portfolio_id: 投资组合ID
            user_id: 用户ID（验证权限）

        Returns:
            VolatilityAnalysisOutput: 波动率分析结果
        """
        # 获取投资组合
        if not self.portfolio_repo.user_owns_portfolio(portfolio_id, user_id):
            raise ValueError(f"投资组合 {portfolio_id} 不存在或无权限")

        # 获取用户账户配置（目标波动率）
        profile = self.account_repo.get_volatility_settings(user_id)
        if profile:
            target_volatility = profile["target_volatility"]
            tolerance = profile["volatility_tolerance"]
            max_reduction = profile["max_volatility_reduction"]
        else:
            # 使用默认值
            target_volatility = 0.15
            tolerance = 0.2
            max_reduction = 0.5

        # 获取历史快照数据（最近90天）
        snapshots = self.snapshot_repo.get_snapshots_for_volatility(portfolio_id=portfolio_id, days=90)
        snapshot_data = [
            {
                "date": snap["snapshot_date"],
                "total_value": snap["total_value"],
            }
            for snap in snapshots
        ]

        # 计算不同窗口的波动率
        vol_30d = self._calculate_volatility_for_window(snapshot_data, 30)
        vol_60d = self._calculate_volatility_for_window(snapshot_data, 60)
        vol_90d = self._calculate_volatility_for_window(snapshot_data, 90)

        # 使用30天波动率作为主要指标
        current_volatility = vol_30d

        # 评估是否需要调整
        adjustment_result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=current_volatility,
            target_volatility=target_volatility,
            tolerance=tolerance,
            max_reduction=max_reduction,
        )

        # 计算历史波动率序列
        volatility_history = VolatilityCalculator.calculate_portfolio_volatility(
            daily_snapshots=snapshot_data,
            window_days=30,
        )

        return VolatilityAnalysisOutput(
            portfolio_id=portfolio_id,
            current_volatility_30d=vol_30d,
            current_volatility_60d=vol_60d,
            current_volatility_90d=vol_90d,
            target_volatility=target_volatility,
            adjustment_result=adjustment_result,
            volatility_history=volatility_history,
        )

    def _calculate_volatility_for_window(
        self,
        snapshots: list[dict],
        window_days: int,
    ) -> float:
        """
        计算指定窗口的波动率

        Args:
            snapshots: 快照数据
            window_days: 窗口天数

        Returns:
            年化波动率
        """
        if len(snapshots) < 2:
            return 0.0

        # 计算收益率
        returns = []
        for i in range(1, len(snapshots)):
            prev_value = snapshots[i - 1]["total_value"]
            curr_value = snapshots[i]["total_value"]
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)

        # 计算波动率
        if len(returns) < 2:
            return 0.0

        metrics = VolatilityCalculator.calculate_volatility(
            returns=returns[-window_days:] if len(returns) >= window_days else returns,
            window_days=window_days,
            annualize=True,
        )

        return metrics.annualized_volatility


class VolatilityAdjustmentUseCase:
    """
    波动率调整执行用例

    根据波动率分析结果执行仓位调整。
    """

    def __init__(self, position_repo: PositionRepository = None):
        self.position_repo = position_repo or PositionRepository()

    def execute_volatility_adjustment(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> dict:
        """
        执行波动率调整

        Args:
            portfolio_id: 投资组合ID
            user_id: 用户ID

        Returns:
            执行结果
        """
        # 分析波动率
        analysis_use_case = VolatilityAnalysisUseCase()
        analysis = analysis_use_case.analyze_portfolio_volatility(
            portfolio_id=portfolio_id,
            user_id=user_id,
        )

        adjustment = analysis.adjustment_result

        # 如果不需要调整，直接返回
        if not adjustment.should_reduce:
            return {
                "status": "no_action",
                "message": "波动率正常，无需调整",
                "current_volatility": adjustment.current_volatility,
                "target_volatility": adjustment.target_volatility,
            }

        # 执行降仓（按比例减少所有持仓）
        multiplier = adjustment.suggested_position_multiplier

        # 获取所有持仓
        positions = self.position_repo.list_open_positions_for_adjustment(portfolio_id)

        reduced_positions = []
        for position in positions:
            # 计算需要减少的数量
            shares_to_reduce = position["shares"] * (1 - multiplier)

            if shares_to_reduce > 0:
                # 执行平仓
                self.position_repo.close_position(
                    position_id=position["id"],
                    shares=shares_to_reduce,
                    price=position["current_price"] or position["avg_cost"],
                    reason=f"波动率控制降仓: {adjustment.reduction_reason}",
                )

                reduced_positions.append({
                    "asset_code": position["asset_code"],
                    "shares_reduced": shares_to_reduce,
                })

        return {
            "status": "executed",
            "message": adjustment.reduction_reason,
            "current_volatility": adjustment.current_volatility,
            "target_volatility": adjustment.target_volatility,
            "position_multiplier": multiplier,
            "reduced_positions": reduced_positions,
        }


class UpdateTargetVolatilityUseCase:
    """
    更新目标波动率用例
    """

    def __init__(self):
        pass

    def execute(
        self,
        user_id: int,
        target_volatility: float | None = None,
        volatility_tolerance: float | None = None,
        max_volatility_reduction: float | None = None,
    ) -> dict:
        """
        更新目标波动率配置

        Args:
            user_id: 用户ID
            target_volatility: 目标波动率（年化）
            volatility_tolerance: 波动率容忍度
            max_volatility_reduction: 最大降仓幅度

        Returns:
            更新后的账户配置
        """
        account_repo = AccountRepository()
        profile = account_repo.update_volatility_settings(
            user_id,
            target_volatility=target_volatility,
            volatility_tolerance=volatility_tolerance,
            max_volatility_reduction=max_volatility_reduction,
        )
        if profile is None:
            raise ValueError(f"用户 {user_id} 账户配置不存在")

        return profile

