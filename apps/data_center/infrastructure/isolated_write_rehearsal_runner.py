"""Candidate-bound PostgreSQL publication write/readback/rollback evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.data_center.application.current_publication_evidence import (
    current_publication_evidence_blocked_reason,
)
from apps.data_center.application.publication_gate_metadata import publication_gate_metadata
from apps.data_center.application.publication_query_bounds import publication_freshness_gate
from apps.data_center.application.query_services import (
    query_published_valuation_facts,
)
from apps.data_center.application.valuation_publication import PublishValuationBatchUseCase
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import ValuationFact
from core.exceptions import DataFetchError

from .catalog_runtime_repositories import DatasetContractRepository
from .control_plane_repositories import CanonicalPublicationRepository
from .fact_and_operational_models import ValuationFactModel
from .market_rehearsal_runner import verify_candidate_release_image
from .publication_member_store import publication_fact_content_hashes
from .publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from .publication_policy_repository import PublicationPolicyRepository
from .valuation_fact_repository import ValuationFactRepository


def _connected_database_identity() -> tuple[str, str, int]:
    """Read the database and server endpoint from the established PostgreSQL session."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), COALESCE(host(inet_server_addr()), ''), "
            "COALESCE(inet_server_port(), 0)"
        )
        database_name, server_address, server_port = cursor.fetchone()
    return str(database_name), str(server_address), int(server_port)


