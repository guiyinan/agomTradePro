"""
DRF API Views for Account Module.

提供账户、投资组合、持仓、交易和资金流水的 RESTful API。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, Count
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
    CapitalFlowModel,
    AssetMetadataModel,
    PortfolioObserverGrantModel,
)
from apps.account.infrastructure.repositories import (
    PortfolioRepository,
    PositionRepository,
)
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    PortfolioSerializer,
    PortfolioCreateSerializer,
    PositionSerializer,
    PositionCreateSerializer,
    PositionUpdateSerializer,
    TransactionSerializer,
    TransactionCreateSerializer,
    CapitalFlowSerializer,
    CapitalFlowCreateSerializer,
    AssetMetadataSerializer,
    PortfolioStatisticsSerializer,
    ObserverGrantSerializer,
    ObserverGrantCreateSerializer,
    ObserverGrantUpdateSerializer,
)
from .permissions import TradingPermission, GeneralPermission, ObserverAccessPermission


# ==================== Portfolio ViewSet ====================

class PortfolioViewSet(viewsets.ModelViewSet):
    """
    投资组合 API ViewSet

    提供以下接口:
    - GET /account/api/portfolios/ - 获取投资组合列表
    - POST /account/api/portfolios/ - 创建投资组合
    - GET /account/api/portfolios/{id}/ - 获取组合详情
    - PUT /account/api/portfolios/{id}/ - 更新组合
    - DELETE /account/api/portfolios/{id}/ - 删除组合
    - GET /account/api/portfolios/{id}/positions/ - 获取组合持仓
    - GET /account/api/portfolios/{id}/statistics/ - 获取统计信息

    权限说明:
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（通过有效的 PortfolioObserverGrant）
    """

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self):
        """返回用户可访问的投资组合（包括被授权观察的）"""
        from .permissions import get_accessible_portfolios
        return get_accessible_portfolios(self.request.user)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PortfolioCreateSerializer
        return PortfolioSerializer

    def perform_create(self, serializer):
        """创建时自动关联当前用户（只有拥有者可以创建）"""
        serializer.save(user=self.request.user)

    def check_permissions(self, request):
        """写操作需要拥有者权限"""
        if request.method not in ['GET', 'HEAD', 'OPTIONS']:
            # 写操作：检查是否是拥有者
            if hasattr(self, 'get_object'):
                try:
                    obj = self.get_object()
                    if obj.user != request.user:
                        self.permission_denied(
                            request,
                            message="观察员无权执行写操作，只有账户拥有者可以修改投资组合"
                        )
                except Exception:
                    # 在获取对象之前无法检查，跳过
                    pass
        super().check_permissions(request)

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取投资组合的持仓列表

        GET /account/api/portfolios/{id}/positions/
        """
        portfolio = self.get_object()

        # 记录观察员访问审计日志
        self._log_observer_access_if_needed(request, portfolio, 'positions')

        positions = portfolio.positions.filter(is_closed=False).select_related()

        serializer = PositionSerializer(positions, many=True)
        return Response({
            'success': True,
            'count': positions.count(),
            'data': serializer.data
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        获取投资组合统计信息

        GET /account/api/portfolios/{id}/statistics/
        """
        portfolio = self.get_object()

        # 记录观察员访问审计日志
        self._log_observer_access_if_needed(request, portfolio, 'statistics')

        # 持仓统计
        positions = portfolio.positions.filter(is_closed=False)
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

        # 资产类别分布
        asset_class_breakdown = {}
        for pos in positions:
            key = pos.get_asset_class_display()
            asset_class_breakdown[key] = asset_class_breakdown.get(key, 0) + float(pos.market_value)

        # 地区分布
        region_breakdown = {}
        for pos in positions:
            key = pos.get_region_display()
            region_breakdown[key] = region_breakdown.get(key, 0) + float(pos.market_value)

        # 资金流水
        capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio)
        total_inflow = capital_flows.filter(flow_type='deposit').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        total_outflow = capital_flows.filter(flow_type='withdraw').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        data = {
            'total_value': total_value,
            'total_cost': total_cost,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'position_count': position_count,
            'asset_class_breakdown': asset_class_breakdown,
            'region_breakdown': region_breakdown,
            'total_capital_inflow': total_inflow,
            'total_capital_outflow': total_outflow,
            'net_capital_flow': total_inflow - total_outflow,
        }

        serializer = PortfolioStatisticsSerializer(data)
        return Response(serializer.data)

    def _log_observer_access_if_needed(self, request, portfolio, action: str):
        """
        记录观察员访问审计日志

        Args:
            request: 请求对象
            portfolio: 被访问的投资组合
            action: 操作动作（如 'positions', 'statistics'）
        """
        # 如果访问者不是拥有者，记录为观察员访问
        if portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action='READ',
                resource_type='portfolio_via_observer_grant',
                resource_id=str(portfolio.id),
                response_status=200,
                extra_context={
                    'portfolio_owner': portfolio.user.username,
                    'portfolio_name': portfolio.name,
                    'access_action': action,
                }
            )

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int, extra_context: dict = None):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
            extra_context: 额外上下文信息
        """
        try:
            from apps.audit.infrastructure.repositories import DjangoAuditRepository
            from apps.audit.domain.entities import (
                OperationLog, OperationSource, OperationType, OperationAction
            )
            import uuid

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
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


# ==================== Position ViewSet ====================

class PositionViewSet(viewsets.ModelViewSet):
    """
    持仓 API ViewSet

    提供以下接口:
    - GET /account/api/positions/ - 获取持仓列表
    - POST /account/api/positions/ - 创建持仓
    - GET /account/api/positions/{id}/ - 获取持仓详情
    - PUT /account/api/positions/{id}/ - 更新持仓
    - DELETE /account/api/positions/{id}/ - 删除持仓
    - POST /account/api/positions/{id}/close/ - 平仓

    权限说明:
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（通过有效的 PortfolioObserverGrant）
    """

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self):
        """返回用户可访问的投资组合的持仓"""
        from .permissions import get_accessible_portfolios
        accessible_portfolios = get_accessible_portfolios(self.request.user)
        return PositionModel._default_manager.filter(portfolio__in=accessible_portfolios)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PositionCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PositionUpdateSerializer
        return PositionSerializer

    def perform_create(self, serializer):
        """创建时需要指定投资组合（只有拥有者可以创建）"""
        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )

        # 计算市值和盈亏
        shares = serializer.validated_data['shares']
        avg_cost = serializer.validated_data['avg_cost']
        current_price = serializer.validated_data.get('current_price', avg_cost)
        market_value = shares * float(current_price)
        unrealized_pnl = market_value - (shares * float(avg_cost))
        unrealized_pnl_pct = (unrealized_pnl / (shares * float(avg_cost)) * 100) if avg_cost > 0 else 0

        serializer.save(
            portfolio=portfolio,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct
        )

    def retrieve(self, request, *args, **kwargs):
        """获取持仓详情时记录观察员访问"""
        instance = self.get_object()

        # 如果访问者不是拥有者，记录为观察员访问
        if instance.portfolio.user != request.user:
            self._log_observer_access_if_needed(request, instance, 'detail')

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        """列表查询时记录观察员访问"""
        response = super().list(request, *args, **kwargs)

        # 检查是否有观察员访问的情况
        for portfolio_id in self._get_observer_accessed_portfolios(request):
            self._log_audit_action(
                request=request,
                action='READ',
                resource_type='position_via_observer_grant',
                resource_id=f'portfolio_{portfolio_id}',
                response_status=200,
                extra_context={
                    'portfolio_id': str(portfolio_id),
                }
            )

        return response

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        平仓

        POST /account/api/positions/{id}/close/
        """
        position = self.get_object()

        # 观察员不能平仓
        if position.portfolio.user != request.user:
            return Response({
                'success': False,
                'error': '观察员无权执行平仓操作，只有账户拥有者可以平仓'
            }, status=status.HTTP_403_FORBIDDEN)

        if position.is_closed:
            return Response({
                'success': False,
                'error': '该持仓已平仓'
            }, status=status.HTTP_400_BAD_REQUEST)

        position.is_closed = True
        position.closed_at = timezone.now()
        position.save()

        serializer = PositionSerializer(position)
        return Response({
            'success': True,
            'message': '持仓已平仓',
            'data': serializer.data
        })

    def _get_observer_accessed_portfolios(self, request):
        """
        获取观察员访问的投资组合ID列表

        Returns:
            list: 被观察的投资组合ID列表
        """
        from apps.account.infrastructure.models import PortfolioObserverGrantModel
        from django.utils import timezone

        now = timezone.now()
        active_grants = PortfolioObserverGrantModel._default_manager.filter(
            observer_user_id=request.user,
            status='active',
        ).filter(
            # 未过期
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        ).values_list('owner_user_id', flat=True)

        # 获取这些拥有者的投资组合ID
        return list(PortfolioModel._default_manager.filter(
            user__in=active_grants
        ).values_list('id', flat=True))

    def _log_observer_access_if_needed(self, request, position, action: str):
        """
        记录观察员访问审计日志

        Args:
            request: 请求对象
            position: 被访问的持仓
            action: 操作动作
        """
        # 如果访问者不是拥有者，记录为观察员访问
        if position.portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action='READ',
                resource_type='position_via_observer_grant',
                resource_id=str(position.id),
                response_status=200,
                extra_context={
                    'portfolio_owner': position.portfolio.user.username,
                    'portfolio_name': position.portfolio.name,
                    'position_asset': position.asset_code,
                    'access_action': action,
                }
            )

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int, extra_context: dict = None):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
            extra_context: 额外上下文信息
        """
        try:
            from apps.audit.infrastructure.repositories import DjangoAuditRepository
            from apps.audit.domain.entities import (
                OperationLog, OperationSource, OperationType, OperationAction
            )
            import uuid

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
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


