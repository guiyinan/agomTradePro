"""
Account Application Use Cases

持仓管理的用例编排。
遵循四层架构：协调Domain层服务和Infrastructure层仓储。
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.account.application.repository_provider import (
    AccountRepository,
    AssetMetadataRepository,
    MacroSizingConfigRepository,
    PortfolioRepository,
    PortfolioSnapshotRepository,
    PositionRepository,
    SystemSettingsRepository,
    build_market_price_service,
)
from apps.account.domain.entities import (
    AssetAllocation,
    AssetClassType,
    Position,
    RegimeMatchAnalysis,
    Region,
)
from apps.account.domain.services import (
    MacroSizingContext,
    PositionService,
    SizingMultiplierResult,
    calculate_macro_multiplier,
    calculate_portfolio_drawdown,
)
from apps.backtest.application.repository_provider import get_backtest_repository
from apps.regime.application.current_regime import resolve_current_regime
from apps.signal.application.repository_provider import get_signal_repository

logger = logging.getLogger(__name__)


@dataclass
class CreatePositionInput:
    """创建持仓输入"""

    user_id: int
    asset_code: str
    shares: float | None = None  # 不指定则自动计算
    price: Decimal | None = None  # 不指定则获取行情


@dataclass
class CreatePositionOutput:
    """创建持仓输出"""

    position: Position
    shares: float
    notional: Decimal
    cash_required: Decimal


@dataclass
class RegimeAnalysisOutput:
    """Regime分析输出"""

    current_regime: str
    regime_date: date
    match_analysis: RegimeMatchAnalysis
    asset_allocation: list[AssetAllocation]
    risk_assessment: dict[str, any]


class CreatePositionUseCase:
    """创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
        asset_meta_repo: AssetMetadataRepository,
        market_price_service: Any | None = None,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo
        self.asset_meta_repo = asset_meta_repo
        self.market_price_service = market_price_service or build_market_price_service()

    def execute(self, input: CreatePositionInput) -> CreatePositionOutput:
        """
        创建持仓

        流程：
        1. 获取用户账户配置
        2. 如果未指定shares，根据风险偏好自动计算
        3. 获取或创建资产元数据
        4. 确定价格（优先使用输入价格，否则从行情接口获取）
        5. 创建持仓记录
        6. 创建交易记录
        """
        # 1. 获取用户配置
        profile = self.account_repo.get_by_user_id(input.user_id)
        if not profile:
            raise ValueError(f"用户 {input.user_id} 账户配置不存在")

        # 2. 获取或创建投资组合
        portfolio_id = self.account_repo.get_or_create_default_portfolio(input.user_id)

        # 3. 获取资产元数据
        asset_meta = self.asset_meta_repo.get_or_create_asset(
            asset_code=input.asset_code,
            name=input.asset_code,  # 简化处理，实际应从接口获取名称
        )

        # 4. 确定价格（从行情接口获取，而非硬编码）
        price = input.price
        if price is None:
            price = self._get_market_price(input.asset_code)
            if price is None:
                raise ValueError(
                    f"无法获取资产 {input.asset_code} 的价格，" f"请检查资产代码或手动指定价格"
                )

        # 5. 计算仓位（如果未指定）
        if input.shares is None:
            calc = PositionService.calculate_position_size(
                account_capital=profile.initial_capital,
                risk_tolerance=profile.risk_tolerance,
                asset_class=AssetClassType(asset_meta["asset_class"]),
                region=Region(asset_meta["region"]),
                current_price=price,
            )
            shares = calc.shares
        else:
            shares = input.shares

        # 6. 创建持仓
        position = self.position_repo.create_position_legacy(
            portfolio_id=portfolio_id,
            asset_code=input.asset_code,
            shares=shares,
            price=price,
            source="manual",
        )

        return CreatePositionOutput(
            position=position,
            shares=shares,
            notional=Decimal(str(shares * float(price))),
            cash_required=Decimal(str(shares * float(price))),
        )

    def _get_market_price(self, asset_code: str) -> Decimal | None:
        """
        从行情接口获取资产价格

        Args:
            asset_code: 资产代码

        Returns:
            Decimal: 价格，获取失败返回 None
        """
        price_metadata = self.market_price_service.get_price_with_metadata(asset_code)
        if price_metadata:
            logger.info(
                f"从行情接口获取价格: {asset_code} = {price_metadata['price']} "
                f"(来源: {price_metadata['source']})"
            )
            return price_metadata["price"]

        logger.warning(f"无法从行情接口获取价格: {asset_code}")
        return None


