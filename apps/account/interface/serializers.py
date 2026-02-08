"""
DRF Serializers for Account API.
"""

from rest_framework import serializers
from datetime import date
from decimal import Decimal

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
    CapitalFlowModel,
    AssetMetadataModel,
    CurrencyModel,
    AssetCategoryModel,
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
