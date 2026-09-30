"""Opt-in real PostgreSQL consistency, locking and rollback publication tests."""

import ipaddress
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from pathlib import Path
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

from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.publication_activation import (
    PublicationActivationRequest,
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
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit
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
from core.integration.data_center_audit import DataPublicationAuditObservation
from tests.component.data_center.test_current_publication_evidence_gate import _published_snapshot


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
        CanonicalPublicationPointerModel,
        CoverageSnapshotModel,
        PublicationMemberModel,
        SystemAuditEventModel,
        SystemAuditOutboxModel,
    )
    created = []
    with django_db_blocker.unblock():
        connections["default"] = wrapper
        try:
            assert wrapper.vendor == "postgresql"
            assert wrapper.introspection.table_names() == [], "Refuse any preexisting test tables"
            with wrapper.schema_editor() as editor:
                for model in models:
                    editor.create_model(model)
                    created.append(model)
            yield _PGProbeFactory(credentials)
        finally:
            if created:
                with wrapper.schema_editor() as editor:
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
            CanonicalPublicationPointerModel,
            CoverageSnapshotModel,
            PublicationMemberModel,
            SystemAuditEventModel,
            SystemAuditOutboxModel,
        )
        expected = {model._meta.db_table for model in models}
        assert set(wrapper.introspection.table_names()) == expected
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


@dataclass(frozen=True)
class _ActivationFenceFingerprint:
    complete_graph_hash: str = "f" * 64


@dataclass(frozen=True)
class _ActivationFenceResult:
    database_alias: str = "default"
    tenant_id: str = "tenant-soak"
    owner_id: str = "owner-soak"
    generation: int = 1
    fingerprint: _ActivationFenceFingerprint = _ActivationFenceFingerprint()
    checked_at: datetime = datetime.now(UTC)
    valid_until: datetime = datetime.now(UTC) + timedelta(hours=1)
    scope: str = "account_authority_complete_graph"


class _PostgresActivationFence:
    """Feature-off test fence with the same caller-owned RC/RW shape."""

    @contextmanager
    def fence_complete(self, proof: object) -> Iterator[_ActivationFenceResult]:
        assert proof == "soak-proof"
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
                cursor.execute("SELECT CURRENT_TIMESTAMP")
                checked_at = cursor.fetchone()[0]
            yield _ActivationFenceResult(
                checked_at=checked_at,
                valid_until=checked_at + timedelta(hours=1),
            )


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


def _build_activation_soak_snapshot() -> tuple[PublicationActivationRequest, str, str]:
    """Build one 5,001-member candidate with exact persisted facts and raw evidence."""

    dataset_key = "equity.valuation.fact"
    now = timezone.now() - timedelta(minutes=5)
    policy = PublicationPolicy(
        dataset=DatasetKey(dataset_key, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="activation-soak",
    )
    PublicationPolicyRepository().save(policy)
    run_id = uuid4()
    ingested_run_id = uuid4()
    ValuationFactModel.objects.bulk_create(
        [
            ValuationFactModel(
                asset_code=f"SOAK{i:06d}.SZ",
                val_date=now.date(),
                pe_ttm=12 + (i % 100) / 10,
                source="soak",
                observed_at=now,
                available_at=now,
                fetched_at=now,
                extra={"raw_payload_scope": "batch_response_body"},
                source_record_id=f"soak-record-{i}",
                raw_payload_hash="a" * 64,
                quality_status="accepted",
                revision_number=1,
                ingested_run_id=ingested_run_id,
            )
            for i in range(_ACTIVATION_SOAK_MEMBER_COUNT)
        ],
        batch_size=1000,
    )
    facts = list(ValuationFactModel.objects.filter(source="soak").order_by("pk"))
    references = [
        publication_fact_reference_for_dataset(row, dataset_key=dataset_key) for row in facts
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
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name="soak",
            capability="valuation",
            request_params={"member_count": _ACTIVATION_SOAK_MEMBER_COUNT},
            status="ok",
            row_count=_ACTIVATION_SOAK_MEMBER_COUNT,
            fetched_at=now,
            run_id=str(run_id),
            ingested_run_id=str(ingested_run_id),
            response_payload_hash="b" * 64,
            schema_fingerprint="c" * 64,
            parser_version="activation-soak",
        )
    )
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.CANDIDATE,
        selected_source="soak",
        publication_hash=publication_hash(
            references,
            policy_identity=policy.identity,
        ),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=_ACTIVATION_SOAK_MEMBER_COUNT,
            eligible_count=_ACTIVATION_SOAK_MEMBER_COUNT,
            selected_count=_ACTIVATION_SOAK_MEMBER_COUNT,
            missing_count=0,
            conflict_count=0,
            generated_at=now,
        ),
        member_count=_ACTIVATION_SOAK_MEMBER_COUNT,
        as_of=now,
        created_by="test.activation.soak",
        run_id=str(run_id),
    )
    DjangoPublicationActivationRepository().stage_candidate_with_members(publication, members)
    raw_reference = raw.exact_reference()
    observation = DataPublicationAuditObservation(
        dataset_key=dataset_key,
        publication_key="current",
        publication_id=publication_id,
        publication_version=policy.identity,
        publication_hash=publication.publication_hash,
        provider_key="soak",
        run_id=str(run_id),
        ingested_run_id=str(ingested_run_id),
        member_count=_ACTIVATION_SOAK_MEMBER_COUNT,
        coverage_requested_count=_ACTIVATION_SOAK_MEMBER_COUNT,
        coverage_eligible_count=_ACTIVATION_SOAK_MEMBER_COUNT,
        coverage_selected_count=_ACTIVATION_SOAK_MEMBER_COUNT,
        outcome=AuditOutcome.PUBLISHED,
        raw_audit_id=raw_reference.raw_audit_id,
        raw_audit_version=raw_reference.version,
        raw_audit_content_hash=raw_reference.content_hash,
        occurred_at=now,
        recorded_at=raw.fetched_at,
        scope=AuditScopeRef(tenant_id="tenant-soak", owner_id="owner-soak"),
    )
    request = PublicationActivationRequest(
        dataset_key=dataset_key,
        publication_key="current",
        candidate_publication_id=publication_id,
        candidate_publication_hash=publication.publication_hash,
        activation_id="activation-soak-1",
        audit_observation=observation,
    )
    return request, publication_id, raw.raw_audit_id


