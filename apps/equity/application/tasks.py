"""Compatibility Celery tasks for legacy equity dotted task paths."""

from typing import cast

from celery import shared_task

from apps.equity.application.tasks_valuation_sync import (
    TaskPayload,
    sync_equity_valuation_task,
    sync_financial_data_task,
    sync_validate_scan_equity_valuation_task,
    validate_equity_valuation_quality_task,
)


@shared_task(name="apps.equity.application.tasks.sync_equity_valuation_task")  # type: ignore[misc]
def sync_equity_valuation_task_alias(
    days_back: int = 1,
    primary_source: str = "akshare",
    fallback_source: str = "tushare",
) -> TaskPayload:
    """Backwards-compatible alias for legacy beat and manual task dispatch."""
    return cast(
        TaskPayload,
        sync_equity_valuation_task.run(
            days_back=days_back,
            primary_source=primary_source,
            fallback_source=fallback_source,
        ),
    )


@shared_task(  # type: ignore[misc]
    name="apps.equity.application.tasks.validate_equity_valuation_quality_task"
)
def validate_equity_valuation_quality_task_alias(
    primary_source: str = "akshare",
) -> TaskPayload:
    """Backwards-compatible alias for legacy beat and manual task dispatch."""
    return cast(
        TaskPayload,
        validate_equity_valuation_quality_task.run(primary_source=primary_source),
    )


@shared_task(  # type: ignore[misc]
    name="apps.equity.application.tasks.sync_validate_scan_equity_valuation_task"
)
def sync_validate_scan_equity_valuation_task_alias(
    days_back: int = 1,
    primary_source: str = "akshare",
    fallback_source: str = "tushare",
    universe: str = "all_active",
    lookback_days: int | None = None,
) -> TaskPayload:
    """Backwards-compatible alias for legacy beat and manual task dispatch."""
    return cast(
        TaskPayload,
        sync_validate_scan_equity_valuation_task.run(
            days_back=days_back,
            primary_source=primary_source,
            fallback_source=fallback_source,
            universe=universe,
            lookback_days=lookback_days,
        ),
    )


@shared_task(name="apps.equity.application.tasks.sync_financial_data_task")  # type: ignore[misc]
def sync_financial_data_task_alias(
    source: str = "akshare",
    periods: int = 8,
    stock_codes: list[str] | None = None,
) -> TaskPayload:
    """Backwards-compatible alias for legacy beat and manual task dispatch."""
    return cast(
        TaskPayload,
        sync_financial_data_task.run(
            source=source,
            periods=periods,
            stock_codes=stock_codes,
        ),
    )
