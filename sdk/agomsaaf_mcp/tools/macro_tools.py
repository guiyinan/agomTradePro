"""
AgomSAAF MCP Tools - Macro 宏观数据工具

提供宏观数据相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_macro_tools(server: FastMCP) -> None:
    """注册 Macro 相关的 MCP 工具"""

    @server.tool()
    def list_macro_indicators(
        data_source: str | None = None,
        frequency: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取宏观指标列表

        Args:
            data_source: 数据源过滤（如 Tushare/AKShare）
            frequency: 频率过滤（monthly/quarterly/daily）
            limit: 返回数量限制

        Returns:
            宏观指标列表

        Example:
            >>> indicators = list_macro_indicators(frequency="monthly")
        """
        client = AgomSAAFClient()
        indicators = client.macro.list_indicators(
            data_source=data_source,
            frequency=frequency,
            limit=limit,
        )

        return [
            {
                "code": i.code,
                "name": i.name,
                "unit": i.unit,
                "frequency": i.frequency,
                "data_source": i.data_source,
            }
            for i in indicators
        ]

    @server.tool()
    def get_macro_indicator(indicator_code: str) -> dict[str, Any]:
        """
        获取宏观指标详情

        Args:
            indicator_code: 指标代码（如 PMI/CPI）

        Returns:
            宏观指标详情

        Example:
            >>> indicator = get_macro_indicator("PMI")
        """
        client = AgomSAAFClient()
        indicator = client.macro.get_indicator(indicator_code)

        return {
            "code": indicator.code,
            "name": indicator.name,
            "unit": indicator.unit,
            "frequency": indicator.frequency,
            "data_source": indicator.data_source,
        }

    @server.tool()
    def get_macro_data(
        indicator_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取宏观指标数据

        Args:
            indicator_code: 指标代码（如 PMI/CPI）
            start_date: 开始日期（ISO 格式，如 2023-01-01）
            end_date: 结束日期（ISO 格式，如 2024-12-31）
            limit: 返回数量限制

        Returns:
            宏观数据点列表

        Example:
            >>> data = get_macro_data(
            ...     indicator_code="PMI",
            ...     start_date="2023-01-01",
            ...     end_date="2024-12-31"
            ... )
        """
        client = AgomSAAFClient()

        # 解析日期
        parsed_start = None
        parsed_end = None
        if start_date:
            parsed_start = date.fromisoformat(start_date)
        if end_date:
            parsed_end = date.fromisoformat(end_date)

        data_points = client.macro.get_indicator_data(
            indicator_code=indicator_code,
            start_date=parsed_start,
            end_date=parsed_end,
            limit=limit,
        )

        return [
            {
                "indicator_code": dp.indicator_code,
                "date": dp.date.isoformat(),
                "value": dp.value,
                "unit": dp.unit,
            }
            for dp in data_points
        ]

    @server.tool()
    def get_latest_macro_data(indicator_code: str) -> dict[str, Any] | None:
        """
        获取宏观指标最新数据

        Args:
            indicator_code: 指标代码（如 PMI/CPI）

        Returns:
            最新的宏观数据点，如果没有数据则返回 None

        Example:
            >>> latest = get_latest_macro_data("PMI")
        """
        client = AgomSAAFClient()
        latest = client.macro.get_latest_data(indicator_code)

        if latest is None:
            return None

        return {
            "indicator_code": latest.indicator_code,
            "date": latest.date.isoformat(),
            "value": latest.value,
            "unit": latest.unit,
        }

    @server.tool()
    def sync_macro_indicator(indicator_code: str, force: bool = False) -> dict[str, Any]:
        """
        同步宏观指标数据

        从数据源拉取最新数据并存储。

        Args:
            indicator_code: 指标代码（如 PMI/CPI）
            force: 是否强制同步（忽略缓存）

        Returns:
            同步结果

        Example:
            >>> result = sync_macro_indicator("PMI", force=True)
        """
        client = AgomSAAFClient()
        result = client.macro.sync_indicator(indicator_code, force=force)

        return result

    @server.tool()
    def explain_macro_indicator(indicator_code: str) -> str:
        """
        解释宏观指标的含义

        Args:
            indicator_code: 指标代码（如 PMI/CPI）

        Returns:
            指标解释和投资意义

        Example:
            >>> explanation = explain_macro_indicator("PMI")
        """
        explanations = {
            "PMI": """PMI（采购经理指数）
定义：反映制造业景气程度的指标，以50为荣枯线

解读：
- PMI > 50：制造业扩张，经济增长
- PMI < 50：制造业收缩，经济放缓
- PMI 上升：经济复苏趋势
- PMI 下降：经济下行风险

投资意义：
作为经济增长的领先指标，PMI 连续回升通常预示经济复苏，利好股票；连续下跌预示经济放缓，利好债券。""",
            "CPI": """CPI（消费者物价指数）
定义：反映居民消费价格变动情况的指标，衡量通胀水平

解读：
- CPI > 3%：通胀压力较大
- CPI < 1%：通缩风险
- CPI 稳定在 2%左右：温和通胀，经济健康

投资意义：
通胀上升可能导致央行加息，利空债券和股票；通缩则可能引发宽松政策，利好债券。""",
            "PPI": """PPI（生产者物价指数）
定义：反映工业企业产品出厂价格变动情况的指标

解读：
- PPI 上升：工业品价格上涨，可能传导至 CPI
- PPI 下降：工业通缩压力
- PPI 与 CPI 差值：反映产业链利润分配

投资意义：
PPI 是 CPI 的领先指标，对判断通胀趋势和工业企业盈利有重要参考价值。""",
            "M2": """M2（广义货币供应量）
定义：反映社会上现实和潜在购买力的指标

解读：
- M2 增速上升：货币政策宽松
- M2 增速下降：货币政策收紧
- M2 与 GDP 差值：反映流动性充裕程度

投资意义：
M2 增速上升通常利好股票和商品，但需警惕通胀风险；M2 增速下降可能导致流动性收紧。""",
            "SHIBOR": """SHIBOR（上海银行间同业拆放利率）
定义：反映银行间市场资金成本的指标

解读：
- SHIBOR 上升：资金面紧张，利率上行
- SHIBOR 下降：资金面宽松，利率下行
- SHIBOR 波动：反映市场情绪和流动性状况

投资意义：
作为市场利率的基准，SHIBOR 变化直接影响债券价格和股票估值。""",
        }

        return explanations.get(
            indicator_code,
            f"暂无指标 {indicator_code} 的解释。常见指标：PMI, CPI, PPI, M2, SHIBOR",
        )

