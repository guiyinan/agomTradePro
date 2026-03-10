"""
AgomSAAF MCP Tools - Equity 个股分析工具

提供个股分析相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_equity_tools(server: FastMCP) -> None:
    """注册 Equity 相关的 MCP 工具"""

    @server.tool()
    def get_stock_score(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取股票评分

        Args:
            stock_code: 股票代码（如 000001.SZ）
            as_of_date: 评分日期（ISO 格式，None 表示最新）

        Returns:
            股票评分信息

        Example:
            >>> score = get_stock_score("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.get_stock_score(stock_code, parsed_date)

    @server.tool()
    def list_stocks(
        sector: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取股票列表

        Args:
            sector: 行业过滤（可选）
            min_score: 最低评分过滤（可选）
            limit: 返回数量限制

        Returns:
            股票列表

        Example:
            >>> stocks = list_stocks(sector="银行", min_score=60)
        """
        client = AgomSAAFClient()
        return client.equity.list_stocks(sector=sector, min_score=min_score, limit=limit)

    @server.tool()
    def get_stock_detail(stock_code: str) -> dict[str, Any]:
        """
        获取股票详情

        Args:
            stock_code: 股票代码

        Returns:
            股票详情

        Example:
            >>> detail = get_stock_detail("000001.SZ")
        """
        client = AgomSAAFClient()
        return client.equity.get_stock_detail(stock_code)

    @server.tool()
    def get_stock_recommendations(
        regime: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取股票推荐

        Args:
            regime: 宏观象限过滤（可选）
            limit: 返回数量限制

        Returns:
            推荐股票列表

        Example:
            >>> recs = get_stock_recommendations(regime="Recovery")
        """
        client = AgomSAAFClient()
        return client.equity.get_recommendations(regime=regime, limit=limit)

    @server.tool()
    def analyze_stock(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        分析股票

        Args:
            stock_code: 股票代码
            as_of_date: 分析日期（ISO 格式，None 表示最新）

        Returns:
            股票分析结果

        Example:
            >>> analysis = analyze_stock("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.analyze_stock(stock_code, parsed_date)

    @server.tool()
    def get_stock_financials(
        stock_code: str,
        report_type: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        获取股票财务数据

        Args:
            stock_code: 股票代码
            report_type: 报告类型（annual/quarterly）
            limit: 返回数量限制

        Returns:
            财务数据列表

        Example:
            >>> financials = get_stock_financials("000001.SZ")
        """
        client = AgomSAAFClient()
        return client.equity.get_financials(stock_code, report_type, limit)

    @server.tool()
    def get_stock_valuation(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取股票估值数据

        Args:
            stock_code: 股票代码
            as_of_date: 估值日期（ISO 格式，None 表示最新）

        Returns:
            估值数据

        Example:
            >>> valuation = get_stock_valuation("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.get_valuation(stock_code, parsed_date)

    # =========================================================================
    # 估值修复跟踪工具
    # =========================================================================

    @server.tool()
    def get_valuation_repair_status(
        stock_code: str,
        lookback_days: int = 756,
    ) -> dict[str, Any]:
        """
        获取股票估值修复状态

        实时计算单只股票的估值修复状态，包括当前阶段、修复进度、速度等。

        Args:
            stock_code: 股票代码（如 000001.SZ）
            lookback_days: 回看窗口天数（默认 756 天，约 3 年）

        Returns:
            估值修复状态信息，包括：
            - phase: 当前阶段（undervalued/repair_started/repairing/near_target/completed/stalled 等）
            - composite_percentile: 综合估值分位数
            - repair_progress: 修复进度（0-1）
            - repair_speed_per_30d: 修复速度（每30天百分点）
            - estimated_days_to_target: 预计到达目标天数
            - is_stalled: 是否停滞
            - description: 状态描述

        Example:
            >>> status = get_valuation_repair_status("000001.SZ")
            >>> print(f"阶段: {status['phase']}")
        """
        client = AgomSAAFClient()
        return client.equity.get_valuation_repair_status(stock_code, lookback_days)

    @server.tool()
    def get_valuation_repair_history(
        stock_code: str,
        lookback_days: int = 252,
    ) -> list[dict[str, Any]]:
        """
        获取估值修复历史百分位序列

        返回指定股票的历史估值百分位时间序列，用于绘制图表。

        Args:
            stock_code: 股票代码（如 000001.SZ）
            lookback_days: 回看窗口天数（默认 252 天，约 1 年）

        Returns:
            百分位历史点列表，每个点包含：
            - trade_date: 交易日期
            - pe_percentile: PE 分位数
            - pb_percentile: PB 分位数
            - composite_percentile: 综合分位数

        Example:
            >>> history = get_valuation_repair_history("000001.SZ")
            >>> for point in history[-10:]:
            ...     print(f"{point['trade_date']}: {point['composite_percentile'] * 100:.1f}%")
        """
        client = AgomSAAFClient()
        return client.equity.get_valuation_repair_history(stock_code, lookback_days)

    @server.tool()
    def scan_valuation_repairs(
        universe: str = "all_active",
        lookback_days: int = 756,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """
        批量扫描估值修复股票

        对指定股票池进行批量扫描，识别估值修复股票并保存快照。

        Args:
            universe: 股票池标识（"all_active" 或 "current_pool"）
            lookback_days: 回看窗口天数（默认 756 天）
            limit: 扫描数量限制（可选）

        Returns:
            扫描结果，包括：
            - scanned_count: 扫描数量
            - saved_count: 保存数量
            - failed_count: 失败数量
            - phase_counts: 各阶段数量统计

        Example:
            >>> result = scan_valuation_repairs(universe="all_active")
            >>> print(f"扫描 {result['scanned_count']} 只，保存 {result['saved_count']} 只")
        """
        client = AgomSAAFClient()
        return client.equity.scan_valuation_repairs(universe, lookback_days, limit)

    @server.tool()
    def list_valuation_repairs(
        universe: str = "all_active",
        phase: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        列出估值修复股票

        从快照表读取活跃的估值修复股票列表。

        Args:
            universe: 股票池标识（"all_active" 或 "current_pool"）
            phase: 阶段过滤（undervalued/repair_started/repairing/near_target/stalled）
            limit: 返回数量限制

        Returns:
            修复股票列表，包括：
            - count: 总数量
            - results: 股票列表

        Example:
            >>> result = list_valuation_repairs(phase="repairing")
            >>> for stock in result['results']:
            ...     print(f"{stock['stock_code']}: {stock['phase']}")
        """
        client = AgomSAAFClient()
        return client.equity.list_valuation_repairs(universe, phase, limit)

    @server.tool()
    def sync_valuation_data(
        days_back: int = 1,
        stock_codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        primary_source: str = "akshare",
        fallback_source: str = "tushare",
    ) -> dict[str, Any]:
        """
        同步估值数据到本地估值表。

        这是数据治理工具，不代表信号已可直接用于自动交易。
        """
        client = AgomSAAFClient()
        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None
        return client.equity.sync_valuation_data(
            days_back=days_back,
            stock_codes=stock_codes,
            start_date=parsed_start,
            end_date=parsed_end,
            primary_source=primary_source,
            fallback_source=fallback_source,
        )

    @server.tool()
    def validate_valuation_data(
        as_of_date: str | None = None,
        primary_source: str = "akshare",
    ) -> dict[str, Any]:
        """
        校验本地估值数据质量并生成 gate 快照。

        这是数据治理工具，不代表信号已可直接用于自动交易。
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.validate_valuation_data(
            as_of_date=parsed_date,
            primary_source=primary_source,
        )

    @server.tool()
    def get_valuation_data_freshness() -> dict[str, Any]:
        """
        获取估值数据新鲜度。
        """
        client = AgomSAAFClient()
        return client.equity.get_valuation_data_freshness()

    @server.tool()
    def get_valuation_data_quality_latest() -> dict[str, Any]:
        """
        获取最近一次估值数据质量快照。
        """
        client = AgomSAAFClient()
        return client.equity.get_valuation_data_quality_latest()
