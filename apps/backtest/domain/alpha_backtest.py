"""
Alpha Backtest Integration

Integration layer for using Alpha signals in backtesting.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .stock_selection_backtest import (
    RebalanceFrequency,
    RebalanceRecord,
    StockPerformance,
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
    StockSelectionBacktestResult,
)

AlphaService = None


logger = logging.getLogger(__name__)


@dataclass
class AlphaBacktestConfig(StockSelectionBacktestConfig):
    """Alpha 回测配置"""
    universe_id: str = "csi300"  # 股票池
    alpha_provider: str = "qlib"  # 优先使用的 Alpha Provider
    min_score: float = 0.6  # 最低评分阈值
    max_positions: int = 30  # 最大持仓数
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY


@dataclass
class AlphaBacktestResult(StockSelectionBacktestResult):
    """Alpha 回测结果"""
    # Alpha 特有指标
    avg_ic: float = 0.0  # 平均 IC
    avg_rank_ic: float = 0.0  # 平均 Rank IC
    icir: float = 0.0  # ICIR
    coverage_ratio: float = 0.0  # 平均覆盖率
    provider_usage: dict[str, int] = field(default_factory=dict)  # 各 Provider 使用次数


class AlphaBacktestEngine(StockSelectionBacktestEngine):
    """
    Alpha 信号回测引擎

    使用 Alpha 信号进行股票选择和回测。
    继承自 StockSelectionBacktestEngine，使用 Alpha 评分替代筛选规则。
    """

    def __init__(
        self,
        config: AlphaBacktestConfig,
        get_regime_func: Callable[[date], str | None],
        get_price_func: Callable[[str, date], Decimal | None],
        get_benchmark_price_func: Callable[[date], float | None],
        alpha_service,
    ):
        """
        初始化 Alpha 回测引擎

        Args:
            config: Alpha 回测配置
            get_regime_func: 获取 Regime 的函数
            get_price_func: 获取股票价格的函数
            get_benchmark_price_func: 获取基准价格的函数
            alpha_service: Alpha 服务实例
        """
        # 初始化父类，使用空的 get_stock_data_func（我们将使用 Alpha 替代）
        super().__init__(
            config=config,
            get_regime_func=get_regime_func,
            get_stock_data_func=lambda d: [],  # 不使用，由 Alpha 替代
            get_price_func=get_price_func,
            get_benchmark_price_func=get_benchmark_price_func
        )

        self.alpha_config = config
        self.alpha_service = alpha_service
        self.provider_usage = {}  # 记录各 Provider 使用次数

    def run(self) -> AlphaBacktestResult:
        """
        运行 Alpha 回测

        Returns:
            Alpha 回测结果
        """
        # 初始化
        capital = self.config.initial_capital
        portfolio = {}  # {stock_code: (shares, entry_price)}
        rebalance_records = []
        stock_performances = []
        equity_curve = []

        # IC 统计
        ics = []
        rank_ics = []

        # 生成再平衡日期
        rebalance_dates = self._generate_rebalance_dates()

        # 初始基准
        initial_benchmark_price = self.get_benchmark_price_func(self.config.start_date)

        logger.info(f"开始 Alpha 回测: {self.config.start_date} ~ {self.config.end_date}")
        logger.info(f"再平衡次数: {len(rebalance_dates)}")

        for i, rebalance_date in enumerate(rebalance_dates):
            # 1. 获取当前 Regime
            regime = self.get_regime_func(rebalance_date) or "Recovery"

            # 2. 获取 Alpha 评分
            alpha_result = self.alpha_service.get_stock_scores(
                universe_id=self.alpha_config.universe_id,
                intended_trade_date=rebalance_date,
                top_n=self.alpha_config.max_positions
            )

            if not alpha_result.success:
                logger.warning(
                    f"日期 {rebalance_date}: Alpha 评分失败 - {alpha_result.error_message}"
                )
                continue

            # 记录 Provider 使用
            provider = alpha_result.source
            self.provider_usage[provider] = self.provider_usage.get(provider, 0) + 1

            # 筛选高分股票
            selected_stocks = [
                stock.code for stock in alpha_result.scores
                if stock.score >= self.alpha_config.min_score
            ]

            if not selected_stocks:
                logger.warning(f"日期 {rebalance_date}: 没有符合条件的股票")
                continue

            # 限制持仓数量
            selected_stocks = selected_stocks[:self.alpha_config.max_positions]

            # 计算覆盖率（如果有目标股票数量）
            coverage = len(selected_stocks) / self.alpha_config.max_positions

            # 3. 卖出不在新股票池中的股票
            sold_stocks = []
            for stock_code in list(portfolio.keys()):
                if stock_code not in selected_stocks:
                    shares, entry_price = portfolio.pop(stock_code)

                    # 获取当前价格
                    current_price = self.get_price_func(stock_code, rebalance_date)
                    if current_price:
                        # 计算收益
                        return_rate = float((current_price - entry_price) / entry_price)

                        # 记录表现
                        stock_performances.append(StockPerformance(
                            stock_code=stock_code,
                            stock_name=stock_code,
                            entry_date=rebalance_date - timedelta(days=30),  # 估算
                            entry_price=entry_price,
                            exit_date=rebalance_date,
                            exit_price=current_price,
                            return_rate=return_rate,
                            holding_days=30
                        ))

                        # 更新资金
                        capital += shares * current_price * Decimal(1 - self.config.commission_rate)
                        sold_stocks.append((stock_code, return_rate))

            # 4. 计算新股票池权重（等权重）
            weights = {code: 1.0 / len(selected_stocks) for code in selected_stocks}

            # 5. 买入新股票
            bought_stocks = []
            for stock_code in selected_stocks:
                if stock_code not in portfolio:
                    weight = weights.get(stock_code, 1.0 / len(selected_stocks))
                    target_value = capital * Decimal(weight)

                    # 获取价格
                    price = self.get_price_func(stock_code, rebalance_date)
                    if price:
                        # 计算买入股数（考虑滑点）
                        actual_price = price * Decimal(1 + self.config.slippage_rate)
                        shares = int(target_value / actual_price)

                        if shares > 0:
                            cost = shares * actual_price * Decimal(1 + self.config.commission_rate)
                            if cost <= capital:
                                portfolio[stock_code] = (shares, actual_price)
                                capital -= cost
                                bought_stocks.append((stock_code, actual_price))

            # 6. 计算当前组合价值
            portfolio_value = capital
            for stock_code, (shares, _) in portfolio.items():
                price = self.get_price_func(stock_code, rebalance_date)
                if price:
                    portfolio_value += shares * price

            # 7. 记录
            rebalance_records.append(RebalanceRecord(
                rebalance_date=rebalance_date,
                regime=regime,
                selected_stocks=selected_stocks,
                sold_stocks=sold_stocks,
                bought_stocks=bought_stocks,
                portfolio_value=portfolio_value
            ))

            # 8. 记录净值
            equity_curve.append((rebalance_date, portfolio_value))

            logger.debug(
                f"{rebalance_date}: Regime={regime}, "
                f"持仓={len(portfolio)}, "
                f"组合价值={portfolio_value:.0f}, "
                f"Provider={provider}"
            )

        # 最后再平衡后清空持仓
        final_date = rebalance_dates[-1] if rebalance_dates else self.config.end_date
        for stock_code, (shares, entry_price) in portfolio.items():
            current_price = self.get_price_func(stock_code, final_date)
            if current_price:
                return_rate = float((current_price - entry_price) / entry_price)
                stock_performances.append(StockPerformance(
                    stock_code=stock_code,
                    stock_name=stock_code,
                    entry_date=final_date - timedelta(days=30),
                    entry_price=entry_price,
                    exit_date=final_date,
                    exit_price=current_price,
                    return_rate=return_rate,
                    holding_days=30
                ))
                capital += shares * current_price

        # 计算最终结果
        final_value = capital
        total_return = float((final_value - self.config.initial_capital) / self.config.initial_capital)

        # 计算基准收益
        final_benchmark_price = self.get_benchmark_price_func(self.config.end_date)
        if initial_benchmark_price and final_benchmark_price:
            benchmark_return = (final_benchmark_price - initial_benchmark_price) / initial_benchmark_price
        else:
            benchmark_return = 0.0

        excess_return = total_return - benchmark_return

        # 计算年化收益
        days = (self.config.end_date - self.config.start_date).days
        annualized_return = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0

        # 计算风险指标
        volatility, max_drawdown, sharpe_ratio = self._calculate_risk_metrics(
            equity_curve,
            annualized_return
        )

        # 计算交易统计
        total_trades = sum(
            len(record.sold_stocks) + len(record.bought_stocks)
            for record in rebalance_records
        )

        # 计算持仓统计
        win_rate, avg_win, avg_loss = self._calculate_win_loss_stats(
            {sp.stock_code: [{'return': sp.return_rate}] for sp in stock_performances}
        )

        # 计算平均覆盖率
        avg_coverage = sum(
            len(r.selected_stocks) / self.alpha_config.max_positions
            for r in rebalance_records
        ) / len(rebalance_records) if rebalance_records else 0

        # 计算换手率
        turnover_rate = self._calculate_turnover_rate(rebalance_records)

        # 计算 ICIR（IC 信息比率）
        icir = self._calculate_icir(ics)

        # 构造结果
        return AlphaBacktestResult(
            config=self.config,
            total_return=total_return,
            annualized_return=annualized_return,
            benchmark_return=benchmark_return,
            excess_return=excess_return,
            volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            calmar_ratio=annualized_return / max_drawdown if max_drawdown != 0 else 0,
            total_rebalances=len(rebalance_dates),
            total_trades=total_trades,
            avg_holding_period=30.0,  # 简化假设
            turnover_rate=turnover_rate,
            avg_positions=sum(len(r.selected_stocks) for r in rebalance_records) / len(rebalance_records) if rebalance_records else 0,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            equity_curve=equity_curve,
            rebalance_records=rebalance_records,
            stock_performances=stock_performances,
            avg_ic=sum(ics) / len(ics) if ics else 0.0,
            avg_rank_ic=sum(rank_ics) / len(rank_ics) if rank_ics else 0.0,
            icir=icir,
            coverage_ratio=avg_coverage,
            provider_usage=self.provider_usage,
        )

    def _calculate_turnover_rate(
        self,
        rebalance_records: list[RebalanceRecord]
    ) -> float:
        """
        计算换手率

        换手率 = (买入金额 + 卖出金额) / (2 * 组合平均价值)

        Args:
            rebalance_records: 再平衡记录列表

        Returns:
            float: 平均换手率
        """
        if not rebalance_records:
            return 0.0

        turnover_rates = []

        for record in rebalance_records:
            # 换手率 = (卖出数量 + 买入数量) / (2 * 持仓数量)
            sold_count = len(record.sold_stocks)
            bought_count = len(record.bought_stocks)
            total_positions = len(record.selected_stocks)

            if total_positions > 0:
                turnover = (sold_count + bought_count) / (2 * total_positions)
                turnover_rates.append(turnover)

        if not turnover_rates:
            return 0.0

        return sum(turnover_rates) / len(turnover_rates)

    def _calculate_icir(self, ics: list[float]) -> float:
        """
        计算 ICIR（IC 信息比率）

        ICIR = mean(IC) / std(IC)

        ICIR 衡量 Alpha 因子的预测稳定性，
        类似于 Sharpe Ratio，但衡量的是 IC 值的稳定性。

        Args:
            ics: IC 值列表

        Returns:
            float: ICIR 值
        """
        if len(ics) < 2:
            return 0.0

        import statistics

        mean_ic = statistics.mean(ics)

        try:
            std_ic = statistics.stdev(ics)
        except statistics.StatisticsError:
            # 标准差为零（所有 IC 值相同）
            return 0.0

        if std_ic == 0:
            return 0.0

        return mean_ic / std_ic


@dataclass
class RunAlphaBacktestRequest:
    """运行 Alpha 回测的请求"""
    name: str
    start_date: date
    end_date: date
    initial_capital: float = 1000000.0
    universe_id: str = "csi300"
    alpha_provider: str = "qlib"
    min_score: float = 0.6
    max_positions: int = 30
    rebalance_frequency: str = "monthly"
    transaction_cost_bps: float = 10.0


@dataclass
class RunAlphaBacktestResponse:
    """运行 Alpha 回测的响应"""
    backtest_id: int | None
    status: str
    result: dict[str, Any] | None
    errors: list[str]
    warnings: list[str]


class RunAlphaBacktestUseCase:
    """
    运行 Alpha 回测的用例

    职责：
    1. 验证请求参数
    2. 创建 Alpha 回测配置
    3. 运行回测引擎
    4. 保存结果到数据库
    """

    def __init__(
        self,
        repository,
        get_regime_func: Callable[[date], str | None],
        get_price_func: Callable[[str, date], Decimal | None],
        get_benchmark_price_func: Callable[[date], float | None],
        alpha_service_factory: Callable[[], Any] | None = None,
    ):
        """
        Args:
            repository: 回测仓储
            get_regime_func: 获取 Regime 的函数
            get_price_func: 获取资产价格的函数
            get_benchmark_price_func: 获取基准价格的函数
        """
        self.repository = repository
        self.get_regime = get_regime_func
        self.get_price = get_price_func
        self.get_benchmark_price = get_benchmark_price_func
        self._alpha_service_factory = alpha_service_factory

        # 延迟初始化 Alpha 服务
        self._alpha_service = None

    @property
    def alpha_service(self):
        """获取 Alpha 服务（延迟初始化）"""
        if self._alpha_service is None:
            try:
                if self._alpha_service_factory is not None:
                    self._alpha_service = self._alpha_service_factory()
                elif AlphaService is not None:
                    self._alpha_service = AlphaService()
                else:
                    logger.warning("Alpha service factory not configured")
                    self._alpha_service = False
            except ImportError:
                logger.warning("Alpha 模块不可用")
                self._alpha_service = False
        return self._alpha_service

    def execute(self, request: RunAlphaBacktestRequest) -> RunAlphaBacktestResponse:
        """
        执行 Alpha 回测

        Args:
            request: 回测请求

        Returns:
            RunAlphaBacktestResponse: 回测结果
        """
        errors = []
        warnings = []
        backtest_id = None

        try:
            # 1. 验证 Alpha 服务可用
            if not self.alpha_service:
                return RunAlphaBacktestResponse(
                    backtest_id=None,
                    status='failed',
                    result=None,
                    errors=['Alpha 服务不可用'],
                    warnings=[]
                )

            # 2. 创建回测配置
            config = AlphaBacktestConfig(
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=Decimal(str(request.initial_capital)),
                universe_id=request.universe_id,
                alpha_provider=request.alpha_provider,
                min_score=request.min_score,
                max_positions=request.max_positions,
                rebalance_frequency=RebalanceFrequency(request.rebalance_frequency),
                commission_rate=request.transaction_cost_bps / 10000,  # bps 转 rate
                slippage_rate=0.001,  # 默认 0.1%
            )

            # 3. 创建回测记录
            backtest_model = self.repository.create_backtest(request.name, config)
            backtest_id = backtest_model.id

            # 4. 标记为运行中
            self.repository.update_status(backtest_id, 'running')

            # 5. 创建并运行回测引擎
            engine = AlphaBacktestEngine(
                config=config,
                get_regime_func=self.get_regime,
                get_price_func=self.get_price,
                get_benchmark_price_func=self.get_benchmark_price,
                alpha_service=self.alpha_service,
            )

            result = engine.run()
            warnings.extend([])  # 可以添加警告信息

            # 6. 保存结果
            self.repository.save_result(backtest_id, result)

            logger.info(f"Alpha Backtest {backtest_id} completed successfully")

            return RunAlphaBacktestResponse(
                backtest_id=backtest_id,
                status='completed',
                result=self._result_to_dict(result),
                errors=errors,
                warnings=warnings,
            )

        except Exception as e:
            logger.exception(f"Alpha Backtest failed: {e}")

            # 如果已经创建了记录，标记为失败
            if backtest_id:
                self.repository.update_status(backtest_id, 'failed', str(e))

            return RunAlphaBacktestResponse(
                backtest_id=backtest_id if 'backtest_id' in locals() else None,
                status='failed',
                result=None,
                errors=[str(e)],
                warnings=warnings,
            )

    @staticmethod
    def _result_to_dict(result: AlphaBacktestResult) -> dict[str, Any]:
        """将结果转换为字典"""
        return {
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'benchmark_return': result.benchmark_return,
            'excess_return': result.excess_return,
            'volatility': result.volatility,
            'max_drawdown': result.max_drawdown,
            'sharpe_ratio': result.sharpe_ratio,
            'calmar_ratio': result.calmar_ratio,
            'total_rebalances': result.total_rebalances,
            'total_trades': result.total_trades,
            'avg_positions': result.avg_positions,
            'win_rate': result.win_rate,
            'avg_ic': result.avg_ic,
            'avg_rank_ic': result.avg_rank_ic,
            'icir': result.icir,
            'coverage_ratio': result.coverage_ratio,
            'provider_usage': result.provider_usage,
            'equity_curve': [
                {'date': d.isoformat(), 'value': float(v)}
                for d, v in result.equity_curve
            ],
        }
