"""Composition helper for the audited real-time quote synchronization use case."""

from __future__ import annotations

from typing import cast

from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import PublishQuoteSnapshotBatchUseCase
from apps.data_center.application.sync_transaction import DataCenterSyncUnitOfWorkParticipant
from apps.data_center.application.sync_use_cases import SyncQuoteUseCase
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncClock,
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DatasetContractRepository,
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.repositories import (
    QuoteSnapshotRepository,
    RawAuditRepository,
)


def _compose_system_audited_sync_quote_use_case(
    *,
    provider_repo: ProviderConfigRepositoryProtocol,
    registry: ProviderRegistryProtocol,
    environment: str,
    publish_current: bool,
) -> SyncQuoteUseCase:
    """Build the same-unit-of-work audited quote sync and publication composition."""
    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    quote_repo = QuoteSnapshotRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    (
        fetch_audit_writer,
        publication_audit_writer,
        _validation_audit_writer,
        _failover_audit_writer,
        _decision_read_audit_writer,
        provider_health_audit_writer,
        _freshness_audit_writer,
        quality_audit_writer,
    ) = get_data_reliability_audit_writers(environment=environment, using="default")
    identity_issuer = DjangoSyncExecutionIdentityIssuer(identity_repo, using="default")
    sync_clock = DjangoDataCenterSyncClock()
    quality_recorder = (
        RecordPublicationQualityUseCase(
            publication_reader=publication_repo,
            quality_writer=quality_audit_writer,
            clock=sync_clock,
        )
        if publish_current
        else None
    )
    sync_uow = DjangoDataCenterSyncUnitOfWork(
        (
            cast(DataCenterSyncUnitOfWorkParticipant, provider_repo),
            quote_repo,
            raw_audit_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        fetch_audit_writer,
        additional_audit_writers=(
            publication_audit_writer,
            provider_health_audit_writer,
            quality_audit_writer,
        ),
        using="default",
    )
    return SyncQuoteUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=quote_repo,
        raw_audit_repo=raw_audit_repo,
        dataset_contract_repository=DatasetContractRepository(),
        publication_publisher=(
            PublishQuoteSnapshotBatchUseCase(
                fact_repository=quote_repo,
                publication_repository=publication_repo,
                policy_repository=policy_repo,
            )
            if publish_current
            else None
        ),
        sync_identity_issuer=identity_issuer,
        sync_unit_of_work=sync_uow,
        data_fetch_audit_writer=fetch_audit_writer,
        data_publication_audit_writer=publication_audit_writer,
        publication_quality_recorder=quality_recorder,
        clock=sync_clock,
        data_provider_health_audit_writer=provider_health_audit_writer,
    )
