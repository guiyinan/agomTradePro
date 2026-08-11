"""
Celery Tasks for Backtest Module.

异步执行回测任务。
"""

import logging
from collections.abc import Mapping
from datetime import date, timedelta

from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.application.pit_provider import make_manifest_bound_pit_view
from core.exceptions import BusinessLogicError, InvalidInputError, ResourceNotFoundError
from shared.infrastructure.celery_typing import BoundTask, typed_shared_task
from shared.numeric import safe_float

from ..domain.entities import BacktestConfig, RegimeHistoryEntry, Trade
from ..domain.services import BacktestEngine
from .repository_provider import (
    build_default_price_reader,
    build_default_regime_reader,
    get_backtest_repository,
)
from .use_cases import RunBacktestUseCase

logger = logging.getLogger(__name__)
_MAX_CLEANUP_DAYS = 3650


def _backtest_task_result(
    *,
    outcome: str,
    stored: int = 0,
    **details: object,
) -> dict[str, object]:
    """Build normalized counters for one backtest task request."""

    if outcome not in {"success", "noop"} or stored < 0:
        raise ValueError("invalid backtest task outcome")
    return {
        "outcome": outcome,
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": stored,
        **details,
    }


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    """Return one required non-empty task string."""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(
    payload: Mapping[str, object],
    field_name: str,
    *,
    default: str | None = None,
) -> str | None:
    """Return one optional task string without coercing arbitrary objects."""

    value = payload.get(field_name, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(f"{field_name} must be a string or null")
    return value.strip()


def _finite_number(
    payload: Mapping[str, object],
    field_name: str,
    *,
    default: float | None = None,
) -> float:
    """Parse one finite task number through the shared external-value boundary."""

    value = payload.get(field_name, default)
    if isinstance(value, bool):
        raise InvalidInputError(f"{field_name} must be a finite number")
    normalized = safe_float(value)
    if normalized is None:
        raise InvalidInputError(f"{field_name} must be a finite number")
    return normalized


def _boolean_value(
    payload: Mapping[str, object],
    field_name: str,
    *,
    default: bool,
) -> bool:
    """Return one strict boolean task option."""

    value = payload.get(field_name, default)
    if not isinstance(value, bool):
        raise InvalidInputError(f"{field_name} must be a boolean")
    return value


def _pit_coverage(payload: Mapping[str, object]) -> dict[str, float]:
    """Validate manifest coverage as a finite numeric mapping."""

    raw_coverage = payload.get("pit_coverage") or {}
    if not isinstance(raw_coverage, Mapping):
        raise InvalidInputError("pit_coverage must be an object")

    coverage: dict[str, float] = {}
    for raw_key, raw_value in raw_coverage.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise InvalidInputError("pit_coverage keys must be non-empty strings")
        if isinstance(raw_value, bool):
            raise InvalidInputError("pit_coverage values must be finite numbers")
        normalized = safe_float(raw_value)
        if normalized is None:
            raise InvalidInputError("pit_coverage values must be finite numbers")
        coverage[raw_key.strip()] = normalized
    return coverage


def _build_backtest_config(payload: Mapping[str, object]) -> BacktestConfig:
    """Validate a serialized task payload and build its domain configuration."""

    try:
        start_date = date.fromisoformat(_required_text(payload, "start_date"))
        end_date = date.fromisoformat(_required_text(payload, "end_date"))
    except ValueError as exc:
        raise InvalidInputError("start_date and end_date must use YYYY-MM-DD format") from exc

    return BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=_finite_number(payload, "initial_capital"),
        rebalance_frequency=_required_text(payload, "rebalance_frequency"),
        use_pit_data=_boolean_value(payload, "use_pit_data", default=False),
        transaction_cost_bps=_finite_number(payload, "transaction_cost_bps", default=10.0),
        trust_status=_optional_text(payload, "trust_status", default="exploratory")
        or "exploratory",
        data_manifest_id=_optional_text(payload, "data_manifest_id"),
        pit_coverage=_pit_coverage(payload),
        config_hash=_optional_text(payload, "config_hash", default="") or "",
        code_commit=_optional_text(payload, "code_commit", default="") or "",
        engine_version=_optional_text(payload, "engine_version", default="backtest-v1")
        or "backtest-v1",
        research_trial_id=_optional_text(payload, "research_trial_id"),
        decision_snapshot_id=_optional_text(payload, "decision_snapshot_id"),
    )


