"""Application use cases for the transaction-record API candidate."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.account.application.repository_provider import get_transaction_record_repository
from apps.account.application.transaction_cost_use_cases import (
    normalize_actual_fee,
)
from apps.account.domain.transaction_record_contracts import (
    CreateTransactionInput,
    NewTransactionRecord,
    TransactionPage,
    TransactionRecord,
    TransactionRecordRepositoryProtocol,
)
from core.exceptions import InvalidInputError

CENT = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.0001")
MAX_PRICE = Decimal("9999999999999999.9999")
MAX_NOTIONAL = Decimal("999999999999999999.99")
MAX_SHARES = 1_000_000_000_000


def _validate_positive_id(value: int, *, field_name: str) -> None:
    """Require an actual positive integer identifier, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidInputError("编号必须为正整数", details={"field": field_name})


class CreateTransactionUseCase:
    """Create one transaction after deriving its notional in Application."""

    def __init__(self, repository: TransactionRecordRepositoryProtocol | None = None) -> None:
        self.repository = repository or get_transaction_record_repository()

    def execute(self, command: CreateTransactionInput) -> TransactionRecord:
        """Normalize the computed notional and persist through the typed port."""
        _validate_positive_id(command.actor_user_id, field_name="actor_user_id")
        _validate_positive_id(command.portfolio_id, field_name="portfolio_id")
        if command.position_id is not None:
            _validate_positive_id(command.position_id, field_name="position_id")

        if isinstance(command.shares, bool) or not isinstance(command.shares, (int, float)):
            raise InvalidInputError("交易数量必须为正有限数", details={"field": "shares"})
        try:
            shares = float(command.shares)
        except (OverflowError, TypeError, ValueError) as exc:
            raise InvalidInputError("交易数量必须为正有限数", details={"field": "shares"}) from exc
        if not math.isfinite(shares) or shares <= 0 or shares > MAX_SHARES:
            raise InvalidInputError(
                "交易数量必须为允许范围内的正有限数", details={"field": "shares"}
            )

        if (
            not isinstance(command.price, Decimal)
            or not command.price.is_finite()
            or command.price <= 0
        ):
            raise InvalidInputError("成交价格必须为正有限金额", details={"field": "price"})
        try:
            price = command.price.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            notional = (Decimal(str(shares)) * price).quantize(CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise InvalidInputError(
                "成交价格或金额超出允许范围", details={"field": "price"}
            ) from exc
        if price <= 0 or price > MAX_PRICE:
            raise InvalidInputError("成交价格超出允许范围", details={"field": "price"})
        if notional > MAX_NOTIONAL:
            raise InvalidInputError("成交金额超出允许范围", details={"field": "shares"})
        if not isinstance(command.action, str) or command.action not in ("buy", "sell"):
            raise InvalidInputError("交易方向无效", details={"field": "action"})

        commission = normalize_actual_fee(command.commission, field_name="commission")
        slippage = normalize_actual_fee(command.slippage, field_name="slippage")
        stamp_duty = normalize_actual_fee(command.stamp_duty, field_name="stamp_duty")
        transfer_fee = normalize_actual_fee(command.transfer_fee, field_name="transfer_fee")

        if (
            not isinstance(command.traded_at, datetime)
            or command.traded_at.tzinfo is None
            or command.traded_at.utcoffset() is None
        ):
            raise InvalidInputError(
                "成交时间必须为带时区的 datetime",
                details={"field": "traded_at"},
            )

        return self.repository.create_transaction(
            NewTransactionRecord(
                actor_user_id=command.actor_user_id,
                portfolio_id=command.portfolio_id,
                position_id=command.position_id,
                action=command.action,
                asset_code=command.asset_code,
                shares=shares,
                price=price,
                notional=notional,
                notes=command.notes,
                traded_at=command.traded_at,
                commission=commission,
                slippage=slippage,
                stamp_duty=stamp_duty,
                transfer_fee=transfer_fee,
            )
        )


class ListTransactionPageUseCase:
    """Read one owner-scoped transaction page."""

    def __init__(self, repository: TransactionRecordRepositoryProtocol | None = None) -> None:
        self.repository = repository or get_transaction_record_repository()

    def execute(self, *, user_id: int, page_number: int, page_size: int) -> TransactionPage:
        """Return a typed page using the API's selected pagination values."""
        _validate_positive_id(user_id, field_name="user_id")
        _validate_positive_id(page_number, field_name="page")
        _validate_positive_id(page_size, field_name="page_size")
        return self.repository.list_user_transactions(
            user_id,
            page_number=page_number,
            page_size=page_size,
        )


class GetTransactionUseCase:
    """Read a single transaction inside the authenticated user's scope."""

    def __init__(self, repository: TransactionRecordRepositoryProtocol | None = None) -> None:
        self.repository = repository or get_transaction_record_repository()

    def execute(self, *, user_id: int, transaction_id: int) -> TransactionRecord | None:
        """Return None for both missing and foreign transaction IDs."""
        _validate_positive_id(user_id, field_name="user_id")
        _validate_positive_id(transaction_id, field_name="transaction_id")
        return self.repository.get_user_transaction(user_id, transaction_id)