def _resolved_host_addresses(host: str, port: int) -> set[str]:
    """Resolve an expected database host into normalized network addresses."""
    try:
        return {str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise DataFetchError(
            "Expected rehearsal database host cannot be resolved",
            code="REHEARSAL_WRITE_SCOPE_HOST_UNRESOLVED",
        ) from exc


def _assert_isolated_database(
    *,
    expected_database_name: str,
    expected_database_host: str,
    require_ephemeral_host: bool,
) -> None:
    """Refuse all write rehearsal activity outside an explicitly isolated database."""
    name = str(connection.settings_dict.get("NAME") or "")
    host = str(connection.settings_dict.get("HOST") or "")
    port = int(connection.settings_dict.get("PORT") or 5432)
    if connection.vendor != "postgresql":
        raise DataFetchError(
            "Write rehearsal requires PostgreSQL",
            code="REHEARSAL_WRITE_SCOPE_VENDOR_INVALID",
        )
    if connection.in_atomic_block:
        raise DataFetchError(
            "Write rehearsal cannot run inside an existing transaction",
            code="REHEARSAL_WRITE_SCOPE_TRANSACTION_ACTIVE",
        )
    if os.environ.get("AGOM_RELEASE_REHEARSAL_DATABASE") != "1":
        raise DataFetchError(
            "Write rehearsal requires explicit disposable-database opt-in",
            code="REHEARSAL_WRITE_SCOPE_OPT_IN_MISSING",
        )
    if re.fullmatch(r"agom_release_rehearsal_[a-z0-9_]+", name) is None:
        raise DataFetchError(
            "Configured database name is not a rehearsal database",
            code="REHEARSAL_WRITE_SCOPE_DATABASE_NAME_INVALID",
        )
    if name != expected_database_name:
        raise DataFetchError(
            "Configured database name does not match the expected rehearsal database",
            code="REHEARSAL_WRITE_SCOPE_DATABASE_NAME_MISMATCH",
        )
    if host != expected_database_host:
        raise DataFetchError(
            "Configured database host does not match the expected rehearsal host",
            code="REHEARSAL_WRITE_SCOPE_HOST_CONFIG_MISMATCH",
        )
    if require_ephemeral_host and re.fullmatch(r"agom-s6-postgres-[a-z0-9-]+", host) is None:
        raise DataFetchError(
            "Configured database host is not an ephemeral S6 host",
            code="REHEARSAL_WRITE_SCOPE_HOST_NOT_EPHEMERAL",
        )
    actual_name, server_address, server_port = _connected_database_identity()
    if actual_name != expected_database_name:
        raise DataFetchError(
            "Connected database does not match the expected rehearsal database",
            code="REHEARSAL_WRITE_SCOPE_CONNECTED_DATABASE_MISMATCH",
        )
    if server_port != port:
        raise DataFetchError(
            "Connected database port does not match the configured rehearsal port",
            code="REHEARSAL_WRITE_SCOPE_CONNECTED_PORT_MISMATCH",
        )
    if server_address not in _resolved_host_addresses(expected_database_host, port):
        raise DataFetchError(
            "Connected database address does not match the expected rehearsal host",
            code="REHEARSAL_WRITE_SCOPE_CONNECTED_ADDRESS_MISMATCH",
        )


def assert_isolated_rehearsal_database(
    *,
    expected_database_name: str,
    expected_database_host: str,
    require_ephemeral_host: bool,
) -> None:
    """Validate that the active connection is the disposable rehearsal database."""
    _assert_isolated_database(
        expected_database_name=expected_database_name,
        expected_database_host=expected_database_host,
        require_ephemeral_host=require_ephemeral_host,
    )


def _canonical_json_digest(value: object) -> str:
    """Hash stable JSON identity material."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> str:
    """Create one immutable canonical JSON artifact and return its digest."""
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _database_identity() -> str:
    """Bind the disposable database server, principal and fully migrated schema."""
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise DataFetchError(
            "Isolated database has unapplied migrations",
            code="REHEARSAL_WRITE_MIGRATIONS_PENDING",
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_user, "
            "COALESCE(inet_server_addr()::text, 'local'), "
            "COALESCE(inet_server_port(), 0), current_setting('server_version_num')"
        )
        database_name, database_user, server_address, server_port, server_version = (
            cursor.fetchone()
        )
    return _canonical_json_digest(
        {
            "database_name_sha256": hashlib.sha256(str(database_name).encode()).hexdigest(),
            "database_user_sha256": hashlib.sha256(str(database_user).encode()).hexdigest(),
            "server_address_sha256": hashlib.sha256(str(server_address).encode()).hexdigest(),
            "server_port": int(server_port),
            "server_version": str(server_version),
            "migrations": sorted(
                f"{app}:{name}" for app, name in MigrationRecorder(connection).applied_migrations()
            ),
        }
    )


def _publication_clock_cutoff(
    *,
    dataset_key: str,
    publication_key: str,
) -> tuple[datetime, datetime | None]:
    """Read one database clock cutoff and the latest active publication time."""

    table = connection.ops.quote_name(CanonicalPublicationModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                clock_timestamp(),
                MAX(published_at),
                BOOL_OR(published_at IS NULL)
            FROM {table}
            WHERE dataset_key = %s
              AND publication_key = %s
              AND state = %s
            """,
            [dataset_key, publication_key, PublicationState.PUBLISHED.value],
        )
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], datetime) or row[0].tzinfo is None:
        raise DataFetchError(
            "Database publication clock cutoff is unavailable",
            code="REHEARSAL_WRITE_PUBLICATION_CLOCK_UNAVAILABLE",
        )
    cutoff = row[0].astimezone(UTC)
    latest = row[1]
    if row[2] is True or (
        latest is not None and (not isinstance(latest, datetime) or latest.tzinfo is None)
    ):
        raise DataFetchError(
            "Current publication clock evidence is invalid",
            code="REHEARSAL_WRITE_PUBLICATION_CLOCK_INVALID",
        )
    normalized_latest = latest.astimezone(UTC) if latest is not None else None
    if normalized_latest is not None and normalized_latest >= cutoff:
        raise DataFetchError(
            "Current publication time is later than the database clock cutoff",
            code="REHEARSAL_WRITE_PUBLICATION_CLOCK_INVALID",
        )
    return cutoff, normalized_latest


@contextmanager
def _read_only_preflight_transaction() -> Iterator[None]:
    """Enforce a repeatable-read, read-only PostgreSQL snapshot for preflight queries."""

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT current_setting('transaction_read_only')")
            row = cursor.fetchone()
        if not row or row[0] != "on":
            raise DataFetchError(
                "Rehearsal preflight read-only transaction is unavailable",
                code="REHEARSAL_WRITE_PREFLIGHT_READ_ONLY_UNAVAILABLE",
            )
        yield


def _is_read_only_violation(exception: BaseException) -> bool:
    """Return whether a wrapped PostgreSQL error is SQLSTATE 25006."""

    current: BaseException | None = exception
    visited: set[int] = set()
    for _ in range(5):
        if current is None or id(current) in visited:
            break
        visited.add(id(current))
        for attribute_name in ("sqlstate", "pgcode"):
            try:
                sqlstate = getattr(current, attribute_name, None)
            except Exception:
                sqlstate = None
            if sqlstate == "25006":
                return True
        current = current.__cause__ or current.__context__
    return False


