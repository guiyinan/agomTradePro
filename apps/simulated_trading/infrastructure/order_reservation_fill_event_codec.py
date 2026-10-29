"""Canonical local fill-event wire codec with an explicit daily clock branch.

Legacy event payload bytes remain unchanged. The daily interval schema stores
the interval end and local knowledge clocks separately while leaving supplier
observation and availability unknown. This codec validates structure, not
source qualification, account ownership, or a read cutoff.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, TypeAlias, TypedDict, cast

from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
    validate_local_simulated_fill_event,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _decimal_from_text,
    _decimal_numeric_text,
    _require_aware,
    _utc_text,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide

_logger = logging.getLogger(__name__)
_LEGACY_SCHEMA = "local-simulated-fill-event.v1"
_DAILY_INTERVAL_SCHEMA = "local-simulated-fill-event.daily-interval.v1"
_MAX_EVENT_JSON_LENGTH = 262_144


class _LegacyEventPayload(TypedDict):
    schema: str
    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_hash: str
    source_snapshot_id: str
    source_snapshot_hash: str
    reservation_id: int
    account_id: int
    user_id: int
    order_idempotency_key: str
    intent_payload_hash: str
    reservation_request_hash: str
    plan_snapshot_hash: str
    security_id: str
    asset_code: str
    side: str
    event_kind: str
    quantity: str
    price: str
    occurred_at: str
    source_observed_at: str
    source_available_at: str
    recorded_at: str


class _DailyIntervalEventPayload(TypedDict):
    schema: str
    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_hash: str
    source_snapshot_id: str
    source_snapshot_hash: str
    reservation_id: int
    account_id: int
    user_id: int
    order_idempotency_key: str
    intent_payload_hash: str
    reservation_request_hash: str
    plan_snapshot_hash: str
    security_id: str
    asset_code: str
    side: str
    event_kind: str
    quantity: str
    price: str
    occurred_at: str
    source_observed_at: None
    source_available_at: None
    recorded_at: str
    observation_basis: Literal["daily_interval_end"]
    interval_end_at: str
    local_known_at: str


_EventPayload: TypeAlias = _LegacyEventPayload | _DailyIntervalEventPayload
_LEGACY_FIELDS = (
    "schema",
    "source_namespace",
    "source_version",
    "source_event_id",
    "event_payload_hash",
    "source_snapshot_id",
    "source_snapshot_hash",
    "reservation_id",
    "account_id",
    "user_id",
    "order_idempotency_key",
    "intent_payload_hash",
    "reservation_request_hash",
    "plan_snapshot_hash",
    "security_id",
    "asset_code",
    "side",
    "event_kind",
    "quantity",
    "price",
    "occurred_at",
    "source_observed_at",
    "source_available_at",
    "recorded_at",
)
_DAILY_FIELDS = _LEGACY_FIELDS + (
    "observation_basis",
    "interval_end_at",
    "local_known_at",
)


def _canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize one event payload in the original canonical JSON format."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("event payload is not canonical JSON") from error


def _require_text(value: object, field_name: str) -> str:
    """Require one literal string at the event JSON boundary."""

    if type(value) is not str:
        raise SimulatedSettlementContractError(f"{field_name} must be text")
    return value


def _require_int(value: object, field_name: str) -> int:
    """Require one literal integer at the event JSON boundary."""

    if type(value) is not int:
        raise SimulatedSettlementContractError(f"{field_name} must be an integer")
    return value


def _expect_object(
    value: object,
    *,
    field_names: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    """Narrow JSON data and require the exact event schema field set."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SimulatedSettlementContractError(f"{label} must be a JSON object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != frozenset(field_names):
        raise SimulatedSettlementContractError(f"{label} fields are missing or unknown")
    return payload


def _wire_decimal_text(value: Decimal) -> str:
    """Keep the established numeric-spelling normalization, including zero."""

    normalized = _decimal_numeric_text(value)
    return "0" if value.is_zero() else normalized


def _parse_decimal(value: object, field_name: str) -> Decimal:
    """Parse one bounded canonical decimal without float conversion."""

    return _decimal_from_text(value, field_name)


