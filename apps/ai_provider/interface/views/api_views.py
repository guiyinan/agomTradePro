"""
API Views for AI Provider Management.

DRF ViewSet for CRUD operations via AJAX.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Sum
from datetime import date

from ...infrastructure.models import AIProviderConfig, AIUsageLog
from ...infrastructure.repositories import AIProviderRepository, AIUsageRepository
from ..serializers import (
    AIProviderConfigSerializer,
    AIProviderConfigCreateSerializer,
    AIUsageLogSerializer
)


class AIProviderConfigViewSet(viewsets.ModelViewSet):
    """
    AI提供商配置 API ViewSet

    提供增删改查接口，用于前端模态窗口操作。
    """
    queryset = AIProviderConfig.objects.all().order_by('priority', 'name')
    serializer_class = AIProviderConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action in ['create', 'update', 'partial_update']:
            return AIProviderConfigCreateSerializer
        return AIProviderConfigSerializer

    def list(self, request, *args, **kwargs):
        """获取提供商列表，带今日统计数据"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        # 为每个提供商添加今日统计
        usage_repo = AIUsageRepository()
        providers_with_stats = []

        for provider_data, provider in zip(serializer.data, queryset):
            today_usage = usage_repo.get_daily_usage(provider.id, date.today())
            month_usage = usage_repo.get_monthly_usage(
                provider.id,
                date.today().year,
                date.today().month
            )

            provider_data.update({
                'today_requests': today_usage['total_requests'],
                'today_cost': str(today_usage['total_cost']),
                'month_requests': month_usage['total_requests'],
                'month_cost': str(month_usage['total_cost']),
            })
            providers_with_stats.append(provider_data)

        return Response(providers_with_stats)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """切换启用/禁用状态"""
        provider = self.get_object()
        provider.is_active = not provider.is_active
        provider.save()
        serializer = self.get_serializer(provider)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def usage_stats(self, request, pk=None):
        """获取使用统计"""
        provider = self.get_object()
        usage_repo = AIUsageRepository()

        # 今日统计
        today_usage = usage_repo.get_daily_usage(provider.id, date.today())

        # 本月统计
        month_usage = usage_repo.get_monthly_usage(
            provider.id,
            date.today().year,
            date.today().month
        )

        # 按日期统计（最近30天）
        usage_by_date = usage_repo.get_usage_by_date(provider.id, days=30)

        # 按模型统计
        model_stats = usage_repo.get_model_stats(provider.id, days=30)

        return Response({
            'provider_id': provider.id,
            'today_usage': today_usage,
            'month_usage': month_usage,
            'usage_by_date': usage_by_date,
            'model_stats': model_stats,
        })

    @action(detail=False, methods=['get'])
    def overall_stats(self, request):
        """获取总体统计"""
        today = date.today()

        return Response({
            'total_providers': AIProviderConfig.objects.count(),
            'active_providers': AIProviderConfig.objects.filter(is_active=True).count(),
            'total_requests_today': AIUsageLog.objects.filter(
                created_at__date=today
            ).count(),
            'total_cost_today': float(
                AIUsageLog.objects.filter(
                    created_at__date=today,
                    status='success'
                ).aggregate(
                    total=Sum('estimated_cost')
                )['total'] or 0
            ),
        })


class AIUsageLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    AI调用日志 API ViewSet

    只读接口，用于查看日志。
    """
    queryset = AIUsageLog.objects.all().order_by('-created_at')
    serializer_class = AIUsageLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """支持过滤"""
        queryset = super().get_queryset()
        provider_id = self.request.query_params.get('provider')
        status_filter = self.request.query_params.get('status')

        if provider_id:
            queryset = queryset.filter(provider_id=provider_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset
