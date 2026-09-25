"""Candidate-bound PostgreSQL publication write/readback/rollback evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.data_center.application.query_services import query_published_valuation_facts
from apps.data_center.application.valuation_publication import PublishValuationBatchUseCase
from apps.data_center.domain.entities import ValuationFact
from core.exceptions import DataFetchError

from .catalog_runtime_repositories import DatasetContractRepository
from .control_plane_repositories import CanonicalPublicationRepository
from .fact_and_operational_models import ValuationFactModel
from .market_rehearsal_runner import verify_candidate_release_image
from .publication_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from .publication_policy_repository import PublicationPolicyRepository
from .valuation_fact_repository import ValuationFactRepository


def _assert_isolated_database() -> None:
    """Refuse all write rehearsal activity outside an explicitly isolated database."""
    name = str(connection.settings_dict.get("NAME") or "")
    if (
        connection.vendor != "postgresql"
        or connection.in_atomic_block
        or os.environ.get("AGOM_RELEASE_REHEARSAL_DATABASE") != "1"
        or re.fullmatch(r"agom_release_rehearsal_[a-z0-9_]+", name) is None
    ):
        raise DataFetchError(
            "Write rehearsal requires an explicitly isolated PostgreSQL database",
            code="REHEARSAL_WRITE_SCOPE_INVALID",
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


def collect_isolated_write_rehearsal(
    *,
    candidate_sha: str,
    target_trade_date: date,
    universe_sha256: str,
    provider_identities_sha256: str,
    output_dir: Path,
    source_root: Path,
) -> dict[str, object]:
    """Write and read a published valuation member, then roll the transaction back."""
    _assert_isolated_database()
    source_attestation, candidate_image_id = verify_candidate_release_image(
        source_root, candidate_sha
    )
    if output_dir.exists():
        raise ValueError("REHEARSAL_WRITE_OUTPUT_EXISTS")
    if re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None or any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (universe_sha256, provider_identities_sha256)
    ):
        raise ValueError("REHEARSAL_WRITE_IDENTITY_INVALID")

    started = datetime.now(UTC)
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
    database_identity_sha256 = _database_identity()

    with transaction.atomic():
        contract = DatasetContractRepository().get_active("equity.valuation.fact")
        policies = PublicationPolicyRepository()
        policy = policies.get_active("equity.valuation.fact")
        if contract is None or policy is None or contract.key != policy.dataset:
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
            fetched_at=started,
            available_at=started,
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
        publication = PublishValuationBatchUseCase(
            fact_repository=facts,
            publication_repository=publications,
            policy_repository=policies,
        ).execute(
            [fact],
            provider_name=source,
            publication_key=publication_key,
            published_at=started,
        )
        if publication is None:
            raise DataFetchError(
                "Isolated publication was not created",
                code="REHEARSAL_WRITE_PUBLICATION_FAILED",
            )
        publication_id = publication.publication_id
        member = publications.list_members(publication_id)[0]
        readback = query_published_valuation_facts(
            "000001.SZ",
            publication_key=publication_key,
        )
        rows_value = readback.get("rows")
        rows = (
            [cast(dict[str, object], row) for row in rows_value if isinstance(row, dict)]
            if isinstance(rows_value, list)
            else []
        )
        readback_verified = (
            readback.get("must_not_use_for_decision") is False
            and readback.get("publication_id") == publication_id
            and len(rows) == 1
            and rows[0].get("pe_ttm") == 12.5
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
        if not readback_verified or not publication_verified:
            raise DataFetchError(
                "Isolated publication readback failed",
                code="REHEARSAL_WRITE_READBACK_FAILED",
            )
        with transaction.atomic():
            ValuationFactModel.objects.filter(pk=member.fact_pk).update(pe_ttm=99)
            tampered = query_published_valuation_facts(
                "000001.SZ",
                publication_key=publication_key,
            )
            tamper_blocked = (
                tampered.get("must_not_use_for_decision") is True
                and tampered.get("blocked_reason") == "publication_member_fact_changed"
                and tampered.get("rows") == []
            )
            transaction.set_rollback(True)
        restored = query_published_valuation_facts(
            "000001.SZ",
            publication_key=publication_key,
        )
        if not tamper_blocked or restored.get("must_not_use_for_decision") is not False:
            raise DataFetchError(
                "Publication tamper guard was not reversible and fail-closed",
                code="REHEARSAL_WRITE_TAMPER_GUARD_FAILED",
            )
        written_rows = (
            ValuationFactModel.objects.filter(source=source).count()
            + CanonicalPublicationModel.objects.filter(publication_key=publication_key).count()
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
    rollback_verified = residual_rows == 0
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
