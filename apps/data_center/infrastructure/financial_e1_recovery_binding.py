"""Bind a one-shot no-transport financial recovery to its sealed source and both audits."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

from django.db import transaction

from apps.data_center.domain.control_plane import SyncRun, SyncRunStatus
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel, SyncRunModel
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataValidationError

RECOVERY_TRIGGER = "financial_e1_retained_recovery"


def forecast_digest(facts: tuple[FinancialFact, ...]) -> str:
    """Pin every predicted value, raw identity, unit and financial availability time."""

    rows = []
    for fact in facts:
        decision = fact.decision_evidence
        if decision is None or fact.available_at is None:
            raise DataValidationError("Recovery forecast lacks a verified row or availability.")
        ref = decision.artifact_reference
        rows.append(
            (
                fact.asset_code,
                fact.period_end.isoformat(),
                fact.period_type.value,
                fact.metric_code,
                fact.source,
                str(fact.value),
                fact.unit,
                decision.native_row_id,
                str(ref.capture_id),
                ref.body_sha256,
                fact.available_at.isoformat(),
            )
        )
    return hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode()).hexdigest()


def _forecast_binding(inputs: str, forecast: str) -> str:
    if len(forecast) != 64 or any(c not in "0123456789abcdef" for c in forecast):
        raise DataValidationError("Recovery requires an independently pinned forecast.")
    return hashlib.sha256((inputs + ":" + forecast).encode("ascii")).hexdigest()


def _source(source_id: UUID, plan_hash: str) -> SyncRun:
    source = SyncRunModel.objects.select_for_update().get(pk=source_id).to_domain()
    if not (
        source.trigger == "financial_e1_discovery"
        and source.config_snapshot_hash == plan_hash
        and source.contract_version == "financial-e1-discovery.v2"
        and source.status is SyncRunStatus.FAILED
        and source.outcome == "failed"
        and source.error_code == "FINANCIAL_FACT_PROVENANCE_CONFLICT"
        and source.fetched == 2
        and source.stored == source.succeeded == source.published == 0
        and source.failed == source.requested > 0
        and source.finished_at is not None
    ):
        raise DataValidationError(
            "Recovery requires the exact sealed zero-write provenance failure."
        )
    return source


def _binding(source: SyncRun, main: RawAudit, balance: RawAudit) -> str:
    rows = [main, balance]
    ids = list(
        RawAuditModel.objects.select_for_update()
        .filter(run_id=source.run_id, capability="financial", status="ok")
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if len(ids) != 2 or {str(pk) for pk in ids} != {row.raw_audit_id for row in rows}:
        raise DataValidationError("Recovery requires precisely the two original financial audits.")
    records = []
    for row in rows:
        ref = reference_from_audit(row)
        if (
            RawAuditRepository().get_by_id(row.raw_audit_id) != row
            or row.run_id != source.run_id
            or row.ingested_run_id != source.run_id
            or row.provider_name != source.provider_name
        ):
            raise DataValidationError("Retained recovery audit differs from its persisted source.")
        records.append([row.raw_audit_id, row.content_hash, str(ref.capture_id), ref.body_sha256])
    if records[0][2] == records[1][2]:
        raise DataValidationError("Recovery cannot use the same capture for both roles.")
    return hashlib.sha256(
        json.dumps(
            [RECOVERY_TRIGGER, source.run_id, source.config_snapshot_hash, records],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate_recovery_source(
    source_id: UUID, plan_hash: str, main: RawAudit, balance: RawAudit
) -> None:
    """Validate both locked originals against the exact sealed run before claiming it."""

    with transaction.atomic():
        _binding(_source(source_id, plan_hash), main, balance)


def claim_recovery(
    source_id: UUID, plan_hash: str, main: RawAudit, balance: RawAudit, forecast: str
) -> SyncRun:
    """Insert a unique durable claim before any write attempt, without updating the source."""

    with transaction.atomic():
        source = _source(source_id, plan_hash)
        digest = _forecast_binding(_binding(source, main, balance), forecast)
        recovery_id = uuid5(source_id, RECOVERY_TRIGGER)
        if SyncRunModel.objects.filter(pk=recovery_id).exists():
            raise DataValidationError("This source already has a retained recovery claim.")
        from django.utils.timezone import now

        return SyncRunModel.objects.create(
            run_id=recovery_id,
            dataset_key=source.dataset_key,
            provider_name=source.provider_name,
            requested=source.requested,
            trigger=RECOVERY_TRIGGER,
            status=SyncRunStatus.REQUESTED.value,
            outcome="blocked",
            started_at=now(),
            contract_version="financial-e1-retained-recovery.v1",
            config_snapshot_hash=digest,
        ).to_domain()


def validate_recovery_commit(
    run: SyncRun, main: RawAudit, balance: RawAudit, facts: tuple[FinancialFact, ...]
) -> None:
    """Lock the real source, claim, and both immutable rows again inside the fact transaction."""

    source_id = UUID(main.run_id)
    row = SyncRunModel.objects.select_for_update().get(pk=source_id)
    source = _source(source_id, row.config_snapshot_hash)
    persisted = SyncRunModel.objects.select_for_update().get(pk=run.run_id).to_domain()
    if (
        persisted != run
        or run.status is not SyncRunStatus.REQUESTED
        or run.finished_at is not None
        or run.trigger != RECOVERY_TRIGGER
        or run.run_id != str(uuid5(source_id, RECOVERY_TRIGGER))
        or run.dataset_key != source.dataset_key
        or run.provider_name != source.provider_name
        or run.requested != source.requested
        or run.config_snapshot_hash
        != _forecast_binding(_binding(source, main, balance), forecast_digest(facts))
    ):
        raise DataValidationError("Recovery claim does not match its locked source and captures.")
