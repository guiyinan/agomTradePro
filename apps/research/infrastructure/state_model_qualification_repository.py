"""Strict append-only persistence and PIT reads for R6 qualification evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.state_model_qualification_lifecycle import (
    R6QualificationAuthorizationRef,
)
from apps.research.application.state_model_qualification_persistence import (
    R6QualificationAuditEntry,
    R6QualificationAuditPage,
    R6QualificationConflict,
    R6QualificationCorruption,
    R6QualificationUnavailable,
    r6_qualification_assessment_id,
)
from apps.research.domain.state_model_qualification import (
    StateModelQualificationAssessment,
    StateModelQualificationStatus,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationLifecycleEvent,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
    derive_r6_qualification_lifecycle_state,
)
from apps.research.infrastructure.state_model_qualification_codec import (
    R6QualificationCodecError,
    decode_r6_qualification_assessment,
    decode_r6_qualification_authorization,
    decode_r6_qualification_event,
    encode_r6_qualification_assessment,
    encode_r6_qualification_authorization,
    encode_r6_qualification_event,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
    R6QualificationLifecycleAuthorizationModel,
    R6QualificationLifecycleEventModel,
    _activate_r6_qualification_uow,
    _claim_r6_qualification_insert,
    _require_active_r6_qualification_uow,
)


class R6QualificationClock(Protocol):
    """Authoritative server clock for registration and PIT reads."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class DjangoR6QualificationClock:
    """Django timezone-backed server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R6QualificationCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _require_token(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 192:
        raise R6QualificationCorruption(f"{label} must be a bounded token")
    if any(character.isspace() for character in value):
        raise R6QualificationCorruption(f"{label} cannot contain whitespace")


class DjangoR6QualificationReadRepository:
    """Public exact/PIT reader with no clock, token, or mutation capability."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if type(using) is not str or not using.strip() or using != using.strip():
            raise ValueError("R6 qualification database alias is invalid")
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the Django database unit-of-work identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        assessment_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Restore one exact assessment only when its row was known at ``as_of``."""

        self._require_ref(assessment_ref)
        self._require_pit_cutoff(as_of)
        models = list(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=assessment_ref.assessment_id)
                | Q(content_hash=assessment_ref.assessment_hash)
            )
        )
        restored = tuple((model, self._restore_assessment(model)) for model in models)
        matches = tuple(
            pair
            for pair in restored
            if r6_qualification_assessment_id(
                study_id=pair[1].study_id,
                assessed_at=pair[1].assessed_at,
                content_hash=pair[1].content_hash,
            )
            == assessment_ref.assessment_id
            and pair[1].content_hash == assessment_ref.assessment_hash
        )
        if len(matches) > 1:
            raise R6QualificationCorruption(
                "multiple R6 qualification assessments match one exact identity"
            )
        if not matches or self._recorded_at(matches[0][0], matches[0][1]) > as_of:
            return None
        return matches[0][1]

    def get_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Replay the exact lifecycle prefix for one caller-selected identity."""

        self._require_ref(qualification_ref)
        self._require_pit_cutoff(as_of)
        assessment = self.get_exact(assessment_ref=qualification_ref, as_of=as_of)
        if (
            assessment is None
            or assessment.status is not StateModelQualificationStatus.EVIDENCE_COMPLETE
        ):
            return None
        models = tuple(
            R6QualificationLifecycleEventModel._default_manager.using(self._using)
            .select_related("assessment", "authorization")
            .filter(
                Q(assessment__assessment_id=qualification_ref.assessment_id)
                | Q(assessment__content_hash=qualification_ref.assessment_hash)
            )
            .order_by("sequence", "id")
        )
        events: list[R6QualificationLifecycleEvent] = []
        for model in models:
            event = self._restore_event(model)
            if event.qualification_ref != qualification_ref:
                raise R6QualificationCorruption("R6 lifecycle event scope/hash anchor substitution")
            events.append(event)
        if len({event.sequence for event in events}) != len(events):
            raise R6QualificationCorruption("duplicate R6 qualification lifecycle event")
        prefix = tuple(event for event in events if event.recorded_at <= as_of)
        if not prefix:
            return None
        try:
            state = derive_r6_qualification_lifecycle_state(prefix, evaluated_at=as_of)
        except ValueError as error:
            raise R6QualificationCorruption("R6 qualification lifecycle replay failed") from error
        if not state.active or state.qualification_ref != qualification_ref:
            return None
        return assessment

    @staticmethod
    def _require_ref(value: object) -> None:
        try:
            if type(value) is not R6QualificationRef:
                raise TypeError
            R6QualificationRef.__post_init__(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise R6QualificationUnavailable("R6 qualification reference is malformed") from error

    @staticmethod
    def _require_pit_cutoff(as_of: object) -> None:
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R6QualificationUnavailable("R6 qualification as_of must be timezone-aware")
        now = timezone.now()
        if _aware_utc(now, "R6 qualification server clock") < _aware_utc(
            as_of,
            "R6 qualification as_of",
        ):
            raise R6QualificationUnavailable("future R6 qualification as_of is not permitted")

    @staticmethod
    def _restore_assessment(
        model: R6QualificationAssessmentModel,
    ) -> StateModelQualificationAssessment:
        try:
            assessment = decode_r6_qualification_assessment(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification assessment payload is invalid"
            ) from error
        expected_id = r6_qualification_assessment_id(
            study_id=assessment.study_id,
            assessed_at=assessment.assessed_at,
            content_hash=assessment.content_hash,
        )
        expected_headers = (
            model.assessment_id,
            model.study_id,
            model.assessed_at,
            model.status,
            model.candidate_id,
            model.candidate_version,
            model.study_hash,
            model.preregistration_hash,
            model.baseline_shortfall_report_hash,
            model.candidate_evidence_hash,
            model.advanced_assessment_hash,
            model.pit_manifest_canonical_hash,
            model.artifact_attestation_hash,
            model.advanced_threshold_hash,
            model.derived_metric_bundle_hash,
            model.policy_hash,
            model.metric_result_count,
            model.blockers,
            model.may_request_promotion_review,
            model.promotion_decision_present,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
            model.content_hash,
        )
        actual_headers = (
            expected_id,
            assessment.study_id,
            assessment.assessed_at,
            assessment.status.value,
            assessment.candidate_id,
            assessment.candidate_version,
            assessment.study_hash,
            assessment.preregistration_hash,
            assessment.baseline_shortfall_report_hash,
            assessment.candidate_evidence_hash,
            assessment.advanced_assessment_hash,
            assessment.pit_manifest_canonical_hash,
            assessment.artifact_attestation_hash,
            assessment.advanced_threshold_hash,
            assessment.derived_metric_bundle_hash,
            assessment.policy_hash,
            len(assessment.metric_results),
            [item.value for item in assessment.blockers],
            assessment.may_request_promotion_review,
            assessment.promotion_decision_present,
            assessment.research_only,
            assessment.must_not_use_for_decision,
            assessment.must_not_replace_regime,
            assessment.content_hash,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 qualification assessment header mismatch")
        return assessment

    def _restore_authorization(
        self,
        model: R6QualificationLifecycleAuthorizationModel,
    ) -> R6QualificationPromotionAuthorization:
        try:
            authorization = decode_r6_qualification_authorization(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification authorization payload is invalid"
            ) from error
        assessment = self._restore_assessment(model.assessment)
        expected_ref = R6QualificationRef(model.assessment.assessment_id, assessment.content_hash)
        if authorization.qualification_ref != expected_ref:
            raise R6QualificationCorruption("R6 authorization assessment relation mismatch")
        expected_headers = (
            model.authorization_id,
            model.authorization_version,
            model.event_id,
            model.event_version,
            model.action,
            model.expected_sequence,
            model.owner,
            model.issued_at,
            model.recorded_at,
            model.valid_until,
            model.reason_codes,
            model.evidence_ref,
            model.content_hash,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
        )
        actual_headers = (
            authorization.authorization_id,
            authorization.authorization_version,
            authorization.event_id,
            authorization.event_version,
            authorization.action.value,
            authorization.expected_sequence,
            authorization.owner,
            authorization.issued_at,
            authorization.recorded_at,
            authorization.valid_until,
            list(authorization.reason_codes),
            authorization.evidence_ref,
            authorization.content_hash,
            authorization.research_only,
            authorization.must_not_use_for_decision,
            authorization.must_not_replace_regime,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 qualification authorization header mismatch")
        return authorization

    def _restore_event(
        self,
        model: R6QualificationLifecycleEventModel,
    ) -> R6QualificationLifecycleEvent:
        try:
            event = decode_r6_qualification_event(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification lifecycle payload is invalid"
            ) from error
        authorization = self._restore_authorization(model.authorization)
        assessment = self._restore_assessment(model.assessment)
        expected_ref = R6QualificationRef(model.assessment.assessment_id, assessment.content_hash)
        if (
            event.qualification_ref != expected_ref
            or event.authorization_hash != authorization.content_hash
            or event.authorization_id != authorization.authorization_id
            or event.authorization_version != authorization.authorization_version
        ):
            raise R6QualificationCorruption("R6 lifecycle relation substitution")
        if model.assessment_id != model.authorization.assessment_id:
            raise R6QualificationCorruption("R6 lifecycle assessment foreign-key mismatch")
        expected_headers = (
            model.event_id,
            model.event_version,
            model.action,
            model.sequence,
            model.occurred_at,
            model.recorded_at,
            model.previous_event_hash,
            model.reason_codes,
            model.content_hash,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
        )
        actual_headers = (
            event.event_id,
            event.event_version,
            event.action.value,
            event.sequence,
            event.occurred_at,
            event.recorded_at,
            event.previous_event_hash,
            list(event.reason_codes),
            event.content_hash,
            event.research_only,
            event.must_not_use_for_decision,
            event.must_not_replace_regime,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 qualification lifecycle event header mismatch")
        return event

    @staticmethod
    def _recorded_at(
        model: R6QualificationAssessmentModel,
        assessment: StateModelQualificationAssessment,
    ) -> datetime:
        if model.recorded_at.tzinfo is None or model.recorded_at.utcoffset() is None:
            raise R6QualificationCorruption("R6 qualification recorded_at is naive")
        if model.assessed_at != assessment.assessed_at:
            raise R6QualificationCorruption("R6 qualification assessed_at relation mismatch")
        return model.recorded_at


class _DjangoR6QualificationRepository:
    """Private exact/PIT repository plus lifecycle write primitives."""

    __slots__ = ("_clock", "_token", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R6QualificationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR6QualificationClock()
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the Django database unit-of-work identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Enter one repository-owned transaction and append capability scope."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r6_qualification_uow(self._token):
            yield

    def server_now(self) -> datetime:
        """Return and validate the authoritative repository clock."""

        return _aware_utc(self._clock.now(), "R6 qualification server clock")

    def get_exact(
        self,
        *,
        assessment_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Restore one exact assessment only when its row was known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        models = list(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=assessment_ref.assessment_id)
                | Q(content_hash=assessment_ref.assessment_hash)
            )
        )
        if not models:
            return None
        restored = tuple((model, self._restore_assessment(model)) for model in models)
        matches = tuple(
            pair
            for pair in restored
            if r6_qualification_assessment_id(
                study_id=pair[1].study_id,
                assessed_at=pair[1].assessed_at,
                content_hash=pair[1].content_hash,
            )
            == assessment_ref.assessment_id
            and pair[1].content_hash == assessment_ref.assessment_hash
        )
        if len(matches) > 1:
            raise R6QualificationCorruption(
                "multiple R6 qualification assessments match one exact identity"
            )
        if not matches or self._recorded_at(matches[0][0], matches[0][1]) > as_of:
            return None
        return matches[0][1]

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6QualificationAuditPage:
        """Return a deterministic PIT page with derived lifecycle state."""

        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R6 qualification audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = _decode_cursor(cursor)
        with self.atomic():
            query = R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                recorded_at__lte=as_of
            )
            if cursor_value is not None:
                cursor_at, cursor_id = cursor_value
                query = query.filter(
                    Q(recorded_at__gt=cursor_at)
                    | Q(recorded_at=cursor_at, assessment_id__gt=cursor_id)
                )
            models = list(query.order_by("recorded_at", "assessment_id")[: limit + 1])
            entries: list[R6QualificationAuditEntry] = []
            for model in models[:limit]:
                assessment = self._restore_assessment(model)
                assessment_ref = R6QualificationRef(
                    assessment_id=model.assessment_id,
                    assessment_hash=assessment.content_hash,
                )
                history = self.load_lifecycle_stream(assessment_ref=assessment_ref)
                prefix = tuple(item for item in history if item.recorded_at <= as_of)
                active = False
                head_event_hash: str | None = None
                if prefix:
                    state = derive_r6_qualification_lifecycle_state(
                        prefix,
                        evaluated_at=as_of,
                    )
                    active = state.active
                    head_event_hash = state.head_event_hash
                    if (
                        active
                        and assessment.status is not StateModelQualificationStatus.EVIDENCE_COMPLETE
                    ):
                        raise R6QualificationCorruption(
                            "blocked R6 qualification has an active lifecycle event"
                        )
                entries.append(
                    R6QualificationAuditEntry(
                        assessment_ref=assessment_ref,
                        study_id=assessment.study_id,
                        status=assessment.status,
                        assessed_at=assessment.assessed_at,
                        recorded_at=self._recorded_at(model, assessment),
                        blockers=tuple(item.value for item in assessment.blockers),
                        active=active,
                        head_event_hash=head_event_hash,
                    )
                )
            next_cursor = None
            if len(models) > limit:
                last = entries[-1]
                next_cursor = _encode_cursor(last.recorded_at, last.assessment_ref.assessment_id)
            return R6QualificationAuditPage(tuple(entries), next_cursor)

    def get_exact_authorization(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
        qualification_ref: R6QualificationRef,
        action: R6QualificationLifecycleAction,
    ) -> R6QualificationPromotionAuthorization | None:
        """Restore one persisted authorization for hybrid idempotent replay."""

        _require_active_r6_qualification_uow()
        models = list(
            R6QualificationLifecycleAuthorizationModel._default_manager.using(self._using)
            .select_related("assessment")
            .filter(
                authorization_id=authorization_ref.authorization_id,
                authorization_version=authorization_ref.authorization_version,
            )
        )
        if not models:
            return None
        matches = tuple(
            authorization
            for model in models
            for authorization in (self._restore_authorization(model),)
            if authorization.qualification_ref == qualification_ref
            and authorization.action is action
        )
        if len(matches) > 1:
            raise R6QualificationCorruption("duplicate R6 qualification authorization identity")
        return matches[0] if matches else None

    def load_lifecycle_stream(
        self,
        *,
        assessment_ref: R6QualificationRef,
    ) -> tuple[R6QualificationLifecycleEvent, ...]:
        """Restore a scope-local event stream without latest/current fallback."""

        _require_active_r6_qualification_uow()
        models = list(
            R6QualificationLifecycleEventModel._default_manager.using(self._using)
            .select_related("assessment", "authorization")
            .filter(
                Q(assessment__assessment_id=assessment_ref.assessment_id)
                | Q(assessment__content_hash=assessment_ref.assessment_hash)
            )
            .order_by("sequence", "id")
        )
        events: list[R6QualificationLifecycleEvent] = []
        for model in models:
            event = self._restore_event(model)
            if event.qualification_ref != assessment_ref:
                raise R6QualificationCorruption("R6 lifecycle event scope/hash anchor substitution")
            events.append(event)
        if len({event.sequence for event in events}) != len(events):
            raise R6QualificationCorruption("duplicate R6 qualification lifecycle event")
        return tuple(events)

    def get_event_by_authorization(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
    ) -> R6QualificationLifecycleEvent | None:
        """Return the immutable event winner for one authorization identity."""

        _require_active_r6_qualification_uow()
        models = list(
            R6QualificationLifecycleEventModel._default_manager.using(self._using)
            .select_related("assessment", "authorization")
            .filter(
                authorization__authorization_id=authorization_ref.authorization_id,
                authorization__authorization_version=authorization_ref.authorization_version,
            )
        )
        if not models:
            return None
        events = tuple(self._restore_event(model) for model in models)
        for event in events:
            if (
                event.authorization_id != authorization_ref.authorization_id
                or event.authorization_version != authorization_ref.authorization_version
            ):
                raise R6QualificationCorruption("R6 lifecycle authorization anchor substitution")
        if len(events) > 1:
            raise R6QualificationCorruption("multiple R6 events share one authorization")
        return events[0]

    def append_lifecycle_event(
        self,
        *,
        authorization: R6QualificationPromotionAuthorization,
        event: R6QualificationLifecycleEvent,
    ) -> R6QualificationLifecycleEvent:
        """Append one exact authorization/event pair transactionally."""

        _require_active_r6_qualification_uow()
        if event.authorization_hash != authorization.content_hash:
            raise R6QualificationCorruption("R6 lifecycle authorization hash substitution")
        if event.qualification_ref != authorization.qualification_ref:
            raise R6QualificationCorruption("R6 lifecycle qualification identity substitution")
        if event.action is not authorization.action:
            raise R6QualificationCorruption("R6 lifecycle action substitution")
        if (
            event.event_id != authorization.event_id
            or event.event_version != authorization.event_version
            or event.reason_codes != authorization.reason_codes
            or event.occurred_at != authorization.recorded_at
        ):
            raise R6QualificationCorruption("R6 lifecycle authorization fields substituted")
        if event.sequence != authorization.expected_sequence:
            raise R6QualificationConflict("R6 lifecycle sequence authorization is stale")
        if event.recorded_at > self.server_now():
            raise R6QualificationUnavailable("future R6 lifecycle event is not yet knowable")
        assessment_model = self._assessment_model_for_ref(authorization.qualification_ref)
        assessment = self._restore_assessment(assessment_model)
        if assessment.status is not StateModelQualificationStatus.EVIDENCE_COMPLETE:
            raise R6QualificationUnavailable(
                "only complete R6 qualification evidence may transition"
            )
        if assessment_model.recorded_at > authorization.recorded_at:
            raise R6QualificationUnavailable(
                "R6 lifecycle authorization predates qualification evidence knowledge"
            )
        if assessment_model.recorded_at > event.recorded_at:
            raise R6QualificationUnavailable(
                "R6 lifecycle event predates qualification evidence knowledge"
            )
        history = self.load_lifecycle_stream(assessment_ref=authorization.qualification_ref)
        if history:
            state = derive_r6_qualification_lifecycle_state(
                history,
                evaluated_at=event.recorded_at,
            )
            if (
                state.sequence + 1 != event.sequence
                or state.head_event_hash != event.previous_event_hash
            ):
                raise R6QualificationConflict("R6 lifecycle stream head moved")
        elif event.sequence != 1 or event.previous_event_hash is not None:
            raise R6QualificationConflict("R6 lifecycle root sequence is invalid")
        existing = self.get_event_by_authorization(
            authorization_ref=R6QualificationAuthorizationRef(
                authorization.authorization_id,
                authorization.authorization_version,
            )
        )
        if existing is not None:
            if existing != event:
                raise R6QualificationConflict("R6 lifecycle authorization winner substitution")
            return existing
        authorization_values = _authorization_values(authorization)
        event_values = _event_values(event)
        try:
            with transaction.atomic(using=self._using):
                with _claim_r6_qualification_insert(
                    token=self._token,
                    model_type=R6QualificationLifecycleAuthorizationModel,
                    expected_values={**authorization_values, "assessment_id": assessment_model.pk},
                ):
                    authorization_model = (
                        R6QualificationLifecycleAuthorizationModel._default_manager.using(
                            self._using
                        ).create(assessment=assessment_model, **authorization_values)
                    )
                with _claim_r6_qualification_insert(
                    token=self._token,
                    model_type=R6QualificationLifecycleEventModel,
                    expected_values={
                        **event_values,
                        "assessment_id": assessment_model.pk,
                        "authorization_id": authorization_model.pk,
                    },
                ):
                    R6QualificationLifecycleEventModel._default_manager.using(self._using).create(
                        assessment=assessment_model,
                        authorization=authorization_model,
                        **event_values,
                    )
        except IntegrityError as error:
            winner = self.get_event_by_authorization(
                authorization_ref=R6QualificationAuthorizationRef(
                    authorization.authorization_id,
                    authorization.authorization_version,
                )
            )
            if winner == event:
                return winner
            raise R6QualificationConflict("R6 lifecycle append lost an identity race") from error
        return event

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R6QualificationUnavailable("R6 qualification as_of must be timezone-aware")
        if _aware_utc(self.server_now(), "R6 qualification server clock") < _aware_utc(
            as_of,
            "R6 qualification as_of",
        ):
            raise R6QualificationUnavailable("future R6 qualification as_of is not permitted")

    def _assessment_model_for_ref(
        self, assessment_ref: R6QualificationRef
    ) -> R6QualificationAssessmentModel:
        models = list(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=assessment_ref.assessment_id)
                | Q(content_hash=assessment_ref.assessment_hash)
            )
        )
        matches = [
            model
            for model in models
            if model.assessment_id == assessment_ref.assessment_id
            and model.content_hash == assessment_ref.assessment_hash
        ]
        if len(matches) != 1:
            raise R6QualificationCorruption("R6 qualification assessment identity is unavailable")
        return matches[0]

    def _restore_assessment(
        self,
        model: R6QualificationAssessmentModel,
    ) -> StateModelQualificationAssessment:
        try:
            assessment = decode_r6_qualification_assessment(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification assessment payload is invalid"
            ) from error
        expected_id = r6_qualification_assessment_id(
            study_id=assessment.study_id,
            assessed_at=assessment.assessed_at,
            content_hash=assessment.content_hash,
        )
        expected_headers = (
            model.assessment_id,
            model.study_id,
            model.assessed_at,
            model.status,
            model.candidate_id,
            model.candidate_version,
            model.study_hash,
            model.preregistration_hash,
            model.baseline_shortfall_report_hash,
            model.candidate_evidence_hash,
            model.advanced_assessment_hash,
            model.pit_manifest_canonical_hash,
            model.artifact_attestation_hash,
            model.advanced_threshold_hash,
            model.derived_metric_bundle_hash,
            model.policy_hash,
            model.metric_result_count,
            model.blockers,
            model.may_request_promotion_review,
            model.promotion_decision_present,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
            model.content_hash,
        )
        actual_headers = (
            expected_id,
            assessment.study_id,
            assessment.assessed_at,
            assessment.status.value,
            assessment.candidate_id,
            assessment.candidate_version,
            assessment.study_hash,
            assessment.preregistration_hash,
            assessment.baseline_shortfall_report_hash,
            assessment.candidate_evidence_hash,
            assessment.advanced_assessment_hash,
            assessment.pit_manifest_canonical_hash,
            assessment.artifact_attestation_hash,
            assessment.advanced_threshold_hash,
            assessment.derived_metric_bundle_hash,
            assessment.policy_hash,
            len(assessment.metric_results),
            [item.value for item in assessment.blockers],
            assessment.may_request_promotion_review,
            assessment.promotion_decision_present,
            assessment.research_only,
            assessment.must_not_use_for_decision,
            assessment.must_not_replace_regime,
            assessment.content_hash,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 qualification assessment header mismatch")
        return assessment

    def _restore_authorization(
        self,
        model: R6QualificationLifecycleAuthorizationModel,
    ) -> R6QualificationPromotionAuthorization:
        try:
            authorization = decode_r6_qualification_authorization(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification authorization payload is invalid"
            ) from error
        assessment = self._restore_assessment(model.assessment)
        expected_ref = R6QualificationRef(model.assessment.assessment_id, assessment.content_hash)
        if authorization.qualification_ref != expected_ref:
            raise R6QualificationCorruption("R6 authorization assessment relation mismatch")
        expected_headers = (
            model.authorization_id,
            model.authorization_version,
            model.event_id,
            model.event_version,
            model.action,
            model.expected_sequence,
            model.owner,
            model.issued_at,
            model.recorded_at,
            model.valid_until,
            model.reason_codes,
            model.evidence_ref,
            model.content_hash,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
        )
        actual_headers = (
            authorization.authorization_id,
            authorization.authorization_version,
            authorization.event_id,
            authorization.event_version,
            authorization.action.value,
            authorization.expected_sequence,
            authorization.owner,
            authorization.issued_at,
            authorization.recorded_at,
            authorization.valid_until,
            list(authorization.reason_codes),
            authorization.evidence_ref,
            authorization.content_hash,
            authorization.research_only,
            authorization.must_not_use_for_decision,
            authorization.must_not_replace_regime,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 qualification authorization header mismatch")
        return authorization

    def _restore_event(
        self,
        model: R6QualificationLifecycleEventModel,
    ) -> R6QualificationLifecycleEvent:
        try:
            event = decode_r6_qualification_event(model.canonical_payload)
        except R6QualificationCodecError as error:
            raise R6QualificationCorruption(
                "R6 qualification lifecycle payload is invalid"
            ) from error
        authorization = self._restore_authorization(model.authorization)
        assessment = self._restore_assessment(model.assessment)
        expected_ref = R6QualificationRef(model.assessment.assessment_id, assessment.content_hash)
        if (
            event.qualification_ref != expected_ref
            or event.authorization_hash != authorization.content_hash
            or event.authorization_id != authorization.authorization_id
            or event.authorization_version != authorization.authorization_version
        ):
            raise R6QualificationCorruption("R6 lifecycle relation substitution")
        if model.assessment_id != model.authorization.assessment_id:
            raise R6QualificationCorruption("R6 lifecycle assessment foreign-key mismatch")
        expected_headers = (
            model.event_id,
            model.event_version,
            model.action,
            model.sequence,
            model.occurred_at,
            model.recorded_at,
            model.previous_event_hash,
            model.reason_codes,
            model.content_hash,
            model.research_only,
            model.must_not_use_for_decision,
            model.must_not_replace_regime,
        )
        actual_headers = (
            event.event_id,
            event.event_version,
            event.action.value,
            event.sequence,
            event.occurred_at,
            event.recorded_at,
            event.previous_event_hash,
            list(event.reason_codes),
            event.content_hash,
            event.research_only,
            event.must_not_use_for_decision,
            event.must_not_replace_regime,
        )
        if expected_headers != actual_headers:
            raise R6QualificationCorruption("R6 lifecycle event header mismatch")
        return event

    def _recorded_at(
        self,
        model: R6QualificationAssessmentModel,
        assessment: StateModelQualificationAssessment,
    ) -> datetime:
        if model.recorded_at.tzinfo is None or model.recorded_at.utcoffset() is None:
            raise R6QualificationCorruption("R6 qualification recorded_at is naive")
        if model.assessed_at != assessment.assessed_at:
            raise R6QualificationCorruption("R6 qualification assessed_at relation mismatch")
        return model.recorded_at


class _DjangoR6QualificationStore(_DjangoR6QualificationRepository):
    """Private append capability retained by the composition root."""

    def append_assessment(
        self,
        assessment: StateModelQualificationAssessment,
    ) -> StateModelQualificationAssessment:
        """Append one canonical assessment using the repository server clock."""

        _require_active_r6_qualification_uow()
        recorded_at = self.server_now()
        if assessment.assessed_at > recorded_at:
            raise R6QualificationUnavailable("R6 qualification assessed_at is in the future")
        assessment_id = r6_qualification_assessment_id(
            study_id=assessment.study_id,
            assessed_at=assessment.assessed_at,
            content_hash=assessment.content_hash,
        )
        candidates = list(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=assessment_id) | Q(content_hash=assessment.content_hash)
            )
        )
        if candidates:
            records = tuple(self._restore_assessment(model) for model in candidates)
            matches = tuple(
                record
                for record in records
                if record == assessment
                and r6_qualification_assessment_id(
                    study_id=record.study_id,
                    assessed_at=record.assessed_at,
                    content_hash=record.content_hash,
                )
                == assessment_id
            )
            if len(matches) == 1:
                return matches[0]
            raise R6QualificationConflict("R6 qualification assessment identity already sealed")
        values = _assessment_values(
            assessment, assessment_id=assessment_id, recorded_at=recorded_at
        )
        try:
            with transaction.atomic(using=self._using):
                with _claim_r6_qualification_insert(
                    token=self._token,
                    model_type=R6QualificationAssessmentModel,
                    expected_values=values,
                ):
                    R6QualificationAssessmentModel._default_manager.using(self._using).create(
                        **values
                    )
        except IntegrityError as error:
            winner = self.get_exact(
                assessment_ref=R6QualificationRef(assessment_id, assessment.content_hash),
                as_of=self.server_now(),
            )
            if winner == assessment:
                return winner
            raise R6QualificationConflict(
                "R6 qualification append lost an identity race"
            ) from error
        return assessment


def _assessment_values(
    assessment: StateModelQualificationAssessment,
    *,
    assessment_id: str,
    recorded_at: datetime,
) -> dict[str, object]:
    return {
        "assessment_id": assessment_id,
        "study_id": assessment.study_id,
        "assessed_at": assessment.assessed_at,
        "recorded_at": recorded_at,
        "status": assessment.status.value,
        "candidate_id": assessment.candidate_id,
        "candidate_version": assessment.candidate_version,
        "study_hash": assessment.study_hash,
        "preregistration_hash": assessment.preregistration_hash,
        "baseline_shortfall_report_hash": assessment.baseline_shortfall_report_hash,
        "candidate_evidence_hash": assessment.candidate_evidence_hash,
        "advanced_assessment_hash": assessment.advanced_assessment_hash,
        "pit_manifest_canonical_hash": assessment.pit_manifest_canonical_hash,
        "artifact_attestation_hash": assessment.artifact_attestation_hash,
        "advanced_threshold_hash": assessment.advanced_threshold_hash,
        "derived_metric_bundle_hash": assessment.derived_metric_bundle_hash,
        "policy_hash": assessment.policy_hash,
        "metric_result_count": len(assessment.metric_results),
        "blockers": [item.value for item in assessment.blockers],
        "canonical_payload": encode_r6_qualification_assessment(assessment),
        "content_hash": assessment.content_hash,
        "may_request_promotion_review": assessment.may_request_promotion_review,
        "promotion_decision_present": assessment.promotion_decision_present,
        "research_only": assessment.research_only,
        "must_not_use_for_decision": assessment.must_not_use_for_decision,
        "must_not_replace_regime": assessment.must_not_replace_regime,
    }


def _authorization_values(
    authorization: R6QualificationPromotionAuthorization,
) -> dict[str, object]:
    return {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "expected_sequence": authorization.expected_sequence,
        "owner": authorization.owner,
        "issued_at": authorization.issued_at,
        "recorded_at": authorization.recorded_at,
        "valid_until": authorization.valid_until,
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        "canonical_payload": encode_r6_qualification_authorization(authorization),
        "content_hash": authorization.content_hash,
        "research_only": authorization.research_only,
        "must_not_use_for_decision": authorization.must_not_use_for_decision,
        "must_not_replace_regime": authorization.must_not_replace_regime,
    }


def _event_values(event: R6QualificationLifecycleEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "action": event.action.value,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash,
        "reason_codes": list(event.reason_codes),
        "canonical_payload": encode_r6_qualification_event(event),
        "content_hash": event.content_hash,
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_replace_regime": event.must_not_replace_regime,
    }


def _encode_cursor(recorded_at: datetime, assessment_id: str) -> str:
    return f"{recorded_at.astimezone(UTC).isoformat()}|{assessment_id}"


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or cursor.count("|") != 1:
        raise ValueError("R6 qualification audit cursor is invalid")
    raw_time, assessment_id = cursor.split("|", 1)
    try:
        parsed = datetime.fromisoformat(raw_time)
    except ValueError as error:
        raise ValueError("R6 qualification audit cursor timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("R6 qualification audit cursor timestamp must be aware")
    _require_token(assessment_id, "R6 qualification audit cursor assessment_id")
    canonical = parsed.astimezone(UTC).isoformat()
    if canonical != raw_time:
        raise ValueError("R6 qualification audit cursor timestamp is non-canonical")
    return parsed, assessment_id


__all__ = [
    "DjangoR6QualificationClock",
    "DjangoR6QualificationReadRepository",
    "R6QualificationClock",
    "_DjangoR6QualificationStore",
]
