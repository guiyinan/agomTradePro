"""Opt-in real PostgreSQL consistency, locking and rollback publication tests."""

import hashlib
import ipaddress
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from threading import Barrier
from time import monotonic
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from django.apps import apps
from django.db import (
    DatabaseError,
    IntegrityError,
    OperationalError,
    connection,
    connections,
    transaction,
)
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.state import ProjectState
from django.db.utils import load_backend
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationUnavailable,
    AccountAuthorityFinalRevalidatorV3,
)
from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.akshare_financial_capture_composition import (
    AKSHARE_FINANCIAL_DATASET_KEY,
    AKSHARE_SOURCE_TIME_DATASET_KEY,
    AkshareFinancialCaptureGateway,
)
from apps.data_center.application.egress_service import (
    FinancialResponseAttemptBudget,
    FinancialResponseCaptureProtocol,
)
from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityBinding,
    FinancialCapacityCheckpoint,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityPublicationIndeterminateError,
    FinancialCapacityPublicationPlan,
    FinancialCapacityReceipt,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    GovernedFinancialProductionCeiling,
    _empty_evidence_sha256,
    _manifest_sha256,
)
from apps.data_center.application.financial_scope_capacity_input import (
    install_financial_scope_manifest_pointer,
    prepare_financial_scope_manifest_pointer,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    PublicationActivationError,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.application.query_services import query_published_valuation_facts
from apps.data_center.application.sync_use_cases import (
    with_verified_financial_transport_metadata,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAsset,
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    make_candidate,
    universe_sha256,
)
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
)
from apps.data_center.financial_source_time_composition import (
    verify_retained_financial_source_time_evidence,
)
from apps.data_center.infrastructure._provider_adapter_akshare import (
    AkshareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.financial_capacity_publisher_runtime import (
    AtomicFinancialPolicyV3Publisher,
)
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_response_artifact_config import (
    FinancialResponseArtifactRuntimeConfig,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_scope_capacity_import_authority import (
    DjangoFinancialScopeCapacityImportAuthoritySource,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_manifest_current_pointer import (
    DjangoFinancialScopeManifestCurrentPointerSource,
)
from apps.data_center.infrastructure.financial_source_time_artifact_repository import (
    FinancialSourceTimeArtifactRepository,
)
from apps.data_center.infrastructure.financial_source_time_audit_repository import (
    DjangoFinancialSourceTimeArtifactAuditRepository,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityGovernanceRevocationModel,
    FinancialCapacityOwnerApprovalEventModel,
    FinancialFactModel,
    FinancialPublicationCapacityManifestItemModel,
    FinancialPublicationCapacityWorkflowModel,
    FinancialScopeCapacityImportConsumptionModel,
    FinancialScopeCapacityImportModel,
    FinancialScopeManifestCurrentPointerModel,
    FinancialSourceTimeAuditClaimModel,
    PriceBarModel,
    ProviderConfigModel,
    QuoteSnapshotModel,
    RawAuditModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_read_snapshot import (
    PublicationReadSnapshotError,
    consistent_publication_read,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from core.exceptions import DataFetchError
from core.integration.data_center_audit import (
    DataPublicationManifestAuditObservation,
    SystemAuditEventOutboxCommit,
)
from tests.component.account.test_owner_tenant_authority_v3_fresh_v5_parents_postgres import (
    _SCHEMA_MODELS as _ACCOUNT_SCHEMA_MODELS,
)
from tests.component.data_center.test_current_publication_evidence_gate import _published_snapshot

_ACCOUNT_GENERATION_MIGRATION = import_module(
    "apps.account.migrations.0065_account_authority_generation"
)
_ACCOUNT_GENERATION_LOCK_MIGRATION = import_module(
    "apps.account.migrations.0066_account_authority_generation_lock"
)


@dataclass(frozen=True)
class _PGProbeFactory:
    credentials: dict[str, object] = field(repr=False)
    runtime_settings: dict[str, object] = field(repr=False)

    def connect(self):
        return psycopg.connect(**self.credentials)

    def runtime_wrapper(self) -> BaseDatabaseWrapper:
        """Build an isolated connection using the production-like runtime role."""

        settings = deepcopy(self.runtime_settings)
        return load_backend(str(settings["ENGINE"])).DatabaseWrapper(settings, alias="default")


def _public_schema_had_create(connection: BaseDatabaseWrapper) -> bool:
    """Return whether PUBLIC currently has CREATE on the public schema."""

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_namespace AS namespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          namespace.nspacl,
                          pg_catalog.acldefault('n', namespace.nspowner)
                      )
                  ) AS acl
                 WHERE namespace.nspname = 'public'
                   AND acl.grantee = 0
                   AND acl.privilege_type = 'CREATE'
            )
            """)
        row = cursor.fetchone()
    if row is None or type(row[0]) is not bool:
        raise AssertionError("public schema ACL catalog row is malformed")
    return row[0]


def _grant_runtime_business_access(
    connection: BaseDatabaseWrapper,
    *,
    quoted_runtime_role: str,
) -> None:
    """Grant business DML while keeping generation mutation and bump execution denied."""

    with connection.cursor() as cursor:
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_runtime_role}")
        cursor.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            f"TO {quoted_runtime_role}"
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
            "ON TABLE public.account_authority_generation "
            f"FROM {quoted_runtime_role}"
        )
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION public.account_authority_generation_lock() "
            f"TO {quoted_runtime_role}"
        )
        cursor.execute(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_runtime_role}"
        )


@pytest.fixture(scope="module")
def _actual_publication_pg_schema(django_db_blocker) -> Iterator[_PGProbeFactory]:
    """Use only the explicitly opted-in empty dedicated loopback test database."""

    if os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1":
        pytest.skip("Enable the disposable loopback PostgreSQL test explicitly")
    parsed = urlsplit(os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", ""))
    assert parsed.scheme in {"postgres", "postgresql"}
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert unquote(parsed.path.removeprefix("/")) == "agom_release_rehearsal_ci"
    credentials = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": "agom_release_rehearsal_ci",
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 10,
    }
    original = connections["default"]
    settings = deepcopy(original.settings_dict)
    settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=credentials["dbname"],
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=credentials["host"],
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={"connect_timeout": 10},
    )
    wrapper = load_backend(settings["ENGINE"]).DatabaseWrapper(settings, alias="default")
    publication_models = (
        DatasetContractModel,
        DatasetProviderBindingModel,
        DatasetPublicationPolicyModel,
        DataOwnerRegistrationModel,
        AssetMasterModel,
        AssetAliasModel,
        ProviderConfigModel,
        PriceBarModel,
        QuoteSnapshotModel,
        FinancialFactModel,
        FinancialPublicationCapacityWorkflowModel,
        FinancialPublicationCapacityManifestItemModel,
        FinancialCapacityGovernanceRecordModel,
        FinancialCapacityGovernanceRevocationModel,
        FinancialCapacityOwnerApprovalEventModel,
        FinancialScopeManifestCurrentPointerModel,
        FinancialScopeCapacityImportModel,
        FinancialScopeCapacityImportConsumptionModel,
        ValuationFactModel,
        RawAuditModel,
        FinancialSourceTimeAuditClaimModel,
        CanonicalPublicationModel,
        CandidateRawAuditManifestModel,
        CandidateRawAuditManifestMemberModel,
        CanonicalPublicationPointerModel,
        CoverageSnapshotModel,
        PublicationMemberModel,
        SystemAuditEventModel,
        SystemAuditOutboxModel,
    )
    models = (*_ACCOUNT_SCHEMA_MODELS, AccountAuthorityGenerationModel, *publication_models)
    created = []
    source_triggers_installed = False
    generation_lock_installed = False
    generation_owner = f"publication_authority_owner_{uuid4().hex}"
    runtime_role = f"publication_runtime_{uuid4().hex}"
    runtime_password = uuid4().hex
    quoted_generation_owner = wrapper.ops.quote_name(generation_owner)
    quoted_runtime_role = wrapper.ops.quote_name(runtime_role)
    generation_owner_created = False
    runtime_role_created = False
    public_create_revoked = False
    public_had_create = False
    with django_db_blocker.unblock():
        connections["default"] = wrapper
        try:
            assert wrapper.vendor == "postgresql"
            assert wrapper.introspection.table_names() == [], "Refuse any preexisting test tables"
            public_had_create = _public_schema_had_create(wrapper)
            with wrapper.cursor() as cursor:
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            public_create_revoked = True
            with wrapper.schema_editor() as editor:
                for model in models:
                    editor.create_model(model)
                    created.append(model)
                _ACCOUNT_GENERATION_MIGRATION.seed_generation_row(apps, editor)
                _ACCOUNT_GENERATION_MIGRATION.install_source_triggers(apps, editor)
                source_triggers_installed = True
                with wrapper.cursor() as cursor:
                    cursor.execute(
                        f"CREATE ROLE {quoted_generation_owner} "
                        "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    )
                    generation_owner_created = True
                    cursor.execute(f"GRANT CREATE ON SCHEMA public TO {quoted_generation_owner}")
                    cursor.execute(
                        "ALTER TABLE public.account_authority_generation "
                        f"OWNER TO {quoted_generation_owner}"
                    )
                    for model in _ACCOUNT_SCHEMA_MODELS:
                        table_name = wrapper.ops.quote_name(model._meta.db_table)
                        cursor.execute(
                            f"ALTER TABLE public.{table_name} OWNER TO {quoted_generation_owner}"
                        )
                _ACCOUNT_GENERATION_LOCK_MIGRATION.install_generation_lock_function(apps, editor)
                generation_lock_installed = True
            with wrapper.cursor() as cursor:
                cursor.execute(f"REVOKE CREATE ON SCHEMA public FROM {quoted_generation_owner}")
                cursor.execute(
                    f"CREATE ROLE {quoted_runtime_role} LOGIN PASSWORD '{runtime_password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE"
                )
                runtime_role_created = True
            _grant_runtime_business_access(
                wrapper,
                quoted_runtime_role=quoted_runtime_role,
            )
            runtime_settings = deepcopy(settings)
            runtime_settings["USER"] = runtime_role
            runtime_settings["PASSWORD"] = runtime_password
            yield _PGProbeFactory(credentials, runtime_settings)
        finally:
            if runtime_role_created:
                with wrapper.cursor() as cursor:
                    cursor.execute(f"DROP OWNED BY {quoted_runtime_role}")
                    cursor.execute(f"DROP ROLE {quoted_runtime_role}")
            if created:
                with wrapper.schema_editor() as editor:
                    if generation_lock_installed:
                        _ACCOUNT_GENERATION_LOCK_MIGRATION.remove_generation_lock_function(
                            apps,
                            editor,
                        )
                    if source_triggers_installed:
                        _ACCOUNT_GENERATION_MIGRATION.remove_source_triggers(apps, editor)
                    for model in reversed(created):
                        editor.delete_model(model)
                assert wrapper.introspection.table_names() == []
            if generation_owner_created:
                with wrapper.cursor() as cursor:
                    cursor.execute(f"DROP OWNED BY {quoted_generation_owner}")
                    cursor.execute(f"DROP ROLE {quoted_generation_owner}")
            if public_create_revoked and public_had_create:
                with wrapper.cursor() as cursor:
                    cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
            wrapper.close()
            connections["default"] = original


@pytest.fixture
def actual_publication_pg(_actual_publication_pg_schema) -> Iterator[_PGProbeFactory]:
    """Reset only the tables created in the opted-in empty test database."""

    try:
        yield _actual_publication_pg_schema
    finally:
        wrapper = connections["default"]
        assert wrapper.vendor == "postgresql"
        assert wrapper.settings_dict["NAME"] == "agom_release_rehearsal_ci"
        models = (
            DatasetContractModel,
            DatasetProviderBindingModel,
            DatasetPublicationPolicyModel,
            DataOwnerRegistrationModel,
            AssetMasterModel,
            AssetAliasModel,
            ProviderConfigModel,
            PriceBarModel,
            QuoteSnapshotModel,
            FinancialFactModel,
            FinancialPublicationCapacityWorkflowModel,
            FinancialPublicationCapacityManifestItemModel,
            FinancialCapacityGovernanceRecordModel,
            FinancialCapacityGovernanceRevocationModel,
            FinancialCapacityOwnerApprovalEventModel,
            FinancialScopeManifestCurrentPointerModel,
            FinancialScopeCapacityImportModel,
            FinancialScopeCapacityImportConsumptionModel,
            ValuationFactModel,
            RawAuditModel,
            FinancialSourceTimeAuditClaimModel,
            CanonicalPublicationModel,
            CandidateRawAuditManifestModel,
            CandidateRawAuditManifestMemberModel,
            CanonicalPublicationPointerModel,
            CoverageSnapshotModel,
            PublicationMemberModel,
            SystemAuditEventModel,
            SystemAuditOutboxModel,
        )
        full_expected = {
            model._meta.db_table
            for model in (*_ACCOUNT_SCHEMA_MODELS, AccountAuthorityGenerationModel, *models)
        }
        full_expected.update(
            field.remote_field.through._meta.db_table
            for model in _ACCOUNT_SCHEMA_MODELS
            for field in model._meta.local_many_to_many
            if field.remote_field.through._meta.auto_created
        )
        assert set(wrapper.introspection.table_names()) == full_expected
        names = ", ".join(wrapper.ops.quote_name(name) for name in sorted(full_expected))
        with wrapper.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY")
        with wrapper.schema_editor() as editor:
            _ACCOUNT_GENERATION_MIGRATION.seed_generation_row(apps, editor)


@pytest.fixture
def activation_runtime_pg(actual_publication_pg) -> Iterator[_PGProbeFactory]:
    """Run activation through a fresh least-privilege runtime connection."""

    admin_wrapper = connections["default"]
    runtime_wrapper = actual_publication_pg.runtime_wrapper()
    connections["default"] = runtime_wrapper
    try:
        runtime_wrapper.ensure_connection()
        yield actual_publication_pg
    finally:
        runtime_wrapper.close()
        connections["default"] = admin_wrapper


def _probe_update(probe, fact_pk: str) -> None:
    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    probe.execute("UPDATE data_center_valuation_fact SET pe_ttm=99 WHERE id=%s", [fact_pk])


_ACTIVATION_SOAK_MEMBER_COUNT = 5_001
_ACTIVATION_SOAK_MAX_QUERIES = 35
_ACTIVATION_SOAK_MAX_HELD_SECONDS = 2.0
_ACTIVATION_SOAK_MAX_LOCK_WAIT_SECONDS = 0.25


def _production_activation_fence() -> tuple[
    AccountAuthorityFinalRevalidatorV3,
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
]:
    """Capture a proof for the production Account complete RC/RW fence implementation."""

    from tests.component.account.test_account_authority_final_revalidator_v3_postgres import (
        _complete_finalizer,
    )

    finalizer, command, scan, _reader = _complete_finalizer("default")
    if not isinstance(command, GetCurrentOwnerTenantAuthorityV3Command):
        raise AssertionError("Account complete-fence command has an invalid type")
    proof = finalizer.capture_complete(command, scan)
    return finalizer, proof


class _PostgresActivationAuditWriter:
    """Audit-owned caller-transaction writer used by the soak."""

    def __init__(self) -> None:
        self.coordinator = DjangoSystemAuditEventOutboxCoordinator()
        self._adapter = DjangoPublicationActivationAuditWriter(self.coordinator)

    @property
    def database_alias(self) -> str:
        return self._adapter.database_alias

    def append_required(self, *, observation, **_kwargs):
        return self._adapter.append_required(
            request=_kwargs["request"],
            publication=_kwargs["publication"],
            members=_kwargs["members"],
            observation=observation,
        )

    def append_manifest_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        manifest: CandidateRawAuditManifest,
        observation: DataPublicationManifestAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        return self._adapter.append_manifest_required(
            request=request,
            publication=publication,
            members=members,
            manifest=manifest,
            observation=observation,
        )

    def append_manifest_group_required(self, *, request, writes):
        return self._adapter.append_manifest_group_required(
            request=request,
            writes=writes,
        )


def _build_activation_soak_snapshot(
    *,
    valuation_member_count: int = _ACTIVATION_SOAK_MEMBER_COUNT,
    activation_id: str = "activation-group-soak-1",
) -> tuple[
    PublicationActivationGroupRequest,
    dict[str, str],
    dict[str, str],
]:
    """Build one 5,001-member valuation plus quote and price group candidates."""

    datasets = (
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.valuation.fact",
    )
    repository = DjangoPublicationActivationRepository()
    manifest_repository = DjangoCandidateRawAuditManifestRepository()
    candidate_ids: dict[str, str] = {}
    raw_audit_ids: dict[str, str] = {}
    group_candidates: list[PublicationActivationGroupCandidate] = []
    for dataset_key in datasets:
        valuation_count = valuation_member_count
        member_count = valuation_count if dataset_key == "equity.valuation.fact" else 1
        observed_at = timezone.now() - timedelta(minutes=5)
        policy = PublicationPolicy(
            dataset=DatasetKey(dataset_key, "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=(
                "source",
                "observed_at",
                "fetched_at",
                "source_record_id",
                "fact_content_hash",
            ),
            retention_days=3650,
            policy_version="activation-soak",
        )
        PublicationPolicyRepository().save(policy)
        run_id = uuid4()
        ingested_run_id = uuid4()
        batch_token = uuid4().hex[:6].upper()
        if dataset_key == "equity.valuation.fact":
            ValuationFactModel.objects.bulk_create(
                [
                    ValuationFactModel(
                        asset_code=f"SOAKV{batch_token}{i:06d}.SZ",
                        val_date=observed_at.date(),
                        pe_ttm=12 + (i % 100) / 10,
                        source="soak",
                        observed_at=observed_at,
                        available_at=observed_at,
                        fetched_at=observed_at,
                        extra={"raw_payload_scope": "batch_response_body"},
                        source_record_id=f"soak-record-{i}",
                        raw_payload_hash="a" * 64,
                        quality_status="accepted",
                        revision_number=1,
                        ingested_run_id=ingested_run_id,
                    )
                    for i in range(member_count)
                ],
                batch_size=1000,
            )
            fact_model = ValuationFactModel
        elif dataset_key == "equity.quote.snapshot":
            QuoteSnapshotModel.objects.create(
                asset_code=f"SOAKQ{uuid4().hex[:8].upper()}.SZ",
                snapshot_at=observed_at,
                fetched_at=observed_at,
                current_price=1,
                source="soak",
                source_record_id="soak-quote-record",
                raw_payload_hash="a" * 64,
                quality_status="accepted",
                revision_number=1,
                ingested_run_id=ingested_run_id,
            )
            fact_model = QuoteSnapshotModel
        else:
            PriceBarModel.objects.create(
                asset_code=f"SOAKP{uuid4().hex[:8].upper()}.SZ",
                bar_date=(observed_at - timedelta(days=1)).date(),
                freq="1d",
                adjustment="none",
                open=1,
                high=1,
                low=1,
                close=1,
                source="soak",
                source_record_id="soak-price-record",
                raw_payload_hash="a" * 64,
                quality_status="accepted",
                revision_number=1,
                ingested_run_id=ingested_run_id,
            )
            fact_model = PriceBarModel
        fact_rows = list(fact_model.objects.filter(ingested_run_id=ingested_run_id).order_by("pk"))
        assert len(fact_rows) == member_count
        references = [
            publication_fact_reference_for_dataset(row, dataset_key=dataset_key)
            for row in fact_rows
        ]
        publication_id = str(uuid4())
        members = tuple(
            publication_member_from_reference(
                reference,
                member_id=str(uuid4()),
                publication_id=publication_id,
                dataset_key=dataset_key,
            )
            for reference in references
        )
        capability = canonical_capability_for_publication_dataset(dataset_key)
        assert capability is not None
        raw = RawAuditRepository().log(
            RawAudit(
                provider_name="soak-provider-adapter",
                capability=capability,
                request_params={"dataset_key": dataset_key, "member_count": member_count},
                status="ok",
                row_count=member_count,
                fetched_at=timezone.now(),
                run_id=str(run_id),
                ingested_run_id=str(ingested_run_id),
                response_payload_hash="b" * 64,
                schema_fingerprint="c" * 64,
                parser_version="activation-soak",
                extra={"source_type": "soak"},
            )
        )
        publication_as_of = timezone.now()
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=dataset_key,
            publication_key="current",
            policy_version=policy.identity,
            state=PublicationState.CANDIDATE,
            selected_source="soak",
            publication_hash=publication_hash(references, policy_identity=policy.identity),
            coverage=CoverageSnapshot(
                coverage_id=str(uuid4()),
                publication_id=publication_id,
                requested_count=member_count,
                eligible_count=member_count,
                selected_count=member_count,
                missing_count=0,
                conflict_count=0,
                generated_at=publication_as_of,
            ),
            member_count=member_count,
            as_of=publication_as_of,
            created_by="test.activation.group-soak",
            run_id=str(run_id),
        )
        repository.stage_candidate_with_members(publication, members)
        raw_reference = CandidateRawAuditReference(
            raw_audit_id=raw.raw_audit_id,
            version="1",
            content_hash=raw.content_hash,
            provider_name=raw.provider_name,
            capability=raw.capability,
            run_id=raw.run_id,
            ingested_run_id=raw.ingested_run_id,
        )
        manifest = CandidateRawAuditManifest.create(
            publication_id=publication.publication_id,
            publication_hash=publication.publication_hash,
            run_id=publication.run_id,
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            task_attempt_id="activation-soak-" + uuid4().hex,
            raw_audits=(raw_reference,),
        )
        manifest_repository.stage(manifest)
        candidate_ids[dataset_key] = publication_id
        raw_audit_ids[dataset_key] = raw.raw_audit_id
        group_candidates.append(
            PublicationActivationGroupCandidate(
                dataset_key=dataset_key,
                publication_key="current",
                candidate_publication_id=publication_id,
                candidate_publication_hash=publication.publication_hash,
            )
        )
    return (
        PublicationActivationGroupRequest(
            activation_id=activation_id,
            candidates=tuple(group_candidates),
        ),
        candidate_ids,
        raw_audit_ids,
    )


def test_activation_5001_members_has_fixed_queries_locks_and_retry(
    activation_runtime_pg,
) -> None:
    """Exercise one three-dataset RC/RW activation with 5,001 valuation members."""

    request, candidate_ids, raw_audit_ids = _build_activation_soak_snapshot()
    repository = DjangoPublicationActivationRepository()
    writer = _PostgresActivationAuditWriter()
    authority_fence, authority_proof = _production_activation_fence()
    lock_timing: dict[str, float] = {}

    def capture_generation_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if "account_authority_generation_lock()" in sql:
            lock_timing["acquired_at"] = monotonic()
        return result

    with connections["default"].execute_wrapper(capture_generation_lock):
        with CaptureQueriesContext(connections["default"]) as captured:
            activated = ActivateCanonicalPublicationGroupUseCase(repository).execute(
                request,
                audit_writer=writer,
                authority_fence=authority_fence,
                authority_proof=authority_proof,
            )
    held_seconds = monotonic() - lock_timing["acquired_at"]

    assert {item.publication_id for item in activated} == set(candidate_ids.values())
    query_count = len(captured.captured_queries)
    assert query_count <= _ACTIVATION_SOAK_MAX_QUERIES, (
        f"activation query count {query_count} exceeds " f"{_ACTIVATION_SOAK_MAX_QUERIES}"
    )
    assert held_seconds <= _ACTIVATION_SOAK_MAX_HELD_SECONDS, (
        f"activation held locks for {held_seconds:.6f}s across {query_count} queries; "
        f"limit is {_ACTIVATION_SOAK_MAX_HELD_SECONDS:.6f}s"
    )
    assert PublicationMemberModel._default_manager.count() == _ACTIVATION_SOAK_MEMBER_COUNT + 2
    for dataset_key, publication_id in candidate_ids.items():
        pointer = CanonicalPublicationPointerModel._default_manager.get(
            dataset_key=dataset_key,
            publication_key="current",
        )
        assert str(pointer.publication_id) == publication_id
        assert pointer.activation_id == request.activation_id
        assert RawAuditModel._default_manager.filter(pk=raw_audit_ids[dataset_key]).exists()
    assert SystemAuditEventModel._default_manager.count() == 3
    assert SystemAuditOutboxModel._default_manager.count() == 3

    retry_fence, retry_proof = _production_activation_fence()
    ActivateCanonicalPublicationGroupUseCase(repository).execute(
        request,
        audit_writer=_PostgresActivationAuditWriter(),
        authority_fence=retry_fence,
        authority_proof=retry_proof,
    )
    assert SystemAuditEventModel._default_manager.count() == 3
    assert SystemAuditOutboxModel._default_manager.count() == 3

    probe = activation_runtime_pg.connect()
    try:
        probe.execute("BEGIN")
        pointer_predicates = " OR ".join(
            "(dataset_key=%s AND publication_key=%s)" for _item in request.candidates
        )
        pointer_parameters = tuple(
            value
            for item in request.candidates
            for value in (item.dataset_key, item.publication_key)
        )
        probe.execute(
            f"""
            SELECT pointer_id
            FROM data_center_canonical_publication_pointer
            WHERE {pointer_predicates}
            ORDER BY dataset_key, publication_key
            FOR UPDATE
            """,
            pointer_parameters,
        )
        with connections["default"].cursor() as cursor:
            cursor.execute("SET lock_timeout = '150ms'")
        blocked_fence, blocked_proof = _production_activation_fence()
        blocked_started = monotonic()
        with pytest.raises(AccountAuthorityFinalRevalidationUnavailable) as blocked_error:
            ActivateCanonicalPublicationGroupUseCase(repository).execute(
                request,
                audit_writer=_PostgresActivationAuditWriter(),
                authority_fence=blocked_fence,
                authority_proof=blocked_proof,
            )
        assert isinstance(blocked_error.value.__cause__, OperationalError)
        lock_wait_seconds = monotonic() - blocked_started
        assert lock_wait_seconds <= _ACTIVATION_SOAK_MAX_LOCK_WAIT_SECONDS, (
            f"group pointer lock wait {lock_wait_seconds:.6f}s exceeds "
            f"{_ACTIVATION_SOAK_MAX_LOCK_WAIT_SECONDS:.6f}s"
        )
    finally:
        with connections["default"].cursor() as cursor:
            cursor.execute("SET lock_timeout = '0'")
        probe.rollback()
        probe.close()


def test_concurrent_group_activations_have_one_cas_winner(activation_runtime_pg) -> None:
    """Race two complete groups and require one winner without deadlock or partial state."""

    first_request, first_ids, _first_audits = _build_activation_soak_snapshot(
        valuation_member_count=1,
        activation_id="activation-group-race-a",
    )
    second_request, second_ids, _second_audits = _build_activation_soak_snapshot(
        valuation_member_count=1,
        activation_id="activation-group-race-b",
    )
    settings = deepcopy(connections["default"].settings_dict)
    barrier = Barrier(2)

    def activate(request: PublicationActivationGroupRequest) -> tuple[str, str]:
        previous_connection = connections["default"]
        worker_connection = load_backend(settings["ENGINE"]).DatabaseWrapper(
            deepcopy(settings), alias="default"
        )
        connections["default"] = worker_connection
        try:
            barrier.wait(timeout=10)
            authority_fence, authority_proof = _production_activation_fence()
            result = ActivateCanonicalPublicationGroupUseCase(
                DjangoPublicationActivationRepository()
            ).execute(
                request,
                audit_writer=_PostgresActivationAuditWriter(),
                authority_fence=authority_fence,
                authority_proof=authority_proof,
            )
            return "published", ",".join(item.publication_id for item in result)
        except PublicationActivationError as error:
            return "rejected", str(error)
        finally:
            worker_connection.close()
            connections["default"] = previous_connection

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result(timeout=45)
            for future in (
                executor.submit(activate, first_request),
                executor.submit(activate, second_request),
            )
        )
    winners = [result for outcome, result in outcomes if outcome == "published"]
    rejected = [result for outcome, result in outcomes if outcome == "rejected"]
    assert len(winners) == 1
    assert len(rejected) == 1
    assert "compare-and-swap" in rejected[0]
    winner_ids = set(winners[0].split(","))
    assert winner_ids in (set(first_ids.values()), set(second_ids.values()))
    for request in (first_request, second_request):
        current_ids = {
            str(
                CanonicalPublicationPointerModel._default_manager.get(
                    dataset_key=item.dataset_key,
                    publication_key=item.publication_key,
                ).publication_id
            )
            for item in request.candidates
        }
        assert current_ids == winner_ids
    assert (
        CanonicalPublicationModel._default_manager.filter(
            publication_id__in=winner_ids,
            state=PublicationState.PUBLISHED.value,
        ).count()
        == 3
    )
    assert SystemAuditEventModel._default_manager.count() == 3
    assert SystemAuditOutboxModel._default_manager.count() == 3


def test_connected_database_identity_returns_real_postgres_address_without_cidr(
    actual_publication_pg,
    monkeypatch,
) -> None:
    """Both endpoint guards must return the real host address without a CIDR mask."""
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from scripts import manage_vps_migrations as migration_runner

    del actual_publication_pg
    database_name, server_address, server_port = runner._connected_database_identity()
    configured = connections["default"].settings_dict

    assert database_name == configured["NAME"]
    assert "/" not in server_address
    ipaddress.ip_address(server_address)
    assert server_port == 5432

    monkeypatch.setenv("AGOM_S6_ISOLATED_DATABASE_MIGRATION", "1")
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_NAME", str(database_name))
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_HOST", "agom-s6-postgres-contract-test")
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_CONTAINER_ID", "a" * 64)
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_ADDRESS", server_address)
    monkeypatch.setenv(
        "AGOM_S6_MIGRATION_RESULT_PATH",
        migration_runner._S6_MIGRATION_RESULT_PATH,
    )
    monkeypatch.setattr(runner, "assert_isolated_rehearsal_database", lambda **kwargs: None)

    assert migration_runner._assert_s6_rehearsal_scope() == (server_port, server_address)


def test_market_rehearsal_database_enforces_read_only_on_provider_write(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from types import SimpleNamespace

    from django.db import DatabaseError

    from apps.data_center.domain.target_date_universe import TargetDateAssetUniverseScope
    from apps.data_center.infrastructure import market_rehearsal_runner as runner

    class Provider:
        def fetch_quote_snapshots_for_session(self, codes, target_trade_date):
            pytest.fail("must abort after database-enforced read-only rejection")

        def fetch_current_valuations(self, codes, as_of_date):
            with connections["default"].cursor() as cursor:
                cursor.execute("UPDATE data_center_valuation_fact SET pe_ttm=99")
            pytest.fail("PostgreSQL must reject a business write even with no rows")

    monkeypatch.setattr(runner, "market_rehearsal_source_digest", lambda root: "b" * 64)
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    monkeypatch.setattr(runner, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    monkeypatch.setattr(runner, "latest_completed_cn_market_session", lambda now: date(2026, 9, 24))
    monkeypatch.setattr(
        runner,
        "build_target_date_a_share_universe_scope",
        lambda target_date: TargetDateAssetUniverseScope(
            target_date=target_date,
            candidate_codes=("000001.SZ",),
            requested_codes=("000001.SZ",),
            excluded_not_yet_listed=(),
            unknown_listing_date_codes=("000001.SZ",),
        ),
    )
    monkeypatch.setattr(
        runner, "get_provider_registry", lambda: SimpleNamespace(get_by_id=lambda _: Provider())
    )
    with pytest.raises(DatabaseError, match="read-only"):
        runner.run_market_provider_rehearsal(
            quote_provider_id=1,
            valuation_provider_id=2,
            candidate_sha="a" * 40,
            source_root=tmp_path,
        )
    assert ValuationFactModel.objects.count() == 0
    with connections["default"].cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        assert cursor.fetchone()[0] == "off"


def test_isolated_write_preflight_database_enforces_read_only(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from core.exceptions import DataFetchError

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )

    def attempted_write() -> str:
        with connections["default"].cursor() as cursor:
            cursor.execute("UPDATE data_center_valuation_fact SET pe_ttm = 99")
        pytest.fail("PostgreSQL must reject a preflight write even with no matching rows")

    monkeypatch.setattr(runner, "_database_identity", attempted_write)
    before = _isolated_write_table_counts()

    with pytest.raises(DataFetchError) as exc_info:
        runner.preflight_isolated_write_rehearsal(
            candidate_sha="a" * 40,
            source_root=tmp_path,
            expected_database_name="agom_release_rehearsal_ci",
            expected_database_host=str(connections["default"].settings_dict["HOST"]),
            require_ephemeral_host=False,
        )

    assert exc_info.value.code == "REHEARSAL_WRITE_PREFLIGHT_READ_ONLY_VIOLATION"
    assert _isolated_write_table_counts() == before
    with connections["default"].cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        assert cursor.fetchone()[0] == "off"


def test_isolated_write_rehearsal_uses_production_publication_and_rolls_back(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    source = tmp_path / "source"
    source.mkdir()
    candidate = "c" * 40
    (source / ".agom-build-identity.json").write_text(
        json.dumps({"schema_version": 1, "source_commit": candidate}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", "sha256:" + "f" * 64)
    DatasetContractModel.objects.create(
        dataset_key="equity.valuation.fact",
        contract_version="1.0",
        schema_version="1.0",
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=[{"name": "observed_at", "type": "datetime", "nullable": False}],
        freshness_seconds=172800,
    )
    DatasetPublicationPolicyModel.objects.create(
        dataset_key="equity.valuation.fact",
        contract_version="1.0",
        schema_version="1.0",
        policy_version="component-production",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=[
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        ],
        retention_days=30,
    )
    prior_published_at = timezone.now() - timedelta(minutes=1)
    prior_publication = CanonicalPublicationModel.objects.create(
        dataset_key="equity.valuation.fact",
        publication_key="current",
        policy_version="component-production",
        state=PublicationState.PUBLISHED.value,
        selected_source="component-existing",
        publication_hash="e" * 64,
        member_count=1,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        as_of=prior_published_at,
        published_at=prior_published_at,
    )
    PublicationMemberModel.objects.create(
        publication_id=prior_publication.publication_id,
        dataset_key="equity.valuation.fact",
        natural_key="component-existing",
        source="component-existing",
        source_record_id="component-existing",
        fact_table=ValuationFactModel._meta.db_table,
        fact_pk="component-existing",
        observed_at=prior_published_at,
        raw_payload_hash="c" * 64,
        available_at=prior_published_at,
        fetched_at=prior_published_at,
        raw_payload_scope="record",
        fact_content_hash="b" * 64,
    )
    CoverageSnapshotModel.objects.create(
        publication_id=prior_publication.publication_id,
        requested_count=1,
        eligible_count=1,
        selected_count=1,
        missing_count=0,
        conflict_count=0,
        generated_at=prior_published_at,
    )
    prior_pointer = CanonicalPublicationPointerModel.objects.create(
        dataset_key="equity.valuation.fact",
        publication_key="current",
        publication_id=prior_publication.publication_id,
        publication_hash=prior_publication.publication_hash,
        activation_id="component-existing",
    )

    class MigrationExecutor:
        loader = type(
            "Loader",
            (),
            {"graph": type("Graph", (), {"leaf_nodes": lambda self: []})()},
        )()

        def __init__(self, _connection) -> None:
            pass

        def migration_plan(self, _leaves):
            return []

    class MigrationRecorder:
        def __init__(self, _connection) -> None:
            pass

        def applied_migrations(self):
            return {("data_center", "fixture")}

    monkeypatch.setattr(runner, "MigrationExecutor", MigrationExecutor)
    monkeypatch.setattr(runner, "MigrationRecorder", MigrationRecorder)

    report = runner.collect_isolated_write_rehearsal(
        candidate_sha=candidate,
        target_trade_date=date.today() - timedelta(days=7),
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        output_dir=tmp_path / "evidence",
        source_root=source,
        expected_database_name="agom_release_rehearsal_ci",
        expected_database_host=str(connections["default"].settings_dict["HOST"]),
    )

    receipt = json.loads(
        (tmp_path / "evidence" / "isolated-write-receipt.json").read_text(encoding="utf-8")
    )
    assert report["outcome"] == "success"
    assert receipt["publication_verified"] is True
    assert receipt["readback_verified"] is True
    assert receipt["exact_member_fact_readback_verified"] is True
    assert receipt["legacy_current_fail_closed_verified"] is True
    assert receipt["current_pointer_preserved_verified"] is True
    assert receipt["current_pointer_rollback_verified"] is True
    assert receipt["publication_graph_rollback_verified"] is True
    assert receipt["publication_clock_source"] == "database_clock_timestamp"
    assert receipt["publication_clock_cutoff"] == receipt["publication_published_at"]
    assert receipt["prior_current_published_at"] == prior_published_at.isoformat()
    assert receipt["current_time_stale_expected"] is True
    assert receipt["current_time_freshness_guard_verified"] is True
    assert receipt["tamper_guard_verified"] is True
    assert receipt["rollback_verified"] is True
    assert receipt["residual_rows"] == 0
    assert receipt["written_rows"] == 4
    assert receipt["publication_id"] == report["publication_id"]
    assert len(receipt["member_fact_content_hash"]) == 64
    assert len(receipt["catalog_seed_sha256"]) == 64
    prior_publication.refresh_from_db()
    prior_pointer.refresh_from_db()
    assert prior_publication.state == PublicationState.PUBLISHED.value
    assert prior_publication.superseded_at is None
    assert prior_pointer.publication_id == prior_publication.publication_id
    assert prior_pointer.publication_hash == prior_publication.publication_hash
    assert prior_pointer.activation_id == "component-existing"
    assert ValuationFactModel.objects.count() == 0
    assert CanonicalPublicationModel.objects.count() == 1
    assert PublicationMemberModel.objects.count() == 1
    assert CoverageSnapshotModel.objects.count() == 1
    assert CanonicalPublicationPointerModel.objects.count() == 1


def test_isolated_write_publication_clock_rejects_future_current_publication(
    actual_publication_pg,
) -> None:
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from core.exceptions import DataFetchError

    del actual_publication_pg
    future_published_at = timezone.now() + timedelta(days=1)
    CanonicalPublicationModel.objects.create(
        dataset_key="equity.valuation.fact",
        publication_key="current",
        policy_version="component-production",
        state=PublicationState.PUBLISHED.value,
        selected_source="component-future",
        publication_hash="d" * 64,
        member_count=0,
        as_of=future_published_at,
        published_at=future_published_at,
    )

    with pytest.raises(DataFetchError) as exc_info:
        runner._publication_clock_cutoff(
            dataset_key="equity.valuation.fact",
            publication_key="current",
        )

    assert exc_info.value.code == "REHEARSAL_WRITE_PUBLICATION_CLOCK_INVALID"
    assert CanonicalPublicationModel.objects.count() == 1
    assert CanonicalPublicationPointerModel.objects.count() == 0


def test_isolated_write_command_initializes_reviewed_catalog_and_rolls_back_business_rows(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from django.conf import settings
    from django.core.management import call_command

    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    _allow_component_migration_snapshot(monkeypatch, runner)
    monkeypatch.setattr(settings, "BASE_DIR", Path(__file__).resolve().parents[3], raising=False)
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    output_dir = tmp_path / "initialized-evidence"

    call_command(
        "rehearse_isolated_publication_write",
        candidate_sha="d" * 40,
        target_trade_date=date.today() - timedelta(days=1),
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        expected_database_name="agom_release_rehearsal_ci",
        expected_database_host=str(connections["default"].settings_dict["HOST"]),
        initialize_reviewed_catalog=True,
        output_dir=output_dir,
        verbosity=0,
    )

    report = json.loads((output_dir / "isolated-write-rehearsal.json").read_text(encoding="utf-8"))
    assert report["outcome"] == "success"
    assert report["written_rows"] == 4
    assert report["rollback_verified"] is True
    assert report["residual_rows"] == 0
    assert DatasetContractModel.objects.count() > 0
    assert DatasetProviderBindingModel.objects.count() > 0
    assert DatasetPublicationPolicyModel.objects.count() > 0
    assert DataOwnerRegistrationModel.objects.count() > 0
    assert ValuationFactModel.objects.count() == 0
    assert CanonicalPublicationModel.objects.count() == 0
    assert PublicationMemberModel.objects.count() == 0
    assert CoverageSnapshotModel.objects.count() == 0


def test_isolated_write_command_without_catalog_initialization_fails_closed(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from django.conf import settings
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    _allow_component_migration_snapshot(monkeypatch, runner)
    monkeypatch.setattr(settings, "BASE_DIR", Path(__file__).resolve().parents[3], raising=False)
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    output_dir = tmp_path / "missing-catalog-evidence"

    with pytest.raises(CommandError, match="REHEARSAL_WRITE_CATALOG_UNAVAILABLE"):
        call_command(
            "rehearse_isolated_publication_write",
            candidate_sha="e" * 40,
            target_trade_date=date.today() - timedelta(days=1),
            universe_sha256="a" * 64,
            provider_identities_sha256="b" * 64,
            expected_database_name="agom_release_rehearsal_ci",
            expected_database_host=str(connections["default"].settings_dict["HOST"]),
            output_dir=output_dir,
            verbosity=0,
        )

    assert DatasetContractModel.objects.count() == 0
    assert DatasetProviderBindingModel.objects.count() == 0
    assert DatasetPublicationPolicyModel.objects.count() == 0
    assert DataOwnerRegistrationModel.objects.count() == 0
    assert ValuationFactModel.objects.count() == 0
    assert CanonicalPublicationModel.objects.count() == 0
    assert PublicationMemberModel.objects.count() == 0
    assert CoverageSnapshotModel.objects.count() == 0
    assert not output_dir.exists()


def _isolated_write_arguments(tmp_path) -> dict[str, object]:
    source = tmp_path / "candidate"
    source.mkdir()
    return {
        "candidate_sha": "c" * 40,
        "target_trade_date": date.today() - timedelta(days=1),
        "universe_sha256": "a" * 64,
        "provider_identities_sha256": "b" * 64,
        "output_dir": tmp_path / "evidence",
        "source_root": source,
        "expected_database_name": "agom_release_rehearsal_ci",
        "expected_database_host": str(connections["default"].settings_dict["HOST"]),
    }


def _allow_component_loopback_scope(monkeypatch, runner) -> None:
    """Keep component coverage on its separately guarded empty loopback database."""
    _database_name, server_address, server_port = runner._connected_database_identity()
    monkeypatch.setitem(runner.connection.settings_dict, "PORT", str(server_port))

    def assert_loopback_scope(
        *,
        expected_database_name: str,
        expected_database_host: str,
        require_ephemeral_host: bool = False,
    ) -> None:
        del require_ephemeral_host
        runner._assert_isolated_database(
            expected_database_name=expected_database_name,
            expected_database_host=expected_database_host,
            require_ephemeral_host=False,
        )

    monkeypatch.setattr(runner, "assert_isolated_rehearsal_database", assert_loopback_scope)
    monkeypatch.setattr(
        runner,
        "_resolved_host_addresses",
        lambda _host, _port: {server_address},
    )


def _isolated_write_table_counts() -> tuple[int, ...]:
    return (
        DatasetContractModel.objects.count(),
        DatasetPublicationPolicyModel.objects.count(),
        ValuationFactModel.objects.count(),
        CanonicalPublicationModel.objects.count(),
        PublicationMemberModel.objects.count(),
        CoverageSnapshotModel.objects.count(),
    )


@pytest.mark.parametrize(
    "invalid_scope", ["non_postgresql", "wrong_database", "env_missing", "atomic"]
)
def test_isolated_write_rehearsal_scope_guards_leave_real_pg_tables_unchanged(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
    invalid_scope: str,
) -> None:
    from types import SimpleNamespace

    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from core.exceptions import DataFetchError

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    output_dir = tmp_path / "evidence"
    real_connection = connections["default"]
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    if invalid_scope == "non_postgresql":
        monkeypatch.setattr(
            runner,
            "connection",
            SimpleNamespace(
                vendor="sqlite",
                in_atomic_block=False,
                settings_dict={"NAME": "agom_release_rehearsal_ci"},
            ),
        )
    elif invalid_scope == "wrong_database":
        monkeypatch.setattr(
            runner,
            "connection",
            SimpleNamespace(
                vendor="postgresql",
                in_atomic_block=False,
                settings_dict={"NAME": "production"},
            ),
        )
    else:
        monkeypatch.setattr(runner, "connection", real_connection)
    if invalid_scope == "env_missing":
        monkeypatch.delenv("AGOM_RELEASE_REHEARSAL_DATABASE", raising=False)

    before = _isolated_write_table_counts()
    arguments = _isolated_write_arguments(tmp_path)
    if invalid_scope == "atomic":
        with transaction.atomic():
            with pytest.raises(DataFetchError) as exc_info:
                runner.collect_isolated_write_rehearsal(**arguments)
    else:
        with pytest.raises(DataFetchError) as exc_info:
            runner.collect_isolated_write_rehearsal(**arguments)

    expected_codes = {
        "non_postgresql": "REHEARSAL_WRITE_SCOPE_VENDOR_INVALID",
        "wrong_database": "REHEARSAL_WRITE_SCOPE_DATABASE_NAME_INVALID",
        "env_missing": "REHEARSAL_WRITE_SCOPE_OPT_IN_MISSING",
        "atomic": "REHEARSAL_WRITE_SCOPE_TRANSACTION_ACTIVE",
    }
    assert exc_info.value.code == expected_codes[invalid_scope]
    assert _isolated_write_table_counts() == before
    assert not output_dir.exists()


def test_isolated_write_rehearsal_rejects_real_pending_migrations_before_any_write(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
) -> None:
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from core.exceptions import DataFetchError

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    before = _isolated_write_table_counts()
    arguments = _isolated_write_arguments(tmp_path)

    with pytest.raises(DataFetchError) as exc_info:
        runner.collect_isolated_write_rehearsal(**arguments)

    assert exc_info.value.code == "REHEARSAL_WRITE_MIGRATIONS_PENDING"
    assert _isolated_write_table_counts() == before
    assert not arguments["output_dir"].exists()


def _allow_component_migration_snapshot(monkeypatch, runner) -> None:
    class MigrationExecutor:
        loader = type(
            "Loader",
            (),
            {"graph": type("Graph", (), {"leaf_nodes": lambda self: []})()},
        )()

        def __init__(self, _connection) -> None:
            pass

        def migration_plan(self, _leaves):
            return []

    class MigrationRecorder:
        def __init__(self, _connection) -> None:
            pass

        def applied_migrations(self):
            return {("data_center", "fixture")}

    monkeypatch.setattr(runner, "MigrationExecutor", MigrationExecutor)
    monkeypatch.setattr(runner, "MigrationRecorder", MigrationRecorder)


@pytest.mark.parametrize(
    ("catalog_state", "expected_catalog_counts"),
    [
        ("both_missing", (0, 0)),
        ("contract_missing", (0, 1)),
        ("policy_missing", (1, 0)),
        ("version_mismatch", (1, 1)),
    ],
)
def test_isolated_write_rehearsal_catalog_failures_are_read_only_and_leave_no_residue(
    actual_publication_pg,
    monkeypatch,
    tmp_path,
    catalog_state: str,
    expected_catalog_counts: tuple[int, int],
) -> None:
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
    from core.exceptions import DataFetchError

    del actual_publication_pg
    _allow_component_loopback_scope(monkeypatch, runner)
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    _allow_component_migration_snapshot(monkeypatch, runner)
    if catalog_state in {"policy_missing", "version_mismatch"}:
        contract_version = "1.0"
        DatasetContractModel.objects.create(
            dataset_key="equity.valuation.fact",
            contract_version=contract_version,
            schema_version="1.0",
            owner="data-platform",
            frequency="daily",
            decision_critical=True,
            fields=[{"name": "observed_at", "type": "datetime", "nullable": False}],
            freshness_seconds=604800,
        )
    if catalog_state in {"contract_missing", "version_mismatch"}:
        policy_contract_version = "2.0" if catalog_state == "version_mismatch" else "1.0"
        DatasetPublicationPolicyModel.objects.create(
            dataset_key="equity.valuation.fact",
            contract_version=policy_contract_version,
            schema_version="1.0",
            policy_version="component-negative",
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=["observed_at", "available_at", "fetched_at"],
            retention_days=30,
        )
    before = _isolated_write_table_counts()
    assert before[:2] == expected_catalog_counts
    arguments = _isolated_write_arguments(tmp_path)

    with pytest.raises(DataFetchError) as exc_info:
        runner.collect_isolated_write_rehearsal(**arguments)

    assert exc_info.value.code == "REHEARSAL_WRITE_CATALOG_UNAVAILABLE"
    assert _isolated_write_table_counts() == before
    assert before[2:] == (0, 0, 0, 0)
    assert not arguments["output_dir"].exists()


def _probe_write(probe, statement: str, params: Sequence[object]) -> None:
    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    probe.execute(statement, params)


def _assert_probe_write_blocked(
    probe,
    statement: str,
    params: Sequence[object],
) -> None:
    with pytest.raises(psycopg.errors.LockNotAvailable) as locked:
        _probe_write(probe, statement, params)
    assert locked.value.sqlstate == "55P03"
    probe.rollback()


def test_outer_read_only_snapshot_keeps_gate_and_rows_consistent_after_concurrent_commit(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with consistent_publication_read("equity.valuation.fact"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            assert cursor.fetchone() == ("repeatable read",)
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone() == ("on",)
        first = query_published_valuation_facts("000001.SZ")
        with actual_publication_pg.connect() as probe:
            probe.execute(
                "UPDATE data_center_valuation_fact SET pe_ttm=99 WHERE id=%s", [member.fact_pk]
            )
        second = query_published_valuation_facts("000001.SZ")
        assert first["must_not_use_for_decision"] is False
        assert second["rows"] == first["rows"]
        assert second["rows"][0]["pe_ttm"] == 12.5
    assert (
        query_published_valuation_facts("000001.SZ")["blocked_reason"]
        == "publication_member_fact_changed"
    )


def test_nested_read_committed_locks_remain_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            with pytest.raises(psycopg.errors.LockNotAvailable) as locked:
                _probe_update(probe, member.fact_pk)
            assert locked.value.sqlstate == "55P03"
            probe.rollback()
            assert query_published_valuation_facts("000001.SZ")["rows"][0]["pe_ttm"] == 12.5
        _probe_update(probe, member.fact_pk)
    assert query_published_valuation_facts("000001.SZ")["rows"] == []


def test_nested_read_committed_locks_dataset_contract_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    dataset_key = "equity.valuation.fact"
    contract_version = f"probe-{uuid4().hex}"
    statement = """
        INSERT INTO data_center_dataset_contract (
            dataset_key,
            contract_version,
            schema_version,
            owner,
            frequency,
            decision_critical,
            fields,
            freshness_seconds,
            comparable_group,
            active,
            created_at,
            updated_at
        ) VALUES (%s, %s, %s, %s, %s, TRUE, %s::jsonb, %s, %s, TRUE,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    params = (
        dataset_key,
        contract_version,
        "1.0",
        "probe",
        "daily",
        '[{"name":"observed_at","value_type":"datetime"}]',
        3600,
        "",
    )
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, params)
        _probe_write(probe, statement, params)
        assert probe.execute(
            "SELECT contract_version FROM data_center_dataset_contract "
            "WHERE dataset_key=%s AND contract_version=%s",
            [dataset_key, contract_version],
        ).fetchone() == (contract_version,)


def test_nested_read_committed_locks_asset_master_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    asset_code = f"999{uuid4().hex[:8]}.SH"
    statement = """
        INSERT INTO data_center_asset_master (
            code,
            name,
            short_name,
            asset_type,
            exchange,
            is_active,
            list_date,
            delist_date,
            sector,
            industry,
            currency,
            total_shares,
            extra,
            created_at,
            updated_at
        ) VALUES (%s, 'Probe Asset', 'Probe', 'stock', 'SSE', TRUE,
                  NULL, NULL, '', '', 'CNY', NULL, '{}'::jsonb,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, [asset_code])
        _probe_write(probe, statement, [asset_code])
        assert probe.execute(
            "SELECT code FROM data_center_asset_master WHERE code=%s",
            [asset_code],
        ).fetchone() == (asset_code,)


def test_nested_read_committed_locks_asset_alias_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    asset = AssetMasterModel.objects.create(
        code=f"600{uuid4().hex[:8]}.SH",
        name="Probe Alias Asset",
        asset_type="stock",
        exchange="SSE",
    )
    alias_code = f"probe-{uuid4().hex[:27]}"
    statement = """
        INSERT INTO data_center_asset_alias (
            asset_id,
            provider_name,
            alias_code,
            created_at
        ) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
    """
    params = (asset.pk, "probe", alias_code)
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, params)
        _probe_write(probe, statement, params)
        assert probe.execute(
            "SELECT asset_id, provider_name, alias_code FROM data_center_asset_alias "
            "WHERE provider_name=%s AND alias_code=%s",
            ["probe", alias_code],
        ).fetchone() == (asset.pk, "probe", alias_code)


def test_nested_repeatable_read_reuses_snapshot_without_share_table_locks(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        before = query_published_valuation_facts("000001.SZ")
        with actual_publication_pg.connect() as probe:
            _probe_update(probe, member.fact_pk)
        assert query_published_valuation_facts("000001.SZ")["rows"] == before["rows"]
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND mode='ShareLock' AND locktype='relation'"
            )
            assert cursor.fetchone() == (0,)
    assert query_published_valuation_facts("000001.SZ")["rows"] == []


def test_nested_read_only_read_committed_fails_closed_without_poisoning_parent(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        with pytest.raises(PublicationReadSnapshotError, match="read-only READ COMMITTED"):
            query_published_valuation_facts("000001.SZ")
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)


def test_versioned_publish_locks_facts_and_commits_complete_members_atomically(
    actual_publication_pg,
) -> None:
    policy, previous, member = _published_snapshot()
    # A successor must contain a genuinely changed fact; identical scope/hash
    # is an idempotent publication, protected by the existing unique constraint.
    ValuationFactModel.objects.filter(pk=member.fact_pk).update(pe_ttm=13)
    reference = ValuationFactRepository().list_current_publication_candidates(("000001.SZ",))[0]
    identifier = str(uuid4())
    published_at = timezone.now()
    successor = replace(
        previous,
        publication_id=identifier,
        publication_hash=publication_hash([reference], policy_identity=policy.identity),
        published_at=published_at,
        coverage=replace(
            previous.coverage,
            publication_id=identifier,
            coverage_id=str(uuid4()),
            generated_at=published_at,
        ),
    )
    frozen = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=identifier,
        dataset_key=policy.dataset.value,
    )
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            written = CanonicalPublicationRepository().publish_with_members(successor, (frozen,))
            assert written.policy_version == policy.identity
            assert CanonicalPublicationRepository().list_members(identifier) == [frozen]
            with pytest.raises(psycopg.errors.LockNotAvailable):
                _probe_update(probe, member.fact_pk)
            probe.rollback()
            rows = probe.execute(
                "SELECT publication_id FROM data_center_canonical_publication WHERE state='published'"
            ).fetchall()
            assert rows == [(UUID(previous.publication_id),)]
        rows = probe.execute(
            "SELECT publication_id FROM data_center_canonical_publication WHERE state='published'"
        ).fetchall()
        assert rows == [(UUID(identifier),)]


def test_forged_frozen_provenance_with_real_row_digest_never_replaces_current(
    actual_publication_pg,
) -> None:
    policy, previous, member = _published_snapshot()
    identifier = str(uuid4())
    forged = replace(
        member,
        publication_id=identifier,
        member_id=str(uuid4()),
        source_record_id="invented-body-proof",
    )
    publication = replace(
        previous,
        publication_id=identifier,
        publication_hash=publication_hash(
            [member_reference(forged)], policy_identity=policy.identity
        ),
        coverage=replace(previous.coverage, publication_id=identifier, coverage_id=str(uuid4())),
    )
    with pytest.raises(ValueError, match="canonical facts"):
        CanonicalPublicationRepository().publish_with_members(publication, (forged,))
    assert CanonicalPublicationRepository().get_current(policy.dataset.value, "current") == previous
    assert CanonicalPublicationModel.objects.count() == 1
    assert PublicationMemberModel.objects.count() == 1


def test_postgres_refetch_retains_frozen_publication_and_excludes_parallel_writer(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    repo = ValuationFactRepository()
    first = repo.get_latest("000001.SZ")
    assert first is not None
    before = query_published_valuation_facts("000001.SZ")
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            assert repo.bulk_upsert([replace(first, pe_ttm=19.5)]) == 1
            assert query_published_valuation_facts("000001.SZ")["rows"] == before["rows"]
            with pytest.raises(psycopg.errors.LockNotAvailable):
                _probe_update(probe, member.fact_pk)
            probe.rollback()
    assert ValuationFactModel.objects.count() == 2
    assert repo.get_latest("000001.SZ").pe_ttm == 19.5
    assert query_published_valuation_facts("000001.SZ")["rows"] == before["rows"]


def test_postgres_fact_refresh_honors_stricter_lock_timeout_and_rolls_back(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    repo = ValuationFactRepository()
    first = repo.get_latest("000001.SZ")
    assert first is not None
    with actual_publication_pg.connect() as probe:
        _probe_update(probe, member.fact_pk)
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '75ms'")
            with pytest.raises(OperationalError, match="lock timeout"):
                repo.bulk_upsert([replace(first, pe_ttm=19.5)])
            with connections["default"].cursor() as cursor:
                cursor.execute("SHOW lock_timeout")
                assert cursor.fetchone() == ("75ms",)
        probe.rollback()
    assert ValuationFactModel.objects.count() == 1
    assert repo.get_latest("000001.SZ").pe_ttm == first.pe_ttm


def test_postgres_revision_migration_preserves_rows_and_refuses_lossy_downgrade(
    actual_publication_pg,
) -> None:
    migration_type = import_module(
        "apps.data_center.migrations.0085_published_market_fact_revisions"
    ).Migration
    migration = migration_type("0085_published_market_fact_revisions", "data_center")
    before = ProjectState.from_apps(apps)
    for name, fields in (
        (
            "financialfactmodel",
            ("asset_code", "period_end", "period_type", "metric_code", "source"),
        ),
        ("pricebarmodel", ("asset_code", "bar_date", "freq", "adjustment", "source")),
        ("quotesnapshotmodel", ("asset_code", "snapshot_at", "source")),
        ("valuationfactmodel", ("asset_code", "val_date", "source")),
    ):
        before.alter_model_options(
            "data_center", name, {"unique_together": {fields}}, ["unique_together"]
        )
    before.remove_index("data_center", "publicationmembermodel", "dc_pub_member_fact_idx")
    connection = connections["default"]
    with connection.schema_editor() as editor:
        migration.unapply(before, editor)
    _policy, _publication, member = _published_snapshot()
    retained = ValuationFactModel.objects.values().get(pk=member.fact_pk)
    duplicate = {key: value for key, value in retained.items() if key != "id"}
    duplicate["revision_number"] = 2
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ValuationFactModel.objects.create(**duplicate)
    with connection.schema_editor() as editor:
        migration.apply(before.clone(), editor)
    assert ValuationFactModel.objects.values().get(pk=member.fact_pk) == retained
    with connection.cursor() as cursor:
        for model in (FinancialFactModel, PriceBarModel, QuoteSnapshotModel, ValuationFactModel):
            constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
            expected = list(model._meta.unique_together[0])
            assert any(
                item["unique"] and item["columns"] == expected for item in constraints.values()
            )
    repo = ValuationFactRepository()
    first = repo.get_latest("000001.SZ")
    assert first is not None
    repo.bulk_upsert([replace(first, pe_ttm=19.5)])
    assert ValuationFactModel.objects.count() == 2
    with pytest.raises(IntegrityError):
        with connection.schema_editor() as editor:
            migration.unapply(before, editor)
    assert ValuationFactModel.objects.count() == 2
    assert ValuationFactModel.objects.values().get(pk=member.fact_pk) == retained
    with connection.cursor() as cursor:
        indexes = connection.introspection.get_constraints(
            cursor, PublicationMemberModel._meta.db_table
        )
    assert "dc_pub_member_fact_idx" in indexes


def test_postgres_0085_orm_insert_uses_0086_scope_blocks_database_default(
    actual_publication_pg,
) -> None:
    """An 0085 model insert omitting scope_blocks must succeed after 0086."""
    migration_type = import_module(
        "apps.data_center.migrations.0086_canonical_publication_scope_blocks"
    ).Migration
    migration = migration_type("0086_canonical_publication_scope_blocks", "data_center")
    current_state = ProjectState.from_apps(apps)
    previous_state = current_state.clone()
    previous_state.remove_field("data_center", "canonicalpublicationmodel", "scope_blocks")
    connection = connections["default"]

    with connection.schema_editor() as editor:
        migration.unapply(current_state, editor)
    with connection.schema_editor() as editor:
        migration.apply(previous_state.clone(), editor)

    previous_model = previous_state.apps.get_model("data_center", "CanonicalPublicationModel")
    with CaptureQueriesContext(connection) as captured_queries:
        row = previous_model._default_manager.create(
            dataset_key="rollback-compatibility",
            publication_key="legacy-writer",
            policy_version="0085",
            publication_hash="legacy-writer-hash",
        )

    insert_statements = [
        query["sql"]
        for query in captured_queries.captured_queries
        if query["sql"].lstrip().upper().startswith("INSERT INTO")
    ]
    assert len(insert_statements) == 1
    assert "scope_blocks" not in insert_statements[0]
    assert row.pk
    persisted = CanonicalPublicationModel._default_manager.get(pk=row.pk)
    assert persisted.scope_blocks == []

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT is_nullable, data_type, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'data_center_canonical_publication'
              AND column_name = 'scope_blocks'
            """)
        column_metadata = cursor.fetchone()
    assert column_metadata is not None
    assert column_metadata[0:2] == ("NO", "jsonb")
    assert column_metadata[2] is not None and "[]" in column_metadata[2]


_FINANCIAL_CAPACITY_DATASET = "equity.financial.fact"


def _financial_capacity_pg_policy() -> PublicationPolicy:
    """Build the exact versioned evidence policy used by the capacity publisher tests."""

    return PublicationPolicy(
        dataset=DatasetKey(_FINANCIAL_CAPACITY_DATASET, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "payload_hash",
            "raw_payload_hash",
            "raw_payload_scope",
            "source_record_id",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="3",
    )


@dataclass(frozen=True, slots=True)
class _FinancialCapacityPgCapture:
    """Raw provider bytes returned by the test-only external transport seam."""

    payload: object
    evidence: FinancialResponseEvidence
    raw_body: bytes
    physical_request_attempts: int = 1


class _FinancialCapacityPgCaptureRunner:
    """Return deterministic EastMoney bytes while exercising production capture storage."""

    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        self._bodies = dict(bodies)
        self.requested_datasets: list[str] = []

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        request_id: UUID,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
        max_attempts: int = 2,
        attempt_budget: FinancialResponseAttemptBudget | None = None,
    ) -> FinancialResponseCaptureProtocol:
        """Satisfy one capture request at the external provider boundary."""

        del request_id
        if method != "GET" or params is None or json_body is not None or headers is not None:
            raise AssertionError("financial capture fixture received an unexpected request")
        if max_attempts != 1:
            raise AssertionError("financial capacity capture must use one route attempt")
        if attempt_budget is None or not attempt_budget.reserve():
            raise AssertionError("financial capacity capture must reserve one transport attempt")
        body = self._bodies[context.dataset_key]
        self.requested_datasets.append(context.dataset_key)
        evidence = FinancialResponseEvidence(
            body_sha256=raw_body_sha256(body),
            body_size_bytes=len(body),
            response_completed_at=timezone.now(),
            request_scope=request_scope,
            response_scope=response_scope,
        )
        return _FinancialCapacityPgCapture(
            payload={},
            evidence=evidence,
            raw_body=body,
        )


def _financial_capacity_pg_body(asset_code: str, *, pretty: bool) -> bytes:
    """Build a valid one-row EastMoney response for the real AKShare parser."""

    row = {
        "SECUCODE": asset_code,
        "REPORT_DATE": "2026-06-30 00:00:00",
        "NOTICE_DATE": "2026-09-30 00:00:00",
        "TOTALOPERATEREVE": 1000000,
        "PARENTNETPROFIT": 250000,
        "TOTALOPERATEREVETZ": 8.5,
        "PARENTNETPROFITTZ": 12.0,
        "ROEJQ": 7.5,
        "ZCFZL": 50,
        "LIABILITY": 500000,
        "TOTAL_ASSETS": 1000000,
        "TOTAL_EQUITY": 500000,
        "JROA": 3.8,
    }
    payload = {"success": True, "code": 0, "result": {"count": 1, "data": [row]}}
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _financial_capacity_pg_artifact_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> FinancialResponseArtifactRuntimeConfig:
    """Inject only a test-local explicit key/root into the real verifier."""

    runtime = FinancialResponseArtifactRuntimeConfig(
        root=(tmp_path / "financial-capacity-artifacts").resolve(),
        encryption_key=Fernet.generate_key(),
        encryption_key_ref="test/financial-capacity-pg-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )
    source_time_composition = import_module("apps.data_center.financial_source_time_composition")
    monkeypatch.setattr(
        source_time_composition,
        "resolve_financial_response_artifact_config",
        lambda **_kwargs: runtime,
    )
    return runtime


def _seed_financial_capacity_pg_case(
    *,
    asset_code: str,
    artifact_runtime: FinancialResponseArtifactRuntimeConfig,
) -> tuple[FinancialCapacityBinding, UUID, FinancialCapacitySliceEvidence, FinancialFactModel]:
    """Capture, verify, and atomically persist a real financial slice lineage."""

    policy = PublicationPolicyRepository().get_active(_FINANCIAL_CAPACITY_DATASET)
    if policy is None:
        policy = PublicationPolicyRepository().save(_financial_capacity_pg_policy())
    provider_row = ProviderConfigModel.objects.create(
        name=f"financial-capacity-pg-{uuid4().hex}",
        source_type="akshare",
        is_active=True,
        priority=1,
        description="Disposable provider identity for financial publication PostgreSQL tests",
    )
    provider = provider_row.to_domain()
    run_id = uuid4()
    raw_audits = RawAuditRepository()
    financial_store = FinancialResponseBodyStore(
        artifact_runtime.root,
        encryption_key=artifact_runtime.encryption_key,
        encryption_key_ref=artifact_runtime.encryption_key_ref,
        encryption_key_version=artifact_runtime.encryption_key_version,
        max_body_bytes=artifact_runtime.max_body_bytes,
    )
    source_time_store = FinancialSourceTimeBodyStore(
        artifact_runtime.root,
        encryption_key=artifact_runtime.encryption_key,
        encryption_key_ref=artifact_runtime.encryption_key_ref,
        encryption_key_version=artifact_runtime.encryption_key_version,
        max_body_bytes=artifact_runtime.max_body_bytes,
    )
    runner = _FinancialCapacityPgCaptureRunner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: _financial_capacity_pg_body(
                asset_code,
                pretty=False,
            ),
            AKSHARE_SOURCE_TIME_DATASET_KEY: _financial_capacity_pg_body(
                asset_code,
                pretty=True,
            ),
        }
    )
    gateway = AkshareFinancialCaptureGateway(
        provider,
        deployment_region="postgres-ci",
        financial_repository=FinancialResponseArtifactRepository(
            financial_store,
            raw_audits,
            failure_audit_repository=raw_audits,
        ),
        source_time_repository=FinancialSourceTimeArtifactRepository(
            source_time_store,
            DjangoFinancialSourceTimeArtifactAuditRepository(raw_audits),
        ),
        capture_runner=runner,
        max_route_attempts=1,
    )
    facts = AkshareUnifiedProviderAdapter(provider).fetch_financials_for_announcement_date(
        asset_code,
        date(2026, 9, 30),
        periods=8,
        capture_gateway=gateway,
        run_id=run_id,
    )
    if not facts or len(runner.requested_datasets) != 2:
        raise AssertionError("the real AKShare adapter did not complete one dual capture")
    facts_with_transport = [with_verified_financial_transport_metadata(fact) for fact in facts]
    written = FinancialFactRepository(
        source_time_evidence_verifier=verify_retained_financial_source_time_evidence,
    ).bulk_upsert(facts_with_transport, ingested_run_id=run_id)
    persisted_facts = tuple(
        FinancialFactModel.objects.filter(asset_code=asset_code, ingested_run_id=run_id).order_by(
            "metric_code"
        )
    )
    if written != len(facts) or len(persisted_facts) != written:
        raise AssertionError("the real financial fact repository did not persist the exact batch")
    if any(
        fact.source_record_id == "" or not fact.raw_payload_hash or fact.decision_evidence == {}
        for fact in persisted_facts
    ):
        raise AssertionError("persisted financial facts are missing typed source evidence")

    first_decision = facts[0].decision_evidence
    if first_decision is None or first_decision.source_time_witness is None:
        raise AssertionError("the real AKShare adapter did not bind its source-time witness")
    financial_reference = first_decision.artifact_reference
    source_time_reference = first_decision.source_time_witness.artifact_reference
    financial_audits = raw_audits.list_by_artifact_capture_id(financial_reference.capture_id)
    source_time_audits = raw_audits.list_by_source_time_artifact_capture_id(
        source_time_reference.capture_id
    )
    if len(financial_audits) != 1 or len(source_time_audits) != 1:
        raise AssertionError("the dual capture did not produce one audit on each side")
    for audit in (*financial_audits, *source_time_audits):
        if audit.run_id != str(run_id) or audit.ingested_run_id != str(run_id):
            raise AssertionError("the captured RawAudit run lineage is inconsistent")

    pointer, _created = CanonicalPublicationPointerModel.objects.get_or_create(
        dataset_key=_FINANCIAL_CAPACITY_DATASET,
        publication_key="current",
    )
    if pointer.publication_id is not None or pointer.publication_hash or pointer.activation_id:
        raise AssertionError("financial capacity PostgreSQL fixture requires an empty pointer")
    evidence = FinancialCapacitySliceEvidence(
        asset_code=asset_code,
        announcement_date=date(2026, 9, 30),
        financial_body_sha256=financial_reference.body_sha256,
        source_time_body_sha256=source_time_reference.body_sha256,
        financial_body_size_bytes=financial_reference.body_size_bytes,
        source_time_body_size_bytes=source_time_reference.body_size_bytes,
        financial_capture_id=str(financial_reference.capture_id),
        source_time_capture_id=str(source_time_reference.capture_id),
        financial_raw_audit_id=financial_audits[0].raw_audit_id,
        source_time_raw_audit_id=source_time_audits[0].raw_audit_id,
        financial_raw_audit_count=len(financial_audits),
        source_time_raw_audit_count=len(source_time_audits),
        typed_financial_evidence_count=len(facts),
        source_time_witness_count=len(facts),
        atomic_fact_write_count=1,
        stored=written,
        duration_ms=1,
    )
    binding = FinancialCapacityBinding(
        environment="production",
        candidate_sha="f" * 40,
        provider_id=int(provider_row.pk),
        provider_name="akshare",
        provider_source="akshare",
        provider_identity_sha256="1" * 64,
        contract_id="capacity-financial-contract",
        contract_version="1",
        contract_sha256="2" * 64,
        parser_id="capacity-financial-parser",
        parser_sha256="3" * 64,
        deployment_region="postgres-ci",
        publication_policy_version="3",
        publication_policy_sha256=policy.content_hash,
    )
    return binding, run_id, evidence, persisted_facts[0]


