"""
AgomTradePro MCP Tools - Factor 因子选股工具

提供因子选股相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_factor_tools(server: FastMCP) -> None:
    """注册 Factor 相关的 MCP 工具"""

    @server.tool()
    def get_factor_top_stocks(
        value_preference: str = "medium",
        quality_preference: str = "medium",
        growth_preference: str = "medium",
        momentum_preference: str = "medium",
        top_n: int = 30
    ) -> dict[str, Any]:
        """
        获取因子选股结果

        根据因子偏好获取top N股票。

        Args:
            value_preference: 价值因子偏好 (high/medium/low)
            quality_preference: 质量因子偏好 (high/medium/low)
            growth_preference: 成长因子偏好 (high/medium/low)
            momentum_preference: 动量因子偏好 (high/medium/low)
            top_n: 返回股票数量 (默认30)

        Returns:
            包含以下字段的字典：
            - total_stocks: 股票总数
            - stocks: 股票列表

        Example:
            >>> result = get_factor_top_stocks(
            ...     value_preference="high",
            ...     quality_preference="high",
            ...     growth_preference="medium",
            ...     top_n=30
            ... )
            >>> for stock in result['stocks']:
            ...     print(f"{stock['stock_code']}: {stock['composite_score']}")
        """
        client = AgomTradeProClient()

        factor_preferences = {
            "value": value_preference,
            "quality": quality_preference,
            "growth": growth_preference,
            "momentum": momentum_preference,
        }

        result = client.factor.get_top_stocks(factor_preferences, top_n)

        if "error" in result:
            return {
                "error": result["error"],
                "message": "无法获取因子选股结果",
            }

        return {
            "total_stocks": result.get("total_stocks", 0),
            "stocks": result.get("stocks", []),
        }

    @server.tool()
    def explain_factor_stock(
        stock_code: str,
        focus: str = "balanced"
    ) -> dict[str, Any]:
        """
        解释股票的因子得分

        分析指定股票在各因子上的表现。

        Args:
            stock_code: 股票代码 (如 "000001.SZ")
            focus: 分析重点
                - "value": 价值导向 (低PE/PB)
                - "growth": 成长导向 (高增长)
                - "quality": 质量导向 (高ROE)
                - "balanced": 平衡配置

        Returns:
            因子得分说明

        Example:
            >>> explanation = explain_factor_stock("000001.SZ", focus="value")
            >>> print(f"综合得分: {explanation['composite_score']}")
            >>> print(f"价值得分: {explanation['valuation_score']}")
        """
        client = AgomTradeProClient()

        # Determine factor weights based on focus
        if focus == "value":
            factor_weights = {
                "pe_ttm": -0.4,
                "pb": -0.3,
                "roe": 0.15,
                "revenue_growth": 0.1,
                "profit_growth": 0.05,
            }
        elif focus == "growth":
            factor_weights = {
                "revenue_growth": 0.35,
                "profit_growth": 0.35,
                "roe": 0.2,
                "momentum_3m": 0.1,
            }
        elif focus == "quality":
            factor_weights = {
                "roe": 0.3,
                "roa": 0.2,
                "debt_ratio": -0.2,
                "current_ratio": 0.15,
                "gross_margin": 0.15,
            }
        else:  # balanced
            factor_weights = {
                "pe_ttm": -0.2,
                "pb": -0.1,
                "roe": 0.25,
                "revenue_growth": 0.2,
                "profit_growth": 0.15,
                "momentum_3m": 0.1,
            }

        result = client.factor.explain_stock(stock_code, factor_weights)

        if result is None or "error" in result:
            return {
                "error": f"无法分析股票 {stock_code}",
                "message": "请检查股票代码是否正确",
            }

        return result

    @server.tool()
    def list_factor_definitions() -> dict[str, Any]:
        """
        列出所有因子定义

        获取系统中所有可用的因子定义。

        Returns:
            因子定义列表，按类别分组

        Example:
            >>> result = list_factor_definitions()
            >>> for category, factors in result['by_category'].items():
            ...     print(f"{category}: {len(factors)} 个因子")
        """
        client = AgomTradeProClient()
        factors = client.factor.get_all_factors()

        # Group by category
        by_category = {}
        for factor in factors:
            category = factor.get('category', 'unknown')
            if category not in by_category:
                by_category[category] = []
            by_category[category].append({
                'code': factor['code'],
                'name': factor['name'],
                'description': factor['description'],
                'direction': factor['direction'],
            })

        return {
            'total_factors': len(factors),
            'by_category': by_category,
        }

    @server.tool()
    def list_factor_configs() -> list[dict[str, Any]]:
        """
        列出所有因子组合配置

        获取系统中配置的因子组合策略。

        Returns:
            配置列表

        Example:
            >>> configs = list_factor_configs()
            >>> for config in configs:
            ...     print(f"{config['name']}: {config['universe']}, Top {config['top_n']}")
        """
        client = AgomTradeProClient()
        configs = client.factor.get_all_configs()

        return configs

    @server.tool()
    def create_factor_portfolio(
        config_name: str,
        trade_date: str | None = None
    ) -> dict[str, Any]:
        """
        创建因子组合

        根据指定配置创建因子组合。

        Args:
            config_name: 配置名称，如：
                - "价值成长平衡组合"
                - "深度价值组合"
                - "高成长组合"
                - "质量优选组合"
                - "动量精选组合"
                - "小盘价值组合"
            trade_date: 交易日期 (ISO格式，默认今天)

        Returns:
            组合详情

        Example:
            >>> portfolio = create_factor_portfolio("价值成长平衡组合")
            >>> print(f"总股票数: {portfolio['total_stocks']}")
            >>> for stock in portfolio['holdings']:
            ...     print(f"{stock['stock_code']}: {stock['weight']}%")
        """
        client = AgomTradeProClient()

        # Parse date if provided
        parsed_date = None
        if trade_date:
            try:
                parsed_date = date.fromisoformat(trade_date)
            except ValueError:
                return {
                    "error": f"无效的日期格式: {trade_date}，请使用 YYYY-MM-DD 格式",
                }

        try:
            result = client.factor.create_portfolio(config_name, parsed_date)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "config_name": config_name,
            }

        if result is None or "error" in result:
            return {
                "error": f"创建组合失败: {config_name}",
                "message": "请检查配置名称是否正确",
            }

        return result

    @server.tool()
    def get_factor_portfolio(config_name: str) -> dict[str, Any]:
        """
        获取因子组合最新持仓

        获取指定因子组合的最新持仓情况。

        Args:
            config_name: 配置名称

        Returns:
            组合持仓详情

        Example:
            >>> portfolio = get_factor_portfolio("价值成长平衡组合")
            >>> print(f"持仓日期: {portfolio['trade_date']}")
            >>> for stock in portfolio['holdings']:
            ...     print(f"{stock['stock_code']}: {stock['weight']}%")
        """
        client = AgomTradeProClient()
        portfolio = client.factor.get_portfolio(config_name)

        if portfolio is None:
            return {
                "error": f"无法获取组合持仓: {config_name}",
                "message": "组合可能尚未生成，请先使用 create_factor_portfolio 创建",
            }

        return portfolio

    @server.tool()
    def what_are_the_best_value_stocks(
        top_n: int = 20
    ) -> dict[str, Any]:
        """
        最优价值股票有哪些？

        快捷获取基于价值因子的选股结果。

        Args:
            top_n: 返回股票数量

        Returns:
            价值选股结果

        Example:
            >>> result = what_are_the_best_value_stocks(20)
            >>> print("推荐价值股:")
            >>> for stock in result['stocks'][:10]:
            ...     print(f"{stock['stock_code']}: {stock['stock_name']}")
        """
        return get_factor_top_stocks(
            value_preference="high",
            quality_preference="medium",
            growth_preference="low",
            momentum_preference="low",
            top_n=top_n
        )

    @server.tool()
    def what_are_the_best_growth_stocks(
        top_n: int = 20
    ) -> dict[str, Any]:
        """
        最优成长股票有哪些？

        快捷获取基于成长因子的选股结果。

        Args:
            top_n: 返回股票数量

        Returns:
            成长选股结果
        """
        return get_factor_top_stocks(
            value_preference="low",
            quality_preference="medium",
            growth_preference="high",
            momentum_preference="medium",
            top_n=top_n
        )

    @server.tool()
    def explain_factor_type(factor_type: str) -> str:
        """
        解释因子类型

        获取指定因子类型的详细说明。

        Args:
            factor_type: 因子类型
                - "value": 价值因子
                - "quality": 质量因子
                - "growth": 成长因子
                - "momentum": 动量因子
                - "volatility": 波动因子
                - "liquidity": 流动性因子

        Returns:
            因子类型说明
        """
        explanations = {
            "value": """价值因子 (Value Factors)

