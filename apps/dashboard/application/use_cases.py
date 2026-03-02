"""
Dashboard Application Use Cases

首页数据聚合用例。
"""

import logging
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

logger = logging.getLogger(__name__)


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

    # 资产配置建议（新增）
    allocation_advice: Optional[Dict] = None

    # 图表数据（用于前端渲染）
    allocation_data: Dict[str, float] = None  # 资产配置饼图数据
    performance_data: List[Dict] = None  # 收益趋势图数据

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
    regime_data_health: str = "unknown"
    regime_warnings: List[str] = None

    def __post_init__(self):
        if self.recent_policies is None:
            self.recent_policies = []
        if self.allocation_data is None:
            self.allocation_data = {}
        if self.performance_data is None:
            self.performance_data = []
        if self.regime_warnings is None:
            self.regime_warnings = []


class GetDashboardDataUseCase:
    """获取首页数据用例"""
    MAX_MACRO_STALENESS_DAYS = 45
    INDICATOR_STALENESS_DAYS = {
        "PMI": 70,
        "CPI": 70,
    }
    MIN_MACRO_POINTS = 12

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

        # 2. 实时计算当前Regime（使用 V2 水平法）
        # V2 水平法：基于 PMI/CPI 的绝对水平判定
        # - PMI >= 50 → 经济扩张
        # - CPI > 2% → 高通胀
        # 判定矩阵：Recovery (PMI>50, CPI<=2%), Overheat (PMI>50, CPI>2%),
        #          Stagflation (PMI<50, CPI>2%), Deflation (PMI<50, CPI<=2%)
        from apps.regime.application.use_cases import CalculateRegimeV2UseCase, CalculateRegimeV2Request
        from apps.macro.infrastructure.repositories import DjangoMacroRepository
        from apps.macro.infrastructure.models import DataSourceConfig

        macro_repo = DjangoMacroRepository()
        regime_use_case = CalculateRegimeV2UseCase(macro_repo)
        first_source = DataSourceConfig._default_manager.filter(is_active=True).order_by('priority').first()
        default_source = first_source.source_type if first_source else "akshare"

        regime_request = CalculateRegimeV2Request(
            as_of_date=date.today(),
            use_pit=True,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source=default_source,
        )

        regime_response = regime_use_case.execute(regime_request)
        health = self._assess_macro_data_health(
            growth_indicator="PMI",
            inflation_indicator="CPI",
            as_of_date=date.today(),
        )

        if regime_response.success and regime_response.result:
            current_regime = regime_response.result.regime.value
            regime_date = date.today()  # V2 返回结果中没有 observed_at
            regime_confidence = regime_response.result.confidence
            # V2 返回趋势指标而非动量 Z-score
            growth_momentum_z = 0.0
            inflation_momentum_z = 0.0
            regime_distribution = regime_response.result.distribution
            regime_data_health = "healthy" if health["is_healthy"] else "degraded"
            regime_warnings = list(health["warnings"])
        else:
            # 当本地未同步宏观数据时，回退到已落库的最新 Regime 快照，避免首页完全空白。
            latest_snapshot = self.regime_repo.get_latest_snapshot()
            if latest_snapshot:
                current_regime = latest_snapshot.dominant_regime
                regime_date = latest_snapshot.observed_at
                regime_confidence = latest_snapshot.confidence
                growth_momentum_z = latest_snapshot.growth_momentum_z
                inflation_momentum_z = latest_snapshot.inflation_momentum_z
                regime_distribution = latest_snapshot.distribution or {}
                regime_data_health = "fallback"
                regime_warnings = ["Regime 实时计算失败，已回退到历史快照"]
            else:
                current_regime = "Unknown"
                regime_date = date.today()
                regime_confidence = 0.0
                growth_momentum_z = 0.0
                inflation_momentum_z = 0.0
                regime_distribution = {}
                regime_data_health = "unavailable"
                regime_warnings = ["Regime 实时计算失败，且无可用历史快照"]

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

        # 10. 生成资产配置建议（新增）
        allocation_advice = self._generate_allocation_advice(
            current_regime=current_regime,
            policy_level=current_policy_level,
            profile=profile,
            total_assets=float(snapshot.total_value),
            positions=snapshot.positions,
        )

        # 11. 生成图表数据
        allocation_data = self._generate_allocation_chart_data(asset_allocation)
        performance_data = self._generate_performance_chart_data(portfolio_id)

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
            regime_data_health=regime_data_health,
            regime_warnings=regime_warnings,
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
            allocation_advice=allocation_advice,  # 新增
            current_policy_level=current_policy_level,
            current_policy_date=current_policy_date,
            pending_review_count=pending_review_count,
            recent_policies=recent_policies,
            allocation_data=allocation_data,
            performance_data=performance_data,
        )

    def _assess_macro_data_health(
        self,
        growth_indicator: str,
        inflation_indicator: str,
        as_of_date: date,
    ) -> Dict[str, object]:
        """评估 Regime 输入数据健康度（时效+完整性）。"""
        from apps.macro.infrastructure.repositories import DjangoMacroRepository

        repo = DjangoMacroRepository()
        warnings: List[str] = []

        growth_full = repo.get_growth_series_full(
            indicator_code=growth_indicator,
            end_date=as_of_date,
            use_pit=False,
        )
        inflation_full = repo.get_inflation_series_full(
            indicator_code=inflation_indicator,
            end_date=as_of_date,
            use_pit=False,
        )

        growth_points = len(growth_full)
        inflation_points = len(inflation_full)

        if growth_points < self.MIN_MACRO_POINTS:
            warnings.append(f"增长指标样本不足（{growth_points} 条）")
        if inflation_points < self.MIN_MACRO_POINTS:
            warnings.append(f"通胀指标样本不足（{inflation_points} 条）")

        if growth_full:
            growth_staleness = self._get_staleness_days(growth_full[-1], as_of_date)
            growth_threshold = self.INDICATOR_STALENESS_DAYS.get(
                growth_indicator,
                self.MAX_MACRO_STALENESS_DAYS,
            )
            if growth_staleness > growth_threshold:
                warnings.append(f"PMI 数据陈旧（距今 {growth_staleness} 天）")
        else:
            warnings.append("PMI 无可用数据")

        if inflation_full:
            inflation_staleness = self._get_staleness_days(inflation_full[-1], as_of_date)
            inflation_threshold = self.INDICATOR_STALENESS_DAYS.get(
                inflation_indicator,
                self.MAX_MACRO_STALENESS_DAYS,
            )
            if inflation_staleness > inflation_threshold:
                warnings.append(f"CPI 数据陈旧（距今 {inflation_staleness} 天）")
        else:
            warnings.append("CPI 无可用数据")

        return {
            "is_healthy": not warnings,
            "warnings": warnings,
        }

    @staticmethod
    def _get_staleness_days(indicator, as_of_date: date) -> int:
        """优先用 published_at 计算时效，缺失时回退 reporting_period。"""
        anchor_date = indicator.published_at or indicator.reporting_period
        return (as_of_date - anchor_date).days

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
        policy_level: str = None,
    ) -> List[str]:
        """调用 AI 生成投资建议"""
        import requests
        from django.conf import settings

        insights = []

        # 1. 准备 AI 请求的上下文信息
        context = {
            "current_regime": current_regime,
            "total_assets": float(snapshot.total_value),
            "total_return_pct": snapshot.total_return_pct,
            "invested_ratio": snapshot.get_invested_ratio(),
            "cash_ratio": 1 - snapshot.get_invested_ratio(),
            "regime_match_score": match_analysis.total_match_score,
            "position_count": len(snapshot.positions),
            "active_signal_count": len(active_signals),
            "policy_level": policy_level or "P0",
        }

        # 如果有敌对资产，添加到上下文
        if match_analysis.hostile_assets:
            context["hostile_assets"] = match_analysis.hostile_assets[:5]

        # 如果有活跃信号，添加信号信息
        if active_signals:
            context["recent_signals"] = [
                {"asset": s["asset_code"], "direction": s["direction"]}
                for s in active_signals[:3]
            ]

        # 2. 构建 AI 提示词
        prompt = f"""作为 AgomSAAF 投资助手，基于以下当前投资组合状态，给出 3-5 条简洁的投资建议（每条不超过30字）：

【宏观环境】
- 当前 Regime: {current_regime}
- 政策档位: {policy_level or 'P0'}
- Regime 匹配度: {match_analysis.total_match_score:.0f} 分

【资产组合】
- 总资产: ¥{snapshot.total_value:,.0f}
- 收益率: {snapshot.total_return_pct:+.2f}%
- 仓位比例: {snapshot.get_invested_ratio()*100:.0f}% 股票 / { (1-snapshot.get_invested_ratio())*100:.0f}% 现金
- 持仓数量: {len(snapshot.positions)} 个
- 活跃信号: {len(active_signals)} 个

{f"【不匹配资产】{', '.join(match_analysis.hostile_assets[:3])}" if match_analysis.hostile_assets else ""}

请给出 3-5 条具体、可操作的投资建议，每条建议单独一行，不要太长。"""

        # 3. 调用 AI API
        try:
            # 获取 AI 提供商配置
            from apps.prompt.infrastructure.models import AIProvider

            provider = AIProvider._default_manager.filter(is_active=True).first()

            if not provider:
                # 如果没有配置 AI，使用数据库规则作为后备
                return self._enhanced_fallback_insights(
                    current_regime, snapshot, match_analysis, active_signals, policy_level
                )

            # 构建 API 请求
            api_url = provider.get_api_url()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {provider.api_key}"
            }

            # 根据不同的提供商调整请求格式
            if provider.provider_type == 'openai':
                payload = {
                    "model": provider.model_name,
                    "messages": [
                        {"role": "system", "content": "你是 AgomSAAF 投资助手，给出简洁具体的投资建议。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500
                }
            elif provider.provider_type == 'deepseek':
                payload = {
                    "model": provider.model_name,
                    "messages": [
                        {"role": "system", "content": "你是 AgomSAAF 投资助手，给出简洁具体的投资建议。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500
                }
            else:  # 通用格式
                payload = {
                    "model": provider.model_name,
                    "messages": [
                        {"role": "system", "content": "你是 AgomSAAF 投资助手，给出简洁具体的投资建议。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500
                }

            # 发送请求
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                # 解析响应
                if provider.provider_type in ['openai', 'deepseek', 'qwen']:
                    content = data['choices'][0]['message']['content']
                else:
                    content = str(data)

                # 分割建议（按行）
                lines = [line.strip() for line in content.split('\n') if line.strip()]

                # 清理和限制建议数量
                insights = []
                for line in lines:
                    # 移除序号、符号等
                    line = line.lstrip('0123456789.-*•、 ')
                    line = line.lstrip('【').rstrip('】')
                    if len(line) > 5 and len(line) < 100:  # 过滤太短或太长的
                        insights.append(line)
                    if len(insights) >= 5:  # 最多 5 条
                        break

                if insights:
                    return insights

        except Exception as e:
            # AI 调用失败，使用增强后备方案
            logger.warning(f"AI 调用失败: {e}，使用增强数据库规则")

        # 后备方案：使用增强数据库规则
        return self._enhanced_fallback_insights(
            current_regime, snapshot, match_analysis, active_signals, policy_level
        )

    def _enhanced_fallback_insights(
        self,
        current_regime: str,
        snapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: List[Dict],
        policy_level: str = None,
    ) -> List[str]:
        """
        从数据库规则生成投资建议（AI 失败时的增强后备方案）

        易用性改进 - AI助手降级增强：
        - 支持Regime+Policy组合规则
        - 支持匹配度+仓位组合规则
        - 支持多层规则优先级
        - 永不空白，至少返回静态建议
        """
        from apps.account.infrastructure.models import InvestmentRuleModel

        insights = []
        invested_ratio = snapshot.get_invested_ratio()
        match_score = match_analysis.total_match_score

        # Policy档位转换为数字（用于比较）
        policy_level_num = self._policy_to_numeric(policy_level or "P0")

        # 获取所有启用的全局规则
        all_rules = InvestmentRuleModel._default_manager.filter(
            is_active=True,
            user__isnull=True  # 全局规则
        ).order_by('priority', 'id')

        # ==================== Level 1: 组合规则（最高优先级） ====================

        # 1. Regime + Policy 组合规则
        combo_rules = all_rules.filter(rule_type='regime_policy_combo')
        for rule in combo_rules:
            conditions = rule.conditions
            if conditions.get('regime') == current_regime:
                min_policy = conditions.get('min_policy_level', 0)
                if policy_level_num >= min_policy:
                    advice = rule.advice_template.format(
                        regime=current_regime,
                        policy_level=policy_level or "P0",
                        match_score=f"{match_score:.0f}",
                        invested_ratio=f"{invested_ratio*100:.0f}%",
                    )
                    insights.append(advice)
                    break  # 只取第一个匹配的

        # 2. 匹配度 + 仓位 组合规则
        if not insights:  # 只在前面没有匹配时检查
            match_pos_rules = all_rules.filter(rule_type='match_position_combo')
            for rule in match_pos_rules:
                conditions = rule.conditions
                max_match = conditions.get('max_match_score', 100)
                min_invested = conditions.get('min_invested_ratio', 0)
                max_invested = conditions.get('max_invested_ratio', 1)

                if match_score <= max_match and min_invested <= invested_ratio <= max_invested:
                    advice = rule.advice_template.format(
                        match_score=f"{match_score:.0f}",
                        invested_ratio=f"{invested_ratio*100:.0f}%",
                    )
                    insights.append(advice)
                    break

        # 3. Regime + 仓位 组合规则
        if not insights:
            regime_pos_rules = all_rules.filter(rule_type='regime_position_combo')
            for rule in regime_pos_rules:
                conditions = rule.conditions
                if conditions.get('regime') == current_regime:
                    min_invested = conditions.get('min_invested_ratio', 0)
                    max_invested = conditions.get('max_invested_ratio', 1)
                    if min_invested <= invested_ratio <= max_invested:
                        advice = rule.advice_template.format(
                            regime=current_regime,
                            invested_ratio=f"{invested_ratio*100:.0f}%",
                        )
                        insights.append(advice)
                        break

        # ==================== Level 2: 单维度规则 ====================

        # 4. Regime环境建议
        if len(insights) < 3:  # 限制建议数量
            regime_rules = all_rules.filter(rule_type='regime_advice')
            for rule in regime_rules:
                conditions = rule.conditions
                if conditions.get('regime') == current_regime:
                    advice = rule.advice_template.format(
                        regime=current_regime,
                        growth_direction="↑" if current_regime in ['Recovery', 'Overheat'] else "↓",
                        inflation_direction="↑" if current_regime in ['Overheat', 'Stagflation'] else "↓",
                    )
                    insights.append(advice)
                    break

        # 5. Policy档位建议
        if len(insights) < 3:
            policy_rules = all_rules.filter(rule_type='policy_advice')
            for rule in policy_rules:
                conditions = rule.conditions
                min_policy = conditions.get('min_policy_level', 0)
                max_policy = conditions.get('max_policy_level', 3)
                if min_policy <= policy_level_num <= max_policy:
                    advice = rule.advice_template.format(
                        policy_level=policy_level or "P0",
                    )
                    insights.append(advice)
                    break

        # 6. 仓位建议
        if len(insights) < 3:
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
                    break

        # 7. 匹配度建议
        if len(insights) < 3:
            match_rules = all_rules.filter(rule_type='match_advice')
            for rule in match_rules:
                conditions = rule.conditions
                min_match = conditions.get('min_match_score', 0)
                max_match = conditions.get('max_match_score', 100)
                if min_match <= match_score <= max_match:
                    advice = rule.advice_template.format(
                        match_score=f"{match_score:.0f}",
                    )
                    insights.append(advice)
                    break

            # 如果有敌对资产，添加额外提示
            if match_analysis.hostile_assets and match_score < 50:
                hostile_codes = [a.split()[0] for a in match_analysis.hostile_assets[:3]]
                insights.append(f"建议关注: {', '.join(hostile_codes)} 与当前环境不匹配")

        # 8. 信号建议
        if len(insights) < 3:
            signal_rules = all_rules.filter(rule_type='signal_advice')
            for rule in signal_rules:
                conditions = rule.conditions
                min_count = conditions.get('min_signal_count', 0)
                has_active = conditions.get('has_active_signals', True)

                match = False
                if has_active and len(active_signals) >= min_count:
                    match = True
                elif not has_active and len(active_signals) == 0:
                    match = True

                if match:
                    advice = rule.advice_template.format(
                        signal_count=len(active_signals),
                    )
                    insights.append(advice)
                    break

        # 9. 风险提示
        if len(insights) < 3:
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
                    break

        # ==================== Level 3: 静态保底规则（永不空白） ====================

        if len(insights) < 2:
            static_rules = all_rules.filter(rule_type='static_advice')
            for rule in static_rules:
                insights.append(rule.advice_template)
                if len(insights) >= 2:
                    break

        # 确保至少有一条建议
        if not insights:
            insights.append("定期查看持仓与Regime的匹配度，关注市场变化")

        return insights[:5]  # 最多返回5条建议

    def _policy_to_numeric(self, policy_level: str) -> int:
        """将Policy档位转换为数字"""
        policy_map = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return policy_map.get(policy_level, 0)

    def _fallback_insights(
        self,
        current_regime: str,
        snapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: List[Dict],
    ) -> List[str]:
        """从数据库规则生成投资建议（AI 失败时的后备方案）- 保留兼容性"""
        return self._enhanced_fallback_insights(
            current_regime, snapshot, match_analysis, active_signals, None
        )

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
            pmi_value = float(pmi_series[-1]) if pmi_series else None
        except Exception:
            pmi_value = None

        # 获取最新 CPI
        try:
            cpi_series = macro_repo.get_inflation_series(
                indicator_code="CPI",
                end_date=date.today(),
                use_pit=False
            )
            cpi_value = float(cpi_series[-1]) if cpi_series else None
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
            pending_review_count = PolicyAuditQueue._default_manager.filter(
                assigned_to__user_id=user_id,
                status__in=['pending', 'in_progress']
            ).count()
        except Exception:
            pass

        # 获取最近政策（7天内已审核通过的）
        recent_policies = []
        try:
            recent_logs = PolicyLog._default_manager.filter(
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

    def _generate_allocation_advice(
        self,
        current_regime: str,
        policy_level: str,
        profile,
        total_assets: float,
        positions,
    ) -> Optional[Dict]:
        """生成资产配置建议"""
        try:
            from apps.strategy.application.allocation_service import AllocationService

            # 获取用户风险偏好
            risk_profile = profile.risk_tolerance  # conservative/moderate/aggressive

            # 调用AllocationService计算建议
            advice = AllocationService.calculate_allocation_advice(
                current_regime=current_regime,
                risk_profile=risk_profile,
                policy_level=policy_level,
                total_assets=total_assets,
                positions=positions,
            )

            # 转换为字典格式
            return {
                "current_allocation": advice.current_allocation,
                "target_allocation": advice.target_allocation,
                "allocation_diff": advice.allocation_diff,
                "trade_actions": [
                    {
                        "asset_code": a.asset_code,
                        "asset_name": a.asset_name,
                        "action": a.action,
                        "amount": round(a.amount, 2),
                        "reason": a.reason,
                        "asset_class": a.asset_class,
                        "asset_class_display": self._get_asset_class_display(a.asset_class),
                        "priority": a.priority,
                    }
                    for a in advice.trade_actions
                ],
                "summary": advice.summary,
                "expected_return": advice.expected_return,
                "expected_volatility": advice.expected_volatility,
                "sharpe_ratio": advice.sharpe_ratio,
                "regime": advice.regime,
                "risk_profile_display": profile.get_risk_tolerance_display(),
            }
        except Exception as e:
            logger.warning(f"生成资产配置建议失败: {e}")
            return None

    def _generate_allocation_chart_data(self, asset_allocation: List[Dict]) -> Dict[str, float]:
        """
        生成资产配置图表数据

        Args:
            asset_allocation: 资产配置列表

        Returns:
            Dict[str, float]: {"股票": 100000, "债券": 50000, ...}
        """
        allocation_chart_data = {}
        for alloc in asset_allocation:
            dimension_display = alloc.get('dimension_display', alloc.get('dimension_value', 'Unknown'))
            market_value = alloc.get('market_value', 0)
            allocation_chart_data[dimension_display] = market_value
        return allocation_chart_data

    def _generate_performance_chart_data(
        self,
        portfolio_id: int,
        days: int = 30
    ) -> List[Dict]:
        """
        生成收益趋势图表数据

        Args:
            portfolio_id: 投资组合ID
            days: 获取最近N天的数据

        Returns:
            List[Dict]: [{"date": "2026-01-01", "return_pct": 5.2}, ...]

        Note: 当前版本暂不支持历史快照，返回空列表
              前端会显示"暂无收益数据"的占位提示
        """
        # 暂时返回空列表，等待历史快照功能实现
        # TODO: 实现历史快照存储后，从数据库读取历史收益数据
        return []

