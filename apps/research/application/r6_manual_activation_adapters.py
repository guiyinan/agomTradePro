"""Exact read adapters for the R6 manual-activation preflight."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from apps.research.application.r6_manual_activation_preflight import (
    R6ManualActivationMonitoringProvider,
    R6ManualActivationQualificationProvider,
    R6ManualActivationScopeProvider,
    R6ManualActivationStateProvider,
)
from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
)
from apps.research.application.state_model_monitoring_persistence import (
    R6MonitoringPersistedAssessment,
)
from apps.research.domain.state_model_activation import (
    R6ActivationApprovalRef,
    R6ActivationScope,
    R6ActivationScopeRef,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationStatus,
    validate_r6_activation_scope,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessmentStatus,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R6 manual activation adapter UoW key must be an exact string")
    return value


class R6ActivationScopeSource(Protocol):
    """Future canonical owner query for an existing activation scope."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(self, *, scope_id: str, as_of: datetime) -> R6ActivationScope | None:
        """Return one exact owner-defined scope or explicit absence."""


class R6LatestActiveQualificationRefSource(Protocol):
    """Future canonical mapping from scope to its promoted qualification winner."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_latest_active_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> R6QualificationRef | None:
        """Select the active winner without accepting a caller reference."""


class R6ExactActiveQualificationQuery(Protocol):
    """Existing 0008 promotion/lifecycle exact projection reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Replay the exact promoted qualification at a PIT cutoff."""


class R6LatestCompleteMonitoringRepository(Protocol):
    """Read-only latest-period selector over the existing 0011 ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_latest_complete_for_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> R6MonitoringPersistedAssessment | None:
        """Return a unique latest complete graph or explicit absence."""


class R6ActivationStateRepository(Protocol):
    """Narrow read-only state derivation over the existing 0012 stream."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_active_approval_ref_for_scope(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> R6ActivationApprovalRef | None:
        """Return the replayed active stack head without exposing events."""


class R6ActivationScopeExactAdapter(R6ManualActivationScopeProvider):
    """Validate a scope returned by its future canonical owner."""

    def __init__(self, source: R6ActivationScopeSource) -> None:
        self._source = source
        _exact_uow_key(source.unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        """Return the live owner transaction identity."""

        return _exact_uow_key(self._source.unit_of_work_key)

    def get_exact(self, *, scope_id: str, as_of: datetime) -> R6ActivationScope | None:
        """Return only an exact, live-sealed owner scope."""

        value = self._source.get_exact(scope_id=scope_id, as_of=as_of)
        if value is None:
            return None
        if type(value) is not R6ActivationScope:
            raise TypeError("R6 activation scope owner returned another type")
        validate_r6_activation_scope(value)
        if value.scope_id != scope_id:
            raise ValueError("R6 activation scope owner substituted the requested scope")
        return value


class R6LatestActiveQualificationExactAdapter(R6ManualActivationQualificationProvider):
    """Resolve a server-selected ref through the exact 0008 promotion reader."""

    def __init__(
        self,
        *,
        ref_source: R6LatestActiveQualificationRefSource,
        exact_query: R6ExactActiveQualificationQuery,
    ) -> None:
        if _exact_uow_key(ref_source.unit_of_work_key) != _exact_uow_key(
            exact_query.unit_of_work_key
        ):
            raise ValueError("R6 qualification adapter uses different units of work")
        self._ref_source = ref_source
        self._exact_query = exact_query

    @property
    def unit_of_work_key(self) -> str:
        """Return the live common owner transaction identity."""

        source_key = _exact_uow_key(self._ref_source.unit_of_work_key)
        query_key = _exact_uow_key(self._exact_query.unit_of_work_key)
        if source_key != query_key:
            raise ValueError("R6 qualification adapter UoW changed")
        return source_key

    def get_latest_active(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Select the latest ref at the owner, then replay that exact promotion."""

        validate_r6_activation_scope(scope)
        qualification_ref = self._ref_source.get_latest_active_ref(
            scope=scope,
            as_of=as_of,
        )
        if qualification_ref is None:
            return None
        if type(qualification_ref) is not R6QualificationRef:
            raise TypeError("R6 qualification ref owner returned another type")
        R6QualificationRef.__post_init__(qualification_ref)
        evidence = self._exact_query.get_exact_active(
            qualification_ref=qualification_ref,
            as_of=as_of,
        )
        if evidence is None:
            return None
        if (
            type(evidence) is not ActiveR6QualificationEvidence
            or evidence.qualification_ref != qualification_ref
            or evidence.known_at > as_of
        ):
            raise ValueError("R6 active qualification exact reader substituted evidence")
        return evidence


