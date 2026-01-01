"""
Dashboard Application Use Cases

首页数据聚合用例。
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import date, datetime

from apps.account.domain.entities import (
    Position,
    RegimeMatchAnalysis,
    AssetAllocation,
)
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@dataclass
class DashboardData:
    """首页数据DTO"""
    # 用户信息
    user_id: int
    username: str
    display_name: str

    # 宏观环境
    current_regime: str
    regime_date: date
    regime_confidence: float

    # 资产总览
    total_assets: float
    initial_capital: float
    total_return: float
    total_return_pct: float
    cash_balance: float
    invested_value: float
    invested_ratio: float

    # 持仓分析
    positions: List[Dict]
    position_count: int
    regime_match_score: float
    regime_recommendations: List[str]

    # 投资信号
    active_signals: List[Dict]
    signal_stats: Dict[str, int]

    # 资产配置
    asset_allocation: List[Dict]

    # AI建议
    ai_insights: List[str]

    # 有默认值的字段放最后
    # 政策环境（新增）
    current_policy_level: str = None
    current_policy_date: date = None
    pending_review_count: int = 0
    recent_policies: List[Dict] = None
    # 宏观环境额外数据
    growth_momentum_z: float = 0.0
    inflation_momentum_z: float = 0.0
    regime_distribution: dict = None
    pmi_value: float = None
    cpi_value: float = None

    def __post_init__(self):
        if self.recent_policies is None:
            self.recent_policies = []


class GetDashboardDataUseCase:
    """获取首页数据用例"""

    def __init__(
        self,
        account_repo: AccountRepository,
        portfolio_repo: PortfolioRepository,
        position_repo: PositionRepository,
        regime_repo: DjangoRegimeRepository,
        signal_repo: DjangoSignalRepository,
    ):
        self.account_repo = account_repo
        self.portfolio_repo = portfolio_repo
        self.position_repo = position_repo
        self.regime_repo = regime_repo
        self.signal_repo = signal_repo

    def execute(self, user_id: int) -> DashboardData:
        """
        获取首页所有数据

        聚合数据来源：
        1. 用户账户配置
        2. 当前Regime状态（公共数据）
        3. 投资组合快照
        4. 持仓列表及Regime匹配度
        5. 投资信号统计
        6. AI建议生成
        """
        # 1. 获取用户配置，如果不存在则自动创建
        profile = self.account_repo.get_by_user_id(user_id)
        if not profile:
            # 自动创建默认账户配置
            profile = self.account_repo.create_default_profile(user_id)

        # 2. 实时计算当前Regime（与/regime/dashboard/保持一致）
        from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
        from apps.macro.infrastructure.repositories import DjangoMacroRepository

        macro_repo = DjangoMacroRepository()
        regime_use_case = CalculateRegimeUseCase(macro_repo)

        regime_request = CalculateRegimeRequest(
            as_of_date=date.today(),
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        regime_response = regime_use_case.execute(regime_request)

        if regime_response.success and regime_response.snapshot:
            current_regime = regime_response.snapshot.dominant_regime
            regime_date = regime_response.snapshot.observed_at
            regime_confidence = regime_response.snapshot.confidence
            growth_momentum_z = regime_response.snapshot.growth_momentum_z
            inflation_momentum_z = regime_response.snapshot.inflation_momentum_z
            regime_distribution = regime_response.snapshot.distribution
        else:
            current_regime = "Unknown"
            regime_date = date.today()
            regime_confidence = 0.0
            growth_momentum_z = 0.0
            inflation_momentum_z = 0.0
            regime_distribution = {}

        # 获取最新的 PMI 和 CPI 值
        pmi_value, cpi_value = self._get_latest_macro_values()

        # 3. 获取投资组合快照
        portfolio_id = self.account_repo.get_or_create_default_portfolio(user_id)
        snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)

        # 4. 获取持仓列表（转换为字典格式）
        positions_dict = self._format_positions(snapshot.positions)

        # 5. 计算Regime匹配度
        from apps.account.domain.services import PositionService
        match_analysis = PositionService.calculate_regime_match_score(
            positions=snapshot.positions,
            current_regime=current_regime,
        )

        # 6. 获取投资信号
        active_signals = self._get_user_signals(user_id)
        signal_stats = self._calculate_signal_stats(user_id)

        # 7. 资产配置分布
        asset_allocation = self._format_asset_allocation(snapshot.positions)

        # 8. 生成AI建议
        ai_insights = self._generate_ai_insights(
            current_regime=current_regime,
            snapshot=snapshot,
            match_analysis=match_analysis,
            active_signals=active_signals,
        )

        # 9. 获取政策环境信息
        current_policy_level, current_policy_date, pending_review_count, recent_policies = \
            self._get_policy_environment(user_id)

        return DashboardData(
            user_id=user_id,
            username="",  # 由视图层填充
            display_name=profile.display_name,
            current_regime=current_regime,
            regime_date=regime_date,
            regime_confidence=regime_confidence,
            growth_momentum_z=growth_momentum_z,
            inflation_momentum_z=inflation_momentum_z,
            regime_distribution=regime_distribution,
            pmi_value=pmi_value,
            cpi_value=cpi_value,
            total_assets=float(snapshot.total_value),
            initial_capital=float(profile.initial_capital),
            total_return=float(snapshot.total_return),
            total_return_pct=snapshot.total_return_pct,
            cash_balance=float(snapshot.cash_balance),
            invested_value=float(snapshot.invested_value),
            invested_ratio=snapshot.get_invested_ratio(),
            positions=positions_dict,
            position_count=len(snapshot.positions),
            regime_match_score=match_analysis.total_match_score,
            regime_recommendations=match_analysis.recommendations,
            active_signals=active_signals,
            signal_stats=signal_stats,
            asset_allocation=asset_allocation,
            ai_insights=ai_insights,
            current_policy_level=current_policy_level,
            current_policy_date=current_policy_date,
            pending_review_count=pending_review_count,
            recent_policies=recent_policies,
        )

    def _format_positions(self, positions: List[Position]) -> List[Dict]:
        """格式化持仓数据为字典"""
        return [
            {
                "id": p.id,
                "asset_code": p.asset_code,
                "asset_class": p.asset_class.value,
                "asset_class_display": self._get_asset_class_display(p.asset_class.value),
                "region": p.region.value,
                "region_display": self._get_region_display(p.region.value),
                "shares": p.shares,
                "avg_cost": float(p.avg_cost),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pnl": float(p.unrealized_pnl),
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "opened_at": p.opened_at.strftime("%Y-%m-%d"),
            }
            for p in positions
        ]

    def _get_asset_class_display(self, value: str) -> str:
        """获取资产大类显示名称"""
        display_map = {
            "equity": "股票",
            "fixed_income": "债券",
            "commodity": "商品",
            "currency": "外汇",
            "cash": "现金",
            "fund": "基金",
            "derivative": "衍生品",
            "other": "其他",
        }
        return display_map.get(value, value)

    def _get_region_display(self, value: str) -> str:
        """获取地区显示名称"""
        display_map = {
            "CN": "中国",
            "US": "美国",
            "EU": "欧洲",
            "JP": "日本",
            "EM": "新兴市场",
            "GLOBAL": "全球",
            "OTHER": "其他",
        }
        return display_map.get(value, value)

    def _get_user_signals(self, user_id: int, limit: int = 5) -> List[Dict]:
        """获取用户活跃信号"""
        signals = self.signal_repo.get_user_signals(
            user_id=user_id,
            status="approved",
            limit=limit,
        )
        return [
            {
                "id": s.id,
                "asset_code": s.asset_code,
                "direction": s.direction,
                "status": s.status,
                "logic_desc": s.logic_desc[:100] + "..." if len(s.logic_desc) > 100 else s.logic_desc,
                "created_at": s.created_at.strftime("%Y-%m-%d"),
            }
            for s in signals
        ]

    def _calculate_signal_stats(self, user_id: int) -> Dict[str, int]:
        """计算信号统计"""
        all_signals = self.signal_repo.get_user_signals(user_id)
        return {
            "total": len(all_signals),
            "approved": len([s for s in all_signals if s.status == "approved"]),
            "pending": len([s for s in all_signals if s.status == "pending"]),
            "rejected": len([s for s in all_signals if s.status == "rejected"]),
        }

    def _format_asset_allocation(self, positions: List[Position]) -> List[Dict]:
        """格式化资产配置"""
        from apps.account.domain.services import PositionService

        allocations = PositionService.calculate_asset_allocation(positions, "asset_class")
        return [
            {
                "dimension": "asset_class",
                "dimension_value": a.dimension_value,
                "dimension_display": self._get_asset_class_display(a.dimension_value),
                "count": a.count,
                "market_value": float(a.market_value),
                "percentage": round(a.percentage, 1),
            }
            for a in allocations
        ]

    def _generate_ai_insights(
        self,
        current_regime: str,
        snapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: List[Dict],
    ) -> List[str]:
        """从数据库规则生成投资建议"""
        from apps.account.infrastructure.models import InvestmentRuleModel

        insights = []
        invested_ratio = snapshot.get_invested_ratio()

        # 获取所有启用的规则
        all_rules = InvestmentRuleModel.objects.filter(is_active=True).order_by('priority', 'id')

        # 1. Regime环境建议
        regime_rules = all_rules.filter(rule_type='regime_advice')
        for rule in regime_rules:
            conditions = rule.conditions
            # 检查regime条件
            if conditions.get('regime') == current_regime:
                # 替换模板变量
                advice = rule.advice_template.format(
                    regime=current_regime,
                    growth_direction="↑" if current_regime in ['Recovery', 'Overheat'] else "↓",
                    inflation_direction="↑" if current_regime in ['Overheat', 'Stagflation'] else "↓",
                )
                insights.append(advice)

        # 如果没有匹配的Regime规则，添加默认说明
        if not any(r for r in insights if "象限" in r):
            insights.append(f"当前处于【{current_regime}】象限")

        # 2. 仓位建议
        position_rules = all_rules.filter(rule_type='position_advice')
        for rule in position_rules:
            conditions = rule.conditions
            min_invested = conditions.get('min_invested_ratio', 0)
            max_invested = conditions.get('max_invested_ratio', 1)

            if min_invested <= invested_ratio <= max_invested:
                advice = rule.advice_template.format(
                    invested_ratio=f"{invested_ratio*100:.0f}%",
                    cash_ratio=f"{(1-invested_ratio)*100:.0f}%",
                )
                insights.append(advice)

        # 3. Regime匹配度建议
        match_rules = all_rules.filter(rule_type='match_advice')
        for rule in match_rules:
            conditions = rule.conditions
            max_match_score = conditions.get('max_match_score', 100)

            if match_analysis.total_match_score <= max_match_score:
                advice = rule.advice_template.format(
                    match_score=f"{match_analysis.total_match_score:.0f}",
                )
                insights.append(advice)

                # 如果有敌对资产，添加建议
                if match_analysis.hostile_assets:
                    hostile_codes = [a.split()[0] for a in match_analysis.hostile_assets[:3]]
                    insights.append(f"建议关注: {', '.join(hostile_codes)} 与当前环境不匹配")

        # 4. 信号建议
        signal_rules = all_rules.filter(rule_type='signal_advice')
        for rule in signal_rules:
            conditions = rule.conditions
            has_active = conditions.get('has_active_signals', True)

            if (active_signals and has_active) or (not active_signals and not has_active):
                advice = rule.advice_template.format(
                    signal_count=len(active_signals),
                )
                insights.append(advice)

        # 5. 风险提示
        risk_rules = all_rules.filter(rule_type='risk_alert')
        for rule in risk_rules:
            conditions = rule.conditions
            min_return = conditions.get('min_return_pct', -100)
            max_return = conditions.get('max_return_pct', 100)

            if min_return <= snapshot.total_return_pct <= max_return:
                advice = rule.advice_template.format(
                    return_pct=f"{snapshot.total_return_pct:.0f}",
                )
                insights.append(advice)

        # 如果没有任何建议，返回默认提示
        if not insights:
            insights.append("暂无特殊建议，请关注市场变化")

        return insights

    def _get_latest_macro_values(self) -> tuple:
        """获取最新的 PMI 和 CPI 值"""
        from apps.macro.infrastructure.repositories import DjangoMacroRepository

        macro_repo = DjangoMacroRepository()

        # 获取最新 PMI
        try:
            pmi_series = macro_repo.get_growth_series(
                indicator_code="PMI",
                end_date=date.today(),
                use_pit=False
            )
            pmi_value = float(pmi_series[-1].value) if pmi_series else None
        except Exception:
            pmi_value = None

        # 获取最新 CPI
        try:
            cpi_series = macro_repo.get_inflation_series(
                indicator_code="CPI",
                end_date=date.today(),
                use_pit=False
            )
            cpi_value = float(cpi_series[-1].value) if cpi_series else None
        except Exception:
            cpi_value = None

        return pmi_value, cpi_value

    def _get_policy_environment(self, user_id: int) -> tuple:
        """获取政策环境信息"""
        from apps.policy.infrastructure.repositories import DjangoPolicyRepository
        from apps.policy.infrastructure.models import PolicyLog, PolicyAuditQueue
        from django.utils import timezone
        from datetime import timedelta

        # 获取当前政策档位
        policy_repo = DjangoPolicyRepository()
        current_policy_level = None
        current_policy_date = None

        try:
            latest_event = policy_repo.get_latest_event()
            if latest_event:
                current_policy_level = latest_event.level.value
                current_policy_date = latest_event.event_date
        except Exception:
            pass  # 政策信息获取失败不影响其他功能

        # 获取待审核数量（分配给当前用户的）
        pending_review_count = 0
        try:
            pending_review_count = PolicyAuditQueue.objects.filter(
                assigned_to__user_id=user_id,
                status__in=['pending', 'in_progress']
            ).count()
        except Exception:
            pass

        # 获取最近政策（7天内已审核通过的）
        recent_policies = []
        try:
            recent_logs = PolicyLog.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7),
                audit_status__in=['auto_approved', 'manual_approved']
            ).order_by('-created_at')[:5]

            for p in recent_logs:
                recent_policies.append({
                    'id': p.id,
                    'title': p.title,
                    'level': p.level,
                    'level_display': p.get_level_display(),
                    'category': p.info_category,
                    'category_display': p.get_info_category_display(),
                    'created_at': p.created_at.strftime("%Y-%m-%d %H:%M"),
                })
        except Exception:
            pass

        return current_policy_level, current_policy_date, pending_review_count, recent_policies