衡量股票是否被低估的指标。

核心逻辑：低估值 = 未来收益潜力

主要因子：
- PE(TTM): 滚动市盈率，越低越便宜
- PB: 市净率，越低越便宜
- PS: 市销率，越低越便宜
- 股息率: 越高越好

使用场景：
- 防御性投资
- 长期价值投资
- 低迷期布局

风险：
- 价值陷阱：看似便宜但基本面恶化""",
            "quality": """质量因子 (Quality Factors)

衡量公司盈利能力和财务健康的指标。

核心逻辑：高质量 = 持续盈利能力

主要因子：
- ROE: 净资产收益率，越高越好
- ROA: 总资产收益率
- 资产负债率: 越低越稳健
- 毛利率: 越高代表盈利质量越好
- 流动比率: 短期偿债能力

使用场景：
- 长期持有
- 稳健投资
- 风险控制

风险：
- 财务造假""",
            "growth": """成长因子 (Growth Factors)

衡量公司成长性的指标。

核心逻辑：高增长 = 未来股价上涨潜力

主要因子：
- 营收增长率: 营业收入同比增速
- 利润增长率: 净利润同比增速
- 营收3年复合增长率: 长期成长性

使用场景：
- 牛市进攻
- 新兴产业
- 小盘股

风险：
- 增长不可持续
- 估值过高""",
            "momentum": """动量因子 (Momentum Factors)

