"""
Hedge Module Application Layer - Use Cases

Application use cases for the hedge module.
Orchestrates domain services and infrastructure adapters.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.hedge.application.dtos import (
    CorrelationMatrixRequest,
    CorrelationMatrixResponse,
    HedgeAlertResponse,
    HedgeEffectivenessRequest,
    HedgeEffectivenessResponse,
)
from apps.hedge.domain.entities import HedgeAlert, HedgePair
from apps.hedge.domain.services import (
    CorrelationMonitor,
    HedgeContext,
    HedgePortfolioService,
)


@dataclass
class HedgeUseCaseContext:
    """Context for hedge use case execution"""
    calc_date: date
    hedge_pairs: list[HedgePair]

    # Repository accessors (injected)
    get_asset_prices: Callable[[str, date, int], list[float] | None]
    get_asset_name: Callable[[str], str | None]
    get_hedge_pair: Callable[[str], HedgePair | None]


class CheckHedgeEffectivenessUseCase:
    """
    Use case: Check hedge pair effectiveness.

    Returns effectiveness metrics and recommendations.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, request: HedgeEffectivenessRequest) -> HedgeEffectivenessResponse:
        """Execute hedge effectiveness check"""
        # Get hedge pair
        pair = self.context.get_hedge_pair(request.pair_name)
        if not pair:
            raise ValueError(f"Hedge pair not found: {request.pair_name}")

        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[pair],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and check effectiveness
        service = HedgePortfolioService(domain_context)
        effectiveness = service.check_hedge_effectiveness(pair)

        return HedgeEffectivenessResponse(
            pair_name=effectiveness["pair_name"],
            correlation=effectiveness["correlation"],
            beta=effectiveness["beta"],
            hedge_ratio=effectiveness["hedge_ratio"],
            hedge_method=effectiveness["hedge_method"],
            effectiveness=effectiveness["effectiveness"],
            rating=effectiveness["rating"],
            recommendation=effectiveness["recommendation"],
        )


class GetCorrelationMatrixUseCase:
    """
    Use case: Get correlation matrix for assets.

    Returns correlation matrix for specified assets.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, request: CorrelationMatrixRequest) -> CorrelationMatrixResponse:
        """Execute correlation matrix calculation"""
        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and get matrix
        service = HedgePortfolioService(domain_context)
        matrix = service.get_correlation_matrix(
            request.asset_codes,
            request.window_days
        )

        return CorrelationMatrixResponse(
            matrix=matrix,
            calc_date=self.context.calc_date,
            window_days=request.window_days,
        )


class MonitorHedgeAlertsUseCase:
    """
    Use case: Monitor hedge pairs for alerts.

    Returns any alerts for hedge pairs.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self) -> list[HedgeAlertResponse]:
        """Execute hedge monitoring"""
        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=self.context.hedge_pairs,
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create monitor and check for alerts
        monitor = CorrelationMonitor(domain_context)
        alerts = monitor.monitor_hedge_pairs()

        return [
            HedgeAlertResponse(
                pair_name=alert.pair_name,
                alert_date=alert.alert_date,
                alert_type=alert.alert_type.value,
                severity=alert.severity,
                message=alert.message,
                action_required=alert.action_required,
                priority=alert.action_priority,
            )
            for alert in alerts
        ]


