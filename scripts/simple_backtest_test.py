"""
简化的回测验证脚本
"""
import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

# 设置路径
sys.path.insert(0, '.')

# 导入模块
from apps.backtest.domain.stock_selection_backtest import (
    RebalanceFrequency,
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
)
from apps.equity.domain.entities import FinancialData, StockInfo, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule


def main():
    random.seed(42)

    print("=" * 50)
    print("Stock Selection Backtest Validation")
    print("=" * 50)

    # 配置
    start_date = date(2023, 1, 1)
    end_date = date(2023, 12, 31)
    print(f"\nBacktest period: {start_date} to {end_date}")

    # 生成模拟数据
    print("\nGenerating mock data...")

    # 生成 50 只股票
    stocks = []
    sectors = ['Securities', 'Materials', 'Chemical', 'Auto', 'Electronics']
    for i in range(50):
        code = f"60{1000 + i:04d}.SH"
        stock = StockInfo(
            stock_code=code,
            name=f"Stock{i+1}",
            sector=sectors[i % len(sectors)],
            market="SH",
            list_date=date(2020, 1, 1)
        )
        stocks.append(stock)

    stock_codes = [s.stock_code for s in stocks]

    # 优质股票 (代码数字部分以0或3结尾)
    quality_codes = [c for c in stock_codes if c.split('.')[0][-1] in ['0', '3']]
    print(f"  Total stocks: {len(stocks)}")
    print(f"  Quality stocks: {len(quality_codes)}")

    # 生成价格数据
    print("Generating price data...")
    prices_by_stock = {}

    for code in stock_codes:
        is_quality = code.split('.')[0][-1] in ['0', '3']
        base_price = Decimal("20.0") if is_quality else Decimal("10.0")
        daily_drift = 0.0008 if is_quality else 0.0002

        prices = {}
        current_price = base_price
        current = start_date

        while current <= end_date:
            if current.weekday() < 5:  # Weekday
                change = random.gauss(daily_drift, 0.02)
                current_price = current_price * Decimal(1 + change)
                prices[current] = current_price
            current += timedelta(days=1)

        prices_by_stock[code] = prices

    # 生成 Regime 历史
    print("Generating regime history...")
    regime_history = {}
    regimes = ['Recovery', 'Overheat', 'Stagflation', 'Deflation']
    current = start_date
    regime_idx = 0

    while current <= end_date:
        if current.day == 1 and current.month % 3 == 1:
            regime_idx = (regime_idx + 1) % 4
        regime_history[current] = regimes[regime_idx]
        current += timedelta(days=1)

    # 生成财务和估值数据
    print("Generating fundamental data...")
    financial_by_date = {}
    valuation_by_date = {}

    current = start_date
    while current <= end_date:
        # 每季度生成一次
        if current.day == 1 and current.month % 3 == 1:
            financial = {}
            valuation = {}

            for code in stock_codes:
                is_quality = code.split('.')[0][-1] in ['0', '3']

                # 财务数据
                roe = random.uniform(15, 25) if is_quality else random.uniform(5, 12)
                financial[code] = FinancialData(
                    stock_code=code,
                    report_date=current,
                    revenue=Decimal("1000000000"),
                    net_profit=Decimal("100000000"),
                    revenue_growth=random.uniform(15, 30) if is_quality else random.uniform(-5, 15),
                    net_profit_growth=random.uniform(15, 30) if is_quality else random.uniform(-10, 15),
                    total_assets=Decimal("5000000000"),
                    total_liabilities=Decimal("2000000000"),
                    equity=Decimal("3000000000"),
                    roe=round(roe, 2),
                    roa=round(roe * 0.3, 2),
                    debt_ratio=random.uniform(30, 50)
                )

                # 估值数据
                pe = random.uniform(10, 20) if is_quality else random.uniform(20, 40)
                valuation[code] = ValuationMetrics(
                    stock_code=code,
                    trade_date=current,
                    pe=round(pe, 2),
                    pb=round(pe * 0.1, 2),
                    ps=round(random.uniform(1, 5), 2),
                    total_mv=Decimal("10000000000"),
                    circ_mv=Decimal("8000000000"),
                    dividend_yield=round(random.uniform(0, 3), 2)
                )

            financial_by_date[current] = financial
            valuation_by_date[current] = valuation

        current += timedelta(days=1)

    # 辅助函数
    def get_regime(d):
        return regime_history.get(d, 'Recovery')

    def get_stock_data(d):
        fin = financial_by_date.get(d, {})
        val = valuation_by_date.get(d, {})
        result = []
        for s in stocks:
            if s.stock_code in fin and s.stock_code in val:
                result.append((s, fin[s.stock_code], val[s.stock_code]))
        return result

    def get_price(code, d):
        if code not in prices_by_stock:
            return None
        if d in prices_by_stock[code]:
            return prices_by_stock[code][d]
        # 查找最近的价格
        for offset in range(1, 5):
            prev = d - timedelta(days=offset)
            if prev in prices_by_stock[code]:
                return prices_by_stock[code][prev]
        return None

    benchmark_prices = {}
    current = start_date
    base_benchmark = 3000.0
    while current <= end_date:
        if current.weekday() < 5:
            change = random.gauss(0.0003, 0.015)
            base_benchmark = base_benchmark * (1 + change)
            benchmark_prices[current] = base_benchmark
        current += timedelta(days=1)

    def get_benchmark_price(d):
        if d in benchmark_prices:
            return benchmark_prices[d]
        for offset in range(1, 5):
            prev = d - timedelta(days=offset)
            if prev in benchmark_prices:
                return benchmark_prices[prev]
        return 3000.0

    # 回测配置
    print("\nInitializing backtest engine...")
    config = StockSelectionBacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=Decimal("1000000"),
        rebalance_frequency=RebalanceFrequency.QUARTERLY,
        max_positions=10,
        position_method="equal_weight",
        commission_rate=0.0003,
        slippage_rate=0.001
    )

    # 筛选规则
    screening_rules = {
        'Recovery': StockScreeningRule(
            regime='Recovery',
            name='Recovery Growth',
            min_roe=15.0,
            min_revenue_growth=10.0,
            max_pe=30.0,
            max_pb=4.0,
            sector_preference=['Securities', 'Materials', 'Chemical'],
            max_count=10
        ),
        'Overheat': StockScreeningRule(
            regime='Overheat',
            name='Overheat Commodity',
            min_roe=12.0,
            max_pe=25.0,
            max_pb=3.0,
            max_count=10
        ),
        'Stagflation': StockScreeningRule(
            regime='Stagflation',
            name='Stagflation Defensive',
            min_roe=10.0,
            max_pe=20.0,
            max_pb=2.5,
            max_count=10
        ),
        'Deflation': StockScreeningRule(
            regime='Deflation',
            name='Deflation Value',
            min_roe=8.0,
            max_pe=15.0,
            max_pb=2.0,
            max_count=10
        )
    }

    # 创建回测引擎
    engine = StockSelectionBacktestEngine(
        config=config,
        get_regime_func=get_regime,
        get_stock_data_func=get_stock_data,
        get_price_func=get_price,
        get_benchmark_price_func=get_benchmark_price
    )

    # 运行回测
    print("Running backtest...")
    result = engine.run(screening_rules)

    # 输出结果
    print("\n" + "=" * 50)
    print("BACKTEST RESULTS")
    print("=" * 50)

    print("\nReturn Metrics:")
    print(f"  Total Return: {result.total_return*100:.2f}%")
    print(f"  Annualized Return: {result.annualized_return*100:.2f}%")
    print(f"  Benchmark Return: {result.benchmark_return*100:.2f}%")
    print(f"  Excess Return: {result.excess_return*100:.2f}%")

    print("\nRisk Metrics:")
    print(f"  Volatility: {result.volatility*100:.2f}%")
    print(f"  Max Drawdown: {result.max_drawdown*100:.2f}%")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")

    print("\nTrading Stats:")
    print(f"  Rebalances: {result.total_rebalances}")
    print(f"  Total Trades: {result.total_trades}")
    print(f"  Avg Positions: {result.avg_positions:.1f}")

    print("\nPerformance:")
    print(f"  Win Rate: {result.win_rate*100:.1f}%")
    print(f"  Avg Win: {result.avg_win*100:.2f}%")
    print(f"  Avg Loss: {result.avg_loss*100:.2f}%")

    # 评估
    print("\n" + "=" * 50)
    print("ASSESSMENT")
    print("=" * 50)

    score = 0
    if result.annualized_return > 0.10:
        print("[PASS] Annualized return > 10%")
        score += 1
    if result.sharpe_ratio > 0.5:
        print("[PASS] Sharpe ratio > 0.5")
        score += 1
    if result.max_drawdown < 0.25:
        print("[PASS] Max drawdown < 25%")
        score += 1
    if result.excess_return > 0:
        print("[PASS] Excess return > 0%")
        score += 1

    print(f"\nScore: {score}/4")
    print("\nBacktest validation complete!")
    print("=" * 50)

    return result


if __name__ == "__main__":
    result = main()
