"""
自动交易引擎

Application层核心组件：
- 每日定时运行(Celery Beat)
- 自动扫描账户、生成订单、更新持仓
- 依赖Use Cases和Domain层服务
- 集成策略系统（Phase 5）
"""
import logging
from typing import List, Optional, Protocol
from datetime import date, datetime

from apps.simulated_trading.domain.entities import SimulatedAccount, Position
from apps.simulated_trading.domain.rules import PositionSizingRule
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase
)

logger = logging.getLogger(__name__)


# Protocol接口定义
class AssetPoolServiceProtocol(Protocol):
    """资产池服务接口"""
    def get_investable_assets(self, asset_type: str) -> List[dict]:
        """获取可投池资产"""
        ...


class SignalServiceProtocol(Protocol):
    """信号服务接口"""
    def get_valid_signals(self) -> List[dict]:
        """获取有效信号"""
        ...


class MarketDataProviderProtocol(Protocol):
    """市场数据提供者接口"""
    def get_price(self, asset_code: str, trade_date: date) -> Optional[float]:
        """获取指定日期的价格"""
        ...


class RegimeServiceProtocol(Protocol):
    """Regime服务接口"""
    def get_current_regime(self) -> str:
        """获取当前Regime"""
        ...


class AutoTradingEngine:
    """
    自动交易引擎

    核心流程:
    1. 扫描所有活跃模拟账户
    2. 检查持仓是否需要卖出
    3. 从可投池+信号获取买入候选
    4. 执行买入/卖出订单
    5. 更新账户绩效

    Phase 5 更新：
    - 支持策略系统集成
    - 如果账户绑定了策略，使用策略执行引擎
    - 如果账户未绑定策略，使用原有逻辑（向后兼容）
    """

    def __init__(
        self,
        account_repo,
        position_repo,
        trade_repo,
        buy_use_case: ExecuteBuyOrderUseCase,
        sell_use_case: ExecuteSellOrderUseCase,
        performance_use_case: GetAccountPerformanceUseCase,
        asset_pool_service: Optional[AssetPoolServiceProtocol] = None,
        signal_service: Optional[SignalServiceProtocol] = None,
        market_data_provider: Optional[MarketDataProviderProtocol] = None,
        regime_service: Optional[RegimeServiceProtocol] = None,
        strategy_executor: Optional['StrategyExecutor'] = None
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.buy_use_case = buy_use_case
        self.sell_use_case = sell_use_case
        self.performance_use_case = performance_use_case
        self.asset_pool_service = asset_pool_service
        self.signal_service = signal_service
        self.market_data = market_data_provider
        self.regime_service = regime_service
        self.strategy_executor = strategy_executor  # Phase 5: 策略执行引擎

    def run_daily_trading(self, trade_date: date) -> dict:
        """
        执行每日自动交易

        Args:
            trade_date: 交易日期

        Returns:
            {account_id: {buy_count: int, sell_count: int}}
        """
        logger.info(f"="*60)
        logger.info(f"开始执行模拟盘自动交易: {trade_date}")
        logger.info(f"="*60)

        # 1. 获取所有活跃的模拟账户
        accounts = self.account_repo.get_active_accounts()
        logger.info(f"找到 {len(accounts)} 个活跃模拟账户")

        results = {}
        for account in accounts:
            if not account.auto_trading_enabled:
                logger.info(f"账户 {account.account_name} (ID={account.account_id}) 未启用自动交易,跳过")
                continue

            buy_count, sell_count = self._process_account(account, trade_date)
            results[account.account_id] = {
                "buy_count": buy_count,
                "sell_count": sell_count
            }

        logger.info(f"="*60)
        logger.info(f"模拟盘自动交易完成: {results}")
        logger.info(f"="*60)

        return results

    def _process_account(self, account: SimulatedAccount, trade_date: date) -> tuple[int, int]:
        """
        处理单个账户的自动交易

        Phase 5 更新：
        - 检查账户是否绑定了策略
        - 如果有策略，使用策略执行引擎
        - 如果没有策略，使用原有逻辑（向后兼容）

        Returns:
            (买入次数, 卖出次数)
        """
        logger.info(f"\n处理账户: {account.account_name} (ID={account.account_id})")
        logger.info(f"  当前资金: {account.current_cash:.2f}元, 持仓市值: {account.current_market_value:.2f}元")

        # Phase 5: 检查是否绑定了策略
        active_strategy_id = self._get_account_strategy_id(account.account_id)

        if active_strategy_id and self.strategy_executor:
            logger.info(f"  账户绑定策略ID: {active_strategy_id}, 使用策略执行引擎")
            return self._execute_strategy_based_trading(account, active_strategy_id, trade_date)
        else:
            logger.info(f"  账户未绑定策略或策略引擎未配置，使用原有逻辑")
            return self._execute_legacy_trading(account, trade_date)

    def _get_account_strategy_id(self, account_id: int) -> Optional[int]:
        """
        获取账户绑定的策略ID

        Args:
            account_id: 账户ID

        Returns:
            策略ID，如果未绑定则返回 None
        """
        try:
            from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
            from apps.strategy.infrastructure.models import PortfolioStrategyAssignmentModel

            account_model = SimulatedAccountModel._default_manager.filter(id=account_id).first()
            if not account_model:
                return None

            # 兼容旧模型字段（如果存在）
            legacy_strategy = getattr(account_model, "active_strategy", None)
            if legacy_strategy:
                return legacy_strategy.id

            # 现行实现：通过 portfolio_strategy_assignment 关联表读取
            assignment = (
                PortfolioStrategyAssignmentModel._default_manager
                .select_related("strategy")
                .filter(
                    portfolio_id=account_id,
                    is_active=True,
                    strategy__is_active=True,
                )
                .first()
            )
            if assignment:
                return assignment.strategy_id
            return None
        except Exception as e:
            logger.warning(f"获取账户策略失败: {e}")
            return None

    def _execute_strategy_based_trading(
        self,
        account: SimulatedAccount,
        strategy_id: int,
        trade_date: date
    ) -> tuple[int, int]:
        """
        使用策略执行引擎进行交易

        Args:
            account: 账户实体
            strategy_id: 策略ID
            trade_date: 交易日期

        Returns:
            (买入次数, 卖出次数)
        """
        buy_count = 0
        sell_count = 0

        try:
            # 1. 执行策略，获取信号推荐
            from apps.strategy.application.strategy_executor import StrategyExecutor
            execution_result = self.strategy_executor.execute_strategy(strategy_id, account.account_id)

            if not execution_result.is_success:
                logger.error(f"策略执行失败: {execution_result.error_message}")
                return 0, 0

            logger.info(f"  策略执行成功，生成 {len(execution_result.signals)} 个信号")

            # 2. 处理卖出信号
            positions = self.position_repo.get_by_account(account.account_id)
            held_codes = {p.asset_code for p in positions}

            for signal in execution_result.signals:
                if signal.action.value == 'sell' and signal.asset_code in held_codes:
                    try:
                        price = self._get_current_price(signal.asset_code, trade_date)
                        if price is None:
                            logger.warning(f"    无法获取 {signal.asset_code} 价格,跳过卖出")
                            continue

                        position = next(p for p in positions if p.asset_code == signal.asset_code)
                        quantity = signal.quantity or position.quantity

                        self.sell_use_case.execute(
                            account_id=account.account_id,
                            asset_code=signal.asset_code,
                            quantity=quantity,
                            price=price,
                            reason=f"策略信号: {signal.reason}"
                        )
                        sell_count += 1
                        logger.info(f"    ✓ 卖出: {signal.asset_name} x{quantity} @ {price:.2f} (原因: {signal.reason})")
                    except Exception as e:
                        logger.error(f"    ✗ 卖出失败: {signal.asset_code}, 错误: {e}")

            # 3. 处理买入信号
            for signal in execution_result.signals:
                if signal.action.value == 'buy':
                    try:
                        # 检查是否已有持仓
                        if signal.asset_code in held_codes:
                            logger.info(f"    跳过 {signal.asset_code}: 已有持仓")
                            continue

                        price = self._get_current_price(signal.asset_code, trade_date)
                        if price is None:
                            logger.warning(f"    无法获取 {signal.asset_code} 价格,跳过")
                            continue

                        # 计算买入数量
                        quantity = signal.quantity
                        if quantity is None:
                            # 根据权重计算数量
                            positions = self.position_repo.get_by_account(account.account_id)
                            quantity = PositionSizingRule.calculate_buy_quantity(
                                account=account,
                                asset_price=price,
                                asset_score=signal.confidence * 100,
                                existing_positions=positions
                            )

                        if quantity == 0:
                            logger.info(f"    跳过 {signal.asset_code}: 计算买入数量为0")
                            continue

                        self.buy_use_case.execute(
                            account_id=account.account_id,
                            asset_code=signal.asset_code,
                            asset_name=signal.asset_name,
                            asset_type='equity',
                            quantity=quantity,
                            price=price,
                            reason=f"策略信号: {signal.reason}",
                            signal_id=None
                        )
                        buy_count += 1
                        logger.info(f"    ✓ 买入: {signal.asset_name} x{quantity} @ {price:.2f} (原因: {signal.reason})")
                    except Exception as e:
                        logger.error(f"    ✗ 买入失败: {signal.asset_code}, 错误: {e}")

            # 4. 更新账户绩效
            self._update_account_performance(account.account_id, trade_date)

            logger.info(f"  账户处理完成(策略模式): 买入{buy_count}次, 卖出{sell_count}次")

        except Exception as e:
            logger.error(f"策略执行异常: {e}", exc_info=True)

        return buy_count, sell_count

    def _execute_legacy_trading(self, account: SimulatedAccount, trade_date: date) -> tuple[int, int]:
        """
        使用原有逻辑进行交易（向后兼容）

        Args:
            account: 账户实体
            trade_date: 交易日期

        Returns:
            (买入次数, 卖出次数)
        """
        buy_count = 0
        sell_count = 0

        # 1. 获取当前持仓
        positions = self.position_repo.get_by_account(account.account_id)
        logger.info(f"  当前持仓: {len(positions)} 个")

        # 2. 检查是否需要卖出现有持仓
        for position in positions:
            if self._should_sell_position(position, account, trade_date):
                try:
                    price = self._get_current_price(position.asset_code, trade_date)
                    if price is None:
                        logger.warning(f"    无法获取 {position.asset_code} 价格,跳过卖出")
                        continue

                    self.sell_use_case.execute(
                        account_id=account.account_id,
                        asset_code=position.asset_code,
                        quantity=position.quantity,  # 全部卖出
                        price=price,
                        reason=self._get_sell_reason(position)
                    )
                    sell_count += 1
                    logger.info(f"    ✓ 卖出: {position.asset_name} x{position.quantity} @ {price:.2f}")
                except Exception as e:
                    logger.error(f"    ✗ 卖出失败: {position.asset_code}, 错误: {e}")

        # 3. 检查是否需要买入新资产
        buy_candidates = self._get_buy_candidates(account, trade_date)
        logger.info(f"  买入候选: {len(buy_candidates)} 个")

        for candidate in buy_candidates:
            try:
                if self._execute_buy(account, candidate, trade_date):
                    buy_count += 1
            except Exception as e:
                logger.error(f"    ✗ 买入失败: {candidate.get('asset_code')}, 错误: {e}")

        # 4. 更新账户绩效
        self._update_account_performance(account.account_id, trade_date)

        logger.info(f"  账户处理完成(原有模式): 买入{buy_count}次, 卖出{sell_count}次")

        return buy_count, sell_count

    def _should_sell_position(
        self,
        position: Position,
        account: SimulatedAccount,
        trade_date: date
    ) -> bool:
        """
        判断是否应该卖出持仓

        卖出条件:
        1. 信号失效
        2. Regime不匹配(资产进入禁投池)
        3. 触发止损
        """
        # 1. 检查信号是否仍然有效
        signal_valid = True
        if position.signal_id:
            if self.signal_service:
                signal = self.signal_service.get_signal_by_id(position.signal_id)
                signal_valid = signal and signal.get('is_valid', False) if signal else False
            else:
                # 如果没有信号服务，从数据库查询
                try:
                    from apps.signal.infrastructure.models import InvestmentSignalModel
                    signal = InvestmentSignalModel._default_manager.filter(
                        id=position.signal_id
                    ).first()
                    signal_valid = signal and signal.status == 'valid' if signal else False
                except Exception as e:
                    logger.warning(f"查询信号失败: {position.signal_id}, 错误: {e}")
                    signal_valid = True  # 查询失败时假设有效，避免误杀

        if not signal_valid:
            logger.info(f"    持仓 {position.asset_code} 信号失效,准备卖出")
            return True

        # 2. 检查是否仍在可投池
        regime_match = True
        if self.asset_pool_service:
            pool_type = self.asset_pool_service.get_asset_pool_type(position.asset_code)
            # 不在可投池或候选池，则认为不匹配
            regime_match = pool_type in ["investable", "candidate", None]  # None表示未分类，暂不处理
            if pool_type == "prohibited":
                logger.info(f"    持仓 {position.asset_code} 进入禁投池,准备卖出")
                return True

        # 3. 检查是否触发止损
        if account.stop_loss_pct and position.unrealized_pnl_pct < -account.stop_loss_pct:
            logger.info(
                f"    持仓 {position.asset_code} 触发止损 "
                f"(浮亏{position.unrealized_pnl_pct:.2f}% > 止损线{account.stop_loss_pct}%),准备卖出"
            )
            return True

        return False

    def _get_sell_reason(self, position: Position) -> str:
        """获取卖出原因"""
        if position.unrealized_pnl_pct < 0:
            return f"止损卖出(浮亏{position.unrealized_pnl_pct:.2f}%)"
        else:
            return "信号变化卖出"

    def _get_buy_candidates(self, account: SimulatedAccount, trade_date: date) -> List[dict]:
        """
        获取买入候选资产

        策略:
        1. 从可投池获取高分资产
        2. 筛选有有效信号的资产
        3. 检查账户是否已有持仓(避免重复)
        """
        if not self.asset_pool_service:
            logger.warning("资产池服务未配置，无法获取买入候选")
            return []

        try:
            # 1. 获取可投池且有有效信号的资产
            candidates = self.asset_pool_service.get_investable_assets_with_signals(
                asset_type="equity",  # 当前只支持股票
                min_score=60.0,
                limit=20
            )

            if not candidates:
                logger.info("  未找到符合条件的有信号资产")
                return []

            # 2. 过滤掉已持仓的资产
            existing_positions = self.position_repo.get_by_account(account.account_id)
            held_codes = {p.asset_code for p in existing_positions}

            filtered_candidates = [
                c for c in candidates
                if c['asset_code'] not in held_codes
            ]

            logger.info(
                f"  找到 {len(candidates)} 个有信号的资产, "
                f"过滤持仓后剩余 {len(filtered_candidates)} 个"
            )

            return filtered_candidates

        except Exception as e:
            logger.error(f"获取买入候选失败: {e}")
            return []

    def _execute_buy(
        self,
        account: SimulatedAccount,
        candidate: dict,
        trade_date: date
    ) -> bool:
        """
        执行买入

        Returns:
            是否成功买入
        """
        asset_code = candidate.get('asset_code')
        asset_name = candidate.get('asset_name')
        asset_type = candidate.get('asset_type', 'equity')
        asset_score = candidate.get('score', 70.0)
        signal_id = candidate.get('signal_id')

        # 1. 获取当前价格
        price = self._get_current_price(asset_code, trade_date)
        if price is None:
            logger.warning(f"    无法获取 {asset_code} 价格,跳过")
            return False

        # 2. 检查是否已有持仓
        existing = self.position_repo.get_position(account.account_id, asset_code)
        if existing:
            logger.info(f"    跳过 {asset_code}: 已有持仓 {existing.quantity} 股")
            return False

        # 3. 计算买入数量
        positions = self.position_repo.get_by_account(account.account_id)
        quantity = PositionSizingRule.calculate_buy_quantity(
            account=account,
            asset_price=price,
            asset_score=asset_score,
            existing_positions=positions
        )

        if quantity == 0:
            logger.info(f"    跳过 {asset_code}: 计算买入数量为0")
            return False

        # 4. 执行买入
        self.buy_use_case.execute(
            account_id=account.account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            quantity=quantity,
            price=price,
            reason="自动交易引擎买入",
            signal_id=signal_id
        )

        logger.info(f"    ✓ 买入: {asset_name} x{quantity} @ {price:.2f}")
        return True

    def _get_current_price(self, asset_code: str, trade_date: date) -> Optional[float]:
        """获取当前价格"""
        if self.market_data:
            return self.market_data.get_price(asset_code, trade_date)
        return None

    def _update_account_performance(self, account_id: int, trade_date: date):
        """更新账户绩效"""
        # TODO: 实现绩效计算逻辑
        # 当前跳过,等待Phase 2实现
        pass


class MockMarketDataProvider:
    """模拟市场数据提供者(用于测试)"""

    def __init__(self):
        self._prices = {
            "000001.SZ": 10.50,
            "000002.SZ": 25.80,
            "600000.SH": 7.20,
            "600519.SH": 1850.00,
        }

    def get_price(self, asset_code: str, trade_date: date) -> Optional[float]:
        """获取指定日期的价格(模拟)"""
        return self._prices.get(asset_code)

