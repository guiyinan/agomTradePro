"""
Hedge Module Interface Layer - Views

DRF ViewSets and page views for the hedge module.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from datetime import date, datetime

# Infrastructure models - kept for DRF ViewSets (read-only access)
from apps.hedge.infrastructure.models import (
    HedgePairModel,
    CorrelationHistoryModel,
    HedgePortfolioHoldingModel,
    HedgeAlertModel,
)
from apps.hedge.infrastructure.services import HedgeIntegrationService
from apps.hedge.infrastructure.repositories import (
    HedgePairRepository,
    CorrelationHistoryRepository,
    HedgePortfolioRepository,
    HedgeAlertRepository,
)
from apps.hedge.interface.serializers import (
    HedgePairSerializer,
    CorrelationHistorySerializer,
    HedgePortfolioHoldingSerializer,
    HedgeAlertSerializer,
    HedgeEffectivenessRequestSerializer,
)

# Application layer UseCases - for page views
from apps.hedge.application.use_cases import (
    GetHedgePairsForViewUseCase,
    GetHedgeHoldingsForViewUseCase,
    GetHedgeAlertsForViewUseCase,
    ActivateHedgePairUseCase,
    DeactivateHedgePairUseCase,
    ResolveHedgeAlertUseCase,
    HedgePairsViewRequest,
    HedgeHoldingsViewRequest,
    HedgeAlertsViewRequest,
    ActivateHedgePairRequest,
    DeactivateHedgePairRequest,
    ResolveHedgeAlertRequest,
)


class HedgePairViewSet(viewsets.ModelViewSet):
    """ViewSet for HedgePair model"""
    queryset = HedgePairModel._default_manager.all()
    serializer_class = HedgePairSerializer
    filterset_fields = ['is_active', 'hedge_method']
    search_fields = ['name', 'long_asset', 'hedge_asset']
    ordering = ['-is_active', 'name']

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate this hedge pair"""
        pair = self.get_object()
        pair.is_active = True
        pair.save()
        return Response({'status': 'activated'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate this hedge pair"""
        pair = self.get_object()
        pair.is_active = False
        pair.save()
        return Response({'status': 'deactivated'})

    @action(detail=True, methods=['get', 'post'])
    def check_effectiveness(self, request, pk=None):
        """Check hedge effectiveness for this pair"""
        pair = self.get_object()
        service = HedgeIntegrationService()

        result = service.check_hedge_effectiveness(pair.name)

        if result is None:
            return Response(
                {'error': 'Unable to calculate effectiveness'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(result)

    @action(detail=False, methods=['post'])
    def correlation_matrix(self, request):
        """Get correlation matrix for specified assets"""
        serializer = HedgeEffectivenessRequestSerializer(data=request.data)
        if serializer.is_valid():
            asset_codes = serializer.validated_data.get('asset_codes', [])
            window_days = serializer.validated_data.get('window_days', 60)

            service = HedgeIntegrationService()
            matrix = service.get_correlation_matrix(asset_codes, window_days=window_days)

            return Response({
                'asset_codes': asset_codes,
                'window_days': window_days,
                'matrix': matrix,
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def all_effectiveness(self, request):
        """Get effectiveness for all active hedge pairs"""
        service = HedgeIntegrationService()
        results = service.get_all_effectiveness()

        return Response({
            'count': len(results),
            'results': results,
        })


class CorrelationHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for CorrelationHistory model"""
    queryset = CorrelationHistoryModel._default_manager.all()
    serializer_class = CorrelationHistorySerializer
    filterset_fields = ['asset1', 'asset2', 'calc_date', 'window_days']
    ordering = ['-calc_date']

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

        service = HedgeIntegrationService()
        metric = service.calculate_correlation(asset1, asset2, window_days=window_days)

        if metric is None:
            return Response(
                {'error': 'Unable to calculate correlation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'asset1': metric.asset1,
            'asset2': metric.asset2,
            'calc_date': metric.calc_date.isoformat(),
            'window_days': metric.window_days,
            'correlation': round(metric.correlation, 4),
            'beta': round(metric.beta, 4) if metric.beta else None,
            'correlation_trend': metric.correlation_trend,
            'alert': metric.alert,
        })


class HedgePortfolioHoldingViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for HedgePortfolioHolding model"""
    queryset = HedgePortfolioHoldingModel._default_manager.all()
    serializer_class = HedgePortfolioHoldingSerializer
    filterset_fields = ['pair', 'trade_date', 'rebalance_needed']
    ordering = ['-trade_date']

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest holding for each hedge pair"""
        service = HedgeIntegrationService()
        pairs = service.get_all_pairs(active_only=True)

        holdings = []
        for pair in pairs:
            latest = service.get_hedge_portfolio(pair.name)
            if latest:
                holdings.append({
                    'pair_name': latest.pair_name,
                    'trade_date': latest.trade_date.isoformat(),
                    'long_weight': round(latest.long_weight * 100, 2),
                    'hedge_weight': round(latest.hedge_weight * 100, 2),
                    'hedge_ratio': round(latest.hedge_ratio, 3),
                    'current_correlation': round(latest.current_correlation, 3),
                    'hedge_effectiveness': round(latest.hedge_effectiveness * 100, 1),
                    'rebalance_needed': latest.rebalance_needed,
                    'rebalance_reason': latest.rebalance_reason,
                })

        return Response({
            'count': len(holdings),
            'results': holdings,
        })

    @action(detail=False, methods=['post'])
    def update_all(self, request):
        """Update all hedge portfolios"""
        service = HedgeIntegrationService()
        portfolios = service.update_all_portfolios()

        return Response({
            'updated': len(portfolios),
            'portfolios': [
                {
                    'pair_name': p.pair_name,
                    'trade_date': p.trade_date.isoformat(),
                    'hedge_ratio': round(p.hedge_ratio, 3),
                    'rebalance_needed': p.rebalance_needed,
                }
                for p in portfolios
            ]
        })


class HedgeAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for HedgeAlert model"""
    queryset = HedgeAlertModel._default_manager.filter(is_resolved=False)
    serializer_class = HedgeAlertSerializer
    filterset_fields = ['pair_name', 'alert_date', 'alert_type', 'severity', 'is_resolved']
    ordering = ['-alert_date', '-action_priority']

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark alert as resolved"""
        service = HedgeIntegrationService()
        alert = service.resolve_alert(pk)

        if alert is None:
            return Response(
                {'error': 'Alert not found'},
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

        service = HedgeIntegrationService()
        alerts = service.get_recent_alerts(days=days)

        return Response({
            'count': len(alerts),
            'results': [
                {
                    'pair_name': a.pair_name,
                    'alert_date': a.alert_date.isoformat(),
                    'alert_type': a.alert_type.value,
                    'severity': a.severity,
                    'message': a.message,
                    'action_required': a.action_required,
                    'action_priority': a.action_priority,
                }
                for a in alerts
            ]
        })

    @action(detail=False, methods=['post'])
    def monitor(self, request):
        """Run hedge pair monitoring and generate alerts"""
        service = HedgeIntegrationService()
        alerts = service.monitor_hedge_pairs()

        return Response({
            'generated_alerts': len(alerts),
            'alerts': [
                {
                    'pair_name': a.pair_name,
                    'alert_date': a.alert_date.isoformat(),
                    'alert_type': a.alert_type.value,
                    'severity': a.severity,
                    'message': a.message,
                }
                for a in alerts
            ]
        })


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

        service = HedgeIntegrationService()
        metric = service.calculate_correlation(asset1, asset2, window_days=window_days)

        if metric is None:
            return Response(
                {'error': 'Unable to calculate correlation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'asset1': metric.asset1,
            'asset2': metric.asset2,
            'calc_date': metric.calc_date.isoformat(),
            'window_days': metric.window_days,
            'correlation': round(metric.correlation, 4),
            'covariance': round(metric.covariance, 4) if metric.covariance else None,
            'beta': round(metric.beta, 4) if metric.beta else None,
            'correlation_trend': metric.correlation_trend,
            'correlation_ma': round(metric.correlation_ma, 4) if metric.correlation_ma else None,
            'alert': metric.alert,
            'alert_type': metric.alert_type.value if metric.alert_type else None,
        })

    @action(detail=False, methods=['post'])
    def check_hedge_ratio(self, request):
        """Calculate hedge ratio for a pair"""
        pair_name = request.data.get('pair_name')

        if not pair_name:
            return Response(
                {'error': 'pair_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = HedgeIntegrationService()
        result = service.calculate_hedge_ratio(pair_name)

        if result is None:
            return Response(
                {'error': f'Hedge pair not found: {pair_name}'},
                status=status.HTTP_404_NOT_FOUND
            )

        hedge_ratio, details = result

        return Response({
            'pair_name': pair_name,
            'hedge_ratio': round(hedge_ratio, 4),
            'method': details.get('method', 'unknown'),
            'details': details,
        })

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

        service = HedgeIntegrationService()
        matrix = service.get_correlation_matrix(asset_codes, window_days=window_days)

        return Response({
            'asset_codes': asset_codes,
            'window_days': window_days,
            'matrix': matrix,
        })


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

    # Create request DTO
    usecase_request = HedgePairsViewRequest(
        is_active=is_active,
        hedge_method=hedge_method,
        search=search_term,
    )

    # Instantiate repositories
    pair_repo = HedgePairRepository()
    correlation_repo = CorrelationHistoryRepository()
    holding_repo = HedgePortfolioRepository()

    # Execute UseCase
    use_case = GetHedgePairsForViewUseCase(pair_repo, correlation_repo, holding_repo)
    response = use_case.execute(usecase_request)

    # Hedge method choices (for filter dropdown)
    hedge_methods = [
        ('beta', 'Beta对冲'),
        ('min_variance', '最小方差'),
        ('equal_risk', '等风险贡献'),
        ('dollar_neutral', '货币中性'),
        ('fixed_ratio', '固定比例'),
    ]

    context = {
        'pairs': response.pairs,
        'stats': response.stats,
        'hedge_methods': hedge_methods,
        'filter_is_active': is_active_filter,
        'filter_hedge_method': hedge_method_filter,
        'filter_search': search,
    }

    return render(request, 'hedge/pairs.html', context)


@ensure_csrf_cookie
def hedge_holdings_view(request):
    """
    Hedge holdings status page.
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

    # Create request DTO
    usecase_request = HedgeHoldingsViewRequest(
        pair_name=pair_name,
        rebalance_needed=rebalance_needed,
        limit=50,
    )

    # Instantiate repositories
    holding_repo = HedgePortfolioRepository()
    pair_repo = HedgePairRepository()

    # Execute UseCase
    use_case = GetHedgeHoldingsForViewUseCase(holding_repo, pair_repo)
    response = use_case.execute(usecase_request)

    context = {
        'holdings': response.holdings,
        'stats': response.stats,
        'pair_names': response.pair_names,
        'filter_pair_name': pair_name_filter,
        'filter_rebalance_needed': rebalance_filter,
    }

    return render(request, 'hedge/holdings.html', context)


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

    # Create request DTO
    usecase_request = HedgeAlertsViewRequest(
        pair_name=pair_name,
        severity=severity,
        alert_type=alert_type,
        is_resolved=is_resolved,
        limit=100,
    )

    # Instantiate repositories
    alert_repo = HedgeAlertRepository()
    pair_repo = HedgePairRepository()

    # Execute UseCase
    use_case = GetHedgeAlertsForViewUseCase(alert_repo, pair_repo)
    response = use_case.execute(usecase_request)

    context = {
        'alerts': response.alerts,
        'stats': response.stats,
        'alert_types': response.alert_types,
        'severity_choices': response.severity_choices,
        'pair_names': response.pair_names,
        'filter_pair_name': pair_name_filter,
        'filter_severity': severity_filter,
        'filter_alert_type': alert_type_filter,
        'filter_is_resolved': is_resolved_filter,
    }

    return render(request, 'hedge/alerts.html', context)


@require_http_methods(["POST"])
def activate_pair_view(request, pair_id):
    """
    Activate a hedge pair.
    Uses UseCase to access data through Application layer.
    """
    usecase_request = ActivateHedgePairRequest(pair_id=pair_id)
    pair_repo = HedgePairRepository()
    use_case = ActivateHedgePairUseCase(pair_repo)
    response = use_case.execute(usecase_request)

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
    usecase_request = DeactivateHedgePairRequest(pair_id=pair_id)
    pair_repo = HedgePairRepository()
    use_case = DeactivateHedgePairUseCase(pair_repo)
    response = use_case.execute(usecase_request)

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
    service = HedgeIntegrationService()
    portfolios = service.update_all_portfolios()

    return JsonResponse({
        'success': True,
        'updated': len(portfolios),
        'portfolios': [
            {
                'pair_name': p.pair_name,
                'trade_date': p.trade_date.isoformat(),
                'hedge_ratio': round(p.hedge_ratio, 3),
            }
            for p in portfolios
        ]
    })


@require_http_methods(["POST"])
def run_monitoring_view(request):
    """Run hedge pair monitoring"""
    service = HedgeIntegrationService()
    alerts = service.monitor_hedge_pairs()

    return JsonResponse({
        'success': True,
        'generated_alerts': len(alerts),
    })


@require_http_methods(["POST"])
def resolve_alert_view(request, alert_id):
    """
    Mark an alert as resolved.
    Uses UseCase to access data through Application layer.
    """
    usecase_request = ResolveHedgeAlertRequest(alert_id=alert_id)
    alert_repo = HedgeAlertRepository()
    use_case = ResolveHedgeAlertUseCase(alert_repo)
    response = use_case.execute(usecase_request)

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
