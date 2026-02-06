"""
Account Application - Transaction Cost Use Cases

交易成本预估与验证用例。
"""

from decimal import Decimal
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass

from shared.infrastructure.models import TransactionCostConfigModel
from apps.account.infrastructure.models import PositionModel, AssetMetadataModel


@dataclass
class TransactionCostEstimate:
    """交易成本预估"""
    market: str                # 市场
    asset_class: str           # 资产类别
    trade_value: Decimal       # 交易金额
    is_buy: bool              # 是否买入

    # 成本明细
    commission: Decimal        # 佣金
    slippage: Decimal          # 滑点
    stamp_duty: Decimal        # 印花税
    transfer_fee: Decimal      # 过户费
    total_cost: Decimal        # 总成本
    cost_ratio: float          # 成本比例

    # 预警
    exceeds_threshold: bool    # 是否超过阈值
    warning_message: str       # 警告消息


@dataclass
class TransactionCostAnalysis:
    """交易成本分析"""
    total_transactions: int           # 总交易次数
    total_traded_value: Decimal       # 总交易金额
    total_actual_cost: Decimal        # 总实际成本
    total_estimated_cost: Decimal     # 总预估成本
    cost_variance: Decimal            # 成本差异
    cost_variance_pct: float          # 成本差异百分比
    estimation_accuracy: float        # 预估准确率
    avg_cost_ratio: float             # 平均成本比例
    high_cost_transactions: List[Dict]  # 高成本交易列表


class TransactionCostEstimationUseCase:
    """
    交易成本预估用例

    在交易执行前预估成本，用于决策和风险控制。
    """

    def __init__(self):
        pass

    def estimate_transaction_cost(
        self,
        asset_code: str,
        shares: float,
        price: Decimal,
        action: str,
        user_id: int,
    ) -> TransactionCostEstimate:
        """
        预估交易成本

        Args:
            asset_code: 资产代码
            shares: 交易数量
            price: 价格
            action: 交易方向 (buy/sell)
            user_id: 用户ID

        Returns:
            TransactionCostEstimate: 成本预估
        """
        # 计算交易金额
        notional = Decimal(str(shares)) * price

        # 获取资产元数据
        try:
            asset_meta = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            # 使用默认配置
            asset_meta = None

        # 确定市场和资产类别
        if asset_meta:
            market = self._infer_market(asset_meta)
            asset_class = asset_meta.asset_class
        else:
            market = 'CN_A_SHARE'  # 默认A股
            asset_class = 'equity'

        # 获取成本配置
        cost_config = self._get_cost_config(market, asset_class)

        # 计算成本
        is_buy = (action == 'buy')
        cost_detail = cost_config.calculate_total_cost(notional, is_buy)

        # 检查是否超过阈值
        exceeds_threshold = cost_detail['cost_ratio'] > cost_config.cost_warning_threshold
        warning_message = ""
        if exceeds_threshold:
            warning_message = (
                f"⚠️ 交易成本过高：{cost_detail['cost_ratio']:.2%} "
                f"（超过阈值 {cost_config.cost_warning_threshold:.2%}）"
            )
            if notional < Decimal('1000'):
                warning_message += "，建议：小额交易可考虑合并以降低成本"

        return TransactionCostEstimate(
            market=market,
            asset_class=asset_class,
            trade_value=notional,
            is_buy=is_buy,
            commission=cost_detail['commission'],
            slippage=cost_detail['slippage'],
            stamp_duty=cost_detail['stamp_duty'],
            transfer_fee=cost_detail['transfer_fee'],
            total_cost=cost_detail['total_cost'],
            cost_ratio=cost_detail['cost_ratio'],
            exceeds_threshold=exceeds_threshold,
            warning_message=warning_message,
        )

    def _infer_market(self, asset_meta) -> str:
        """推断市场"""
        code = asset_meta.asset_code.upper()

        if 'SH' in code or 'SZ' in code:
            return 'CN_A_SHARE'
        elif 'HK' in code:
            return 'CN_HK_STOCK'
        elif 'US' in code:
            return 'US_STOCK'
        else:
            return 'CN_A_SHARE'  # 默认

    def _get_cost_config(self, market: str, asset_class: str) -> TransactionCostConfigModel:
        """获取成本配置"""
        try:
            return TransactionCostConfigModel._default_manager.get(
                market=market,
                asset_class=asset_class,
                is_active=True,
            )
        except TransactionCostConfigModel.DoesNotExist:
            # 返回默认配置
            return TransactionCostConfigModel(
                market=market,
                asset_class=asset_class,
                commission_rate=0.0003,
                slippage_rate=0.0002,
                stamp_duty_rate=0.001,
                transfer_fee_rate=0.00001,
                min_commission=Decimal('5.00'),
                cost_warning_threshold=0.005,
            )


