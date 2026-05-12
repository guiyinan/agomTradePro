"""
Model Evaluation Infrastructure

Qlib 模型评估相关的基础设施。
包括 IC/ICIR 计算、滚动指标、绩效度量等。

仅使用 Python 标准库和 numpy（允许用于计算）。
"""

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelMetrics:
    """
    模型评估指标

    Attributes:
        ic: Information Coefficient（相关系数）
        icir: Information Coefficient Information Ratio
        rank_ic: Rank IC（排序相关系数）
        rank_icir: Rank ICIR
        group_ic: 分组 IC（按行业分组）
        sharpe: 夏普比率
        turnover: 换手率
        coverage: 覆盖率
        long_short_ratio: 多空比
        annual_return: 年化收益
        annual_volatility: 年化波动率
        max_drawdown: 最大回撤
    """

    ic: float | None = None
    icir: float | None = None
    rank_ic: float | None = None
    rank_icir: float | None = None
    group_ic: float | None = None
    sharpe: float | None = None
    turnover: float | None = None
    coverage: float | None = None
    long_short_ratio: float | None = None
    annual_return: float | None = None
    annual_volatility: float | None = None
    max_drawdown: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """转换为字典"""
        return {
            "ic": self.ic,
            "icir": self.icir,
            "rank_ic": self.rank_ic,
            "rank_icir": self.rank_icir,
            "group_ic": self.group_ic,
            "sharpe": self.sharpe,
            "turnover": self.turnover,
            "coverage": self.coverage,
            "long_short_ratio": self.long_short_ratio,
            "annual_return": self.annual_return,
            "annual_volatility": self.annual_volatility,
            "max_drawdown": self.max_drawdown,
        }

    @classmethod
    def from_dict(cls, data: dict[str, float | None]) -> "ModelMetrics":
        """从字典创建"""
        return cls(**data)


@dataclass
class RollingMetrics:
    """
    滚动评估指标

    Attributes:
        date: 评估日期
        ic: IC 值
        icir: ICIR 值（滚动）
        rank_ic: Rank IC 值
        ic_ma_5: IC 5日均值
        ic_std_20: IC 20日标准差
    """

    date: date
    ic: float
    icir: float | None = None
    rank_ic: float | None = None
    ic_ma_5: float | None = None
    ic_std_20: float | None = None

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "ic": self.ic,
            "icir": self.icir,
            "rank_ic": self.rank_ic,
            "ic_ma_5": self.ic_ma_5,
            "ic_std_20": self.ic_std_20,
        }