def test_activation_5001_members_has_fixed_queries_locks_and_retry(
    actual_publication_pg,
) -> None:
    """Exercise the short RC/RW activation with a real 5,001-member graph."""

    request, publication_id, raw_audit_id = _build_activation_soak_snapshot()
    repository = DjangoPublicationActivationRepository()
    writer = _PostgresActivationAuditWriter()
    started = monotonic()
    with CaptureQueriesContext(connections["default"]) as captured:
        activated = repository.activate_candidate(
            request,
            audit_writer=writer,
            authority_fence=_PostgresActivationFence(),
            authority_proof="soak-proof",
        )
    held_seconds = monotonic() - started

    assert activated.publication_id == publication_id
    query_count = len(captured.captured_queries)
    assert query_count <= _ACTIVATION_SOAK_MAX_QUERIES, (
        f"activation query count {query_count} exceeds " f"{_ACTIVATION_SOAK_MAX_QUERIES}"
    )
    assert held_seconds <= _ACTIVATION_SOAK_MAX_HELD_SECONDS, (
        f"activation held locks for {held_seconds:.6f}s across {query_count} queries; "
        f"limit is {_ACTIVATION_SOAK_MAX_HELD_SECONDS:.6f}s"
    )
    assert (
        PublicationMemberModel._default_manager.filter(publication_id=publication_id).count()
        == _ACTIVATION_SOAK_MEMBER_COUNT
    )
    pointer = CanonicalPublicationPointerModel._default_manager.get(
        dataset_key=request.dataset_key,
        publication_key=request.publication_key,
    )
    assert str(pointer.publication_id) == publication_id
    assert pointer.activation_id == request.activation_id
    assert RawAuditModel._default_manager.filter(pk=raw_audit_id).exists()
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1

    repository.activate_candidate(
        request,
        audit_writer=_PostgresActivationAuditWriter(),
        authority_fence=_PostgresActivationFence(),
        authority_proof="soak-proof",
    )
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1

    probe = actual_publication_pg.connect()
    try:
        probe.execute("BEGIN")
        probe.execute(
            """
            SELECT pointer_id
            FROM data_center_canonical_publication_pointer
            WHERE dataset_key=%s AND publication_key=%s
            FOR UPDATE
            """,
            [request.dataset_key, request.publication_key],
        )
        with connections["default"].cursor() as cursor:
            cursor.execute("SET lock_timeout = '150ms'")
        blocked_started = monotonic()
        with pytest.raises(OperationalError):
            repository.activate_candidate(
                request,
                audit_writer=_PostgresActivationAuditWriter(),
                authority_fence=_PostgresActivationFence(),
                authority_proof="soak-proof",
            )
        lock_wait_seconds = monotonic() - blocked_started
        assert lock_wait_seconds <= _ACTIVATION_SOAK_MAX_LOCK_WAIT_SECONDS, (
            f"pointer lock wait {lock_wait_seconds:.6f}s exceeds "
            f"{_ACTIVATION_SOAK_MAX_LOCK_WAIT_SECONDS:.6f}s"
        )
    finally:
        with connections["default"].cursor() as cursor:
            cursor.execute("SET lock_timeout = '0'")
        probe.rollback()
        probe.close()


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
