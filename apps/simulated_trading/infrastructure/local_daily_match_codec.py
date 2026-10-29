"""Strict JSON and record seals for immutable local daily-match decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    LocalDailyMatchEvidenceKind,
    LocalDailyMatchSourceReference,
    QualifiedLocalDailyMatchInput,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
    OrderFillContext,
    validate_local_simulated_fill_event,
)
from apps.simulated_trading.domain.execution_settlement_primitives import _require_aware
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicyBinding,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchLimitState,
    LocalMatchObservation,
    LocalMatchOutcome,
    LocalMatchPriceAdjustment,
    LocalMatchTradingState,
    LocalMatchVolumeUnit,
    LocalOrderMatchResult,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_event_codec import (
    decode_local_simulated_fill_event,
    encode_local_simulated_fill_event,
)

_QUALIFIED_INPUT_SCHEMA = "local-daily-match-qualified-input.v1"
_DECISION_SCHEMA = "local-daily-match-decision.v1"
_RECORD_SCHEMA = "local-daily-match-record.v1"
_ZERO_HASH = "0" * 64
_HASH_LENGTH = 64


def canonical_json(payload: object) -> str:
    """Serialize one JSON-safe value with the repository's stable spelling."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("LOCAL_DAILY_MATCH_JSON_INVALID") from error


