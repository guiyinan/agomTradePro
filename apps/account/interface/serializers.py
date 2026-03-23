"""
DRF Serializers for Account API.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from rest_framework import serializers

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CapitalFlowModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TransactionModel,
)

# ==================== Account Profile ====================

class AccountProfileSerializer(serializers.ModelSerializer):
    """账户配置序列化器"""

    class Meta:
        model = AccountProfileModel
        fields = [
            'id', 'display_name', 'initial_capital', 'risk_tolerance', 'rbac_role',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['rbac_role', 'created_at', 'updated_at']


class AccountProfileUpdateSerializer(serializers.ModelSerializer):
    """账户配置更新序列化器"""

    class Meta:
        model = AccountProfileModel
        fields = ['display_name', 'risk_tolerance']


# ==================== Portfolio ====================

class PortfolioSerializer(serializers.ModelSerializer):
    """投资组合序列化器"""

    username = serializers.CharField(source='user.username', read_only=True)
    base_currency_code = serializers.CharField(source='base_currency.code', read_only=True, allow_null=True)
    base_currency_name = serializers.CharField(source='base_currency.name', read_only=True, allow_null=True)
    total_value = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_pnl = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_pnl_pct = serializers.FloatField(read_only=True)
    position_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PortfolioModel
        fields = [
            'id', 'name', 'is_active', 'base_currency', 'base_currency_code', 'base_currency_name',
            'total_value', 'total_cost', 'total_pnl', 'total_pnl_pct', 'position_count',
            'username', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class PortfolioCreateSerializer(serializers.ModelSerializer):
    """投资组合创建序列化器"""

    class Meta:
        model = PortfolioModel
        fields = ['name', 'is_active', 'base_currency']


# ==================== Position ====================

class PositionSerializer(serializers.ModelSerializer):
    """持仓序列化器"""

    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    asset_name = serializers.CharField(source='asset_code', read_only=True)
    category_code = serializers.CharField(source='category.code', read_only=True, allow_null=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    category_path = serializers.CharField(source='category.get_full_path', read_only=True, allow_null=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True, allow_null=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True, allow_null=True)
    currency_symbol = serializers.CharField(source='currency.symbol', read_only=True, allow_null=True)
    market_value = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    unrealized_pnl = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    unrealized_pnl_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = PositionModel
        fields = [
            'id', 'portfolio', 'portfolio_name', 'asset_code', 'asset_name',
            'category', 'category_code', 'category_name', 'category_path',
            'currency', 'currency_code', 'currency_name', 'currency_symbol',
            'asset_class', 'region', 'cross_border',
            'shares', 'avg_cost', 'current_price',
            'market_value', 'unrealized_pnl', 'unrealized_pnl_pct',
            'source', 'source_id', 'is_closed',
            'opened_at', 'closed_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['market_value', 'unrealized_pnl', 'unrealized_pnl_pct',
                           'opened_at', 'created_at', 'updated_at']


class PositionCreateSerializer(serializers.ModelSerializer):
    """持仓创建序列化器"""

    class Meta:
        model = PositionModel
        fields = [
            'asset_code', 'category', 'currency',
            'asset_class', 'region', 'cross_border',
            'shares', 'avg_cost', 'current_price', 'source', 'source_id'
        ]

    def validate_shares(self, value):
        if value <= 0:
            raise serializers.ValidationError("持仓数量必须大于0")
        return value

    def validate_avg_cost(self, value):
        if value <= 0:
            raise serializers.ValidationError("平均成本价必须大于0")
        return value


class PositionUpdateSerializer(serializers.ModelSerializer):
    """持仓更新序列化器"""

    class Meta:
        model = PositionModel
        fields = ['shares', 'avg_cost', 'current_price', 'is_closed']


# ==================== Transaction ====================

class TransactionSerializer(serializers.ModelSerializer):
    """交易记录序列化器"""

    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    asset_code = serializers.CharField(read_only=True)

    class Meta:
        model = TransactionModel
        fields = [
            'id', 'portfolio', 'portfolio_name', 'position', 'asset_code',
            'action', 'shares', 'price', 'notional', 'commission',
            'notes', 'traded_at', 'created_at'
        ]
        read_only_fields = ['created_at']


class TransactionCreateSerializer(serializers.ModelSerializer):
    """交易记录创建序列化器"""

    class Meta:
        model = TransactionModel
        fields = [
            'portfolio', 'position', 'action', 'asset_code',
            'shares', 'price', 'commission', 'notes', 'traded_at'
        ]

    def validate_shares(self, value):
        if value <= 0:
            raise serializers.ValidationError("交易数量必须大于0")
        return value

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("交易价格必须大于0")
        return value


# ==================== Capital Flow ====================

class CapitalFlowSerializer(serializers.ModelSerializer):
    """资金流水序列化器"""

    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)

    class Meta:
        model = CapitalFlowModel
        fields = [
            'id', 'portfolio', 'portfolio_name', 'flow_type',
            'amount', 'flow_date', 'notes', 'created_at'
        ]
        read_only_fields = ['created_at']


class CapitalFlowCreateSerializer(serializers.ModelSerializer):
    """资金流水创建序列化器"""

    class Meta:
        model = CapitalFlowModel
        fields = ['flow_type', 'amount', 'flow_date', 'notes']

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("金额必须大于0")
        return value


# ==================== Asset Metadata ====================

class AssetMetadataSerializer(serializers.ModelSerializer):
    """资产元数据序列化器"""

    class Meta:
        model = AssetMetadataModel
        fields = [
            'id', 'asset_code', 'name', 'description',
            'asset_class', 'region', 'cross_border', 'style',
            'sector', 'sub_class', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


# ==================== Statistics ====================

class PortfolioStatisticsSerializer(serializers.Serializer):
    """投资组合统计序列化器"""

    total_value = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_pnl = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_pnl_pct = serializers.FloatField()
    position_count = serializers.IntegerField()
    asset_class_breakdown = serializers.DictField(child=serializers.FloatField())
    region_breakdown = serializers.DictField(child=serializers.FloatField())
    total_capital_inflow = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_capital_outflow = serializers.DecimalField(max_digits=20, decimal_places=2)
    net_capital_flow = serializers.DecimalField(max_digits=20, decimal_places=2)


# ==================== Observer Grant ====================

class ObserverGrantSerializer(serializers.ModelSerializer):
    """观察员授权序列化器"""

    owner_username = serializers.CharField(source='owner_user_id.username', read_only=True)
    observer_username = serializers.CharField(source='observer_user_id.username', read_only=True)
    scope_display = serializers.CharField(source='get_scope_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = PortfolioObserverGrantModel
        fields = [
            'id', 'owner_user_id', 'observer_user_id', 'owner_username', 'observer_username',
            'scope', 'scope_display', 'status', 'status_display', 'expires_at',
            'is_valid', 'created_at', 'revoked_at', 'revoked_by'
        ]
        read_only_fields = ['id', 'created_at', 'revoked_at', 'revoked_by']


class ObserverGrantCreateSerializer(serializers.ModelSerializer):
    """观察员授权创建序列化器"""

    # 支持通过 observer_user_id 或 username 指定观察员
    observer_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        write_only=True,
        help_text="观察员用户ID（与 username 二选一）"
    )
    username = serializers.CharField(
        write_only=True,
        required=False,
        help_text="观察员用户名（与 observer_user_id 二选一）"
    )

    class Meta:
        model = PortfolioObserverGrantModel
        fields = ['observer_user_id', 'username', 'expires_at']

    def validate(self, attrs):
        """验证创建授权请求"""
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("用户未登录")

        # 获取观察员用户
        observer_user_id = attrs.get('observer_user_id')
        username = attrs.get('username')

        if not observer_user_id and not username:
            raise serializers.ValidationError({
                "observer_user_id": "请提供 observer_user_id 或 username"
            })

        if username:
            # 通过 username 查找用户
            try:
                observer = User.objects.get(username=username)
                attrs['observer_user_id'] = observer
            except User.DoesNotExist:
                raise serializers.ValidationError({
                    "username": f"用户 '{username}' 不存在"
                })

        # observer_user_id 可能是 User 对象（来自 PrimaryKeyRelatedField 或 username 转换）
        # 或整数 ID（来自直接传递）
        observer_user_id_value = attrs.get('observer_user_id')

        # 处理 DRF 反序列化的情况：可能是 User 对象或整数 ID
        if isinstance(observer_user_id_value, User):
            observer = observer_user_id_value
        elif observer_user_id_value:
            try:
                observer = User.objects.get(id=observer_user_id_value)
            except (User.DoesNotExist, ValueError, TypeError):
                raise serializers.ValidationError({
                    "observer_user_id": "观察员用户不存在"
                })
        else:
            raise serializers.ValidationError({
                "observer_user_id": "请提供观察员用户"
            })

        # 不能授权给自己
        if observer.id == request.user.id:
            raise serializers.ValidationError({
                "observer_user_id": "不能授权给自己"
            })

        # 检查是否已存在 active 授权
        existing = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=request.user,
            observer_user_id=observer,
            status='active'
        ).first()
        if existing:
            raise serializers.ValidationError({
                "observer_user_id": f"该用户已被授权为观察员，授权 ID: {existing.id}"
            })

        # 检查观察员数量限制（每账户最多 10 个）
        active_count = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=request.user,
            status='active'
        ).count()
        if active_count >= 10:
            raise serializers.ValidationError({
                "__all__": "已达到观察员数量上限（10个），请先撤销部分授权"
            })

        # 验证过期时间
        expires_at = attrs.get('expires_at')
        if expires_at:
            from django.utils import timezone
            if expires_at <= timezone.now():
                raise serializers.ValidationError({
                    "expires_at": "过期时间必须大于当前时间"
                })

        return attrs

    def create(self, validated_data):
        """创建授权记录"""
        validated_data.pop('username', None)  # 移除临时字段

        # owner_user_id 由视图的 perform_create 方法提供
        # 这里只处理 validated_data 中的字段
        grant = PortfolioObserverGrantModel._default_manager.create(
            created_by=self.context['request'].user,
            **validated_data
        )
        return grant


class ObserverGrantUpdateSerializer(serializers.ModelSerializer):
    """观察员授权更新序列化器（仅支持更新过期时间）"""

    class Meta:
        model = PortfolioObserverGrantModel
        fields = ['expires_at']

    def validate_expires_at(self, value):
        """验证过期时间"""
        if value:
            from django.utils import timezone
            if value <= timezone.now():
                raise serializers.ValidationError("过期时间必须大于当前时间")
        return value


# ==================== Trading Cost Config ====================

class TradingCostConfigSerializer(serializers.ModelSerializer):
    """交易费率配置序列化器"""

    # 只读计算字段：以万为单位的佣金率（方便展示）
    commission_rate_wan = serializers.SerializerMethodField()
    stamp_duty_rate_qian = serializers.SerializerMethodField()

    class Meta:
        from apps.account.infrastructure.models import TradingCostConfigModel
        model = TradingCostConfigModel
        fields = [
            'id', 'portfolio', 'commission_rate', 'min_commission',
            'stamp_duty_rate', 'transfer_fee_rate', 'is_active',
            'commission_rate_wan', 'stamp_duty_rate_qian',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_commission_rate_wan(self, obj) -> float:
        """佣金率（万）"""
        return round(obj.commission_rate * 10000, 2)

    def get_stamp_duty_rate_qian(self, obj) -> float:
        """印花税率（千）"""
        return round(obj.stamp_duty_rate * 1000, 2)


class TradingCostConfigCreateSerializer(serializers.ModelSerializer):
    """交易费率配置创建/更新序列化器"""

    class Meta:
        from apps.account.infrastructure.models import TradingCostConfigModel
        model = TradingCostConfigModel
        fields = [
            'portfolio', 'commission_rate', 'min_commission',
            'stamp_duty_rate', 'transfer_fee_rate', 'is_active',
        ]

    def validate(self, attrs):
        portfolio = attrs.get("portfolio")
        if self.instance is not None and portfolio is not None and portfolio != self.instance.portfolio:
            raise serializers.ValidationError({"portfolio": "更新时不允许修改所属投资组合"})
        return attrs

    def validate_commission_rate(self, value: float) -> float:
        if value < 0 or value > 0.01:
            raise serializers.ValidationError("佣金率应在 0 ~ 0.01（万0 ~ 万10）之间")
        return value

    def validate_min_commission(self, value: float) -> float:
        if value < 0:
            raise serializers.ValidationError("最低佣金不能为负数")
        return value

    def validate_stamp_duty_rate(self, value: float) -> float:
        if value < 0 or value > 0.01:
            raise serializers.ValidationError("印花税率应在 0 ~ 0.01 之间")
        return value

    def validate_transfer_fee_rate(self, value: float) -> float:
        if value < 0 or value > 0.001:
            raise serializers.ValidationError("过户费率应在 0 ~ 0.001 之间")
        return value


class TradingCostCalculationSerializer(serializers.Serializer):
    """交易费率试算参数校验"""

    ACTION_CHOICES = ("buy", "sell")

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    amount = serializers.FloatField(min_value=0.01)
    is_shanghai = serializers.BooleanField(required=False, default=False)
