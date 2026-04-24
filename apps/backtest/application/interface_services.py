"""Application-side builders and query services for backtest interface views."""

from __future__ import annotations

from datetime import date
from typing import Any

from .repository_provider import get_backtest_repository
from .use_cases import (
    DeleteBacktestRequest,
    DeleteBacktestUseCase,
    GetBacktestResultRequest,
    GetBacktestResultUseCase,
    GetBacktestStatisticsUseCase,
    ListBacktestsRequest,
    ListBacktestsUseCase,
    RunBacktestRequest,
    RunBacktestUseCase,
)


def _build_regime_reader():
    def get_regime(as_of_date: date):
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        snapshot = DjangoRegimeRepository().get_regime_by_date(as_of_date)
        if snapshot:
            return {
                "dominant_regime": snapshot.dominant_regime,
                "confidence": snapshot.confidence,
                "growth_momentum_z": snapshot.growth_momentum_z,
                "inflation_momentum_z": snapshot.inflation_momentum_z,
                "distribution": snapshot.distribution,
            }
        return None

    return get_regime


def _build_price_reader():
    def get_asset_price(asset_class: str, as_of_date: date):
        from shared.config.secrets import get_secrets

        from ..infrastructure.adapters import create_default_price_adapter

        try:
            tushare_settings = get_secrets().data_sources
        except Exception:
            tushare_settings = None

        adapter = create_default_price_adapter(
            tushare_token=(tushare_settings.tushare_token if tushare_settings else None),
            tushare_http_url=(tushare_settings.tushare_http_url if tushare_settings else None),
        )
        return adapter.get_price(asset_class, as_of_date)

    return get_asset_price


def load_backtest_list_context(*, limit: int = 20) -> dict[str, Any]:
    """Build the backtest list page context."""
    repository = get_backtest_repository()
    return {
        "backtests": repository.get_all_backtests(limit=limit),
        "stats": repository.get_statistics(),
    }


def load_backtest_detail_context(backtest_id: int) -> dict[str, Any] | None:
    """Build the backtest detail page context."""
    repository = get_backtest_repository()
    backtest = repository.get_backtest_by_id(backtest_id)
    if backtest is None:
        return None

    summary = None
    if backtest.status == "completed":
        summary = type(repository).to_domain_entity(backtest).to_summary_dict()

    return {
        "backtest": backtest,
        "summary": summary,
        "is_completed": backtest.status == "completed",
    }


def load_backtest_create_context() -> dict[str, Any]:
    """Build the backtest create page context."""
    from apps.regime.infrastructure.repositories import DjangoRegimeRepository

    regime_repo = DjangoRegimeRepository()
    return {
        "earliest_date": regime_repo.get_earliest_date(),
        "latest_date": regime_repo.get_latest_date(),
        "frequencies": [
            ("monthly", "月度"),
            ("quarterly", "季度"),
            ("yearly", "年度"),
        ],
    }


def list_backtests_payload(
    *,
    status_filter: str | None,
    limit: int | None,
) -> dict[str, Any]:
    """Return the backtest list API payload."""
    response = ListBacktestsUseCase(get_backtest_repository()).execute(
        ListBacktestsRequest(status=status_filter, limit=limit)
    )
    return {"backtests": response.backtests, "total_count": response.total_count}


def get_backtest_result_payload(backtest_id: int) -> dict[str, Any]:
    """Return one backtest result payload."""
    response = GetBacktestResultUseCase(get_backtest_repository()).execute(
        GetBacktestResultRequest(backtest_id=backtest_id)
    )
    return {
        "backtest_id": response.backtest_id,
        "name": response.name,
        "status": response.status,
        "result": response.result,
        "error": response.error,
    }


def run_backtest_payload(validated_data: dict[str, Any]):
    """Execute a backtest run from validated request data."""
    return RunBacktestUseCase(
        get_backtest_repository(),
        _build_regime_reader(),
        _build_price_reader(),
    ).execute(RunBacktestRequest(**validated_data))


def delete_backtest_payload(backtest_id: int) -> dict[str, Any]:
    """Delete one backtest and return a simple payload."""
    response = DeleteBacktestUseCase(get_backtest_repository()).execute(
        DeleteBacktestRequest(backtest_id=backtest_id)
    )
    return {"success": response.success, "error": response.error}


def get_backtest_statistics_payload():
    """Return the backtest statistics DTO."""
    return GetBacktestStatisticsUseCase(get_backtest_repository()).execute()


def backtest_exists(backtest_id: int) -> bool:
    """Return whether a backtest exists."""
    return get_backtest_repository().get_backtest_by_id(backtest_id) is not None
