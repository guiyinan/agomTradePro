"""Domain contracts for owner-published M1 rebalance risk revisions.

This module uses only the Python standard library.  A revision is a new,
explicit M1 preview policy; it never claims to version an older strategy rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

RiskDimension = Literal["max_single_position", "max_total_position", "max_stop_loss"]
RiskSourceLimitField = Literal[
    "max_single_position_pct",
    "max_total_position_pct",
    "stop_loss_pct",
]
StrategySelectionState = Literal["configured", "confirmed_unconfigured", "unavailable"]
AccountType = Literal["simulated", "real", "unknown"]
RevocationState = Literal["not_revoked", "revoked", "unknown"]
RiskFalsificationStatus = Literal[
    "not_evaluated",
    "not_applicable",
    "not_falsified",
    "falsified",
    "unknown",
]


class RiskApplicability(StrEnum):
    """Whether one risk condition has a value for this explicit policy."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class RiskConditionOutcome(StrEnum):
    """Observed falsification state for one versioned risk condition."""

    NOT_FALSIFIED = "not_falsified"
    FALSIFIED = "falsified"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RiskQualificationState(StrEnum):
    """Result of checking revision identity, validity, and bound sources."""

    QUALIFIED = "qualified"
    MISSING = "missing"
    NOT_EFFECTIVE = "not_effective"
    SOURCE_CHANGED = "source_changed"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class M1RiskCondition:
    """One explicit percentage-point limit or an explicit unknown state.

    ``not_applicable`` must include an owner-supplied reason.  That declaration
    concerns this new M1 policy only; it never changes the legacy account or
    strategy source and does not imply that a legacy NULL means disabled.
    """

    applicability: RiskApplicability
    limit_pct: Decimal | None
    not_applicable_reason: str | None = None

    def __post_init__(self) -> None:
        """Require an exact, bounded Decimal when a condition applies."""

        if type(self.applicability) is not RiskApplicability:
            raise TypeError("applicability must be an exact RiskApplicability")
        if self.applicability is RiskApplicability.APPLICABLE:
            if type(self.limit_pct) is not Decimal or not self.limit_pct.is_finite():
                raise ValueError("applicable risk conditions require a finite Decimal limit")
            if self.limit_pct < Decimal("0") or self.limit_pct > Decimal("100"):
                raise ValueError("risk percentage-point limit must be within 0..100")
            if self.not_applicable_reason is not None:
                raise ValueError("applicable conditions cannot carry a not-applicable reason")
        elif self.applicability is RiskApplicability.NOT_APPLICABLE:
            if self.limit_pct is not None:
                raise ValueError("not-applicable conditions cannot carry a numeric limit")
            if (
                type(self.not_applicable_reason) is not str
                or not self.not_applicable_reason.strip()
            ):
                raise ValueError("not-applicable conditions require an owner-supplied reason")
        else:
            if self.limit_pct is not None:
                raise ValueError("unknown conditions cannot carry an inferred numeric limit")
            if self.not_applicable_reason is not None:
                raise ValueError("unknown conditions cannot claim not-applicability")


