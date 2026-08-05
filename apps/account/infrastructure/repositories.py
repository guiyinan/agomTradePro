"""Compatibility exports plus focused transaction, risk, and settings repositories."""

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.account.domain.entities import (
    DrawdownTier,
    MacroSizingConfig,
    MarketTemperatureTier,
    PulseTier,
    RegimeTier,
    Transaction,
)
from apps.account.domain.transaction_cost_contracts import (
    TransactionCostConfigRecord,
    TransactionCostRecord,
)
from apps.account.infrastructure.account_interface_repository import (
    AccountInterfaceRepository as AccountInterfaceRepository,
)
from apps.account.infrastructure.account_profile_repository import (
    AccountClassificationRepository as AccountClassificationRepository,
)
from apps.account.infrastructure.account_profile_repository import (
    AccountRepository as AccountRepository,
)
from apps.account.infrastructure.asset_metadata_repository import (
    AssetMetadataRepository as AssetMetadataRepository,
)
from apps.account.infrastructure.models import (
    BrokerTradeImportBatchModel,
    MacroSizingConfigModel,
    PortfolioDailySnapshotModel,
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
    TransactionCostConfigModel,
    TransactionModel,
)
from apps.account.infrastructure.portfolio_api_repository import (
    PortfolioApiRepository as PortfolioApiRepository,
)
from apps.account.infrastructure.portfolio_repository import (
    PortfolioRepository as PortfolioRepository,
)
from apps.account.infrastructure.position_repository import PositionRepository as PositionRepository
from apps.config_center.application.public import get_runtime_asset_proxy_map
from apps.config_center.infrastructure.models import SystemSettingsModel

logger = logging.getLogger(__name__)


class TransactionRepository:
    """交易记录仓储"""

    def get_portfolio_transactions(
        self,
        portfolio_id: int,
        limit: int = 50,
    ) -> list[Transaction]:
        """获取组合交易记录"""
        models = (
            TransactionModel._default_manager.filter(portfolio_id=portfolio_id)
            .select_related("position")
            .order_by("-traded_at")[:limit]
        )

        transactions = []
        for model in models:
            transactions.append(
                Transaction(
                    id=model.id,
                    portfolio_id=model.portfolio_id,
                    user_id=model.portfolio.user_id,
                    position_id=model.position_id,
                    asset_code=model.asset_code,
                    action=model.action,
                    shares=model.shares,
                    price=model.price,
                    notional=model.notional,
                    commission=model.commission,
                    traded_at=model.traded_at,
                    notes=model.notes,
                )
            )
        return transactions

    def get_transaction_cost_record(self, transaction_id: int) -> TransactionCostRecord | None:
        """获取交易成本分析所需的交易明细。"""
        try:
            model = TransactionModel._default_manager.get(id=transaction_id)
        except TransactionModel.DoesNotExist:
            return None

        return self._to_transaction_cost_dict(model)

    def update_transaction_costs(
        self,
        transaction_id: int,
        *,
        commission: Decimal,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
    ) -> TransactionCostRecord | None:
        """更新交易的实际成本并返回最新明细。"""
        try:
            model = TransactionModel._default_manager.get(id=transaction_id)
        except TransactionModel.DoesNotExist:
            return None

        model.commission = commission
        if slippage is not None:
            model.slippage = slippage
        if stamp_duty is not None:
            model.stamp_duty = stamp_duty
        if transfer_fee is not None:
            model.transfer_fee = transfer_fee

        total_actual = (
            commission
            + (slippage or Decimal("0"))
            + (stamp_duty or Decimal("0"))
            + (transfer_fee or Decimal("0"))
        )
        if model.estimated_cost:
            variance = total_actual - model.estimated_cost
            variance_pct = (
                float(variance) / float(model.estimated_cost) if model.estimated_cost > 0 else 0
            )
            model.cost_variance = variance
            model.cost_variance_pct = variance_pct

        model.save()
        return self._to_transaction_cost_dict(model)

    def list_user_transaction_costs(
        self,
        user_id: int,
        *,
        portfolio_id: int | None = None,
        since_date: datetime | None = None,
    ) -> list[TransactionCostRecord]:
        """列出用户指定时间范围内的交易成本明细。"""
        queryset = TransactionModel._default_manager.filter(portfolio__user_id=user_id)
        if portfolio_id is not None:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        if since_date is not None:
            queryset = queryset.filter(created_at__gte=since_date)
        return [
            self._to_transaction_cost_dict(model)
            for model in queryset.order_by("-created_at").all()
        ]

    @staticmethod
    def _to_transaction_cost_dict(model: TransactionModel) -> TransactionCostRecord:
        """转换为交易成本分析用的字典。"""
        return {
            "id": model.id,
            "portfolio_id": model.portfolio_id,
            "position_id": model.position_id,
            "asset_code": model.asset_code,
            "action": model.action,
            "notional": model.notional,
            "commission": model.commission,
            "slippage": model.slippage,
            "stamp_duty": model.stamp_duty,
            "transfer_fee": model.transfer_fee,
            "estimated_cost": model.estimated_cost,
            "cost_variance": model.cost_variance,
            "cost_variance_pct": model.cost_variance_pct,
            "traded_at": model.traded_at,
        }


