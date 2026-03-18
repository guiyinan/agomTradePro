"""
Hedge Module Infrastructure Layer - ORM Models

Django ORM models for hedge portfolio management.
Follows four-layer architecture.
"""

from django.db import models
from decimal import Decimal


class HedgePairModel(models.Model):
    """Hedge pair configuration table"""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="对冲对名称"
    )
    long_asset = models.CharField(
        max_length=20,
        verbose_name="多头资产"
    )
    hedge_asset = models.CharField(
        max_length=20,
        verbose_name="对冲资产"
    )
    hedge_method = models.CharField(
        max_length=30,
        choices=[
            ('beta', 'Beta对冲'),
            ('min_variance', '最小方差'),
            ('equal_risk', '等风险贡献'),
            ('dollar_neutral', '货币中性'),
            ('fixed_ratio', '固定比例'),
        ],
        default='beta',
        verbose_name="对冲方法"
    )
    target_long_weight = models.FloatField(
        default=0.7,
        verbose_name="目标多头权重"
    )
    target_hedge_weight = models.FloatField(
        default=0.3,
        verbose_name="目标对冲权重"
    )

    # Rebalance triggers
    rebalance_trigger = models.FloatField(
        default=0.05,
        verbose_name="调仓触发阈值"
    )
    correlation_window = models.IntegerField(
        default=60,
        verbose_name="相关性计算窗口（天）"
    )

    # Correlation monitoring
    min_correlation = models.FloatField(
        default=-0.3,
        verbose_name="最小相关性"
    )
    max_correlation = models.FloatField(
        default=-0.9,
        verbose_name="最大相关性"
    )
    correlation_alert_threshold = models.FloatField(
        default=0.2,
        verbose_name="相关性告警阈值"
    )

    # Risk limits
    max_hedge_cost = models.FloatField(
        default=0.05,
        verbose_name="最大对冲成本"
    )
    beta_target = models.FloatField(
        null=True,
        blank=True,
        verbose_name="目标Beta"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hedge_pair'
        verbose_name = '对冲对配置'
        verbose_name_plural = '对冲对配置'
        ordering = ['-is_active', 'name']

    def __str__(self):
        return f"{self.name} ({'启用' if self.is_active else '未启用'})"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.hedge.domain.entities import HedgePair, HedgeMethod

        method_map = {
            'beta': HedgeMethod.BETA,
            'min_variance': HedgeMethod.MIN_VARIANCE,
            'equal_risk': HedgeMethod.EQUAL_RISK,
            'dollar_neutral': HedgeMethod.DOLLAR_NEUTRAL,
            'fixed_ratio': HedgeMethod.FIXED_RATIO,
        }

        return HedgePair(
            name=self.name,
            long_asset=self.long_asset,
            hedge_asset=self.hedge_asset,
            hedge_method=method_map[self.hedge_method],
            target_long_weight=self.target_long_weight,
            target_hedge_weight=self.target_hedge_weight,
            rebalance_trigger=self.rebalance_trigger,
            correlation_window=self.correlation_window,
            min_correlation=self.min_correlation,
            max_correlation=self.max_correlation,
            correlation_alert_threshold=self.correlation_alert_threshold,
            max_hedge_cost=self.max_hedge_cost,
            beta_target=self.beta_target,
            is_active=self.is_active,
        )


class CorrelationHistoryModel(models.Model):
    """Correlation history table"""

    asset1 = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产1"
    )
    asset2 = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产2"
    )
    calc_date = models.DateField(
        db_index=True,
        verbose_name="计算日期"
    )
    window_days = models.IntegerField(
        verbose_name="窗口天数"
    )

    # Correlation statistics
    correlation = models.FloatField(
        verbose_name="相关系数"
    )
    covariance = models.FloatField(
        default=0.0,
        verbose_name="协方差"
    )
    beta = models.FloatField(
        default=0.0,
        verbose_name="Beta"
    )

    # Additional metrics
    p_value = models.FloatField(
        default=0.0,
        verbose_name="P值"
    )
    standard_error = models.FloatField(
        default=0.0,
        verbose_name="标准误差"
    )

    # Trend information
    correlation_trend = models.CharField(
        max_length=20,
        default='neutral',
        verbose_name="相关性趋势"
    )
    correlation_ma = models.FloatField(
        default=0.0,
        verbose_name="相关性均线"
    )

    # Alert information
    alert = models.TextField(
        blank=True,
        verbose_name="告警信息"
    )
    alert_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="告警类型"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hedge_correlation_history'
        verbose_name = '相关性历史'
        verbose_name_plural = '相关性历史'
        unique_together = [('asset1', 'asset2', 'calc_date', 'window_days')]
        indexes = [
            models.Index(fields=['calc_date', 'asset1', 'asset2']),
            models.Index(fields=['calc_date', 'correlation']),
        ]
        ordering = ['-calc_date']

    def __str__(self):
        return f"{self.asset1}-{self.asset2} {self.calc_date}"