@dataclass(frozen=True, slots=True)
class M1RiskSourceSnapshot:
    """Exact current account, strategy, and position-rule facts bound at publish.

    The selected strategy identity and available version number are captured,
    but a strategy version is not treated as an archived risk-policy revision
    or source effective time.  Source timestamps are not inferred.  The
    serialized position rule is source content, not a generated hash.
    """

    account_id: int
    account_owner_user_id: int | None
    account_type: AccountType
    account_is_active: bool | None
    account_max_single_position_pct: Decimal | None
    account_max_total_position_pct: Decimal | None
    account_stop_loss_pct: Decimal | None
    strategy_selection_state: StrategySelectionState
    strategy_id: int | None
    strategy_version: int | None
    strategy_max_single_position_pct: Decimal | None
    strategy_max_total_position_pct: Decimal | None
    strategy_stop_loss_pct: Decimal | None
    position_rule_id: int | None
    position_rule_source_json: str | None
    account_invalid_limit_fields: tuple[RiskSourceLimitField, ...] = ()
    strategy_invalid_limit_fields: tuple[RiskSourceLimitField, ...] = ()

    def __post_init__(self) -> None:
        """Reject malformed IDs and non-finite source percentages."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be an exact positive integer")
        if self.account_owner_user_id is not None and (
            type(self.account_owner_user_id) is not int or self.account_owner_user_id <= 0
        ):
            raise ValueError("account_owner_user_id must be a positive integer or None")
        if type(self.account_type) is not str or self.account_type not in {
            "simulated",
            "real",
            "unknown",
        }:
            raise ValueError("account_type must be simulated, real, or unknown")
        if self.account_is_active is not None and type(self.account_is_active) is not bool:
            raise TypeError("account_is_active must be an exact bool or None")
        if type(self.strategy_selection_state) is not str or self.strategy_selection_state not in {
            "configured",
            "confirmed_unconfigured",
            "unavailable",
        }:
            raise ValueError("unsupported strategy selection state")
        for name in ("strategy_id", "strategy_version", "position_rule_id"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        for name in (
            "account_max_single_position_pct",
            "account_max_total_position_pct",
            "account_stop_loss_pct",
            "strategy_max_single_position_pct",
            "strategy_max_total_position_pct",
            "strategy_stop_loss_pct",
        ):
            _validate_optional_pct(name, getattr(self, name))
        _validate_invalid_limit_fields(
            "account_invalid_limit_fields", self.account_invalid_limit_fields
        )
        _validate_invalid_limit_fields(
            "strategy_invalid_limit_fields", self.strategy_invalid_limit_fields
        )
        if (
            self.position_rule_source_json is not None
            and type(self.position_rule_source_json) is not str
        ):
            raise TypeError("position_rule_source_json must be str or None")
        if self.strategy_selection_state == "confirmed_unconfigured" and (
            any(
                value is not None
                for value in (
                    self.strategy_id,
                    self.strategy_version,
                    self.strategy_max_single_position_pct,
                    self.strategy_max_total_position_pct,
                    self.strategy_stop_loss_pct,
                    self.position_rule_id,
                    self.position_rule_source_json,
                )
            )
            or bool(self.strategy_invalid_limit_fields)
        ):
            raise ValueError("confirmed_unconfigured cannot carry strategy source values")
        if self.strategy_selection_state == "configured" and self.strategy_id is None:
            raise ValueError("configured strategy source requires an exact strategy_id")

    def unknown_source_reasons(self) -> tuple[str, ...]:
        """Return stable blockers for any missing source needed by M1 BUY rules."""

        reasons: list[str] = []
        reasons.extend(
            _limit_source_reason("ACCOUNT", field_name)
            for field_name in self.account_invalid_limit_fields
        )
        reasons.extend(
            _limit_source_reason("STRATEGY", field_name)
            for field_name in self.strategy_invalid_limit_fields
        )
        if self.account_owner_user_id is None:
            reasons.append("ACCOUNT_OWNER_SOURCE_UNKNOWN")
        if self.account_type == "unknown":
            reasons.append("ACCOUNT_TYPE_SOURCE_UNKNOWN")
        elif self.account_type != "simulated":
            reasons.append("ACCOUNT_TYPE_NOT_SIMULATED")
        if self.account_is_active is not True:
            reasons.append("ACCOUNT_ACTIVE_SOURCE_NOT_VALID")
        if self.strategy_selection_state == "unavailable":
            reasons.append("STRATEGY_SELECTION_SOURCE_UNKNOWN")
        elif self.strategy_selection_state == "configured":
            if self.strategy_id is None:
                reasons.append("STRATEGY_ID_SOURCE_UNKNOWN")
            if self.position_rule_id is not None and self.position_rule_source_json is None:
                reasons.append("POSITION_RULE_SOURCE_UNKNOWN")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class M1RiskPolicyRevision:
    """One persisted owner decision, with real validity and knowledge times."""

    risk_policy_version: str
    account_id: int
    actor_user_id: int
    effective_from: datetime
    effective_until: datetime
    known_at: datetime
    reason: str
    max_single_position: M1RiskCondition
    max_total_position: M1RiskCondition
    max_stop_loss: M1RiskCondition
    source_snapshot: M1RiskSourceSnapshot
    revocation_state: RevocationState = "not_revoked"
    revoked_at: datetime | None = None
    revoked_by_user_id: int | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate persisted identity and aware clocks without deriving them."""

        if type(self.risk_policy_version) is not str or not self.risk_policy_version.strip():
            raise ValueError("risk_policy_version is required")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be an exact positive integer")
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be an exact positive integer")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("owner reason is required")
        if self.source_snapshot.account_id != self.account_id:
            raise ValueError("revision and source snapshot account identities differ")
        for name in ("effective_from", "effective_until", "known_at"):
            _require_aware_datetime(name, getattr(self, name))
        if self.effective_from >= self.effective_until:
            raise ValueError("effective_from must precede effective_until")
        if self.effective_from < self.known_at:
            raise ValueError("effective_from cannot precede the real known_at source")
        if type(self.revocation_state) is not str or self.revocation_state not in {
            "not_revoked",
            "revoked",
            "unknown",
        }:
            raise ValueError("revocation_state is unsupported")
        if self.revocation_state == "not_revoked":
            if any(
                value is not None
                for value in (self.revoked_at, self.revoked_by_user_id, self.revocation_reason)
            ):
                raise ValueError("not_revoked revision cannot carry audit event values")
        elif self.revocation_state == "revoked":
            if self.revoked_at is None:
                raise ValueError("revoked revision requires the audit effective_at source")
            _require_aware_datetime("revoked_at", self.revoked_at)
            if type(self.revoked_by_user_id) is not int or self.revoked_by_user_id <= 0:
                raise ValueError("revoked revision requires a real audit actor")
            if type(self.revocation_reason) is not str or not self.revocation_reason.strip():
                raise ValueError("revocation requires a non-empty audit reason")
        else:
            if self.revoked_at is not None:
                _require_aware_datetime("revoked_at", self.revoked_at)
            if self.revoked_by_user_id is not None and (
                type(self.revoked_by_user_id) is not int or self.revoked_by_user_id <= 0
            ):
                raise ValueError("revocation actor must be positive or None")
            if self.revocation_reason is not None and (
                type(self.revocation_reason) is not str or not self.revocation_reason.strip()
            ):
                raise ValueError("revocation reason must be non-empty when present")


