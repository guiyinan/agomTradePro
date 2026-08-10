"""Strict append-only persistence and exact PIT reads for R7 monitoring."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoringCommand,
    R7MonitoringClock,
    R7MonitoringEvaluationEvidence,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    R7MonitoringAssessmentRef,
    R7MonitoringAuditEntry,
    R7MonitoringAuditPage,
    R7MonitoringPersistenceConflict,
    R7MonitoringPersistenceCorruption,
    R7MonitoringPersistenceUnavailable,
    R7PersistedMonitoringAssessment,
    derive_r7_monitoring_assessment_id,
    r7_monitoring_evidence_hash,
)
from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationMember,
)
from apps.research.infrastructure.r7_post_promotion_monitoring_audit_codec import (
    _R7MonitoringAuditSnapshot,
    create_r7_monitoring_audit_snapshot,
    decode_r7_monitoring_audit_cursor,
    decode_r7_monitoring_audit_snapshot,
    encode_r7_monitoring_audit_cursor,
    encode_r7_monitoring_audit_snapshot,
)
from apps.research.infrastructure.r7_post_promotion_monitoring_codec import (
    R7MonitoringCodecError,
    decode_r7_monitoring_evidence,
    encode_r7_monitoring_evidence,
)
from apps.research.infrastructure.r7_post_promotion_monitoring_models import (
    R7MonitoringAssessmentLedgerModel,
    R7MonitoringAuditSnapshotModel,
    R7MonitoringObservationLedgerModel,
    _activate_r7_monitoring_uow,
    _claim_r7_monitoring_insert,
    _require_active_r7_monitoring_uow,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel


class DjangoR7MonitoringClock:
    """Django timezone-backed trusted monitoring clock."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias shared with monitoring repositories."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoR7MonitoringRepository:
    """Public exact PIT repository without a write capability token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7MonitoringClock | None = None,
    ) -> None:
        self._using = _database_alias(using)
        self._clock = clock or DjangoR7MonitoringClock(using=self._using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity for read-only facades."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open a read transaction without activating write capability."""

        return self._read_atomic()

    @contextmanager
    def _read_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            yield

    def server_now(self) -> datetime:
        """Return one validated trusted server timestamp."""

        try:
            return _aware(self._clock.now(), "R7 monitoring server clock")
        except R7MonitoringPersistenceCorruption:
            raise
        except Exception as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring server clock is unavailable"
            ) from error

    def get_exact(
        self,
        *,
        reference: R7MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R7PersistedMonitoringAssessment | None:
        """Restore one exact complete graph ledger-known at ``as_of``."""

        cutoff = self._require_pit_cutoff(as_of)
        try:
            if type(reference) is not R7MonitoringAssessmentRef:
                raise TypeError("reference type differs")
            reference.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring assessment reference is malformed"
            ) from error
        rows = tuple(
            R7MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(
                Q(assessment_id=reference.assessment_id) | Q(content_hash=reference.content_hash),
                ledger_recorded_at__lte=cutoff,
            )
            .select_related("result", "lifecycle_head")
        )
        if not rows:
            return None
        restored = tuple(self._restore_bundle(row) for row in rows)
        matches = tuple(item for item in restored if item.reference == reference)
        if len(rows) != 1 or len(matches) != 1:
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring exact assessment is aliased or substituted"
            )
        return matches[0]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R7MonitoringAuditPage:
        """Materialize or replay one immutable signed PIT audit manifest."""

        if type(limit) is not int or not 1 <= limit <= 200:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring audit limit must be between 1 and 200"
            )
        cutoff = self._require_pit_cutoff(as_of)
        cursor_value = decode_r7_monitoring_audit_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                entries = self._materialize_audit_entries(as_of=cutoff)
                if len(entries) <= limit:
                    return R7MonitoringAuditPage(entries, None, cutoff)
                snapshot = create_r7_monitoring_audit_snapshot(
                    as_of=cutoff,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return R7MonitoringAuditPage(
                    snapshot.entries[:limit],
                    encode_r7_monitoring_audit_cursor(
                        snapshot=snapshot,
                        next_offset=limit,
                    ),
                    cutoff,
                )
            if cursor_value.snapshot_as_of != cutoff:
                raise R7MonitoringPersistenceUnavailable(
                    "R7 monitoring audit cursor cutoff differs"
                )
            snapshot = self._get_audit_snapshot(
                snapshot_id=cursor_value.snapshot_id,
                snapshot_version=cursor_value.snapshot_version,
                expected_hash=cursor_value.snapshot_hash,
            )
            offset = cursor_value.next_offset
            if offset >= len(snapshot.entries):
                raise R7MonitoringPersistenceUnavailable(
                    "R7 monitoring audit cursor offset is invalid"
                )
            end = min(offset + limit, len(snapshot.entries))
            next_cursor = (
                encode_r7_monitoring_audit_cursor(snapshot=snapshot, next_offset=end)
                if end < len(snapshot.entries)
                else None
            )
            return R7MonitoringAuditPage(snapshot.entries[offset:end], next_cursor, cutoff)

    def _materialize_audit_entries(
        self,
        *,
        as_of: datetime,
    ) -> tuple[R7MonitoringAuditEntry, ...]:
        rows = (
            R7MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .select_related("result", "lifecycle_head")
            .order_by("ledger_recorded_at", "assessment_id")
        )
        return tuple(self._audit_entry(self._restore_bundle(row)) for row in rows)

    @staticmethod
    def _audit_entry(bundle: R7PersistedMonitoringAssessment) -> R7MonitoringAuditEntry:
        evidence = bundle.evidence
        assessment = evidence.assessment
        return R7MonitoringAuditEntry(
            reference=bundle.reference,
            policy_id=evidence.policy.policy_id,
            policy_version=evidence.policy.policy_version,
            result_id=evidence.active.result_id,
            result_hash=evidence.active.result_hash,
            period_id=evidence.period.period_id,
            evaluated_at=assessment.evaluated_at,
            ledger_recorded_at=bundle.ledger_recorded_at,
            status=assessment.status,
            observation_count=len(evidence.realization_owner_record.members),
            blocker_codes=tuple(item.value for item in assessment.blocker_codes),
            manual_retirement_review_required=(assessment.manual_retirement_review_required),
        )

    def _append_audit_snapshot(self, snapshot: _R7MonitoringAuditSnapshot) -> None:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring audit persistence capability is unavailable"
        )

    def _get_audit_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_hash: str,
    ) -> _R7MonitoringAuditSnapshot:
        rows = tuple(
            R7MonitoringAuditSnapshotModel._default_manager.using(self._using).filter(
                Q(snapshot_id=snapshot_id, snapshot_version=snapshot_version)
                | Q(content_hash=expected_hash)
            )
        )
        if len(rows) != 1:
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring audit snapshot is missing or aliased"
            )
        row = rows[0]
        try:
            snapshot = decode_r7_monitoring_audit_snapshot(row.canonical_payload)
        except Exception as error:
            if isinstance(error, R7MonitoringPersistenceCorruption):
                raise
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring audit snapshot is malformed"
            ) from error
        expected_values = _snapshot_values(snapshot)
        _require_row_values(row, expected_values, "audit snapshot")
        if (
            snapshot.snapshot_id != snapshot_id
            or snapshot.snapshot_version != snapshot_version
            or snapshot.content_hash != expected_hash
        ):
            raise R7MonitoringPersistenceCorruption("R7 monitoring audit snapshot identity differs")
        return snapshot

    def _restore_bundle(
        self,
        row: R7MonitoringAssessmentLedgerModel,
    ) -> R7PersistedMonitoringAssessment:
        try:
            evidence = decode_r7_monitoring_evidence(row.canonical_payload)
        except (R7MonitoringCodecError, TypeError, ValueError) as error:
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring assessment payload is invalid"
            ) from error
        expected = _assessment_values(
            assessment_id=row.assessment_id,
            evidence=evidence,
            ledger_recorded_at=row.ledger_recorded_at,
            result_pk=row.result_id,
            lifecycle_head_pk=row.lifecycle_head_id,
        )
        _require_row_values(row, expected, "assessment")
        _require_result_fk(row.result, evidence)
        _require_lifecycle_head_fk(row.lifecycle_head, evidence)
        observations = tuple(
            R7MonitoringObservationLedgerModel._default_manager.using(self._using)
            .filter(assessment_id=row.pk)
            .select_related("result", "lifecycle_head")
            .order_by("observation_index")
        )
        members = evidence.realization_owner_record.members
        if len(observations) != len(members):
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring observation membership is incomplete"
            )
        for index, (observation, member) in enumerate(zip(observations, members, strict=True)):
            expected_observation = _observation_values(
                assessment_id=row.pk,
                assessment_stable_id=row.assessment_id,
                result_pk=row.result_id,
                lifecycle_head_pk=row.lifecycle_head_id,
                index=index,
                member=member,
                period_id=evidence.period.period_id,
                period_hash=evidence.period.content_hash,
                ledger_recorded_at=row.ledger_recorded_at,
            )
            _require_row_values(observation, expected_observation, "observation")
            _require_result_fk(observation.result, evidence)
            _require_lifecycle_head_fk(observation.lifecycle_head, evidence)
        reference = R7MonitoringAssessmentRef(
            assessment_id=row.assessment_id,
            assessment_version=row.assessment_version,
            content_hash=row.content_hash,
        )
        try:
            return R7PersistedMonitoringAssessment(
                reference=reference,
                evidence=evidence,
                ledger_recorded_at=row.ledger_recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring persisted bundle is invalid"
            ) from error

    def _require_pit_cutoff(self, as_of: datetime) -> datetime:
        try:
            cutoff = _aware(as_of, "R7 monitoring PIT as_of")
            if cutoff > self.server_now():
                raise R7MonitoringPersistenceUnavailable(
                    "R7 monitoring PIT cutoff is in the future"
                )
            return cutoff.astimezone(UTC)
        except R7MonitoringPersistenceUnavailable:
            raise
        except Exception as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring PIT cutoff is invalid"
            ) from error