def _parse_datetime(value: object, field_name: str) -> datetime:
    """Parse one canonical UTC instant while preserving its exact clock value."""

    text = _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        _require_aware(parsed, field_name)
        if _utc_text(parsed) != text:
            raise SimulatedSettlementContractError(f"{field_name} is not canonical UTC text")
        return parsed.astimezone(UTC)
    except SimulatedSettlementContractError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} is not an aware UTC instant"
        ) from error


def _log_unknown_kind() -> None:
    """Log a fixed event-kind diagnostic without identifiers or source values."""

    _logger.warning(
        "Unknown local simulated fill event kind rejected by event codec",
        extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
    )


def _event_payload(event: LocalSimulatedFillEventV1) -> _EventPayload:
    """Build exact legacy bytes or a daily interval event payload."""

    common: dict[str, object] = {
        "source_namespace": event.source_namespace,
        "source_version": event.source_version,
        "source_event_id": event.source_event_id,
        "event_payload_hash": event.event_payload_hash,
        "source_snapshot_id": event.source_snapshot_id,
        "source_snapshot_hash": event.source_snapshot_hash,
        "reservation_id": event.reservation_id,
        "account_id": event.account_id,
        "user_id": event.user_id,
        "order_idempotency_key": event.order_idempotency_key,
        "intent_payload_hash": event.intent_payload_hash,
        "reservation_request_hash": event.reservation_request_hash,
        "plan_snapshot_hash": event.plan_snapshot_hash,
        "security_id": event.security_id,
        "asset_code": event.asset_code,
        "side": event.side.value,
        "event_kind": event.event_kind.value,
        "quantity": _wire_decimal_text(event.quantity),
        "price": _wire_decimal_text(event.price),
        "occurred_at": _utc_text(event.occurred_at),
        "recorded_at": _utc_text(event.recorded_at),
    }
    if event.observation_basis == "daily_interval_end":
        if (
            type(event.interval_end_at) is not datetime
            or type(event.local_known_at) is not datetime
            or event.source_observed_at is not None
            or event.source_available_at is not None
        ):
            raise SimulatedSettlementContractError("daily event clocks are invalid")
        return cast(
            _DailyIntervalEventPayload,
            {
                "schema": _DAILY_INTERVAL_SCHEMA,
                **common,
                "source_observed_at": None,
                "source_available_at": None,
                "observation_basis": "daily_interval_end",
                "interval_end_at": _utc_text(event.interval_end_at),
                "local_known_at": _utc_text(event.local_known_at),
            },
        )
    if (
        type(event.source_observed_at) is not datetime
        or type(event.source_available_at) is not datetime
    ):
        raise SimulatedSettlementContractError("legacy event source clocks are required")
    return cast(
        _LegacyEventPayload,
        {
            "schema": _LEGACY_SCHEMA,
            **common,
            "source_observed_at": _utc_text(event.source_observed_at),
            "source_available_at": _utc_text(event.source_available_at),
        },
    )


def encode_local_simulated_fill_event(event: object) -> str:
    """Validate and serialize one event using its exact basis-specific wire shape."""

    checked = validate_local_simulated_fill_event(event)
    return _canonical_json(_event_payload(checked))