class CreatePositionFromSignalUseCase:
    """从投资信号创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
        market_price_service: Any | None = None,
        signal_repo: object = None,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo
        self.market_price_service = market_price_service or build_market_price_service()
        self.signal_repo = signal_repo or get_signal_repository()

    def execute(
        self,
        user_id: int,
        signal_id: int,
        price: Decimal | None = None,
    ) -> CreatePositionOutput:
        """
        从投资信号创建持仓

        流程：
        1. 验证信号归属
        2. 获取资产代码（从信号中）
        3. 确定价格（从行情接口获取）
        4. 创建持仓
        5. 记录信号关联
        """
        # 获取用户配置
        profile = self.account_repo.get_by_user_id(user_id)
        if not profile:
            raise ValueError(f"用户 {user_id} 账户配置不存在")

        # 获取信号信息
        signal = self.signal_repo.get_signal_snapshot(signal_id)
        if not signal or signal.get("user_id") != user_id:
            raise ValueError(f"信号 {signal_id} 不存在或无权限")

        # 确定价格（从行情接口获取，而非硬编码）
        if price is None:
            asset_code = signal["asset_code"]
            price_metadata = self.market_price_service.get_price_with_metadata(asset_code)
            if price_metadata:
                price = price_metadata["price"]
                logger.info(
                    f"从行情接口获取价格: {asset_code} = {price} "
                    f"(来源: {price_metadata['source']})"
                )
            else:
                raise ValueError(
                    f"无法获取资产 {asset_code} 的价格，" f"请检查资产代码或手动指定价格"
                )

        # 创建持仓（会自动记录信号关联）
        position = self.position_repo.create_position_from_signal(
            user_id=user_id,
            signal_id=signal_id,
            price=price,
        )

        if not position:
            raise ValueError(f"信号 {signal_id} 不存在或无权限")

        return CreatePositionOutput(
            position=position,
            shares=position.shares,
            notional=position.market_value,
            cash_required=position.market_value,
        )


class ClosePositionUseCase:
    """平仓用例"""

    def __init__(self, position_repo: PositionRepository):
        self.position_repo = position_repo

    def execute(
        self,
        position_id: int,
        user_id: int,
        shares: float | None = None,
    ) -> Position | None:
        """
        平仓

        Args:
            position_id: 持仓ID
            user_id: 用户ID（验证权限）
            shares: 平仓数量，None表示全部平仓
        """
        # 验证权限
        position = self.position_repo.get_position_by_id(position_id)
        if not position:
            raise ValueError(f"持仓 {position_id} 不存在")

        if position.user_id != user_id:
            raise ValueError("无权限操作此持仓")

        # 执行平仓
        return self.position_repo.close_position(position_id, shares)


class AnalyzePortfolioUseCase:
    """组合分析用例"""

    def __init__(
        self,
        portfolio_repo: PortfolioRepository,
        regime_repo: object,
    ):
        self.portfolio_repo = portfolio_repo
        self.regime_repo = regime_repo

    def execute(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> RegimeAnalysisOutput:
        """
        分析投资组合

        返回：
        1. 当前Regime状态
        2. 持仓与Regime的匹配度分析
        3. 资产配置分布
        4. 风险评估
        """
        # 1. 获取组合快照
        snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if not snapshot:
            raise ValueError(f"投资组合 {portfolio_id} 不存在")

        # 2. 获取当前Regime
        latest_regime = resolve_current_regime(as_of_date=date.today())
        current_regime = latest_regime.dominant_regime
        regime_date = latest_regime.observed_at

        # 3. 计算Regime匹配度
        match_analysis = PositionService.calculate_regime_match_score(
            positions=snapshot.positions,
            current_regime=current_regime,
        )

        # 4. 计算资产配置分布
        allocation_by_class = PositionService.calculate_asset_allocation(
            positions=snapshot.positions,
            dimension="asset_class",
        )
        allocation_by_region = PositionService.calculate_asset_allocation(
            positions=snapshot.positions,
            dimension="region",
        )

        # 5. 风险评估
        risk_assessment = PositionService.assess_portfolio_risk(
            positions=snapshot.positions,
            account_capital=snapshot.cash_balance + snapshot.invested_value,
        )

        return RegimeAnalysisOutput(
            current_regime=current_regime,
            regime_date=regime_date,
            match_analysis=match_analysis,
            asset_allocation=allocation_by_class + allocation_by_region,
            risk_assessment=risk_assessment,
        )


class UpdatePositionPricesUseCase:
    """更新持仓价格用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        asset_meta_repo: AssetMetadataRepository,
    ):
        self.position_repo = position_repo
        self.asset_meta_repo = asset_meta_repo

    def execute(self, user_id: int) -> dict[str, any]:
        """
        批量更新用户持仓价格

        从行情数据源获取最新价格并更新持仓记录。
        如果行情接口不可用，则使用当前价格（成本价作为后备）。

        Args:
            user_id: 用户ID

        Returns:
            Dict: 更新统计，包含 updated_count, user_id, updated_at
        """
        # 通过 AssetMetadataRepository 批量更新持仓价格
        # 该方法已集成行情数据源 (MarketPriceService)
        count = self.asset_meta_repo.update_position_prices(user_id)

        return {
            "updated_count": count,
            "user_id": user_id,
            "updated_at": timezone.now(),
        }


