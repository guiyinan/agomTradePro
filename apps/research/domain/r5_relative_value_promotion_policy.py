"""Stable R5 relative-value promotion scope and pre-selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TypedDict

from apps.fixed_income.domain.evidence import (
    canonical_hash as _strict_canonical_hash,
)
from apps.fixed_income.domain.evidence import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.relative_value_assessment import R5Component

_REQUIRED_COMPONENTS = tuple(sorted(R5Component, key=lambda item: item.value))


def _canonical_hash(payload: object) -> str:
    """Hash payloads after narrowing accidental list syntax to exact tuples."""

    return _strict_canonical_hash(_tuple_payload(payload))


def _tuple_payload(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _tuple_payload(item) for key, item in value.items()}
    return value


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _content_addressed_id(namespace: str, digest: str) -> str:
    require_sha256(digest, f"{namespace} digest")
    return f"{namespace}:{digest}"


class R5RelativeValuePromotionPolicyStatus(str, Enum):
    """Research-owner availability state for an exact policy."""

    ACTIVE = "active"


@dataclass(frozen=True)
class R5RelativeValuePromotionScope:
    """Stable semantic stream containing no result identity or exact version."""

    scope_id: str
    owner: str
    capability: str
    purpose: str
    study_family_id: str
    currency: str
    universe_policy_id: str
    split_policy_id: str
    cost_policy_id: str
    liquidity_policy_id: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_family_id: str,
        currency: str,
        universe_policy_id: str,
        split_policy_id: str,
        cost_policy_id: str,
        liquidity_policy_id: str,
    ) -> R5RelativeValuePromotionScope:
        """Create a canonical Research-owned R5 semantic scope."""

        digest = _canonical_hash(
            _scope_payload(
                study_family_id=study_family_id,
                currency=currency,
                universe_policy_id=universe_policy_id,
                split_policy_id=split_policy_id,
                cost_policy_id=cost_policy_id,
                liquidity_policy_id=liquidity_policy_id,
            )
        )
        return cls(
            scope_id=_content_addressed_id("r5-rv-scope", digest),
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            study_family_id=study_family_id,
            currency=currency,
            universe_policy_id=universe_policy_id,
            split_policy_id=split_policy_id,
            cost_policy_id=cost_policy_id,
            liquidity_policy_id=liquidity_policy_id,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
        ):
            raise ValueError("R5 relative-value promotion scope authority is invalid")
        for field_name in (
            "study_family_id",
            "currency",
            "universe_policy_id",
            "split_policy_id",
            "cost_policy_id",
            "liquidity_policy_id",
        ):
            require_token(
                str(getattr(self, field_name)),
                f"R5 promotion scope {field_name}",
            )
        require_sha256(self.content_hash, "R5 promotion scope content_hash")
        expected = r5_relative_value_promotion_scope_hash(self)
        if self.content_hash != expected or self.scope_id != _content_addressed_id(
            "r5-rv-scope", expected
        ):
            raise ValueError("R5 promotion scope content hash or identity mismatch")


def _scope_payload(
    *,
    study_family_id: str,
    currency: str,
    universe_policy_id: str,
    split_policy_id: str,
    cost_policy_id: str,
    liquidity_policy_id: str,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-promotion-scope.v1",
        "authority": ["research", "r5", "fixed_income_relative_value_research"],
        "study_family_id": study_family_id,
        "currency": currency,
        "semantic_policy_ids": [
            universe_policy_id,
            split_policy_id,
            cost_policy_id,
            liquidity_policy_id,
        ],
    }


def r5_relative_value_promotion_scope_hash(
    scope: R5RelativeValuePromotionScope,
) -> str:
    """Recompute the stable semantic scope hash."""

    return _canonical_hash(
        _scope_payload(
            study_family_id=scope.study_family_id,
            currency=scope.currency,
            universe_policy_id=scope.universe_policy_id,
            split_policy_id=scope.split_policy_id,
            cost_policy_id=scope.cost_policy_id,
            liquidity_policy_id=scope.liquidity_policy_id,
        )
    )


@dataclass(frozen=True)
class R5RelativeValuePromotionRegistration:
    """Pre-selection mapping from one scope to an expected OOS trial calendar."""

    registration_id: str
    registration_version: str
    owner: str
    capability: str
    purpose: str
    scope: R5RelativeValuePromotionScope
    trial_version: str
    expected_observation_ids: tuple[str, ...]
    required_components: tuple[R5Component, ...]
    universe_policy_version: str
    split_policy_version: str
    cost_policy_version: str
    liquidity_policy_version: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        scope: R5RelativeValuePromotionScope,
        trial_version: str,
        expected_observation_ids: tuple[str, ...],
        universe_policy_version: str,
        split_policy_version: str,
        cost_policy_version: str,
        liquidity_policy_version: str,
    ) -> R5RelativeValuePromotionRegistration:
        """Seal the exact observation calendar and semantic-policy versions."""

        payload = _registration_payload(
            scope=scope,
            trial_version=trial_version,
            expected_observation_ids=expected_observation_ids,
            required_components=_REQUIRED_COMPONENTS,
            universe_policy_version=universe_policy_version,
            split_policy_version=split_policy_version,
            cost_policy_version=cost_policy_version,
            liquidity_policy_version=liquidity_policy_version,
        )
        digest = _canonical_hash(payload)
        return cls(
            registration_id=_content_addressed_id("r5-rv-registration", digest),
            registration_version="r5-relative-value-registration.v1",
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            scope=scope,
            trial_version=trial_version,
            expected_observation_ids=expected_observation_ids,
            required_components=_REQUIRED_COMPONENTS,
            universe_policy_version=universe_policy_version,
            split_policy_version=split_policy_version,
            cost_policy_version=cost_policy_version,
            liquidity_policy_version=liquidity_policy_version,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
            or self.scope.owner != self.owner
            or self.scope.capability != self.capability
            or self.scope.purpose != self.purpose
        ):
            raise ValueError("R5 promotion registration authority is invalid")
        require_token(self.registration_version, "R5 registration version")
        for field_name in (
            "trial_version",
            "universe_policy_version",
            "split_policy_version",
            "cost_policy_version",
            "liquidity_policy_version",
        ):
            require_token(
                str(getattr(self, field_name)),
                f"R5 promotion registration {field_name}",
            )
        if not self.expected_observation_ids or self.expected_observation_ids != tuple(
            sorted(set(self.expected_observation_ids))
        ):
            raise ValueError("R5 expected observation IDs must be non-empty and ordered")
        for observation_id in self.expected_observation_ids:
            require_token(observation_id, "R5 expected observation ID")
        if self.required_components != _REQUIRED_COMPONENTS:
            raise ValueError("R5 registration must require the complete component family")
        require_sha256(self.content_hash, "R5 registration content_hash")
        expected = r5_relative_value_promotion_registration_hash(self)
        if self.content_hash != expected or self.registration_id != _content_addressed_id(
            "r5-rv-registration", expected
        ):
            raise ValueError("R5 registration content hash or identity mismatch")


def _registration_payload(
    *,
    scope: R5RelativeValuePromotionScope,
    trial_version: str,
    expected_observation_ids: tuple[str, ...],
    required_components: tuple[R5Component, ...],
    universe_policy_version: str,
    split_policy_version: str,
    cost_policy_version: str,
    liquidity_policy_version: str,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-promotion-registration.v1",
        "authority": ["research", "r5", "fixed_income_relative_value_research"],
        "scope": [scope.scope_id, scope.content_hash],
        "trial_version": trial_version,
        "expected_observation_ids": expected_observation_ids,
        "required_components": tuple(item.value for item in required_components),
        "policy_versions": [
            universe_policy_version,
            split_policy_version,
            cost_policy_version,
            liquidity_policy_version,
        ],
    }


def r5_relative_value_promotion_registration_hash(
    registration: R5RelativeValuePromotionRegistration,
) -> str:
    """Recompute an exact pre-selection registration hash."""

    return _canonical_hash(
        _registration_payload(
            scope=registration.scope,
            trial_version=registration.trial_version,
            expected_observation_ids=registration.expected_observation_ids,
            required_components=registration.required_components,
            universe_policy_version=registration.universe_policy_version,
            split_policy_version=registration.split_policy_version,
            cost_policy_version=registration.cost_policy_version,
            liquidity_policy_version=registration.liquidity_policy_version,
        )
    )


class _PolicyValues(TypedDict):
    policy_version: str
    scope: R5RelativeValuePromotionScope
    registration: R5RelativeValuePromotionRegistration
    minimum_observation_count: int
    minimum_coverage_ratio: Decimal
    minimum_excess_net_return: Decimal
    maximum_drawdown_increase: Decimal
    maximum_total_cost: Decimal
    maximum_liquidity_breach_ratio: Decimal
    maximum_capacity_utilization: Decimal
    maximum_realized_credit_loss: Decimal
    decision_validity_seconds: int
    approved_at: datetime
    recorded_at: datetime
    active_from: datetime
    active_until: datetime


@dataclass(frozen=True)
class R5RelativeValuePromotionPolicy:
    """Research-owned explicit gates for one pre-registered R5 trial."""

    policy_id: str
    policy_version: str
    owner: str
    capability: str
    purpose: str
    scope: R5RelativeValuePromotionScope
    registration: R5RelativeValuePromotionRegistration
    status: R5RelativeValuePromotionPolicyStatus
    minimum_observation_count: int
    minimum_coverage_ratio: Decimal
    minimum_excess_net_return: Decimal
    maximum_drawdown_increase: Decimal
    maximum_total_cost: Decimal
    maximum_liquidity_breach_ratio: Decimal
    maximum_capacity_utilization: Decimal
    maximum_realized_credit_loss: Decimal
    decision_validity_seconds: int
    approved_at: datetime
    recorded_at: datetime
    active_from: datetime
    active_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        scope: R5RelativeValuePromotionScope,
        registration: R5RelativeValuePromotionRegistration,
        minimum_observation_count: int,
        minimum_coverage_ratio: Decimal,
        minimum_excess_net_return: Decimal,
        maximum_drawdown_increase: Decimal,
        maximum_total_cost: Decimal,
        maximum_liquidity_breach_ratio: Decimal,
        maximum_capacity_utilization: Decimal,
        maximum_realized_credit_loss: Decimal,
        decision_validity_seconds: int,
        approved_at: datetime,
        recorded_at: datetime,
        active_from: datetime,
        active_until: datetime,
    ) -> R5RelativeValuePromotionPolicy:
        """Seal every gate and clock without defaults or inferred thresholds."""

        values: _PolicyValues = {
            "policy_version": policy_version,
            "scope": scope,
            "registration": registration,
            "minimum_observation_count": minimum_observation_count,
            "minimum_coverage_ratio": minimum_coverage_ratio,
            "minimum_excess_net_return": minimum_excess_net_return,
            "maximum_drawdown_increase": maximum_drawdown_increase,
            "maximum_total_cost": maximum_total_cost,
            "maximum_liquidity_breach_ratio": maximum_liquidity_breach_ratio,
            "maximum_capacity_utilization": maximum_capacity_utilization,
            "maximum_realized_credit_loss": maximum_realized_credit_loss,
            "decision_validity_seconds": decision_validity_seconds,
            "approved_at": approved_at,
            "recorded_at": recorded_at,
            "active_from": active_from,
            "active_until": active_until,
        }
        digest = _canonical_hash(_policy_payload(**values))
        return cls(
            policy_id=_content_addressed_id("r5-rv-policy", digest),
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            status=R5RelativeValuePromotionPolicyStatus.ACTIVE,
            content_hash=digest,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            **values,
        )

    def __post_init__(self) -> None:
        require_token(self.policy_version, "R5 promotion policy_version")
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
            or self.status is not R5RelativeValuePromotionPolicyStatus.ACTIVE
        ):
            raise ValueError("R5 promotion policy authority or status is invalid")
        if self.registration.scope != self.scope:
            raise ValueError("R5 promotion registration crosses semantic scopes")
        if (
            isinstance(self.minimum_observation_count, bool)
            or self.minimum_observation_count < 2
            or self.minimum_observation_count > len(self.registration.expected_observation_ids)
        ):
            raise ValueError("R5 minimum_observation_count is outside registration")
        for field_name in (
            "minimum_coverage_ratio",
            "minimum_excess_net_return",
            "maximum_drawdown_increase",
            "maximum_total_cost",
            "maximum_liquidity_breach_ratio",
            "maximum_capacity_utilization",
            "maximum_realized_credit_loss",
        ):
            _require_finite(
                getattr(self, field_name),
                f"R5 promotion policy {field_name}",
            )
        if not Decimal("0") < self.minimum_coverage_ratio <= Decimal("1"):
            raise ValueError("R5 minimum coverage ratio must be within (0, 1]")
        if self.minimum_excess_net_return < 0:
            raise ValueError("R5 minimum excess net return cannot be negative")
        if self.maximum_drawdown_increase < 0 or self.maximum_total_cost < 0:
            raise ValueError("R5 drawdown and cost maxima cannot be negative")
        if not Decimal("0") <= self.maximum_liquidity_breach_ratio <= Decimal("1"):
            raise ValueError("R5 liquidity breach ratio must be within [0, 1]")
        if not Decimal("0") < self.maximum_capacity_utilization <= Decimal("1"):
            raise ValueError("R5 capacity utilization maximum must be within (0, 1]")
        if self.maximum_realized_credit_loss < 0:
            raise ValueError("R5 realized credit loss maximum cannot be negative")
        if (
            isinstance(self.decision_validity_seconds, bool)
            or not 1 <= self.decision_validity_seconds <= 31_536_000
        ):
            raise ValueError("R5 decision validity must be within one year")
        for field_name in ("approved_at", "recorded_at", "active_from", "active_until"):
            require_aware(
                getattr(self, field_name),
                f"R5 promotion policy {field_name}",
            )
        if not self.approved_at <= self.recorded_at <= self.active_from < self.active_until:
            raise ValueError("R5 promotion policy approval/active clocks are invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 promotion policy must remain research-only")
        require_sha256(self.content_hash, "R5 promotion policy content_hash")
        expected = r5_relative_value_promotion_policy_hash(self)
        if self.content_hash != expected or self.policy_id != _content_addressed_id(
            "r5-rv-policy", expected
        ):
            raise ValueError("R5 promotion policy content hash or identity mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact policy receipt is known and active."""

        require_aware(as_of, "R5 promotion policy as_of")
        return self.recorded_at <= as_of and self.active_from <= as_of < self.active_until


