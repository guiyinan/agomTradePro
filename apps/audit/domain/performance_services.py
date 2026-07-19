"""Indicator performance evaluation domain services for Audit.

Pure business logic for evaluating indicator predictive power against Regime
history. Only uses Python standard library (no pandas/numpy).
"""

import math
from datetime import date, timedelta

from .entities import (
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    RecommendedAction,
    RegimeSnapshot,
    SignalEvent,
)

__all__ = [
    "IndicatorPerformanceAnalyzer",
    "ThresholdValidator",
]


# ============ 指标表现评估服务 ============


class IndicatorPerformanceAnalyzer:
    """
    指标表现分析器（纯业务逻辑）

    评估单个指标对 Regime 判断的预测能力。
    """

    def __init__(self, threshold_config: IndicatorThresholdConfig):
        """
        初始化分析器

        Args:
            threshold_config: 指标阈值配置
        """
        self.threshold_config = threshold_config

    def analyze_performance(
        self,
        indicator_code: str,
        indicator_values: list[tuple[date, float]],
        regime_history: list[RegimeSnapshot],
        evaluation_start: date,
        evaluation_end: date,
    ) -> IndicatorPerformanceReport:
        """
        分析指标表现

        步骤：
        1. 生成信号序列（基于阈值）
        2. 对比 Regime 历史，计算混淆矩阵
        3. 计算统计指标（precision/recall/F1）
        4. 计算领先时间
        5. 计算子样本期稳定性
        6. 生成建议

        Args:
            indicator_code: 指标代码
            indicator_values: 指标历史值 [(date, value), ...]
            regime_history: Regime 判定历史
            evaluation_start: 评估起始日期
            evaluation_end: 评估结束日期

        Returns:
            IndicatorPerformanceReport: 指标表现报告
        """
        # 1. 生成信号序列
        signals = self._generate_signals(indicator_values, evaluation_start, evaluation_end)

        # 2. 将 regime_history 转为字典方便查找
        regime_dict = {r.observed_at: r for r in regime_history}

        # 3. 计算混淆矩阵
        tp, fp, tn, fn = self._calculate_confusion_matrix(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 4. 计算统计指标
        precision, recall, f1_score, accuracy = self._calculate_metrics(tp, fp, tn, fn)

        # 5. 计算领先时间
        lead_time_mean, lead_time_std = self._calculate_lead_time(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 6. 计算稳定性
        pre_2015_corr, post_2015_corr, stability_score = self._calculate_stability(
            indicator_values, regime_dict, evaluation_start, evaluation_end
        )

        # 7. 计算衰减率和信号强度
        decay_rate, signal_strength = self._calculate_decay_and_strength(
            signals, regime_dict, evaluation_start, evaluation_end
        )

        # 8. 生成建议
        recommended_action, recommended_weight, confidence = self._generate_recommendation(
            f1_score, stability_score, decay_rate, signal_strength
        )

        return IndicatorPerformanceReport(
            indicator_code=indicator_code,
            evaluation_period_start=evaluation_start,
            evaluation_period_end=evaluation_end,
            true_positive_count=tp,
            false_positive_count=fp,
            true_negative_count=tn,
            false_negative_count=fn,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            accuracy=accuracy,
            lead_time_mean=lead_time_mean,
            lead_time_std=lead_time_std,
            pre_2015_correlation=pre_2015_corr,
            post_2015_correlation=post_2015_corr,
            stability_score=stability_score,
            # Report contract uses enum names ("KEEP"/"INCREASE"/"DECREASE"/"REMOVE").
            recommended_action=recommended_action.name,
            recommended_weight=recommended_weight,
            confidence_level=confidence,
            decay_rate=decay_rate,
            signal_strength=signal_strength,
        )

    def _generate_signals(
        self,
        indicator_values: list[tuple[date, float]],
        start_date: date,
        end_date: date,
    ) -> list[SignalEvent]:
        """
        基于阈值生成信号

        信号规则：
        - value > level_high: BULLISH（看多）
        - value < level_low: BEARISH（看空）
        - 中间区域: NEUTRAL（中性）

        Args:
            indicator_values: 指标历史值
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[SignalEvent]: 信号事件列表
        """
        signals = []
        level_low = self.threshold_config.level_low
        level_high = self.threshold_config.level_high
        # Macro data may be published 1-2 days after period end; keep a small grace window.
        effective_end = end_date + timedelta(days=3)

        for obs_date, value in indicator_values:
            if not (start_date <= obs_date <= effective_end):
                continue

            if value is None:
                continue

            # 确定信号类型
            if level_high is not None and value > level_high:
                signal_type = "BULLISH"
                threshold_used = level_high
            elif level_low is not None and value < level_low:
                signal_type = "BEARISH"
                threshold_used = level_low
            else:
                signal_type = "NEUTRAL"
                threshold_used = (level_low + level_high) / 2 if level_low and level_high else 0.0

            # 计算置信度（基于距离阈值的程度）
            if signal_type == "BULLISH" and level_high is not None:
                confidence = min(1.0, (value - level_high) / abs(level_high) * 0.5 + 0.5)
            elif signal_type == "BEARISH" and level_low is not None:
                confidence = min(1.0, (level_low - value) / abs(level_low) * 0.5 + 0.5)
            else:
                confidence = 0.5

            signals.append(
                SignalEvent(
                    indicator_code=self.threshold_config.indicator_code,
                    signal_date=obs_date,
                    signal_type=signal_type,
                    signal_value=value,
                    threshold_used=threshold_used,
                    confidence=confidence,
                )
            )

        return signals

    def _calculate_confusion_matrix(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[int, int, int, int]:
        """
        计算混淆矩阵

        将信号与实际 Regime 对比：
        - 真阳性 (TP): 预测扩张/过热，实际确实是扩张/过热
        - 假阳性 (FP): 预测扩张/过热，实际是通缩/滞胀
        - 真阴性 (TN): 预测通缩/滞胀，实际确实是通缩/滞胀
        - 假阴性 (FN): 预测通缩/滞胀，实际是扩张/过热

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (tp, fp, tn, fn): 混淆矩阵四个值
        """
        tp = fp = tn = fn = 0

        for signal in signals:
            # 找到最近的 Regime 判定
            regime = regime_dict.get(signal.signal_date)
            if regime is None:
                # 找最近的日期
                closest_date = min(
                    (d for d in regime_dict.keys() if d <= signal.signal_date), default=None
                )
                if closest_date:
                    regime = regime_dict[closest_date]
                else:
                    continue

            # 定义扩张/过热 vs 通缩/滞胀
            is_bullish_signal = signal.signal_type in ("BULLISH", "NEUTRAL_POSITIVE")
            is_expansion_regime = regime.dominant_regime in ("Recovery", "Overheat")

            if is_bullish_signal and is_expansion_regime:
                tp += 1
            elif is_bullish_signal and not is_expansion_regime:
                fp += 1
            elif not is_bullish_signal and not is_expansion_regime:
                tn += 1
            else:  # not is_bullish_signal and is_expansion_regime
                fn += 1

        return tp, fp, tn, fn

    def _calculate_metrics(
        self,
        tp: int,
        fp: int,
        tn: int,
        fn: int,
    ) -> tuple[float, float, float, float]:
        """
        计算统计指标

        Args:
            tp, fp, tn, fn: 混淆矩阵值

        Returns:
            (precision, recall, f1_score, accuracy)
        """
        total = tp + fp + tn + fn
        if total == 0:
            return 0.0, 0.0, 0.0, 0.0

        # Precision = TP / (TP + FP)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

        # Recall = TP / (TP + FN)
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        # F1 Score = 2 * Precision * Recall / (Precision + Recall)
        if precision + recall > 0:
            f1_score = 2 * precision * recall / (precision + recall)
        else:
            f1_score = 0.0

        # Accuracy = (TP + TN) / Total
        accuracy = (tp + tn) / total if total > 0 else 0.0

        return precision, recall, f1_score, accuracy

    def _calculate_lead_time(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float, float]:
        """
        计算领先时间

        计算信号领先于 Regime 变化的平均时间（月）

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (mean_lead_time, std_lead_time): 平均领先时间和标准差
        """
        lead_times = []

        # 排序信号
        sorted_signals = sorted(signals, key=lambda s: s.signal_date)

        # 排序 Regime 历史
        sorted_regimes = sorted(regime_dict.items(), key=lambda x: x[0])

        # 检测 Regime 变化
        for i in range(1, len(sorted_regimes)):
            prev_date, prev_regime = sorted_regimes[i - 1]
            curr_date, curr_regime = sorted_regimes[i]

            # 检测 Regime 变化
            if prev_regime.dominant_regime != curr_regime.dominant_regime:
                # 找到变化前的信号
                regime_change_date = curr_date
                for signal in sorted_signals:
                    if signal.signal_date < regime_change_date:
                        # 计算领先时间（天 -> 月）
                        lead_days = (regime_change_date - signal.signal_date).days
                        lead_months = lead_days / 30.0  # 近似

                        # 只统计合理的领先时间（0-12个月）
                        if 0 <= lead_months <= 12:
                            lead_times.append(lead_months)
                    break

        if not lead_times:
            return 0.0, 0.0

        # 计算均值和标准差
        mean_lead = sum(lead_times) / len(lead_times)
        variance = sum((t - mean_lead) ** 2 for t in lead_times) / len(lead_times)
        std_lead = math.sqrt(variance)

        return mean_lead, std_lead

    def _calculate_stability(
        self,
        indicator_values: list[tuple[date, float]],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float | None, float | None, float]:
        """
        计算稳定性

        通过分段相关性评估指标在不同时期的表现稳定性。

        Args:
            indicator_values: 指标历史值
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (pre_2015_correlation, post_2015_correlation, stability_score)
        """
        cutoff_date = date(2015, 1, 1)

        # 分段
        pre_values = [(d, v) for d, v in indicator_values if start_date <= d < cutoff_date]
        post_values = [(d, v) for d, v in indicator_values if cutoff_date <= d <= end_date]

        # 计算相关性（简化：基于信号一致率）
        # 在实际应用中，这里应该使用 Pearson 或 Spearman 相关系数
        # 由于 Domain 层不能用 numpy，我们简化处理

        if len(pre_values) < 10 or len(post_values) < 10:
            return None, None, 0.5  # 数据不足

        # 简化的相关性计算（使用信号变化的一致性）
        pre_corr = self._calculate_simple_correlation(
            pre_values, regime_dict, start_date, cutoff_date
        )
        post_corr = self._calculate_simple_correlation(
            post_values, regime_dict, cutoff_date, end_date
        )

        # 稳定性分数 = 1 - |pre - post|
        if pre_corr is not None and post_corr is not None:
            stability_score = 1.0 - abs(pre_corr - post_corr)
            stability_score = max(0.0, min(1.0, stability_score))
        else:
            stability_score = 0.5

        return pre_corr, post_corr, stability_score

    def _calculate_simple_correlation(
        self,
        values: list[tuple[date, float]],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> float | None:
        """
        计算简化的相关性指标

        使用信号与 Regime 的一致率作为相关性代理
        """
        if not values:
            return None

        consistent = 0
        total = 0

        level_low = self.threshold_config.level_low
        level_high = self.threshold_config.level_high

        for obs_date, value in values:
            if not (start_date <= obs_date <= end_date):
                continue

            # 找到对应的 Regime
            regime = regime_dict.get(obs_date)
            if regime is None:
                continue

            # 判断指标方向
            is_high = value > level_high if level_high is not None else False
            is_low = value < level_low if level_low is not None else False

            # 判断 Regime 方向
            is_expansion = regime.dominant_regime in ("Recovery", "Overheat")

            # 检查一致性
            if (is_high and is_expansion) or (is_low and not is_expansion):
                consistent += 1
            total += 1

        if total == 0:
            return None

        return consistent / total

    def _calculate_decay_and_strength(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
        start_date: date,
        end_date: date,
    ) -> tuple[float, float]:
        """
        计算信号衰减率和强度

        Args:
            signals: 信号事件列表
            regime_dict: Regime 快照字典
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            (decay_rate, signal_strength)
        """
        if not signals:
            return 0.0, 0.0

        # 计算信号强度（平均置信度）
        signal_strength = sum(s.confidence for s in signals) / len(signals)

        # 计算衰减率（后期信号准确率下降程度）
        mid_point = len(signals) // 2
        early_signals = signals[:mid_point]
        late_signals = signals[mid_point:]

        early_accuracy = self._calculate_signal_accuracy(early_signals, regime_dict)
        late_accuracy = self._calculate_signal_accuracy(late_signals, regime_dict)

        if early_accuracy is not None and late_accuracy is not None:
            decay_rate = max(0.0, early_accuracy - late_accuracy)
        else:
            decay_rate = 0.0

        return decay_rate, signal_strength

    def _calculate_signal_accuracy(
        self,
        signals: list[SignalEvent],
        regime_dict: dict[date, RegimeSnapshot],
    ) -> float | None:
        """计算信号准确率"""
        if not signals:
            return None

        correct = 0
        for signal in signals:
            regime = regime_dict.get(signal.signal_date)
            if regime is None:
                continue

            is_bullish_signal = signal.signal_type in ("BULLISH", "NEUTRAL_POSITIVE")
            is_expansion_regime = regime.dominant_regime in ("Recovery", "Overheat")

            if is_bullish_signal == is_expansion_regime:
                correct += 1

        return correct / len(signals) if signals else None

    def _generate_recommendation(
        self,
        f1_score: float,
        stability_score: float,
        decay_rate: float,
        signal_strength: float,
    ) -> tuple[RecommendedAction, float, float]:
        """
        生成建议

        根据各项指标的表现，生成建议操作和权重调整。

        规则：
        - F1 >= 0.6: KEEP
        - 0.4 <= F1 < 0.6: DECREASE
        - F1 < 0.4: REMOVE
        - 稳定性 < 0.5: DECREASE
        - 衰减率 > 0.2: DECREASE

        Args:
            f1_score: F1 分数
            stability_score: 稳定性分数
            decay_rate: 衰减率
            signal_strength: 信号强度

        Returns:
            (recommended_action, recommended_weight, confidence_level)
        """
        # 获取配置阈值
        keep_min_f1 = self.threshold_config.keep_min_f1
        remove_max_f1 = self.threshold_config.remove_max_f1
        decay_threshold = self.threshold_config.decay_threshold

        base_weight = self.threshold_config.base_weight
        min_weight = self.threshold_config.min_weight
        max_weight = self.threshold_config.max_weight

        # 判断建议操作
        action = RecommendedAction.KEEP
        new_weight = base_weight

        if f1_score >= keep_min_f1 and stability_score >= 0.6 and decay_rate < decay_threshold:
            # 表现良好，保持或增加权重
            if f1_score > 0.8 and stability_score > 0.8:
                action = RecommendedAction.INCREASE
                proposed_weight = base_weight * 1.2
                if max_weight is None or max_weight <= base_weight:
                    new_weight = proposed_weight
                else:
                    new_weight = min(max_weight, proposed_weight)
            else:
                action = RecommendedAction.KEEP
                new_weight = base_weight
            confidence = f1_score * stability_score

        elif f1_score < remove_max_f1 or stability_score < 0.3 or decay_rate > decay_threshold * 2:
            # 表现很差，建议移除
            action = RecommendedAction.REMOVE
            new_weight = min_weight
            confidence = 1.0 - f1_score

        else:
            # 表现一般，降低权重
            action = RecommendedAction.DECREASE
            # 根据 F1 分数线性调整权重
            weight_factor = (f1_score - remove_max_f1) / (keep_min_f1 - remove_max_f1)
            new_weight = max(min_weight, base_weight * weight_factor)
            confidence = 0.5

        return action, new_weight, confidence


class ThresholdValidator:
    """
    阈值验证器

    验证历史阈值配置的表现。
    """

    def __init__(self):
        self.analyzers: dict[str, IndicatorPerformanceAnalyzer] = {}

    def add_indicator(self, indicator_code: str, threshold_config: IndicatorThresholdConfig):
        """添加指标分析器"""
        self.analyzers[indicator_code] = IndicatorPerformanceAnalyzer(threshold_config)

    def validate_all(
        self,
        indicators_data: dict[str, list[tuple[date, float]]],
        regime_history: list[RegimeSnapshot],
        evaluation_start: date,
        evaluation_end: date,
    ) -> list[IndicatorPerformanceReport]:
        """
        验证所有指标

        Args:
            indicators_data: 指标数据 {indicator_code: [(date, value), ...]}
            regime_history: Regime 历史
            evaluation_start: 评估起始日期
            evaluation_end: 评估结束日期

        Returns:
            List[IndicatorPerformanceReport]: 所有指标的表现报告
        """
        reports = []

        for indicator_code, analyzer in self.analyzers.items():
            if indicator_code not in indicators_data:
                continue

            try:
                report = analyzer.analyze_performance(
                    indicator_code=indicator_code,
                    indicator_values=indicators_data[indicator_code],
                    regime_history=regime_history,
                    evaluation_start=evaluation_start,
                    evaluation_end=evaluation_end,
                )
                reports.append(report)
            except Exception as e:
                # 记录错误但继续处理其他指标
                import logging

                logging.warning(f"Failed to analyze {indicator_code}: {e}")

        return reports