@typed_shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=600,
    time_limit=3600,
    soft_time_limit=3300,
)
def run_backtest_task(
    self: BoundTask,
    backtest_id: int,
    config_dict: Mapping[str, object],
) -> dict[str, object]:
    """
    异步执行回测任务

    Args:
        backtest_id: 回测 ID
        config_dict: 回测配置字典

    Returns:
        Dict: 任务结果
    """
    if isinstance(backtest_id, bool) or not isinstance(backtest_id, int) or backtest_id <= 0:
        raise InvalidInputError("backtest_id must be a positive integer")

    repository = get_backtest_repository()
    backtest_exists = False

    try:
        # 1. 获取回测记录
        backtest = repository.get_backtest_by_id(backtest_id)
        if not backtest:
            raise ResourceNotFoundError(f"Backtest {backtest_id} not found")
        backtest_exists = True

        # 2. Resolve trusted evidence before persisting/using the config.
        pit_view = None
        resolved_config: dict[str, object] = dict(config_dict)
        if _optional_text(config_dict, "trust_status", default="exploratory") == "pit_verified":
            pit_view = make_manifest_bound_pit_view(
                _optional_text(config_dict, "data_manifest_id") or ""
            )
            resolved_config["pit_coverage"] = dict(pit_view.coverage)

        # 3. 创建配置
        config = _build_backtest_config(resolved_config)

        # 4. 标记为运行中
        if not repository.update_status(backtest_id, "running"):
            raise ResourceNotFoundError(f"Backtest {backtest_id} not found")

        # 5. Trusted workers use exactly the evidence frozen by the manifest.
        if config.trust_status == "pit_verified":
            assert pit_view is not None
            from core.integration.research_integrity_registry import get_decision_snapshot

            if get_decision_snapshot(config.decision_snapshot_id or "") is None:
                raise ValueError("decision input snapshot not found")
            regime_reader, price_reader = RunBacktestUseCase._build_pit_readers(pit_view)
        else:
            regime_reader = build_default_regime_reader()
            price_reader = build_default_price_reader()

        # 6. 创建并运行回测引擎
        engine = BacktestEngine(
            config=config,
            get_regime_func=regime_reader,
            get_asset_price_func=price_reader,
            pit_processor=None,
        )

        result = engine.run()

        # 7. 保存结果
        if not repository.save_result(backtest_id, result):
            raise ResourceNotFoundError(f"Backtest {backtest_id} not found while saving result")

        logger.info(f"Backtest {backtest_id} completed successfully via Celery")

        return _backtest_task_result(
            outcome="success",
            stored=1,
            backtest_id=backtest_id,
            status="completed",
            total_return=result.total_return,
            annualized_return=result.annualized_return,
            max_drawdown=result.max_drawdown,
            sharpe_ratio=result.sharpe_ratio,
        )

    except (
        BusinessLogicError,
        InvalidInputError,
        ResourceNotFoundError,
        ValueError,
    ) as exc:
        logger.exception("Backtest task %s rejected: %s", backtest_id, exc)
        if backtest_exists:
            repository.update_status(backtest_id, "failed", str(exc))
        raise
    except Exception as exc:
        logger.exception("Backtest task %s failed: %s", backtest_id, exc)
        if self.request.retries < self.max_retries:
            countdown = 60 * (2**self.request.retries)
            logger.warning(
                "Scheduling retry %s for backtest %s in %s seconds",
                self.request.retries + 1,
                backtest_id,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        if backtest_exists:
            repository.update_status(backtest_id, "failed", str(exc))
        raise


@typed_shared_task(
    name="backtest.cleanup_old_backtests",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def cleanup_old_backtests(self: BoundTask, days_old: int = 90) -> dict[str, object]:
    """
    清理旧的回测记录

    Args:
        days_old: 保留天数，超过此天数的已完成回测将被删除

    Returns:
        int: 删除的记录数
    """
    if (
        isinstance(days_old, bool)
        or not isinstance(days_old, int)
        or not 1 <= days_old <= _MAX_CLEANUP_DAYS
    ):
        raise InvalidInputError(f"days_old must be between 1 and {_MAX_CLEANUP_DAYS}")

    try:
        repository = get_backtest_repository()
        cutoff_date = timezone.now() - timedelta(days=days_old)
        deleted_count = repository.delete_completed_before(cutoff_date)

        logger.info(f"Cleanup completed: {deleted_count} old backtests deleted")
        if type(deleted_count) is not int or deleted_count < 0:
            raise BusinessLogicError("Backtest cleanup returned an invalid deleted count")
        return _backtest_task_result(
            outcome="success" if deleted_count else "noop",
            deleted_count=deleted_count,
            days_old=days_old,
        )
    except DatabaseError as exc:
        logger.exception("Backtest cleanup failed")
        raise self.retry(exc=exc, countdown=60) from exc


@typed_shared_task(
    name="backtest.generate_backtest_report",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def generate_backtest_report(
    self: BoundTask,
    backtest_id: int,
) -> dict[str, object]:
    """
    生成回测报告

    Args:
        backtest_id: 回测 ID

    Returns:
        Dict: 报告数据
    """
    if isinstance(backtest_id, bool) or not isinstance(backtest_id, int) or backtest_id <= 0:
        raise InvalidInputError("backtest_id must be a positive integer")

    try:
        repository = get_backtest_repository()
        backtest = repository.get_backtest_by_id(backtest_id)
    except DatabaseError as exc:
        logger.exception("Loading backtest %s for report failed", backtest_id)
        raise self.retry(exc=exc, countdown=60) from exc

    if backtest is None:
        raise ResourceNotFoundError(f"Backtest {backtest_id} not found")
    if backtest.status != "completed":
        raise BusinessLogicError(f"Backtest {backtest_id} is not completed")

    # 转换为 Domain 实体
    domain_result = repository.to_domain_entity(backtest)

    # 生成报告
    report: dict[str, object] = {
        "summary": domain_result.to_summary_dict(),
        "regime_analysis": _analyze_regime_performance(domain_result.regime_history),
        "trade_analysis": _analyze_trades(domain_result.trades),
        "risk_metrics": {
            "max_drawdown": domain_result.max_drawdown,
            "sharpe_ratio": domain_result.sharpe_ratio,
        },
    }

    return _backtest_task_result(
        outcome="success",
        summary=report["summary"],
        regime_analysis=report["regime_analysis"],
        trade_analysis=report["trade_analysis"],
        risk_metrics=report["risk_metrics"],
    )


def _analyze_regime_performance(
    regime_history: list[RegimeHistoryEntry],
) -> dict[str, object]:
    """分析各 Regime 下的表现"""
    if not regime_history:
        return {}

    regime_returns: dict[str, list[float]] = {}
    for entry in regime_history:
        regime = entry.get("regime", "Unknown")
        value = entry.get("portfolio_value", 0.0)
        if regime not in regime_returns:
            regime_returns[regime] = []
        regime_returns[regime].append(value)

    analysis: dict[str, object] = {}
    for regime, values in regime_returns.items():
        if len(values) >= 2:
            total_return = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0
            analysis[regime] = {
                "count": len(values),
                "total_return": total_return,
                "avg_value": sum(values) / len(values),
            }

    return analysis


def _analyze_trades(trades: list[Trade]) -> dict[str, object]:
    """分析交易记录"""
    if not trades:
        return {}

    buy_trades = [t for t in trades if t.action == "buy"]
    sell_trades = [t for t in trades if t.action == "sell"]

    total_cost = sum(t.cost for t in trades)
    total_notional = sum(t.notional for t in trades)

    return {
        "total_trades": len(trades),
        "buy_trades": len(buy_trades),
        "sell_trades": len(sell_trades),
        "total_cost": total_cost,
        "total_notional": total_notional,
        "cost_ratio": total_cost / total_notional if total_notional > 0 else 0,
    }
