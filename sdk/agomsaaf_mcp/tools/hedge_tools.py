"""
AgomSAAF MCP Tools - Hedge 对冲组合工具

提供对冲组合相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_hedge_tools(server: FastMCP) -> None:
    """注册 Hedge 相关的 MCP 工具"""

    @server.tool()
    def check_hedge_effectiveness(pair_name: str) -> dict[str, Any]:
        """
        检查对冲对有效性

        评估指定对冲对的对冲效果。

        Args:
            pair_name: 对冲对名称，如：
                - "股债对冲" - 沪深300ETF vs 10年国债ETF
                - "成长价值对冲" - 创业板ETF vs 红利ETF
                - "大小盘对冲" - 中证1000ETF vs 沪深300ETF
                - "股票黄金对冲" - 沪深300ETF vs 黄金ETF

        Returns:
            包含以下字段的字典：
            - pair_name: 对冲对名称
            - correlation: 当前相关性
            - beta: Beta值
            - hedge_ratio: 对冲比例
            - hedge_method: 对冲方法
            - effectiveness: 对冲有效性 (0-1)
            - rating: 评级 (优秀/良好/一般/较差)
            - recommendation: 建议说明

        Example:
            >>> result = check_hedge_effectiveness("股债对冲")
            >>> print(f"对冲有效性: {result['effectiveness']}")
            >>> print(f"建议: {result['recommendation']}")
        """
        client = AgomSAAFClient()

        # Get hedge pair effectiveness
        # Note: This would call the hedge module API when implemented
        result = client.hedge.check_effectiveness(pair_name)

        if "error" in result:
            return {
                "error": result["error"],
                "message": f"无法获取对冲有效性，请检查对冲对名称: {pair_name}",
                "available_pairs": [
                    "股债对冲",
                    "成长价值对冲",
                    "大小盘对冲",
                    "股票黄金对冲",
                    "股票商品对冲",
                    "A股黄金对冲",
                    "高波低波对冲",
                    "中盘国债对冲",
                ],
            }

        return result

    @server.tool()
    def get_hedge_correlation_matrix(
        asset_codes: list[str],
        window_days: int = 60
    ) -> dict[str, Any]:
        """
        获取资产相关性矩阵

        计算指定资产之间的相关系数，用于构建对冲组合。

        Args:
            asset_codes: 资产代码列表，如 ["510300", "511260"]
            window_days: 计算窗口天数（默认60天）

        Returns:
            相关性矩阵字典

        Example:
            >>> matrix = get_hedge_correlation_matrix(
            ...     asset_codes=["510300", "510500", "511260"],
            ...     window_days=60
            ... )
            >>> # matrix["correlation_matrix"]["510300"]["511260"]
        """
        client = AgomSAAFClient()
        result = client.hedge.get_correlation_matrix(asset_codes, window_days)

        if "error" in result:
            return {
                "error": result["error"],
                "message": "无法计算相关性矩阵",
            }

        return {
            "calc_date": result.get("calc_date", ""),
            "window_days": window_days,
            "assets": asset_codes,
            "correlation_matrix": result.get("correlation_matrix", {}),
        }

    @server.tool()
    def list_hedge_pairs() -> list[dict[str, Any]]:
        """
        列出所有对冲对

        获取系统中配置的所有对冲对信息。

        Returns:
            对冲对列表

        Example:
            >>> pairs = list_hedge_pairs()
            >>> for pair in pairs:
            ...     print(f"{pair['name']}: {pair['long_asset']} vs {pair['hedge_asset']}")
        """
        client = AgomSAAFClient()
        pairs = client.hedge.get_all_pairs()

        return pairs

    @server.tool()
    def get_hedge_pair_info(pair_name: str) -> dict[str, Any]:
        """
        获取对冲对详情

        获取指定对冲对的详细配置信息。

        Args:
            pair_name: 对冲对名称

        Returns:
            对冲对详情

        Example:
            >>> info = get_hedge_pair_info("股债对冲")
        """
        client = AgomSAAFClient()
        info = client.hedge.get_pair_info(pair_name)

        if info is None or "error" in info:
            return {
                "error": f"对冲对未找到: {pair_name}",
            }

        return info

    @server.tool()
    def explain_hedge_method(method: str) -> str:
        """
        解释对冲方法

        获取指定对冲方法的详细说明。

        Args:
            method: 对冲方法
                - "beta": Beta对冲
                - "min_variance": 最小方差对冲
                - "equal_risk": 等风险贡献
                - "dollar_neutral": 货币中性
                - "fixed_ratio": 固定比例

        Returns:
            方法说明

        Example:
            >>> explanation = explain_hedge_method("beta")
            >>> print(explanation)
        """
        explanations = {
            "beta": """Beta对冲法

原理：根据Beta值确定对冲比例，使组合Beta达到目标水平。

对冲比例 = 目标Beta / 资产Beta

例如：如果股票Beta为1.2，希望组合Beta为0.6，则对冲比例为50%。

优点：
- 简单直观
- 易于实施
- 市场风险对冲效果好

缺点：
- 假设Beta稳定
- 不考虑非线性风险

适合：大盘股、指数基金的对冲""",
            "min_variance": """最小方差对冲法

原理：通过最小化组合方差来确定对冲比例。

