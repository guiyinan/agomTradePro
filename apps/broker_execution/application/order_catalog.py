"""Typed, lossy, and display-only broker order catalog projection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderStatus,
    LiveOrderType,
)

JsonObject = dict[str, object]

DISPLAY_ONLY: Final = "display_only"
_ACTIONS: Final = ("approve", "reject", "cancel")
_DISPLAY_BLOCKER: Final = "broker_order_catalog_display_only"


def _require_aware(value: datetime) -> datetime:
    """Return a UTC projection clock or reject a naive caller clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _actions(value: object) -> dict[str, bool]:
    """Return only the stable order action flags."""

    source = value if isinstance(value, Mapping) else {}
    return {action: source.get(action) is True for action in _ACTIONS}


def _text(
    value: object,
    *,
    field: str,
    max_length: int,
    blockers: list[str],
    required: bool = False,
) -> str | None:
    """Project one bounded string without coercing dynamic values."""

    if value is None and not required:
        return None
    if not isinstance(value, str):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    normalized = value.strip()
    if (required and not normalized) or len(normalized) > max_length:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return normalized


def _positive_int(value: object, *, field: str, blockers: list[str]) -> int | None:
    """Project a positive integer without accepting booleans."""

    if type(value) is not int or value <= 0:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return value


def _non_negative_int(value: object, *, field: str, blockers: list[str]) -> int | None:
    """Project a non-negative integer without accepting booleans."""

    if type(value) is not int or value < 0:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return value


def _decimal_text(
    value: object,
    *,
    field: str,
    blockers: list[str],
    required: bool = True,
    positive: bool = False,
) -> str | None:
    """Project one finite Decimal as canonical plain text."""

    if value is None and not required:
        return None
    if isinstance(value, bool):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    if not parsed.is_finite() or parsed < 0 or (positive and parsed <= 0):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return format(parsed, "f")


def _aware_time(
    value: object,
    *,
    field: str,
    blockers: list[str],
    required: bool = False,
) -> str | None:
    """Parse and normalize one aware ISO timestamp."""

    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return parsed.astimezone(UTC).isoformat()


def _parsed_time(value: str | None) -> datetime | None:
    """Parse a previously normalized UTC timestamp."""

    return datetime.fromisoformat(value) if value is not None else None


def _enum_value(
    value: object,
    *,
    enum_type: type[LiveOrderSide] | type[LiveOrderType] | type[LiveOrderStatus],
    field: str,
    blockers: list[str],
) -> str | None:
    """Project one exact broker order enum value."""

    if not isinstance(value, str):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    try:
        enum_value = enum_type(value.strip()).value
    except ValueError:
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    if not isinstance(enum_value, str):
        blockers.append(f"broker_order_catalog_{field}_invalid")
        return None
    return enum_value


def _canonical_uuid(value: object, *, blockers: list[str]) -> str | None:
    """Project one canonical client order UUID."""

    if not isinstance(value, str):
        blockers.append("broker_order_catalog_client_order_id_invalid")
        return None
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        blockers.append("broker_order_catalog_client_order_id_invalid")
        return None


def _risk_hash(value: object, *, blockers: list[str]) -> str | None:
    """Replace raw risk JSON with its deterministic content hash."""

    if not isinstance(value, Mapping):
        blockers.append("broker_order_catalog_risk_snapshot_invalid")
        return None
    try:
        canonical = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        blockers.append("broker_order_catalog_risk_snapshot_invalid")
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerOrderCatalogItem:
    """One bounded order summary with non-authoritative action hints."""

    order: JsonObject
    evaluated_at: datetime
    lifecycle_transitions: dict[str, bool]
    actor_authorization: dict[str, bool]
    evidence_gate: dict[str, bool]
    effective_actions: dict[str, bool]
    blocker_codes: tuple[str, ...]
    permission: str = DISPLAY_ONLY
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        """Keep catalog rows display-only and action maps exact."""

        _require_aware(self.evaluated_at)
        if self.permission != DISPLAY_ONLY:
            raise ValueError("broker order catalog permission must remain display_only")
        if self.must_not_use_for_decision is not True or self.must_not_execute is not True:
            raise ValueError("broker order catalog must remain non-executable")
        for actions in (
            self.lifecycle_transitions,
            self.actor_authorization,
            self.evidence_gate,
            self.effective_actions,
        ):
            if set(actions) != set(_ACTIONS) or not all(
                type(flag) is bool for flag in actions.values()
            ):
                raise ValueError("broker order catalog action maps are invalid")
        if self.evidence_gate["approve"] is not False:
            raise ValueError("catalog approval must require the order-detail Evidence gate")
        if _DISPLAY_BLOCKER not in self.blocker_codes:
            raise ValueError("catalog rows must publish the display-only blocker")

    def to_payload(self) -> JsonObject:
        """Return the safe order summary and governed read markers."""

        return {
            **self.order,
            "evaluated_at": self.evaluated_at.isoformat(),
            "action_availability": dict(self.lifecycle_transitions),
            "lifecycle_transitions": dict(self.lifecycle_transitions),
            "actor_authorization": dict(self.actor_authorization),
            "evidence_gate": dict(self.evidence_gate),
            "effective_actions": dict(self.effective_actions),
            "risk_snapshot_policy": "content_hash_only",
            "blocker_codes": list(self.blocker_codes),
            "permission": self.permission,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }


