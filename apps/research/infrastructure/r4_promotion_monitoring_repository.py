"""Strict append-only persistence and exact PIT reads for R4 monitoring."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringClock,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringAssessmentRef,
    R4MonitoringAuditEntry,
    R4MonitoringAuditPage,
    R4MonitoringPersistedAssessment,
    R4MonitoringPersistenceConflict,
    R4MonitoringPersistenceCorruption,
    R4MonitoringPersistenceUnavailable,
    r4_monitoring_assessment_id,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionR3AttestationEvidence,
)
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessment,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
    evaluate_r4_promotion_monitoring,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)
from apps.research.infrastructure.r4_promotion_codec import (
    R4PromotionCodecError,
    decode_r4_promotion_decision_bundle,
)
from apps.research.infrastructure.r4_promotion_model_values import (
    _decision_bundle_model_values,
    _decision_receipt_model_values,
    _policy_model_values,
)
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_audit_codec import (
    _R4MonitoringAuditCursor,
    _R4MonitoringAuditSnapshot,
    create_r4_monitoring_audit_snapshot,
    decode_r4_monitoring_audit_cursor,
    decode_r4_monitoring_audit_snapshot,
    encode_r4_monitoring_audit_cursor,
    encode_r4_monitoring_audit_snapshot,
)
from apps.research.infrastructure.r4_promotion_monitoring_codec import (
    R4MonitoringCodecError,
    decode_r4_monitoring_active_decision,
    decode_r4_monitoring_assessment,
    decode_r4_monitoring_observation,
    decode_r4_monitoring_period_calendar,
    decode_r4_monitoring_policy,
    decode_r4_monitoring_portfolio_result,
    decode_r4_monitoring_r3_attestation,
    encode_r4_monitoring_active_decision,
    encode_r4_monitoring_assessment,
    encode_r4_monitoring_observation,
    encode_r4_monitoring_period_calendar,
    encode_r4_monitoring_policy,
    encode_r4_monitoring_portfolio_result,
    encode_r4_monitoring_r3_attestation,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringAuditSnapshotModel,
    R4MonitoringObservationLedgerModel,
    _activate_r4_monitoring_uow,
    _claim_r4_monitoring_insert,
    _require_active_r4_monitoring_uow,
)


class DjangoR4MonitoringClock:
    """Django timezone-backed authoritative server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


