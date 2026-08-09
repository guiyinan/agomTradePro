"""Spread-percentile evaluation orchestration split from its contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from apps.fixed_income.domain.evidence import EvidenceRole, require_aware, require_sha256
from apps.fixed_income.domain.spread_history import (
    ExpectedObservationCalendar,
    SelectedSpreadObservation,
    SpreadAssessmentStatus,
    SpreadBlocker,
    SpreadBlockerCode,
    SpreadObservation,
    SpreadObservationState,
    SpreadPercentileAssessment,
    SpreadPercentileEvidence,
    SpreadPercentilePolicy,
    SpreadTieConvention,
    _blocker,
    _reference_matches_scope,
    _result,
    spread_percentile_input_hash,
)


def evaluate_spread_percentile(
    evidence: SpreadPercentileEvidence,
    *,
    policy: SpreadPercentilePolicy,
    calendar: ExpectedObservationCalendar,
    evaluated_at: datetime,
    expected_input_hash: str | None = None,
) -> SpreadPercentileAssessment:
    """Evaluate an exact PIT historical spread percentile without future revisions."""

    require_aware(evaluated_at, "evaluated_at")
    input_hash = spread_percentile_input_hash(
        evidence,
        policy,
        calendar,
        evaluated_at=evaluated_at,
    )
    blockers: list[SpreadBlocker] = []
    if expected_input_hash is not None:
        require_sha256(expected_input_hash, "expected_input_hash")
        if expected_input_hash.lower() != input_hash:
            blockers.append(_blocker(SpreadBlockerCode.INPUT_HASH_MISMATCH, "input hash mismatch"))

    policy_reason = policy.evidence.usability_reason(evaluated_at)
    if policy_reason is not None:
        blockers.append(_blocker(SpreadBlockerCode.POLICY_INACTIVE, "policy evidence inactive"))
    source_reason = evidence.source.usability_reason(evaluated_at)
    if source_reason == "evidence_from_future":
        blockers.append(_blocker(SpreadBlockerCode.EVIDENCE_FROM_FUTURE, "PIT source from future"))
    elif source_reason == "evidence_stale":
        blockers.append(_blocker(SpreadBlockerCode.EVIDENCE_STALE, "PIT source stale"))
    if calendar.evidence.role is not EvidenceRole.CALENDAR:
        blockers.append(
            _blocker(
                SpreadBlockerCode.CALENDAR_ROLE_MISMATCH,
                "calendar role mismatch",
            )
        )
    calendar_reason = calendar.evidence.usability_reason(evaluated_at)
    if calendar_reason == "evidence_from_future":
        blockers.append(_blocker(SpreadBlockerCode.CALENDAR_FROM_FUTURE, "calendar from future"))
    elif calendar_reason == "evidence_stale":
        blockers.append(_blocker(SpreadBlockerCode.CALENDAR_STALE, "calendar stale"))
    if calendar.scope_id != evidence.scope_id:
        blockers.append(_blocker(SpreadBlockerCode.SCOPE_MISMATCH, "calendar scope mismatch"))

    if (
        policy.lookback_ends_at > evaluated_at
        or policy.lookback_ends_at > evidence.target.observed_at
    ):
        blockers.append(
            _blocker(
                SpreadBlockerCode.LOOKBACK_CUTOFF_INVALID,
                "lookback end exceeds target or PIT cutoff",
            )
        )

    expected_periods = tuple(
        period
        for period in calendar.periods
        if period.starts_at >= policy.lookback_starts_at
        and period.ends_at <= policy.lookback_ends_at
        and period.expected_release_at <= evaluated_at
    )
    expected_period_ids = {period.period_id for period in expected_periods}
    if any(period.ends_at > evaluated_at for period in expected_periods):
        blockers.append(
            _blocker(
                SpreadBlockerCode.LOOKBACK_CUTOFF_INVALID,
                "expected reference period exceeds PIT cutoff",
            )
        )
    if evidence.target.period_id in expected_period_ids:
        blockers.append(
            _blocker(
                SpreadBlockerCode.TARGET_PERIOD_IN_REFERENCE,
                "target period appears in expected reference calendar",
            )
        )

    all_observations = (evidence.target, *evidence.reference_observations)
    for observation in all_observations:
        blockers.extend(_reference_matches_scope(evidence, observation))
        if observation.publication.role is not EvidenceRole.PUBLICATION:
            blockers.append(
                _blocker(
                    SpreadBlockerCode.PUBLICATION_ROLE_MISMATCH,
                    "publication role mismatch",
                )
            )
        if observation.observed_at > evaluated_at or observation.available_at > evaluated_at:
            blockers.append(
                _blocker(SpreadBlockerCode.EVIDENCE_FROM_FUTURE, "observation from future")
            )
        if observation is evidence.target:
            publication_reason = observation.publication.usability_reason(evaluated_at)
            if publication_reason == "evidence_from_future":
                blockers.append(
                    _blocker(
                        SpreadBlockerCode.EVIDENCE_FROM_FUTURE,
                        "target publication from future",
                    )
                )
            elif publication_reason == "evidence_stale":
                blockers.append(
                    _blocker(
                        SpreadBlockerCode.EVIDENCE_STALE,
                        "target publication stale",
                    )
                )

    if evidence.target.state is SpreadObservationState.MISSING:
        blockers.append(_blocker(SpreadBlockerCode.TARGET_MISSING, "target spread is missing"))
    elif (
        evidence.target.state is SpreadObservationState.ESTIMATED
        and not policy.allow_estimated_target
    ):
        blockers.append(
            _blocker(
                SpreadBlockerCode.TARGET_ESTIMATED_NOT_ALLOWED,
                "estimated target spread is not allowed",
            )
        )

    target_identity = (
        evidence.target.observation_id,
        evidence.target.observation_version,
        evidence.target.record_hash.lower(),
    )
    if any(
        (
            observation.observation_id,
            observation.observation_version,
            observation.record_hash.lower(),
        )
        == target_identity
        for observation in evidence.reference_observations
    ):
        blockers.append(
            _blocker(
                SpreadBlockerCode.TARGET_IN_REFERENCE_SAMPLE,
                "target appears in reference sample",
            )
        )
    if any(
        observation.period_id == evidence.target.period_id
        for observation in evidence.reference_observations
    ):
        blockers.append(
            _blocker(
                SpreadBlockerCode.TARGET_PERIOD_IN_REFERENCE,
                "target period revision appears in reference sample",
            )
        )

    grouped: dict[str, list[SpreadObservation]] = {}
    for observation in evidence.reference_observations:
        if observation.period_id not in expected_period_ids:
            blockers.append(
                _blocker(
                    SpreadBlockerCode.PERIOD_OUTSIDE_CALENDAR,
                    "reference period outside expected calendar",
                )
            )
            continue
        grouped.setdefault(observation.period_id, []).append(observation)

    selected_rows: list[SelectedSpreadObservation] = []
    for period_id in sorted(grouped):
        candidates = grouped[period_id]
        ordered_by_revision = tuple(
            sorted(candidates, key=lambda observation: observation.revision_number)
        )
        revision_numbers = tuple(observation.revision_number for observation in ordered_by_revision)
        if len(revision_numbers) != len(set(revision_numbers)):
            blockers.append(
                _blocker(
                    SpreadBlockerCode.PERIOD_DUPLICATE_REVISION,
                    "duplicate period revision number",
                )
            )
        for previous, current in zip(
            ordered_by_revision,
            ordered_by_revision[1:],
            strict=False,
        ):
            if (
                current.revision_number > previous.revision_number
                and current.available_at <= previous.available_at
            ):
                blockers.append(
                    _blocker(
                        SpreadBlockerCode.REVISION_CHRONOLOGY_INVALID,
                        "revision availability does not advance",
                    )
                )
        eligible = tuple(
            observation
            for observation in candidates
            if observation.observed_at <= evaluated_at and observation.available_at <= evaluated_at
        )
        if not eligible:
            continue
        max_revision = max(observation.revision_number for observation in eligible)
        latest = tuple(
            observation for observation in eligible if observation.revision_number == max_revision
        )
        if len(latest) != 1:
            blockers.append(
                _blocker(
                    SpreadBlockerCode.PERIOD_DUPLICATE_REVISION,
                    "duplicate latest period revision",
                )
            )
            continue
        chosen = latest[0]
        calendar_period = next(
            period for period in expected_periods if period.period_id == period_id
        )
        release_deadline = calendar_period.expected_release_at + timedelta(
            seconds=policy.maximum_release_lag_seconds
        )
        if chosen.available_at > release_deadline:
            blockers.append(
                _blocker(
                    SpreadBlockerCode.RELEASE_LAG_EXCEEDED,
                    "selected revision exceeds release-lag policy",
                )
            )
        if chosen.state is SpreadObservationState.ESTIMATED and not policy.allow_estimated:
            blockers.append(
                _blocker(
                    SpreadBlockerCode.ESTIMATED_NOT_ALLOWED,
                    "estimated observation not allowed",
                )
            )
            continue
        if chosen.state is SpreadObservationState.MISSING:
            continue
        if chosen.value_bp is None:
            continue
        selected_rows.append(
            SelectedSpreadObservation(
                period_id=chosen.period_id,
                observation_id=chosen.observation_id,
                observation_version=chosen.observation_version,
                revision_number=chosen.revision_number,
                record_hash=chosen.record_hash.lower(),
                value_bp=chosen.value_bp,
            )
        )

    selected = tuple(selected_rows)
    reference_count = len(selected)
    expected_count = len(expected_periods)
    coverage = (
        Decimal(reference_count) / Decimal(expected_count) if expected_count > 0 else Decimal("0")
    )
    if reference_count == 0:
        blockers.append(
            _blocker(SpreadBlockerCode.EMPTY_REFERENCE_SAMPLE, "reference sample empty")
        )
    if reference_count < policy.minimum_observation_count:
        blockers.append(
            _blocker(
                SpreadBlockerCode.MINIMUM_SAMPLE_NOT_MET,
                "minimum observation count not met",
            )
        )
    if coverage < policy.minimum_coverage_ratio:
        blockers.append(
            _blocker(
                SpreadBlockerCode.COVERAGE_INSUFFICIENT,
                "calendar coverage insufficient",
            )
        )

    target_value = evidence.target.value_bp
    less = equal = greater = 0
    percentile: Decimal | None = None
    if target_value is not None and reference_count > 0:
        less = sum(row.value_bp < target_value for row in selected)
        equal = sum(row.value_bp == target_value for row in selected)
        greater = sum(row.value_bp > target_value for row in selected)
        if policy.tie_convention is SpreadTieConvention.MID_RANK:
            percentile = (Decimal(less) + (Decimal("0.5") * Decimal(equal))) / Decimal(
                reference_count
            )
        elif policy.tie_convention is SpreadTieConvention.STRICT_LESS:
            percentile = Decimal(less) / Decimal(reference_count)
        else:
            percentile = Decimal(less + equal) / Decimal(reference_count)

    unique_blockers = tuple(
        sorted(set(blockers), key=lambda blocker: (blocker.code.value, blocker.detail))
    )
    return _result(
        status=(
            SpreadAssessmentStatus.BLOCKED if unique_blockers else SpreadAssessmentStatus.AVAILABLE
        ),
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        policy=policy,
        calendar=calendar,
        target_value_bp=target_value,
        expected_period_count=expected_count,
        selected=selected,
        less_count=less,
        equal_count=equal,
        greater_count=greater,
        percentile=percentile,
        blockers=unique_blockers,
    )


__all__ = ["evaluate_spread_percentile"]
