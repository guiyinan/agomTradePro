"""Strict append-only persistence and exact PIT reads for R6 monitoring."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.state_model_monitoring import R6MonitoringClock
from apps.research.application.state_model_monitoring_persistence import (
    R6MonitoringAssessmentRef,
    R6MonitoringAuditEntry,
    R6MonitoringAuditPage,
    R6MonitoringPersistedAssessment,
    R6MonitoringPersistenceConflict,
    R6MonitoringPersistenceCorruption,
    R6MonitoringPersistenceUnavailable,
    r6_monitoring_assessment_id,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
    evaluate_r6_monitoring,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef
from apps.research.infrastructure.state_model_monitoring_codec import (
    R6MonitoringCodecError,
    decode_r6_monitoring_assessment,
    decode_r6_monitoring_observation,
    decode_r6_monitoring_period_calendar,
    decode_r6_monitoring_policy,
    encode_r6_monitoring_assessment,
    encode_r6_monitoring_observation,
    encode_r6_monitoring_period_calendar,
    encode_r6_monitoring_policy,
)
from apps.research.infrastructure.state_model_monitoring_models import (
    R6MonitoringAssessmentModel,
    R6MonitoringObservationModel,
    _activate_r6_monitoring_uow,
    _claim_r6_monitoring_insert,
    _require_active_r6_monitoring_uow,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
)


class DjangoR6MonitoringClock:
    """Django timezone-backed server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R6MonitoringPersistenceCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _ledger_header_value(value: object) -> object:
    """Normalize a row-header value for a deterministic infrastructure seal."""

    if isinstance(value, datetime):
        return _aware_utc(value, "R6 monitoring ledger header datetime").isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring ledger header keys must be strings"
            )
        return {
            key: _ledger_header_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, (list, tuple)):
        return [_ledger_header_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise R6MonitoringPersistenceCorruption(
        f"unsupported R6 monitoring ledger header value: {type(value).__name__}"
    )


def _ledger_header_hash(*, row_kind: str, values: dict[str, object]) -> str:
    payload = {
        "schema": "r6-monitoring-ledger-row-header.v1",
        "row_kind": row_kind,
        "values": {
            key: _ledger_header_value(value)
            for key, value in sorted(values.items(), key=lambda item: item[0])
            if key != "ledger_header_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_exact_model_values(
    *,
    model: R6MonitoringAssessmentModel | R6MonitoringObservationModel,
    values: dict[str, object],
    label: str,
) -> None:
    if any(getattr(model, field_name) != expected for field_name, expected in values.items()):
        raise R6MonitoringPersistenceCorruption(f"R6 monitoring {label} header mismatch")


class DjangoR6MonitoringRepository:
    """Public exact PIT repository without any write or live-audit capability."""

    __slots__ = ("_using",)

    def __init__(
        self,
        *,
        using: str = "default",
    ) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the Django database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Enter a read transaction without activating append capability."""

        return transaction.atomic(using=self._using)

    def server_now(self) -> datetime:
        """Return the validated authoritative server clock."""

        return _aware_utc(DjangoR6MonitoringClock().now(), "R6 monitoring server clock")

    def get_exact(
        self,
        *,
        assessment_ref: R6MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R6MonitoringPersistedAssessment | None:
        """Restore one exact graph only when ledger-known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        models = list(
            R6MonitoringAssessmentModel._default_manager.using(self._using).filter(
                Q(
                    assessment_id=assessment_ref.assessment_id,
                    ledger_recorded_at__lte=as_of,
                )
                | Q(
                    content_hash=assessment_ref.assessment_hash,
                    ledger_recorded_at__lte=as_of,
                )
            )
        )
        if not models:
            return None
        matches = tuple(
            bundle
            for model in models
            for bundle in (self._restore_bundle(model),)
            if bundle.assessment_ref == assessment_ref
        )
        if len(matches) > 1:
            raise R6MonitoringPersistenceCorruption(
                "multiple R6 monitoring rows match one exact assessment"
            )
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6MonitoringAuditPage:
        """Reject live-ledger audit from the public read capability."""

        raise R6MonitoringPersistenceUnavailable("R6 monitoring production audit is unavailable")

    def _list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6MonitoringAuditPage:
        """Return one deterministic PIT audit page for the private test store."""

        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R6 monitoring audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = _decode_cursor(cursor, as_of=as_of)
        query = R6MonitoringAssessmentModel._default_manager.using(self._using).filter(
            ledger_recorded_at__lte=as_of
        )
        if cursor_value is not None:
            cursor_at, cursor_id = cursor_value
            query = query.filter(
                Q(ledger_recorded_at__gt=cursor_at)
                | Q(ledger_recorded_at=cursor_at, assessment_id__gt=cursor_id)
            )
        models = list(query.order_by("ledger_recorded_at", "assessment_id")[: limit + 1])
        entries: list[R6MonitoringAuditEntry] = []
        for model in models[:limit]:
            bundle = self._restore_bundle(model)
            assessment = bundle.assessment
            entries.append(
                R6MonitoringAuditEntry(
                    assessment_ref=bundle.assessment_ref,
                    qualification_ref=assessment.qualification_ref,
                    policy_id=assessment.requested_policy_id,
                    policy_version=assessment.requested_policy_version,
                    evaluated_at=assessment.evaluated_at,
                    recorded_at=bundle.recorded_at,
                    status=assessment.status,
                    observation_count=len(bundle.observations),
                    blockers=tuple(item.value for item in assessment.blockers),
                    retirement_review_required=assessment.retirement_review_required,
                )
            )
        next_cursor = None
        if len(models) > limit:
            last = entries[-1]
            next_cursor = _encode_cursor(
                as_of=as_of,
                recorded_at=last.recorded_at,
                assessment_id=last.assessment_ref.assessment_id,
            )
        return R6MonitoringAuditPage(tuple(entries), next_cursor)

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R6MonitoringPersistenceUnavailable("R6 monitoring as_of must be timezone-aware")
        if self.server_now() < as_of.astimezone(UTC):
            raise R6MonitoringPersistenceUnavailable("future R6 monitoring as_of is not permitted")

    def _restore_bundle(
        self,
        model: R6MonitoringAssessmentModel,
    ) -> R6MonitoringPersistedAssessment:
        try:
            policy = decode_r6_monitoring_policy(model.policy_payload)
            calendar = decode_r6_monitoring_period_calendar(model.period_calendar_payload)
            assessment = decode_r6_monitoring_assessment(model.canonical_payload)
        except R6MonitoringCodecError as error:
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring assessment owner graph payload is invalid"
            ) from error
        expected_id = r6_monitoring_assessment_id(
            qualification_ref=assessment.qualification_ref,
            expected_policy_hash=assessment.expected_policy_hash,
            evaluated_at=assessment.evaluated_at,
        )
        _aware_utc(model.ledger_recorded_at, "R6 monitoring ledger recorded_at")
        _require_exact_model_values(
            model=model,
            values=_assessment_values(
                assessment_id=expected_id,
                policy=policy,
                period_calendar=calendar,
                assessment=assessment,
                ledger_recorded_at=model.ledger_recorded_at,
            ),
            label="assessment",
        )
        if (
            policy.content_hash != assessment.expected_policy_hash
            or assessment.policy_hash != policy.content_hash
            or policy.expected_period_calendar_hash != calendar.content_hash
            or policy.expected_period_calendar_owner != calendar.source_owner
            or policy.expected_period_calendar_id != calendar.calendar_id
            or policy.expected_period_calendar_version != calendar.calendar_version
        ):
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring persisted policy/calendar binding mismatch"
            )
        if (
            model.qualification.assessment_id != assessment.qualification_ref.assessment_id
            or model.qualification.content_hash != assessment.qualification_ref.assessment_hash
            or model.qualification_id is None
        ):
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring qualification foreign-key mismatch"
            )
        observations = self._observations_for_assessment(model, assessment)
        replayed = evaluate_r6_monitoring(
            qualification_ref=assessment.qualification_ref,
            qualification_content_hash=assessment.qualification_content_hash,
            qualification_assessed_at=model.qualification.assessed_at,
            qualification_known_at=model.qualification.recorded_at,
            requested_policy_id=assessment.requested_policy_id,
            requested_policy_version=assessment.requested_policy_version,
            expected_policy_hash=assessment.expected_policy_hash,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            evaluated_at=assessment.evaluated_at,
        )
        if replayed != assessment:
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring assessment does not replay from persisted raw facts"
            )
        return R6MonitoringPersistedAssessment(
            assessment_ref=R6MonitoringAssessmentRef(
                expected_id,
                assessment.content_hash,
            ),
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            assessment=assessment,
            recorded_at=model.ledger_recorded_at,
        )

    def _observations_for_assessment(
        self,
        assessment_model: R6MonitoringAssessmentModel,
        assessment: R6MonitoringAssessment,
    ) -> tuple[R6MonitoringObservation, ...]:
        models = list(
            R6MonitoringObservationModel._default_manager.using(self._using).filter(
                content_hash__in=assessment.observation_hashes
            )
        )
        restored_by_hash: dict[str, R6MonitoringObservation] = {}
        for model in models:
            observation = self._restore_observation(model)
            if observation.content_hash in restored_by_hash:
                raise R6MonitoringPersistenceCorruption(
                    "duplicate R6 monitoring observation content seal"
                )
            if model.ledger_recorded_at > assessment_model.ledger_recorded_at:
                raise R6MonitoringPersistenceCorruption(
                    "R6 monitoring assessment predates a referenced observation"
                )
            restored_by_hash[observation.content_hash] = observation
        if set(restored_by_hash) != set(assessment.observation_hashes):
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring assessment observation graph is incomplete"
            )
        return tuple(restored_by_hash[item] for item in assessment.observation_hashes)

    def _restore_observation(
        self,
        model: R6MonitoringObservationModel,
    ) -> R6MonitoringObservation:
        try:
            observation = decode_r6_monitoring_observation(model.canonical_payload)
        except R6MonitoringCodecError as error:
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring observation payload is invalid"
            ) from error
        _aware_utc(model.ledger_recorded_at, "R6 monitoring observation ledger recorded_at")
        _require_exact_model_values(
            model=model,
            values=_observation_values(
                observation,
                ledger_recorded_at=model.ledger_recorded_at,
            ),
            label="observation",
        )
        if (
            model.qualification.assessment_id != observation.qualification_ref.assessment_id
            or model.qualification.content_hash != observation.qualification_ref.assessment_hash
        ):
            raise R6MonitoringPersistenceCorruption(
                "R6 monitoring observation qualification FK mismatch"
            )
        return observation


