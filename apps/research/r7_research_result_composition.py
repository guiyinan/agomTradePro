"""Production composition for persisted R7 calibration/analogy/path results."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError

from apps.research.application.r7_research_result_persistence import (
    AuthoritativeR7ResearchEvidenceGraphProvider,
    ExactR7ForecastObservationProvider,
    ExactR7HistoricalAnalogyProvider,
    ExactR7PathStudyProvider,
    GetExactR7ResearchResult,
    R7ResearchResultConflict,
    R7ResearchResultUnavailable,
    RegisterR7ResearchResult,
    RegisterR7ResearchResultCommand,
    materialize_persisted_r7_research_result,
)
from apps.research.domain.r7_research_result_persistence import PersistedR7ResearchResult
from apps.research.infrastructure.r7_research_result_repository import (
    DjangoR7ResearchEvidenceGraphProvider,
    DjangoR7ResearchResultClock,
    DjangoR7ResearchResultRepository,
    DjangoR7SamplePolicyRecordIdentityProvider,
    R7ResearchResultClock,
    _DjangoR7ResearchResultStore,
)


class _R7ResearchResultRegistrationWriter:
    """Private ID-only writer that rereads every owner inside one UoW."""

    def __init__(
        self,
        *,
        policy_provider: DjangoR7SamplePolicyRecordIdentityProvider,
        evidence_provider: DjangoR7ResearchEvidenceGraphProvider,
        store: _DjangoR7ResearchResultStore,
        clock: R7ResearchResultClock,
    ) -> None:
        keys = {
            policy_provider.unit_of_work_key,
            evidence_provider.unit_of_work_key,
            store.unit_of_work_key,
        }
        if len(keys) != 1:
            raise ValueError("R7 result persistence uses different units of work")
        self._policy_provider = policy_provider
        self._evidence_provider = evidence_provider
        self._store = store
        self._clock = clock

    def register(
        self,
        command: RegisterR7ResearchResultCommand,
    ) -> PersistedR7ResearchResult:
        """Resolve IDs, recompute research outputs, and append atomically."""

        try:
            with self._store.atomic():
                recorded_at = self._clock.now()
                if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
                    raise ValueError("R7 result server clock must be timezone-aware")
                if command.as_of > recorded_at:
                    raise R7ResearchResultUnavailable("future R7 result cutoff")
                policy_record = self._policy_provider.get_exact_by_identity(
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    as_of=command.as_of,
                )
                if policy_record is None:
                    raise R7ResearchResultUnavailable(
                        "exact persisted approved R7 sample policy is unavailable"
                    )
                if (
                    policy_record.policy_id != command.policy_id
                    or policy_record.policy_version != command.policy_version
                ):
                    raise ValueError("R7 result policy substitution")
                evidence_graph = self._evidence_provider.get_exact_graph(
                    policy_record=policy_record,
                    evaluated_at=command.as_of,
                )
                result = materialize_persisted_r7_research_result(
                    result_id=command.result_id,
                    result_version=command.result_version,
                    policy_record=policy_record,
                    evidence_graph=evidence_graph,
                    evaluated_at=command.as_of,
                    recorded_at=recorded_at,
                )
                return self._store.append(result)
        except IntegrityError as exc:
            raise R7ResearchResultConflict("R7 research result race lost") from exc


class _UnavailableR7ResearchResultRegistrationFacade:
    """State-free production writer surface while canonical owners are absent."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterR7ResearchResultCommand,
    ) -> PersistedR7ResearchResult:
        """Validate the ID-only command and fail before any repository is built."""

        try:
            if type(command) is not RegisterR7ResearchResultCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7ResearchResultUnavailable(
                "R7 research result registration command is invalid"
            ) from error
        raise R7ResearchResultUnavailable(
            "R7 research result canonical owner providers are unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR7ResearchResultRuntime:
    """Production-safe inert registration plus an exact read-only query."""

    register: _UnavailableR7ResearchResultRegistrationFacade
    get_exact: GetExactR7ResearchResult


@dataclass(frozen=True, slots=True)
class _DjangoR7ResearchResultTestRuntime:
    """Private injectable runtime used by persistence component tests."""

    register: RegisterR7ResearchResult
    get_exact: GetExactR7ResearchResult
    repository: DjangoR7ResearchResultRepository


def build_django_r7_research_result_runtime(
    *,
    using: str = "default",
) -> DjangoR7ResearchResultRuntime:
    """Build an inert writer and a read-only exact query with no caller owner ports."""

    repository = DjangoR7ResearchResultRepository(using=using)
    return DjangoR7ResearchResultRuntime(
        register=_UnavailableR7ResearchResultRegistrationFacade(),
        get_exact=GetExactR7ResearchResult(repository),
    )


def _build_django_r7_research_result_test_runtime(
    *,
    forecast_provider: ExactR7ForecastObservationProvider,
    historical_analogy_provider: ExactR7HistoricalAnalogyProvider,
    path_study_provider: ExactR7PathStudyProvider,
    using: str = "default",
    clock: R7ResearchResultClock | None = None,
) -> _DjangoR7ResearchResultTestRuntime:
    """Build the private injectable runtime used by component tests."""

    authoritative_clock = clock or DjangoR7ResearchResultClock()
    store = _DjangoR7ResearchResultStore(using=using)
    repository = DjangoR7ResearchResultRepository(
        using=using,
        clock=authoritative_clock,
    )
    policy_provider = DjangoR7SamplePolicyRecordIdentityProvider(
        using=using,
        clock=authoritative_clock,
    )
    source = AuthoritativeR7ResearchEvidenceGraphProvider(
        forecast_provider=forecast_provider,
        historical_analogy_provider=historical_analogy_provider,
        path_study_provider=path_study_provider,
    )
    evidence_provider = DjangoR7ResearchEvidenceGraphProvider(source)
    keys = {
        repository.unit_of_work_key,
        policy_provider.unit_of_work_key,
        evidence_provider.unit_of_work_key,
        store.unit_of_work_key,
    }
    if len(keys) != 1:
        raise ValueError("R7 result runtime requires one shared unit of work")
    writer = _R7ResearchResultRegistrationWriter(
        policy_provider=policy_provider,
        evidence_provider=evidence_provider,
        store=store,
        clock=authoritative_clock,
    )
    return _DjangoR7ResearchResultTestRuntime(
        register=RegisterR7ResearchResult(writer),
        get_exact=GetExactR7ResearchResult(repository),
        repository=repository,
    )


__all__ = [
    "DjangoR7ResearchResultRuntime",
    "build_django_r7_research_result_runtime",
]
