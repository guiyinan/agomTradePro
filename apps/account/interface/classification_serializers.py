"""
DRF Serializers for Asset Classification and Multi-Currency Support.
"""

from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from rest_framework import serializers

AssetCategoryModel = django_apps.get_model("account", "AssetCategoryModel")
CurrencyModel = django_apps.get_model("account", "CurrencyModel")
ExchangeRateModel = django_apps.get_model("account", "ExchangeRateModel")

# ==================== Asset Category ====================

class AssetCategorySerializer(serializers.ModelSerializer):
    """资产分类序列化器"""

    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)
    full_path = serializers.CharField(source='get_full_path', read_only=True)
    children_count = serializers.IntegerField(source='children.count', read_only=True)

    class Meta:
        model = AssetCategoryModel
        fields = [
            'id', 'code', 'name', 'parent', 'parent_name',
            'level', 'path', 'full_path',
            'description', 'is_active', 'sort_order',
            'children_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['level', 'path', 'created_at', 'updated_at']


class AssetCategoryTreeSerializer(serializers.ModelSerializer):
    """资产分类树形序列化器"""
    children = serializers.SerializerMethodField()

    class Meta:
        model = AssetCategoryModel
        fields = [
            'id', 'code', 'name', 'level', 'path',
            'description', 'is_active', 'sort_order',
            'children'
        ]

    def get_children(self, obj):
        """获取子分类"""
        children = obj.children.filter(is_active=True).order_by('sort_order')
        return AssetCategoryTreeSerializer(children, many=True).data


# ==================== Currency ====================

class CurrencySerializer(serializers.ModelSerializer):
    """币种序列化器"""

    class Meta:
        model = CurrencyModel
        fields = [
            'id', 'code', 'name', 'symbol', 'is_base', 'is_active',
            'precision', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


# ==================== Exchange Rate ====================

class ExchangeRateSerializer(serializers.ModelSerializer):
    """汇率序列化器"""

    from_currency_code = serializers.CharField(source='from_currency.code', read_only=True)
    from_currency_name = serializers.CharField(source='from_currency.name', read_only=True)
    to_currency_code = serializers.CharField(source='to_currency.code', read_only=True)
    to_currency_name = serializers.CharField(source='to_currency.name', read_only=True)

    class Meta:
        model = ExchangeRateModel
        fields = [
            'id', 'from_currency', 'from_currency_code', 'from_currency_name',
            'to_currency', 'to_currency_code', 'to_currency_name',
            'rate', 'effective_date', 'created_at'
        ]
        read_only_fields = ['created_at']


class ExchangeRateCreateSerializer(serializers.ModelSerializer):
    """汇率创建序列化器"""

    class Meta:
        model = ExchangeRateModel
        fields = ['from_currency', 'to_currency', 'rate', 'effective_date']

    def validate_rate(self, value):
        if value <= 0:
            raise serializers.ValidationError("汇率必须大于0")
        return value


class CurrencyConvertSerializer(serializers.Serializer):
    """货币转换序列化器"""

    amount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=0)
    from_currency = serializers.CharField(max_length=10)
    to_currency = serializers.CharField(max_length=10)
    date = serializers.DateField(required=False, allow_null=True)

    converted_amount = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    rate_used = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)
    rate_date = serializers.DateField(read_only=True)


# ==================== Statistics ====================

class AssetAllocationSerializer(serializers.Serializer):
    """资产配置统计序列化器"""

    category_path = serializers.CharField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    percentage = serializers.FloatField()
    currency_code = serializers.CharField()


class CurrencyAllocationSerializer(serializers.Serializer):
    """币种配置序列化器"""

    currency_code = serializers.CharField()
    currency_name = serializers.CharField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    amount_base = serializers.DecimalField(max_digits=20, decimal_places=2)  # 基准货币金额
    percentage = serializers.FloatField()
