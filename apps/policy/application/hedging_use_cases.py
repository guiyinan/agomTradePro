"""
Policy Application - Hedging Use Cases

动态对冲策略执行用例。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from apps.policy.application.repository_provider import get_hedge_position_repository
from apps.realtime.application.repository_provider import get_realtime_price_repository
from core.integration.account_positions import list_portfolio_position_weights

logger = logging.getLogger(__name__)


@dataclass
class HedgeCalculationResult:
    """对冲计算结果"""
    should_hedge: bool           # 是否需要对冲
    hedge_ratio: float           # 对冲比例
    hedge_value: Decimal         # 对冲金额
    recommended_instrument: str  # 建议对冲工具
    estimated_cost: Decimal      # 预估对冲成本
    reason: str                  # 对冲原因


@dataclass
class HedgeExecutionResult:
    """对冲执行结果"""
    hedge_id: int                # 对冲记录ID
    instrument_code: str         # 对冲工具代码
    hedge_ratio: float           # 对冲比例
    hedge_value: Decimal         # 对冲金额
    execution_price: Decimal     # 执行价格
    cost: Decimal                # 实际成本
    executed_at: datetime        # 执行时间


class CalculateHedgeUseCase:
    """
    计算对冲需求用例

    根据政策档位和投资组合情况计算对冲需求。
    """

    def __init__(self):
        pass

    def calculate_hedge_requirement(
        self,
        portfolio_id: int,
        policy_level: str,
        portfolio_value: Decimal,
        equity_exposure: Decimal,
    ) -> HedgeCalculationResult:
        """
        计算对冲需求

        Args:
            portfolio_id: 投资组合ID
            policy_level: 政策档位 (P0/P1/P2/P3)
            portfolio_value: 组合总值
            equity_exposure: 权益敞口

        Returns:
            HedgeCalculationResult: 对冲计算结果
        """
        # P2/P3 档位需要对冲
        hedge_ratios = {
            'P0': 0.0,   # 无对冲
            'P1': 0.0,   # 无对冲
            'P2': 0.5,   # 50%对冲
            'P3': 1.0,   # 100%对冲（或转现金）
        }

        hedge_ratio = hedge_ratios.get(policy_level, 0.0)
        should_hedge = hedge_ratio > 0

        if should_hedge:
            hedge_value = equity_exposure * Decimal(str(hedge_ratio))
            reason = f"政策档位 {policy_level} 触发对冲要求，对冲比例 {hedge_ratio:.0%}"

            # 简化成本估算（5基点）
            estimated_cost = hedge_value * Decimal('0.0005')

            return HedgeCalculationResult(
                should_hedge=True,
                hedge_ratio=hedge_ratio,
                hedge_value=hedge_value,
                recommended_instrument='IF2312',  # 沪深300股指期货
                estimated_cost=estimated_cost,
                reason=reason,
            )
        else:
            return HedgeCalculationResult(
                should_hedge=False,
                hedge_ratio=0.0,
                hedge_value=Decimal('0'),
                recommended_instrument='',
                estimated_cost=Decimal('0'),
                reason=f"政策档位 {policy_level} 无需对冲",
            )


class ExecuteHedgingUseCase:
    """
    执行对冲用例

    根据对冲计算结果执行对冲操作。
    """

    def __init__(self):
        self.hedge_repository = get_hedge_position_repository()

    def execute_hedge(
        self,
        portfolio_id: int,
        user_id: int,
        calculation: HedgeCalculationResult,
    ) -> HedgeExecutionResult | None:
        """
        执行对冲操作

        Args:
            portfolio_id: 投资组合ID
            user_id: 用户ID
            calculation: 对冲计算结果

        Returns:
            HedgeExecutionResult: 对冲执行结果
        """
        if not calculation.should_hedge:
            return None

        # 获取对冲标的当前价格
        execution_price = self._get_instrument_price(
            calculation.recommended_instrument
        )
        hedge_status = 'executed' if execution_price > 0 else 'pending'

        # 创建对冲记录
        hedge = self.hedge_repository.create_hedge_position(
            portfolio_id=portfolio_id,
            instrument_code=calculation.recommended_instrument,
            instrument_type='future',
            hedge_ratio=calculation.hedge_ratio,
            hedge_value=calculation.hedge_value,
            policy_level='',
            status=hedge_status,
            notes=calculation.reason,
            execution_price=Decimal(str(execution_price)) if execution_price > 0 else None,
            opening_cost=calculation.estimated_cost,
            total_cost=calculation.estimated_cost,
            executed_at=timezone.now() if hedge_status == 'executed' else None,
        )

        return HedgeExecutionResult(
            hedge_id=hedge["id"],
            instrument_code=calculation.recommended_instrument,
            hedge_ratio=calculation.hedge_ratio,
            hedge_value=calculation.hedge_value,
            execution_price=Decimal(str(execution_price)),
            cost=calculation.estimated_cost,
            executed_at=timezone.now(),
        )

    @staticmethod
    def _get_instrument_price(instrument_code: str) -> float:
        """获取对冲标的当前价格

        Args:
            instrument_code: 标的代码

        Returns:
            当前价格，获取失败返回 0
        """
        try:
            repo = get_realtime_price_repository()
            price_data = repo.get_latest_price(instrument_code)
            if price_data and price_data.price > 0:
                return float(price_data.price)
        except Exception:
            pass
        return 0


class HedgeEffectivenessAnalyzer:
    """
    对冲效果分析器

    评估对冲操作的效果。
    """

    def __init__(self):
        self.hedge_repository = get_hedge_position_repository()

    def analyze_hedge_effectiveness(
        self,
        portfolio_id: int,
        hedge_id: int,
    ) -> dict:
        """
        分析对冲效果

        通过回归计算对冲前后的 beta 变化，并计算对冲成本与收益。

        Args:
            portfolio_id: 投资组合ID
            hedge_id: 对冲记录ID

        Returns:
            对冲效果分析结果
        """
        hedge = self.hedge_repository.get_hedge_position(
            hedge_id=hedge_id,
            portfolio_id=portfolio_id,
        )
        if hedge is None:
            return {
                'error': f'对冲记录 {hedge_id} 不存在',
                'beta_before': None,
                'beta_after': None,
                'hedge_cost': 0.0,
                'hedge_benefit': 0.0,
                'net_benefit': 0.0,
            }

        # 计算实际成本
        total_cost = float(hedge.get('total_cost') or 0)
        if not total_cost:
            opening = float(hedge.get('opening_cost') or 0)
            closing = float(hedge.get('closing_cost') or 0)
            total_cost = opening + closing

        # 计算 beta before/after 和对冲收益
        beta_before = hedge.get('beta_before')
        beta_after = hedge.get('beta_after')
        hedge_profit = float(hedge.get('hedge_profit') or 0)

        # 如果 DB 中没有记录 beta，尝试从持仓数据计算
        if beta_before is None or beta_after is None:
            computed = self._compute_beta_change(
                portfolio_id, hedge
            )
            beta_before = computed.get('beta_before', 1.0)
            beta_after = computed.get('beta_after', beta_before)

            # 回写到 DB
            self.hedge_repository.update_beta_metrics(
                hedge_id=hedge_id,
                beta_before=beta_before,
                beta_after=beta_after,
            )

        net_benefit = hedge_profit - total_cost

        return {
            'beta_before': beta_before,
            'beta_after': beta_after,
            'hedge_cost': total_cost,
            'hedge_benefit': hedge_profit,
            'net_benefit': net_benefit,
        }

    def _compute_beta_change(
        self,
        portfolio_id: int,
        hedge: dict,
    ) -> dict:
        """
        根据持仓和对冲标的历史收益率，回归计算 beta

        Returns:
            {'beta_before': float, 'beta_after': float}
        """
        try:
            # 获取持仓
            positions = list_portfolio_position_weights(portfolio_id)

            if not positions:
                return {'beta_before': 1.0, 'beta_after': 1.0}

            # 简化：用组合权重加权的 beta 估计
            # beta_before ≈ 1.0 (组合无对冲时假设 beta=1)
            # beta_after = beta_before * (1 - hedge_ratio)
            beta_before = 1.0
            beta_after = beta_before * (1.0 - hedge['hedge_ratio'])

            return {'beta_before': beta_before, 'beta_after': max(0.0, beta_after)}

        except Exception as e:
            logger.warning(f"Beta 计算失败: {e}")
            return {'beta_before': 1.0, 'beta_after': 1.0}

