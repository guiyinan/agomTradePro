"""
AgomTradePro MCP Tools - Regime 宏观象限工具

提供宏观象限相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_regime_tools(server: FastMCP) -> None:
    """注册 Regime 相关的 MCP 工具"""

    @server.tool()
    def get_current_regime() -> dict[str, Any]:
        """
        获取当前宏观象限

        返回当前的宏观象限状态，包括主导象限、增长水平、通胀水平等信息。

        Returns:
            包含以下字段的字典：
            - dominant_regime: 主导象限（Recovery/Overheat/Stagflation/Repression）
            - growth_level: 增长水平（up/down/neutral）
            - inflation_level: 通胀水平（up/down/neutral）
            - growth_indicator: 增长指标名称
            - inflation_indicator: 通胀指标名称
            - growth_value: 增长指标值
            - inflation_value: 通胀指标值
            - observed_at: 观测日期

        Example:
            >>> regime = get_current_regime()
            >>> print(f"当前象限: {regime['dominant_regime']}")
        """
        client = AgomTradeProClient()
        regime = client.regime.get_current()

        return {
            "dominant_regime": regime.dominant_regime,
            "growth_level": regime.growth_level,
            "inflation_level": regime.inflation_level,
            "growth_indicator": regime.growth_indicator,
            "inflation_indicator": regime.inflation_indicator,
            "growth_value": regime.growth_value,
            "inflation_value": regime.inflation_value,
            "observed_at": regime.observed_at.isoformat(),
        }

    @server.tool()
    def calculate_regime(
        as_of_date: str | None = None,
        growth_indicator: str = "PMI",
        inflation_indicator: str = "CPI",
        use_kalman: bool = True,
    ) -> dict[str, Any]:
        """
        计算指定日期的 Regime 判定

        Args:
            as_of_date: 计算日期（ISO 格式，如 2024-01-01），None 表示使用最新数据
            growth_indicator: 增长指标代码（默认 PMI）
            inflation_indicator: 通胀指标代码（默认 CPI）
            use_kalman: 是否使用 Kalman 滤波（默认 True）

        Returns:
            包含 Regime 状态的字典

        Example:
            >>> result = calculate_regime(
            ...     as_of_date="2024-01-01",
            ...     growth_indicator="PMI",
            ...     inflation_indicator="CPI"
            ... )
        """
        client = AgomTradeProClient()

        # 解析日期
        parsed_date = None
        if as_of_date:
            parsed_date = date.fromisoformat(as_of_date)

        regime = client.regime.calculate(
            as_of_date=parsed_date,
            growth_indicator=growth_indicator,
            inflation_indicator=inflation_indicator,
            use_kalman=use_kalman,
        )

        return {
            "dominant_regime": regime.dominant_regime,
            "growth_level": regime.growth_level,
            "inflation_level": regime.inflation_level,
            "growth_indicator": regime.growth_indicator,
            "inflation_indicator": regime.inflation_indicator,
            "growth_value": regime.growth_value,
            "inflation_value": regime.inflation_value,
            "observed_at": regime.observed_at.isoformat(),
        }

    @server.tool()
    def get_regime_history(
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取 Regime 历史记录

        Args:
            start_date: 开始日期（ISO 格式）
            end_date: 结束日期（ISO 格式）
            limit: 返回记录数量限制

        Returns:
            Regime 状态列表

        Example:
            >>> history = get_regime_history(
            ...     start_date="2023-01-01",
            ...     end_date="2024-12-31",
            ...     limit=365
            ... )
        """
        client = AgomTradeProClient()

        # 解析日期
        parsed_start = None
        parsed_end = None
        if start_date:
            parsed_start = date.fromisoformat(start_date)
        if end_date:
            parsed_end = date.fromisoformat(end_date)

        regimes = client.regime.history(
            start_date=parsed_start,
            end_date=parsed_end,
            limit=limit,
        )

        return [
            {
                "dominant_regime": r.dominant_regime,
                "growth_level": r.growth_level,
                "inflation_level": r.inflation_level,
                "observed_at": r.observed_at.isoformat(),
            }
            for r in regimes
        ]

    @server.tool()
    def get_regime_distribution(
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """
        获取 Regime 分布统计

        返回指定时间段内各象限出现的天数。

        Args:
            start_date: 开始日期（ISO 格式）
            end_date: 结束日期（ISO 格式）

        Returns:
            各象限出现天数的字典

        Example:
            >>> distribution = get_regime_distribution(
            ...     start_date="2023-01-01",
            ...     end_date="2024-12-31"
            ... )
            >>> print(f"Recovery 天数: {distribution['Recovery']}")
        """
        client = AgomTradeProClient()

        # 解析日期
        parsed_start = None
        parsed_end = None
        if start_date:
            parsed_start = date.fromisoformat(start_date)
        if end_date:
            parsed_end = date.fromisoformat(end_date)

        distribution = client.regime.get_regime_distribution(
            start_date=parsed_start,
            end_date=parsed_end,
        )

        return dict(distribution.items())

    @server.tool()
    def explain_regime(regime_type: str) -> str:
        """
        解释宏观象限的含义

        Args:
            regime_type: 象限类型（Recovery/Overheat/Stagflation/Repression）

        Returns:
            象限解释和投资建议

        Example:
            >>> explanation = explain_regime("Recovery")
        """
        explanations = {
            "Recovery": """复苏象限
特征：增长向上，通胀向下
经济处于复苏阶段，产出缺口收窄，通胀压力缓解。

投资建议：
- 股票：企业盈利改善，股市表现较好
- 商品：需求复苏带来商品价格上涨
- 房地产：低利率环境利好房地产
- 债券：收益率可能上行，需谨慎""",
            "Overheat": """过热象限
特征：增长向上，通胀向上
经济过热，通胀压力上升，央行可能收紧货币政策。

投资建议：
- 债券：利率上行压力，债券价格下跌
- 现金：保持流动性，等待更好的投资时机
- 股票：通胀和利率压力，股市波动加大
- 商品：通胀推高商品价格""",
            "Stagflation": """滞胀象限
特征：增长向下，通胀向上
经济停滞但通胀高企，是最具挑战性的宏观环境。

投资建议：
- 商品：通胀保值，黄金、原油等抗通胀
- 现金：保持流动性，规避风险
- 防御性股票：公用事业、消费必需品等
- 避免高估值成长股""",
            "Repression": """衰退象限
特征：增长向下，通胀向下
经济衰退，央行可能采取宽松货币政策。

投资建议：
- 债券：利率下行，债券价格上涨
- 股票：估值底部，优质股票具备配置价值
- 现金：保持流动性等待机会
- 房地产：低利率环境可能带来复苏""",
        }

        return explanations.get(
            regime_type,
            f"未知的象限类型: {regime_type}。有效值: Recovery, Overheat, Stagflation, Repression",
        )

    @server.tool()
    def get_recommended_assets(regime_type: str) -> list[str]:
        """
        根据宏观象限获取推荐资产类别

        Args:
            regime_type: 象限类型（Recovery/Overheat/Stagflation/Repression）

        Returns:
            推荐的资产类别列表

        Example:
            >>> assets = get_recommended_assets("Recovery")
            >>> print(f"推荐资产: {', '.join(assets)}")
        """
        recommendations = {
            "Recovery": ["股票", "商品", "房地产", "投资级信用债"],
            "Overheat": ["现金", "短期国债", "商品", "抗通胀资产"],
            "Stagflation": ["商品", "黄金", "现金", "防御性股票"],
            "Repression": ["长期国债", "高评级信用债", "优质股票", "房地产REITs"],
        }

        return recommendations.get(
            regime_type,
            [],
        )

