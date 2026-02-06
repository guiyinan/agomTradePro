"""
Policy Influence Service - 政策影响服务

本服务用于检查政策事件对投资信号的影响，
包括黑名单检查、板块政策影响、个股舆情等。
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import timedelta

from django.utils import timezone
from django.db.models import Q

from signal.domain.entities import InvestmentSignal
from policy.infrastructure.models import PolicyLog

logger = logging.getLogger(__name__)


class PolicyInfluenceService:
    """
    政策影响服务

    将政策事件应用到投资信号，检查：
    1. 黑名单检查（直接拒绝）
    2. 白名单检查（优先考虑）
    3. 板块政策影响
    4. 个股舆情影响
    """

    def __init__(self):
        # 简化版本的股票到板块映射
        # 实际应用中应该从数据库或配置文件获取
        self._sector_map = self._build_sector_mapping()

    def apply_policy_influences(
        self,
        signal: InvestmentSignal
    ) -> Dict[str, Any]:
        """
        应用政策影响到信号

        Args:
            signal: 投资信号

        Returns:
            Dict: 影响分析结果
        """
        influences = {
            'blacklisted': False,
            'whitelisted': False,
            'affected_by_policies': [],
            'risk_adjustments': [],
            'recommendations': []
        }

        # 1. 检查黑名单
        blacklisted_policies = self._check_blacklist(signal.asset_code)
        if blacklisted_policies:
            influences['blacklisted'] = True
            influences['affected_by_policies'].extend([
                {
                    'policy_id': p.id,
                    'title': p.title,
                    'level': p.level,
                    'reason': 'blacklist'
                }
                for p in blacklisted_policies
            ])
            influences['recommendations'].append(
                f"该资产在黑名单中（{len(blacklisted_policies)}条政策），建议避免交易"
            )

        # 2. 检查白名单
        whitelisted_policies = self._check_whitelist(signal.asset_code)
        if whitelisted_policies:
            influences['whitelisted'] = True
            influences['affected_by_policies'].extend([
                {
                    'policy_id': p.id,
                    'title': p.title,
                    'level': p.level,
                    'reason': 'whitelist'
                }
                for p in whitelisted_policies
            ])

        # 3. 检查板块政策影响
        sector_policies = self._check_sector_influence(signal.asset_code)
        if sector_policies:
            influences['affected_by_policies'].extend([
                {
                    'policy_id': p.id,
                    'title': p.title,
                    'level': p.level,
                    'category': p.info_category,
                    'reason': 'sector_influence',
                    'sentiment': p.structured_data.get('sentiment', 'unknown')
                }
                for p in sector_policies
            ])

            # 根据政策情绪调整风险
            for policy in sector_policies:
                sentiment = policy.structured_data.get('sentiment', 'neutral')
                if sentiment == 'negative' and policy.level in ['P2', 'P3']:
                    influences['risk_adjustments'].append({
                        'policy_id': policy.id,
                        'adjustment': 'increase_cash',
                        'reason': f"负面政策: {policy.title}"
                    })
                elif sentiment == 'positive' and policy.level in ['P1', 'P2']:
                    influences['risk_adjustments'].append({
                        'policy_id': policy.id,
                        'adjustment': 'favorable_sector',
                        'reason': f"利好政策: {policy.title}"
                    })

        # 4. 检查个股舆情
        sentiment_policies = self._check_sentiment_influence(signal.asset_code)
        if sentiment_policies:
            influences['affected_by_policies'].extend([
                {
                    'policy_id': p.id,
                    'title': p.title,
                    'category': p.info_category,
                    'reason': 'sentiment_influence',
                    'sentiment': p.structured_data.get('sentiment', 'unknown'),
                    'sentiment_score': p.structured_data.get('sentiment_score', 0)
                }
                for p in sentiment_policies
            ])

            # 根据舆情情绪调整建议
            negative_sentiments = [
                p for p in sentiment_policies
                if p.structured_data.get('sentiment') == 'negative'
            ]
            if negative_sentiments:
                influences['recommendations'].append(
                    f"检测到{len(negative_sentiments)}条负面舆情，建议谨慎交易"
                )

        return influences

    def _check_blacklist(self, asset_code: str) -> List[PolicyLog]:
        """
        检查黑名单

        Args:
            asset_code: 资产代码

        Returns:
            List[PolicyLog]: 黑名单政策列表
        """
        # 直接标记的黑名单
        direct_blacklist = PolicyLog._default_manager.filter(
            is_blacklist=True,
            structured_data__affected_stocks__contains=asset_code
        )

        # 高风险宏观政策
        high_risk_macro = PolicyLog._default_manager.filter(
            info_category='macro',
            level__in=['P2', 'P3'],
            risk_impact='high_risk'
        )

        return list(direct_blacklist) + list(high_risk_macro)

    def _check_whitelist(self, asset_code: str) -> List[PolicyLog]:
        """
        检查白名单

        Args:
            asset_code: 资产代码

        Returns:
            List[PolicyLog]: 白名单政策列表
        """
        return list(PolicyLog._default_manager.filter(
            is_whitelist=True,
            structured_data__affected_stocks__contains=asset_code
        ))

    def _check_sector_influence(self, asset_code: str) -> List[PolicyLog]:
        """
        检查板块政策影响

        Args:
            asset_code: 资产代码

        Returns:
            List[PolicyLog]: 相关板块政策列表
        """
        # 获取资产所属板块
        sectors = self._sector_map.get(asset_code, [])

        if not sectors:
            return []

        # 查找影响这些板块的政策（30天内）
        cutoff_date = timezone.now() - timedelta(days=30)

        policies = PolicyLog._default_manager.filter(
            info_category='sector',
            audit_status__in=['auto_approved', 'manual_approved'],
            created_at__gte=cutoff_date
        )

        # 过滤出真正影响该板块的政策
        affected = []
        for policy in policies:
            policy_sectors = policy.structured_data.get('affected_sectors', [])
            if any(
                sector in policy_sectors or
                any(policy_sector in sector for sector in sectors)
                for policy_sector in policy_sectors
            ):
                affected.append(policy)

        return affected

    def _check_sentiment_influence(self, asset_code: str) -> List[PolicyLog]:
        """
        检查个股舆情影响

        Args:
            asset_code: 资产代码

        Returns:
            List[PolicyLog]: 个股舆情列表
        """
        # 7天内的个股舆情
        cutoff_date = timezone.now() - timedelta(days=7)

        return list(PolicyLog._default_manager.filter(
            info_category='individual',
            audit_status__in=['auto_approved', 'manual_approved'],
            structured_data__affected_stocks__contains=asset_code,
            created_at__gte=cutoff_date
        ))

    def _build_sector_mapping(self) -> Dict[str, List[str]]:
        """
        构建股票到板块的映射

        Returns:
            Dict: 股票代码到板块列表的映射
        """
        # 简化版本：硬编码一些示例
        # 实际应用中应该从数据库或配置文件获取
        return {
            '000001.SZ': ['银行', '金融'],
            '000002.SZ': ['房地产'],
            '600000.SH': ['银行', '金融'],
            '600036.SH': ['银行', '金融'],
            '000858.SZ': ['房地产'],
            '600519.SH': ['白酒', '消费'],
            '000333.SZ': ['家电', '消费'],
            '300750.SZ': ['新能源汽车', '电池'],
            '002594.SZ': ['新能源汽车'],
            '601318.SH': ['保险', '金融'],
            '601336.SH': ['保险', '金融'],
        }


def create_policy_influence_service() -> PolicyInfluenceService:
    """
    创建PolicyInfluenceService实例

    Returns:
        PolicyInfluenceService
    """
    return PolicyInfluenceService()

