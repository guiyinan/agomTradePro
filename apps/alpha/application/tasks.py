"""
Alpha Celery Tasks

Alpha 信号相关的异步任务。
包括 Qlib 推理、训练等任务。
"""

# ruff: noqa: I001

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol, cast

from django.utils import timezone

from apps.alpha.application.ops_services import QlibRuntimeDataRefreshService
from apps.alpha.application.ops_use_cases import collect_portfolio_refs_for_refresh
from apps.alpha.application.repository_provider import (
    build_outdated_qlib_reason as _build_outdated_qlib_reason,
)
from apps.alpha.application.repository_provider import (
    build_qlib_runtime_failure_reason as _build_qlib_runtime_failure_reason,
)
from apps.alpha.application.repository_provider import (
    cache_is_fresh_for_trade_date as _cache_is_fresh_for_trade_date,
)
from apps.alpha.application.repository_provider import (
    calculate_artifact_hash as _calculate_artifact_hash,
)
from apps.alpha.application.repository_provider import (
    evaluate_model_from_cache,
)
from apps.alpha.application.repository_provider import (
    evaluate_model_metrics as _evaluate_model_metrics,
)
from apps.alpha.application.repository_provider import (
    execute_qlib_prediction as _execute_qlib_prediction_runtime,
)
from apps.alpha.application.repository_provider import (
    extract_model_filename as _extract_model_filename,
)
from apps.alpha.application.repository_provider import (
    find_broader_qlib_cache_for_scope as _find_broader_qlib_cache_for_scope,
)
from apps.alpha.application.repository_provider import (
    get_alpha_pool_data_repository,
    get_alpha_score_cache_repository,
)
from apps.alpha.application.repository_provider import (
    get_qlib_data_latest_date as _get_qlib_data_latest_date,
)
from apps.alpha.application.repository_provider import (
    get_qlib_data_latest_date_for_provider as _get_qlib_data_latest_date_for_provider,
)
from apps.alpha.application.repository_provider import (
    get_qlib_model_registry_repository,
)
from apps.alpha.application.repository_provider import (
    get_runtime_qlib_config as _get_runtime_qlib_config,
)
from apps.alpha.application.repository_provider import (
    install_qlib_pandas_compat as _install_qlib_pandas_compat,
)
from apps.alpha.application.repository_provider import make_json_safe as _make_json_safe_runtime
from apps.alpha.application.repository_provider import (
    normalize_calendar_date as _normalize_calendar_date,
)
from apps.alpha.application.repository_provider import (
    normalize_qlib_feature_set_id as _normalize_qlib_feature_set_id,
)
from apps.alpha.application.repository_provider import (
    normalize_qlib_instrument_code as _normalize_qlib_instrument_code,
)
from apps.alpha.application.repository_provider import (
    normalize_qlib_instrument_list as _normalize_qlib_instrument_list,
)
from apps.alpha.application.repository_provider import (
    normalize_qlib_region as _normalize_qlib_region,
)
from apps.alpha.application.repository_provider import (
    normalize_reused_scores as _normalize_reused_scores,
)
from apps.alpha.application.repository_provider import parse_universe_list as _parse_universe_list
from apps.alpha.application.repository_provider import (
    require_usable_qlib_runtime as _require_usable_qlib_runtime,
)
from apps.alpha.application.repository_provider import (
    reset_qlib_runtime_binding as _reset_qlib_runtime_binding,
)
from apps.alpha.application.repository_provider import (
    resolve_effective_trade_date,
)
from apps.alpha.application.repository_provider import (
    resolve_qlib_handler_class as _resolve_qlib_handler_class,
)
from apps.alpha.application.repository_provider import (
    resolve_qlib_model_path as _resolve_qlib_model_path,
)
from apps.alpha.application.repository_provider import (
    resolve_qlib_stock_list as _resolve_qlib_stock_list,
)
from apps.alpha.application.repository_provider import (
    reuse_latest_qlib_cache as _reuse_latest_qlib_cache,
)
from apps.alpha.application.repository_provider import save_model_artifact as _save_model_artifact
from apps.alpha.application.repository_provider import train_qlib_model as _train_qlib_model
from apps.alpha.application.repository_provider import upsert_qlib_cache as _upsert_qlib_cache
from apps.alpha.application.trade_dates import resolve_recent_closed_trade_date
from apps.alpha.application.workspace_sync import sync_default_workspace_after_alpha_update
from apps.alpha.domain.entities import AlphaPoolScope, normalize_stock_code
from apps.config_center.application.repository_provider import get_qlib_training_run_repository
from shared.infrastructure.celery_typing import BoundTask, typed_shared_task

