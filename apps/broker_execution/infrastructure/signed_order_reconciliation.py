"""Order-level reconciliation of a signed Broker order against captured QMT facts."""

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from .models import BrokerAccountSnapshotModel, LiveOrderModel


def _number(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _same_order(row: Mapping[str, object], order: LiveOrderModel) -> bool:
    return row.get("broker_order_id") == order.broker_order_id and row.get("client_order_id") in (
        None,
        "",
        str(order.client_order_id),
    )


def _candidates(
    rows: Sequence[Mapping[str, object]], order: LiveOrderModel
) -> list[Mapping[str, object]]:
    return [
        row
        for row in rows
        if row.get("broker_order_id") == order.broker_order_id
        or row.get("client_order_id") == str(order.client_order_id)
    ]


def matched_signed_snapshot(
    *,
    order: LiveOrderModel,
    snapshot: BrokerAccountSnapshotModel,
    broker_orders: Sequence[Mapping[str, object]],
    broker_trades: Sequence[Mapping[str, object]],
    broker_trade_id_counts: Counter[str],
) -> dict[str, object] | None:
    """Return source evidence only for one exact order, status, economic terms and all fills."""
    if (
        order.status
        not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "FILLED",
            "BROKER_REJECTED",
            "CANCELED",
            "CANCEL_PENDING",
        }
        or order.quantity <= 0
        or not 0 <= order.filled_quantity <= order.quantity
        or (order.status == "FILLED" and order.filled_quantity != order.quantity)
        or (order.status == "PARTIALLY_FILLED" and not 0 < order.filled_quantity < order.quantity)
        or not order.authority_pin
        or not order.broker_order_id
        or order.updated_at > snapshot.captured_at
        or (order.user_id, order.account_id, order.agent_id)
        != (snapshot.user_id, snapshot.account_id, snapshot.agent_id)
    ):
        return None
    candidates = _candidates(broker_orders, order)
    if len(candidates) != 1:
        return None
    observed = candidates[0]
    if (
        not _same_order(observed, order)
        or (observed.get("asset_code"), observed.get("side"), observed.get("status"))
        != (order.asset_code, order.side, order.status)
        or _number(observed.get("quantity")) != order.quantity
        or _number(observed.get("limit_price")) != order.limit_price
        or _number(observed.get("traded_quantity")) != order.filled_quantity
    ):
        return None
    fills = {fill.broker_trade_id: fill for fill in order.fills.all()}
    trades = _candidates(broker_trades, order)
    trade_ids = [row.get("broker_trade_id") for row in trades]
    if (
        any(not isinstance(trade_id, str) for trade_id in trade_ids)
        or len(trade_ids) != len(fills)
        or set(trade_ids) != fills.keys()
        or sum((fill.quantity for fill in fills.values()), Decimal(0)) != order.filled_quantity
    ):
        return None
    for row in trades:
        fill = fills[str(row["broker_trade_id"])]
        if (
            broker_trade_id_counts[fill.broker_trade_id] != 1
            or not _same_order(row, order)
            or row.get("asset_code") != order.asset_code
            or fill.agent_id != order.agent_id
            or (_number(row.get("quantity")), _number(row.get("price")))
            != (fill.quantity, fill.price)
        ):
            return None
    return {
        "authority_pin": order.authority_pin,
        "version": order.version,
        "status": order.status,
        "snapshot_id": snapshot.pk,
        "snapshot_captured_at": snapshot.captured_at.isoformat(),
        "snapshot_first_recorded_at": snapshot.created_at.isoformat(),
        "clock_source": "agent_snapshot",
        "broker_source_at": None,
        "source_order": dict(observed),
        "source_trades": [dict(row) for row in trades],
    }
