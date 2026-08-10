"""Fail-closed composition root for the concrete R3 research runner."""

from __future__ import annotations

from dataclasses import dataclass

from apps.macro_factor.application.reproducible_runner import (
    MacroFactorRunLedgerRepository,
    MacroFactorRunnerAssessment,
    MacroFactorRunnerBlockerCode,
    MacroFactorRunnerDatasetProvider,
    MacroFactorRunnerManifestProvider,
    MacroFactorRunnerSpecProvider,
    MacroFactorRunnerStatus,
    RunReproducibleMacroFactor,
    RunReproducibleMacroFactorCommand,
)
from apps.macro_factor.domain.entities import PITManifestEvidence
from apps.macro_factor.domain.reproducible_runner import (
    ExternalNestedCVArtifact,
    MacroFactorLifecycleEvent,
    MacroFactorRunnerSpec,
    NestedCVExecutionRequest,
    PITResearchDataset,
    ReproducibleMacroFactorRunArtifact,
    ReproducibleMacroFactorRunBundle,
)
from apps.macro_factor.infrastructure.run_ledger_repository import (
    DjangoMacroFactorRunLedgerReadRepository,
)
from apps.macro_factor.infrastructure.sklearn_nested_cv_runner import (
    SklearnNestedCVFittingConfig,
    SklearnNestedCVLassoRunner,
)


class UnavailableConcreteLassoRunFacade:
    """State-free production mutation surface while canonical owners are absent."""

    __slots__ = ()

    def execute(
        self,
        command: RunReproducibleMacroFactorCommand,
    ) -> MacroFactorRunnerAssessment:
        """Validate the identity-only command and return one stable blocker."""

        try:
            if type(command) is not RunReproducibleMacroFactorCommand:
                raise TypeError("macro-factor run command type differs")
            RunReproducibleMacroFactorCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError):
            pass
        return MacroFactorRunnerAssessment(
            status=MacroFactorRunnerStatus.BLOCKED,
            blocked_reasons=(MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,),
            bundle=None,
            lifecycle_event=None,
        )


@dataclass(frozen=True, slots=True)
class ConcreteLassoRunnerRuntime:
    """Read-safe runtime with an inert public run surface."""

    run: UnavailableConcreteLassoRunFacade
    ledger: DjangoMacroFactorRunLedgerReadRepository


@dataclass(frozen=True, slots=True)
class _ConcreteLassoRunnerTestRuntime:
    """Private injectable runtime used only by synthetic adapter tests."""

    run: RunReproducibleMacroFactor


class _UnavailableManifestProvider:
    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        """Return no manifest when composition is incomplete."""

        return None


class _UnavailableSpecProvider:
    def get_spec(
        self,
        *,
        spec_id: str,
        spec_version: int,
    ) -> MacroFactorRunnerSpec | None:
        """Return no spec when no authoritative owner was composed."""

        return None


class _UnavailableDatasetProvider:
    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> PITResearchDataset | None:
        """Return no dataset when composition is incomplete."""

        return None


class _UnavailableExternalRunner:
    def execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact | None:
        """Never fabricate numerical evidence."""

        return None


class _UnavailableRepository:
    def append_bundle(
        self,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> ReproducibleMacroFactorRunBundle:
        """Reject persistence when no repository was explicitly provided."""

        raise RuntimeError("macro-factor ledger repository is unavailable")

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return no artifact when persistence is unavailable."""

        return None

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return no lifecycle evidence when persistence is unavailable."""

        return ()

    def append_lifecycle_event(
        self,
        event: MacroFactorLifecycleEvent,
    ) -> MacroFactorLifecycleEvent:
        """Reject lifecycle writes when persistence is unavailable."""

        raise RuntimeError("macro-factor ledger repository is unavailable")


def build_concrete_lasso_runner_runtime(
    *,
    using: str = "default",
) -> ConcreteLassoRunnerRuntime:
    """Build exact ledger reads without retaining any run write capability."""

    return ConcreteLassoRunnerRuntime(
        run=UnavailableConcreteLassoRunFacade(),
        ledger=DjangoMacroFactorRunLedgerReadRepository(using=using),
    )


def _build_concrete_lasso_runner_runtime_for_test(
    *,
    config: SklearnNestedCVFittingConfig | None,
    spec_provider: MacroFactorRunnerSpecProvider | None,
    manifest_provider: MacroFactorRunnerManifestProvider | None,
    dataset_provider: MacroFactorRunnerDatasetProvider | None,
    repository: MacroFactorRunLedgerRepository | None,
) -> _ConcreteLassoRunnerTestRuntime:
    """Compose the injectable fitting graph for isolated synthetic tests."""

    use_case = RunReproducibleMacroFactor(
        spec_provider=(spec_provider if spec_provider is not None else _UnavailableSpecProvider()),
        manifest_provider=(
            manifest_provider if manifest_provider is not None else _UnavailableManifestProvider()
        ),
        dataset_provider=(
            dataset_provider if dataset_provider is not None else _UnavailableDatasetProvider()
        ),
        external_runner=(
            SklearnNestedCVLassoRunner(config)
            if config is not None
            else _UnavailableExternalRunner()
        ),
        repository=repository if repository is not None else _UnavailableRepository(),
    )
    return _ConcreteLassoRunnerTestRuntime(run=use_case)


__all__ = [
    "ConcreteLassoRunnerRuntime",
    "UnavailableConcreteLassoRunFacade",
    "build_concrete_lasso_runner_runtime",
]