@dataclass(frozen=True, slots=True)
class M1RiskPolicyPublishCommand:
    """Owner-confirmed inputs for a new M1-only policy revision."""

    account_id: int
    actor_user_id: int
    effective_from: datetime
    effective_until: datetime
    reason: str
    max_single_position: M1RiskCondition
    max_total_position: M1RiskCondition
    max_stop_loss: M1RiskCondition
    source_snapshot: M1RiskSourceSnapshot


@dataclass(frozen=True, slots=True)
class M1RiskPolicyQualification:
    """Identity, validity, and source qualification for one as-of preview."""

    state: RiskQualificationState
    reason_codes: tuple[str, ...]
    revision: M1RiskPolicyRevision | None

    @property
    def ready_for_buy(self) -> bool:
        """Return true only for a unique, current, complete versioned source."""

        return self.state is RiskQualificationState.QUALIFIED and not self.reason_codes


@dataclass(frozen=True, slots=True)
class M1RiskObservation:
    """One percentage-point observation used to evaluate a policy condition."""

    dimension: RiskDimension
    applicability: RiskApplicability
    observed_pct: Decimal | None

    def __post_init__(self) -> None:
        """Reject an observation that hides a missing or non-finite measure."""

        if type(self.applicability) is not RiskApplicability:
            raise TypeError("observation applicability must be an exact RiskApplicability")
        if self.dimension not in {"max_single_position", "max_total_position", "max_stop_loss"}:
            raise ValueError("unsupported M1 risk dimension")
        if self.applicability is RiskApplicability.APPLICABLE:
            if type(self.observed_pct) is not Decimal or not self.observed_pct.is_finite():
                raise ValueError("applicable risk observations require a finite Decimal")
        elif self.observed_pct is not None:
            raise ValueError("non-applicable and unknown observations cannot carry a value")


