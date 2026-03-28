"""
Django REST Framework Views for Strategy System

Interface层:
- 提供REST API接口
- 使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.domain.services import (
    DecisionPolicyEngine,
    PreTradeRiskGate,
    SizingEngine,
)
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    StrategyExecutionLogModel,
    StrategyModel,
)
from apps.strategy.interface.serializers import (
    AIStrategyConfigSerializer,
    ExecutionEvaluateInputSerializer,
    ExecutionEvaluateOutputSerializer,
    PortfolioStrategyAssignmentDetailSerializer,
    PortfolioStrategyAssignmentSerializer,
    PositionManagementEvaluateInputSerializer,
    PositionManagementEvaluateResultSerializer,
    PositionManagementRuleSerializer,
    RuleConditionListSerializer,
    RuleConditionSerializer,
    ScriptConfigSerializer,
    StrategyDetailSerializer,
    StrategyExecutionLogListSerializer,
    StrategyExecutionLogSerializer,
    StrategySerializer,
)
from core.exceptions import DuplicateResourceError, InvalidInputError

logger = logging.getLogger(__name__)

_UNSET = object()
DEFAULT_SCRIPT_ALLOWED_MODULES = ['math', 'datetime', 'statistics', 'pandas', 'numpy']
DEFAULT_SCRIPT_SANDBOX_CONFIG = {'mode': 'relaxed'}
VALID_STRATEGY_TYPES = {choice[0] for choice in StrategyModel._meta.get_field('strategy_type').choices}
VALID_SCRIPT_LANGUAGES = {choice[0] for choice in ScriptConfigModel._meta.get_field('script_language').choices}


def _json_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> JsonResponse:
    """Return a consistent JSON error payload for HTML form endpoints."""
    return JsonResponse({'success': False, 'error': message}, status=status_code)


def _format_validation_detail(detail) -> str:
    """Flatten DRF validation details into a compact human-readable string."""
    if isinstance(detail, dict):
        parts = [f'{key}: {_format_validation_detail(value)}' for key, value in detail.items()]
        return '; '.join(parts)
    if isinstance(detail, list):
        return '; '.join(_format_validation_detail(item) for item in detail)
    return str(detail)


def _parse_rules_payload(raw_value: str | None, preserve_existing: bool = False):
    """Parse rule payload JSON from the page form."""
    if raw_value is None:
        return _UNSET if preserve_existing else []

    try:
        rules_payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise InvalidInputError('规则配置格式无效，无法保存') from exc

    if not isinstance(rules_payload, list):
        raise InvalidInputError('规则配置必须是数组格式')
    return rules_payload


def _parse_script_payload(raw_value: str | None, preserve_existing: bool = False):
    """Parse script payload from the page form."""
    if raw_value is None:
        return _UNSET if preserve_existing else ''
    return raw_value


def _build_strategy_serializer(request, existing_strategy: StrategyModel | None = None) -> StrategySerializer:
    """Build a validated serializer for strategy base fields."""
    name = (request.POST.get('name') or '').strip()
    if not name:
        raise InvalidInputError('策略名称不能为空')

    submitted_strategy_type = (request.POST.get('strategy_type') or '').strip()
    if existing_strategy is None:
        strategy_type = submitted_strategy_type
        if strategy_type not in VALID_STRATEGY_TYPES:
            raise InvalidInputError('策略类型无效')
        version = request.POST.get('version', 1)
    else:
        if submitted_strategy_type and submitted_strategy_type != existing_strategy.strategy_type:
            raise InvalidInputError('策略类型创建后不可修改')
        strategy_type = existing_strategy.strategy_type
        version = existing_strategy.version + 1

    serializer = StrategySerializer(
        existing_strategy,
        data={
            'name': name,
            'description': request.POST.get('description', ''),
            'strategy_type': strategy_type,
            'version': version,
            'is_active': existing_strategy.is_active if existing_strategy is not None else False,
            'max_position_pct': request.POST.get('max_position_pct', 20),
            'max_total_position_pct': request.POST.get('max_total_position_pct', 95),
            'stop_loss_pct': request.POST.get('stop_loss_pct') or None,
        },
    )
    serializer.is_valid(raise_exception=True)
    return serializer


def _replace_rule_conditions(strategy: StrategyModel, rules_payload) -> None:
    """Replace strategy rule conditions after validating the submitted payload."""
    if rules_payload is _UNSET:
        return

    validated_rules: list[dict] = []
    for index, rule_data in enumerate(rules_payload, start=1):
        if not isinstance(rule_data, dict):
            raise InvalidInputError(f'第 {index} 条规则格式无效')

        rule_name = str(rule_data.get('rule_name', '')).strip()
        if not rule_name:
            continue

        serializer = RuleConditionSerializer(
            data={
                'strategy': strategy.id,
                'rule_name': rule_name,
                'rule_type': rule_data.get('rule_type', 'macro'),
                'condition_json': rule_data.get('condition_json', {}),
                'action': str(rule_data.get('action', 'buy')).lower(),
                'weight': rule_data.get('weight', 0.1),
                'target_assets': rule_data.get('target_assets', []),
                'priority': rule_data.get('priority', 10),
                'is_enabled': rule_data.get('is_enabled', True),
            }
        )
        try:
            serializer.is_valid(raise_exception=True)
        except drf_serializers.ValidationError as exc:
            raise InvalidInputError(
                f'第 {index} 条规则校验失败: {_format_validation_detail(exc.detail)}'
            ) from exc
        validated_rules.append(serializer.validated_data)

    RuleConditionModel._default_manager.filter(strategy=strategy).delete()
    for validated_rule in validated_rules:
        RuleConditionModel._default_manager.create(**validated_rule)


def _save_script_config(
    strategy: StrategyModel,
    script_code_payload,
    script_language: str,
) -> None:
    """Create, update, or delete script config based on submitted form data."""
    if script_code_payload is _UNSET:
        return

    existing_config = ScriptConfigModel._default_manager.filter(strategy=strategy).first()
    script_code = (script_code_payload or '').strip()

    if not script_code:
        if existing_config is not None:
            existing_config.delete()
        return

    if script_language not in VALID_SCRIPT_LANGUAGES:
        raise InvalidInputError('脚本语言无效')

    serializer = ScriptConfigSerializer(
        existing_config,
        data={
            'strategy': strategy.id,
            'script_language': script_language,
            'script_code': script_code,
            'sandbox_config': DEFAULT_SCRIPT_SANDBOX_CONFIG,
            'allowed_modules': DEFAULT_SCRIPT_ALLOWED_MODULES,
            'version': existing_config.version if existing_config is not None else '1.0',
            'is_active': True,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(f'脚本配置校验失败: {_format_validation_detail(exc.detail)}') from exc
    serializer.save()

# ========================================================================
# Strategy ViewSet
# ========================================================================

class StrategyViewSet(viewsets.ModelViewSet):
    """策略 CRUD API"""

    queryset = StrategyModel._default_manager.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'version']
    ordering = ['-created_at']

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
        strategies = self.queryset.filter(created_by=request.user.account_profile)
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
        strategy.is_active = True
        strategy.save()
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
        strategy.is_active = False
        strategy.save()
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
        try:
            config = strategy.script_config
            serializer = ScriptConfigSerializer(config)
            return Response(serializer.data)
        except ScriptConfigModel.DoesNotExist:
            return Response(
                {'detail': '该策略没有脚本配置'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="获取策略的 AI 配置",
        description="获取指定策略的 AI 配置",
        responses={200: AIStrategyConfigSerializer}
    )
    @action(detail=True, methods=['get'])
    def ai_config(self, request, pk=None):
        """获取策略的 AI 配置"""
        strategy = self.get_object()
        try:
            config = strategy.ai_config
            serializer = AIStrategyConfigSerializer(config)
            return Response(serializer.data)
        except AIStrategyConfigModel.DoesNotExist:
            return Response(
                {'detail': '该策略没有 AI 配置'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="获取策略的执行日志",
        description="获取指定策略的执行日志（支持分页）",
        responses={200: StrategyExecutionLogListSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def execution_logs(self, request, pk=None):
        """获取策略的执行日志（支持分页）"""
        strategy = self.get_object()
        queryset = strategy.execution_logs.all().order_by('-execution_time')

        # 分页参数
        offset = int(request.query_params.get('offset', 0))
        limit = int(request.query_params.get('limit', 20))

        # 应用分页
        logs = queryset[offset:offset + limit]
        total = queryset.count()

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
        try:
            rule = strategy.position_management_rule
        except PositionManagementRuleModel.DoesNotExist:
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
        try:
            rule = strategy.position_management_rule
        except PositionManagementRuleModel.DoesNotExist:
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
# Position Management Rule ViewSet
# ========================================================================

class PositionManagementRuleViewSet(viewsets.ModelViewSet):
    """仓位管理规则 CRUD + 评估 API"""

    queryset = PositionManagementRuleModel._default_manager.select_related('strategy')
    serializer_class = PositionManagementRuleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['name', 'strategy__name']
    ordering_fields = ['updated_at', 'created_at']
    ordering = ['-updated_at']

    @extend_schema(
        summary="评估仓位管理规则",
        description="按规则ID计算买卖价、止盈止损与仓位建议",
        request=PositionManagementEvaluateInputSerializer,
        responses={200: PositionManagementEvaluateResultSerializer}
    )
    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        rule = self.get_object()
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
# Rule Condition ViewSet
# ========================================================================

class RuleConditionViewSet(viewsets.ModelViewSet):
    """规则条件 CRUD API"""

    queryset = RuleConditionModel._default_manager.all()
    serializer_class = RuleConditionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'rule_type', 'is_enabled']
    search_fields = ['rule_name']
    ordering_fields = ['priority', 'created_at']
    ordering = ['-priority', '-created_at']

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'list':
            return RuleConditionListSerializer
        return RuleConditionSerializer

    @extend_schema(
        summary="启用规则",
        description="启用指定的规则条件",
        responses={200: RuleConditionSerializer}
    )
    @action(detail=True, methods=['post'])
    def enable(self, request, pk=None):
        """启用规则"""
        rule = self.get_object()
        rule.is_enabled = True
        rule.save()
        serializer = self.get_serializer(rule)
        return Response(serializer.data)

    @extend_schema(
        summary="停用规则",
        description="停用指定的规则条件",
        responses={200: RuleConditionSerializer}
    )
    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        """停用规则"""
        rule = self.get_object()
        rule.is_enabled = False
        rule.save()
        serializer = self.get_serializer(rule)
        return Response(serializer.data)


# ========================================================================
# Script Config ViewSet
# ========================================================================

class ScriptConfigViewSet(viewsets.ModelViewSet):
    """脚本配置 CRUD API"""

    queryset = ScriptConfigModel._default_manager.all()
    serializer_class = ScriptConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['strategy__name']


# ========================================================================
# AI Strategy Config ViewSet
# ========================================================================

class AIStrategyConfigViewSet(viewsets.ModelViewSet):
    """AI策略配置 CRUD API"""

    queryset = AIStrategyConfigModel._default_manager.all()
    serializer_class = AIStrategyConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'approval_mode', 'ai_provider']
    search_fields = ['strategy__name']


# ========================================================================
# Portfolio Strategy Assignment ViewSet
# ========================================================================

class PortfolioStrategyAssignmentViewSet(viewsets.ModelViewSet):
    """投资组合策略关联 CRUD API"""

    queryset = PortfolioStrategyAssignmentModel._default_manager.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['portfolio', 'strategy', 'is_active']
    search_fields = ['portfolio__account_name', 'strategy__name']
    ordering_fields = ['assigned_at', 'created_at']
    ordering = ['-assigned_at']

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

        assignments = self.queryset.filter(portfolio_id=portfolio_id)
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
        assignment.is_active = True
        assignment.save()
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
        assignment.is_active = False
        assignment.save()
        serializer = self.get_serializer(assignment)
        return Response(serializer.data)


# ========================================================================
# Strategy Execution Log ViewSet
# ========================================================================

class StrategyExecutionLogViewSet(viewsets.ReadOnlyModelViewSet):
    """策略执行日志 API（只读）"""

    queryset = StrategyExecutionLogModel._default_manager.all()
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['strategy', 'portfolio', 'is_success']
    ordering_fields = ['execution_time', 'execution_duration_ms']
    ordering = ['-execution_time']

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'list':
            return StrategyExecutionLogListSerializer
        return StrategyExecutionLogSerializer

    @extend_schema(
        summary="获取策略的执行日志",
        description="获取指定策略的执行日志",
        parameters=[
            OpenApiParameter(
                name='strategy_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='策略ID'
            )
        ],
        responses={200: StrategyExecutionLogListSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def by_strategy(self, request):
        """获取策略的执行日志"""
        strategy_id = request.query_params.get('strategy_id')
        if not strategy_id:
            return Response(
                {'detail': '必须提供 strategy_id 参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logs = self.queryset.filter(strategy_id=strategy_id)[:100]
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="获取投资组合的执行日志",
        description="获取指定投资组合的执行日志",
        parameters=[
            OpenApiParameter(
                name='portfolio_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='投资组合ID'
            )
        ],
        responses={200: StrategyExecutionLogListSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def by_portfolio(self, request):
        """获取投资组合的执行日志"""
        portfolio_id = request.query_params.get('portfolio_id')
        if not portfolio_id:
            return Response(
                {'detail': '必须提供 portfolio_id 参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logs = self.queryset.filter(portfolio_id=portfolio_id)[:100]
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)


# ========================================================================
# Django HTML Views (Frontend Pages)
# ========================================================================

@login_required
@login_required
def strategy_list(request):
    """策略列表页面"""
    # 获取当前用户的策略
    user_profile = request.user.account_profile
    strategies = StrategyModel._default_manager.filter(created_by=user_profile).annotate(
        rule_count=Count('rules'),
        execution_count=Count('execution_logs'),
        portfolio_count=Count('portfolio_assignments')
    ).order_by('-created_at')

    # 计算统计数据
    stats = {
        'total': strategies.count(),
        'active': strategies.filter(is_active=True).count(),
        'inactive': strategies.filter(is_active=False).count(),
        'by_type': {
            'rule_based': strategies.filter(strategy_type='rule_based').count(),
            'script_based': strategies.filter(strategy_type='script_based').count(),
            'hybrid': strategies.filter(strategy_type='hybrid').count(),
            'ai_driven': strategies.filter(strategy_type='ai_driven').count(),
        }
    }

    # 为每个策略添加规则摘要
    for strategy in strategies:
        rules = strategy.rules.filter(is_enabled=True)[:3]
        strategy.rule_summary = rules

    return render(request, 'strategy/list.html', {
        'strategies': strategies,
        'stats': stats
    })


@login_required
def strategy_create(request):
    """创建策略页面"""
    if request.method == 'POST':
        try:
            strategy_serializer = _build_strategy_serializer(request)
            rules_payload = _parse_rules_payload(request.POST.get('rules_data'))
            script_code_payload = _parse_script_payload(request.POST.get('script_code'))
            script_language = (request.POST.get('script_language') or 'python').strip()

            with transaction.atomic():
                strategy = strategy_serializer.save(created_by=request.user.account_profile)
                _replace_rule_conditions(strategy, rules_payload)
                _save_script_config(strategy, script_code_payload, script_language)

            return JsonResponse({'success': True, 'id': strategy.id})
        except InvalidInputError as exc:
            return _json_error(exc.message, exc.status_code)
        except IntegrityError as exc:
            logger.warning('Strategy create failed due to integrity error: %s', exc)
            duplicate_error = DuplicateResourceError('同名策略版本或脚本配置已存在')
            return _json_error(duplicate_error.message, duplicate_error.status_code)
        except drf_serializers.ValidationError as exc:
            return _json_error(_format_validation_detail(exc.detail))
        except Exception:
            logger.exception('Unexpected error while creating strategy')
            return _json_error('创建策略失败，请稍后重试', status.HTTP_500_INTERNAL_SERVER_ERROR)

    return render(request, 'strategy/create.html')


@login_required
def strategy_detail(request, strategy_id):
    """策略详情页面"""
    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)
    rules = strategy.rules.all().order_by('-priority', '-created_at')
    execution_logs = strategy.execution_logs.all()[:20]

    return render(request, 'strategy/detail.html', {
        'strategy': strategy,
        'rules': rules,
        'execution_logs': execution_logs
    })


@login_required
def strategy_edit(request, strategy_id):
    """编辑策略页面"""
    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    if request.method == 'POST':
        try:
            strategy_serializer = _build_strategy_serializer(request, existing_strategy=strategy)
            rules_payload = _parse_rules_payload(
                request.POST.get('rules_data'),
                preserve_existing=True,
            )
            script_code_payload = _parse_script_payload(
                request.POST.get('script_code'),
                preserve_existing=True,
            )
            script_language = (request.POST.get('script_language') or 'python').strip()

            with transaction.atomic():
                strategy = strategy_serializer.save()
                _replace_rule_conditions(strategy, rules_payload)
                _save_script_config(strategy, script_code_payload, script_language)

            return JsonResponse({'success': True, 'id': strategy.id})
        except InvalidInputError as exc:
            return _json_error(exc.message, exc.status_code)
        except IntegrityError as exc:
            logger.warning('Strategy edit failed due to integrity error: %s', exc)
            duplicate_error = DuplicateResourceError('策略保存失败，存在重复版本或脚本配置冲突')
            return _json_error(duplicate_error.message, duplicate_error.status_code)
        except drf_serializers.ValidationError as exc:
            return _json_error(_format_validation_detail(exc.detail))
        except Exception:
            logger.exception('Unexpected error while editing strategy %s', strategy_id)
            return _json_error('保存策略失败，请稍后重试', status.HTTP_500_INTERNAL_SERVER_ERROR)

    # GET 请求 - 渲染编辑页面
    return render(request, 'strategy/edit.html', {'strategy': strategy})


@login_required
def strategy_toggle_status(request, strategy_id):
    """切换策略状态"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)
    action = request.POST.get('action')

    if action == 'activate':
        strategy.is_active = True
    elif action == 'deactivate':
        strategy.is_active = False
    else:
        return JsonResponse({'success': False, 'error': '无效的操作'})

    strategy.save()
    return JsonResponse({'success': True})


