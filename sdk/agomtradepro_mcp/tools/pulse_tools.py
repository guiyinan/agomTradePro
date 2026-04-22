"""
AgomTradePro MCP Tools - Pulse 脉搏 + Regime Navigator 工具

提供 Pulse 和 Navigator 相关的 MCP 工具。
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_pulse_tools(server: FastMCP) -> None:
    """注册 Pulse + Navigator 相关的 MCP 工具"""

    @server.tool()
    def get_pulse_current() -> dict[str, Any]:
        """
        获取当前 Pulse 脉搏快照

        返回 4 维度（增长/通胀/流动性/情绪）评分和综合分数，
        用于评估当前宏观环境的战术强弱。

        Returns:
            包含以下字段的字典：
            - composite_score: 综合分数 (-1 到 1)
            - regime_strength: Regime 强弱 (strong/moderate/weak)
            - regime_context: 当时的 Regime 象限
            - dimension_scores: 4 维度分数
            - transition_warning: 是否有转折预警
            - observed_at: 观测日期
            - contract.must_not_use_for_decision: 当前快照是否禁止用于决策
            - contract.blocked_reason: 禁止用于决策时的原因

        Example:
            >>> pulse = get_pulse_current()
            >>> if pulse["data"]["contract"]["must_not_use_for_decision"]:
            ...     print(pulse["data"]["contract"]["blocked_reason"])
        """
        client = AgomTradeProClient()
        return client.pulse.get_current()

    @server.tool()
    def get_pulse_history(limit: int = 20) -> list[dict[str, Any]]:
        """
        获取 Pulse 脉搏历史记录

        Args:
            limit: 返回记录数量限制（默认 20）

        Returns:
            Pulse 快照列表，按时间倒序

        Example:
            >>> history = get_pulse_history(limit=10)
            >>> for snap in history:
            ...     print(f"{snap['observed_at']}: {snap['composite_score']}")
        """
        client = AgomTradeProClient()
        return client.pulse.get_history(limit=limit)

    @server.tool()
    def get_regime_navigator() -> dict[str, Any]:
        """
        获取 Regime 导航仪完整输出

        比 get_current_regime 更丰富——除了象限判定外，
        还包含移动方向、资产配置指引、关注指标。

        Returns:
            包含以下字段的字典：
            - regime_name: 当前象限 (Recovery/Overheat/Stagflation/Deflation)
            - confidence: 置信度 (0-1)
            - distribution: 四象限概率分布
            - movement: 移动方向信息
              - direction: stable/transitioning
              - transition_target: 目标象限
              - transition_probability: 转折概率
              - leading_indicators: 领先指标说明
              - momentum_summary: 动量摘要
            - asset_guidance: 资产配置指引
              - weight_ranges: [{category, lower, upper, label}]
              - risk_budget_pct: 风险预算
              - recommended_sectors: 推荐板块列表
              - benefiting_styles: 受益风格列表
              - reasoning: 配置逻辑说明
            - watch_indicators: 关注指标列表

        Example:
            >>> nav = get_regime_navigator()
            >>> print(f"象限: {nav['regime_name']}, 方向: {nav['movement']['direction']}")
            >>> for wr in nav['asset_guidance']['weight_ranges']:
            ...     print(f"  {wr['label']}: {wr['lower']:.0%} - {wr['upper']:.0%}")
        """
        client = AgomTradeProClient()
        return client.pulse.get_navigator()

    @server.tool()
    def get_action_recommendation() -> dict[str, Any]:
        """
        获取 Regime + Pulse 联合行动建议

        基于当前 Regime 和 Pulse 数据，计算具体的资产配置百分比
        和投资建议。这是系统最核心的决策输出。
        若 Pulse stale 或不可靠，返回值会携带阻断契约，Agent 不得继续
        把该结果解释为可执行配置建议。

        Returns:
            包含以下字段的字典：
            - regime_name: 当前象限
            - asset_weights: 各资产类别配置比例
              (e.g. {"equity": 0.55, "bond": 0.25, "commodity": 0.10, "cash": 0.10})
            - risk_budget_pct: 风险预算百分比 (0-1)
            - position_limit: 单一持仓上限
            - sectors: 推荐板块列表
            - styles: 受益风格列表
            - hedge_recommendation: 对冲建议（Stagflation/Deflation 特有）
            - regime_contribution: Regime 贡献说明
            - pulse_contribution: Pulse 贡献说明
            - reasoning: 综合配置逻辑
            - confidence: 置信度
            - as_of_date: 生效日期
            - must_not_use_for_decision: 是否禁止用于决策
            - blocked_reason: 阻断原因
            - pulse_is_reliable: Pulse 是否达到决策级可靠性

        Example:
            >>> action = get_action_recommendation()
            >>> if action["data"]["contract"]["must_not_use_for_decision"]:
            ...     print(action["data"]["contract"]["blocked_reason"])
        """
        client = AgomTradeProClient()
        return client.pulse.get_action_recommendation()

    @server.tool()
    def explain_pulse_dimensions() -> str:
        """
        解释 Pulse 四维度的含义

        Returns:
            Pulse 四维度详细说明

        Example:
            >>> explanation = explain_pulse_dimensions()
            >>> print(explanation)
        """
        return """Pulse 脉搏四维度说明

1. 增长 (Growth)
   代表经济增长动力。核心指标：PMI、工业增加值增速、期限利差。
   正值 = 经济扩张动力强；负值 = 经济收缩压力大。

2. 通胀 (Inflation)
   代表通胀压力。核心指标：CPI 同比、PPI 同比、M2-M1 剪刀差。
   正值 = 通胀上升；负值 = 通缩风险。

3. 流动性 (Liquidity)
   代表市场资金面松紧。核心指标：DR007/央行基准利差、社融增速。
   正值 = 流动性宽松；负值 = 流动性收紧。

4. 情绪 (Sentiment)
   代表市场风险偏好。核心指标：市场成交额变化率、信用利差。
   正值 = 风险偏好上升；负值 = 避险情绪浓厚。

综合分数范围：-1 到 +1
- > 0.3: 当前 Regime 偏强
- -0.3 ~ 0.3: 当前 Regime 中等
- < -0.3: 当前 Regime 偏弱
"""
