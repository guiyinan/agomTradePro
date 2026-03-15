"""
AgomSAAF MCP Tools - Rotation 资产轮动工具

提供资产轮动相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_rotation_tools(server: FastMCP) -> None:
    """注册 Rotation 相关的 MCP 工具"""

    @server.tool()
    def list_rotation_regimes() -> list[dict[str, Any]]:
        """
        列出轮动配置使用的宏观象限

        Returns:
            象限列表，元素包含 key 和 label
        """
        client = AgomSAAFClient()
        return client.rotation.list_regimes()

    @server.tool()
    def list_rotation_templates() -> list[dict[str, Any]]:
        """
        列出可用的账户轮动模板

        Returns:
            模板列表
        """
        client = AgomSAAFClient()
        return client.rotation.list_templates()

    @server.tool()
    def list_account_rotation_configs() -> list[dict[str, Any]]:
        """
        列出当前用户所有账户的轮动配置

        Returns:
            账户轮动配置列表
        """
        client = AgomSAAFClient()
        return client.rotation.list_account_configs()

    @server.tool()
    def get_account_rotation_config(
        config_id: int | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """
        查询账户轮动配置

        Args:
            config_id: 配置 ID，优先使用
            account_id: 账户 ID；未提供 config_id 时按账户查询

        Returns:
            单条账户轮动配置
        """
        client = AgomSAAFClient()
        if config_id is not None:
            try:
                return client.rotation.get_account_config(config_id)
            except Exception as exc:
                return {
                    "success": False,
                    "config_id": config_id,
                    "error": str(exc),
                }
        if account_id is not None:
            try:
                return client.rotation.get_account_config_by_account(account_id)
            except Exception as exc:
                return {
                    "success": False,
                    "account_id": account_id,
                    "error": str(exc),
                }
        return {
            "error": "必须提供 config_id 或 account_id 之一",
        }

    @server.tool()
    def create_account_rotation_config(
        account_id: int,
        risk_tolerance: str = "moderate",
        is_enabled: bool = False,
        regime_allocations: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """
        新建账户轮动配置

        Args:
            account_id: 账户 ID
            risk_tolerance: 风险偏好
            is_enabled: 是否启用自动轮动
            regime_allocations: 各象限资产权重配置

        Returns:
            新建后的账户轮动配置
        """
        client = AgomSAAFClient()
        payload = {
            "account": account_id,
            "risk_tolerance": risk_tolerance,
            "is_enabled": is_enabled,
            "regime_allocations": regime_allocations or {},
        }
        try:
            return client.rotation.create_account_config(payload)
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id,
                "error": str(exc),
            }

    @server.tool()
    def update_account_rotation_config(
        config_id: int,
        payload: dict[str, Any],
        partial: bool = True,
    ) -> dict[str, Any]:
        """
        更新账户轮动配置

        Args:
            config_id: 配置 ID
            payload: 更新内容
            partial: True 使用 PATCH，False 使用 PUT

        Returns:
            更新后的账户轮动配置
        """
        client = AgomSAAFClient()
        return client.rotation.update_account_config(config_id, payload, partial=partial)

    @server.tool()
    def delete_account_rotation_config(config_id: int) -> dict[str, Any]:
        """
        删除账户轮动配置

        Args:
            config_id: 配置 ID

        Returns:
            删除响应
        """
        client = AgomSAAFClient()
        return client.rotation.delete_account_config(config_id)

    @server.tool()
    def apply_rotation_template_to_account_config(
        config_id: int,
        template_key: str,
    ) -> dict[str, Any]:
        """
        将预设模板应用到指定账户轮动配置

        Args:
            config_id: 配置 ID
            template_key: 模板 key

        Returns:
            应用模板后的账户轮动配置
        """
        client = AgomSAAFClient()
        return client.rotation.apply_template_to_account_config(config_id, template_key)

    @server.tool()
    def get_rotation_recommendation(strategy: str = "momentum") -> dict[str, Any]:
        """
        获取资产轮动推荐

        根据指定策略获取当前资产配置建议。

        Args:
            strategy: 轮动策略类型
                - "momentum": 动量轮动（选择近期表现最好的资产）
                - "regime_based": 宏观象限轮动（根据当前宏观环境配置）
                - "risk_parity": 风险平价（按波动率倒数配置）

        Returns:
            包含以下字段的字典：
            - config_name: 配置名称
            - signal_date: 信号日期
            - target_allocation: 目标配置 {资产代码: 权重}
            - current_regime: 当前宏观象限（regime_based策略）
            - action_required: 建议操作（rebalance/hold）
            - reason: 配置理由
            - momentum_ranking: 动量排名（momentum策略）

        Example:
            >>> recommendation = get_rotation_recommendation("momentum")
            >>> print(f"推荐配置: {recommendation['target_allocation']}")
        """
        client = AgomSAAFClient()
        result = client.rotation.get_recommendation(strategy)

        if "error" in result:
            return {
                "error": result["error"],
                "message": "无法获取轮动推荐，请检查配置",
            }

        return {
            "config_name": result.get("config_name", ""),
            "signal_date": result.get("signal_date", ""),
            "strategy_type": result.get("strategy_type", strategy),
            "target_allocation": result.get("target_allocation", {}),
            "current_regime": result.get("current_regime", ""),
            "action_required": result.get("action_required", "hold"),
            "reason": result.get("reason", ""),
            "momentum_ranking": result.get("momentum_ranking", []),
        }

    @server.tool()
    def compare_assets(
        asset_codes: list[str],
        lookback_days: int = 60
    ) -> dict[str, Any]:
        """
        比较多个资产的动量表现

        对指定资产进行多维度比较，包括动量得分、趋势等。

        Args:
            asset_codes: 资产代码列表，如 ["510300", "510500", "159915"]
                - 510300: 沪深300ETF
                - 510500: 中证500ETF
                - 159915: 创业板ETF
                - 159980: 黄金ETF
                - 511260: 十年国债ETF
            lookback_days: 回溯天数（默认60天）

        Returns:
            各资产的比较结果字典

        Example:
            >>> result = compare_assets(
            ...     asset_codes=["510300", "510500", "159980"],
            ...     lookback_days=60
            ... )
        """
        client = AgomSAAFClient()
        result = client.rotation.compare_assets(asset_codes, lookback_days)

        if "error" in result:
            return {
                "error": result["error"],
                "message": "无法比较资产，请检查资产代码",
            }

        return {
            "calc_date": result.get("calc_date", ""),
            "lookback_days": lookback_days,
            "assets": result.get("assets", {}),
        }

    @server.tool()
    def get_correlation_matrix(
        asset_codes: list[str],
        window_days: int = 60
    ) -> dict[str, Any]:
        """
        获取资产相关性矩阵

        计算指定资产之间的相关系数矩阵，用于构建分散化组合。

        Args:
            asset_codes: 资产代码列表
            window_days: 计算窗口（默认60天）

        Returns:
            相关性矩阵字典

        Example:
            >>> matrix = get_correlation_matrix(
            ...     asset_codes=["510300", "510500", "511260"],
            ...     window_days=60
            ... )
            >>> # matrix["correlation_matrix"]["510300"]["511260"] 表示沪深300和国债的相关性
        """
        client = AgomSAAFClient()
        result = client.rotation.get_correlation_matrix(asset_codes, window_days)

        if "error" in result:
            return {
                "error": result["error"],
                "message": "无法计算相关性，请检查资产代码",
            }

        return {
            "calc_date": result.get("calc_date", ""),
            "window_days": window_days,
            "assets": result.get("assets", []),
            "correlation_matrix": result.get("correlation_matrix", {}),
        }

    @server.tool()
    def get_rotation_config(config_name: str) -> dict[str, Any]:
        """
        获取轮动配置详情

        获取指定轮动策略的配置信息。

        Args:
            config_name: 配置名称，如：
                - "动量轮动策略"
                - "宏观象限轮动策略"
                - "风险平价策略"

        Returns:
            配置详情字典

        Example:
            >>> config = get_rotation_config("动量轮动策略")
        """
        client = AgomSAAFClient()
        configs = client.rotation.get_all_configs()

        for cfg in configs:
            if cfg["name"] == config_name:
                return cfg

        return {
            "error": f"配置未找到: {config_name}",
            "available_configs": [cfg["name"] for cfg in configs],
        }

    @server.tool()
    def list_rotation_assets(category: str = "all") -> list[dict[str, Any]]:
        """
        列出可轮动资产

        获取系统中所有可轮动资产的列表。

        Args:
            category: 资产类别筛选
                - "all": 全部资产
                - "equity": 股票类ETF
                - "bond": 债券类ETF
                - "commodity": 商品类ETF
                - "currency": 货币基金

        Returns:
            资产列表

        Example:
            >>> assets = list_rotation_assets(category="equity")
            >>> for asset in assets:
            ...     print(f"{asset['code']}: {asset['name']}")
        """
        client = AgomSAAFClient()
        all_assets = client.rotation.get_all_assets()

        if category != "all":
            all_assets = [a for a in all_assets if a.get("category") == category]

        return all_assets

    @server.tool()
    def explain_rotation_strategy(strategy_type: str) -> str:
        """
        解释轮动策略

        获取指定轮动策略的详细说明。

        Args:
            strategy_type: 策略类型
                - "momentum": 动量轮动
                - "regime_based": 宏观象限轮动
                - "risk_parity": 风险平价

        Returns:
            策略说明

        Example:
            >>> explanation = explain_rotation_strategy("momentum")
            >>> print(explanation)
        """
        explanations = {
            "momentum": """动量轮动策略

