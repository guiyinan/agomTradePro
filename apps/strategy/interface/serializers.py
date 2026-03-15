"""
Django REST Framework Serializers for Strategy System

Interface层:
- 负责输入验证和输出格式化
- 使用DRF Serializer进行数据转换
"""
from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.strategy.infrastructure.models import (
    StrategyModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    StrategyExecutionLogModel
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)


# ========================================================================
# Strategy Serializers
# ========================================================================

class StrategySerializer(serializers.ModelSerializer):
    """策略序列化器"""

    class Meta:
        model = StrategyModel
        fields = [
            'id', 'name', 'description', 'strategy_type',
            'version', 'is_active',
            'max_position_pct', 'max_total_position_pct', 'stop_loss_pct',
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate_max_position_pct(self, value):
        """验证单资产最大持仓比例"""
        if not 0 <= value <= 100:
            raise serializers.ValidationError("单资产最大持仓比例必须在 0-100 之间")
        return value

    def validate_max_total_position_pct(self, value):
        """验证总持仓比例上限"""
        if not 0 <= value <= 100:
            raise serializers.ValidationError("总持仓比例上限必须在 0-100 之间")
        return value

    def validate_stop_loss_pct(self, value):
        """验证止损比例"""
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("止损比例必须在 0-100 之间")
        return value


class StrategyDetailSerializer(StrategySerializer):
    """策略详情序列化器（包含关联配置）"""

    rules_count = serializers.SerializerMethodField()
    has_script_config = serializers.SerializerMethodField()
    has_ai_config = serializers.SerializerMethodField()

    class Meta(StrategySerializer.Meta):
        fields = StrategySerializer.Meta.fields + [
            'rules_count', 'has_script_config', 'has_ai_config'
        ]

    def get_rules_count(self, obj):
        """获取规则数量"""
        return obj.rules.count()

    def get_has_script_config(self, obj):
        """是否有脚本配置"""
        return hasattr(obj, 'script_config')

    def get_has_ai_config(self, obj):
        """是否有 AI 配置"""
        return hasattr(obj, 'ai_config')


# ========================================================================
# Position Management Rule Serializers
# ========================================================================

class PositionManagementRuleSerializer(serializers.ModelSerializer):
    """仓位管理规则序列化器"""

    strategy_name = serializers.CharField(source='strategy.name', read_only=True)

    class Meta:
        model = PositionManagementRuleModel
        fields = [
            'id',
            'strategy',
            'strategy_name',
            'name',
            'description',
            'is_active',
            'price_precision',
            'variables_schema',
            'buy_condition_expr',
            'sell_condition_expr',
            'buy_price_expr',
            'sell_price_expr',
            'stop_loss_expr',
            'take_profit_expr',
            'position_size_expr',
            'metadata',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        errors: dict[str, str] = {}
        for field in (
            'buy_condition_expr',
            'sell_condition_expr',
            'buy_price_expr',
            'sell_price_expr',
            'stop_loss_expr',
            'take_profit_expr',
            'position_size_expr',
        ):
            expression = attrs.get(field)
            if expression is None and self.instance is not None:
                expression = getattr(self.instance, field, "")
            if field in ('buy_condition_expr', 'sell_condition_expr') and not expression:
                continue
            try:
                PositionManagementService.validate_expression(str(expression))
            except PositionRuleError as exc:
                errors[field] = str(exc)

        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class PositionManagementEvaluateInputSerializer(serializers.Serializer):
    """仓位管理规则评估入参"""

    context = serializers.JSONField()

    def validate_context(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("context 必须是对象")
        return value


class PositionManagementEvaluateResultSerializer(serializers.Serializer):
    """仓位管理规则评估结果"""

    should_buy = serializers.BooleanField()
    should_sell = serializers.BooleanField()
    buy_price = serializers.FloatField()
    sell_price = serializers.FloatField()
    stop_loss_price = serializers.FloatField()
    take_profit_price = serializers.FloatField()
    position_size = serializers.FloatField()
    risk_reward_ratio = serializers.FloatField(allow_null=True)


# ========================================================================
# Rule Condition Serializers
# ========================================================================

class RuleConditionSerializer(serializers.ModelSerializer):
    """规则条件序列化器"""

    class Meta:
        model = RuleConditionModel
        fields = [
            'id', 'strategy', 'rule_name', 'rule_type',
            'condition_json', 'action', 'weight', 'target_assets',
            'priority', 'is_enabled', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_weight(self, value):
        """验证权重"""
        if value is not None and not 0 <= value <= 1:
            raise serializers.ValidationError("权重必须在 0-1 之间")
        return value

    def validate_condition_json(self, value):
        """验证条件表达式 JSON 格式"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("条件表达式必须是字典类型")

        if 'operator' not in value:
            raise serializers.ValidationError("条件表达式必须包含 'operator' 字段")

        return value


class RuleConditionListSerializer(serializers.ModelSerializer):
    """规则条件列表序列化器（精简版）"""

    class Meta:
        model = RuleConditionModel
        fields = [
            'id', 'rule_name', 'rule_type', 'action',
            'weight', 'priority', 'is_enabled'
        ]


# ========================================================================
# Script Config Serializers
# ========================================================================

class ScriptConfigSerializer(serializers.ModelSerializer):
    """脚本配置序列化器"""

    class Meta:
        model = ScriptConfigModel
        fields = [
            'id', 'strategy', 'script_language', 'script_code',
            'script_hash', 'sandbox_config', 'allowed_modules',
            'version', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'script_hash', 'created_at', 'updated_at']

    def create(self, validated_data):
        """创建脚本配置时自动生成 script_hash"""
        import hashlib
        script_code = validated_data['script_code']
        script_hash = hashlib.sha256(script_code.encode()).hexdigest()
        validated_data['script_hash'] = script_hash
        return super().create(validated_data)


# ========================================================================
# AI Strategy Config Serializers
# ========================================================================

class AIStrategyConfigSerializer(serializers.ModelSerializer):
    """AI策略配置序列化器"""

    class Meta:
        model = AIStrategyConfigModel
        fields = [
            'id', 'strategy', 'prompt_template', 'chain_config', 'ai_provider',
            'temperature', 'max_tokens', 'approval_mode', 'confidence_threshold',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_temperature(self, value):
        """验证温度参数"""
        if not 0 <= value <= 2:
            raise serializers.ValidationError("温度参数必须在 0-2 之间")
        return value

    def validate_confidence_threshold(self, value):
        """验证置信度阈值"""
        if not 0 <= value <= 1:
            raise serializers.ValidationError("置信度阈值必须在 0-1 之间")
        return value

    def validate_max_tokens(self, value):
        """验证最大 Token 数"""
        if value <= 0:
            raise serializers.ValidationError("最大 Token 数必须大于 0")
        return value


# ========================================================================
# Portfolio Strategy Assignment Serializers
# ========================================================================

class PortfolioStrategyAssignmentSerializer(serializers.ModelSerializer):
    """投资组合策略关联序列化器"""

    strategy_name = serializers.CharField(source='strategy.name', read_only=True)
    strategy_type = serializers.CharField(source='strategy.strategy_type', read_only=True)
    portfolio_name = serializers.CharField(source='portfolio.account_name', read_only=True)

    class Meta:
        model = PortfolioStrategyAssignmentModel
        fields = [
            'id', 'portfolio', 'strategy', 'assigned_at', 'assigned_by',
            'is_active', 'override_max_position_pct', 'override_stop_loss_pct',
            'strategy_name', 'strategy_type', 'portfolio_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'assigned_at', 'created_at', 'updated_at']

    def validate_override_max_position_pct(self, value):
        """验证覆盖的单资产最大持仓比例"""
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("覆盖的单资产最大持仓比例必须在 0-100 之间")
        return value

    def validate_override_stop_loss_pct(self, value):
        """验证覆盖的止损比例"""
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("覆盖的止损比例必须在 0-100 之间")
        return value


class PortfolioStrategyAssignmentDetailSerializer(PortfolioStrategyAssignmentSerializer):
    """投资组合策略关联详情序列化器"""

    strategy_detail = StrategySerializer(source='strategy', read_only=True)

    class Meta(PortfolioStrategyAssignmentSerializer.Meta):
        fields = PortfolioStrategyAssignmentSerializer.Meta.fields + ['strategy_detail']


# ========================================================================
# Strategy Execution Log Serializers
# ========================================================================

class StrategyExecutionLogSerializer(serializers.ModelSerializer):
    """策略执行日志序列化器"""

    strategy_name = serializers.CharField(source='strategy.name', read_only=True)
    portfolio_name = serializers.CharField(source='portfolio.account_name', read_only=True)

    class Meta:
        model = StrategyExecutionLogModel
        fields = [
            'id', 'strategy', 'portfolio', 'execution_time',
            'execution_duration_ms', 'execution_result', 'signals_generated',
            'error_message', 'is_success',
            'strategy_name', 'portfolio_name'
        ]
        read_only_fields = ['id', 'execution_time']


class StrategyExecutionLogListSerializer(serializers.ModelSerializer):
    """策略执行日志列表序列化器（精简版）"""

    strategy_name = serializers.CharField(source='strategy.name', read_only=True)
    portfolio_name = serializers.CharField(source='portfolio.account_name', read_only=True)
    signals_count = serializers.IntegerField(source='signals_generated.__len__', read_only=True)

    class Meta:
        model = StrategyExecutionLogModel
        fields = [
            'id', 'execution_time', 'execution_duration_ms',
            'is_success', 'signals_count',
            'strategy_name', 'portfolio_name'
        ]


# ========================================================================
# M3: 执行评估 API Serializers
# ========================================================================

class ExecutionEvaluateInputSerializer(serializers.Serializer):
    """执行评估输入序列化器"""

    symbol = serializers.CharField(help_text="资产代码")
    side = serializers.ChoiceField(choices=['buy', 'sell'], help_text="买卖方向")
    portfolio_id = serializers.IntegerField(help_text="投资组合ID", required=False)

    current_price = serializers.FloatField(help_text="当前价格", required=False)
    signal_strength = serializers.FloatField(
        help_text="信号强度 (0-1)",
        default=0.6,
        min_value=0.0,
        max_value=1.0
    )
    signal_direction = serializers.ChoiceField(
        choices=['bullish', 'bearish', 'neutral'],
        help_text="信号方向",
        default='bullish'
    )
    signal_confidence = serializers.FloatField(
        help_text="信号置信度 (0-1)",
        default=0.8,
        min_value=0.0,
        max_value=1.0
    )
    stop_loss_price = serializers.FloatField(help_text="止损价", required=False)
    atr = serializers.FloatField(help_text="ATR值", required=False)
    target_regime = serializers.CharField(help_text="目标Regime", required=False)
    account_equity = serializers.FloatField(help_text="账户权益", default=100000.0)
    current_position_value = serializers.FloatField(help_text="当前持仓市值", default=0.0)
    daily_pnl_pct = serializers.FloatField(help_text="当日盈亏比例", default=0.0)
    daily_trade_count = serializers.IntegerField(help_text="当日交易次数", default=0)
    volatility_z = serializers.FloatField(help_text="波动率Z分数", required=False)
    avg_volume = serializers.FloatField(help_text="平均成交量", required=False)
    sizing_method = serializers.ChoiceField(
        choices=['fixed_fraction', 'atr_risk'],
        help_text="仓位计算方法",
        default='fixed_fraction'
    )


class ExecutionEvaluateOutputSerializer(serializers.Serializer):
    """执行评估输出序列化器"""

    # 决策结果
    decision_action = serializers.ChoiceField(
        choices=['allow', 'deny', 'watch'],
        help_text="决策动作"
    )
    decision_reasons = serializers.ListField(
        child=serializers.CharField(),
        help_text="决策原因码列表"
    )
    decision_text = serializers.CharField(help_text="决策原因描述")
    decision_confidence = serializers.FloatField(help_text="决策置信度")
    valid_until_seconds = serializers.IntegerField(
        help_text="决策有效期（秒）",
        allow_null=True
    )

    # 仓位结果
    target_notional = serializers.FloatField(help_text="目标名义金额")
    qty = serializers.IntegerField(help_text="数量")
    expected_risk_pct = serializers.FloatField(help_text="预期风险比例")
    sizing_method = serializers.CharField(help_text="仓位计算方法")
    sizing_explain = serializers.CharField(help_text="仓位计算说明")

    # 风险快照
    risk_snapshot = serializers.DictField(help_text="风险快照")

    # 执行状态
    can_execute = serializers.BooleanField(help_text="是否可以执行")
    requires_confirmation = serializers.BooleanField(help_text="是否需要人工确认")