class IC_Calculator:
    """
    IC 计算器

    计算信息系数（IC）和相关系数信息比率（ICIR）。
    """

    @staticmethod
    def calculate_ic(
        predictions: np.ndarray,
        targets: np.ndarray
    ) -> float:
        """
        计算 IC（相关系数）

        Args:
            predictions: 预测值数组
            targets: 目标值数组

        Returns:
            IC 值

        Example:
            >>> calc = IC_Calculator()
            >>> ic = calc.calculate_ic(
            ...     np.array([0.1, 0.2, 0.3]),
            ...     np.array([0.15, 0.25, 0.35])
            ... )
        """
        if len(predictions) != len(targets):
            raise ValueError("predictions 和 targets 长度必须相同")

        if len(predictions) < 2:
            return 0.0

        # 计算相关系数
        correlation = np.corrcoef(predictions, targets)[0, 1]

        # 处理 NaN
        if np.isnan(correlation):
            return 0.0

        return float(correlation)

    @staticmethod
    def calculate_rank_ic(
        predictions: np.ndarray,
        targets: np.ndarray
    ) -> float:
        """
        计算 Rank IC（排序相关系数）

        Args:
            predictions: 预测值数组
            targets: 目标值数组

        Returns:
            Rank IC 值
        """
        if len(predictions) != len(targets):
            raise ValueError("predictions 和 targets 长度必须相同")

        if len(predictions) < 2:
            return 0.0

        # 计算排名
        pred_ranks = np.argsort(np.argsort(-predictions)) + 1
        target_ranks = np.argsort(np.argsort(-targets)) + 1

        # 计算排名的相关系数
        rank_ic = np.corrcoef(pred_ranks, target_ranks)[0, 1]

        if np.isnan(rank_ic):
            return 0.0

        return float(rank_ic)

    @staticmethod
    def calculate_icir(
        ics: list[float],
        annualize: bool = True
    ) -> float:
        """
        计算 ICIR（IC 的信息比率）

        ICIR = mean(IC) / std(IC)

        Args:
            ics: IC 值列表
            annualize: 是否年化（乘以 sqrt(252)）

        Returns:
            ICIR 值
        """
        if not ics or len(ics) < 2:
            return 0.0

        ics_array = np.array(ics)

        # 移除 NaN
        ics_array = ics_array[~np.isnan(ics_array)]

        if len(ics_array) < 2:
            return 0.0

        mean_ic = np.mean(ics_array)
        std_ic = np.std(ics_array)

        if std_ic == 0:
            return 0.0

        icir = mean_ic / std_ic

        if annualize:
            icir *= np.sqrt(252)

        return float(icir)

    @staticmethod
    def calculate_group_ic(
        predictions: dict[str, np.ndarray],
        targets: dict[str, np.ndarray],
        groups: dict[str, str]
    ) -> float:
        """
        计算分组 IC（按行业分组）

        Args:
            predictions: {股票代码: 预测值}
            targets: {股票代码: 目标值}
            groups: {股票代码: 分组标识}

        Returns:
            分组 IC 值
        """
        if not predictions:
            return 0.0

        # 按分组计算 IC
        group_ics = []
        for group_id in set(groups.values()):
            group_stocks = [k for k, v in groups.items() if v == group_id]

            group_preds = np.array([predictions.get(k, 0) for k in group_stocks])
            group_targets = np.array([targets.get(k, 0) for k in group_stocks])

            if len(group_preds) > 1:
                group_ic = IC_Calculator.calculate_ic(group_preds, group_targets)
                group_ics.append(group_ic)

        if not group_ics:
            return 0.0

        # 返回平均分组 IC
        return float(np.mean(group_ics))

    @staticmethod
    def calculate_rolling_ic(
        predictions: list[float],
        targets: list[float],
        window: int = 20
    ) -> list[tuple[int, float]]:
        """
        计算滚动 IC

        Args:
            predictions: 预测值列表
            targets: 目标值列表
            window: 滚动窗口大小

        Returns:
            [(索引, IC 值), ...] 列表
        """
        if len(predictions) < window or len(targets) < window:
            return []

        preds_array = np.array(predictions)
        targets_array = np.array(targets)

        rolling_ics = []

        for i in range(window - 1, len(predictions)):
            window_preds = preds_array[i - window + 1:i + 1]
            window_targets = targets_array[i - window + 1:i + 1]

            ic = IC_Calculator.calculate_ic(window_preds, window_targets)
            rolling_ics.append((i, ic))

        return rolling_ics


class PerformanceCalculator:
    """
    性能计算器

    计算夏普比率、最大回撤、换手率等绩效指标。
    """

    @staticmethod
    def calculate_sharpe_ratio(
        returns: np.ndarray,
        risk_free_rate: float = 0.03,
        annualize: bool = True
    ) -> float:
        """
        计算夏普比率

        Sharpe = (mean(returns) - risk_free_rate) / std(returns)

        Args:
            returns: 收益率数组
            risk_free_rate: 无风险利率（年化）
            annualize: 是否年化

        Returns:
            夏普比率
        """
        if len(returns) < 2:
            return 0.0

        mean_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        sharpe = (mean_return - risk_free_rate) / std_return

        if annualize:
            sharpe *= np.sqrt(252)

        return float(sharpe)

    @staticmethod
    def calculate_max_drawdown(
        cumulative_returns: np.ndarray
    ) -> float:
        """
        计算最大回撤

        Args:
            cumulative_returns: 累计收益数组

        Returns:
            最大回撤（正值）
        """
        if len(cumulative_returns) < 2:
            return 0.0

        # 计算回撤
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = cumulative_returns - running_max

        max_dd = np.min(drawdown)

        return float(abs(max_dd))

    @staticmethod
    def calculate_turnover(
        current_positions: list[str],
        previous_positions: list[str]
    ) -> float:
        """
        计算换手率

        Args:
            current_positions: 当前持仓
            previous_positions: 上期持仓

        Returns:
            换手率（0-1）
        """
        if not previous_positions:
            return 0.0

        # 计算变化
        current_set = set(current_positions)
        previous_set = set(previous_positions)

        added = current_set - previous_set
        removed = previous_set - current_set

        turnover = (len(added) + len(removed)) / (2 * len(previous_set))

        return float(turnover)

    @staticmethod
    def calculate_coverage(
        scored_stocks: list[str],
        universe_stocks: list[str]
    ) -> float:
        """
        计算覆盖率

        Args:
            scored_stocks: 有评分的股票
            universe_stocks: 股票池所有股票

        Returns:
            覆盖率（0-1）
        """
        if not universe_stocks:
            return 0.0

        scored_set = set(scored_stocks)
        universe_set = set(universe_stocks)

        coverage = len(scored_set & universe_set) / len(universe_set)

        return float(coverage)


