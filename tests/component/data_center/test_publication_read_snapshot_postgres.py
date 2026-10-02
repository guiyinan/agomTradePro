"""Opt-in real PostgreSQL consistency, locking and rollback publication tests."""

import ipaddress
import json
import os
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from threading import Barrier
from time import monotonic
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from django.apps import apps
from django.db import IntegrityError, OperationalError, connections, transaction
from django.db.migrations.state import ProjectState
from django.db.utils import load_backend
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
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
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
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
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    FinancialFactModel,
    PriceBarModel,
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

    def connect(self):
        return psycopg.connect(**self.credentials)


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
        PriceBarModel,
        QuoteSnapshotModel,
        FinancialFactModel,
        ValuationFactModel,
        RawAuditModel,
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
    with django_db_blocker.unblock():
        connections["default"] = wrapper
        try:
            assert wrapper.vendor == "postgresql"
            assert wrapper.introspection.table_names() == [], "Refuse any preexisting test tables"
            with wrapper.schema_editor() as editor:
                for model in models:
                    editor.create_model(model)
                    created.append(model)
                _ACCOUNT_GENERATION_MIGRATION.seed_generation_row(apps, editor)
                _ACCOUNT_GENERATION_MIGRATION.install_source_triggers(apps, editor)
                source_triggers_installed = True
                _ACCOUNT_GENERATION_LOCK_MIGRATION.install_generation_lock_function(apps, editor)
                generation_lock_installed = True
            yield _PGProbeFactory(credentials)
        finally:
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
            PriceBarModel,
            QuoteSnapshotModel,
            FinancialFactModel,
            ValuationFactModel,
            RawAuditModel,
            CanonicalPublicationModel,
            CandidateRawAuditManifestModel,
            CandidateRawAuditManifestMemberModel,
            CanonicalPublicationPointerModel,
            CoverageSnapshotModel,
            PublicationMemberModel,
            SystemAuditEventModel,
            SystemAuditOutboxModel,
        )
        expected = {model._meta.db_table for model in models}
        full_expected = {
            model._meta.db_table
            for model in (*_ACCOUNT_SCHEMA_MODELS, AccountAuthorityGenerationModel, *models)
        }
        assert set(wrapper.introspection.table_names()) == full_expected
        names = ", ".join(wrapper.ops.quote_name(name) for name in sorted(expected))
        with wrapper.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {names}")


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
    actual_publication_pg,
) -> None:
    """Exercise one three-dataset RC/RW activation with 5,001 valuation members."""

    request, candidate_ids, raw_audit_ids = _build_activation_soak_snapshot()
    repository = DjangoPublicationActivationRepository()
    writer = _PostgresActivationAuditWriter()
    authority_fence, authority_proof = _production_activation_fence()
    started = monotonic()
    with CaptureQueriesContext(connections["default"]) as captured:
        activated = ActivateCanonicalPublicationGroupUseCase(repository).execute(
            request,
            audit_writer=writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )
    held_seconds = monotonic() - started

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

    probe = actual_publication_pg.connect()
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
        with pytest.raises(OperationalError):
            ActivateCanonicalPublicationGroupUseCase(repository).execute(
                request,
                audit_writer=_PostgresActivationAuditWriter(),
                authority_fence=blocked_fence,
                authority_proof=blocked_proof,
            )
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


def test_concurrent_group_activations_have_one_cas_winner(actual_publication_pg) -> None:
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
) -> None:
    """Real PostgreSQL endpoint identity must return a host address without a CIDR mask."""
    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner

    del actual_publication_pg
    database_name, server_address, server_port = runner._connected_database_identity()
    configured = connections["default"].settings_dict

    assert database_name == configured["NAME"]
    assert "/" not in server_address
    ipaddress.ip_address(server_address)
    assert server_port == 5432


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
    assert receipt["current_time_stale_expected"] is True
    assert receipt["current_time_freshness_guard_verified"] is True
    assert receipt["tamper_guard_verified"] is True
    assert receipt["rollback_verified"] is True
    assert receipt["residual_rows"] == 0
    assert receipt["written_rows"] == 4
    assert receipt["publication_id"] == report["publication_id"]
    assert len(receipt["member_fact_content_hash"]) == 64
    assert len(receipt["catalog_seed_sha256"]) == 64
    assert ValuationFactModel.objects.count() == 0
    assert CanonicalPublicationModel.objects.count() == 0
    assert PublicationMemberModel.objects.count() == 0
    assert CoverageSnapshotModel.objects.count() == 0
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
