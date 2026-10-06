"""Composition root for the governed AKShare financial slice sync."""

from __future__ import annotations

from apps.data_center.application.financial_slice_sync import (
    SyncAkshareFinancialSlicesUseCase,
)
from apps.data_center.composition import (
    FinancialFactRepository,
    build_provider_registry_for_repo,
    get_provider_config_repository,
)
from apps.data_center.financial_source_time_composition import (
    verify_provider_financial_source_time_evidence,
    verify_retained_financial_source_time_evidence,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    build_akshare_financial_slice_fetcher,
    load_akshare_financial_slice_sync_budget,
)


def make_sync_akshare_financial_slices_use_case() -> SyncAkshareFinancialSlicesUseCase:
    """Build the explicit, one-provider AKShare financial slice sync entrypoint."""

    provider_repo = get_provider_config_repository()
    financial_repository = FinancialFactRepository(
        source_time_evidence_verifier=verify_retained_financial_source_time_evidence
    )
    return SyncAkshareFinancialSlicesUseCase(
        provider_repo=provider_repo,
        provider_registry=build_provider_registry_for_repo(provider_repo),
        fact_repo=financial_repository,
        fetcher_factory=build_akshare_financial_slice_fetcher,
        evidence_verifier=verify_provider_financial_source_time_evidence,
        request_budget=load_akshare_financial_slice_sync_budget(),
    )


__all__ = ["make_sync_akshare_financial_slices_use_case"]