def _aware_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R4MonitoringPersistenceCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _aware_utc(value, "R4 monitoring ledger datetime").isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise R4MonitoringPersistenceCorruption("R4 monitoring ledger keys must be strings")
        return {
            key: _ledger_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, (list, tuple)):
        return [_ledger_value(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise R4MonitoringPersistenceCorruption(
        f"unsupported R4 monitoring ledger value: {type(value).__name__}"
    )


def _ledger_header_hash(*, row_kind: str, values: dict[str, object]) -> str:
    payload = {
        "schema": "r4-monitoring-ledger-row-header.v1",
        "row_kind": row_kind,
        "values": {
            key: _ledger_value(value)
            for key, value in sorted(values.items(), key=lambda item: item[0])
            if key != "ledger_header_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_exact_model_values(
    *,
    model: object,
    values: dict[str, object],
    label: str,
) -> None:
    try:
        differs = any(
            getattr(model, field_name) != expected for field_name, expected in values.items()
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R4MonitoringPersistenceCorruption(
            f"R4 monitoring {label} row header is malformed"
        ) from error
    if differs:
        raise R4MonitoringPersistenceCorruption(f"R4 monitoring {label} row header differs")


class DjangoR4MonitoringRepository:
    """Public exact PIT repository without a write capability token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R4MonitoringClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR4MonitoringClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

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
            return _aware_utc(self._clock.now(), "R4 monitoring server clock")
        except R4MonitoringPersistenceCorruption:
            raise
        except Exception as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring server clock is unavailable"
            ) from error

    def get_exact(
        self,
        *,
        assessment_ref: R4MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R4MonitoringPersistedAssessment | None:
        """Restore one exact complete graph ledger-known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        try:
            assessment_ref.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring assessment reference is malformed"
            ) from error
        models = tuple(
            R4MonitoringAssessmentLedgerModel._default_manager.using(self._using)
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
                "active_decision__receipt",
                "active_decision__policy",
            )
        )
        if not models:
            return None
        restored = tuple(self._restore_bundle(model) for model in models)
        matches = tuple(item for item in restored if item.assessment_ref == assessment_ref)
        if len(models) != 1 or len(matches) != 1:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring exact assessment is aliased or substituted"
            )
        return matches[0]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R4MonitoringAuditPage:
        """Materialize or replay one immutable signed PIT audit manifest."""

        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValueError("R4 monitoring audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = decode_r4_monitoring_audit_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                entries = self._materialize_audit_entries(as_of=as_of)
                if len(entries) <= limit:
                    return R4MonitoringAuditPage(entries, None, as_of.astimezone(UTC))
                snapshot = create_r4_monitoring_audit_snapshot(
                    as_of=as_of,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return R4MonitoringAuditPage(
                    snapshot.entries[:limit],
                    encode_r4_monitoring_audit_cursor(
                        snapshot=snapshot,
                        next_offset=limit,
                    ),
                    snapshot.as_of,
                )
            if cursor_value.snapshot_as_of != as_of.astimezone(UTC):
                raise R4MonitoringPersistenceUnavailable(
                    "R4 monitoring audit cursor belongs to another cutoff"
                )
            snapshot = self._get_audit_snapshot(cursor_value)
            if snapshot.as_of != as_of.astimezone(UTC):
                raise R4MonitoringPersistenceCorruption(
                    "R4 monitoring audit snapshot cutoff differs"
                )
            start = cursor_value.next_offset
            if start >= len(snapshot.entries):
                raise R4MonitoringPersistenceCorruption(
                    "R4 monitoring audit cursor exceeds its snapshot"
                )
            entries = snapshot.entries[start : start + limit]
            self._validate_snapshot_entries(snapshot=snapshot, entries=entries)
            next_offset = start + len(entries)
            next_cursor = None
            if next_offset < len(snapshot.entries):
                next_cursor = encode_r4_monitoring_audit_cursor(
                    snapshot=snapshot,
                    next_offset=next_offset,
                )
            return R4MonitoringAuditPage(entries, next_cursor, snapshot.as_of)

    def _materialize_audit_entries(
        self,
        *,
        as_of: datetime,
    ) -> tuple[R4MonitoringAuditEntry, ...]:
        models = tuple(
            R4MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .select_related(
                "active_decision",
                "active_decision__receipt",
                "active_decision__policy",
            )
            .order_by("ledger_recorded_at", "assessment_id")
        )
        return tuple(self._audit_entry(self._restore_bundle(model)) for model in models)

    @staticmethod
    def _audit_entry(bundle: R4MonitoringPersistedAssessment) -> R4MonitoringAuditEntry:
        assessment = bundle.assessment
        return R4MonitoringAuditEntry(
            assessment_ref=bundle.assessment_ref,
            active_decision=assessment.active_decision,
            policy_id=assessment.requested_policy_id,
            policy_version=assessment.requested_policy_version,
            evaluated_at=assessment.evaluated_at,
            ledger_recorded_at=bundle.ledger_recorded_at,
            status=assessment.status,
            observation_count=len(bundle.observations),
            blockers=tuple(item.value for item in assessment.blockers),
            review_reason_codes=assessment.review_reason_codes,
            retirement_review_required=assessment.retirement_review_required,
        )

    def _append_audit_snapshot(self, snapshot: _R4MonitoringAuditSnapshot) -> None:
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring audit snapshot writer is unavailable on read repository"
        )

    def _get_audit_snapshot(
        self,
        cursor: _R4MonitoringAuditCursor,
    ) -> _R4MonitoringAuditSnapshot:
        models = tuple(
            R4MonitoringAuditSnapshotModel._default_manager.using(self._using).filter(
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
            if (
                model.snapshot_id,
                model.snapshot_version,
                model.content_hash,
            )
            == (
                cursor.snapshot_id,
                cursor.snapshot_version,
                cursor.snapshot_hash,
            )
        )
        if len(models) != 1 or len(matches) != 1:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring audit snapshot is unavailable or substituted"
            )
        return _restore_snapshot(matches[0])

    def _validate_snapshot_entries(
        self,
        *,
        snapshot: _R4MonitoringAuditSnapshot,
        entries: tuple[R4MonitoringAuditEntry, ...],
    ) -> None:
        for entry in entries:
            bundle = self.get_exact(
                assessment_ref=entry.assessment_ref,
                as_of=snapshot.as_of,
            )
            if bundle is None or self._audit_entry(bundle) != entry:
                raise R4MonitoringPersistenceCorruption(
                    "R4 monitoring audit snapshot entry differs from its ledger"
                )

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        try:
            cutoff = _aware_utc(as_of, "R4 monitoring as_of")
        except R4MonitoringPersistenceCorruption as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring as_of must be timezone-aware"
            ) from error
        if cutoff > self.server_now():
            raise R4MonitoringPersistenceUnavailable("future R4 monitoring as_of is not permitted")

    def _restore_bundle(
        self,
        model: R4MonitoringAssessmentLedgerModel,
    ) -> R4MonitoringPersistedAssessment:
        try:
            active_decision = decode_r4_monitoring_active_decision(model.active_decision_payload)
            portfolio = decode_r4_monitoring_portfolio_result(model.portfolio_result_payload)
            r3 = decode_r4_monitoring_r3_attestation(model.r3_attestation_payload)
            policy = decode_r4_monitoring_policy(model.policy_payload)
            calendar = decode_r4_monitoring_period_calendar(model.period_calendar_payload)
            assessment = decode_r4_monitoring_assessment(model.canonical_payload)
        except R4MonitoringCodecError as error:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring assessment owner graph payload is invalid"
            ) from error
        expected_id = r4_monitoring_assessment_id(
            active_decision=assessment.active_decision,
            expected_policy_hash=assessment.expected_policy_hash,
            evaluated_at=assessment.evaluated_at,
        )
        owner_decision = self._restore_owner_decision(model.active_decision)
        if owner_decision != active_decision:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring assessment active-decision FK differs"
            )
        observations = self._observations_for_assessment(
            model=model,
            assessment=assessment,
            active_decision=active_decision,
        )
        values = _assessment_values(
            active_decision_row_id=model.active_decision_id,
            assessment_id=expected_id,
            active_decision=active_decision,
            portfolio=portfolio,
            r3=r3,
            policy=policy,
            calendar=calendar,
            observations=observations,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_exact_model_values(model=model, values=values, label="assessment")
        replayed = evaluate_r4_promotion_monitoring(
            requested_active_decision=assessment.active_decision,
            requested_policy_id=assessment.requested_policy_id,
            requested_policy_version=assessment.requested_policy_version,
            expected_policy_hash=assessment.expected_policy_hash,
            active_decision=active_decision,
            portfolio_result=portfolio,
            current_r3_attestation=r3,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            evaluated_at=assessment.evaluated_at,
        )
        if replayed != assessment:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring assessment does not replay from persisted owner facts"
            )
        return R4MonitoringPersistedAssessment(
            assessment_ref=R4MonitoringAssessmentRef(expected_id, assessment.content_hash),
            active_decision=active_decision,
            portfolio_result=portfolio,
            current_r3_attestation=r3,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            assessment=assessment,
            ledger_recorded_at=model.ledger_recorded_at,
        )

    def _observations_for_assessment(
        self,
        *,
        model: R4MonitoringAssessmentLedgerModel,
        assessment: R4MonitoringAssessment,
        active_decision: R4PromotionDecision,
    ) -> tuple[R4MonitoringObservation, ...]:
        models = tuple(
            R4MonitoringObservationLedgerModel._default_manager.using(self._using)
            .filter(
                content_hash__in=assessment.observation_hashes,
                ledger_recorded_at__lte=model.ledger_recorded_at,
            )
            .select_related(
                "active_decision",
                "active_decision__receipt",
                "active_decision__policy",
            )
        )
        restored: dict[str, R4MonitoringObservation] = {}
        for observation_model in models:
            observation = self._restore_observation(
                observation_model,
                active_decision=active_decision,
            )
            if observation.content_hash in restored:
                raise R4MonitoringPersistenceCorruption(
                    "duplicate R4 monitoring observation content seal"
                )
            restored[observation.content_hash] = observation
        if set(restored) != set(assessment.observation_hashes):
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring assessment observation graph is incomplete"
            )
        return tuple(restored[item] for item in assessment.observation_hashes)

    def _restore_observation(
        self,
        model: R4MonitoringObservationLedgerModel,
        *,
        active_decision: R4PromotionDecision,
    ) -> R4MonitoringObservation:
        try:
            observation = decode_r4_monitoring_observation(model.canonical_payload)
        except R4MonitoringCodecError as error:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring observation payload is invalid"
            ) from error
        values = _observation_values(
            active_decision_row_id=model.active_decision_id,
            observation=observation,
            ledger_recorded_at=model.ledger_recorded_at,
        )
        _require_exact_model_values(model=model, values=values, label="observation")
        if self._restore_owner_decision(model.active_decision) != active_decision:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring observation active-decision FK differs"
            )
        return observation

    @staticmethod
    def _restore_owner_decision(model: R4PromotionDecisionBundleModel) -> R4PromotionDecision:
        try:
            bundle = decode_r4_promotion_decision_bundle(model.canonical_payload)
        except R4PromotionCodecError as error:
            raise R4MonitoringPersistenceCorruption(
                "persisted R4 active-decision owner payload is invalid"
            ) from error
        _require_exact_model_values(
            model=model,
            values=_decision_bundle_model_values(bundle),
            label="active-decision owner",
        )
        _require_exact_model_values(
            model=model.receipt,
            values=_decision_receipt_model_values(bundle.receipt),
            label="active-decision receipt owner",
        )
        _require_exact_model_values(
            model=model.policy,
            values=_policy_model_values(bundle.decision.policy),
            label="active-decision policy owner",
        )
        if (
            model.receipt_id is None
            or model.policy_id is None
            or model.receipt.policy_id != model.policy_id
        ):
            raise R4MonitoringPersistenceCorruption(
                "persisted R4 active-decision owner FK graph differs"
            )
        return bundle.decision


