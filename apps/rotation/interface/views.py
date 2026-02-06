"""
Rotation Module Interface Layer - Views

DRF ViewSets for the rotation module API.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from apps.rotation.infrastructure.models import (
    AssetClassModel,
    RotationConfigModel,
    RotationSignalModel,
)
from apps.rotation.infrastructure.services import RotationIntegrationService
from apps.rotation.interface.serializers import (
    AssetClassSerializer,
    RotationConfigSerializer,
    RotationSignalSerializer,
    RotationSignalRequestSerializer,
)


class AssetClassViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for AssetClass model"""
    queryset = AssetClassModel.objects.filter(is_active=True)
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
    queryset = RotationConfigModel.objects.all()
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
    queryset = RotationSignalModel.objects.all()
    serializer_class = RotationSignalSerializer
    filterset_fields = ['config', 'signal_date', 'current_regime', 'action_required']
    ordering = ['-signal_date']

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest signal for each configuration"""
        service = RotationIntegrationService()

        # Get all active configs and their latest signals
        configs = RotationConfigModel.objects.filter(is_active=True)
        signals = []

        for config in configs:
            latest_signal = self.queryset.filter(config=config).first()
            if latest_signal:
                serializer = self.get_serializer(latest_signal)
                signals.append(serializer.data)

        return Response(signals)


class RotationActionViewSet(viewsets.ViewSet):
    """ViewSet for rotation actions (not tied to a specific model)"""
    permission_classes = []  # Allow unauthenticated access for basic endpoints

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
            {'error': 'Failed to generate signal'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=False, methods=['post'], url_path='clear-cache')
    def clear_cache(self, request):
        """Clear price data cache"""
        service = RotationIntegrationService()
        service.clear_price_cache()
        return Response({'status': 'cache cleared'})
