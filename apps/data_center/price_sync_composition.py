"""Composition helper for the audited historical-price synchronization use case."""

from __future__ import annotations

from typing import cast

from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import PublishPriceBarBatchUseCase
from apps.data_center.application.sync_transaction import DataCenterSyncUnitOfWorkParticipant
from apps.data_center.application.sync_use_cases import SyncPriceUseCase
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
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.repositories import PriceBarRepository, RawAuditRepository


def _compose_system_audited_sync_price_use_case(
    *,
    provider_repo: ProviderConfigRepositoryProtocol,
    registry: ProviderRegistryProtocol,
    environment: str,
    publish_current: bool,
    publication_key: str,
) -> SyncPriceUseCase:
    """Build the same-unit-of-work audited historical-price sync composition."""

    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    price_repo = PriceBarRepository()
    raw_audit_repo = RawAuditRepository()
    raw_payload_repo = RawLandingRepository()
    response_payload_retainer = RetainProviderResponsePayloadUseCase(raw_payload_repo)
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
            price_repo,
            raw_audit_repo,
            raw_payload_repo,
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
    return SyncPriceUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=price_repo,
        raw_audit_repo=raw_audit_repo,
        publication_publisher=(
            PublishPriceBarBatchUseCase(
                fact_repository=price_repo,
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
        publication_key=publication_key,
        provider_response_payload_retainer=response_payload_retainer,
    )
