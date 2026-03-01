"""
External Data Providers for Strategy Execution

Infrastructure层:
- 实现Domain层定义的Protocol接口
- 通过适配器模式集成现有系统
- 提供策略执行所需的外部数据
"""
import logging
from typing import List, Dict, Any, Optional

from django.db.models import Q, F
from django.utils import timezone

logger = logging.getLogger(__name__)


def _to_legacy_regime_code(regime_name: str) -> str:
    """Regime 英文全称 -> 历史四象限简码。"""
    mapping = {
        'Overheat': 'HG',
        'Recovery': 'HD',
        'Stagflation': 'LG',
        'Deflation': 'LD',
    }
    return mapping.get(regime_name, regime_name)


# ========================================================================
# Macro Data Provider
# ========================================================================

class DjangoMacroDataProvider:
    """
    Django ORM 实现的宏观数据提供者

    从 macro 应用获取宏观数据
    """

    def get_indicator(self, indicator_code: str) -> Optional[float]:
        """
        获取宏观指标值

        Args:
            indicator_code: 指标代码（如 CN_PMI_MANUFACTURING）

        Returns:
            指标值，如果不存在返回 None
        """
        try:
            from apps.macro.infrastructure.models import MacroIndicator

            indicator = MacroIndicator.objects.filter(
                code=indicator_code
            ).order_by('-reporting_period').first()

            if indicator:
                return float(indicator.value)

            return None

        except Exception as e:
            logger.error(f"Error getting macro indicator {indicator_code}: {e}")
            return None

    def get_all_indicators(self) -> Dict[str, float]:
        """
        获取所有宏观指标

        Returns:
            指标代码到值的映射
        """
        try:
            from apps.macro.infrastructure.models import MacroIndicator

            # 获取每个指标的最新值
            indicators = MacroIndicator.objects.all().values(
                'code'
            ).distinct()

            result = {}
            for ind in indicators:
                code = ind['code']
                latest = MacroIndicator.objects.filter(
                    code=code
                ).order_by('-reporting_period').first()
                if latest:
                    result[code] = float(latest.value)

            return result

        except Exception as e:
            logger.error(f"Error getting all macro indicators: {e}")
            return {}


# ========================================================================
# Regime Provider
# ========================================================================

class DjangoRegimeProvider:
    """
    Django ORM 实现的 Regime 提供者

    从 regime 应用获取当前 Regime 状态
    """

    def get_current_regime(self) -> Dict[str, Any]:
        """
        获取当前Regime状态

        Returns:
            Regime 状态字典
        """
        try:
            from apps.regime.infrastructure.models import RegimeLog

            # 获取最新的 Regime 状态
            latest_state = RegimeLog.objects.order_by('-observed_at').first()

            if latest_state:
                dominant_regime = latest_state.dominant_regime
                return {
                    # 统一使用 regime 模块的标准命名
                    'dominant_regime': dominant_regime,
                    # 保留历史简码字段，避免旧脚本/规则立即失效
                    'dominant_regime_code': _to_legacy_regime_code(dominant_regime),
                    'confidence': float(latest_state.confidence) if latest_state.confidence else 0.0,
                    'growth_momentum_z': float(latest_state.growth_momentum_z) if latest_state.growth_momentum_z else 0.0,
                    'inflation_momentum_z': float(latest_state.inflation_momentum_z) if latest_state.inflation_momentum_z else 0.0,
                    'date': latest_state.observed_at.isoformat() if latest_state.observed_at else None
                }

            # 返回默认值
            return {
                'dominant_regime': 'Recovery',
                'dominant_regime_code': 'HD',
                'confidence': 0.5,
                'growth_momentum_z': 0.0,
                'inflation_momentum_z': 0.0,
                'date': None
            }

        except Exception as e:
            logger.error(f"Error getting current regime: {e}")
            return {
                'dominant_regime': 'Recovery',
                'dominant_regime_code': 'HD',
                'confidence': 0.5,
                'growth_momentum_z': 0.0,
                'inflation_momentum_z': 0.0,
                'date': None
            }


