"""
Backtest Runner Script.

运行回测并生成分析报告。

Usage:
    python scripts/run_backtest.py --start 2020-01-01 --end 2024-12-31
    python scripts/run_backtest.py --frequency monthly
    python scripts/run_backtest.py --plot
"""

import os
import sys
from datetime import date, timedelta

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
import django

django.setup()

import logging

from apps.audit.domain.services import AttributionAnalyzer, AttributionConfig, analyze_attribution
from apps.backtest.domain.services import (
    BacktestConfig,
    BacktestEngine,
    PITDataProcessor,
    RebalanceFrequency,
)
from apps.macro.infrastructure.adapters import PUBLICATION_LAGS
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.application.use_cases import CalculateRegimeUseCase
from apps.regime.domain.services import RegimeCalculator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# 模拟资产价格数据（简化版）
def get_simulated_asset_price(asset_class: str, as_of_date: date) -> float:
    """
    获取模拟资产价格

    简化版本：使用固定收益率模拟
    """
    # 基础价格
    base_prices = {
        "a_share_growth": 1.0,
        "a_share_value": 1.0,
        "china_bond": 1.0,
        "gold": 1.0,
        "commodity": 1.0,
        "cash": 1.0,
    }

    # 月度收益率（简化）
    monthly_returns = {
        "a_share_growth": 0.01,      # 1% 月度
        "a_share_value": 0.008,      # 0.8%
        "china_bond": 0.003,         # 0.3%
        "gold": 0.005,               # 0.5%
        "commodity": 0.004,          # 0.4%
        "cash": 0.0002,              # 0.02%
    }

    base = base_prices.get(asset_class, 1.0)
    monthly_return = monthly_returns.get(asset_class, 0.005)

    # 根据日期计算价格
    days = (as_of_date - date(2020, 1, 1)).days
    months = days / 30

    return base * (1 + monthly_return) ** months


def get_regime_for_date(as_of_date: date) -> dict:
    """
    获取指定日期的 Regime

    Args:
        as_of_date: 查询日期

    Returns:
        dict: Regime 信息
    """
    repository = DjangoMacroRepository()

    # 获取增长和通胀数据
    try:
        growth_series = repository.get_growth_series(
            indicator_code="PMI",
            start_date=date(2015, 1, 1),
            end_date=as_of_date
        )

        inflation_series = repository.get_inflation_series(
            indicator_code="CPI",
            start_date=date(2015, 1, 1),
            end_date=as_of_date
        )

        if not growth_series or not inflation_series:
            logger.warning(f"数据不足: {as_of_date}")
            return {
                "dominant_regime": "Recovery",
                "confidence": 0.25,
                "growth_momentum_z": 0.0,
                "inflation_momentum_z": 0.0,
            }

        # 使用 RegimeCalculator 计算
        calculator = RegimeCalculator(
            momentum_period=3,
            zscore_window=60,
            zscore_min_periods=24,
            sigmoid_k=2.0
        )

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=as_of_date
        )

        return {
            "dominant_regime": result.snapshot.dominant_regime,
            "confidence": result.snapshot.confidence,
            "growth_momentum_z": result.snapshot.growth_momentum_z,
            "inflation_momentum_z": result.snapshot.inflation_momentum_z,
            "distribution": result.snapshot.distribution,
        }

    except Exception as e:
        logger.error(f"获取 Regime 失败: {e}")
        return {
            "dominant_regime": "Recovery",
            "confidence": 0.25,
        }


def run_backtest(
    start_date: date,
    end_date: date,
    frequency: str = "monthly",
    initial_capital: float = 100000.0,
    use_pit: bool = False
):
    """
    运行回测

    Args:
        start_date: 起始日期
        end_date: 结束日期
        frequency: 再平衡频率
        initial_capital: 初始资金
        use_pit: 是否使用 Point-in-Time 数据
    """
    logger.info(f"\n{'='*60}")
    logger.info("运行回测")
    logger.info(f"{'='*60}")
    logger.info(f"时间范围: {start_date} ~ {end_date}")
    logger.info(f"再平衡频率: {frequency}")
    logger.info(f"初始资金: {initial_capital:,.2f}")
    logger.info(f"使用 PIT: {use_pit}")

    # 创建配置
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        rebalance_frequency=frequency,
        use_pit_data=use_pit,
        transaction_cost_bps=10
    )

    # 创建 PIT 处理器
    pit_processor = None
    if use_pit:
        pit_processor = PITDataProcessor(
            publication_lags={
                code: timedelta(days=lag.days)
                for code, lag in PUBLICATION_LAGS.items()
            }
        )

    # 创建回测引擎
    engine = BacktestEngine(
        config=config,
        get_regime_func=get_regime_for_date,
        get_asset_price_func=get_simulated_asset_price,
        pit_processor=pit_processor
    )

    # 运行回测
    logger.info("\n开始运行回测...")
    result = engine.run()

    # 打印结果
    print_backtest_result(result)

    # 运行归因分析
    logger.info("\n运行归因分析...")
    AttributionAnalyzer()

    # 简化的资产收益率
    asset_returns = {}
    for asset_class in ["a_share_growth", "a_share_value", "china_bond", "gold", "commodity"]:
        returns = []
        for dt, _ in result.equity_curve:
            price = get_simulated_asset_price(asset_class, dt)
            prev_price = get_simulated_asset_price(asset_class, dt - timedelta(days=30))
            ret = (price - prev_price) / prev_price if prev_price > 0 else 0
            returns.append(ret)
        asset_returns[asset_class] = list(zip([dt for dt, _ in result.equity_curve], returns, strict=True))

    attribution = analyze_attribution(
        backtest_result=result,
        regime_history=result.regime_history,
        asset_returns=asset_returns
    )

    print_attribution_result(attribution)

    return result, attribution


