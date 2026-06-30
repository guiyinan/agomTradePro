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
    def get_auto_advisor_decision_sheet(account_id: int | str) -> dict[str, Any]:
        """
        获取账户级自动投顾建议单。

        返回今日结论、订单建议、阻断项、风险提示和执行提示。该工具只读，
        不会执行任何交易；真实落地仍必须经过人工确认和现有执行流程。
        """
        client = AgomTradeProClient()
        return client.decision_rhythm.advisor_sheet(account_id=account_id)

    @server.tool()
    def get_auto_advisor_console(account_id: int | str) -> dict[str, Any]:
        """
        获取首页自动投顾 console 聚合数据。

        用于 MCP 客户端直接读取与 Dashboard 首页一致的账户快照、建议摘要、
        风控闸门和 freshness 摘要。
        """
        client = AgomTradeProClient()
        return client.dashboard.auto_advisor_console(account_id=account_id)

    @server.tool()
    def ask_auto_advisor(account_id: int | str, question: str) -> dict[str, Any]:
        """
        使用自然语言查询个人自动投顾上下文。

        复用 Dashboard auto-advisor query API，适合询问“最大风险是什么”、
        “为什么减仓”、“哪些持仓已触发证伪”等 CLI/TUI/MCP 共享问题。
        """
        client = AgomTradeProClient()
        return client.dashboard.auto_advisor_query(
            account_id=account_id,
            question=question,
        )

    @server.tool()
    def get_auto_advisor_weekly_report(
        account_id: int | str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """
        获取个人自动投顾周报。

        `as_of` 可传 `YYYY-MM-DD`；不传则由后端按当前日期生成。
        """
        client = AgomTradeProClient()
        return client.dashboard.auto_advisor_weekly_report(
            account_id=account_id,
            as_of=as_of,
        )

    @server.tool()
    def create_auto_advisor_weekly_report(
        account_id: int | str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """
        生成并持久化个人自动投顾周报。

        会写入周报快照、投资日记、Dashboard 通知和审计日志；不会执行交易。
        `as_of` 可传 `YYYY-MM-DD`。
        """
        client = AgomTradeProClient()
        return client.dashboard.create_auto_advisor_weekly_report(
            account_id=account_id,
            as_of=as_of,
        )

    @server.tool()
    def list_auto_advisor_weekly_report_history(
        account_id: int | str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """列出已持久化的个人自动投顾周报历史。"""
        client = AgomTradeProClient()
        return client.dashboard.auto_advisor_weekly_report_history(
            account_id=account_id,
            limit=limit,
        )

    @server.tool()
    def list_auto_advisor_notifications(
        account_id: int | str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """列出已持久化的自动投顾通知/输出渠道记录。"""
        client = AgomTradeProClient()
        return client.dashboard.auto_advisor_notifications(
            account_id=account_id,
            limit=limit,
        )

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
        kwargs = {
            "top_n": top_n,
            "portfolio_id": portfolio_id,
            "pool_mode": pool_mode,
        }
        if alpha_scope is not None:
            kwargs["alpha_scope"] = alpha_scope
        return client.dashboard.alpha_stocks(
            **kwargs,
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
        kwargs = {
            "top_n": top_n,
            "portfolio_id": portfolio_id,
            "pool_mode": pool_mode,
        }
        if alpha_scope is not None:
            kwargs["alpha_scope"] = alpha_scope
        return client.dashboard.alpha_refresh(**kwargs)

    @server.tool()
    def get_dashboard_positions() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.positions()

    @server.tool()
    def get_dashboard_allocation() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.allocation()
