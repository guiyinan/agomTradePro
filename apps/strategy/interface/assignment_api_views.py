"""Portfolio-strategy assignment API viewset and bind/unbind endpoints.

Interface层:
- 提供REST API接口与页面表单 JSON 端点
- 只做输入验证和输出格式化，禁止业务逻辑
"""

import json
import logging

from django.apps import apps as django_apps
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy.application.interface_services import (
    bind_strategy_assignment,
    get_assignment_queryset,
    list_assignments_by_portfolio,
    set_assignment_active,
    unbind_strategy_assignments,
)
from apps.strategy.application.simulated_trading_gateway import get_simulated_trading_facade
from apps.strategy.interface.page_views import _json_error
from apps.strategy.interface.serializers import (
    PortfolioStrategyAssignmentDetailSerializer,
    PortfolioStrategyAssignmentSerializer,
)
from core.exceptions import InvalidInputError

logger = logging.getLogger(__name__)

StrategyModel = django_apps.get_model("strategy", "StrategyModel")


# ========================================================================
# Portfolio Strategy Assignment ViewSet
# ========================================================================

class PortfolioStrategyAssignmentViewSet(viewsets.ModelViewSet):
    """投资组合策略关联 CRUD API"""

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['portfolio', 'strategy', 'is_active']
    search_fields = ['portfolio__account_name', 'strategy__name']
    ordering_fields = ['assigned_at', 'created_at']
    ordering = ['-assigned_at']

    def get_queryset(self):
        return get_assignment_queryset()

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'retrieve':
            return PortfolioStrategyAssignmentDetailSerializer
        return PortfolioStrategyAssignmentSerializer

    def perform_create(self, serializer):
        """创建时自动设置分配者"""
        serializer.save(assigned_by=self.request.user.account_profile)

    @extend_schema(
        summary="获取投资组合的策略列表",
        description="获取指定投资组合的所有策略分配",
        parameters=[
            OpenApiParameter(
                name='portfolio_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='投资组合ID'
            )
        ],
        responses={200: PortfolioStrategyAssignmentSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def by_portfolio(self, request):
        """获取投资组合的策略列表"""
        portfolio_id = request.query_params.get('portfolio_id')
        if not portfolio_id:
            return Response(
                {'detail': '必须提供 portfolio_id 参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        assignments = list_assignments_by_portfolio(portfolio_id)
        serializer = self.get_serializer(assignments, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="激活策略分配",
        description="激活指定的投资组合策略分配",
        responses={200: PortfolioStrategyAssignmentSerializer}
    )
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """激活策略分配"""
        assignment = self.get_object()
        assignment = set_assignment_active(assignment.id, True) or assignment
        serializer = self.get_serializer(assignment)
        return Response(serializer.data)

    @extend_schema(
        summary="停用策略分配",
        description="停用指定的投资组合策略分配",
        responses={200: PortfolioStrategyAssignmentSerializer}
    )
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """停用策略分配"""
        assignment = self.get_object()
        assignment = set_assignment_active(assignment.id, False) or assignment
        serializer = self.get_serializer(assignment)
        return Response(serializer.data)


@login_required
def bind_strategy(request):
    """绑定策略到投资组合"""
    if request.method != 'POST':
        return _json_error('只支持 POST 请求', status.HTTP_405_METHOD_NOT_ALLOWED)

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')
        strategy_id = data.get('strategy_id')
    except json.JSONDecodeError:
        return _json_error('无效 JSON', status.HTTP_400_BAD_REQUEST)

    try:
        if not portfolio_id or not strategy_id:
            raise InvalidInputError('缺少必要参数')
        portfolio_id = int(portfolio_id)

        strategy = get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by=request.user.account_profile,
        )
        if not get_simulated_trading_facade().user_owns_account(
            portfolio_id,
            request.user.id,
        ):
            return _json_error('账户不存在或无权限访问', status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            bind_strategy_assignment(
                portfolio_id=portfolio_id,
                strategy=strategy,
                assigned_by=request.user.account_profile,
            )

        return JsonResponse({'success': True, 'message': '策略绑定成功'})

    except InvalidInputError as exc:
        return _json_error(exc.message, exc.status_code)
    except Exception:
        logger.exception('Unexpected error while binding strategy')
        return _json_error('策略绑定失败，请稍后重试', status.HTTP_500_INTERNAL_SERVER_ERROR)


@login_required
def unbind_strategy(request):
    """解绑投资组合的策略"""
    if request.method != 'POST':
        return _json_error('只支持 POST 请求', status.HTTP_405_METHOD_NOT_ALLOWED)

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')
    except json.JSONDecodeError:
        return _json_error('无效 JSON', status.HTTP_400_BAD_REQUEST)

    try:
        if not portfolio_id:
            raise InvalidInputError('缺少必要参数')
        portfolio_id = int(portfolio_id)
        if not get_simulated_trading_facade().user_owns_account(
            portfolio_id,
            request.user.id,
        ):
            return _json_error('账户不存在或无权限访问', status.HTTP_404_NOT_FOUND)

        unbind_strategy_assignments(portfolio_id)

        return JsonResponse({'success': True, 'message': '策略已解绑'})

    except InvalidInputError as exc:
        return _json_error(exc.message, exc.status_code)
    except Exception:
        logger.exception('Unexpected error while unbinding strategy')
        return _json_error('策略解绑失败，请稍后重试', status.HTTP_500_INTERNAL_SERVER_ERROR)


__all__ = [
    "PortfolioStrategyAssignmentViewSet",
    "bind_strategy",
    "unbind_strategy",
]
