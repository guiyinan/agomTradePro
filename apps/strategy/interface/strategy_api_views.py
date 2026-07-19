"""Strategy aggregate API viewsets (strategy, script config, AI config).

Interface层:
- 提供REST API接口，使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy.application.interface_services import (
    get_ai_strategy_config_queryset_for_access,
    get_script_config_queryset,
    get_strategy_ai_config,
    get_strategy_execution_logs_page,
    get_strategy_position_rule,
    get_strategy_queryset_for_access,
    get_strategy_queryset_for_owner,
    get_strategy_script_config,
    set_strategy_active,
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.interface.sdk_contract_actions import StrategySDKContractActionsMixin
from apps.strategy.interface.serializers import (
    AIStrategyConfigSerializer,
    PositionManagementEvaluateInputSerializer,
    PositionManagementEvaluateResultSerializer,
    PositionManagementRuleSerializer,
    RuleConditionListSerializer,
    ScriptConfigSerializer,
    StrategyDetailSerializer,
    StrategyExecutionLogListSerializer,
    StrategySerializer,
)

# ========================================================================
# Strategy ViewSet
# ========================================================================

class StrategyViewSet(StrategySDKContractActionsMixin, viewsets.ModelViewSet):
    """策略 CRUD API"""

    serializer_class = StrategySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'version']
    ordering = ['-created_at']

    def get_queryset(self):
        return get_strategy_queryset_for_access(
            owner_profile_id=getattr(getattr(self.request.user, "account_profile", None), "id", None),
            include_all=bool(self.request.user.is_staff or self.request.user.is_superuser))

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'retrieve':
            return StrategyDetailSerializer
        return StrategySerializer

    def perform_create(self, serializer):
        """创建时自动设置创建者"""
        serializer.save(created_by=self.request.user.account_profile)

    @extend_schema(
        summary="获取我的策略列表",
        description="获取当前用户创建的所有策略",
        responses={200: StrategySerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def my_strategies(self, request):
        """获取我的策略列表"""
        strategies = get_strategy_queryset_for_owner(request.user.account_profile.id)
        serializer = self.get_serializer(strategies, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="激活策略",
        description="激活指定的策略",
        responses={200: StrategySerializer}
    )
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """激活策略"""
        strategy = self.get_object()
        strategy = set_strategy_active(strategy.id, True) or strategy
        serializer = self.get_serializer(strategy)
        return Response(serializer.data)

    @extend_schema(
        summary="停用策略",
        description="停用指定的策略",
        responses={200: StrategySerializer}
    )
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """停用策略"""
        strategy = self.get_object()
        strategy = set_strategy_active(strategy.id, False) or strategy
        serializer = self.get_serializer(strategy)
        return Response(serializer.data)

    @extend_schema(
        summary="获取策略的规则列表",
        description="获取指定策略的所有规则条件",
        responses={200: RuleConditionListSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def rules(self, request, pk=None):
        """获取策略的规则列表"""
        strategy = self.get_object()
        rules = strategy.rules.all()
        serializer = RuleConditionListSerializer(rules, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="获取策略的脚本配置",
        description="获取指定策略的脚本配置",
        responses={200: ScriptConfigSerializer}
    )
    @action(detail=True, methods=['get'])
    def script_config(self, request, pk=None):
        """获取策略的脚本配置"""
        strategy = self.get_object()
        config = get_strategy_script_config(strategy.id)
        if config is None:
            return Response(
                {'detail': '该策略没有脚本配置'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = ScriptConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        summary="获取策略的 AI 配置",
        description="获取指定策略的 AI 配置",
        responses={200: AIStrategyConfigSerializer}
    )
    @action(detail=True, methods=['get'])
    def ai_config(self, request, pk=None):
        """获取策略的 AI 配置"""
        strategy = self.get_object()
        config = get_strategy_ai_config(strategy.id)
        if config is None:
            return Response(
                {'detail': '该策略没有 AI 配置'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = AIStrategyConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        summary="获取策略的执行日志",
        description="获取指定策略的执行日志（支持分页）",
        responses={200: StrategyExecutionLogListSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def execution_logs(self, request, pk=None):
        """获取策略的执行日志（支持分页）"""
        strategy = self.get_object()

        # 分页参数
        offset = int(request.query_params.get('offset', 0))
        limit = int(request.query_params.get('limit', 20))

        logs, total = get_strategy_execution_logs_page(strategy.id, offset, limit)

        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response({
            'results': serializer.data,
            'total': total,
            'offset': offset,
            'limit': limit,
            'has_more': offset + limit < total
        })

    @extend_schema(
        summary="获取策略仓位管理规则",
        description="获取指定策略绑定的仓位管理规则",
        responses={200: PositionManagementRuleSerializer}
    )
    @action(detail=True, methods=['get'])
    def position_rule(self, request, pk=None):
        strategy = self.get_object()
        rule = get_strategy_position_rule(strategy.id)
        if rule is None:
            return Response(
                {'detail': '该策略尚未配置仓位管理规则'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(PositionManagementRuleSerializer(rule).data)

    @extend_schema(
        summary="按策略计算仓位管理建议",
        description="基于策略绑定规则与上下文变量计算买卖价、止盈止损与仓位建议",
        request=PositionManagementEvaluateInputSerializer,
        responses={200: PositionManagementEvaluateResultSerializer}
    )
    @action(detail=True, methods=['post'])
    def evaluate_position_management(self, request, pk=None):
        strategy = self.get_object()
        rule = get_strategy_position_rule(strategy.id)
        if rule is None:
            return Response(
                {'detail': '该策略尚未配置仓位管理规则'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not rule.is_active:
            return Response(
                {'detail': '仓位管理规则未启用'},
                status=status.HTTP_400_BAD_REQUEST
            )

        input_serializer = PositionManagementEvaluateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        context = input_serializer.validated_data['context']

        try:
            result = PositionManagementService.evaluate(rule=rule, context=context)
        except PositionRuleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = PositionManagementEvaluateResultSerializer(data=result.to_dict())
        output_serializer.is_valid(raise_exception=True)
        return Response(output_serializer.data)


# ========================================================================
# Script Config ViewSet
# ========================================================================

class ScriptConfigViewSet(viewsets.ModelViewSet):
    """脚本配置 CRUD API"""

    serializer_class = ScriptConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['strategy__name']

    def get_queryset(self):
        return get_script_config_queryset()


# ========================================================================
# AI Strategy Config ViewSet
# ========================================================================

class AIStrategyConfigViewSet(viewsets.ModelViewSet):
    """AI策略配置 CRUD API"""

    serializer_class = AIStrategyConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'approval_mode', 'ai_provider']
    search_fields = ['strategy__name']

    def get_queryset(self):
        return get_ai_strategy_config_queryset_for_access(owner_profile_id=getattr(getattr(self.request.user, "account_profile", None), "id", None), include_all=bool(self.request.user.is_staff or self.request.user.is_superuser))


__all__ = [
    "AIStrategyConfigViewSet",
    "ScriptConfigViewSet",
    "StrategyViewSet",
]