对冲比例 = -Cov(long, hedge) / Var(hedge)

优点：
- 数学上最优
- 考虑了资产间的相关性

缺点：
- 历史数据依赖
- 可能过度拟合

适合：具有良好历史数据的资产对冲""",
            "equal_risk": """等风险贡献法

原理：调整对冲比例，使多头和对冲资产对组合风险的贡献相等。

优点：
- 风险分散化
- 避免单一资产主导风险

缺点：
- 计算复杂
- 需要定期调整

适合：风险平价策略、多资产组合""",
            "dollar_neutral": """货币中性对冲

原理：多头和对冲头寸的金额相等。

多头金额 = 对冲金额 × 价格比率

优点：
- 简单明了
- 市场中性

缺点：
- 不考虑波动率差异
- 风险暴露可能不均衡

适合：配对交易、统计套利""",
            "fixed_ratio": """固定比例对冲

原理：使用预设的固定对冲比例，不随市场变化调整。

例如：70%股票 + 30%国债

优点：
- 简单易操作
- 交易成本低

缺点：
- 不适应市场变化
- 可能对冲不足或过度

适合：长期资产配置、战略对冲""",
        }

        return explanations.get(
            method,
            f"未知的对冲方法: {method}。有效值: beta, min_variance, equal_risk, dollar_neutral, fixed_ratio",
        )

    @server.tool()
    def is_my_hedge_still_working(pair_name: str) -> dict[str, Any]:
        """
        我的对冲组合还有效吗？

        快速检查对冲组合是否仍然有效。

        Args:
            pair_name: 对冲对名称

        Returns:
            检查结果和建议

        Example:
            >>> result = is_my_hedge_still_working("股债对冲")
            >>> if result['is_effective']:
            ...     print("对冲仍然有效")
            ... else:
            ...     print(f"需要调整: {result['recommendation']}")
        """
        client = AgomSAAFClient()
        result = client.hedge.check_effectiveness(pair_name)

        if "error" in result:
            return {
                "is_effective": False,
                "reason": "无法检查对冲有效性",
                "recommendation": "请检查对冲对配置",
            }

        effectiveness = result.get("effectiveness", 0)
        is_effective = effectiveness >= 0.5

        return {
            "is_effective": is_effective,
            "effectiveness": effectiveness,
            "rating": result.get("rating", ""),
            "correlation": result.get("correlation", 0),
            "recommendation": result.get("recommendation", ""),
            "reason": result.get("reason", ""),
        }

    @server.tool()
    def get_hedge_alerts() -> list[dict[str, Any]]:
        """
        获取对冲告警

        获取当前所有未解决的对冲告警。

        Returns:
            告警列表

        Example:
            >>> alerts = get_hedge_alerts()
            >>> for alert in alerts:
            ...     print(f"{alert['pair_name']}: {alert['message']}")
        """
        client = AgomSAAFClient()
        alerts = client.hedge.get_alerts()

        return alerts

    @server.tool()
    def get_hedge_portfolio_state(pair_name: str) -> dict[str, Any]:
        """
        获取对冲组合当前状态

        获取指定对冲对的当前快照状态和风险指标。

        Args:
            pair_name: 对冲对名称

        Returns:
            组合状态

        Example:
            >>> state = get_hedge_portfolio_state("股债对冲")
            >>> print(f"多头权重: {state['long_weight']}")
            >>> print(f"对冲权重: {state['hedge_weight']}")
        """
        client = AgomSAAFClient()
        state = client.hedge.get_portfolio_state(pair_name)

        if state is None or "error" in state:
            return {
                "error": f"无法获取组合状态: {pair_name}",
            }

        return state

    @server.tool()
    def recommend_hedge_for_asset(asset_code: str) -> dict[str, Any]:
        """
        为资产推荐对冲工具

        根据资产特性推荐合适的对冲工具。

        Args:
            asset_code: 资产代码（如 "510300" 沪深300ETF）

        Returns:
            推荐的对冲工具

        Example:
            >>> rec = recommend_hedge_for_asset("510300")
            >>> print(f"推荐对冲工具: {rec['hedge_asset']}")
        """
        # 简单推荐逻辑
        recommendations = {
            "510300": {  # 沪深300 - 大盘蓝筹
                "hedge_asset": "511260",  # 10年国债
                "hedge_method": "beta",
                "reason": "大盘股与国债负相关，Beta对冲效果好",
            },
            "510500": {  # 中证500 - 中盘成长
                "hedge_asset": "511260",  # 10年国债
                "hedge_method": "beta",
                "reason": "中盘股与国债负相关，Beta对冲效果好",
            },
            "159915": {  # 创业板 - 高波动
                "hedge_asset": "512100",  # 红利ETF
                "hedge_method": "min_variance",
                "reason": "高波动股票用价值股对冲，最小方差方法",
            },
            "512100": {  # 中证1000 - 小盘
                "hedge_asset": "510300",  # 沪深300
                "hedge_method": "equal_risk",
                "reason": "小盘与大盘轮动对冲，等风险贡献",
            },
        }

        return recommendations.get(
            asset_code,
            {
                "hedge_asset": "511260",  # 默认推荐国债
                "hedge_method": "beta",
                "reason": "股票默认使用国债对冲",
            },
        )