@dataclass(frozen=True, slots=True)
class M1RiskFalsificationItem:
    """One policy condition and its distinct runtime applicability/result."""

    dimension: RiskDimension
    policy_applicability: RiskApplicability
    observation_applicability: RiskApplicability
    predicate: str
    threshold_pct: Decimal | None
    observed_pct: Decimal | None
    outcome: RiskConditionOutcome


@dataclass(frozen=True, slots=True)
class M1RiskFalsification:
    """Typed, reproducible M1 falsification summary for the current preview."""

    risk_policy_version: str | None
    effective_from: datetime | None
    effective_until: datetime | None
    known_at: datetime | None
    revoked_at: datetime | None
    status: RiskFalsificationStatus
    reason_codes: tuple[str, ...]
    conditions: tuple[M1RiskFalsificationItem, ...]


def validate_publish_command(command: M1RiskPolicyPublishCommand) -> tuple[str, ...]:
    """Return publication blockers while preserving unknown source evidence."""

    if command.source_snapshot.account_id != command.account_id:
        return ("RISK_SOURCE_ACCOUNT_MISMATCH",)
    if command.source_snapshot.account_owner_user_id != command.actor_user_id:
        return ("RISK_SOURCE_ACTOR_MISMATCH",)
    if command.source_snapshot.account_type != "simulated":
        return ("RISK_SOURCE_ACCOUNT_TYPE_NOT_SIMULATED",)
    if command.source_snapshot.account_is_active is not True:
        return ("RISK_SOURCE_ACCOUNT_NOT_ACTIVE",)
    _require_aware_datetime("effective_from", command.effective_from)
    _require_aware_datetime("effective_until", command.effective_until)
    if command.effective_from >= command.effective_until:
        return ("RISK_POLICY_EFFECTIVE_WINDOW_INVALID",)
    if not command.reason.strip():
        return ("RISK_POLICY_OWNER_REASON_REQUIRED",)
    reasons: list[str] = [
        *(
            _limit_source_reason("ACCOUNT", field_name)
            for field_name in command.source_snapshot.account_invalid_limit_fields
        ),
        *(
            _limit_source_reason("STRATEGY", field_name)
            for field_name in command.source_snapshot.strategy_invalid_limit_fields
        ),
    ]
    if command.source_snapshot.strategy_selection_state == "unavailable":
        reasons.append("STRATEGY_SELECTION_SOURCE_UNKNOWN")
    applicable_dimensions = 0
    for name, policy_condition, legacy_values in (
        (
            "max_single_position",
            command.max_single_position,
            (
                command.source_snapshot.account_max_single_position_pct,
                (
                    command.source_snapshot.strategy_max_single_position_pct
                    if command.source_snapshot.strategy_selection_state == "configured"
                    else None
                ),
            ),
        ),
        (
            "max_total_position",
            command.max_total_position,
            (
                command.source_snapshot.account_max_total_position_pct,
                (
                    command.source_snapshot.strategy_max_total_position_pct
                    if command.source_snapshot.strategy_selection_state == "configured"
                    else None
                ),
            ),
        ),
        (
            "max_stop_loss",
            command.max_stop_loss,
            (
                command.source_snapshot.account_stop_loss_pct,
                (
                    command.source_snapshot.strategy_stop_loss_pct
                    if command.source_snapshot.strategy_selection_state == "configured"
                    else None
                ),
            ),
        ),
    ):
        configured_legacy_limits = tuple(value for value in legacy_values if value is not None)
        if policy_condition.applicability is RiskApplicability.APPLICABLE:
            applicable_dimensions += 1
        elif configured_legacy_limits:
            reasons.append(f"M1_POLICY_OMITS_CONFIGURED_{name.upper()}_LIMIT")
        if policy_condition.applicability is not RiskApplicability.APPLICABLE:
            continue
        if configured_legacy_limits and policy_condition.limit_pct is not None:
            if policy_condition.limit_pct > min(configured_legacy_limits):
                reasons.append(f"M1_POLICY_WIDENS_{name.upper()}_LIMIT")
    if applicable_dimensions == 0:
        reasons.append("M1_POLICY_HAS_NO_APPLICABLE_LIMITS")
    if command.source_snapshot.strategy_selection_state == "configured":
        if (
            command.source_snapshot.position_rule_id is not None
            and command.source_snapshot.position_rule_source_json is None
        ):
            reasons.append("POSITION_RULE_SOURCE_UNKNOWN")
    return tuple(reasons)


