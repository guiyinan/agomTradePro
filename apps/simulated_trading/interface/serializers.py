"""
模拟盘交易模块 Interface 层序列化器

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
"""
from datetime import date
from decimal import Decimal

from rest_framework import serializers

# ============================================================================
# 账户相关序列化器
# ============================================================================

class CreateAccountRequestSerializer(serializers.Serializer):
    """创建模拟账户请求序列化器"""

    account_name = serializers.CharField(
        required=True,
        max_length=100,
        help_text="账户名称"
    )
    initial_capital = serializers.DecimalField(
        required=True,
        max_digits=18,
        decimal_places=2,
        min_value=Decimal('1000.00'),
        help_text="初始资金（元）"
    )
    max_position_pct = serializers.FloatField(
        required=False,
        default=20.0,
        min_value=1.0,
        max_value=100.0,
        help_text="单资产最大持仓比例（%）"
    )
    stop_loss_pct = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=50.0,
        help_text="止损比例（%）"
    )
    commission_rate = serializers.FloatField(
        required=False,
        default=0.0003,
        min_value=0.0,
        max_value=0.01,
        help_text="手续费率"
    )
    slippage_rate = serializers.FloatField(
        required=False,
        default=0.001,
        min_value=0.0,
        max_value=0.01,
        help_text="滑点率"
    )
    fee_config_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="费率配置ID"
    )


class AccountResponseSerializer(serializers.Serializer):
    """账户响应序列化器"""

    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    account_type = serializers.CharField()
    initial_capital = serializers.DecimalField(max_digits=18, decimal_places=2)
    current_cash = serializers.DecimalField(max_digits=18, decimal_places=2)
    current_market_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_return = serializers.FloatField(allow_null=True)
    annual_return = serializers.FloatField(allow_null=True)
    max_drawdown = serializers.FloatField(allow_null=True)
    sharpe_ratio = serializers.FloatField(allow_null=True)
    win_rate = serializers.FloatField(allow_null=True)
    max_position_pct = serializers.FloatField()
    stop_loss_pct = serializers.FloatField(allow_null=True)
    commission_rate = serializers.FloatField()
    slippage_rate = serializers.FloatField()
    total_trades = serializers.IntegerField()
    winning_trades = serializers.IntegerField()
    is_active = serializers.BooleanField()
    auto_trading_enabled = serializers.BooleanField()
    start_date = serializers.DateField()
    last_trade_date = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()


class AccountListResponseSerializer(serializers.Serializer):
    """账户列表响应序列化器"""

    success = serializers.BooleanField()
    count = serializers.IntegerField()
    accounts = AccountResponseSerializer(many=True)


class AccountDeleteResponseSerializer(serializers.Serializer):
    """删除单个账户响应序列化器"""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    deleted_positions = serializers.IntegerField()
    deleted_trades = serializers.IntegerField()
    deleted_reports = serializers.IntegerField()
    message = serializers.CharField()


class AccountBatchDeleteRequestSerializer(serializers.Serializer):
    """批量删除账户请求序列化器"""

    account_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="待删除账户 ID 列表",
    )


class AccountBatchDeleteResponseSerializer(serializers.Serializer):
    """批量删除账户响应序列化器"""

    success = serializers.BooleanField()
    requested_count = serializers.IntegerField()
    deleted_count = serializers.IntegerField()
    deleted_account_ids = serializers.ListField(child=serializers.IntegerField())
    deleted_account_names = serializers.ListField(child=serializers.CharField())
    failed = serializers.ListField(child=serializers.DictField(), required=False)
    message = serializers.CharField()


# ============================================================================
# 持仓相关序列化器
# ============================================================================

class PositionResponseSerializer(serializers.Serializer):
    """持仓响应序列化器"""

    position_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    asset_code = serializers.CharField()
    asset_name = serializers.CharField()
    asset_type = serializers.CharField()
    quantity = serializers.IntegerField()
    available_quantity = serializers.IntegerField()
    avg_cost = serializers.DecimalField(max_digits=12, decimal_places=4)
    total_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    current_price = serializers.DecimalField(max_digits=12, decimal_places=4)
    market_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    unrealized_pnl = serializers.DecimalField(max_digits=18, decimal_places=2)
    unrealized_pnl_pct = serializers.FloatField()
    first_buy_date = serializers.DateField()
    last_update_date = serializers.DateField()
    signal_id = serializers.IntegerField(allow_null=True)
    entry_reason = serializers.CharField(allow_null=True)

    # 证伪跟踪相关字段
    invalidation_description = serializers.CharField(allow_null=True, required=False)
    invalidation_rule = serializers.JSONField(source='invalidation_rule_json', allow_null=True, required=False)
    is_invalidated = serializers.BooleanField(required=False)
    invalidation_reason = serializers.CharField(allow_null=True, required=False)
    invalidation_checked_at = serializers.DateTimeField(allow_null=True, required=False)


class PositionListResponseSerializer(serializers.Serializer):
    """持仓列表响应序列化器"""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    total_positions = serializers.IntegerField()
    total_market_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    positions = PositionResponseSerializer(many=True)


# ============================================================================
# 交易记录相关序列化器
# ============================================================================

class TradeListRequestSerializer(serializers.Serializer):
    """交易记录列表请求序列化器"""

    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    asset_code = serializers.CharField(required=False, allow_null=True)
    action = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=['buy', 'sell']
    )