def _patch_financial_capacity_activation_runtime(
    monkeypatch,
    *,
    writer_factory=None,
    capture_barrier: Barrier | None = None,
) -> object:
    """Keep PG authority, audit, pointer, candidate and outbox transactions real."""

    runtime = import_module("apps.data_center.infrastructure.financial_capacity_publisher_runtime")
    authority = (
        import_module("tests.unit.account.test_account_authority_shadow_scanner")
        ._legacy_current()
        .authority
    )
    context = SimpleNamespace(tenant_id=authority.tenant_id, owner_id=authority.owner_id)
    monkeypatch.setattr(
        runtime,
        "preflight_data_reliability_audit_runtime",
        lambda **_kwargs: context,
    )

    def capture_authority(**_kwargs):
        fence, proof = _production_activation_fence()
        if capture_barrier is not None:
            capture_barrier.wait(timeout=20)
        return SimpleNamespace(authority_fence=fence, authority_proof=proof)

    monkeypatch.setattr(runtime, "capture_production_account_authority", capture_authority)
    monkeypatch.setattr(
        runtime,
        "get_data_publication_activation_audit_writer",
        lambda **_kwargs: (
            writer_factory() if writer_factory is not None else _PostgresActivationAuditWriter()
        ),
    )
    return runtime


def test_financial_capacity_stage_commit_unknown_recovers_exact_candidate_postgresql(
    activation_runtime_pg,
    monkeypatch,
    tmp_path,
) -> None:
    """Recover a staged candidate after its PG commit succeeds but its response is lost."""

    del activation_runtime_pg
    artifact_runtime = _financial_capacity_pg_artifact_runtime(tmp_path, monkeypatch)
    binding, run_id, evidence, fact = _seed_financial_capacity_pg_case(
        asset_code="000001.SZ",
        artifact_runtime=artifact_runtime,
    )
    publisher = AtomicFinancialPolicyV3Publisher()
    intent = publisher.begin_activation(binding=binding, run_id=run_id, evidence=(evidence,))
    repository_type = import_module(
        "apps.data_center.infrastructure.financial_capacity_publisher_runtime"
    ).DjangoPublicationActivationRepository
    original_stage = repository_type.stage_candidate_with_members
    lost_response = True

    def commit_then_disconnect(repository, publication, members):
        nonlocal lost_response
        persisted = original_stage(repository, publication, members)
        if lost_response:
            lost_response = False
            raise OSError("injected lost stage response after PostgreSQL commit")
        return persisted

    monkeypatch.setattr(repository_type, "stage_candidate_with_members", commit_then_disconnect)
    plan = publisher.stage(
        binding=binding,
        intent=intent,
        asset_codes=(fact.asset_code,),
        manifest_sha256="9" * 64,
    )
    replay = publisher.stage(
        binding=binding,
        intent=intent,
        asset_codes=(fact.asset_code,),
        manifest_sha256="9" * 64,
    )

    assert replay == plan
    assert (
        CanonicalPublicationModel.objects.filter(
            dataset_key=_FINANCIAL_CAPACITY_DATASET,
            publication_key="current",
            run_id=run_id,
        ).count()
        == 1
    )
    staged = CanonicalPublicationModel.objects.get(publication_id=plan.candidate_publication_id)
    assert staged.state == PublicationState.CANDIDATE.value
    assert staged.publication_hash == plan.candidate_publication_hash
    assert staged.members_sealed_at is not None
    assert staged.member_manifest_hash == plan.member_manifest_sha256
    assert (
        PublicationMemberModel.objects.filter(publication_id=plan.candidate_publication_id).count()
        == evidence.stored
    )


