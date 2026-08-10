"""Strict append-only persistence and exact PIT reads for R5 monitoring."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoringCommand,
    R5MonitoringClock,
    R5MonitoringEvaluationEvidence,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringAssessmentRef,
    R5MonitoringAuditEntry,
    R5MonitoringAuditPage,
    R5MonitoringPersistedAssessment,
    R5MonitoringPersistenceConflict,
    R5MonitoringPersistenceCorruption,
    R5MonitoringPersistenceUnavailable,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5PostPromotionMonitoringAssessment,
    evaluate_r5_post_promotion_monitoring,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringPolicy,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleEventType,
)
from apps.research.infrastructure.r5_relative_value_monitoring_audit_codec import (
    _R5MonitoringAuditCursor,
    _R5MonitoringAuditSnapshot,
    create_r5_monitoring_audit_snapshot,
    decode_r5_monitoring_audit_cursor,
    encode_r5_monitoring_audit_cursor,
)
from apps.research.infrastructure.r5_relative_value_monitoring_codec import (
    R5MonitoringCodecError,
    decode_r5_monitoring_active_lifecycle,
    decode_r5_monitoring_assessment,
    decode_r5_monitoring_fact,
    decode_r5_monitoring_fixed_income,
    decode_r5_monitoring_period_calendar,
    decode_r5_monitoring_policy,
    encode_r5_monitoring_active_lifecycle,
    encode_r5_monitoring_assessment,
    encode_r5_monitoring_fact,
    encode_r5_monitoring_fixed_income,
    encode_r5_monitoring_period_calendar,
    encode_r5_monitoring_policy,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAssessmentLedgerModel,
    R5MonitoringAuditSnapshotModel,
    R5MonitoringObservationLedgerModel,
    _activate_r5_monitoring_uow,
    _claim_r5_monitoring_insert,
    _require_active_r5_monitoring_uow,
)
from apps.research.infrastructure.r5_relative_value_monitoring_persistence_codec import (
    _assessment_values,
    _aware_utc,
    _observation_row_matches_domain_values,
    _observation_values,
    _require_model_values,
    _restore_snapshot,
    _snapshot_values,
    _winner_matches_domain_evidence,
)
from apps.research.infrastructure.r5_relative_value_promotion_models import (
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleEventModel,
)
from apps.research.infrastructure.r5_relative_value_promotion_repository import (
    DjangoR5PromotionRepository,
    R5PromotionRepositoryCorruption,
)


class DjangoR5MonitoringClock:
    """Django timezone-backed authoritative server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoR5MonitoringRepository:
    """Public exact PIT repository without a write capability token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R5MonitoringClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR5MonitoringClock()

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
        """Return one validated authoritative server timestamp."""

        try:
            return _aware_utc(self._clock.now(), "R5 monitoring server clock")
        except R5MonitoringPersistenceCorruption:
            raise
        except Exception as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring server clock is unavailable"
            ) from error

    def get_exact(
        self,
        *,
        assessment_ref: R5MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R5MonitoringPersistedAssessment | None:
        """Restore one exact complete graph ledger-known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        try:
            if type(assessment_ref) is not R5MonitoringAssessmentRef:
                raise TypeError("assessment ref type differs")
            R5MonitoringAssessmentRef.__post_init__(assessment_ref)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring assessment reference is malformed"
            ) from error
        rows = tuple(
            R5MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(
                Q(
                    assessment_id=assessment_ref.assessment_id,
                    ledger_recorded_at__lte=as_of,
                )
                | Q(
                    content_hash=assessment_ref.assessment_hash,
                    ledger_recorded_at__lte=as_of,
                )
            )
            .select_related(
                "active_decision",
                "lifecycle_event",
                "active_decision__authorization",
                "active_decision__policy",
                "active_decision__trial",
                "lifecycle_event__authorization",
                "lifecycle_event__decision",
            )
        )
        if not rows:
            return None
        restored = tuple(self._restore_bundle(row) for row in rows)
        matches = tuple(item for item in restored if item.assessment_ref == assessment_ref)
        if len(rows) != 1 or len(matches) != 1:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring exact assessment is aliased or substituted"
            )
        return matches[0]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R5MonitoringAuditPage:
        """Materialize or replay one immutable signed PIT audit manifest."""

        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("R5 monitoring audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = decode_r5_monitoring_audit_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                entries = self._materialize_audit_entries(as_of=as_of)
                if len(entries) <= limit:
                    return R5MonitoringAuditPage(entries, None, as_of.astimezone(UTC))
                snapshot = create_r5_monitoring_audit_snapshot(
                    as_of=as_of,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return R5MonitoringAuditPage(
                    snapshot.entries[:limit],
                    encode_r5_monitoring_audit_cursor(
                        snapshot=snapshot,
                        next_offset=limit,
                    ),
                    snapshot.as_of,
                )
            if cursor_value.snapshot_as_of != as_of.astimezone(UTC):
                raise R5MonitoringPersistenceUnavailable(
                    "R5 monitoring audit cursor belongs to another cutoff"
                )
            snapshot = self._get_audit_snapshot(cursor_value)
            start = cursor_value.next_offset
            if snapshot.as_of != as_of.astimezone(UTC) or start >= len(snapshot.entries):
                raise R5MonitoringPersistenceCorruption(
                    "R5 monitoring audit cursor differs from its snapshot"
                )
            entries = snapshot.entries[start : start + limit]
            self._validate_snapshot_entries(snapshot=snapshot, entries=entries)
            next_offset = start + len(entries)
            next_cursor = None
            if next_offset < len(snapshot.entries):
                next_cursor = encode_r5_monitoring_audit_cursor(
                    snapshot=snapshot,
                    next_offset=next_offset,
                )
            return R5MonitoringAuditPage(entries, next_cursor, snapshot.as_of)

    def _materialize_audit_entries(
        self,
        *,
        as_of: datetime,
    ) -> tuple[R5MonitoringAuditEntry, ...]:
        rows = tuple(
            R5MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .select_related(
                "active_decision",
                "lifecycle_event",
                "active_decision__authorization",
                "active_decision__policy",
                "active_decision__trial",
                "lifecycle_event__authorization",
            )
            .order_by("ledger_recorded_at", "assessment_id")
        )
        return tuple(self._audit_entry(self._restore_bundle(row)) for row in rows)

    @staticmethod
    def _audit_entry(bundle: R5MonitoringPersistedAssessment) -> R5MonitoringAuditEntry:
        assessment = bundle.assessment
        return R5MonitoringAuditEntry(
            assessment_ref=bundle.assessment_ref,
            result_id=assessment.result_id,
            result_hash=assessment.result_hash,
            policy_id=assessment.policy_id,
            policy_version=bundle.policy.policy_version,
            evaluated_at=assessment.evaluated_at,
            ledger_recorded_at=bundle.ledger_recorded_at,
            status=assessment.status,
            fact_count=len(bundle.portfolio_facts),
            blocker_codes=tuple(item.value for item in assessment.blocker_codes),
            retirement_review_required=assessment.manual_retirement_review_required,
        )

    def _append_audit_snapshot(self, snapshot: _R5MonitoringAuditSnapshot) -> None:
        raise R5MonitoringPersistenceUnavailable(
            "R5 monitoring audit snapshot writer is unavailable on read repository"
        )

    def _get_audit_snapshot(
        self,
        cursor: _R5MonitoringAuditCursor,
    ) -> _R5MonitoringAuditSnapshot:
        rows = tuple(
            R5MonitoringAuditSnapshotModel._default_manager.using(self._using).filter(
                Q(
                    snapshot_id=cursor.snapshot_id,
                    snapshot_version=cursor.snapshot_version,
                )
                | Q(content_hash=cursor.snapshot_hash)
            )
        )
        matches = tuple(
            row
            for row in rows
            if (row.snapshot_id, row.snapshot_version, row.content_hash)
            == (cursor.snapshot_id, cursor.snapshot_version, cursor.snapshot_hash)
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring audit snapshot is unavailable or substituted"
            )
        return _restore_snapshot(matches[0])

    def _validate_snapshot_entries(
        self,
        *,
        snapshot: _R5MonitoringAuditSnapshot,
        entries: tuple[R5MonitoringAuditEntry, ...],
    ) -> None:
        for entry in entries:
            bundle = self.get_exact(
                assessment_ref=entry.assessment_ref,
                as_of=snapshot.as_of,
            )
            if bundle is None or self._audit_entry(bundle) != entry:
                raise R5MonitoringPersistenceCorruption(
                    "R5 monitoring audit snapshot entry differs from its ledger"
                )

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        try:
            cutoff = _aware_utc(as_of, "R5 monitoring as_of")
        except R5MonitoringPersistenceCorruption as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring as_of must be timezone-aware"
            ) from error
        if cutoff > self.server_now():
            raise R5MonitoringPersistenceUnavailable("future R5 monitoring as_of is not permitted")

    def _restore_bundle(
        self,
        model: R5MonitoringAssessmentLedgerModel,
    ) -> R5MonitoringPersistedAssessment:
        try:
            active = decode_r5_monitoring_active_lifecycle(model.active_lifecycle_payload)
            fixed_income = decode_r5_monitoring_fixed_income(model.fixed_income_payload)
            policy = decode_r5_monitoring_policy(model.policy_payload)
            calendar = decode_r5_monitoring_period_calendar(model.calendar_payload)
            assessment = decode_r5_monitoring_assessment(model.assessment_payload)
        except R5MonitoringCodecError as error:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring assessment owner graph payload is invalid"
            ) from error
        self._validate_owner_rows(model=model, active=active)
        facts = self._facts_for_assessment(model=model, assessment=assessment)
        values = _assessment_values(
            decision_row_id=model.active_decision_id,
            lifecycle_event_row_id=model.lifecycle_event_id,
            active=active,
            fixed_income=fixed_income,
            policy=policy,
            calendar=calendar,
            facts=facts,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_model_values(model=model, values=values, label="assessment")
        replayed = evaluate_r5_post_promotion_monitoring(
            requested_policy_id=model.requested_policy_id,
            requested_policy_version=model.requested_policy_version,
            expected_policy_hash=model.expected_policy_hash,
            active_lifecycle=active,
            fixed_income=fixed_income,
            policy=policy,
            calendar=calendar,
            portfolio_facts=facts,
            evaluated_at=model.evaluated_at,
        )
        if replayed != assessment:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring assessment does not replay from owner facts"
            )
        return R5MonitoringPersistedAssessment(
            assessment_ref=R5MonitoringAssessmentRef(
                assessment.assessment_id,
                assessment.content_hash,
            ),
            active_lifecycle=active,
            fixed_income=fixed_income,
            policy=policy,
            calendar=calendar,
            portfolio_facts=facts,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )

    def _facts_for_assessment(
        self,
        *,
        model: R5MonitoringAssessmentLedgerModel,
        assessment: R5PostPromotionMonitoringAssessment,
    ) -> tuple[R5PostPromotionMonitoringFact, ...]:
        rows = tuple(
            R5MonitoringObservationLedgerModel._default_manager.using(self._using)
            .filter(
                assessment_id=model.pk,
                ledger_recorded_at__lte=model.ledger_recorded_at,
            )
            .select_related("active_decision", "lifecycle_event", "assessment")
        )
        restored: dict[str, R5PostPromotionMonitoringFact] = {}
        for row in rows:
            fact = self._restore_fact(row)
            if fact.content_hash in restored:
                raise R5MonitoringPersistenceCorruption("duplicate R5 monitoring fact content seal")
            restored[fact.content_hash] = fact
        if set(restored) != set(assessment.fact_hashes):
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring assessment fact graph is incomplete"
            )
        return tuple(restored[item] for item in assessment.fact_hashes)

    def _restore_fact(
        self,
        model: R5MonitoringObservationLedgerModel,
    ) -> R5PostPromotionMonitoringFact:
        try:
            fact = decode_r5_monitoring_fact(model.canonical_payload)
        except R5MonitoringCodecError as error:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring observation payload is invalid"
            ) from error
        values = _observation_values(
            assessment_row_id=model.assessment_id,
            assessment_stable_id=model.assessment.assessment_id,
            decision_row_id=model.active_decision_id,
            lifecycle_event_row_id=model.lifecycle_event_id,
            fact=fact,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_model_values(model=model, values=values, label="observation")
        if (
            model.active_decision_id != model.assessment.active_decision_id
            or model.lifecycle_event_id != model.assessment.lifecycle_event_id
        ):
            raise R5MonitoringPersistenceCorruption("R5 monitoring observation FK graph differs")
        return fact

    def _validate_owner_rows(
        self,
        *,
        model: R5MonitoringAssessmentLedgerModel,
        active: R5MonitoringActiveLifecycle,
    ) -> None:
        try:
            owner_repository = DjangoR5PromotionRepository(using=self._using)
            decision_bundle = owner_repository._decision_bundle_from_model(  # noqa: SLF001
                model.active_decision
            )
            event_bundle = owner_repository._lifecycle_event_bundle_from_model(  # noqa: SLF001
                model.lifecycle_event
            )
        except (AttributeError, R5PromotionRepositoryCorruption, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring authoritative lifecycle row is invalid"
            ) from error
        decision = decision_bundle.decision
        event = event_bundle.event
        owner_seals = tuple(
            sorted({item.fixed_income_record.content_hash for item in decision.trial.observations})
        )
        if (
            (decision.decision_id, decision.decision_version, decision.content_hash)
            != (active.decision_id, active.decision_version, active.decision_hash)
            or (decision.scope.scope_id, decision.scope.content_hash)
            != (active.scope_id, active.scope_hash)
            or (decision.trial.trial_id, decision.trial.content_hash)
            != (active.trial_id, active.trial_hash)
            or owner_seals != active.fixed_income_owner_seal_hashes
            or event.decision.content_hash != active.decision_hash
            or event.stream_id != active.stream_id
            or (event.event_id, event.content_hash)
            != (active.latest_event_id, active.latest_event_hash)
            or event.event_type
            not in {
                R5RelativeValueLifecycleEventType.PROMOTED,
                R5RelativeValueLifecycleEventType.ROLLED_BACK,
            }
            or event.occurred_at != active.promoted_at
            or event.recorded_at != active.recorded_at
            or model.active_decision_id != model.lifecycle_event.decision_id
        ):
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring authoritative lifecycle projection differs"
            )


