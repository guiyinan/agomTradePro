"""Bind a one-shot no-transport financial recovery to its sealed source and both audits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from django.db import connection, transaction

from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1ExecutionAuthorityPort,
)
from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialMetricSourceCatalogEntryModel,
)

if TYPE_CHECKING:
    from apps.data_center.infrastructure.financial_e1_discovery_runtime import (
        DjangoFinancialE1SelectionLoader,
    )

from apps.data_center.domain.control_plane import SyncRun, SyncRunStatus
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel, SyncRunModel
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataValidationError

RECOVERY_TRIGGER = "financial_e1_retained_recovery"


def forecast_digest(facts: tuple[FinancialFact, ...], review_sha256: str | None = None) -> str:
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
    return hashlib.sha256(
        json.dumps(
            sorted(rows) if review_sha256 is None else [review_sha256, sorted(rows)],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


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
    run: SyncRun,
    main: RawAudit,
    balance: RawAudit,
    facts: tuple[FinancialFact, ...],
    review_sha256: str | None = None,
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
        != _forecast_binding(_binding(source, main, balance), forecast_digest(facts, review_sha256))
    ):
        raise DataValidationError("Recovery claim does not match its locked source and captures.")


@dataclass(frozen=True, slots=True)
class RetainedWriteReview:
    """Bind a separately approved current review to one sealed pair and source plan."""

    digest: str
    marker: str
    owner_id: int
    qualification_ids: tuple[str, ...]
    captures: tuple[UUID, UUID]
    completed: tuple[datetime, datetime]

    def verify_material_forecast(
        self, path: Path, *, facts: tuple[FinancialFact, ...], plan_hash: str, source: UUID
    ) -> None:
        """Compare the actual predicted rows to the independently reviewed original values."""
        body = path.read_bytes()
        if self.marker != f"retained-e1:{source}:{hashlib.sha256(body).hexdigest()}":
            raise ValueError("Official material bytes differ from the separate signed review.")
        review = json.loads(body)
        if (
            review["schema"] != "retained-e1-material-review.v1"
            or review["plan_sha256"] != plan_hash
            or review["source_run"] != str(source)
            or len(facts) != len(review["fields"])
            or set(review["fields"]) != {f.metric_code for f in facts}
        ):
            raise ValueError("Official material scope differs from the recovery forecast.")
        for fact in facts:
            row = review["fields"][fact.metric_code]
            if (
                fact.decision_evidence is None
                or str(fact.decision_evidence.artifact_reference.capture_id) != row["capture"]
                or Decimal(row["raw"]) != fact.value
                or row["unit"] != fact.unit
                or review["asset"] != fact.asset_code
                or review["period"] != fact.period_end.isoformat()
            ):
                raise ValueError("Forecast does not match an independently reviewed source value.")

    @classmethod
    def load(
        cls,
        path: Path,
        digest: str,
        *,
        source: UUID,
        plan_hash: str,
        operator: str,
        main: RawAudit,
        balance: RawAudit,
    ) -> RetainedWriteReview:
        """Require exact file bytes, original audit identities and the authenticated actor."""
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Retained write review digest mismatch.")
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {
            "schema",
            "plan_sha256",
            "source_run",
            "owner_id",
            "material_sha256",
            "qualifications",
        }:
            raise ValueError("Invalid retained write review fields.")
        owner, material, ids = data["owner_id"], data["material_sha256"], data["qualifications"]
        if (
            data["schema"] != "retained-e1-split-review.v1"
            or data["plan_sha256"] != plan_hash
            or data["source_run"] != str(source)
            or main.run_id != str(source)
            or balance.run_id != str(source)
            or type(owner) is not int
            or owner <= 0
            or operator != f"django-user:{owner}"
            or not isinstance(material, str)
            or len(material) != 64
            or any(c not in "0123456789abcdef" for c in material)
            or not isinstance(ids, list)
            or not ids
            or not all(isinstance(i, str) for i in ids)
            or ids != sorted(set(ids))
        ):
            raise ValueError("Retained write review identity or scope mismatch.")
        a, b = reference_from_audit(main), reference_from_audit(balance)
        if a.capture_id == b.capture_id:
            raise ValueError("Retained write review requires two distinct originals.")
        return cls(
            digest,
            f"retained-e1:{source}:{material}",
            owner,
            tuple(ids),
            (a.capture_id, b.capture_id),
            (a.evidence.response_completed_at, b.evidence.response_completed_at),
        )


def verify_reviewed_fields(
    original: FinancialNumericSourceQualification,
    current: FinancialNumericSourceQualification,
    *,
    marker: str,
    completed: datetime,
) -> None:
    """Compare the whole typed source contract, context, endpoint and official capture."""
    if (
        current.effective_from <= completed
        or current.effective_until is None
        or current
        != replace(
            original,
            source_applicability=marker,
            effective_from=current.effective_from,
            effective_until=current.effective_until,
        )
    ):
        raise ValueError(
            "Currently signed financial fields differ from their capture qualification."
        )


class RetainedWriteReviewGuard:
    """Verify the original eligibility clocks and lock the separate current Owner review."""

    def __init__(
        self,
        authority: FinancialE1ExecutionAuthorityPort,
        review: RetainedWriteReview,
        plan: FinancialE1DiscoveryPlanV2,
        loader: DjangoFinancialE1SelectionLoader,
    ) -> None:
        self.authority = authority
        self.review = review
        self.loader = loader
        self.current_plan = replace(plan, qualification_identities=review.qualification_ids)
        historical: dict[str, FinancialNumericSourceQualification] = {}
        for endpoint, stamp in zip(
            (plan.main_request.endpoint, plan.balance_request.endpoint),
            review.completed,
            strict=True,
        ):
            snapshot = loader.load(plan, known_at=stamp)
            for q in snapshot.qualifications:
                if q.endpoint == endpoint:
                    if q.contract.metric_code in historical:
                        raise ValueError("Duplicate metric in retained source selection.")
                    historical[q.contract.metric_code] = q
        if len(historical) != len(plan.qualification_identities):
            raise ValueError("Incomplete retained source selection.")
        self.historical = historical

    def assert_current(self) -> None:
        """Validate the signed write interval on the real clock, including inside the fact UOW."""
        self.authority.assert_current()
        if connection.in_atomic_block:
            # The catalog revoke command locks this same parent row before appending an event.
            list(
                FinancialMetricSourceCatalogEntryModel._default_manager.using("default")
                .select_for_update()
                .filter(qualification_identity__in=self.review.qualification_ids)
                .order_by("qualification_identity")
                .values_list("pk", flat=True)
            )
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            checked_at = cursor.fetchone()[0]
        current = self.loader.load(self.current_plan, known_at=checked_at)
        codes = [q.contract.metric_code for q in current.qualifications]
        if set(codes) != set(self.historical) or len(codes) != len(self.historical):
            raise ValueError("Current review must cover exactly the retained metrics.")
        for entry in current.entries:
            if (
                len(entry.owner_events) != 1
                or entry.owner_events[0].actor_id != self.review.owner_id
            ):
                raise ValueError("Retained write review is not signed by the bound Owner.")
            q = entry.qualification
            verify_reviewed_fields(
                self.historical[q.contract.metric_code],
                q,
                marker=self.review.marker,
                completed=max(self.review.completed),
            )