class _DjangoR7MonitoringStore(DjangoR7MonitoringRepository):
    """Private claimed append store; never exported by production composition."""

    __slots__ = ("_token",)

    def __init__(self, *, using: str, clock: R7MonitoringClock, token: object) -> None:
        super().__init__(using=using, clock=clock)
        self._token = token

    def atomic(self) -> AbstractContextManager[None]:
        """Open one write transaction and activate the private claim token."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            with _activate_r7_monitoring_uow(self._token):
                yield

    def append_evidence(
        self,
        *,
        command: EvaluateR7PostPromotionMonitoringCommand,
        evidence: R7MonitoringEvaluationEvidence,
    ) -> R7MonitoringEvaluationEvidence:
        """Append one complete graph or replay the exact first winner."""

        _require_active_r7_monitoring_uow()
        try:
            command.__post_init__()
            copied = evidence.validated_copy()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring append evidence is malformed"
            ) from error
        if copied.assessment.evaluated_at != command.as_of:
            raise R7MonitoringPersistenceConflict(
                "R7 monitoring command and assessment cutoff differ"
            )
        assessment_id = derive_r7_monitoring_assessment_id(command)
        result_row, lifecycle_head = self._lock_owner_rows(copied, command.as_of)
        existing = self._assessment_winner(assessment_id, copied)
        if existing is not None:
            return existing.evidence
        ledger_recorded_at = self.server_now().astimezone(UTC)
        owner_valid_until = min(
            copied.policy.valid_until,
            copied.active.lifecycle_valid_until,
            copied.realization_owner_record.valid_until,
        )
        if not (copied.assessment.evaluated_at <= ledger_recorded_at < owner_valid_until):
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring ledger clock is outside owner validity"
            )
        try:
            with transaction.atomic(using=self._using):
                row = self._append_assessment(
                    assessment_id=assessment_id,
                    evidence=copied,
                    ledger_recorded_at=ledger_recorded_at,
                    result_row=result_row,
                    lifecycle_head=lifecycle_head,
                )
                for index, member in enumerate(copied.realization_owner_record.members):
                    self._append_observation(
                        assessment=row,
                        evidence=copied,
                        member=member,
                        index=index,
                        ledger_recorded_at=ledger_recorded_at,
                        result_row=result_row,
                        lifecycle_head=lifecycle_head,
                    )
        except IntegrityError as error:
            winner = self._assessment_winner(assessment_id, copied)
            if winner is None:
                raise R7MonitoringPersistenceConflict(
                    "R7 monitoring insert lost a conflicting race"
                ) from error
            return winner.evidence
        winner = self._assessment_winner(assessment_id, copied)
        if winner is None:
            raise R7MonitoringPersistenceCorruption(
                "R7 monitoring append winner cannot be replayed"
            )
        return winner.evidence

    def _lock_owner_rows(
        self,
        evidence: R7MonitoringEvaluationEvidence,
        as_of: datetime,
    ) -> tuple[R7ResearchResultModel, R7ResultLifecycleEventModel]:
        result_rows = tuple(
            R7ResearchResultModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                result_id=evidence.active.result_id,
                result_version=evidence.active.result_version,
                content_hash=evidence.active.result_hash,
                recorded_at__lte=as_of,
            )
        )
        if len(result_rows) != 1:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring authoritative result row is unavailable"
            )
        result_row = result_rows[0]
        event_rows = tuple(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(result_id=result_row.pk, recorded_at__lte=as_of)
            .order_by("sequence")
        )
        expected = tuple(
            (item.event_id, item.event_version, item.content_hash, item.sequence)
            for item in evidence.active_owner_graph.lifecycle_stream
        )
        actual = tuple(
            (item.event_id, item.event_version, item.content_hash, item.sequence)
            for item in event_rows
        )
        if actual != expected or not event_rows:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring lifecycle stream changed before append"
            )
        return result_row, event_rows[-1]

    def _assessment_winner(
        self,
        assessment_id: str,
        evidence: R7MonitoringEvaluationEvidence,
    ) -> R7PersistedMonitoringAssessment | None:
        content_hash = r7_monitoring_evidence_hash(evidence)
        rows = tuple(
            R7MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .select_for_update()
            .filter(Q(assessment_id=assessment_id) | Q(content_hash=content_hash))
            .select_related("result", "lifecycle_head")
        )
        if not rows:
            return None
        restored = tuple(self._restore_bundle(row) for row in rows)
        matches = tuple(
            item
            for item in restored
            if item.reference.assessment_id == assessment_id
            and item.reference.content_hash == content_hash
            and item.evidence == evidence
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R7MonitoringPersistenceConflict(
                "R7 monitoring immutable winner conflicts with evidence"
            )
        return matches[0]

    def _append_assessment(
        self,
        *,
        assessment_id: str,
        evidence: R7MonitoringEvaluationEvidence,
        ledger_recorded_at: datetime,
        result_row: R7ResearchResultModel,
        lifecycle_head: R7ResultLifecycleEventModel,
    ) -> R7MonitoringAssessmentLedgerModel:
        values = _assessment_values(
            assessment_id=assessment_id,
            evidence=evidence,
            ledger_recorded_at=ledger_recorded_at,
            result_pk=result_row.pk,
            lifecycle_head_pk=lifecycle_head.pk,
        )
        row = R7MonitoringAssessmentLedgerModel(**values)
        with _claim_r7_monitoring_insert(
            token=self._token,
            model_type=R7MonitoringAssessmentLedgerModel,
            expected_values=values,
        ):
            row.save(force_insert=True, using=self._using)
        return row

    def _append_observation(
        self,
        *,
        assessment: R7MonitoringAssessmentLedgerModel,
        evidence: R7MonitoringEvaluationEvidence,
        member: R7ForecastRealizationMember,
        index: int,
        ledger_recorded_at: datetime,
        result_row: R7ResearchResultModel,
        lifecycle_head: R7ResultLifecycleEventModel,
    ) -> None:
        values = _observation_values(
            assessment_id=assessment.pk,
            assessment_stable_id=assessment.assessment_id,
            result_pk=result_row.pk,
            lifecycle_head_pk=lifecycle_head.pk,
            index=index,
            member=member,
            period_id=evidence.period.period_id,
            period_hash=evidence.period.content_hash,
            ledger_recorded_at=ledger_recorded_at,
        )
        row = R7MonitoringObservationLedgerModel(**values)
        with _claim_r7_monitoring_insert(
            token=self._token,
            model_type=R7MonitoringObservationLedgerModel,
            expected_values=values,
        ):
            row.save(force_insert=True, using=self._using)

    def _append_audit_snapshot(self, snapshot: _R7MonitoringAuditSnapshot) -> None:
        _require_active_r7_monitoring_uow()
        values = _snapshot_values(snapshot)
        row = R7MonitoringAuditSnapshotModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_r7_monitoring_insert(
                    token=self._token,
                    model_type=R7MonitoringAuditSnapshotModel,
                    expected_values=values,
                ):
                    row.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            restored = self._get_audit_snapshot(
                snapshot_id=snapshot.snapshot_id,
                snapshot_version=snapshot.snapshot_version,
                expected_hash=snapshot.content_hash,
            )
            if restored != snapshot:
                raise R7MonitoringPersistenceConflict(
                    "R7 monitoring audit snapshot race conflicts"
                ) from error


def _build_r7_monitoring_writer(
    *,
    using: str,
    clock: R7MonitoringClock,
) -> _DjangoR7MonitoringStore:
    """Build a private writer for test/composition roots inside this package."""

    return _DjangoR7MonitoringStore(using=using, clock=clock, token=object())


def _assessment_values(
    *,
    assessment_id: str,
    evidence: R7MonitoringEvaluationEvidence,
    ledger_recorded_at: datetime,
    result_pk: object,
    lifecycle_head_pk: object,
) -> dict[str, object]:
    policy = evidence.policy
    active = evidence.active
    owner = evidence.realization_owner_record
    payload = encode_r7_monitoring_evidence(evidence)
    values: dict[str, object] = {
        "assessment_id": assessment_id,
        "assessment_version": evidence.assessment.assessment_version,
        "result_id": result_pk,
        "lifecycle_head_id": lifecycle_head_pk,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_hash": policy.content_hash,
        "result_stable_id": active.result_id,
        "result_version": active.result_version,
        "result_hash": active.result_hash,
        "lifecycle_attestation_id": active.lifecycle_attestation_id,
        "lifecycle_attestation_version": active.lifecycle_attestation_version,
        "lifecycle_attestation_hash": active.lifecycle_attestation_hash,
        "lifecycle_head_hash": active.lifecycle_head_hash,
        "calendar_id": evidence.calendar.calendar_id,
        "calendar_version": evidence.calendar.calendar_version,
        "calendar_hash": evidence.calendar.content_hash,
        "period_id": evidence.period.period_id,
        "period_version": evidence.period.period_version,
        "period_hash": evidence.period.content_hash,
        "realization_owner_id": owner.owner_record_id,
        "realization_owner_version": owner.owner_record_version,
        "realization_owner_hash": owner.content_hash,
        "evaluated_at": evidence.assessment.evaluated_at,
        "policy_recorded_at": policy.recorded_at,
        "result_recorded_at": evidence.active_owner_graph.result.recorded_at,
        "lifecycle_recorded_at": active.lifecycle_recorded_at,
        "calendar_recorded_at": evidence.calendar.recorded_at,
        "realization_recorded_at": owner.recorded_at,
        "owner_valid_until": min(
            policy.valid_until,
            active.lifecycle_valid_until,
            owner.valid_until,
        ),
        "ledger_recorded_at": ledger_recorded_at,
        "observation_count": len(owner.members),
        "canonical_payload": payload,
        "content_hash": r7_monitoring_evidence_hash(evidence),
        "status": evidence.assessment.status.value,
        "automatic_retirement": False,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash("assessment", values)
    return values


def _observation_values(
    *,
    assessment_id: object,
    assessment_stable_id: str,
    result_pk: object,
    lifecycle_head_pk: object,
    index: int,
    member: R7ForecastRealizationMember,
    period_id: str,
    period_hash: str,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "research.r7.monitoring-observation.v1",
        "member_version": member.member_version,
        "observation_id": member.observation_id,
        "observation_version": member.observation_version,
        "observation_hash": member.observation_hash,
        "prediction_hash": member.prediction_hash,
        "entry_id": member.entry_id,
        "forecast_group_id": member.forecast_group_id,
        "scenario_revision_id": str(member.scenario_revision_id),
        "published_at": member.published_at.isoformat(),
        "horizon_end": member.horizon_end.isoformat(),
        "realized": member.realized,
        "invalidated": member.invalidated,
        "available_at": member.available_at.isoformat(),
        "recorded_at": member.recorded_at.isoformat(),
        "evidence_ref": member.evidence_ref,
        "content_hash": member.content_hash,
    }
    scoped_hash = sha256(
        f"{assessment_stable_id}\x00{index}\x00{member.content_hash}".encode()
    ).hexdigest()
    values: dict[str, object] = {
        "assessment_id": assessment_id,
        "result_id": result_pk,
        "lifecycle_head_id": lifecycle_head_pk,
        "observation_index": index,
        "observation_id": member.observation_id,
        "observation_version": member.observation_version,
        "observation_hash": member.observation_hash,
        "prediction_hash": member.prediction_hash,
        "member_hash": member.content_hash,
        "period_id": period_id,
        "period_hash": period_hash,
        "published_at": member.published_at,
        "horizon_end": member.horizon_end,
        "available_at": member.available_at,
        "owner_recorded_at": member.recorded_at,
        "ledger_recorded_at": ledger_recorded_at,
        "canonical_payload": payload,
        "content_hash": scoped_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash("observation", values)
    return values


def _snapshot_values(snapshot: _R7MonitoringAuditSnapshot) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": encode_r7_monitoring_audit_snapshot(snapshot),
        "content_hash": snapshot.content_hash,
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash("audit-snapshot", values)
    return values


def _require_row_values(
    row: object,
    expected: dict[str, object],
    label: str,
) -> None:
    for field_name, value in expected.items():
        if getattr(row, field_name) != value:
            raise R7MonitoringPersistenceCorruption(
                f"R7 monitoring {label} header or payload differs"
            )


def _require_result_fk(
    row: R7ResearchResultModel,
    evidence: R7MonitoringEvaluationEvidence,
) -> None:
    result = evidence.active_owner_graph.result
    if (
        row.result_id,
        row.result_version,
        row.content_hash,
        row.recorded_at,
    ) != (result.result_id, result.result_version, result.content_hash, result.recorded_at):
        raise R7MonitoringPersistenceCorruption("R7 monitoring result foreign key was replaced")


def _require_lifecycle_head_fk(
    row: R7ResultLifecycleEventModel,
    evidence: R7MonitoringEvaluationEvidence,
) -> None:
    head = evidence.active_owner_graph.lifecycle_stream[-1]
    if (
        row.event_id,
        row.event_version,
        row.content_hash,
        row.result_content_hash,
        row.sequence,
    ) != (
        head.event_id,
        head.event_version,
        head.content_hash,
        head.result_ref.content_hash,
        head.sequence,
    ):
        raise R7MonitoringPersistenceCorruption(
            "R7 monitoring lifecycle-head foreign key was replaced"
        )


def _header_hash(kind: str, values: dict[str, object]) -> str:
    payload = {"kind": kind, **values}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode()
    ).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R7MonitoringPersistenceCorruption(f"{label} is invalid")
    return value


def _database_alias(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise ValueError("R7 monitoring database alias is invalid")
    return value


__all__ = ["DjangoR7MonitoringClock", "DjangoR7MonitoringRepository"]