衡量股票价格趋势的指标。

核心逻辑：强者恒强

主要因子：
- 1月动量: 近1个月收益率
- 3月动量: 近3个月收益率
- 6月动量: 近6个月收益率
- 52周新高距离: 距离52周高点的位置

使用场景：
- 趋势投资
- 技术分析
- 短期交易

风险：
- 趋势反转
- 追涨杀跌""",
            "volatility": """波动因子 (Volatility Factors)

衡量股票波动风险的指标。

核心逻辑：低波动 = 更稳定收益

主要因子：
- 20日波动率: 收益率标准差
- 60日波动率
- Beta: 相对于市场的波动

使用场景：
- 风险厌恶
- 防御配置
- 组合对冲

风险：
- 低波动可能错过大涨""",
            "liquidity": """流动性因子 (Liquidity Factors)

衡量股票流动性的指标。

核心逻辑：高流动性 = 交易便利

主要因子：
- 20日换手率: 平均日换手率
- 60日换手率
- 成交额

使用场景：
- 大资金配置
- 交易活跃度要求

风险：
- 流动性溢价可能不稳定""",
        }

        return explanations.get(
            factor_type,
            f"未知的因子类型: {factor_type}。有效值: value, quality, growth, momentum, volatility, liquidity",
        )

    @server.tool()
    def recommend_portfolio_for_regime(regime_type: str) -> dict[str, Any]:
        """
        根据宏观象限推荐因子组合策略

        Args:
            regime_type: 宏观象限 (Recovery/Overheat/Stagflation/Deflation)

        Returns:
            推荐的因子配置和组合

        Example:
            >>> recommendation = recommend_portfolio_for_regime("Recovery")
            >>> print(f"推荐配置: {recommendation['config_name']}")
        """
        # Map regime to factor focus
        regime_factor_map = {
            "Recovery": {
                "config_name": "价值成长平衡组合",
                "reason": "复苏期适合价值与成长兼顾，既要估值安全又要抓住成长机会",
            },
            "Overheat": {
                "config_name": "质量优选组合",
                "reason": "过热期通胀上升，优先选择高质量、财务稳健的公司",
            },
            "Stagflation": {
                "config_name": "深度价值组合",
                "reason": "滞胀期防御优先，低估值、高股息的价值股具有较强的防御属性",
            },
            "Deflation": {
                "config_name": "高成长组合",
                "reason": "衰退期货币政策宽松，成长股具有较大反弹空间",
            },
        }

        recommendation = regime_factor_map.get(regime_type)

        if not recommendation:
            return {
                "error": f"未知的象限类型: {regime_type}",
                "valid_types": list(regime_factor_map.keys()),
            }

        return {
            "regime_type": regime_type,
            "config_name": recommendation["config_name"],
            "reason": recommendation["reason"],
        }

