"""Validate retained account-wide V4 fill history before ordinary UoW writes.

The ordinary simulated UoW shares account cash with reservation fills. This
module therefore validates every retained V4 chain while the caller holds the
account lock. It does not qualify market data, reconstruct Positions, or
change the ordinary V3 price contract.
"""

from __future__ import annotations

from typing import cast

from django.db.models import Q

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    _FILL_BINDING_SCHEMA,
    SimulatedAccountModel,
    SimulatedTradeModel,
)


def _invalid_chain(message: str) -> SimulatedTradeExecutionBlocked:
    """Create the stable failure used for incomplete or damaged V4 history."""

    return SimulatedTradeExecutionBlocked(
        message,
        code="SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
    )


def _bind_instrument_identity(
    *,
    security_id: str,
    asset_code: str,
    security_to_asset: dict[str, str],
    asset_to_security: dict[str, str],
) -> None:
    """Reject either direction of a retained security/ledger-asset alias."""

    known_asset = security_to_asset.get(security_id)
    known_security = asset_to_security.get(asset_code)
    if (known_asset is not None and known_asset != asset_code) or (
        known_security is not None and known_security != security_id
    ):
        raise SimulatedTradeExecutionBlocked(
            "retained fill history aliases a security and ledger asset",
            code="ORDER_RESERVATION_IDENTITY_CONFLICT",
        )
    security_to_asset[security_id] = asset_code
    asset_to_security[asset_code] = security_id