class RecordTransactionCostUseCase:
    """
    记录交易成本用例

    在交易执行后记录实际成本，并与预估对比。
    """

    def __init__(self):
        pass

    def record_actual_cost(
        self,
        transaction_id: int,
        actual_commission: Decimal,
        actual_slippage: Decimal = None,
        actual_stamp_duty: Decimal = None,
        actual_transfer_fee: Decimal = None,
    ):
        """
        记录实际交易成本

        Args:
            transaction_id: 交易ID
            actual_commission: 实际佣金
            actual_slippage: 实际滑点
            actual_stamp_duty: 实际印花税
            actual_transfer_fee: 实际过户费
        """
        from apps.account.infrastructure.models import TransactionModel

        try:
            transaction = TransactionModel._default_manager.get(id=transaction_id)
        except TransactionModel.DoesNotExist:
            raise ValueError(f"交易 {transaction_id} 不存在")

        # 记录实际成本
        transaction.commission = actual_commission
        if actual_slippage is not None:
            transaction.slippage = actual_slippage
        if actual_stamp_duty is not None:
            transaction.stamp_duty = actual_stamp_duty
        if actual_transfer_fee is not None:
            transaction.transfer_fee = actual_transfer_fee

        # 计算总成本
        total_actual = (
            actual_commission +
            (actual_slippage or Decimal('0')) +
            (actual_stamp_duty or Decimal('0')) +
            (actual_transfer_fee or Decimal('0'))
        )

        # 对比预估成本
        if transaction.estimated_cost:
            variance = total_actual - transaction.estimated_cost
            variance_pct = float(variance) / float(transaction.estimated_cost) if transaction.estimated_cost > 0 else 0

            transaction.cost_variance = variance
            transaction.cost_variance_pct = variance_pct

        transaction.save()

        return transaction


class TransactionCostAnalysisUseCase:
    """
    交易成本分析用例

    分析历史交易成本，评估预估准确率。
    """

    def __init__(self):
        pass

    def analyze_user_transaction_costs(
        self,
        user_id: int,
        portfolio_id: Optional[int] = None,
        days: int = 90,
    ) -> TransactionCostAnalysis:
        """
        分析用户交易成本

        Args:
            user_id: 用户ID
            portfolio_id: 投资组合ID（可选）
            days: 分析天数

        Returns:
            TransactionCostAnalysis: 成本分析结果
        """
        from apps.account.infrastructure.models import TransactionModel
        from django.utils import timezone
        from datetime import timedelta

        # 获取时间范围
        since_date = timezone.now() - timedelta(days=days)

        # 查询交易记录
        queryset = TransactionModel._default_manager.filter(
            portfolio__user_id=user_id,
            created_at__gte=since_date,
        )

        if portfolio_id:
            queryset = queryset.filter(portfolio_id=portfolio_id)

        transactions = queryset.all()

        if not transactions:
            return TransactionCostAnalysis(
                total_transactions=0,
                total_traded_value=Decimal('0'),
                total_actual_cost=Decimal('0'),
                total_estimated_cost=Decimal('0'),
                cost_variance=Decimal('0'),
                cost_variance_pct=0.0,
                estimation_accuracy=0.0,
                avg_cost_ratio=0.0,
                high_cost_transactions=[],
            )

        # 统计分析
        total_transactions = len(transactions)
        total_traded_value = sum(t.notional for t in transactions)
        total_actual_cost = sum(
            t.commission + (t.slippage or 0) + (t.stamp_duty or 0) + (t.transfer_fee or 0)
            for t in transactions
        )

        # 预估成本统计
        estimated_transactions = [t for t in transactions if t.estimated_cost]
        total_estimated_cost = sum(t.estimated_cost for t in estimated_transactions) if estimated_transactions else Decimal('0')

        # 成本差异
        cost_variance = total_actual_cost - total_estimated_cost
        cost_variance_pct = float(cost_variance) / float(total_estimated_cost) if total_estimated_cost > 0 else 0

        # 预估准确率（基于有预估的交易）
        accuracy = 0.0
        if estimated_transactions:
            accurate_count = sum(
                1 for t in estimated_transactions
                if t.cost_variance_pct and abs(t.cost_variance_pct) < 0.2  # 误差小于20%
            )
            accuracy = accurate_count / len(estimated_transactions)

        # 平均成本比例
        avg_cost_ratio = sum(
            (float(t.commission + (t.slippage or 0) + (t.stamp_duty or 0) + (t.transfer_fee or 0)) / float(t.notional))
            for t in transactions
            if t.notional > 0
        ) / len(transactions) if transactions else 0

        # 高成本交易（成本比例 > 1%）
        high_cost_transactions = [
            {
                'id': t.id,
                'asset_code': t.asset_code,
                'action': t.action,
                'notional': float(t.notional),
                'cost_ratio': float(t.commission + (t.slippage or 0) + (t.stamp_duty or 0) + (t.transfer_fee or 0)) / float(t.notional),
                'traded_at': t.traded_at,
            }
            for t in transactions
            if t.notional > 0 and
            float(t.commission + (t.slippage or 0) + (t.stamp_duty or 0) + (t.transfer_fee or 0)) / float(t.notional) > 0.01
        ]

        return TransactionCostAnalysis(
            total_transactions=total_transactions,
            total_traded_value=total_traded_value,
            total_actual_cost=total_actual_cost,
            total_estimated_cost=total_estimated_cost,
            cost_variance=cost_variance,
            cost_variance_pct=cost_variance_pct,
            estimation_accuracy=accuracy,
            avg_cost_ratio=avg_cost_ratio,
            high_cost_transactions=high_cost_transactions,
        )

