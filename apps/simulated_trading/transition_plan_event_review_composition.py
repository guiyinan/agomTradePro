"""Revalidate an event-bound plan against current official policy and durable facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta

from django.db import DatabaseError
from django.utils import timezone

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
from apps.simulated_trading.application.corporate_action_official_window_evidence import (
    CorporateActionCurrentOfficialWindowClock,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    DISCLOSURE_COVERAGE_POLICY_KEY,
    ConfigCenterDisclosurePolicyEvidenceReader,
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    DisclosurePolicyEvidenceReader,
    RuntimeDisclosurePolicyEvidence,
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
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

_MAXIMUM_LEASE = timedelta(seconds=60)


class _ServerClock:
    """Keep completion clocks independent of caller-provided plan timestamps."""

    def now(self) -> datetime:
        """Return the actual aware server clock."""
        return timezone.now()


class _CurrentOptionalPolicyEvidenceReader:
    """Distinguish a proved absent optional M1 feature from unavailable runtime evidence."""

    def read_active_evidence(
        self, *, runtime_environment: str, definition_key: str, as_of: datetime
    ) -> RuntimeDisclosurePolicyEvidence | None:
        """Keep original active snapshot facts; never manufacture an enabled/disabled value."""
        original = ConfigCenterDisclosurePolicyEvidenceReader().read_active_evidence(
            runtime_environment=runtime_environment, definition_key=definition_key, as_of=as_of
        )
        if original is not None:
            return original
        if definition_key != DISCLOSURE_COVERAGE_POLICY_KEY:
            return None
        profile = get_active_runtime_profile(runtime_environment)
        if not isinstance(profile, RuntimeConfigProfileRead):
            return None
        snapshot = get_latest_runtime_snapshot(profile.profile_key)
        if (
            not isinstance(snapshot, RuntimeConfigSnapshotRead)
            or definition_key in snapshot.resolved_values
        ):
            return None
        value = get_active_runtime_value(
            environment=runtime_environment, definition_key=definition_key, as_of=as_of
        )
        final_profile = get_active_runtime_profile(runtime_environment)
        final_snapshot = get_latest_runtime_snapshot(profile.profile_key)
        if value is not None or final_profile != profile or final_snapshot != snapshot:
            return None
        return RuntimeDisclosurePolicyEvidence(
            runtime_environment, definition_key, None, profile, snapshot, as_of
        )


class ConfiguredTransitionPlanEventReviewValidator:
    """Check active policy provenance before reading the exact DB event snapshots."""

    def __init__(
        self,
        *,
        origin_reader: VerifiedOriginCalendarReader,
        policy_reader: OfficialDisclosurePolicyReader,
        snapshot_reader: TransitionPlanEventSnapshotReader,
        runtime_environment: str,
        policy_evidence_reader: DisclosurePolicyEvidenceReader | None = None,
        classification_reader: CurrentReferenceClassificationReader | None = None,
        clock: CorporateActionCurrentOfficialWindowClock | None = None,
    ) -> None:
        """Bind current policy/classification evidence and database-only event readers."""

        if (
            not callable(getattr(origin_reader, "read_verified_zero_origin_calendar", None))
            or not callable(getattr(policy_reader, "read_policy", None))
            or not callable(getattr(snapshot_reader, "read_latest_snapshot", None))
            or (
                policy_evidence_reader is not None
                and not callable(getattr(policy_evidence_reader, "read_active_evidence", None))
            )
            or (
                classification_reader is not None
                and not callable(
                    getattr(
                        classification_reader, "resolve_simulated_instrument_classification", None
                    )
                )
            )
            or type(runtime_environment) is not str
            or not runtime_environment
        ):
            raise ValueError("event review dependencies are invalid")
        self._origin_reader = origin_reader
        self._policy_reader = policy_reader
        self._snapshot_reader = snapshot_reader
        self._runtime_environment = runtime_environment
        self._policy_evidence_reader = (
            _CurrentOptionalPolicyEvidenceReader()
            if policy_evidence_reader is None
            else policy_evidence_reader
        )
        self._classification_reader = classification_reader
        self._clock = clock if clock is not None else _ServerClock()

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Block changed source, window, timezone, lease, or proof at action time."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            return _blocked("EVENT_REVIEW_CUTOFF_INVALID")
        if not has_transition_plan_event_bindings(revision.basis.source_bindings):
            try:
                return self._assess_unpinned_fenced(revision, as_of=as_of)
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

    def _assess_unpinned_fenced(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Recheck complete configuration and classification after I/O and at actual completion."""
        evidence = self._policy_evidence_reader.read_active_evidence(
            runtime_environment=self._runtime_environment,
            definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
            as_of=as_of,
        )
        if (
            not _valid_policy_evidence(
                evidence, as_of=as_of, runtime_environment=self._runtime_environment
            )
            or evidence is None
        ):
            return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
        original_identity = _evidence_identity(evidence)
        classifications: list[SimulatedInstrumentClassificationEvidenceV1] = []
        result = self._assess_unpinned_revision(
            revision, as_of=as_of, evidence=evidence, classifications=classifications
        )
        reread_at = self._clock.now()
        if not _aware_not_after(as_of, reread_at) or reread_at >= revision.identity.valid_until:
            return _blocked("EVENT_REVIEW_COMPLETION_CLOCK_INVALID")
        for original in classifications:
            if self._classification_reader is None:
                return _blocked("EVENT_CLASSIFICATION_UNAVAILABLE")
            identity = original.identity_evidence
            current = self._classification_reader.resolve_simulated_instrument_classification(
                security_id=identity.security_id, asset_code=identity.asset_code, as_of=reread_at
            )
            if (
                not _valid_classification(
                    current,
                    asset_code=identity.asset_code,
                    security_id=identity.security_id,
                    as_of=reread_at,
                )
                or current is None
                or not _same_classification(original, current)
            ):
                return _blocked("EVENT_CLASSIFICATION_CHANGED_DURING_READ")
        policy_read_at = self._clock.now()
        if not _aware_not_after(reread_at, policy_read_at):
            return _blocked("EVENT_REVIEW_COMPLETION_CLOCK_INVALID")
        final = self._policy_evidence_reader.read_active_evidence(
            runtime_environment=self._runtime_environment,
            definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
            as_of=policy_read_at,
        )
        if (
            not _valid_policy_evidence(
                final, as_of=policy_read_at, runtime_environment=self._runtime_environment
            )
            or final is None
            or _evidence_identity(final) != original_identity
        ):
            return _blocked("EVENT_CURRENT_POLICY_CHANGED_DURING_READ")
        completed = self._clock.now()
        if (
            not _aware_not_after(policy_read_at, completed)
            or completed >= revision.identity.valid_until
        ):
            return _blocked("EVENT_REVIEW_COMPLETION_CLOCK_INVALID")
        for original in classifications:
            original.validate_at(as_of=completed)
        return result

    def _assess_unpinned_revision(
        self,
        revision: TransitionPlanRevision,
        *,
        as_of: datetime,
        evidence: RuntimeDisclosurePolicyEvidence,
        classifications: list[SimulatedInstrumentClassificationEvidenceV1],
    ) -> TransitionPlanEventReviewAssessment:
        """Review a legacy plan from current Config Center and classification evidence."""

        if evidence is None or not _valid_policy_evidence(
            evidence,
            as_of=as_of,
            runtime_environment=self._runtime_environment,
        ):
            return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
        value = evidence.value
        if (
            value is None
            and DISCLOSURE_COVERAGE_POLICY_KEY not in evidence.snapshot.resolved_values
        ):
            # Preserve the existing optional M1 contract only when a complete
            # current snapshot actually proves absence. This grants no source,
            # decision or trading authority and is fenced again before return.
            return _unchanged()
        if type(value) is not dict or type(value.get("enabled")) is not bool:
            return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
        if value["enabled"] is False:
            return _unchanged()
        if self._classification_reader is None:
            return _blocked("EVENT_CLASSIFICATION_UNAVAILABLE")
        identities = _revision_asset_identities(revision)
        if not identities:
            return _blocked("EVENT_CLASSIFICATION_SCOPE_UNAVAILABLE")
        affected_scope = False
        classification_changed = False
        for asset_code, security_id in identities:
            classification = (
                self._classification_reader.resolve_simulated_instrument_classification(
                    security_id=security_id,
                    asset_code=asset_code,
                    as_of=as_of,
                )
            )
            if classification is None or not _valid_classification(
                classification,
                asset_code=asset_code,
                security_id=security_id,
                as_of=as_of,
            ):
                return _blocked("EVENT_CLASSIFICATION_UNAVAILABLE")
            scope = _classification_scope(classification)
            classifications.append(classification)
            if scope == "unsupported":
                return _blocked("EVENT_SOURCE_UNSUPPORTED_MARKET")
            if scope == "szse_security":
                affected_scope = True
            for order in revision.orders:
                if (order.asset_code, order.security_id) == (asset_code, security_id):
                    # Full original selector/source pins are independently
                    # checked by JourneyCurrentPolicyPinsValidator. The new
                    # event gate compares the business type, not read-clock hashes.
                    if order.asset_type != classification.simulated_asset_type:
                        classification_changed = True
        if classification_changed:
            return TransitionPlanEventReviewAssessment(
                state=TransitionPlanEventReviewState.REVIEW_REQUIRED,
                reason_code="EVENT_CLASSIFICATION_CHANGED",
            )
        if not affected_scope:
            return _unchanged()
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
        if (
            policy is None
            or not _valid_policy(
                policy,
                calendar=calendar,
                as_of=as_of,
                runtime_environment=self._runtime_environment,
            )
            or not _policy_matches_evidence(policy, evidence)
        ):
            return _blocked("EVENT_CURRENT_POLICY_UNAVAILABLE")
        return TransitionPlanEventReviewAssessment(
            state=TransitionPlanEventReviewState.REVIEW_REQUIRED,
            reason_code="EVENT_COVERAGE_PIN_MISSING",
        )


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
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=runtime_environment
        ),
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


