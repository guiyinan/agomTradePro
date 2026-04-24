"""Application-facing helpers for hedge interface views and APIs."""

from __future__ import annotations

from typing import Any

from apps.hedge.application.repository_provider import (
    get_hedge_alert_repository,
    get_hedge_correlation_repository,
    get_hedge_pair_repository,
    get_hedge_portfolio_repository,
)
from apps.hedge.application.use_cases import (
    ActivateHedgePairRequest,
    ActivateHedgePairResponse,
    ActivateHedgePairUseCase,
    DeactivateHedgePairRequest,
    DeactivateHedgePairResponse,
    DeactivateHedgePairUseCase,
    GetHedgeAlertsForViewUseCase,
    GetHedgePairsForViewUseCase,
    GetHedgeSnapshotsForViewUseCase,
    HedgeAlertsViewRequest,
    HedgePairsViewRequest,
    HedgeSnapshotsViewRequest,
    ResolveHedgeAlertRequest,
    ResolveHedgeAlertResponse,
    ResolveHedgeAlertUseCase,
)
from apps.hedge.infrastructure.services import HedgeIntegrationService

HEDGE_METHOD_CHOICES = [
    ("beta", "Beta对冲"),
    ("min_variance", "最小方差"),
    ("equal_risk", "等风险贡献"),
    ("dollar_neutral", "货币中性"),
    ("fixed_ratio", "固定比例"),
]


def _get_integration_service() -> HedgeIntegrationService:
    """Return the hedge integration service."""

    return HedgeIntegrationService()


def get_hedge_pair_queryset():
    """Return the hedge pair queryset for DRF viewsets."""

    return get_hedge_pair_repository().get_queryset()


def get_correlation_history_queryset():
    """Return the correlation history queryset for DRF viewsets."""

    return get_hedge_correlation_repository().get_queryset()


def get_hedge_snapshot_queryset():
    """Return the hedge snapshot queryset for DRF viewsets."""

    return get_hedge_portfolio_repository().get_queryset()


def get_hedge_alert_queryset(*, active_only: bool = True):
    """Return the hedge alert queryset for DRF viewsets."""

    is_resolved = False if active_only else None
    return get_hedge_alert_repository().get_queryset(is_resolved=is_resolved)


def activate_hedge_pair(*, pair_id: int) -> ActivateHedgePairResponse:
    """Activate one hedge pair."""

    use_case = ActivateHedgePairUseCase(get_hedge_pair_repository())
    return use_case.execute(ActivateHedgePairRequest(pair_id=pair_id))


def deactivate_hedge_pair(*, pair_id: int) -> DeactivateHedgePairResponse:
    """Deactivate one hedge pair."""

    use_case = DeactivateHedgePairUseCase(get_hedge_pair_repository())
    return use_case.execute(DeactivateHedgePairRequest(pair_id=pair_id))


def resolve_hedge_alert(*, alert_id: int) -> ResolveHedgeAlertResponse:
    """Resolve one hedge alert."""

    use_case = ResolveHedgeAlertUseCase(get_hedge_alert_repository())
    return use_case.execute(ResolveHedgeAlertRequest(alert_id=alert_id))


def get_hedge_effectiveness_payload(*, pair_name: str) -> dict[str, Any] | None:
    """Return hedge effectiveness payload for one pair."""

    return _get_integration_service().check_hedge_effectiveness(pair_name)


def get_correlation_matrix_payload(*, asset_codes: list[str], window_days: int) -> dict[str, Any]:
    """Return the correlation matrix payload for multiple assets."""

    matrix = _get_integration_service().get_correlation_matrix(
        asset_codes,
        window_days=window_days,
    )
    return {
        "asset_codes": asset_codes,
        "window_days": window_days,
        "matrix": matrix,
    }


def get_all_effectiveness_payload() -> dict[str, Any]:
    """Return the effectiveness payload for all active hedge pairs."""

    results = _get_integration_service().get_all_effectiveness()
    return {
        "count": len(results),
        "results": results,
    }


def get_correlation_metric_payload(
    *,
    asset1: str,
    asset2: str,
    window_days: int,
) -> dict[str, Any] | None:
    """Return a serialized correlation metric payload."""

    metric = _get_integration_service().calculate_correlation(
        asset1,
        asset2,
        window_days=window_days,
    )
    if metric is None:
        return None

    return {
        "asset1": metric.asset1,
        "asset2": metric.asset2,
        "calc_date": metric.calc_date.isoformat(),
        "window_days": metric.window_days,
        "correlation": round(metric.correlation, 4),
        "covariance": round(metric.covariance, 4) if metric.covariance else None,
        "beta": round(metric.beta, 4) if metric.beta else None,
        "correlation_trend": metric.correlation_trend,
        "correlation_ma": round(metric.correlation_ma, 4) if metric.correlation_ma else None,
        "alert": metric.alert,
        "alert_type": metric.alert_type.value if metric.alert_type else None,
    }


