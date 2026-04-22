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
        pool_mode: str | None = None,
        alpha_scope: str | None = None,
    ) -> dict[str, Any]:
        """
        获取 Dashboard Alpha 候选视图。

        `alpha_scope=general` 返回通用研究排名，可使用 broader/universe cache，
        但始终是 research-only，不得用于真实决策。
        `alpha_scope=portfolio` 返回账户专属 scoped Alpha 结果，只有 strict readiness
        全部通过时，`recommendation_ready` 才可能为 true。
        响应会附带 `contract`，其中包含 `alpha_scope`、`readiness_status`、
        `scope_verification_status`、`freshness_status`、`blocked_reason` 等字段，
        用于明确区分“研究结果”和“可执行推荐”。
        `pool_mode` 支持 `strict_valuation`、`market`、`price_covered`。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_stocks(
            top_n=top_n,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            alpha_scope=alpha_scope,
        )

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
        pool_mode: str | None = None,
        alpha_scope: str | None = None,
    ) -> dict[str, Any]:
        """
        手动触发 Dashboard Alpha 刷新。

        `alpha_scope=general` 触发通用研究池刷新，结果只用于研究排名。
        `alpha_scope=portfolio` 触发账户专属 scoped Qlib 推理；此时必须提供 `portfolio_id`。
        返回的 `contract.must_not_treat_as_recommendation` 恒为 true；刷新完成后需再次调用
        `get_dashboard_alpha_candidates` 读取对应 scope 的真实结果。
        `pool_mode` 支持 `strict_valuation`、`market`、`price_covered`。
        """
        client = AgomTradeProClient()
        return client.dashboard.alpha_refresh(
            top_n=top_n,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            alpha_scope=alpha_scope,
        )

    @server.tool()
    def get_dashboard_positions() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.positions()

    @server.tool()
    def get_dashboard_allocation() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.allocation()
