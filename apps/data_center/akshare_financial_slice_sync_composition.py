"""Composition root for the governed AKShare financial slice sync."""

from __future__ import annotations

from pathlib import Path

from apps.data_center.application.financial_slice_sync import (
    FinancialSliceFetcherProtocol,
    SyncAkshareFinancialSlicesUseCase,
)
from apps.data_center.composition import (
    FinancialFactRepository,
    build_provider_registry_for_repo,
    get_provider_config_repository,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.protocols import UnifiedDataProviderProtocol
from apps.data_center.financial_source_time_composition import (
    verify_provider_financial_source_time_evidence,
    verify_retained_financial_source_time_evidence,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    build_akshare_financial_slice_fetcher,
    load_akshare_financial_slice_sync_budget,
)


def make_sync_akshare_financial_slices_use_case(
    *, artifact_storage_root: Path | None = None
) -> SyncAkshareFinancialSlicesUseCase:
    """Build the explicit, one-provider AKShare financial slice sync entrypoint."""

    def build_fetcher(
        config: ProviderConfig,
        provider: UnifiedDataProviderProtocol,
    ) -> FinancialSliceFetcherProtocol:
        """Build the exact capture path, optionally rooted in stage-local temp storage."""

        return build_akshare_financial_slice_fetcher(
            config,
            provider,
            artifact_storage_root=artifact_storage_root,
        )

    def verify_provider_evidence(
        provider: ProviderConfig,
        evidence: FinancialFactDecisionEvidence,
    ) -> bool:
        """Reverify the captured pair under the same stage-local retention root."""

        return verify_provider_financial_source_time_evidence(
            provider,
            evidence,
            artifact_storage_root=artifact_storage_root,
        )

    def verify_retained_evidence(evidence: FinancialFactDecisionEvidence) -> bool:
        """Reverify evidence at repository write time under the same retention root."""

        return verify_retained_financial_source_time_evidence(
            evidence,
            artifact_storage_root=artifact_storage_root,
        )

    fetcher_factory = (
        build_akshare_financial_slice_fetcher if artifact_storage_root is None else build_fetcher
    )
    provider_evidence_verifier = (
        verify_provider_financial_source_time_evidence
        if artifact_storage_root is None
        else verify_provider_evidence
    )
    retained_evidence_verifier = (
        verify_retained_financial_source_time_evidence
        if artifact_storage_root is None
        else verify_retained_evidence
    )
    provider_repo = get_provider_config_repository()
    financial_repository = FinancialFactRepository(
        source_time_evidence_verifier=retained_evidence_verifier
    )
    return SyncAkshareFinancialSlicesUseCase(
        provider_repo=provider_repo,
        provider_registry=build_provider_registry_for_repo(provider_repo),
        fact_repo=financial_repository,
        fetcher_factory=fetcher_factory,
        evidence_verifier=provider_evidence_verifier,
        request_budget=load_akshare_financial_slice_sync_budget(),
    )


__all__ = ["make_sync_akshare_financial_slices_use_case"]