def hash_payload(payload: object) -> str:
    """Return the bare SHA-256 of one canonical UTF-8 JSON payload."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def encode_qualified_input(value: QualifiedLocalDailyMatchInput) -> dict[str, object]:
    """Encode the full policy, observation and exact source references."""

    if type(value) is not QualifiedLocalDailyMatchInput:
        raise ValueError("LOCAL_DAILY_MATCH_QUALIFICATION_INVALID")
    value.__post_init__()
    observation = value.observation
    return {
        "schema": _QUALIFIED_INPUT_SCHEMA,
        "as_of": _utc_text(value.as_of),
        "policy_binding": value.policy_binding.to_payload(),
        "observation": _observation_payload(observation),
        "evidence": [_reference_payload(item) for item in value.evidence],
    }


def encode_qualified_input_json(value: QualifiedLocalDailyMatchInput) -> str:
    """Return canonical exact qualified-input JSON for text sealing."""

    return canonical_json(encode_qualified_input(value))


def qualified_input_hash(value: QualifiedLocalDailyMatchInput) -> str:
    """Hash every policy, cutoff, observation and retained reference field."""

    return hash_payload(encode_qualified_input(value))


def observation_source_hash(value: QualifiedLocalDailyMatchInput) -> str:
    """Hash source observation and evidence without policy-version partitioning."""

    payload = encode_qualified_input(value)
    return hash_payload(
        {
            "schema": "local-daily-match-observation-source.v1",
            "observation": payload["observation"],
            "evidence": payload["evidence"],
        }
    )


def decode_qualified_input(payload: object) -> QualifiedLocalDailyMatchInput:
    """Strictly reconstruct one saved qualified input and all nested evidence."""

    values = _object(
        payload,
        fields=frozenset({"schema", "as_of", "policy_binding", "observation", "evidence"}),
    )
    if values["schema"] != _QUALIFIED_INPUT_SCHEMA:
        raise ValueError("LOCAL_DAILY_MATCH_QUALIFICATION_SCHEMA_INVALID")
    if type(values["evidence"]) is not list:
        raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_INVALID")
    evidence_payloads = cast(list[object], values["evidence"])
    evidence = tuple(_decode_reference(item) for item in evidence_payloads)
    result = QualifiedLocalDailyMatchInput(
        as_of=_parse_utc(values["as_of"], "as_of"),
        policy_binding=LocalDailySimulationPolicyBinding.from_payload(values["policy_binding"]),
        observation=_decode_observation(values["observation"]),
        evidence=evidence,
    )
    # Reject a noncanonical source ordering or repeated reference even if the
    # DTO would otherwise sort it into a valid current representation.
    if canonical_json(encode_qualified_input(result)) != canonical_json(payload):
        raise ValueError("LOCAL_DAILY_MATCH_QUALIFICATION_NOT_CANONICAL")
    return result


def encode_decision_result(result: LocalOrderMatchResult) -> dict[str, object]:
    """Encode the exact matcher disposition without converting Decimal values."""

    if type(result) is not LocalOrderMatchResult:
        raise ValueError("LOCAL_DAILY_MATCH_RESULT_INVALID")
    result.__post_init__()
    return {
        "schema": _DECISION_SCHEMA,
        "outcome": result.outcome.value,
        "reason_code": result.reason_code,
        "matched_quantity": _decimal_text(result.matched_quantity),
        "matched_price": _decimal_text(result.matched_price),
    }


def decode_decision_result(payload: object) -> LocalOrderMatchResult:
    """Strictly decode one persisted matcher result and validate its outcome."""

    values = _object(
        payload,
        fields=frozenset({"schema", "outcome", "reason_code", "matched_quantity", "matched_price"}),
    )
    if values["schema"] != _DECISION_SCHEMA:
        raise ValueError("LOCAL_DAILY_MATCH_RESULT_SCHEMA_INVALID")
    if type(values["outcome"]) is not str or type(values["reason_code"]) is not str:
        raise ValueError("LOCAL_DAILY_MATCH_RESULT_INVALID")
    try:
        outcome = LocalMatchOutcome(values["outcome"])
    except ValueError as error:
        raise ValueError("LOCAL_DAILY_MATCH_RESULT_OUTCOME_INVALID") from error
    if outcome is LocalMatchOutcome.BLOCKED:
        raise ValueError("LOCAL_DAILY_MATCH_BLOCKED_RESULT_NOT_PERSISTABLE")
    return LocalOrderMatchResult(
        outcome=outcome,
        reason_code=values["reason_code"],
        matched_quantity=_parse_optional_decimal(values["matched_quantity"], "matched_quantity"),
        matched_price=_parse_optional_decimal(values["matched_price"], "matched_price"),
    )


def make_daily_fill_event(
    *,
    command: LocalDailyMatchCommand,
    context: OrderFillContext,
    qualified_input: QualifiedLocalDailyMatchInput,
    result: LocalOrderMatchResult,
    recorded_at: datetime,
) -> LocalSimulatedFillEventV1:
    """Bind one calculated match to the locked order and daily interval clocks."""

    if result.outcome is not LocalMatchOutcome.MATCHED:
        raise ValueError("LOCAL_DAILY_MATCH_MATCHED_RESULT_REQUIRED")
    result.__post_init__()
    quantity = result.matched_quantity
    price = result.matched_price
    if type(quantity) is not Decimal or type(price) is not Decimal:
        raise ValueError("LOCAL_DAILY_MATCH_MATCHED_FIELDS_INVALID")
    _require_aware(recorded_at, "recorded_at")
    observation = qualified_input.observation
    if recorded_at < qualified_input.as_of or recorded_at < observation.available_at:
        raise ValueError("LOCAL_DAILY_MATCH_RECORD_CLOCK_INVALID")
    remaining = context.reservation.quantity - context.reservation.filled_quantity
    event_kind = (
        LocalSimulatedFillEventKind.FINAL_FILL
        if quantity == remaining
        else LocalSimulatedFillEventKind.FILL
    )
    base = LocalSimulatedFillEventV1(
        source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        source_event_id=command.operation_key,
        event_payload_hash=_ZERO_HASH,
        source_snapshot_id=observation.observation_id,
        source_snapshot_hash=observation_source_hash(qualified_input),
        reservation_id=context.reservation_id,
        account_id=context.account_id,
        user_id=context.owner_user_id,
        order_idempotency_key=context.order_idempotency_key,
        intent_payload_hash=context.intent_payload_hash,
        reservation_request_hash=context.reservation.identity.request_payload_hash,
        plan_snapshot_hash=context.plan_snapshot_hash,
        security_id=context.reservation.identity.security_id,
        asset_code=context.asset_code,
        side=context.reservation.side,
        event_kind=event_kind,
        quantity=quantity,
        price=price,
        occurred_at=observation.observed_at,
        source_observed_at=None,
        source_available_at=None,
        recorded_at=recorded_at,
        observation_basis="daily_interval_end",
        interval_end_at=observation.observed_at,
        local_known_at=observation.available_at,
    )
    checked_base = validate_local_simulated_fill_event(base)
    event_hash = hashlib.sha256(
        encode_local_simulated_fill_event(checked_base).encode("utf-8")
    ).hexdigest()
    event = replace(checked_base, event_payload_hash=event_hash)
    return validate_local_simulated_fill_event(event)


def event_payload_hash(event: LocalSimulatedFillEventV1) -> str:
    """Recompute a daily event digest without trusting its stored digest field."""

    checked = validate_local_simulated_fill_event(event)
    if checked.observation_basis != "daily_interval_end":
        raise ValueError("LOCAL_DAILY_MATCH_EVENT_BASIS_INVALID")
    placeholder = replace(checked, event_payload_hash=_ZERO_HASH)
    return hashlib.sha256(
        encode_local_simulated_fill_event(placeholder).encode("utf-8")
    ).hexdigest()


def encode_event(event: LocalSimulatedFillEventV1) -> str:
    """Encode one validated event and verify its source digest first."""

    checked = validate_local_simulated_fill_event(event)
    if event_payload_hash(checked) != checked.event_payload_hash:
        raise ValueError("LOCAL_DAILY_MATCH_EVENT_HASH_INVALID")
    return encode_local_simulated_fill_event(checked)


def decode_event(text: object) -> LocalSimulatedFillEventV1:
    """Decode one daily event and verify its self-contained source hash."""

    event = decode_local_simulated_fill_event(text)
    if event.observation_basis != "daily_interval_end":
        raise ValueError("LOCAL_DAILY_MATCH_EVENT_BASIS_INVALID")
    if event_payload_hash(event) != event.event_payload_hash:
        raise ValueError("LOCAL_DAILY_MATCH_EVENT_HASH_INVALID")
    return event


def record_digest_values(values: dict[str, object]) -> str:
    """Seal all immutable decision columns except the database-generated row ID."""

    return hash_payload({"schema": _RECORD_SCHEMA, **values})


def decision_from_parts(
    *,
    command: LocalDailyMatchCommand,
    request_hash: str,
    result: LocalOrderMatchResult,
    event: LocalSimulatedFillEventV1 | None,
    replayed: bool,
) -> LocalDailyMatchDecision:
    """Build the application result after persistence fields have been verified."""

    return LocalDailyMatchDecision(
        command=command,
        request_hash=request_hash,
        result=result,
        event=event,
        replayed=replayed,
    )


def _observation_payload(value: LocalMatchObservation) -> dict[str, object]:
    """Return every matching input with exact enum, clock and decimal spelling."""

    return {
        "security_id": value.security_id,
        "session_date": value.session_date.isoformat(),
        "observation_id": value.observation_id,
        "observed_at": _utc_text(value.observed_at),
        "available_at": _utc_text(value.available_at),
        "close_price": _decimal_text(value.close_price),
        "price_adjustment": value.price_adjustment.value,
        "traded_volume": _decimal_text(value.traded_volume),
        "volume_unit": value.volume_unit.value,
        "trading_state": value.trading_state.value,
        "limit_state": value.limit_state.value,
        "lower_limit_price": _decimal_text(value.lower_limit_price),
        "upper_limit_price": _decimal_text(value.upper_limit_price),
    }


def _decode_observation(payload: object) -> LocalMatchObservation:
    """Strictly parse one stored observation without guessing missing fields."""

    fields = frozenset(
        {
            "security_id",
            "session_date",
            "observation_id",
            "observed_at",
            "available_at",
            "close_price",
            "price_adjustment",
            "traded_volume",
            "volume_unit",
            "trading_state",
            "limit_state",
            "lower_limit_price",
            "upper_limit_price",
        }
    )
    values = _object(payload, fields=fields)
    try:
        session_date = date.fromisoformat(_text(values["session_date"], "session_date"))
        if session_date.isoformat() != values["session_date"]:
            raise ValueError("session date is not canonical")
        price_adjustment = LocalMatchPriceAdjustment(
            _text(values["price_adjustment"], "price_adjustment")
        )
        volume_unit = LocalMatchVolumeUnit(_text(values["volume_unit"], "volume_unit"))
        trading_state = LocalMatchTradingState(_text(values["trading_state"], "trading_state"))
        limit_state = LocalMatchLimitState(_text(values["limit_state"], "limit_state"))
    except (TypeError, ValueError) as error:
        raise ValueError("LOCAL_DAILY_MATCH_OBSERVATION_INVALID") from error
    return LocalMatchObservation(
        security_id=_text(values["security_id"], "security_id"),
        session_date=session_date,
        observation_id=_text(values["observation_id"], "observation_id"),
        observed_at=_parse_utc(values["observed_at"], "observed_at"),
        available_at=_parse_utc(values["available_at"], "available_at"),
        close_price=_parse_decimal(values["close_price"], "close_price"),
        price_adjustment=price_adjustment,
        traded_volume=_parse_decimal(values["traded_volume"], "traded_volume"),
        volume_unit=volume_unit,
        trading_state=trading_state,
        limit_state=limit_state,
        lower_limit_price=_parse_optional_decimal(values["lower_limit_price"], "lower_limit_price"),
        upper_limit_price=_parse_optional_decimal(values["upper_limit_price"], "upper_limit_price"),
    )


def _reference_payload(value: LocalDailyMatchSourceReference) -> dict[str, object]:
    """Encode one typed reference without dropping its local recording clock."""

    value.__post_init__()
    return {
        "kind": value.kind.value,
        "identity": value.identity,
        "content_hash": value.content_hash,
        "recorded_at": _utc_text(value.recorded_at),
    }


def _decode_reference(payload: object) -> LocalDailyMatchSourceReference:
    """Decode one source reference from its exact public kind vocabulary."""

    values = _object(
        payload,
        fields=frozenset({"kind", "identity", "content_hash", "recorded_at"}),
    )
    try:
        kind = LocalDailyMatchEvidenceKind(_text(values["kind"], "kind"))
    except ValueError as error:
        raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_KIND_INVALID") from error
    return LocalDailyMatchSourceReference(
        kind=kind,
        identity=_text(values["identity"], "identity"),
        content_hash=_text(values["content_hash"], "content_hash"),
        recorded_at=_parse_utc(values["recorded_at"], "recorded_at"),
    )


def _object(payload: object, *, fields: frozenset[str]) -> dict[str, object]:
    """Require one exact JSON object key set at a persisted boundary."""

    if type(payload) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], payload)
    ):
        raise ValueError("LOCAL_DAILY_MATCH_JSON_OBJECT_INVALID")
    values = cast(dict[str, object], payload)
    if frozenset(values) != fields:
        raise ValueError("LOCAL_DAILY_MATCH_JSON_FIELDS_INVALID")
    return values


def _text(value: object, field_name: str) -> str:
    """Require a literal stored string instead of stringifying malformed JSON."""

    if type(value) is not str:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    return value


def _decimal_text(value: Decimal | None) -> str | None:
    """Render exact finite Decimal scale as its original canonical text."""

    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("LOCAL_DAILY_MATCH_DECIMAL_INVALID")
    return str(value)


def _parse_decimal(value: object, field_name: str) -> Decimal:
    """Parse finite Decimal text and reject alternate exponent spellings."""

    text = _text(value, field_name)
    try:
        parsed = Decimal(text)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID") from error
    if not parsed.is_finite() or str(parsed) != text:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    return parsed


def _parse_optional_decimal(value: object, field_name: str) -> Decimal | None:
    """Decode nullable exact decimal text without a numeric default."""

    return None if value is None else _parse_decimal(value, field_name)


def _utc_text(value: datetime) -> str:
    """Encode one aware instant as canonical UTC with microsecond precision."""

    _require_aware(value, "local_daily_match_clock")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    """Parse canonical UTC text, preserving its instant without local defaults."""

    text = _text(value, field_name)
    if not text.endswith("Z"):
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID") from error
    _require_aware(parsed, field_name)
    if _utc_text(parsed) != text:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    return parsed


__all__ = (
    "canonical_json",
    "decode_decision_result",
    "decode_event",
    "decode_qualified_input",
    "decision_from_parts",
    "encode_decision_result",
    "encode_event",
    "encode_qualified_input",
    "encode_qualified_input_json",
    "event_payload_hash",
    "hash_payload",
    "make_daily_fill_event",
    "observation_source_hash",
    "qualified_input_hash",
    "record_digest_values",
)
