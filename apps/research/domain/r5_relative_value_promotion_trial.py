"""True OOS observation evidence and exact R5 relative-value trial seal."""

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
from apps.fixed_income.domain.relative_value_assessment import R5ComponentStatus
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
    R5RelativeValuePromotionScope,
)
from apps.research.domain.r5_relative_value_promotion_record import (
    R5RelativeValueOwnerRecordSeal,
)


def _canonical_hash(payload: object) -> str:
    """Hash after narrowing payload list syntax to exact tuples."""

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


class R5RelativeValuePromotionTrialState(str, Enum):
    """Readiness derived exclusively from exact observation evidence."""

    READY_FOR_POLICY_EVALUATION = "ready_for_policy_evaluation"
    BLOCKED = "blocked"


class _ObservationValues(TypedDict):
    observation_id: str
    fixed_income_record: R5RelativeValueOwnerRecordSeal
    portfolio_outcome: R5PortfolioOutcomeSeal


@dataclass(frozen=True)
class R5RelativeValueTrialObservation:
    """One formation-time owner record paired with a later realized outcome."""

    observation_id: str
    fixed_income_record: R5RelativeValueOwnerRecordSeal
    portfolio_outcome: R5PortfolioOutcomeSeal
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        observation_id: str,
        fixed_income_record: R5RelativeValueOwnerRecordSeal,
        portfolio_outcome: R5PortfolioOutcomeSeal,
    ) -> R5RelativeValueTrialObservation:
        """Bind two exact independent owner projections without caller metrics."""

        values: _ObservationValues = {
            "observation_id": observation_id,
            "fixed_income_record": fixed_income_record,
            "portfolio_outcome": portfolio_outcome,
        }
        digest = _canonical_hash(_observation_payload(**values))
        return cls(content_hash=digest, **values)

    def __post_init__(self) -> None:
        require_token(self.observation_id, "R5 trial observation_id")
        outcome = self.portfolio_outcome
        if outcome.observation_id != self.observation_id:
            raise ValueError("R5 Portfolio outcome observation identity differs")
        if (
            outcome.fixed_income_result_id != self.fixed_income_record.result_id
            or outcome.fixed_income_result_version != self.fixed_income_record.result_version
            or outcome.fixed_income_result_record_hash
            != self.fixed_income_record.result_record_hash
            or outcome.fixed_income_owner_seal_hash != self.fixed_income_record.content_hash
        ):
            raise ValueError("R5 Portfolio outcome fixed-income binding differs")
        if self.fixed_income_record.recorded_at > outcome.selection_as_of:
            raise ValueError("R5 outcome selection predates fixed-income owner record")
        require_sha256(self.content_hash, "R5 trial observation content_hash")
        if self.content_hash != r5_relative_value_trial_observation_hash(self):
            raise ValueError("R5 trial observation content hash mismatch")

    @property
    def target_net_return(self) -> Decimal:
        """Return target return after the exact once-only cost."""

        return self.portfolio_outcome.target_net_return

    @property
    def benchmark_net_return(self) -> Decimal:
        """Return benchmark return after its exact once-only cost."""

        return self.portfolio_outcome.benchmark_net_return

    @property
    def outcome_version(self) -> str:
        """Return the exact Portfolio outcome version."""

        return self.portfolio_outcome.outcome_version

    @property
    def outcome_content_hash(self) -> str:
        """Return the exact Portfolio outcome seal hash."""

        return self.portfolio_outcome.content_hash

    @property
    def selection_as_of(self) -> datetime:
        """Return the formation-time observation boundary."""

        return self.portfolio_outcome.selection_as_of

    @property
    def outcome_observed_at(self) -> datetime:
        """Return the source outcome observation time."""

        return self.portfolio_outcome.outcome_observed_at

    @property
    def outcome_available_at(self) -> datetime:
        """Return the Portfolio owner availability time."""

        return self.portfolio_outcome.outcome_available_at

    @property
    def recorded_at(self) -> datetime:
        """Return the canonical Portfolio record time."""

        return self.portfolio_outcome.recorded_at

    @property
    def valid_until(self) -> datetime:
        """Return the Portfolio outcome validity boundary."""

        return self.portfolio_outcome.valid_until

    @property
    def target_gross_return(self) -> Decimal:
        """Return the Portfolio-owned target gross return."""

        return self.portfolio_outcome.target_gross_return

    @property
    def target_cost(self) -> Decimal:
        """Return the Portfolio-owned target cost."""

        return self.portfolio_outcome.target_cost

    @property
    def benchmark_gross_return(self) -> Decimal:
        """Return the Portfolio-owned benchmark gross return."""

        return self.portfolio_outcome.benchmark_gross_return

    @property
    def benchmark_cost(self) -> Decimal:
        """Return the Portfolio-owned benchmark cost."""

        return self.portfolio_outcome.benchmark_cost

    @property
    def target_maximum_drawdown(self) -> Decimal:
        """Return the Portfolio-owned target maximum drawdown."""

        return self.portfolio_outcome.target_maximum_drawdown

    @property
    def benchmark_maximum_drawdown(self) -> Decimal:
        """Return the Portfolio-owned benchmark maximum drawdown."""

        return self.portfolio_outcome.benchmark_maximum_drawdown

    @property
    def capacity_utilization(self) -> Decimal:
        """Return the Portfolio-owned capacity utilization."""

        return self.portfolio_outcome.capacity_utilization

    @property
    def liquidity_breached(self) -> bool:
        """Return the Portfolio-owned liquidity breach state."""

        return self.portfolio_outcome.liquidity_breached

    @property
    def realized_credit_loss(self) -> Decimal:
        """Return the Portfolio-owned realized credit loss."""

        return self.portfolio_outcome.realized_credit_loss


