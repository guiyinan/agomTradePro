"""
Rotation Module Interface Layer - Views

DRF ViewSets and page views for the rotation module.
"""

import csv
import json
from datetime import datetime

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.rotation.application import interface_services as rotation_interface_services
from apps.rotation.interface.serializers import (
    AssetClassSerializer,
    PortfolioRotationConfigSerializer,
    RotationConfigSerializer,
    RotationSignalSerializer,
    RotationTemplateSerializer,
)


class AssetClassViewSet(viewsets.ModelViewSet):
    """ViewSet for AssetClass model"""
    queryset = rotation_interface_services.get_asset_queryset()
    serializer_class = AssetClassSerializer
    filterset_fields = ['category', 'is_active']
    search_fields = ['code', 'name', 'description']
    ordering_fields = ['category', 'code']
    lookup_field = 'code'

    @action(detail=False, methods=['get'])
    def with_prices(self, request):
        """Get all assets with current price information"""
        assets = rotation_interface_services.get_all_assets_with_prices()
        return Response(assets)

    @action(detail=False, methods=['post'], url_path='import-defaults')
    def import_defaults(self, request):
        """Import or reactivate default rotation assets."""
        return Response(rotation_interface_services.import_default_assets())

    @action(detail=False, methods=['get'], url_path='export')
    def export_assets(self, request):
        """Export current rotation asset pool as JSON or CSV."""
        export_format = request.query_params.get('format', 'json').lower()
        fields, rows = rotation_interface_services.export_asset_rows()

        if export_format == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="rotation-assets.csv"'
            writer = csv.DictWriter(response, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            return response

        response = HttpResponse(
            json.dumps(rows, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8',
        )
        response['Content-Disposition'] = 'attachment; filename="rotation-assets.json"'
        return response

    @action(detail=True, methods=['get'])
    def detail(self, request, pk=None):
        """Get detailed information about a specific asset"""
        asset_code = pk
        info = rotation_interface_services.get_asset_info(asset_code)

        if info:
            return Response(info)
        return Response(
            {'error': f'Asset not found: {asset_code}'},
            status=status.HTTP_404_NOT_FOUND
        )

    def destroy(self, request, *args, **kwargs):
        """Soft delete by default; use ?hard=true for physical delete."""
        instance = self.get_object()
        if request.query_params.get('hard', '').lower() == 'true':
            return super().destroy(request, *args, **kwargs)

        if not instance.is_active:
            return Response({'status': 'already_inactive', 'code': instance.code})

        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        return Response({'status': 'soft_deleted', 'code': instance.code, 'is_active': False})


class RotationConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for RotationConfig model"""
    queryset = rotation_interface_services.get_rotation_config_queryset()
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

        signal = rotation_interface_services.generate_rotation_signal(config.name)

        if signal:
            return Response(signal)
        return Response(
            {'error': 'Failed to generate signal'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class RotationSignalViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for RotationSignal model"""
    queryset = rotation_interface_services.get_rotation_signal_queryset()
    serializer_class = RotationSignalSerializer
    filterset_fields = ['config', 'signal_date', 'current_regime', 'action_required']
    ordering = ['-signal_date']

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest signal for each configuration"""
        signals = []

        for latest_signal in rotation_interface_services.get_latest_signal_models_for_active_configs():
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

        result = rotation_interface_services.get_rotation_recommendation(strategy_type)

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

        result = rotation_interface_services.compare_assets(asset_codes, lookback_days)

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

        result = rotation_interface_services.get_correlation_matrix(asset_codes, window_days)

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

        signal = rotation_interface_services.generate_rotation_signal(config_name, signal_date)

        if signal:
            return Response(signal)
        return Response(
            {'error': f'Rotation config not found or signal generation failed: {config_name}'},
            status=status.HTTP_404_NOT_FOUND
        )

    @action(detail=False, methods=['post'], url_path='clear-cache')
    def clear_cache(self, request):
        """Clear price data cache"""
        rotation_interface_services.clear_price_cache()
        return Response({'status': 'cache cleared'})


# ============================================================================
# Page Views (for frontend templates)
# ============================================================================

def rotation_assets_view(request):
    """资产类别管理页面 - 显示所有资产类别、价格和动量信息"""
    return render(
        request,
        'rotation/assets.html',
        rotation_interface_services.build_rotation_assets_context(),
    )


def rotation_configs_view(request):
    """轮动配置管理页面 - 显示和编辑策略配置"""
    return render(
        request,
        'rotation/configs.html',
        rotation_interface_services.build_rotation_configs_context(request.user),
    )


def rotation_signals_view(request):
    """轮动信号页面 - 显示当前推荐和历史信号"""
    return render(
        request,
        'rotation/signals.html',
        rotation_interface_services.build_rotation_signals_context(
            {
                'config': request.GET.get('config', ''),
                'regime': request.GET.get('regime', ''),
                'action': request.GET.get('action', ''),
            }
        ),
    )


def rotation_account_config_view(request):
    """账户轮动配置页面 - 每个账户独立配置风险偏好和象限配置"""
    return render(
        request,
        'rotation/account_config.html',
        rotation_interface_services.build_rotation_account_config_context(request.user),
    )


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

        signal = rotation_interface_services.generate_rotation_signal(config_name, signal_date)

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
    queryset = rotation_interface_services.get_active_template_queryset()
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
        return rotation_interface_services.get_portfolio_rotation_config_queryset(
            self.request.user
        )

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

        config = rotation_interface_services.apply_template_to_portfolio_config(
            config,
            template_key,
        )
        if config is None:
            return Response(
                {'error': f'模板 "{template_key}" 不存在'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(PortfolioRotationConfigSerializer(config).data)

    @action(detail=False, methods=['get'], url_path='by-account/(?P<account_id>[^/.]+)')
    def by_account(self, request, account_id=None):
        """
        按账户 ID 查询该账户的轮动配置（MCP 友好接口）。

        GET /api/rotation/account-configs/by-account/{account_id}/
        若该账户尚未创建配置，返回 404。
        """
        config = rotation_interface_services.get_portfolio_rotation_config_by_account(
            account_id,
            request.user,
        )
        if config is None:
            return Response({'detail': '该账户尚未配置轮动'}, status=status.HTTP_404_NOT_FOUND)

        return Response(PortfolioRotationConfigSerializer(config).data)
