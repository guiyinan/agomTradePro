"""Compose the isolated finite E1 discovery runner from canonical Django ports.

The composition performs the first exact catalog/Owner/body/config/route
preflight before returning a callable use case, so an incomplete selection is
blocked before the capture gateway can make an HTTP request. It creates no
catalog entry, qualification, authority, or network policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.financial_e1_discovery_runner import (
    CaptureFinancialE1DiscoveryUseCase,
    FinancialE1ExecutionAuthorityPort,
)
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactRetention,
    FinancialResponseFailureRetention,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3OfficialSourceProfileExpectation,
)
from apps.data_center.application.sync_transaction import DataFetchAuditWriter
from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2
from apps.data_center.domain.financial_next_session_witness import (
    FinancialNativeRowBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence
from apps.data_center.financial_availability_e1_composition import (
    build_financial_next_session_witness_v3,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
)
from apps.data_center.infrastructure.control_plane_repositories import SyncRunRepository
from apps.data_center.infrastructure.financial_availability_governance_writer import (
    DjangoFinancialAvailabilityGovernanceRepository,
    DjangoFinancialAvailabilityOwnerEventRepository,
)
from apps.data_center.infrastructure.financial_availability_source_reader import (
    DjangoFinancialAvailabilitySourceReader,
)
from apps.data_center.infrastructure.financial_e1_capture_gateway import (
    FinancialE1RetainedCaptureGateway,
)
from apps.data_center.infrastructure.financial_e1_discovery_replay import (
    FinancialE1DiscoveryResponseScopeVerifier,
    FinancialE1DiscoveryRoleReplayer,
)
from apps.data_center.infrastructure.financial_e1_discovery_runtime import (
    DjangoFinancialE1DatabaseClock,
    DjangoFinancialE1PinnedPreflight,
    DjangoFinancialE1RequestProjector,
    DjangoFinancialE1SelectionLoader,
    build_financial_e1_preflight_loader,
    build_financial_e1_resolver,
)
from apps.data_center.infrastructure.financial_e1_discovery_v3_writer import (
    FinancialE1V3FactWriterReadback,
)
from apps.data_center.infrastructure.financial_e1_recovery_binding import (
    RetainedWriteReview,
    RetainedWriteReviewGuard,
)
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_fact_v3_e1_verifier import (
    FinancialFactV3E1EvidenceVerifier,
    FinancialV3QualifiedTemporalGate,
)
from apps.data_center.infrastructure.financial_native_numeric_verifier import (
    DjangoFinancialNativeProviderIdentityResolver,
    FinancialNativeRawBodyReader,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_reader import (
    DjangoFinancialNumericOriginSnapshotReader,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    BalanceNumericEndpointRouteResolver,
    BalanceNumericOriginalBodyReader,
)
from apps.data_center.infrastructure.financial_numeric_qualification.composition import (
    build_django_financial_numeric_endpoint_verifier,
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
from apps.data_center.infrastructure.financial_statutory_numeric_capture_adapter import (
    DjangoFinancialStatutoryNumericCaptureAdapter,
)
from apps.data_center.infrastructure.financial_v3_official_source_qualifier import (
    FinancialV3ConfiguredOfficialSourceQualifier,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError
from core.integration.data_center_audit import get_data_reliability_audit_writers


class _AuthorityGuardedArtifactRepository:
    """Revalidate task/account authority immediately before each RawAudit write."""

    def __init__(
        self,
        repository: FinancialResponseArtifactRepository,
        authority_guard: FinancialE1ExecutionAuthorityPort,
    ) -> None:
        """Bind the existing artifact adapter to the current E1 guard."""

        self._repository = repository
        self._authority_guard = authority_guard

    def retain(
        self,
        *,
        capture_id: UUID,
        evidence: FinancialResponseEvidence,
        body: bytes,
        provider_name: str,
        request_params: Mapping[str, object],
        row_count: int = 0,
        provider_id: int | None = None,
        run_id: UUID | None = None,
    ) -> FinancialResponseArtifactRetention:
        """Append one exact RawAudit only while the authorized Account is current."""

        self._authority_guard.assert_current()
        return self._repository.retain(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
            provider_name=provider_name,
            request_params=request_params,
            row_count=row_count,
            provider_id=provider_id,
            run_id=run_id,
        )

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Read one immutable retained artifact without mutation."""

        return self._repository.read(reference)

    def retain_rejected(
        self,
        *,
        capture_id: UUID,
        evidence: FinancialResponseEvidence,
        body: bytes,
        provider_name: str,
        request_params: Mapping[str, object],
        failure_code: str,
        provider_id: int | None = None,
    ) -> FinancialResponseFailureRetention:
        """Append one rejected-body RawAudit only while authority remains current."""

        self._authority_guard.assert_current()
        return self._repository.retain_rejected(
            capture_id=capture_id,
            evidence=evidence,
            body=body,
            provider_name=provider_name,
            request_params=request_params,
            failure_code=failure_code,
            provider_id=provider_id,
        )