class _DjangoR4MonitoringStore(DjangoR4MonitoringRepository):
    """Private append and audit-snapshot capability for internal composition."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R4MonitoringClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Open the private R4 monitoring write capability scope."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r4_monitoring_uow(self._token):
            yield

    def append_evidence(
        self,
        *,
        command: EvaluateR4PromotionMonitoringCommand,
        evidence: R4MonitoringEvaluationEvidence,
    ) -> R4MonitoringPersistedAssessment:
        """Canonicalize, replay, and append one complete exact owner graph."""

        _require_active_r4_monitoring_uow()
        ledger_recorded_at = self.server_now()
        if command.as_of > ledger_recorded_at:
            raise R4MonitoringPersistenceUnavailable(
                "future R4 monitoring assessment cannot be persisted"
            )
        try:
            if (
                evidence.active_decision is None
                or evidence.portfolio_result is None
                or evidence.current_r3_attestation is None
                or evidence.policy is None
                or evidence.period_calendar is None
                or not evidence.observations
            ):
                raise ValueError("complete owner graph is required")
            active_decision = decode_r4_monitoring_active_decision(
                encode_r4_monitoring_active_decision(evidence.active_decision)
            )
            portfolio = decode_r4_monitoring_portfolio_result(
                encode_r4_monitoring_portfolio_result(evidence.portfolio_result)
            )
            r3 = decode_r4_monitoring_r3_attestation(
                encode_r4_monitoring_r3_attestation(evidence.current_r3_attestation)
            )
            policy = decode_r4_monitoring_policy(encode_r4_monitoring_policy(evidence.policy))
            calendar = decode_r4_monitoring_period_calendar(
                encode_r4_monitoring_period_calendar(evidence.period_calendar)
            )
            observations = tuple(
                decode_r4_monitoring_observation(encode_r4_monitoring_observation(item))
                for item in evidence.observations
            )
            assessment = decode_r4_monitoring_assessment(
                encode_r4_monitoring_assessment(evidence.assessment)
            )
        except (AttributeError, R4MonitoringCodecError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring append owner graph is malformed"
            ) from error
        if (
            assessment.evaluated_at != command.as_of
            or assessment.active_decision != command.active_decision
            or assessment.requested_policy_id != command.policy_id
            or assessment.requested_policy_version != command.policy_version
            or assessment.expected_policy_hash != command.expected_policy_hash
        ):
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring append command differs from assessment"
            )
        active_model = self._active_decision_model(
            active_decision,
            as_of=command.as_of,
        )
        replayed = evaluate_r4_promotion_monitoring(
            requested_active_decision=command.active_decision,
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_decision=active_decision,
            portfolio_result=portfolio,
            current_r3_attestation=r3,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            evaluated_at=command.as_of,
        )
        if replayed != assessment:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring append differs from authoritative replay"
            )
        assessment_id = r4_monitoring_assessment_id(
            active_decision=command.active_decision,
            expected_policy_hash=command.expected_policy_hash,
            evaluated_at=command.as_of,
        )
        try:
            with transaction.atomic(using=self._using):
                for observation in observations:
                    self._append_observation(
                        active_decision_model=active_model,
                        observation=observation,
                        ledger_recorded_at=ledger_recorded_at,
                    )
                return self._append_assessment(
                    active_decision_model=active_model,
                    assessment_id=assessment_id,
                    active_decision=active_decision,
                    portfolio=portfolio,
                    r3=r3,
                    policy=policy,
                    calendar=calendar,
                    observations=observations,
                    assessment=assessment,
                    ledger_recorded_at=ledger_recorded_at,
                )
        except IntegrityError as error:
            winner = self._assessment_winner(assessment_id, assessment)
            if winner is not None and winner.assessment == assessment:
                return winner
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring append lost an identity race"
            ) from error

    def _active_decision_model(
        self,
        decision: R4PromotionDecision,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundleModel:
        models = tuple(
            R4PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                Q(
                    decision_id=decision.decision_id,
                    decision_version=decision.decision_version,
                    recorded_at__lte=as_of,
                )
                | Q(
                    decision_content_hash=decision.content_hash,
                    recorded_at__lte=as_of,
                )
            )
            .select_related("receipt", "policy", "receipt__policy")
        )
        if not models:
            raise R4MonitoringPersistenceUnavailable(
                "exact persisted R4 active-decision owner is unavailable"
            )
        restored = tuple(self._restore_owner_decision(model) for model in models)
        matches = tuple(
            model
            for model, restored_decision in zip(models, restored, strict=True)
            if restored_decision == decision
        )
        if len(models) != 1 or len(matches) != 1:
            raise R4MonitoringPersistenceCorruption(
                "persisted R4 active-decision owner is aliased or substituted"
            )
        return matches[0]

    def _append_observation(
        self,
        *,
        active_decision_model: R4PromotionDecisionBundleModel,
        observation: R4MonitoringObservation,
        ledger_recorded_at: datetime,
    ) -> R4MonitoringObservationLedgerModel:
        candidates = self._observation_collisions(observation)
        if candidates:
            exact = tuple(
                model
                for model in candidates
                if self._restore_observation(
                    model,
                    active_decision=self._restore_owner_decision(active_decision_model),
                )
                == observation
            )
            if len(exact) == 1:
                return exact[0]
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring observation identity/period is already sealed"
            )
        values = _observation_values(
            active_decision_row_id=active_decision_model.pk,
            observation=observation,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_monitoring_insert(
                    token=self._token,
                    model_type=R4MonitoringObservationLedgerModel,
                    expected_values=values,
                ):
                    return R4MonitoringObservationLedgerModel._default_manager.using(
                        self._using
                    ).create(**values)
        except IntegrityError as error:
            winners = self._observation_collisions(observation)
            exact = tuple(
                model
                for model in winners
                if self._restore_observation(
                    model,
                    active_decision=self._restore_owner_decision(active_decision_model),
                )
                == observation
            )
            if len(exact) == 1:
                return exact[0]
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring observation append lost an identity race"
            ) from error

    def _observation_collisions(
        self,
        observation: R4MonitoringObservation,
    ) -> tuple[R4MonitoringObservationLedgerModel, ...]:
        return tuple(
            R4MonitoringObservationLedgerModel._default_manager.using(self._using)
            .filter(
                Q(
                    observation_id=observation.observation_id,
                    observation_version=observation.observation_version,
                )
                | Q(content_hash=observation.content_hash)
                | Q(
                    active_decision_stable_id=observation.active_decision.decision_id,
                    active_decision_version=observation.active_decision.decision_version,
                    policy_hash=observation.policy_hash,
                    period_id=observation.period_id,
                )
            )
            .select_related(
                "active_decision",
                "active_decision__receipt",
                "active_decision__policy",
            )
        )

    def _append_assessment(
        self,
        *,
        active_decision_model: R4PromotionDecisionBundleModel,
        assessment_id: str,
        active_decision: R4PromotionDecision,
        portfolio: R4PromotionPortfolioRecordSeal,
        r3: R4PromotionR3AttestationEvidence,
        policy: R4MonitoringPolicy,
        calendar: R4MonitoringPeriodCalendar,
        observations: tuple[R4MonitoringObservation, ...],
        assessment: R4MonitoringAssessment,
        ledger_recorded_at: datetime,
    ) -> R4MonitoringPersistedAssessment:
        candidates = self._assessment_collisions(assessment_id, assessment)
        if candidates:
            exact = tuple(
                self._restore_bundle(model)
                for model in candidates
                if model.assessment_id == assessment_id
                and model.content_hash == assessment.content_hash
            )
            if len(exact) == 1:
                return exact[0]
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring assessment command identity is already sealed"
            )
        values = _assessment_values(
            active_decision_row_id=active_decision_model.pk,
            assessment_id=assessment_id,
            active_decision=active_decision,
            portfolio=portfolio,
            r3=r3,
            policy=policy,
            calendar=calendar,
            observations=observations,
            assessment=assessment,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_monitoring_insert(
                    token=self._token,
                    model_type=R4MonitoringAssessmentLedgerModel,
                    expected_values=values,
                ):
                    model = R4MonitoringAssessmentLedgerModel._default_manager.using(
                        self._using
                    ).create(**values)
        except IntegrityError as error:
            winner = self._assessment_winner(assessment_id, assessment)
            if winner is not None and winner.assessment == assessment:
                return winner
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring assessment append lost an identity race"
            ) from error
        return self._restore_bundle(model)

    def _assessment_collisions(
        self,
        assessment_id: str,
        assessment: R4MonitoringAssessment,
    ) -> tuple[R4MonitoringAssessmentLedgerModel, ...]:
        return tuple(
            R4MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(
                Q(assessment_id=assessment_id)
                | Q(content_hash=assessment.content_hash)
                | Q(
                    active_decision_stable_id=assessment.active_decision.decision_id,
                    active_decision_version=assessment.active_decision.decision_version,
                    expected_policy_hash=assessment.expected_policy_hash,
                    evaluated_at=assessment.evaluated_at,
                )
            )
            .select_related(
                "active_decision",
                "active_decision__receipt",
                "active_decision__policy",
            )
        )

    def _assessment_winner(
        self,
        assessment_id: str,
        assessment: R4MonitoringAssessment,
    ) -> R4MonitoringPersistedAssessment | None:
        candidates = self._assessment_collisions(assessment_id, assessment)
        exact = tuple(
            self._restore_bundle(model)
            for model in candidates
            if model.assessment_id == assessment_id
            and model.content_hash == assessment.content_hash
        )
        return exact[0] if len(exact) == 1 else None

    def _append_audit_snapshot(self, snapshot: _R4MonitoringAuditSnapshot) -> None:
        _require_active_r4_monitoring_uow()
        values = _snapshot_values(snapshot)
        try:
            with _claim_r4_monitoring_insert(
                token=self._token,
                model_type=R4MonitoringAuditSnapshotModel,
                expected_values=values,
            ):
                R4MonitoringAuditSnapshotModel._default_manager.using(self._using).create(**values)
        except IntegrityError as error:
            raise R4MonitoringPersistenceConflict(
                "R4 monitoring audit snapshot identity already exists"
            ) from error


def _observation_values(
    *,
    active_decision_row_id: int,
    observation: R4MonitoringObservation,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "active_decision_id": active_decision_row_id,
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "active_decision_stable_id": observation.active_decision.decision_id,
        "active_decision_version": observation.active_decision.decision_version,
        "active_decision_hash": observation.active_decision.content_hash,
        "policy_id": observation.policy_id,
        "policy_version": observation.policy_version,
        "policy_hash": observation.policy_hash,
        "period_calendar_id": observation.period_calendar_id,
        "period_calendar_version": observation.period_calendar_version,
        "period_calendar_hash": observation.period_calendar_hash,
        "period_id": observation.period_id,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "source_owner": observation.source_owner,
        "portfolio_record_id": observation.portfolio_record_id,
        "portfolio_record_hash": observation.portfolio_record_hash,
        "portfolio_record_content_hash": observation.portfolio_record_content_hash,
        "r3_attestation_content_hash": observation.r3_attestation_content_hash,
        "observed_at": observation.observed_at,
        "available_at": observation.available_at,
        "owner_recorded_at": observation.recorded_at,
        "valid_until": observation.valid_until,
        "pit_manifest_id": observation.pit_manifest_id,
        "pit_manifest_hash": observation.pit_manifest_hash,
        "evidence_ref": observation.evidence_ref,
        "label_protocol_version": observation.label_protocol_version,
        "observed_label_set_hash": observation.observed_label_set_hash,
        "observed_data_schema_hash": observation.observed_data_schema_hash,
        "metric_count": len(observation.metrics),
        "canonical_payload": encode_r4_monitoring_observation(observation),
        "content_hash": observation.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": observation.research_only,
        "must_not_use_for_decision": observation.must_not_use_for_decision,
        "must_not_publish_current": observation.must_not_publish_current,
        "must_not_execute": observation.must_not_execute,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="observation",
        values=values,
    )
    return values


def _assessment_values(
    *,
    active_decision_row_id: int,
    assessment_id: str,
    active_decision: R4PromotionDecision,
    portfolio: R4PromotionPortfolioRecordSeal,
    r3: R4PromotionR3AttestationEvidence,
    policy: R4MonitoringPolicy,
    calendar: R4MonitoringPeriodCalendar,
    observations: tuple[R4MonitoringObservation, ...],
    assessment: R4MonitoringAssessment,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    if (
        type(portfolio) is not R4PromotionPortfolioRecordSeal
        or type(r3) is not R4PromotionR3AttestationEvidence
        or not observations
    ):
        raise R4MonitoringPersistenceCorruption("R4 monitoring assessment owner types are invalid")
    values: dict[str, object] = {
        "active_decision_id": active_decision_row_id,
        "assessment_id": assessment_id,
        "active_decision_stable_id": assessment.active_decision.decision_id,
        "active_decision_version": assessment.active_decision.decision_version,
        "active_decision_hash": assessment.active_decision.content_hash,
        "requested_policy_id": assessment.requested_policy_id,
        "requested_policy_version": assessment.requested_policy_version,
        "expected_policy_hash": assessment.expected_policy_hash,
        "policy_hash": policy.content_hash,
        "period_calendar_id": calendar.calendar_id,
        "period_calendar_version": calendar.calendar_version,
        "period_calendar_hash": calendar.content_hash,
        "portfolio_record_content_hash": portfolio.content_hash,
        "r3_attestation_content_hash": r3.content_hash,
        "evaluated_at": assessment.evaluated_at,
        "active_decision_owner_recorded_at": active_decision.recorded_at,
        "portfolio_owner_recorded_at": portfolio.recorded_at,
        "r3_owner_known_at": r3.approved_at,
        "policy_owner_recorded_at": policy.recorded_at,
        "calendar_owner_recorded_at": calendar.recorded_at,
        "latest_observation_owner_recorded_at": max(
            observation.recorded_at for observation in observations
        ),
        "ledger_recorded_at": ledger_recorded_at,
        "status": assessment.status.value,
        "observation_count": len(assessment.observation_hashes),
        "metric_result_count": len(assessment.metric_results),
        "observation_hashes": list(assessment.observation_hashes),
        "blockers": [item.value for item in assessment.blockers],
        "review_reason_codes": list(assessment.review_reason_codes),
        "active_decision_payload": encode_r4_monitoring_active_decision(active_decision),
        "portfolio_result_payload": encode_r4_monitoring_portfolio_result(portfolio),
        "r3_attestation_payload": encode_r4_monitoring_r3_attestation(r3),
        "policy_payload": encode_r4_monitoring_policy(policy),
        "period_calendar_payload": encode_r4_monitoring_period_calendar(calendar),
        "canonical_payload": encode_r4_monitoring_assessment(assessment),
        "content_hash": assessment.content_hash,
        "label_drift_detected": assessment.label_drift_detected,
        "data_drift_detected": assessment.data_drift_detected,
        "retirement_review_required": assessment.retirement_review_required,
        "automatic_retirement": assessment.automatic_retirement,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_publish_current": assessment.must_not_publish_current,
        "must_not_execute": assessment.must_not_execute,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="assessment",
        values=values,
    )
    return values


def _snapshot_values(snapshot: _R4MonitoringAuditSnapshot) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": encode_r4_monitoring_audit_snapshot(snapshot),
        "content_hash": snapshot.content_hash,
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="audit_snapshot",
        values=values,
    )
    return values


def _restore_snapshot(model: R4MonitoringAuditSnapshotModel) -> _R4MonitoringAuditSnapshot:
    snapshot = decode_r4_monitoring_audit_snapshot(model.canonical_payload)
    values = _snapshot_values(snapshot)
    _require_exact_model_values(model=model, values=values, label="audit snapshot")
    return snapshot


__all__ = ["DjangoR4MonitoringClock", "DjangoR4MonitoringRepository"]