class ManualTradeSyncRepository:
    """Persistence operations for manual broker trade imports."""

    @contextmanager
    def atomic_import_row(self, *, portfolio_id: int) -> Iterator[None]:
        """Serialize and atomically persist every side effect for one import row."""

        with transaction.atomic():
            PortfolioModel._default_manager.select_for_update().get(id=portfolio_id)
            yield

    def get_owned_portfolio(self, *, user_id: int, portfolio_id: int) -> PortfolioModel | None:
        return PortfolioModel._default_manager.filter(id=portfolio_id, user_id=user_id).first()

    def broker_trade_key_exists(self, broker_trade_key: str) -> bool:
        return bool(
            TransactionModel._default_manager.filter(
                broker_trade_key=broker_trade_key,
            ).exists()
        )

    def create_import_batch(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        source_filename: str,
        file_hash: str,
        total_rows: int,
        preview_rows: list[dict[str, Any]],
    ) -> BrokerTradeImportBatchModel:
        batch, _ = BrokerTradeImportBatchModel._default_manager.update_or_create(
            user_id=user_id,
            portfolio_id=portfolio_id,
            file_hash=file_hash,
            defaults={
                "broker_name": broker_name,
                "source_filename": source_filename,
                "status": "previewed",
                "total_rows": total_rows,
                "imported_rows": 0,
                "skipped_rows": 0,
                "error_rows": 0,
                "errors": [],
                "preview_rows": preview_rows,
            },
        )
        return batch

    def update_import_batch_result(
        self,
        batch: BrokerTradeImportBatchModel,
        *,
        imported_rows: int,
        skipped_rows: int,
        error_rows: int,
        errors: list[dict[str, Any]],
    ) -> BrokerTradeImportBatchModel:
        batch.imported_rows = imported_rows
        batch.skipped_rows = skipped_rows
        batch.error_rows = error_rows
        batch.errors = errors
        if error_rows and imported_rows:
            batch.status = "completed_with_errors"
        elif error_rows and not imported_rows:
            batch.status = "failed"
        else:
            batch.status = "completed"
        batch.save(
            update_fields=[
                "imported_rows",
                "skipped_rows",
                "error_rows",
                "errors",
                "status",
                "updated_at",
            ]
        )
        return batch

    def create_imported_transaction(
        self,
        *,
        portfolio: PortfolioModel,
        position: PositionModel | None = None,
        action: str,
        asset_code: str,
        shares: float,
        price: Decimal,
        commission: Decimal,
        stamp_duty: Decimal,
        transfer_fee: Decimal,
        traded_at: datetime,
        notes: str,
        broker_name: str,
        external_trade_id: str,
        broker_trade_key: str,
        raw_payload: dict[str, Any],
        import_batch: BrokerTradeImportBatchModel,
    ) -> TransactionModel:
        return TransactionModel._default_manager.create(
            portfolio=portfolio,
            position=position,
            action=action,
            asset_code=asset_code,
            shares=shares,
            price=price,
            notional=Decimal(str(shares)) * price,
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            traded_at=traded_at,
            notes=notes,
            broker_name=broker_name,
            external_trade_id=external_trade_id,
            broker_trade_key=broker_trade_key,
            raw_payload=raw_payload,
            import_batch=import_batch,
        )

    def list_recent_import_batches(
        self, *, user_id: int, limit: int = 20
    ) -> list[BrokerTradeImportBatchModel]:
        return list(
            BrokerTradeImportBatchModel._default_manager.filter(user_id=user_id)
            .select_related("portfolio")
            .order_by("-created_at")[:limit]
        )

    def list_imported_transactions(
        self, *, user_id: int, limit: int = 50
    ) -> list[TransactionModel]:
        return list(
            TransactionModel._default_manager.filter(
                portfolio__user_id=user_id,
                import_batch__isnull=False,
            )
            .select_related("portfolio", "import_batch")
            .order_by("-traded_at")[:limit]
        )

    def list_imported_transactions_for_portfolio(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        start_date: date,
        end_date: date,
    ) -> list[TransactionModel]:
        return list(
            TransactionModel._default_manager.filter(
                portfolio_id=portfolio_id,
                portfolio__user_id=user_id,
                import_batch__isnull=False,
                traded_at__date__gte=start_date,
                traded_at__date__lte=end_date,
            )
            .select_related("portfolio", "import_batch")
            .order_by("traded_at", "id")
        )