def qualify_revision(
    *,
    revision: M1RiskPolicyRevision | None,
    account_id: int,
    as_of: datetime,
    current_source: M1RiskSourceSnapshot,
) -> M1RiskPolicyQualification:
    """Fail closed on absence, expired windows, source drift, or unknown facts."""

    _require_aware_datetime("as_of", as_of)
    if revision is None:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.MISSING,
            reason_codes=("M1_RISK_POLICY_VERSION_UNKNOWN",),
            revision=None,
        )
    if revision.account_id != account_id or current_source.account_id != account_id:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.SOURCE_CHANGED,
            reason_codes=("M1_RISK_POLICY_ACCOUNT_MISMATCH",),
            revision=revision,
        )
    if revision.actor_user_id != current_source.account_owner_user_id:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.SOURCE_CHANGED,
            reason_codes=("M1_RISK_POLICY_OWNER_SOURCE_CHANGED",),
            revision=revision,
        )
    if not revision.effective_from <= as_of < revision.effective_until:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.NOT_EFFECTIVE,
            reason_codes=("M1_RISK_POLICY_OUTSIDE_EFFECTIVE_WINDOW",),
            revision=revision,
        )
    if revision.revocation_state == "unknown":
        return M1RiskPolicyQualification(
            state=RiskQualificationState.UNKNOWN,
            reason_codes=("M1_RISK_POLICY_REVOCATION_SOURCE_UNKNOWN",),
            revision=revision,
        )
    if (
        revision.revocation_state == "revoked"
        and revision.revoked_at is not None
        and as_of >= revision.revoked_at
    ):
        return M1RiskPolicyQualification(
            state=RiskQualificationState.REVOKED,
            reason_codes=("M1_RISK_POLICY_REVOKED",),
            revision=revision,
        )
    current_source_reasons = current_source.unknown_source_reasons()
    if current_source_reasons:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.UNKNOWN,
            reason_codes=tuple(dict.fromkeys(current_source_reasons)),
            revision=revision,
        )
    if revision.source_snapshot != current_source:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.SOURCE_CHANGED,
            reason_codes=("M1_RISK_POLICY_SOURCE_CHANGED",),
            revision=revision,
        )
    unknown_sources: list[str] = []
    applicable_dimensions = 0
    for name, condition, account_limit, strategy_limit in (
        (
            "max_single_position",
            revision.max_single_position,
            current_source.account_max_single_position_pct,
            current_source.strategy_max_single_position_pct,
        ),
        (
            "max_total_position",
            revision.max_total_position,
            current_source.account_max_total_position_pct,
            current_source.strategy_max_total_position_pct,
        ),
        (
            "max_stop_loss",
            revision.max_stop_loss,
            current_source.account_stop_loss_pct,
            current_source.strategy_stop_loss_pct,
        ),
    ):
        known_limits = tuple(
            value
            for value in (
                account_limit,
                strategy_limit if current_source.strategy_selection_state == "configured" else None,
            )
            if value is not None
        )
        if condition.applicability is RiskApplicability.APPLICABLE:
            applicable_dimensions += 1
        elif known_limits:
            unknown_sources.append(f"M1_POLICY_OMITS_CONFIGURED_{name.upper()}_LIMIT")
        if (
            condition.applicability is RiskApplicability.APPLICABLE
            and condition.limit_pct is not None
            and known_limits
            and condition.limit_pct > min(known_limits)
        ):
            unknown_sources.append(f"M1_POLICY_WIDENS_{name.upper()}_LIMIT")
        if condition.applicability is not RiskApplicability.APPLICABLE:
            continue
        if account_limit is None:
            unknown_sources.append(_dimension_source_reason("ACCOUNT", name))
        if current_source.strategy_selection_state == "configured" and strategy_limit is None:
            unknown_sources.append(_dimension_source_reason("STRATEGY", name))
    unknown_conditions = tuple(
        f"M1_{name.upper()}_CONDITION_UNKNOWN"
        for name, condition in (
            ("max_single_position", revision.max_single_position),
            ("max_total_position", revision.max_total_position),
            ("max_stop_loss", revision.max_stop_loss),
        )
        if condition.applicability is RiskApplicability.UNKNOWN
    )
    if applicable_dimensions == 0:
        unknown_sources.append("M1_RISK_POLICY_HAS_NO_APPLICABLE_LIMITS")
    reasons = tuple(dict.fromkeys((*unknown_sources, *unknown_conditions)))
    if reasons:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.UNKNOWN,
            reason_codes=reasons,
            revision=revision,
        )
    return M1RiskPolicyQualification(
        state=RiskQualificationState.QUALIFIED,
        reason_codes=(),
        revision=revision,
    )


