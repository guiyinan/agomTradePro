"""Focused persistence methods for canonical transaction records."""

from __future__ import annotations

from decimal import Decimal

from django.db import router, transaction

import core.exceptions as core_exceptions
from apps.account.domain.transaction_record_contracts import (
    NewTransactionRecord,
    TransactionPage,
    TransactionRecord,
)
from apps.account.infrastructure.models import PortfolioModel, PositionModel, TransactionModel


class TransactionRecordRepositoryMixin:
    """Create and read typed transaction records through the Account ORM models."""

    def create_transaction(self, record: NewTransactionRecord) -> TransactionRecord:
        """Create a new account transaction after locked owner rechecks."""
        using = router.db_for_write(TransactionModel)
        with transaction.atomic(using=using):
            try:
                portfolio = (
                    PortfolioModel._default_manager.using(using)
                    .select_for_update(no_key=True)
                    .get(id=record.portfolio_id)
                )
            except PortfolioModel.DoesNotExist as exc:
                raise core_exceptions.InvalidInputError(
                    "投资组合不存在",
                    details={"field": "portfolio"},
                ) from exc
            if portfolio.user_id != record.actor_user_id:
                raise core_exceptions.AuthorizationError("无权为此投资组合创建交易记录")

            position: PositionModel | None = None
            if record.position_id is not None:
                position = (
                    PositionModel._default_manager.using(using)
                    .select_for_update(no_key=True)
                    .filter(id=record.position_id, portfolio_id=portfolio.id)
                    .first()
                )
                if position is None:
                    try:
                        observed_position = (
                            PositionModel._default_manager.using(using)
                            .select_related("portfolio")
                            .get(id=record.position_id)
                        )
                    except PositionModel.DoesNotExist as exc:
                        raise core_exceptions.InvalidInputError(
                            "持仓不存在",
                            details={"field": "position"},
                        ) from exc
                    try:
                        position_owner_id = observed_position.portfolio.user_id
                    except PortfolioModel.DoesNotExist as exc:
                        raise core_exceptions.InvalidInputError(
                            "持仓所属投资组合不存在",
                            details={"field": "position"},
                        ) from exc
                    if position_owner_id != record.actor_user_id:
                        raise core_exceptions.AuthorizationError("无权为此持仓创建交易记录")
                    raise core_exceptions.InvalidInputError(
                        "持仓不属于该投资组合",
                        details={"field": "position"},
                    )
                if position.asset_code != record.asset_code:
                    raise core_exceptions.InvalidInputError(
                        "资产代码与关联持仓不一致",
                        details={"field": "asset_code"},
                    )

            model = TransactionModel._default_manager.using(using).create(
                portfolio=portfolio,
                position=position,
                action=record.action,
                asset_code=record.asset_code,
                shares=record.shares,
                price=record.price,
                notional=record.notional,
                commission=(record.commission if record.commission is not None else Decimal("0")),
                commission_known=record.commission is not None,
                slippage=(record.slippage if record.slippage is not None else Decimal("0")),
                slippage_known=record.slippage is not None,
                stamp_duty=(record.stamp_duty if record.stamp_duty is not None else Decimal("0")),
                stamp_duty_known=record.stamp_duty is not None,
                transfer_fee=(
                    record.transfer_fee if record.transfer_fee is not None else Decimal("0")
                ),
                transfer_fee_known=record.transfer_fee is not None,
                notes=record.notes,
                traded_at=record.traded_at,
            )
            return self._to_transaction_record(model)

    def list_user_transactions(
        self,
        user_id: int,
        *,
        page_number: int,
        page_size: int,
    ) -> TransactionPage:
        """Return a typed owner-scoped page ordered by traded time."""
        using = router.db_for_read(TransactionModel)
        queryset = (
            TransactionModel._default_manager.using(using)
            .filter(portfolio__user_id=user_id)
            .select_related("portfolio")
        )
        count = queryset.count()
        offset = (page_number - 1) * page_size
        models = queryset.order_by("-traded_at")[offset : offset + page_size]
        return TransactionPage(
            count=count,
            page_number=page_number,
            page_size=page_size,
            results=tuple(self._to_transaction_record(model) for model in models),
        )

    def get_user_transaction(self, user_id: int, transaction_id: int) -> TransactionRecord | None:
        """Return an owner-scoped record or None for missing/foreign IDs."""
        using = router.db_for_read(TransactionModel)
        model = (
            TransactionModel._default_manager.using(using)
            .filter(id=transaction_id, portfolio__user_id=user_id)
            .select_related("portfolio")
            .first()
        )
        return self._to_transaction_record(model) if model is not None else None

    @staticmethod
    def _to_transaction_record(model: TransactionModel) -> TransactionRecord:
        """Project one ORM row into the canonical transaction DTO."""
        return TransactionRecord(
            id=model.id,
            portfolio_id=model.portfolio_id,
            portfolio_name=model.portfolio.name,
            position_id=model.position_id,
            asset_code=model.asset_code,
            action=model.action,
            shares=model.shares,
            price=model.price,
            notional=model.notional,
            commission=model.commission if model.commission_known is True else None,
            commission_known=model.commission_known,
            slippage=model.slippage if model.slippage_known is True else None,
            slippage_known=model.slippage_known,
            stamp_duty=model.stamp_duty if model.stamp_duty_known is True else None,
            stamp_duty_known=model.stamp_duty_known,
            transfer_fee=model.transfer_fee if model.transfer_fee_known is True else None,
            transfer_fee_known=model.transfer_fee_known,
            broker_name=model.broker_name,
            external_trade_id=model.external_trade_id,
            broker_trade_key=model.broker_trade_key,
            import_batch_id=model.import_batch_id,
            notes=model.notes,
            traded_at=model.traded_at,
            created_at=model.created_at,
        )