class DjangoFinancialE1WitnessBuilder:
    """Bind the accepted C2 v3 builder to one real set of default-alias readers."""

    def __init__(
        self,
        *,
        records: FinancialAvailabilityGovernanceRepositoryPort,
        owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
        source_reader: FinancialAvailabilitySourceReaderPort,
    ) -> None:
        """Require the same current repositories later used by the v3 gate."""

        aliases = (
            records.database_alias,
            owner_events.database_alias,
            source_reader.database_alias,
        )
        if any(type(alias) is not str or alias != DEFAULT_DB_ALIAS for alias in aliases):
            raise ValueError("E1 C2 witness ports must share the default database alias")
        self._records = records
        self._owner_events = owner_events
        self._source_reader = source_reader

    def __call__(
        self,
        financial_row: FinancialNativeRowBinding,
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> FinancialNextSessionSourceTimeWitnessV3:
        """Resolve and build the actual date-only witness in the caller's RC UOW."""

        return build_financial_next_session_witness_v3(
            financial_row,
            exchange=exchange,
            calendar_dataset_key=calendar_dataset_key,
            records=self._records,
            owner_events=self._owner_events,
            source_reader=self._source_reader,
        )


def build_django_financial_e1_discovery_use_case(
    plan: FinancialE1DiscoveryPlanV2,
    *,
    official_source_profile_expectation: FinancialV3OfficialSourceProfileExpectation,
    authority_guard: FinancialE1ExecutionAuthorityPort,
    environment: str | None = None,
    retained_review: RetainedWriteReview | None = None,
) -> CaptureFinancialE1DiscoveryUseCase:
    """Build one preflighted Main+Balance writer/readback use case.

    The independent official-source profile expectation is an explicit
    composition input. It must come from the reviewed deployment configuration
    and cannot be copied from the mutable catalog being verified.
    """

    if type(plan) is not FinancialE1DiscoveryPlanV2:
        raise TypeError("E1 composition requires one exact finite discovery plan")
    if type(official_source_profile_expectation) is not FinancialV3OfficialSourceProfileExpectation:
        raise TypeError("an independently reviewed official-source profile expectation is required")
    if authority_guard is None:
        raise TypeError("a current DATA02 actor/account guard is required")
    official_source_profile_expectation.__post_init__()
    clock = DjangoFinancialE1DatabaseClock()

    response_config = resolve_financial_response_artifact_config(environment=environment)
    if response_config is None:
        raise DataValidationError(
            "Financial response retention is not explicitly configured.",
            code="FINANCIAL_E1_RESPONSE_STORE_UNAVAILABLE",
        )
    audit_repository = RawAuditRepository()
    response_store = FinancialResponseBodyStore(
        response_config.root,
        encryption_key=response_config.encryption_key,
        encryption_key_ref=response_config.encryption_key_ref,
        encryption_key_version=response_config.encryption_key_version,
        max_body_bytes=response_config.max_body_bytes,
    )
    artifact_repository = FinancialResponseArtifactRepository(
        response_store,
        audit_repository,
        failure_audit_repository=audit_repository,
    )
    guarded_artifact_repository = _AuthorityGuardedArtifactRepository(
        artifact_repository,
        authority_guard,
    )

    source_body_store = build_statutory_source_body_store()
    numeric_capture_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=source_body_store,
        using=DEFAULT_DB_ALIAS,
    )
    source_repository = DjangoStatutorySourceRepository(
        body_store=source_body_store,
        using=DEFAULT_DB_ALIAS,
    )
    source_reader = DjangoFinancialAvailabilitySourceReader(
        repository=source_repository,
        body_store=source_body_store,
        using=DEFAULT_DB_ALIAS,
    )
    records = DjangoFinancialAvailabilityGovernanceRepository(using=DEFAULT_DB_ALIAS)
    owner_events = DjangoFinancialAvailabilityOwnerEventRepository(
        using=DEFAULT_DB_ALIAS,
        source_reader=source_reader,
    )
    if any(
        repository.database_alias != DEFAULT_DB_ALIAS
        for repository in (records, owner_events, source_reader, numeric_capture_repository)
    ):
        raise DataValidationError(
            "E1 source, Owner, and numeric capture readers must use the default alias.",
            code="FINANCIAL_E1_ALIAS_MISMATCH",
        )

    loader: DjangoFinancialE1SelectionLoader = build_financial_e1_preflight_loader(
        capture_repository=numeric_capture_repository
    )
    cutoff = clock.now_utc()
    if retained_review is not None:
        authority_guard = RetainedWriteReviewGuard(authority_guard, retained_review, plan, loader)
        authority_guard.assert_current()
        cutoff = min(retained_review.completed)
    prepared = loader.load(plan, known_at=cutoff)
    preflight = DjangoFinancialE1PinnedPreflight(loader=loader, expected=prepared)
    projector = DjangoFinancialE1RequestProjector(
        plan=plan,
        prepared=prepared,
        deployment_region=_deployment_region(),
    )
    provider_identity_resolver = DjangoFinancialNativeProviderIdentityResolver()
    scope_verifier = FinancialE1DiscoveryResponseScopeVerifier(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=prepared.balance_parser_contract,
    )
    capture_gateway = FinancialE1RetainedCaptureGateway(
        projection_port=projector,
        provider_identity_resolver=provider_identity_resolver,
        scope_verifiers={
            plan.main_request.endpoint: scope_verifier,
            plan.balance_request.endpoint: scope_verifier,
        },
        artifact_repository=cast(
            FinancialResponseArtifactRepository,
            guarded_artifact_repository,
        ),
        audit_repository=audit_repository,
    )
    numeric_verifier = build_django_financial_numeric_endpoint_verifier(
        balance_parser_contract=prepared.balance_parser_contract,
        using=DEFAULT_DB_ALIAS,
        environment=environment,
    )
    main_body_reader = FinancialNativeRawBodyReader(
        artifact_repository=artifact_repository,
        audit_repository=audit_repository,
        provider_identity_resolver=provider_identity_resolver,
    )
    balance_body_reader = BalanceNumericOriginalBodyReader(
        artifact_repository=artifact_repository,
        audit_repository=audit_repository,
        provider_identity_resolver=provider_identity_resolver,
    )
    route_resolver = BalanceNumericEndpointRouteResolver(
        audit_repository,
        provider_identity_resolver,
    )
    origin_snapshot_reader = DjangoFinancialNumericOriginSnapshotReader(
        capture_repository=numeric_capture_repository,
    )
    official_source_qualifier = FinancialV3ConfiguredOfficialSourceQualifier(
        origin_snapshots=origin_snapshot_reader,
        profile_expectation=official_source_profile_expectation,
        using=DEFAULT_DB_ALIAS,
    )
    statutory_capture = DjangoFinancialStatutoryNumericCaptureAdapter(
        statutory_reader=source_reader,
        numeric_capture_repository=numeric_capture_repository,
        using=DEFAULT_DB_ALIAS,
    )
    temporal_gate = FinancialV3QualifiedTemporalGate(
        records=records,
        owner_events=owner_events,
        source_reader=source_reader,
        statutory_capture=statutory_capture,
        official_source_qualifier=official_source_qualifier,
        using=DEFAULT_DB_ALIAS,
    )
    v3_verifier = FinancialFactV3E1EvidenceVerifier(
        numeric_verifier=numeric_verifier,
        temporal_gate=temporal_gate,
        route_resolver=route_resolver,
        main_body_reader=main_body_reader,
        balance_body_reader=balance_body_reader,
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=prepared.balance_parser_contract,
    )
    repository = FinancialFactRepository(
        qualified_numeric_evidence_verifier=numeric_verifier,
        v3_evidence_verifier=v3_verifier,
        database_alias=DEFAULT_DB_ALIAS,
    )
    witness_builder = DjangoFinancialE1WitnessBuilder(
        records=records,
        owner_events=owner_events,
        source_reader=source_reader,
    )
    fetch_audit_writer = cast(
        DataFetchAuditWriter,
        get_data_reliability_audit_writers(
            environment=environment or "production",
            using=DEFAULT_DB_ALIAS,
        )[0],
    )
    sync_unit_of_work = DjangoDataCenterSyncUnitOfWork(
        (audit_repository,),
        fetch_audit_writer,
        using=DEFAULT_DB_ALIAS,
    )
    fact_writer = FinancialE1V3FactWriterReadback(
        repository=repository,
        witness_builder=witness_builder,
        records=records,
        owner_events=owner_events,
        source_reader=source_reader,
        sync_unit_of_work=sync_unit_of_work,
        data_fetch_audit_writer=fetch_audit_writer,
        run_repository=SyncRunRepository(),
        review_sha256=retained_review.digest if retained_review else None,
        authority_guard=authority_guard,
    )
    qualification_resolver = build_financial_e1_resolver(
        capture_repository=numeric_capture_repository,
        using=DEFAULT_DB_ALIAS,
    )
    role_replayer = FinancialE1DiscoveryRoleReplayer(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=prepared.balance_parser_contract,
    )
    return CaptureFinancialE1DiscoveryUseCase(
        preflight=preflight,
        retained_captures=retained_review.captures if retained_review else None,
        capture_gateway=capture_gateway,
        role_replayer=role_replayer,
        qualification_resolver=qualification_resolver,
        fact_writer=fact_writer,
        clock=clock,
        authority_guard=authority_guard,
    )


def _deployment_region() -> str:
    """Use the existing explicit AKShare egress deployment region setting."""

    from apps.data_center.infrastructure.akshare_financial_slice_sync import (
        akshare_financial_deployment_region,
    )

    value = akshare_financial_deployment_region()
    if type(value) is not str or not value or value == "unknown":
        raise DataValidationError(
            "E1 deployment region is not explicitly configured.",
            code="FINANCIAL_E1_EGRESS_ROUTE_BLOCKED",
        )
    return value


__all__ = [
    "DjangoFinancialE1WitnessBuilder",
    "build_django_financial_e1_discovery_use_case",
]
