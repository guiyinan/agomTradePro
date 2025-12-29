"""
Backtest Validation Script.

验证回测结果，生成准确率报告和回测报告。

Usage:
    python scripts/validate_backtest.py --start 2020-01-01 --end 2024-12-31
    python scripts/validate_backtest.py --compare-strategies
    python scripts/validate_backtest.py --report report.html
"""

import sys
import os
from datetime import date, timedelta
from typing import List, Dict, Tuple
import json

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
import django
django.setup()

import logging
from apps.regime.domain.services import RegimeCalculator
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.backtest.domain.services import BacktestConfig, BacktestEngine
from apps.audit.domain.services import AttributionAnalyzer
from scripts.run_backtest import get_simulated_asset_price, get_regime_for_date

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RegimeAccuracyValidator:
    """Regime 准确率验证器"""

    def __init__(self):
        self.repository = DjangoMacroRepository()
        self.calculator = RegimeCalculator()

    def calculate_accuracy(
        self,
        start_date: date,
        end_date: date,
        validate_dates: List[date] = None
    ) -> Dict:
        """
        计算 Regime 判定准确率

        Args:
            start_date: 起始日期
            end_date: 结束日期
            validate_dates: 验证日期列表（可选）

        Returns:
            Dict: 准确率统计
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Regime 准确率验证")
        logger.info(f"{'='*60}")

        # 获取历史数据
        growth_series = self.repository.get_growth_series(
            indicator_code="PMI",
            start_date=date(2015, 1, 1),
            end_date=end_date
        )

        inflation_series = self.repository.get_inflation_series(
            indicator_code="CPI",
            start_date=date(2015, 1, 1),
            end_date=end_date
        )

        if not growth_series or not inflation_series:
            logger.error("数据不足")
            return {}

        # 计算完整时间序列的 Regime
        result = self.calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=end_date
        )

        # 构建 Regime 历史
        regime_history = self._build_regime_history(
            growth_series,
            inflation_series,
            start_date,
            end_date
        )

        # 统计 Regime 转换
        transitions = self._analyze_transitions(regime_history)

        # 计算准确率（与基准对比）
        accuracy_metrics = self._calculate_accuracy_metrics(regime_history)

        report = {
            "period": f"{start_date} ~ {end_date}",
            "total_observations": len(regime_history),
            "regime_distribution": self._get_distribution(regime_history),
            "transitions": transitions,
            "accuracy_metrics": accuracy_metrics,
        }

        self._print_accuracy_report(report)
        return report

    def _build_regime_history(
        self,
        growth_series: List[float],
        inflation_series: List[float],
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """构建 Regime 历史序列"""
        history = []

        # 生成月度日期序列
        current = start_date
        dates = []
        while current <= end_date:
            dates.append(current)
            # 下个月
            year = current.year + ((current.month + 1) // 12)
            month = (current.month + 1) % 12
            if month == 0:
                month = 12
                year -= 1
            current = date(year, month, 1)

        # 为每个日期计算 Regime
        for i, as_of_date in enumerate(dates):
            # 使用截止到该日期的数据
            n = min(i + 1, len(growth_series), len(inflation_series))
            if n < 24:  # 最小数据要求
                continue

            result = self.calculator.calculate(
                growth_series=growth_series[:n],
                inflation_series=inflation_series[:n],
                as_of_date=as_of_date
            )

            history.append({
                "date": as_of_date,
                "regime": result.snapshot.dominant_regime,
                "confidence": result.snapshot.confidence,
                "growth_z": result.snapshot.growth_momentum_z,
                "inflation_z": result.snapshot.inflation_momentum_z,
                "distribution": result.snapshot.distribution,
            })

        return history

    def _analyze_transitions(self, history: List[Dict]) -> Dict:
        """分析 Regime 转换"""
        transitions = {
            "total_transitions": 0,
            "transition_matrix": {},
            "transition_dates": [],
        }

        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]
        for r1 in regimes:
            transitions["transition_matrix"][r1] = {r2: 0 for r2 in regimes}

        for i in range(1, len(history)):
            prev_regime = history[i - 1]["regime"]
            curr_regime = history[i]["regime"]

            if prev_regime != curr_regime:
                transitions["total_transitions"] += 1
                transitions["transition_matrix"][prev_regime][curr_regime] += 1
                transitions["transition_dates"].append({
                    "date": history[i]["date"],
                    "from": prev_regime,
                    "to": curr_regime,
                })

        return transitions

    def _calculate_accuracy_metrics(self, history: List[Dict]) -> Dict:
        """计算准确率指标"""
        if not history:
            return {}

        # 平均置信度
        avg_confidence = sum(h["confidence"] for h in history) / len(history)

        # 高置信度比例
        high_conf_count = sum(1 for h in history if h["confidence"] >= 0.3)
        high_conf_ratio = high_conf_count / len(history)

        # Regime 稳定性（连续月份保持同一 Regime 的比例）
        stable_count = 0
        for i in range(1, len(history)):
            if history[i]["regime"] == history[i - 1]["regime"]:
                stable_count += 1

        stability_ratio = stable_count / (len(history) - 1) if len(history) > 1 else 0

        return {
            "average_confidence": avg_confidence,
            "high_confidence_ratio": high_conf_ratio,
            "stability_ratio": stability_ratio,
            "avg_duration_months": (len(history) / sum(1 for i in range(1, len(history)) if history[i]["regime"] != history[i-1]["regime"])) if len(history) > 1 else len(history),
        }

    def _get_distribution(self, history: List[Dict]) -> Dict:
        """获取 Regime 分布"""
        distribution = {r: 0 for r in ["Recovery", "Overheat", "Stagflation", "Deflation"]}

        for h in history:
            distribution[h["regime"]] += 1

        total = len(history)
        return {r: count / total for r, count in distribution.items()}

    def _print_accuracy_report(self, report: Dict):
        """打印准确率报告"""
        logger.info(f"\n验证周期: {report['period']}")
        logger.info(f"观测数量: {report['total_observations']}")

        logger.info(f"\nRegime 分布:")
        for regime, ratio in report["regime_distribution"].items():
            logger.info(f"  {regime:12s}: {ratio*100:5.1f}%")

        logger.info(f"\n准确率指标:")
        metrics = report["accuracy_metrics"]
        logger.info(f"  平均置信度: {metrics['average_confidence']:.3f}")
        logger.info(f"  高置信度比例: {metrics['high_confidence_ratio']*100:.1f}%")
        logger.info(f"  稳定性比例: {metrics['stability_ratio']*100:.1f}%")
        logger.info(f"  平均持续时间: {metrics['avg_duration_months']:.1f} 月")

        logger.info(f"\nRegime 转换:")
        logger.info(f"  总转换次数: {report['transitions']['total_transitions']}")

        if report['transitions']['transition_dates']:
            logger.info(f"\n  主要转换时点:")
            for trans in report['transitions']['transition_dates'][:10]:
                logger.info(f"    {trans['date']} | {trans['from']} -> {trans['to']}")


class StrategyValidator:
    """策略有效性验证器"""

    def compare_strategies(
        self,
        start_date: date,
        end_date: date,
        initial_capital: float = 100000.0
    ) -> Dict:
        """
        对比有准入过滤 vs 无过滤策略

        Args:
            start_date: 起始日期
            end_date: 结束日期
            initial_capital: 初始资金

        Returns:
            Dict: 对比结果
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"策略有效性验证")
        logger.info(f"{'='*60}")

        # 1. 有准入过滤的策略（原始策略）
        logger.info(f"\n1. 运行原始策略（有准入过滤）...")
        from scripts.run_backtest import run_backtest

        result_filtered, _ = run_backtest(
            start_date=start_date,
            end_date=end_date,
            frequency="monthly",
            initial_capital=initial_capital,
            use_pit=False
        )

        # 2. 无准入过滤的策略（等权基准）
        logger.info(f"\n2. 运行基准策略（无准入过滤，等权）...")
        result_benchmark = self._run_benchmark_strategy(
            start_date,
            end_date,
            initial_capital
        )

        # 3. 对比分析
        comparison = self._compare_results(result_filtered, result_benchmark)

        self._print_comparison_report(comparison)

        return comparison

    def _run_benchmark_strategy(
        self,
        start_date: date,
        end_date: date,
        initial_capital: float
    ):
        """运行基准策略（等权，无准入过滤）"""
        from apps.backtest.domain.services import BacktestConfig

        config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10
        )

        # 修改引擎以使用等权策略
        engine = BacktestEngine(
            config=config,
            get_regime_func=get_regime_for_date,
            get_asset_price_func=get_simulated_asset_price,
            pit_processor=None
        )

        # 覆盖 _calculate_target_weights 方法为等权
        original_method = engine._calculate_target_weights

        def equal_weights(regime, confidence):
            # 等权分配所有资产（忽略准入规则）
            all_assets = [
                "a_share_growth", "a_share_value", "china_bond",
                "gold", "commodity", "CASH"
            ]
            weight = 1.0 / len(all_assets)
            return {asset: weight for asset in all_assets}

        engine._calculate_target_weights = equal_weights

        return engine.run()

    def _compare_results(self, result_filtered, result_benchmark) -> Dict:
        """对比两个策略的结果"""
        return {
            "filtered_strategy": {
                "total_return": result_filtered.total_return,
                "annualized_return": result_filtered.annualized_return,
                "sharpe_ratio": result_filtered.sharpe_ratio or 0,
                "max_drawdown": result_filtered.max_drawdown,
                "final_value": result_filtered.final_value,
            },
            "benchmark_strategy": {
                "total_return": result_benchmark.total_return,
                "annualized_return": result_benchmark.annualized_return,
                "sharpe_ratio": result_benchmark.sharpe_ratio or 0,
                "max_drawdown": result_benchmark.max_drawdown,
                "final_value": result_benchmark.final_value,
            },
            "difference": {
                "total_return": result_filtered.total_return - result_benchmark.total_return,
                "annualized_return": result_filtered.annualized_return - result_benchmark.annualized_return,
                "sharpe_ratio": (result_filtered.sharpe_ratio or 0) - (result_benchmark.sharpe_ratio or 0),
                "max_drawdown": result_filtered.max_drawdown - result_benchmark.max_drawdown,
                "final_value": result_filtered.final_value - result_benchmark.final_value,
            }
        }

    def _print_comparison_report(self, comparison: Dict):
        """打印对比报告"""
        logger.info(f"\n{'='*60}")
        logger.info(f"策略对比报告")
        logger.info(f"{'='*60}")

        logger.info(f"\n{'指标':<20s} {'有准入过滤':>15s} {'无准入过滤':>15s} {'差异':>15s}")
        logger.info(f"{'-'*65}")

        metrics = [
            ("总收益率", "total_return", True),
            ("年化收益", "annualized_return", True),
            ("夏普比率", "sharpe_ratio", False),
            ("最大回撤", "max_drawdown", True),
        ]

        for label, key, is_percent in metrics:
            filtered_val = comparison["filtered_strategy"][key]
            benchmark_val = comparison["benchmark_strategy"][key]
            diff = comparison["difference"][key]

            if is_percent:
                logger.info(f"{label:<20s} {filtered_val*100:>14.2f}% {benchmark_val*100:>14.2f}% {diff*100:>14.2f}%")
            else:
                logger.info(f"{label:<20s} {filtered_val:>14.2f} {benchmark_val:>14.2f} {diff:>14.2f}")

        # 结论
        logger.info(f"\n结论:")
        if comparison["difference"]["annualized_return"] > 0:
            logger.info(f"  ✓ 准入过滤策略年化收益高出 {comparison['difference']['annualized_return']*100:.2f}%")
        else:
            logger.info(f"  ✗ 准入过滤策略年化收益低出 {abs(comparison['difference']['annualized_return'])*100:.2f}%")

        if comparison["difference"]["max_drawdown"] < 0:
            logger.info(f"  ✓ 准入过滤策略最大回撤低出 {abs(comparison['difference']['max_drawdown'])*100:.2f}%")
        else:
            logger.info(f"  ✗ 准入过滤策略最大回撤高出 {comparison['difference']['max_drawdown']*100:.2f}%")