def _unchanged() -> TransitionPlanEventReviewAssessment:
    """Return the stable no-change result only after current evidence proves no scope."""

    return TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.UNCHANGED,
        reason_code="EVENTS_UNCHANGED",
    )


def _valid_policy_evidence(
    value: RuntimeDisclosurePolicyEvidence | None,
    *,
    as_of: datetime,
    runtime_environment: str,
) -> bool:
    """Require one active, time-valid Config Center profile and resolved snapshot."""

    if type(value) is not RuntimeDisclosurePolicyEvidence:
        return False
    profile = value.profile
    snapshot = value.snapshot
    if (
        value.runtime_environment != runtime_environment
        or value.definition_key != DISCLOSURE_COVERAGE_POLICY_KEY
        or value.read_at != as_of
        or not isinstance(profile, RuntimeConfigProfileRead)
        or not isinstance(snapshot, RuntimeConfigSnapshotRead)
    ):
        return False
    profile.__post_init__()
    snapshot.__post_init__()
    activated_at = profile.activated_at
    effective_at = snapshot.effective_from
    return (
        profile.environment == runtime_environment
        and profile.status == "active"
        and bool(profile.profile_id)
        and bool(profile.profile_key)
        and type(profile.version) is int
        and profile.version > 0
        and _is_sha256(profile.content_hash)
        and _aware_not_after(profile.created_at, as_of)
        and activated_at is not None
        and _aware_not_after(activated_at, as_of)
        and bool(snapshot.snapshot_id)
        and _is_sha256(snapshot.snapshot_hash)
        and _aware_not_after(snapshot.generated_at, as_of)
        and effective_at is not None
        and _aware_not_after(effective_at, as_of)
        and (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        == (profile.profile_id, profile.profile_key, profile.version)
        and effective_at == activated_at
        and profile.created_at <= activated_at <= snapshot.generated_at
        and isinstance(snapshot.resolved_values, Mapping)
        and snapshot.resolved_values.get(DISCLOSURE_COVERAGE_POLICY_KEY) == value.value
        and snapshot.snapshot_hash == _public_snapshot_hash(snapshot.resolved_values)
    )


def _policy_matches_evidence(
    policy: TransitionPlanDisclosureRuntimePolicy,
    evidence: RuntimeDisclosurePolicyEvidence,
) -> bool:
    """Bind the configured policy to the same active profile and snapshot read."""

    profile = evidence.profile
    snapshot = evidence.snapshot
    return (
        policy.runtime_environment == evidence.runtime_environment
        and policy.profile_id == profile.profile_id
        and policy.profile_key == profile.profile_key
        and policy.profile_version == profile.version
        and policy.profile_content_hash == profile.content_hash
        and policy.snapshot_id == snapshot.snapshot_id
        and policy.snapshot_content_hash == snapshot.snapshot_hash
        and policy.known_at == profile.created_at
        and policy.effective_at == snapshot.effective_from
        and policy.read_at == evidence.read_at
        and type(evidence.value) is dict
        and policy.policy_version == evidence.value.get("policy_version")
    )


def _revision_asset_identities(
    revision: TransitionPlanRevision,
) -> tuple[tuple[str, str], ...]:
    """Collect one exact, non-conflicting asset/security identity set from the revision."""

    identity_pairs = tuple(
        (item.asset_code, item.security_id)
        for item in (
            *revision.basis.current_positions,
            *revision.basis.target_positions,
        )
    ) + tuple((item.asset_code, item.security_id) for item in revision.orders)
    by_asset: dict[str, str] = {}
    by_security: dict[str, str] = {}
    for asset_code, security_id in identity_pairs:
        existing_security = by_asset.get(asset_code)
        existing_asset = by_security.get(security_id)
        if (existing_security is not None and existing_security != security_id) or (
            existing_asset is not None and existing_asset != asset_code
        ):
            return ()
        by_asset[asset_code] = security_id
        by_security[security_id] = asset_code
    return tuple(sorted(by_asset.items()))


def _valid_classification(
    value: SimulatedInstrumentClassificationEvidenceV1 | None,
    *,
    asset_code: str,
    security_id: str,
    as_of: datetime,
) -> bool:
    """Require typed current classification for the exact security and asset code."""

    if type(value) is not SimulatedInstrumentClassificationEvidenceV1:
        return False
    value.validate_at(as_of=as_of)
    return (
        value.read_at == as_of
        and value.identity_evidence.asset_code == asset_code
        and value.identity_evidence.security_id == security_id
    )


def _classification_scope(value: SimulatedInstrumentClassificationEvidenceV1) -> str:
    """Recognize only supported SZSE equities and explicit known US classifications."""

    identity = value.identity_evidence
    if identity.source_exchange == "SZSE" and identity.rule_market == "SZ":
        return "szse_security"
    if identity.source_exchange in {"NYSE", "NASDAQ"}:
        return "unrelated_us"
    return "unsupported"


def _aware_not_after(value: datetime, cutoff: datetime) -> bool:
    """Check that one Config Center clock is timezone-aware and known by the cutoff."""

    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value <= cutoff
    )


