"""Strict append-only persistence and exact PIT reads for R8 monitoring."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
    GovernedOptimizationMonitoringClock,
    GovernedOptimizationMonitoringEvaluationEvidence,
)
from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringAssessmentRef,
    GovernedOptimizationMonitoringAuditEntry,
    GovernedOptimizationMonitoringAuditPage,
    GovernedOptimizationMonitoringPersistedAssessment,
    GovernedOptimizationMonitoringPersistenceConflict,
    GovernedOptimizationMonitoringPersistenceCorruption,
    GovernedOptimizationMonitoringPersistenceUnavailable,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    ActiveGovernedOptimizationResultEvidence,
    GovernedOptimizationMonitoringAssessment,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    evaluate_governed_optimization_monitoring,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_audit_codec import (
    _GovernedOptimizationMonitoringAuditCursor,
    _GovernedOptimizationMonitoringAuditSnapshot,
    create_monitoring_audit_snapshot,
    decode_monitoring_audit_cursor,
    encode_monitoring_audit_cursor,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    GovernedOptimizationMonitoringCodecError,
    decode_monitoring_assessment,
    decode_monitoring_calendar,
    decode_monitoring_observation,
    decode_monitoring_policy,
    decode_monitoring_promotions,
    decode_monitoring_source_evidence,
    encode_monitoring_assessment,
    encode_monitoring_calendar,
    encode_monitoring_observation,
    encode_monitoring_policy,
    encode_monitoring_promotions,
    encode_monitoring_source_evidence,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_models import (
    GovernedOptimizationMonitoringAssessmentModel,
    GovernedOptimizationMonitoringAuditSnapshotModel,
    GovernedOptimizationMonitoringObservationModel,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_persistence_codec import (
    _assessment_values,
    _aware_utc,
    _observation_id,
    _observation_row_matches_domain_values,
    _observation_values,
    _require_model_values,
    _restore_snapshot,
    _snapshot_values,
    _winner_matches_domain_evidence,
)
from apps.portfolio.infrastructure.optimization_input_receipt_codec import (
    decode_input_receipt,
    encode_input_receipt,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_codec import (
    lifecycle_to_domain,
    result_to_domain,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
    _claim_governed_optimization_insert,
    _require_active_governed_optimization_uow,
)


class DjangoGovernedOptimizationMonitoringClock:
    """Django timezone-backed authoritative server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoGovernedOptimizationMonitoringRepository:
    """Public exact PIT repository without a write capability token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: GovernedOptimizationMonitoringClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoGovernedOptimizationMonitoringClock()

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
            return _aware_utc(self._clock.now(), "R8 monitoring server clock")
        except GovernedOptimizationMonitoringPersistenceCorruption:
            raise
        except Exception as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring server clock is unavailable"
            ) from exc

    def get_exact(
        self,
        *,
        assessment_ref: GovernedOptimizationMonitoringAssessmentRef,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringPersistedAssessment | None:
        """Restore one exact complete graph ledger-known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        try:
            if type(assessment_ref) is not GovernedOptimizationMonitoringAssessmentRef:
                raise TypeError("assessment ref type differs")
            GovernedOptimizationMonitoringAssessmentRef.__post_init__(assessment_ref)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring assessment reference is malformed"
            ) from exc
        models = tuple(
            GovernedOptimizationMonitoringAssessmentModel._default_manager.using(self._using)
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
            .select_related("result", "result__input_receipt", "input_receipt")
        )
        if not models:
            return None
        restored = tuple(self._restore_bundle(model) for model in models)
        matches = tuple(item for item in restored if item.assessment_ref == assessment_ref)
        if len(models) != 1 or len(matches) != 1:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring exact assessment is aliased or substituted"
            )
        return matches[0]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> GovernedOptimizationMonitoringAuditPage:
        """Materialize or replay one immutable signed PIT audit manifest."""

        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("R8 monitoring audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = decode_monitoring_audit_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                entries = self._materialize_audit_entries(as_of=as_of)
                if len(entries) <= limit:
                    return GovernedOptimizationMonitoringAuditPage(
                        entries, None, as_of.astimezone(UTC)
                    )
                snapshot = create_monitoring_audit_snapshot(
                    as_of=as_of,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return GovernedOptimizationMonitoringAuditPage(
                    snapshot.entries[:limit],
                    encode_monitoring_audit_cursor(
                        snapshot=snapshot,
                        next_offset=limit,
                    ),
                    snapshot.as_of,
                )
            if cursor_value.snapshot_as_of != as_of.astimezone(UTC):
                raise GovernedOptimizationMonitoringPersistenceUnavailable(
                    "R8 monitoring audit cursor belongs to another cutoff"
                )
            snapshot = self._get_audit_snapshot(cursor_value)
            start = cursor_value.next_offset
            if snapshot.as_of != as_of.astimezone(UTC) or start >= len(snapshot.entries):
                raise GovernedOptimizationMonitoringPersistenceCorruption(
                    "R8 monitoring audit cursor differs from its snapshot"
                )
            entries = snapshot.entries[start : start + limit]
            self._validate_snapshot_entries(snapshot=snapshot, entries=entries)
            next_offset = start + len(entries)
            next_cursor = None
            if next_offset < len(snapshot.entries):
                next_cursor = encode_monitoring_audit_cursor(
                    snapshot=snapshot,
                    next_offset=next_offset,
                )
            return GovernedOptimizationMonitoringAuditPage(entries, next_cursor, snapshot.as_of)

    def _materialize_audit_entries(
        self,
        *,
        as_of: datetime,
    ) -> tuple[GovernedOptimizationMonitoringAuditEntry, ...]:
        models = tuple(
            GovernedOptimizationMonitoringAssessmentModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .select_related("result", "result__input_receipt", "input_receipt")
            .order_by("ledger_recorded_at", "assessment_id")
        )
        return tuple(self._audit_entry(self._restore_bundle(model)) for model in models)

    @staticmethod
    def _audit_entry(
        bundle: GovernedOptimizationMonitoringPersistedAssessment,
    ) -> GovernedOptimizationMonitoringAuditEntry:
        assessment = bundle.assessment
        return GovernedOptimizationMonitoringAuditEntry(
            assessment_ref=bundle.assessment_ref,
            result_id=assessment.result_id,
            result_hash=assessment.result_hash,
            policy_id=assessment.policy_id,
            policy_version=bundle.policy.policy_version,
            evaluated_at=assessment.evaluated_at,
            ledger_recorded_at=bundle.ledger_recorded_at,
            status=assessment.status,
            observation_count=len(bundle.observations),
            blocker_codes=tuple(item.value for item in assessment.blocker_codes),
            retirement_review_required=(assessment.manual_retirement_review_required),
        )

    def _append_audit_snapshot(
        self,
        snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
    ) -> None:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit snapshot writer is unavailable on read repository"
        )

    def _get_audit_snapshot(
        self,
        cursor: _GovernedOptimizationMonitoringAuditCursor,
    ) -> _GovernedOptimizationMonitoringAuditSnapshot:
        models = tuple(
            GovernedOptimizationMonitoringAuditSnapshotModel._default_manager.using(
                self._using
            ).filter(
                Q(
                    snapshot_id=cursor.snapshot_id,
                    snapshot_version=cursor.snapshot_version,
                )
                | Q(content_hash=cursor.snapshot_hash)
            )
        )
        matches = tuple(
            model
            for model in models
            if (model.snapshot_id, model.snapshot_version, model.content_hash)
            == (
                cursor.snapshot_id,
                cursor.snapshot_version,
                cursor.snapshot_hash,
            )
        )
        if len(models) != 1 or len(matches) != 1:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring audit snapshot is unavailable or substituted"
            )
        return _restore_snapshot(matches[0])

    def _validate_snapshot_entries(
        self,
        *,
        snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
        entries: tuple[GovernedOptimizationMonitoringAuditEntry, ...],
    ) -> None:
        for entry in entries:
            bundle = self.get_exact(
                assessment_ref=entry.assessment_ref,
                as_of=snapshot.as_of,
            )
            if bundle is None or self._audit_entry(bundle) != entry:
                raise GovernedOptimizationMonitoringPersistenceCorruption(
                    "R8 monitoring audit snapshot entry differs from its ledger"
                )

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        try:
            cutoff = _aware_utc(as_of, "R8 monitoring as_of")
        except GovernedOptimizationMonitoringPersistenceCorruption as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring as_of must be timezone-aware"
            ) from exc
        if cutoff > self.server_now():
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "future R8 monitoring as_of is not permitted"
            )

    def _restore_bundle(
        self,
        model: GovernedOptimizationMonitoringAssessmentModel,
    ) -> GovernedOptimizationMonitoringPersistedAssessment:
        try:
            promotions = decode_monitoring_promotions(model.upstream_promotions_payload)
            policy = decode_monitoring_policy(model.policy_payload)
            calendar = decode_monitoring_calendar(model.calendar_payload)
            assessment = decode_monitoring_assessment(model.assessment_payload)
        except GovernedOptimizationMonitoringCodecError as exc:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring assessment owner graph payload is invalid"
            ) from exc
        active_result = self._active_result_from_model(
            model.result,
            as_of=model.evaluated_at,
        )
        receipt = self._receipt_from_model(model.input_receipt)
        observations, portfolio, broker = self._observations_for_assessment(
            model=model,
            assessment=assessment,
        )
        values = _assessment_values(
            result_row_id=model.result_id,
            receipt_row_id=model.input_receipt_id,
            active_result=active_result,
            receipt=receipt,
            promotions=promotions,
            policy=policy,
            calendar=calendar,
            observations=observations,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_model_values(model=model, values=values, label="assessment")
        replayed = evaluate_governed_optimization_monitoring(
            requested_policy_id=model.requested_policy_id,
            requested_policy_version=model.requested_policy_version,
            expected_policy_hash=model.expected_policy_hash,
            active_result=active_result,
            receipt=receipt,
            current_upstream_promotions=promotions,
            policy=policy,
            calendar=calendar,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            observations=observations,
            evaluated_at=model.evaluated_at,
        )
        if replayed != assessment:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring assessment does not replay from owner facts"
            )
        return GovernedOptimizationMonitoringPersistedAssessment(
            assessment_ref=GovernedOptimizationMonitoringAssessmentRef(
                assessment.assessment_id,
                assessment.content_hash,
            ),
            active_result=active_result,
            receipt=receipt,
            upstream_promotions=promotions,
            policy=policy,
            calendar=calendar,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            observations=observations,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )

    def _observations_for_assessment(
        self,
        *,
        model: GovernedOptimizationMonitoringAssessmentModel,
        assessment: GovernedOptimizationMonitoringAssessment,
    ) -> tuple[
        tuple[OptimizationMonitoringPeriodObservation, ...],
        tuple[OptimizationMonitoringSourceEvidence, ...],
        tuple[OptimizationMonitoringSourceEvidence, ...],
    ]:
        rows = tuple(
            GovernedOptimizationMonitoringObservationModel._default_manager.using(self._using)
            .filter(
                assessment_id=model.assessment_id,
                domain_observation_hash__in=assessment.observation_hashes,
                ledger_recorded_at__lte=model.ledger_recorded_at,
            )
            .select_related("result", "result__input_receipt", "input_receipt")
        )
        restored: dict[
            str,
            tuple[
                OptimizationMonitoringPeriodObservation,
                tuple[OptimizationMonitoringSourceEvidence, ...],
                tuple[OptimizationMonitoringSourceEvidence, ...],
            ],
        ] = {}
        for row in rows:
            item = self._restore_observation(row)
            if item[0].content_hash in restored:
                raise GovernedOptimizationMonitoringPersistenceCorruption(
                    "duplicate R8 monitoring observation content seal"
                )
            restored[item[0].content_hash] = item
        if set(restored) != set(assessment.observation_hashes):
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring assessment observation graph is incomplete"
            )
        ordered = tuple(restored[item] for item in assessment.observation_hashes)
        return (
            tuple(item[0] for item in ordered),
            tuple(evidence for item in ordered for evidence in item[1]),
            tuple(evidence for item in ordered for evidence in item[2]),
        )

    def _restore_observation(
        self,
        model: GovernedOptimizationMonitoringObservationModel,
    ) -> tuple[
        OptimizationMonitoringPeriodObservation,
        tuple[OptimizationMonitoringSourceEvidence, ...],
        tuple[OptimizationMonitoringSourceEvidence, ...],
    ]:
        try:
            observation = decode_monitoring_observation(model.canonical_payload)
            portfolio = decode_monitoring_source_evidence(model.portfolio_evidence_payload)
            broker = decode_monitoring_source_evidence(model.broker_evidence_payload)
        except GovernedOptimizationMonitoringCodecError as exc:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring observation payload is invalid"
            ) from exc
        period = next(
            (
                item
                for item in decode_monitoring_calendar(
                    GovernedOptimizationMonitoringAssessmentModel._default_manager.using(
                        self._using
                    )
                    .get(assessment_id=model.assessment_id)
                    .calendar_payload
                ).periods
                if item.period_id == observation.period_id
            ),
            None,
        )
        if period is None:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring observation period is absent from its calendar"
            )
        values = _observation_values(
            result_row_id=model.result_id,
            receipt_row_id=model.input_receipt_id,
            assessment_id=model.assessment_id,
            result_hash=model.result_hash,
            receipt_hash=model.receipt_hash,
            policy_id=model.policy_id,
            policy_version=model.policy_version,
            policy_hash=model.policy_hash,
            calendar_id=model.calendar_id,
            calendar_version=model.calendar_version,
            calendar_hash=model.calendar_hash,
            period_start_at=period.start_at,
            period_end_at=period.end_at,
            observation=observation,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_model_values(model=model, values=values, label="observation")
        if (
            model.result.input_receipt_id != model.input_receipt_id
            or model.result.content_hash != model.result_hash
            or model.input_receipt.content_hash != model.receipt_hash
        ):
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring observation FK graph differs"
            )
        return observation, portfolio, broker

    def _active_result_from_model(
        self,
        model: GovernedOptimizationResearchResultModel,
        *,
        as_of: datetime,
    ) -> ActiveGovernedOptimizationResultEvidence:
        try:
            result = result_to_domain(model)
            events = tuple(
                lifecycle_to_domain(item)
                for item in OptimizationResearchLifecycleEventModel._default_manager.using(
                    self._using
                )
                .filter(result_id=model.pk, recorded_at__lte=as_of)
                .order_by("sequence")
            )
            return ActiveGovernedOptimizationResultEvidence.create(
                result=result,
                lifecycle_events=events,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring authoritative active result is invalid"
            ) from exc

    @staticmethod
    def _receipt_from_model(
        model: GovernedOptimizationInputReceiptModel,
    ) -> GovernedOptimizationInputReceipt:
        try:
            receipt = decode_input_receipt(model.canonical_payload)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring authoritative receipt is invalid"
            ) from exc
        if (
            model.receipt_id != receipt.receipt_id
            or model.receipt_version != receipt.receipt_version
            or model.owner != receipt.owner
            or model.input_set_id != receipt.input_set.input_set_id
            or model.input_set_version != receipt.input_set.input_set_version
            or model.input_set_hash != receipt.input_set.content_hash
            or model.evidence_graph_hash != receipt.evidence_graph_hash
            or model.pit_manifest_set_hash != receipt.pit_manifest_set_hash
            or model.recorded_at != receipt.recorded_at
            or model.content_hash != receipt.content_hash
            or model.canonical_payload != encode_input_receipt(receipt)
            or not (
                model.research_only and model.must_not_use_for_decision and model.must_not_execute
            )
        ):
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring authoritative receipt row differs"
            )
        return receipt