def validate_account_v4_fill_history(
    *,
    account: SimulatedAccountModel,
    intent: SimulatedTradeIntent,
    using: str,
) -> None:
    """Lock and revalidate every retained V4 receipt prefix for one account.

    The caller must already hold the account parent row and active reservation
    locks. This function locks all discovered reservation parents in primary
    key order before the strict chain helper locks receipts and same-account
    Trades. It scans both Receipt foreign-key sides and scalar/payload Trade
    markers, including terminal orders. Exact existing-trade replay belongs
    ahead of this call so an already committed result remains read-only.
    """

    if (
        type(account) is not SimulatedAccountModel
        or type(account.pk) is not int
        or account.pk <= 0
        or type(account.user_id) is not int
        or account.user_id <= 0
        or type(intent) is not SimulatedTradeIntent
        or type(intent.account_id) is not int
        or intent.account_id != account.pk
        or type(intent.user_id) is not int
        or intent.user_id != account.user_id
        or type(intent.security_id) is not str
        or not intent.security_id
        or type(intent.asset_code) is not str
        or not intent.asset_code
        or type(using) is not str
        or not using
    ):
        raise _invalid_chain("模拟成交历史校验范围无效")

    raw_marker_ids: object = list(
        SimulatedTradeModel._base_manager.using(using)
        .filter(account_id=account.pk)
        .filter(
            Q(settlement_plan_binding_version=4)
            | Q(settlement_plan_binding_payload__schema=_FILL_BINDING_SCHEMA)
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if type(raw_marker_ids) is not list:
        raise _invalid_chain("V4 Trade 标记查询结果无效")
    marker_trade_ids: set[int] = set()
    for raw_trade_id in cast(list[object], raw_marker_ids):
        if type(raw_trade_id) is not int or raw_trade_id <= 0:
            raise _invalid_chain("V4 Trade 标记主键无效")
        if raw_trade_id in marker_trade_ids:
            raise _invalid_chain("V4 Trade 标记主键重复")
        marker_trade_ids.add(raw_trade_id)

    raw_locator_rows: object = list(
        SimulatedOrderFillReceiptModel._base_manager.using(using)
        .filter(Q(reservation__account_id=account.pk) | Q(trade__account_id=account.pk))
        .order_by("pk")
        .values_list(
            "pk",
            "reservation_id",
            "reservation__account_id",
            "trade_id",
            "trade__account_id",
        )
    )
    if type(raw_locator_rows) is not list:
        raise _invalid_chain("成交回执定位查询结果无效")

    receipt_ids: set[int] = set()
    receipt_trade_ids: set[int] = set()
    reservation_trade_ids: dict[int, set[int]] = {}
    reservation_ids: set[int] = set()
    for raw_row in cast(list[object], raw_locator_rows):
        if type(raw_row) is not tuple or len(raw_row) != 5:
            raise _invalid_chain("成交回执定位行结构无效")
        raw_values = cast(tuple[object, ...], raw_row)
        if any(type(value) is not int or value <= 0 for value in raw_values):
            raise _invalid_chain("成交回执定位身份无效")
        receipt_id, reservation_id, reservation_account_id, trade_id, trade_account_id = cast(
            tuple[int, int, int, int, int],
            raw_row,
        )
        if reservation_account_id != account.pk or trade_account_id != account.pk:
            raise _invalid_chain("成交回执跨越了账户边界")
        if receipt_id in receipt_ids or trade_id in receipt_trade_ids:
            raise _invalid_chain("V4 Trade 对应多条成交回执")
        receipt_ids.add(receipt_id)
        receipt_trade_ids.add(trade_id)
        reservation_ids.add(reservation_id)
        reservation_trade_ids.setdefault(reservation_id, set()).add(trade_id)

    # Filled or consumed parent counters are independent evidence that a fill
    # prefix must still exist, even if both the Receipt and Trade marker were
    # damaged or removed. A zero-fill cancellation remains a valid no-receipt
    # reservation and is deliberately excluded here.
    raw_filled_reservation_ids: object = list(
        SimulatedOrderReservationModel._base_manager.using(using)
        .filter(account_id=account.pk)
        .filter(
            Q(filled_quantity__gt=0)
            | Q(cash_consumed__gt=0)
            | Q(shares_consumed__gt=0)
            | Q(status=SimulatedOrderReservationModel.STATUS_COMPLETED)
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if type(raw_filled_reservation_ids) is not list:
        raise _invalid_chain("成交预留计数查询结果无效")
    for raw_reservation_id in cast(list[object], raw_filled_reservation_ids):
        if type(raw_reservation_id) is not int or raw_reservation_id <= 0:
            raise _invalid_chain("成交预留主键无效")
        reservation_ids.add(raw_reservation_id)

    if not marker_trade_ids.issubset(receipt_trade_ids):
        raise _invalid_chain("V4 Trade 标记缺少唯一持久成交回执")
    if not reservation_ids:
        if marker_trade_ids:
            raise _invalid_chain("V4 Trade 标记没有可锁定的 Reservation")
        return

    locked_reservations = tuple(
        SimulatedOrderReservationModel._base_manager.using(using)
        .select_for_update(of=("self",))
        .filter(
            pk__in=tuple(sorted(reservation_ids)),
            account_id=account.pk,
            owner_user_id=account.user_id,
        )
        .order_by("pk")
    )
    reservations_by_id: dict[int, SimulatedOrderReservationModel] = {}
    for reservation_row in locked_reservations:
        if (
            type(reservation_row.pk) is not int
            or reservation_row.pk in reservations_by_id
            or reservation_row.account_id != account.pk
            or reservation_row.owner_user_id != account.user_id
        ):
            raise _invalid_chain("成交回执 Reservation 不属于当前账户")
        reservations_by_id[reservation_row.pk] = reservation_row
    if set(reservations_by_id) != reservation_ids:
        raise _invalid_chain("成交回执引用了缺失或跨所有者 Reservation")

    security_to_asset: dict[str, str] = {}
    asset_to_security: dict[str, str] = {}
    for reservation_id in sorted(reservation_ids):
        chain = _locked_fill_chain(
            reservation_row=reservations_by_id[reservation_id],
            using=using,
        )
        if (
            chain.intent.account_id != account.pk
            or chain.intent.user_id != account.user_id
            or type(chain.intent.security_id) is not str
            or not chain.intent.security_id
            or type(chain.intent.asset_code) is not str
            or not chain.intent.asset_code
        ):
            raise _invalid_chain("成交回执封存意图与账户身份不一致")
        chain_trade_ids: set[int] = set()
        for receipt_row, decoded in chain.rows:
            trade_id = decoded.trade_id
            if (
                receipt_row.reservation_id != reservation_id
                or type(trade_id) is not int
                or trade_id in chain_trade_ids
                or receipt_row.trade.account_id != account.pk
                or receipt_row.trade.settlement_plan_binding_version != 4
            ):
                raise _invalid_chain("成交回执链的账户或 Trade 标记不一致")
            chain_trade_ids.add(trade_id)
        if chain_trade_ids != reservation_trade_ids[reservation_id]:
            raise _invalid_chain("Reservation 的完整回执前缀与定位行不一致")
        _bind_instrument_identity(
            security_id=chain.intent.security_id,
            asset_code=chain.intent.asset_code,
            security_to_asset=security_to_asset,
            asset_to_security=asset_to_security,
        )

    _bind_instrument_identity(
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        security_to_asset=security_to_asset,
        asset_to_security=asset_to_security,
    )
