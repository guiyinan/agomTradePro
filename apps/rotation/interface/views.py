"""
Rotation Module Interface Layer - Views

DRF ViewSets and page views for the rotation module.
"""

from datetime import date, datetime
import json

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone

from apps.rotation.infrastructure.models import (
    AssetClassModel,
    RotationConfigModel,
    RotationSignalModel,
    RotationTemplateModel,
    PortfolioRotationConfigModel,
)
from apps.rotation.infrastructure.services import RotationIntegrationService
from apps.rotation.interface.serializers import (
    AssetClassSerializer,
    RotationConfigSerializer,
    RotationSignalSerializer,
    RotationSignalRequestSerializer,
    RotationTemplateSerializer,
    PortfolioRotationConfigSerializer,
)
from apps.rotation.application.use_cases import (
    GetAssetsForViewUseCase,
    GetRotationConfigsForViewUseCase,
    GetRotationSignalsForViewUseCase,
)
from apps.rotation.application.dtos import (
    AssetsViewRequest,
    RotationConfigsViewRequest,
    RotationSignalsViewRequest,
)


class AssetClassViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for AssetClass model"""
    queryset = AssetClassModel._default_manager.filter(is_active=True)
    serializer_class = AssetClassSerializer
    filterset_fields = ['category', 'is_active']
    search_fields = ['code', 'name', 'description']
    ordering_fields = ['category', 'code']

    @action(detail=False, methods=['get'])
    def with_prices(self, request):
        """Get all assets with current price information"""
        service = RotationIntegrationService()
        assets = service.get_all_assets()
        return Response(assets)

    @action(detail=True, methods=['get'])
    def detail(self, request, pk=None):
        """Get detailed information about a specific asset"""
        service = RotationIntegrationService()
        asset_code = pk
        info = service.get_asset_info(asset_code)

        if info:
            return Response(info)
        return Response(
            {'error': f'Asset not found: {asset_code}'},
            status=status.HTTP_404_NOT_FOUND
        )


class RotationConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for RotationConfig model"""
    queryset = RotationConfigModel._default_manager.all()
    serializer_class = RotationConfigSerializer
    filterset_fields = ['is_active', 'strategy_type', 'rebalance_frequency']
    search_fields = ['name', 'description']
    ordering = ['-is_active', '-created_at']

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate this configuration"""
        config = self.get_object()
        config.is_active = True
        config.save()
        return Response({'status': 'activated'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate this configuration"""
        config = self.get_object()
        config.is_active = False
        config.save()
        return Response({'status': 'deactivated'})

    @action(detail=True, methods=['post'])
    def generate_signal(self, request, pk=None):
        """Generate rotation signal for this configuration"""
        config = self.get_object()
        service = RotationIntegrationService()

        signal = service.generate_rotation_signal(config.name)

        if signal:
            return Response(signal)
        return Response(
            {'error': 'Failed to generate signal'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class RotationSignalViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for RotationSignal model"""
    queryset = RotationSignalModel._default_manager.all()
    serializer_class = RotationSignalSerializer
    filterset_fields = ['config', 'signal_date', 'current_regime', 'action_required']
    ordering = ['-signal_date']

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest signal for each configuration"""
        service = RotationIntegrationService()

        # Get all active configs and their latest signals
        configs = RotationConfigModel._default_manager.filter(is_active=True)
        signals = []

        for config in configs:
            latest_signal = self.queryset.filter(config=config).first()
            if latest_signal:
                serializer = self.get_serializer(latest_signal)
                signals.append(serializer.data)

        return Response(signals)


class RotationActionViewSet(viewsets.ViewSet):
    """ViewSet for rotation actions (not tied to a specific model)"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Get available rotation actions"""
        return Response({
            'actions': {
                'recommendation': 'GET /rotation/api/recommendation/ - Get rotation recommendation',
                'compare': 'POST /rotation/api/compare/ - Compare assets',
                'correlation': 'POST /rotation/api/correlation/ - Get correlation matrix',
                'generate_signal': 'POST /rotation/api/generate_signal/ - Generate signal for config',
            }
        })

    @action(detail=False, methods=['get'], url_path='recommendation')
    def recommendation(self, request):
        """Get rotation recommendation based on strategy type"""
        strategy_type = request.query_params.get('strategy', 'momentum')

        service = RotationIntegrationService()
        result = service.get_rotation_recommendation(strategy_type)

        return Response(result)

    @action(detail=False, methods=['post'], url_path='compare')
    def compare_assets(self, request):
        """Compare multiple assets"""
        asset_codes = request.data.get('asset_codes', [])
        lookback_days = request.data.get('lookback_days', 60)

        if not asset_codes:
            return Response(
                {'error': 'asset_codes is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = RotationIntegrationService()
        result = service.compare_assets(asset_codes, lookback_days)

        return Response(result)

    @action(detail=False, methods=['post'], url_path='correlation')
    def correlation_matrix(self, request):
        """Get correlation matrix for assets"""
        asset_codes = request.data.get('asset_codes', [])
        window_days = request.data.get('window_days', 60)

        if not asset_codes:
            return Response(
                {'error': 'asset_codes is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = RotationIntegrationService()
        result = service.get_correlation_matrix(asset_codes, window_days)

        return Response(result)

    @action(detail=False, methods=['post'], url_path='generate-signal')
    def generate_signal_action(self, request):
        """Generate rotation signal for a configuration"""
        config_name = request.data.get('config_name')
        signal_date = request.data.get('signal_date')

        if not config_name:
            return Response(
                {'error': 'config_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = RotationIntegrationService()
        signal = service.generate_rotation_signal(config_name, signal_date)

        if signal:
            return Response(signal)
        return Response(
            {'error': f'Rotation config not found or signal generation failed: {config_name}'},
            status=status.HTTP_404_NOT_FOUND
        )

    @action(detail=False, methods=['post'], url_path='clear-cache')
    def clear_cache(self, request):
        """Clear price data cache"""
        service = RotationIntegrationService()
        service.clear_price_cache()
        return Response({'status': 'cache cleared'})


# ============================================================================
# Page Views (for frontend templates)
# ============================================================================

def rotation_assets_view(request):
    """资产类别管理页面 - 显示所有资产类别、价格和动量信息"""
    service = RotationIntegrationService()
    use_case = GetAssetsForViewUseCase(service)

    response = use_case.execute(AssetsViewRequest())

    # Convert DTOs to dict format for template
    momentum_scores_dict = {}
    for asset_code, score_dto in response.momentum_scores.items():
        momentum_scores_dict[asset_code] = {
            'composite_score': score_dto.composite_score,
            'rank': score_dto.rank,
            'momentum_1m': score_dto.momentum_1m,
            'momentum_3m': score_dto.momentum_3m,
            'momentum_6m': score_dto.momentum_6m,
            'trend_strength': score_dto.trend_strength,
            'calc_date': score_dto.calc_date,
        }

    context = {
        'assets': response.assets,
        'categories': response.categories,
        'momentum_scores': momentum_scores_dict,
        'latest_calc_date': response.latest_calc_date,
        'current_date': date.today(),
    }

    return render(request, 'rotation/assets.html', context)


def rotation_configs_view(request):
    """轮动配置管理页面 - 显示和编辑策略配置"""
    service = RotationIntegrationService()
    use_case = GetRotationConfigsForViewUseCase(service)

    response = use_case.execute(RotationConfigsViewRequest())

    # Convert ConfigLatestSignal DTOs to dict format for template
    latest_signals_dict = {}
    for config_id, signal_dto in response.latest_signals.items():
        latest_signals_dict[config_id] = {
            'signal_date': signal_dto.signal_date,
            'current_regime': signal_dto.current_regime,
            'action_required': signal_dto.action_required,
            'target_allocation': signal_dto.target_allocation,
        }

    # Attach latest signal to each config for simple template rendering
    for config in response.configs:
        config['latest_signal'] = latest_signals_dict.get(config['id'])

    # 当前用户所有账户及其轮动配置状态
    user_accounts = []
    if request.user.is_authenticated:
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
        user_accounts = list(
            SimulatedAccountModel.objects.filter(
                user=request.user, is_active=True
            ).select_related('rotation_config').order_by('account_type', 'account_name')
        )

    context = {
        'configs': response.configs,
        'latest_signals': latest_signals_dict,
        'strategy_types': response.strategy_types,
        'frequencies': response.frequencies,
        'current_date': date.today(),
        'user_accounts': user_accounts,
        'assets': AssetClassModel.objects.filter(is_active=True).order_by('category', 'code'),
    }

    return render(request, 'rotation/configs.html', context)


def rotation_signals_view(request):
    """轮动信号页面 - 显示当前推荐和历史信号"""
    service = RotationIntegrationService()
    use_case = GetRotationSignalsForViewUseCase(service)

    # Get filter parameters from request
    request_dto = RotationSignalsViewRequest(
        config_filter=request.GET.get('config', ''),
        regime_filter=request.GET.get('regime', ''),
        action_filter=request.GET.get('action', ''),
    )

    response = use_case.execute(request_dto)

    context = {
        'signals': response.signals,
        'configs': response.configs,
        'latest_by_config': response.latest_by_config,
        'current_regime': response.current_regime,
        'filter_config': response.filter_config,
        'filter_regime': response.filter_regime,
        'filter_action': response.filter_action,
        'regime_choices': response.regime_choices,
        'action_choices': response.action_choices,
        'current_date': date.today(),
    }

    return render(request, 'rotation/signals.html', context)


def rotation_account_config_view(request):
    """账户轮动配置页面 - 每个账户独立配置风险偏好和象限配置"""
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    user_accounts = []
    if request.user.is_authenticated:
        user_accounts = list(
            SimulatedAccountModel.objects.filter(
                user=request.user, is_active=True
            ).select_related('rotation_config').order_by('account_type', 'account_name')
        )

    assets = AssetClassModel.objects.filter(is_active=True).order_by('category', 'code')
    templates = RotationTemplateModel.objects.filter(is_active=True).order_by('display_order')

    context = {
        'user_accounts': user_accounts,
        'assets': assets,
        'templates': templates,
        'current_date': date.today(),
        'risk_tolerance_choices': PortfolioRotationConfigModel.RISK_TOLERANCE_CHOICES,
    }
    return render(request, 'rotation/account_config.html', context)


@require_http_methods(["POST"])
def rotation_generate_signal_view(request):
    """生成轮动信号的 API 端点"""
    try:
        data = json.loads(request.body)
        config_name = data.get('config_name')
        signal_date_str = data.get('signal_date')

        if not config_name:
            return JsonResponse({
                'success': False,
                'error': '请指定配置名称'
            }, status=400)

        signal_date = None
        if signal_date_str:
            try:
                signal_date = datetime.strptime(signal_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        service = RotationIntegrationService()
        signal = service.generate_rotation_signal(config_name, signal_date)

        if signal:
            return JsonResponse({
                'success': True,
                'signal': signal
            })
        else:
            return JsonResponse({
                'success': False,
                'error': f'生成信号失败，请检查配置名称和数据可用性: {config_name}'
            }, status=404)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# Regime List API (dynamic, sourced from regime module — no hardcoding)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_regime_list(request):
    """
    返回系统支持的宏观象限名称列表。

    前端编辑器用此接口动态渲染 Tab，不在 JS 中硬编码象限名称。
    象限定义来自 regime 模块的 RegimeProbability 实体。

    GET /api/rotation/regimes/
    """
    # Regime 名称由 regime 模块 RegimeProbabilities.distribution 定义
    from apps.regime.domain.entities import RegimeProbabilities
    dummy = RegimeProbabilities(
        growth_reflation=0.25,
        growth_disinflation=0.25,
        stagnation_reflation=0.25,
        stagnation_disinflation=0.25,
        confidence=1.0,
        data_freshness_score=1.0,
        predictive_power_score=1.0,
        consistency_score=1.0,
    )
    regimes = [
        {'key': regime_name, 'label': regime_name}
        for regime_name in dummy.distribution.keys()
    ]
    return Response(regimes)


# ============================================================================
# RotationTemplateViewSet — read-only presets from DB
# ============================================================================

class RotationTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    预设模板 API。

    模板数据存储在数据库，由 init_rotation 命令初始化，不硬编码。
    前端编辑器加载此接口填充模板下拉，用户选择后应用到象限编辑器。

    GET /api/rotation/templates/
    GET /api/rotation/templates/{id}/
    """
    queryset = RotationTemplateModel.objects.filter(is_active=True)
    serializer_class = RotationTemplateSerializer
    permission_classes = [IsAuthenticated]


# ============================================================================
# PortfolioRotationConfigViewSet — per-account rotation config CRUD
# ============================================================================

class PortfolioRotationConfigViewSet(viewsets.ModelViewSet):
    """
    账户级轮动配置 API。

    每个投资组合账户独立一份配置，支持完整 CRUD。
    MCP 可直接调用此接口读写任意账户的风险偏好和象限配置。

    GET    /api/rotation/account-configs/                      — 当前用户所有账户配置
    POST   /api/rotation/account-configs/                      — 新建账户配置
    GET    /api/rotation/account-configs/{id}/                 — 查看单条
    PUT    /api/rotation/account-configs/{id}/                 — 全量更新
    PATCH  /api/rotation/account-configs/{id}/                 — 部分更新
    DELETE /api/rotation/account-configs/{id}/                 — 删除
    POST   /api/rotation/account-configs/{id}/apply-template/  — 应用预设模板
    GET    /api/rotation/account-configs/by-account/{id}/      — 按账户 ID 查询（MCP 友好）
    """
    serializer_class = PortfolioRotationConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PortfolioRotationConfigModel.objects.filter(
            account__user=self.request.user
        ).select_related('account', 'base_config')

    def perform_create(self, serializer: PortfolioRotationConfigSerializer) -> None:
        account = serializer.validated_data['account']
        if account.user != self.request.user:
            raise PermissionDenied("无权配置他人账户")
        serializer.save()

    @action(detail=True, methods=['post'], url_path='apply-template')
    def apply_template(self, request, pk=None):
        """
        将预设模板的 regime_allocations 应用到此账户配置。

        POST /api/rotation/account-configs/{id}/apply-template/
        Body: {"template_key": "conservative"}
        """
        config = self.get_object()
        template_key = request.data.get('template_key')

        if not template_key:
            return Response({'error': 'template_key 不能为空'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            template = RotationTemplateModel.objects.get(key=template_key, is_active=True)
        except RotationTemplateModel.DoesNotExist:
            return Response(
                {'error': f'模板 "{template_key}" 不存在'},
                status=status.HTTP_404_NOT_FOUND
            )

        config.regime_allocations = template.regime_allocations
        # 模板 key 与 risk_tolerance 一致（conservative/moderate/aggressive）
        if template_key in ('conservative', 'moderate', 'aggressive'):
            config.risk_tolerance = template_key
        config.save()

        return Response(PortfolioRotationConfigSerializer(config).data)

    @action(detail=False, methods=['get'], url_path='by-account/(?P<account_id>[^/.]+)')
    def by_account(self, request, account_id=None):
        """
        按账户 ID 查询该账户的轮动配置（MCP 友好接口）。

        GET /api/rotation/account-configs/by-account/{account_id}/
        若该账户尚未创建配置，返回 404。
        """
        try:
            config = PortfolioRotationConfigModel.objects.get(
                account_id=account_id,
                account__user=request.user,
            )
        except PortfolioRotationConfigModel.DoesNotExist:
            return Response({'detail': '该账户尚未配置轮动'}, status=status.HTTP_404_NOT_FOUND)

        return Response(PortfolioRotationConfigSerializer(config).data)
