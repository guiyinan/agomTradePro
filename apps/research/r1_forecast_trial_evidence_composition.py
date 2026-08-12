"""Production-inert and private injectable composition for R1 trial evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.research.application.r1_forecast_trial_evidence import (
    R1ForecastBaselineEvidenceProvider,
    R1ForecastTrialDefinitionProvider,
    R1ForecastTrialEvidenceClock,
    R1ForecastTrialEvidenceUnavailable,
    RegisterR1ForecastTrialEvidence,
    RegisterR1ForecastTrialEvidenceCommand,
)
from apps.research.domain.r1_forecast_trial_evidence import (
    PersistedR1ForecastTrialEvidence,
)
from apps.research.infrastructure.r1_forecast_trial_evidence_repository import (
    DjangoR1ForecastTrialEvidenceClock,
    DjangoR1ForecastTrialEvidenceRepository,
    DjangoResearchTrialEvidenceProvider,
    _private_r1_forecast_trial_evidence_store,
)


class R1ForecastTrialRegistration(Protocol):
    """Narrow registration surface shared by inert and private runtimes."""

    def execute(
        self, command: RegisterR1ForecastTrialEvidenceCommand
    ) -> PersistedR1ForecastTrialEvidence:
        """Register one exact owner-backed receipt or fail stably."""


class _InertR1ForecastTrialRegistration:
    __slots__ = ()

    def execute(
        self, command: RegisterR1ForecastTrialEvidenceCommand
    ) -> PersistedR1ForecastTrialEvidence:
        """Keep production mutation inert until canonical owner adapters exist."""

        try:
            if type(command) is not RegisterR1ForecastTrialEvidenceCommand:
                raise TypeError
            RegisterR1ForecastTrialEvidenceCommand.__post_init__(command)
        except Exception as error:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial registration command is invalid"
            ) from error
        raise R1ForecastTrialEvidenceUnavailable(
            "R1 trial registration is production-inert without canonical owner providers"
        )


@dataclass(frozen=True)
class R1ForecastTrialEvidenceRuntime:
    """Public read path plus an explicitly inert registration surface."""

    repository: DjangoR1ForecastTrialEvidenceRepository
    equity_provider: DjangoResearchTrialEvidenceProvider
    registration: R1ForecastTrialRegistration


def build_r1_forecast_trial_evidence_runtime(
    *, using: str = "default"
) -> R1ForecastTrialEvidenceRuntime:
    """Build public exact reads without retaining any append capability."""

    clock = DjangoR1ForecastTrialEvidenceClock(using=using)
    repository = DjangoR1ForecastTrialEvidenceRepository(using=using, clock=clock)
    return R1ForecastTrialEvidenceRuntime(
        repository=repository,
        equity_provider=DjangoResearchTrialEvidenceProvider(repository),
        registration=_InertR1ForecastTrialRegistration(),
    )


def build_r1_forecast_trial_evidence_provider(
    *, using: str = "default"
) -> DjangoResearchTrialEvidenceProvider:
    """Build only the exact read provider for cross-app composition."""

    return build_r1_forecast_trial_evidence_runtime(using=using).equity_provider


def _build_private_r1_forecast_trial_evidence_runtime(
    *,
    definition_provider: R1ForecastTrialDefinitionProvider,
    baseline_provider: R1ForecastBaselineEvidenceProvider,
    using: str = "default",
    clock: R1ForecastTrialEvidenceClock | None = None,
) -> R1ForecastTrialEvidenceRuntime:
    """Build the injectable registration runtime reserved for synthetic tests."""

    trusted_clock = clock or DjangoR1ForecastTrialEvidenceClock(using=using)
    repository = DjangoR1ForecastTrialEvidenceRepository(
        using=using,
        clock=trusted_clock,
    )
    store = _private_r1_forecast_trial_evidence_store(using=using)
    registration = RegisterR1ForecastTrialEvidence(
        definition_provider=definition_provider,
        baseline_provider=baseline_provider,
        store=store,
        clock=trusted_clock,
    )
    return R1ForecastTrialEvidenceRuntime(
        repository=repository,
        equity_provider=DjangoResearchTrialEvidenceProvider(repository),
        registration=registration,
    )


__all__ = [
    "R1ForecastTrialEvidenceRuntime",
    "build_r1_forecast_trial_evidence_provider",
    "build_r1_forecast_trial_evidence_runtime",
]
