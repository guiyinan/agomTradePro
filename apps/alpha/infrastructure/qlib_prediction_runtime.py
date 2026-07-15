"""Qlib prediction, cache reuse, and scope inference runtime helpers."""

from __future__ import annotations

import logging
import pickle
from datetime import date

from apps.alpha.domain.entities import normalize_stock_code
from apps.alpha.infrastructure.providers import AlphaScoreCacheRepository
from apps.alpha.infrastructure.qlib_runtime_init import (
    _build_outdated_qlib_reason,
    _get_runtime_qlib_config,
    _install_qlib_pandas_compat,
    _make_json_safe,
    _normalize_qlib_instrument_list,
    _normalize_qlib_region,
    _resolve_qlib_handler_class,
    _resolve_qlib_model_path,
    _resolve_qlib_stock_list,
)
from apps.alpha.infrastructure.scientific_runtime import get_pandas

logger = logging.getLogger(__name__)


def get_alpha_score_cache_repository():
    """Return the concrete Alpha score cache repository."""
    return AlphaScoreCacheRepository()


def _upsert_qlib_cache(
    active_model,
    universe_id: str,
    trade_date: date,
    asof_date: date,
    scores_data: list[dict],
    status: str,
    metrics_snapshot: dict | None = None,
    pool_scope=None,
):
    """Persist a qlib cache row for the active model."""
    return get_alpha_score_cache_repository().upsert_qlib_cache(
        universe_id=universe_id,
        trade_date=trade_date,
        asof_date=asof_date,
        active_model=active_model,
        scores_data=_make_json_safe(scores_data),
        status=status,
        metrics_snapshot=_make_json_safe(metrics_snapshot),
        pool_scope=pool_scope,
    )


def _normalize_reused_scores(scores_data: list[dict], top_n: int) -> list[dict]:
    """Keep score payloads JSON-safe and re-rank after truncation."""
    normalized_scores: list[dict] = []
    for index, raw_score in enumerate(scores_data[:top_n], start=1):
        score_item = dict(raw_score)
        score_item["rank"] = index
        score_item["source"] = "qlib"
        normalized_scores.append(score_item)
    return normalized_scores


def _reuse_latest_qlib_cache(
    active_model,
    universe_id: str,
    trade_date: date,
    top_n: int,
    failure_reason: str,
    pool_scope=None,
    extra_metadata: dict | None = None,
) -> dict | None:
    """Forward-fill the latest qlib cache into today's active model slot when fresh inference fails."""
    cache_repository = get_alpha_score_cache_repository()
    latest_cache = cache_repository.get_latest_qlib_cache(
        universe_id=universe_id,
        model_artifact_hash=active_model.artifact_hash,
        scope_hash=getattr(pool_scope, "scope_hash", None),
    )
    reused_scores_data: list[dict] | None = None
    if latest_cache is None and pool_scope is not None:
        broader_cache_result = _find_broader_qlib_cache_for_scope(
            active_model=active_model,
            trade_date=trade_date,
            top_n=top_n,
            pool_scope=pool_scope,
        )
        if broader_cache_result is not None:
            latest_cache, reused_scores_data = broader_cache_result
    if latest_cache is None:
        return None

    scores_data = reused_scores_data or _normalize_reused_scores(latest_cache.scores or [], top_n)
    if not scores_data:
        return None

    metrics_snapshot = dict(latest_cache.metrics_snapshot or {})
    metrics_snapshot.update(
        {
            "fallback_mode": "forward_fill_latest_qlib_cache",
            "fallback_reason": failure_reason,
            "fallback_source_trade_date": latest_cache.intended_trade_date.isoformat(),
            "fallback_source_asof_date": latest_cache.asof_date.isoformat(),
        }
    )
    if reused_scores_data is not None:
        metrics_snapshot.update(
            {
                "scope_fallback": True,
                "scope_fallback_universe_id": latest_cache.universe_id,
                "scope_fallback_reason": (
                    f"账户池专属 Qlib cache 缺失，已使用 {latest_cache.universe_id} "
                    "的最近缓存并按当前账户池成分裁剪。"
                ),
            }
        )
    if extra_metadata:
        metrics_snapshot.update(extra_metadata)

    _, created = _upsert_qlib_cache(
        active_model=active_model,
        universe_id=universe_id,
        trade_date=trade_date,
        asof_date=latest_cache.asof_date,
        scores_data=scores_data,
        status="degraded",
        metrics_snapshot=metrics_snapshot,
        pool_scope=pool_scope,
    )

    return {
        "status": "success",
        "cache_status": "degraded",
        "fallback_used": True,
        "universe_id": universe_id,
        "trade_date": trade_date.isoformat(),
        "cache_created": created,
        "stock_count": len(scores_data),
        "model_artifact_hash": active_model.artifact_hash,
        "fallback_source_trade_date": latest_cache.intended_trade_date.isoformat(),
        "fallback_source_asof_date": latest_cache.asof_date.isoformat(),
        "scope_fallback_universe_id": (
            latest_cache.universe_id if reused_scores_data is not None else None
        ),
        **(extra_metadata or {}),
    }