# ==================== Transaction ViewSet ====================

class TransactionViewSet(viewsets.ModelViewSet):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /account/api/transactions/ - 获取交易列表
    - POST /account/api/transactions/ - 创建交易记录
    - GET /account/api/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的交易"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return TransactionModel._default_manager.filter(portfolio__in=user_portfolios).select_related(
            'portfolio', 'position'
        )

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return TransactionCreateSerializer
        return TransactionSerializer

    def perform_create(self, serializer):
        """创建时验证持仓归属"""
        position = serializer.validated_data.get('position')
        if position and position.portfolio.user != self.request.user:
            raise PermissionError("无权为此持仓创建交易记录")

        # 计算成交金额
        shares = serializer.validated_data['shares']
        price = serializer.validated_data['price']
        notional = shares * float(price)

        serializer.save(notional=notional)


# ==================== Capital Flow ViewSet ====================

class CapitalFlowViewSet(viewsets.ModelViewSet):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /account/api/capital-flows/ - 获取资金流水列表
    - POST /account/api/capital-flows/ - 创建资金流水
    - GET /account/api/capital-flows/{id}/ - 获取流水详情
    - DELETE /account/api/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的资金流水"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return CapitalFlowModel._default_manager.filter(portfolio__in=user_portfolios).select_related('portfolio')

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return CapitalFlowCreateSerializer
        return CapitalFlowSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )
        serializer.save(portfolio=portfolio, user=self.request.user)


