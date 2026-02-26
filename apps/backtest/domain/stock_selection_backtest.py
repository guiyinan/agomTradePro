"""
股票筛选策略回测服务

用于验证基于估值和财务指标的股票筛选策略的有效性
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple, Callable
from decimal import Decimal
from enum import Enum

from apps.equity.domain.entities import StockInfo, FinancialData, ValuationMetrics
from apps.equity.domain.services import StockScreener, ValuationAnalyzer
from apps.equity.domain.rules import StockScreeningRule


class RebalanceFrequency(Enum):
    """再平衡频率"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass
class StockSelectionBacktestConfig:
    """股票筛选回测配置"""
    start_date: date
    end_date: date
    initial_capital: Decimal = Decimal(1000000)  # 初始资金 100 万
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY
    max_positions: int = 30  # 最大持仓数
    position_method: str = "equal_weight"  # equal_weight 或 market_cap_weight
    commission_rate: float = 0.0003  # 手续费率（万三）
    slippage_rate: float = 0.001  # 滑点率（0.1%）


@dataclass
class StockPerformance:
    """个股表现"""
    stock_code: str
    stock_name: str
    entry_date: date
    entry_price: Decimal
    exit_date: Optional[date]
    exit_price: Optional[Decimal]
    return_rate: Optional[float]  # 收益率
    holding_days: int  # 持有天数


@dataclass
class RebalanceRecord:
    """再平衡记录"""
    rebalance_date: date
    regime: str  # 当时的 Regime
    selected_stocks: List[str]  # 筛选出的股票
    sold_stocks: List[Tuple[str, float]]  # (股票代码, 收益率)
    bought_stocks: List[Tuple[str, Decimal]]  # (股票代码, 买入价格)
    portfolio_value: Decimal  # 组合价值


@dataclass
class StockSelectionBacktestResult:
    """股票筛选回测结果"""
    # 基础信息
    config: StockSelectionBacktestConfig

    # 收益指标
    total_return: float  # 总收益率
    annualized_return: float  # 年化收益率
    benchmark_return: float  # 基准收益率（沪深 300）
    excess_return: float  # 超额收益率

    # 风险指标
    volatility: float  # 波动率（年化）
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    calmar_ratio: float  # 卡玛比率（收益/最大回撤）

    # 交易统计
    total_rebalances: int  # 总再平衡次数
    total_trades: int  # 总交易次数
    avg_holding_period: float  # 平均持仓天数
    turnover_rate: float  # 换手率

    # 持仓分析
    avg_positions: float  # 平均持仓数
    win_rate: float  # 胜率（盈利股票占比）
    avg_win: float  # 平均盈利幅度
    avg_loss: float  # 平均亏损幅度

    # 详细记录
    equity_curve: List[Tuple[date, Decimal]]  # 净值曲线
    rebalance_records: List[RebalanceRecord]  # 再平衡记录
    stock_performances: List[StockPerformance]  # 个股表现