def _find_broader_qlib_cache_for_scope(
    *,
    active_model,
    trade_date: date,
    top_n: int,
    pool_scope,
) -> tuple[object, list[dict]] | None:
    """Find a broader qlib cache row and trim it to the current scoped instrument set."""
    scope_codes = {
        normalize_stock_code(raw_code)
        for raw_code in getattr(pool_scope, "instrument_codes", ()) or ()
        if normalize_stock_code(raw_code)
    }
    if not scope_codes:
        return None

    broader_cache_result = get_alpha_score_cache_repository().find_broader_qlib_cache_for_scope(
        trade_date=trade_date,
        model_artifact_hash=active_model.artifact_hash,
        scope_hash=getattr(pool_scope, "scope_hash", None),
        allowed_codes=scope_codes,
    )
    if broader_cache_result is not None:
        broader_cache, filtered_scores = broader_cache_result
        normalized_scores = _normalize_reused_scores(filtered_scores, top_n)
        if normalized_scores:
            return broader_cache, normalized_scores
    return None


def _execute_qlib_prediction(
    active_model,
    universe_id: str,
    trade_date: date,
    top_n: int,
    pool_scope=None,
    outdated_reason_builder=None,
) -> list[dict]:
    """
    执行 Qlib 预测

    Args:
        active_model: 激活的模型实例
        universe_id: 股票池标识
        trade_date: 交易日期
        top_n: 返回前 N 只

    Returns:
        评分数据列表
    """
    outdated_reason = (outdated_reason_builder or _build_outdated_qlib_reason)(trade_date)
    if outdated_reason:
        raise RuntimeError(outdated_reason)

    try:
        # 尝试导入 Qlib
        pd = get_pandas()
        import qlib
        from qlib.data import D
        from qlib.data.dataset import DatasetH

        # 获取 Qlib 配置（优先从数据库读取）
        qlib_config = _get_runtime_qlib_config()

        if not qlib_config.get("enabled"):
            logger.warning("Qlib 未启用，跳过预测")
            return []

        _install_qlib_pandas_compat()

        provider_uri = qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data")
        region = _normalize_qlib_region(qlib_config.get("region", "CN"))

        # 初始化 Qlib（仅初始化一次）
        if not hasattr(_execute_qlib_prediction, "_qlib_initialized"):
            qlib.init(provider_uri=provider_uri, region=region)
            _execute_qlib_prediction._qlib_initialized = True
            logger.info(f"Qlib 已初始化: provider={provider_uri}, region={region}")

        # 加载模型
        model_path = _resolve_qlib_model_path(active_model, qlib_config)
        if not model_path.exists():
            logger.error(f"模型文件不存在: {model_path}")
            raise RuntimeError(f"模型文件不存在: {model_path}")

        with open(model_path, "rb") as f:
            model = pickle.load(f)

        if pool_scope is not None and getattr(pool_scope, "instrument_codes", None):
            stock_list = _normalize_qlib_instrument_list(list(pool_scope.instrument_codes))
        else:
            stock_list = _resolve_qlib_stock_list(
                D,
                universe_id=universe_id,
                start_time=f"{trade_date.year - 1}-01-01",
                end_time=trade_date.isoformat(),
            )

        handler_cls = _resolve_qlib_handler_class(getattr(active_model, "feature_set_id", None))

        # 准备预测数据
        handler_config = {
            "start_time": f"{trade_date.year - 1}-01-01",  # 使用过去一年的数据
            "end_time": trade_date.isoformat(),
            "fit_start_time": f"{trade_date.year - 1}-01-01",
            "fit_end_time": trade_date.isoformat(),
            "instruments": stock_list,
        }

        try:
            # 当前 qlib 版本要求通过 DatasetH 进行预测，而不是直接将 handler 传给模型。
            handler = handler_cls(**handler_config)
            dataset = DatasetH(
                handler=handler,
                segments={"test": (pd.Timestamp(trade_date), pd.Timestamp(trade_date))},
            )
            prediction = model.predict(dataset)

            # 处理预测结果
            if isinstance(prediction, pd.DataFrame):
                if prediction.empty:
                    logger.warning(f"预测结果为空: {universe_id}@{trade_date}")
                    raise RuntimeError(f"预测结果为空: {universe_id}@{trade_date}")
                if isinstance(prediction.index, pd.MultiIndex):
                    latest_date = prediction.index.get_level_values(0).max()
                    latest_prediction = prediction.xs(latest_date, level=0)
                    if isinstance(latest_prediction, pd.DataFrame):
                        scores_series = latest_prediction.iloc[:, 0]
                    else:
                        scores_series = latest_prediction
                else:
                    scores_series = (
                        prediction.iloc[:, 0] if prediction.shape[1] else prediction.iloc[-1]
                    )
            elif isinstance(prediction, pd.Series):
                scores_series = prediction
            elif isinstance(prediction, dict):
                scores_series = pd.Series(prediction)
            else:
                logger.warning(f"不支持的预测结果类型: {type(prediction)}")
                raise RuntimeError(f"不支持的预测结果类型: {type(prediction)}")

            # 转换为评分格式
            scores_data = []
            for stock, pred_score in scores_series.items():
                if pd.notna(pred_score):
                    normalized_code = normalize_stock_code(stock) or str(stock)
                    scores_data.append(
                        {
                            "code": normalized_code,
                            "score": float(pred_score),
                            "rank": 0,  # 稍后计算
                            "factors": {},
                            "source": "qlib",
                            "confidence": 0.8,
                            "asof_date": trade_date.isoformat(),
                            "intended_trade_date": trade_date.isoformat(),
                            "universe_id": universe_id,
                        }
                    )

            # 按评分排序
            scores_data.sort(key=lambda x: x["score"], reverse=True)

            # 更新排名
            for i, score in enumerate(scores_data[:top_n], 1):
                score["rank"] = i

            logger.info(f"Qlib 预测成功: {universe_id}@{trade_date}, 共 {len(scores_data)} 只股票")
            return scores_data[:top_n]

        except Exception as handler_error:
            logger.error(f"数据处理器或预测失败: {handler_error}", exc_info=True)
            raise RuntimeError(f"Qlib 预测失败: {handler_error}") from handler_error

    except ImportError as e:
        logger.error(f"Qlib 未安装，无法进行预测: {e}")
        raise RuntimeError("Qlib 未安装。请安装 qlib: pip install pyqlib") from e

    except Exception as e:
        logger.error(f"Qlib 预测失败: {e}", exc_info=True)
        raise RuntimeError(f"Qlib 预测失败: {e}") from e


upsert_qlib_cache = _upsert_qlib_cache
normalize_reused_scores = _normalize_reused_scores
reuse_latest_qlib_cache = _reuse_latest_qlib_cache
find_broader_qlib_cache_for_scope = _find_broader_qlib_cache_for_scope
execute_qlib_prediction = _execute_qlib_prediction