__all__ = [
    "_build_outdated_qlib_reason",
    "_build_qlib_runtime_failure_reason",
    "_cache_is_fresh_for_trade_date",
    "_calculate_artifact_hash",
    "_evaluate_model_metrics",
    "_execute_qlib_prediction",
    "_extract_model_filename",
    "_find_broader_qlib_cache_for_scope",
    "_get_qlib_data_latest_date",
    "_get_qlib_data_latest_date_for_provider",
    "_get_runtime_qlib_config",
    "_install_qlib_pandas_compat",
    "_make_json_safe",
    "_require_usable_qlib_runtime",
    "_normalize_calendar_date",
    "_normalize_qlib_instrument_code",
    "_normalize_qlib_instrument_list",
    "_normalize_qlib_region",
    "_normalize_reused_scores",
    "_parse_universe_list",
    "_resolve_qlib_handler_class",
    "_resolve_qlib_model_path",
    "_resolve_qlib_stock_list",
    "_reuse_latest_qlib_cache",
    "_save_model_artifact",
    "_train_qlib_model",
    "_upsert_qlib_cache",
    "qlib_daily_inference",
    "qlib_daily_inference_alias",
    "qlib_daily_scoped_inference",
    "qlib_daily_scoped_inference_alias",
    "qlib_evaluate_model",
    "qlib_predict_scores",
    "qlib_refresh_cache",
    "qlib_refresh_cache_alias",
    "qlib_refresh_runtime_data_for_codes_task",
    "qlib_refresh_runtime_data_task",
    "qlib_train_model",
]

logger = logging.getLogger(__name__)

_resolve_recent_closed_trade_date = resolve_recent_closed_trade_date


def _make_json_safe(value: Any) -> Any:
    """Serialize dynamic Qlib values through a typed compatibility boundary."""

    serializer = cast(Callable[[Any], Any], _make_json_safe_runtime)
    return serializer(value)


class _PredictionProxy(Protocol):
    """Typed prediction proxy with the legacy implementation marker."""

    runtime_implementation: Callable[..., Any]

    def __call__(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]: ...


