"""Production composition for current-market staging and group activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    PublicationActivationGroupAuditWriter,
)
from apps.data_center.domain.raw_audit_manifest import CURRENT_MARKET_PUBLICATION_DATASETS
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from apps.data_center.publication_rebuild_composition import build_current_publication_rebuild
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    SystemAuditReaderContext,
    get_data_publication_activation_audit_writer,
)
from core.integration.production_account_authority_capture import (
    ProductionAccountAuthorityCapture,
    capture_production_account_authority,
)

_DEFAULT_DATABASE_ALIAS = "default"
_PRODUCTION_ENVIRONMENT = "production"


class PublicationActivationAuditWriterFactory(Protocol):
    """Build an Audit-owned activation writer after runtime validation."""

    def __call__(self) -> PublicationActivationGroupAuditWriter:
        """Return one manifest-bound writer on the bundle database alias."""


class ProductionAccountAuthorityCaptureFactory(Protocol):
    """Capture the complete Account authority proof for a later group UOW."""

    def __call__(
        self,
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ProductionAccountAuthorityCapture:
        """Return an alias-bound complete authority fence and opaque proof."""


@dataclass(frozen=True, slots=True)
class ProductionCurrentMarketPublicationBundle:
    """Fixed quote, price, and valuation staging plus atomic group activation."""

    database_alias: str
    quote_staging: CurrentPublicationStagingUseCase
    price_staging: CurrentPublicationStagingUseCase
    valuation_staging: CurrentPublicationStagingUseCase
    activate_group: ActivateCanonicalPublicationGroupUseCase
    audit_writer_factory: PublicationActivationAuditWriterFactory
    authority_capture: ProductionAccountAuthorityCaptureFactory


def build_production_current_market_publication_bundle(
    *,
    using: str = _DEFAULT_DATABASE_ALIAS,
    created_by: str = "ops.current_publication_rebuild",
) -> ProductionCurrentMarketPublicationBundle:
    """Compose fixed market staging and group activation on the production alias.

    Candidate construction comes from the existing current rebuild composition,
    so scope, policy, freshness, and coverage decisions remain shared with the
    legacy publisher. Audit configuration and Account authority are exposed as
    validated callables for the later activation request path.
    """

    alias = _require_default_database_alias(using)
    rebuild = build_current_publication_rebuild(
        created_by=created_by,
        dataset_keys=tuple(sorted(CURRENT_MARKET_PUBLICATION_DATASETS)),
    )
    rebuilders_by_dataset = {item.dataset.dataset_key: item for item in rebuild.rebuilders}
    if set(rebuilders_by_dataset) != CURRENT_MARKET_PUBLICATION_DATASETS:
        raise SystemAuditCompositionUnavailable(
            "current market publication rebuild composition is incomplete",
            reason_code="publication_rebuilders_incomplete",
        )

    quote_staging = _build_staging_use_case(
        rebuilder=rebuilders_by_dataset["equity.quote.snapshot"],
        using=alias,
    )
    price_staging = _build_staging_use_case(
        rebuilder=rebuilders_by_dataset["equity.price.bar"],
        using=alias,
    )
    valuation_staging = _build_staging_use_case(
        rebuilder=rebuilders_by_dataset["equity.valuation.fact"],
        using=alias,
    )
    activation_repository = DjangoPublicationActivationGroupRepository(using=alias)
    if activation_repository.database_alias != alias:
        raise SystemAuditCompositionUnavailable(
            "publication group activation repository uses a different database alias",
            reason_code="composition_alias_mismatch",
        )

    def build_audit_writer() -> PublicationActivationGroupAuditWriter:
        """Use the canonical Audit runtime/outbox factory on this alias."""

        writer = get_data_publication_activation_audit_writer(
            environment=_PRODUCTION_ENVIRONMENT,
            using=alias,
        )
        if getattr(writer, "database_alias", None) != alias:
            raise SystemAuditCompositionUnavailable(
                "publication activation audit writer uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        if not callable(getattr(writer, "append_manifest_required", None)):
            raise SystemAuditCompositionUnavailable(
                "manifest-bound publication activation audit writer is unavailable",
                reason_code="composition_not_wired",
            )
        return cast(PublicationActivationGroupAuditWriter, writer)

    def capture_authority(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ProductionAccountAuthorityCapture:
        """Delegate complete V3 authority capture through the core facade."""

        capture = capture_production_account_authority(
            using=alias,
            as_of=as_of,
            preflight_context=preflight_context,
        )
        if type(capture) is not ProductionAccountAuthorityCapture:
            raise SystemAuditCompositionUnavailable(
                "production Account authority capture returned an invalid result",
                reason_code="authority_capture_invalid",
            )
        if capture.database_alias != alias:
            raise SystemAuditCompositionUnavailable(
                "production Account authority capture uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        return capture

    return ProductionCurrentMarketPublicationBundle(
        database_alias=alias,
        quote_staging=quote_staging,
        price_staging=price_staging,
        valuation_staging=valuation_staging,
        activate_group=ActivateCanonicalPublicationGroupUseCase(activation_repository),
        audit_writer_factory=build_audit_writer,
        authority_capture=capture_authority,
    )


def _build_staging_use_case(
    *,
    rebuilder: CurrentPublicationRebuildUseCase,
    using: str,
) -> CurrentPublicationStagingUseCase:
    """Build one dataset-specific stage use case with the shared default alias."""

    resolver = DjangoCandidateRawAuditMetadataResolver(using=using)
    repository = DjangoCurrentPublicationStagingRepository(using=using)
    if resolver.database_alias != using or repository.database_alias != using:
        raise SystemAuditCompositionUnavailable(
            "current publication staging components use different database aliases",
            reason_code="composition_alias_mismatch",
        )
    return CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=resolver,
        repository=repository,
    )


def _require_default_database_alias(value: object) -> str:
    """Reject unsupported database aliases before constructing any component."""

    if type(value) is not str or value != _DEFAULT_DATABASE_ALIAS:
        raise SystemAuditCompositionUnavailable(
            "current market publication production composition requires the default database",
            reason_code="composition_alias_mismatch",
        )
    return _DEFAULT_DATABASE_ALIAS


__all__ = [
    "ProductionAccountAuthorityCaptureFactory",
    "ProductionCurrentMarketPublicationBundle",
    "PublicationActivationAuditWriterFactory",
    "build_production_current_market_publication_bundle",
]