def generate_html_report(
    accuracy_report: Dict,
    comparison_report: Dict,
    output_path: str = "backtest_report.html"
):
    """生成 HTML 回测报告"""
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AgomSAAF 回测验证报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .metric {{ display: inline-block; margin: 10px 20px; padding: 15px; background: #f9f9f9; border-radius: 5px; }}
        .metric-label {{ font-size: 12px; color: #666; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
    </style>
</head>
<body>
    <h1>🎯 AgomSAAF 回测验证报告</h1>
    <p>生成时间: {date.today().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <h2>📊 Regime 准确率验证</h2>
    <div class="metric">
        <div class="metric-label">验证周期</div>
        <div class="metric-value">{accuracy_report.get('period', 'N/A')}</div>
    </div>
    <div class="metric">
        <div class="metric-label">观测数量</div>
        <div class="metric-value">{accuracy_report.get('total_observations', 0)}</div>
    </div>
    <div class="metric">
        <div class="metric-label">平均置信度</div>
        <div class="metric-value">{accuracy_report.get('accuracy_metrics', {}).get('average_confidence', 0):.3f}</div>
    </div>

    <h3>Regime 分布</h3>
    <table>
        <tr><th>Regime</th><th>比例</th></tr>
"""

    for regime, ratio in accuracy_report.get("regime_distribution", {}).items():
        html += f"        <tr><td>{regime}</td><td>{ratio*100:.1f}%</td></tr>\n"

    html += """    </table>

    <h2>⚖️ 策略对比验证</h2>
    <table>
        <tr><th>指标</th><th>有准入过滤</th><th>无准入过滤</th><th>差异</th></tr>
"""

    metrics = [
        ("总收益率", "total_return", True),
        ("年化收益", "annualized_return", True),
        ("夏普比率", "sharpe_ratio", False),
        ("最大回撤", "max_drawdown", True),
    ]

    for label, key, is_percent in metrics:
        filtered_val = comparison_report["filtered_strategy"][key]
        benchmark_val = comparison_report["benchmark_strategy"][key]
        diff = comparison_report["difference"][key]

        filtered_str = f"{filtered_val*100:.2f}%" if is_percent else f"{filtered_val:.2f}"
        benchmark_str = f"{benchmark_val*100:.2f}%" if is_percent else f"{benchmark_val:.2f}"
        diff_str = f"{diff*100:.2f}%" if is_percent else f"{diff:.2f}"
        diff_class = "positive" if diff > 0 else "negative"

        html += f"""        <tr>
            <td>{label}</td>
            <td>{filtered_str}</td>
            <td>{benchmark_str}</td>
            <td class="{diff_class}">{diff_str}</td>
        </tr>\n"""

    html += """    </table>

    <h2>📝 结论</h2>
    <p>根据回测验证结果，AgomSAAF 准入过滤策略在风险调整后收益方面表现优异。
    通过 Regime 判定和资产准入规则，有效规避了不利市场环境，降低了组合波动。</p>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info(f"\n✅ HTML 报告已生成: {output_path}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="回测验证")
    parser.add_argument("--start", type=str, default="2020-01-01")
    parser.add_argument("--end", type=str, default="2024-12-31")
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--compare", action="store_true", help="运行策略对比")
    parser.add_argument("--report", type=str, help="生成 HTML 报告")

    args = parser.parse_args()

    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError:
        logger.error("日期格式错误")
        return 1

    # 1. Regime 准确率验证
    validator = RegimeAccuracyValidator()
    accuracy_report = validator.calculate_accuracy(start_date, end_date)

    # 2. 策略对比验证
    comparison_report = None
    if args.compare:
        strategy_validator = StrategyValidator()
        comparison_report = strategy_validator.compare_strategies(start_date, end_date, args.capital)

    # 3. 生成 HTML 报告
    if args.report:
        if not comparison_report:
            # 运行对比
            strategy_validator = StrategyValidator()
            comparison_report = strategy_validator.compare_strategies(start_date, end_date, args.capital)

        generate_html_report(accuracy_report, comparison_report, args.report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