class ModelEvaluator:
    """
    模型评估器

    综合评估模型性能。
    """

    def __init__(self):
        self.ic_calculator = IC_Calculator()
        self.perf_calculator = PerformanceCalculator()

    def evaluate_predictions(
        self,
        predictions: dict[str, float],
        targets: dict[str, float],
        returns: dict[str, float] | None = None,
        groups: dict[str, str] | None = None
    ) -> ModelMetrics:
        """
        评估预测结果

        Args:
            predictions: {股票代码: 预测评分}
            targets: {股票代码: 目标收益}
            returns: {股票代码: 实际收益}（可选）
            groups: {股票代码: 分组}（可选）

        Returns:
            模型指标
        """
        # 准备数组
        pred_list = []
        target_list = []
        stock_list = []

        for stock in predictions:
            if stock in targets:
                pred_list.append(predictions[stock])
                target_list.append(targets[stock])
                stock_list.append(stock)

        if not pred_list:
            return ModelMetrics()

        preds_array = np.array(pred_list)
        targets_array = np.array(target_list)

        # 计算 IC
        ic = self.ic_calculator.calculate_ic(preds_array, targets_array)

        # 计算 Rank IC
        rank_ic = self.ic_calculator.calculate_rank_ic(preds_array, targets_array)

        # 计算 ICIR（使用单日 IC）
        icir = self.ic_calculator.calculate_icir([ic], annualize=False)

        # 计算分组 IC
        group_ic = None
        if groups:
            group_ic = self.ic_calculator.calculate_group_ic(
                predictions, targets, groups
            )

        metrics = ModelMetrics(
            ic=ic,
            icir=icir,
            rank_ic=rank_ic,
            group_ic=group_ic,
            coverage=len(predictions) / max(len(targets), 1)
        )

        # 如果提供了收益数据，计算更多指标
        if returns:
            metrics = self._calculate_performance_metrics(
                predictions, returns, metrics
            )

        return metrics

    def _calculate_performance_metrics(
        self,
        predictions: dict[str, float],
        returns: dict[str, float],
        metrics: ModelMetrics
    ) -> ModelMetrics:
        """计算绩效指标"""
        # 取 top N 股票
        top_n = 30
        sorted_stocks = sorted(
            predictions.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]

        top_returns = [returns.get(stock, 0) for stock, _ in sorted_stocks]
        returns_array = np.array(top_returns)

        if len(returns_array) < 2:
            return metrics

        # 计算夏普比率
        sharpe = self.perf_calculator.calculate_sharpe_ratio(returns_array)

        # 计算累计收益和最大回撤
        cumulative_returns = np.cumsum(returns_array)
        max_dd = self.perf_calculator.calculate_max_drawdown(cumulative_returns)

        # 年化收益
        total_return = cumulative_returns[-1]
        annual_return = total_return * 252  # 假设日度

        # 年化波动
        annual_vol = np.std(returns_array) * np.sqrt(252)

        # 更新指标
        return ModelMetrics(
            ic=metrics.ic,
            icir=metrics.icir,
            rank_ic=metrics.rank_ic,
            group_ic=metrics.group_ic,
            sharpe=sharpe,
            annual_return=annual_return,
            annual_volatility=annual_vol,
            max_drawdown=max_dd,
            coverage=metrics.coverage,
        )