class TradeResponseSerializer(serializers.Serializer):
    """交易记录响应序列化器"""

    trade_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    asset_code = serializers.CharField()
    asset_name = serializers.CharField()
    asset_type = serializers.CharField()
    action = serializers.CharField()
    quantity = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=12, decimal_places=4)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    commission = serializers.DecimalField(max_digits=12, decimal_places=4)
    slippage = serializers.DecimalField(max_digits=12, decimal_places=4)
    total_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    realized_pnl_pct = serializers.FloatField(allow_null=True)
    reason = serializers.CharField(allow_null=True)
    signal_id = serializers.IntegerField(allow_null=True)
    order_date = serializers.DateField()
    execution_date = serializers.DateField()
    execution_time = serializers.DateTimeField()
    status = serializers.CharField()


class TradeListResponseSerializer(serializers.Serializer):
    """交易记录列表响应序列化器"""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    total_trades = serializers.IntegerField()
    total_buy_count = serializers.IntegerField()
    total_sell_count = serializers.IntegerField()
    total_realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=2)
    trades = TradeResponseSerializer(many=True)


# ============================================================================
# 绩效相关序列化器
# ============================================================================

class PerformanceResponseSerializer(serializers.Serializer):
    """绩效响应序列化器"""

    success = serializers.BooleanField()
    account = AccountResponseSerializer()
    total_positions = serializers.IntegerField()
    total_trades = serializers.IntegerField()
    winning_trades = serializers.IntegerField()
    win_rate = serializers.FloatField()
    performance = serializers.DictField(child=serializers.FloatField())


# ============================================================================
# 费率配置相关序列化器
# ============================================================================

class FeeConfigResponseSerializer(serializers.Serializer):
    """费率配置响应序列化器"""

    config_id = serializers.IntegerField()
    config_name = serializers.CharField()
    asset_type = serializers.CharField()
    commission_rate_buy = serializers.FloatField()
    commission_rate_sell = serializers.FloatField()
    min_commission = serializers.FloatField()
    stamp_duty_rate = serializers.FloatField()
    transfer_fee_rate = serializers.FloatField()
    min_transfer_fee = serializers.FloatField()
    slippage_rate = serializers.FloatField()
    description = serializers.CharField(allow_null=True)


class FeeConfigListResponseSerializer(serializers.Serializer):
    """费率配置列表响应序列化器"""

    success = serializers.BooleanField()
    count = serializers.IntegerField()
    configs = FeeConfigResponseSerializer(many=True)


# ============================================================================
# 手动交易相关序列化器
# ============================================================================

class ManualTradeRequestSerializer(serializers.Serializer):
    """手动交易请求序列化器"""

    asset_code = serializers.CharField(
        required=True,
        help_text="资产代码"
    )
    asset_name = serializers.CharField(
        required=True,
        help_text="资产名称"
    )
    asset_type = serializers.ChoiceField(
        required=True,
        choices=['equity', 'fund', 'bond']
    )
    action = serializers.ChoiceField(
        required=True,
        choices=['buy', 'sell']
    )
    quantity = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text="交易数量"
    )
    price = serializers.DecimalField(
        required=True,
        max_digits=12,
        decimal_places=4,
        min_value=Decimal('0.01'),
        help_text="交易价格"
    )
    reason = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="交易原因"
    )
    signal_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="关联信号ID"
    )


class ManualTradeResponseSerializer(serializers.Serializer):
    """手动交易响应序列化器"""

    success = serializers.BooleanField()
    message = serializers.CharField()
    trade = TradeResponseSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


# ============================================================================
# 净值曲线相关序列化器
# ============================================================================

class EquityCurveRequestSerializer(serializers.Serializer):
    """净值曲线请求序列化器"""

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)


class EquityCurveDataPointSerializer(serializers.Serializer):
    """净值曲线数据点序列化器"""

    date = serializers.CharField()
    net_value = serializers.FloatField()
    trades_count = serializers.IntegerField()
    daily_pnl = serializers.FloatField()


class EquityCurveResponseSerializer(serializers.Serializer):
    """净值曲线响应序列化器"""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    data_points = EquityCurveDataPointSerializer(many=True)


# ============================================================================
# 自动交易相关序列化器
# ============================================================================

class AutoTradingRunRequestSerializer(serializers.Serializer):
    """执行自动交易请求序列化器"""

    trade_date = serializers.DateField(required=False, help_text="交易日期（默认今天）")
    account_ids = serializers.ListField(
        required=False,
        child=serializers.IntegerField(),
        help_text="指定账户ID列表（空则全部活跃账户）"
    )


class AutoTradingRunResponseSerializer(serializers.Serializer):
    """执行自动交易响应序列化器"""

    success = serializers.BooleanField()
    trade_date = serializers.CharField()
    total_accounts = serializers.IntegerField()
    results = serializers.DictField(
        child=serializers.DictField(
            child=serializers.IntegerField()
        )
    )
    summary = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="汇总统计：{total_buy_count, total_sell_count}"
    )
    error = serializers.CharField(allow_null=True, required=False)


class DailyInspectionRunRequestSerializer(serializers.Serializer):
    """执行日更巡检请求"""

    strategy_id = serializers.IntegerField(required=False, allow_null=True)
    inspection_date = serializers.DateField(required=False)


class DailyInspectionReportItemSerializer(serializers.Serializer):
    """日更巡检报告项"""

    report_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    inspection_date = serializers.DateField()
    status = serializers.CharField()
    macro_regime = serializers.CharField(allow_blank=True)
    policy_gear = serializers.CharField(allow_blank=True)
    strategy_id = serializers.IntegerField(allow_null=True)
    position_rule_id = serializers.IntegerField(allow_null=True)
    summary = serializers.DictField()
    checks = serializers.ListField(child=serializers.DictField())


class DailyInspectionReportListResponseSerializer(serializers.Serializer):
    """日更巡检报告列表"""

    success = serializers.BooleanField()
    count = serializers.IntegerField()
    reports = DailyInspectionReportItemSerializer(many=True)
