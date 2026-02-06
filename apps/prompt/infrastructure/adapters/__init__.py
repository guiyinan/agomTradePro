"""
Predefined Prompt Templates and Chain Configurations.

This module contains predefined templates and chain configurations
that can be loaded into the database for common use cases.

Author: AgomSAAF System
Version: 1.0
"""

from datetime import date

from apps.prompt.domain.entities import (
    PromptTemplate, ChainConfig, ChainStep, PlaceholderDef,
    PlaceholderType, PromptCategory, ChainExecutionMode
)


# ============================================
# Predefined Prompt Templates
# ============================================

def get_predefined_templates() -> list[PromptTemplate]:
    """
    获取预定义的Prompt模板列表

    Returns:
        PromptTemplate实体列表
    """
    return [
        # 1. Regime分析模板
        PromptTemplate(
            id=None,
            name="regime_analysis",
            category=PromptCategory.REPORT_ANALYSIS,
            version="1.0",
            template_content="""请分析当前的宏观经济Regime状态：

## 当前Regime状态
- 主导Regime: {{DOMINANT_REGIME_NAME}}
- 置信度: {{REGIME_CONFIDENCE}}
- 增长动量Z-score: {{GROWTH_Z}}
- 通胀动量Z-score: {{INFLATION_Z}}

## 分析要点
1. 分析当前Regime的特征和形成原因
2. 评估该Regime的可持续性
3. 给出该Regime下的投资建议

请用专业的宏观经济分析语言进行阐述。""",
            placeholders=[
                PlaceholderDef(
                    name="DOMINANT_REGIME_NAME",
                    type=PlaceholderType.SIMPLE,
                    description="主导Regime名称",
                    required=True
                ),
                PlaceholderDef(
                    name="REGIME_CONFIDENCE",
                    type=PlaceholderType.SIMPLE,
                    description="Regime置信度",
                    required=True
                ),
                PlaceholderDef(
                    name="GROWTH_Z",
                    type=PlaceholderType.SIMPLE,
                    description="增长动量Z-score",
                    required=True
                ),
                PlaceholderDef(
                    name="INFLATION_Z",
                    type=PlaceholderType.SIMPLE,
                    description="通胀动量Z-score",
                    required=True
                ),
            ],
            system_prompt="你是一位专业的宏观经济分析师，擅长分析增长/通胀象限及其投资含义。",
            temperature=0.7,
            max_tokens=2000,
            description="Regime分析报告模板",
            is_active=True,
            created_at=date.today()
        ),

        # 2. 宏观数据摘要模板
        PromptTemplate(
            id=None,
            name="macro_summary",
            category=PromptCategory.REPORT_ANALYSIS,
            version="1.0",
            template_content="""请分析以下宏观经济数据：

## 宏观指标概览
{{MACRO_DATA}}

## 分析要求
1. 总结各项指标的最新读数和变化趋势
2. 识别异常变化的指标
3. 分析指标之间的联动关系
4. 给出综合判断

请以结构化的方式呈现分析结果。""",
            placeholders=[
                PlaceholderDef(
                    name="MACRO_DATA",
                    type=PlaceholderType.STRUCTURED,
                    description="宏观指标摘要数据",
                    required=True
                ),
            ],
            system_prompt="你是一位资深的经济数据分析师，擅长从多维度解读宏观数据。",
            temperature=0.6,
            max_tokens=1500,
            description="宏观数据摘要分析模板",
            is_active=True,
            created_at=date.today()
        ),

        # 3. 投资信号生成模板
        PromptTemplate(
            id=None,
            name="signal_generation",
            category=PromptCategory.SIGNAL_GENERATION,
            version="1.0",
            template_content="""基于以下信息，为资产 {{ASSET_CODE}} 生成投资信号：

## 市场环境
- 当前Regime: {{REGIME}}
- 政策档位: {{POLICY_LEVEL}}

## 宏观背景
{{MACRO_DATA}}

## 要求
请生成投资信号，包含以下内容（JSON格式）：
```json
{
  "direction": "LONG/SHORT/NEUTRAL",
  "logic_desc": "投资逻辑描述",
  "invalidation_logic": "证伪逻辑",
  "invalidation_threshold": 数值,
  "target_regime": "目标Regime",
  "confidence": 0.0-1.0
}
```""",
            placeholders=[
                PlaceholderDef(
                    name="ASSET_CODE",
                    type=PlaceholderType.SIMPLE,
                    description="资产代码",
                    required=True
                ),
                PlaceholderDef(
                    name="REGIME",
                    type=PlaceholderType.STRUCTURED,
                    description="当前Regime状态",
                    required=True
                ),
                PlaceholderDef(
                    name="POLICY_LEVEL",
                    type=PlaceholderType.SIMPLE,
                    description="政策档位",
                    required=True
                ),
                PlaceholderDef(
                    name="MACRO_DATA",
                    type=PlaceholderType.STRUCTURED,
                    description="宏观指标摘要",
                    required=True
                ),
            ],
            system_prompt="你是一位专业的量化投资分析师，擅长基于宏观环境生成投资信号，并设计完善的证伪逻辑。",
            temperature=0.5,
            max_tokens=1000,
            description="投资信号生成模板",
            is_active=True,
            created_at=date.today()
        ),

        # 4. 趋势分析模板
        PromptTemplate(
            id=None,
            name="trend_analysis",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""请分析指标 {{INDICATOR_CODE}} 的趋势：

## 趋势数据
{{TREND_DATA}}

## 时序数据（最近3个月）
{{SERIES_DATA}}

## 分析要求
1. 判断趋势方向（上升/下降/震荡）
2. 评估趋势强度
3. 识别可能的转折点
4. 预测未来走势

请给出专业的技术分析结论。""",
            placeholders=[
                PlaceholderDef(
                    name="INDICATOR_CODE",
                    type=PlaceholderType.SIMPLE,
                    description="指标代码",
                    required=True
                ),
                PlaceholderDef(
                    name="TREND_DATA",
                    type=PlaceholderType.FUNCTION,
                    description="趋势分析结果",
                    function_name="calculate_trend",
                    function_params={"period": "3m"}
                ),
                PlaceholderDef(
                    name="SERIES_DATA",
                    type=PlaceholderType.FUNCTION,
                    description="时序数据",
                    function_name="get_series",
                    function_params={"days": 90}
                ),
            ],
            system_prompt="你是一位技术分析专家，擅长识别数据趋势和模式。",
            temperature=0.6,
            max_tokens=1500,
            description="趋势分析模板",
            is_active=True,
            created_at=date.today()
        ),

        # 5. 聊天助手模板
        PromptTemplate(
            id=None,
            name="chat_assistant",
            category=PromptCategory.CHAT,
            version="1.0",
            template_content="""{{USER_MESSAGE}}

{%if CONTEXT%}
## 上下文信息
{{CONTEXT}}
{%endif%}

请基于你的专业知识回答用户问题。要求：
1. 回答要专业且易懂
2. 必要时提供数据支撑
3. 给出明确的结论和建议""",
            placeholders=[
                PlaceholderDef(
                    name="USER_MESSAGE",
                    type=PlaceholderType.SIMPLE,
                    description="用户消息",
                    required=True
                ),
                PlaceholderDef(
                    name="CONTEXT",
                    type=PlaceholderType.STRUCTURED,
                    description="上下文数据",
                    required=False
                ),
            ],
            system_prompt="你是AgomSAAF系统的智能助手，精通宏观经济学、Regime理论和量化投资。请以专业、友好的方式回答用户问题。",
            temperature=0.8,
            max_tokens=1000,
            description="聊天助手模板",
            is_active=True,
            created_at=date.today()
        ),

        # 6. 周度市场分析报告
        PromptTemplate(
            id=None,
            name="weekly_market_report",
            category=PromptCategory.REPORT_ANALYSIS,
            version="1.0",
            template_content="""请生成{{REPORT_DATE}}所在周的金融市场分析报告：

## 一、宏观环境摘要
{{MACRO_SUMMARY}}

## 二、Regime状态分析
当前Regime: {{DOMINANT_REGIME_NAME}}
置信度: {{REGIME_CONFIDENCE}}%
增长动量: {{GROWTH_Z}}
通胀动量: {{INFLATION_Z}}

## 三、市场影响分析
请分析当前宏观环境对不同资产类别的影响：
1. 股票市场
2. 债券市场
3. 商品市场
4. 汇率市场

## 四、下周展望
基于当前数据，预测下周可能的变化。

## 五、投资建议
给出具体的资产配置建议（JSON格式）：
```json
{
  "equity_allocation": "百分比",
  "bond_allocation": "百分比",
  "commodity_allocation": "百分比",
  "cash_allocation": "百分比",
  "rationale": "理由说明"
}
```""",
            placeholders=[
                PlaceholderDef(
                    name="REPORT_DATE",
                    type=PlaceholderType.SIMPLE,
                    description="报告日期",
                    required=True
                ),
                PlaceholderDef(
                    name="MACRO_SUMMARY",
                    type=PlaceholderType.STRUCTURED,
                    description="宏观摘要",
                    required=True
                ),
                PlaceholderDef(
                    name="DOMINANT_REGIME_NAME",
                    type=PlaceholderType.SIMPLE,
                    description="主导Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="REGIME_CONFIDENCE",
                    type=PlaceholderType.SIMPLE,
                    description="置信度",
                    required=True
                ),
                PlaceholderDef(
                    name="GROWTH_Z",
                    type=PlaceholderType.SIMPLE,
                    description="增长Z-score",
                    required=True
                ),
                PlaceholderDef(
                    name="INFLATION_Z",
                    type=PlaceholderType.SIMPLE,
                    description="通胀Z-score",
                    required=True
                ),
            ],
            system_prompt="你是一位资深的市场策略分析师，擅长综合宏观分析生成投资策略报告。",
            temperature=0.7,
            max_tokens=2500,
            description="周度市场分析报告",
            is_active=True,
            created_at=date.today()
        ),

        # 7. PMI专项分析
        PromptTemplate(
            id=None,
            name="pmi_deep_analysis",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""请对中国PMI数据进行深度分析：

## PMI最新读数
- 制造业PMI: {{MANUFACTURING_PMI}}
- 非制造业PMI: {{NON_MANUFACTURING_PMI}}
- 综合PMI: {{COMPOSITE_PMI}}

## 历史趋势（最近6个月）
{{PMI_HISTORY}}

## 分析要求
1. 当前PMI处于什么水平（扩张/收缩区间）
2. 与上月相比的变化方向和幅度
3. PMI细分项分析（生产、新订单、库存等）
4. 对经济增长的含义
5. 政策建议

请以专业的宏观经济分析视角给出完整报告。""",
            placeholders=[
                PlaceholderDef(
                    name="MANUFACTURING_PMI",
                    type=PlaceholderType.SIMPLE,
                    description="制造业PMI",
                    required=True,
                    default_value="50.0"
                ),
                PlaceholderDef(
                    name="NON_MANUFACTURING_PMI",
                    type=PlaceholderType.SIMPLE,
                    description="非制造业PMI",
                    required=True,
                    default_value="50.0"
                ),
                PlaceholderDef(
                    name="COMPOSITE_PMI",
                    type=PlaceholderType.SIMPLE,
                    description="综合PMI",
                    required=True,
                    default_value="50.0"
                ),
                PlaceholderDef(
                    name="PMI_HISTORY",
                    type=PlaceholderType.STRUCTURED,
                    description="PMI历史数据",
                    required=True
                ),
            ],
            system_prompt="你是PMI分析专家，精通中国采购经理指数的含义和解读。",
            temperature=0.6,
            max_tokens=1500,
            description="PMI专项深度分析",
            is_active=True,
            created_at=date.today()
        ),

        # 8. CPI通胀分析
        PromptTemplate(
            id=None,
            name="cpi_inflation_analysis",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""请分析中国CPI通胀数据：

## CPI最新数据
- CPI同比: {{CPI_YOY}}%
- CPI环比: {{CPI_MOM}}%
- 核心CPI: {{CORE_CPI}}%

## 分项数据
{{CPI_BREAKDOWN}}

## 分析要求
1. 当前通胀水平评估
2. 翘尾因素和新涨价因素分析
3. 食品和非食品价格变化
4. 货币政策含义
5. 未来走势预测

请给出完整的通胀分析报告。""",
            placeholders=[
                PlaceholderDef(
                    name="CPI_YOY",
                    type=PlaceholderType.SIMPLE,
                    description="CPI同比",
                    required=True,
                    default_value="0.0"
                ),
                PlaceholderDef(
                    name="CPI_MOM",
                    type=PlaceholderType.SIMPLE,
                    description="CPI环比",
                    required=True,
                    default_value="0.0"
                ),
                PlaceholderDef(
                    name="CORE_CPI",
                    type=PlaceholderType.SIMPLE,
                    description="核心CPI",
                    required=True,
                    default_value="0.0"
                ),
                PlaceholderDef(
                    name="CPI_BREAKDOWN",
                    type=PlaceholderType.STRUCTURED,
                    description="CPI分项数据",
                    required=True
                ),
            ],
            system_prompt="你是通胀分析专家，精通中国CPI数据构成和通胀理论。",
            temperature=0.6,
            max_tokens=1500,
            description="CPI通胀专项分析",
            is_active=True,
            created_at=date.today()
        ),

        # 9. 债券市场分析
        PromptTemplate(
            id=None,
            name="bond_market_analysis",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""请分析债券市场投资机会：

## 宏观环境
- Regime: {{REGIME}}
- 增长Z-score: {{GROWTH_Z}}
- 通胀Z-score: {{INFLATION_Z}}

## 利率环境
- 10年期国债收益率: {{BOND_YIELD_10Y}}%
- 1年期国债收益率: {{BOND_YIELD_1Y}}%
- 收益率曲线利差: {{YIELD_SPREAD}}bp

## 分析要求
1. 当前利率周期阶段判断
2. 收益率曲线形态分析
3. 债券市场投资策略（久期、信用、杠杆）
4. 风险提示

请给出专业的债券投资建议。""",
            placeholders=[
                PlaceholderDef(
                    name="REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="当前Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="GROWTH_Z",
                    type=PlaceholderType.SIMPLE,
                    description="增长Z-score",
                    required=True
                ),
                PlaceholderDef(
                    name="INFLATION_Z",
                    type=PlaceholderType.SIMPLE,
                    description="通胀Z-score",
                    required=True
                ),
                PlaceholderDef(
                    name="BOND_YIELD_10Y",
                    type=PlaceholderType.SIMPLE,
                    description="10年期国债收益率",
                    required=True,
                    default_value="2.5"
                ),
                PlaceholderDef(
                    name="BOND_YIELD_1Y",
                    type=PlaceholderType.SIMPLE,
                    description="1年期国债收益率",
                    required=True,
                    default_value="2.0"
                ),
                PlaceholderDef(
                    name="YIELD_SPREAD",
                    type=PlaceholderType.SIMPLE,
                    description="收益率曲线利差",
                    required=True,
                    default_value="50"
                ),
            ],
            system_prompt="你是债券投资专家，精通固定收益分析和利率周期理论。",
            temperature=0.6,
            max_tokens=1500,
            description="债券市场投资分析",
            is_active=True,
            created_at=date.today()
        ),

        # 10. 风险预警分析
        PromptTemplate(
            id=None,
            name="risk_warning_analysis",
            category=PromptCategory.REPORT_ANALYSIS,
            version="1.0",
            template_content="""请分析当前市场的潜在风险：

## 宏观指标
{{MACRO_INDICATORS}}

## Regime状态
- 当前: {{CURRENT_REGIME}}
- 上月: {{LAST_MONTH_REGIME}}
- 变化趋势: {{REGIME_TREND}}

## 分析要求
请识别以下潜在风险：
1. **系统性风险**：经济周期拐点风险
2. **政策风险**：货币政策转向风险
3. **市场风险**：估值泡沫风险
4. **流动性风险**：资金面紧张风险

对每个风险给出：
- 风险等级（高/中/低）
- 触发条件
- 影响程度
- 应对建议

输出格式为JSON：
```json
{
  "overall_risk_level": "HIGH/MEDIUM/LOW",
  "risks": [
    {
      "type": "风险类型",
      "level": "风险等级",
      "trigger_conditions": ["触发条件1", "触发条件2"],
      "impact_description": "影响描述",
      "mitigation_actions": ["应对措施1", "应对措施2"]
    }
  ]
}
```""",
            placeholders=[
                PlaceholderDef(
                    name="MACRO_INDICATORS",
                    type=PlaceholderType.STRUCTURED,
                    description="宏观指标",
                    required=True
                ),
                PlaceholderDef(
                    name="CURRENT_REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="当前Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="LAST_MONTH_REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="上月Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="REGIME_TREND",
                    type=PlaceholderType.SIMPLE,
                    description="Regime变化趋势",
                    required=True
                ),
            ],
            system_prompt="你是风险管理专家，擅长识别和评估金融市场各类风险。",
            temperature=0.5,
            max_tokens=2000,
            description="市场风险预警分析",
            is_active=True,
            created_at=date.today()
        ),

        # 11. 资产配置建议
        PromptTemplate(
            id=None,
            name="asset_allocation_advice",
            category=PromptCategory.SIGNAL_GENERATION,
            version="1.0",
            template_content="""基于宏观环境给出资产配置建议：

## 投资者信息
- 风险偏好: {{RISK_PROFILE}}
- 投资期限: {{INVESTMENT_HORIZON}}
- 资金规模: {{CAPITAL}}

## 宏观环境
- Regime: {{REGIME}}
- 置信度: {{CONFIDENCE}}%
- 政策档位: {{POLICY_LEVEL}}

## 配置建议要求
请为以下资产类别给出配置比例（总和100%）：
1. 股票（A股/港股/美股）
2. 债券（国债/信用债）
3. 商品（黄金/原油）
4. 现金及货币基金

输出JSON格式：
```json
{
  "allocation": {
    "equity": {"a_share": 0, "h_share": 0, "us_stock": 0},
    "bond": {"government": 0, "corporate": 0},
    "commodity": {"gold": 0, "oil": 0},
    "cash": 0
  },
  "rationale": "配置理由",
  "tactical_adjustments": "战术调整建议",
  "risk_mitigation": "风险缓释措施"
}
```""",
            placeholders=[
                PlaceholderDef(
                    name="RISK_PROFILE",
                    type=PlaceholderType.SIMPLE,
                    description="风险偏好（conservative/balanced/aggressive）",
                    required=True,
                    default_value="balanced"
                ),
                PlaceholderDef(
                    name="INVESTMENT_HORIZON",
                    type=PlaceholderType.SIMPLE,
                    description="投资期限（short/medium/long）",
                    required=True,
                    default_value="medium"
                ),
                PlaceholderDef(
                    name="CAPITAL",
                    type=PlaceholderType.SIMPLE,
                    description="资金规模",
                    required=True,
                    default_value="100万"
                ),
                PlaceholderDef(
                    name="REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="当前Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="CONFIDENCE",
                    type=PlaceholderType.SIMPLE,
                    description="置信度",
                    required=True
                ),
                PlaceholderDef(
                    name="POLICY_LEVEL",
                    type=PlaceholderType.SIMPLE,
                    description="政策档位",
                    required=True
                ),
            ],
            system_prompt="你是资产配置专家，精通基于宏观环境的战略资产配置（SAA）和战术资产配置（TAA）。",
            temperature=0.6,
            max_tokens=1500,
            description="资产配置建议生成",
            is_active=True,
            created_at=date.today()
        ),

        # 12. 行业轮动建议
        PromptTemplate(
            id=None,
            name="sector_rotation_advice",
            category=PromptCategory.SIGNAL_GENERATION,
            version="1.0",
            template_content="""基于当前宏观环境给出行业轮动建议：

## 宏观环境
- Regime: {{REGIME}}
- 增长Z-score: {{GROWTH_Z}}
- 通胀Z-score: {{INFLATION_Z}}

## 分析要求
1. 当前阶段最适合的行业/主题
2. 应当规避的行业/主题
3. 行业配置权重建议

主要关注行业：
- 金融（银行、保险、券商）
- 周期（钢铁、化工、建材）
- 消费（食品饮料、家电、白酒）
- 成长（新能源、半导体、医药）
- 稳定（公用事业、高速公路）

输出JSON格式：
```json
{
  "overweight_sectors": ["超配行业1", "超配行业2"],
  "underweight_sectors": ["低配行业1", "低配行业2"],
  "neutral_sectors": ["标配行业"],
  "rationale": {
    "超配行业1": "理由",
    "低配行业1": "理由"
  }
}
```""",
            placeholders=[
                PlaceholderDef(
                    name="REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="当前Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="GROWTH_Z",
                    type=PlaceholderType.SIMPLE,
                    description="增长Z-score",
                    required=True
                ),
                PlaceholderDef(
                    name="INFLATION_Z",
                    type=PlaceholderType.SIMPLE,
                    description="通胀Z-score",
                    required=True
                ),
            ],
            system_prompt="你是行业配置专家，精通基于宏观周期的行业轮动理论。",
            temperature=0.6,
            max_tokens=1500,
            description="行业轮动建议",
            is_active=True,
            created_at=date.today()
        ),

        # 13. 货币政策解读
        PromptTemplate(
            id=None,
            name="monetary_policy_interpretation",
            category=PromptCategory.REPORT_ANALYSIS,
            version="1.0",
            template_content="""请解读最近的货币政策信号：

## 政策信息
- 政策会议: {{POLICY_MEETING}}
- 政策档位: {{POLICY_LEVEL}}
- 利率决定: {{RATE_DECISION}}
- 政策表述: {{POLICY_STATEMENT}}

## 宏观背景
{{MACRO_CONTEXT}}

## 解读要求
1. 政策倾向（宽松/中性/紧缩）
2. 政策变化点及含义
3. 未来政策路径预测
4. 对市场的影响

请给出专业的货币政策解读报告。""",
            placeholders=[
                PlaceholderDef(
                    name="POLICY_MEETING",
                    type=PlaceholderType.SIMPLE,
                    description="政策会议名称",
                    required=True
                ),
                PlaceholderDef(
                    name="POLICY_LEVEL",
                    type=PlaceholderType.SIMPLE,
                    description="政策档位",
                    required=True
                ),
                PlaceholderDef(
                    name="RATE_DECISION",
                    type=PlaceholderType.SIMPLE,
                    description="利率决定",
                    required=True
                ),
                PlaceholderDef(
                    name="POLICY_STATEMENT",
                    type=PlaceholderType.STRUCTURED,
                    description="政策声明摘要",
                    required=True
                ),
                PlaceholderDef(
                    name="MACRO_CONTEXT",
                    type=PlaceholderType.STRUCTURED,
                    description="宏观背景",
                    required=True
                ),
            ],
            system_prompt="你是货币政策专家，精通央行政策和利率传导机制。",
            temperature=0.6,
            max_tokens=1500,
            description="货币政策解读",
            is_active=True,
            created_at=date.today()
        ),

        # 14. 重大事件影响评估
        PromptTemplate(
            id=None,
            name="event_impact_assessment",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""请评估重大事件对市场的影响：

## 事件信息
- 事件类型: {{EVENT_TYPE}}
- 事件描述: {{EVENT_DESCRIPTION}}
- 发生时间: {{EVENT_DATE}}

## 当前市场环境
- Regime: {{REGIME}}
- 市场状态: {{MARKET_STATE}}

## 影响评估要求
1. 短期影响（1周内）
2. 中期影响（1-3个月）
3. 长期影响（3个月以上）
4. 受影响最大的资产/板块
5. 投资建议

请给出结构化的事件影响评估报告。""",
            placeholders=[
                PlaceholderDef(
                    name="EVENT_TYPE",
                    type=PlaceholderType.SIMPLE,
                    description="事件类型（政策/数据/地缘等）",
                    required=True
                ),
                PlaceholderDef(
                    name="EVENT_DESCRIPTION",
                    type=PlaceholderType.SIMPLE,
                    description="事件描述",
                    required=True
                ),
                PlaceholderDef(
                    name="EVENT_DATE",
                    type=PlaceholderType.SIMPLE,
                    description="事件时间",
                    required=True
                ),
                PlaceholderDef(
                    name="REGIME",
                    type=PlaceholderType.SIMPLE,
                    description="当前Regime",
                    required=True
                ),
                PlaceholderDef(
                    name="MARKET_STATE",
                    type=PlaceholderType.STRUCTURED,
                    description="市场状态",
                    required=True
                ),
            ],
            system_prompt="你是事件分析专家，擅长评估突发事件对金融市场的影响。",
            temperature=0.7,
            max_tokens=1500,
            description="重大事件影响评估",
            is_active=True,
            created_at=date.today()
        ),

        # 15. 简易快速分析
        PromptTemplate(
            id=None,
            name="quick_analysis",
            category=PromptCategory.DATA_ANALYSIS,
            version="1.0",
            template_content="""快速分析{{ANALYSIS_TARGET}}：

## 相关数据
{{DATA}}

## 简要分析
请用3-5句话给出核心结论：
1. 当前状态
2. 趋势判断
3. 关键信号
4. 操作建议

要求简洁明了，直击要点。""",
            placeholders=[
                PlaceholderDef(
                    name="ANALYSIS_TARGET",
                    type=PlaceholderType.SIMPLE,
                    description="分析目标",
                    required=True
                ),
                PlaceholderDef(
                    name="DATA",
                    type=PlaceholderType.STRUCTURED,
                    description="相关数据",
                    required=True
                ),
            ],
            system_prompt="你是快速分析专家，擅长从复杂数据中快速提炼核心观点。",
            temperature=0.6,
            max_tokens=500,
            description="快速简易分析",
            is_active=True,
            created_at=date.today()
        ),
    ]


# ============================================
# Predefined Chain Configurations
# ============================================

def get_predefined_chains() -> list[ChainConfig]:
    """
    获取预定义的链配置列表

    Returns:
        ChainConfig实体列表
    """
    return [
        # 1. 完整投资报告链（串行）
        ChainConfig(
            id=None,
            name="investment_report_chain",
            category=PromptCategory.REPORT_ANALYSIS,
            description="完整的投资分析报告生成流程：宏观摘要 -> Regime分析 -> 综合报告",
            steps=[
                ChainStep(
                    step_id="step1_macro",
                    template_id="macro_summary",  # 引用模板名称
                    step_name="宏观数据摘要",
                    order=1,
                    input_mapping={},
                    output_parser=None,
                    parallel_group=None
                ),
                ChainStep(
                    step_id="step2_regime",
                    template_id="regime_analysis",
                    step_name="Regime分析",
                    order=2,
                    input_mapping={
                        "DOMINANT_REGIME_NAME": "step1.output.dominant_regime_name",
                        "REGIME_CONFIDENCE": "step1.output.confidence",
                    },
                    output_parser=None,
                    parallel_group=None
                ),
                ChainStep(
                    step_id="step3_report",
                    template_id="final_report",
                    step_name="综合报告",
                    order=3,
                    input_mapping={
                        "MACRO_SUMMARY": "step1.output.summary",
                        "REGIME_ANALYSIS": "step2.output.content",
                    },
                    output_parser=None,
                    parallel_group=None
                ),
            ],
            execution_mode=ChainExecutionMode.SERIAL,
            aggregate_step=None,
            is_active=True,
            created_at=date.today()
        ),

        # 2. 多维度并行分析链
        ChainConfig(
            id=None,
            name="multi_analysis_chain",
            category=PromptCategory.DATA_ANALYSIS,
            description="对多个宏观指标并行分析，然后汇总",
            steps=[
                ChainStep(
                    step_id="step_pmi",
                    template_id="trend_analysis",
                    step_name="PMI趋势分析",
                    order=1,
                    input_mapping={"INDICATOR_CODE": "CN_PMI"},
                    output_parser=None,
                    parallel_group="group1"
                ),
                ChainStep(
                    step_id="step_cpi",
                    template_id="trend_analysis",
                    step_name="CPI趋势分析",
                    order=1,
                    input_mapping={"INDICATOR_CODE": "CN_CPI"},
                    output_parser=None,
                    parallel_group="group1"
                ),
                ChainStep(
                    step_id="step_ppi",
                    template_id="trend_analysis",
                    step_name="PPI趋势分析",
                    order=1,
                    input_mapping={"INDICATOR_CODE": "CN_PPI"},
                    output_parser=None,
                    parallel_group="group1"
                ),
                ChainStep(
                    step_id="step_aggregate",
                    template_id="aggregate_analysis",
                    step_name="汇总分析",
                    order=2,
                    input_mapping={
                        "PMI_ANALYSIS": "step_pmi.output.content",
                        "CPI_ANALYSIS": "step_cpi.output.content",
                        "PPI_ANALYSIS": "step_ppi.output.content",
                    },
                    output_parser=None,
                    parallel_group=None
                ),
            ],
            execution_mode=ChainExecutionMode.PARALLEL,
            aggregate_step=None,
            is_active=True,
            created_at=date.today()
        ),

        # 3. 信号验证链（工具调用模式）
        ChainConfig(
            id=None,
            name="signal_validation_chain",
            category=PromptCategory.SIGNAL_GENERATION,
            description="AI生成投资信号并验证证伪逻辑的完整性",
            steps=[
                ChainStep(
                    step_id="step_generate",
                    template_id="signal_generation",
                    step_name="生成信号",
                    order=1,
                    input_mapping={},
                    output_parser="extract_json",
                    parallel_group=None,
                    enable_tool_calling=True,
                    available_tools=["get_macro_indicator", "get_regime_status"]
                ),
                ChainStep(
                    step_id="step_validate",
                    template_id="signal_validation",
                    step_name="验证信号",
                    order=2,
                    input_mapping={
                        "SIGNAL_DATA": "step_generate.output.parsed_output"
                    },
                    output_parser=None,
                    parallel_group=None
                ),
            ],
            execution_mode=ChainExecutionMode.TOOL_CALLING,
            aggregate_step=None,
            is_active=True,
            created_at=date.today()
        ),
    ]


# ============================================
# Load Functions
# ============================================

def load_predefined_templates(repository) -> int:
    """
    加载预定义模板到数据库

    Args:
        repository: DjangoPromptRepository实例

    Returns:
        成功加载的模板数量
    """
    templates = get_predefined_templates()
    count = 0

    for template in templates:
        try:
            # 检查是否已存在
            existing = repository.get_template_by_name(template.name)
            if not existing:
                repository.create_template(template)
                count += 1
        except Exception as e:
            print(f"加载模板 {template.name} 失败: {e}")

    return count


def load_predefined_chains(repository) -> int:
    """
    加载预定义链配置到数据库

    Args:
        repository: DjangoChainRepository实例

    Returns:
        成功加载的链配置数量
    """
    chains = get_predefined_chains()
    count = 0

    for chain in chains:
        try:
            # 检查是否已存在
            existing = repository.get_chain_by_name(chain.name)
            if not existing:
                repository.create_chain(chain)
                count += 1
        except Exception as e:
            print(f"加载链配置 {chain.name} 失败: {e}")

    return count

