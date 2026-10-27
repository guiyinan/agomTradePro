"""Production composition for the fixed M1 close-reference publication lane."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationDataset,
)
from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.m1_reference_price_publication import (
    M1_REFERENCE_PRICE_DATABASE_ALIAS,
    M1ReferencePricePublicationUseCase,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationGroupAuditWriter,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.sync_transaction import DataQualityAuditWriter
from apps.data_center.composition import (
    build_provider_registry_for_repo,
    make_system_audited_sync_price_use_case,
)
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.infrastructure.audited_sync_runtime import DjangoDataCenterSyncClock
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.m1_reference_price_publication_audit import (
    M1ReferencePricePublicationAuditWriter,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from apps.data_center.infrastructure.publication_models import CanonicalPublicationPointerModel
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    SystemAuditReaderContext,
    get_data_publication_activation_audit_writer,
    get_data_reliability_audit_writers,
    preflight_data_reliability_audit_runtime,
)
from core.integration.production_account_authority_capture import (
    ProductionAccountAuthorityCapture,
    capture_account_authority_for_environment,
)

_M1_CREATED_BY = "ops.m1_rebalance_reference"
_PRODUCTION_ENVIRONMENT: Literal["production"] = "production"


def build_m1_reference_price_publication_use_case(
    *,
    provider_repository: ProviderConfigRepositoryProtocol | None = None,
    provider_registry: ProviderRegistryProtocol | None = None,
    environment: Literal["development", "production"] = _PRODUCTION_ENVIRONMENT,
) -> M1ReferencePricePublicationUseCase:
    """Compose exact daily sync, fixed-lane staging, and fenced activation."""

    alias = M1_REFERENCE_PRICE_DATABASE_ALIAS
    providers = provider_repository or ProviderConfigRepository()
    registry = provider_registry or build_provider_registry_for_repo(providers)
    clock = DjangoDataCenterSyncClock()
    price_sync = make_system_audited_sync_price_use_case(
        provider_repository=providers,
        provider_registry=registry,
        environment=environment,
        publish_current=False,
    )
    publication_repository = CanonicalPublicationRepository()
    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=CurrentPublicationDataset(
            dataset_key="equity.price.bar",
            fact_table="data_center_price_bar",
            created_by=_M1_CREATED_BY,
        ),
        candidate_repository=PriceBarRepository(),
        publication_repository=publication_repository,
        policy_repository=PublicationPolicyRepository(),
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    resolver = DjangoCandidateRawAuditMetadataResolver(using=alias)
    staging_repository = DjangoCurrentPublicationStagingRepository(
        using=alias,
        publication_repository=publication_repository,
    )
    if resolver.database_alias != alias or staging_repository.database_alias != alias:
        raise SystemAuditCompositionUnavailable(
            "M1 staging components use different database aliases",
            reason_code="composition_alias_mismatch",
        )
    staging = CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=resolver,
        repository=staging_repository,
    )
    activation_repository = DjangoPublicationActivationGroupRepository(using=alias)
    activate_group = ActivateCanonicalPublicationGroupUseCase(activation_repository)
    if activation_repository.database_alias != alias:
        raise SystemAuditCompositionUnavailable(
            "M1 activation repository uses a different database alias",
            reason_code="composition_alias_mismatch",
        )

    (
        _fetch_writer,
        _publication_writer,
        _validation_writer,
        _failover_writer,
        _decision_read_writer,
        _provider_health_writer,
        _freshness_writer,
        quality_writer,
    ) = get_data_reliability_audit_writers(environment=environment, using=alias)
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repository,
        quality_writer=cast(DataQualityAuditWriter, quality_writer),
        clock=clock,
    )

    def preflight_authority(*, as_of: datetime) -> SystemAuditReaderContext:
        """Require provider-issued current Audit authority before exact sync writes."""

        context = preflight_data_reliability_audit_runtime(
            environment=environment,
            using=alias,
            as_of=as_of,
        )
        if type(context) is not SystemAuditReaderContext or not context.can_read_at(as_of):
            raise SystemAuditCompositionUnavailable(
                "current Audit authority is unavailable for M1 reference publication",
                reason_code="authority_context_unavailable",
            )
        return context

    def build_audit_writer() -> PublicationActivationGroupAuditWriter:
        """Bind manifest, quality, and outbox writers to the fixed alias."""

        delegate = get_data_publication_activation_audit_writer(
            environment=environment,
            using=alias,
        )
        if getattr(delegate, "database_alias", None) != alias:
            raise SystemAuditCompositionUnavailable(
                "M1 manifest audit writer uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        writer = M1ReferencePricePublicationAuditWriter(
            delegate=delegate,
            quality_recorder=quality_recorder,
        )
        if writer.database_alias != alias:
            raise SystemAuditCompositionUnavailable(
                "M1 required audit writer uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        return cast(PublicationActivationGroupAuditWriter, writer)

    def capture_authority(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ProductionAccountAuthorityCapture:
        """Capture the complete Account graph only after the M1 candidate is sealed."""

        capture = capture_account_authority_for_environment(
            using=alias,
            environment=environment,
            as_of=as_of,
            preflight_context=preflight_context,
        )
        if type(capture) is not ProductionAccountAuthorityCapture:
            raise SystemAuditCompositionUnavailable(
                "M1 Account authority capture returned an invalid proof",
                reason_code="authority_capture_invalid",
            )
        if capture.database_alias != alias:
            raise SystemAuditCompositionUnavailable(
                "M1 Account authority capture uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        return capture

    def read_current_pointer(
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot:
        """Read the exact pointer pair for the singleton M1 activation scope."""

        if (
            dataset_key != "equity.price.bar"
            or publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        ):
            raise SystemAuditCompositionUnavailable(
                "M1 pointer reader received a different publication scope",
                reason_code="publication_scope_invalid",
            )
        pointer = (
            CanonicalPublicationPointerModel._default_manager.using(alias)
            .filter(dataset_key=dataset_key, publication_key=publication_key)
            .first()
        )
        if pointer is None:
            return CurrentPublicationPointerSnapshot(None, None)
        if pointer.publication_id is None:
            if pointer.publication_hash or pointer.activation_id:
                raise SystemAuditCompositionUnavailable(
                    "empty M1 publication pointer contains stale identity",
                    reason_code="publication_pointer_empty_identity_invalid",
                )
            return CurrentPublicationPointerSnapshot(None, None)
        return CurrentPublicationPointerSnapshot(
            publication_id=str(pointer.publication_id),
            publication_hash=pointer.publication_hash,
        )

    return M1ReferencePricePublicationUseCase(
        price_sync=price_sync,
        provider_repository=providers,
        staging=staging,
        activate_group=activate_group,
        audit_writer_factory=build_audit_writer,
        authority_preflight=preflight_authority,
        authority_capture=capture_authority,
        current_pointer_reader=read_current_pointer,
        clock=clock,
        database_alias=alias,
    )


__all__ = ["build_m1_reference_price_publication_use_case"]
