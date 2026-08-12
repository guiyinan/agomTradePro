"""Strict append-only persistence and exact PIT reads for R2 trial monitoring."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureTrialCommand,
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2MonitoringAssessmentRef,
    R2MonitoringAuditEntry,
    R2MonitoringAuditPage,
    R2PersistedMonitoringAssessment,
    R2PersistedTrialAssessment,
    R2TrialAssessmentRef,
    R2TrialMonitoringPersistenceConflict,
    R2TrialMonitoringPersistenceCorruption,
    R2TrialMonitoringPersistenceUnavailable,
    derive_r2_monitoring_assessment_id,
    derive_r2_trial_assessment_id,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MonitoringRawFact,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_codec import (
    R2TrialMonitoringCodecError,
    decode_r2_monitoring_evidence,
    decode_r2_monitoring_fact,
    decode_r2_trial_evidence,
    encode_r2_monitoring_evidence,
    encode_r2_monitoring_fact,
    encode_r2_trial_evidence,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_models import (
    R2ExplanatoryTrialAssessmentLedgerModel,
    R2MonitoringAssessmentLedgerModel,
    R2MonitoringAuditSnapshotModel,
    R2MonitoringObservationLedgerModel,
    _activate_r2_trial_monitoring_uow,
    _claim_r2_trial_monitoring_insert,
    _require_active_r2_trial_monitoring_uow,
)

_TRIAL_VERSION = "r2-explanatory-trial-ledger.v1"
_MONITORING_VERSION = "r2-monitoring-assessment-ledger.v1"
_AUDIT_SNAPSHOT_VERSION = "r2-monitoring-audit-snapshot.v1"
_AUDIT_CURSOR_VERSION = "r2-monitoring-audit-cursor.v1"


class R2PersistenceClock(Protocol):
    """Authoritative server clock boundary."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class DjangoR2TrialMonitoringClock:
    """Django timezone-backed authoritative clock."""

    def now(self) -> datetime:
        """Return the current server timestamp."""

        return timezone.now()