def project_broker_order_catalog_item(
    raw: Mapping[str, object],
    *,
    evaluated_at: datetime,
    actor_authorization: Mapping[str, bool],
) -> BrokerOrderCatalogItem:
    """Project one repository row without exposing raw or executable data."""

    evaluated = _require_aware(evaluated_at)
    blockers: list[str] = []
    client_order_id = _canonical_uuid(raw.get("client_order_id"), blockers=blockers)
    account_id = _positive_int(raw.get("account_id"), field="account_id", blockers=blockers)
    asset_code = _text(
        raw.get("asset_code"),
        field="asset_code",
        max_length=32,
        blockers=blockers,
        required=True,
    )
    market = _text(
        raw.get("market"),
        field="market",
        max_length=16,
        blockers=blockers,
        required=True,
    )
    side = _enum_value(raw.get("side"), enum_type=LiveOrderSide, field="side", blockers=blockers)
    order_type = _enum_value(
        raw.get("order_type"),
        enum_type=LiveOrderType,
        field="order_type",
        blockers=blockers,
    )
    quantity = _decimal_text(
        raw.get("quantity"), field="quantity", blockers=blockers, positive=True
    )
    limit_price = _decimal_text(
        raw.get("limit_price"), field="limit_price", blockers=blockers, positive=True
    )
    estimated_amount = _decimal_text(
        raw.get("estimated_amount"),
        field="estimated_amount",
        blockers=blockers,
        positive=True,
    )
    status = _enum_value(
        raw.get("status"), enum_type=LiveOrderStatus, field="status", blockers=blockers
    )
    expires_at = _aware_time(raw.get("expires_at"), field="expires_at", blockers=blockers)
    submitted_at = _aware_time(raw.get("submitted_at"), field="submitted_at", blockers=blockers)
    created_at = _aware_time(
        raw.get("created_at"), field="created_at", blockers=blockers, required=True
    )
    updated_at = _aware_time(
        raw.get("updated_at"), field="updated_at", blockers=blockers, required=True
    )
    filled_quantity = _decimal_text(
        raw.get("filled_quantity"),
        field="filled_quantity",
        blockers=blockers,
        required=False,
    )
    version = _positive_int(raw.get("version"), field="version", blockers=blockers)
    created = _parsed_time(created_at)
    updated = _parsed_time(updated_at)
    submitted = _parsed_time(submitted_at)
    expires = _parsed_time(expires_at)
    if created is not None and updated is not None and not created <= updated <= evaluated:
        blockers.append("broker_order_catalog_time_order_invalid")
    if submitted is not None and created is not None and submitted < created:
        blockers.append("broker_order_catalog_submitted_at_invalid")
    if expires is not None and created is not None and expires <= created:
        blockers.append("broker_order_catalog_expires_at_invalid")
    if quantity is not None and filled_quantity is not None:
        if Decimal(filled_quantity) > Decimal(quantity):
            blockers.append("broker_order_catalog_filled_quantity_invalid")

    order: JsonObject = {
        "client_order_id": client_order_id,
        "account_id": account_id,
        "asset_code": asset_code,
        "market": market,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "limit_price": limit_price,
        "estimated_amount": estimated_amount,
        "status": status,
        "expires_at": expires_at,
        "submitted_at": submitted_at,
        "filled_quantity": filled_quantity,
        "average_fill_price": _decimal_text(
            raw.get("average_fill_price"),
            field="average_fill_price",
            blockers=blockers,
            required=False,
        ),
        "failure_code": _text(
            raw.get("failure_code"),
            field="failure_code",
            max_length=64,
            blockers=blockers,
        ),
        "version": version,
        "created_at": created_at,
        "updated_at": updated_at,
        "risk_snapshot_content_hash": _risk_hash(raw.get("risk_snapshot"), blockers=blockers),
    }
    lifecycle = _actions(raw.get("action_availability"))
    authorization = _actions(actor_authorization)
    evidence_gate = {"approve": False, "reject": True, "cancel": True}
    invalid = bool(blockers)
    effective = {
        action: (
            not invalid and lifecycle[action] and authorization[action] and evidence_gate[action]
        )
        for action in _ACTIONS
    }
    return BrokerOrderCatalogItem(
        order=order,
        evaluated_at=evaluated,
        lifecycle_transitions=lifecycle,
        actor_authorization=authorization,
        evidence_gate=evidence_gate,
        effective_actions=effective,
        blocker_codes=tuple(dict.fromkeys([_DISPLAY_BLOCKER, *blockers])),
    )


__all__ = ["BrokerOrderCatalogItem", "project_broker_order_catalog_item"]
