"""Account observer grant API views."""

from decimal import Decimal
from importlib import import_module
from typing import Any

from django.apps import apps as django_apps
from django.db import models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import GeneralPermission, ObserverAccessPermission, TradingPermission
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    AssetMetadataSerializer,
    CapitalFlowCreateSerializer,
    CapitalFlowSerializer,
    ObserverGrantCreateSerializer,
    ObserverGrantSerializer,
    ObserverGrantUpdateSerializer,
    PortfolioCreateSerializer,
    PortfolioSerializer,
    PortfolioStatisticsSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PositionUpdateSerializer,
    TradingCostCalculationSerializer,
    TradingCostConfigCreateSerializer,
    TradingCostConfigSerializer,
    TransactionCreateSerializer,
    TransactionSerializer,
)

PortfolioModel = django_apps.get_model("account", "PortfolioModel")
PortfolioObserverGrantModel = django_apps.get_model("account", "PortfolioObserverGrantModel")

class ObserverGrantViewSet(viewsets.ModelViewSet):
    """
    观察员授权 API ViewSet

    提供以下接口:
    - GET /api/account/observer-grants/ - 获取当前用户的授权列表
    - POST /api/account/observer-grants/ - 创建观察员授权
    - GET /api/account/observer-grants/{id}/ - 获取授权详情
    - PUT /api/account/observer-grants/{id}/ - 更新授权（过期时间）
    - DELETE /api/account/observer-grants/{id}/ - 撤销授权
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get_queryset(self):
        """支持 owner 和 observer 双视角查询"""
        # 支持观察员视角查询
        as_observer = self.request.query_params.get('as_observer') == '1'

        if as_observer:
            # 返回当前用户作为观察员的授权
            queryset = PortfolioObserverGrantModel._default_manager.filter(
                observer_user_id=self.request.user
            ).select_related('observer_user_id', 'owner_user_id', 'revoked_by')
        else:
            # 返回当前用户作为 owner 的授权
            queryset = PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id=self.request.user
            ).select_related('observer_user_id', 'owner_user_id', 'revoked_by')

        # 支持按状态过滤
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at')

    def get_object(self):
        """
        对写操作使用全量查询后做显式鉴权，确保“对象存在但无权限”返回 403。
        """
        if self.action in ['destroy', 'update', 'partial_update', 'retrieve', 'positions']:
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            lookup_value = self.kwargs.get(lookup_url_kwarg)
            grant = get_object_or_404(
                PortfolioObserverGrantModel._default_manager.select_related(
                    'owner_user_id', 'observer_user_id', 'revoked_by'
                ),
                **{self.lookup_field: lookup_value},
            )
            if self.action in ['retrieve', 'positions']:
                if grant.owner_user_id == self.request.user or grant.observer_user_id == self.request.user:
                    return grant
                if self.action == 'positions':
                    self.permission_denied(self.request, message='无权访问此授权')
                return super().get_object()
            if grant.owner_user_id != self.request.user:
                self.permission_denied(self.request, message='无权访问此授权')
            return grant
        return super().get_object()

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取授权对应账户的持仓列表（观察员专用）

        GET /api/account/observer-grants/{id}/positions/
        """
        grant = self.get_object()

        # 验证当前用户是该授权的观察员
        if grant.observer_user_id != request.user:
            return Response({
                'success': False,
                'error': '您无权查看此授权的持仓信息'
            }, status=status.HTTP_403_FORBIDDEN)

        # 验证授权状态
        if grant.status != 'active':
            return Response({
                'success': False,
                'error': f'授权状态为 {grant.get_status_display()}，无法查看'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查授权是否过期
        if grant.is_expired():
            return Response({
                'success': False,
                'error': '授权已过期，无法查看'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 获取 owner 的活跃投资组合
        portfolio = PortfolioModel._default_manager.filter(
            user=grant.owner_user_id,
            is_active=True
        ).first()

        if not portfolio:
            return Response({
                'success': True,
                'data': {
                    'positions': [],
                    'statistics': {
                        'position_count': 0,
                        'total_value': 0,
                        'total_cost': 0,
                        'total_pnl': 0,
                        'total_pnl_pct': 0
                    }
                }
            })

        # 获取持仓
        positions = portfolio.positions.filter(is_closed=False).select_related()

        # 计算统计
        position_count = positions.count()
        total_value = positions.aggregate(total=Sum('market_value'))['total'] or Decimal('0')
        total_cost = positions.aggregate(
            total=Sum(
                models.F('shares') * models.F('avg_cost'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2),
            )
        )['total'] or Decimal('0')
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        # 序列化持仓数据
        positions_data = []
        for pos in positions:
            positions_data.append({
                'id': pos.id,
                'asset_code': pos.asset_code,
                'asset_name': getattr(pos, 'asset_name', pos.asset_code),
                'asset_class': pos.asset_class,
                'shares': float(pos.shares),
                'avg_cost': float(pos.avg_cost),
                'current_price': float(pos.current_price),
                'market_value': float(pos.market_value),
                'unrealized_pnl': float(pos.unrealized_pnl),
                'unrealized_pnl_pct': float(pos.unrealized_pnl_pct),
            })

        # 记录观察员访问审计日志
        self._log_audit_action(
            request=request,
            action='READ',
            resource_type='observer_grant_positions',
            resource_id=str(grant.id),
            response_status=200,
            extra_context={
                'grant_owner': grant.owner_user_id.username,
                'portfolio_id': portfolio.id,
            }
        )

        return Response({
            'success': True,
            'data': {
                'positions': positions_data,
                'statistics': {
                    'position_count': position_count,
                    'total_value': float(total_value),
                    'total_cost': float(total_cost),
                    'total_pnl': float(total_pnl),
                    'total_pnl_pct': total_pnl_pct,
                }
            }
        })

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return ObserverGrantCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ObserverGrantUpdateSerializer
        return ObserverGrantSerializer

    def perform_create(self, serializer):
        """创建时自动关联当前用户为 owner"""
        serializer.save(owner_user_id=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """
        撤销授权（软删除）

        DELETE /api/account/observer-grants/{id}/
        """
        grant = self.get_object()

        # 验证权限：只有 owner 可以撤销
        if grant.owner_user_id != request.user:
            return Response({
                'success': False,
                'error': '无权撤销此授权'
            }, status=status.HTTP_403_FORBIDDEN)

        # 已撤销或过期的授权不能再次撤销
        if grant.status != 'active':
            return Response({
                'success': False,
                'error': f'授权状态为 {grant.get_status_display()}，无法撤销'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 撤销授权
        grant.revoke(request.user)

        # 审计打点
        self._log_audit_action(
            request=request,
            action='DELETE',
            resource_type='observer_grant',
            resource_id=str(grant.id),
            response_status=200
        )

        serializer = ObserverGrantSerializer(grant)
        return Response({
            'success': True,
            'message': '授权已撤销',
            'data': serializer.data
        })

    def create(self, request, *args, **kwargs):
        """
        创建观察员授权

        POST /api/account/observer-grants/
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # 审计打点
        grant = serializer.instance
        self._log_audit_action(
            request=request,
            action='CREATE',
            resource_type='observer_grant',
            resource_id=str(grant.id),
            response_status=201
        )

        # 使用完整序列化器返回创建的数据
        response_serializer = ObserverGrantSerializer(grant)
        headers = self.get_success_headers(response_serializer.data)
        return Response({
            'success': True,
            'message': '观察员授权创建成功',
            'data': response_serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)

    def _log_audit_action(
        self,
        request,
        action: str,
        resource_type: str,
        resource_id: str,
        response_status: int,
        extra_context: dict[str, Any] | None = None,
    ):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
        """
        try:
            import uuid

            from apps.audit.domain.entities import (
                OperationAction,
                OperationLog,
                OperationSource,
                OperationType,
            )

            audit_repo = import_module("apps.audit.infrastructure.repositories").DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.DATA_MODIFY if action in ('CREATE', 'DELETE', 'UPDATE') else OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
                request_params=extra_context or {},
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            audit_repo.save_operation_log(log_entity)

        except Exception as e:
            # 审计失败不影响主流程
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"记录审计日志失败: {e}", exc_info=True)

    @staticmethod
    def _get_client_ip(request):
        """获取客户端IP地址"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