def evaluate_falsification(
    *,
    qualification: M1RiskPolicyQualification,
    observations: tuple[M1RiskObservation, ...],
) -> M1RiskFalsification:
    """Evaluate all three bound predicates and expose unknown evidence directly."""

    revision = qualification.revision
    policy_version = revision.risk_policy_version if revision is not None else None
    effective_from = revision.effective_from if revision is not None else None
    effective_until = revision.effective_until if revision is not None else None
    known_at = revision.known_at if revision is not None else None
    revoked_at = revision.revoked_at if revision is not None else None
    conditions: list[M1RiskFalsificationItem] = []
    if revision is None:
        return M1RiskFalsification(
            risk_policy_version=None,
            effective_from=None,
            effective_until=None,
            known_at=None,
            revoked_at=None,
            status="unknown",
            reason_codes=qualification.reason_codes,
            conditions=(),
        )
    condition_by_name: dict[RiskDimension, M1RiskCondition] = {
        "max_single_position": revision.max_single_position,
        "max_total_position": revision.max_total_position,
        "max_stop_loss": revision.max_stop_loss,
    }
    observation_by_name: dict[RiskDimension, M1RiskObservation] = {
        observation.dimension: observation for observation in observations
    }
    for name, policy_condition in condition_by_name.items():
        observation = observation_by_name.get(name)
        observation_applicability = (
            observation.applicability if observation is not None else RiskApplicability.UNKNOWN
        )
        observed_pct = observation.observed_pct if observation is not None else None
        legacy_limits = _legacy_limits_for(revision, name)
        if policy_condition.applicability is RiskApplicability.NOT_APPLICABLE and any(
            value is not None for value in legacy_limits
        ):
            conditions.append(
                M1RiskFalsificationItem(
                    dimension=name,
                    policy_applicability=policy_condition.applicability,
                    observation_applicability=observation_applicability,
                    predicate="configured_legacy_limit_must_be_covered_by_m1_policy",
                    threshold_pct=None,
                    observed_pct=observed_pct,
                    outcome=RiskConditionOutcome.UNKNOWN,
                )
            )
            continue
        if policy_condition.applicability is RiskApplicability.NOT_APPLICABLE:
            conditions.append(
                M1RiskFalsificationItem(
                    dimension=name,
                    policy_applicability=policy_condition.applicability,
                    observation_applicability=observation_applicability,
                    predicate="owner_declared_not_applicable_to_this_m1_policy",
                    threshold_pct=None,
                    observed_pct=observed_pct,
                    outcome=RiskConditionOutcome.NOT_APPLICABLE,
                )
            )
            continue
        if (
            policy_condition.applicability is RiskApplicability.UNKNOWN
            or observation_applicability is RiskApplicability.UNKNOWN
        ):
            conditions.append(
                M1RiskFalsificationItem(
                    dimension=name,
                    policy_applicability=policy_condition.applicability,
                    observation_applicability=observation_applicability,
                    predicate=_predicate_for(name),
                    threshold_pct=policy_condition.limit_pct,
                    observed_pct=observed_pct,
                    outcome=RiskConditionOutcome.UNKNOWN,
                )
            )
            continue
        if observation_applicability is RiskApplicability.NOT_APPLICABLE:
            conditions.append(
                M1RiskFalsificationItem(
                    dimension=name,
                    policy_applicability=policy_condition.applicability,
                    observation_applicability=observation_applicability,
                    predicate=_predicate_for(name),
                    threshold_pct=policy_condition.limit_pct,
                    observed_pct=None,
                    outcome=RiskConditionOutcome.NOT_APPLICABLE,
                )
            )
            continue
        threshold = policy_condition.limit_pct
        if threshold is None or observed_pct is None:
            outcome = RiskConditionOutcome.UNKNOWN
        elif name == "max_stop_loss":
            outcome = (
                RiskConditionOutcome.FALSIFIED
                if observed_pct >= threshold
                else RiskConditionOutcome.NOT_FALSIFIED
            )
        else:
            outcome = (
                RiskConditionOutcome.FALSIFIED
                if observed_pct > threshold
                else RiskConditionOutcome.NOT_FALSIFIED
            )
        conditions.append(
            M1RiskFalsificationItem(
                dimension=name,
                policy_applicability=policy_condition.applicability,
                observation_applicability=observation_applicability,
                predicate=_predicate_for(name),
                threshold_pct=threshold,
                observed_pct=observed_pct,
                outcome=outcome,
            )
        )
    outcomes = {item.outcome for item in conditions}
    if qualification.state is not RiskQualificationState.QUALIFIED:
        status: RiskFalsificationStatus = "unknown"
    elif RiskConditionOutcome.FALSIFIED in outcomes:
        status = "falsified"
    elif RiskConditionOutcome.UNKNOWN in outcomes:
        status = "unknown"
    elif outcomes == {RiskConditionOutcome.NOT_APPLICABLE}:
        status = "not_applicable"
    else:
        status = "not_falsified"
    reason_codes = qualification.reason_codes
    if RiskConditionOutcome.FALSIFIED in outcomes:
        reason_codes = (*reason_codes, "M1_RISK_FALSIFICATION_TRIGGERED")
    if RiskConditionOutcome.UNKNOWN in outcomes:
        reason_codes = (*reason_codes, "M1_RISK_FALSIFICATION_UNKNOWN")
    return M1RiskFalsification(
        risk_policy_version=policy_version,
        effective_from=effective_from,
        effective_until=effective_until,
        known_at=known_at,
        revoked_at=revoked_at,
        status=status,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        conditions=tuple(conditions),
    )