def _policy_payload(
    *,
    policy_version: str,
    scope: R5RelativeValuePromotionScope,
    registration: R5RelativeValuePromotionRegistration,
    minimum_observation_count: int,
    minimum_coverage_ratio: Decimal,
    minimum_excess_net_return: Decimal,
    maximum_drawdown_increase: Decimal,
    maximum_total_cost: Decimal,
    maximum_liquidity_breach_ratio: Decimal,
    maximum_capacity_utilization: Decimal,
    maximum_realized_credit_loss: Decimal,
    decision_validity_seconds: int,
    approved_at: datetime,
    recorded_at: datetime,
    active_from: datetime,
    active_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-promotion-policy.v1",
        "identity": [policy_version, "research", "r5"],
        "scope": [scope.scope_id, scope.content_hash],
        "registration": [registration.registration_id, registration.content_hash],
        "gates": {
            "minimum_observation_count": minimum_observation_count,
            "minimum_coverage_ratio": minimum_coverage_ratio,
            "minimum_excess_net_return": minimum_excess_net_return,
            "maximum_drawdown_increase": maximum_drawdown_increase,
            "maximum_total_cost": maximum_total_cost,
            "maximum_liquidity_breach_ratio": maximum_liquidity_breach_ratio,
            "maximum_capacity_utilization": maximum_capacity_utilization,
            "maximum_realized_credit_loss": maximum_realized_credit_loss,
        },
        "decision_validity_seconds": decision_validity_seconds,
        "window": [approved_at, recorded_at, active_from, active_until],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_relative_value_promotion_policy_hash(
    policy: R5RelativeValuePromotionPolicy,
) -> str:
    """Recompute one exact content-addressed R5 promotion policy hash."""

    return _canonical_hash(
        _policy_payload(
            policy_version=policy.policy_version,
            scope=policy.scope,
            registration=policy.registration,
            minimum_observation_count=policy.minimum_observation_count,
            minimum_coverage_ratio=policy.minimum_coverage_ratio,
            minimum_excess_net_return=policy.minimum_excess_net_return,
            maximum_drawdown_increase=policy.maximum_drawdown_increase,
            maximum_total_cost=policy.maximum_total_cost,
            maximum_liquidity_breach_ratio=policy.maximum_liquidity_breach_ratio,
            maximum_capacity_utilization=policy.maximum_capacity_utilization,
            maximum_realized_credit_loss=policy.maximum_realized_credit_loss,
            decision_validity_seconds=policy.decision_validity_seconds,
            approved_at=policy.approved_at,
            recorded_at=policy.recorded_at,
            active_from=policy.active_from,
            active_until=policy.active_until,
        )
    )


__all__ = [
    "R5RelativeValuePromotionPolicy",
    "R5RelativeValuePromotionPolicyStatus",
    "R5RelativeValuePromotionRegistration",
    "R5RelativeValuePromotionScope",
    "r5_relative_value_promotion_policy_hash",
    "r5_relative_value_promotion_registration_hash",
    "r5_relative_value_promotion_scope_hash",
]
