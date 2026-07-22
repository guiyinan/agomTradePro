"""QMT adapter; this is the only Agent file allowed to import ``xtquant``."""

from __future__ import annotations

import base64
import hashlib
import random
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

_ORDER_REMARK_PREFIX = "A"


def encode_order_remark(client_order_id: str) -> str:
    """Encode a UUID into a reversible QMT remark under its 24-byte limit."""

    raw = uuid.UUID(str(client_order_id)).bytes
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_ORDER_REMARK_PREFIX}{encoded}"


def decode_order_remark(order_remark: str) -> str | None:
    """Decode an Agom compact remark, while accepting legacy full UUID remarks."""

    value = str(order_remark or "").strip()
    try:
        if value.startswith(_ORDER_REMARK_PREFIX) and len(value) == 23:
            raw = base64.urlsafe_b64decode(value[1:] + "==")
            return str(uuid.UUID(bytes=raw))
        return str(uuid.UUID(value))
    except (ValueError, TypeError):
        return None


def _qmt_order_status_map(xtconstant: Any) -> dict[Any, str]:
    """Map all documented stock-order states to the server lifecycle."""

    return {
        getattr(xtconstant, "ORDER_UNREPORTED", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_WAIT_REPORTING", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_REPORTED", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_REPORTED_CANCEL", object()): "CANCEL_PENDING",
        getattr(xtconstant, "ORDER_PARTSUCC_CANCEL", object()): "CANCEL_PENDING",
        getattr(xtconstant, "ORDER_PART_CANCEL", object()): "CANCELED",
        getattr(xtconstant, "ORDER_CANCELED", object()): "CANCELED",
        getattr(xtconstant, "ORDER_PART_SUCC", object()): "PARTIALLY_FILLED",
        getattr(xtconstant, "ORDER_SUCCEEDED", object()): "FILLED",
        getattr(xtconstant, "ORDER_JUNK", object()): "BROKER_REJECTED",
        getattr(xtconstant, "ORDER_UNKNOWN", object()): "RECONCILIATION_REQUIRED",
    }


def _qmt_event_time(raw: Any, fallback: str) -> str:
    """Return an aware ISO timestamp from QMT epoch seconds when available."""

    try:
        value = int(raw)
        if value > 0:
            return datetime.fromtimestamp(value, UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return fallback


@dataclass(frozen=True)
class BrokerSubmitResult:
    """Normalized result returned immediately by QMT order submission."""

    accepted: bool
    broker_order_id: str
    message: str = ""


class BrokerAdapter(Protocol):
    """Minimal broker boundary used by the executor."""

    def connect(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
    def account_snapshot(self) -> dict[str, Any]: ...
    def market_snapshot(self, asset_code: str) -> dict[str, Any]: ...
    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult: ...
    def cancel_order(self, broker_order_id: str) -> bool: ...
    def query_order(self, client_order_id: str, broker_order_id: str = "") -> dict[str, Any] | None: ...
    def find_order_candidates(self, order: dict[str, Any]) -> list[dict[str, Any]]: ...
    def poll_events(self) -> list[dict[str, Any]]: ...


class XtQuantAdapter:
    """Thin adapter over the broker-distributed xtquant package."""

    def __init__(
        self,
        *,
        userdata_path: Path,
        broker_account_id: str,
        account_type: str = "STOCK",
        qmt_client_version: str = "",
        xtquant_version: str = "",
    ) -> None:
        if str(account_type).upper() != "STOCK":
            raise ValueError("The first QMT Agent release supports STOCK accounts only")
        self.userdata_path = userdata_path
        self.broker_account_id = broker_account_id
        self.account_type = account_type
        self.qmt_client_version = str(qmt_client_version).strip()
        self.xtquant_version = str(xtquant_version).strip()
        self.trader = None
        self.account = None
        self.callback = None
        self._callback_dirty = threading.Event()
        self._callback_disconnected = False

    def connect(self) -> None:
        # Keep the optional vendor dependency isolated to this method/module.
        from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
        from xtquant.xttype import StockAccount

        adapter = self

        class AgomXtQuantCallback(XtQuantTraderCallback):
            """Wake the polling projection without duplicating normalization logic."""

            def on_disconnected(self) -> None:
                adapter._callback_disconnected = True
                adapter._callback_dirty.set()

            def on_stock_order(self, _order: Any) -> None:
                adapter._callback_dirty.set()

            def on_stock_trade(self, _trade: Any) -> None:
                adapter._callback_dirty.set()

            def on_order_error(self, _order_error: Any) -> None:
                adapter._callback_dirty.set()

            def on_cancel_error(self, _cancel_error: Any) -> None:
                adapter._callback_dirty.set()

        session_id = random.randint(100000, 999999999)
        self.trader = XtQuantTrader(str(self.userdata_path), session_id)
        self.callback = AgomXtQuantCallback()
        self.trader.register_callback(self.callback)
        self.trader.start()
        if self.trader.connect() != 0:
            raise RuntimeError("QMT trader connection failed")
        self.account = StockAccount(self.broker_account_id, "STOCK")
        if self.trader.subscribe(self.account) != 0:
            raise RuntimeError("QMT account subscription failed")
        self._callback_disconnected = False
        self._callback_dirty.set()

    def health(self) -> dict[str, Any]:
        connected = False
        if self.trader is not None and self.account is not None:
            try:
                connected = self.trader.query_stock_asset(self.account) is not None
            except Exception:
                connected = False
        if connected:
            self._callback_disconnected = False
        elif self._callback_disconnected:
            connected = False
        version = (
            f"QMT {self.qmt_client_version or 'unknown'}; "
            f"xtquant {self.xtquant_version or 'unknown'}"
        )
        return {"qmt_connected": connected, "qmt_version": version[:64]}

    def account_snapshot(self) -> dict[str, Any]:
        if self.trader is None or self.account is None:
            raise RuntimeError("QMT is not connected")
        from xtquant import xtconstant

        asset = self.trader.query_stock_asset(self.account)
        positions = self.trader.query_stock_positions(self.account) or []
        orders = self.trader.query_stock_orders(self.account) or []
        trades = self.trader.query_stock_trades(self.account) or []
        by_order_id = {str(getattr(item, "order_id", "")): item for item in orders}
        status_map = _qmt_order_status_map(xtconstant)
        return {
            "cash_available": str(getattr(asset, "cash", 0)),
            "total_asset": str(getattr(asset, "total_asset", 0)),
            "positions": [
                {
                    "asset_code": item.stock_code,
                    "quantity": str(item.volume),
                    "available_quantity": str(item.can_use_volume),
                    "payload": {},
                }
                for item in positions
            ],
            "orders": [
                {
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "client_order_id": decode_order_remark(
                        str(getattr(item, "order_remark", "") or "")
                    )
                    or "",
                    "asset_code": str(getattr(item, "stock_code", "")),
                    "side": (
                        "BUY"
                        if getattr(item, "order_type", None)
                        == getattr(xtconstant, "STOCK_BUY", object())
                        else "SELL"
                        if getattr(item, "order_type", None)
                        == getattr(xtconstant, "STOCK_SELL", object())
                        else "UNKNOWN"
                    ),
                    "quantity": str(getattr(item, "order_volume", 0)),
                    "traded_quantity": str(getattr(item, "traded_volume", 0)),
                    "limit_price": str(getattr(item, "price", 0)),
                    "status": status_map.get(
                        getattr(item, "order_status", None), "UNKNOWN"
                    ),
                }
                for item in orders
            ],
            "trades": [
                {
                    "broker_trade_id": str(getattr(item, "traded_id", "")),
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "client_order_id": decode_order_remark(
                        str(
                            getattr(
                                by_order_id.get(str(getattr(item, "order_id", ""))),
                                "order_remark",
                                "",
                            )
                            or ""
                        )
                    )
                    or "",
                    "asset_code": str(getattr(item, "stock_code", "")),
                    "quantity": str(getattr(item, "traded_volume", 0)),
                    "price": str(getattr(item, "traded_price", 0)),
                }
                for item in trades
            ],
        }

    def market_snapshot(self, asset_code: str) -> dict[str, Any]:
        """Return the latest price and exchange price boundaries for local checks."""

        if self.trader is None:
            raise RuntimeError("QMT is not connected")
        from xtquant import xtdata

        tick = (xtdata.get_full_tick([asset_code]) or {}).get(asset_code) or {}
        return {
            "last_price": str(tick.get("lastPrice") or 0),
            "upper_limit": str(tick.get("upperLimit") or 0),
            "lower_limit": str(tick.get("lowerLimit") or 0),
        }

    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult:
        if self.trader is None or self.account is None:
            raise RuntimeError("QMT is not connected")
        from xtquant import xtconstant

        side = xtconstant.STOCK_BUY if order["side"] == "BUY" else xtconstant.STOCK_SELL
        broker_order_id = self.trader.order_stock(
            self.account,
            order["asset_code"],
            side,
            int(Decimal(str(order["quantity"]))),
            xtconstant.FIX_PRICE,
            float(Decimal(str(order["limit_price"]))),
            "AgomTradePro",
            encode_order_remark(str(order["client_order_id"])),
        )
        accepted = int(broker_order_id) > 0
        return BrokerSubmitResult(accepted, str(broker_order_id), "" if accepted else "QMT rejected")

    def cancel_order(self, broker_order_id: str) -> bool:
        if self.trader is None or self.account is None:
            return False
        return self.trader.cancel_order_stock(self.account, int(broker_order_id)) == 0

    def query_order(self, client_order_id: str, broker_order_id: str = "") -> dict[str, Any] | None:
        if self.trader is None or self.account is None:
            return None
        from xtquant import xtconstant

        status_map = _qmt_order_status_map(xtconstant)
        orders = self.trader.query_stock_orders(self.account) or []
        for item in orders:
            if str(getattr(item, "order_id", "")) == broker_order_id or decode_order_remark(
                str(getattr(item, "order_remark", ""))
            ) == client_order_id:
                return {
                    "broker_order_id": str(item.order_id),
                    "broker_status": str(item.order_status),
                    "broker_message": str(getattr(item, "status_msg", "") or ""),
                    "status": status_map.get(
                        getattr(item, "order_status", None),
                        "RECONCILIATION_REQUIRED",
                    ),
                    "traded_volume": str(item.traded_volume),
                    "traded_price": str(item.traded_price),
                }
        return None

    def find_order_candidates(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        """Conservatively match fields when the QMT remark cannot be trusted."""

        if self.trader is None or self.account is None:
            return []
        quantity = Decimal(str(order.get("quantity") or "0"))
        price = Decimal(str(order.get("limit_price") or "0"))
        candidates = []
        for item in self.trader.query_stock_orders(self.account) or []:
            if str(getattr(item, "stock_code", "")).upper() != str(
                order.get("asset_code") or ""
            ).upper():
                continue
            if Decimal(str(getattr(item, "order_volume", 0))) != quantity:
                continue
            if abs(Decimal(str(getattr(item, "price", 0))) - price) > Decimal("0.0001"):
                continue
            candidates.append(
                {
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "broker_status": str(getattr(item, "order_status", "")),
                    "match_mode": "conservative_fields",
                }
            )
        return candidates

    def poll_events(self) -> list[dict[str, Any]]:
        """Normalize current-day QMT orders/trades into idempotent server events."""

        if self.trader is None or self.account is None:
            return []
        self._callback_dirty.clear()
        from xtquant import xtconstant

        order_status_map = _qmt_order_status_map(xtconstant)
        now = datetime.now(UTC).isoformat()
        orders = self.trader.query_stock_orders(self.account) or []
        by_order_id = {str(item.order_id): item for item in orders}
        order_events: list[dict[str, Any]] = []
        for item in orders:
            client_order_id = decode_order_remark(
                str(getattr(item, "order_remark", "") or "")
            ) or ""
            status = order_status_map.get(getattr(item, "order_status", None))
            if not client_order_id or not status:
                continue
            order_events.append(
                {
                    "event_id": (
                        f"qmt-order:{item.order_id}:{item.order_status}:"
                        f"{getattr(item, 'traded_volume', 0)}"
                    ),
                    "client_order_id": client_order_id,
                    "event_type": "QMT_ORDER_STATUS",
                    "status": status,
                    "occurred_at": _qmt_event_time(
                        getattr(item, "order_time", None), now
                    ),
                    "broker_order_id": str(item.order_id),
                    "payload": {
                        "broker_status": str(item.order_status),
                        "status_msg": str(getattr(item, "status_msg", "") or ""),
                    },
                }
            )
        trade_events: list[dict[str, Any]] = []
        trades = self.trader.query_stock_trades(self.account) or []
        for trade in trades:
            order = by_order_id.get(str(getattr(trade, "order_id", "")))
            client_order_id = decode_order_remark(
                str(getattr(order, "order_remark", "") or "")
            ) or ""
            trade_id = str(getattr(trade, "traded_id", "") or "")
            if not client_order_id or not trade_id:
                continue
            event_key = f"{self.broker_account_id}:{trade_id}"
            trade_events.append(
                {
                    "event_id": (
                        "qmt-trade:"
                        + hashlib.sha256(event_key.encode("utf-8")).hexdigest()
                    ),
                    "client_order_id": client_order_id,
                    "event_type": "QMT_TRADE",
                    # A fill is an immutable fact, not authoritative order state.
                    # The QMT order query below supplies PARTIALLY_FILLED/FILLED.
                    "status": "",
                    "occurred_at": _qmt_event_time(
                        getattr(trade, "traded_time", None), now
                    ),
                    "broker_order_id": str(getattr(trade, "order_id", "")),
                    "payload": {},
                    "fill": {
                        "broker_account_ref": self.broker_account_id,
                        "broker_trade_id": trade_id,
                        "quantity": str(getattr(trade, "traded_volume", 0)),
                        "price": str(getattr(trade, "traded_price", 0)),
                        "occurred_at": _qmt_event_time(
                            getattr(trade, "traded_time", None), now
                        ),
                    },
                }
            )
        # Persist fills first, then apply QMT's authoritative aggregate order state.
        return [*trade_events, *order_events]