class _DjangoR6MonitoringStore(DjangoR6MonitoringRepository):
    """Private append capability retained by the composition root."""

    __slots__ = ("_clock", "_token")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R6MonitoringClock | None = None,
    ) -> None:
        super().__init__(using=using)
        self._clock = clock or DjangoR6MonitoringClock()
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the private append transaction/capability scope."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r6_monitoring_uow(self._token):
            yield

    def server_now(self) -> datetime:
        """Return the private store's injected authoritative clock."""

        return _aware_utc(self._clock.now(), "R6 monitoring server clock")

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6MonitoringAuditPage:
        """Return the private deterministic audit projection used by tests."""

        return self._list_audit(as_of=as_of, cursor=cursor, limit=limit)

    def append_bundle(
        self,
        *,
        policy: R6MonitoringPolicy,
        period_calendar: R6MonitoringPeriodCalendar,
        observations: tuple[R6MonitoringObservation, ...],
        assessment: R6MonitoringAssessment,
    ) -> R6MonitoringPersistedAssessment:
        """Replay and atomically append raw observations plus assessment."""

        _require_active_r6_monitoring_uow()
        recorded_at = self.server_now()
        if assessment.evaluated_at > recorded_at:
            raise R6MonitoringPersistenceUnavailable(
                "future R6 monitoring evaluation cannot be persisted"
            )
        if policy.recorded_at > assessment.evaluated_at:
            raise R6MonitoringPersistenceUnavailable(
                "R6 monitoring policy was not owner-known at the evaluation cutoff"
            )
        if period_calendar.recorded_at > assessment.evaluated_at:
            raise R6MonitoringPersistenceUnavailable(
                "R6 monitoring calendar was not owner-known at the evaluation cutoff"
            )
        if any(item.recorded_at > recorded_at for item in observations):
            raise R6MonitoringPersistenceUnavailable(
                "future owner monitoring observation cannot be persisted"
            )
        canonical_policy = decode_r6_monitoring_policy(encode_r6_monitoring_policy(policy))
        canonical_calendar = decode_r6_monitoring_period_calendar(
            encode_r6_monitoring_period_calendar(period_calendar)
        )
        canonical_observations = tuple(
            decode_r6_monitoring_observation(encode_r6_monitoring_observation(item))
            for item in observations
        )
        canonical_assessment = decode_r6_monitoring_assessment(
            encode_r6_monitoring_assessment(assessment)
        )
        qualification_model = self._qualification_model(
            canonical_assessment.qualification_ref,
            as_of=canonical_assessment.evaluated_at,
        )
        replayed = evaluate_r6_monitoring(
            qualification_ref=canonical_assessment.qualification_ref,
            qualification_content_hash=canonical_assessment.qualification_content_hash,
            qualification_assessed_at=qualification_model.assessed_at,
            qualification_known_at=qualification_model.recorded_at,
            requested_policy_id=canonical_assessment.requested_policy_id,
            requested_policy_version=canonical_assessment.requested_policy_version,
            expected_policy_hash=canonical_assessment.expected_policy_hash,
            policy=canonical_policy,
            period_calendar=canonical_calendar,
            observations=canonical_observations,
            evaluated_at=canonical_assessment.evaluated_at,
        )
        if replayed != canonical_assessment:
            raise R6MonitoringPersistenceCorruption(
                "caller monitoring assessment differs from authoritative replay"
            )
        assessment_id = r6_monitoring_assessment_id(
            qualification_ref=canonical_assessment.qualification_ref,
            expected_policy_hash=canonical_assessment.expected_policy_hash,
            evaluated_at=canonical_assessment.evaluated_at,
        )
        with transaction.atomic(using=self._using):
            for observation in canonical_observations:
                self._append_observation(
                    qualification_model=qualification_model,
                    observation=observation,
                    ledger_recorded_at=recorded_at,
                )
            return self._append_assessment(
                qualification_model=qualification_model,
                assessment_id=assessment_id,
                policy=canonical_policy,
                period_calendar=canonical_calendar,
                assessment=canonical_assessment,
                ledger_recorded_at=recorded_at,
            )

    def _qualification_model(
        self,
        ref: R6QualificationRef,
        *,
        as_of: datetime,
    ) -> R6QualificationAssessmentModel:
        models = list(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=ref.assessment_id) | Q(content_hash=ref.assessment_hash)
            )
        )
        matches = tuple(
            item
            for item in models
            if item.assessment_id == ref.assessment_id and item.content_hash == ref.assessment_hash
        )
        if len(matches) != 1 or matches[0].recorded_at > as_of:
            raise R6MonitoringPersistenceUnavailable(
                "exact persisted R6 qualification is unavailable at monitoring cutoff"
            )
        return matches[0]

    def _append_observation(
        self,
        *,
        qualification_model: R6QualificationAssessmentModel,
        observation: R6MonitoringObservation,
        ledger_recorded_at: datetime,
    ) -> R6MonitoringObservationModel:
        candidates = self._observation_collisions(observation)
        if candidates:
            exact = tuple(
                model for model in candidates if self._restore_observation(model) == observation
            )
            if len(exact) == 1:
                return exact[0]
            raise R6MonitoringPersistenceConflict(
                "R6 monitoring observation identity/period already sealed"
            )
        values = _observation_values(
            observation,
            ledger_recorded_at=ledger_recorded_at,
        )
        claim_values = {**values, "qualification_id": qualification_model.pk}
        try:
            with transaction.atomic(using=self._using):
                with _claim_r6_monitoring_insert(
                    token=self._token,
                    model_type=R6MonitoringObservationModel,
                    expected_values=claim_values,
                ):
                    return R6MonitoringObservationModel._default_manager.using(self._using).create(
                        qualification=qualification_model, **values
                    )
        except IntegrityError as error:
            winners = self._observation_collisions(observation)
            exact = tuple(
                model for model in winners if self._restore_observation(model) == observation
            )
            if len(exact) == 1:
                return exact[0]
            raise R6MonitoringPersistenceConflict(
                "R6 monitoring observation append lost an identity race"
            ) from error

    def _observation_collisions(
        self,
        observation: R6MonitoringObservation,
    ) -> tuple[R6MonitoringObservationModel, ...]:
        return tuple(
            R6MonitoringObservationModel._default_manager.using(self._using).filter(
                Q(
                    observation_id=observation.observation_id,
                    observation_version=observation.observation_version,
                )
                | Q(content_hash=observation.content_hash)
                | Q(
                    qualification_assessment_id=(observation.qualification_ref.assessment_id),
                    policy_hash=observation.policy_hash,
                    observation_period_id=observation.observation_period_id,
                )
            )
        )

    def _append_assessment(
        self,
        *,
        qualification_model: R6QualificationAssessmentModel,
        assessment_id: str,
        policy: R6MonitoringPolicy,
        period_calendar: R6MonitoringPeriodCalendar,
        assessment: R6MonitoringAssessment,
        ledger_recorded_at: datetime,
    ) -> R6MonitoringPersistedAssessment:
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
            raise R6MonitoringPersistenceConflict(
                "R6 monitoring assessment command identity already sealed"
            )
        values = _assessment_values(
            assessment_id=assessment_id,
            policy=policy,
            period_calendar=period_calendar,
            assessment=assessment,
            ledger_recorded_at=ledger_recorded_at,
        )
        claim_values = {**values, "qualification_id": qualification_model.pk}
        try:
            with transaction.atomic(using=self._using):
                with _claim_r6_monitoring_insert(
                    token=self._token,
                    model_type=R6MonitoringAssessmentModel,
                    expected_values=claim_values,
                ):
                    model = R6MonitoringAssessmentModel._default_manager.using(self._using).create(
                        qualification=qualification_model, **values
                    )
        except IntegrityError as error:
            winners = self._assessment_collisions(assessment_id, assessment)
            exact = tuple(
                self._restore_bundle(model)
                for model in winners
                if model.assessment_id == assessment_id
                and model.content_hash == assessment.content_hash
            )
            if len(exact) == 1:
                return exact[0]
            raise R6MonitoringPersistenceConflict(
                "R6 monitoring assessment append lost an identity race"
            ) from error
        return self._restore_bundle(model)

    def _assessment_collisions(
        self,
        assessment_id: str,
        assessment: R6MonitoringAssessment,
    ) -> tuple[R6MonitoringAssessmentModel, ...]:
        return tuple(
            R6MonitoringAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=assessment_id)
                | Q(content_hash=assessment.content_hash)
                | Q(
                    qualification_assessment_id=(assessment.qualification_ref.assessment_id),
                    expected_policy_hash=assessment.expected_policy_hash,
                    evaluated_at=assessment.evaluated_at,
                )
            )
        )