def test_financial_capacity_activation_commit_unknown_replays_only_same_plan_postgresql(
    activation_runtime_pg,
    monkeypatch,
    tmp_path,
) -> None:
    """Reconcile a lost activation response without rebuilding mutated live facts."""

    del activation_runtime_pg
    artifact_runtime = _financial_capacity_pg_artifact_runtime(tmp_path, monkeypatch)
    binding, run_id, evidence, fact = _seed_financial_capacity_pg_case(
        asset_code="000002.SZ",
        artifact_runtime=artifact_runtime,
    )
    publisher = AtomicFinancialPolicyV3Publisher()
    intent = publisher.begin_activation(binding=binding, run_id=run_id, evidence=(evidence,))
    plan = publisher.stage(
        binding=binding,
        intent=intent,
        asset_codes=(fact.asset_code,),
        manifest_sha256="8" * 64,
    )
    runtime = _patch_financial_capacity_activation_runtime(monkeypatch)
    original_execute = runtime.ActivateCanonicalPublicationUseCase.execute
    lost_response = True

    def commit_then_disconnect(use_case, request, **kwargs):
        nonlocal lost_response
        activated = original_execute(use_case, request, **kwargs)
        if lost_response:
            lost_response = False
            raise OSError("injected lost activation response after PostgreSQL commit")
        return activated

    monkeypatch.setattr(
        runtime.ActivateCanonicalPublicationUseCase,
        "execute",
        commit_then_disconnect,
    )
    assert publisher.activate(binding=binding, plan=plan) == plan.candidate_publication_hash
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_FINANCIAL_CAPACITY_DATASET,
        publication_key="current",
    )
    assert str(pointer.publication_id) == plan.candidate_publication_id
    assert pointer.publication_hash == plan.candidate_publication_hash
    assert pointer.activation_id == str(intent.activation_id)
    assert (
        CanonicalPublicationModel.objects.get(publication_id=plan.candidate_publication_id).state
        == PublicationState.PUBLISHED.value
    )
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1
    event = SystemAuditEventModel.objects.get()
    assert event.correlations["run_id"] == str(run_id)
    assert event.correlations["ingested_run_id"] == str(run_id)
    assert event.publication_id == plan.candidate_publication_id

    FinancialFactModel.objects.filter(pk=fact.pk).update(value=Decimal("999.0000"))
    monkeypatch.setattr(
        runtime,
        "build_current_publication_rebuild",
        lambda **_kwargs: pytest.fail("same-plan replay must not rebuild mutable live facts"),
    )
    assert publisher.activate(binding=binding, plan=plan) == plan.candidate_publication_hash
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1

    different_activation = replace(intent, activation_id=uuid4())
    different_plan = replace(plan, intent=different_activation)
    with pytest.raises(DataFetchError) as rejected:
        publisher.activate(binding=binding, plan=different_plan)
    assert (
        getattr(rejected.value, "code", "") == "financial_capacity_current_pointer_activation_drift"
    )
    assert (
        str(
            CanonicalPublicationPointerModel.objects.get(
                dataset_key=_FINANCIAL_CAPACITY_DATASET,
                publication_key="current",
            ).publication_id
        )
        == plan.candidate_publication_id
    )
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


