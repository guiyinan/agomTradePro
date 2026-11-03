"""Execution-proof deadlines derived from exact portfolio-risk source clocks."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, tzinfo

from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyBundle
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCloseSnapshotStateProof,
    PortfolioRiskDateSnapshotProof,
    PortfolioRiskTimestampSnapshotProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


def portfolio_risk_execution_deadline(
    evidence: PortfolioRiskSourceEvidence,
    policy: PortfolioRiskPolicyBundle,
    *,
    business_timezone: tzinfo,
    additional_policy_deadlines: tuple[datetime, ...],
) -> datetime | None:
    """Return the earliest exact source-age, source-expiry, and policy cutoff.

    Timestamp age is measured from the original observation instant in UTC. A
    date-only observation expires at midnight in the supplied business timezone
    after its final policy-allowed business date. That derived boundary is only
    a policy age deadline; it is never written to a source clock. Actual
    baseline or exception end instants are passed explicitly in
    ``additional_policy_deadlines``. Missing source clocks, source expiry, or
    timezone information returns ``None`` instead of inventing a TTL.
    """

    if type(evidence) is not PortfolioRiskSourceEvidence:
        return None
    if type(policy) is not PortfolioRiskPolicyBundle:
        return None
    if not isinstance(business_timezone, tzinfo):
        return None
    if type(additional_policy_deadlines) is not tuple:
        return None
    try:
        evidence.__post_init__()
        policy.__post_init__()
        timezone_offset = datetime.combine(
            policy.business_date,
            time.min,
            tzinfo=business_timezone,
        ).utcoffset()
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return None
    if timezone_offset is None:
        return None
    if evidence.decision_cutoff != policy.as_of:
        return None
    try:
        if policy.business_date != policy.as_of.astimezone(business_timezone).date():
            return None
    except (OverflowError, TypeError, ValueError):
        return None
    if evidence.available_at is None or evidence.known_at is None:
        return None
    if evidence.valid_until is None:
        return None
    as_of_utc = policy.as_of.astimezone(UTC)
    if (
        evidence.available_at > policy.as_of
        or evidence.known_at > policy.as_of
        or evidence.valid_until <= policy.as_of
        or evidence.must_not_use_for_decision
    ):
        return None

    deadlines = [evidence.valid_until.astimezone(UTC)]
    if evidence.observation_precision is SourceObservationPrecision.TIMESTAMP:
        if evidence.observed_at is None or evidence.observed_on is not None:
            return None
        observed_utc = evidence.observed_at.astimezone(UTC)
        if observed_utc > as_of_utc:
            return None
        try:
            deadlines.append(
                observed_utc + timedelta(seconds=policy.source_max_timestamp_age_seconds)
            )
        except OverflowError:
            return None
    elif evidence.observation_precision is SourceObservationPrecision.DATE:
        if evidence.observed_on is None or evidence.observed_at is not None:
            return None
        if (
            evidence.decision_date_cutoff != policy.business_date
            or evidence.observed_on > policy.business_date
        ):
            return None
        try:
            final_valid_date = evidence.observed_on + timedelta(
                days=policy.source_max_date_age_days
            )
            exclusive_local_date = final_valid_date + timedelta(days=1)
            local_deadline = datetime.combine(
                exclusive_local_date,
                time.min,
                tzinfo=business_timezone,
            )
            deadlines.append(local_deadline.astimezone(UTC))
        except (OverflowError, TypeError, ValueError):
            return None
    else:
        return None

    for deadline in (
        policy.industry_policy.effective_until,
        policy.capacity_policy.effective_until,
    ):
        if deadline is None:
            continue
        if type(deadline) is not datetime or deadline.tzinfo is None:
            return None
        try:
            if deadline.utcoffset() is None:
                return None
            deadlines.append(deadline.astimezone(UTC))
        except (OverflowError, TypeError, ValueError):
            return None

    for deadline in additional_policy_deadlines:
        if type(deadline) is not datetime or deadline.tzinfo is None:
            return None
        try:
            if deadline.utcoffset() is None:
                return None
            deadlines.append(deadline.astimezone(UTC))
        except (OverflowError, TypeError, ValueError):
            return None

    earliest = min(deadlines)
    return earliest if earliest > as_of_utc else None


def portfolio_risk_execution_deadline_for_evidence(
    evidence: PortfolioRiskSourceEvidence,
    policy: PortfolioRiskPolicyBundle,
    *,
    account_id: int,
    business_timezone: tzinfo,
    additional_policy_deadlines: tuple[datetime, ...],
    requested_purpose: str | None = None,
) -> datetime | None:
    """Use an exact configured proof or preserve the generic strict deadline."""

    if type(evidence) is not PortfolioRiskSourceEvidence:
        return None
    proof = evidence.policy_clock_proof
    if proof is None:
        return portfolio_risk_execution_deadline(
            evidence,
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=additional_policy_deadlines,
        )
    if type(proof) is PortfolioRiskDateSnapshotProof:
        proof_matches = _matches_policy_bounded_industry_proof(
            evidence=evidence,
            proof=proof,
            policy=policy,
            account_id=account_id,
            business_timezone=business_timezone,
        )
    elif type(proof) is PortfolioRiskTimestampSnapshotProof:
        proof_matches = _matches_policy_bounded_timestamp_proof(
            evidence=evidence,
            proof=proof,
            policy=policy,
            account_id=account_id,
            business_timezone=business_timezone,
            requested_purpose=requested_purpose,
        )
    elif type(proof) is PortfolioRiskCloseSnapshotStateProof:
        proof_matches = _matches_close_snapshot_state_proof(
            evidence=evidence,
            proof=proof,
            policy=policy,
            account_id=account_id,
            requested_purpose=requested_purpose,
        )
    else:
        return None
    if not proof_matches:
        return None
    try:
        deadlines = (proof.policy_acceptance_deadline, *additional_policy_deadlines)
        if any(
            type(deadline) is not datetime
            or deadline.tzinfo is None
            or deadline.utcoffset() is None
            for deadline in deadlines
        ):
            return None
        as_of = policy.as_of.astimezone(UTC)
        earliest = min(deadline.astimezone(UTC) for deadline in deadlines)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return None
    return earliest if earliest > as_of else None


def _matches_close_snapshot_state_proof(
    *,
    evidence: PortfolioRiskSourceEvidence,
    proof: PortfolioRiskCloseSnapshotStateProof,
    policy: PortfolioRiskPolicyBundle,
    account_id: int,
    requested_purpose: str | None,
) -> bool:
    """Rebind quote-time state evidence to the current close-only risk policy."""

    if (
        type(proof) is not PortfolioRiskCloseSnapshotStateProof
        or type(policy) is not PortfolioRiskPolicyBundle
        or type(account_id) is not int
        or account_id not in policy.account_ids
        or requested_purpose != "close_snapshot_simulation"
    ):
        return False
    reference = next(
        (
            item
            for item in policy.source_references
            if item.kind == "execution_session_state"
            and item.asset_code == proof.asset_code
            and item.security_id == proof.security_id
        ),
        None,
    )
    if reference is None:
        return False
    try:
        proof.__post_init__()
        qualification = qualify_portfolio_risk_source(
            evidence=evidence,
            requested_purpose="close_snapshot_simulation",
            allowed_observation_precisions=policy.capacity_policy.allowed_observation_precisions,
            as_of=policy.as_of,
            allowed_restrictions=policy.capacity_policy.allowed_source_restrictions,
            expected_source_kind="execution_session_state",
        )
        if not qualification.eligible:
            return False
        policy_deadlines = tuple(
            sorted(
                deadline
                for deadline in (
                    policy.industry_policy.effective_until,
                    policy.capacity_policy.effective_until,
                )
                if deadline is not None
            )
        )
    except (TypeError, ValueError):
        return False
    return (
        proof.scope == "simulation_only"
        and proof.clock_evidence_mode == "policy_bounded_close_snapshot_state"
        and proof.account_id == account_id
        and proof.as_of == policy.as_of == evidence.decision_cutoff
        and proof.business_date == policy.business_date
        and proof.execution_session == policy.business_date
        and proof.profile_key == policy.profile_key
        and proof.profile_version == policy.profile_version
        and proof.profile_content_hash == policy.profile_content_hash
        and proof.policy_snapshot_id == policy.snapshot_id
        and proof.policy_snapshot_hash == policy.snapshot_hash
        and proof.policy_content_sha256 == policy.normalized_config_sha256
        and proof.policy_known_at == policy.known_at
        and proof.policy_effective_at == policy.effective_at
        and proof.source_reference_hash == reference.raw_payload_hash
        and proof.source_record_id == reference.source_record_id
        and reference.clock_evidence_mode == proof.clock_evidence_mode
        and evidence.source_id == proof.source_id
        and evidence.source_record_id == proof.source_record_id
        and evidence.original_payload_sha256 == proof.original_body_sha256
        and evidence.observed_at == proof.observed_at
        and evidence.known_at == proof.known_at
        and evidence.available_at is None
        and evidence.valid_until is None
        and evidence.source_purpose == proof.purpose
        and set(proof.required_restrictions) <= set(evidence.restrictions)
        and proof.source_max_timestamp_age_seconds == policy.source_max_timestamp_age_seconds
        and proof.policy_deadlines == policy_deadlines
        and proof.policy_acceptance_deadline > policy.as_of
    )


def _matches_policy_bounded_industry_proof(
    *,
    evidence: PortfolioRiskSourceEvidence,
    proof: PortfolioRiskDateSnapshotProof,
    policy: PortfolioRiskPolicyBundle,
    account_id: int,
    business_timezone: tzinfo,
) -> bool:
    """Rebind the proof to the current policy, source reference, account and bounds."""

    if (
        type(proof) is not PortfolioRiskDateSnapshotProof
        or type(policy) is not PortfolioRiskPolicyBundle
        or type(account_id) is not int
        or account_id not in policy.account_ids
        or not isinstance(business_timezone, tzinfo)
    ):
        return False
    timezone_name = getattr(business_timezone, "key", None)
    if type(timezone_name) is not str:
        return False
    references = tuple(
        reference
        for reference in policy.source_references
        if reference.kind == "industry_membership"
        and reference.asset_code == proof.asset_code
        and reference.security_id == proof.security_id
        and reference.source_record_id == evidence.source_record_id
        and reference.raw_payload_hash == proof.source_reference_hash
        and reference.clock_evidence_mode == "policy_bounded_date_snapshot"
    )
    if len(references) != 1:
        return False
    if (
        policy.scope != "simulation_only"
        or proof.scope != "simulation_only"
        or proof.source_kind != "industry_membership"
        or proof.clock_evidence_mode != "policy_bounded_date_snapshot"
        or proof.account_id != account_id
        or proof.profile_key != policy.profile_key
        or proof.profile_version != policy.profile_version
        or proof.profile_content_hash != policy.profile_content_hash
        or proof.policy_snapshot_id != policy.snapshot_id
        or proof.policy_snapshot_hash != policy.snapshot_hash
        or proof.policy_content_sha256 != policy.normalized_config_sha256
        or proof.policy_known_at != policy.known_at
        or proof.policy_effective_at != policy.effective_at
        or proof.as_of != policy.as_of
        or proof.as_of != evidence.decision_cutoff
        or proof.business_date != policy.business_date
        or proof.business_timezone_name != timezone_name
        or proof.source_id != evidence.source_id
        or proof.source_record_id != evidence.source_record_id
        or proof.original_body_sha256 != evidence.original_payload_sha256
        or proof.observed_on != evidence.observed_on
        or proof.observed_on != policy.business_date
        or proof.effective_from != evidence.effective_on
        or proof.effective_until != evidence.effective_until
        or proof.effective_from != policy.business_date
        or proof.effective_until != policy.business_date
        or proof.known_at != evidence.known_at
        or proof.coverage_status != evidence.coverage.status.value
        or proof.coverage_precision_basis != evidence.coverage.precision_basis
        or proof.source_max_date_age_days != policy.source_max_date_age_days
        or proof.source_available_at is not None
        or proof.source_valid_until is not None
        or evidence.available_at is not None
        or evidence.valid_until is not None
    ):
        return False
    industry_policy = policy.industry_policy
    if (
        evidence.observation_precision is not SourceObservationPrecision.DATE
        or evidence.decision_date_cutoff != policy.business_date
        or evidence.must_not_use_for_decision
        or evidence.coverage.status.value == "unknown"
        or industry_policy.requested_purpose not in evidence.allowed_purposes
        or SourceObservationPrecision.DATE not in industry_policy.allowed_observation_precisions
        or industry_policy.requested_purpose not in industry_policy.date_precision_purposes
    ):
        return False
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=industry_policy.requested_purpose,
        allowed_observation_precisions=industry_policy.allowed_observation_precisions,
        as_of=policy.as_of,
        allowed_restrictions=industry_policy.allowed_source_restrictions,
        expected_source_kind="industry_membership",
    )
    if not qualification.eligible:
        return False
    try:
        membership_deadline = datetime.combine(
            policy.business_date + timedelta(days=1), time.min, tzinfo=business_timezone
        ).astimezone(UTC)
        date_age_deadline = datetime.combine(
            policy.business_date + timedelta(days=policy.source_max_date_age_days + 1),
            time.min,
            tzinfo=business_timezone,
        ).astimezone(UTC)
        source_policy_deadlines = tuple(
            deadline.astimezone(UTC)
            for deadline in (
                industry_policy.effective_until,
                policy.capacity_policy.effective_until,
            )
            if deadline is not None
        )
        if (
            proof.membership_deadline != membership_deadline
            or proof.date_age_deadline != date_age_deadline
            or proof.policy_deadlines != source_policy_deadlines
            or proof.policy_acceptance_deadline
            != min((membership_deadline, date_age_deadline, *source_policy_deadlines))
        ):
            return False
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return False
    return proof.policy_acceptance_deadline > policy.as_of.astimezone(UTC)


def _matches_policy_bounded_timestamp_proof(
    *,
    evidence: PortfolioRiskSourceEvidence,
    proof: PortfolioRiskTimestampSnapshotProof,
    policy: PortfolioRiskPolicyBundle,
    account_id: int,
    business_timezone: tzinfo,
    requested_purpose: str | None,
) -> bool:
    """Rebind a timestamp receipt proof to the exact active policy and source."""

    if (
        type(proof) is not PortfolioRiskTimestampSnapshotProof
        or type(policy) is not PortfolioRiskPolicyBundle
        or type(account_id) is not int
        or account_id not in policy.account_ids
        or not isinstance(business_timezone, tzinfo)
        or type(requested_purpose) is not str
        or not requested_purpose
    ):
        return False
    timezone_name = getattr(business_timezone, "key", None)
    if type(timezone_name) is not str:
        return False
    references = tuple(
        reference
        for reference in policy.source_references
        if reference.kind == proof.source_kind
        and reference.asset_code == proof.asset_code
        and reference.security_id == proof.security_id
        and reference.source_record_id == evidence.source_record_id
        and reference.raw_payload_hash == proof.source_reference_hash
        and reference.clock_evidence_mode == "policy_bounded_timestamp_snapshot"
    )
    if len(references) != 1:
        return False
    if (
        policy.scope != "simulation_only"
        or proof.scope != "simulation_only"
        or proof.clock_evidence_mode != "policy_bounded_timestamp_snapshot"
        or proof.account_id != account_id
        or proof.profile_key != policy.profile_key
        or proof.profile_version != policy.profile_version
        or proof.profile_content_hash != policy.profile_content_hash
        or proof.policy_snapshot_id != policy.snapshot_id
        or proof.policy_snapshot_hash != policy.snapshot_hash
        or proof.policy_content_sha256 != policy.normalized_config_sha256
        or proof.policy_known_at != policy.known_at
        or proof.policy_effective_at != policy.effective_at
        or proof.as_of != policy.as_of
        or proof.as_of != evidence.decision_cutoff
        or proof.business_date != policy.business_date
        or proof.execution_session != policy.business_date
        or proof.business_timezone_name != timezone_name
        or proof.source_id != evidence.source_id
        or proof.source_record_id != evidence.source_record_id
        or proof.original_body_sha256 != evidence.original_payload_sha256
        or proof.observed_at != evidence.observed_at
        or proof.known_at != evidence.known_at
        or proof.source_max_timestamp_age_seconds != policy.source_max_timestamp_age_seconds
        or proof.source_available_at is not None
        or proof.source_valid_until is not None
        or evidence.available_at is not None
        or evidence.valid_until is not None
        or evidence.observation_precision is not SourceObservationPrecision.TIMESTAMP
        or evidence.observed_on is not None
        or evidence.must_not_use_for_decision
        or evidence.known_at is None
        or proof.proven_available_at > evidence.known_at
        or proof.observed_at > proof.proven_available_at
    ):
        return False
    if proof.source_kind == "valuation":
        source_purpose = policy.industry_policy.requested_purpose
        if (
            requested_purpose != source_purpose
            or proof.valuation_quantity_unit is None
            or proof.valuation_price_unit != policy.ledger_money_unit
            or proof.capacity_window_kind is not None
        ):
            return False
        allowed_precisions = policy.industry_policy.allowed_observation_precisions
        allowed_restrictions = policy.industry_policy.allowed_source_restrictions
    else:
        capacity = policy.capacity_policy
        if (
            proof.capacity_measure != capacity.measure
            or proof.capacity_policy_unit != capacity.unit
            or proof.capacity_window_kind != capacity.window_kind
            or proof.capacity_window_sessions != capacity.window_sessions
            or capacity.window_kind != "session_cumulative"
            or capacity.window_sessions != 1
            or capacity.capacity_basis != "session_total"
        ):
            return False
        allowed_precisions = capacity.allowed_observation_precisions
        allowed_restrictions = capacity.allowed_source_restrictions
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=requested_purpose,
        allowed_observation_precisions=allowed_precisions,
        as_of=policy.as_of,
        allowed_restrictions=allowed_restrictions,
        expected_source_kind=proof.source_kind,
    )
    if not qualification.eligible:
        return False
    try:
        market_window_deadline = datetime.combine(
            policy.business_date + timedelta(days=1), time.min, tzinfo=business_timezone
        ).astimezone(UTC)
        timestamp_age_deadline = proof.observed_at + timedelta(
            seconds=policy.source_max_timestamp_age_seconds
        )
        policy_deadlines = tuple(
            deadline.astimezone(UTC)
            for deadline in (
                policy.industry_policy.effective_until,
                policy.capacity_policy.effective_until,
            )
            if deadline is not None
        )
        expected_deadline = min((timestamp_age_deadline, market_window_deadline, *policy_deadlines))
        if (
            proof.timestamp_age_deadline != timestamp_age_deadline
            or proof.market_window_deadline != market_window_deadline
            or proof.policy_deadlines != policy_deadlines
            or proof.policy_acceptance_deadline != expected_deadline
        ):
            return False
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return False
    return proof.policy_acceptance_deadline > policy.as_of.astimezone(UTC)


__all__ = [
    "portfolio_risk_execution_deadline",
    "portfolio_risk_execution_deadline_for_evidence",
]
