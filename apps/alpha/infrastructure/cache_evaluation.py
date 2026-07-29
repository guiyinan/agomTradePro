"""
Alpha Cache Evaluation Functions

从缓存的预测结果评估 Alpha 模型。
"""

import logging
from datetime import date, timedelta

import numpy as np

from apps.alpha.infrastructure.cache_code_parser import extract_cached_score_code
from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from shared.infrastructure.model_evaluation import (
    IC_Calculator,
    ModelEvaluator,
    ModelMetrics,
    RollingMetrics,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def _validate_evaluation_request(
    *,
    model_artifact_hash: str,
    universe_id: str,
    start_date: date,
    end_date: date,
) -> None:
    """Reject malformed cache-evaluation selectors before querying storage."""

    for name, value, limit in (
        ("model_artifact_hash", model_artifact_hash, 128),
        ("universe_id", universe_id, 64),
    ):
        if not value or len(value) > limit or any(ord(character) < 32 for character in value):
            raise ValueError(f"invalid {name}")
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise ValueError("start_date and end_date must be dates")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")


def _get_actual_returns(
    stock_codes: set[str],
    trade_date: date,
    horizon: int = 1,
) -> dict[str, float]:
    """
    获取股票在 trade_date 后 horizon 天的实际收益率

    Args:
        stock_codes: 股票代码集合
        trade_date: 预测日期
        horizon: 持有期（天）

    Returns:
        {stock_code: 实际收益率}
    """
    try:
        from apps.equity.infrastructure.adapters import TushareStockAdapter

        adapter = TushareStockAdapter()
    except Exception as exc:
        logger.warning(
            "无法初始化 TushareStockAdapter (error_type=%s)",
            type(exc).__name__,
        )
        return {}

    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 252:
        raise ValueError("horizon must be between 1 and 252")
    returns: dict[str, float] = {}
    end_date = trade_date + timedelta(days=horizon + 10)  # 多取几天以覆盖非交易日

    for code in stock_codes:
        try:
            df = adapter.fetch_daily_data(code, trade_date, end_date)
            if df is None or df.empty or len(df) < 2:
                continue

            # pct_chg 是百分比，转为小数
            # 取 trade_date 之后的 horizon 天累积收益
            daily_returns = df["pct_chg"].values[: horizon + 1] / 100.0
            if len(daily_returns) >= 2:
                # 跳过 trade_date 当天，取后续 horizon 天
                future_returns = daily_returns[1 : horizon + 1]
                if len(future_returns) > 0:
                    cumulative_return = safe_float(np.prod(1 + future_returns) - 1)
                    if cumulative_return is not None:
                        returns[code] = cumulative_return

        except Exception as exc:
            logger.debug(
                "获取股票收益率失败 (code=%s, error_type=%s)",
                code,
                type(exc).__name__,
            )
            continue

    return returns


def evaluate_model_from_cache(
    model_artifact_hash: str, universe_id: str, start_date: date, end_date: date
) -> ModelMetrics:
    """
    从缓存的预测结果评估模型

    Args:
        model_artifact_hash: 模型哈希
        universe_id: 股票池
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        模型指标
    """
    _validate_evaluation_request(
        model_artifact_hash=model_artifact_hash,
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
    )
    # 获取缓存数据
    caches = AlphaScoreCacheModel.objects.filter(
        universe_id=universe_id,
        provider_source="qlib",
        model_artifact_hash=model_artifact_hash,
        intended_trade_date__gte=start_date,
        intended_trade_date__lte=end_date,
    ).order_by("intended_trade_date")

    if not caches.exists():
        logger.warning("没有找到匹配的模型缓存")
        return ModelMetrics()

    evaluator = ModelEvaluator()

    # 收集所有预测和实际收益
    all_predictions: dict[str, float] = {}
    all_targets: dict[str, float] = {}
    all_returns: dict[str, float] = {}

    # 按日期收集股票代码，批量获取真实收益
    for cache in caches:
        stock_codes = set()
        for stock_data in cache.scores:
            stock_code = extract_cached_score_code(stock_data)
            if not stock_code:
                continue
            score = safe_float(stock_data.get("score")) if isinstance(stock_data, dict) else None
            if score is None:
                continue
            all_predictions[stock_code] = score
            stock_codes.add(stock_code)

        # 获取真实收益率
        actual_returns = _get_actual_returns(stock_codes, cache.intended_trade_date)

        for stock_code in stock_codes:
            if stock_code in actual_returns:
                actual_ret = safe_float(actual_returns[stock_code])
                if actual_ret is not None:
                    all_targets[stock_code] = actual_ret
                    all_returns[stock_code] = actual_ret

    # 过滤：只保留有真实收益的股票
    valid_codes = set(all_predictions.keys()) & set(all_targets.keys())
    if not valid_codes:
        logger.warning("没有获取到任何股票的真实收益率，无法评估模型")
        return ModelMetrics()

    filtered_predictions = {k: all_predictions[k] for k in valid_codes}
    filtered_targets = {k: all_targets[k] for k in valid_codes}
    filtered_returns = {k: all_returns[k] for k in valid_codes}

    logger.info(f"评估模型: {len(valid_codes)} 只股票有真实收益数据")

    # 评估
    return evaluator.evaluate_predictions(
        predictions=filtered_predictions, targets=filtered_targets, returns=filtered_returns
    )


def calculate_rolling_metrics(
    model_artifact_hash: str, universe_id: str, start_date: date, end_date: date, window: int = 20
) -> list[RollingMetrics]:
    """
    计算滚动指标

    Args:
        model_artifact_hash: 模型哈希
        universe_id: 股票池
        start_date: 开始日期
        end_date: 结束日期
        window: 滚动窗口

    Returns:
        滚动指标列表
    """
    _validate_evaluation_request(
        model_artifact_hash=model_artifact_hash,
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
    )
    if isinstance(window, bool) or not isinstance(window, int) or not 2 <= window <= 252:
        raise ValueError("window must be between 2 and 252")
    caches = AlphaScoreCacheModel.objects.filter(
        universe_id=universe_id,
        provider_source="qlib",
        model_artifact_hash=model_artifact_hash,
        intended_trade_date__gte=start_date,
        intended_trade_date__lte=end_date,
    ).order_by("intended_trade_date")

    # 按日期分组预测值
    date_scores: dict[date, dict[str, float]] = {}
    for cache in caches:
        trade_date = cache.intended_trade_date
        if trade_date not in date_scores:
            date_scores[trade_date] = {}
        for stock_data in cache.scores:
            if not isinstance(stock_data, dict):
                continue
            stock_code = extract_cached_score_code(stock_data)
            score = safe_float(stock_data.get("score"))
            if stock_code and score is not None:
                date_scores[trade_date][stock_code] = score

    # 获取每个日期的真实收益
    date_returns: dict[date, dict[str, float]] = {}
    for trade_date, scores in date_scores.items():
        actual = _get_actual_returns(set(scores.keys()), trade_date)
        if actual:
            date_returns[trade_date] = {
                code: parsed
                for code, value in actual.items()
                if (parsed := safe_float(value)) is not None
            }

    # 计算滚动 IC
    sorted_dates = sorted(date_scores.keys())
    if len(sorted_dates) < window:
        return []

    ic_calculator = IC_Calculator()
    rolling_metrics: list[RollingMetrics] = []
    ic_history: list[float] = []

    for i in range(window - 1, len(sorted_dates)):
        window_dates = sorted_dates[i - window + 1 : i + 1]

        window_preds = []
        window_targets = []

        for dt in window_dates:
            returns_for_date = date_returns.get(dt, {})
            for stock, score in date_scores[dt].items():
                if stock in returns_for_date:
                    window_preds.append(score)
                    window_targets.append(returns_for_date[stock])

        if len(window_preds) >= 5:
            ic = safe_float(
                ic_calculator.calculate_ic(np.array(window_preds), np.array(window_targets))
            )
            if ic is None:
                continue
            ic_history.append(ic)

            # 计算 IC MA 和 Std
            ic_arr = np.array(ic_history)
            ic_ma_5 = float(np.mean(ic_arr[-5:])) if len(ic_arr) >= 5 else None
            ic_std_20 = float(np.std(ic_arr[-20:])) if len(ic_arr) >= 20 else None

            rolling_metrics.append(
                RollingMetrics(date=window_dates[-1], ic=ic, ic_ma_5=ic_ma_5, ic_std_20=ic_std_20)
            )

    return rolling_metrics
