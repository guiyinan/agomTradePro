"""Composition of the atomic current-publication rebuild workflow."""

from django.db import transaction

from apps.data_center.application.current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationDataset,
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import PublicationPolicyRepository
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.repositories import (
    FinancialFactRepository,
    PriceBarRepository,
    QuoteSnapshotRepository,
    ValuationFactRepository,
)


def build_current_publication_rebuild(
    *,
    created_by: str = "ops.current_publication_rebuild",
    dataset_keys: tuple[str, ...] | None = None,
) -> CoreCurrentPublicationRebuildUseCase:
    """Compose the atomic active-universe publication rebuild workflow."""

    publication_repository = CanonicalPublicationRepository()
    policy_repository = PublicationPolicyRepository()
    specifications = (
        (
            CurrentPublicationDataset(
                dataset_key="equity.quote.snapshot",
                fact_table="data_center_quote_snapshot",
                created_by=created_by,
            ),
            QuoteSnapshotRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.price.bar",
                fact_table="data_center_price_bar",
                created_by=created_by,
            ),
            PriceBarRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.valuation.fact",
                fact_table="data_center_valuation_fact",
                created_by=created_by,
            ),
            ValuationFactRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.financial.fact",
                fact_table="data_center_financial_fact",
                created_by=created_by,
            ),
            FinancialFactRepository(),
        ),
    )
    if dataset_keys is not None:
        available = {dataset.dataset_key for dataset, _ in specifications}
        if (
            not dataset_keys
            or len(set(dataset_keys)) != len(dataset_keys)
            or not set(dataset_keys) <= available
        ):
            raise ValueError("Invalid current-publication dataset selection")
    rebuilders = tuple(
        CurrentPublicationRebuildUseCase(
            dataset=dataset,
            candidate_repository=repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        )
        for dataset, repository in specifications
        if dataset_keys is None or dataset.dataset_key in dataset_keys
    )
    return CoreCurrentPublicationRebuildUseCase(
        rebuilders=rebuilders,
        transaction=transaction.atomic,
    )