class UpdateHedgePortfolioUseCase:
    """
    Use case: Update hedge portfolio state.

    Calculates current hedge ratios and portfolio state.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, pair_name: str) -> dict | None:
        """Execute hedge portfolio update"""
        # Get hedge pair
        pair = self.context.get_hedge_pair(pair_name)
        if not pair:
            raise ValueError(f"Hedge pair not found: {pair_name}")

        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[pair],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and update portfolio
        service = HedgePortfolioService(domain_context)
        portfolio = service.update_hedge_portfolio(pair)

        if portfolio is None:
            return None

        return {
            "pair_name": portfolio.pair_name,
            "trade_date": portfolio.trade_date,
            "long_weight": portfolio.long_weight,
            "hedge_weight": portfolio.hedge_weight,
            "hedge_ratio": portfolio.hedge_ratio,
            "current_correlation": portfolio.current_correlation,
            "portfolio_beta": portfolio.portfolio_beta,
            "hedge_effectiveness": portfolio.hedge_effectiveness,
            "rebalance_needed": portfolio.rebalance_needed,
            "rebalance_reason": portfolio.rebalance_reason,
        }


# ============================================================================
# View-focused UseCases for HTML page rendering
# ============================================================================

@dataclass
class HedgePairsViewRequest:
    """Request for hedge pairs view"""
    is_active: bool | None = None
    hedge_method: str | None = None
    search: str | None = None


@dataclass
class HedgePairsViewResponse:
    """Response for hedge pairs view"""
    pairs: list[dict[str, Any]]
    stats: dict[str, int]


class GetHedgePairsForViewUseCase:
    """
    UseCase for hedge pairs page.
    Retrieves pairs with correlation and snapshot data.
    """

    def __init__(
        self,
        pair_repo,
        correlation_repo,
        snapshot_repo,
    ):
        self.pair_repo = pair_repo
        self.correlation_repo = correlation_repo
        self.snapshot_repo = snapshot_repo

    def execute(self, request: HedgePairsViewRequest) -> HedgePairsViewResponse:
        """Execute hedge pairs view query"""
        # Get pairs from repository
        pairs = self._filter_pairs(request)

        # Enrich with correlation and snapshot data
        pair_data = []
        for pair in pairs:
            pair_info = self._build_pair_info(pair)
            pair_data.append(pair_info)

        # Calculate statistics
        stats = self._calculate_stats()

        return HedgePairsViewResponse(
            pairs=pair_data,
            stats=stats,
        )

    def _filter_pairs(self, request: HedgePairsViewRequest) -> list[HedgePair]:
        """Filter pairs based on request parameters"""
        pairs = self.pair_repo.get_all(active_only=False)

        if request.is_active is not None:
            pairs = [p for p in pairs if p.is_active == request.is_active]

        if request.hedge_method:
            pairs = [p for p in pairs if p.hedge_method.value == request.hedge_method]

        if request.search:
            search_lower = request.search.lower()
            pairs = [
                p for p in pairs
                if (search_lower in p.name.lower() or
                    search_lower in p.long_asset.lower() or
                    search_lower in p.hedge_asset.lower())
            ]

        return pairs

    def _build_pair_info(self, pair: HedgePair) -> dict[str, Any]:
        """Build pair info dict with correlation and snapshot data"""
        pair_info = {
            'id': pair.id if hasattr(pair, 'id') else id(pair),
            'name': pair.name,
            'long_asset': pair.long_asset,
            'hedge_asset': pair.hedge_asset,
            'hedge_method': pair.hedge_method.value,
            'hedge_method_display': self._get_hedge_method_display(pair.hedge_method.value),
            'target_long_weight': pair.target_long_weight,
            'target_hedge_weight': pair.target_hedge_weight,
            'rebalance_trigger': pair.rebalance_trigger,
            'correlation_window': pair.correlation_window,
            'min_correlation': pair.min_correlation,
            'max_correlation': pair.max_correlation,
            'correlation_alert_threshold': pair.correlation_alert_threshold,
            'max_hedge_cost': pair.max_hedge_cost,
            'beta_target': pair.beta_target,
            'is_active': pair.is_active,
            'created_at': getattr(pair, 'created_at', None),
            'updated_at': getattr(pair, 'updated_at', None),
        }

        # Get latest correlation data
        latest_corr = self.correlation_repo.get_latest(
            pair.long_asset,
            pair.hedge_asset,
            pair.correlation_window
        )
        if latest_corr:
            pair_info['current_correlation'] = round(latest_corr.correlation, 4)
            pair_info['current_beta'] = round(latest_corr.beta, 4) if latest_corr.beta else None
            pair_info['correlation_trend'] = latest_corr.correlation_trend
            pair_info['correlation_calc_date'] = latest_corr.calc_date
        else:
            pair_info['current_correlation'] = None
            pair_info['current_beta'] = None
            pair_info['correlation_trend'] = None
            pair_info['correlation_calc_date'] = None

        # Get latest snapshot data
        # Note: This would require a method in snapshot_repo that gets by pair name
        # For now, set defaults
        pair_info['hedge_ratio'] = None
        pair_info['hedge_effectiveness'] = None
        pair_info['rebalance_needed'] = False
        pair_info['rebalance_reason'] = None

        return pair_info

    def _get_hedge_method_display(self, method: str) -> str:
        """Get display name for hedge method"""
        display_names = {
            'beta': 'Beta对冲',
            'min_variance': '最小方差',
            'equal_risk': '等风险贡献',
            'dollar_neutral': '货币中性',
            'fixed_ratio': '固定比例',
        }
        return display_names.get(method, method)

    def _calculate_stats(self) -> dict[str, int]:
        """Calculate statistics for all pairs"""
        all_pairs = self.pair_repo.get_all(active_only=False)
        active_pairs = self.pair_repo.get_all(active_only=True)

        return {
            'total': len(all_pairs),
            'active': len(active_pairs),
            'inactive': len(all_pairs) - len(active_pairs),
        }


@dataclass
class HedgeSnapshotsViewRequest:
    """Request for hedge snapshots view"""
    pair_name: str | None = None
    rebalance_needed: bool | None = None
    limit: int = 50


@dataclass
class HedgeSnapshotsViewResponse:
    """Response for hedge snapshots view"""
    snapshots: list[dict[str, Any]]
    stats: dict[str, int]
    pair_names: list[str]


class GetHedgeSnapshotsForViewUseCase:
    """
    UseCase for hedge snapshots page.
    Retrieves snapshots with filtering and statistics.
    """

    def __init__(self, snapshot_repo, pair_repo):
        self.snapshot_repo = snapshot_repo
        self.pair_repo = pair_repo

    def execute(self, request: HedgeSnapshotsViewRequest) -> HedgeSnapshotsViewResponse:
        """Execute hedge snapshots view query"""
        # Get snapshots from repository (already formatted)
        snapshots = self.snapshot_repo.get_recent_snapshots(
            pair_name=request.pair_name,
            rebalance_needed=request.rebalance_needed,
            limit=request.limit,
        )

        # Get statistics
        stats = self.snapshot_repo.get_statistics()

        # Get all pair names for filter
        pair_names = self._get_pair_names()

        return HedgeSnapshotsViewResponse(
            snapshots=snapshots,
            stats=stats,
            pair_names=pair_names,
        )

    def _get_pair_names(self) -> list[str]:
        """Get all pair names for filter dropdown"""
        pairs = self.pair_repo.get_all(active_only=False)
        return sorted([p.name for p in pairs])


@dataclass
class HedgeAlertsViewRequest:
    """Request for hedge alerts view"""
    pair_name: str | None = None
    severity: str | None = None
    alert_type: str | None = None
    is_resolved: bool | None = None
    limit: int = 100


@dataclass
class HedgeAlertsViewResponse:
    """Response for hedge alerts view"""
    alerts: list[dict[str, Any]]
    stats: dict[str, int]
    pair_names: list[str]
    alert_types: list[tuple]
    severity_choices: list[tuple]


class GetHedgeAlertsForViewUseCase:
    """
    UseCase for hedge alerts page.
    Retrieves alerts with filtering and statistics.
    """

    def __init__(self, alert_repo, pair_repo):
        self.alert_repo = alert_repo
        self.pair_repo = pair_repo

    def execute(self, request: HedgeAlertsViewRequest) -> HedgeAlertsViewResponse:
        """Execute hedge alerts view query"""
        # Get alerts from repository
        alerts = self._get_alerts(request)

        # Format alert data
        alert_data = [self._format_alert(a) for a in alerts]

        # Get statistics
        stats = self._calculate_stats()

        # Get all pair names for filter
        pair_names = self._get_pair_names()

        # Get alert type and severity choices
        alert_types = self._get_alert_type_choices()
        severity_choices = self._get_severity_choices()

        return HedgeAlertsViewResponse(
            alerts=alert_data,
            stats=stats,
            pair_names=pair_names,
            alert_types=alert_types,
            severity_choices=severity_choices,
        )

    def _get_alerts(self, request: HedgeAlertsViewRequest) -> list[HedgeAlert]:
        """Get alerts with filtering"""
        # For resolved filter
        if request.is_resolved is True:
            # Get resolved alerts - not directly supported by repo
            # Would need to extend repository
            return []
        elif request.is_resolved is False:
            alerts = self.alert_repo.get_active_alerts(pair_name=request.pair_name)
        else:
            # Get all recent alerts
            alerts = self.alert_repo.get_recent_alerts(days=365, pair_name=request.pair_name)

        # Apply additional filters
        if request.severity:
            alerts = [a for a in alerts if a.severity == request.severity]

        if request.alert_type:
            alerts = [a for a in alerts if a.alert_type.value == request.alert_type]

        return alerts[:request.limit]

    def _format_alert(self, alert: HedgeAlert) -> dict[str, Any]:
        """Format alert for display"""
        return {
            'id': alert.id if hasattr(alert, 'id') else id(alert),
            'pair_name': alert.pair_name,
            'alert_date': alert.alert_date,
            'alert_type': alert.alert_type.value,
            'alert_type_display': self._get_alert_type_display(alert.alert_type.value),
            'severity': alert.severity,
            'severity_display': self._get_severity_display(alert.severity),
            'message': alert.message,
            'current_value': round(alert.current_value, 4),
            'threshold_value': round(alert.threshold_value, 4),
            'action_required': alert.action_required,
            'action_priority': alert.action_priority,
            'is_resolved': alert.is_resolved,
            'resolved_at': alert.resolved_at,
            'created_at': getattr(alert, 'created_at', None),
        }

    def _calculate_stats(self) -> dict[str, int]:
        """Calculate statistics for alerts"""
        all_alerts = self.alert_repo.get_recent_alerts(days=365)
        active_alerts = self.alert_repo.get_active_alerts()

        critical_count = sum(1 for a in active_alerts if a.severity == 'critical')
        high_count = sum(1 for a in active_alerts if a.severity == 'high')

        return {
            'total': len(all_alerts),
            'active': len(active_alerts),
            'resolved': len(all_alerts) - len(active_alerts),
            'critical': critical_count,
            'high': high_count,
        }

    def _get_pair_names(self) -> list[str]:
        """Get all pair names for filter dropdown"""
        pairs = self.pair_repo.get_all(active_only=False)
        return sorted([p.name for p in pairs])

    def _get_alert_type_choices(self) -> list[tuple]:
        """Get alert type choices for filter"""
        return [
            ('correlation_breakdown', '相关性失效'),
            ('hedge_ratio_drift', '对冲比例漂移'),
            ('beta_change', 'Beta变化'),
            ('liquidity_risk', '流动性风险'),
        ]

    def _get_severity_choices(self) -> list[tuple]:
        """Get severity choices for filter"""
        return [
            ('low', '低'),
            ('medium', '中'),
            ('high', '高'),
            ('critical', '严重'),
        ]

    def _get_alert_type_display(self, alert_type: str) -> str:
        """Get display name for alert type"""
        display_names = {
            'correlation_breakdown': '相关性失效',
            'hedge_ratio_drift': '对冲比例漂移',
            'beta_change': 'Beta变化',
            'liquidity_risk': '流动性风险',
        }
        return display_names.get(alert_type, alert_type)

    def _get_severity_display(self, severity: str) -> str:
        """Get display name for severity"""
        display_names = {
            'low': '低',
            'medium': '中',
            'high': '高',
            'critical': '严重',
        }
        return display_names.get(severity, severity)


@dataclass
class ActivateHedgePairRequest:
    """Request for activating hedge pair"""
    pair_id: int


@dataclass
class ActivateHedgePairResponse:
    """Response for activating hedge pair"""
    success: bool
    message: str
    pair_name: str | None = None


class ActivateHedgePairUseCase:
    """
    UseCase for activating a hedge pair.
    """

    def __init__(self, pair_repo):
        self.pair_repo = pair_repo

    def execute(self, request: ActivateHedgePairRequest) -> ActivateHedgePairResponse:
        """Execute hedge pair activation"""
        pair = self.pair_repo.set_active(request.pair_id, True)

        if not pair:
            return ActivateHedgePairResponse(
                success=False,
                message='对冲对不存在'
            )

        return ActivateHedgePairResponse(
            success=True,
            message=f'对冲对 {pair.name} 已启用',
            pair_name=pair.name,
        )


@dataclass
class DeactivateHedgePairRequest:
    """Request for deactivating hedge pair"""
    pair_id: int


@dataclass
class DeactivateHedgePairResponse:
    """Response for deactivating hedge pair"""
    success: bool
    message: str
    pair_name: str | None = None


class DeactivateHedgePairUseCase:
    """
    UseCase for deactivating a hedge pair.
    """

    def __init__(self, pair_repo):
        self.pair_repo = pair_repo

    def execute(self, request: DeactivateHedgePairRequest) -> DeactivateHedgePairResponse:
        """Execute hedge pair deactivation"""
        pair = self.pair_repo.set_active(request.pair_id, False)

        if not pair:
            return DeactivateHedgePairResponse(
                success=False,
                message='对冲对不存在'
            )

        return DeactivateHedgePairResponse(
            success=True,
            message=f'对冲对 {pair.name} 已停用',
            pair_name=pair.name,
        )


@dataclass
class ResolveHedgeAlertRequest:
    """Request for resolving hedge alert"""
    alert_id: int


@dataclass
class ResolveHedgeAlertResponse:
    """Response for resolving hedge alert"""
    success: bool
    message: str
    alert_id: int | None = None


class ResolveHedgeAlertUseCase:
    """
    UseCase for resolving a hedge alert.
    """

    def __init__(self, alert_repo):
        self.alert_repo = alert_repo

    def execute(self, request: ResolveHedgeAlertRequest) -> ResolveHedgeAlertResponse:
        """Execute hedge alert resolution"""
        alert = self.alert_repo.resolve_alert(request.alert_id)

        if alert is None:
            return ResolveHedgeAlertResponse(
                success=False,
                message='告警不存在',
                alert_id=None,
            )

        return ResolveHedgeAlertResponse(
            success=True,
            message='告警已标记为已解决',
            alert_id=request.alert_id,
        )
