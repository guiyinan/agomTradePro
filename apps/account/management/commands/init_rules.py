"""
初始化投资规则管理命令

加载默认的投资建议规则到数据库。
"""

from django.core.management.base import BaseCommand
from apps.account.infrastructure.models import InvestmentRuleModel


class Command(BaseCommand):
    help = '初始化投资建议规则'

    def handle(self, *args, **options):
        # 初始规则数据
        initial_rules = [
            # ==================== Regime 环境建议 ====================
            {
                'name': '复苏象限建议',
                'rule_type': 'regime_advice',
                'priority': 1,
                'conditions': {'regime': 'Recovery'},
                'advice_template': '当前处于【复苏】象限（增长↑ 通胀↓），建议增加权益仓位至70%以上，重点关注成长股和周期股。'
            },
            {
                'name': '过热象限建议',
                'rule_type': 'regime_advice',
                'priority': 1,
                'conditions': {'regime': 'Overheat'},
                'advice_template': '当前处于【过热】象限（增长↑ 通胀↑），建议增加商品配置，关注通胀对冲，降低久期债券仓位。'
            },
            {
                'name': '滞胀象限建议',
                'rule_type': 'regime_advice',
                'priority': 1,
                'conditions': {'regime': 'Stagflation'},
                'advice_template': '当前处于【滞胀】象限（增长↓ 通胀↑），建议增加现金和短债，关注防御股和黄金等避险资产。'
            },
            {
                'name': '通缩象限建议',
                'rule_type': 'regime_advice',
                'priority': 1,
                'conditions': {'regime': 'Deflation'},
                'advice_template': '当前处于【通缩】象限（增长↓ 通胀↓），建议增加长久期国债，降低权益仓位，保持充足现金流。'
            },

            # ==================== 仓位建议 ====================
            {
                'name': '低仓位建议',
                'rule_type': 'position_advice',
                'priority': 10,
                'conditions': {'min_cash_ratio': 0.7},
                'advice_template': '💡 您的现金仓位较高({cash_ratio}%)，建议适度建仓以把握市场机会'
            },
            {
                'name': '高仓位建议',
                'rule_type': 'position_advice',
                'priority': 10,
                'conditions': {'min_invested_ratio': 0.95},
                'advice_template': '⚠️ 您的仓位接近满仓，建议保留一定现金以应对市场波动'
            },

            # ==================== Regime 匹配度建议 ====================
            {
                'name': '低匹配度建议',
                'rule_type': 'match_advice',
                'priority': 20,
                'conditions': {'max_match_score': 50},
                'advice_template': '⚠️ 当前持仓与Regime匹配度较低({match_score}分)，建议调整配置'
            },

            # ==================== 投资信号建议 ====================
            {
                'name': '有活跃信号建议',
                'rule_type': 'signal_advice',
                'priority': 30,
                'conditions': {'min_signal_count': 1},
                'advice_template': '📊 您有{signal_count}个活跃投资信号，建议关注证伪条件'
            },
            {
                'name': '无活跃信号建议',
                'rule_type': 'signal_advice',
                'priority': 30,
                'conditions': {'max_signal_count': 0},
                'advice_template': '📊 当前无活跃信号，可基于当前Regime创建新的投资信号'
            },

            # ==================== 风险提示 ====================
            {
                'name': '高亏损警告',
                'rule_type': 'risk_alert',
                'priority': 5,
                'conditions': {'max_return_pct': -10},
                'advice_template': '📉 当前组合亏损超过10%，建议复盘投资逻辑，必要时止损'
            },
            {
                'name': '高盈利提醒',
                'rule_type': 'risk_alert',
                'priority': 5,
                'conditions': {'min_return_pct': 20},
                'advice_template': '📈 当前组合收益良好，建议考虑部分止盈锁定利润'
            },
        ]

        created_count = 0
        updated_count = 0

        for rule_data in initial_rules:
            conditions = rule_data.pop('conditions')
            # 检查是否已存在同名规则
            existing = InvestmentRuleModel._default_manager.filter(
                name=rule_data['name'],
                user__isnull=True
            ).first()

            if existing:
                # 更新现有规则
                for key, value in rule_data.items():
                    setattr(existing, key, value)
                existing.conditions = conditions
                existing.save()
                updated_count += 1
                self.stdout.write(f'[更新] {rule_data["name"]}')
            else:
                # 创建新规则
                rule = InvestmentRuleModel._default_manager.create(
                    user=None,  # 全局默认规则
                    conditions=conditions,
                    **rule_data
                )
                created_count += 1
                self.stdout.write(f'[创建] {rule_data["name"]}')

        self.stdout.write(self.style.SUCCESS(f'\n初始化完成！创建 {created_count} 条规则，更新 {updated_count} 条规则。'))