def _validate_optional_pct(name: str, value: Decimal | None) -> None:
    """Validate one nullable source percentage without assigning its meaning."""

    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal or None")
    if value < Decimal("0") or value > Decimal("100"):
        raise ValueError(f"{name} must be within 0..100 percentage points")


def _validate_invalid_limit_fields(
    name: str,
    value: tuple[RiskSourceLimitField, ...],
) -> None:
    """Accept only unique, explicit risk source field corruption markers."""

    allowed = {"max_single_position_pct", "max_total_position_pct", "stop_loss_pct"}
    if type(value) is not tuple or any(type(field_name) is not str for field_name in value):
        raise TypeError(f"{name} must be an exact tuple of risk field names")
    if len(value) != len(set(value)) or any(field_name not in allowed for field_name in value):
        raise ValueError(f"{name} contains a duplicate or unsupported field")


def _limit_source_reason(prefix: str, field_name: RiskSourceLimitField) -> str:
    """Map one stored column name to its stable public unknown-source reason."""

    suffix_by_field: dict[str, str] = {
        "max_single_position_pct": "MAX_SINGLE_POSITION",
        "max_total_position_pct": "MAX_TOTAL_POSITION",
        "stop_loss_pct": "STOP_LOSS",
    }
    return f"{prefix}_{suffix_by_field[field_name]}_SOURCE_UNKNOWN"