class DjangoR2TrialMonitoringRepository:
    """Public exact PIT repository without a write capability token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R2PersistenceClock | None = None,
    ) -> None:
        self._using = _exact_using(using)
        self._clock = clock or DjangoR2TrialMonitoringClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity."""

        return f"django:{self._using}"

    def get_trial_exact(
        self,
        *,
        reference: R2TrialAssessmentRef,
        as_of: datetime,
    ) -> R2PersistedTrialAssessment | None:
        """Restore one exact trial graph known at ``as_of``."""

        cutoff = self._require_pit_cutoff(as_of)
        try:
            if type(reference) is not R2TrialAssessmentRef:
                raise TypeError("trial reference type differs")
            reference.__post_init__()
            rows = tuple(
                R2ExplanatoryTrialAssessmentLedgerModel._default_manager.using(self._using).filter(
                    Q(
                        assessment_id=reference.assessment_id,
                        assessment_version=reference.assessment_version,
                        ledger_recorded_at__lte=cutoff,
                    )
                    | Q(
                        content_hash=reference.content_hash.lower(),
                        ledger_recorded_at__lte=cutoff,
                    )
                )
            )
            if not rows:
                return None
            restored = tuple(_restore_trial_row(row) for row in rows)
            exact = tuple(item for item in restored if item.reference == reference)
            if len(rows) != 1 or len(exact) != 1:
                raise R2TrialMonitoringPersistenceCorruption(
                    "R2 trial exact identity is aliased or substituted"
                )
            return exact[0]
        except (
            R2TrialMonitoringPersistenceCorruption,
            R2TrialMonitoringPersistenceUnavailable,
        ):
            raise
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 trial exact read is unavailable"
            ) from error

    def get_monitoring_exact(
        self,
        *,
        reference: R2MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R2PersistedMonitoringAssessment | None:
        """Restore one exact assessment-scoped monitoring graph."""

        cutoff = self._require_pit_cutoff(as_of)
        try:
            if type(reference) is not R2MonitoringAssessmentRef:
                raise TypeError("monitoring reference type differs")
            reference.__post_init__()
            rows = tuple(
                R2MonitoringAssessmentLedgerModel._default_manager.using(self._using)
                .filter(
                    Q(
                        assessment_id=reference.assessment_id,
                        assessment_version=reference.assessment_version,
                        ledger_recorded_at__lte=cutoff,
                    )
                    | Q(
                        content_hash=reference.content_hash.lower(),
                        ledger_recorded_at__lte=cutoff,
                    )
                )
                .select_related("trial_assessment")
            )
            if not rows:
                return None
            restored = tuple(self._restore_monitoring_row(row) for row in rows)
            exact = tuple(item for item in restored if item.reference == reference)
            if len(rows) != 1 or len(exact) != 1:
                raise R2TrialMonitoringPersistenceCorruption(
                    "R2 monitoring exact identity is aliased or substituted"
                )
            return exact[0]
        except (
            R2TrialMonitoringPersistenceCorruption,
            R2TrialMonitoringPersistenceUnavailable,
        ):
            raise
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 monitoring exact read is unavailable"
            ) from error

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R2MonitoringAuditPage:
        """Reject snapshot mutation from the public read-only repository."""

        del as_of, cursor, limit
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 monitoring audit snapshot writer is unavailable"
        )

    def _restore_monitoring_row(
        self,
        row: R2MonitoringAssessmentLedgerModel,
    ) -> R2PersistedMonitoringAssessment:
        trial = _restore_trial_row(row.trial_assessment)
        try:
            evidence = decode_r2_monitoring_evidence(row.canonical_payload)
            if evidence.trial != trial.evidence:
                raise R2TrialMonitoringPersistenceCorruption(
                    "R2 monitoring trial graph differs from its parent"
                )
            command = _command_for_trial(evidence.trial)
            expected = _monitoring_values(
                command=command,
                evidence=evidence,
                trial_row_id=_require_pk(row.trial_assessment_id),
                ledger_recorded_at=row.ledger_recorded_at,
            )
            _require_model_values(row, expected)
            observation_rows = tuple(
                R2MonitoringObservationLedgerModel._default_manager.using(self._using)
                .filter(monitoring_assessment_id=row.pk)
                .order_by("period_start", "fact_id", "fact_version", "pk")
            )
            if len(observation_rows) != len(evidence.facts):
                raise R2TrialMonitoringPersistenceCorruption(
                    "R2 monitoring observation set is incomplete"
                )
            for observation, fact in zip(
                observation_rows,
                _ordered_facts(evidence.facts),
                strict=True,
            ):
                restored_fact = decode_r2_monitoring_fact(observation.canonical_payload)
                if restored_fact != fact:
                    raise R2TrialMonitoringPersistenceCorruption(
                        "R2 monitoring observation payload was substituted"
                    )
                expected_observation = _observation_values(
                    monitoring_row_id=_require_pk(row.pk),
                    trial_row_id=_require_pk(row.trial_assessment_id),
                    fact=restored_fact,
                    ledger_recorded_at=row.ledger_recorded_at,
                )
                _require_model_values(observation, expected_observation)
            return R2PersistedMonitoringAssessment(
                reference=R2MonitoringAssessmentRef(
                    assessment_id=row.assessment_id,
                    assessment_version=row.assessment_version,
                    content_hash=row.content_hash,
                ),
                trial_reference=trial.reference,
                evidence=evidence,
                ledger_recorded_at=_aware_utc(
                    row.ledger_recorded_at,
                    "R2 monitoring ledger clock",
                ),
            )
        except R2TrialMonitoringPersistenceCorruption:
            raise
        except (R2TrialMonitoringCodecError, TypeError, ValueError) as error:
            raise R2TrialMonitoringPersistenceCorruption(
                "R2 monitoring persisted graph failed strict replay"
            ) from error

    def _require_pit_cutoff(self, as_of: datetime) -> datetime:
        cutoff = _aware_utc(as_of, "R2 PIT cutoff")
        try:
            server_now = _aware_utc(self._clock.now(), "R2 server clock")
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 authoritative server clock is unavailable"
            ) from error
        if cutoff > server_now:
            raise R2TrialMonitoringPersistenceUnavailable("R2 PIT cutoff is in the future")
        return cutoff