def get_latest_snapshots_payload() -> dict[str, Any]:
    """Return the latest snapshot payload for all active hedge pairs."""

    service = _get_integration_service()
    snapshots: list[dict[str, Any]] = []

    for pair in service.get_all_pairs(active_only=True):
        latest = service.get_hedge_portfolio(pair.name)
        if latest is None:
            continue
        snapshots.append(
            {
                "pair_name": latest.pair_name,
                "trade_date": latest.trade_date.isoformat(),
                "long_weight": round(latest.long_weight * 100, 2),
                "hedge_weight": round(latest.hedge_weight * 100, 2),
                "hedge_ratio": round(latest.hedge_ratio, 3),
                "current_correlation": round(latest.current_correlation, 3),
                "hedge_effectiveness": round(latest.hedge_effectiveness * 100, 1),
                "rebalance_needed": latest.rebalance_needed,
                "rebalance_reason": latest.rebalance_reason,
            }
        )

    return {
        "count": len(snapshots),
        "results": snapshots,
    }


def update_all_portfolios_payload() -> dict[str, Any]:
    """Return the payload after updating all hedge portfolios."""

    portfolios = _get_integration_service().update_all_portfolios()
    return {
        "updated": len(portfolios),
        "portfolios": [
            {
                "pair_name": portfolio.pair_name,
                "trade_date": portfolio.trade_date.isoformat(),
                "hedge_ratio": round(portfolio.hedge_ratio, 3),
                "rebalance_needed": portfolio.rebalance_needed,
            }
            for portfolio in portfolios
        ],
    }


def get_recent_alerts_payload(*, days: int) -> dict[str, Any]:
    """Return recent hedge alerts payload."""

    alerts = _get_integration_service().get_recent_alerts(days=days)
    return {
        "count": len(alerts),
        "results": [
            {
                "pair_name": alert.pair_name,
                "alert_date": alert.alert_date.isoformat(),
                "alert_type": alert.alert_type.value,
                "severity": alert.severity,
                "message": alert.message,
                "action_required": alert.action_required,
                "action_priority": alert.action_priority,
            }
            for alert in alerts
        ],
    }


def monitor_hedge_pairs_payload() -> dict[str, Any]:
    """Return the payload after running hedge monitoring."""

    alerts = _get_integration_service().monitor_hedge_pairs()
    return {
        "generated_alerts": len(alerts),
        "alerts": [
            {
                "pair_name": alert.pair_name,
                "alert_date": alert.alert_date.isoformat(),
                "alert_type": alert.alert_type.value,
                "severity": alert.severity,
                "message": alert.message,
            }
            for alert in alerts
        ],
    }


def get_hedge_ratio_payload(*, pair_name: str) -> dict[str, Any] | None:
    """Return the hedge ratio payload for one pair."""

    result = _get_integration_service().calculate_hedge_ratio(pair_name)
    if result is None:
        return None

    hedge_ratio, details = result
    return {
        "pair_name": pair_name,
        "hedge_ratio": round(hedge_ratio, 4),
        "method": details.get("method", "unknown"),
        "details": details,
    }


def get_hedge_pairs_page_context(
    *,
    is_active: bool | None,
    hedge_method: str | None,
    search: str | None,
    filter_is_active: str,
    filter_hedge_method: str,
    filter_search: str,
) -> dict[str, Any]:
    """Build the hedge pairs page context."""

    use_case = GetHedgePairsForViewUseCase(
        get_hedge_pair_repository(),
        get_hedge_correlation_repository(),
        get_hedge_portfolio_repository(),
    )
    response = use_case.execute(
        HedgePairsViewRequest(
            is_active=is_active,
            hedge_method=hedge_method,
            search=search,
        )
    )
    return {
        "pairs": response.pairs,
        "stats": response.stats,
        "hedge_methods": HEDGE_METHOD_CHOICES,
        "filter_is_active": filter_is_active,
        "filter_hedge_method": filter_hedge_method,
        "filter_search": filter_search,
    }


def get_hedge_snapshots_page_context(
    *,
    pair_name: str | None,
    rebalance_needed: bool | None,
    filter_pair_name: str,
    filter_rebalance_needed: str,
) -> dict[str, Any]:
    """Build the hedge snapshots page context."""

    use_case = GetHedgeSnapshotsForViewUseCase(
        get_hedge_portfolio_repository(),
        get_hedge_pair_repository(),
    )
    response = use_case.execute(
        HedgeSnapshotsViewRequest(
            pair_name=pair_name,
            rebalance_needed=rebalance_needed,
            limit=50,
        )
    )
    return {
        "snapshots": response.snapshots,
        "stats": response.stats,
        "pair_names": response.pair_names,
        "filter_pair_name": filter_pair_name,
        "filter_rebalance_needed": filter_rebalance_needed,
    }


def get_hedge_alerts_page_context(
    *,
    pair_name: str | None,
    severity: str | None,
    alert_type: str | None,
    is_resolved: bool | None,
    filter_pair_name: str,
    filter_severity: str,
    filter_alert_type: str,
    filter_is_resolved: str,
) -> dict[str, Any]:
    """Build the hedge alerts page context."""

    use_case = GetHedgeAlertsForViewUseCase(
        get_hedge_alert_repository(),
        get_hedge_pair_repository(),
    )
    response = use_case.execute(
        HedgeAlertsViewRequest(
            pair_name=pair_name,
            severity=severity,
            alert_type=alert_type,
            is_resolved=is_resolved,
            limit=100,
        )
    )
    return {
        "alerts": response.alerts,
        "stats": response.stats,
        "alert_types": response.alert_types,
        "severity_choices": response.severity_choices,
        "pair_names": response.pair_names,
        "filter_pair_name": filter_pair_name,
        "filter_severity": filter_severity,
        "filter_alert_type": filter_alert_type,
        "filter_is_resolved": filter_is_resolved,
    }
