"""AgomTradePro MCP Tools - Dashboard 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_dashboard_tools(server: FastMCP) -> None:
    @server.tool()
    def get_dashboard_summary_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.summary_v1()

    @server.tool()
    def get_dashboard_regime_quadrant_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.regime_quadrant_v1()

    @server.tool()
    def get_dashboard_equity_curve_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.equity_curve_v1()

    @server.tool()
    def get_dashboard_signal_status_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.signal_status_v1()

    @server.tool()
    def get_dashboard_alpha_decision_chain_v1(
        top_n: int = 10,
        max_candidates: int = 5,
        max_pending: int = 10,
    ) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.alpha_decision_chain_v1(
            top_n=top_n,
            max_candidates=max_candidates,
            max_pending=max_pending,
        )

    @server.tool()
    def get_dashboard_alpha_candidates(
        top_n: int = 10,
        portfolio_id: int | None = None,
    ) -> dict[str, Any]:
        """
        获取账户驱动的 Dashboard Alpha 候选视图。

        返回当前组合的 `Alpha Top 候选/排名`、`可行动候选`、`待执行队列`、
        缓存/实时元数据，以及最近历史 run 摘要。响应会附带 `contract`：
        `recommendation_ready=false` 时，Agent 不得把待执行或异步排队状态解释为推荐。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_stocks(top_n=top_n, portfolio_id=portfolio_id)

    @server.tool()
    def get_dashboard_alpha_history(
        portfolio_id: int | None = None,
        trade_date: str | None = None,
        stock_code: str | None = None,
        stage: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """
        获取 Dashboard Alpha 历史 run 列表。

        支持按组合、日期、股票、阶段、来源过滤历史推荐记录。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_history(
            portfolio_id=portfolio_id,
            trade_date=trade_date,
            stock_code=stock_code,
            stage=stage,
            source=source,
        )

    @server.tool()
    def get_dashboard_alpha_history_detail(run_id: int) -> dict[str, Any]:
        """
        获取单次 Dashboard Alpha 历史 run 的详细快照。

        返回逐票的买入理由、不买理由、证伪条件、风控闸门和建议仓位。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_history_detail(run_id)

    @server.tool()
    def trigger_dashboard_alpha_refresh(
        top_n: int = 10,
        portfolio_id: int | None = None,
    ) -> dict[str, Any]:
        """
        手动触发当前组合的 Dashboard Alpha 实时刷新。

        该工具只触发 Qlib 后台刷新任务，作用于账户驱动池，而不是固定指数池。
        返回的 `contract.must_not_treat_as_recommendation` 恒为 true；刷新完成后需再次调用
        `get_dashboard_alpha_candidates` 读取真实 scoped cache。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_refresh(top_n=top_n, portfolio_id=portfolio_id)

    @server.tool()
    def get_dashboard_positions() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.positions()

    @server.tool()
    def get_dashboard_allocation() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.allocation()