def _observation_values(
    observation: R6MonitoringObservation,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "qualification_assessment_id": observation.qualification_ref.assessment_id,
        "qualification_assessment_hash": observation.qualification_ref.assessment_hash,
        "policy_id": observation.policy_id,
        "policy_version": observation.policy_version,
        "policy_hash": observation.policy_hash,
        "period_calendar_id": observation.period_calendar_id,
        "period_calendar_version": observation.period_calendar_version,
        "period_calendar_hash": observation.period_calendar_hash,
        "observation_period_id": observation.observation_period_id,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "source_owner": observation.source_owner,
        "observed_at": observation.observed_at,
        "available_at": observation.available_at,
        "owner_recorded_at": observation.recorded_at,
        "valid_until": observation.valid_until,
        "pit_manifest_id": observation.pit_manifest_id,
        "pit_manifest_hash": observation.pit_manifest_hash,
        "evidence_ref": observation.evidence_ref,
        "label_protocol_version": observation.label_protocol_version,
        "observed_label_set_hash": observation.observed_label_set_hash,
        "metric_count": len(observation.metrics),
        "canonical_payload": encode_r6_monitoring_observation(observation),
        "content_hash": observation.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": observation.research_only,
        "must_not_use_for_decision": observation.must_not_use_for_decision,
        "must_not_replace_regime": observation.must_not_replace_regime,
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
    assessment_id: str,
    policy: R6MonitoringPolicy,
    period_calendar: R6MonitoringPeriodCalendar,
    assessment: R6MonitoringAssessment,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    if assessment.policy_hash is None:
        raise R6MonitoringPersistenceCorruption(
            "persisted R6 monitoring assessment requires an exact policy"
        )
    values: dict[str, object] = {
        "assessment_id": assessment_id,
        "qualification_assessment_id": assessment.qualification_ref.assessment_id,
        "qualification_assessment_hash": assessment.qualification_ref.assessment_hash,
        "requested_policy_id": assessment.requested_policy_id,
        "requested_policy_version": assessment.requested_policy_version,
        "expected_policy_hash": assessment.expected_policy_hash,
        "policy_hash": assessment.policy_hash,
        "period_calendar_id": period_calendar.calendar_id,
        "period_calendar_version": period_calendar.calendar_version,
        "period_calendar_hash": period_calendar.content_hash,
        "evaluated_at": assessment.evaluated_at,
        "ledger_recorded_at": ledger_recorded_at,
        "status": assessment.status.value,
        "observation_count": len(assessment.observation_hashes),
        "metric_result_count": len(assessment.metric_results),
        "observation_hashes": list(assessment.observation_hashes),
        "blockers": [item.value for item in assessment.blockers],
        "policy_payload": encode_r6_monitoring_policy(policy),
        "period_calendar_payload": encode_r6_monitoring_period_calendar(period_calendar),
        "canonical_payload": encode_r6_monitoring_assessment(assessment),
        "content_hash": assessment.content_hash,
        "label_drift_detected": assessment.label_drift_detected,
        "retirement_review_required": assessment.retirement_review_required,
        "automatic_retirement": assessment.automatic_retirement,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_replace_regime": assessment.must_not_replace_regime,
        "must_not_publish_current": assessment.must_not_publish_current,
        "must_not_execute": assessment.must_not_execute,
    }
    values["ledger_header_hash"] = _ledger_header_hash(
        row_kind="assessment",
        values=values,
    )
    return values


def _encode_cursor(*, as_of: datetime, recorded_at: datetime, assessment_id: str) -> str:
    payload = {
        "schema": "r6-monitoring-audit-cursor.v1",
        "as_of": _aware_utc(as_of, "R6 monitoring audit cursor as_of").isoformat(),
        "recorded_at": _aware_utc(
            recorded_at,
            "R6 monitoring audit cursor recorded_at",
        ).isoformat(),
        "assessment_id": assessment_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    as_of: datetime,
) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > 1024:
        raise ValueError("R6 monitoring audit cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw_payload = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw_payload.decode("utf-8"))
    except ValueError as error:
        raise ValueError("R6 monitoring audit cursor is invalid") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "as_of", "recorded_at", "assessment_id"}
        or payload.get("schema") != "r6-monitoring-audit-cursor.v1"
    ):
        raise ValueError("R6 monitoring audit cursor is non-canonical")
    raw_as_of = payload["as_of"]
    raw_time = payload["recorded_at"]
    assessment_id = payload["assessment_id"]
    if (
        not isinstance(raw_as_of, str)
        or not isinstance(raw_time, str)
        or not isinstance(assessment_id, str)
        or not assessment_id
        or len(assessment_id) > 192
        or any(character.isspace() for character in assessment_id)
    ):
        raise ValueError("R6 monitoring audit cursor fields are invalid")
    try:
        parsed_as_of = datetime.fromisoformat(raw_as_of)
        parsed = datetime.fromisoformat(raw_time)
    except ValueError as error:
        raise ValueError("R6 monitoring audit cursor timestamp is invalid") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.astimezone(UTC).isoformat() != raw_time
        or parsed_as_of.tzinfo is None
        or parsed_as_of.utcoffset() is None
        or parsed_as_of.astimezone(UTC).isoformat() != raw_as_of
        or parsed_as_of != as_of.astimezone(UTC)
        or _encode_cursor(
            as_of=parsed_as_of,
            recorded_at=parsed,
            assessment_id=assessment_id,
        )
        != cursor
    ):
        raise ValueError("R6 monitoring audit cursor cutoff is invalid")
    return parsed, assessment_id


__all__ = [
    "DjangoR6MonitoringClock",
    "DjangoR6MonitoringRepository",
]
