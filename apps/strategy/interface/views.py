"""
Django REST Framework Views for Strategy System

Interface层:
- 提供REST API接口
- 使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Count, Q, Sum

from apps.strategy.infrastructure.models import (
    StrategyModel,
    RuleConditionModel,
    ScriptConfigModel,
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    StrategyExecutionLogModel
)
from apps.strategy.interface.serializers import (
    StrategySerializer,
    StrategyDetailSerializer,
    RuleConditionSerializer,
    RuleConditionListSerializer,
    ScriptConfigSerializer,
    AIStrategyConfigSerializer,
    PortfolioStrategyAssignmentSerializer,
    PortfolioStrategyAssignmentDetailSerializer,
    StrategyExecutionLogSerializer,
    StrategyExecutionLogListSerializer
)


# ========================================================================
# Strategy ViewSet
# ========================================================================

class StrategyViewSet(viewsets.ModelViewSet):
    """策略 CRUD API"""

    queryset = StrategyModel.objects.all()
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
        description="获取指定策略的执行日志",
        responses={200: StrategyExecutionLogListSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def execution_logs(self, request, pk=None):
        """获取策略的执行日志"""
        strategy = self.get_object()
        logs = strategy.execution_logs.all()[:100]  # 限制返回 100 条
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)


# ========================================================================
# Rule Condition ViewSet
# ========================================================================

class RuleConditionViewSet(viewsets.ModelViewSet):
    """规则条件 CRUD API"""

    queryset = RuleConditionModel.objects.all()
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

    queryset = ScriptConfigModel.objects.all()
    serializer_class = ScriptConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['strategy__name']


# ========================================================================
# AI Strategy Config ViewSet
# ========================================================================

class AIStrategyConfigViewSet(viewsets.ModelViewSet):
    """AI策略配置 CRUD API"""

    queryset = AIStrategyConfigModel.objects.all()
    serializer_class = AIStrategyConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['strategy', 'approval_mode', 'ai_provider']
    search_fields = ['strategy__name']


# ========================================================================
# Portfolio Strategy Assignment ViewSet
# ========================================================================

class PortfolioStrategyAssignmentViewSet(viewsets.ModelViewSet):
    """投资组合策略关联 CRUD API"""

    queryset = PortfolioStrategyAssignmentModel.objects.all()
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
        serializer.save(assigned_by=request.user.account_profile)

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

    queryset = StrategyExecutionLogModel.objects.all()
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
def strategy_list(request):
    """策略列表页面"""
    # 获取当前用户的策略
    user_profile = request.user.account_profile
    strategies = StrategyModel.objects.filter(created_by=user_profile).annotate(
        rule_count=Count('rules'),
        execution_count=Count('execution_logs'),
        portfolio_count=Count('portfolios')
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
        import json

        name = request.POST.get('name')
        strategy_type = request.POST.get('strategy_type')
        description = request.POST.get('description', '')
        max_position_pct = request.POST.get('max_position_pct', 20)
        max_total_position_pct = request.POST.get('max_total_position_pct', 95)
        stop_loss_pct = request.POST.get('stop_loss_pct')
        version = request.POST.get('version', 1)
        rules_data = request.POST.get('rules_data', '[]')

        if not name or not strategy_type:
            return JsonResponse({'success': False, 'error': '策略名称和类型不能为空'})

        try:
            # 创建策略
            strategy = StrategyModel.objects.create(
                name=name,
                strategy_type=strategy_type,
                description=description,
                max_position_pct=float(max_position_pct),
                max_total_position_pct=float(max_total_position_pct),
                stop_loss_pct=float(stop_loss_pct) if stop_loss_pct else None,
                version=int(version),
                is_active=False,
                created_by=request.user.account_profile
            )

            # 创建规则条件
            try:
                rules = json.loads(rules_data)
                for rule_data in rules:
                    if rule_data.get('rule_name'):  # 只创建有名称的规则
                        RuleConditionModel.objects.create(
                            strategy=strategy,
                            rule_name=rule_data['rule_name'],
                            rule_type=rule_data.get('rule_type', 'macro'),
                            condition_json=rule_data.get('condition_json', {}),
                            action=rule_data.get('action', 'BUY'),
                            weight=rule_data.get('weight', 0.1),
                            target_assets=rule_data.get('target_assets', []),
                            priority=rule_data.get('priority', 10),
                            is_enabled=rule_data.get('is_enabled', True)
                        )
            except json.JSONDecodeError:
                pass  # 如果规则数据格式错误，忽略

            return JsonResponse({'success': True, 'id': strategy.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

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
    # TODO: 实现编辑功能
    return render(request, 'strategy/create.html', {'strategy': strategy})


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
    """立即执行策略"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    # TODO: 调用策略执行引擎
    # from apps.strategy.application.strategy_executor import StrategyExecutor
    # executor = StrategyExecutor()
    # results = []
    # for portfolio in strategy.portfolios.filter(is_active=True):
    #     result = executor.execute_strategy(strategy.id, portfolio.id)
    #     results.append(result)

    return JsonResponse({'success': True, 'signals_count': 0})