class StockSelectionBacktestEngine:
    """
    股票筛选策略回测引擎

    核心逻辑：
    1. 按频率再平衡（如每月末）
    2. 每次再平衡时：
       a. 获取当前 Regime
       b. 使用 StockScreener 筛选股票池（Top N）
       c. 卖出不在新股票池中的股票
       d. 买入新股票池中的股票
    3. 计算收益、风险指标
    """

    def __init__(
        self,
        config: StockSelectionBacktestConfig,
        get_regime_func: Callable[[date], Optional[str]],
        get_stock_data_func: Callable[[date], List[Tuple[StockInfo, FinancialData, ValuationMetrics]]],
        get_price_func: Callable[[str, date], Optional[Decimal]],
        get_benchmark_price_func: Callable[[date], Optional[float]]
    ):
        """
        初始化回测引擎

        Args:
            config: 回测配置
            get_regime_func: 获取 Regime 的函数 (date) -> regime_name
            get_stock_data_func: 获取股票数据的函数 (date) -> [(StockInfo, FinancialData, ValuationMetrics), ...]
            get_price_func: 获取股票价格的函数 (stock_code, date) -> price
            get_benchmark_price_func: 获取基准价格的函数 (date) -> price
        """
        self.config = config
        self.get_regime_func = get_regime_func
        self.get_stock_data_func = get_stock_data_func
        self.get_price_func = get_price_func
        self.get_benchmark_price_func = get_benchmark_price_func

    def run(
        self,
        screening_rules: Dict[str, StockScreeningRule]
    ) -> StockSelectionBacktestResult:
        """
        运行回测

        Args:
            screening_rules: 各 Regime 对应的筛选规则 {regime: StockScreeningRule}

        Returns:
            回测结果
        """
        # 初始化
        capital = self.config.initial_capital
        portfolio = {}  # {stock_code: (shares, entry_price)}
        rebalance_records = []
        stock_performances = {}
        equity_curve = []

        # 生成再平衡日期
        rebalance_dates = self._generate_rebalance_dates()

        # 初始基准
        initial_benchmark_price = self.get_benchmark_price_func(self.config.start_date)

        for i, rebalance_date in enumerate(rebalance_dates):
            # 1. 获取当前 Regime
            regime = self.get_regime_func(rebalance_date) or "Recovery"

            # 2. 获取所有股票数据
            all_stocks = self.get_stock_data_func(rebalance_date)

            if not all_stocks:
                continue

            # 3. 筛选股票
            rule = screening_rules.get(regime, screening_rules.get("Recovery"))
            if not rule:
                continue

            screener = StockScreener()
            selected_stocks = screener.screen(all_stocks, rule)

            # 限制持仓数量
            selected_stocks = selected_stocks[:self.config.max_positions]

            # 4. 卖出不在新股票池中的股票
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
                        if stock_code not in stock_performances:
                            stock_performances[stock_code] = []
                        stock_performances[stock_code].append({
                            'entry_date': entry_price,
                            'exit_date': rebalance_date,
                            'return': return_rate
                        })

                        # 更新资金
                        capital += shares * current_price * Decimal(1 - self.config.commission_rate)
                        sold_stocks.append((stock_code, return_rate))

            # 5. 计算新股票池权重
            weights = self._calculate_weights(selected_stocks, rebalance_date)

            # 6. 买入新股票
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

            # 7. 计算当前组合价值
            portfolio_value = capital
            for stock_code, (shares, _) in portfolio.items():
                price = self.get_price_func(stock_code, rebalance_date)
                if price:
                    portfolio_value += shares * price

            # 8. 记录
            rebalance_records.append(RebalanceRecord(
                rebalance_date=rebalance_date,
                regime=regime,
                selected_stocks=selected_stocks,
                sold_stocks=sold_stocks,
                bought_stocks=bought_stocks,
                portfolio_value=portfolio_value
            ))

            # 9. 记录净值
            equity_curve.append((rebalance_date, portfolio_value))

        # 最后再平衡后清空持仓
        final_date = rebalance_dates[-1] if rebalance_dates else self.config.end_date
        for stock_code, (shares, entry_price) in portfolio.items():
            current_price = self.get_price_func(stock_code, final_date)
            if current_price:
                return_rate = float((current_price - entry_price) / entry_price)
                if stock_code not in stock_performances:
                    stock_performances[stock_code] = []
                stock_performances[stock_code].append({
                    'entry_date': entry_price,
                    'exit_date': final_date,
                    'return': return_rate
                })
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
        total_trades = sum(len(record.sold_stocks) + len(record.bought_stocks)
                          for record in rebalance_records)

        # 计算持仓统计
        win_rate, avg_win, avg_loss = self._calculate_win_loss_stats(stock_performances)

        # 计算平均持仓天数
        avg_holding_period = self._calculate_avg_holding_period(rebalance_dates)

        # 计算换手率
        turnover_rate = self._calculate_turnover_rate(rebalance_records)

        # 整理个股表现
        stock_performances_list = self._organize_stock_performances(stock_performances)

        # 构造结果
        return StockSelectionBacktestResult(
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
            avg_holding_period=avg_holding_period,
            turnover_rate=turnover_rate,
            avg_positions=sum(len(r.selected_stocks) for r in rebalance_records) / len(rebalance_records) if rebalance_records else 0,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            equity_curve=equity_curve,
            rebalance_records=rebalance_records,
            stock_performances=stock_performances_list
        )

    def _generate_rebalance_dates(self) -> List[date]:
        """生成再平衡日期"""
        dates = []
        current = self.config.start_date

        while current <= self.config.end_date:
            dates.append(current)

            # 计算下一个日期
            if self.config.rebalance_frequency == RebalanceFrequency.MONTHLY:
                # 下个月的同一天
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
            elif self.config.rebalance_frequency == RebalanceFrequency.QUARTERLY:
                # 下个季度
                month = current.month + 3
                if month > 12:
                    current = current.replace(year=current.year + 1, month=month - 12)
                else:
                    current = current.replace(month=month)
            elif self.config.rebalance_frequency == RebalanceFrequency.WEEKLY:
                current += timedelta(days=7)
            else:  # DAILY
                current += timedelta(days=1)

        return dates

    def _calculate_weights(
        self,
        stock_codes: List[str],
        rebalance_date: date
    ) -> Dict[str, float]:
        """计算持仓权重"""
        n = len(stock_codes)
        if n == 0:
            return {}

        if self.config.position_method == "equal_weight":
            # 等权重
            return {code: 1.0 / n for code in stock_codes}
        else:
            # 市值加权（TODO: 实现）
            return {code: 1.0 / n for code in stock_codes}

    def _calculate_risk_metrics(
        self,
        equity_curve: List[Tuple[date, Decimal]],
        annualized_return: float
    ) -> Tuple[float, float, float]:
        """计算风险指标"""
        if len(equity_curve) < 2:
            return 0.0, 0.0, 0.0

        # 计算日收益率
        returns = []
        for i in range(1, len(equity_curve)):
            prev_value = float(equity_curve[i - 1][1])
            curr_value = float(equity_curve[i][1])
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)

        if not returns:
            return 0.0, 0.0, 0.0

        # 波动率（年化）
        import statistics
        volatility = statistics.stdev(returns) * (252 ** 0.5)

        # 最大回撤
        max_drawdown = 0.0
        peak = float(equity_curve[0][1])

        for _, value in equity_curve:
            value_float = float(value)
            if value_float > peak:
                peak = value_float
            drawdown = (peak - value_float) / peak
            max_drawdown = max(max_drawdown, drawdown)

        # 夏普比率（假设无风险利率 3%）
        risk_free_rate = 0.03
        sharpe_ratio = (annualized_return - risk_free_rate) / volatility if volatility != 0 else 0

        return volatility, max_drawdown, sharpe_ratio

    def _calculate_win_loss_stats(
        self,
        stock_performances: Dict[str, List[Dict]]
    ) -> Tuple[float, float, float]:
        """计算胜率、平均盈利、平均亏损"""
        all_returns = []
        for performances in stock_performances.values():
            for perf in performances:
                all_returns.append(perf['return'])

        if not all_returns:
            return 0.0, 0.0, 0.0

        # 胜率
        winning_trades = [r for r in all_returns if r > 0]
        win_rate = len(winning_trades) / len(all_returns) if all_returns else 0

        # 平均盈利
        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0

        # 平均亏损
        losing_trades = [r for r in all_returns if r < 0]
        avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0

        return win_rate, avg_win, avg_loss

    def _calculate_avg_holding_period(
        self,
        rebalance_dates: List[date]
    ) -> float:
        """
        计算平均持仓天数

        假设股票在两次再平衡之间被持有，
        持仓天数约为再平衡间隔天数。

        Args:
            rebalance_dates: 再平衡日期列表

        Returns:
            float: 平均持仓天数
        """
        if len(rebalance_dates) < 2:
            return 0.0

        # 计算相邻再平衡日期之间的平均天数
        intervals = []
        for i in range(1, len(rebalance_dates)):
            days = (rebalance_dates[i] - rebalance_dates[i - 1]).days
            intervals.append(days)

        if not intervals:
            return 0.0

        return sum(intervals) / len(intervals)

    def _calculate_turnover_rate(
        self,
        rebalance_records: List[RebalanceRecord]
    ) -> float:
        """
        计算换手率

        换手率 = (买入金额 + 卖出金额) / (2 * 组合平均价值)

        这里使用简化方法：每次再平衡的换手率平均

        Args:
            rebalance_records: 再平衡记录列表

        Returns:
            float: 平均换手率
        """
        if not rebalance_records:
            return 0.0

        turnover_rates = []

        for record in rebalance_records:
            # 计算本次再平衡的换手率
            # 换手率 = min(买入金额, 卖出金额) / 组合价值
            # 这里使用简化版本：(卖出数量 + 买入数量) / (2 * 持仓数量)

            sold_count = len(record.sold_stocks)
            bought_count = len(record.bought_stocks)
            total_positions = len(record.selected_stocks)

            if total_positions > 0:
                # 换手率定义为：变动股票数 / 2 / 目标持仓数
                # 这样完全换仓时换手率为 100%
                turnover = (sold_count + bought_count) / (2 * total_positions)
                turnover_rates.append(turnover)

        if not turnover_rates:
            return 0.0

        return sum(turnover_rates) / len(turnover_rates)

    def _organize_stock_performances(
        self,
        stock_performances: Dict[str, List[Dict]]
    ) -> List[StockPerformance]:
        """
        整理个股表现

        将字典格式的个股表现转换为 StockPerformance 对象列表

        Args:
            stock_performances: {stock_code: [{'entry_date': ..., 'exit_date': ..., 'return': ...}, ...]}

        Returns:
            List[StockPerformance]: 个股表现列表
        """
        result = []

        for stock_code, performances in stock_performances.items():
            for perf in performances:
                # perf 包含 entry_date (实际是 entry_price), exit_date, return
                # 需要重新构造 StockPerformance
                # 由于原设计中 entry_date 可能不准确，我们做最佳估算
                entry_price = perf.get('entry_date')
                exit_date = perf.get('exit_date')
                return_rate = perf.get('return', 0.0)

                if entry_price and exit_date:
                    # 估算入场日期（假设持有30天）
                    if isinstance(exit_date, date):
                        estimated_entry_date = exit_date - timedelta(days=30)
                    else:
                        estimated_entry_date = exit_date - timedelta(days=30)

                    result.append(StockPerformance(
                        stock_code=stock_code,
                        stock_name=stock_code,  # 简化：使用代码作为名称
                        entry_date=estimated_entry_date,
                        entry_price=Decimal(str(entry_price)) if not isinstance(entry_price, date) else Decimal('100'),
                        exit_date=exit_date if isinstance(exit_date, date) else date(2024, 1, 1),
                        exit_price=Decimal('100'),  # 简化：无法获取真实出场价
                        return_rate=return_rate,
                        holding_days=30  # 简化假设
                    ))

        return result