def _is_sha256(value: object) -> bool:
    """Validate a bare lowercase SHA-256 value from the public Config Center contract."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _public_snapshot_hash(values: Mapping[str, object]) -> str:
    """Verify the complete public Config Center projection, not merely a nonempty hash."""
    return hashlib.sha256(
        json.dumps(
            dict(values), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _evidence_identity(value: RuntimeDisclosurePolicyEvidence) -> str:
    """Freeze original profile/snapshot/value identity independently of mutable maps or read clocks."""
    payload = {
        "environment": value.runtime_environment,
        "definition_key": value.definition_key,
        "value": value.value,
        "profile_id": value.profile.profile_id,
        "profile_key": value.profile.profile_key,
        "profile_version": value.profile.version,
        "profile_hash": value.profile.content_hash,
        "profile_created_at": value.profile.created_at.isoformat(),
        "profile_activated_at": (
            value.profile.activated_at.isoformat() if value.profile.activated_at else None
        ),
        "snapshot_id": value.snapshot.snapshot_id,
        "snapshot_hash": value.snapshot.snapshot_hash,
        "snapshot_generated_at": value.snapshot.generated_at.isoformat(),
        "snapshot_effective_from": (
            value.snapshot.effective_from.isoformat() if value.snapshot.effective_from else None
        ),
    }
    return _public_snapshot_hash(payload)


def _same_classification(
    original: SimulatedInstrumentClassificationEvidenceV1,
    current: SimulatedInstrumentClassificationEvidenceV1,
) -> bool:
    """Ignore only the two read clocks, retaining every original source and profile pin."""
    identity = replace(
        original.identity_evidence,
        selection=replace(
            original.identity_evidence.selection,
            selected_at=current.identity_evidence.selection.selected_at,
        ),
    )
    comparable = replace(original, identity_evidence=identity, read_at=current.read_at)
    return comparable.to_payload() == current.to_payload()


__all__ = (
    "ConfiguredTransitionPlanEventReviewValidator",
    "build_configured_transition_plan_event_review_validator",
)
