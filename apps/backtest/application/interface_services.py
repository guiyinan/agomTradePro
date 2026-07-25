"""Application-side builders and query services for backtest interface views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from apps.regime.application.repository_provider import get_regime_repository
from core.integration.research_integrity_registry import (
    get_decision_snapshot,
    make_manifest_bound_pit_view,
)

from .repository_provider import (
    build_default_price_reader,
    build_default_regime_reader,
    get_backtest_repository,
)
from .use_cases import (
    DeleteBacktestRequest,
    DeleteBacktestUseCase,
    GetBacktestResultRequest,
    GetBacktestResultUseCase,
    GetBacktestStatisticsResponse,
    GetBacktestStatisticsUseCase,
    ListBacktestsRequest,
    ListBacktestsUseCase,
    RunBacktestRequest,
    RunBacktestResponse,
    RunBacktestUseCase,
)


def _build_regime_reader() -> Callable[[date], dict[str, object] | None]:
    """Return a repository-cached regime reader."""

    return build_default_regime_reader()


def _build_price_reader() -> Callable[[str, date], float | None]:
    """Return a lazily initialized, execution-scoped price reader."""

    return build_default_price_reader()


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

    regime_repo = get_regime_repository()
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


def get_backtest_equity_curve_payload(backtest_id: int) -> dict[str, Any] | None:
    """Return one persisted backtest equity curve without recalculation."""
    backtest = get_backtest_repository().get_backtest_by_id(backtest_id)
    if backtest is None:
        return None
    curve = [dict(point) for point in backtest.equity_curve if isinstance(point, dict)]
    return {
        "backtest_id": backtest.id,
        "status": backtest.status,
        "curve": curve,
        "point_count": len(curve),
    }


def run_backtest_payload(validated_data: dict[str, Any]) -> RunBacktestResponse:
    """Execute a backtest run from validated request data."""
    resolved_data = dict(validated_data)
    pit_data_view = None
    if resolved_data.get("trust_status") == "pit_verified":
        pit_data_view = make_manifest_bound_pit_view(
            str(resolved_data.get("data_manifest_id") or "")
        )
        resolved_data["pit_coverage"] = pit_data_view.coverage
    return RunBacktestUseCase(
        get_backtest_repository(),
        _build_regime_reader(),
        _build_price_reader(),
        pit_data_view=pit_data_view,
        get_decision_snapshot_func=(get_decision_snapshot if pit_data_view is not None else None),
    ).execute(RunBacktestRequest(**resolved_data))


def delete_backtest_payload(backtest_id: int) -> dict[str, Any]:
    """Delete one backtest and return a simple payload."""
    response = DeleteBacktestUseCase(get_backtest_repository()).execute(
        DeleteBacktestRequest(backtest_id=backtest_id)
    )
    return {"success": response.success, "error": response.error}


def get_backtest_statistics_payload() -> GetBacktestStatisticsResponse:
    """Return the backtest statistics DTO."""
    return GetBacktestStatisticsUseCase(get_backtest_repository()).execute()


def backtest_exists(backtest_id: int) -> bool:
    """Return whether a backtest exists."""
    return get_backtest_repository().get_backtest_by_id(backtest_id) is not None
