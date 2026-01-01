"""
初始化 AI Prompt 模板

Usage:
    python manage.py shell < scripts/init_prompt_templates.py
    python scripts/init_prompt_templates.py
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.prompt.infrastructure.models import PromptTemplateORM, ChainConfigORM


# 预设 Prompt 模板
DEFAULT_TEMPLATES = [
    {
        'name': 'regime_analysis_report',
        'category': 'report',
        'version': '1.0',
        'template_content': '''请分析当前的宏观经济 Regime 状态，并生成详细报告。

## 当前状态
- 增长动量 Z-score: {{ growth_z }}
- 通胀动量 Z-score: {{ inflation_z }}
- 主导 Regime: {{ dominant_regime }}
- 置信度: {{ confidence }}

## Regime 分布
{% for regime, prob in distribution.items() %}
- {{ regime }}: {{ prob }}%
{% endfor %}

## 任务
请基于以上数据，生成一份包含以下内容的报告：
1. 当前经济状态概述
2. 各象限概率解读
3. 投资建议
4. 风险提示''',
        'system_prompt': '你是一位专业的宏观经济分析师，擅长解读经济周期和投资环境。',
        'placeholders': [
            {'name': 'growth_z', 'type': 'float', 'description': '增长动量Z-score'},
            {'name': 'inflation_z', 'type': 'float', 'description': '通胀动量Z-score'},
            {'name': 'dominant_regime', 'type': 'string', 'description': '主导Regime'},
            {'name': 'confidence', 'type': 'float', 'description': '置信度'},
            {'name': 'distribution', 'type': 'dict', 'description': 'Regime分布'}
        ],
        'temperature': 0.7,
        'max_tokens': 2000,
        'description': 'Regime 分析报告生成模板',
        'is_active': True
    },
    {
        'name': 'signal_validation',
        'category': 'signal',
        'version': '1.0',
        'template_content': '''请验证以下投资信号是否符合当前的宏观环境。

## 信号信息
- 资产代码: {{ asset_code }}
- 投资方向: {{ direction }}
- 目标 Regime: {{ target_regime }}
- 逻辑描述: {{ logic_desc }}
- 证伪条件: {{ invalidation_logic }}

## 当前 Regime
- 当前 Regime: {{ current_regime }}
- 置信度: {{ confidence }}

## 任务
请分析：
1. 该信号是否适合当前的宏观环境？
2. 证伪条件是否合理？
3. 给出通过/拒绝的建议及理由。''',
        'system_prompt': '你是一位资深的投资分析师，擅长宏观环境判断和信号验证。',
        'placeholders': [
            {'name': 'asset_code', 'type': 'string', 'description': '资产代码'},
            {'name': 'direction', 'type': 'string', 'description': '投资方向'},
            {'name': 'target_regime', 'type': 'string', 'description': '目标Regime'},
            {'name': 'logic_desc', 'type': 'string', 'description': '逻辑描述'},
            {'name': 'invalidation_logic', 'type': 'string', 'description': '证伪条件'},
            {'name': 'current_regime', 'type': 'string', 'description': '当前Regime'},
            {'name': 'confidence', 'type': 'float', 'description': '置信度'}
        ],
        'temperature': 0.5,
        'max_tokens': 1500,
        'description': '信号验证模板',
        'is_active': True
    },
    {
        'name': 'backtest_attribution',
        'category': 'analysis',
        'version': '1.0',
        'template_content': '''请分析以下回测结果，识别损失来源并提供改进建议。

## 回测结果
- 总收益率: {{ total_return }}%
- 年化收益率: {{ annual_return }}%
- 最大回撤: {{ max_drawdown }}%
- 夏普比率: {{ sharpe_ratio }}

## 交易统计
- 总交易次数: {{ total_trades }}
- 盈利交易: {{ winning_trades }}
- 亏损交易: {{ losing_trades }}
- 胜率: {{ win_rate }}%

## 任务
请提供：
1. 策略表现评估
2. 主要损失来源识别
3. 改进建议（基于 Regime 切换、止损、仓位管理等）
4. 下一步优化方向''',
        'system_prompt': '你是一位量化投资专家，擅长回测归因分析和策略优化。',
        'placeholders': [
            {'name': 'total_return', 'type': 'float', 'description': '总收益率'},
            {'name': 'annual_return', 'type': 'float', 'description': '年化收益率'},
            {'name': 'max_drawdown', 'type': 'float', 'description': '最大回撤'},
            {'name': 'sharpe_ratio', 'type': 'float', 'description': '夏普比率'},
            {'name': 'total_trades', 'type': 'int', 'description': '总交易次数'},
            {'name': 'winning_trades', 'type': 'int', 'description': '盈利交易'},
            {'name': 'losing_trades', 'type': 'int', 'description': '亏损交易'},
            {'name': 'win_rate', 'type': 'float', 'description': '胜率'}
        ],
        'temperature': 0.6,
        'max_tokens': 2500,
        'description': '回测归因分析模板',
        'is_active': True
    },
    {
        'name': 'policy_impact_analysis',
        'category': 'analysis',
        'version': '1.0',
        'template_content': '''请分析以下政策事件对市场的影响。

## 政策事件
- 事件日期: {{ event_date }}
- 政策档位: {{ policy_level }}
- 信息分类: {{ info_category }}
- 风险影响: {{ risk_impact }}
- 事件描述: {{ description }}

## 市场反应
- 事件前后 Regime 变化:
  - 之前: {{ regime_before }}
  - 之后: {{ regime_after }}

## 任务
请分析：
1. 政策事件的定性（利好/利空/中性）
2. 对投资策略的影响
3. 建议的应对措施（仓位调整、对冲、资产配置等）''',
        'system_prompt': '你是一位政策分析专家，擅长解读政策对金融市场的影响。',
        'placeholders': [
            {'name': 'event_date', 'type': 'string', 'description': '事件日期'},
            {'name': 'policy_level', 'type': 'string', 'description': '政策档位'},
            {'name': 'info_category', 'type': 'string', 'description': '信息分类'},
            {'name': 'risk_impact', 'type': 'string', 'description': '风险影响'},
            {'name': 'description', 'type': 'string', 'description': '事件描述'},
            {'name': 'regime_before', 'type': 'string', 'description': '之前Regime'},
            {'name': 'regime_after', 'type': 'string', 'description': '之后Regime'}
        ],
        'temperature': 0.5,
        'max_tokens': 1500,
        'description': '政策影响分析模板',
        'is_active': True
    },
    {
        'name': 'general_chat',
        'category': 'chat',
        'version': '1.0',
        'template_content': '''用户问题: {{ question }}

请基于 AgomSAAF 系统的知识回答问题。如果需要查询具体数据，请告知用户需要提供哪些信息。

相关上下文:
{% if context %}
{% for key, value in context.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}''',
        'system_prompt': '你是 AgomSAAF 系统的智能助手，帮助用户理解宏观环境、投资信号和策略回测。',
        'placeholders': [
            {'name': 'question', 'type': 'string', 'description': '用户问题'},
            {'name': 'context', 'type': 'dict', 'description': '上下文数据', 'required': False}
        ],
        'temperature': 0.7,
        'max_tokens': 1000,
        'description': '通用聊天模板',
        'is_active': True
    }
]


# 预设 Chain 配置
DEFAULT_CHAINS = [
    {
        'name': 'comprehensive_signal_analysis',
        'category': 'signal',
        'description': '综合信号分析：验证信号 → 评估风险 → 生成建议',
        'steps': [
            {
                'step_id': 'validate_signal',
                'template_name': 'signal_validation',
                'output_key': 'validation_result'
            },
            {
                'step_id': 'assess_risk',
                'template_name': 'policy_impact_analysis',
                'output_key': 'risk_assessment'
            },
            {
                'step_id': 'generate_recommendation',
                'template_name': 'regime_analysis_report',
                'output_key': 'final_recommendation'
            }
        ],
        'execution_mode': 'serial',
        'aggregate_step': {
            'template_name': 'regime_analysis_report',
            'aggregation_logic': '综合所有步骤的结果，生成最终投资建议'
        },
        'is_active': True
    },
    {
        'name': 'backtest_review_chain',
        'category': 'analysis',
        'description': '回测复盘：运行回测 → 归因分析 → 生成报告',
        'steps': [
            {
                'step_id': 'run_backtest',
                'action': 'run_backtest',
                'output_key': 'backtest_result'
            },
            {
                'step_id': 'analyze_attribution',
                'template_name': 'backtest_attribution',
                'output_key': 'attribution_analysis'
            }
        ],
        'execution_mode': 'serial',
        'is_active': True
    }
]


def init_prompt_templates():
    """初始化 Prompt 模板"""
    print("开始初始化 Prompt 模板...")

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for template_data in DEFAULT_TEMPLATES:
        name = template_data['name']

        try:
            existing = PromptTemplateORM.objects.get(name=name, version=template_data['version'])
            print(f"  [更新] {name}")
            for key, value in template_data.items():
                setattr(existing, key, value)
            existing.save()
            updated_count += 1
        except PromptTemplateORM.DoesNotExist:
            print(f"  [创建] {name}")
            PromptTemplateORM.objects.create(**template_data)
            created_count += 1
        except Exception as e:
            print(f"  [跳过] {name} - {e}")
            skipped_count += 1

    print(f"\n模板初始化完成:")
    print(f"  新建: {created_count}")
    print(f"  更新: {updated_count}")
    print(f"  跳过: {skipped_count}")


def init_chain_configs():
    """初始化 Chain 配置"""
    print("\n开始初始化 Chain 配置...")

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for chain_data in DEFAULT_CHAINS:
        name = chain_data['name']

        try:
            existing = ChainConfigORM.objects.get(name=name)
            print(f"  [更新] {name}")
            for key, value in chain_data.items():
                setattr(existing, key, value)
            existing.save()
            updated_count += 1
        except ChainConfigORM.DoesNotExist:
            print(f"  [创建] {name}")
            ChainConfigORM.objects.create(**chain_data)
            created_count += 1
        except Exception as e:
            print(f"  [跳过] {name} - {e}")
            skipped_count += 1

    print(f"\nChain 配置初始化完成:")
    print(f"  新建: {created_count}")
    print(f"  更新: {updated_count}")
    print(f"  跳过: {skipped_count}")


if __name__ == '__main__':
    init_prompt_templates()
    init_chain_configs()
    print("\n✅ Prompt 模板系统初始化完成！")
