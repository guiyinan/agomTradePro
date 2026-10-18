"""Validated storage-boundary codec for broker execution facts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast

from apps.account.application.broker_trade_reconciliation_contracts import (
    BalanceSnapshot,
    BaselineDeclarationView,
    BrokerBaselineDecision,
    BrokerFactCandidate,
    BrokerFactProjectionResult,
    BrokerFactRecord,
    BrokerReconciliationView,
    BrokerTradeAction,
    JsonObject,
    JsonValue,
    MatchingAttemptView,
    MatchingOutcomeKind,
    ProjectionAttemptView,
    ProjectionOutcomeKind,
)
from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState
from apps.account.domain.broker_trade_reconciliation_fingerprints import (
    BrokerFactIdentity,
    canonical_float,
)
from apps.account.infrastructure.models import TransactionModel
from core.exceptions import InvalidInputError

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_SHARE_QUANTUM = Decimal("0.000001")

_PRICE_QUANTUM = Decimal("0.0001")

_FEE_QUANTUM = Decimal("0.01")

_NOTIONAL_QUANTUM = Decimal("0.01")

_UTC = UTC


def _as_decimal(value: object, field_name: str) -> Decimal:
    """Narrow a Decimal or numeric ORM boundary value and reject non-finite input."""

    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise InvalidInputError(f"{field_name} must be a finite decimal") from error
    if not result.is_finite():
        raise InvalidInputError(f"{field_name} must be a finite decimal")
    return result


def _quantized(value: Decimal, quantum: Decimal, field_name: str) -> Decimal:
    """Reject source values that the persisted ORM precision would silently round."""

    try:
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise InvalidInputError(f"{field_name} exceeds supported persistence precision") from error
    if rounded != value:
        raise InvalidInputError(f"{field_name} exceeds supported persistence precision")
    return rounded


def _fits_decimal_field(value: Decimal, *, max_digits: int, decimal_places: int) -> bool:
    """Check DecimalField magnitude and scale before sending values to the ORM."""

    try:
        quantum = Decimal(1).scaleb(-decimal_places)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    integer_limit = Decimal(10) ** (max_digits - decimal_places)
    return rounded == value and abs(rounded) < integer_limit


def _aware_datetime(value: datetime, field_name: str) -> datetime:
    """Require an aware instant without normalizing its stored source offset."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidInputError(f"{field_name} must be timezone-aware")
    return value


def _json_value(value: object) -> JsonValue:
    """Recursively narrow JSON input and reject values the JSONField cannot retain."""

    if value is None or type(value) in {str, bool, int}:
        return cast(JsonValue, value)
    if type(value) is float:
        if not math.isfinite(value):
            raise InvalidInputError("raw_payload contains a non-finite number")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidInputError("raw_payload contains a non-finite decimal")
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            _aware_datetime(value, "raw_payload datetime")
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise InvalidInputError("raw_payload object keys must be strings")
            result[key] = _json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise InvalidInputError("raw_payload contains a non-JSON value")


def _json_object(value: object, *, field_name: str) -> dict[str, JsonValue]:
    """Narrow a JSON object at the ORM edge."""

    narrowed = _json_value(value)
    if not isinstance(narrowed, dict):
        raise InvalidInputError(f"{field_name} must be a JSON object")
    return narrowed


def _string(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: JsonValue | None) -> int | None:
    return value if type(value) is int else None