@dataclass
class CreatePositionFromBacktestInput:
    """从回测创建持仓输入"""

    user_id: int
    backtest_id: int
    scale_factor: float = 1.0  # 缩放因子，用于按比例调整仓位


@dataclass
class CreatePositionFromBacktestOutput:
    """从回测创建持仓输出"""

    positions_created: list[Position]
    total_positions: int
    total_value: float
    backtest_name: str


class CreatePositionFromBacktestUseCase:
    """从回测结果创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
        asset_meta_repo: AssetMetadataRepository,
        market_price_service: Any | None = None,
        backtest_repo: object = None,
        settings_repo: SystemSettingsRepository = None,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo
        self.asset_meta_repo = asset_meta_repo
        self.market_price_service = market_price_service or build_market_price_service()
        self.backtest_repo = backtest_repo or get_backtest_repository()
        self.settings_repo = settings_repo or SystemSettingsRepository()

    def execute(self, input: CreatePositionFromBacktestInput) -> CreatePositionFromBacktestOutput:
        """
        从回测结果创建持仓

        流程：
        1. 验证回测归属
        2. 从回测的trades中提取最终持仓
        3. 为每个资产创建持仓记录
        4. 记录交易历史
        """
        # 1. 获取回测结果
        backtest_model = self.backtest_repo.get_backtest_by_id(input.backtest_id)
        if backtest_model is None:
            raise ValueError(f"回测 {input.backtest_id} 不存在")

        # 验证归属
        if backtest_model.user_id != input.user_id:
            raise ValueError("无权限访问此回测结果")

        if backtest_model.status != "completed":
            raise ValueError(f"回测状态为 {backtest_model.status}，无法应用")

        # 2. 从trades中提取最终持仓
        final_holdings = self._extract_final_holdings_from_trades(
            backtest_model.trades, input.scale_factor
        )

        if not final_holdings:
            raise ValueError("回测结果中无持仓数据")

        # 3. 获取或创建投资组合
        portfolio_id = self.account_repo.get_or_create_default_portfolio(input.user_id)

        # 4. 为每个资产创建持仓
        positions_created = []
        total_value = 0.0

        for holding in final_holdings:
            asset_class = holding["asset_class"]

            # 映射 asset_class 到 asset_code（回测中使用的是大类名称）
            asset_code = self._map_asset_class_to_code(asset_class)

            # 获取或创建资产元数据
            self.asset_meta_repo.get_or_create_asset(
                asset_code=asset_code,
                name=asset_class,  # 使用大类名称作为显示名称
                asset_class=self._infer_asset_class_type(asset_class),
                region=self._infer_region(asset_class),
            )

            # 获取当前价格（优先使用行情接口，否则使用回测价格）
            price_metadata = self.market_price_service.get_price_with_metadata(asset_code)
            if price_metadata:
                price = price_metadata["price"]
                logger.info(
                    f"从行情接口获取价格: {asset_code} = {price} "
                    f"(来源: {price_metadata['source']})"
                )
            else:
                # 如果行情接口失败，使用回测中的价格作为后备
                price = Decimal(str(holding.get("price", 100.0)))
                logger.warning(f"无法从行情接口获取价格，使用回测价格: {asset_code} = {price}")

            # 创建持仓
            position = self.position_repo.create_position_legacy(
                portfolio_id=portfolio_id,
                asset_code=asset_code,
                shares=holding["shares"],
                price=price,
                source="backtest",
                source_id=input.backtest_id,
            )

            positions_created.append(position)
            total_value += float(position.market_value)

        return CreatePositionFromBacktestOutput(
            positions_created=positions_created,
            total_positions=len(positions_created),
            total_value=total_value,
            backtest_name=backtest_model.name,
        )

    def _extract_final_holdings_from_trades(
        self, trades: list[dict], scale_factor: float = 1.0
    ) -> list[dict]:
        """
        从交易记录中提取最终持仓

        分析逻辑：
        1. 按时间排序所有交易
        2. 逐笔更新持仓状态
        3. 返回最终持仓（shares > 0）
        """
        holdings: dict[str, dict] = {}  # asset_class -> {shares, last_price}

        for trade in trades:
            asset_class = trade.get("asset_class")
            action = trade.get("action")
            shares = trade.get("shares", 0)
            price = trade.get("price", 100)

            if asset_class not in holdings:
                holdings[asset_class] = {"shares": 0.0, "price": price}

            if action == "buy":
                holdings[asset_class]["shares"] += shares
                # 更新加权平均价格
                old_shares = holdings[asset_class]["shares"] - shares
                old_price = holdings[asset_class]["price"]
                if old_shares > 0:
                    holdings[asset_class]["price"] = (
                        old_shares * old_price + shares * price
                    ) / holdings[asset_class]["shares"]
                else:
                    holdings[asset_class]["price"] = price
            elif action == "sell":
                holdings[asset_class]["shares"] -= shares
                # 清零持仓时重置价格
                if holdings[asset_class]["shares"] <= 0:
                    holdings[asset_class]["shares"] = 0
                    holdings[asset_class]["price"] = price

        # 过滤掉零持仓，应用缩放因子
        final_holdings = []
        for asset_class, data in holdings.items():
            if data["shares"] > 0:
                final_holdings.append(
                    {
                        "asset_class": asset_class,
                        "shares": data["shares"] * scale_factor,
                        "price": data["price"],
                    }
                )

        return final_holdings

    def _map_asset_class_to_code(self, asset_class: str) -> str:
        """
        将回测中的资产大类映射为具体资产代码

        这是一个简化实现，实际应用中需要：
        1. 用户选择具体ETF或基金
        2. 或者使用系统默认的标的映射表
        """
        mapped_code = self.settings_repo.get_runtime_asset_proxy_code(asset_class, "")
        return mapped_code or asset_class

    def _infer_asset_class_type(self, asset_class: str) -> AssetClassType:
        """从资产大类推断资产类型"""
        asset_class_lower = asset_class.lower()

        if (
            "growth" in asset_class_lower
            or "share" in asset_class_lower
            or "equity" in asset_class_lower
        ):
            return AssetClassType.EQUITY
        elif "bond" in asset_class_lower or "fixed" in asset_class_lower:
            return AssetClassType.FIXED_INCOME
        elif "gold" in asset_class_lower or "commodity" in asset_class_lower:
            return AssetClassType.COMMODITY
        elif "cash" in asset_class_lower or "money" in asset_class_lower:
            return AssetClassType.CASH
        else:
            return AssetClassType.OTHER

    def _infer_region(self, asset_class: str) -> Region:
        """从资产大类推断地区"""
        asset_class_lower = asset_class.lower()

        if (
            "china" in asset_class_lower
            or "a_share" in asset_class_lower
            or "sh" in asset_class_lower
        ):
            return Region.CN
        elif "us" in asset_class_lower:
            return Region.US
        elif "global" in asset_class_lower:
            return Region.GLOBAL
        else:
            return Region.CN  # 默认中国


@dataclass
class SizingContextOutput:
    """宏观仓位系数上下文输出。"""

    portfolio_id: int
    as_of_date: date
    regime_name: str
    regime_confidence: float
    pulse_composite: float
    pulse_warning: bool
    portfolio_drawdown_pct: float
    snapshot_count: int
    multiplier_result: SizingMultiplierResult
    warnings: list[str]


class GetSizingContextUseCase:
    """获取宏观感知仓位系数上下文。"""

    def __init__(
        self,
        portfolio_repo: PortfolioRepository | None = None,
        snapshot_repo: PortfolioSnapshotRepository | None = None,
        config_repo: MacroSizingConfigRepository | None = None,
    ):
        self.portfolio_repo = portfolio_repo or PortfolioRepository()
        self.snapshot_repo = snapshot_repo or PortfolioSnapshotRepository()
        self.config_repo = config_repo or MacroSizingConfigRepository()

    def execute(
        self,
        portfolio_id: int,
        user_id: int,
        *,
        refresh_pulse_if_stale: bool = True,
    ) -> SizingContextOutput:
        if not self.portfolio_repo.user_owns_portfolio(portfolio_id, user_id):
            raise ValueError(f"投资组合 {portfolio_id} 不存在或无权限")

        warnings: list[str] = []
        target_date = date.today()
        regime_name = "Unknown"
        regime_confidence = 0.0
        regime_unavailable = False
        try:
            regime_result = resolve_current_regime(as_of_date=target_date)
            regime_name = regime_result.dominant_regime
            regime_confidence = float(regime_result.confidence)
            if regime_result.is_fallback and regime_result.warnings:
                warnings.extend(regime_result.warnings)
        except Exception:
            logger.exception("Failed to resolve current regime for macro sizing context")
            regime_unavailable = True
            warnings.append("regime_unavailable")

        from apps.pulse.application.use_cases import GetLatestPulseUseCase

        pulse_unavailable = False
        try:
            pulse_snapshot = GetLatestPulseUseCase().execute(
                as_of_date=target_date,
                require_reliable=True,
                refresh_if_stale=refresh_pulse_if_stale,
            )
        except Exception:
            logger.exception("Failed to load latest pulse for macro sizing context")
            pulse_snapshot = None
            pulse_unavailable = True

        if pulse_snapshot is None:
            pulse_unavailable = True
            warnings.append("pulse_unavailable")
            pulse_composite = 0.0
            pulse_warning = False
        else:
            pulse_composite = float(pulse_snapshot.composite_score)
            pulse_warning = bool(pulse_snapshot.transition_warning)

        snapshot_unavailable = False
        try:
            snapshots = self.snapshot_repo.get_snapshots_for_volatility(
                portfolio_id=portfolio_id,
                days=180,
            )
        except Exception:
            logger.exception("Failed to load portfolio snapshots for macro sizing context")
            snapshots = []
            snapshot_unavailable = True
            warnings.append("snapshot_unavailable")

        value_history = [float(snapshot["total_value"]) for snapshot in snapshots]
        portfolio_drawdown_pct = calculate_portfolio_drawdown(value_history)

        context = MacroSizingContext(
            regime_confidence=regime_confidence,
            regime_name=regime_name,
            pulse_composite=pulse_composite,
            pulse_warning=pulse_warning,
            portfolio_drawdown_pct=portfolio_drawdown_pct,
        )
        multiplier_result = calculate_macro_multiplier(
            context,
            self.config_repo.get_active_config(),
        )
        reasoning = self._build_reasoning(
            context=context,
            result=multiplier_result,
            regime_unavailable=regime_unavailable,
            pulse_unavailable=pulse_unavailable,
            snapshot_unavailable=snapshot_unavailable,
        )

        return SizingContextOutput(
            portfolio_id=portfolio_id,
            as_of_date=target_date,
            regime_name=context.regime_name,
            regime_confidence=context.regime_confidence,
            pulse_composite=context.pulse_composite,
            pulse_warning=context.pulse_warning,
            portfolio_drawdown_pct=context.portfolio_drawdown_pct,
            snapshot_count=len(snapshots),
            multiplier_result=SizingMultiplierResult(
                multiplier=multiplier_result.multiplier,
                regime_factor=multiplier_result.regime_factor,
                pulse_factor=multiplier_result.pulse_factor,
                drawdown_factor=multiplier_result.drawdown_factor,
                action_hint=multiplier_result.action_hint,
                reasoning=reasoning,
                config_version=multiplier_result.config_version,
            ),
            warnings=warnings,
        )

    @staticmethod
    def _build_reasoning(
        *,
        context: MacroSizingContext,
        result: SizingMultiplierResult,
        regime_unavailable: bool,
        pulse_unavailable: bool,
        snapshot_unavailable: bool,
    ) -> str:
        regime_reason = (
            f"Regime数据不可用，使用最保守置信度（系数{result.regime_factor:.2f}）"
            if regime_unavailable
            else f"Regime置信度{context.regime_confidence:.0%}（系数{result.regime_factor:.2f}）"
        )
        if pulse_unavailable:
            pulse_reason = f"Pulse数据不可用，使用中性系数（系数{result.pulse_factor:.2f}）"
        elif context.pulse_warning:
            pulse_reason = f"Pulse转折预警激活（系数{result.pulse_factor:.2f}）"
        else:
            pulse_reason = (
                f"Pulse综合分{context.pulse_composite:+.2f}（系数{result.pulse_factor:.2f}）"
            )

        if snapshot_unavailable:
            drawdown_reason = (
                f"组合回撤数据不可用，按0.0%回撤处理（系数{result.drawdown_factor:.2f}）"
            )
        elif result.drawdown_factor == 0.0:
            drawdown_reason = f"组合回撤{context.portfolio_drawdown_pct:.1%}已超上限，暂停新仓"
        else:
            drawdown_reason = (
                f"组合回撤{context.portfolio_drawdown_pct:.1%}（系数{result.drawdown_factor:.2f}）"
            )

        return "；".join([regime_reason, pulse_reason, drawdown_reason])
