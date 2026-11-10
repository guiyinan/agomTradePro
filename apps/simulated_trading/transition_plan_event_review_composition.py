"""Revalidate an event-bound plan against current official policy and durable facts."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db import DatabaseError

from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    make_security_disclosure_listing_coverage_reader,
)
from apps.portfolio.application.transition_plan_event_review import (
    AssessTransitionPlanEventReview,
    TransitionPlanEventSnapshotReader,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
    has_transition_plan_event_bindings,
    transition_plan_event_coverage_bindings,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.transition_plan_event_coverage_adapter import (
    DataCenterTransitionPlanEventSnapshotReader,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    OfficialDisclosurePolicyReader,
    VerifiedOriginCalendarReader,
    transition_plan_disclosure_fingerprint,
)
from core.exceptions import AgomTradeProException

_MAXIMUM_LEASE = timedelta(seconds=60)


class ConfiguredTransitionPlanEventReviewValidator:
    """Check active policy provenance before reading the exact DB event snapshots."""

    def __init__(
        self,
        *,
        origin_reader: VerifiedOriginCalendarReader,
        policy_reader: OfficialDisclosurePolicyReader,
        snapshot_reader: TransitionPlanEventSnapshotReader,
        runtime_environment: str,
    ) -> None:
        """Bind database-only readers; no official HTTP capture belongs in this gate."""

        if (
            not callable(getattr(origin_reader, "read_verified_zero_origin_calendar", None))
            or not callable(getattr(policy_reader, "read_policy", None))
            or not callable(getattr(snapshot_reader, "read_latest_snapshot", None))
            or type(runtime_environment) is not str
            or not runtime_environment
        ):
            raise ValueError("event review dependencies are invalid")
        self._origin_reader = origin_reader
        self._policy_reader = policy_reader
        self._snapshot_reader = snapshot_reader
        self._runtime_environment = runtime_environment

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Block changed source, window, timezone, lease, or proof at action time."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            return _blocked("EVENT_REVIEW_CUTOFF_INVALID")
        if not has_transition_plan_event_bindings(revision.basis.source_bindings):
            return TransitionPlanEventReviewAssessment(
                state=TransitionPlanEventReviewState.UNCHANGED,
                reason_code="EVENTS_UNCHANGED",
            )
        try:
            request_scope = RebalanceJourneyEventRequestScope(
                actor_user_id=revision.basis.requested_by_user_id,
                account_id=revision.identity.account_id,
                owner_user_id=revision.identity.owner_user_id,
            )
            calendar = self._origin_reader.read_verified_zero_origin_calendar(
                account_id=request_scope.account_id,
                owner_user_id=request_scope.owner_user_id,
                exchange="SZSE",
                as_of=as_of,
            )
            if not _valid_calendar(calendar, as_of=as_of):
                return _blocked("EVENT_ORIGIN_POLICY_UNAVAILABLE")
            policy = self._policy_reader.read_policy(
                decision_on=calendar.decision_on,
                earliest_required_on=calendar.origin_on,
                as_of=as_of,
            )
            if not _valid_policy(
                policy,
                calendar=calendar,
                as_of=as_of,
                runtime_environment=self._runtime_environment,
            ):
                return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
            if policy is None:
                return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
            fingerprint = transition_plan_disclosure_fingerprint(
                request_scope=request_scope,
                calendar=calendar,
                policy=policy,
            )
            markers = transition_plan_event_coverage_bindings(revision.basis.source_bindings)
            if not markers or any(
                marker.source_id != policy.source_id
                or marker.coverage_start_on != policy.start_on
                or marker.coverage_end_on != policy.end_on
                or marker.coverage_policy_version != fingerprint
                for marker in markers
            ):
                return _blocked("EVENT_CURRENT_POLICY_CHANGED")
            lease_policy = TransitionPlanEventCoverageLeasePolicy(
                policy_version=fingerprint,
                ttl=policy.lease_policy.ttl,
                maximum_ttl=policy.lease_policy.maximum_ttl,
            )
            return AssessTransitionPlanEventReview(
                reader=self._snapshot_reader,
                lease_policy=lease_policy,
            ).assess(revision, as_of=as_of)
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            DatabaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return _blocked("EVENT_REVIEW_EVIDENCE_UNAVAILABLE")


def build_configured_transition_plan_event_review_validator(
    *, runtime_environment: str, using: str = "default"
) -> ConfiguredTransitionPlanEventReviewValidator:
    """Compose current account policy and Data Center latest-to-exact DB readers."""

    return ConfiguredTransitionPlanEventReviewValidator(
        origin_reader=build_corporate_action_ownership_history_repository(
            runtime_environment=runtime_environment,
            using=using,
        ),
        policy_reader=ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
            runtime_environment=runtime_environment,
        ),
        snapshot_reader=DataCenterTransitionPlanEventSnapshotReader(
            query_use_case=make_security_disclosure_listing_coverage_reader(using=using),
            event_query_use_case=make_security_disclosure_event_reader(using=using),
        ),
        runtime_environment=runtime_environment,
    )


def _valid_calendar(value: VerifiedSimulatedAccountOriginCalendar, *, as_of: datetime) -> bool:
    """Require one verified account origin and current SZSE decision date."""

    return (
        type(value) is VerifiedSimulatedAccountOriginCalendar
        and value.as_of == as_of
        and type(value.origin_on) is date
        and type(value.decision_on) is date
        and value.origin_on <= value.decision_on
        and type(value.timezone_policy) is QualifiedExchangeTimezone
        and value.timezone_policy.exchange == "SZSE"
        and bool(value.timezone_policy.policy_id)
        and len(value.timezone_policy.policy_sha256) == 64
    )


def _valid_policy(
    value: TransitionPlanDisclosureRuntimePolicy | None,
    *,
    calendar: VerifiedSimulatedAccountOriginCalendar,
    as_of: datetime,
    runtime_environment: str,
) -> bool:
    """Require the exact current window and bounded lease from one active profile."""

    if type(value) is not TransitionPlanDisclosureRuntimePolicy:
        return False
    lease = value.lease_policy
    return (
        value.runtime_environment == runtime_environment
        and value.source_id == "szse_official"
        and value.read_at == as_of
        and value.start_on <= calendar.origin_on <= calendar.decision_on
        and value.end_on == calendar.decision_on
        and value.policy_version == lease.policy_version
        and timedelta(0) < lease.ttl <= lease.maximum_ttl <= _MAXIMUM_LEASE
    )


def _blocked(reason_code: str) -> TransitionPlanEventReviewAssessment:
    """Return one stable fail-closed review state."""

    return TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.BLOCKED,
        reason_code=reason_code,
    )


__all__ = (
    "ConfiguredTransitionPlanEventReviewValidator",
    "build_configured_transition_plan_event_review_validator",
)