class _DjangoGovernedOptimizationMonitoringStore(DjangoGovernedOptimizationMonitoringRepository):
    """Private append and snapshot capability for internal composition."""

    __slots__ = ("_unit_of_work",)

    def __init__(
        self,
        *,
        unit_of_work: DjangoGovernedOptimizationUnitOfWork,
        clock: GovernedOptimizationMonitoringClock | None = None,
    ) -> None:
        super().__init__(using=unit_of_work.using, clock=clock)
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact private owner/write transaction identity."""

        return self._unit_of_work.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Open the private write capability scope."""

        return self._unit_of_work.atomic()

    def append_evidence(
        self,
        *,
        command: EvaluateGovernedOptimizationMonitoringCommand,
        evidence: GovernedOptimizationMonitoringEvaluationEvidence,
    ) -> GovernedOptimizationMonitoringPersistedAssessment:
        """Canonicalize, replay, and append one complete owner graph."""

        _require_active_governed_optimization_uow()
        try:
            if (
                evidence.active_result is None
                or evidence.receipt is None
                or evidence.policy is None
                or evidence.calendar is None
                or len(evidence.upstream_promotions) != 3
                or not evidence.portfolio_evidence
                or not evidence.broker_evidence
                or not evidence.observations
            ):
                raise ValueError("complete owner graph is required")
            promotions = decode_monitoring_promotions(
                encode_monitoring_promotions(evidence.upstream_promotions)
            )
            policy = decode_monitoring_policy(encode_monitoring_policy(evidence.policy))
            calendar = decode_monitoring_calendar(encode_monitoring_calendar(evidence.calendar))
            portfolio = decode_monitoring_source_evidence(
                encode_monitoring_source_evidence(evidence.portfolio_evidence)
            )
            broker = decode_monitoring_source_evidence(
                encode_monitoring_source_evidence(evidence.broker_evidence)
            )
            observations = tuple(
                decode_monitoring_observation(encode_monitoring_observation(item))
                for item in evidence.observations
            )
            assessment = decode_monitoring_assessment(
                encode_monitoring_assessment(evidence.assessment)
            )
        except (
            AttributeError,
            GovernedOptimizationMonitoringCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring append owner graph is malformed"
            ) from exc
        result_model = self._authoritative_result_model(
            evidence.active_result,
            as_of=command.as_of,
        )
        active_result = self._active_result_from_model(
            result_model,
            as_of=command.as_of,
        )
        receipt_model = result_model.input_receipt
        if receipt_model is None:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring authoritative receipt is unavailable"
            )
        receipt = self._receipt_from_model(receipt_model)
        if active_result != evidence.active_result or receipt != evidence.receipt:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring result or receipt owner changed before append"
            )
        replayed = evaluate_governed_optimization_monitoring(
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_result=active_result,
            receipt=receipt,
            current_upstream_promotions=promotions,
            policy=policy,
            calendar=calendar,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            observations=observations,
            evaluated_at=command.as_of,
        )
        if replayed != assessment:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring append differs from authoritative replay"
            )
        winner = self._assessment_winner(assessment)
        if winner is not None:
            if _winner_matches_domain_evidence(
                winner=winner,
                active_result=active_result,
                receipt=receipt,
                promotions=promotions,
                policy=policy,
                calendar=calendar,
                observations=observations,
                portfolio_evidence=portfolio,
                broker_evidence=broker,
                assessment=assessment,
            ):
                return winner
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring assessment identity is already sealed"
            )
        if self._assessment_collisions(assessment):
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring assessment command identity is already sealed"
            )
        ledger_recorded_at = self.server_now()
        if command.as_of > ledger_recorded_at:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "future R8 monitoring assessment cannot be persisted"
            )
        try:
            with transaction.atomic(using=self._using):
                for observation in observations:
                    self._append_observation(
                        result_model=result_model,
                        receipt_model=receipt_model,
                        assessment_id=assessment.assessment_id,
                        policy=policy,
                        calendar=calendar,
                        observation=observation,
                        portfolio_evidence=tuple(
                            item for item in portfolio if item.period_id == observation.period_id
                        ),
                        broker_evidence=tuple(
                            item for item in broker if item.period_id == observation.period_id
                        ),
                        ledger_recorded_at=ledger_recorded_at,
                    )
                return self._append_assessment(
                    result_model=result_model,
                    receipt_model=receipt_model,
                    active_result=active_result,
                    receipt=receipt,
                    promotions=promotions,
                    policy=policy,
                    calendar=calendar,
                    observations=observations,
                    portfolio_evidence=portfolio,
                    broker_evidence=broker,
                    assessment=assessment,
                    ledger_recorded_at=ledger_recorded_at,
                )
        except IntegrityError as exc:
            winner = self._assessment_winner(assessment)
            if winner is not None and _winner_matches_domain_evidence(
                winner=winner,
                active_result=active_result,
                receipt=receipt,
                promotions=promotions,
                policy=policy,
                calendar=calendar,
                observations=observations,
                portfolio_evidence=portfolio,
                broker_evidence=broker,
                assessment=assessment,
            ):
                return winner
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring append lost an identity race"
            ) from exc

    def _authoritative_result_model(
        self,
        evidence: ActiveGovernedOptimizationResultEvidence,
        *,
        as_of: datetime,
    ) -> GovernedOptimizationResearchResultModel:
        models = tuple(
            GovernedOptimizationResearchResultModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(result_id=evidence.result.result_id)
                | Q(content_hash=evidence.result.content_hash)
            )
            .select_related("input_receipt")
        )
        matches = tuple(
            model
            for model in models
            if self._active_result_from_model(model, as_of=as_of) == evidence
        )
        if len(models) != 1 or len(matches) != 1:
            raise GovernedOptimizationMonitoringPersistenceCorruption(
                "R8 monitoring authoritative result is aliased or substituted"
            )
        if matches[0].input_receipt_id is None:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring legacy result has no canonical receipt"
            )
        return matches[0]

    def _append_observation(
        self,
        *,
        result_model: GovernedOptimizationResearchResultModel,
        receipt_model: GovernedOptimizationInputReceiptModel,
        assessment_id: str,
        policy: GovernedOptimizationMonitoringPolicy,
        calendar: GovernedOptimizationMonitoringCalendar,
        observation: OptimizationMonitoringPeriodObservation,
        portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
        broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
        ledger_recorded_at: datetime,
    ) -> None:
        period = next(item for item in calendar.periods if item.period_id == observation.period_id)
        values = _observation_values(
            result_row_id=result_model.pk,
            receipt_row_id=receipt_model.pk,
            assessment_id=assessment_id,
            result_hash=result_model.content_hash,
            receipt_hash=receipt_model.content_hash,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_hash=policy.content_hash,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            calendar_hash=calendar.content_hash,
            period_start_at=period.start_at,
            period_end_at=period.end_at,
            observation=observation,
            portfolio_evidence=portfolio_evidence,
            broker_evidence=broker_evidence,
            ledger_recorded_at=ledger_recorded_at,
        )
        candidates = self._observation_collisions(
            assessment_id=assessment_id,
            observation=observation,
        )
        if candidates:
            exact = tuple(
                item for item in candidates if _observation_row_matches_domain_values(item, values)
            )
            if len(exact) == 1:
                return
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring observation identity is already sealed"
            )
        try:
            with transaction.atomic(using=self._using):
                with _claim_governed_optimization_insert(
                    token=self._unit_of_work._insert_claim_token(),
                    model_type=GovernedOptimizationMonitoringObservationModel,
                    expected_values=values,
                ):
                    GovernedOptimizationMonitoringObservationModel._default_manager.using(
                        self._using
                    ).create(**values)
        except IntegrityError as exc:
            winners = self._observation_collisions(
                assessment_id=assessment_id,
                observation=observation,
            )
            exact = tuple(
                item for item in winners if _observation_row_matches_domain_values(item, values)
            )
            if len(exact) == 1:
                return
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring observation append lost an identity race"
            ) from exc

    def _observation_collisions(
        self,
        *,
        assessment_id: str,
        observation: OptimizationMonitoringPeriodObservation,
    ) -> tuple[GovernedOptimizationMonitoringObservationModel, ...]:
        return tuple(
            GovernedOptimizationMonitoringObservationModel._default_manager.using(self._using)
            .filter(
                Q(
                    observation_id=_observation_id(assessment_id, observation),
                    observation_version=observation.observation_version,
                )
                | Q(assessment_id=assessment_id, period_id=observation.period_id)
            )
            .select_related("result", "result__input_receipt", "input_receipt")
        )

    def _append_assessment(
        self,
        *,
        result_model: GovernedOptimizationResearchResultModel,
        receipt_model: GovernedOptimizationInputReceiptModel,
        active_result: ActiveGovernedOptimizationResultEvidence,
        receipt: GovernedOptimizationInputReceipt,
        promotions: tuple[ExactPromotionAttestation, ...],
        policy: GovernedOptimizationMonitoringPolicy,
        calendar: GovernedOptimizationMonitoringCalendar,
        observations: tuple[OptimizationMonitoringPeriodObservation, ...],
        portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
        broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
        assessment: GovernedOptimizationMonitoringAssessment,
        ledger_recorded_at: datetime,
    ) -> GovernedOptimizationMonitoringPersistedAssessment:
        values = _assessment_values(
            result_row_id=result_model.pk,
            receipt_row_id=receipt_model.pk,
            active_result=active_result,
            receipt=receipt,
            promotions=promotions,
            policy=policy,
            calendar=calendar,
            observations=observations,
            portfolio_evidence=portfolio_evidence,
            broker_evidence=broker_evidence,
            assessment=assessment,
            ledger_recorded_at=ledger_recorded_at,
        )
        candidates = self._assessment_collisions(assessment)
        if candidates:
            exact = tuple(
                self._restore_bundle(item)
                for item in candidates
                if item.assessment_id == assessment.assessment_id
                and item.content_hash == assessment.content_hash
            )
            if (
                len(candidates) == 1
                and len(exact) == 1
                and _winner_matches_domain_evidence(
                    winner=exact[0],
                    active_result=active_result,
                    receipt=receipt,
                    promotions=promotions,
                    policy=policy,
                    calendar=calendar,
                    observations=observations,
                    portfolio_evidence=portfolio_evidence,
                    broker_evidence=broker_evidence,
                    assessment=assessment,
                )
            ):
                return exact[0]
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring assessment command identity is already sealed"
            )
        try:
            with transaction.atomic(using=self._using):
                with _claim_governed_optimization_insert(
                    token=self._unit_of_work._insert_claim_token(),
                    model_type=GovernedOptimizationMonitoringAssessmentModel,
                    expected_values=values,
                ):
                    model = GovernedOptimizationMonitoringAssessmentModel._default_manager.using(
                        self._using
                    ).create(**values)
        except IntegrityError as exc:
            winner = self._assessment_winner(assessment)
            if winner is not None and _winner_matches_domain_evidence(
                winner=winner,
                active_result=active_result,
                receipt=receipt,
                promotions=promotions,
                policy=policy,
                calendar=calendar,
                observations=observations,
                portfolio_evidence=portfolio_evidence,
                broker_evidence=broker_evidence,
                assessment=assessment,
            ):
                return winner
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring assessment append lost an identity race"
            ) from exc
        return self._restore_bundle(model)

    def _assessment_collisions(
        self,
        assessment: GovernedOptimizationMonitoringAssessment,
    ) -> tuple[GovernedOptimizationMonitoringAssessmentModel, ...]:
        return tuple(
            GovernedOptimizationMonitoringAssessmentModel._default_manager.using(self._using)
            .filter(
                Q(assessment_id=assessment.assessment_id)
                | Q(content_hash=assessment.content_hash)
                | Q(
                    requested_policy_id=assessment.policy_id,
                    expected_policy_hash=assessment.policy_hash,
                    evaluated_at=assessment.evaluated_at,
                )
            )
            .select_related("result", "result__input_receipt", "input_receipt")
        )

    def _assessment_winner(
        self,
        assessment: GovernedOptimizationMonitoringAssessment,
    ) -> GovernedOptimizationMonitoringPersistedAssessment | None:
        candidates = self._assessment_collisions(assessment)
        exact = tuple(
            self._restore_bundle(item)
            for item in candidates
            if item.assessment_id == assessment.assessment_id
            and item.content_hash == assessment.content_hash
        )
        return exact[0] if len(candidates) == 1 and len(exact) == 1 else None

    def _append_audit_snapshot(
        self,
        snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
    ) -> None:
        _require_active_governed_optimization_uow()
        values = _snapshot_values(snapshot)
        try:
            with transaction.atomic(using=self._using):
                with _claim_governed_optimization_insert(
                    token=self._unit_of_work._insert_claim_token(),
                    model_type=GovernedOptimizationMonitoringAuditSnapshotModel,
                    expected_values=values,
                ):
                    GovernedOptimizationMonitoringAuditSnapshotModel._default_manager.using(
                        self._using
                    ).create(**values)
        except IntegrityError as exc:
            raise GovernedOptimizationMonitoringPersistenceConflict(
                "R8 monitoring audit snapshot identity already exists"
            ) from exc


def _build_governed_optimization_monitoring_writer(
    *,
    unit_of_work: DjangoGovernedOptimizationUnitOfWork,
    clock: GovernedOptimizationMonitoringClock | None = None,
) -> _DjangoGovernedOptimizationMonitoringStore:
    """Build a private writer for one internal composition boundary."""

    return _DjangoGovernedOptimizationMonitoringStore(
        unit_of_work=unit_of_work,
        clock=clock,
    )


__all__ = [
    "DjangoGovernedOptimizationMonitoringClock",
    "DjangoGovernedOptimizationMonitoringRepository",
]
