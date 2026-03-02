"""
Unified Signal Service

Service to collect and aggregate signals from all modules (Regime, Factor, Rotation, Hedge, Alpha)
into a unified signal system.
"""

from datetime import date, timedelta
from typing import List, Dict, Any, Optional
import logging

from apps.signal.infrastructure.repositories import UnifiedSignalRepository
from apps.regime.application.current_regime import resolve_current_regime

logger = logging.getLogger(__name__)

# Optional imports for rotation, factor, hedge modules
try:
    from apps.rotation.infrastructure.services import RotationIntegrationService
    ROTATION_AVAILABLE = True
except ImportError:
    ROTATION_AVAILABLE = False
    RotationIntegrationService = None

try:
    from apps.factor.infrastructure.services import FactorIntegrationService
    FACTOR_AVAILABLE = True
except ImportError:
    FACTOR_AVAILABLE = False
    FactorIntegrationService = None

try:
    from apps.hedge.infrastructure.services import HedgeIntegrationService
    HEDGE_AVAILABLE = True
except ImportError:
    HEDGE_AVAILABLE = False
    HedgeIntegrationService = None


class UnifiedSignalService:
    """
    统一信号服务

    从所有模块收集信号并统一管理。
    """

    def __init__(self):
        self.unified_repo = UnifiedSignalRepository()
        self.rotation_service = RotationIntegrationService() if ROTATION_AVAILABLE else None
        self.factor_service = FactorIntegrationService() if FACTOR_AVAILABLE else None
        self.hedge_service = HedgeIntegrationService() if HEDGE_AVAILABLE else None
        # Alpha service - 延迟导入避免循环依赖
        self._alpha_service = None

    @property
    def alpha_service(self):
        """获取 Alpha 服务（延迟初始化）"""
        if self._alpha_service is None:
            try:
                from apps.alpha.application.services import AlphaService
                self._alpha_service = AlphaService()
            except ImportError:
                logger.warning("Alpha 模块不可用")
                self._alpha_service = False
        return self._alpha_service

    def _get_current_regime(self, calc_date: date) -> Optional[str]:
        """获取当前 Regime（可选功能）"""
        try:
            return resolve_current_regime(as_of_date=calc_date).dominant_regime
        except Exception as e:
            logger.warning(f"无法获取当前 Regime: {e}")
            return None

    def collect_all_signals(
        self,
        calc_date: date = None
    ) -> Dict[str, Any]:
        """
        收集所有模块的信号

        Args:
            calc_date: 计算日期（默认今天）

        Returns:
            收集结果统计
        """
        if calc_date is None:
            calc_date = date.today()

        results = {
            'regime_signals': 0,
            'rotation_signals': 0,
            'factor_signals': 0,
            'hedge_signals': 0,
            'alpha_signals': 0,
            'total_signals': 0,
            'errors': []
        }

        # 1. 收集 Regime 信号
        try:
            regime_signals = self._collect_regime_signals(calc_date)
            results['regime_signals'] = len(regime_signals)
        except Exception as e:
            logger.error(f"Error collecting regime signals: {e}")
            results['errors'].append(f"Regime: {str(e)}")

        # 2. 收集 Rotation 信号
        try:
            rotation_signals = self._collect_rotation_signals(calc_date)
            results['rotation_signals'] = len(rotation_signals)
        except Exception as e:
            logger.error(f"Error collecting rotation signals: {e}")
            results['errors'].append(f"Rotation: {str(e)}")

        # 3. 收集 Factor 信号
        try:
            factor_signals = self._collect_factor_signals(calc_date)
            results['factor_signals'] = len(factor_signals)
        except Exception as e:
            logger.error(f"Error collecting factor signals: {e}")
            results['errors'].append(f"Factor: {str(e)}")

        # 4. 收集 Hedge 信号
        try:
            hedge_signals = self._collect_hedge_signals(calc_date)
            results['hedge_signals'] = len(hedge_signals)
        except Exception as e:
            logger.error(f"Error collecting hedge signals: {e}")
            results['errors'].append(f"Hedge: {str(e)}")

        # 5. 收集 Alpha 信号
        try:
            alpha_signals = self._collect_alpha_signals(calc_date)
            results['alpha_signals'] = len(alpha_signals)
        except Exception as e:
            logger.error(f"Error collecting alpha signals: {e}")
            results['errors'].append(f"Alpha: {str(e)}")

        results['total_signals'] = (
            results['regime_signals'] +
            results['rotation_signals'] +
            results['factor_signals'] +
            results['hedge_signals'] +
            results['alpha_signals']
        )

        return results

    def _collect_regime_signals(self, calc_date: date) -> List[Dict]:
        """收集 Regime 模块信号"""
        signals = []

        try:
            regime = resolve_current_regime(as_of_date=calc_date)

            if regime and regime.dominant_regime and regime.dominant_regime != "Unknown":
                # 根据象限生成信号
                regime_type = regime.dominant_regime

                # Regime 变化信号
                signal = self.unified_repo.create_signal(
                    signal_date=calc_date,
                    signal_source='regime',
                    signal_type='info',
                    asset_code='MARKET',
                    asset_name='市场整体',
                    reason=f"当前宏观象限: {regime_type}",
                    priority=6,
                    action_required='根据象限调整资产配置',
                        extra_data={
                            'regime_type': regime_type,
                            'confidence': regime.confidence,
                            'source': regime.data_source,
                        }
                    )
                signals.append(signal)

                # 根据象限生成资产配置建议
                regime_allocations = self._get_regime_allocation(regime_type)
                for asset_code, allocation in regime_allocations.items():
                    signal = self.unified_repo.create_signal(
                        signal_date=calc_date,
                        signal_source='regime',
                        signal_type='rebalance',
                        asset_code=asset_code,
                        reason=f"象限 {regime_type} 建议配置 {allocation['name']}",
                        target_weight=allocation['weight'],
                        priority=5,
                        action_required=f'建议配置权重 {allocation["weight"]:.1%}',
                        extra_data={
                            'regime_type': regime_type,
                            'allocation_type': allocation['name'],
                        }
                    )
                    signals.append(signal)

        except Exception as e:
            logger.error(f"Error in _collect_regime_signals: {e}")

        return signals

    def _collect_rotation_signals(self, calc_date: date) -> List[Dict]:
        """收集 Rotation 模块信号"""
        signals = []

        try:
            # 获取轮动信号
            configs = self.rotation_service.get_all_configs()

            for config in configs:
                if not config.get('is_active'):
                    continue

                config_name = config['name']
                signal_result = self.rotation_service.generate_signal(config_name, calc_date)

                if signal_result and 'target_allocation' in signal_result:
                    target_allocation = signal_result['target_allocation']

                    # 为每个资产生成信号
                    for asset_code, weight in target_allocation.items():
                        signal = self.unified_repo.create_signal(
                            signal_date=calc_date,
                            signal_source='rotation',
                            signal_type='rebalance',
                            asset_code=asset_code,
                            reason=f"{config_name} 轮动信号",
                            target_weight=weight,
                            priority=5,
                            action_required=f'配置权重 {weight:.1%}',
                            extra_data={
                                'config_name': config_name,
                                'strategy_type': config.get('strategy_type'),
                            }
                        )
                        signals.append(signal)

        except Exception as e:
            logger.error(f"Error in _collect_rotation_signals: {e}")

        return signals

    def _collect_factor_signals(self, calc_date: date) -> List[Dict]:
        """收集 Factor 模块信号"""
        signals = []

        try:
            # 获取因子配置
            configs = self.factor_service.get_all_configs()

            for config in configs:
                config_name = config['name']

                # 创建因子组合
                portfolio = self.factor_service.create_factor_portfolio(config_name, calc_date)

                if portfolio and portfolio.get('holdings'):
                    holdings = portfolio['holdings']

                    # 生成前5大持仓信号
                    for i, holding in enumerate(holdings[:5]):
                        signal = self.unified_repo.create_signal(
                            signal_date=calc_date,
                            signal_source='factor',
                            signal_type='buy',
                            asset_code=holding['stock_code'],
                            asset_name=holding.get('stock_name', ''),
                            reason=f"{config_name} 第{i+1}大持仓，综合得分{holding.get('factor_score', 0):.2f}",
                            target_weight=holding['weight'] / 100,
                            priority=7 - i,  # 排名越前优先级越高
                            action_required=f'建议买入，权重{holding["weight"]:.2f}%',
                            extra_data={
                                'config_name': config_name,
                                'factor_score': holding.get('factor_score'),
                                'rank': holding.get('rank'),
                                'sector': holding.get('sector'),
                            }
                        )
                        signals.append(signal)

        except Exception as e:
            logger.error(f"Error in _collect_factor_signals: {e}")

        return signals

    def _collect_hedge_signals(self, calc_date: date) -> List[Dict]:
        """收集 Hedge 模块信号"""
        signals = []

        try:
            # 运行对冲监控
            alerts = self.hedge_service.monitor_hedge_pairs(calc_date)

            for alert in alerts:
                signal_type = 'alert' if alert.severity in ['high', 'critical'] else 'info'

                signal = self.unified_repo.create_signal(
                    signal_date=calc_date,
                    signal_source='hedge',
                    signal_type=signal_type,
                    asset_code=alert.pair_name,
                    reason=alert.message,
                    priority=alert.action_priority,
                    action_required=alert.action_required,
                    extra_data={
                        'alert_type': alert.alert_type.value,
                        'severity': alert.severity,
                        'current_value': alert.current_value,
                        'threshold_value': alert.threshold_value,
                    },
                    related_signal_id=f"hedge_alert_{alert.pair_name}_{calc_date}"
                )
                signals.append(signal)

            # 获取对冲有效性检查结果
            effectiveness_results = self.hedge_service.get_all_effectiveness(calc_date)

            for result in effectiveness_results:
                effectiveness = result.get('effectiveness', 0)
                pair_name = result.get('pair_name', '')

                # 低有效性告警
                if effectiveness < 0.4:
                    signal = self.unified_repo.create_signal(
                        signal_date=calc_date,
                        signal_source='hedge',
                        signal_type='alert',
                        asset_code=pair_name,
                        reason=f"对冲有效性较低 ({effectiveness:.2%}): {result.get('recommendation', '')}",
                        priority=7,
                        action_required=result.get('recommendation', ''),
                        extra_data={
                            'effectiveness': effectiveness,
                            'rating': result.get('rating'),
                            'correlation': result.get('correlation'),
                        }
                    )
                    signals.append(signal)

        except Exception as e:
            logger.error(f"Error in _collect_hedge_signals: {e}")

        return signals

    def _collect_alpha_signals(self, calc_date: date) -> List[Dict]:
        """收集 Alpha 模块信号"""
        signals = []

        try:
            # 检查 Alpha 服务是否可用
            if self.alpha_service is False:
                logger.debug("Alpha 服务不可用，跳过 Alpha 信号收集")
                return signals

            if self.alpha_service is None:
                return signals

            # 获取 Alpha 评分
            alpha_result = self.alpha_service.get_stock_scores(
                universe_id="csi300",
                intended_trade_date=calc_date,
                top_n=10
            )

            if not alpha_result.success or not alpha_result.scores:
                logger.warning(f"Alpha 评分获取失败或无数据: {alpha_result.error_message}")
                return signals

            # 为前 N 名股票生成买入信号
            for stock_score in alpha_result.scores[:10]:
                # 只对高分股票生成信号
                if stock_score.score >= 0.6:  # 阈值可配置
                    signal = self.unified_repo.create_signal(
                        signal_date=calc_date,
                        signal_source='alpha',
                        signal_type='buy',
                        asset_code=stock_score.code,
                        asset_name=stock_score.code,  # 可以通过 API 获取股票名称
                        reason=f"AI 选股排名第 {stock_score.rank}，综合评分 {stock_score.score:.3f}",
                        target_weight=None,  # 权重由策略层决定
                        priority=max(10 - stock_score.rank, 1),  # 排名越前优先级越高
                        action_required=f'建议关注，AI 评分 {stock_score.score:.3f}',
                        extra_data={
                            'score': stock_score.score,
                            'rank': stock_score.rank,
                            'confidence': stock_score.confidence,
                            'source': stock_score.source,
                            'factors': stock_score.factors,
                            'model_id': stock_score.model_id,
                            'model_artifact_hash': stock_score.model_artifact_hash,
                            'asof_date': stock_score.asof_date.isoformat() if stock_score.asof_date else None,
                            'universe_id': stock_score.universe_id,
                        }
                    )
                    signals.append(signal)

            # 如果 Alpha 数据源状态是 degraded，生成告警信号
            if alpha_result.status == "degraded":
                signal = self.unified_repo.create_signal(
                    signal_date=calc_date,
                    signal_source='alpha',
                    signal_type='alert',
                    asset_code='ALPHA_SYSTEM',
                    reason=f"Alpha 数据源状态降级: {alpha_result.source}",
                    priority=5,
                    action_required='检查 Qlib 系统状态',
                    extra_data={
                        'source': alpha_result.source,
                        'staleness_days': alpha_result.staleness_days,
                    }
                )
                signals.append(signal)

        except Exception as e:
            logger.error(f"Error in _collect_alpha_signals: {e}")

        return signals

    def _get_regime_allocation(self, regime_type: str) -> Dict[str, Dict]:
        """
        根据宏观象限获取建议配置

        Args:
            regime_type: 象限类型

        Returns:
            {asset_code: {weight, name}}
        """
        allocations = {
            'Recovery': {
                '510300': {'weight': 0.30, 'name': '沪深300'},
                '510500': {'weight': 0.20, 'name': '中证500'},
                '159985': {'weight': 0.15, 'name': '商品'},
                '511260': {'weight': 0.20, 'name': '国债'},
                '511880': {'weight': 0.15, 'name': '货币'},
            },
            'Overheat': {
                '511260': {'weight': 0.40, 'name': '国债'},
                '511880': {'weight': 0.30, 'name': '货币'},
                '159985': {'weight': 0.20, 'name': '商品'},
                '510300': {'weight': 0.10, 'name': '沪深300'},
            },
            'Stagflation': {
                '159985': {'weight': 0.25, 'name': '商品'},
                '511880': {'weight': 0.25, 'name': '货币'},
                '511260': {'weight': 0.25, 'name': '国债'},
                '518880': {'weight': 0.15, 'name': '黄金'},
                '510300': {'weight': 0.10, 'name': '沪深300'},
            },
            'Repression': {
                '511260': {'weight': 0.50, 'name': '国债'},
                '511880': {'weight': 0.30, 'name': '货币'},
                '510300': {'weight': 0.15, 'name': '沪深300'},
                '518880': {'weight': 0.05, 'name': '黄金'},
            },
        }

        return allocations.get(regime_type, {})

    def get_unified_signals(
        self,
        signal_date: date = None,
        signal_source: str = None,
        min_priority: int = 1
    ) -> List[Dict]:
        """
        获取统一信号列表

        Args:
            signal_date: 信号日期
            signal_source: 信号来源过滤
            min_priority: 最低优先级

        Returns:
            信号列表
        """
        if signal_date is None:
            signal_date = date.today()

        return self.unified_repo.get_signals_by_date(
            signal_date=signal_date,
            signal_source=signal_source
        )

    def get_signal_summary(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> Dict[str, Any]:
        """
        获取信号汇总

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            汇总信息
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=30)

        return self.unified_repo.get_signal_summary(start_date, end_date)