@login_required
def strategy_execute(request, strategy_id):
    """
    立即执行策略

    支持两种模式:
    1. 单个投资组合执行 (portfolio_id 参数)
    2. 所有绑定投资组合执行 (无参数)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    import json

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    try:
        # 解析请求参数
        data = json.loads(request.body) if request.body else {}
        portfolio_id = data.get('portfolio_id')

        # 初始化策略执行引擎
        from apps.strategy.application.strategy_executor import StrategyExecutor
        from apps.strategy.infrastructure.providers import (
            DjangoAssetPoolProvider,
            DjangoMacroDataProvider,
            DjangoPortfolioDataProvider,
            DjangoRegimeProvider,
            DjangoSignalProvider,
        )
        from apps.strategy.infrastructure.repositories import (
            DjangoStrategyExecutionLogRepository,
            DjangoStrategyRepository,
        )

        # 创建提供者实例
        strategy_repository = DjangoStrategyRepository()
        execution_log_repository = DjangoStrategyExecutionLogRepository()
        macro_provider = DjangoMacroDataProvider()
        regime_provider = DjangoRegimeProvider()
        asset_pool_provider = DjangoAssetPoolProvider()
        signal_provider = DjangoSignalProvider()
        portfolio_provider = DjangoPortfolioDataProvider()

        # 创建策略执行引擎
        executor = StrategyExecutor(
            strategy_repository=strategy_repository,
            execution_log_repository=execution_log_repository,
            macro_provider=macro_provider,
            regime_provider=regime_provider,
            asset_pool_provider=asset_pool_provider,
            signal_provider=signal_provider,
            portfolio_provider=portfolio_provider,
            script_security_mode='relaxed'
        )

        # 执行策略
        results = []
        total_signals = 0
        failed_rules = []
        execution_ids = []

        if portfolio_id:
            # 单个投资组合执行
            result = executor.execute_strategy(strategy_id, portfolio_id)
            results.append(result)
            total_signals += len(result.signals)
            execution_ids.append(result.execution_time.isoformat())

            # 收集失败的规则（从上下文中推断）
            if not result.is_success:
                failed_rules.append({
                    'portfolio_id': portfolio_id,
                    'error': result.error_message
                })

        else:
            # 执行所有绑定的投资组合
            from apps.strategy.infrastructure.models import PortfolioStrategyAssignmentModel
            assignments = PortfolioStrategyAssignmentModel.objects.filter(
                strategy=strategy,
                is_active=True
            ).select_related('portfolio').all()

            for assignment in assignments:
                portfolio = assignment.portfolio
                result = executor.execute_strategy(strategy_id, portfolio.id)
                results.append(result)
                total_signals += len(result.signals)
                execution_ids.append(result.execution_time.isoformat())

                if not result.is_success:
                    failed_rules.append({
                        'portfolio_id': portfolio.id,
                        'portfolio_name': portfolio.account_name,
                        'error': result.error_message
                    })

        # 计算总执行时长
        duration_ms = sum(r.execution_duration_ms for r in results) if results else 0

        # 构建响应
        return JsonResponse({
            'success': all(r.is_success for r in results) if results else True,
            'execution_id': execution_ids[0] if len(execution_ids) == 1 else execution_ids,
            'generated_signals': total_signals,
            'failed_rules': failed_rules,
            'duration_ms': duration_ms,
            'executed_portfolios': len(results),
            'message': f'策略执行完成，生成 {total_signals} 个信号'
        })

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Strategy execution failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'execution_id': None,
            'generated_signals': 0,
            'failed_rules': [{'error': str(e)}],
            'duration_ms': 0
        })


@login_required
def execution_evaluate(request):
    """执行评估 API：返回 decision/sizing/risk 的静态评估结果，不提交真实订单。"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'}, status=405)

    import json

    try:
        payload = json.loads(request.body.decode('utf-8') if request.body else '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '无效 JSON'}, status=400)

    input_serializer = ExecutionEvaluateInputSerializer(data=payload)
    if not input_serializer.is_valid():
        return JsonResponse(
            {'success': False, 'errors': input_serializer.errors},
            status=400
        )

    data = input_serializer.validated_data

    decision_engine = DecisionPolicyEngine(
        signal_threshold=getattr(settings, 'DECISION_SIGNAL_THRESHOLD', 0.6),
        confidence_threshold=getattr(settings, 'DECISION_CONFIDENCE_THRESHOLD', 0.7),
        regime_alignment_required=getattr(settings, 'DECISION_REGIME_ALIGNMENT_REQUIRED', True),
        max_daily_loss_pct=getattr(settings, 'RISK_MAX_DAILY_LOSS_PCT', 5.0),
        max_daily_trades=getattr(settings, 'RISK_MAX_DAILY_TRADES', 10),
    )
    sizing_engine = SizingEngine(
        default_method=getattr(settings, 'SIZING_DEFAULT_METHOD', 'fixed_fraction'),
        risk_per_trade_pct=getattr(settings, 'SIZING_RISK_PER_TRADE_PCT', 1.0),
        max_position_pct=getattr(settings, 'SIZING_MAX_POSITION_PCT', 20.0),
        min_qty=getattr(settings, 'SIZING_MIN_QTY', 1),
    )
    risk_gate = PreTradeRiskGate(
        max_single_position_pct=getattr(settings, 'RISK_MAX_SINGLE_POSITION_PCT', 20.0),
        max_daily_trades=getattr(settings, 'RISK_MAX_DAILY_TRADES', 10),
        max_daily_loss_pct=getattr(settings, 'RISK_MAX_DAILY_LOSS_PCT', 5.0),
        min_volume=getattr(settings, 'RISK_MIN_VOLUME', 100000),
    )

    signal_direction = data.get('signal_direction') or ('bullish' if data['side'] == 'buy' else 'bearish')
    current_price = data.get('current_price') or 100.0

    decision_action, reason_codes, reason_text, valid_until_seconds = decision_engine.evaluate(
        signal_strength=data['signal_strength'],
        signal_direction=signal_direction,
        signal_confidence=data['signal_confidence'],
        regime=data.get('target_regime') or 'Unknown',
        regime_confidence=0.8,
        daily_pnl_pct=data['daily_pnl_pct'],
        daily_trade_count=data['daily_trade_count'],
        volatility_z=data.get('volatility_z'),
        target_regime=data.get('target_regime'),
    )

    target_notional, qty, expected_risk_pct, sizing_method, sizing_explain = sizing_engine.calculate(
        method=data.get('sizing_method') or getattr(settings, 'SIZING_DEFAULT_METHOD', 'fixed_fraction'),
        account_equity=data['account_equity'],
        current_price=current_price,
        stop_loss_price=data.get('stop_loss_price'),
        atr=data.get('atr'),
        current_position_value=data['current_position_value'],
    )

    passed, violations, warnings, _ = risk_gate.check(
        symbol=data['symbol'],
        side=data['side'],
        qty=qty,
        price=current_price,
        account_equity=data['account_equity'],
        current_position_value=data['current_position_value'],
        daily_trade_count=data['daily_trade_count'],
        daily_pnl_pct=data['daily_pnl_pct'],
        avg_volume=data.get('avg_volume'),
    )

    risk_snapshot = {
        'daily_trade_count': data['daily_trade_count'],
        'daily_pnl_pct': data['daily_pnl_pct'],
        'violations': violations,
        'warnings': warnings,
    }

    output = {
        'decision_action': decision_action,
        'decision_reasons': reason_codes,
        'decision_text': reason_text,
        'decision_confidence': data['signal_confidence'],
        'valid_until_seconds': valid_until_seconds,
        'target_notional': target_notional,
        'qty': qty,
        'expected_risk_pct': expected_risk_pct,
        'sizing_method': sizing_method,
        'sizing_explain': sizing_explain,
        'risk_snapshot': risk_snapshot,
        'can_execute': decision_action == 'allow' and passed,
        'requires_confirmation': decision_action == 'watch',
    }
    output_serializer = ExecutionEvaluateOutputSerializer(data=output)
    output_serializer.is_valid(raise_exception=True)
    return JsonResponse({'success': True, 'data': output_serializer.validated_data})


@login_required
def bind_strategy(request):
    """绑定策略到投资组合"""
    if request.method != 'POST':
        return _json_error('只支持 POST 请求', status.HTTP_405_METHOD_NOT_ALLOWED)

    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')
        strategy_id = data.get('strategy_id')
    except json.JSONDecodeError:
        return _json_error('无效 JSON', status.HTTP_400_BAD_REQUEST)

    try:
        if not portfolio_id or not strategy_id:
            raise InvalidInputError('缺少必要参数')

        strategy = get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by=request.user.account_profile,
        )

        with transaction.atomic():
            portfolio = SimulatedAccountModel._default_manager.select_for_update().filter(
                id=portfolio_id,
                user=request.user,
            ).first()
            if portfolio is None:
                return _json_error('账户不存在或无权限访问', status.HTTP_404_NOT_FOUND)

            assignments = PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio.id
            )
            assignments.filter(is_active=True).exclude(strategy=strategy).update(is_active=False)

            assignment, created = assignments.get_or_create(
                portfolio_id=portfolio.id,
                strategy=strategy,
                defaults={
                    'assigned_by': request.user.account_profile,
                    'is_active': True,
                }
            )
            if not created and (not assignment.is_active or assignment.assigned_by_id != request.user.account_profile.id):
                assignment.is_active = True
                assignment.assigned_by = request.user.account_profile
                assignment.save(update_fields=['is_active', 'assigned_by', 'updated_at'])

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

    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')
    except json.JSONDecodeError:
        return _json_error('无效 JSON', status.HTTP_400_BAD_REQUEST)

    try:
        if not portfolio_id:
            raise InvalidInputError('缺少必要参数')

        with transaction.atomic():
            portfolio = SimulatedAccountModel._default_manager.select_for_update().filter(
                id=portfolio_id,
                user=request.user,
            ).first()
            if portfolio is None:
                return _json_error('账户不存在或无权限访问', status.HTTP_404_NOT_FOUND)

            PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio.id,
                is_active=True,
            ).update(is_active=False)

        return JsonResponse({'success': True, 'message': '策略已解绑'})

    except InvalidInputError as exc:
        return _json_error(exc.message, exc.status_code)
    except Exception:
        logger.exception('Unexpected error while unbinding strategy')
        return _json_error('策略解绑失败，请稍后重试', status.HTTP_500_INTERNAL_SERVER_ERROR)


