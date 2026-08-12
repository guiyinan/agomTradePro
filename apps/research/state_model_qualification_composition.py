"""Django composition root for persisted R6 qualification research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, Protocol

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
    ApplyR6QualificationLifecycleCommand,
    GetActiveR6Qualification,
    R6QualificationAuthorizationRef,
    R6QualificationClock,
    R6QualificationLifecycleAuthorizationProvider,
    R6QualificationLifecycleRepository,
)
from apps.research.application.state_model_qualification_persistence import (
    GetExactR6QualificationAssessment,
    MonitorR6Qualification,
    R6QualificationAuditPage,
    R6QualificationUnavailable,
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
    DjangoR6QualificationReadRepository,
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
        repository: _DjangoR6QualificationStore,
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


class UnavailableR6QualificationRegisterFacade:
    """Stateless production registration surface without owner or write authority."""

    __slots__ = ()

    def execute(self, command: RegisterR6QualificationAssessmentCommand) -> NoReturn:
        """Validate the ID-only command, then stop before database access."""

        try:
            if type(command) is not RegisterR6QualificationAssessmentCommand:
                raise TypeError("R6 qualification command type differs")
            RegisterR6QualificationAssessmentCommand.__post_init__(command)
            if (
                RegisterR6QualificationAssessmentCommand(
                    study_id=command.study_id,
                    assessed_at=command.assessed_at,
                )
                != command
            ):
                raise ValueError("R6 qualification command differs after replay")
        except (AttributeError, TypeError, ValueError) as error:
            raise R6QualificationUnavailable(
                "R6 qualification registration command is malformed"
            ) from error
        raise R6QualificationUnavailable(
            "canonical R6 qualification owner providers are unavailable"
        )


class UnavailableR6QualificationMonitorFacade:
    """Stateless production audit surface without a live-ledger capability."""

    __slots__ = ()

    def execute(
        self,
        *,
        as_of: datetime,
        cursor: str | None = None,
        limit: int = 50,
    ) -> R6QualificationAuditPage:
        """Validate a bounded audit request, then fail without reading the ledger."""

        if (
            type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or (cursor is not None and type(cursor) is not str)
            or type(limit) is not int
            or limit < 1
            or limit > 200
        ):
            raise R6QualificationUnavailable("R6 qualification monitor request is malformed")
        raise R6QualificationUnavailable("R6 qualification production monitor is unavailable")


class UnavailableR6QualificationLifecycleFacade:
    """Stateless production lifecycle surface without authorization or a writer."""

    __slots__ = ()

    def execute(self, command: ApplyR6QualificationLifecycleCommand) -> NoReturn:
        """Validate an ID-only lifecycle command, then fail without persistence access."""

        try:
            if type(command) is not ApplyR6QualificationLifecycleCommand:
                raise TypeError("R6 qualification lifecycle command type differs")
            if type(command.qualification_ref) is not R6QualificationRef:
                raise TypeError("R6 qualification lifecycle ref type differs")
            R6QualificationRef.__post_init__(command.qualification_ref)
            if type(command.action) is not R6QualificationLifecycleAction:
                raise TypeError("R6 qualification lifecycle action type differs")
            if type(command.authorization_ref) is not R6QualificationAuthorizationRef:
                raise TypeError("R6 qualification authorization ref type differs")
            R6QualificationAuthorizationRef.__post_init__(command.authorization_ref)
            if (
                ApplyR6QualificationLifecycleCommand(
                    qualification_ref=command.qualification_ref,
                    action=command.action,
                    authorization_ref=command.authorization_ref,
                )
                != command
            ):
                raise ValueError("R6 qualification lifecycle command differs after replay")
        except (AttributeError, TypeError, ValueError) as error:
            raise R6QualificationUnavailable(
                "R6 qualification lifecycle command is malformed"
            ) from error
        raise R6QualificationUnavailable(
            "canonical R6 qualification lifecycle owner providers are unavailable"
        )


class R6QualificationActiveExactReadFacade:
    """Narrow exact active reader over a repository with no write capability."""

    __slots__ = ("_repository",)

    def __init__(self, repository: DjangoR6QualificationReadRepository) -> None:
        if type(repository) is not DjangoR6QualificationReadRepository:
            raise TypeError("R6 qualification active reader requires the exact repository")
        self._repository = repository

    def get_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Return one exact active assessment or explicit absence."""

        return self._repository.get_active(
            qualification_ref=qualification_ref,
            as_of=as_of,
        )


@dataclass(frozen=True, slots=True)
class DjangoR6QualificationRuntime:
    """Public exact reads plus deliberately inert mutation and audit surfaces."""

    register: UnavailableR6QualificationRegisterFacade
    get_exact: GetExactR6QualificationAssessment
    monitor: UnavailableR6QualificationMonitorFacade
    apply_lifecycle: UnavailableR6QualificationLifecycleFacade
    get_active: R6QualificationActiveExactReadFacade


@dataclass(frozen=True, slots=True)
class _DjangoR6QualificationTestRuntime:
    """Private source-injected runtime proving the persistence contracts."""

    register: RegisterR6QualificationAssessment
    get_exact: GetExactR6QualificationAssessment
    monitor: MonitorR6Qualification
    apply_lifecycle: ApplyR6QualificationLifecycle
    get_active: GetActiveR6Qualification


def build_django_r6_qualification_runtime(
    *,
    using: str = "default",
) -> DjangoR6QualificationRuntime:
    """Build using-only exact reads without a writer, token, or clock object."""

    repository = DjangoR6QualificationReadRepository(using=using)
    return DjangoR6QualificationRuntime(
        register=UnavailableR6QualificationRegisterFacade(),
        get_exact=GetExactR6QualificationAssessment(repository),
        monitor=UnavailableR6QualificationMonitorFacade(),
        apply_lifecycle=UnavailableR6QualificationLifecycleFacade(),
        get_active=R6QualificationActiveExactReadFacade(repository),
    )


def _build_django_r6_qualification_test_runtime(
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
) -> _DjangoR6QualificationTestRuntime:
    """Build the source-injected success graph for isolated contract tests."""

    authoritative_clock = clock or DjangoR6QualificationClock()
    store = _DjangoR6QualificationStore(using=using, clock=authoritative_clock)
    read_repository = DjangoR6QualificationReadRepository(using=using)
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
        store.unit_of_work_key,
        *(_owner_unit_of_work_key(source, store.unit_of_work_key) for source in owner_sources),
    }
    if len(keys) != 1:
        raise ValueError("R6 lifecycle owner and Research repository use different units of work")
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
    return _DjangoR6QualificationTestRuntime(
        register=RegisterR6QualificationAssessment(_RegistrationClosure(store, writer)),
        get_exact=GetExactR6QualificationAssessment(read_repository),
        monitor=MonitorR6Qualification(store),
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
    "R6QualificationActiveExactReadFacade",
    "UnavailableR6QualificationLifecycleFacade",
    "UnavailableR6QualificationMonitorFacade",
    "UnavailableR6QualificationRegisterFacade",
    "build_django_r6_qualification_runtime",
]