# ==================== Account Profile API ====================

class AccountProfileView(APIView):
    """
    账户配置 API

    - GET /account/api/profile/ - 获取账户配置
    - PUT /account/api/profile/ - 更新账户配置
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """获取当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        """更新当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileUpdateSerializer(profile, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            # 更新邮箱
            email = request.data.get('email')
            if email:
                request.user.email = email
                request.user.save()

            return Response(serializer.data)
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# ==================== Asset Metadata API ====================

class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    资产元数据 API ViewSet (只读)

    - GET /account/api/assets/ - 获取资产列表
    - GET /account/api/assets/{id}/ - 获取资产详情
    - GET /account/api/assets/by-class/{asset_class}/ - 按类别查询
    """

    queryset = AssetMetadataModel._default_manager.all()
    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='by-class/(?P<asset_class>[^/]+)')
    def by_class(self, request, asset_class=None):
        """
        按资产类别查询

        GET /account/api/assets/by-class/{asset_class}/
        """
        assets = self.get_queryset().filter(asset_class=asset_class)
        serializer = AssetMetadataSerializer(assets, many=True)
        return Response({
            'success': True,
            'count': assets.count(),
            'data': serializer.data
        })


# ==================== Health Check ====================

class AccountHealthView(APIView):
    """Account 服务健康检查"""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """检查 Account 服务健康状态"""
        portfolio_count = PortfolioModel._default_manager.filter(user=request.user).count()
        position_count = PositionModel._default_manager.filter(
            portfolio__user=request.user,
            is_closed=False
        ).count()

        return Response({
            'status': 'healthy',
            'service': 'account',
            'portfolio_count': portfolio_count,
            'position_count': position_count
        })