class HedgePortfolioSnapshotModel(models.Model):
    """Hedge portfolio snapshot table"""

    pair = models.ForeignKey(
        HedgePairModel,
        on_delete=models.CASCADE,
        related_name='snapshots',
        verbose_name="对冲对"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )

    # Current positions
    long_weight = models.FloatField(
        verbose_name="多头权重"
    )
    hedge_weight = models.FloatField(
        verbose_name="对冲权重"
    )

    # Hedge metrics
    hedge_ratio = models.FloatField(
        verbose_name="对冲比例"
    )
    target_hedge_ratio = models.FloatField(
        default=0.0,
        verbose_name="目标对冲比例"
    )

    # Correlation metrics
    current_correlation = models.FloatField(
        verbose_name="当前相关性"
    )
    correlation_20d = models.FloatField(
        default=0.0,
        verbose_name="20日相关性"
    )
    correlation_60d = models.FloatField(
        default=0.0,
        verbose_name="60日相关性"
    )

    # Portfolio metrics
    portfolio_beta = models.FloatField(
        default=0.0,
        verbose_name="组合Beta"
    )
    portfolio_volatility = models.FloatField(
        default=0.0,
        verbose_name="组合波动率"
    )
    hedge_effectiveness = models.FloatField(
        default=0.0,
        verbose_name="对冲有效性"
    )

    # Performance
    daily_return = models.FloatField(
        default=0.0,
        verbose_name="日收益率"
    )
    unhedged_return = models.FloatField(
        default=0.0,
        verbose_name="未对冲收益"
    )
    hedge_return = models.FloatField(
        default=0.0,
        verbose_name="对冲部位收益"
    )

    # Risk metrics
    value_at_risk = models.FloatField(
        default=0.0,
        verbose_name="VaR"
    )
    max_drawdown = models.FloatField(
        default=0.0,
        verbose_name="最大回撤"
    )

    # Status
    rebalance_needed = models.BooleanField(
        default=False,
        verbose_name="需要调仓"
    )
    rebalance_reason = models.TextField(
        blank=True,
        verbose_name="调仓原因"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hedge_portfolio_snapshots'
        verbose_name = '对冲组合快照'
        verbose_name_plural = '对冲组合快照'
        unique_together = [('pair', 'trade_date')]
        indexes = [
            models.Index(fields=['pair', 'trade_date']),
            models.Index(fields=['trade_date', 'rebalance_needed']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.pair.name} - {self.trade_date}"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.hedge.domain.entities import HedgePortfolio

        return HedgePortfolio(
            pair_name=self.pair.name,
            trade_date=self.trade_date,
            long_weight=self.long_weight,
            hedge_weight=self.hedge_weight,
            hedge_ratio=self.hedge_ratio,
            target_hedge_ratio=self.target_hedge_ratio,
            current_correlation=self.current_correlation,
            correlation_20d=self.correlation_20d,
            correlation_60d=self.correlation_60d,
            portfolio_beta=self.portfolio_beta,
            portfolio_volatility=self.portfolio_volatility,
            hedge_effectiveness=self.hedge_effectiveness,
            daily_return=self.daily_return,
            unhedged_return=self.unhedged_return,
            hedge_return=self.hedge_return,
            value_at_risk=self.value_at_risk,
            max_drawdown=self.max_drawdown,
            rebalance_needed=self.rebalance_needed,
            rebalance_reason=self.rebalance_reason,
        )


class HedgeAlertModel(models.Model):
    """Hedge alert table"""

    pair_name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="对冲对名称"
    )
    alert_date = models.DateField(
        db_index=True,
        verbose_name="告警日期"
    )
    alert_type = models.CharField(
        max_length=50,
        choices=[
            ('correlation_breakdown', '相关性失效'),
            ('hedge_ratio_drift', '对冲比例漂移'),
            ('beta_change', 'Beta变化'),
            ('liquidity_risk', '流动性风险'),
        ],
        verbose_name="告警类型"
    )

    # Alert details
    severity = models.CharField(
        max_length=20,
        choices=[
            ('low', '低'),
            ('medium', '中'),
            ('high', '高'),
            ('critical', '严重'),
        ],
        default='medium',
        verbose_name="严重程度"
    )
    message = models.TextField(
        verbose_name="告警信息"
    )
    current_value = models.FloatField(
        default=0.0,
        verbose_name="当前值"
    )
    threshold_value = models.FloatField(
        default=0.0,
        verbose_name="阈值"
    )

    # Recommended action
    action_required = models.TextField(
        blank=True,
        verbose_name="建议操作"
    )
    action_priority = models.IntegerField(
        default=5,
        verbose_name="优先级"
    )

    # Status
    is_resolved = models.BooleanField(
        default=False,
        verbose_name="已解决"
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="解决时间"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hedge_alert'
        verbose_name = '对冲告警'
        verbose_name_plural = '对冲告警'
        indexes = [
            models.Index(fields=['alert_date', '-action_priority']),
            models.Index(fields=['is_resolved', 'alert_date']),
        ]
        ordering = ['-alert_date', '-action_priority']

    def __str__(self):
        return f"{self.pair_name} - {self.alert_type} - {self.alert_date}"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.hedge.domain.entities import HedgeAlert, HedgeAlertType

        alert_type_map = {
            'correlation_breakdown': HedgeAlertType.CORRELATION_BREAKDOWN,
            'hedge_ratio_drift': HedgeAlertType.HEDGE_RATIO_DRIFT,
            'beta_change': HedgeAlertType.BETA_CHANGE,
            'liquidity_risk': HedgeAlertType.LIQUIDITY_RISK,
        }

        return HedgeAlert(
            pair_name=self.pair_name,
            alert_date=self.alert_date,
            alert_type=alert_type_map.get(self.alert_type, HedgeAlertType.CORRELATION_BREAKDOWN),
            severity=self.severity,
            message=self.message,
            current_value=self.current_value,
            threshold_value=self.threshold_value,
            action_required=self.action_required,
            action_priority=self.action_priority,
            is_resolved=self.is_resolved,
            resolved_at=self.resolved_at,
        )


class HedgePerformanceModel(models.Model):
    """Hedge performance tracking table"""

    pair_name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="对冲对名称"
    )
    period_start = models.DateField(
        verbose_name="期间开始"
    )
    period_end = models.DateField(
        verbose_name="期间结束"
    )

    # Return metrics
    total_return = models.FloatField(
        verbose_name="总收益率"
    )
    annual_return = models.FloatField(
        verbose_name="年化收益率"
    )
    sharpe_ratio = models.FloatField(
        verbose_name="夏普比率"
    )

    # Hedge effectiveness
    volatility_reduction = models.FloatField(
        verbose_name="波动率降低（%）"
    )
    drawdown_reduction = models.FloatField(
        verbose_name="回撤降低（%）"
    )
    hedge_effectiveness = models.FloatField(
        verbose_name="对冲有效性"
    )

    # Cost metrics
    hedge_cost = models.FloatField(
        default=0.0,
        verbose_name="对冲成本"
    )
    cost_benefit_ratio = models.FloatField(
        default=0.0,
        verbose_name="成本收益比"
    )

    # Correlation metrics
    avg_correlation = models.FloatField(
        verbose_name="平均相关性"
    )
    correlation_stability = models.FloatField(
        default=0.0,
        verbose_name="相关性稳定性"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hedge_performance'
        verbose_name = '对冲表现'
        verbose_name_plural = '对冲表现'
        unique_together = [('pair_name', 'period_start', 'period_end')]
        ordering = ['-period_start', 'pair_name']

    def __str__(self):
        return f"{self.pair_name} - {self.period_start} to {self.period_end}"
