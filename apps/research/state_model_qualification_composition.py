"""Django composition root for persisted R6 qualification research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.application.state_model_qualification import (
    AssessStateModelQualificationCommand,
    AssessStateModelQualificationUseCase,
    QualificationAdvancedAssessmentProvider,
    QualificationBaselineShortfallProvider,
    QualificationCandidateProvider,
    StateModelComparativeStudyProvider,
    StateModelDerivedMetricBundleProvider,
    StateModelQualificationPolicyProvider,
    StateModelStudyPreregistrationProvider,
)
from apps.research.application.state_model_qualification_lifecycle import (
    ApplyR6QualificationLifecycle,
    GetActiveR6Qualification,
    R6QualificationAuthorizationRef,
    R6QualificationClock,
    R6QualificationLifecycleAuthorizationProvider,
    R6QualificationLifecycleRepository,
)
from apps.research.application.state_model_qualification_persistence import (
    GetExactR6QualificationAssessment,
    MonitorR6Qualification,
    RegisterR6QualificationAssessment,
    RegisterR6QualificationAssessmentCommand,
)
from apps.research.domain.advanced_state_model import AdvancedStateModelCandidateEvidence
from apps.research.domain.state_model_baseline import BaselineShortfallReport
from apps.research.domain.state_model_qualification import (
    AdvancedStateModelAssessmentAttestation,
    StateModelComparativeStudyEvidence,
    StateModelDerivedMetricBundle,
    StateModelQualificationAssessment,
    StateModelQualificationPolicy,
    StateModelStudyPreregistration,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
)
from apps.research.infrastructure.state_model_qualification_models import (
    _require_active_r6_qualification_uow,
)
from apps.research.infrastructure.state_model_qualification_repository import (
    DjangoR6QualificationClock,
    DjangoR6QualificationRepository,
    _DjangoR6QualificationStore,
)


class _R6QualificationAuthorizationSource(Protocol):
    """External owner port consumed only inside the Research UoW."""

    def get_exact(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
        qualification_ref: R6QualificationRef,
        action: R6QualificationLifecycleAction,
    ) -> R6QualificationPromotionAuthorization | None:
        """Return one exact human authorization or explicit absence."""


class _StudyOwnerGuard:
    def __init__(self, source: StateModelComparativeStudyProvider) -> None:
        self._source = source

    def get_study(
        self,
        study_id: str,
        *,
        as_of: datetime,
    ) -> StateModelComparativeStudyEvidence | None:
        _require_active_r6_qualification_uow()
        return self._source.get_study(study_id, as_of=as_of)


class _PreregistrationOwnerGuard:
    def __init__(self, source: StateModelStudyPreregistrationProvider) -> None:
        self._source = source

    def get_preregistration(
        self,
        registration_id: str,
        *,
        as_of: datetime,
    ) -> StateModelStudyPreregistration | None:
        _require_active_r6_qualification_uow()
        return self._source.get_preregistration(registration_id, as_of=as_of)


class _CandidateOwnerGuard:
    def __init__(self, source: QualificationCandidateProvider) -> None:
        self._source = source

    def get_candidate(
        self,
        candidate_id: str,
        candidate_version: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelCandidateEvidence | None:
        _require_active_r6_qualification_uow()
        return self._source.get_candidate(candidate_id, candidate_version, as_of=as_of)


class _AdvancedAssessmentOwnerGuard:
    def __init__(self, source: QualificationAdvancedAssessmentProvider) -> None:
        self._source = source

    def get_assessment(
        self,
        assessment_id: str,
        *,
        as_of: datetime,
    ) -> AdvancedStateModelAssessmentAttestation | None:
        _require_active_r6_qualification_uow()
        return self._source.get_assessment(assessment_id, as_of=as_of)


class _DerivedBundleOwnerGuard:
    def __init__(self, source: StateModelDerivedMetricBundleProvider) -> None:
        self._source = source

    def get_bundle(
        self,
        bundle_id: str,
        bundle_version: str,
        *,
        as_of: datetime,
    ) -> StateModelDerivedMetricBundle | None:
        _require_active_r6_qualification_uow()
        return self._source.get_bundle(bundle_id, bundle_version, as_of=as_of)


class _BaselineOwnerGuard:
    def __init__(self, source: QualificationBaselineShortfallProvider) -> None:
        self._source = source

    def get_report(
        self,
        *,
        specification_version: str,
        evaluation_id: str,
        as_of: datetime,
    ) -> BaselineShortfallReport | None:
        _require_active_r6_qualification_uow()
        return self._source.get_report(
            specification_version=specification_version,
            evaluation_id=evaluation_id,
            as_of=as_of,
        )


class _PolicyOwnerGuard:
    def __init__(self, source: StateModelQualificationPolicyProvider) -> None:
        self._source = source

    def get_policy(
        self,
        policy_version: str,
        *,
        as_of: datetime,
    ) -> StateModelQualificationPolicy | None:
        _require_active_r6_qualification_uow()
        return self._source.get_policy(policy_version, as_of=as_of)


class _HybridR6QualificationAuthorizationProvider:
    """Replay persisted authorizations first, then consult the owner port."""

    def __init__(
        self,
        *,
        source: _R6QualificationAuthorizationSource,
        repository: DjangoR6QualificationRepository,
    ) -> None:
        self._source = source
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
        qualification_ref: R6QualificationRef,
        action: R6QualificationLifecycleAction,
    ) -> R6QualificationPromotionAuthorization | None:
        _require_active_r6_qualification_uow()
        persisted = self._repository.get_exact_authorization(
            authorization_ref=authorization_ref,
            qualification_ref=qualification_ref,
            action=action,
        )
        if persisted is not None:
            return persisted
        authorization = self._source.get_exact(
            authorization_ref=authorization_ref,
            qualification_ref=qualification_ref,
            action=action,
        )
        if authorization is None:
            return None
        if (
            authorization.qualification_ref != qualification_ref
            or authorization.action is not action
        ):
            raise ValueError("R6 owner authorization substitution")
        return authorization


class _R6AssessmentWriter:
    def __init__(
        self,
        *,
        store: _DjangoR6QualificationStore,
        use_case: AssessStateModelQualificationUseCase,
    ) -> None:
        self._store = store
        self._use_case = use_case

    def register(
        self,
        command: RegisterR6QualificationAssessmentCommand,
    ) -> StateModelQualificationAssessment:
        _require_active_r6_qualification_uow()
        if command.assessed_at > self._store.server_now():
            raise ValueError("R6 qualification assessed_at cannot be in the future")
        assessment = self._use_case.execute(
            AssessStateModelQualificationCommand(
                study_id=command.study_id,
                assessed_at=command.assessed_at,
            )
        )
        return self._store.append_assessment(assessment)


def _owner_unit_of_work_key(source: object, default: str) -> str:
    """Read an optional owner UoW declaration without weakening old ports."""

    candidate = getattr(source, "unit_of_work_key", default)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError("R6 owner provider unit_of_work_key is invalid")
    return candidate


@dataclass(frozen=True)
class DjangoR6QualificationRuntime:
    """Application facades bound to one Django database/UoW."""

    register: RegisterR6QualificationAssessment
    get_exact: GetExactR6QualificationAssessment
    monitor: MonitorR6Qualification
    apply_lifecycle: ApplyR6QualificationLifecycle
    get_active: GetActiveR6Qualification


def build_django_r6_qualification_runtime(
    *,
    study_provider: StateModelComparativeStudyProvider,
    preregistration_provider: StateModelStudyPreregistrationProvider,
    candidate_provider: QualificationCandidateProvider,
    advanced_assessment_provider: QualificationAdvancedAssessmentProvider,
    derived_metric_bundle_provider: StateModelDerivedMetricBundleProvider,
    baseline_shortfall_provider: QualificationBaselineShortfallProvider,
    policy_provider: StateModelQualificationPolicyProvider,
    authorization_provider: R6QualificationLifecycleAuthorizationProvider,
    using: str = "default",
    clock: R6QualificationClock | None = None,
) -> DjangoR6QualificationRuntime:
    """Build Research-only registration, monitoring, and lifecycle facades."""

    authoritative_clock = clock or DjangoR6QualificationClock()
    repository = DjangoR6QualificationRepository(
        using=using,
        clock=authoritative_clock,
    )
    owner_sources = (
        study_provider,
        preregistration_provider,
        candidate_provider,
        advanced_assessment_provider,
        derived_metric_bundle_provider,
        baseline_shortfall_provider,
        policy_provider,
        authorization_provider,
    )
    keys = {
        repository.unit_of_work_key,
        *(_owner_unit_of_work_key(source, repository.unit_of_work_key) for source in owner_sources),
    }
    if len(keys) != 1:
        raise ValueError("R6 lifecycle owner and Research repository use different units of work")
    store = _DjangoR6QualificationStore(using=using, clock=authoritative_clock)
    use_case = AssessStateModelQualificationUseCase(
        study_provider=_StudyOwnerGuard(study_provider),
        preregistration_provider=_PreregistrationOwnerGuard(preregistration_provider),
        candidate_provider=_CandidateOwnerGuard(candidate_provider),
        advanced_assessment_provider=_AdvancedAssessmentOwnerGuard(advanced_assessment_provider),
        derived_metric_bundle_provider=_DerivedBundleOwnerGuard(derived_metric_bundle_provider),
        baseline_shortfall_provider=_BaselineOwnerGuard(baseline_shortfall_provider),
        policy_provider=_PolicyOwnerGuard(policy_provider),
    )
    writer = _R6AssessmentWriter(store=store, use_case=use_case)
    lifecycle_repository: R6QualificationLifecycleRepository = store
    lifecycle_authorization_provider = _HybridR6QualificationAuthorizationProvider(
        source=authorization_provider,
        repository=store,
    )
    return DjangoR6QualificationRuntime(
        register=RegisterR6QualificationAssessment(_RegistrationClosure(store, writer)),
        get_exact=GetExactR6QualificationAssessment(repository),
        monitor=MonitorR6Qualification(repository),
        apply_lifecycle=ApplyR6QualificationLifecycle(
            authorization_provider=lifecycle_authorization_provider,
            repository=lifecycle_repository,
        ),
        get_active=GetActiveR6Qualification(
            repository=lifecycle_repository,
            clock=authoritative_clock,
        ),
    )


class _RegistrationClosure:
    """Keep the append capability inside one repository-owned transaction."""

    def __init__(
        self,
        store: _DjangoR6QualificationStore,
        writer: _R6AssessmentWriter,
    ) -> None:
        self._store = store
        self._writer = writer

    def register(
        self,
        command: RegisterR6QualificationAssessmentCommand,
    ) -> StateModelQualificationAssessment:
        with self._store.atomic():
            return self._writer.register(command)


__all__ = [
    "DjangoR6QualificationRuntime",
    "build_django_r6_qualification_runtime",
]