def test_financial_capacity_activation_audit_failure_rolls_back_pointer_and_outbox_postgresql(
    activation_runtime_pg,
    monkeypatch,
    tmp_path,
) -> None:
    """A required audit append failure rolls back candidate, pointer, event and outbox together."""

    del activation_runtime_pg
    artifact_runtime = _financial_capacity_pg_artifact_runtime(tmp_path, monkeypatch)
    binding, run_id, evidence, fact = _seed_financial_capacity_pg_case(
        asset_code="000003.SZ",
        artifact_runtime=artifact_runtime,
    )
    publisher = AtomicFinancialPolicyV3Publisher()
    intent = publisher.begin_activation(binding=binding, run_id=run_id, evidence=(evidence,))
    plan = publisher.stage(
        binding=binding,
        intent=intent,
        asset_codes=(fact.asset_code,),
        manifest_sha256="7" * 64,
    )

    class AppendThenRaiseWriter(_PostgresActivationAuditWriter):
        def append_required(self, *, request, publication, members, observation):
            super().append_required(
                request=request,
                publication=publication,
                members=members,
                observation=observation,
            )
            raise RuntimeError("injected failure after audit and outbox writes")

    _patch_financial_capacity_activation_runtime(
        monkeypatch,
        writer_factory=AppendThenRaiseWriter,
    )
    with pytest.raises(FinancialCapacityPublicationIndeterminateError) as exc_info:
        publisher.activate(binding=binding, plan=plan)
    assert exc_info.value.phase == "activation"
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_FINANCIAL_CAPACITY_DATASET,
        publication_key="current",
    )
    assert pointer.publication_id is None
    assert pointer.publication_hash == ""
    assert pointer.activation_id == ""
    assert (
        CanonicalPublicationModel.objects.get(publication_id=plan.candidate_publication_id).state
        == PublicationState.CANDIDATE.value
    )
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_concurrent_financial_capacity_activations_have_one_postgresql_cas_winner(
    activation_runtime_pg,
    monkeypatch,
    tmp_path,
) -> None:
    """Two distinct financial candidates racing one empty pointer must have one winner."""

    del activation_runtime_pg
    artifact_runtime = _financial_capacity_pg_artifact_runtime(tmp_path, monkeypatch)
    first_binding, first_run, first_evidence, first_fact = _seed_financial_capacity_pg_case(
        asset_code="000004.SZ",
        artifact_runtime=artifact_runtime,
    )
    second_binding, second_run, second_evidence, second_fact = _seed_financial_capacity_pg_case(
        asset_code="000005.SZ",
        artifact_runtime=artifact_runtime,
    )
    publisher = AtomicFinancialPolicyV3Publisher()
    first_intent = publisher.begin_activation(
        binding=first_binding,
        run_id=first_run,
        evidence=(first_evidence,),
    )
    second_intent = publisher.begin_activation(
        binding=second_binding,
        run_id=second_run,
        evidence=(second_evidence,),
    )
    first_plan = publisher.stage(
        binding=first_binding,
        intent=first_intent,
        asset_codes=(first_fact.asset_code,),
        manifest_sha256="6" * 64,
    )
    second_plan = publisher.stage(
        binding=second_binding,
        intent=second_intent,
        asset_codes=(second_fact.asset_code,),
        manifest_sha256="5" * 64,
    )
    capture_barrier = Barrier(2)
    _patch_financial_capacity_activation_runtime(
        monkeypatch,
        capture_barrier=capture_barrier,
    )
    settings = deepcopy(connections["default"].settings_dict)

    def activate(plan: FinancialCapacityPublicationPlan, binding: FinancialCapacityBinding):
        previous_connection = connections["default"]
        worker_connection = load_backend(settings["ENGINE"]).DatabaseWrapper(
            deepcopy(settings), alias="default"
        )
        connections["default"] = worker_connection
        try:
            return "published", publisher.activate(binding=binding, plan=plan)
        except Exception as error:
            return "rejected", getattr(error, "code", type(error).__name__)
        finally:
            worker_connection.close()
            connections["default"] = previous_connection

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result(timeout=45)
            for future in (
                executor.submit(activate, first_plan, first_binding),
                executor.submit(activate, second_plan, second_binding),
            )
        )
    assert [outcome for outcome, _result in outcomes].count("published") == 1
    assert [outcome for outcome, _result in outcomes].count("rejected") == 1
    winner_hash = next(result for outcome, result in outcomes if outcome == "published")
    winning_plan = next(
        plan for plan in (first_plan, second_plan) if plan.candidate_publication_hash == winner_hash
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_FINANCIAL_CAPACITY_DATASET,
        publication_key="current",
    )
    assert str(pointer.publication_id) == winning_plan.candidate_publication_id
    assert pointer.publication_hash == winning_plan.candidate_publication_hash
    assert pointer.activation_id == str(winning_plan.intent.activation_id)
    assert (
        CanonicalPublicationModel.objects.filter(
            dataset_key=_FINANCIAL_CAPACITY_DATASET,
            publication_key="current",
            state=PublicationState.PUBLISHED.value,
        ).count()
        == 1
    )
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


