"""Fail-closed composition root for the concrete R3 research runner."""

from __future__ import annotations

from dataclasses import dataclass

from apps.macro_factor.application.reproducible_runner import (
    MacroFactorRunLedgerRepository,
    MacroFactorRunnerDatasetProvider,
    MacroFactorRunnerManifestProvider,
    RunReproducibleMacroFactor,
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
from apps.macro_factor.infrastructure.sklearn_nested_cv_runner import (
    SklearnNestedCVFittingConfig,
    SklearnNestedCVLassoRunner,
)


@dataclass(frozen=True)
class ConcreteLassoRunnerRuntime:
    """Application runtime that exposes research orchestration only."""

    run: RunReproducibleMacroFactor


class _UnavailableManifestProvider:
    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        """Return no manifest when composition is incomplete."""

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
    config: SklearnNestedCVFittingConfig | None,
    manifest_provider: MacroFactorRunnerManifestProvider | None,
    dataset_provider: MacroFactorRunnerDatasetProvider | None,
    repository: MacroFactorRunLedgerRepository | None,
) -> ConcreteLassoRunnerRuntime:
    """Compose the concrete adapter only when every required owner is present."""

    if (
        config is None
        or manifest_provider is None
        or dataset_provider is None
        or repository is None
    ):
        use_case = RunReproducibleMacroFactor(
            manifest_provider=_UnavailableManifestProvider(),
            dataset_provider=_UnavailableDatasetProvider(),
            external_runner=_UnavailableExternalRunner(),
            repository=_UnavailableRepository(),
        )
    else:
        use_case = RunReproducibleMacroFactor(
            manifest_provider=manifest_provider,
            dataset_provider=dataset_provider,
            external_runner=SklearnNestedCVLassoRunner(config),
            repository=repository,
        )
    return ConcreteLassoRunnerRuntime(run=use_case)


__all__ = ["ConcreteLassoRunnerRuntime", "build_concrete_lasso_runner_runtime"]
