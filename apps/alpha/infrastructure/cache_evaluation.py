"""
Alpha Cache Evaluation Functions

从缓存的预测结果评估 Alpha 模型。
"""

import logging
from datetime import date
from typing import List

import numpy as np

from shared.infrastructure.model_evaluation import (
    ModelMetrics,
    RollingMetrics,
    IC_Calculator,
    ModelEvaluator,
)
from apps.alpha.infrastructure.models import AlphaScoreCacheModel


logger = logging.getLogger(__name__)


def evaluate_model_from_cache(
    model_artifact_hash: str,
    universe_id: str,
    start_date: date,
    end_date: date
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
    # 获取缓存数据
    caches = AlphaScoreCacheModel.objects.filter(
        universe_id=universe_id,
        provider_source="qlib",
        model_artifact_hash=model_artifact_hash,
        intended_trade_date__gte=start_date,
        intended_trade_date__lte=end_date
    ).order_by('intended_trade_date')

    if not caches.exists():
        logger.warning(f"没有找到模型缓存: {model_artifact_hash}")
        return ModelMetrics()

    evaluator = ModelEvaluator()

    # 收集所有预测
    all_predictions = {}
    all_targets = {}

    # TODO: 从其他数据源获取实际收益
    all_returns = {}

    for cache in caches:
        for stock_data in cache.scores:
            stock_code = stock_data["code"]
            score = stock_data["score"]
            # 假设 score 是预测值，实际收益需要从其他数据源获取
            all_predictions[stock_code] = score
            # TODO: 替换为实际收益
            all_targets[stock_code] = score * 0.5  # 模拟目标
            all_returns[stock_code] = score * 0.3  # 模拟收益

    # 评估
    return evaluator.evaluate_predictions(
        predictions=all_predictions,
        targets=all_targets,
        returns=all_returns
    )


def calculate_rolling_metrics(
    model_artifact_hash: str,
    universe_id: str,
    start_date: date,
    end_date: date,
    window: int = 20
) -> List[RollingMetrics]:
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
    caches = AlphaScoreCacheModel.objects.filter(
        universe_id=universe_id,
        provider_source="qlib",
        model_artifact_hash=model_artifact_hash,
        intended_trade_date__gte=start_date,
        intended_trade_date__lte=end_date
    ).order_by('intended_trade_date')

    # 按日期分组
    date_scores = {}
    for cache in caches:
        trade_date = cache.intended_trade_date
        if trade_date not in date_scores:
            date_scores[trade_date] = {}
        for stock_data in cache.scores:
            date_scores[trade_date][stock_data["code"]] = stock_data["score"]

    # 计算滚动 IC
    sorted_dates = sorted(date_scores.keys())
    if len(sorted_dates) < window:
        return []

    ic_calculator = IC_Calculator()
    rolling_metrics = []

    for i in range(window - 1, len(sorted_dates)):
        window_dates = sorted_dates[i - window + 1:i + 1]

        window_preds = []
        window_targets = []

        for dt in window_dates:
            for stock, score in date_scores[dt].items():
                window_preds.append(score)
                window_targets.append(score * 0.5)  # 模拟目标

        if window_preds:
            ic = ic_calculator.calculate_ic(
                np.array(window_preds),
                np.array(window_targets)
            )

            # 计算 IC MA 和 Std
            preds_array = np.array(window_preds)
            ic_ma_5 = np.mean(preds_array[-5:]) if len(preds_array) >= 5 else None
            ic_std_20 = np.std(preds_array[-20:]) if len(preds_array) >= 20 else None

            rolling_metrics.append(RollingMetrics(
                date=window_dates[-1],
                ic=ic,
                ic_ma_5=ic_ma_5,
                ic_std_20=ic_std_20
            ))

    return rolling_metrics