class StopLossRepository:
    """止损配置仓储"""

    def get_active_stop_loss_configs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """
        Get all active stop loss configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of stop loss config dicts with position relationship
        """
        queryset = StopLossConfigModel._default_manager.filter(
            status="active",
            position__is_closed=False,
        )

        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        configs = queryset.select_related("position", "position__portfolio").all()

        return [
            {
                "id": config.id,
                "position_id": config.position_id,
                "stop_loss_type": config.stop_loss_type,
                "stop_loss_pct": config.stop_loss_pct,
                "trailing_stop_pct": config.trailing_stop_pct,
                "max_holding_days": config.max_holding_days,
                "highest_price": config.highest_price,
                "highest_price_updated_at": config.highest_price_updated_at,
                "status": config.status,
                "position": {
                    "id": config.position.id,
                    "asset_code": config.position.asset_code,
                    "shares": config.position.shares,
                    "avg_cost": config.position.avg_cost,
                    "current_price": config.position.current_price,
                    "opened_at": config.position.opened_at,
                    "portfolio_id": config.position.portfolio_id,
                    "user_id": config.position.portfolio.user_id,
                    "user_email": config.position.portfolio.user.email,
                },
            }
            for config in configs
        ]

    def get_stop_loss_config_by_position(self, position_id: int) -> dict[str, Any] | None:
        """Get stop loss config for a position."""
        try:
            config = StopLossConfigModel._default_manager.get(position_id=position_id)
            return {
                "id": config.id,
                "position_id": config.position_id,
                "stop_loss_type": config.stop_loss_type,
                "stop_loss_pct": config.stop_loss_pct,
                "trailing_stop_pct": config.trailing_stop_pct,
                "max_holding_days": config.max_holding_days,
                "highest_price": config.highest_price,
                "status": config.status,
            }
        except StopLossConfigModel.DoesNotExist:
            return None

    def create_stop_loss_config(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
        highest_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Create stop loss configuration."""
        config = StopLossConfigModel._default_manager.create(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=highest_price,
            status="active",
        )
        return {
            "id": config.id,
            "position_id": config.position_id,
            "stop_loss_type": config.stop_loss_type,
            "stop_loss_pct": config.stop_loss_pct,
            "status": config.status,
        }

    def update_stop_loss_config(
        self,
        config_id: int,
        status: str | None = None,
        highest_price: Decimal | None = None,
        highest_price_updated_at: Any | None = None,
        triggered_at: Any | None = None,
    ) -> bool:
        """Update stop loss configuration."""
        try:
            config = StopLossConfigModel._default_manager.get(id=config_id)
            if status is not None:
                config.status = status
            if highest_price is not None:
                config.highest_price = highest_price
            if highest_price_updated_at is not None:
                config.highest_price_updated_at = highest_price_updated_at
            if triggered_at is not None:
                config.triggered_at = triggered_at
            config.save()
            return True
        except StopLossConfigModel.DoesNotExist:
            return False

    def create_stop_loss_trigger(
        self,
        position_id: int,
        trigger_type: str,
        trigger_price: Decimal,
        trigger_reason: str,
        pnl: Decimal,
        pnl_pct: float,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create stop loss trigger record."""
        trigger = StopLossTriggerModel._default_manager.create(
            position_id=position_id,
            trigger_type=trigger_type,
            trigger_price=trigger_price,
            trigger_time=timezone.now(),
            trigger_reason=trigger_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
            notes=notes,
        )
        return {
            "id": trigger.id,
            "position_id": trigger.position_id,
            "trigger_type": trigger.trigger_type,
            "trigger_price": trigger.trigger_price,
            "trigger_time": trigger.trigger_time,
        }


class TakeProfitRepository:
    """止盈配置仓储"""

    def get_active_take_profit_configs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """
        Get all active take profit configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of take profit config dicts with position relationship
        """
        queryset = TakeProfitConfigModel._default_manager.filter(
            is_active=True,
            position__is_closed=False,
        )

        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        configs = queryset.select_related("position", "position__portfolio").all()

        return [
            {
                "id": config.id,
                "position_id": config.position_id,
                "take_profit_pct": config.take_profit_pct,
                "partial_profit_levels": config.partial_profit_levels,
                "is_active": config.is_active,
                "position": {
                    "id": config.position.id,
                    "asset_code": config.position.asset_code,
                    "shares": config.position.shares,
                    "avg_cost": config.position.avg_cost,
                    "current_price": config.position.current_price,
                    "opened_at": config.position.opened_at,
                    "portfolio_id": config.position.portfolio_id,
                    "user_id": config.position.portfolio.user_id,
                    "user_email": config.position.portfolio.user.email,
                },
            }
            for config in configs
        ]

    def get_take_profit_config_by_position(self, position_id: int) -> dict[str, Any] | None:
        """Get take profit config for a position."""
        try:
            config = TakeProfitConfigModel._default_manager.get(position_id=position_id)
            return {
                "id": config.id,
                "position_id": config.position_id,
                "take_profit_pct": config.take_profit_pct,
                "partial_profit_levels": config.partial_profit_levels,
                "is_active": config.is_active,
            }
        except TakeProfitConfigModel.DoesNotExist:
            return None

    def create_take_profit_config(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create take profit configuration."""
        config = TakeProfitConfigModel._default_manager.create(
            position_id=position_id,
            take_profit_pct=take_profit_pct,
            partial_profit_levels=partial_profit_levels,
            is_active=True,
        )
        return {
            "id": config.id,
            "position_id": config.position_id,
            "take_profit_pct": config.take_profit_pct,
            "is_active": config.is_active,
        }

    def update_take_profit_config(
        self,
        config_id: int,
        is_active: bool | None = None,
    ) -> bool:
        """Update take profit configuration."""
        try:
            config = TakeProfitConfigModel._default_manager.get(id=config_id)
            if is_active is not None:
                config.is_active = is_active
            config.save()
            return True
        except TakeProfitConfigModel.DoesNotExist:
            return False

    def execute_take_profit_tranche(
        self,
        *,
        config_id: int,
        position_id: int,
        expected_partial_levels: list[float] | None,
        remaining_partial_levels: list[float],
        shares: float | None,
        price: Decimal,
        reason: str,
        deactivate: bool,
    ) -> bool:
        """Atomically close one tranche and advance its take-profit configuration."""

        with transaction.atomic():
            config = (
                TakeProfitConfigModel._default_manager.select_for_update()
                .select_related("position")
                .filter(
                    id=config_id,
                    position_id=position_id,
                    is_active=True,
                    position__is_closed=False,
                )
                .first()
            )
            if config is None:
                return False

            persisted_levels = [float(level) for level in (config.partial_profit_levels or [])]
            expected_levels = [float(level) for level in (expected_partial_levels or [])]
            if persisted_levels != expected_levels:
                return False

            closed_position = PositionRepository().close_position(
                position_id=position_id,
                shares=shares,
                price=price,
                reason=reason,
            )
            if closed_position is None:
                return False

            config.partial_profit_levels = remaining_partial_levels
            config.is_active = not deactivate
            config.save(
                update_fields=[
                    "partial_profit_levels",
                    "is_active",
                    "updated_at",
                ]
            )
            return True


class PortfolioSnapshotRepository:
    """投资组合快照仓储"""

    def get_snapshots_for_volatility(
        self,
        portfolio_id: int,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """
        Get portfolio daily snapshots for volatility calculation.

        Returns:
            List of dicts with snapshot_date, total_value
        """
        snapshots = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by("-snapshot_date")[:days]

        return [
            {
                "snapshot_date": snap.snapshot_date,
                "total_value": float(snap.total_value),
            }
            for snap in reversed(list(snapshots))
        ]

    def list_performance_rows(self, portfolio_id: int) -> list[dict[str, Any]]:
        """Return ordered snapshot rows for dashboard performance charts."""

        snapshots = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by("snapshot_date")
        return [
            {
                "snapshot_date": snapshot.snapshot_date,
                "total_value": float(snapshot.total_value or 0),
                "cash_balance": float(snapshot.cash_balance or 0),
                "invested_value": float(snapshot.invested_value or 0),
                "position_count": int(snapshot.position_count or 0),
            }
            for snapshot in snapshots
        ]


class TransactionCostConfigRepository:
    """交易成本配置仓储"""

    def get_cost_config(self, market: str, asset_class: str) -> TransactionCostConfigRecord | None:
        """
        Get transaction cost configuration for market and asset class.

        Returns:
            Dict with commission_rate, slippage_rate, etc., or None
        """
        try:
            config = TransactionCostConfigModel._default_manager.get(
                market=market,
                asset_class=asset_class,
                is_active=True,
            )
            return {
                "id": config.id,
                "market": config.market,
                "asset_class": config.asset_class,
                "commission_rate": Decimal(str(config.commission_rate)),
                "slippage_rate": Decimal(str(config.slippage_rate)),
                "stamp_duty_rate": Decimal(str(config.stamp_duty_rate)),
                "transfer_fee_rate": Decimal(str(config.transfer_fee_rate)),
                "min_commission": config.min_commission,
                "cost_warning_threshold": config.cost_warning_threshold,
            }
        except TransactionCostConfigModel.DoesNotExist:
            return None


class SystemSettingsRepository:
    """系统设置仓储。"""

    def get_settings(self) -> SystemSettingsModel:
        """返回系统设置模型实例。"""

        get_settings = cast(Callable[[], SystemSettingsModel], SystemSettingsModel.get_settings)
        return get_settings()

    def get_runtime_asset_proxy_code(self, asset_class: str, default: str = "") -> str:
        """获取运行时资产代理代码。"""

        value = get_runtime_asset_proxy_map().get(asset_class)
        return str(value) if isinstance(value, str) and value else default


class MacroSizingConfigRepository:
    """宏观仓位系数配置仓储。"""

    _DEFAULT_REGIME_TIERS = [
        {"min_confidence": 0.6, "factor": 1.0},
        {"min_confidence": 0.4, "factor": 0.8},
        {"min_confidence": 0.0, "factor": 0.5},
    ]
    _DEFAULT_PULSE_TIERS = [
        {"min_composite": 0.3, "max_composite": 99, "factor": 1.0},
        {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
        {"min_composite": -99, "max_composite": -0.3, "factor": 0.7},
    ]
    _DEFAULT_DRAWDOWN_TIERS = [
        {"min_drawdown": 0.15, "factor": 0.0},
        {"min_drawdown": 0.1, "factor": 0.5},
        {"min_drawdown": 0.05, "factor": 0.8},
        {"min_drawdown": 0.0, "factor": 1.0},
    ]
    _DEFAULT_MARKET_TEMPERATURE_TIERS = [
        {"band": "cold", "factor": 1.0, "block_new_position": False},
        {"band": "warm", "factor": 1.0, "block_new_position": False},
        {"band": "hot", "factor": 0.9, "block_new_position": False},
        {"band": "overheat", "factor": 0.75, "block_new_position": False},
        {"band": "extreme", "factor": 0.35, "block_new_position": True},
    ]

    def get_active_config(self) -> MacroSizingConfig:
        """返回当前生效配置；若库中不存在则返回默认配置。"""
        model = self._get_active_model()
        if model is None:
            return self._build_config(
                regime_tiers=self._DEFAULT_REGIME_TIERS,
                pulse_tiers=self._DEFAULT_PULSE_TIERS,
                warning_factor=0.5,
                drawdown_tiers=self._DEFAULT_DRAWDOWN_TIERS,
                market_temperature_tiers=self._DEFAULT_MARKET_TEMPERATURE_TIERS,
                version=1,
            )
        return self._to_entity(model)

    def get_active_config_payload(self) -> dict[str, Any]:
        """返回当前生效配置的 API 载荷。"""

        model = self._get_active_model()
        if model is None:
            return self._serialize_payload(
                {
                    "id": None,
                    "version": 1,
                    "is_active": True,
                    "description": "",
                    "warning_factor": 0.5,
                    "regime_tiers_json": self._DEFAULT_REGIME_TIERS,
                    "pulse_tiers_json": self._DEFAULT_PULSE_TIERS,
                    "drawdown_tiers_json": self._DEFAULT_DRAWDOWN_TIERS,
                    "market_temperature_cold_factor": 1.0,
                    "market_temperature_warm_factor": 1.0,
                    "market_temperature_hot_factor": 0.9,
                    "market_temperature_overheat_factor": 0.75,
                    "market_temperature_extreme_factor": 0.35,
                    "block_new_position_on_extreme": True,
                    "created_at": None,
                    "updated_at": None,
                }
            )
        return self._serialize_model(model)

    def save_active_config_payload(self, *, validated_data: Mapping[str, Any]) -> dict[str, Any]:
        """创建新的生效版本并返回其 API 载荷。"""

        current = self._get_active_model()
        payload = self.get_active_config_payload()
        payload.update(dict(validated_data))
        payload.pop("id", None)
        payload.pop("created_at", None)
        payload.pop("updated_at", None)
        payload["version"] = (current.version + 1) if current is not None else 1
        payload["is_active"] = True
        self._validate_config_payload(payload)

        with transaction.atomic():
            MacroSizingConfigModel._default_manager.filter(is_active=True).update(is_active=False)
            created = MacroSizingConfigModel._default_manager.create(**payload)

        return self._serialize_model(created)

    def _validate_config_payload(self, payload: Mapping[str, Any]) -> None:
        """Build the Domain value object before changing the active version."""

        self._build_config(
            regime_tiers=self._require_tier_rows(payload, "regime_tiers_json"),
            pulse_tiers=self._require_tier_rows(payload, "pulse_tiers_json"),
            warning_factor=float(payload["warning_factor"]),
            drawdown_tiers=self._require_tier_rows(payload, "drawdown_tiers_json"),
            market_temperature_tiers=[
                {
                    "band": "cold",
                    "factor": payload["market_temperature_cold_factor"],
                    "block_new_position": False,
                },
                {
                    "band": "warm",
                    "factor": payload["market_temperature_warm_factor"],
                    "block_new_position": False,
                },
                {
                    "band": "hot",
                    "factor": payload["market_temperature_hot_factor"],
                    "block_new_position": False,
                },
                {
                    "band": "overheat",
                    "factor": payload["market_temperature_overheat_factor"],
                    "block_new_position": False,
                },
                {
                    "band": "extreme",
                    "factor": payload["market_temperature_extreme_factor"],
                    "block_new_position": payload["block_new_position_on_extreme"],
                },
            ],
            version=int(payload["version"]),
        )

    @staticmethod
    def _require_tier_rows(
        payload: Mapping[str, Any],
        field_name: str,
    ) -> list[dict[str, Any]]:
        """Return a non-empty list of object-shaped sizing tiers."""

        value = payload.get(field_name)
        if not isinstance(value, list) or not value:
            raise ValueError(f"{field_name} 必须是非空对象数组")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{field_name} 每一项都必须是对象")
        return [dict(item) for item in value]

    def _get_active_model(self) -> MacroSizingConfigModel | None:
        try:
            return (
                MacroSizingConfigModel._default_manager.filter(is_active=True)
                .order_by("-version")
                .first()
            )
        except (OperationalError, ProgrammingError):
            logger.warning("MacroSizingConfigModel table unavailable; using default sizing config")
            return None

    def _serialize_model(self, model: MacroSizingConfigModel) -> dict[str, Any]:
        return self._serialize_payload(
            {
                "id": model.id,
                "version": model.version,
                "is_active": model.is_active,
                "description": model.description,
                "warning_factor": model.warning_factor,
                "regime_tiers_json": model.regime_tiers_json,
                "pulse_tiers_json": model.pulse_tiers_json,
                "drawdown_tiers_json": model.drawdown_tiers_json,
                "market_temperature_cold_factor": model.market_temperature_cold_factor,
                "market_temperature_warm_factor": model.market_temperature_warm_factor,
                "market_temperature_hot_factor": model.market_temperature_hot_factor,
                "market_temperature_overheat_factor": model.market_temperature_overheat_factor,
                "market_temperature_extreme_factor": model.market_temperature_extreme_factor,
                "block_new_position_on_extreme": model.block_new_position_on_extreme,
                "created_at": model.created_at,
                "updated_at": model.updated_at,
            }
        )

    @staticmethod
    def _serialize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        serialized = dict(payload)
        for key in ("created_at", "updated_at"):
            value = serialized.get(key)
            serialized[key] = value.isoformat() if value is not None else None
        return serialized

    def _to_entity(self, model: MacroSizingConfigModel) -> MacroSizingConfig:
        return self._build_config(
            regime_tiers=model.regime_tiers_json,
            pulse_tiers=model.pulse_tiers_json,
            warning_factor=model.warning_factor,
            drawdown_tiers=model.drawdown_tiers_json,
            market_temperature_tiers=[
                {
                    "band": "cold",
                    "factor": model.market_temperature_cold_factor,
                    "block_new_position": False,
                },
                {
                    "band": "warm",
                    "factor": model.market_temperature_warm_factor,
                    "block_new_position": False,
                },
                {
                    "band": "hot",
                    "factor": model.market_temperature_hot_factor,
                    "block_new_position": False,
                },
                {
                    "band": "overheat",
                    "factor": model.market_temperature_overheat_factor,
                    "block_new_position": False,
                },
                {
                    "band": "extreme",
                    "factor": model.market_temperature_extreme_factor,
                    "block_new_position": model.block_new_position_on_extreme,
                },
            ],
            version=model.version,
        )

    def _build_config(
        self,
        *,
        regime_tiers: list[dict[str, Any]],
        pulse_tiers: list[dict[str, Any]],
        warning_factor: float,
        drawdown_tiers: list[dict[str, Any]],
        market_temperature_tiers: list[dict[str, Any]],
        version: int,
    ) -> MacroSizingConfig:
        return MacroSizingConfig(
            regime_tiers=[
                RegimeTier(
                    min_confidence=float(item["min_confidence"]),
                    factor=float(item["factor"]),
                )
                for item in regime_tiers
            ],
            pulse_tiers=[
                PulseTier(
                    min_composite=float(item["min_composite"]),
                    max_composite=float(item.get("max_composite", item["min_composite"])),
                    factor=float(item["factor"]),
                )
                for item in pulse_tiers
            ],
            warning_factor=float(warning_factor),
            drawdown_tiers=[
                DrawdownTier(
                    min_drawdown=float(item["min_drawdown"]),
                    factor=float(item["factor"]),
                )
                for item in drawdown_tiers
            ],
            market_temperature_tiers=[
                MarketTemperatureTier(
                    band=str(item["band"]),
                    factor=float(item["factor"]),
                    block_new_position=self._require_bool(
                        item.get("block_new_position", False),
                        field_name="block_new_position",
                    ),
                )
                for item in market_temperature_tiers
            ],
            version=version,
        )

    @staticmethod
    def _require_bool(value: Any, *, field_name: str) -> bool:
        """Reject truthy strings in persisted configuration JSON."""

        if not isinstance(value, bool):
            raise ValueError(f"{field_name} 必须是布尔值")
        return value


__all__ = [
    "AccountRepository",
    "AccountClassificationRepository",
    "PortfolioRepository",
    "PositionRepository",
    "PortfolioApiRepository",
    "TransactionRepository",
    "ManualTradeSyncRepository",
    "AssetMetadataRepository",
    "StopLossRepository",
    "TakeProfitRepository",
    "PortfolioSnapshotRepository",
    "TransactionCostConfigRepository",
    "SystemSettingsRepository",
    "MacroSizingConfigRepository",
    "AccountInterfaceRepository",
]
