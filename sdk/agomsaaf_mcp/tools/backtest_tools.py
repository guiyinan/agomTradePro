"""
AgomSAAF MCP Tools - Backtest 回测工具

提供回测相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_backtest_tools(server: FastMCP) -> None:
    """注册 Backtest 相关的 MCP 工具"""

    @server.tool()
    def run_backtest(
        strategy_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1000000.0,
    ) -> dict[str, Any]:
        """
        运行回测

        Args:
            strategy_name: 策略名称（如 momentum/mean_reversion）
            start_date: 回测开始日期（ISO 格式，如 2023-01-01）
            end_date: 回测结束日期（ISO 格式，如 2024-12-31）
            initial_capital: 初始资金（默认 100 万）

        Returns:
            回测结果

        Example:
            >>> result = run_backtest(
            ...     strategy_name="momentum",
            ...     start_date="2023-01-01",
            ...     end_date="2024-12-31",
            ...     initial_capital=1000000.0
            ... )
        """
        client = AgomSAAFClient()

        # 解析日期
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)

        try:
            result = client.backtest.run(
                strategy_name=strategy_name,
                start_date=parsed_start,
                end_date=parsed_end,
                initial_capital=initial_capital,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "strategy_name": strategy_name,
            }

        return {
            "success": True,
            "id": result.id,
            "status": result.status,
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
        }

    @server.tool()
    def get_backtest_result(backtest_id: int) -> dict[str, Any]:
        """
        获取回测结果详情

        Args:
            backtest_id: 回测 ID

        Returns:
            回测结果详情

        Example:
            >>> result = get_backtest_result(123)
        """
        client = AgomSAAFClient()
        result = client.backtest.get_result(backtest_id)

        return {
            "id": result.id,
            "status": result.status,
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
        }

    @server.tool()
    def list_backtests(
        strategy_name: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取回测列表

        Args:
            strategy_name: 策略名称过滤（可选）
            status: 状态过滤（可选）
            limit: 返回数量限制

        Returns:
            回测结果列表

        Example:
            >>> results = list_backtests(strategy_name="momentum", status="completed")
        """
        client = AgomSAAFClient()
        results = client.backtest.list_backtests(
            strategy_name=strategy_name,
            status=status,
            limit=limit,
        )

        return [
            {
                "id": r.id,
                "status": r.status,
                "total_return": r.total_return,
                "annual_return": r.annual_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
            }
            for r in results
        ]

    @server.tool()
    def get_backtest_equity_curve(backtest_id: int) -> list[dict[str, Any]]:
        """
        获取回测净值曲线

        Args:
            backtest_id: 回测 ID

        Returns:
            净值曲线数据

        Example:
            >>> curve = get_backtest_equity_curve(123)
        """
        client = AgomSAAFClient()
        curve = client.backtest.get_equity_curve(backtest_id)

        return curve