def _parse_datetime(value: JsonValue | None) -> datetime | None:
    """Parse one persisted ISO datetime and reject naive stored values."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _details(model: TransactionModel) -> dict[str, JsonValue]:
    """Return checked reconciliation JSON without discarding unknown audit keys."""

    return _json_object(model.broker_reconciliation_details, field_name="reconciliation details")


def _fact_identity(model: TransactionModel) -> BrokerFactIdentity:
    """Build the exact economic digest row from a locked persisted transaction."""

    if model.broker_trade_key is None:
        raise InvalidInputError("broker fact is missing its stable key")
    if model.action not in {"buy", "sell"}:
        raise InvalidInputError("broker fact action is not recognized")
    traded_at = _aware_datetime(model.traded_at, "traded_at")
    shares = _quantized(_as_decimal(model.shares, "shares"), _SHARE_QUANTUM, "shares")
    price = _quantized(_as_decimal(model.price, "price"), _PRICE_QUANTUM, "price")
    if shares <= 0 or price <= 0:
        raise InvalidInputError("broker fact shares and price must be positive")
    expected_notional = (shares * price).quantize(_NOTIONAL_QUANTUM, rounding=ROUND_HALF_UP)
    if _as_decimal(model.notional, "notional") != expected_notional:
        raise InvalidInputError("broker fact notional does not match its quantity and price")
    commission = (
        _as_decimal(model.commission, "commission") if model.commission_known is True else None
    )
    stamp_duty = (
        _as_decimal(model.stamp_duty, "stamp_duty") if model.stamp_duty_known is True else None
    )
    transfer_fee = (
        _as_decimal(model.transfer_fee, "transfer_fee")
        if model.transfer_fee_known is True
        else None
    )
    if any(value is not None and value < 0 for value in (commission, stamp_duty, transfer_fee)):
        raise InvalidInputError("broker fact fees must not be negative")
    return BrokerFactIdentity(
        broker_trade_key=model.broker_trade_key,
        action=cast(BrokerTradeAction, model.action),
        asset_code=model.asset_code,
        shares=shares,
        price=price,
        commission=commission,
        stamp_duty=stamp_duty,
        transfer_fee=transfer_fee,
        traded_at=traded_at,
    )


def _economic_identity_matches(
    model: TransactionModel,
    candidate: BrokerFactCandidate,
    *,
    shares: Decimal,
    price: Decimal,
    commission: Decimal | None,
    stamp_duty: Decimal | None,
    transfer_fee: Decimal | None,
) -> bool:
    """Compare stable-key economics without replacing first-seen source provenance."""

    source = candidate.source_row
    if model.action != source.action or model.asset_code != source.asset_code:
        return False
    expected_notional = (shares * price).quantize(_NOTIONAL_QUANTUM, rounding=ROUND_HALF_UP)
    if (
        _as_decimal(model.shares, "shares") != shares
        or _as_decimal(model.price, "price") != price
        or _as_decimal(model.notional, "notional") != expected_notional
    ):
        return False
    fee_pairs = (
        (model.commission, model.commission_known, commission),
        (model.stamp_duty, model.stamp_duty_known, stamp_duty),
        (model.transfer_fee, model.transfer_fee_known, transfer_fee),
    )
    for stored_value, stored_known, source_value in fee_pairs:
        if (stored_known is True) != (source_value is not None):
            return False
        if source_value is not None and _as_decimal(stored_value, "fee") != source_value:
            return False
    return model.traded_at.astimezone(_UTC) == source.traded_at.astimezone(_UTC)


def _balance_hash(snapshots: tuple[BalanceSnapshot, ...]) -> str:
    """Hash local balance identity/economics while omitting observation clocks."""

    body: list[dict[str, JsonValue]] = []
    for snapshot in sorted(snapshots, key=lambda item: item.asset_code):
        body.append(
            {
                "owner_user_id": snapshot.owner_user_id,
                "portfolio_id": snapshot.portfolio_id,
                "asset_code": snapshot.asset_code,
                "account_id": snapshot.account_id,
                "account_mapping_id": snapshot.account_mapping_id,
                "kind": snapshot.kind,
                "unified_position_id": snapshot.unified_position_id,
                "legacy_position_id": snapshot.legacy_position_id,
                "total_shares": canonical_float(snapshot.total_shares, field_name="total_shares"),
                "available_quantity": canonical_float(
                    snapshot.available_quantity, field_name="available_quantity"
                ),
                "available_quantity_known": snapshot.available_quantity_known,
                "average_cost": (
                    str(snapshot.average_cost.normalize())
                    if snapshot.average_cost is not None
                    else None
                ),
                "reference_mark": (
                    str(snapshot.reference_mark.normalize())
                    if snapshot.reference_mark is not None
                    else None
                ),
                "reference_mark_as_of": (
                    snapshot.reference_mark_as_of.isoformat()
                    if snapshot.reference_mark_as_of is not None
                    else None
                ),
                "valuation_status": snapshot.valuation_status,
                "source_updated_at": (
                    snapshot.source_updated_at.isoformat()
                    if snapshot.source_updated_at is not None
                    else None
                ),
                "blocked_reason_code": snapshot.blocked_reason_code,
                "snapshot_fingerprint": snapshot.fingerprint,
            }
        )
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class BrokerFactRecordCodecMixin:
    """Map stored facts and audit details into typed Application records."""

    def _record(self, model: TransactionModel) -> BrokerFactRecord:
        """Map one persisted ORM row and validated details into the public record."""

        details = _details(model)
        try:
            state = BrokerReconciliationState(model.broker_reconciliation_state)
        except ValueError as error:
            raise InvalidInputError(
                "transaction contains an unknown reconciliation state"
            ) from error
        if state is BrokerReconciliationState.UNKNOWN:
            raise InvalidInputError("UNKNOWN cannot be persisted as a reconciliation state")
        declaration = self._baseline_view(details.get("baseline_declaration"))
        projection = self._projection_view(details.get("last_projection"))
        matching = self._matching_view(details.get("matching_attempt"))
        last_reason = _string(details.get("last_reason_code"))
        raw_payload = _json_object(model.raw_payload, field_name="raw_payload")
        return BrokerFactRecord(
            transaction_id=int(model.pk),
            owner_user_id=int(model.portfolio.user_id),
            portfolio_id=int(model.portfolio_id),
            position_id=int(model.position_id) if model.position_id is not None else None,
            action=cast(BrokerTradeAction, model.action),
            asset_code=model.asset_code,
            shares=float(model.shares),
            price=_as_decimal(model.price, "price"),
            notional=_as_decimal(model.notional, "notional"),
            commission=_as_decimal(model.commission, "commission"),
            commission_known=model.commission_known,
            slippage=_as_decimal(model.slippage, "slippage"),
            slippage_known=model.slippage_known,
            stamp_duty=_as_decimal(model.stamp_duty, "stamp_duty"),
            stamp_duty_known=model.stamp_duty_known,
            transfer_fee=_as_decimal(model.transfer_fee, "transfer_fee"),
            transfer_fee_known=model.transfer_fee_known,
            broker_name=model.broker_name,
            external_trade_id=model.external_trade_id,
            broker_trade_key=model.broker_trade_key,
            first_import_batch_id=(
                int(model.import_batch_id) if model.import_batch_id is not None else None
            ),
            raw_payload=cast(JsonObject, raw_payload),
            notes=model.notes,
            traded_at=_aware_datetime(model.traded_at, "traded_at"),
            created_at=_aware_datetime(model.created_at, "created_at"),
            reconciliation=BrokerReconciliationView(
                state=state,
                baseline=declaration,
                last_projection=projection,
                last_reason_code=last_reason,
            ),
            matching_attempt=matching,
        )

    @staticmethod
    def _baseline_view(value: JsonValue | None) -> BaselineDeclarationView | None:
        """Parse the latest baseline audit object into a typed read view."""

        if not isinstance(value, dict):
            return None
        declared_at = _parse_datetime(value.get("declared_at"))
        decision = _string(value.get("decision"))
        actor = _integer(value.get("actor_user_id"))
        if (
            declared_at is None
            or decision not in {"pending", "included", "excluded"}
            or actor is None
        ):
            raise InvalidInputError("baseline declaration details are malformed")
        as_of = _parse_datetime(value.get("baseline_as_of"))
        return BaselineDeclarationView(
            decision=cast(BrokerBaselineDecision, decision),
            actor_user_id=actor,
            declared_at=declared_at,
            expected_fact_set_fingerprint=_string(value.get("expected_fact_set_fingerprint")),
            expected_balance_fingerprint=_string(value.get("expected_balance_fingerprint")),
            baseline_as_of=as_of,
        )

    @staticmethod
    def _projection_view(value: JsonValue | None) -> ProjectionAttemptView | None:
        """Parse the latest economic projection attempt into a typed read view."""

        if not isinstance(value, dict):
            return None
        attempted_at = _parse_datetime(value.get("attempted_at"))
        outcome = _string(value.get("outcome"))
        if attempted_at is None or outcome not in {
            "projected",
            "already_in_baseline",
            "awaiting_baseline",
            "blocked",
        }:
            raise InvalidInputError("projection attempt details are malformed")
        return ProjectionAttemptView(
            attempted_at=attempted_at,
            outcome=cast(ProjectionOutcomeKind, outcome),
            reason_code=_string(value.get("reason_code")),
            account_id=_integer(value.get("account_id")),
            unified_position_id=_integer(value.get("unified_position_id")),
            legacy_position_id=_integer(value.get("legacy_position_id")),
            resulting_balance_fingerprint=_string(value.get("resulting_balance_fingerprint")),
        )

    @staticmethod
    def _matching_view(value: JsonValue | None) -> MatchingAttemptView | None:
        """Parse the latest independent matcher attempt into a typed read view."""

        if not isinstance(value, dict):
            return None
        attempted_at = _parse_datetime(value.get("attempted_at"))
        outcome = _string(value.get("outcome"))
        if attempted_at is None or outcome not in {"matched", "manual_only", "deferred", "failed"}:
            raise InvalidInputError("matching attempt details are malformed")
        return MatchingAttemptView(
            attempted_at=attempted_at,
            outcome=cast(MatchingOutcomeKind, outcome),
            link_id=_integer(value.get("link_id")),
            reason_code=_string(value.get("reason_code")),
        )

    @staticmethod
    def _projection_result(
        row: TransactionModel,
        *,
        outcome: ProjectionOutcomeKind,
    ) -> BrokerFactProjectionResult:
        """Map one row state into the per-fact reconciliation result."""

        try:
            state = BrokerReconciliationState(row.broker_reconciliation_state)
        except ValueError as error:
            raise InvalidInputError(
                "transaction contains an unknown reconciliation state"
            ) from error
        details = _details(row)
        last_projection = details.get("last_projection")
        reason = (
            _string(last_projection.get("reason_code"))
            if isinstance(last_projection, dict)
            else _string(details.get("last_reason_code"))
        )
        fingerprint = (
            _string(last_projection.get("resulting_balance_fingerprint"))
            if isinstance(last_projection, dict)
            else None
        )
        return BrokerFactProjectionResult(
            transaction_id=int(row.pk),
            state=state,
            outcome=outcome,
            reason_code=reason,
            resulting_balance_fingerprint=fingerprint,
        )