def decode_local_simulated_fill_event(text: object) -> LocalSimulatedFillEventV1:
    """Decode either exact event schema and verify its canonical typed representation."""

    if type(text) is not str or not text or len(text) > _MAX_EVENT_JSON_LENGTH:
        raise SimulatedSettlementContractError("source event JSON is missing or oversized")
    try:
        raw_value: object = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("source event JSON is invalid") from error
    if type(raw_value) is not dict:
        raise SimulatedSettlementContractError("source event must be a JSON object")
    schema = raw_value.get("schema")
    if schema == _LEGACY_SCHEMA:
        payload = _expect_object(raw_value, field_names=_LEGACY_FIELDS, label="source event")
        observation_basis: Literal["legacy_source_observed", "daily_interval_end"] = (
            "legacy_source_observed"
        )
        interval_end_at: datetime | None = None
        local_known_at: datetime | None = None
        source_observed_at: datetime | None = _parse_datetime(
            payload["source_observed_at"], "source_observed_at"
        )
        source_available_at: datetime | None = _parse_datetime(
            payload["source_available_at"], "source_available_at"
        )
    elif schema == _DAILY_INTERVAL_SCHEMA:
        payload = _expect_object(
            raw_value,
            field_names=_DAILY_FIELDS,
            label="daily interval source event",
        )
        if payload["source_observed_at"] is not None or payload["source_available_at"] is not None:
            raise SimulatedSettlementContractError("daily interval supplier clocks must be null")
        basis_text = _require_text(payload["observation_basis"], "observation_basis")
        if basis_text != "daily_interval_end":
            raise SimulatedSettlementContractError("daily interval event basis is unsupported")
        observation_basis = "daily_interval_end"
        interval_end_at = _parse_datetime(payload["interval_end_at"], "interval_end_at")
        local_known_at = _parse_datetime(payload["local_known_at"], "local_known_at")
        source_observed_at = None
        source_available_at = None
    else:
        raise SimulatedSettlementContractError("source event schema is unsupported")
    if _canonical_json(payload) != text:
        raise SimulatedSettlementContractError("source event JSON is not canonical")

    try:
        side = SimulatedTradeSide(_require_text(payload["side"], "side"))
    except ValueError as error:
        raise SimulatedSettlementContractError("event side is unsupported") from error
    kind_text = payload["event_kind"]
    if type(kind_text) is not str:
        _log_unknown_kind()
        raise SimulatedSettlementContractError("event kind is unknown")
    try:
        event_kind = LocalSimulatedFillEventKind(kind_text)
    except ValueError as error:
        _log_unknown_kind()
        raise SimulatedSettlementContractError("event kind is unknown") from error
    if event_kind is LocalSimulatedFillEventKind.UNKNOWN:
        _log_unknown_kind()
        raise SimulatedSettlementContractError("event kind is unknown")

    event = LocalSimulatedFillEventV1(
        source_namespace=_require_text(payload["source_namespace"], "source_namespace"),
        source_version=_require_text(payload["source_version"], "source_version"),
        source_event_id=_require_text(payload["source_event_id"], "source_event_id"),
        event_payload_hash=_require_text(payload["event_payload_hash"], "event_payload_hash"),
        source_snapshot_id=_require_text(payload["source_snapshot_id"], "source_snapshot_id"),
        source_snapshot_hash=_require_text(payload["source_snapshot_hash"], "source_snapshot_hash"),
        reservation_id=_require_int(payload["reservation_id"], "reservation_id"),
        account_id=_require_int(payload["account_id"], "account_id"),
        user_id=_require_int(payload["user_id"], "user_id"),
        order_idempotency_key=_require_text(
            payload["order_idempotency_key"], "order_idempotency_key"
        ),
        intent_payload_hash=_require_text(payload["intent_payload_hash"], "intent_payload_hash"),
        reservation_request_hash=_require_text(
            payload["reservation_request_hash"], "reservation_request_hash"
        ),
        plan_snapshot_hash=_require_text(payload["plan_snapshot_hash"], "plan_snapshot_hash"),
        security_id=_require_text(payload["security_id"], "security_id"),
        asset_code=_require_text(payload["asset_code"], "asset_code"),
        side=side,
        event_kind=event_kind,
        quantity=validate_ledger_quantity(
            _parse_decimal(payload["quantity"], "quantity"),
            "quantity",
            allow_zero=False,
        ),
        price=validate_ledger_price(
            _parse_decimal(payload["price"], "price"),
            "price",
            allow_zero=False,
        ),
        occurred_at=_parse_datetime(payload["occurred_at"], "occurred_at"),
        source_observed_at=source_observed_at,
        source_available_at=source_available_at,
        recorded_at=_parse_datetime(payload["recorded_at"], "recorded_at"),
        observation_basis=observation_basis,
        interval_end_at=interval_end_at,
        local_known_at=local_known_at,
    )
    checked = validate_local_simulated_fill_event(event)
    if encode_local_simulated_fill_event(checked) != text:
        raise SimulatedSettlementContractError("source event JSON differs from its typed value")
    return checked


__all__: tuple[str, ...] = (
    "decode_local_simulated_fill_event",
    "encode_local_simulated_fill_event",
    "validate_local_simulated_fill_event",
)
