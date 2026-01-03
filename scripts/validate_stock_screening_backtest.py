"""
股票筛选策略回测验证脚本

使用模拟数据验证回测引擎的功能
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Tuple, Optional
import random

# 导入回测引擎和相关实体
from apps.backtest.domain.stock_selection_backtest import (
    StockSelectionBacktestEngine,
    StockSelectionBacktestConfig,
    RebalanceFrequency
)
from apps.equity.domain.entities import StockInfo, FinancialData, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule


def generate_mock_stocks(num_stocks: int = 100) -> List[StockInfo]:
    """生成模拟股票信息"""
    sectors = ['证券', '建筑材料', '化工', '汽车', '电子', '医药生物', '食品饮料', '银行', '保险']
    markets = ['SH', 'SZ']

    stocks = []
    for i in range(num_stocks):
        code = f"{600000 + i:06d}.{random.choice(markets)}"
        stock = StockInfo(
            stock_code=code,
            name=f"测试股票{i+1}",
            sector=random.choice(sectors),
            market=random.choice(markets),
            list_date=date(2020, 1, 1) + timedelta(days=random.randint(0, 365*5))
        )
        stocks.append(stock)

    return stocks


def generate_mock_financial_data(
    stock_codes: List[str],
    report_date: date
) -> Dict[str, FinancialData]:
    """生成模拟财务数据"""
    financial_data = {}

    for code in stock_codes:
        # 生成随机但合理的财务数据
        # 优质股票（以6或8结尾的代码）表现更好
        is_quality = int(code[-1]) % 3 == 0

        if is_quality:
            roe = random.uniform(15, 25)
            revenue_growth = random.uniform(20, 40)
            profit_growth = random.uniform(15, 35)
            debt_ratio = random.uniform(30, 50)
        else:
            roe = random.uniform(5, 15)
            revenue_growth = random.uniform(-10, 20)
            profit_growth = random.uniform(-20, 20)
            debt_ratio = random.uniform(40, 80)

        financial_data[code] = FinancialData(
            stock_code=code,
            report_date=report_date,
            revenue=Decimal(random.uniform(10_0000_0000, 1000_0000_0000)),
            net_profit=Decimal(random.uniform(1_0000_0000, 100_0000_0000)),
            revenue_growth=round(revenue_growth, 2),
            net_profit_growth=round(profit_growth, 2),
            total_assets=Decimal(random.uniform(50_0000_0000, 5000_0000_0000)),
            total_liabilities=Decimal(random.uniform(20_0000_0000, 2000_0000_0000)),
            equity=Decimal(random.uniform(30_0000_0000, 3000_0000_0000)),
            roe=round(roe, 2),
            roa=round(roe * 0.3, 2),
            debt_ratio=round(debt_ratio, 2)
        )

    return financial_data


def generate_mock_valuation_data(
    stock_codes: List[str],
    trade_date: date,
    quality_codes: List[str]
) -> Dict[str, ValuationMetrics]:
    """生成模拟估值数据"""
    valuation_data = {}

    for code in stock_codes:
        is_quality = code in quality_codes

        # 优质股票估值更低
        if is_quality:
            pe = random.uniform(10, 20)
            pb = random.uniform(1.0, 2.5)
        else:
            pe = random.uniform(20, 50)
            pb = random.uniform(2.0, 5.0)

        valuation_data[code] = ValuationMetrics(
            stock_code=code,
            trade_date=trade_date,
            pe=round(pe, 2),
            pb=round(pb, 2),
            ps=round(random.uniform(1, 10), 2),
            total_mv=Decimal(random.uniform(50_0000_0000, 1000_0000_0000)),
            circ_mv=Decimal(random.uniform(30_0000_0000, 500_0000_0000)),
            dividend_yield=round(random.uniform(0, 5), 2)
        )

    return valuation_data


def generate_mock_prices(
    stock_codes: List[str],
    start_date: date,
    end_date: date,
    quality_codes: List[str]
) -> Dict[str, Dict[date, Decimal]]:
    """生成模拟价格数据"""
    prices = {}
    days = (end_date - start_date).days

    for code in stock_codes:
        is_quality = code in quality_codes

        # 初始价格
        if is_quality:
            base_price = Decimal(random.uniform(10, 30))
            # 优质股票有更高的平均收益率
            daily_return_mean = 0.0008  # 约20%年化
            daily_return_std = 0.02
        else:
            base_price = Decimal(random.uniform(5, 50))
            daily_return_mean = 0.0002  # 约5%年化
            daily_return_std = 0.03

        current_price = base_price
        prices[code] = {}

        for i in range(days + 1):
            current_date = start_date + timedelta(days=i)

            # 只记录交易日（跳过周末）
            if current_date.weekday() < 5:
                # 模拟价格变动（几何布朗运动）
                import math
                drift = daily_return_mean - 0.5 * (daily_return_std ** 2)
                shock = random.gauss(0, 1) * daily_return_std
                daily_return = drift + shock

                current_price = current_price * Decimal(1 + daily_return)
                prices[code][current_date] = current_price

    return prices


def generate_mock_regime_history(
    start_date: date,
    end_date: date
) -> Dict[date, str]:
    """生成模拟 Regime 历史"""
    regimes = {}
    current_date = start_date

    # 每3个月切换一次 Regime
    regime_list = ['Recovery', 'Overheat', 'Stagflation', 'Deflation']
    current_regime_idx = 0

    while current_date <= end_date:
        # 每季度切换
        if current_date.day == 1 and current_date.month % 3 == 1:
            current_regime_idx = (current_regime_idx + 1) % 4

        regimes[current_date] = regime_list[current_regime_idx]
        current_date += timedelta(days=1)

    return regimes


def generate_mock_benchmark_prices(
    start_date: date,
    end_date: date
) -> Dict[date, float]:
    """生成模拟基准价格（沪深300）"""
    prices = {}
    base_value = 3000.0
    daily_return_mean = 0.0003  # 约7.5%年化
    daily_return_std = 0.015

    current_value = base_value
    days = (end_date - start_date).days

    for i in range(days + 1):
        current_date = start_date + timedelta(days=i)

        if current_date.weekday() < 5:
            import math
            drift = daily_return_mean - 0.5 * (daily_return_std ** 2)
            shock = random.gauss(0, 1) * daily_return_std
            daily_return = drift + shock

            current_value = current_value * (1 + daily_return)
            prices[current_date] = current_value

    return prices


def get_regime_func_factory(regime_history: Dict[date, str]):
    """创建获取 Regime 的函数"""
    def get_regime(query_date: date) -> Optional[str]:
        # 找到最接近的日期
        if query_date in regime_history:
            return regime_history[query_date]

        # 查找最近的工作日
        for offset in range(1, 10):
            prev_date = query_date - timedelta(days=offset)
            if prev_date in regime_history:
                return regime_history[prev_date]
            next_date = query_date + timedelta(days=offset)
            if next_date in regime_history:
                return regime_history[next_date]

        return 'Recovery'  # 默认

    return get_regime


def get_stock_data_func_factory(
    stocks: List[StockInfo],
    financial_data_by_date: Dict[date, Dict[str, FinancialData]],
    valuation_data_by_date: Dict[date, Dict[str, ValuationMetrics]]
):
    """创建获取股票数据的函数"""
    def get_stock_data(query_date: date) -> List[Tuple[StockInfo, FinancialData, ValuationMetrics]]:
        # 找到最近的财务和估值数据
        financial = financial_data_by_date.get(query_date, {})
        valuation = valuation_data_by_date.get(query_date, {})

        result = []
        for stock in stocks:
            if stock.stock_code in financial and stock.stock_code in valuation:
                result.append((stock, financial[stock.stock_code], valuation[stock.stock_code]))

        return result

    return get_stock_data


def get_price_func_factory(prices_by_stock: Dict[str, Dict[date, Decimal]]):
    """创建获取价格的函数"""
    def get_price(stock_code: str, query_date: date) -> Optional[Decimal]:
        if stock_code not in prices_by_stock:
            return None

        stock_prices = prices_by_stock[stock_code]

        # 精确匹配
        if query_date in stock_prices:
            return stock_prices[query_date]

        # 查找最近的价格
        for offset in range(1, 10):
            prev_date = query_date - timedelta(days=offset)
            if prev_date in stock_prices:
                return stock_prices[prev_date]
            next_date = query_date + timedelta(days=offset)
            if next_date in stock_prices:
                return stock_prices[next_date]

        return None

    return get_price


def get_benchmark_price_func_factory(benchmark_prices: Dict[date, float]):
    """创建获取基准价格的函数"""
    def get_benchmark_price(query_date: date) -> Optional[float]:
        if query_date in benchmark_prices:
            return benchmark_prices[query_date]

        # 查找最近的价格
        for offset in range(1, 10):
            prev_date = query_date - timedelta(days=offset)
            if prev_date in benchmark_prices:
                return benchmark_prices[prev_date]
            next_date = query_date + timedelta(days=offset)
            if next_date in benchmark_prices:
                return benchmark_prices[next_date]

        return None

    return get_benchmark_price


def run_backtest_validation():
    """运行回测验证"""
    print("=" * 60)
    print("股票筛选策略回测验证")
    print("=" * 60)

    # 1. 设置参数
    start_date = date(2023, 1, 1)
    end_date = date(2024, 12, 31)

    print(f"\n回测区间: {start_date} ~ {end_date}")
    print(f"回测时长: {(end_date - start_date).days} 天")

    # 2. 生成模拟数据
    print("\n生成模拟数据...")
    stocks = generate_mock_stocks(num_stocks=100)
    stock_codes = [s.stock_code for s in stocks]

    # 优质股票标识
    quality_codes = [code for code in stock_codes if int(code[-1]) % 3 == 0]
    print(f"  - 股票数量: {len(stocks)}")
    print(f"  - 优质股票: {len(quality_codes)}")

    # 生成各期财务和估值数据
    financial_data_by_date = {}
    valuation_data_by_date = {}

    # 每季度生成一次数据
    current = start_date
    while current <= end_date:
        financial_data_by_date[current] = generate_mock_financial_data(stock_codes, current)
        valuation_data_by_date[current] = generate_mock_valuation_data(stock_codes, current, quality_codes)
        current += timedelta(days=90)

    # 生成价格数据
    print("  - 生成价格数据...")
    prices_by_stock = generate_mock_prices(stock_codes, start_date, end_date, quality_codes)

    # 生成 Regime 历史
    print("  - 生成 Regime 历史...")
    regime_history = generate_mock_regime_history(start_date, end_date)

    # 生成基准价格
    print("  - 生成基准价格...")
    benchmark_prices = generate_mock_benchmark_prices(start_date, end_date)

    # 3. 创建辅助函数
    get_regime_func = get_regime_func_factory(regime_history)
    get_stock_data_func = get_stock_data_func_factory(stocks, financial_data_by_date, valuation_data_by_date)
    get_price_func = get_price_func_factory(prices_by_stock)
    get_benchmark_price_func = get_benchmark_price_func_factory(benchmark_prices)

    # 4. 配置回测
    config = StockSelectionBacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=Decimal(1_000_000),  # 100万初始资金
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        max_positions=20,
        position_method="equal_weight",
        commission_rate=0.0003,
        slippage_rate=0.001
    )

    # 5. 定义筛选规则
    screening_rules = {
        'Recovery': StockScreeningRule(
            regime='Recovery',
            name='复苏期成长股',
            min_roe=15.0,
            min_revenue_growth=15.0,
            max_pe=30.0,
            max_pb=4.0,
            sector_preference=['证券', '建筑材料', '化工', '汽车', '电子'],
            max_count=20
        ),
        'Overheat': StockScreeningRule(
            regime='Overheat',
            name='过热期商品股',
            min_roe=12.0,
            max_pe=25.0,
            max_pb=3.0,
            sector_preference=['煤炭', '有色金属', '石油石化', '钢铁'],
            max_count=20
        ),
        'Stagflation': StockScreeningRule(
            regime='Stagflation',
            name='滞胀期防御股',
            min_roe=10.0,
            max_pe=20.0,
            max_pb=2.5,
            sector_preference=['医药生物', '食品饮料', '公用事业'],
            max_count=20
        ),
        'Deflation': StockScreeningRule(
            regime='Deflation',
            name='通缩期价值股',
            min_roe=8.0,
            max_debt_ratio=60.0,
            max_pe=15.0,
            max_pb=2.0,
            sector_preference=['银行', '保险', '房地产'],
            max_count=20
        )
    }

    # 6. 创建并运行回测引擎
    print("\n初始化回测引擎...")
    engine = StockSelectionBacktestEngine(
        config=config,
        get_regime_func=get_regime_func,
        get_stock_data_func=get_stock_data_func,
        get_price_func=get_price_func,
        get_benchmark_price_func=get_benchmark_price_func
    )

    print("运行回测...")
    result = engine.run(screening_rules)

    # 7. 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)

    print(f"\n【收益指标】")
    print(f"  总收益率: {result.total_return*100:.2f}%")
    print(f"  年化收益率: {result.annualized_return*100:.2f}%")
    print(f"  基准收益率: {result.benchmark_return*100:.2f}%")
    print(f"  超额收益率: {result.excess_return*100:.2f}%")

    print(f"\n【风险指标】")
    print(f"  波动率: {result.volatility*100:.2f}%")
    print(f"  最大回撤: {result.max_drawdown*100:.2f}%")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  卡玛比率: {result.calmar_ratio:.2f}")

    print(f"\n【交易统计】")
    print(f"  总再平衡次数: {result.total_rebalances}")
    print(f"  总交易次数: {result.total_trades}")
    print(f"  平均持仓数: {result.avg_positions:.1f}")

    print(f"\n【持仓分析】")
    print(f"  胜率: {result.win_rate*100:.1f}%")
    print(f"  平均盈利: {result.avg_win*100:.2f}%")
    print(f"  平均亏损: {result.avg_loss*100:.2f}%")

    # 显示前几次再平衡记录
    print(f"\n【再平衡记录】(前5次)")
    for i, record in enumerate(result.rebalance_records[:5]):
        print(f"\n  第{i+1}次 ({record.rebalance_date}):")
        print(f"    Regime: {record.regime}")
        print(f"    选中股票: {len(record.selected_stocks)}只")
        print(f"    组合价值: {float(record.portfolio_value):,.0f}元")
        print(f"    卖出: {len(record.sold_stocks)}只")
        print(f"    买入: {len(record.bought_stocks)}只")

    # 8. 评估结果
    print("\n" + "=" * 60)
    print("回测评估")
    print("=" * 60)

    assessments = []

    # 收益评估
    if result.annualized_return > 0.15:
        assessments.append(("✅ 年化收益率 > 15%", "优秀"))
    elif result.annualized_return > 0.05:
        assessments.append(("⚠️ 年化收益率 5%-15%", "一般"))
    else:
        assessments.append(("❌ 年化收益率 < 5%", "需改进"))

    # 超额收益评估
    if result.excess_return > 0.05:
        assessments.append(("✅ 超额收益 > 5%", "跑赢基准"))
    elif result.excess_return > 0:
        assessments.append(("⚠️ 超额收益 0%-5%", "小幅跑赢"))
    else:
        assessments.append(("❌ 超额收益 < 0%", "跑输基准"))

    # 夏普比率评估
    if result.sharpe_ratio > 1.0:
        assessments.append(("✅ 夏普比率 > 1.0", "风险调整后收益良好"))
    elif result.sharpe_ratio > 0.5:
        assessments.append(("⚠️ 夏普比率 0.5-1.0", "风险调整后收益一般"))
    else:
        assessments.append(("❌ 夏普比率 < 0.5", "风险调整后收益较差"))

    # 最大回撤评估
    if result.max_drawdown < 0.15:
        assessments.append(("✅ 最大回撤 < 15%", "风险控制良好"))
    elif result.max_drawdown < 0.30:
        assessments.append(("⚠️ 最大回撤 15%-30%", "风险控制一般"))
    else:
        assessments.append(("❌ 最大回撤 > 30%", "风险控制较差"))

    for assessment, status in assessments:
        print(f"\n{assessment} - {status}")

    print("\n" + "=" * 60)
    print("回测验证完成！")
    print("=" * 60)

    return result


if __name__ == "__main__":
    # 设置随机种子以便复现结果
    random.seed(42)

    result = run_backtest_validation()