def print_backtest_result(result):
    """打印回测结果"""
    logger.info(f"\n{'='*60}")
    logger.info("回测结果")
    logger.info(f"{'='*60}")
    logger.info(f"初始资金: {result.config.initial_capital:,.2f}")
    logger.info(f"最终价值: {result.final_value:,.2f}")
    logger.info(f"总收益率: {result.total_return*100:.2f}%")
    logger.info(f"年化收益: {result.annualized_return*100:.2f}%")

    if result.sharpe_ratio is not None:
        logger.info(f"夏普比率: {result.sharpe_ratio:.3f}")
    else:
        logger.info("夏普比率: N/A")

    logger.info(f"最大回撤: {result.max_drawdown*100:.2f}%")
    logger.info(f"交易次数: {len(result.trades)}")

    # 打印前 10 笔交易
    if result.trades:
        logger.info("\n最近 10 笔交易:")
        for trade in result.trades[-10:]:
            logger.info(
                f"  {trade.trade_date} | {trade.asset_class:15s} | "
                f"{trade.action:4s} | {trade.shares:.2f} @ {trade.price:.2f} | "
                f"成本: {trade.cost:.2f}"
            )


def print_attribution_result(attribution):
    """打印归因分析结果"""
    logger.info(f"\n{'='*60}")
    logger.info("归因分析")
    logger.info(f"{'='*60}")
    logger.info(f"经验总结: {attribution.lesson_learned}")

    logger.info("\n收益归因:")
    logger.info(f"  择时收益: {attribution.regime_timing_pnl*100:.2f}%")
    logger.info(f"  选资产收益: {attribution.asset_selection_pnl*100:.2f}%")
    logger.info(f"  交互收益: {attribution.interaction_pnl*100:.2f}%")
    logger.info(f"  交易成本: {attribution.transaction_cost_pnl*100:.2f}%")

    logger.info("\n损失分析:")
    logger.info(f"  主要来源: {attribution.loss_source.value}")
    logger.info(f"  损失金额: {attribution.loss_amount*100:.2f}%")

    if attribution.improvement_suggestions:
        logger.info("\n改进建议:")
        for suggestion in attribution.improvement_suggestions:
            logger.info(f"  - {suggestion}")

    # 打印周期归因
    if attribution.period_attributions:
        logger.info("\n周期归因 (前 5 个):")
        for period_attr in attribution.period_attributions[:5]:
            logger.info(
                f"  {period_attr['start_date']} ~ {period_attr['end_date']} | "
                f"{period_attr['regime']:12s} | "
                f"组合收益: {period_attr['portfolio_return']*100:6.2f}% | "
                f"超额收益: {period_attr['excess_return']*100:6.2f}%"
            )


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="运行回测")
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="起始日期 (默认: 2020-01-01)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2024-12-31",
        help="结束日期 (默认: 2024-12-31)"
    )
    parser.add_argument(
        "--frequency",
        type=str,
        default="monthly",
        choices=["monthly", "quarterly", "yearly"],
        help="再平衡频率 (默认: monthly)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
        help="初始资金 (默认: 100000)"
    )
    parser.add_argument(
        "--pit",
        action="store_true",
        help="使用 Point-in-Time 数据"
    )

    args = parser.parse_args()

    # 解析日期
    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD 格式")
        return 1

    # 运行回测
    try:
        result, attribution = run_backtest(
            start_date=start_date,
            end_date=end_date,
            frequency=args.frequency,
            initial_capital=args.capital,
            use_pit=args.pit
        )
        return 0
    except Exception as e:
        logger.error(f"回测失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
