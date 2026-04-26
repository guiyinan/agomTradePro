"""
External Data Providers for Strategy Execution

Infrastructure层:
- 实现Domain层定义的Protocol接口
- 通过适配器模式集成现有系统
- 提供策略执行所需的外部数据
"""
import logging
from typing import Any, Dict, List, Optional

from django.db.models import F, Q
from django.utils import timezone
from core.integration.simulated_trading_facade import (
    get_simulated_trading_facade_bridge,
)
from apps.strategy.infrastructure.repositories import (
    DjangoStrategyExecutionLogRepository,
    DjangoStrategyRepository,
    StrategyInterfaceRepository,
)

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

    def get_indicator(self, indicator_code: str) -> float | None:
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

    def get_all_indicators(self) -> dict[str, float]:
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

    def get_current_regime(self) -> dict[str, Any]:
        """
        获取当前Regime状态

        Returns:
            Regime 状态字典
        """
        try:
            from apps.regime.application.current_regime import resolve_current_regime
            latest_state = resolve_current_regime()
            if latest_state:
                dominant_regime = latest_state.dominant_regime
                return {
                    'dominant_regime': dominant_regime,
                    'dominant_regime_code': _to_legacy_regime_code(dominant_regime),
                    'confidence': float(latest_state.confidence) if latest_state.confidence else 0.0,
                    'growth_momentum_z': 0.0,
                    'inflation_momentum_z': 0.0,
                    'date': latest_state.observed_at.isoformat() if latest_state.observed_at else None,
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
    ) -> list[dict[str, Any]]:
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

    def get_valid_signals(self) -> list[dict[str, Any]]:
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

    重构说明 (2026-03-11):
    - 改为使用 SimulatedTradingFacade
    - 移除对 PositionModel 和 SimulatedAccountModel 的直接导入
    """

    def __init__(self):
        # 凶迟导入 Facade 避免 circular dependency
        self._facade = None

    def _get_facade(self):
        """延迟获取 Facade 实例"""
        if self._facade is None:
            self._facade = get_simulated_trading_facade_bridge()
        return self._facade

    def get_positions(self, portfolio_id: int) -> list[dict[str, Any]]:
        """
        获取投资组合持仓

        Args:
            portfolio_id: 投资组合ID

        Returns:
            持仓列表
        """
        try:
            facade = self._get_facade()
            position_summaries = facade.get_positions(portfolio_id)

            result = []
            for pos in position_summaries:
                result.append({
                    'asset_code': pos.asset_code,
                    'asset_name': pos.asset_name,
                    'quantity': pos.quantity,
                    'avg_cost': float(pos.avg_cost),
                    'current_price': float(pos.current_price),
                    'market_value': float(pos.market_value),
                    'asset_type': pos.asset_type
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
            facade = self._get_facade()
            cash = facade.get_cash(portfolio_id)
            return float(cash)

        except Exception as e:
            logger.error(f"Error getting cash for portfolio {portfolio_id}: {e}")
            return 0.0


class DjangoAssetNameResolver:
    """Django ORM 实现的资产名称解析器。"""

    def resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        code_set = {code for code in codes if code}
        if not code_set:
            return {}

        resolved: dict[str, str] = {}

        try:
            from apps.equity.infrastructure.models import StockInfoModel

            stock_rows = StockInfoModel._default_manager.filter(
                stock_code__in=list(code_set)
            ).values("stock_code", "name")
            for row in stock_rows:
                resolved[row["stock_code"]] = row["name"]
        except Exception as e:
            logger.warning("Failed to resolve stock names: %s", e)

        unresolved = [code for code in code_set if code not in resolved]
        if not unresolved:
            return resolved

        try:
            from apps.fund.infrastructure.models import FundInfoModel

            code_to_fund_code = {code: code.split(".")[0] for code in unresolved}
            fund_rows = FundInfoModel._default_manager.filter(
                fund_code__in=list(set(code_to_fund_code.values()))
            ).values("fund_code", "fund_name")
            fund_name_map = {row["fund_code"]: row["fund_name"] for row in fund_rows}
            for code, fund_code in code_to_fund_code.items():
                if fund_code in fund_name_map:
                    resolved[code] = fund_name_map[fund_code]
        except Exception as e:
            logger.warning("Failed to resolve fund names: %s", e)

        return resolved


# ========================================================================
# M3: 执行适配器实现
# ========================================================================

class PaperExecutionAdapter:
    """
    模拟执行适配器

    不实际发送订单，只模拟执行过程并记录日志。
    用于：
    - 策略回测
    - 开发测试
    - 金丝雀发布前的验证
    """

    def __init__(self, portfolio_id: int):
        self.portfolio_id = portfolio_id
        self._orders: dict[str, dict[str, Any]] = {}

    def submit_order(self, intent) -> str:
        """
        模拟提交订单

        Args:
            intent: OrderIntent 订单意图

        Returns:
            模拟订单ID（使用 intent_id）
        """
        import uuid

        from django.utils import timezone

        from apps.strategy.domain.entities import OrderEvent, OrderStatus
        from apps.strategy.domain.services import OrderStateMachine

        # 生成模拟订单ID
        paper_order_id = f"PAPER-{intent.intent_id}"

        # 模拟订单状态
        self._orders[paper_order_id] = {
            'intent_id': intent.intent_id,
            'symbol': intent.symbol,
            'side': intent.side.value,
            'qty': intent.qty,
            'limit_price': intent.limit_price,
            'status': OrderStatus.SENT.value,
            'filled_qty': 0,
            'filled_price': None,
            'created_at': timezone.now().isoformat(),
            'updated_at': timezone.now().isoformat(),
        }

        logger.info(
            f"[PaperAdapter] Order submitted: {paper_order_id} "
            f"symbol={intent.symbol} side={intent.side.value} qty={intent.qty}"
        )

        return paper_order_id

    def query_order_status(self, broker_order_id: str) -> dict[str, Any]:
        """
        查询模拟订单状态

        Args:
            broker_order_id: 模拟订单ID

        Returns:
            订单状态信息
        """
        from django.utils import timezone

        from apps.strategy.domain.entities import OrderStatus

        if broker_order_id in self._orders:
            order = self._orders[broker_order_id]

            # 模拟部分成交或全部成交
            if order['status'] == OrderStatus.SENT.value:
                # 模拟立即全部成交
                order['status'] = OrderStatus.FILLED.value
                order['filled_qty'] = order['qty']
                order['filled_price'] = order['limit_price'] or 100.0  # 默认价格
                order['updated_at'] = timezone.now().isoformat()

            return {
                'status': order['status'],
                'filled_qty': order['filled_qty'],
                'filled_price': order['filled_price'],
                'remaining_qty': order['qty'] - order['filled_qty'],
                'error_message': None,
            }

        return {
            'status': 'not_found',
            'filled_qty': 0,
            'filled_price': None,
            'remaining_qty': 0,
            'error_message': f'Order not found: {broker_order_id}',
        }

    def cancel_order(self, broker_order_id: str) -> bool:
        """
        模拟撤销订单

        Args:
            broker_order_id: 模拟订单ID

        Returns:
            是否撤销成功
        """
        from django.utils import timezone

        from apps.strategy.domain.entities import OrderStatus

        if broker_order_id in self._orders:
            order = self._orders[broker_order_id]
            if order['status'] == OrderStatus.SENT.value:
                order['status'] = OrderStatus.CANCELED.value
                order['updated_at'] = timezone.now().isoformat()
                logger.info(f"[PaperAdapter] Order canceled: {broker_order_id}")
                return True
            else:
                logger.warning(
                    f"[PaperAdapter] Cannot cancel order in status: {order['status']}"
                )
                return False

        return False

    def get_name(self) -> str:
        return "paper"

    def is_live(self) -> bool:
        return False


class BrokerExecutionAdapter:
    """
    券商执行适配器（占位实现）

    实盘执行适配器，需要根据实际券商API实现。
    当前为占位实现，用于：
    - 接口定义
    - 沙盒测试
    """

    def __init__(self, broker_config: dict[str, Any]):
        """
        初始化券商适配器

        Args:
            broker_config: 券商配置，包含：
            - broker_type: 券商类型（如 "xtp", "ib"）
            - api_key: API密钥
            - api_secret: API密钥
            - sandbox: 是否沙箱模式
        """
        self.broker_config = broker_config
        self._is_sandbox = broker_config.get('sandbox', True)

    def submit_order(self, intent) -> str:
        """
        提交订单到券商

        Args:
            intent: OrderIntent 订单意图

        Returns:
            券商订单ID

        Raises:
            NotImplementedError: 当前为占位实现
        """
        # 占位实现： 实际使用时需要对接券商API
        raise NotImplementedError(
            "BrokerExecutionAdapter.submit_order is not implemented. "
            "Please implement the actual broker API integration."
        )

    def query_order_status(self, broker_order_id: str) -> dict[str, Any]:
        """
        查询券商订单状态

        Args:
            broker_order_id: 券商订单ID

        Returns:
            订单状态信息

        Raises:
            NotImplementedError: 当前为占位实现
        """
        raise NotImplementedError(
            "BrokerExecutionAdapter.query_order_status is not implemented. "
            "Please implement the actual broker API integration."
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        """
        撤销券商订单

        Args:
            broker_order_id: 券商订单ID

        Returns:
            是否撤销成功

        Raises:
            NotImplementedError: 当前为占位实现
        """
        raise NotImplementedError(
            "BrokerExecutionAdapter.cancel_order is not implemented. "
            "Please implement the actual broker API integration."
        )

    def get_name(self) -> str:
        return f"broker_{self.broker_config.get('broker_type', 'unknown')}"

    def is_live(self) -> bool:
        return not self._is_sandbox


class ExecutionAdapterFactory:
    """执行适配器工厂"""

    @staticmethod
    def create_adapter(
        mode: str,
        portfolio_id: int,
        broker_config: dict[str, Any] = None
    ):
        """
        创建执行适配器

        Args:
            mode: 执行模式 ("paper" | "broker")
            portfolio_id: 投资组合ID
            broker_config: 券商配置（仅broker模式需要）

        Returns:
            执行适配器实例
        """
        if mode == "paper":
            return PaperExecutionAdapter(portfolio_id)
        elif mode == "broker":
            if not broker_config:
                raise ValueError("broker_config is required for broker mode")
            return BrokerExecutionAdapter(broker_config)
        else:
            raise ValueError(f"Unknown execution mode: {mode}")