class R6LatestCompleteMonitoringExactAdapter(R6ManualActivationMonitoringProvider):
    """Project the repository-selected latest complete 0011 assessment."""

    def __init__(self, repository: R6LatestCompleteMonitoringRepository) -> None:
        self._repository = repository
        _exact_uow_key(repository.unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        """Return the live monitoring-ledger transaction identity."""

        return _exact_uow_key(self._repository.unit_of_work_key)

    def get_latest_complete(
        self,
        *,
        scope: R6ActivationScope,
        qualification: ActiveR6QualificationEvidence,
        as_of: datetime,
    ) -> R6MonitoringActivationEvidence | None:
        """Return a safe activation projection from one fully restored graph."""

        validate_r6_activation_scope(scope)
        if type(qualification) is not ActiveR6QualificationEvidence:
            raise TypeError("R6 monitoring adapter qualification type differs")
        bundle = self._repository.get_latest_complete_for_active(
            qualification_ref=qualification.qualification_ref,
            as_of=as_of,
        )
        if bundle is None:
            return None
        if type(bundle) is not R6MonitoringPersistedAssessment:
            raise TypeError("R6 monitoring repository returned another type")
        assessment = bundle.assessment
        policy = bundle.policy
        if (
            bundle.assessment_ref.assessment_hash != assessment.content_hash
            or assessment.qualification_ref != qualification.qualification_ref
            or policy.qualification_ref != qualification.qualification_ref
            or policy.label_protocol_version != scope.label_protocol_version
            or assessment.status is R6MonitoringAssessmentStatus.BLOCKED
            or assessment.evaluated_at > bundle.recorded_at
            or bundle.recorded_at > as_of
        ):
            raise ValueError("R6 latest monitoring graph was substituted or incomplete")
        valid_until = min(
            policy.active_until,
            assessment.evaluated_at + timedelta(seconds=policy.maximum_observation_age_seconds),
        )
        if bundle.recorded_at >= valid_until or not bundle.recorded_at <= as_of < valid_until:
            return None
        return R6MonitoringActivationEvidence(
            assessment_id=bundle.assessment_ref.assessment_id,
            assessment_hash=bundle.assessment_ref.assessment_hash,
            qualification_ref=qualification.qualification_ref,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_hash=policy.content_hash,
            label_protocol_version=policy.label_protocol_version,
            label_set_hash=policy.expected_label_set_hash,
            status=R6MonitoringActivationStatus(assessment.status.value),
            evaluated_at=assessment.evaluated_at,
            recorded_at=bundle.recorded_at,
            valid_until=valid_until,
            owner="research",
            evidence_ref=(
                f"research:r6-monitoring-assessment:{bundle.assessment_ref.assessment_id}"
            ),
            retirement_review_required=assessment.retirement_review_required,
        )


class R6ActivationStateExactAdapter(R6ManualActivationStateProvider):
    """Derive only the 0012 active stack head for an exact owner scope."""

    def __init__(self, repository: R6ActivationStateRepository) -> None:
        self._repository = repository
        _exact_uow_key(repository.unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        """Return the live activation-ledger transaction identity."""

        return _exact_uow_key(self._repository.unit_of_work_key)

    def get_active_approval_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> R6ActivationApprovalRef | None:
        """Return the derived stack head without selecting an event at the caller."""

        validate_r6_activation_scope(scope)
        value = self._repository.get_active_approval_ref_for_scope(
            scope_ref=R6ActivationScopeRef.from_scope(scope),
            as_of=as_of,
        )
        if value is None:
            return None
        if type(value) is not R6ActivationApprovalRef:
            raise TypeError("R6 activation repository returned another active type")
        R6ActivationApprovalRef.__post_init__(value)
        return value


__all__ = [
    "R6ActivationScopeExactAdapter",
    "R6ActivationStateExactAdapter",
    "R6ExactActiveQualificationQuery",
    "R6LatestActiveQualificationExactAdapter",
    "R6LatestActiveQualificationRefSource",
    "R6LatestCompleteMonitoringExactAdapter",
]
