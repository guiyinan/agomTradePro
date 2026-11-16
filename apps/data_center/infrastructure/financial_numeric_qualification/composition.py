"""Compose exact retained-body readers with the Owner-qualified numeric catalog."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.data_center.application.financial_numeric_qualification import (
    ContextualFinancialNumericEvidenceVerifier,
)
from apps.data_center.infrastructure.financial_native_numeric_verifier import (
    DjangoFinancialNativeProviderIdentityResolver,
    FinancialNativeRawBodyReader,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    BalanceNumericEndpointRouteResolver,
    BalanceNumericOriginalBodyReader,
    FinancialNumericEndpointVerifierDispatcher,
    FinancialNumericQualificationAwareBalanceVerifier,
)
from apps.data_center.infrastructure.financial_numeric_qualification.django_catalog_adapter import (
    DjangoFinancialNumericSourceQualificationCatalogAdapter,
)
from apps.data_center.infrastructure.financial_numeric_qualification.main_verifier import (
    FinancialNumericQualificationAwareNativeVerifier,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_source_body_runtime import (
    build_statutory_source_body_store,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataValidationError


class FinancialNumericQualificationCompositionError(DataValidationError):
    """Block verifier construction when exact retained storage is not configured."""


def build_django_financial_numeric_endpoint_verifier(
    *,
    balance_parser_contract: BalanceCandidateContract,
    using: str = DEFAULT_DB_ALIAS,
    environment: str | None = None,
) -> ContextualFinancialNumericEvidenceVerifier:
    """Build the Main-plus-Balance verifier over exact stores and one DB alias.

    ``balance_parser_contract`` must be supplied from separately reviewed
    typed source contracts. This builder supplies no units, currency,
    consolidation policy, source qualification, or Owner approval. It performs
    no provider request and cannot turn a parsed Balance candidate into a
    qualified response.
    """

    if type(using) is not str or using != DEFAULT_DB_ALIAS:
        raise FinancialNumericQualificationCompositionError(
            "qualified financial verification currently requires the default database alias"
        )
    if type(balance_parser_contract) is not BalanceCandidateContract:
        raise TypeError("an explicit typed Balance parser contract is required")
    response_config = resolve_financial_response_artifact_config(environment=environment)
    if response_config is None:
        raise FinancialNumericQualificationCompositionError(
            "retained financial response storage requires explicit configuration"
        )

    audit_repository = RawAuditRepository()
    provider_identity_resolver = DjangoFinancialNativeProviderIdentityResolver()
    response_body_store = FinancialResponseBodyStore(
        response_config.root,
        encryption_key=response_config.encryption_key,
        encryption_key_ref=response_config.encryption_key_ref,
        encryption_key_version=response_config.encryption_key_version,
        max_body_bytes=response_config.max_body_bytes,
    )
    response_repository = FinancialResponseArtifactRepository(
        response_body_store,
        audit_repository,
        failure_audit_repository=audit_repository,
    )
    source_body_store = build_statutory_source_body_store()
    source_capture_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=source_body_store,
        using=using,
    )
    catalog = DjangoFinancialNumericSourceQualificationCatalogAdapter(
        capture_repository=source_capture_repository,
        using=using,
    )
    main_body_reader = FinancialNativeRawBodyReader(
        artifact_repository=response_repository,
        audit_repository=audit_repository,
        provider_identity_resolver=provider_identity_resolver,
    )
    balance_body_reader = BalanceNumericOriginalBodyReader(
        artifact_repository=response_repository,
        audit_repository=audit_repository,
        provider_identity_resolver=provider_identity_resolver,
    )
    main_verifier = FinancialNumericQualificationAwareNativeVerifier(catalog, main_body_reader)
    balance_verifier = FinancialNumericQualificationAwareBalanceVerifier(
        catalog,
        balance_body_reader,
        balance_parser_contract,
    )
    route_resolver = BalanceNumericEndpointRouteResolver(
        audit_repository,
        provider_identity_resolver,
    )
    return FinancialNumericEndpointVerifierDispatcher(
        route_resolver,
        main_verifier=main_verifier,
        balance_verifier=balance_verifier,
    )


__all__ = [
    "FinancialNumericQualificationCompositionError",
    "build_django_financial_numeric_endpoint_verifier",
]
