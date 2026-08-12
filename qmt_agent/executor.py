"""Safe lease, submit, event, command, and recovery orchestration."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .api_client import AgentApiClient
from .config import AgentConfig
from .qmt_adapter import BrokerAdapter
from .state_store import AgentStateStore

logger = logging.getLogger(__name__)


class QmtAgentExecutor:
    """Execute one conservative Agent polling cycle."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        api: AgentApiClient,
        broker: BrokerAdapter,
        state: AgentStateStore,
    ) -> None:
        self.config = config
        self.api = api
        self.broker = broker
        self.state = state
        self.paused = False

    def ensure_broker_connection(self) -> None:
        """Reconnect QMT when the polling health probe reports a disconnect."""

        try:
            connected = bool(self.broker.health().get("qmt_connected"))
        except Exception:
            connected = False
        if not connected:
            self.broker.connect()

    def initialize(self) -> None:
        """Establish QMT and upload a baseline before any order can be leased."""

        self.ensure_broker_connection()
        self.sync_snapshot()
        self.recover_uncertain_submissions()

    def heartbeat(self) -> dict[str, Any]:
        health = self.broker.health()
        return self.api.post(
            "heartbeat/",
            {
                "contract_version": "1.0",
                "observed_at": datetime.now(UTC).isoformat(),
                "qmt_connected": bool(health.get("qmt_connected")),
                "account_ids": [self.config.system_account_id],
                "agent_version": "0.1.0",
                "qmt_version": str(health.get("qmt_version") or ""),
                "dry_run": self.config.dry_run,
                "message": "local STOP file active" if self.config.kill_switch_file.exists() else "",
            },
        )

    def sync_snapshot(self) -> dict[str, Any]:
        snapshot = self.broker.account_snapshot()
        return self.api.post(
            "snapshots/",
            {
                "contract_version": "1.0",
                "account_id": self.config.system_account_id,
                "captured_at": datetime.now(UTC).isoformat(),
                **snapshot,
            },
        )

    def recover_uncertain_submissions(self) -> None:
        """Query broker state after restart; never blindly resubmit uncertain orders."""

        events: list[dict[str, Any]] = []
        for record in self.state.unresolved():
            found = self.broker.query_order(
                record["client_order_id"], record.get("broker_order_id", "")
            )
            candidates = [] if found else self.broker.find_order_candidates(record["payload"])
            conservative_candidate = candidates[0] if len(candidates) == 1 else None
            status = (
                str(found.get("status") or "RECONCILIATION_REQUIRED").upper()
                if found
                else "RECONCILIATION_REQUIRED"
            )
            if status not in {
                "SUBMITTED",
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCEL_PENDING",
                "CANCELED",
                "BROKER_REJECTED",
                "RECONCILIATION_REQUIRED",
            }:
                status = "RECONCILIATION_REQUIRED"
            matched = found or conservative_candidate or {}
            recovery_key = (
                f"{record['client_order_id']}:{status}:"
                f"{str(matched.get('broker_order_id') or '')}"
            )
            events.append(
                {
                    "event_id": (
                        "recovery:"
                        + hashlib.sha256(recovery_key.encode("utf-8")).hexdigest()
                    ),
                    "client_order_id": record["client_order_id"],
                    "event_type": "AGENT_RECOVERY_QUERY",
                    "status": status,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "broker_order_id": str(matched.get("broker_order_id") or ""),
                    "payload": {
                        "found": bool(found),
                        "conservative_candidate_count": len(candidates),
                        "manual_review_required": not bool(found),
                        "broker_status": str(matched.get("broker_status") or ""),
                        "broker_message": str(matched.get("broker_message") or ""),
                    },
                }
            )
            self.state.mark_result(
                record["client_order_id"], status, str(matched.get("broker_order_id") or "")
            )
        if events:
            self.api.post("events/", {"contract_version": "1.0", "events": events})

    def _validate_before_submit(self, order: dict[str, Any]) -> None:
        if self.config.kill_switch_file.exists():
            raise RuntimeError("Local STOP file is active")
        if int(order["account_id"]) != self.config.system_account_id:
            raise RuntimeError("Leased order account does not match local account")
        if order.get("order_type") != "LIMIT" or order.get("limit_price") in (None, ""):
            raise RuntimeError("Only limit orders are permitted")
        if Decimal(str(order["quantity"])) <= 0 or Decimal(str(order["limit_price"])) <= 0:
            raise RuntimeError("Order quantity and price must be positive")
        quantity = Decimal(str(order["quantity"]))
        price = Decimal(str(order["limit_price"]))
        if bool(getattr(self.config, "enforce_trading_session", True)):
            local_now = datetime.now(ZoneInfo(getattr(self.config, "trading_timezone", "Asia/Shanghai")))
            windows = getattr(
                self.config,
                "allowed_trading_windows",
                ("09:30-11:30", "13:00-15:00"),
            )
            current = local_now.strftime("%H:%M")
            if local_now.weekday() >= 5 or not any(
                str(window).split("-", 1)[0] <= current <= str(window).split("-", 1)[1]
                for window in windows
                if "-" in str(window)
            ):
                raise RuntimeError("Trading session is closed")
        market = self.broker.market_snapshot(str(order["asset_code"]))
        last_price = Decimal(str(market.get("last_price") or "0"))
        upper_limit = Decimal(str(market.get("upper_limit") or "0"))
        lower_limit = Decimal(str(market.get("lower_limit") or "0"))
        if upper_limit > 0 and price > upper_limit:
            raise RuntimeError("Limit price exceeds the exchange upper boundary")
        if lower_limit > 0 and price < lower_limit:
            raise RuntimeError("Limit price is below the exchange lower boundary")
        deviation_limit = Decimal(
            str(getattr(self.config, "price_deviation_limit_pct", 0.03))
        )
        if last_price <= 0:
            raise RuntimeError("Current market price is unavailable")
        if deviation_limit > 0 and abs(price - last_price) / last_price > deviation_limit:
            raise RuntimeError("Limit price deviates too far from the current market price")
        snapshot = self.broker.account_snapshot()
        if order["side"] == "BUY":
            if quantity % Decimal("100") != 0:
                raise RuntimeError("A-share buy quantity must use 100-share lots")
            if Decimal(str(snapshot.get("cash_available") or "0")) < quantity * price:
                raise RuntimeError("Available cash is insufficient")
            held_symbols = {
                str(item.get("asset_code") or "").upper()
                for item in snapshot.get("positions", [])
                if Decimal(str(item.get("quantity") or "0")) > 0
            }
            if (
                str(order["asset_code"]).upper() not in held_symbols
                and len(held_symbols) >= int(getattr(self.config, "max_position_count", 20))
            ):
                raise RuntimeError("Maximum position count would be exceeded")
        else:
            position = next(
                (
                    item
                    for item in snapshot.get("positions", [])
                    if str(item.get("asset_code")) == str(order["asset_code"])
                ),
                None,
            )
            if position is None or Decimal(
                str(position.get("available_quantity") or "0")
            ) < quantity:
                raise RuntimeError("Available position is insufficient")
        if self.state.get(str(order["client_order_id"])) is not None:
            raise RuntimeError("Order already exists in the local idempotency store")

    def _report_submission(
        self,
        order: dict[str, Any],
        *,
        status: str,
        event_type: str,
        broker_order_id: str = "",
        message: str = "",
        event_id: str = "",
    ) -> None:
        self.api.post(
            "events/",
            {
                "contract_version": "1.0",
                "events": [
                    {
                        "event_id": event_id or str(uuid.uuid4()),
                        "client_order_id": order["client_order_id"],
                        "event_type": event_type,
                        "status": status,
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "broker_order_id": broker_order_id,
                        "payload": {"message": message, "dry_run": self.config.dry_run},
                    }
                ],
            },
        )

    def execute_order(self, order: dict[str, Any]) -> None:
        """Enter SUBMITTING before broker call and handle uncertainty conservatively."""

        self._validate_before_submit(order)
        if self.config.dry_run:
            logger.info("dry-run validated order %s", order["client_order_id"])
            evidence_key = (
                f"{order['client_order_id']}:{order.get('approval_digest', '')}:"
                "DRY_RUN_VALIDATED"
            )
            self._report_submission(
                order,
                status="",
                event_type="DRY_RUN_VALIDATED",
                message="Validated locally without submitting to QMT",
                event_id=(
                    "dry-run:"
                    + hashlib.sha256(evidence_key.encode("utf-8")).hexdigest()
                ),
            )
            return
        self.api.post(
            "orders/submitting/",
            {
                "contract_version": "1.0",
                "client_order_id": order["client_order_id"],
                "lease_token": order["lease_token"],
            },
        )
        self.state.mark_submitting(str(order["client_order_id"]), order)
        try:
            result = self.broker.submit_order(order)
        except Exception as exc:
            self.state.mark_result(str(order["client_order_id"]), "RECONCILIATION_REQUIRED")
            self._report_submission(
                order,
                status="RECONCILIATION_REQUIRED",
                event_type="SUBMIT_OUTCOME_UNKNOWN",
                message=str(exc),
            )
            return
        status = "SUBMITTED" if result.accepted else "BROKER_REJECTED"
        self.state.mark_result(str(order["client_order_id"]), status, result.broker_order_id)
        self._report_submission(
            order,
            status=status,
            event_type="ORDER_SUBMITTED" if result.accepted else "BROKER_REJECTED",
            broker_order_id=result.broker_order_id,
            message=result.message,
        )

    def process_commands(self) -> None:
        data = self.api.post(
            "commands/lease/", {"contract_version": "1.0", "limit": 20}
        )
        for command in data.get("commands", []):
            success = False
            result: dict[str, Any] = {}
            if command["command_type"] == "cancel":
                broker_order_id = str(command.get("payload", {}).get("broker_order_id") or "")
                success = self.broker.cancel_order(broker_order_id)
                result = {"broker_order_id": broker_order_id, "cancel_accepted": success}
            elif command["command_type"] == "pause":
                self.paused = True
                success = True
                result = {"paused": True}
            elif command["command_type"] == "resume":
                success = not self.config.kill_switch_file.exists()
                self.paused = not success
                result = {"paused": self.paused}
            elif command["command_type"] == "full_sync":
                self.ensure_broker_connection()
                self.sync_broker_events()
                self.sync_snapshot()
                success = True
                result = {"full_sync": True}
            self.api.post(
                "commands/complete/",
                {
                    "contract_version": "1.0",
                    "command_id": command["command_id"],
                    "success": success,
                    "result": result,
                },
            )

    def sync_broker_events(self) -> None:
        """Report idempotent QMT order and fill facts discovered by polling."""

        events = self.broker.poll_events()
        if events:
            self.api.post(
                "events/", {"contract_version": "1.0", "events": events[:200]}
            )

    def run_once(self) -> None:
        """Run one complete polling cycle."""

        self.ensure_broker_connection()
        heartbeat = self.heartbeat()
        if (
            heartbeat.get("kill_switch_active")
            or self.config.kill_switch_file.exists()
            or self.paused
        ):
            self.process_commands()
            self.sync_broker_events()
            self.sync_snapshot()
            return
        leases = self.api.post(
            "orders/lease/",
            {
                "contract_version": "1.0",
                "limit": 10,
                "lease_seconds": self.config.lease_seconds,
            },
        )
        for order in leases.get("orders", []):
            try:
                self.execute_order(order)
            except Exception as exc:
                logger.exception("order validation/execution failed: %s", exc)
        self.sync_broker_events()
        self.process_commands()
        self.sync_snapshot()