def preflight_isolated_write_rehearsal(
    *,
    candidate_sha: str,
    source_root: Path,
    expected_database_name: str,
    expected_database_host: str,
    require_ephemeral_host: bool,
) -> tuple[str, str, str]:
    """Bind a migrated isolated database to the exact candidate before any setup write."""
    assert_isolated_rehearsal_database(
        expected_database_name=expected_database_name,
        expected_database_host=expected_database_host,
        require_ephemeral_host=require_ephemeral_host,
    )
    source_attestation, candidate_image_id = verify_candidate_release_image(
        source_root, candidate_sha
    )
    try:
        with _read_only_preflight_transaction():
            database_identity = _database_identity()
    except DatabaseError as exc:
        code = (
            "REHEARSAL_WRITE_PREFLIGHT_READ_ONLY_VIOLATION"
            if _is_read_only_violation(exc)
            else "REHEARSAL_WRITE_PREFLIGHT_DATABASE_UNAVAILABLE"
        )
        raise DataFetchError("Rehearsal database preflight failed", code=code) from exc
    return source_attestation, candidate_image_id, database_identity


def collect_isolated_write_rehearsal(
    *,
    candidate_sha: str,
    target_trade_date: date,
    universe_sha256: str,
    provider_identities_sha256: str,
    output_dir: Path,
    source_root: Path,
    expected_database_name: str,
    expected_database_host: str,
) -> dict[str, object]:
    """Write and read a published valuation member, then roll the transaction back."""
    source_attestation, candidate_image_id, database_identity_sha256 = (
        preflight_isolated_write_rehearsal(
            candidate_sha=candidate_sha,
            source_root=source_root,
            expected_database_name=expected_database_name,
            expected_database_host=expected_database_host,
            require_ephemeral_host=True,
        )
    )
    if output_dir.exists():
        raise ValueError("REHEARSAL_WRITE_OUTPUT_EXISTS")
    if re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None or any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (universe_sha256, provider_identities_sha256)
    ):
        raise ValueError("REHEARSAL_WRITE_IDENTITY_INVALID")

    publication_id = ""
    source = f"release-rehearsal-{candidate_sha[:12]}"
    publication_key = "current"
    observed_at = datetime(
        target_trade_date.year,
        target_trade_date.month,
        target_trade_date.day,
        15,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    ).astimezone(UTC)
    available_at = observed_at + timedelta(minutes=1)
    identity = {
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "target_trade_date": target_trade_date.isoformat(),
        "universe_sha256": universe_sha256,
        "provider_identities_sha256": provider_identities_sha256,
    }
    identity_digest = _canonical_json_digest(identity)
    readback_verified = False
    publication_verified = False
    written_rows = 0
    tamper_blocked = False
    with transaction.atomic():
        database_clock_cutoff, prior_current_published_at = _publication_clock_cutoff(
            dataset_key="equity.valuation.fact",
            publication_key=publication_key,
        )
        started = database_clock_cutoff
        published_at = database_clock_cutoff
        knowledge_cutoff = database_clock_cutoff
        contract = DatasetContractRepository().get_active("equity.valuation.fact")
        policies = PublicationPolicyRepository()
        policy = policies.get_active("equity.valuation.fact")
        if (
            contract is None
            or policy is None
            or contract.key != policy.dataset
            or contract.freshness_seconds is None
        ):
            raise DataFetchError(
                "Candidate valuation catalog seed is incomplete or inconsistent",
                code="REHEARSAL_WRITE_CATALOG_UNAVAILABLE",
            )
        catalog_seed_sha256 = _canonical_json_digest(
            {"contract": asdict(contract), "policy": asdict(policy)}
        )
        synthetic_payload = json.dumps(
            {"identity": identity, "asset_code": "000001.SZ", "pe_ttm": 12.5},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        synthetic_payload_sha256 = hashlib.sha256(synthetic_payload).hexdigest()
        fact = ValuationFact(
            asset_code="000001.SZ",
            val_date=target_trade_date,
            pe_ttm=12.5,
            pb=1.25,
            market_cap=1_000_000_000.0,
            source=source,
            observed_at=observed_at,
            fetched_at=available_at,
            available_at=available_at,
            source_record_id=identity_digest,
            raw_payload_hash=synthetic_payload_sha256,
            extra={
                "release_rehearsal": identity,
                "raw_payload_scope": "record_response_body",
                "availability_basis": "response_completed_utc",
            },
        )
        facts = ValuationFactRepository()
        if facts.bulk_upsert([fact]) != 1:
            raise DataFetchError(
                "Isolated fact persistence failed",
                code="REHEARSAL_WRITE_FACT_FAILED",
            )
        publications = CanonicalPublicationRepository()
        baseline_scope_publications = tuple(
            CanonicalPublicationModel.objects.filter(
                dataset_key="equity.valuation.fact",
                publication_key=publication_key,
            )
            .order_by("publication_id")
            .values_list(
                "publication_id",
                "state",
                "publication_hash",
                "published_at",
                "superseded_at",
            )
        )
        pointer_before = (
            CanonicalPublicationPointerModel.objects.filter(
                dataset_key="equity.valuation.fact",
                publication_key=publication_key,
            )
            .values_list(
                "publication_id",
                "publication_hash",
                "activation_id",
            )
            .first()
        )
        baseline_graph_publication_ids = tuple(
            row[0]
            for row in baseline_scope_publications
            if row[1] == PublicationState.PUBLISHED.value
            or (pointer_before is not None and row[0] == pointer_before[0])
        )
        baseline_graph_members = tuple(
            PublicationMemberModel.objects.filter(publication_id__in=baseline_graph_publication_ids)
            .order_by("member_id")
            .values_list()
        )
        baseline_graph_coverage = tuple(
            CoverageSnapshotModel.objects.filter(publication_id__in=baseline_graph_publication_ids)
            .order_by("coverage_id")
            .values_list()
        )
        publication = PublishValuationBatchUseCase(
            fact_repository=facts,
            publication_repository=publications,
            policy_repository=policies,
        ).execute(
            [fact],
            provider_name=source,
            publication_key=publication_key,
            published_at=published_at,
        )
        if publication is None:
            raise DataFetchError(
                "Isolated publication was not created",
                code="REHEARSAL_WRITE_PUBLICATION_FAILED",
            )
        publication_id = publication.publication_id
        member = publications.list_members(publication_id)[0]
        current_readback = query_published_valuation_facts(
            "000001.SZ",
            publication_key=publication_key,
        )
        pointer_after = (
            CanonicalPublicationPointerModel.objects.filter(
                dataset_key="equity.valuation.fact",
                publication_key=publication_key,
            )
            .values_list(
                "publication_id",
                "publication_hash",
                "activation_id",
            )
            .first()
        )
        current_pointer_preserved_verified = pointer_after == pointer_before
        legacy_current_fail_closed_verified = (
            current_readback.get("must_not_use_for_decision") is True
            and current_readback.get("blocked_reason") == "canonical_publication_missing"
            and current_readback.get("rows") == []
            and publications.get_current("equity.valuation.fact", publication_key) is None
            and current_pointer_preserved_verified
        )
        current_time_stale_expected = (
            started - observed_at
        ).total_seconds() > contract.freshness_seconds
        rows = facts.get_series(
            "000001.SZ",
            end=target_trade_date,
            fact_pks=(member.fact_pk,),
        )
        fact_hashes = publication_fact_content_hashes((member,))
        evidence_reason = current_publication_evidence_blocked_reason(
            publication,
            policy=policy,
            members=(member,),
            fact_content_hashes=fact_hashes,
            knowledge_cutoff=knowledge_cutoff,
        )
        freshness = publication_freshness_gate(
            publication_gate_metadata(
                publication,
                requested_dataset_key="equity.valuation.fact",
                requested_publication_key=publication_key,
            ),
            observed_at=member.observed_at,
            publication_as_of=publication.as_of,
            reference=started,
            max_age_seconds=contract.freshness_seconds,
        )
        if current_time_stale_expected:
            current_time_freshness_guard_verified = (
                freshness.get("must_not_use_for_decision") is True
                and freshness.get("blocked_reason") == "canonical_publication_stale"
            )
        else:
            current_time_freshness_guard_verified = (
                freshness.get("must_not_use_for_decision") is False
            )
        readback_verified = (
            len(rows) == 1
            and rows[0].pe_ttm == 12.5
            and fact_hashes.get((member.fact_table, member.fact_pk)) == member.fact_content_hash
            and evidence_reason is None
        )
        publication_verified = (
            publication.state.value == "published"
            and publication.member_count == 1
            and member.fact_table == ValuationFactModel._meta.db_table
            and member.fact_content_hash != member.raw_payload_hash
            and CanonicalPublicationModel.objects.filter(
                publication_id=publication_id,
                publication_hash=publication.publication_hash,
                coverage_selected_count=1,
            ).exists()
            and CoverageSnapshotModel.objects.filter(
                publication_id=publication_id,
                selected_count=1,
            ).exists()
        )
        if (
            not legacy_current_fail_closed_verified
            or not current_time_freshness_guard_verified
            or not readback_verified
            or not publication_verified
        ):
            raise DataFetchError(
                "Isolated publication readback failed",
                code="REHEARSAL_WRITE_READBACK_FAILED",
            )
        with transaction.atomic():
            ValuationFactModel.objects.filter(pk=member.fact_pk).update(pe_ttm=99)
            tampered_hashes = publication_fact_content_hashes((member,))
            tamper_reason = current_publication_evidence_blocked_reason(
                publication,
                policy=policy,
                members=(member,),
                fact_content_hashes=tampered_hashes,
                knowledge_cutoff=knowledge_cutoff,
            )
            tamper_blocked = tamper_reason in {
                "publication_member_evidence_missing",
                "publication_member_fact_changed",
            }
            transaction.set_rollback(True)
        restored_hashes = publication_fact_content_hashes((member,))
        restored_reason = current_publication_evidence_blocked_reason(
            publication,
            policy=policy,
            members=(member,),
            fact_content_hashes=restored_hashes,
            knowledge_cutoff=knowledge_cutoff,
        )
        if not tamper_blocked or restored_reason is not None:
            raise DataFetchError(
                "Publication tamper guard was not reversible and fail-closed",
                code="REHEARSAL_WRITE_TAMPER_GUARD_FAILED",
            )
        written_rows = (
            ValuationFactModel.objects.filter(source=source).count()
            + CanonicalPublicationModel.objects.filter(publication_id=publication_id).count()
            + PublicationMemberModel.objects.filter(publication_id=publication_id).count()
            + CoverageSnapshotModel.objects.filter(publication_id=publication_id).count()
        )
        if written_rows != 4:
            raise DataFetchError(
                "Isolated write did not create the expected production records",
                code="REHEARSAL_WRITE_COUNT_INVALID",
            )
        transaction.set_rollback(True)

    residual_rows = (
        ValuationFactModel.objects.filter(source=source).count()
        + CanonicalPublicationModel.objects.filter(publication_id=publication_id).count()
        + PublicationMemberModel.objects.filter(publication_id=publication_id).count()
        + CoverageSnapshotModel.objects.filter(publication_id=publication_id).count()
    )
    pointer_after_rollback = (
        CanonicalPublicationPointerModel.objects.filter(
            dataset_key="equity.valuation.fact",
            publication_key=publication_key,
        )
        .values_list(
            "publication_id",
            "publication_hash",
            "activation_id",
        )
        .first()
    )
    scope_publications_after_rollback = tuple(
        CanonicalPublicationModel.objects.filter(
            dataset_key="equity.valuation.fact",
            publication_key=publication_key,
        )
        .order_by("publication_id")
        .values_list(
            "publication_id",
            "state",
            "publication_hash",
            "published_at",
            "superseded_at",
        )
    )
    graph_members_after_rollback = tuple(
        PublicationMemberModel.objects.filter(publication_id__in=baseline_graph_publication_ids)
        .order_by("member_id")
        .values_list()
    )
    graph_coverage_after_rollback = tuple(
        CoverageSnapshotModel.objects.filter(publication_id__in=baseline_graph_publication_ids)
        .order_by("coverage_id")
        .values_list()
    )
    current_pointer_rollback_verified = pointer_after_rollback == pointer_before
    publication_graph_rollback_verified = (
        scope_publications_after_rollback == baseline_scope_publications
        and graph_members_after_rollback == baseline_graph_members
        and graph_coverage_after_rollback == baseline_graph_coverage
    )
    rollback_verified = (
        residual_rows == 0
        and current_pointer_rollback_verified
        and publication_graph_rollback_verified
    )
    if not rollback_verified:
        raise DataFetchError(
            "Isolated write rollback left residual rows",
            code="REHEARSAL_ROLLBACK_RESIDUAL",
        )
    finished = datetime.now(UTC)
    receipt: dict[str, object] = {
        "schema": "release.isolated-write-receipt.v1",
        **identity,
        "outcome": "success",
        "database_scope": "isolated_staging",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "written_rows": written_rows,
        "publication_verified": publication_verified,
        "readback_verified": readback_verified,
        "exact_member_fact_readback_verified": readback_verified,
        "legacy_current_fail_closed_verified": legacy_current_fail_closed_verified,
        "current_pointer_preserved_verified": current_pointer_preserved_verified,
        "current_pointer_rollback_verified": current_pointer_rollback_verified,
        "publication_graph_rollback_verified": publication_graph_rollback_verified,
        "publication_clock_source": "database_clock_timestamp",
        "publication_clock_cutoff": database_clock_cutoff.isoformat(),
        "prior_current_published_at": (
            prior_current_published_at.isoformat()
            if prior_current_published_at is not None
            else None
        ),
        "publication_published_at": published_at.isoformat(),
        "current_time_stale_expected": current_time_stale_expected,
        "current_time_freshness_guard_verified": current_time_freshness_guard_verified,
        "tamper_guard_verified": tamper_blocked,
        "rollback_verified": rollback_verified,
        "residual_rows": residual_rows,
        "publication_hash": publication.publication_hash,
        "publication_id": publication_id,
        "publication_key": publication_key,
        "member_id": member.member_id,
        "member_fact_pk": member.fact_pk,
        "member_fact_content_hash": member.fact_content_hash,
        "database_identity_sha256": database_identity_sha256,
        "catalog_seed_sha256": catalog_seed_sha256,
        "payload_evidence_mode": "synthetic_isolated_writer_path",
        "synthetic_payload_sha256": synthetic_payload_sha256,
        "candidate_source_attestation": source_attestation,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    receipt_digest = _write_json(output_dir / "isolated-write-receipt.json", receipt)
    report: dict[str, object] = {
        "schema": "release.isolated-write-rehearsal.v1",
        "kind": "isolated_write_rehearsal",
        "evidence_mode": "isolated_postgresql",
        **identity,
        "outcome": "success",
        "candidate_source_attestation": source_attestation,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "database_scope": "isolated_staging",
        "written_rows": written_rows,
        "publication_verified": publication_verified,
        "readback_verified": readback_verified,
        "exact_member_fact_readback_verified": readback_verified,
        "legacy_current_fail_closed_verified": legacy_current_fail_closed_verified,
        "current_pointer_preserved_verified": current_pointer_preserved_verified,
        "current_pointer_rollback_verified": current_pointer_rollback_verified,
        "publication_graph_rollback_verified": publication_graph_rollback_verified,
        "publication_clock_source": "database_clock_timestamp",
        "publication_clock_cutoff": database_clock_cutoff.isoformat(),
        "prior_current_published_at": (
            prior_current_published_at.isoformat()
            if prior_current_published_at is not None
            else None
        ),
        "publication_published_at": published_at.isoformat(),
        "current_time_stale_expected": current_time_stale_expected,
        "current_time_freshness_guard_verified": current_time_freshness_guard_verified,
        "tamper_guard_verified": tamper_blocked,
        "rollback_verified": rollback_verified,
        "residual_rows": residual_rows,
        "publication_hash": publication.publication_hash,
        "publication_id": publication_id,
        "publication_key": publication_key,
        "member_id": member.member_id,
        "member_fact_pk": member.fact_pk,
        "member_fact_content_hash": member.fact_content_hash,
        "database_identity_sha256": database_identity_sha256,
        "catalog_seed_sha256": catalog_seed_sha256,
        "payload_evidence_mode": "synthetic_isolated_writer_path",
        "synthetic_payload_sha256": synthetic_payload_sha256,
        "write_artifacts": [{"path": "isolated-write-receipt.json", "sha256": receipt_digest}],
    }
    _write_json(output_dir / "isolated-write-rehearsal.json", report)
    return report