def _run_qlib_prediction_proxy(
    *args: Any,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Proxy prediction runtime while preserving the legacy patch surface."""
    kwargs.setdefault("outdated_reason_builder", _build_outdated_qlib_reason)
    runtime = cast(
        Callable[..., list[dict[str, Any]]],
        _execute_qlib_prediction_runtime,
    )
    return runtime(*args, **kwargs)


_execute_qlib_prediction = cast(_PredictionProxy, _run_qlib_prediction_proxy)
_execute_qlib_prediction.runtime_implementation = _execute_qlib_prediction_runtime


def _reset_qlib_runtime_state() -> None:
    """Clear one-process qlib init markers so refreshed day data becomes visible immediately."""
    _reset_qlib_runtime_binding()
    for func in (
        _get_qlib_data_latest_date,
        _execute_qlib_prediction,
        _execute_qlib_prediction_runtime,
    ):
        if hasattr(func, "_qlib_initialized"):
            delattr(func, "_qlib_initialized")


def _refresh_qlib_runtime_data(
    *,
    target_date: date,
    universes: str | list[str] | tuple[str, ...] | None = None,
    lookback_days: int = 400,
) -> dict[str, Any]:
    """Refresh local qlib data before inference so scheduled runs do not rely on manual repair."""
    try:
        return QlibRuntimeDataRefreshService().refresh_universes(
            target_date=target_date,
            universes=universes,
            lookback_days=lookback_days,
        )
    finally:
        _reset_qlib_runtime_state()


def _refresh_qlib_runtime_data_for_codes(
    *,
    target_date: date,
    stock_codes: list[str] | tuple[str, ...] | set[str],
    universe_id: str = "scoped_portfolios",
    lookback_days: int = 120,
) -> dict[str, Any]:
    """Refresh qlib data for explicit account/portfolio stock scopes."""
    try:
        return QlibRuntimeDataRefreshService().refresh_codes(
            target_date=target_date,
            stock_codes=stock_codes,
            universe_id=universe_id,
            lookback_days=lookback_days,
        )
    finally:
        _reset_qlib_runtime_state()


def _maybe_refresh_qlib_runtime_data_for_prediction(
    *,
    trade_date: date,
    universe_id: str,
    pool_scope: AlphaPoolScope | None = None,
    latest_qlib_data_date: date | None,
) -> tuple[date | None, dict[str, Any]]:
    """Try refreshing local qlib data inline before prediction when the request is newer."""
    metadata: dict[str, Any] = {}
    if latest_qlib_data_date is not None:
        metadata["qlib_data_latest_date_before_refresh"] = latest_qlib_data_date.isoformat()

    if latest_qlib_data_date is not None and latest_qlib_data_date >= trade_date:
        metadata["qlib_runtime_refresh_status"] = "skipped"
        metadata["qlib_runtime_refresh_reason"] = "already_up_to_date"
        return latest_qlib_data_date, metadata

    try:
        if pool_scope is not None and getattr(pool_scope, "instrument_codes", None):
            refresh_summary = _refresh_qlib_runtime_data_for_codes(
                target_date=trade_date,
                stock_codes=list(getattr(pool_scope, "instrument_codes", ()) or ()),
                universe_id=getattr(pool_scope, "universe_id", None) or universe_id,
                lookback_days=120,
            )
        else:
            refresh_summary = _refresh_qlib_runtime_data(
                target_date=trade_date,
                universes=[universe_id],
                lookback_days=400,
            )
    except Exception as exc:
        metadata["qlib_runtime_refresh_status"] = "failed"
        metadata["qlib_runtime_refresh_error"] = str(exc)
        return latest_qlib_data_date, metadata

    metadata["qlib_runtime_refresh_status"] = str(refresh_summary.get("status") or "unknown")
    metadata["qlib_runtime_refresh_summary"] = _make_json_safe(refresh_summary)

    try:
        latest_after_refresh = _get_qlib_data_latest_date()
    except Exception as exc:
        metadata["qlib_runtime_refresh_post_check_error"] = str(exc)
        return latest_qlib_data_date, metadata

    if latest_after_refresh is not None:
        metadata["qlib_data_latest_date_after_refresh"] = latest_after_refresh.isoformat()
    return latest_after_refresh, metadata


@typed_shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def qlib_predict_scores(
    self: BoundTask,
    universe_id: str,
    intended_trade_date: str,
    top_n: int = 30,
    scope_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Qlib 推理任务（运行在 qlib_infer 队列）

    1. 加载激活的模型
    2. 准备数据
    3. 执行预测
    4. 结果写入 AlphaScoreCache

    Args:
        self: Celery task 实例
        universe_id: 股票池标识
        intended_trade_date: 计划交易日期 (ISO 格式)
        top_n: 返回前 N 只

    """
    try:
        logger.info(
            f"开始 Qlib 推理: universe={universe_id}, " f"date={intended_trade_date}, top_n={top_n}"
        )
        pool_scope = AlphaPoolScope.from_dict(scope_payload) if scope_payload else None

        # Qlib inference is a decision-facing current-data path.  Do not let
        # the first calendar probe or the infrastructure runtime silently use
        # a legacy/default provider URI when Config Center has no usable typed
        # snapshot.
        runtime_qlib = _get_runtime_qlib_config()
        _require_usable_qlib_runtime(runtime_qlib)
        runtime_metadata = {
            "qlib_runtime_status": str(runtime_qlib.get("status") or "active"),
            "qlib_runtime_source": str(
                runtime_qlib.get("source") or "config_center_runtime_profile"
            ),
        }

        # 1. 获取激活的模型
        active_model = get_qlib_model_registry_repository().get_active_model()

        if not active_model:
            raise Exception("没有激活的 Qlib 模型")

        # 2. 准备数据
        trade_date = date.fromisoformat(intended_trade_date)
        asof_date = trade_date  # 信号日期等于交易日期（实际中可能需要调整）
        refresh_metadata: dict[str, Any] = {}

        latest_qlib_data_date = None
        try:
            latest_qlib_data_date = _get_qlib_data_latest_date()
        except Exception as exc:
            runtime_failure_reason = _build_qlib_runtime_failure_reason(exc)
            fallback_result = _reuse_latest_qlib_cache(
                active_model=active_model,
                universe_id=pool_scope.universe_id if pool_scope else universe_id,
                trade_date=trade_date,
                top_n=top_n,
                failure_reason=runtime_failure_reason,
                pool_scope=pool_scope,
                extra_metadata={
                    "qlib_data_latest_date": None,
                    "qlib_runtime_error": str(exc),
                    **runtime_metadata,
                },
            )
            if fallback_result is not None:
                logger.warning(
                    "读取 Qlib 本地数据状态失败，已前推历史缓存: universe=%s, date=%s, error=%s",
                    universe_id,
                    intended_trade_date,
                    exc,
                )
                return fallback_result
            raise RuntimeError(runtime_failure_reason) from exc

        if latest_qlib_data_date is None or latest_qlib_data_date < trade_date:
            latest_qlib_data_date, refresh_metadata = (
                _maybe_refresh_qlib_runtime_data_for_prediction(
                    trade_date=trade_date,
                    universe_id=pool_scope.universe_id if pool_scope else universe_id,
                    pool_scope=pool_scope,
                    latest_qlib_data_date=latest_qlib_data_date,
                )
            )

        outdated_reason = None
        if latest_qlib_data_date is None:
            outdated_reason = "本地 Qlib 数据目录为空，无法执行实时推理"
        elif trade_date > latest_qlib_data_date + timedelta(days=10):
            outdated_reason = (
                f"本地 Qlib 数据最新交易日为 {latest_qlib_data_date.isoformat()}，"
                f"早于请求交易日 {trade_date.isoformat()}，请先同步 Qlib 数据"
            )
        if outdated_reason:
            fallback_result = _reuse_latest_qlib_cache(
                active_model=active_model,
                universe_id=pool_scope.universe_id if pool_scope else universe_id,
                trade_date=trade_date,
                top_n=top_n,
                failure_reason=outdated_reason,
                pool_scope=pool_scope,
                extra_metadata={
                    **refresh_metadata,
                    "qlib_data_latest_date": (
                        latest_qlib_data_date.isoformat() if latest_qlib_data_date else None
                    ),
                    **runtime_metadata,
                },
            )
            if fallback_result is not None:
                logger.warning(
                    "Qlib 数据未更新到请求日期，已前推历史缓存: universe=%s, date=%s, reason=%s",
                    universe_id,
                    intended_trade_date,
                    outdated_reason,
                )
                return fallback_result

        execution_trade_date = trade_date
        execution_metadata: dict[str, object] = {
            "requested_trade_date": trade_date.isoformat(),
            **runtime_metadata,
            **refresh_metadata,
        }
        if latest_qlib_data_date is not None:
            execution_metadata["qlib_data_latest_date"] = latest_qlib_data_date.isoformat()
            execution_trade_date, resolved_metadata = resolve_effective_trade_date(
                trade_date,
                latest_qlib_data_date,
                max_forward_gap_days=10,
            )
            execution_metadata.update(resolved_metadata)
        asof_date = execution_trade_date

        # 3. 执行预测（使用 Qlib）
        try:
            scores_data = _execute_qlib_prediction(
                active_model=active_model,
                universe_id=pool_scope.universe_id if pool_scope else universe_id,
                trade_date=execution_trade_date,
                top_n=top_n,
                pool_scope=pool_scope,
            )
        except Exception as exc:
            fallback_result = _reuse_latest_qlib_cache(
                active_model=active_model,
                universe_id=pool_scope.universe_id if pool_scope else universe_id,
                trade_date=trade_date,
                top_n=top_n,
                failure_reason=str(exc),
                pool_scope=pool_scope,
                extra_metadata={
                    "qlib_data_latest_date": (
                        latest_qlib_data_date.isoformat() if latest_qlib_data_date else None
                    ),
                    **execution_metadata,
                },
            )
            if fallback_result is not None:
                logger.warning(
                    "Qlib 实时推理失败，已前推历史缓存: universe=%s, date=%s, error=%s",
                    universe_id,
                    intended_trade_date,
                    exc,
                )
                return fallback_result
            raise

        if not scores_data:
            fallback_result = _reuse_latest_qlib_cache(
                active_model=active_model,
                universe_id=pool_scope.universe_id if pool_scope else universe_id,
                trade_date=trade_date,
                top_n=top_n,
                failure_reason="Qlib 预测未返回任何评分",
                pool_scope=pool_scope,
                extra_metadata={
                    "qlib_data_latest_date": (
                        latest_qlib_data_date.isoformat() if latest_qlib_data_date else None
                    ),
                    **execution_metadata,
                },
            )
            if fallback_result is not None:
                logger.warning(
                    "Qlib 预测为空，已前推历史缓存: universe=%s, date=%s",
                    universe_id,
                    intended_trade_date,
                )
                return fallback_result
            raise RuntimeError("Qlib 预测未返回任何评分")

        # 4. 写入缓存
        cache, created = _upsert_qlib_cache(
            active_model=active_model,
            universe_id=pool_scope.universe_id if pool_scope else universe_id,
            trade_date=trade_date,
            asof_date=asof_date,
            scores_data=scores_data,
            status="available",
            metrics_snapshot=execution_metadata,
            pool_scope=pool_scope,
        )

        action = "创建" if created else "更新"
        logger.info(
            f"Qlib 推理完成: {action}缓存 {universe_id}@{intended_trade_date}, "
            f"共 {len(scores_data)} 只股票"
        )
        workspace_refresh_metadata = sync_default_workspace_after_alpha_update(
            pool_scope.universe_id if pool_scope else universe_id, trade_date, pool_scope
        )

        return {
            "status": "success",
            "universe_id": universe_id,
            "scope_hash": pool_scope.scope_hash if pool_scope else None,
            "trade_date": intended_trade_date,
            "cache_created": created,
            "stock_count": len(scores_data),
            "model_artifact_hash": active_model.artifact_hash,
            **execution_metadata,
            **workspace_refresh_metadata,
        }

    except Exception as exc:
        logger.error(f"Qlib 推理失败: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60) from exc


@typed_shared_task(
    bind=True,
    max_retries=1,
    time_limit=3600,
    soft_time_limit=3300,
)
def qlib_train_model(
    self: BoundTask,
    model_name: str,
    model_type: str,
    train_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Qlib 训练任务（运行在 qlib_train 队列）

    1. 准备数据
    2. 训练模型
    3. 评估指标
    4. 保存 artifact
    5. 写入 Registry

    Args:
        self: Celery task 实例
        model_name: 模型名称
        model_type: 模型类型 (LGBModel/LSTMModel/TransformerModel)
        train_config: 训练配置字典

    Returns:
        训练结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_train_model
        >>> qlib_train_model.delay(
        ...     model_name="mlp_csi300",
        ...     model_type="LGBModel",
        ...     train_config={"learning_rate": 0.01}
        ... )
    """
    try:
        logger.info(f"开始 Qlib 训练: {model_name} ({model_type})")
        registry_repo = get_qlib_model_registry_repository()
        runtime_qlib = _get_runtime_qlib_config()
        training_run_repo = get_qlib_training_run_repository()
        training_run_id = str(train_config.get("training_run_id") or "").strip()
        _require_usable_qlib_runtime(runtime_qlib)
        if training_run_id:
            training_run_repo.mark_running(
                run_id=training_run_id,
                celery_task_id=getattr(self.request, "id", "") or "",
            )

        # 解析训练配置
        universe = train_config.get("universe") or runtime_qlib.get("default_universe", "csi300")
        end_date = train_config.get("end_date")
        model_path = train_config.get("model_path") or runtime_qlib.get("model_path")
        if not isinstance(model_path, str) or not model_path.strip():
            raise RuntimeError("Qlib runtime blocked: runtime_config_snapshot_unavailable")
        if "activate" in train_config:
            activate_after_train = bool(train_config.get("activate", False))
        else:
            activate_after_train = bool(runtime_qlib.get("allow_auto_activate", False))
        feature_set_id = _normalize_qlib_feature_set_id(
            train_config.get("feature_set_id")
            or runtime_qlib.get("default_feature_set_id", "alpha360")
        )
        label_id = train_config.get("label_id") or runtime_qlib.get(
            "default_label_id",
            "return_5d",
        )

        # 计算数据版本
        data_version = end_date or timezone.now().strftime("%Y-%m-%d")

        # 1. 准备数据
        logger.info("  准备训练数据...")
        # 数据准备逻辑（使用 Qlib API）

        # 2. 训练模型
        logger.info(f"  训练模型 ({model_type})...")
        effective_train_config = {
            **train_config,
            "universe": universe,
            "feature_set_id": feature_set_id,
            "label_id": label_id,
        }
        model = _train_qlib_model(model_type, effective_train_config)

        # 3. 评估指标
        logger.info("  评估模型...")
        metrics = _evaluate_model_metrics(model, universe, effective_train_config)

        # 4. 生成 artifact hash
        artifact_hash = _calculate_artifact_hash(
            f"{model_name}_{model_type}_{universe}_{data_version}"
        )

        # 5. 保存 artifact
        logger.info("  保存模型 artifact...")
        artifact_dir = _save_model_artifact(
            model=model,
            model_name=model_name,
            artifact_hash=artifact_hash,
            model_path=model_path,
            train_config=effective_train_config,
            metrics=metrics,
        )

        # 6. 写入 Registry
        logger.info("  写入模型注册表...")
        registry_repo.create_model_entry(
            model_name=model_name,
            artifact_hash=artifact_hash,
            model_type=model_type,
            universe=universe,
            train_config=effective_train_config,
            feature_set_id=feature_set_id,
            label_id=label_id,
            data_version=data_version,
            ic=metrics.get("ic"),
            icir=metrics.get("icir"),
            rank_ic=metrics.get("rank_ic"),
            model_path=str(artifact_dir / "model.pkl"),
            is_active=False,  # 需要手动激活
        )

        if activate_after_train:
            registry_repo.activate_model(
                artifact_hash=artifact_hash,
                activated_by="qlib_train_task",
            )

        if training_run_id:
            training_run_repo.mark_succeeded(
                run_id=training_run_id,
                result_model_name=model_name,
                result_artifact_hash=artifact_hash,
                result_metrics=dict(metrics),
                registry_result={
                    "artifact_hash": artifact_hash,
                    "activated": activate_after_train,
                    "model_path": str(artifact_dir / "model.pkl"),
                },
            )

        logger.info(f"Qlib 训练完成: {model_name}")
        logger.info(f"  Artifact Hash: {artifact_hash[:12]}...")
        logger.info(f"  IC: {metrics.get('ic', 'N/A')}")
        logger.info(f"  ICIR: {metrics.get('icir', 'N/A')}")

        return {
            "status": "success",
            "model_name": model_name,
            "model_type": model_type,
            "artifact_hash": artifact_hash,
            "activated": activate_after_train,
            "ic": metrics.get("ic"),
            "icir": metrics.get("icir"),
        }

    except Exception as exc:
        logger.error(f"Qlib 训练失败: {exc}", exc_info=True)
        training_run_id = str(train_config.get("training_run_id") or "").strip()
        if training_run_id:
            try:
                get_qlib_training_run_repository().mark_failed(
                    run_id=training_run_id,
                    error_message=str(exc),
                )
            except Exception:
                logger.exception("回写 QlibTrainingRun FAILED 状态失败: run_id=%s", training_run_id)
        raise


@typed_shared_task(
    bind=True,
    max_retries=1,
    time_limit=3600,
    soft_time_limit=3300,
)
def qlib_evaluate_model(
    self: BoundTask,
    model_artifact_hash: str,
) -> dict[str, Any]:
    """
    Qlib 模型评估任务

    计算模型的 IC/ICIR/Rank IC 等指标。

    Args:
        self: Celery task 实例
        model_artifact_hash: 模型哈希

    Returns:
        评估结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_evaluate_model
        >>> qlib_evaluate_model.delay("abc123...")
    """
    try:
        from datetime import timedelta

        from django.utils import timezone as tz

        logger.info(f"开始评估模型: {model_artifact_hash}")

        registry_repo = get_qlib_model_registry_repository()
        model = registry_repo.get_by_artifact_hash(model_artifact_hash)

        # 计算 IC/ICIR：取最近 60 天缓存数据评估
        end_date = tz.now().date()
        start_date = end_date - timedelta(days=60)

        metrics = evaluate_model_from_cache(
            model_artifact_hash=model_artifact_hash,
            universe_id=model.universe,
            start_date=start_date,
            end_date=end_date,
        )

        model = registry_repo.update_metrics(
            artifact_hash=model_artifact_hash,
            ic=metrics.ic,
            icir=metrics.icir,
            rank_ic=metrics.rank_ic,
        )

        logger.info(
            f"模型评估完成: {model_artifact_hash}, " f"IC={metrics.ic}, ICIR={metrics.icir}"
        )

        return {
            "status": "success",
            "model_artifact_hash": model_artifact_hash,
            "ic": float(model.ic) if model.ic else None,
            "icir": float(model.icir) if model.icir else None,
        }

    except Exception as exc:
        logger.error(f"模型评估失败: {exc}", exc_info=True)
        raise


@typed_shared_task(
    name="alpha.qlib_refresh_cache",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    time_limit=3600,
    soft_time_limit=3300,
)
def qlib_refresh_cache(
    self: BoundTask,
    universe_id: str,
    days_back: int = 7,
    top_n: int = 30,
) -> dict[str, Any]:
    """
    刷新 Qlib 缓存任务

    为指定日期范围内的日期补齐缓存。

    Args:
        universe_id: 股票池标识
        days_back: 回溯天数
        top_n: 每日缓存保留的推荐数量

    Returns:
        刷新结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_refresh_cache
        >>> qlib_refresh_cache.delay("csi300", days_back=7)
    """
    try:
        from datetime import timedelta

        logger.info(f"开始刷新缓存: {universe_id}, 回溯 {days_back} 天, top_n={top_n}")

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        results = []
        current_date = start_date

        while current_date <= end_date:
            # 触发推理任务（仅工作日）
            if current_date.weekday() < 5:  # 周一到周五
                result = qlib_predict_scores.delay(
                    universe_id,
                    current_date.isoformat(),
                    top_n,
                )
                results.append({"date": current_date.isoformat(), "task_id": result.id})

            current_date += timedelta(days=1)

        logger.info(f"已触发 {len(results)} 个推理任务")

        return {
            "status": "success",
            "universe_id": universe_id,
            "top_n": top_n,
            "tasks_triggered": len(results),
            "tasks": results,
        }

    except Exception as exc:
        logger.error(f"刷新缓存失败: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}


@typed_shared_task(
    name="alpha.qlib_daily_inference",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    time_limit=3600,
    soft_time_limit=3300,
)
def qlib_daily_inference(
    self: BoundTask,
    universe_id: str = "csi300",
    top_n: int = 30,
    refresh_data: bool = True,
    refresh_universes: str | list[str] | tuple[str, ...] | None = None,
    lookback_days: int = 400,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """
    每日触发 Qlib 推理任务。

    用于 Celery Beat 无参调度入口，自动使用当天日期，并先刷新本地 Qlib 日线。
    """
    trade_date_obj = (
        date.fromisoformat(trade_date) if trade_date else _resolve_recent_closed_trade_date()
    )
    refresh_result: dict[str, Any] = {"status": "skipped", "reason": "refresh_disabled"}
    if refresh_data:
        try:
            refresh_result = _refresh_qlib_runtime_data(
                target_date=trade_date_obj,
                universes=refresh_universes or universe_id,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            logger.error("Qlib 每日数据刷新失败，继续尝试推理: %s", exc, exc_info=True)
            refresh_result = {
                "status": "failed",
                "error": str(exc),
            }

    trade_date = trade_date_obj.isoformat()
    result = qlib_predict_scores.delay(universe_id, trade_date, top_n)
    return {
        "status": "queued",
        "task_id": result.id,
        "universe_id": universe_id,
        "trade_date": trade_date,
        "top_n": top_n,
        "refresh_result": refresh_result,
    }


@typed_shared_task(name="apps.alpha.application.tasks.qlib_daily_inference")
def qlib_daily_inference_alias(
    universe_id: str = "csi300",
    top_n: int = 30,
    refresh_data: bool = True,
    refresh_universes: str | list[str] | tuple[str, ...] | None = None,
    lookback_days: int = 400,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Backwards-compatible alias for database/beat task paths."""
    return qlib_daily_inference.run(
        universe_id=universe_id,
        top_n=top_n,
        refresh_data=refresh_data,
        refresh_universes=refresh_universes,
        lookback_days=lookback_days,
        trade_date=trade_date,
    )


@typed_shared_task(
    name="alpha.qlib_daily_scoped_inference",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    time_limit=3600,
    soft_time_limit=3300,
)
def qlib_daily_scoped_inference(
    self: BoundTask,
    top_n: int = 30,
    portfolio_limit: int = 0,
    pool_mode: str = "price_covered",
    refresh_data: bool = True,
    lookback_days: int = 120,
    trade_date: str | None = None,
    only_missing: bool = True,
) -> dict[str, Any]:
    """Queue daily scoped Qlib inference for active portfolios used by the dashboard."""
    from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver

    target_trade_date = (
        date.fromisoformat(trade_date) if trade_date else _resolve_recent_closed_trade_date()
    )
    active_model = get_qlib_model_registry_repository().get_active_model()
    if active_model is None:
        return {
            "status": "skipped",
            "reason": "no_active_model",
            "trade_date": target_trade_date.isoformat(),
        }

    cache_repository = get_alpha_score_cache_repository()
    portfolio_refs = get_alpha_pool_data_repository().list_active_portfolio_refs(
        limit=portfolio_limit
    )
    resolver = PortfolioAlphaPoolResolver()

    resolved_scopes: list[tuple[dict[str, Any], AlphaPoolScope]] = []
    scoped_codes: set[str] = set()
    seen_scope_keys: set[tuple[str, str | None]] = set()
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    fresh_cache_count = 0
    for ref in portfolio_refs:
        try:
            resolved = resolver.resolve(
                user_id=int(ref["user_id"]),
                portfolio_id=int(ref["portfolio_id"]),
                trade_date=target_trade_date,
                pool_mode=pool_mode,
            )
            if resolved.scope.pool_size == 0:
                skipped.append(
                    {
                        "portfolio_id": ref["portfolio_id"],
                        "reason": "empty_scope",
                    }
                )
                continue
            scope_key = (resolved.scope.universe_id, resolved.scope.scope_hash)
            if scope_key in seen_scope_keys:
                skipped.append(
                    {
                        "portfolio_id": ref["portfolio_id"],
                        "reason": "duplicate_scope",
                        "scope_hash": resolved.scope.scope_hash,
                    }
                )
                continue
            seen_scope_keys.add(scope_key)
            if only_missing:
                existing_cache = cache_repository.get_qlib_cache_for_trade_date(
                    universe_id=resolved.scope.universe_id,
                    trade_date=target_trade_date,
                    model_artifact_hash=getattr(active_model, "artifact_hash", None),
                    scope_hash=resolved.scope.scope_hash,
                )
                if existing_cache is not None and _cache_is_fresh_for_trade_date(
                    existing_cache, target_trade_date
                ):
                    fresh_cache_count += 1
                    skipped.append(
                        {
                            "portfolio_id": ref["portfolio_id"],
                            "reason": "fresh_cache_exists",
                            "scope_hash": resolved.scope.scope_hash,
                            "asof_date": existing_cache.asof_date.isoformat(),
                        }
                    )
                    continue
            resolved_scopes.append((ref, resolved.scope))
            scoped_codes.update(
                normalized
                for normalized in (
                    normalize_stock_code(code)
                    for code in getattr(resolved.scope, "instrument_codes", ()) or ()
                )
                if normalized
            )
        except Exception as exc:
            logger.error(
                "Qlib scoped inference resolve failed: portfolio_id=%s, error=%s",
                ref.get("portfolio_id"),
                exc,
                exc_info=True,
            )
            skipped.append(
                {
                    "portfolio_id": ref.get("portfolio_id"),
                    "reason": str(exc),
                }
            )

    refresh_result: dict[str, Any] = {"status": "skipped", "reason": "refresh_disabled"}
    if refresh_data and scoped_codes and resolved_scopes:
        try:
            refresh_result = _refresh_qlib_runtime_data_for_codes(
                target_date=target_trade_date,
                stock_codes=scoped_codes,
                universe_id="scoped_portfolios",
                lookback_days=lookback_days,
            )
        except Exception as exc:
            logger.error(
                "Qlib scoped data refresh failed, continue queueing inference: %s",
                exc,
                exc_info=True,
            )
            refresh_result = {
                "status": "failed",
                "error": str(exc),
                "stock_count": len(scoped_codes),
            }

    for ref, scope in resolved_scopes:
        try:
            task = qlib_predict_scores.delay(
                scope.universe_id,
                target_trade_date.isoformat(),
                top_n,
                scope_payload=scope.to_dict(),
            )
            queued.append(
                {
                    "portfolio_id": ref["portfolio_id"],
                    "user_id": ref["user_id"],
                    "scope_hash": scope.scope_hash,
                    "universe_id": scope.universe_id,
                    "pool_size": scope.pool_size,
                    "task_id": task.id,
                }
            )
        except Exception as exc:
            logger.error(
                "Qlib scoped inference queue failed: portfolio_id=%s, error=%s",
                ref.get("portfolio_id"),
                exc,
                exc_info=True,
            )
            skipped.append(
                {
                    "portfolio_id": ref.get("portfolio_id"),
                    "reason": str(exc),
                }
            )

    status = "queued" if queued else "skipped"
    reason = None
    if status == "skipped":
        if fresh_cache_count and not resolved_scopes:
            reason = "all_scopes_fresh"
        elif not resolved_scopes:
            reason = "no_scopes_to_queue"

    return {
        "status": status,
        "reason": reason,
        "trade_date": target_trade_date.isoformat(),
        "top_n": top_n,
        "portfolio_count": len(portfolio_refs),
        "scope_count": len(seen_scope_keys),
        "scoped_stock_count": len(scoped_codes),
        "refresh_result": refresh_result,
        "queued_count": len(queued),
        "fresh_cache_count": fresh_cache_count,
        "skipped_count": len(skipped),
        "queued": queued,
        "skipped": skipped,
    }


@typed_shared_task(name="apps.alpha.application.tasks.qlib_daily_scoped_inference")
def qlib_daily_scoped_inference_alias(
    top_n: int = 30,
    portfolio_limit: int = 0,
    pool_mode: str = "price_covered",
    refresh_data: bool = True,
    lookback_days: int = 120,
    trade_date: str | None = None,
    only_missing: bool = True,
) -> dict[str, Any]:
    """Backwards-compatible alias for database/beat task paths."""
    return qlib_daily_scoped_inference.run(
        top_n=top_n,
        portfolio_limit=portfolio_limit,
        pool_mode=pool_mode,
        refresh_data=refresh_data,
        lookback_days=lookback_days,
        trade_date=trade_date,
        only_missing=only_missing,
    )


@typed_shared_task(name="apps.alpha.application.tasks.qlib_refresh_runtime_data_task")
def qlib_refresh_runtime_data_task(
    *,
    target_date: str,
    universes: list[str] | tuple[str, ...] | str | None = None,
    lookback_days: int = 400,
) -> dict[str, Any]:
    """Refresh local qlib data for named universes from the ops page."""
    trade_date = date.fromisoformat(target_date)
    summary = _refresh_qlib_runtime_data(
        target_date=trade_date,
        universes=universes,
        lookback_days=lookback_days,
    )
    return {
        "status": "success" if summary.get("status") == "success" else summary.get("status"),
        "mode": "universes",
        "summary": summary,
    }


@typed_shared_task(name="apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task")
def qlib_refresh_runtime_data_for_codes_task(
    *,
    target_date: str,
    portfolio_ids: list[int] | tuple[int, ...] | None = None,
    all_active_portfolios: bool = False,
    pool_mode: str = "price_covered",
    lookback_days: int = 120,
) -> dict[str, Any]:
    """Refresh qlib data for active or selected portfolio-driven stock scopes."""
    from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver

    trade_date = date.fromisoformat(target_date)
    resolver = PortfolioAlphaPoolResolver()
    requested_portfolio_ids = [int(item) for item in portfolio_ids or []]
    portfolio_refs = collect_portfolio_refs_for_refresh(
        portfolio_ids=requested_portfolio_ids,
        all_active_portfolios=all_active_portfolios,
    )

    scoped_codes: set[str] = set()
    resolved_scopes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    requested_portfolio_set = set(requested_portfolio_ids)
    seen_portfolio_ids: set[int] = set()

    for ref in portfolio_refs:
        portfolio_id = int(ref["portfolio_id"])
        seen_portfolio_ids.add(portfolio_id)
        try:
            resolved = resolver.resolve(
                user_id=int(ref["user_id"]),
                portfolio_id=portfolio_id,
                trade_date=trade_date,
                pool_mode=pool_mode,
            )
            scope_codes = list(getattr(resolved.scope, "instrument_codes", ()) or ())
            if not scope_codes:
                skipped.append({"portfolio_id": portfolio_id, "reason": "empty_scope"})
                continue
            scoped_codes.update(scope_codes)
            resolved_scopes.append(
                {
                    "portfolio_id": resolved.portfolio_id,
                    "portfolio_name": resolved.portfolio_name,
                    "scope_hash": resolved.scope.scope_hash,
                    "scope_label": resolved.scope.display_label,
                    "pool_size": resolved.scope.pool_size,
                    "pool_mode": resolved.scope.pool_mode,
                }
            )
        except Exception as exc:
            skipped.append({"portfolio_id": portfolio_id, "reason": str(exc)})

    if not all_active_portfolios:
        missing_portfolio_ids = sorted(requested_portfolio_set - seen_portfolio_ids)
        skipped.extend(
            {
                "portfolio_id": portfolio_id,
                "reason": "portfolio_not_active_or_not_found",
            }
            for portfolio_id in missing_portfolio_ids
        )

    summary = _refresh_qlib_runtime_data_for_codes(
        target_date=trade_date,
        stock_codes=scoped_codes,
        universe_id="scoped_portfolios",
        lookback_days=lookback_days,
    )
    return {
        "status": "success" if summary.get("status") == "success" else summary.get("status"),
        "mode": "scoped_codes",
        "portfolio_count": len(resolved_scopes),
        "pool_mode": pool_mode,
        "summary": {
            **summary,
            "requested_portfolio_ids": requested_portfolio_ids,
            "all_active_portfolios": all_active_portfolios,
            "resolved_scopes": resolved_scopes,
            "skipped": skipped,
        },
    }


@typed_shared_task(name="apps.alpha.application.tasks.qlib_refresh_cache")
def qlib_refresh_cache_alias(
    universe_id: str = "csi300",
    days_back: int = 7,
    top_n: int = 30,
) -> dict[str, Any]:
    """Backwards-compatible alias for database/beat task paths."""
    return qlib_refresh_cache.run(universe_id=universe_id, days_back=days_back, top_n=top_n)


# ========================================================================
# 辅助函数
# ========================================================================
