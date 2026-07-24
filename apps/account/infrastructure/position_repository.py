"""Position lifecycle repository owner."""

import logging
import warnings
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.account.domain.entities import (
    Position,
)
from apps.account.domain.interfaces import (
    VolatilityPositionRecord,
    VolatilityReductionBatchResult,
    VolatilityReductionInstruction,
    VolatilityReductionItem,
)
from apps.account.infrastructure.account_profile_repository import AccountRepository
from apps.account.infrastructure.models import (
    AssetMetadataModel,
    PortfolioModel,
    PositionModel,
    PositionSignalLogModel,
    TransactionModel,
)
from apps.account.infrastructure.portfolio_repository import PortfolioRepository
from apps.signal.infrastructure.models import InvestmentSignalModel

logger = logging.getLogger(__name__)


class PositionRepository:
    """持仓仓储"""

    def get_user_positions(
        self,
        user_id: int,
        status: str | None = None,
        asset_class: str | None = None,
    ) -> list[Position]:
        """获取用户持仓列表"""
        queryset = (
            PositionModel._default_manager.filter(portfolio__user_id=user_id)
            .select_related("portfolio")
            .order_by("-opened_at")
        )

        if status == "active":
            queryset = queryset.filter(is_closed=False)
        elif status == "closed":
            queryset = queryset.filter(is_closed=True)

        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)

        return PortfolioRepository()._convert_to_position_entities(list(queryset))

    def get_position_by_id(self, position_id: int) -> Position | None:
        """根据ID获取持仓"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
            return PortfolioRepository()._convert_to_position_entities([model])[0]
        except PositionModel.DoesNotExist:
            return None

    def get_user_position_by_asset_code(self, *, user_id: int, asset_code: str) -> Position | None:
        """Return one active user position by asset code."""

        model = (
            PositionModel._default_manager.filter(
                portfolio__user_id=user_id,
                asset_code=asset_code,
                is_closed=False,
            )
            .order_by("-opened_at")
            .first()
        )
        if model is None:
            return None
        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def list_open_positions_for_adjustment(
        self,
        portfolio_id: int,
    ) -> list[VolatilityPositionRecord]:
        """获取用于风控调仓的活跃持仓。"""
        models = PositionModel._default_manager.filter(
            portfolio_id=portfolio_id,
            is_closed=False,
        ).only("id", "asset_code", "shares", "current_price", "avg_cost")
        return [
            {
                "id": int(model.id),
                "asset_code": model.asset_code,
                "shares": float(model.shares),
                "current_price": (
                    Decimal(str(model.current_price)) if model.current_price is not None else None
                ),
                "avg_cost": Decimal(str(model.avg_cost)),
            }
            for model in models
        ]

    def execute_volatility_reduction(
        self,
        *,
        portfolio_id: int,
        user_id: int,
        idempotency_key: str,
        reason: str,
        instructions: list[VolatilityReductionInstruction],
    ) -> VolatilityReductionBatchResult:
        """Execute one portfolio-wide volatility reduction atomically and once."""

        notes = f"volatility_adjustment:{idempotency_key}: {reason}"
        requested_ids = {item["position_id"] for item in instructions}
        if not instructions or len(requested_ids) != len(instructions):
            raise ValueError("波动率调整指令为空或包含重复持仓")

        with transaction.atomic():
            try:
                PortfolioModel._default_manager.select_for_update().get(
                    id=portfolio_id,
                    user_id=user_id,
                )
            except PortfolioModel.DoesNotExist as exc:
                raise ValueError(f"投资组合 {portfolio_id} 不存在或无权限") from exc

            completed_ids = set(
                TransactionModel._default_manager.filter(
                    portfolio_id=portfolio_id,
                    position_id__in=requested_ids,
                    action="sell",
                    notes=notes,
                ).values_list("position_id", flat=True)
            )
            if completed_ids == requested_ids:
                return {
                    "status": "already_executed",
                    "reduced_positions": [],
                }
            if completed_ids:
                raise ValueError("检测到不完整的历史波动率调整批次")

            locked_positions = {
                int(position.id): position
                for position in PositionModel._default_manager.select_for_update().filter(
                    id__in=requested_ids,
                    portfolio_id=portfolio_id,
                    is_closed=False,
                )
            }
            if set(locked_positions) != requested_ids:
                raise ValueError("波动率调整持仓已变化，请重新分析后执行")

            reduced_positions: list[VolatilityReductionItem] = []
            for item in instructions:
                position = locked_positions[item["position_id"]]
                if position.asset_code != item["asset_code"]:
                    raise ValueError("波动率调整持仓标识不一致")
                if item["shares"] <= 0 or item["shares"] > float(position.shares):
                    raise ValueError("波动率调整数量已失效，请重新分析后执行")

                closed = self.close_position(
                    position_id=item["position_id"],
                    shares=item["shares"],
                    price=item["price"],
                    reason=notes,
                )
                if closed is None:
                    raise ValueError("波动率调整执行失败")
                reduced_positions.append(
                    {
                        "asset_code": item["asset_code"],
                        "shares_reduced": item["shares"],
                    }
                )

        return {
            "status": "executed",
            "reduced_positions": reduced_positions,
        }

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[dict[str, Any]]:
        """获取组合中各持仓的权重。"""
        positions = list(
            PositionModel._default_manager.filter(
                portfolio_id=portfolio_id,
                market_value__gt=0,
            ).values("asset_code", "market_value")
        )
        if not positions:
            return []

        total_value = sum(float(position["market_value"]) for position in positions)
        if total_value <= 0:
            return []

        return [
            {
                "asset_code": position["asset_code"],
                "weight": float(position["market_value"]) / total_value,
            }
            for position in positions
        ]

    def get_position_notification_context(self, position_id: int) -> dict[str, Any] | None:
        """获取持仓通知所需的最小上下文。"""
        try:
            model = PositionModel._default_manager.select_related("portfolio__user").get(
                id=position_id
            )
        except PositionModel.DoesNotExist:
            return None

        return {
            "id": model.id,
            "asset_code": model.asset_code,
            "user_id": model.portfolio.user_id,
            "user_email": model.portfolio.user.email,
            "portfolio_id": model.portfolio_id,
            "portfolio_name": model.portfolio.name,
        }

    def get_position_stop_management_context(self, position_id: int) -> dict[str, Any] | None:
        """Return stop-loss/take-profit management context for one position."""

        try:
            model = PositionModel._default_manager.select_related("portfolio__user").get(
                id=position_id
            )
        except PositionModel.DoesNotExist:
            return None

        return {
            "id": model.id,
            "asset_code": model.asset_code,
            "shares": model.shares,
            "avg_cost": model.avg_cost,
            "current_price": model.current_price,
            "opened_at": model.opened_at,
            "portfolio_id": model.portfolio_id,
            "user_id": model.portfolio.user_id,
            "user_email": model.portfolio.user.email,
        }

    def create_position_legacy(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: int | None = None,
    ) -> Position:
        """Create a position in the legacy `apps/account` ledger tables."""
        # 获取资产元数据
        try:
            asset_meta = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            # 如果元数据不存在，使用默认值
            asset_meta = None

        model = PositionModel._default_manager.create(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            asset_class=asset_meta.asset_class if asset_meta else "equity",
            region=asset_meta.region if asset_meta else "CN",
            cross_border=asset_meta.cross_border if asset_meta else "domestic",
            shares=shares,
            avg_cost=price,
            current_price=price,
            market_value=Decimal(str(shares * float(price))),
            source=source,
            source_id=source_id,
        )

        # 创建交易记录
        TransactionModel._default_manager.create(
            portfolio_id=portfolio_id,
            position_id=model.id,
            action="buy",
            asset_code=asset_code,
            shares=shares,
            price=price,
            notional=Decimal(str(shares * float(price))),
            traded_at=timezone.now(),
            notes=f"开仓 ({source})",
        )

        # 更新持仓状态为活跃
        model.is_closed = False
        model.save()

        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: int | None = None,
    ) -> Position:
        """创建新持仓

        .. deprecated::
            此方法写入旧账本表（apps/account）。
            新代码请使用 UnifiedPositionService（apps/simulated_trading）。
            旧路径将于 2026-09-27 停用。
        """
        warnings.warn(
            "PositionRepository.create_position() is deprecated and will be removed on 2026-09-27. "
            "Use apps.simulated_trading.application.unified_position_service.UnifiedPositionService instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.create_position_legacy(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            shares=shares,
            price=price,
            source=source,
            source_id=source_id,
        )

    def close_position(
        self,
        position_id: int,
        shares: float | None = None,
        price: Decimal | None = None,
        reason: str | None = None,
    ) -> Position | None:
        """平仓（全部或部分）"""
        try:
            model = PositionModel._default_manager.select_related("portfolio").get(id=position_id)
        except PositionModel.DoesNotExist:
            return None

        if model.is_closed:
            return PortfolioRepository()._convert_to_position_entities([model])[0]

        close_shares = model.shares if shares is None else min(float(shares), model.shares)
        if close_shares <= 0:
            return PortfolioRepository()._convert_to_position_entities([model])[0]

        execution_price = price or model.current_price or model.avg_cost
        execution_price = Decimal(str(execution_price))
        notes = reason or "平仓"
        now = timezone.now()

        with transaction.atomic():
            TransactionModel._default_manager.create(
                portfolio_id=model.portfolio_id,
                position_id=model.id,
                action="sell",
                asset_code=model.asset_code,
                shares=close_shares,
                price=execution_price,
                notional=Decimal(str(close_shares)) * execution_price,
                traded_at=now,
                notes=notes,
            )

            model.current_price = execution_price
            if close_shares >= model.shares:
                model.is_closed = True
                model.closed_at = now
            else:
                model.shares -= close_shares

            # Recalculate derived fields
            from shared.domain.position_calculations import recalculate_derived_fields

            mv, pnl, pnl_pct = recalculate_derived_fields(
                shares=model.shares if not model.is_closed else 0,
                avg_cost=float(model.avg_cost),
                current_price=float(execution_price),
            )
            model.market_value = mv
            model.unrealized_pnl = pnl
            model.unrealized_pnl_pct = pnl_pct
            model.save()

        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def update_position_price(self, position_id: int, new_price: Decimal) -> Position | None:
        """更新持仓当前价格并重算盈亏"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
        except PositionModel.DoesNotExist:
            return None

        model.current_price = new_price
        model.market_value = Decimal(str(model.shares * float(new_price)))

        # 计算盈亏
        pnl = (new_price - model.avg_cost) * Decimal(str(model.shares))
        model.unrealized_pnl = pnl
        model.unrealized_pnl_pct = float((new_price / model.avg_cost - 1) * 100)

        model.save()
        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def create_position_from_signal(
        self,
        user_id: int,
        signal_id: int,
        price: Decimal,
    ) -> Position | None:
        """从投资信号创建持仓"""
        try:
            signal = InvestmentSignalModel._default_manager.get(id=signal_id, user_id=user_id)
        except InvestmentSignalModel.DoesNotExist:
            return None

        # 获取用户默认组合
        account_repo = AccountRepository()
        portfolio_id = account_repo.get_or_create_default_portfolio(user_id)

        # 计算仓位（使用默认策略）
        profile = account_repo.get_by_user_id(user_id)
        if profile is None:
            raise ValueError(f"用户 {user_id} 账户配置不存在")
        max_notional = float(profile.initial_capital) * 0.1  # 默认10%
        shares = int(max_notional / float(price))

        # 创建持仓
        position = self.create_position_legacy(
            portfolio_id=portfolio_id,
            asset_code=signal.asset_code,
            shares=shares,
            price=price,
            source="signal",
            source_id=signal_id,
        )
        if position.id is None:
            raise ValueError("新建持仓缺少主键")

        # 记录信号关联
        PositionSignalLogModel._default_manager.create(
            signal_id=signal_id,
            position_id=position.id,
            notes=f"从信号 {signal_id} 创建",
        )

        return position

    def update_or_create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        avg_cost: Decimal,
        current_price: Decimal,
        source: str = "signal",
    ) -> Position:
        """
        更新或创建持仓（P2-11: 添加此方法以支持架构合规）

        Args:
            portfolio_id: 投资组合 ID
            asset_code: 资产代码
            shares: 持仓数量
            avg_cost: 平均成本
            current_price: 当前价格
            source: 来源

        Returns:
            Position 实体
        """
        # 获取资产元数据
        try:
            asset_meta = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            asset_meta = None

        # 创建或更新持仓
        model, created = PositionModel._default_manager.update_or_create(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            defaults={
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": Decimal(str(shares * float(current_price))),
                "asset_class": asset_meta.asset_class if asset_meta else "equity",
                "region": asset_meta.region if asset_meta else "CN",
                "cross_border": asset_meta.cross_border if asset_meta else "domestic",
                "source": source,
                "is_closed": False,
            },
        )

        return PortfolioRepository()._convert_to_position_entities([model])[0]