# ==================== Observer Grant ViewSet ====================

class ObserverGrantViewSet(viewsets.ModelViewSet):
    """
    观察员授权 API ViewSet

    提供以下接口:
    - GET /account/api/observer-grants/ - 获取当前用户的授权列表
    - POST /account/api/observer-grants/ - 创建观察员授权
    - GET /account/api/observer-grants/{id}/ - 获取授权详情
    - PUT /account/api/observer-grants/{id}/ - 更新授权（过期时间）
    - DELETE /account/api/observer-grants/{id}/ - 撤销授权
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

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取授权对应账户的持仓列表（观察员专用）

        GET /account/api/observer-grants/{id}/positions/
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
                'asset_name': pos.asset_name,
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

        DELETE /account/api/observer-grants/{id}/
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

        POST /account/api/observer-grants/
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

        headers = self.get_success_headers(serializer.data)
        return Response({
            'success': True,
            'message': '观察员授权创建成功',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int):
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
            from apps.audit.infrastructure.repositories import DjangoAuditRepository
            from apps.audit.domain.entities import (
                OperationLog, OperationSource, OperationType, OperationAction
            )
            import uuid

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.DATA_MODIFY if action in ('CREATE', 'DELETE', 'UPDATE') else OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
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




# ==================== User Search API ====================

class UserSearchView(APIView):
    """
    用户搜索 API

    用于协作页面添加观察员时的用户搜索

    - GET /account/api/users/search/?q=xxx - 搜索用户
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """
        搜索用户

        支持按用户名或显示名称搜索
        排除当前用户和已授权的用户
        """
        from django.contrib.auth.models import User
        from apps.account.infrastructure.models import PortfolioObserverGrantModel

        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return Response({
                "success": True,
                "results": []
            })

        # 搜索用户（按用户名或显示名称）
        users = User._default_manager.filter(
            is_active=True
        ).filter(
            models.Q(username__icontains=query) |
            models.Q(account_profile__display_name__icontains=query)
        ).exclude(id=request.user.id).select_related("account_profile")[:10]

        # 获取已授权的用户ID列表
        granted_user_ids = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=request.user,
            status="active"
        ).values_list("observer_user_id", flat=True)

        # 格式化结果
        results = []
        for user in users:
            # 检查是否已授权
            is_already_granted = user.id in granted_user_ids

            results.append({
                "id": user.id,
                "username": user.username,
                "display_name": user.account_profile.display_name if hasattr(user, "account_profile") else user.username,
                "email": user.email or "",
                "is_already_granted": is_already_granted,
            })

        return Response({
            "success": True,
            "results": results
        })

