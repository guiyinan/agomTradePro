"""Composition of the atomic current-publication rebuild workflow."""

from datetime import datetime

from django.db import transaction

from apps.data_center.application.current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationDataset,
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.market_publication_refresh import (
    MarketPublicationRefreshBlocked,
)
from apps.data_center.financial_source_time_composition import (
    verify_retained_financial_source_time_evidence,
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
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    preflight_data_reliability_audit_runtime,
)

_GENERIC_CURRENT_DATASET_KEYS = (
    "equity.quote.snapshot",
    "equity.price.bar",
    "equity.valuation.fact",
)
_FINANCIAL_DATASET_KEY = "equity.financial.fact"


def build_current_publication_rebuild(
    *,
    created_by: str = "ops.current_publication_rebuild",
    dataset_keys: tuple[str, ...] | None = None,
) -> CoreCurrentPublicationRebuildUseCase:
    """Compose the atomic active-universe publication rebuild workflow."""

    def preflight_current_authority(as_of: datetime) -> None:
        """Require exact current authority before the publication transaction."""

        try:
            preflight_data_reliability_audit_runtime(
                environment="production",
                using="default",
                as_of=as_of,
            )
        except SystemAuditCompositionUnavailable as exc:
            reason_code = exc.reason_code.strip().lower() or "authority_unavailable"
            error_code = (
                reason_code
                if reason_code.startswith("system_audit_")
                else f"system_audit_{reason_code}"
            )
            raise MarketPublicationRefreshBlocked(
                code=error_code,
            ) from exc

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
            FinancialFactRepository(
                source_time_evidence_verifier=verify_retained_financial_source_time_evidence
            ),
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
    selected_dataset_keys = (
        set(_GENERIC_CURRENT_DATASET_KEYS) if dataset_keys is None else set(dataset_keys)
    )
    rebuilders = tuple(
        CurrentPublicationRebuildUseCase(
            dataset=dataset,
            candidate_repository=repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        )
        for dataset, repository in specifications
        if dataset.dataset_key in selected_dataset_keys
    )
    return CoreCurrentPublicationRebuildUseCase(
        rebuilders=rebuilders,
        transaction=transaction.atomic,
        authority_preflight=preflight_current_authority,
        deferred_dataset_keys=((_FINANCIAL_DATASET_KEY,) if dataset_keys is None else ()),
    )