@login_required
def test_script(request):
    """测试脚本执行（沙箱环境）"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    import json
    import time

    from apps.strategy.application.script_engine import (
        ScriptAPI,
        ScriptExecutionEnvironment,
        SecurityMode,
    )

    try:
        data = json.loads(request.body)
        script_code = data.get('script_code', '')

        if not script_code or not script_code.strip():
            return JsonResponse({'success': False, 'error': '脚本代码不能为空'})

        # 创建模拟的 API 提供者
        class MockMacroProvider:
            def get_indicator(self, code):
                mock_data = {
                    'CN_PMI_MANUFACTURING': 50.8,
                    'CN_CPI_YOY': 2.1,
                    'CN_PPI_YOY': -2.8,
                }
                return mock_data.get(code)

            def get_all_indicators(self):
                return {
                    'CN_PMI_MANUFACTURING': 50.8,
                    'CN_CPI_YOY': 2.1,
                    'CN_PPI_YOY': -2.8,
                }

        class MockRegimeProvider:
            def get_current_regime(self):
                return {
                    'dominant_regime': 'HG',
                    'confidence': 0.75,
                    'growth_momentum_z': 1.2,
                    'inflation_momentum_z': 0.8,
                }

        class MockAssetPoolProvider:
            def get_investable_assets(self, min_score=60, limit=50):
                return []

        class MockSignalProvider:
            def get_valid_signals(self):
                return []

        class MockPortfolioProvider:
            def get_positions(self, portfolio_id):
                return []

            def get_cash(self, portfolio_id):
                return 100000.0

        # 创建脚本 API
        script_api = ScriptAPI(
            macro_provider=MockMacroProvider(),
            regime_provider=MockRegimeProvider(),
            asset_pool_provider=MockAssetPoolProvider(),
            signal_provider=MockSignalProvider(),
            portfolio_provider=MockPortfolioProvider(),
            portfolio_id=1
        )

        # 创建沙箱执行环境
        env = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED)

        # 记录开始时间
        start_time = time.time()

        # 执行脚本
        try:
            signals = env.execute(
                script_code=script_code,
                script_api=script_api,
                script_name='<test>'
            )

            execution_time = int((time.time() - start_time) * 1000)

            return JsonResponse({
                'success': True,
                'execution_time': execution_time,
                'signals_count': len(signals),
                'signals': signals,
                'output': f'脚本执行成功，生成 {len(signals)} 个信号'
            })

        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'脚本执行错误: {str(e)}'
            })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '无效的 JSON 数据'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def test_strategy(request, strategy_id):
    """测试策略执行（模拟数据）"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    import json
    import time

    from apps.strategy.application.strategy_executor import StrategyExecutor

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')
        test_date = data.get('test_date')

        if not portfolio_id:
            return JsonResponse({'success': False, 'error': '缺少 portfolio_id 参数'})

        # 模拟策略执行（使用模拟数据）
        start_time = time.time()

        # 测试模式不再注入任何模拟证券代码；仅返回真实执行结果或空列表。
        mock_signals = []

        if strategy.strategy_type in ['rule_based', 'hybrid']:
            mock_signals = []

        elif strategy.strategy_type in ['script_based', 'hybrid']:
            # 脚本驱动策略：模拟脚本执行结果
            try:
                from apps.strategy.application.script_engine import (
                    ScriptAPI,
                    ScriptExecutionEnvironment,
                    SecurityMode,
                )

                # 创建模拟 API 提供者
                class MockMacroProvider:
                    def get_indicator(self, code):
                        mock_data = {
                            'CN_PMI_MANUFACTURING': 50.8,
                            'CN_CPI_YOY': 2.1,
                        }
                        return mock_data.get(code)

                class MockRegimeProvider:
                    def get_current_regime(self):
                        return {'dominant_regime': 'HG'}

                class MockAssetPoolProvider:
                    def get_investable_assets(self, min_score=60, limit=50):
                        return []

                class MockSignalProvider:
                    def get_valid_signals(self):
                        return []

                class MockPortfolioProvider:
                    def get_positions(self, portfolio_id):
                        return []
                    def get_cash(self, portfolio_id):
                        return 100000.0

                # 如果有脚本配置，执行脚本
                if strategy.script_config:
                    script_api = ScriptAPI(
                        macro_provider=MockMacroProvider(),
                        regime_provider=MockRegimeProvider(),
                        asset_pool_provider=MockAssetPoolProvider(),
                        signal_provider=MockSignalProvider(),
                        portfolio_provider=MockPortfolioProvider(),
                        portfolio_id=portfolio_id
                    )
                    env = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED)
                    mock_signals = env.execute(
                        script_code=strategy.script_config.script_code,
                        script_api=script_api,
                        script_name=f'test_{strategy.id}'
                    )
            except Exception as e:
                mock_signals = []

        elif strategy.strategy_type == 'ai_driven':
            mock_signals = []

        execution_time = int((time.time() - start_time) * 1000)

        return JsonResponse({
            'success': True,
            'execution_time': execution_time,
            'signals_count': len(mock_signals),
            'signals': mock_signals
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


