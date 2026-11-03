"""Execution-proof deadlines derived from exact portfolio-risk source clocks."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, tzinfo

from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyBundle
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
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


__all__ = ["portfolio_risk_execution_deadline"]