# ========================================================================
# Asset Pool Provider
# ========================================================================

class DjangoAssetPoolProvider:
    """
    Django ORM 实现的资产池提供者

    从 asset_analysis 应用获取可投资产
    """

    def get_investable_assets(
        self,
        min_score: float = 60.0,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        获取可投资产列表

        Args:
            min_score: 最低评分
            limit: 返回数量限制

        Returns:
            资产列表
        """
        try:
            from apps.asset_analysis.infrastructure.models import AssetScoreCache

            # 获取评分高于阈值的资产
            assets = AssetScoreCache.objects.filter(
                total_score__gte=min_score
            ).order_by('-total_score')[:limit]

            result = []
            for asset in assets:
                result.append({
                    'asset_code': asset.asset_code,
                    'asset_name': asset.asset_name or asset.asset_code,
                    'total_score': float(asset.total_score) if asset.total_score else 0.0,
                    'regime_score': float(asset.regime_score) if asset.regime_score else 0.0,
                    'policy_score': float(asset.policy_score) if asset.policy_score else 0.0,
                    'asset_type': asset.asset_type or 'equity'
                })

            return result

        except Exception as e:
            logger.error(f"Error getting investable assets: {e}")
            return []


# ========================================================================
# Signal Provider
# ========================================================================

class DjangoSignalProvider:
    """
    Django ORM 实现的信号提供者

    从 signal 应用获取有效信号
    """

    def get_valid_signals(self) -> List[Dict[str, Any]]:
        """
        获取有效信号列表

        Returns:
            信号列表
        """
        try:
            from apps.signal.infrastructure.models import InvestmentSignalModel

            # 获取有效的投资信号
            signals = InvestmentSignalModel.objects.filter(
                is_valid=True
            ).order_by('-created_at')[:100]

            result = []
            for signal in signals:
                result.append({
                    'signal_id': signal.id,
                    'asset_code': signal.asset_code,
                    'direction': signal.direction,
                    'logic_desc': signal.logic_desc or '',
                    'target_regime': signal.target_regime or '',
                    'invalidation_logic': signal.invalidation_logic or '',
                    'created_at': signal.created_at.isoformat() if signal.created_at else None
                })

            return result

        except Exception as e:
            logger.error(f"Error getting valid signals: {e}")
            return []


# ========================================================================
# Portfolio Data Provider
# ========================================================================

class DjangoPortfolioDataProvider:
    """
    Django ORM 实现的投资组合数据提供者

    从 simulated_trading 应用获取投资组合数据
    """

    def get_positions(self, portfolio_id: int) -> List[Dict[str, Any]]:
        """
        获取投资组合持仓

        Args:
            portfolio_id: 投资组合ID

        Returns:
            持仓列表
        """
        try:
            from apps.simulated_trading.infrastructure.models import PositionModel

            positions = PositionModel.objects.filter(
                account_id=portfolio_id,
                quantity__gt=0  # 只返回有持仓的
            ).all()

            result = []
            for pos in positions:
                result.append({
                    'asset_code': pos.asset_code,
                    'asset_name': pos.asset_name or pos.asset_code,
                    'quantity': int(pos.quantity),
                    'avg_cost': float(pos.avg_cost) if pos.avg_cost else 0.0,
                    'current_price': float(pos.current_price) if pos.current_price else 0.0,
                    'market_value': float(pos.market_value) if pos.market_value else 0.0,
                    'asset_type': pos.asset_type or 'equity'
                })

            return result

        except Exception as e:
            logger.error(f"Error getting positions for portfolio {portfolio_id}: {e}")
            return []

    def get_cash(self, portfolio_id: int) -> float:
        """
        获取投资组合现金

        Args:
            portfolio_id: 投资组合ID

        Returns:
            现金余额
        """
        try:
            from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

            account = SimulatedAccountModel.objects.filter(
                id=portfolio_id
            ).first()

            if account:
                return float(account.current_cash) if account.current_cash else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting cash for portfolio {portfolio_id}: {e}")
            return 0.0
