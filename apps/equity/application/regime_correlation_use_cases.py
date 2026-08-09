"""Regime-correlation analysis use case for equities."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import cast

from apps.equity.application.use_case_protocols import (
    EquityStockReadRepositoryProtocol,
    RegimeHistoryRepositoryProtocol,
)
from apps.equity.application.use_case_runtime import (
    RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS,
)
from apps.equity.domain.ports import MarketDataPort

logger = logging.getLogger(__name__)


# ============================================================================
# Regime 相关性分析
# ============================================================================


@dataclass
class AnalyzeRegimeCorrelationRequest:
    """Regime 相关性分析请求"""

    stock_code: str
    lookback_days: int = 1260  # 回看天数（默认 5 年，约 1260 个交易日）


@dataclass
class RegimePerformance:
    """单个 Regime 的表现"""

    regime: str
    avg_return: float
    beta: float | None
    sample_days: int


@dataclass
class AnalyzeRegimeCorrelationResponse:
    """Regime 相关性分析响应"""

    success: bool
    stock_code: str
    stock_name: str
    regime_performance: dict[str, RegimePerformance]
    best_regime: str
    worst_regime: str
    error: str | None = None


class AnalyzeRegimeCorrelationUseCase:
    """Regime 相关性分析用例"""

    def __init__(
        self,
        stock_repository: EquityStockReadRepositoryProtocol,
        regime_repository: RegimeHistoryRepositoryProtocol,
    ) -> None:
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            regime_repository: Regime 数据仓储
        """
        self.stock_repo = stock_repository
        self.regime_repo = regime_repository

    def execute(self, request: AnalyzeRegimeCorrelationRequest) -> AnalyzeRegimeCorrelationResponse:
        """
        执行 Regime 相关性分析

        流程：
        1. 获取股票基本信息
        2. 获取历史收益率数据
        3. 获取 Regime 历史数据
        4. 获取市场指数收益率（用于计算 Beta）
        5. 调用 Domain 层的分析逻辑
        6. 返回结果
        """
        try:
            from datetime import timedelta

            from apps.equity.domain.services import RegimeCorrelationAnalyzer

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取历史收益率
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            stock_returns = self.stock_repo.calculate_daily_returns(
                request.stock_code,
                start_date,
                end_date,
                hydrate=True,
            )

            if not stock_returns:
                raise ValueError(
                    f"未找到股票 {request.stock_code} 的价格数据，请先同步日线数据或检查 Tushare/AKShare 数据源"
                )

            # 3. 获取 Regime 历史（从 Regime 模块）
            regime_history = self._get_regime_history(start_date, end_date)

            # 4. 获取市场收益率（使用沪深 300）
            market_returns = self._get_market_returns(start_date, end_date)

            # 5. 调用 Domain 层分析
            analyzer = RegimeCorrelationAnalyzer()

            # 计算各 Regime 下的平均收益
            avg_returns = analyzer.calculate_regime_correlation(stock_returns, regime_history)

            # 计算各 Regime 下的 Beta
            regime_betas = analyzer.calculate_regime_beta(
                stock_returns, market_returns, regime_history
            )

            # 6. 构造响应
            regime_performance: dict[str, RegimePerformance] = {}
            for regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]:
                # 计算样本天数
                sample_days = sum(1 for r in regime_history.values() if r == regime)

                regime_performance[regime] = RegimePerformance(
                    regime=regime,
                    avg_return=avg_returns.get(regime, 0.0),
                    beta=regime_betas.get(regime, 1.0),
                    sample_days=sample_days,
                )

            # 找出最佳和最差 Regime
            sorted_by_return = sorted(
                regime_performance.items(), key=lambda x: x[1].avg_return, reverse=True
            )
            best_regime = sorted_by_return[0][0] if sorted_by_return else "Recovery"
            worst_regime = sorted_by_return[-1][0] if sorted_by_return else "Deflation"

            return AnalyzeRegimeCorrelationResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                regime_performance=regime_performance,
                best_regime=best_regime,
                worst_regime=worst_regime,
            )

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as e:
            logger.warning("AnalyzeRegimeCorrelationUseCase.execute failed: %s", e)
            return AnalyzeRegimeCorrelationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name="",
                regime_performance={},
                best_regime="",
                worst_regime="",
                error=str(e),
            )

    def _get_regime_history(self, start_date: date, end_date: date) -> dict[date, str]:
        """
        获取 Regime 历史数据

        从 regime 模块获取指定日期范围内的 Regime 快照，
        将其转换为按日期索引的字典。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: Regime 名称}
        """
        try:
            snapshots = self.regime_repo.get_snapshots_in_range(start_date, end_date)

            # 将快照列表转换为日期字典
            regime_history: dict[date, str] = {}
            for snapshot in snapshots:
                regime_history[snapshot.observed_at] = snapshot.dominant_regime

            # 对于缺失的日期，使用前一个有效日期的 Regime
            return self._fill_missing_dates(regime_history, start_date, end_date)

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as exc:
            # 如果获取失败，返回空字典
            # Domain 层的 RegimeCorrelationAnalyzer 会处理空数据情况
            logger.warning("AnalyzeRegimeCorrelationUseCase._get_regime_history degraded: %s", exc)
            return {}

    def _get_market_returns(self, start_date: date, end_date: date) -> dict[date, float]:
        """
        获取市场指数收益率

        使用数据库配置的市场基准。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}
        """
        try:
            from apps.equity.application import use_cases as _facade

            market_adapter = cast(
                MarketDataPort,
                _facade.get_equity_market_data_repository(),
            )
            benchmark_code = _facade.get_runtime_benchmark_code("equity_market_benchmark")
            if not benchmark_code:
                return {}
            returns = market_adapter.get_index_daily_returns(
                index_code=benchmark_code,
                start_date=start_date,
                end_date=end_date,
            )
            return dict(returns)

        except RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS as exc:
            # 如果获取失败，返回空字典
            logger.warning("AnalyzeRegimeCorrelationUseCase._get_market_returns degraded: %s", exc)
            return {}

    def _fill_missing_dates(
        self, regime_history: dict[date, str], start_date: date, end_date: date
    ) -> dict[date, str]:
        """
        填充缺失的日期

        Regime 数据通常不会每天都有，使用前一个有效日期的值填充。

        Args:
            regime_history: 原始 Regime 历史（可能有日期缺失）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            填充后的完整日期字典
        """
        from datetime import timedelta

        result: dict[date, str] = {}
        if not regime_history:
            return result
        current = start_date
        last_regime: str | None = None

        while current <= end_date:
            # 如果当前日期有数据，使用当前日期的数据
            if current in regime_history:
                result[current] = regime_history[current]
                last_regime = regime_history[current]
            elif last_regime is not None:
                result[current] = last_regime

            current += timedelta(days=1)

        return result