class _DjangoR5MonitoringStore(DjangoR5MonitoringRepository):
    """Private append and audit-snapshot capability for internal composition."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R5MonitoringClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Open the private R5 monitoring write capability scope."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r5_monitoring_uow(self._token):
            yield

    def append_evidence(
        self,
        *,
        command: EvaluateR5PostPromotionMonitoringCommand,
        evidence: R5MonitoringEvaluationEvidence,
    ) -> R5MonitoringPersistedAssessment:
        """Canonicalize, replay, and append one complete exact owner graph."""

        _require_active_r5_monitoring_uow()
        try:
            if (
                evidence.active_lifecycle is None
                or evidence.fixed_income is None
                or evidence.policy is None
                or evidence.calendar is None
                or not evidence.portfolio_facts
            ):
                raise ValueError("complete owner graph is required")
            active = decode_r5_monitoring_active_lifecycle(
                encode_r5_monitoring_active_lifecycle(evidence.active_lifecycle)
            )
            fixed_income = decode_r5_monitoring_fixed_income(
                encode_r5_monitoring_fixed_income(evidence.fixed_income)
            )
            policy = decode_r5_monitoring_policy(encode_r5_monitoring_policy(evidence.policy))
            calendar = decode_r5_monitoring_period_calendar(
                encode_r5_monitoring_period_calendar(evidence.calendar)
            )
            facts = tuple(
                decode_r5_monitoring_fact(encode_r5_monitoring_fact(item))
                for item in evidence.portfolio_facts
            )
            assessment = decode_r5_monitoring_assessment(
                encode_r5_monitoring_assessment(evidence.assessment)
            )
        except (AttributeError, R5MonitoringCodecError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring append owner graph is malformed"
            ) from error
        if (
            assessment.evaluated_at != command.as_of
            or policy.policy_id != command.policy_id
            or policy.policy_version != command.policy_version
            or policy.content_hash != command.expected_policy_hash
            or active != policy.target.active_lifecycle
            or fixed_income != policy.target.fixed_income
        ):
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring append command differs from assessment"
            )
        replayed = evaluate_r5_post_promotion_monitoring(
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_lifecycle=active,
            fixed_income=fixed_income,
            policy=policy,
            calendar=calendar,
            portfolio_facts=facts,
            evaluated_at=command.as_of,
        )
        if replayed != assessment:
            raise R5MonitoringPersistenceCorruption(
                "R5 monitoring append differs from authoritative replay"
            )
        winner = self._assessment_winner(assessment)
        if winner is not None:
            if _winner_matches_domain_evidence(
                winner=winner,
                active=active,
                fixed_income=fixed_income,
                policy=policy,
                calendar=calendar,
                facts=facts,
                assessment=assessment,
            ):
                return winner
            raise R5MonitoringPersistenceConflict(
                "R5 monitoring exact winner differs from owner evidence"
            )
        ledger_recorded_at = self.server_now()
        if command.as_of > ledger_recorded_at:
            raise R5MonitoringPersistenceUnavailable(
                "future R5 monitoring assessment cannot be persisted"
            )
        decision_row, lifecycle_row = self._lock_owner_rows(
            active=active,
            as_of=command.as_of,
        )
        try:
            with transaction.atomic(using=self._using):
                assessment_row = self._append_assessment(
                    decision_row=decision_row,
                    lifecycle_row=lifecycle_row,
                    active=active,
                    fixed_income=fixed_income,
                    policy=policy,
                    calendar=calendar,
                    facts=facts,
                    assessment=assessment,
                    ledger_recorded_at=ledger_recorded_at,
                )
                for fact in facts:
                    self._append_fact(
                        assessment_row=assessment_row,
                        decision_row=decision_row,
                        lifecycle_row=lifecycle_row,
                        fact=fact,
                        ledger_recorded_at=ledger_recorded_at,
                    )
                return self._restore_bundle(assessment_row)
        except IntegrityError as error:
            winner = self._assessment_winner(assessment)
            if winner is not None and _winner_matches_domain_evidence(
                winner=winner,
                active=active,
                fixed_income=fixed_income,
                policy=policy,
                calendar=calendar,
                facts=facts,
                assessment=assessment,
            ):
                return winner
            raise R5MonitoringPersistenceConflict(
                "R5 monitoring append lost an immutable identity race"
            ) from error

    def _lock_owner_rows(
        self,
        *,
        active: R5MonitoringActiveLifecycle,
        as_of: datetime,
    ) -> tuple[R5PromotionDecisionBundleModel, R5PromotionLifecycleEventModel]:
        decisions = tuple(
            R5PromotionDecisionBundleModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(
                    decision_id=active.decision_id,
                    decision_version=active.decision_version,
                    ledger_recorded_at__lte=as_of,
                )
                | Q(decision_content_hash=active.decision_hash, ledger_recorded_at__lte=as_of)
            )
            .select_related("authorization", "policy", "trial")
        )
        events = tuple(
            R5PromotionLifecycleEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(event_id=active.latest_event_id, ledger_recorded_at__lte=as_of)
                | Q(event_content_hash=active.latest_event_hash, ledger_recorded_at__lte=as_of)
            )
            .select_related(
                "authorization",
                "decision__authorization",
                "decision__policy",
                "decision__trial",
                "rollback_target",
                "previous_event",
            )
        )
        if len(decisions) != 1 or len(events) != 1:
            raise R5MonitoringPersistenceUnavailable(
                "exact persisted R5 active lifecycle is unavailable"
            )
        probe = R5MonitoringAssessmentLedgerModel(
            assessment_id="owner-validation-probe",
            active_decision=decisions[0],
            lifecycle_event=events[0],
        )
        self._validate_owner_rows(model=probe, active=active)
        return decisions[0], events[0]

    def _append_assessment(
        self,
        *,
        decision_row: R5PromotionDecisionBundleModel,
        lifecycle_row: R5PromotionLifecycleEventModel,
        active: R5MonitoringActiveLifecycle,
        fixed_income: R5MonitoringFixedIncomeEvidence,
        policy: R5MonitoringPolicy,
        calendar: R5MonitoringCalendar,
        facts: tuple[R5PostPromotionMonitoringFact, ...],
        assessment: R5PostPromotionMonitoringAssessment,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringAssessmentLedgerModel:
        rows = self._assessment_collisions(assessment)
        if rows:
            exact = tuple(
                row
                for row in rows
                if row.assessment_id == assessment.assessment_id
                and row.content_hash == assessment.content_hash
            )
            if len(exact) == 1:
                return exact[0]
            raise R5MonitoringPersistenceConflict(
                "R5 monitoring assessment command identity is already sealed"
            )
        values = _assessment_values(
            decision_row_id=decision_row.pk,
            lifecycle_event_row_id=lifecycle_row.pk,
            active=active,
            fixed_income=fixed_income,
            policy=policy,
            calendar=calendar,
            facts=facts,
            assessment=assessment,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r5_monitoring_insert(
            token=self._token,
            model_type=R5MonitoringAssessmentLedgerModel,
            expected_values=values,
        ):
            return R5MonitoringAssessmentLedgerModel._default_manager.using(self._using).create(
                **values
            )

    def _assessment_collisions(
        self,
        assessment: R5PostPromotionMonitoringAssessment,
    ) -> tuple[R5MonitoringAssessmentLedgerModel, ...]:
        return tuple(
            R5MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(
                Q(assessment_id=assessment.assessment_id)
                | Q(content_hash=assessment.content_hash)
                | Q(
                    requested_policy_id=assessment.policy_id,
                    expected_policy_hash=assessment.policy_hash,
                    evaluated_at=assessment.evaluated_at,
                )
            )
            .select_related(
                "active_decision",
                "lifecycle_event",
                "active_decision__authorization",
                "active_decision__policy",
                "active_decision__trial",
                "lifecycle_event__authorization",
            )
        )

    def _assessment_winner(
        self,
        assessment: R5PostPromotionMonitoringAssessment,
    ) -> R5MonitoringPersistedAssessment | None:
        rows = self._assessment_collisions(assessment)
        exact = tuple(
            self._restore_bundle(row)
            for row in rows
            if row.assessment_id == assessment.assessment_id
            and row.content_hash == assessment.content_hash
        )
        return exact[0] if len(exact) == 1 else None

    def _append_fact(
        self,
        *,
        assessment_row: R5MonitoringAssessmentLedgerModel,
        decision_row: R5PromotionDecisionBundleModel,
        lifecycle_row: R5PromotionLifecycleEventModel,
        fact: R5PostPromotionMonitoringFact,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringObservationLedgerModel:
        values = _observation_values(
            assessment_row_id=assessment_row.pk,
            assessment_stable_id=assessment_row.assessment_id,
            decision_row_id=decision_row.pk,
            lifecycle_event_row_id=lifecycle_row.pk,
            fact=fact,
            ledger_recorded_at=ledger_recorded_at,
        )
        rows = tuple(
            R5MonitoringObservationLedgerModel._default_manager.using(self._using).filter(
                assessment_id=assessment_row.pk,
                period_id=fact.period_id,
            )
        )
        if rows:
            exact = tuple(
                row for row in rows if _observation_row_matches_domain_values(row, values)
            )
            if len(exact) == 1:
                return exact[0]
            raise R5MonitoringPersistenceConflict(
                "R5 monitoring assessment period is already sealed"
            )
        with _claim_r5_monitoring_insert(
            token=self._token,
            model_type=R5MonitoringObservationLedgerModel,
            expected_values=values,
        ):
            return R5MonitoringObservationLedgerModel._default_manager.using(self._using).create(
                **values
            )

    def _append_audit_snapshot(self, snapshot: _R5MonitoringAuditSnapshot) -> None:
        _require_active_r5_monitoring_uow()
        values = _snapshot_values(snapshot)
        try:
            with _claim_r5_monitoring_insert(
                token=self._token,
                model_type=R5MonitoringAuditSnapshotModel,
                expected_values=values,
            ):
                R5MonitoringAuditSnapshotModel._default_manager.using(self._using).create(**values)
        except IntegrityError as error:
            raise R5MonitoringPersistenceConflict(
                "R5 monitoring audit snapshot identity already exists"
            ) from error


def _build_r5_monitoring_writer(
    *,
    using: str = "default",
    clock: R5MonitoringClock | None = None,
) -> _DjangoR5MonitoringStore:
    """Build the private writer for component composition only."""

    return _DjangoR5MonitoringStore(using=using, clock=clock)


__all__ = ["DjangoR5MonitoringClock", "DjangoR5MonitoringRepository"]