def _observation_payload(
    *,
    observation_id: str,
    fixed_income_record: R5RelativeValueOwnerRecordSeal,
    portfolio_outcome: R5PortfolioOutcomeSeal,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-trial-observation.v1",
        "observation_id": observation_id,
        "fixed_income_record": (
            fixed_income_record.result_id,
            fixed_income_record.result_version,
            fixed_income_record.result_record_hash,
            fixed_income_record.content_hash,
        ),
        "portfolio_outcome": (
            portfolio_outcome.outcome_id,
            portfolio_outcome.outcome_version,
            portfolio_outcome.owner_record_id,
            portfolio_outcome.owner_record_version,
            portfolio_outcome.owner_record_hash,
            portfolio_outcome.content_hash,
        ),
    }


def r5_relative_value_trial_observation_hash(
    observation: R5RelativeValueTrialObservation,
) -> str:
    """Recompute one exact formation/outcome observation hash."""

    return _canonical_hash(
        _observation_payload(
            observation_id=observation.observation_id,
            fixed_income_record=observation.fixed_income_record,
            portfolio_outcome=observation.portfolio_outcome,
        )
    )


class _TrialValues(TypedDict):
    trial_version: str
    scope: R5RelativeValuePromotionScope
    policy_id: str
    policy_version: str
    policy_content_hash: str
    registration_id: str
    registration_content_hash: str
    observations: tuple[R5RelativeValueTrialObservation, ...]
    observed_count: int
    expected_count: int
    coverage_ratio: Decimal
    state: R5RelativeValuePromotionTrialState
    blocker_codes: tuple[str, ...]
    evaluated_at: datetime
    recorded_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class R5RelativeValuePromotionTrial:
    """Research-owned exact trial over a pre-registered OOS observation set."""

    trial_id: str
    trial_version: str
    owner: str
    capability: str
    purpose: str
    scope: R5RelativeValuePromotionScope
    policy_id: str
    policy_version: str
    policy_content_hash: str
    registration_id: str
    registration_content_hash: str
    observations: tuple[R5RelativeValueTrialObservation, ...]
    observed_count: int
    expected_count: int
    coverage_ratio: Decimal
    state: R5RelativeValuePromotionTrialState
    blocker_codes: tuple[str, ...]
    evaluated_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy: R5RelativeValuePromotionPolicy,
        observations: tuple[R5RelativeValueTrialObservation, ...],
        evaluated_at: datetime,
    ) -> R5RelativeValuePromotionTrial:
        """Validate preregistration and derive coverage/readiness/validity."""

        require_aware(evaluated_at, "R5 trial evaluated_at")
        if observations != tuple(sorted(observations, key=lambda item: item.observation_id)):
            raise ValueError("R5 trial observations must be ordered by observation ID")
        observation_ids = tuple(item.observation_id for item in observations)
        if observation_ids != tuple(sorted(set(observation_ids))):
            raise ValueError("R5 trial observations must be unique")
        expected_ids = policy.registration.expected_observation_ids
        if any(observation_id not in expected_ids for observation_id in observation_ids):
            raise ValueError("R5 trial contains an observation outside preregistration")
        result_ids = tuple(item.fixed_income_record.result_id for item in observations)
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("R5 trial requires distinct fixed-income records")
        outcome_owner_records = tuple(
            (
                item.portfolio_outcome.owner_record_id,
                item.portfolio_outcome.owner_record_version,
                item.portfolio_outcome.owner_record_hash,
            )
            for item in observations
        )
        if len(outcome_owner_records) != len(set(outcome_owner_records)):
            raise ValueError("R5 trial requires distinct Portfolio outcome records")
        for observation in observations:
            if not (
                policy.recorded_at <= observation.selection_as_of
                and policy.active_from <= observation.selection_as_of < policy.active_until
            ):
                raise ValueError("R5 promotion policy was not preregistered before selection")
            if not observation.recorded_at <= evaluated_at < observation.valid_until:
                raise ValueError("R5 trial observation is unavailable at evaluation")
            if observation.fixed_income_record.assessment.input_set_id == "":
                raise ValueError("R5 trial fixed-income record identity is invalid")
        observed_count = len(observations)
        expected_count = len(expected_ids)
        coverage_ratio = Decimal(observed_count) / Decimal(expected_count)
        blockers = _trial_blockers(
            policy=policy,
            observations=observations,
            observation_ids=observation_ids,
            observed_count=observed_count,
            coverage_ratio=coverage_ratio,
        )
        state = (
            R5RelativeValuePromotionTrialState.READY_FOR_POLICY_EVALUATION
            if not blockers
            else R5RelativeValuePromotionTrialState.BLOCKED
        )
        recorded_at = max(item.recorded_at for item in observations)
        valid_until = min(
            policy.active_until,
            *(item.valid_until for item in observations),
        )
        values: _TrialValues = {
            "trial_version": policy.registration.trial_version,
            "scope": policy.scope,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_content_hash": policy.content_hash,
            "registration_id": policy.registration.registration_id,
            "registration_content_hash": policy.registration.content_hash,
            "observations": observations,
            "observed_count": observed_count,
            "expected_count": expected_count,
            "coverage_ratio": coverage_ratio,
            "state": state,
            "blocker_codes": blockers,
            "evaluated_at": evaluated_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
        }
        digest = _canonical_hash(_trial_payload(**values))
        return cls(
            trial_id=f"r5-rv-trial:{digest}",
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            content_hash=digest,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            **values,
        )

    def __post_init__(self) -> None:
        require_token(self.trial_version, "R5 promotion trial_version")
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
            or self.scope.owner != self.owner
            or self.scope.capability != self.capability
            or self.scope.purpose != self.purpose
        ):
            raise ValueError("R5 promotion trial authority is invalid")
        for value, label in (
            (self.policy_id, "policy_id"),
            (self.policy_version, "policy_version"),
            (self.registration_id, "registration_id"),
        ):
            require_token(value, f"R5 promotion trial {label}", maximum=300)
        for value, label in (
            (self.policy_content_hash, "policy_content_hash"),
            (self.registration_content_hash, "registration_content_hash"),
            (self.content_hash, "content_hash"),
        ):
            require_sha256(value, f"R5 promotion trial {label}")
        if (
            isinstance(self.observed_count, bool)
            or isinstance(self.expected_count, bool)
            or self.observed_count < 1
            or self.expected_count < self.observed_count
        ):
            raise ValueError("R5 promotion trial observation counts are invalid")
        _require_finite(self.coverage_ratio, "R5 trial coverage ratio")
        if not Decimal("0") < self.coverage_ratio <= Decimal("1"):
            raise ValueError("R5 trial coverage ratio must be within (0, 1]")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("R5 trial blockers must be unique and ordered")
        if (self.state is R5RelativeValuePromotionTrialState.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R5 trial state must be derived from blockers")
        for field_name in ("evaluated_at", "recorded_at", "valid_until"):
            require_aware(
                getattr(self, field_name),
                f"R5 promotion trial {field_name}",
            )
        if not self.recorded_at <= self.evaluated_at < self.valid_until:
            raise ValueError("R5 trial knowledge/validity window is invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 promotion trial must remain research-only")
        expected = r5_relative_value_promotion_trial_hash(self)
        if self.content_hash != expected or self.trial_id != f"r5-rv-trial:{expected}":
            raise ValueError("R5 promotion trial content hash or identity mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact trial is known and valid at knowledge time."""

        require_aware(as_of, "R5 promotion trial as_of")
        return self.recorded_at <= as_of < self.valid_until


def _trial_blockers(
    *,
    policy: R5RelativeValuePromotionPolicy,
    observations: tuple[R5RelativeValueTrialObservation, ...],
    observation_ids: tuple[str, ...],
    observed_count: int,
    coverage_ratio: Decimal,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if observation_ids != policy.registration.expected_observation_ids:
        blockers.append("expected_observation_coverage_incomplete")
    if observed_count < policy.minimum_observation_count:
        blockers.append("minimum_observation_count_not_met")
    if coverage_ratio < policy.minimum_coverage_ratio:
        blockers.append("minimum_coverage_ratio_not_met")
    for observation in observations:
        record = observation.fixed_income_record
        if not record.is_assessment_available:
            blockers.append("fixed_income_assessment_unavailable")
        if any(
            component.status is not R5ComponentStatus.AVAILABLE
            for component in record.assessment.component_seals
        ):
            blockers.append("fixed_income_component_family_incomplete")
        if not (
            record.research_only and record.must_not_use_for_decision and record.must_not_execute
        ):
            blockers.append("fixed_income_safety_boundary_invalid")
    return tuple(sorted(set(blockers)))


def _trial_payload(
    *,
    trial_version: str,
    scope: R5RelativeValuePromotionScope,
    policy_id: str,
    policy_version: str,
    policy_content_hash: str,
    registration_id: str,
    registration_content_hash: str,
    observations: tuple[R5RelativeValueTrialObservation, ...],
    observed_count: int,
    expected_count: int,
    coverage_ratio: Decimal,
    state: R5RelativeValuePromotionTrialState,
    blocker_codes: tuple[str, ...],
    evaluated_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-promotion-trial.v1",
        "identity": [trial_version, "research", "r5"],
        "scope": [scope.scope_id, scope.content_hash],
        "policy": [policy_id, policy_version, policy_content_hash],
        "registration": [registration_id, registration_content_hash],
        "observations": tuple(
            [
                item.observation_id,
                item.content_hash,
                item.fixed_income_record.result_id,
                item.fixed_income_record.result_version,
                item.fixed_income_record.result_record_hash,
                item.fixed_income_record.content_hash,
                item.portfolio_outcome.outcome_id,
                item.portfolio_outcome.outcome_version,
                item.portfolio_outcome.owner_record_id,
                item.portfolio_outcome.owner_record_version,
                item.portfolio_outcome.owner_record_hash,
                item.portfolio_outcome.content_hash,
            ]
            for item in observations
        ),
        "coverage": [observed_count, expected_count, coverage_ratio],
        "state": [state.value, blocker_codes],
        "window": [evaluated_at, recorded_at, valid_until],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_relative_value_promotion_trial_hash(
    trial: R5RelativeValuePromotionTrial,
) -> str:
    """Recompute the complete content-addressed R5 trial hash."""

    return _canonical_hash(
        _trial_payload(
            trial_version=trial.trial_version,
            scope=trial.scope,
            policy_id=trial.policy_id,
            policy_version=trial.policy_version,
            policy_content_hash=trial.policy_content_hash,
            registration_id=trial.registration_id,
            registration_content_hash=trial.registration_content_hash,
            observations=trial.observations,
            observed_count=trial.observed_count,
            expected_count=trial.expected_count,
            coverage_ratio=trial.coverage_ratio,
            state=trial.state,
            blocker_codes=trial.blocker_codes,
            evaluated_at=trial.evaluated_at,
            recorded_at=trial.recorded_at,
            valid_until=trial.valid_until,
        )
    )


__all__ = [
    "R5RelativeValuePromotionTrial",
    "R5RelativeValuePromotionTrialState",
    "R5RelativeValueTrialObservation",
    "r5_relative_value_promotion_trial_hash",
    "r5_relative_value_trial_observation_hash",
]
