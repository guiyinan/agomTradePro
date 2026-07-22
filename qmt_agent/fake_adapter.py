"""Deterministic fake broker adapter for dry-run and fault-injection tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .qmt_adapter import BrokerSubmitResult


class FakeQmtAdapter:
    """In-memory broker supporting success, rejection, and unknown outcomes."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.connected = False
        self.orders: dict[str, dict[str, Any]] = {}

    def connect(self) -> None:
        if self.scenario == "disconnect":
            raise RuntimeError("simulated QMT disconnect")
        self.connected = True

    def health(self) -> dict[str, Any]:
        return {"qmt_connected": self.connected, "qmt_version": "fake-1"}

    def account_snapshot(self) -> dict[str, Any]:
        return {
            "cash_available": "1000000",
            "total_asset": "1000000",
            "positions": [],
            "orders": [
                {
                    "broker_order_id": order["broker_order_id"],
                    "client_order_id": client_order_id,
                    "asset_code": order["asset_code"],
                    "side": order["side"],
                    "quantity": order["quantity"],
                    "traded_quantity": order["quantity"] if order["status"] == "FILLED" else "0",
                    "limit_price": order["limit_price"],
                    "status": order["status"],
                }
                for client_order_id, order in self.orders.items()
            ],
            "trades": [
                {
                    "broker_trade_id": f"TRADE-{order['broker_order_id']}",
                    "broker_order_id": order["broker_order_id"],
                    "client_order_id": client_order_id,
                    "asset_code": order["asset_code"],
                    "quantity": order["quantity"],
                    "price": order["limit_price"],
                }
                for client_order_id, order in self.orders.items()
                if order["status"] == "FILLED"
            ],
        }

    def market_snapshot(self, asset_code: str) -> dict[str, Any]:
        return {"last_price": "3.90", "upper_limit": "4.29", "lower_limit": "3.51"}

    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult:
        if self.scenario == "unknown":
            raise TimeoutError("simulated unknown submit outcome")
        if self.scenario == "reject":
            return BrokerSubmitResult(False, "", "simulated rejection")
        broker_id = f"FAKE-{len(self.orders)+1:06d}"
        status = {
            "partial": "PARTIALLY_FILLED",
            "filled": "FILLED",
        }.get(self.scenario, "SUBMITTED")
        self.orders[str(order["client_order_id"])] = {
            "broker_order_id": broker_id,
            "status": status,
            "asset_code": str(order["asset_code"]),
            "side": str(order["side"]),
            "quantity": str(order["quantity"]),
            "limit_price": str(order["limit_price"]),
        }
        return BrokerSubmitResult(True, broker_id)

    def cancel_order(self, broker_order_id: str) -> bool:
        for order in self.orders.values():
            if order["broker_order_id"] == broker_order_id:
                order["status"] = "CANCELED"
                return True
        return False

    def query_order(
        self, client_order_id: str, broker_order_id: str = ""
    ) -> dict[str, Any] | None:
        return self.orders.get(client_order_id)

    def find_order_candidates(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in self.orders.values()
            if item["asset_code"] == str(order.get("asset_code"))
            and item["side"] == str(order.get("side"))
            and Decimal(item["quantity"]) == Decimal(str(order.get("quantity") or "0"))
            and Decimal(item["limit_price"])
            == Decimal(str(order.get("limit_price") or "0"))
        ]

    def poll_events(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        events: list[dict[str, Any]] = []
        for client_order_id, order in self.orders.items():
            status = str(order["status"])
            if status in {"PARTIALLY_FILLED", "FILLED"}:
                total_quantity = Decimal(str(order["quantity"]))
                fill_quantity = (
                    total_quantity / Decimal("2")
                    if status == "PARTIALLY_FILLED"
                    else total_quantity
                )
                events.append(
                    {
                        "event_id": f"fake-trade:{order['broker_order_id']}:{fill_quantity}",
                        "client_order_id": client_order_id,
                        "event_type": "FAKE_TRADE",
                        "status": "",
                        "occurred_at": now,
                        "broker_order_id": order["broker_order_id"],
                        "payload": {},
                        "fill": {
                            "broker_account_ref": "fake",
                            "broker_trade_id": f"TRADE-{order['broker_order_id']}",
                            "quantity": str(fill_quantity),
                            "price": order["limit_price"],
                            "occurred_at": now,
                        },
                    }
                )
            events.append(
                {
                    "event_id": f"fake-order:{order['broker_order_id']}:{status}",
                    "client_order_id": client_order_id,
                    "event_type": "FAKE_ORDER_STATUS",
                    "status": status,
                    "occurred_at": now,
                    "broker_order_id": order["broker_order_id"],
                    "payload": {},
                }
            )
        return events
