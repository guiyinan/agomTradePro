"""Safe lease, submit, event, command, and recovery orchestration."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from zoneinfo import ZoneInfo

from . import __version__
from .api_client import AgentApiClient
from .config import AgentConfig
from .execution_constraints import (
    ExecutionConstraintViolation,
)
from .execution_submission_v2 import validate_execution_submission_v2
from .qmt_adapter import BrokerAdapter
from .state_store import AgentStateStore

logger = logging.getLogger(__name__)
_UNIX_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=UTC)


def _exact_decimal(value: object, field_name: str) -> Decimal:
    """Parse only exact leased-order numeric types and reject non-finite values."""

    if type(value) is Decimal:
        parsed = value
    elif type(value) is int:
        parsed = Decimal(value)
    elif type(value) is str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise RuntimeError(f"{field_name} is not an exact decimal") from exc
    else:
        raise RuntimeError(f"{field_name} must be str, int, or Decimal")
    if not parsed.is_finite():
        raise RuntimeError(f"{field_name} must be finite")
    return parsed


def _positive_account_id(value: object, field_name: str) -> int:
    """Require a positive exact integer account identifier."""

    if type(value) is not int or value <= 0:
        raise RuntimeError(f"{field_name} must be a positive integer")
    return value


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
        """Report local health and the execution schema supported by this agent."""

        health = self.broker.health()
        return self.api.post(
            "heartbeat/",
            {
                "contract_version": "1.0",
                "observed_at": datetime.now(UTC).isoformat(),
                "qmt_connected": bool(health.get("qmt_connected")),
                "account_ids": [self.config.system_account_id],
                "agent_version": __version__,
                "execution_constraint_schemas": ["a-share-execution-constraints.v2"],
                "qmt_version": str(health.get("qmt_version") or ""),
                "dry_run": self.config.dry_run,
                "message": (
                    "local STOP file active" if self.config.kill_switch_file.exists() else ""
                ),
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
                f"{record['client_order_id']}:{status}:{str(matched.get('broker_order_id') or '')}"
            )
            events.append(
                {
                    "event_id": (
                        "recovery:" + hashlib.sha256(recovery_key.encode("utf-8")).hexdigest()
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

    def _validate_execution_constraints(
        self, order: dict[str, Any], submitted_at: datetime
    ) -> None:
        """Validate current evidence and bind its inner order to the leased order."""

        envelope: object = order.get("execution_constraints")
        validate_execution_submission_v2(envelope, submitted_at=submitted_at)
        self._validate_lease_deadlines(order, submitted_at)
        if type(envelope) is not dict:
            raise RuntimeError("execution constraint envelope is not an object")
        inner_value: object = envelope.get("order")
        if type(inner_value) is not dict:
            raise RuntimeError("execution constraint order is not an object")
        inner_order = cast(dict[str, object], inner_value)

        client_order_id = order.get("client_order_id")
        if type(client_order_id) is not str or not client_order_id:
            raise RuntimeError("execution constraint binding requires client_order_id")
        account_id = _positive_account_id(order.get("account_id"), "account_id")
        asset_code = order.get("asset_code")
        side = order.get("side")
        if type(asset_code) is not str or not asset_code:
            raise RuntimeError("execution constraint binding requires asset_code")
        if type(side) is not str or side not in {"BUY", "SELL"}:
            raise RuntimeError("execution constraint binding requires BUY or SELL side")
        if order.get("order_type") != "LIMIT":
            raise RuntimeError("Only limit orders are permitted")

        if (
            inner_order["order_id"] != client_order_id
            or inner_order["account_id"] != account_id
            or inner_order["security_id"] != asset_code
            or inner_order["side"] != side
        ):
            raise RuntimeError("execution constraint binding mismatch for order identity")
        outer_quantity = _exact_decimal(order.get("quantity"), "quantity")
        outer_limit_price = _exact_decimal(order.get("limit_price"), "limit_price")
        inner_quantity = _exact_decimal(inner_order["quantity"], "execution quantity")
        inner_limit_price = _exact_decimal(inner_order["limit_price"], "execution limit_price")
        if outer_quantity != inner_quantity or outer_limit_price != inner_limit_price:
            raise RuntimeError("execution constraint binding mismatch for quantity or limit price")
        # The canonical projection is already validated and numerically bound;
        # store and submit those exact strings so JSON and QMT see one value.
        order["quantity"] = cast(str, inner_order["quantity"])
        order["limit_price"] = cast(str, inner_order["limit_price"])

    def _validate_lease_deadlines(self, order: dict[str, Any], submitted_at: datetime) -> None:
        """Require both server order and lease deadlines to remain live."""

        for field_name in ("expires_at", "lease_expires_at"):
            raw_value: object = order.get(field_name)
            if type(raw_value) is not str or not raw_value:
                raise RuntimeError(f"{field_name} must be an explicit aware ISO timestamp")
            timestamp_text = f"{raw_value[:-1]}+00:00" if raw_value.endswith("Z") else raw_value
            try:
                deadline = datetime.fromisoformat(timestamp_text)
            except (OverflowError, ValueError) as exc:
                raise RuntimeError(f"{field_name} is not a valid aware ISO timestamp") from exc
            try:
                offset = deadline.utcoffset()
            except (OverflowError, ValueError) as exc:
                raise RuntimeError(f"{field_name} timezone is invalid") from exc
            if deadline.tzinfo is None or offset is None:
                raise RuntimeError(f"{field_name} must be timezone-aware")
            try:
                deadline_utc = deadline.astimezone(UTC)
            except (OverflowError, ValueError) as exc:
                raise RuntimeError(f"{field_name} cannot be normalized to UTC") from exc
            if deadline_utc <= submitted_at:
                raise RuntimeError(f"{field_name} has expired")

    def _validate_local_order_identity(self, order: dict[str, Any]) -> None:
        """Recheck local stop, account scope, order type, and exact positive prices."""

        if self.config.kill_switch_file.exists():
            raise RuntimeError("Local STOP file is active")
        account_id = _positive_account_id(order.get("account_id"), "account_id")
        if account_id != self.config.system_account_id:
            raise RuntimeError("Leased order account does not match local account")
        if order.get("order_type") != "LIMIT" or order.get("limit_price") in (None, ""):
            raise RuntimeError("Only limit orders are permitted")
        quantity = _exact_decimal(order.get("quantity"), "quantity")
        price = _exact_decimal(order.get("limit_price"), "limit_price")
        if quantity <= 0 or price <= 0:
            raise RuntimeError("Order quantity and price must be positive")

    def _validate_before_submit(
        self, order: dict[str, Any], *, check_idempotency: bool = True
    ) -> None:
        """Check constraints, local scope, market, funds, holdings, and idempotency."""

        submitted_at = datetime.now(UTC)
        self._validate_execution_constraints(order, submitted_at)
        self._validate_local_order_identity(order)
        self._validate_local_trading_session(submitted_at)
        market = self.broker.market_snapshot(str(order["asset_code"]))
        market_read_at = datetime.now(UTC)
        self._validate_execution_constraints(order, market_read_at)
        self._validate_local_trading_session(market_read_at)
        last_price = self._validated_local_last_price(order, market, market_read_at)
        quantity = _exact_decimal(order.get("quantity"), "quantity")
        price = _exact_decimal(order.get("limit_price"), "limit_price")
        deviation_limit = Decimal(str(getattr(self.config, "price_deviation_limit_pct", 0.03)))
        if deviation_limit > 0 and abs(price - last_price) / last_price > deviation_limit:
            raise RuntimeError("Limit price deviates too far from the current market price")

        snapshot = self.broker.account_snapshot()
        self._validate_local_account_capacity(order, snapshot, quantity, price)
        if check_idempotency and self.state.get(str(order["client_order_id"])) is not None:
            raise RuntimeError("Order already exists in the local idempotency store")

        # Broker snapshots can block. Recheck all time-bound contracts and local
        # controls after every broker read, using the exact source tick retained
        # above and one fresh local clock value immediately before submit.
        submission_check_at = datetime.now(UTC)
        self._validate_execution_constraints(order, submission_check_at)
        self._validate_local_order_identity(order)
        self._validate_local_trading_session(submission_check_at)
        self._validated_local_last_price(order, market, submission_check_at)

    def _validate_local_trading_session(self, submitted_at: datetime) -> None:
        """Apply the configured local session as an additional restriction."""

        if bool(getattr(self.config, "enforce_trading_session", True)):
            local_now = submitted_at.astimezone(
                ZoneInfo(getattr(self.config, "trading_timezone", "Asia/Shanghai"))
            )
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

    def _validate_local_account_capacity(
        self,
        order: dict[str, Any],
        snapshot: dict[str, Any],
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        """Check current local cash or available holdings for the leased order."""

        if order["side"] == "BUY":
            if Decimal(str(snapshot.get("cash_available") or "0")) < quantity * price:
                raise RuntimeError("Available cash is insufficient")
            held_symbols = {
                str(item.get("asset_code") or "").upper()
                for item in snapshot.get("positions", [])
                if Decimal(str(item.get("quantity") or "0")) > 0
            }
            if str(order["asset_code"]).upper() not in held_symbols and len(held_symbols) >= int(
                getattr(self.config, "max_position_count", 20)
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
            if (
                position is None
                or Decimal(str(position.get("available_quantity") or "0")) < quantity
            ):
                raise RuntimeError("Available position is insufficient")

    def _validated_local_last_price(
        self,
        order: dict[str, Any],
        snapshot: object,
        submitted_at: datetime,
    ) -> Decimal:
        """Require exact fresh last-price evidence from the source QMT tick."""

        if type(snapshot) is not dict:
            raise RuntimeError("Local market snapshot must be an object")
        market = cast(dict[str, Any], snapshot)
        if market.get("asset_code") != order.get("asset_code"):
            raise RuntimeError("Local market snapshot asset does not match the order")
        fields_value: object = market.get("field_evidence")
        if type(fields_value) is not dict:
            raise RuntimeError("Local market field evidence is missing")
        fields = cast(dict[str, object], fields_value)
        last_value: object = fields.get("last_price")
        tick_value: object = fields.get("tick_time_ms")
        if type(last_value) is not dict or type(tick_value) is not dict:
            raise RuntimeError("Local price or source tick-time evidence is missing")
        last_evidence = cast(dict[str, object], last_value)
        tick_evidence = cast(dict[str, object], tick_value)
        if (
            last_evidence.get("state") != "PRESENT"
            or last_evidence.get("source_api") != "xtdata.get_full_tick"
            or last_evidence.get("source_field") != "lastPrice"
            or last_evidence.get("reason_code") is not None
        ):
            raise RuntimeError("Local last price is not exact PRESENT QMT tick evidence")
        last_raw: object = market.get("last_price")
        evidence_last_raw: object = last_evidence.get("value")
        if type(last_raw) is not str or type(evidence_last_raw) is not str:
            raise RuntimeError("Local last price must be a canonical decimal string")
        last_price = _exact_decimal(last_raw, "local last_price")
        if (
            last_price <= 0
            or _exact_decimal(evidence_last_raw, "evidence last_price") != last_price
        ):
            raise RuntimeError("Local last price value is invalid or inconsistent")

        tick_time_ms: object = market.get("tick_time_ms")
        evidence_tick_time_ms: object = tick_evidence.get("value")
        if (
            type(tick_time_ms) is not int
            or tick_time_ms <= 0
            or evidence_tick_time_ms != tick_time_ms
            or type(evidence_tick_time_ms) is not int
            or tick_evidence.get("state") != "PRESENT"
            or tick_evidence.get("source_api") != "xtdata.get_full_tick"
            or tick_evidence.get("source_field") != "time"
            or tick_evidence.get("reason_code") is not None
        ):
            raise RuntimeError("Local source tick time is not exact PRESENT QMT evidence")
        try:
            source_tick_at = _UNIX_EPOCH + timedelta(milliseconds=tick_time_ms)
        except (OverflowError, ValueError) as exc:
            raise RuntimeError("Local source tick time is outside the supported range") from exc

        envelope_value: object = order.get("execution_constraints")
        if type(envelope_value) is not dict:
            raise RuntimeError("Execution constraint envelope is not an object")
        envelope = cast(dict[str, Any], envelope_value)
        market_value: object = envelope.get("market_evidence")
        if type(market_value) is not dict:
            raise RuntimeError("Execution market evidence is missing")
        market_envelope = cast(dict[str, Any], market_value)
        base_value: object = market_envelope.get("market_evidence_v1")
        if type(base_value) is not dict:
            raise RuntimeError("Base market evidence is missing")
        base_market = cast(dict[str, Any], base_value)
        observed_raw: object = base_market.get("market_observed_at")
        if type(observed_raw) is not str or not observed_raw.endswith("Z"):
            raise RuntimeError("Approved market source time is missing or invalid")
        try:
            market_observed_at = datetime.fromisoformat(observed_raw[:-1] + "+00:00").astimezone(
                UTC
            )
        except (OverflowError, ValueError) as exc:
            raise RuntimeError("Approved market source time is invalid") from exc
        if market_observed_at.tzinfo is None or market_observed_at.utcoffset() is None:
            raise RuntimeError("Approved market source time must be aware")
        normalized_submitted_at = submitted_at.astimezone(UTC)
        if not market_observed_at <= source_tick_at <= normalized_submitted_at:
            raise RuntimeError(
                "Local source tick must be no older than approved market evidence and not future"
            )
        return last_price

    def _validate_ack_order(self, response: object, order: dict[str, Any]) -> None:
        """Require a strict accepted ACK and an exact echo of the leased order."""

        if type(response) is not dict or response.get("accepted") is not True:
            raise RuntimeError("server ACK did not strictly accept the order")
        acknowledged_value: object = response.get("order")
        if type(acknowledged_value) is not dict:
            raise RuntimeError("server ACK omitted its order echo")
        acknowledged = cast(dict[str, object], acknowledged_value)
        if acknowledged.get("order_type") != "LIMIT":
            raise RuntimeError("server ACK order type is not LIMIT")
        for field_name in ("client_order_id", "asset_code", "side"):
            if acknowledged.get(field_name) != order.get(field_name):
                raise RuntimeError(f"server ACK order echo mismatch for {field_name}")
        acknowledged_account = _positive_account_id(
            acknowledged.get("account_id"), "ACK account_id"
        )
        if acknowledged_account != _positive_account_id(order.get("account_id"), "account_id"):
            raise RuntimeError("server ACK order echo mismatch for account_id")
        if _exact_decimal(acknowledged.get("quantity"), "ACK quantity") != _exact_decimal(
            order.get("quantity"), "quantity"
        ):
            raise RuntimeError("server ACK order echo mismatch for quantity")
        if _exact_decimal(acknowledged.get("limit_price"), "ACK limit_price") != _exact_decimal(
            order.get("limit_price"), "limit_price"
        ):
            raise RuntimeError("server ACK order echo mismatch for limit_price")

    def _report_submission(
        self,
        order: dict[str, Any],
        *,
        status: str,
        event_type: str,
        broker_submit_attempted: bool,
        broker_order_id: str = "",
        message: str = "",
        event_id: str = "",
    ) -> None:
        """Report a local submission outcome and whether QMT was called."""

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
                        "payload": {
                            "message": message,
                            "dry_run": self.config.dry_run,
                            "broker_submit_attempted": broker_submit_attempted,
                        },
                    }
                ],
            },
        )

    def execute_order(self, order: dict[str, Any]) -> None:
        """Validate, record local state, obtain server ACK, then call QMT once."""

        self._validate_before_submit(order)
        if self.config.dry_run:
            logger.info("dry-run validated order %s", order["client_order_id"])
            evidence_key = (
                f"{order['client_order_id']}:{order.get('approval_digest', '')}:DRY_RUN_VALIDATED"
            )
            self._report_submission(
                order,
                status="",
                event_type="DRY_RUN_VALIDATED",
                broker_submit_attempted=False,
                message="Validated locally without submitting to QMT",
                event_id=("dry-run:" + hashlib.sha256(evidence_key.encode("utf-8")).hexdigest()),
            )
            return
        self.state.mark_submitting(str(order["client_order_id"]), order)
        try:
            acknowledgment = self.api.post(
                "orders/submitting/",
                {
                    "contract_version": "1.0",
                    "client_order_id": order["client_order_id"],
                    "lease_token": order["lease_token"],
                },
            )
        except Exception as exc:
            self.state.mark_result(str(order["client_order_id"]), "RECONCILIATION_REQUIRED")
            self._report_submission(
                order,
                status="RECONCILIATION_REQUIRED",
                event_type="SERVER_ACK_OUTCOME_UNKNOWN",
                broker_submit_attempted=False,
                message=str(exc),
            )
            return
        try:
            self._validate_ack_order(acknowledgment, order)
            self._validate_before_submit(order, check_idempotency=False)
        except (
            ArithmeticError,
            ExecutionConstraintViolation,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            self.state.mark_result(str(order["client_order_id"]), "FAILED")
            self._report_submission(
                order,
                status="FAILED",
                event_type="LOCAL_SUBMIT_VALIDATION_FAILED",
                broker_submit_attempted=False,
                message=str(exc),
            )
            return
        try:
            result = self.broker.submit_order(order)
        except Exception as exc:
            self.state.mark_result(str(order["client_order_id"]), "RECONCILIATION_REQUIRED")
            self._report_submission(
                order,
                status="RECONCILIATION_REQUIRED",
                event_type="SUBMIT_OUTCOME_UNKNOWN",
                broker_submit_attempted=True,
                message=str(exc),
            )
            return
        status = "SUBMITTED" if result.accepted else "BROKER_REJECTED"
        self.state.mark_result(str(order["client_order_id"]), status, result.broker_order_id)
        self._report_submission(
            order,
            status=status,
            event_type="ORDER_SUBMITTED" if result.accepted else "BROKER_REJECTED",
            broker_submit_attempted=True,
            broker_order_id=result.broker_order_id,
            message=result.message,
        )

    def process_commands(self) -> None:
        data = self.api.post("commands/lease/", {"contract_version": "1.0", "limit": 20})
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
            self.api.post("events/", {"contract_version": "1.0", "events": events[:200]})

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
