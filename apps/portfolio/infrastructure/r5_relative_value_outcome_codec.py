"""Strict JSON codec for Portfolio-owned R5 relative-value outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TypeGuard

from apps.fixed_income.domain.evidence import decimal_text
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal

_SCHEMA = "portfolio-r5-relative-value-outcome-ledger.v1"
_KEYS = frozenset(
    {
        "schema",
        "outcome_id",
        "outcome_version",
        "owner",
        "owner_record_id",
        "owner_record_version",
        "owner_record_hash",
        "observation_id",
        "fixed_income_result_id",
        "fixed_income_result_version",
        "fixed_income_result_record_hash",
        "fixed_income_owner_seal_hash",
        "selection_as_of",
        "outcome_observed_at",
        "outcome_available_at",
        "recorded_at",
        "valid_until",
        "target_gross_return",
        "target_cost",
        "benchmark_gross_return",
        "benchmark_cost",
        "target_maximum_drawdown",
        "benchmark_maximum_drawdown",
        "capacity_utilization",
        "liquidity_breached",
        "realized_credit_loss",
        "content_hash",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    }
)


class R5PortfolioOutcomeCodecError(ValueError):
    """Raised when persisted JSON is incomplete, noncanonical, or invalid."""


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _mapping(payload: object) -> Mapping[str, object]:
    if not _is_mapping(payload) or frozenset(payload) != _KEYS:
        raise R5PortfolioOutcomeCodecError("R5 outcome payload keys are invalid")
    return payload


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} must be text")
    return value


def _boolean(payload: Mapping[str, object], key: str) -> bool:
    value = payload[key]
    if type(value) is not bool:
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} must be boolean")
    return value


def _datetime(payload: Mapping[str, object], key: str) -> datetime:
    value = _text(payload, key)
    try:
        restored = datetime.fromisoformat(value)
    except ValueError as error:
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} is invalid") from error
    if restored.tzinfo is None or restored.utcoffset() is None:
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} must be timezone-aware")
    return restored


def _decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = _text(payload, key)
    try:
        restored = Decimal(value)
    except InvalidOperation as error:
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} is invalid") from error
    if not restored.is_finite():
        raise R5PortfolioOutcomeCodecError(f"R5 outcome {key} must be finite")
    return restored


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def encode_r5_portfolio_outcome(outcome: R5PortfolioOutcomeSeal) -> dict[str, object]:
    """Encode every sealed field into deterministic JSON-compatible values."""

    return {
        "schema": _SCHEMA,
        "outcome_id": outcome.outcome_id,
        "outcome_version": outcome.outcome_version,
        "owner": outcome.owner,
        "owner_record_id": outcome.owner_record_id,
        "owner_record_version": outcome.owner_record_version,
        "owner_record_hash": outcome.owner_record_hash,
        "observation_id": outcome.observation_id,
        "fixed_income_result_id": outcome.fixed_income_result_id,
        "fixed_income_result_version": outcome.fixed_income_result_version,
        "fixed_income_result_record_hash": outcome.fixed_income_result_record_hash,
        "fixed_income_owner_seal_hash": outcome.fixed_income_owner_seal_hash,
        "selection_as_of": _timestamp(outcome.selection_as_of),
        "outcome_observed_at": _timestamp(outcome.outcome_observed_at),
        "outcome_available_at": _timestamp(outcome.outcome_available_at),
        "recorded_at": _timestamp(outcome.recorded_at),
        "valid_until": _timestamp(outcome.valid_until),
        "target_gross_return": decimal_text(outcome.target_gross_return),
        "target_cost": decimal_text(outcome.target_cost),
        "benchmark_gross_return": decimal_text(outcome.benchmark_gross_return),
        "benchmark_cost": decimal_text(outcome.benchmark_cost),
        "target_maximum_drawdown": decimal_text(outcome.target_maximum_drawdown),
        "benchmark_maximum_drawdown": decimal_text(outcome.benchmark_maximum_drawdown),
        "capacity_utilization": decimal_text(outcome.capacity_utilization),
        "liquidity_breached": outcome.liquidity_breached,
        "realized_credit_loss": decimal_text(outcome.realized_credit_loss),
        "content_hash": outcome.content_hash,
        "research_only": outcome.research_only,
        "must_not_use_for_decision": outcome.must_not_use_for_decision,
        "must_not_execute": outcome.must_not_execute,
    }


def decode_r5_portfolio_outcome(payload: object) -> R5PortfolioOutcomeSeal:
    """Strictly reconstruct one outcome and reject noncanonical encodings."""

    values = _mapping(payload)
    if _text(values, "schema") != _SCHEMA:
        raise R5PortfolioOutcomeCodecError("R5 outcome payload schema is invalid")
    try:
        outcome = R5PortfolioOutcomeSeal(
            outcome_id=_text(values, "outcome_id"),
            outcome_version=_text(values, "outcome_version"),
            owner=_text(values, "owner"),
            owner_record_id=_text(values, "owner_record_id"),
            owner_record_version=_text(values, "owner_record_version"),
            owner_record_hash=_text(values, "owner_record_hash"),
            observation_id=_text(values, "observation_id"),
            fixed_income_result_id=_text(values, "fixed_income_result_id"),
            fixed_income_result_version=_text(values, "fixed_income_result_version"),
            fixed_income_result_record_hash=_text(
                values,
                "fixed_income_result_record_hash",
            ),
            fixed_income_owner_seal_hash=_text(values, "fixed_income_owner_seal_hash"),
            selection_as_of=_datetime(values, "selection_as_of"),
            outcome_observed_at=_datetime(values, "outcome_observed_at"),
            outcome_available_at=_datetime(values, "outcome_available_at"),
            recorded_at=_datetime(values, "recorded_at"),
            valid_until=_datetime(values, "valid_until"),
            target_gross_return=_decimal(values, "target_gross_return"),
            target_cost=_decimal(values, "target_cost"),
            benchmark_gross_return=_decimal(values, "benchmark_gross_return"),
            benchmark_cost=_decimal(values, "benchmark_cost"),
            target_maximum_drawdown=_decimal(values, "target_maximum_drawdown"),
            benchmark_maximum_drawdown=_decimal(values, "benchmark_maximum_drawdown"),
            capacity_utilization=_decimal(values, "capacity_utilization"),
            liquidity_breached=_boolean(values, "liquidity_breached"),
            realized_credit_loss=_decimal(values, "realized_credit_loss"),
            content_hash=_text(values, "content_hash"),
            research_only=_boolean(values, "research_only"),
            must_not_use_for_decision=_boolean(values, "must_not_use_for_decision"),
            must_not_execute=_boolean(values, "must_not_execute"),
        )
    except (TypeError, ValueError) as error:
        raise R5PortfolioOutcomeCodecError("R5 outcome payload is invalid") from error
    if encode_r5_portfolio_outcome(outcome) != dict(values):
        raise R5PortfolioOutcomeCodecError("R5 outcome payload is not canonical")
    return outcome


__all__ = [
    "R5PortfolioOutcomeCodecError",
    "decode_r5_portfolio_outcome",
    "encode_r5_portfolio_outcome",
]