class _DjangoR2TrialMonitoringStore(DjangoR2TrialMonitoringRepository):
    """Private component writer; never retained by public production runtimes."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R2PersistenceClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Open the private claimed write transaction."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            with _activate_r2_trial_monitoring_uow(self._token):
                yield

    def append_trial(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2ExplanatoryTrialEvaluationEvidence,
    ) -> R2ExplanatoryTrialEvaluationEvidence:
        """Append or exactly replay one complete trial graph."""

        _require_active_r2_trial_monitoring_uow()
        canonical = _canonical_trial(evidence)
        _require_command_matches_trial(command, canonical)
        row = self._trial_collision(command=command, evidence=canonical)
        if row is not None:
            return _restore_trial_row(row).evidence
        ledger_recorded_at = self._server_ledger_clock()
        values = _trial_values(
            command=command,
            evidence=canonical,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with _claim_r2_trial_monitoring_insert(
                token=self._token,
                model_type=R2ExplanatoryTrialAssessmentLedgerModel,
                expected_values=values,
            ):
                row = R2ExplanatoryTrialAssessmentLedgerModel._default_manager.using(
                    self._using
                ).create(**values)
        except IntegrityError as error:
            raise R2TrialMonitoringPersistenceConflict(
                "R2 trial assessment identity is already sealed"
            ) from error
        return _restore_trial_row(row).evidence

    def append_monitoring(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2MonitoringEvaluationEvidence,
    ) -> R2MonitoringEvaluationEvidence:
        """Atomically append a trial, monitoring parent, and exact raw-fact set."""

        _require_active_r2_trial_monitoring_uow()
        canonical = _canonical_monitoring(evidence)
        _require_command_matches_trial(command, canonical.trial)
        collision = self._monitoring_collision(command=command, evidence=canonical)
        if collision is not None:
            return self._restore_monitoring_row(collision).evidence
        ledger_recorded_at = self._server_ledger_clock()
        trial_row = self._append_trial_row(
            command=command,
            evidence=canonical.trial,
            ledger_recorded_at=ledger_recorded_at,
        )
        values = _monitoring_values(
            command=command,
            evidence=canonical,
            trial_row_id=_require_pk(trial_row.pk),
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with _claim_r2_trial_monitoring_insert(
                token=self._token,
                model_type=R2MonitoringAssessmentLedgerModel,
                expected_values=values,
            ):
                row = R2MonitoringAssessmentLedgerModel._default_manager.using(self._using).create(
                    **values
                )
            for fact in _ordered_facts(canonical.facts):
                observation_values = _observation_values(
                    monitoring_row_id=_require_pk(row.pk),
                    trial_row_id=_require_pk(trial_row.pk),
                    fact=fact,
                    ledger_recorded_at=ledger_recorded_at,
                )
                with _claim_r2_trial_monitoring_insert(
                    token=self._token,
                    model_type=R2MonitoringObservationLedgerModel,
                    expected_values=observation_values,
                ):
                    R2MonitoringObservationLedgerModel._default_manager.using(self._using).create(
                        **observation_values
                    )
        except IntegrityError as error:
            raise R2TrialMonitoringPersistenceConflict(
                "R2 monitoring assessment identity is already sealed"
            ) from error
        return self._restore_monitoring_row(row).evidence

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R2MonitoringAuditPage:
        """Materialize or replay an immutable assessment manifest."""

        _require_active_r2_trial_monitoring_uow()
        cutoff = self._require_pit_cutoff(as_of)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise R2TrialMonitoringPersistenceUnavailable("R2 audit limit is invalid")
        if cursor is None:
            snapshot = self._create_audit_snapshot(cutoff)
            offset = 0
        else:
            snapshot_id, snapshot_version, content_hash, offset = _decode_cursor(cursor)
            snapshot = self._restore_audit_snapshot(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                content_hash=content_hash,
            )
            if snapshot[0] != cutoff:
                raise R2TrialMonitoringPersistenceUnavailable("R2 audit cursor cutoff differs")
        snapshot_as_of, entries, snapshot_ref = snapshot
        page = entries[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = (
            _encode_cursor(snapshot_ref=snapshot_ref, offset=next_offset)
            if next_offset < len(entries)
            else None
        )
        return R2MonitoringAuditPage(page, next_cursor, snapshot_as_of)

    def _append_trial_row(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2ExplanatoryTrialEvaluationEvidence,
        ledger_recorded_at: datetime,
    ) -> R2ExplanatoryTrialAssessmentLedgerModel:
        row = self._trial_collision(command=command, evidence=evidence)
        if row is not None:
            return row
        values = _trial_values(
            command=command,
            evidence=evidence,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r2_trial_monitoring_insert(
            token=self._token,
            model_type=R2ExplanatoryTrialAssessmentLedgerModel,
            expected_values=values,
        ):
            return R2ExplanatoryTrialAssessmentLedgerModel._default_manager.using(
                self._using
            ).create(**values)

    def _trial_collision(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2ExplanatoryTrialEvaluationEvidence,
    ) -> R2ExplanatoryTrialAssessmentLedgerModel | None:
        reference = _trial_reference(command, evidence)
        rows = tuple(
            R2ExplanatoryTrialAssessmentLedgerModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(
                    assessment_id=reference.assessment_id,
                    assessment_version=reference.assessment_version,
                )
                | Q(content_hash=reference.content_hash)
            )
        )
        if not rows:
            return None
        exact = tuple(
            row
            for row in rows
            if _restore_trial_row(row).reference == reference
            and _restore_trial_row(row).evidence == evidence
        )
        if len(rows) == 1 and len(exact) == 1:
            return exact[0]
        raise R2TrialMonitoringPersistenceConflict(
            "R2 trial assessment command identity is already sealed"
        )

    def _monitoring_collision(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2MonitoringEvaluationEvidence,
    ) -> R2MonitoringAssessmentLedgerModel | None:
        reference = _monitoring_reference(command, evidence)
        rows = tuple(
            R2MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(
                    assessment_id=reference.assessment_id,
                    assessment_version=reference.assessment_version,
                )
                | Q(content_hash=reference.content_hash)
            )
            .select_related("trial_assessment")
        )
        if not rows:
            return None
        restored = tuple(self._restore_monitoring_row(row) for row in rows)
        exact = tuple(
            row
            for row, item in zip(rows, restored, strict=True)
            if item.reference == reference and item.evidence == evidence
        )
        if len(rows) == 1 and len(exact) == 1:
            return exact[0]
        raise R2TrialMonitoringPersistenceConflict(
            "R2 monitoring assessment command identity is already sealed"
        )

    def _server_ledger_clock(self) -> datetime:
        try:
            return _aware_utc(self._clock.now(), "R2 ledger clock")
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 authoritative ledger clock is unavailable"
            ) from error

    def _create_audit_snapshot(
        self,
        as_of: datetime,
    ) -> tuple[
        datetime,
        tuple[R2MonitoringAuditEntry, ...],
        tuple[str, str, str],
    ]:
        rows = tuple(
            R2MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .select_related("trial_assessment")
            .order_by("ledger_recorded_at", "assessment_id", "pk")
        )
        entries = tuple(_audit_entry(self._restore_monitoring_row(row)) for row in rows)
        payload = _audit_payload(as_of=as_of, entries=entries)
        content_hash = _payload_hash(payload)
        snapshot_id = (
            "r2-monitoring-audit:"
            + sha256((as_of.isoformat() + "\x00" + content_hash).encode()).hexdigest()
        )
        created_at = self._server_ledger_clock()
        values = _audit_snapshot_values(
            snapshot_id=snapshot_id,
            as_of=as_of,
            created_at=created_at,
            payload=payload,
            content_hash=content_hash,
        )
        snapshot_rows = tuple(
            R2MonitoringAuditSnapshotModel._default_manager.using(self._using)
            .select_for_update()
            .filter(Q(snapshot_id=snapshot_id) | Q(content_hash=content_hash))
        )
        if snapshot_rows:
            if len(snapshot_rows) != 1:
                raise R2TrialMonitoringPersistenceCorruption(
                    "R2 audit snapshot identity is aliased"
                )
            return self._restore_audit_snapshot(
                snapshot_id=snapshot_id,
                snapshot_version=_AUDIT_SNAPSHOT_VERSION,
                content_hash=content_hash,
            )
        with _claim_r2_trial_monitoring_insert(
            token=self._token,
            model_type=R2MonitoringAuditSnapshotModel,
            expected_values=values,
        ):
            R2MonitoringAuditSnapshotModel._default_manager.using(self._using).create(**values)
        return as_of, entries, (snapshot_id, _AUDIT_SNAPSHOT_VERSION, content_hash)

    def _restore_audit_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        content_hash: str,
    ) -> tuple[
        datetime,
        tuple[R2MonitoringAuditEntry, ...],
        tuple[str, str, str],
    ]:
        rows = tuple(
            R2MonitoringAuditSnapshotModel._default_manager.using(self._using).filter(
                Q(snapshot_id=snapshot_id, snapshot_version=snapshot_version)
                | Q(content_hash=content_hash)
            )
        )
        if len(rows) != 1:
            raise R2TrialMonitoringPersistenceCorruption("R2 audit snapshot is missing or aliased")
        row = rows[0]
        as_of, entries = _decode_audit_payload(row.canonical_payload)
        expected = _audit_snapshot_values(
            snapshot_id=snapshot_id,
            as_of=as_of,
            created_at=row.created_at,
            payload=row.canonical_payload,
            content_hash=content_hash,
        )
        _require_model_values(row, expected)
        return as_of, entries, (snapshot_id, snapshot_version, content_hash)


def _build_r2_trial_monitoring_writer(
    *,
    using: str = "default",
    clock: R2PersistenceClock | None = None,
) -> _DjangoR2TrialMonitoringStore:
    """Build the private writer for component tests and trusted composition only."""

    return _DjangoR2TrialMonitoringStore(using=using, clock=clock)


def _canonical_trial(
    evidence: R2ExplanatoryTrialEvaluationEvidence,
) -> R2ExplanatoryTrialEvaluationEvidence:
    try:
        return decode_r2_trial_evidence(encode_r2_trial_evidence(evidence))
    except R2TrialMonitoringCodecError as error:
        raise R2TrialMonitoringPersistenceUnavailable("R2 trial evidence is malformed") from error


def _canonical_monitoring(
    evidence: R2MonitoringEvaluationEvidence,
) -> R2MonitoringEvaluationEvidence:
    try:
        return decode_r2_monitoring_evidence(encode_r2_monitoring_evidence(evidence))
    except R2TrialMonitoringCodecError as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 monitoring evidence is malformed"
        ) from error


def _trial_reference(
    command: EvaluateR2MarketStructureTrialCommand,
    evidence: R2ExplanatoryTrialEvaluationEvidence,
) -> R2TrialAssessmentRef:
    payload = encode_r2_trial_evidence(evidence)
    return R2TrialAssessmentRef(
        assessment_id=derive_r2_trial_assessment_id(command),
        assessment_version=_TRIAL_VERSION,
        content_hash=_payload_hash(payload),
    )


def _monitoring_reference(
    command: EvaluateR2MarketStructureTrialCommand,
    evidence: R2MonitoringEvaluationEvidence,
) -> R2MonitoringAssessmentRef:
    payload = encode_r2_monitoring_evidence(evidence)
    return R2MonitoringAssessmentRef(
        assessment_id=derive_r2_monitoring_assessment_id(command),
        assessment_version=_MONITORING_VERSION,
        content_hash=_payload_hash(payload),
    )


def _trial_values(
    *,
    command: EvaluateR2MarketStructureTrialCommand,
    evidence: R2ExplanatoryTrialEvaluationEvidence,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    _require_command_matches_trial(command, evidence)
    payload = encode_r2_trial_evidence(evidence)
    reference = _trial_reference(command, evidence)
    owner_valid_until = min(
        evidence.policy.active_until,
        evidence.taxonomy_publication.valid_until,
        evidence.calendar_publication.valid_until,
        *(item.valid_until for item in evidence.cycles),
        evidence.audit_outcome.valid_until,
    ).astimezone(UTC)
    ledger = _aware_utc(ledger_recorded_at, "R2 trial ledger clock")
    if not evidence.assessment.assessed_at <= ledger < owner_valid_until:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial evidence is not valid at the ledger clock"
        )
    cycles = evidence.cycles
    if len(cycles) != 2:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial must bind exactly two complete cycles"
        )
    base: dict[str, object] = {
        "assessment_id": reference.assessment_id,
        "assessment_version": reference.assessment_version,
        "policy_id": evidence.policy.policy_id,
        "policy_version": evidence.policy.policy_version,
        "policy_hash": evidence.policy.content_hash.lower(),
        "taxonomy_publication_id": evidence.taxonomy_publication.reference.publication_id,
        "taxonomy_publication_version": evidence.taxonomy_publication.reference.publication_version,
        "taxonomy_publication_hash": evidence.taxonomy_publication.content_hash.lower(),
        "calendar_publication_id": evidence.calendar_publication.reference.publication_id,
        "calendar_publication_version": evidence.calendar_publication.reference.publication_version,
        "calendar_publication_hash": evidence.calendar_publication.content_hash.lower(),
        "cycle_one_hash": cycles[0].content_hash.lower(),
        "cycle_two_hash": cycles[1].content_hash.lower(),
        "audit_outcome_id": evidence.audit_outcome.outcome_id,
        "audit_outcome_version": evidence.audit_outcome.outcome_version,
        "audit_outcome_hash": evidence.audit_outcome.content_hash.lower(),
        "status": evidence.assessment.status.value,
        "assessed_at": evidence.assessment.assessed_at.astimezone(UTC),
        "owner_valid_until": owner_valid_until,
        "ledger_recorded_at": ledger,
        "canonical_payload": payload,
        "content_hash": reference.content_hash,
        "research_only": True,
        "must_not_use_as_predictive_signal": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "is_attested_ready": False,
    }
    base["ledger_header_hash"] = _header_hash(base)
    return base


def _monitoring_values(
    *,
    command: EvaluateR2MarketStructureTrialCommand,
    evidence: R2MonitoringEvaluationEvidence,
    trial_row_id: int,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    _require_command_matches_trial(command, evidence.trial)
    payload = encode_r2_monitoring_evidence(evidence)
    reference = _monitoring_reference(command, evidence)
    ledger = _aware_utc(ledger_recorded_at, "R2 monitoring ledger clock")
    owner_valid_until = min(
        evidence.trial.policy.active_until,
        evidence.trial.taxonomy_publication.valid_until,
        evidence.trial.calendar_publication.valid_until,
        *(item.valid_until for item in evidence.trial.cycles),
        evidence.trial.audit_outcome.valid_until,
        *(item.valid_until for item in evidence.facts),
    ).astimezone(UTC)
    if not evidence.assessment.assessed_at <= ledger < owner_valid_until:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 monitoring evidence is not valid at the ledger clock"
        )
    if not evidence.facts:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 monitoring requires an exact non-empty fact set"
        )
    base: dict[str, object] = {
        "trial_assessment_id": trial_row_id,
        "assessment_id": reference.assessment_id,
        "assessment_version": reference.assessment_version,
        "policy_id": evidence.trial.policy.policy_id,
        "policy_version": evidence.trial.policy.policy_version,
        "policy_hash": evidence.trial.policy.content_hash.lower(),
        "status": evidence.assessment.status.value,
        "assessed_at": evidence.assessment.assessed_at.astimezone(UTC),
        "owner_valid_until": owner_valid_until,
        "ledger_recorded_at": ledger,
        "fact_count": len(evidence.facts),
        "fact_manifest_hash": _fact_manifest_hash(evidence.facts),
        "canonical_payload": payload,
        "content_hash": reference.content_hash,
        "retirement_review_required": evidence.assessment.retirement_review_required,
        "automatic_retirement": False,
        "research_only": True,
        "must_not_use_as_predictive_signal": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    base["ledger_header_hash"] = _header_hash(base)
    return base


def _observation_values(
    *,
    monitoring_row_id: int,
    trial_row_id: int,
    fact: R2MonitoringRawFact,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    payload = encode_r2_monitoring_fact(fact)
    canonical = decode_r2_monitoring_fact(payload)
    ledger = _aware_utc(ledger_recorded_at, "R2 observation ledger clock")
    if not canonical.recorded_at <= ledger < canonical.valid_until:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 monitoring fact is not valid at the ledger clock"
        )
    base: dict[str, object] = {
        "monitoring_assessment_id": monitoring_row_id,
        "trial_assessment_id": trial_row_id,
        "fact_id": canonical.fact_id,
        "fact_version": canonical.fact_version,
        "fact_content_hash": canonical.content_hash.lower(),
        "policy_id": canonical.policy_ref.evidence_id,
        "policy_version": canonical.policy_ref.evidence_version,
        "policy_hash": canonical.policy_ref.content_hash.lower(),
        "period_id": canonical.period_id,
        "period_start": canonical.period_start.astimezone(UTC),
        "period_end": canonical.period_end.astimezone(UTC),
        "source_owner": canonical.source_owner,
        "owner_observed_at": canonical.observed_at.astimezone(UTC),
        "owner_available_at": canonical.available_at.astimezone(UTC),
        "owner_recorded_at": canonical.recorded_at.astimezone(UTC),
        "owner_valid_until": canonical.valid_until.astimezone(UTC),
        "ledger_recorded_at": ledger,
        "canonical_payload": payload,
        "research_only": True,
        "must_not_use_as_predictive_signal": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    base["row_hash"] = _header_hash(base)
    return base


def _restore_trial_row(
    row: R2ExplanatoryTrialAssessmentLedgerModel,
) -> R2PersistedTrialAssessment:
    try:
        evidence = decode_r2_trial_evidence(row.canonical_payload)
        command = _command_for_trial(evidence)
        expected = _trial_values(
            command=command,
            evidence=evidence,
            ledger_recorded_at=row.ledger_recorded_at,
        )
        _require_model_values(row, expected)
        return R2PersistedTrialAssessment(
            reference=R2TrialAssessmentRef(
                assessment_id=row.assessment_id,
                assessment_version=row.assessment_version,
                content_hash=row.content_hash,
            ),
            evidence=evidence,
            ledger_recorded_at=_aware_utc(
                row.ledger_recorded_at,
                "R2 trial ledger clock",
            ),
        )
    except R2TrialMonitoringPersistenceCorruption:
        raise
    except (R2TrialMonitoringCodecError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceCorruption(
            "R2 trial persisted graph failed strict replay"
        ) from error


def _command_for_trial(
    evidence: R2ExplanatoryTrialEvaluationEvidence,
) -> EvaluateR2MarketStructureTrialCommand:
    return EvaluateR2MarketStructureTrialCommand(
        policy_id=evidence.policy.policy_id,
        policy_version=evidence.policy.policy_version,
        expected_policy_hash=evidence.policy.content_hash,
        as_of=evidence.assessment.assessed_at,
    )


def _require_command_matches_trial(
    command: EvaluateR2MarketStructureTrialCommand,
    evidence: R2ExplanatoryTrialEvaluationEvidence,
) -> None:
    try:
        if type(command) is not EvaluateR2MarketStructureTrialCommand:
            raise TypeError("command type differs")
        command.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 registration command is malformed"
        ) from error
    if (
        command.policy_id != evidence.policy.policy_id
        or command.policy_version != evidence.policy.policy_version
        or command.expected_policy_hash.lower() != evidence.policy.content_hash.lower()
        or command.as_of != evidence.assessment.assessed_at
    ):
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 registration command differs from owner evidence"
        )


def _ordered_facts(
    facts: tuple[R2MonitoringRawFact, ...],
) -> tuple[R2MonitoringRawFact, ...]:
    return tuple(
        sorted(
            facts,
            key=lambda item: (
                item.period_start,
                item.fact_id,
                item.fact_version,
                item.content_hash,
            ),
        )
    )


def _fact_manifest_hash(facts: tuple[R2MonitoringRawFact, ...]) -> str:
    return _payload_hash(
        {
            "facts": [
                {
                    "fact_id": item.fact_id,
                    "fact_version": item.fact_version,
                    "content_hash": item.content_hash.lower(),
                }
                for item in _ordered_facts(facts)
            ],
            "schema": "research-r2-monitoring-fact-manifest.v1",
        }
    )


def _audit_entry(
    persisted: R2PersistedMonitoringAssessment,
) -> R2MonitoringAuditEntry:
    evidence = persisted.evidence
    return R2MonitoringAuditEntry(
        reference=persisted.reference,
        trial_reference=persisted.trial_reference,
        policy_id=evidence.trial.policy.policy_id,
        policy_version=evidence.trial.policy.policy_version,
        assessed_at=evidence.assessment.assessed_at,
        ledger_recorded_at=persisted.ledger_recorded_at,
        status=evidence.assessment.status.value,
        fact_count=len(evidence.facts),
        retirement_review_required=evidence.assessment.retirement_review_required,
    )


def _audit_payload(
    *,
    as_of: datetime,
    entries: tuple[R2MonitoringAuditEntry, ...],
) -> dict[str, object]:
    return {
        "schema": "research-r2-monitoring-audit-manifest.v1",
        "as_of": as_of.astimezone(UTC).isoformat(),
        "entries": [
            {
                "assessment_id": item.reference.assessment_id,
                "assessment_version": item.reference.assessment_version,
                "content_hash": item.reference.content_hash.lower(),
                "trial_assessment_id": item.trial_reference.assessment_id,
                "trial_assessment_version": item.trial_reference.assessment_version,
                "trial_content_hash": item.trial_reference.content_hash.lower(),
                "policy_id": item.policy_id,
                "policy_version": item.policy_version,
                "assessed_at": item.assessed_at.astimezone(UTC).isoformat(),
                "ledger_recorded_at": item.ledger_recorded_at.astimezone(UTC).isoformat(),
                "status": item.status,
                "fact_count": item.fact_count,
                "retirement_review_required": item.retirement_review_required,
            }
            for item in entries
        ],
    }


def _decode_audit_payload(
    payload: object,
) -> tuple[datetime, tuple[R2MonitoringAuditEntry, ...]]:
    try:
        if type(payload) is not dict or set(payload) != {"schema", "as_of", "entries"}:
            raise TypeError("audit payload keys differ")
        raw = cast(dict[str, object], payload)
        if raw["schema"] != "research-r2-monitoring-audit-manifest.v1":
            raise ValueError("audit schema differs")
        as_of = _parse_datetime(raw["as_of"], "R2 audit as_of")
        raw_entries = raw["entries"]
        if type(raw_entries) is not list:
            raise TypeError("audit entries differ")
        entries = tuple(_decode_audit_entry(item) for item in raw_entries)
        if _audit_payload(as_of=as_of, entries=entries) != payload:
            raise ValueError("audit payload is not canonical")
        return as_of, entries
    except (KeyError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceCorruption(
            "R2 audit snapshot payload is malformed"
        ) from error


def _decode_audit_entry(payload: object) -> R2MonitoringAuditEntry:
    keys = {
        "assessment_id",
        "assessment_version",
        "content_hash",
        "trial_assessment_id",
        "trial_assessment_version",
        "trial_content_hash",
        "policy_id",
        "policy_version",
        "assessed_at",
        "ledger_recorded_at",
        "status",
        "fact_count",
        "retirement_review_required",
    }
    if type(payload) is not dict or set(payload) != keys:
        raise TypeError("audit entry keys differ")
    raw = cast(dict[str, object], payload)
    fact_count = raw["fact_count"]
    review = raw["retirement_review_required"]
    if type(fact_count) is not int or fact_count <= 0 or type(review) is not bool:
        raise ValueError("audit entry scalars differ")
    return R2MonitoringAuditEntry(
        reference=R2MonitoringAssessmentRef(
            assessment_id=_text(raw["assessment_id"]),
            assessment_version=_text(raw["assessment_version"]),
            content_hash=_text(raw["content_hash"]),
        ),
        trial_reference=R2TrialAssessmentRef(
            assessment_id=_text(raw["trial_assessment_id"]),
            assessment_version=_text(raw["trial_assessment_version"]),
            content_hash=_text(raw["trial_content_hash"]),
        ),
        policy_id=_text(raw["policy_id"]),
        policy_version=_text(raw["policy_version"]),
        assessed_at=_parse_datetime(raw["assessed_at"], "R2 audit assessed_at"),
        ledger_recorded_at=_parse_datetime(
            raw["ledger_recorded_at"],
            "R2 audit ledger_recorded_at",
        ),
        status=_text(raw["status"]),
        fact_count=fact_count,
        retirement_review_required=review,
    )


def _audit_snapshot_values(
    *,
    snapshot_id: str,
    as_of: datetime,
    created_at: datetime,
    payload: object,
    content_hash: str,
) -> dict[str, object]:
    decoded_as_of, entries = _decode_audit_payload(payload)
    if decoded_as_of != as_of or _payload_hash(payload) != content_hash:
        raise R2TrialMonitoringPersistenceCorruption("R2 audit snapshot seal differs")
    created = _aware_utc(created_at, "R2 audit created_at")
    if as_of > created:
        raise R2TrialMonitoringPersistenceUnavailable("R2 audit cutoff is after its creation clock")
    base: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "snapshot_version": _AUDIT_SNAPSHOT_VERSION,
        "as_of": as_of,
        "created_at": created,
        "entry_count": len(entries),
        "canonical_payload": payload,
        "content_hash": content_hash,
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    base["ledger_header_hash"] = _header_hash(base)
    return base


def _encode_cursor(
    *,
    snapshot_ref: tuple[str, str, str],
    offset: int,
) -> str:
    payload = {
        "schema": _AUDIT_CURSOR_VERSION,
        "snapshot_id": snapshot_ref[0],
        "snapshot_version": snapshot_ref[1],
        "content_hash": snapshot_ref[2],
        "offset": offset,
    }
    return base64.urlsafe_b64encode(_canonical_bytes(payload)).decode().rstrip("=")


def _decode_cursor(cursor: object) -> tuple[str, str, str, int]:
    try:
        if type(cursor) is not str or not cursor or len(cursor) > 4096:
            raise TypeError("cursor differs")
        padding = "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if type(decoded) is not dict or set(decoded) != {
            "schema",
            "snapshot_id",
            "snapshot_version",
            "content_hash",
            "offset",
        }:
            raise TypeError("cursor keys differ")
        raw = cast(dict[str, object], decoded)
        if raw["schema"] != _AUDIT_CURSOR_VERSION:
            raise ValueError("cursor schema differs")
        offset = raw["offset"]
        if type(offset) is not int or offset < 0:
            raise ValueError("cursor offset differs")
        snapshot_id = _text(raw["snapshot_id"])
        snapshot_version = _text(raw["snapshot_version"])
        content_hash = _text(raw["content_hash"])
        R2TrialAssessmentRef(snapshot_id, snapshot_version, content_hash)
        return snapshot_id, snapshot_version, content_hash.lower(), offset
    except Exception as error:
        raise R2TrialMonitoringPersistenceUnavailable("R2 audit cursor is malformed") from error


def _require_model_values(model: object, expected: dict[str, object]) -> None:
    for key, expected_value in expected.items():
        actual = getattr(model, key)
        if isinstance(expected_value, datetime):
            actual = _aware_utc(actual, f"R2 persisted {key}")
        if actual != expected_value:
            raise R2TrialMonitoringPersistenceCorruption(
                f"R2 persisted {key} differs from its sealed payload"
            )


def _header_hash(values: dict[str, object]) -> str:
    return _payload_hash(
        {
            key: _header_value(value)
            for key, value in sorted(values.items())
            if key not in {"canonical_payload", "ledger_header_hash"}
        }
        | {"canonical_payload_hash": _payload_hash(values["canonical_payload"])}
    )


def _header_value(value: object) -> object:
    if isinstance(value, datetime):
        return _aware_utc(value, "R2 header datetime").isoformat()
    return value


def _payload_hash(payload: object) -> str:
    return sha256(_canonical_bytes(payload)).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _aware_utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _parse_datetime(value: object, label: str) -> datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    return _aware_utc(datetime.fromisoformat(value), label)


def _text(value: object) -> str:
    if type(value) is not str:
        raise TypeError("R2 persisted text differs")
    return value


def _exact_using(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise ValueError("R2 database alias is invalid")
    return value


def _require_pk(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise R2TrialMonitoringPersistenceCorruption("R2 persisted primary key is invalid")
    return value


__all__ = [
    "DjangoR2TrialMonitoringClock",
    "DjangoR2TrialMonitoringRepository",
]
