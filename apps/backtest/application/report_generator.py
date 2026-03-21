"""
Backtest Report Generator

生成回测结果的 HTML 报告，包括：
- 资金曲线图
- 收益分布
- 回撤分析
- 交易记录
- 风险指标
"""

import os
from typing import Optional, Dict, Any, List
from datetime import date
from dataclasses import dataclass
import json


@dataclass
class ReportConfig:
    """报告配置"""
    output_dir: str = "reports/backtest"
    include_charts: bool = True
    include_trades: bool = True
    include_regime_analysis: bool = True


class BacktestReportGenerator:
    """
    回测报告生成器

    生成包含图表、指标、交易记录的完整 HTML 报告。
    """

    def __init__(self, config: Optional[ReportConfig] = None):
        self.config = config or ReportConfig()

    def generate(
        self,
        backtest_result: Any,
        benchmark_data: Optional[List[float]] = None
    ) -> str:
        """
        生成 HTML 报告

        Args:
            backtest_result: 回测结果对象
            benchmark_data: 基准数据（可选）

        Returns:
            str: 生成的 HTML 文件路径
        """
        # 准备数据
        data = self._prepare_report_data(backtest_result, benchmark_data)

        # 生成 HTML
        html_content = self._generate_html(data)

        # 保存文件
        output_path = self._save_report(backtest_result, html_content)

        return output_path

    def _prepare_report_data(
        self,
        backtest_result: Any,
        benchmark_data: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """准备报告数据"""

        # 从 backtest_result 提取数据
        equity_curve = getattr(backtest_result, 'equity_curve', [])
        trades = getattr(backtest_result, 'trades', [])
        regime_history = getattr(backtest_result, 'regime_history', [])
        warnings = getattr(backtest_result, 'warnings', [])

        # 基础指标
        total_return = getattr(backtest_result, 'total_return', 0.0)
        annualized_return = getattr(backtest_result, 'annualized_return', 0.0)
        max_drawdown = getattr(backtest_result, 'max_drawdown', 0.0)
        sharpe_ratio = getattr(backtest_result, 'sharpe_ratio', 0.0)

        # 计算额外指标
        equity_values = [e.get('value', e) if isinstance(e, dict) else e for e in equity_curve]
        drawdowns = self._calculate_drawdowns(equity_values)

        return {
            'backtest_name': getattr(backtest_result, 'name', 'Backtest'),
            'dates': [e.get('date') for e in equity_curve if isinstance(e, dict)],
            'equity_values': equity_values,
            'benchmark_values': benchmark_data or [],
            'trades': trades,
            'regime_history': regime_history,
            'warnings': warnings,
            'metrics': {
                'total_return': total_return * 100 if total_return < 1 else total_return,
                'annualized_return': annualized_return * 100 if annualized_return < 1 else annualized_return,
                'max_drawdown': abs(max_drawdown) * 100,
                'sharpe_ratio': sharpe_ratio,
            },
            'drawdowns': drawdowns,
            'start_date': getattr(backtest_result, 'start_date', ''),
            'end_date': getattr(backtest_result, 'end_date', ''),
            'initial_capital': float(getattr(backtest_result, 'initial_capital', 0)),
            'final_capital': float(getattr(backtest_result, 'final_capital', 0)),
        }

    def _calculate_drawdowns(self, equity_values: List[float]) -> List[Dict[str, Any]]:
        """计算回撤序列"""
        if not equity_values:
            return []

        drawdowns = []
        peak = equity_values[0]

        for i, value in enumerate(equity_values):
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100 if peak > 0 else 0
            drawdowns.append({
                'date': i,
                'drawdown': drawdown,
                'peak': peak,
                'value': value
            })

        return drawdowns

    def _generate_html(self, data: Dict[str, Any]) -> str:
        """生成 HTML 内容"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{data['backtest_name']} - 回测报告</title>
    <script src="/static/vendor/chartjs/chart.umd.min.js"></script>
    <script src="/static/vendor/chartjs/chartjs-plugin-annotation.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f7fa; color: #333; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .header h1 {{ font-size: 28px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .metric-card h3 {{ font-size: 14px; color: #666; margin-bottom: 8px; }}
        .metric-card .value {{ font-size: 24px; font-weight: bold; }}
        .metric-card .value.positive {{ color: #10b981; }}
        .metric-card .value.negative {{ color: #ef4444; }}
        .chart-container {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .chart-container h2 {{ font-size: 18px; margin-bottom: 15px; color: #333; }}
        .chart-wrapper {{ position: relative; height: 400px; }}
        .trades-table {{ background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .trades-table h2 {{ font-size: 18px; padding: 20px; margin-bottom: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f9fafb; padding: 12px; text-align: left; font-weight: 600; font-size: 13px; }}
        td {{ padding: 12px; border-bottom: 1px solid #e5e7eb; font-size: 13px; }}
        tr:hover {{ background: #f9fafb; }}
        .regime-tag {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 500; }}
        .regime-Recovery {{ background: #d1fae5; color: #065f46; }}
        .regime-Overheat {{ background: #fed7aa; color: #9a3412; }}
        .regime-Stagflation {{ background: #fecaca; color: #991b1b; }}
        .regime-Deflation {{ background: #e0e7ff; color: #3730a3; }}
        .warnings {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
        .warnings h3 {{ color: #92400e; margin-bottom: 8px; }}
        .warnings ul {{ list-style-position: inside; color: #92400e; }}
        .warnings li {{ margin-bottom: 4px; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>{data['backtest_name']}</h1>
            <p>回测期间: {data['start_date']} 至 {data['end_date']}</p>
            <p>初始资金: ¥{data['initial_capital']:,.2f} → 最终资金: ¥{data['final_capital']:,.2f}</p>
        </div>

        <!-- Warnings -->
        {self._generate_warnings_html(data.get('warnings', []))}

        <!-- Metrics -->
        <div class="metrics-grid">
            {self._generate_metric_html('总收益率', f"{data['metrics']['total_return']:.2f}%", data['metrics']['total_return'] >= 0)}
            {self._generate_metric_html('年化收益率', f"{data['metrics']['annualized_return']:.2f}%", data['metrics']['annualized_return'] >= 0)}
            {self._generate_metric_html('最大回撤', f"{data['metrics']['max_drawdown']:.2f}%", True)}
            {self._generate_metric_html('夏普比率', f"{data['metrics']['sharpe_ratio']:.3f}", data['metrics']['sharpe_ratio'] > 1)}
        </div>

        <!-- Equity Curve Chart -->
        <div class="chart-container">
            <h2>资金曲线</h2>
            <div class="chart-wrapper">
                <canvas id="equityChart"></canvas>
            </div>
        </div>

        <!-- Drawdown Chart -->
        <div class="chart-container">
            <h2>回撤分析</h2>
            <div class="chart-wrapper">
                <canvas id="drawdownChart"></canvas>
            </div>
        </div>

        <!-- Trades Table -->
        {self._generate_trades_html(data.get('trades', []))}

        <!-- Footer -->
        <div class="footer">
            <p>Generated by AgomTradePro Backtest Engine | {date.today().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>

    <script>
        // Chart.js Configuration
        const chartColors = {{
            primary: '#667eea',
            positive: '#10b981',
            negative: '#ef4444',
            grid: '#e5e7eb'
        }};

        // Equity Curve Chart
        const equityCtx = document.getElementById('equityChart').getContext('2d');
        new Chart(equityCtx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(data['dates'][-100:] if len(data['dates']) > 100 else data['dates'])},
                datasets: [{{
                    label: '策略净值',
                    data: {json.dumps(data['equity_values'][-100:] if len(data['equity_values']) > 100 else data['equity_values'])},
                    borderColor: chartColors.primary,
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    fill: true,
                    tension: 0.4
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: true }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        grid: {{ color: chartColors.grid }}
                    }},
                    x: {{
                        grid: {{ display: false }}
                    }}
                }}
            }}
        }});

        // Drawdown Chart
        const drawdownCtx = document.getElementById('drawdownChart').getContext('2d');
        new Chart(drawdownCtx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(data['dates'][-100:] if len(data['dates']) > 100 else data['dates'])},
                datasets: [{{
                    label: '回撤 (%)',
                    data: {json.dumps([d['drawdown'] for d in data['drawdowns']][-100:] if len(data['drawdowns']) > 100 else [d['drawdown'] for d in data['drawdowns']])},
                    borderColor: chartColors.negative,
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.4
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: true }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        grid: {{ color: chartColors.grid }}
                    }},
                    x: {{
                        grid: {{ display: false }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
        return html

    def _generate_warnings_html(self, warnings: List[str]) -> str:
        """生成警告 HTML"""
        if not warnings:
            return ""
        return f"""
        <div class="warnings">
            <h3>⚠️ 警告信息</h3>
            <ul>{''.join(f'<li>{w}</li>' for w in warnings)}</ul>
        </div>
        """

    def _generate_metric_html(self, label: str, value: str, is_positive: bool) -> str:
        """生成指标卡片 HTML"""
        css_class = "positive" if is_positive else "negative"
        return f"""
        <div class="metric-card">
            <h3>{label}</h3>
            <div class="value {css_class}">{value}</div>
        </div>
        """

    def _generate_trades_html(self, trades: List[Dict[str, Any]]) -> str:
        """生成交易表格 HTML"""
        if not trades:
            return ""

        trades_html = [f"""
        <div class="trades-table">
            <h2>交易记录</h2>
            <table>
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>资产</th>
                        <th>操作</th>
                        <th>数量</th>
                        <th>价格</th>
                        <th>金额</th>
                    </tr>
                </thead>
                <tbody>
        """]

        for trade in trades[:100]:  # 限制显示前100条
            if isinstance(trade, dict):
                trades_html.append(f"""
                    <tr>
                        <td>{trade.get('trade_date', trade.get('date', ''))}</td>
                        <td>{trade.get('asset_class', trade.get('asset', ''))}</td>
                        <td>{trade.get('action', '')}</td>
                        <td>{trade.get('shares', 0):.2f}</td>
                        <td>¥{trade.get('price', 0):.2f}</td>
                        <td>¥{trade.get('notional', 0):,.2f}</td>
                    </tr>
                """)

        trades_html.append("""
                </tbody>
            </table>
        </div>
        """)

        return "".join(trades_html)

    def _save_report(self, backtest_result: Any, html_content: str) -> str:
        """保存报告到文件"""
        os.makedirs(self.config.output_dir, exist_ok=True)

        # 生成文件名
        backtest_name = getattr(backtest_result, 'name', 'backtest').replace(' ', '_')
        backtest_id = getattr(backtest_result, 'id', '')
        timestamp = date.today().strftime('%Y%m%d_%H%M%S')

        filename = f"{backtest_name}_{backtest_id}_{timestamp}.html"
        output_path = os.path.join(self.config.output_dir, filename)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return output_path


def generate_backtest_report(backtest_result: Any, config: Optional[ReportConfig] = None) -> str:
    """
    便捷函数：生成回测报告

    Args:
        backtest_result: 回测结果对象
        config: 报告配置（可选）

    Returns:
        str: 生成的 HTML 文件路径
    """
    generator = BacktestReportGenerator(config)
    return generator.generate(backtest_result)
