"""
Market Data 模块 - Interface 层序列化器
"""

from rest_framework import serializers


class QuoteSnapshotSerializer(serializers.Serializer):
    stock_code = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=4)
    change = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    change_pct = serializers.FloatField(allow_null=True)
    volume = serializers.IntegerField(allow_null=True)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    turnover_rate = serializers.FloatField(allow_null=True)
    volume_ratio = serializers.FloatField(allow_null=True)
    source = serializers.CharField()
    fetched_at = serializers.DateTimeField()


class CapitalFlowSnapshotSerializer(serializers.Serializer):
    stock_code = serializers.CharField()
    trade_date = serializers.DateField()
    main_net_inflow = serializers.FloatField()
    main_net_ratio = serializers.FloatField()
    super_large_net_inflow = serializers.FloatField()
    large_net_inflow = serializers.FloatField()
    medium_net_inflow = serializers.FloatField()
    small_net_inflow = serializers.FloatField()
    source = serializers.CharField()


class StockNewsItemSerializer(serializers.Serializer):
    stock_code = serializers.CharField()
    news_id = serializers.CharField()
    title = serializers.CharField()
    content = serializers.CharField()
    published_at = serializers.DateTimeField()
    url = serializers.CharField(allow_null=True, allow_blank=True)
    source = serializers.CharField()


class ProviderStatusSerializer(serializers.Serializer):
    provider_name = serializers.CharField()
    capability = serializers.CharField()
    is_healthy = serializers.BooleanField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    consecutive_failures = serializers.IntegerField()
    avg_latency_ms = serializers.FloatField(allow_null=True)


class SyncCapitalFlowResponseSerializer(serializers.Serializer):
    stock_code = serializers.CharField()
    synced_count = serializers.IntegerField()
    success = serializers.BooleanField()
    error_message = serializers.CharField(allow_blank=True)


class IngestStockNewsResponseSerializer(serializers.Serializer):
    stock_code = serializers.CharField()
    fetched_count = serializers.IntegerField()
    new_count = serializers.IntegerField()
    data_sufficient = serializers.BooleanField()
    success = serializers.BooleanField()
    error_message = serializers.CharField(allow_blank=True)