def _dimension_source_reason(prefix: str, dimension: str) -> str:
    """Return the stable source blocker for a public risk dimension."""

    suffix_by_dimension: dict[str, str] = {
        "max_single_position": "MAX_SINGLE_POSITION",
        "max_total_position": "MAX_TOTAL_POSITION",
        "max_stop_loss": "STOP_LOSS",
    }
    return f"{prefix}_{suffix_by_dimension[dimension]}_SOURCE_UNKNOWN"


def _legacy_limits_for(
    revision: M1RiskPolicyRevision,
    dimension: RiskDimension,
) -> tuple[Decimal | None, Decimal | None]:
    """Return the actual bound account and selected-strategy limits for a dimension."""

    source = revision.source_snapshot
    if dimension == "max_single_position":
        return (
            source.account_max_single_position_pct,
            (
                source.strategy_max_single_position_pct
                if source.strategy_selection_state == "configured"
                else None
            ),
        )
    if dimension == "max_total_position":
        return (
            source.account_max_total_position_pct,
            (
                source.strategy_max_total_position_pct
                if source.strategy_selection_state == "configured"
                else None
            ),
        )
    return (
        source.account_stop_loss_pct,
        source.strategy_stop_loss_pct if source.strategy_selection_state == "configured" else None,
    )


def _require_aware_datetime(name: str, value: datetime) -> None:
    """Reject naive clocks at every domain boundary."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _predicate_for(dimension: str) -> str:
    """Return the stable supported predicate for one policy dimension."""

    predicates: dict[str, str] = {
        "max_single_position": "target_single_position_pct <= limit_pct",
        "max_total_position": "projected_total_position_pct <= limit_pct",
        "max_stop_loss": "observed_loss_pct < stop_loss_limit_pct",
    }
    return predicates[dimension]


__all__: tuple[str, ...] = (
    "M1RiskCondition",
    "M1RiskFalsification",
    "M1RiskFalsificationItem",
    "M1RiskObservation",
    "M1RiskPolicyPublishCommand",
    "M1RiskPolicyQualification",
    "M1RiskPolicyRevision",
    "M1RiskSourceSnapshot",
    "RiskApplicability",
    "AccountType",
    "RiskConditionOutcome",
    "RiskQualificationState",
    "RiskFalsificationStatus",
    "RiskDimension",
    "RiskSourceLimitField",
    "StrategySelectionState",
    "RevocationState",
    "evaluate_falsification",
    "qualify_revision",
    "validate_publish_command",
)