def _financial_scope_report_for_capacity_pg_universe(
    *,
    binding: FinancialCapacityBinding,
    asset_codes: tuple[str, ...],
    typed_fact: FinancialFactModel,
    now: datetime,
) -> dict[str, object]:
    """Build a full dynamic reviewed-scope report without treating it as typed fact."""

    scope_binding = FinancialScopeDiscoveryBinding(
        candidate_sha=binding.candidate_sha,
        provider_id=binding.provider_id,
        provider_name="akshare",
        provider_identity_sha256=binding.provider_identity_sha256,
        contract_id=binding.contract_id,
        contract_version=binding.contract_version,
        contract_sha256=binding.contract_sha256,
        parser_id=binding.parser_id,
        parser_sha256=binding.parser_sha256,
        deployment_region=binding.deployment_region,
    )
    generated_at = now - timedelta(minutes=5)
    authorization = FinancialScopeDiscoveryAuthorization.for_universe(
        binding=scope_binding,
        asset_codes=asset_codes,
        approval_id="pg-full-universe-discovery-owner",
        approved_by="pg-discovery-owner",
        recorded_by="pg-discovery-operator",
        event_id="pg-full-universe-discovery-event",
        receipt_sha256="a" * 64,
        approved_at=generated_at - timedelta(minutes=1),
        expires_at=now + timedelta(days=1),
        maximum_logical_requests=len(asset_codes) * 2,
        maximum_rows_per_asset=200,
    )
    announcement_date = date(2026, 9, 30)
    native_row_ids = tuple(
        (
            (
                typed_fact.source_record_id
                if asset_code == typed_fact.asset_code
                else f"akshare:{asset_code}:2026-06-30:{announcement_date.isoformat()}"
            ),
        )
        for asset_code in asset_codes
    )
    items = tuple(
        FinancialScopeDiscoveryAsset(
            asset_code=asset_code,
            announcement_date=announcement_date,
            available_at=datetime(2026, 10, 1, tzinfo=UTC),
            native_row_ids=row_ids,
            financial_capture_id=f"financial-capture-{index}",
            financial_body_sha256=f"{index + 1:064x}",
            financial_raw_audit_id=(index * 2) + 1,
            source_time_capture_id=f"source-time-capture-{index}",
            source_time_body_sha256=f"{index + len(asset_codes) + 1:064x}",
            source_time_raw_audit_id=(index * 2) + 2,
            response_completed_at=(now - timedelta(minutes=3), now - timedelta(minutes=2)),
        )
        for index, (asset_code, row_ids) in enumerate(zip(asset_codes, native_row_ids, strict=True))
    )
    candidate = make_candidate(
        binding=scope_binding,
        authorization=authorization,
        asset_codes=asset_codes,
        items=items,
        generated_at=generated_at,
    )
    candidate_manifest = candidate.payload()
    candidate_manifest["manifest_sha256"] = candidate.manifest_sha256
    return {
        "schema": "release.financial-scope-discovery.v1",
        "kind": "financial_scope_discovery",
        "candidate_sha": binding.candidate_sha,
        "started_at": (now - timedelta(minutes=4)).isoformat(),
        "finished_at": (now - timedelta(minutes=3)).isoformat(),
        "outcome": "success",
        "review_status": "pending_independent_review",
        "binding": {
            "provider_id": scope_binding.provider_id,
            "provider_name": scope_binding.provider_name,
            "provider_identity_sha256": scope_binding.provider_identity_sha256,
            "contract_id": scope_binding.contract_id,
            "contract_version": scope_binding.contract_version,
            "contract_sha256": scope_binding.contract_sha256,
            "parser_id": scope_binding.parser_id,
            "parser_sha256": scope_binding.parser_sha256,
            "deployment_region": scope_binding.deployment_region,
        },
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "name": "agom_release_rehearsal_financial_scope",
            "host": "agom-s6-postgres-contract-test",
            "isolation_attestation_sha256": "b" * 64,
        },
        "authorization": {
            "approval_id": candidate.discovery_approval_id,
            "owner_event_id": candidate.discovery_owner_event_id,
            "owner_receipt_sha256": candidate.discovery_owner_receipt_sha256,
        },
        "candidate_image_id": "sha256:" + "c" * 64,
        "artifact_root": "financial-scope-artifacts",
        "encrypted_artifacts": [],
        "result": {
            "schema": "data-center.financial-scope-discovery-result.v1",
            "outcome": "success",
            "error_codes": [],
            "counts": {
                "requested": len(asset_codes),
                "captured": len(asset_codes),
                "failed_capture": 0,
                "missing": 0,
                "duplicates": 0,
                "conflicts": 0,
                "logical_requests": len(asset_codes) * 2,
                "physical_attempts": len(asset_codes) * 2,
                "artifact_writes": len(asset_codes) * 2,
                "raw_audit_writes": len(asset_codes) * 2,
                "fact_writes": 0,
                "publication_writes": 0,
            },
            "candidate": {
                "manifest_sha256": candidate.manifest_sha256,
                "universe_sha256": candidate.universe_sha256,
                "coverage_count": candidate.coverage_count,
                "review_status": "pending_independent_review",
            },
            "candidate_manifest": candidate_manifest,
        },
    }


