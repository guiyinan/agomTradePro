"""
Django Management Command: Initialize Enhanced Investment Rules

初始化增强的投资建议规则库（易用性改进 - AI助手降级增强）

运行方式：
    python manage.py init_enhanced_rules

功能：
    - 创建20+条预定义规则覆盖常见场景
    - 规则类型：regime_advice, position_advice, match_advice, signal_advice, risk_alert
    - 支持Regime+Policy组合、匹配度+仓位组合等复杂条件
"""

from django.core.management.base import BaseCommand
from apps.account.infrastructure.models import InvestmentRuleModel


class Command(BaseCommand):
    help = '初始化增强的投资建议规则库'

    def handle(self, *args, **options):
        """执行初始化"""
        # 清空现有全局规则
        deleted_count = InvestmentRuleModel._default_manager.filter(user__isnull=True).delete()[0]
        self.stdout.write(f"Deleted {deleted_count} old rules")

        # 创建新规则
        rules = self.get_enhanced_rules()
        created_count = 0

        for rule_data in rules:
            # 检查规则是否已存在
            existing = InvestmentRuleModel._default_manager.filter(
                user__isnull=True,
                name=rule_data['name'],
                rule_type=rule_data['rule_type']
            ).first()

            if not existing:
                InvestmentRuleModel._default_manager.create(**rule_data)
                created_count += 1
                self.stdout.write(f"[OK] Created rule: {rule_data['name']}")
            else:
                self.stdout.write(f"[SKIP] Rule exists: {rule_data['name']}")

        self.stdout.write(
            self.style.SUCCESS(f'\nInitialization complete! Created {created_count} new rules, total {len(rules)} rules')
        )

    def get_enhanced_rules(self):
        """
        获取增强规则列表

        返回格式：
        [
            {
                'name': '规则名称',
                'rule_type': 'regime_advice',
                'priority': 1,
                'is_active': True,
                'conditions': {...},
                'advice_template': '建议内容'
            },
            ...
        ]
        """
        return [
            # ============================================================
            # Level 2: 组合规则（最高优先级）
            # ============================================================

            {
                'name': '滞胀期+政策收紧强烈减仓',
                'rule_type': 'regime_policy_combo',
                'priority': 1,
                'is_active': True,
                'conditions': {
                    'regime': 'Stagflation',
                    'min_policy_level': 2,  # P2或P3
                },
                'advice_template': '🚨 滞胀期 + 政策收紧（{policy_level}）：强烈建议清空权益仓位，转入现金或短债',
            },
            {
                'name': '过热期+政策收紧适度减仓',
                'rule_type': 'regime_policy_combo',
                'priority': 2,
                'is_active': True,
                'conditions': {
                    'regime': 'Overheat',
                    'min_policy_level': 2,
                },
                'advice_template': '⚠️ 过热期 + 政策收紧：建议降低权益仓位至40%以下，增加防御性资产',
            },
            {
                'name': '严重不匹配+高仓位警告',
                'rule_type': 'match_position_combo',
                'priority': 3,
                'is_active': True,
                'conditions': {
                    'max_match_score': 40,
                    'min_invested_ratio': 0.7,
                },
                'advice_template': '🚨 持仓严重不匹配（{match_score}分）且仓位过重（{invested_ratio}），强烈建议大幅减仓',
            },
            {
                'name': '复苏期+低仓位建议',
                'rule_type': 'regime_position_combo',
                'priority': 4,
                'is_active': True,
                'conditions': {
                    'regime': 'Recovery',
                    'max_invested_ratio': 0.3,
                },
                'advice_template': '📈 经济复苏期，当前仓位仅{invested_ratio}，可适度加仓权益资产',
            },
            {
                'name': '衰退期+高仓位警告',
                'rule_type': 'regime_position_combo',
                'priority': 5,
                'is_active': True,
                'conditions': {
                    'regime': 'Deflation',
                    'min_invested_ratio': 0.7,
                },
                'advice_template': '⚠️ 经济衰退期+高仓位（{invested_ratio}）风险较大，建议降低权益配置',
            },

            # ============================================================
            # Level 3: Regime环境建议（中等优先级）
            # ============================================================

            {
                'name': '复苏期权益建议',
                'rule_type': 'regime_advice',
                'priority': 10,
                'is_active': True,
                'conditions': {
                    'regime': 'Recovery',
                },
                'advice_template': '📈 经济复苏期（{regime}），增长{growth_direction}通胀{inflation_direction}，权益资产表现较好',
            },
            {
                'name': '过热期配置建议',
                'rule_type': 'regime_advice',
                'priority': 11,
                'is_active': True,
                'conditions': {
                    'regime': 'Overheat',
                },
                'advice_template': '🔥 经济过热期（{regime}），双高环境，建议适度降低权益，增加商品配置',
            },
            {
                'name': '滞胀期防御建议',
                'rule_type': 'regime_advice',
                'priority': 12,
                'is_active': True,
                'conditions': {
                    'regime': 'Stagflation',
                },
                'advice_template': '🛡️ 滞胀期（{regime}），最差宏观环境，建议持有防御性资产（债券、黄金）',
            },
            {
                'name': '衰退期债券建议',
                'rule_type': 'regime_advice',
                'priority': 13,
                'is_active': True,
                'conditions': {
                    'regime': 'Deflation',
                },
                'advice_template': '📉 经济衰退期（{regime}），央行宽松利好债券，建议增加债券配置',
            },

            # ============================================================
            # 仓位建议（根据当前仓位给出建议）
            # ============================================================

            {
                'name': '低仓位提醒',
                'rule_type': 'position_advice',
                'priority': 20,
                'is_active': True,
                'conditions': {
                    'max_invested_ratio': 0.3,
                },
                'advice_template': '💰 当前仓位较低（{invested_ratio}），可考虑适度加仓优质资产',
            },
            {
                'name': '适中仓位确认',
                'rule_type': 'position_advice',
                'priority': 21,
                'is_active': True,
                'conditions': {
                    'min_invested_ratio': 0.4,
                    'max_invested_ratio': 0.7,
                },
                'advice_template': '✓ 当前仓位适中（{invested_ratio}），保持观察',
            },
            {
                'name': '高仓位警示',
                'rule_type': 'position_advice',
                'priority': 22,
                'is_active': True,
                'conditions': {
                    'min_invested_ratio': 0.8,
                },
                'advice_template': '⚠️ 当前仓位较高（{invested_ratio}），注意控制风险',
            },

            # ============================================================
            # Regime匹配度建议
            # ============================================================

            {
                'name': '匹配度优秀',
                'rule_type': 'match_advice',
                'priority': 30,
                'is_active': True,
                'conditions': {
                    'min_match_score': 70,
                },
                'advice_template': '✓ 持仓与当前环境匹配度良好（{match_score}分），继续保持',
            },
            {
                'name': '匹配度一般',
                'rule_type': 'match_advice',
                'priority': 31,
                'is_active': True,
                'conditions': {
                    'min_match_score': 50,
                    'max_match_score': 70,
                },
                'advice_template': '⚠️ 持仓匹配度一般（{match_score}分），建议关注持仓结构',
            },
            {
                'name': '匹配度较差',
                'rule_type': 'match_advice',
                'priority': 32,
                'is_active': True,
                'conditions': {
                    'max_match_score': 50,
                },
                'advice_template': '❌ 持仓匹配度较差（{match_score}分），建议调整持仓结构',
            },

            # ============================================================
            # 投资信号建议
            # ============================================================

            {
                'name': '有活跃信号',
                'rule_type': 'signal_advice',
                'priority': 40,
                'is_active': True,
                'conditions': {
                    'has_active_signals': True,
                    'min_signal_count': 3,
                },
                'advice_template': '🎯 当前有{signal_count}个活跃信号，注意及时跟踪执行情况',
            },
            {
                'name': '无活跃信号提示',
                'rule_type': 'signal_advice',
                'priority': 41,
                'is_active': True,
                'conditions': {
                    'has_active_signals': False,
                },
                'advice_template': '💡 当前无活跃信号，可根据市场情况创建新信号',
            },
            {
                'name': '信号过多提醒',
                'rule_type': 'signal_advice',
                'priority': 42,
                'is_active': True,
                'conditions': {
                    'has_active_signals': True,
                    'min_signal_count': 10,
                },
                'advice_template': '⚠️ 活跃信号过多（{signal_count}个），建议清理已失效的信号',
            },

            # ============================================================
            # 风险提示
            # ============================================================

            {
                'name': '大额盈利提醒',
                'rule_type': 'risk_alert',
                'priority': 50,
                'is_active': True,
                'conditions': {
                    'min_return_pct': 20,
                },
                'advice_template': '🎉 收益率已达到{return_pct}%，建议适当止盈，落袋为安',
            },
            {
                'name': '亏损警示',
                'rule_type': 'risk_alert',
                'priority': 51,
                'is_active': True,
                'conditions': {
                    'max_return_pct': -10,
                },
                'advice_template': '⚠️ 当前亏损{return_pct}%，建议检查持仓，考虑止损或调整策略',
            },
            {
                'name': '巨额亏损警告',
                'rule_type': 'risk_alert',
                'priority': 52,
                'is_active': True,
                'conditions': {
                    'max_return_pct': -20,
                },
                'advice_template': '🚨 亏损已达{return_pct}%，强烈建议重新评估投资策略',
            },

            # ============================================================
            # Policy档位建议
            # ============================================================

            {
                'name': 'P0正常状态',
                'rule_type': 'policy_advice',
                'priority': 60,
                'is_active': True,
                'conditions': {
                    'max_policy_level': 0,
                },
                'advice_template': '✓ 政策环境正常（P0），可正常开展投资活动',
            },
            {
                'name': 'P1轻度限制',
                'rule_type': 'policy_advice',
                'priority': 61,
                'is_active': True,
                'conditions': {
                    'min_policy_level': 1,
                    'max_policy_level': 1,
                },
                'advice_template': '⚠️ 政策轻度收紧（P1），建议适度降低风险敞口',
            },
            {
                'name': 'P2中度限制',
                'rule_type': 'policy_advice',
                'priority': 62,
                'is_active': True,
                'conditions': {
                    'min_policy_level': 2,
                    'max_policy_level': 2,
                },
                'advice_template': '⚠️ 政策明显收紧（P2），建议降低权益仓位，增加防御性资产',
            },
            {
                'name': 'P3极度限制',
                'rule_type': 'policy_advice',
                'priority': 63,
                'is_active': True,
                'conditions': {
                    'min_policy_level': 3,
                },
                'advice_template': '🚨 政策极度收紧（P3），危机模式，强烈建议清空权益仓位',
            },

            # ============================================================
            # 静态保底规则（最后兜底）
            # ============================================================

            {
                'name': '保底规则-关注市场',
                'rule_type': 'static_advice',
                'priority': 100,
                'is_active': True,
                'conditions': {},
                'advice_template': '💡 定期查看持仓与Regime的匹配度，重大政策事件可能影响市场',
            },
            {
                'name': '保底规则-风险提示',
                'rule_type': 'static_advice',
                'priority': 101,
                'is_active': True,
                'conditions': {},
                'advice_template': '⚠️ 投资有风险，以上建议仅供参考，请根据个人情况做出决策',
            },
        ]