原理：选择近期表现最好的资产进行配置，假设强者恒强。

特点：
- 追涨杀跌，在上升趋势中表现较好
- 适合单边趋势市场
- 可能在震荡市中频繁调仓

调仓频率：月度

选资产数量：3-5个

权重方式：等权重

适合市场：趋势明显的牛市或熊市""",
            "regime_based": """宏观象限轮动策略

原理：根据宏观环境（增长×通胀四象限）配置资产。

象限配置：
- 复苏期：股票60%，债券20%，商品10%，现金10%
- 过热期：股票20%，债券25%，商品25%，现金30%
- 滞胀期：商品20%，黄金20%，债券35%，现金25%
- 衰退期：债券50%，现金30%，黄金10%，股票10%

特点：
- 自上而下的宏观配置
- 避免在错误的宏观环境下下注
- 需要准确的宏观判断

调仓频率：月度

适合市场：宏观环境切换明显的市场""",
            "risk_parity": """风险平价策略

原理：按资产的波动率倒数配置权重，使各资产对组合的风险贡献相等。

特点：
- 风险分散化
- 低波动资产会获得更高权重
- 通常债券权重较高

调仓频率：月度

权重计算：权重_i = (1/波动率_i) / Σ(1/波动率_j)

适合市场：震荡市、追求稳健收益""",
        }

        return explanations.get(
            strategy_type,
            f"未知的策略类型: {strategy_type}。有效值: momentum, regime_based, risk_parity",
        )

    @server.tool()
    def get_asset_info(asset_code: str) -> dict[str, Any]:
        """
        获取资产详细信息

        获取指定资产的详细信息，包括当前价格和近期表现。

        Args:
            asset_code: 资产代码（如 "510300"）

        Returns:
            资产详情

        Example:
            >>> info = get_asset_info("510300")
            >>> print(f"{info['name']}: {info['current_price']}")
        """
        client = AgomSAAFClient()
        info = client.rotation.get_asset_info(asset_code)

        if info is None:
            return {
                "error": f"资产未找到: {asset_code}",
            }

        return info

    @server.tool()
    def generate_rotation_signal(
        config_name: str,
        signal_date: str | None = None
    ) -> dict[str, Any]:
        """
        生成轮动信号

        为指定配置生成轮动信号并保存到数据库。

        Args:
            config_name: 配置名称
            signal_date: 信号日期（ISO格式，默认今天）

        Returns:
            生成的信号详情

        Example:
            >>> signal = generate_rotation_signal(
            ...     config_name="动量轮动策略",
            ...     signal_date="2024-01-15"
            ... )
        """
        client = AgomSAAFClient()

        # Parse signal date if provided
        parsed_date = None
        if signal_date:
            try:
                parsed_date = date.fromisoformat(signal_date)
            except ValueError:
                return {
                    "error": f"无效的日期格式: {signal_date}，请使用 YYYY-MM-DD 格式",
                }

        result = client.rotation.generate_signal(config_name, parsed_date)

        if result is None:
            return {
                "error": f"生成信号失败，请检查配置名称: {config_name}",
            }

        return result

    @server.tool()
    def get_latest_rotation_signals() -> list[dict[str, Any]]:
        """
        获取最新轮动信号

        获取所有活跃配置的最新轮动信号。

        Returns:
            最新信号列表

        Example:
            >>> signals = get_latest_rotation_signals()
            >>> for signal in signals:
            ...     print(f"{signal['config_name']}: {signal['action_required']}")
        """
        client = AgomSAAFClient()
        signals = client.rotation.get_latest_signals()

        return signals

    @server.tool()
    def what_to_buy_now() -> dict[str, Any]:
        """
        现在该买什么资产？

        根据动量轮动策略获取当前推荐的资产配置。

        这是一个快捷方法，直接返回当前应该买入的资产。

        Returns:
            推荐配置和建议

        Example:
            >>> advice = what_to_buy_now()
            >>> print(f"建议操作: {advice['action']}")
            >>> print(f"推荐资产: {advice['recommendations']}")
        """
        client = AgomSAAFClient()
        result = client.rotation.get_recommendation("momentum")

        if "error" in result:
            return {
                "action": "hold",
                "reason": "无法获取推荐信号",
                "recommendations": [],
            }

        target_allocation = result.get("target_allocation", {})
        action = result.get("action_required", "hold")
        reason = result.get("reason", "")

        # Convert allocation to recommendations
        recommendations = []
        for asset_code, weight in target_allocation.items():
            asset_info = client.rotation.get_asset_info(asset_code)
            if asset_info:
                recommendations.append({
                    "code": asset_code,
                    "name": asset_info.get("name", ""),
                    "weight": f"{weight * 100:.1f}%",
                    "category": asset_info.get("category", ""),
                })

        # Sort by weight
        recommendations.sort(key=lambda x: float(x["weight"].rstrip("%")), reverse=True)

        return {
            "action": action,
            "reason": reason,
            "recommendations": recommendations,
            "signal_date": result.get("signal_date", ""),
        }