def _install_financial_scope_pg_reviews(
    report: dict[str, object], *, environment: str = "isolated"
) -> None:
    """Persist separately authenticated owner and reviewer events for the exact report."""

    report_bytes = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    manifest = report["result"]["candidate_manifest"]
    candidate = manifest
    review_records = (
        ("data_owner", "pg-financial-data-owner", "owner"),
        ("independent_reviewer", "pg-independent-financial-reviewer", "reviewer"),
    )
    for role, approver, suffix in review_records:
        record_payload: dict[str, object] = {
            "schema_version": "data-center.financial-scope-manifest-review.v1",
            "candidate_sha": candidate["binding"]["candidate_sha"],
            "manifest_sha256": candidate["manifest_sha256"],
            "universe_sha256": candidate["universe"]["sha256"],
            "provider_identity_sha256": candidate["binding"]["provider_identity_sha256"],
            "contract_sha256": candidate["binding"]["contract_sha256"],
            "deployment_region": candidate["binding"]["deployment_region"],
            "approval_id": f"pg-scope-review-{suffix}-{report_sha256[:12]}",
            "approved_by": approver,
            "recorded_by": "pg-financial-scope-operator",
            "event_id": f"pg-scope-review-event-{suffix}-{report_sha256[:12]}",
            "approval_receipt_sha256": ("d" if suffix == "owner" else "e") * 64,
            "role": role,
            "environment": environment,
            "report_sha256": report_sha256,
            "approved_at": timezone.now().isoformat(),
            "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
        }
        governance_record = FinancialCapacityGovernanceRecordModel.objects.create(
            approval_id=str(record_payload["approval_id"]),
            stage=FinancialCapacityGovernanceRecordModel.SCOPE_MANIFEST_REVIEW,
            record=record_payload,
            created_by=str(record_payload["recorded_by"]),
        )
        approval_bytes = json.dumps(
            record_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        FinancialCapacityOwnerApprovalEventModel.objects.create(
            governance_record=governance_record,
            event_id=str(record_payload["event_id"]),
            approved_by=approver,
            approved_at=datetime.fromisoformat(str(record_payload["approved_at"])),
            approval_receipt_sha256=str(record_payload["approval_receipt_sha256"]),
            record_sha256=hashlib.sha256(approval_bytes).hexdigest(),
        )


def test_financial_capacity_formal_manifest_uses_asset_subquery_for_5572_active_assets_postgresql(
    activation_runtime_pg,
    monkeypatch,
    tmp_path,
) -> None:
    """The production manifest query stays bounded on a real 5,572-asset PG universe."""

    del activation_runtime_pg
    artifact_runtime = _financial_capacity_pg_artifact_runtime(tmp_path, monkeypatch)
    binding, _run_id, _evidence, typed_fact = _seed_financial_capacity_pg_case(
        asset_code="000001.SZ",
        artifact_runtime=artifact_runtime,
    )
    AssetMasterModel.objects.bulk_create(
        [
            AssetMasterModel(
                code=f"{index:06d}.SZ",
                name=f"Security {index}",
                short_name=f"S{index}",
                asset_type="stock",
                exchange="SZSE",
                is_active=True,
            )
            for index in range(1, 5_573)
        ],
        batch_size=500,
    )
    manifest_runtime = import_module(
        "apps.data_center.infrastructure.financial_publication_capacity_runtime"
    )
    capacity_binding = replace(
        binding,
        environment="isolated",
        isolation_attestation_sha256="6" * 64,
    )
    asset_codes = tuple(f"{index:06d}.SZ" for index in range(1, 5_573))
    now = timezone.now().astimezone(UTC)
    scope_report = _financial_scope_report_for_capacity_pg_universe(
        binding=capacity_binding,
        asset_codes=asset_codes,
        typed_fact=typed_fact,
        now=now,
    )
    _install_financial_scope_pg_reviews(scope_report)
    install_financial_scope_manifest_pointer(
        pointer_source=DjangoFinancialScopeManifestCurrentPointerSource(),
        review_source=DjangoFinancialScopeManifestReviewSource(),
        report_payload=scope_report,
        environment="isolated",
        updated_by="pg-financial-scope-operator",
        now=now,
    )

    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(
            FinancialCapacityWorkflowError,
            match="typed announcement scope is incomplete",
        ):
            manifest_runtime.DjangoFinancialCapacityManifestSource().freeze(
                stage="capacity_rehearsal",
                environment="isolated",
                binding=capacity_binding,
            )

    sql = " ".join(query["sql"] for query in queries.captured_queries).upper()
    assert len(queries) == 4
    assert " IN (SELECT " in sql
    assert "000001.SZ" not in sql
    assert "005572.SZ" not in sql


def _financial_scope_capacity_import_row_for_pg_test() -> FinancialScopeCapacityImportModel:
    """Create an import identity for database transaction-boundary tests."""

    now = datetime.now(UTC)
    return FinancialScopeCapacityImportModel._default_manager.create(
        import_id=uuid4(),
        environment="production",
        release_manifest_sha256="1" * 64,
        capacity_receipt_raw_sha256="2" * 64,
        scope_report_raw_sha256="3" * 64,
        scope_report_review_sha256="4" * 64,
        receipt_sha256="5" * 64,
        scope_pointer_sha256="6" * 64,
        candidate_sha="f" * 40,
        candidate_image_id="sha256:" + "7" * 64,
        target_trade_date=date(2026, 10, 9),
        release_universe_sha256="8" * 64,
        provider_identities_sha256="9" * 64,
        scope_manifest_sha256="a" * 64,
        financial_universe_sha256="b" * 64,
        financial_provider_id=17,
        financial_provider_identity_sha256="c" * 64,
        source_revision_sha256="d" * 64,
        evidence_ledger_sha256="e" * 64,
        artifact_ledger_sha256="f" * 64,
        owner_approval_id="pg-owner-approval",
        owner_event_id="pg-owner-event",
        reviewer_approval_id="pg-reviewer-approval",
        reviewer_event_id="pg-reviewer-event",
        production_ceiling_approval_id="pg-ceiling-approval",
        production_ceiling_event_id="pg-ceiling-event",
        production_ceiling_record_sha256="1" * 64,
        record_payload={},
        record_sha256="2" * 64,
        imported_by="pg-test-operator",
        imported_at=now,
    )


def test_financial_scope_import_locks_nullable_revocation_join_on_postgresql(
    actual_publication_pg,
) -> None:
    """Importer locks governance rows without asking PostgreSQL to lock a nullable join."""

    del actual_publication_pg
    from apps.data_center.infrastructure.financial_scope_capacity_import_runtime import (
        _lock_authority_rows,
    )

    approval_ids = (
        "pg-scope-owner-lock",
        "pg-scope-reviewer-lock",
        "pg-capacity-ceiling-lock",
    )
    for approval_id in approval_ids:
        FinancialCapacityGovernanceRecordModel.objects.create(
            approval_id=approval_id,
            stage=FinancialCapacityGovernanceRecordModel.SCOPE_MANIFEST_REVIEW,
            record={},
            created_by="pg-lock-test-operator",
        )

    with transaction.atomic():
        _lock_authority_rows(
            owner_approval_id=approval_ids[0],
            reviewer_approval_id=approval_ids[1],
            ceiling_approval_id=approval_ids[2],
        )


def _formal_checkpoint_for_pg_import_test(
    *, scope_import: FinancialScopeCapacityImportModel, workflow_id: str
) -> FinancialCapacityCheckpoint:
    """Build a valid formal checkpoint tied to one persisted scope import."""

    now = datetime.now(UTC)
    binding = FinancialCapacityBinding(
        environment="production",
        candidate_sha=scope_import.candidate_sha,
        provider_id=scope_import.financial_provider_id,
        provider_name="akshare",
        provider_source="akshare",
        provider_identity_sha256=scope_import.financial_provider_identity_sha256,
        contract_id="pg-capacity-contract",
        contract_version="1",
        contract_sha256="3" * 64,
        parser_id="pg-capacity-parser",
        parser_sha256="4" * 64,
        deployment_region="postgres-ci",
        publication_policy_version="3",
        publication_policy_sha256="5" * 64,
    )
    manifest = (FinancialPublicationSlice("000001.SZ", date(2026, 9, 30)),)
    manifest_sha256 = _manifest_sha256(manifest)
    receipt = FinancialCapacityReceipt.build(
        workflow_id=f"capacity-rehearsal-{workflow_id}",
        stage="capacity_rehearsal",
        approval_id=f"capacity-approval-{workflow_id}",
        binding=replace(
            binding,
            environment="isolated",
            isolation_attestation_sha256="6" * 64,
        ),
        manifest_count=1,
        manifest_sha256=manifest_sha256,
        source_revision_sha256="7" * 64,
        outcome="success",
        total_provider_request_budget=2,
        provider_requests=2,
        reserved_provider_requests=2,
        requested=1,
        succeeded=1,
        failed=0,
        stored=1,
        evidence_count=1,
        evidence_sha256="8" * 64,
        raw_body_count=2,
        raw_audit_count=2,
        typed_evidence_count=1,
        atomic_fact_write_count=1,
        error_codes=(),
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
    )
    ceiling = GovernedFinancialProductionCeiling(
        approval_id=f"production-ceiling-{workflow_id}",
        approved_by="pg-data-owner",
        approved_at=now - timedelta(minutes=1),
        approval_receipt_sha256="9" * 64,
        receipt_sha256=receipt.sha256,
        binding=binding,
        manifest_sha256=manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=now + timedelta(hours=1),
        approved=True,
    )
    return FinancialCapacityCheckpoint(
        workflow_id=workflow_id,
        stage="formal_publication",
        binding=binding,
        manifest=manifest,
        manifest_count=1,
        manifest_sha256=manifest_sha256,
        source_revision_sha256=scope_import.source_revision_sha256,
        total_provider_request_budget=2,
        status="running",
        next_slice_index=0,
        reserved_provider_requests=0,
        observed_provider_requests=0,
        requested=0,
        succeeded=0,
        failed=0,
        stored=0,
        evidence=(),
        evidence_count=0,
        evidence_sha256=_empty_evidence_sha256(),
        raw_body_count=0,
        raw_audit_count=0,
        typed_evidence_count=0,
        atomic_fact_write_count=0,
        error_codes=(),
        started_at=now,
        run_id=str(uuid4()),
        capacity_receipt=receipt,
        governed_ceiling=ceiling,
        active_universe_sha256=scope_import.financial_universe_sha256,
        scope_capacity_import_id=str(scope_import.import_id),
        scope_capacity_import_record_sha256=scope_import.record_sha256,
    )


def _seed_real_financial_scope_capacity_authority_pg_case(*, workflow_id: str) -> tuple[
    DjangoFinancialScopeCapacityImportAuthoritySource,
    FinancialScopeCapacityImportModel,
    FinancialCapacityCheckpoint,
    str,
    str,
]:
    """Build a PG import with real current pointer, review, and owner-ceiling rows."""

    from apps.data_center.application.financial_scope_capacity_input import (
        _parse_reviewable_report,
    )
    from apps.data_center.application.financial_scope_capacity_receipt import canonical_sha256

    now = timezone.now().astimezone(UTC) + timedelta(seconds=60)
    binding = FinancialCapacityBinding(
        environment="production",
        candidate_sha="f" * 40,
        provider_id=17,
        provider_name="akshare",
        provider_source="akshare",
        provider_identity_sha256="c" * 64,
        contract_id="pg-capacity-contract",
        contract_version="1",
        contract_sha256="3" * 64,
        parser_id="pg-capacity-parser",
        parser_sha256="4" * 64,
        deployment_region="postgres-ci",
        publication_policy_version="3",
        publication_policy_sha256="5" * 64,
    )
    asset_codes = ("000001.SZ",)
    report = _financial_scope_report_for_capacity_pg_universe(
        binding=binding,
        asset_codes=asset_codes,
        typed_fact=SimpleNamespace(source_record_id="akshare:000001.SZ:2026-06-30:2026-09-30"),
        now=now,
    )
    _install_financial_scope_pg_reviews(report, environment="production")
    report_sha256 = canonical_sha256(report)
    review_source = DjangoFinancialScopeManifestReviewSource()
    pointer = prepare_financial_scope_manifest_pointer(
        report_payload=report,
        environment="production",
        review_source=review_source,
        updated_by="pg-financial-scope-operator",
        now=now,
    )
    pointer_source = DjangoFinancialScopeManifestCurrentPointerSource()
    current_pointer = pointer_source.get_current(environment="production")
    pointer_source.set_current(
        pointer,
        expected_revision=current_pointer.revision if current_pointer is not None else 0,
    )
    candidate, parsed_report_sha256 = _parse_reviewable_report(
        report,
        environment="production",
    )
    if parsed_report_sha256 != report_sha256:
        raise AssertionError("the production scope report digest changed during setup")

    formal_manifest = (FinancialPublicationSlice("000001.SZ", date(2026, 9, 30)),)
    typed_source_snapshot_sha256 = "9" * 64
    snapshot = FinancialCapacityManifestSnapshot.build(
        slices=formal_manifest,
        active_universe_sha256=universe_sha256(asset_codes),
        typed_source_snapshot_sha256=typed_source_snapshot_sha256,
    )
    authority = DjangoFinancialScopeCapacityImportAuthoritySource()
    authority._binding_source = SimpleNamespace(snapshot=lambda **_kwargs: binding)
    authority._manifest_source = SimpleNamespace(freeze=lambda **_kwargs: snapshot)

    receipt_sha256 = hashlib.sha256(f"{workflow_id}:receipt".encode()).hexdigest()
    ceiling_approval_id = f"pg-capacity-ceiling-{workflow_id}"
    ceiling_event_id = f"pg-capacity-ceiling-event-{workflow_id}"
    ceiling_payload: dict[str, object] = {
        "approval_id": ceiling_approval_id,
        "approved_by": "pg-independent-capacity-owner",
        "approved_at": (now - timedelta(minutes=1)).isoformat(),
        "approval_receipt_sha256": "b" * 64,
        "receipt_sha256": receipt_sha256,
        "binding": binding.to_dict(),
        "manifest_sha256": candidate.manifest_sha256,
        "maximum_slices": 1,
        "maximum_provider_requests": 2,
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "approved": True,
    }
    ceiling_record = FinancialCapacityGovernanceRecordModel.objects.create(
        approval_id=ceiling_approval_id,
        stage=FinancialCapacityGovernanceRecordModel.PRODUCTION,
        record=ceiling_payload,
        created_by="pg-capacity-ceiling-recorder",
    )
    FinancialCapacityOwnerApprovalEventModel.objects.create(
        governance_record=ceiling_record,
        event_id=ceiling_event_id,
        approved_by=str(ceiling_payload["approved_by"]),
        approved_at=datetime.fromisoformat(str(ceiling_payload["approved_at"])),
        approval_receipt_sha256=str(ceiling_payload["approval_receipt_sha256"]),
        record_sha256=canonical_sha256(ceiling_payload),
    )

    imported_at = now
    review_ids = {
        "owner_approval_id": f"pg-scope-review-owner-{report_sha256[:12]}",
        "owner_event_id": f"pg-scope-review-event-owner-{report_sha256[:12]}",
        "reviewer_approval_id": f"pg-scope-review-reviewer-{report_sha256[:12]}",
        "reviewer_event_id": f"pg-scope-review-event-reviewer-{report_sha256[:12]}",
    }
    record_payload: dict[str, object] = {
        "schema": "data-center.financial-scope-capacity-import.v1",
        "environment": "production",
        "release_manifest_sha256": "1" * 64,
        "capacity_receipt_raw_sha256": "2" * 64,
        "scope_report_raw_sha256": "3" * 64,
        "scope_report_review_sha256": report_sha256,
        "receipt_sha256": receipt_sha256,
        "scope_pointer_sha256": canonical_sha256({"kind": "scope-pointer", "id": workflow_id}),
        "candidate_sha": binding.candidate_sha,
        "candidate_image_id": "sha256:" + "7" * 64,
        "target_trade_date": "2026-10-09",
        "release_universe_sha256": "8" * 64,
        "provider_identities_sha256": "6" * 64,
        "scope_manifest_sha256": candidate.manifest_sha256,
        "financial_universe_sha256": candidate.universe_sha256,
        "financial_provider_id": binding.provider_id,
        "financial_provider_identity_sha256": binding.provider_identity_sha256,
        "source_revision_sha256": snapshot.source_revision_sha256,
        "evidence_ledger_sha256": "d" * 64,
        "artifact_ledger_sha256": "e" * 64,
        "runtime_binding": binding.to_dict(),
        "review": review_ids,
        "production_ceiling": {
            "approval_id": ceiling_approval_id,
            "event_id": ceiling_event_id,
            "record_sha256": canonical_sha256(ceiling_payload),
            "maximum_slices": 1,
            "maximum_provider_requests": 2,
        },
        "imported_by": "pg-financial-scope-importer",
        "imported_at": imported_at.isoformat(),
        "capacity_receipt": {"receipt_sha256": receipt_sha256},
        "scope_report": report,
    }
    record_sha256 = canonical_sha256(record_payload)
    record_payload["record_sha256"] = record_sha256
    scope_import = FinancialScopeCapacityImportModel.objects.create(
        import_id=uuid4(),
        environment="production",
        release_manifest_sha256="1" * 64,
        capacity_receipt_raw_sha256="2" * 64,
        scope_report_raw_sha256="3" * 64,
        scope_report_review_sha256=report_sha256,
        receipt_sha256=receipt_sha256,
        scope_pointer_sha256=canonical_sha256({"kind": "scope-pointer", "id": workflow_id}),
        candidate_sha=binding.candidate_sha,
        candidate_image_id="sha256:" + "7" * 64,
        target_trade_date=date(2026, 10, 9),
        release_universe_sha256="8" * 64,
        provider_identities_sha256="6" * 64,
        scope_manifest_sha256=candidate.manifest_sha256,
        financial_universe_sha256=candidate.universe_sha256,
        financial_provider_id=binding.provider_id,
        financial_provider_identity_sha256=binding.provider_identity_sha256,
        source_revision_sha256=snapshot.source_revision_sha256,
        evidence_ledger_sha256="d" * 64,
        artifact_ledger_sha256="e" * 64,
        owner_approval_id=review_ids["owner_approval_id"],
        owner_event_id=review_ids["owner_event_id"],
        reviewer_approval_id=review_ids["reviewer_approval_id"],
        reviewer_event_id=review_ids["reviewer_event_id"],
        production_ceiling_approval_id=ceiling_approval_id,
        production_ceiling_event_id=ceiling_event_id,
        production_ceiling_record_sha256=canonical_sha256(ceiling_payload),
        record_payload=record_payload,
        record_sha256=record_sha256,
        imported_by="pg-financial-scope-importer",
        imported_at=imported_at,
    )
    checkpoint = _formal_checkpoint_for_pg_import_test(
        scope_import=scope_import,
        workflow_id=workflow_id,
    )
    return (
        authority,
        scope_import,
        checkpoint,
        ceiling_approval_id,
        review_ids["reviewer_approval_id"],
    )


def test_formal_scope_import_authority_rechecks_real_postgresql_rows(
    actual_publication_pg,
) -> None:
    """Consume only a hash-valid import with live dual review and production ceiling rows."""

    del actual_publication_pg
    failure_expectations = {
        "review_revoked": "financial_capacity_scope_import_authority_revoked_or_missing",
        "ceiling_drift": "financial_capacity_scope_import_ceiling_revoked_or_expired",
        "import_digest_tampered": "financial_capacity_scope_import_invalid",
    }
    for authority_change in ("happy", *failure_expectations):
        authority, scope_import, checkpoint, ceiling_approval_id, reviewer_approval_id = (
            _seed_real_financial_scope_capacity_authority_pg_case(
                workflow_id=f"pg-real-scope-authority-{authority_change}"
            )
        )
        expected_error = failure_expectations.get(authority_change)
        if authority_change == "review_revoked":
            review_record = FinancialCapacityGovernanceRecordModel.objects.get(
                approval_id=reviewer_approval_id
            )
            FinancialCapacityGovernanceRevocationModel.objects.create(
                governance_record=review_record,
                revoked_by="pg-scope-authority-red-team",
            )
        elif authority_change == "ceiling_drift":
            ceiling_record = FinancialCapacityGovernanceRecordModel.objects.get(
                approval_id=ceiling_approval_id
            )
            changed_payload = dict(ceiling_record.record)
            changed_payload["maximum_provider_requests"] = 4
            FinancialCapacityGovernanceRecordModel.objects.filter(pk=ceiling_record.pk).update(
                record=changed_payload
            )
        elif authority_change == "import_digest_tampered":
            changed_payload = dict(scope_import.record_payload)
            changed_payload["scope_report_raw_sha256"] = "f" * 64
            FinancialScopeCapacityImportModel.objects.filter(pk=scope_import.pk).update(
                record_payload=changed_payload
            )
            assert authority.load_record_sha256(str(scope_import.import_id)) is None

        if expected_error is None:
            assert (
                authority.load_record_sha256(str(scope_import.import_id))
                == scope_import.record_sha256
            )
            with transaction.atomic():
                authority.consume_formal_start(checkpoint, now=checkpoint.started_at)
            consumption = FinancialScopeCapacityImportConsumptionModel.objects.get(
                scope_import=scope_import
            )
            assert consumption.workflow_id == checkpoint.workflow_id
            assert consumption.record_sha256 == scope_import.record_sha256
        else:
            with pytest.raises(FinancialCapacityWorkflowError, match=expected_error):
                with transaction.atomic():
                    authority.consume_formal_start(checkpoint, now=checkpoint.started_at)
            assert not FinancialScopeCapacityImportConsumptionModel.objects.filter(
                scope_import=scope_import
            ).exists()


def test_formal_scope_import_authority_rejects_candidate_provider_and_universe_drift_postgresql(
    actual_publication_pg,
) -> None:
    """The real import row cannot resume under a changed candidate, provider, or universe."""

    del actual_publication_pg
    authority, scope_import, checkpoint, _ceiling_approval_id, _reviewer_approval_id = (
        _seed_real_financial_scope_capacity_authority_pg_case(
            workflow_id="pg-real-scope-authority-binding-drift"
        )
    )
    base_kwargs = {
        "import_id": str(scope_import.import_id),
        "record_sha256": scope_import.record_sha256,
        "workflow_id": checkpoint.workflow_id,
        "manifest_sha256": checkpoint.manifest_sha256,
        "active_universe_sha256": checkpoint.active_universe_sha256,
        "source_revision_sha256": checkpoint.source_revision_sha256,
        "now": checkpoint.started_at,
        "expected_consumed": False,
    }
    assert (
        authority.validate_current(
            **base_kwargs,
            binding=replace(checkpoint.binding, candidate_sha="0" * 40),
        )
        == "financial_capacity_scope_import_candidate_drift"
    )
    assert (
        authority.validate_current(
            **base_kwargs,
            binding=replace(checkpoint.binding, provider_id=checkpoint.binding.provider_id + 1),
        )
        == "financial_capacity_scope_import_candidate_drift"
    )
    wrong_universe_kwargs = dict(base_kwargs)
    wrong_universe_kwargs["active_universe_sha256"] = "0" * 64
    assert (
        authority.validate_current(
            **wrong_universe_kwargs,
            binding=checkpoint.binding,
        )
        == "financial_capacity_scope_drift"
    )


def test_formal_scope_import_commit_unknown_after_commit_reads_back_exact_workflow_postgresql(
    actual_publication_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover the exact durable start after PostgreSQL commits but loses its acknowledgment."""

    del actual_publication_pg
    from apps.data_center.infrastructure import financial_capacity_checkpoint_repository as repo

    authority, scope_import, checkpoint, _ceiling_approval_id, _reviewer_approval_id = (
        _seed_real_financial_scope_capacity_authority_pg_case(
            workflow_id="pg-real-scope-authority-commit-unknown"
        )
    )
    original_atomic = transaction.atomic
    lost_acknowledgments: list[str] = []

    @contextmanager
    def commit_then_disconnect(*args: object, **kwargs: object) -> Iterator[None]:
        with original_atomic(*args, **kwargs):
            yield
        if not lost_acknowledgments:
            lost_acknowledgments.append("after-commit")
            raise DatabaseError("injected lost PostgreSQL commit acknowledgment")

    monkeypatch.setattr(repo.transaction, "atomic", commit_then_disconnect)
    repository = repo.DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=authority
    )

    persisted = repository.create(checkpoint)

    assert lost_acknowledgments == ["after-commit"]
    assert persisted.workflow_id == checkpoint.workflow_id
    assert (
        FinancialScopeCapacityImportConsumptionModel.objects.get(
            scope_import=scope_import
        ).workflow_id
        == checkpoint.workflow_id
    )
    assert (
        FinancialPublicationCapacityWorkflowModel.objects.filter(
            workflow_id=checkpoint.workflow_id
        ).count()
        == 1
    )
    assert (
        FinancialPublicationCapacityManifestItemModel.objects.filter(
            workflow_id=checkpoint.workflow_id
        ).count()
        == 1
    )


def _postgres_scope_import_authority(monkeypatch: pytest.MonkeyPatch):
    """Keep real consumption SQL while isolating live authority dependencies."""

    authority_type = import_module(
        "apps.data_center.infrastructure.financial_scope_capacity_import_authority"
    ).DjangoFinancialScopeCapacityImportAuthoritySource
    authority = authority_type()
    monkeypatch.setattr(authority, "_validate_row", lambda **_kwargs: None)
    return authority


def test_formal_start_consumes_verified_scope_import_atomically_postgresql(
    actual_publication_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import consumption, formal workflow, and manifest commit together."""

    del actual_publication_pg
    from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
        DjangoFinancialCapacityCheckpointRepository,
    )

    scope_import = _financial_scope_capacity_import_row_for_pg_test()
    checkpoint = _formal_checkpoint_for_pg_import_test(
        scope_import=scope_import,
        workflow_id="pg-atomic-formal-start",
    )
    repository = DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=_postgres_scope_import_authority(monkeypatch)
    )

    persisted = repository.create(checkpoint)

    assert persisted.status == "running"
    assert (
        FinancialPublicationCapacityWorkflowModel._default_manager.filter(
            workflow_id=checkpoint.workflow_id
        ).count()
        == 1
    )
    assert (
        FinancialPublicationCapacityManifestItemModel._default_manager.filter(
            workflow_id=checkpoint.workflow_id
        ).count()
        == 1
    )
    consumption = FinancialScopeCapacityImportConsumptionModel._default_manager.get(
        scope_import=scope_import
    )
    assert consumption.workflow_id == checkpoint.workflow_id
    assert consumption.record_sha256 == scope_import.record_sha256


