"""Portfolio-owned exact-active transition-plan order reader."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanDefinition,
)
from apps.portfolio.domain.transition_plan_integrity import (
    canonical_transition_plan_payload_v1,
)

PORTFOLIO_PLAN_ORDER_OWNER = "portfolio"
PORTFOLIO_PLAN_ORDER_ARTIFACT_TYPE = "transition_plan_definition"


class TransitionPlanOrderReaderUnavailable(ValueError):
    """The exact active plan or requested order row is unavailable."""


class TransitionPlanOrderReaderCorruption(ValueError):
    """The trusted plan provider returned an invalid or substituted value."""


def _require_token(value: object, field_name: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty canonical token")


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_non_negative_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"order_payload_json contains invalid constant {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("order_payload_json contains duplicate keys")
        result[key] = value
    return result


def _validate_canonical_row_json(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("order_payload_json must be canonical-v1 JSON object text")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("order_payload_json must be canonical-v1 JSON object text") from error
    if type(decoded) is not dict:
        raise ValueError("order_payload_json must be a canonical-v1 JSON object")
    canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    if canonical != value:
        raise ValueError("order_payload_json must use canonical-v1 JSON bytes")
    return value


@dataclass(frozen=True, slots=True)
class ExactActiveTransitionPlanOrderDefinition:
    """Owner projection of one canonical order row from an exact active plan."""

    plan_id: str
    plan_version: int
    content_hash: str
    account_id: str
    order_ordinal: int
    order_payload_json: str
    order_content_hash: str
    recorded_at: datetime
    valid_until: datetime
    owner: str = PORTFOLIO_PLAN_ORDER_OWNER
    artifact_type: str = PORTFOLIO_PLAN_ORDER_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        _require_token(self.plan_id, "plan_id")
        _require_positive_integer(self.plan_version, "plan_version")
        _require_hash(self.content_hash, "content_hash")
        _require_token(self.account_id, "account_id")
        _require_non_negative_integer(self.order_ordinal, "order_ordinal")
        canonical = _validate_canonical_row_json(self.order_payload_json)
        _require_hash(self.order_content_hash, "order_content_hash")
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != self.order_content_hash:
            raise ValueError("order_content_hash does not match canonical-v1 row bytes")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("transition plan order validity window is invalid")
        if self.owner != PORTFOLIO_PLAN_ORDER_OWNER:
            raise ValueError("transition plan order owner is fixed")
        if self.artifact_type != PORTFOLIO_PLAN_ORDER_ARTIFACT_TYPE:
            raise ValueError("transition plan order artifact_type is fixed")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact order row is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class GetExactActiveTransitionPlanOrderQuery:
    """ID-only exact plan-version and ordinal query at one caller cutoff."""

    plan_id: str
    plan_version: int
    order_ordinal: int
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.plan_id, "plan_id")
        _require_positive_integer(self.plan_version, "plan_version")
        _require_non_negative_integer(self.order_ordinal, "order_ordinal")
        _require_aware(self.as_of, "as_of")


class ExactActiveTransitionPlanDefinitionProvider(Protocol):
    """Trusted Portfolio port for one exact approved plan version."""

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        """Return one exact active plan definition at the supplied cutoff."""


class GetExactActiveTransitionPlanOrder:
    """Project one owner-canonical order row without implying latest-plan state."""

    def __init__(self, provider: ExactActiveTransitionPlanDefinitionProvider) -> None:
        self._provider = provider

    def execute(
        self, query: GetExactActiveTransitionPlanOrderQuery
    ) -> ExactActiveTransitionPlanOrderDefinition:
        """Return the exact active plan order selected only by IDs and ordinal."""

        definition = self._provider.get_exact(
            plan_id=query.plan_id,
            plan_version=query.plan_version,
            as_of=query.as_of,
        )
        if definition is None:
            raise TransitionPlanOrderReaderUnavailable(
                "exact active transition plan is unavailable"
            )
        if type(definition) is not TransitionPlanDefinition:
            raise TransitionPlanOrderReaderCorruption(
                "transition plan definition type substitution"
            )
        try:
            TransitionPlanDefinition.__post_init__(definition)
        except (TypeError, ValueError) as error:
            raise TransitionPlanOrderReaderCorruption(
                "transition plan definition is invalid"
            ) from error
        plan = definition.plan
        if plan.plan_id != query.plan_id or plan.version != query.plan_version:
            raise TransitionPlanOrderReaderCorruption(
                "transition plan definition identity substitution"
            )
        if not definition.is_active_at(query.as_of):
            raise TransitionPlanOrderReaderUnavailable(
                "exact transition plan is not active at the cutoff"
            )
        payload = canonical_transition_plan_payload_v1(plan)
        orders = payload.get("orders")
        if type(orders) is not list:
            raise TransitionPlanOrderReaderCorruption(
                "canonical transition plan orders are invalid"
            )
        if query.order_ordinal >= len(orders):
            raise TransitionPlanOrderReaderUnavailable(
                "exact transition plan order ordinal is unavailable"
            )
        row = orders[query.order_ordinal]
        if type(row) is not dict:
            raise TransitionPlanOrderReaderCorruption(
                "canonical transition plan order row is invalid"
            )
        row_json = json.dumps(row, sort_keys=True, separators=(",", ":"))
        row_hash = hashlib.sha256(row_json.encode("utf-8")).hexdigest()
        return ExactActiveTransitionPlanOrderDefinition(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            content_hash=definition.content_hash,
            account_id=plan.account_id,
            order_ordinal=query.order_ordinal,
            order_payload_json=row_json,
            order_content_hash=row_hash,
            recorded_at=definition.recorded_at,
            valid_until=plan.expires_at,
        )


__all__ = [
    "ExactActiveTransitionPlanDefinitionProvider",
    "ExactActiveTransitionPlanOrderDefinition",
    "GetExactActiveTransitionPlanOrder",
    "GetExactActiveTransitionPlanOrderQuery",
    "PORTFOLIO_PLAN_ORDER_ARTIFACT_TYPE",
    "PORTFOLIO_PLAN_ORDER_OWNER",
    "TransitionPlanOrderReaderCorruption",
    "TransitionPlanOrderReaderUnavailable",
]
