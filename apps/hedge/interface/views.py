"""Hedge module interface views."""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.hedge.application import interface_services
from apps.hedge.interface.serializers import (
    CorrelationHistorySerializer,
    CorrelationMatrixRequestSerializer,
    HedgeAlertSerializer,
    HedgePairSerializer,
    HedgePortfolioSnapshotSerializer,
)


class HedgePairViewSet(viewsets.ModelViewSet):
    """ViewSet for HedgePair model"""
    serializer_class = HedgePairSerializer
    filterset_fields = ['is_active', 'hedge_method']
    search_fields = ['name', 'long_asset', 'hedge_asset']
    ordering = ['-is_active', 'name']

    def get_queryset(self):
        """Return the hedge pair queryset."""
        return interface_services.get_hedge_pair_queryset()

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate this hedge pair"""
        pair = self.get_object()
        response = interface_services.activate_hedge_pair(pair_id=pair.id)
        if not response.success:
            return Response({'error': response.message}, status=status.HTTP_404_NOT_FOUND)
        return Response({'status': 'activated'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate this hedge pair"""
        pair = self.get_object()
        response = interface_services.deactivate_hedge_pair(pair_id=pair.id)
        if not response.success:
            return Response({'error': response.message}, status=status.HTTP_404_NOT_FOUND)
        return Response({'status': 'deactivated'})

    @action(detail=True, methods=['get', 'post'])
    def check_effectiveness(self, request, pk=None):
        """Check hedge effectiveness for this pair"""
        pair = self.get_object()
        result = interface_services.get_hedge_effectiveness_payload(pair_name=pair.name)

        if result is None:
            return Response(
                {'error': 'Unable to calculate effectiveness'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(result)

    @action(detail=False, methods=['post'])
    def correlation_matrix(self, request):
        """Get correlation matrix for specified assets"""
        serializer = CorrelationMatrixRequestSerializer(data=request.data)
        if serializer.is_valid():
            asset_codes = serializer.validated_data.get('asset_codes', [])
            window_days = serializer.validated_data.get('window_days', 60)
            return Response(
                interface_services.get_correlation_matrix_payload(
                    asset_codes=asset_codes,
                    window_days=window_days,
                )
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def all_effectiveness(self, request):
        """Get effectiveness for all active hedge pairs"""
        return Response(interface_services.get_all_effectiveness_payload())


class CorrelationHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for CorrelationHistory model"""
    serializer_class = CorrelationHistorySerializer
    filterset_fields = ['asset1', 'asset2', 'calc_date', 'window_days']
    ordering = ['-calc_date']

    def get_queryset(self):
        """Return the correlation history queryset."""
        return interface_services.get_correlation_history_queryset()

    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """Calculate correlation for a pair of assets"""
        asset1 = request.data.get('asset1')
        asset2 = request.data.get('asset2')
        window_days = request.data.get('window_days', 60)

        if not asset1 or not asset2:
            return Response(
                {'error': 'asset1 and asset2 are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        metric = interface_services.get_correlation_metric_payload(
            asset1=asset1,
            asset2=asset2,
            window_days=window_days,
        )

        if metric is None:
            return Response(
                {'error': 'Unable to calculate correlation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(metric)


class HedgePortfolioSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for HedgePortfolioSnapshot model"""
    serializer_class = HedgePortfolioSnapshotSerializer
    filterset_fields = ['pair', 'trade_date', 'rebalance_needed']
    ordering = ['-trade_date']

    def get_queryset(self):
        """Return the hedge snapshot queryset."""
        return interface_services.get_hedge_snapshot_queryset()

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest snapshot for each hedge pair"""
        return Response(interface_services.get_latest_snapshots_payload())

    @action(detail=False, methods=['post'])
    def update_all(self, request):
        """Update all hedge portfolios"""
        return Response(interface_services.update_all_portfolios_payload())


class HedgeAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for HedgeAlert model"""
    serializer_class = HedgeAlertSerializer
    filterset_fields = ['pair_name', 'alert_date', 'alert_type', 'severity', 'is_resolved']
    ordering = ['-alert_date', '-action_priority']

    def get_queryset(self):
        """Return the hedge alert queryset."""
        return interface_services.get_hedge_alert_queryset()

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark alert as resolved"""
        response = interface_services.resolve_hedge_alert(alert_id=pk)

        if not response.success:
            return Response(
                {'error': response.message},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'status': 'resolved',
            'alert_id': pk,
        })

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get all active alerts"""
        days = request.query_params.get('days', 7)
        try:
            days = int(days)
        except ValueError:
            days = 7

        return Response(interface_services.get_recent_alerts_payload(days=days))

    @action(detail=False, methods=['post'])
    def monitor(self, request):
        """Run hedge pair monitoring and generate alerts"""
        return Response(interface_services.monitor_hedge_pairs_payload())


class HedgeActionViewSet(viewsets.ViewSet):
    """ViewSet for hedge-related actions"""

    def list(self, request):
        """List available hedge actions"""
        return Response({
            'actions': [
                {'endpoint': '/hedge/actions/calculate-correlation/', 'method': 'POST', 'description': 'Calculate correlation between two assets'},
                {'endpoint': '/hedge/actions/check-hedge-ratio/', 'method': 'POST', 'description': 'Calculate hedge ratio for a pair'},
                {'endpoint': '/hedge/actions/get-correlation-matrix/', 'method': 'POST', 'description': 'Get correlation matrix for multiple assets'},
            ]
        })

    @action(detail=False, methods=['post'])
    def calculate_correlation(self, request):
        """Calculate correlation between two assets"""
        asset1 = request.data.get('asset1')
        asset2 = request.data.get('asset2')
        window_days = request.data.get('window_days', 60)

        if not asset1 or not asset2:
            return Response(
                {'error': 'asset1 and asset2 are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        metric = interface_services.get_correlation_metric_payload(
            asset1=asset1,
            asset2=asset2,
            window_days=window_days,
        )

        if metric is None:
            return Response(
                {'error': 'Unable to calculate correlation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(metric)

    @action(detail=False, methods=['post'])
    def check_hedge_ratio(self, request):
        """Calculate hedge ratio for a pair"""
        pair_name = request.data.get('pair_name')

        if not pair_name:
            return Response(
                {'error': 'pair_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = interface_services.get_hedge_ratio_payload(pair_name=pair_name)

        if result is None:
            return Response(
                {'error': f'Hedge pair not found: {pair_name}'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(result)

    @action(detail=False, methods=['post'])
    def get_correlation_matrix(self, request):
        """Get correlation matrix for multiple assets"""
        asset_codes = request.data.get('asset_codes', [])
        window_days = request.data.get('window_days', 60)

        if not asset_codes:
            return Response(
                {'error': 'asset_codes is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            interface_services.get_correlation_matrix_payload(
                asset_codes=asset_codes,
                window_days=window_days,
            )
        )


# ============================================================================
# Page Views (for HTML rendering)
# ============================================================================

@ensure_csrf_cookie
def hedge_pairs_view(request):
    """
    Hedge pairs configuration page.
    Uses UseCase to access data through Application layer.
    """
    # Get filter parameters
    is_active_filter = request.GET.get('is_active', '')
    hedge_method_filter = request.GET.get('hedge_method', '')
    search = request.GET.get('search', '')

    # Parse is_active filter
    is_active = None
    if is_active_filter:
        is_active = (is_active_filter == 'true')

    # Parse hedge_method filter
    hedge_method = hedge_method_filter if hedge_method_filter else None

    # Parse search filter
    search_term = search if search else None

    return render(
        request,
        'hedge/pairs.html',
        interface_services.get_hedge_pairs_page_context(
            is_active=is_active,
            hedge_method=hedge_method,
            search=search_term,
            filter_is_active=is_active_filter,
            filter_hedge_method=hedge_method_filter,
            filter_search=search,
        ),
    )


@ensure_csrf_cookie
def hedge_snapshots_view(request):
    """
    Hedge snapshots status page.
    Uses UseCase to access data through Application layer.
    """
    # Get filter parameters
    pair_name_filter = request.GET.get('pair_name', '')
    rebalance_filter = request.GET.get('rebalance_needed', '')

    # Parse filters
    pair_name = pair_name_filter if pair_name_filter else None
    rebalance_needed = None
    if rebalance_filter:
        rebalance_needed = (rebalance_filter == 'true')

    return render(
        request,
        'hedge/snapshots.html',
        interface_services.get_hedge_snapshots_page_context(
            pair_name=pair_name,
            rebalance_needed=rebalance_needed,
            filter_pair_name=pair_name_filter,
            filter_rebalance_needed=rebalance_filter,
        ),
    )


@ensure_csrf_cookie
def hedge_alerts_view(request):
    """
    Hedge alerts page.
    Uses UseCase to access data through Application layer.
    """
    # Get filter parameters
    pair_name_filter = request.GET.get('pair_name', '')
    severity_filter = request.GET.get('severity', '')
    alert_type_filter = request.GET.get('alert_type', '')
    is_resolved_filter = request.GET.get('is_resolved', '')

    # Parse filters
    pair_name = pair_name_filter if pair_name_filter else None
    severity = severity_filter if severity_filter else None
    alert_type = alert_type_filter if alert_type_filter else None
    is_resolved = None
    if is_resolved_filter:
        is_resolved = (is_resolved_filter == 'true')

    return render(
        request,
        'hedge/alerts.html',
        interface_services.get_hedge_alerts_page_context(
            pair_name=pair_name,
            severity=severity,
            alert_type=alert_type,
            is_resolved=is_resolved,
            filter_pair_name=pair_name_filter,
            filter_severity=severity_filter,
            filter_alert_type=alert_type_filter,
            filter_is_resolved=is_resolved_filter,
        ),
    )


@require_http_methods(["POST"])
def activate_pair_view(request, pair_id):
    """
    Activate a hedge pair.
    Uses UseCase to access data through Application layer.
    """
    response = interface_services.activate_hedge_pair(pair_id=pair_id)

    if response.success:
        return JsonResponse({
            'success': True,
            'message': response.message
        })
    else:
        return JsonResponse({
            'success': False,
            'error': response.message
        }, status=404)


@require_http_methods(["POST"])
def deactivate_pair_view(request, pair_id):
    """
    Deactivate a hedge pair.
    Uses UseCase to access data through Application layer.
    """
    response = interface_services.deactivate_hedge_pair(pair_id=pair_id)

    if response.success:
        return JsonResponse({
            'success': True,
            'message': response.message
        })
    else:
        return JsonResponse({
            'success': False,
            'error': response.message
        }, status=404)


@require_http_methods(["POST"])
def update_portfolios_view(request):
    """Update all hedge portfolios"""
    payload = interface_services.update_all_portfolios_payload()
    return JsonResponse({
        'success': True,
        'updated': payload['updated'],
        'portfolios': payload['portfolios'],
    })


@require_http_methods(["POST"])
def run_monitoring_view(request):
    """Run hedge pair monitoring"""
    payload = interface_services.monitor_hedge_pairs_payload()

    return JsonResponse({
        'success': True,
        'generated_alerts': payload['generated_alerts'],
    })


@require_http_methods(["POST"])
def resolve_alert_view(request, alert_id):
    """
    Mark an alert as resolved.
    Uses UseCase to access data through Application layer.
    """
    response = interface_services.resolve_hedge_alert(alert_id=alert_id)

    if response.success:
        return JsonResponse({
            'success': True,
            'message': response.message
        })
    else:
        return JsonResponse({
            'success': False,
            'error': response.message
        }, status=404)