def test_formal_start_import_event_failure_rolls_back_all_rows_postgresql(
    actual_publication_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after event insertion leaves no consumption, workflow, or manifest row."""

    del actual_publication_pg
    from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
        DjangoFinancialCapacityCheckpointRepository,
    )

    scope_import = _financial_scope_capacity_import_row_for_pg_test()
    checkpoint = _formal_checkpoint_for_pg_import_test(
        scope_import=scope_import,
        workflow_id="pg-rollback-formal-start",
    )
    authority = _postgres_scope_import_authority(monkeypatch)
    append_event = authority.consume_formal_start

    def append_then_fail(request: FinancialCapacityCheckpoint, *, now: datetime) -> None:
        append_event(request, now=now)
        raise FinancialCapacityWorkflowError("injected failure after consumption append")

    monkeypatch.setattr(authority, "consume_formal_start", append_then_fail)
    repository = DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=authority
    )

    with pytest.raises(
        FinancialCapacityWorkflowError,
        match="injected failure after consumption append",
    ):
        repository.create(checkpoint)

    assert FinancialScopeCapacityImportConsumptionModel._default_manager.count() == 0
    assert FinancialPublicationCapacityWorkflowModel._default_manager.count() == 0
    assert FinancialPublicationCapacityManifestItemModel._default_manager.count() == 0


def test_formal_start_same_workflow_retry_reconciles_and_other_workflow_replay_is_blocked_postgresql(
    actual_publication_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-workflow retries reconcile while another workflow cannot consume the import."""

    del actual_publication_pg
    from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
        DjangoFinancialCapacityCheckpointRepository,
    )

    scope_import = _financial_scope_capacity_import_row_for_pg_test()
    first_checkpoint = _formal_checkpoint_for_pg_import_test(
        scope_import=scope_import,
        workflow_id="pg-replay-formal-start-a",
    )
    repository = DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=_postgres_scope_import_authority(monkeypatch)
    )

    persisted = repository.create(first_checkpoint)
    retried = repository.create(first_checkpoint)
    second_checkpoint = _formal_checkpoint_for_pg_import_test(
        scope_import=scope_import,
        workflow_id="pg-replay-formal-start-b",
    )
    with pytest.raises(FinancialCapacityWorkflowError):
        repository.create(second_checkpoint)

    assert retried == persisted
    assert FinancialPublicationCapacityWorkflowModel._default_manager.count() == 1
    assert FinancialPublicationCapacityManifestItemModel._default_manager.count() == 1
    assert FinancialScopeCapacityImportConsumptionModel._default_manager.count() == 1


