"""
Django REST Framework Views for Strategy System

Interface层:
- 提供REST API接口
- 使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""
import json
import logging

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy.application.interface_services import (
    bind_strategy_assignment,
    build_strategy_executor,
    build_strategy_list_context,
    delete_strategy_script_config,
    get_ai_strategy_config_queryset,
    get_assignment_queryset,
    get_execution_log_queryset,
    get_position_management_rule_queryset,
    get_rule_condition_queryset,
    get_script_config_queryset,
    get_strategy_ai_config,
    get_strategy_execution_logs_page,
    get_strategy_position_rule,
    get_strategy_queryset,
    get_strategy_queryset_for_owner,
    get_strategy_script_config,
    list_active_ai_providers_for_user,
    list_active_assignments_for_strategy,
    list_active_chain_configs,
    list_active_prompt_templates,
    list_assignments_by_portfolio,
    list_execution_logs_by_portfolio,
    list_execution_logs_by_strategy,
    replace_strategy_rule_conditions,
    set_assignment_active,
    set_rule_enabled,
    set_strategy_active,
    unbind_strategy_assignments,
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.domain.services import (
    DecisionPolicyEngine,
    PreTradeRiskGate,
    SizingEngine,
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

AIStrategyConfigModel = django_apps.get_model("strategy", "AIStrategyConfigModel")
PortfolioStrategyAssignmentModel = django_apps.get_model("strategy", "PortfolioStrategyAssignmentModel")
PositionManagementRuleModel = django_apps.get_model("strategy", "PositionManagementRuleModel")
RuleConditionModel = django_apps.get_model("strategy", "RuleConditionModel")
ScriptConfigModel = django_apps.get_model("strategy", "ScriptConfigModel")
StrategyExecutionLogModel = django_apps.get_model("strategy", "StrategyExecutionLogModel")
StrategyModel = django_apps.get_model("strategy", "StrategyModel")

_UNSET = object()
DEFAULT_SCRIPT_ALLOWED_MODULES = ['math', 'datetime', 'statistics', 'pandas', 'numpy']
DEFAULT_SCRIPT_SANDBOX_CONFIG = {'mode': 'relaxed'}
VALID_STRATEGY_TYPES = {choice[0] for choice in StrategyModel._meta.get_field('strategy_type').choices}
VALID_SCRIPT_LANGUAGES = {choice[0] for choice in ScriptConfigModel._meta.get_field('script_language').choices}
VALID_AI_APPROVAL_MODES = {choice[0] for choice in AIStrategyConfigModel._meta.get_field('approval_mode').choices}
DEFAULT_POSITION_RULE_VARIABLES = [
    {"name": "current_price", "type": "number", "required": True},
    {"name": "support_price", "type": "number", "required": True},
    {"name": "resistance_price", "type": "number", "required": True},
    {"name": "structure_low", "type": "number", "required": True},
    {"name": "atr", "type": "number", "required": True},
    {"name": "account_equity", "type": "number", "required": True},
    {"name": "risk_per_trade_pct", "type": "number", "required": True},
    {"name": "entry_buffer_pct", "type": "number", "required": False},
]
DEFAULT_POSITION_RULE_VALUES = {
    "name": "ATR风险仓位规则",
    "description": "基于支撑位、阻力位和ATR计算买卖价格、止损止盈与下单仓位。",
    "is_active": True,
    "price_precision": 2,
    "variables_schema": DEFAULT_POSITION_RULE_VARIABLES,
    "buy_condition_expr": "current_price <= support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
    "sell_condition_expr": "current_price >= resistance_price",
    "buy_price_expr": "support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
    "sell_price_expr": "resistance_price",
    "stop_loss_expr": "min(structure_low, buy_price - 2 * atr)",
    "take_profit_expr": "buy_price + 2 * abs(buy_price - stop_loss_price)",
    "position_size_expr": "(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
    "metadata": {"template": "atr_risk"},
}


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


def _parse_json_form_field(raw_value: str | None, field_label: str, default_value):
    """Parse JSON textarea values submitted from strategy forms."""
    if raw_value is None or not raw_value.strip():
        return json.loads(json.dumps(default_value))
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f'{field_label} 必须是有效 JSON') from exc


def _parse_optional_int(raw_value: str | None, field_label: str) -> int | None:
    """Parse optional foreign-key ids from HTML form fields."""
    if raw_value is None or raw_value == '':
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f'{field_label} 选择无效') from exc


def _build_ai_config_form(ai_config=None) -> dict:
    """Build template-friendly AI config defaults."""
    return {
        'prompt_template_id': ai_config.prompt_template_id if ai_config else None,
        'chain_config_id': ai_config.chain_config_id if ai_config else None,
        'ai_provider_id': ai_config.ai_provider_id if ai_config else None,
        'temperature': ai_config.temperature if ai_config else 0.7,
        'max_tokens': ai_config.max_tokens if ai_config else 2000,
        'approval_mode': ai_config.approval_mode if ai_config else 'conditional',
        'confidence_threshold': ai_config.confidence_threshold if ai_config else 0.8,
    }


def _build_position_rule_form(position_rule=None) -> dict:
    """Build template-friendly position rule defaults."""
    if position_rule is None:
        values = json.loads(json.dumps(DEFAULT_POSITION_RULE_VALUES, ensure_ascii=False))
    else:
        values = {
            'name': position_rule.name,
            'description': position_rule.description,
            'is_active': position_rule.is_active,
            'price_precision': position_rule.price_precision,
            'variables_schema': position_rule.variables_schema,
            'buy_condition_expr': position_rule.buy_condition_expr,
            'sell_condition_expr': position_rule.sell_condition_expr,
            'buy_price_expr': position_rule.buy_price_expr,
            'sell_price_expr': position_rule.sell_price_expr,
            'stop_loss_expr': position_rule.stop_loss_expr,
            'take_profit_expr': position_rule.take_profit_expr,
            'position_size_expr': position_rule.position_size_expr,
            'metadata': position_rule.metadata,
        }

    values['variables_schema_json'] = json.dumps(
        values.get('variables_schema') or [],
        ensure_ascii=False,
        indent=2,
    )
    values['metadata_json'] = json.dumps(
        values.get('metadata') or {},
        ensure_ascii=False,
        indent=2,
    )
    return values


def _build_strategy_form_context(request, strategy: StrategyModel | None = None) -> dict:
    """Build shared context for strategy create/edit/detail pages."""
    ai_config = get_strategy_ai_config(strategy.id) if strategy is not None else None
    position_rule = get_strategy_position_rule(strategy.id) if strategy is not None else None
    context = {
        'prompt_templates': list_active_prompt_templates(),
        'chain_configs': list_active_chain_configs(),
        'ai_providers': list_active_ai_providers_for_user(request.user.id),
        'ai_config': ai_config,
        'ai_config_form': _build_ai_config_form(ai_config),
        'position_rule': position_rule,
        'position_rule_form': _build_position_rule_form(position_rule),
    }
    if strategy is not None:
        context['strategy'] = strategy
    return context


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

    replace_strategy_rule_conditions(strategy.id, validated_rules)


def _save_script_config(
    strategy: StrategyModel,
    script_code_payload,
    script_language: str,
) -> None:
    """Create, update, or delete script config based on submitted form data."""
    if script_code_payload is _UNSET:
        return

    existing_config = get_strategy_script_config(strategy.id)
    script_code = (script_code_payload or '').strip()

    if not script_code:
        if existing_config is not None:
            delete_strategy_script_config(strategy.id)
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


def _save_ai_config(strategy: StrategyModel, post_data) -> None:
    """Create or update AI strategy config for AI-driven strategies."""
    if strategy.strategy_type != 'ai_driven':
        return

    approval_mode = (post_data.get('ai_approval_mode') or 'conditional').strip()
    if approval_mode not in VALID_AI_APPROVAL_MODES:
        raise InvalidInputError('AI 审核模式无效')

    existing_config = get_strategy_ai_config(strategy.id)
    serializer = AIStrategyConfigSerializer(
        existing_config,
        data={
            'strategy': strategy.id,
            'prompt_template': _parse_optional_int(post_data.get('ai_prompt_template'), 'Prompt 模板'),
            'chain_config': _parse_optional_int(post_data.get('ai_chain_config'), 'Chain 配置'),
            'ai_provider': _parse_optional_int(post_data.get('ai_provider'), 'AI 服务商'),
            'temperature': post_data.get('ai_temperature') or 0.7,
            'max_tokens': post_data.get('ai_max_tokens') or 2000,
            'approval_mode': approval_mode,
            'confidence_threshold': post_data.get('ai_confidence_threshold') or 0.8,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(f'AI 配置校验失败: {_format_validation_detail(exc.detail)}') from exc
    serializer.save()


def _save_position_rule(strategy: StrategyModel, post_data) -> None:
    """Create or update the visual position-management rule submitted by the page."""
    if 'position_rule_name' not in post_data:
        return

    rule_name = (post_data.get('position_rule_name') or '').strip()
    if not rule_name:
        return

    variables_schema = _parse_json_form_field(
        post_data.get('position_rule_variables_schema'),
        '仓位规则变量定义',
        DEFAULT_POSITION_RULE_VARIABLES,
    )
    metadata = _parse_json_form_field(
        post_data.get('position_rule_metadata'),
        '仓位规则元数据',
        {},
    )
    if not isinstance(variables_schema, list):
        raise InvalidInputError('仓位规则变量定义必须是数组 JSON')
    if not isinstance(metadata, dict):
        raise InvalidInputError('仓位规则元数据必须是对象 JSON')

    existing_rule = get_strategy_position_rule(strategy.id)
    serializer = PositionManagementRuleSerializer(
        existing_rule,
        data={
            'strategy': strategy.id,
            'name': rule_name,
            'description': post_data.get('position_rule_description', ''),
            'is_active': post_data.get('position_rule_is_active') == 'on',
            'price_precision': post_data.get('position_rule_price_precision') or 2,
            'variables_schema': variables_schema,
            'buy_condition_expr': post_data.get('position_rule_buy_condition_expr', ''),
            'sell_condition_expr': post_data.get('position_rule_sell_condition_expr', ''),
            'buy_price_expr': post_data.get('position_rule_buy_price_expr', ''),
            'sell_price_expr': post_data.get('position_rule_sell_price_expr', ''),
            'stop_loss_expr': post_data.get('position_rule_stop_loss_expr', ''),
            'take_profit_expr': post_data.get('position_rule_take_profit_expr', ''),
            'position_size_expr': post_data.get('position_rule_position_size_expr', ''),
            'metadata': metadata,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(f'仓位规则校验失败: {_format_validation_detail(exc.detail)}') from exc
    serializer.save()

# ========================================================================
# Strategy ViewSet
# ========================================================================

class StrategyViewSet(viewsets.ModelViewSet):
    """策略 CRUD API"""

    serializer_class = StrategySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'version']
    ordering = ['-created_at']

    def get_queryset(self):
        return get_strategy_queryset()

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
# Position Management Rule ViewSet
# ========================================================================

class PositionManagementRuleViewSet(viewsets.ModelViewSet):
    """仓位管理规则 CRUD + 评估 API"""

    serializer_class = PositionManagementRuleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['name', 'strategy__name']
    ordering_fields = ['updated_at', 'created_at']
    ordering = ['-updated_at']

    def get_queryset(self):
        return get_position_management_rule_queryset()

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

    serializer_class = RuleConditionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'rule_type', 'is_enabled']
    search_fields = ['rule_name']
    ordering_fields = ['priority', 'created_at']
    ordering = ['-priority', '-created_at']

    def get_queryset(self):
        return get_rule_condition_queryset()

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
        rule = set_rule_enabled(rule.id, True) or rule
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
        rule = set_rule_enabled(rule.id, False) or rule
        serializer = self.get_serializer(rule)
        return Response(serializer.data)


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
        return get_ai_strategy_config_queryset()


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


# ========================================================================
# Strategy Execution Log ViewSet
# ========================================================================

class StrategyExecutionLogViewSet(viewsets.ReadOnlyModelViewSet):
    """策略执行日志 API（只读）"""

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['strategy', 'portfolio', 'is_success']
    ordering_fields = ['execution_time', 'execution_duration_ms']
    ordering = ['-execution_time']

    def get_queryset(self):
        return get_execution_log_queryset()

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

        logs = list_execution_logs_by_strategy(strategy_id, limit=100)
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

        logs = list_execution_logs_by_portfolio(portfolio_id, limit=100)
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)


# ========================================================================
# Django HTML Views (Frontend Pages)
# ========================================================================

@login_required
@login_required
def strategy_list(request):
    """策略列表页面"""
    context = build_strategy_list_context(request.user.account_profile.id)
    return render(request, 'strategy/list.html', context)


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
                _save_ai_config(strategy, request.POST)
                _save_position_rule(strategy, request.POST)

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

    return render(request, 'strategy/create.html', _build_strategy_form_context(request))


@login_required
def strategy_detail(request, strategy_id):
    """策略详情页面"""
    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)
    rules = strategy.rules.all().order_by('-priority', '-created_at')
    execution_logs = strategy.execution_logs.all()[:20]
    context = _build_strategy_form_context(request, strategy)
    context.update({
        'rules': rules,
        'execution_logs': execution_logs,
    })

    return render(request, 'strategy/detail.html', context)


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
                _save_ai_config(strategy, request.POST)
                _save_position_rule(strategy, request.POST)

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
    return render(request, 'strategy/edit.html', _build_strategy_form_context(request, strategy))


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
        executor = build_strategy_executor()

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
            assignments = list_active_assignments_for_strategy(strategy.id)

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
            'signals_count': total_signals,
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
            'signals_count': 0,
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
        from apps.simulated_trading.application.facade import get_simulated_trading_facade

        if not get_simulated_trading_facade().user_owns_account(portfolio_id, request.user.id):
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
        from apps.simulated_trading.application.facade import get_simulated_trading_facade

        if not get_simulated_trading_facade().user_owns_account(portfolio_id, request.user.id):
            return _json_error('账户不存在或无权限访问', status.HTTP_404_NOT_FOUND)

        unbind_strategy_assignments(portfolio_id)

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

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')

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
            except Exception:
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