def test_concurrent_formal_start_replay_has_one_postgresql_consumption_winner(
    actual_publication_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent starts racing on one import leave exactly one durable winner."""

    del actual_publication_pg
    from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
        DjangoFinancialCapacityCheckpointRepository,
    )

    scope_import = _financial_scope_capacity_import_row_for_pg_test()
    checkpoints = tuple(
        _formal_checkpoint_for_pg_import_test(
            scope_import=scope_import,
            workflow_id=f"pg-concurrent-formal-start-{index}",
        )
        for index in range(2)
    )
    repository = DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=_postgres_scope_import_authority(monkeypatch)
    )
    settings = deepcopy(connections["default"].settings_dict)
    barrier = Barrier(2)

    def create(checkpoint: FinancialCapacityCheckpoint) -> str:
        previous_connection = connections["default"]
        worker_connection = load_backend(settings["ENGINE"]).DatabaseWrapper(
            deepcopy(settings), alias="default"
        )
        connections["default"] = worker_connection
        try:
            barrier.wait(timeout=20)
            repository.create(checkpoint)
            return "created"
        except FinancialCapacityWorkflowError:
            return "rejected"
        finally:
            worker_connection.close()
            connections["default"] = previous_connection

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result(timeout=45)
            for future in (
                executor.submit(create, checkpoints[0]),
                executor.submit(create, checkpoints[1]),
            )
        )

    assert outcomes.count("created") == 1
    assert outcomes.count("rejected") == 1
    assert FinancialScopeCapacityImportConsumptionModel._default_manager.count() == 1
    assert FinancialPublicationCapacityWorkflowModel._default_manager.count() == 1
    assert FinancialPublicationCapacityManifestItemModel._default_manager.count() == 1
