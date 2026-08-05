"""Transactional persistence for the append-only R7 review reminder ledger."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.research.domain.scenario_review_intent import ReviewReminderIntent
from apps.research.domain.scenario_review_reminders import (
    ReminderEventType,
    ScenarioReviewPeriodEvidenceBinding,
    ScenarioReviewReminder,
    ScenarioReviewReminderConflict,
    ScenarioReviewReminderEvent,
    ScenarioReviewReminderLedger,
    ScenarioReviewReminderSchedulePolicy,
    derive_scenario_review_reminder_state,
)
from apps.research.infrastructure.scenario_review_reminder_models import (
    ScenarioReviewReminderEventModel,
    ScenarioReviewReminderModel,
)


class ScenarioReviewReminderRepository:
    """Insert exact reminder evidence idempotently under row/unique locks."""

    @transaction.atomic
    def save(
        self,
        reminder: ScenarioReviewReminder,
        root_event: ScenarioReviewReminderEvent,
    ) -> ScenarioReviewReminderLedger:
        """Insert one header and root atomically or replay an identical winner."""

        derive_scenario_review_reminder_state(reminder, (root_event,))
        existing = (
            ScenarioReviewReminderModel._default_manager.select_for_update()
            .filter(reminder_id=reminder.reminder_id)
            .first()
        )
        if existing is not None:
            ledger = self._ledger_from_model(existing, for_update=True)
            self._require_same_reminder(ledger.reminder, reminder)
            return self.append_events(reminder.reminder_id, (root_event,))
        try:
            with transaction.atomic():
                model = ScenarioReviewReminderModel._default_manager.create(
                    **_reminder_values(reminder)
                )
                ScenarioReviewReminderEventModel._default_manager.create(
                    reminder=model,
                    **_event_values(root_event),
                )
        except (IntegrityError, ValidationError) as exc:
            winner = (
                ScenarioReviewReminderModel._default_manager.select_for_update()
                .filter(
                    Q(reminder_id=reminder.reminder_id)
                    | Q(intent_id=reminder.intent.intent_id)
                    | Q(content_hash=reminder.content_hash)
                )
                .first()
            )
            if winner is None:
                raise
            if winner.reminder_id != reminder.reminder_id:
                raise ScenarioReviewReminderConflict(
                    "review intent identity was reused by different reminder evidence"
                ) from exc
            ledger = self._ledger_from_model(winner, for_update=True)
            self._require_same_reminder(ledger.reminder, reminder)
            return self.append_events(reminder.reminder_id, (root_event,))
        return self.get_required(reminder.reminder_id)

    @transaction.atomic
    def append_events(
        self,
        reminder_id: str,
        events: tuple[ScenarioReviewReminderEvent, ...],
    ) -> ScenarioReviewReminderLedger:
        """Append events in sequence with scoped idempotency replay and conflict checks."""

        model = ScenarioReviewReminderModel._default_manager.select_for_update().get(
            reminder_id=reminder_id
        )
        ledger = self._ledger_from_model(model, for_update=True)
        history = list(ledger.events)
        by_key = {item.idempotency_key: item for item in history}
        for event in events:
            if event.reminder_id != reminder_id:
                raise ValueError("event reminder identity mismatch")
            prior = by_key.get(event.idempotency_key)
            if prior is not None:
                _require_same_event_request(prior, event)
                continue
            candidate_history = (*history, event)
            try:
                derive_scenario_review_reminder_state(ledger.reminder, candidate_history)
            except ValueError as exc:
                raise ScenarioReviewReminderConflict(
                    "reminder lifecycle changed before the event could be appended"
                ) from exc
            try:
                with transaction.atomic():
                    ScenarioReviewReminderEventModel._default_manager.create(
                        reminder=model,
                        **_event_values(event),
                    )
            except (IntegrityError, ValidationError) as exc:
                winner_model = (
                    ScenarioReviewReminderEventModel._default_manager.select_for_update()
                    .filter(reminder=model, idempotency_key=event.idempotency_key)
                    .first()
                )
                if winner_model is None:
                    raise
                winner = _event_from_model(winner_model)
                _require_same_event_request(winner, event)
                if winner.sequence != len(history) + 1:
                    raise ScenarioReviewReminderConflict(
                        "concurrent reminder event won a different sequence"
                    ) from exc
                event = winner
            history.append(event)
            by_key[event.idempotency_key] = event
        return ScenarioReviewReminderLedger(ledger.reminder, tuple(history))

    def get(self, reminder_id: str) -> ScenarioReviewReminderLedger | None:
        """Read and validate one complete header/hash chain."""

        model = ScenarioReviewReminderModel._default_manager.filter(reminder_id=reminder_id).first()
        return None if model is None else self._ledger_from_model(model, for_update=False)

    def get_required(self, reminder_id: str) -> ScenarioReviewReminderLedger:
        """Return one ledger or raise the model's stable not-found exception."""

        model = ScenarioReviewReminderModel._default_manager.get(reminder_id=reminder_id)
        return self._ledger_from_model(model, for_update=False)

    def list_reconciliation_ids(
        self,
        *,
        due_before: datetime,
    ) -> tuple[str, ...]:
        """Return every due header so persisted terminal evidence is validated."""

        if due_before.tzinfo is None or due_before.utcoffset() is None:
            raise ValueError("due_before must be timezone-aware")

        return tuple(
            ScenarioReviewReminderModel._default_manager.filter(
                due_at__lte=due_before,
            )
            .order_by("due_at", "reminder_id")
            .values_list("reminder_id", flat=True)
            .distinct()
        )

    def _ledger_from_model(
        self,
        model: ScenarioReviewReminderModel,
        *,
        for_update: bool,
    ) -> ScenarioReviewReminderLedger:
        reminder = _reminder_from_model(model)
        queryset = ScenarioReviewReminderEventModel._default_manager.filter(
            reminder=model
        ).order_by("sequence")
        if for_update:
            queryset = queryset.select_for_update()
        events = tuple(_event_from_model(item) for item in queryset)
        return ScenarioReviewReminderLedger(reminder, events)

    @staticmethod
    def _require_same_reminder(
        existing: ScenarioReviewReminder,
        requested: ScenarioReviewReminder,
    ) -> None:
        if existing != requested:
            raise ScenarioReviewReminderConflict(
                "reminder identity was reused with different immutable evidence"
            )


def _reminder_values(reminder: ScenarioReviewReminder) -> dict[str, object]:
    intent = reminder.intent
    policy = reminder.schedule_policy
    return {
        "reminder_id": reminder.reminder_id,
        "reminder_version": reminder.reminder_version,
        "intent_id": intent.intent_id,
        "intent_version": intent.intent_version,
        "intent_content_hash": intent.content_hash,
        "forecast_entry_id": intent.forecast_entry_id,
        "forecast_group_id": intent.forecast_group_id,
        "forecast_observation_hash": intent.forecast_observation_hash,
        "probability_policy_version": intent.policy_version,
        "probability_policy_hash": intent.policy_content_hash,
        "scenario_revision_id": intent.scenario_revision_id,
        "scenario_set_revision_id": intent.scenario_set_revision_id,
        "invalidation_evidence_hash": intent.invalidation_evidence_hash,
        "intent_reason_code": intent.reason_code,
        "schedule_version": policy.schedule_version,
        "schedule_policy_hash": policy.content_hash,
        "expiry_delay": policy.expiry_delay,
        "escalation_delay": policy.escalation_delay,
        "maximum_escalation_level": policy.maximum_escalation_level,
        "path_horizon_periods": policy.path_horizon_periods,
        "owner_evidence_hash": policy.owner_evidence_hash,
        "escalation_policy_version": policy.escalation_policy_version,
        "escalation_policy_hash": policy.escalation_policy_hash,
        "path_evidence_hash": reminder.path_evidence_hash,
        "period_bindings": [_period_values(item) for item in reminder.period_bindings],
        "created_at": reminder.created_at,
        "due_at": reminder.due_at,
        "expires_at": reminder.expires_at,
        "delivery_scope": reminder.delivery_scope,
        "must_not_execute": reminder.must_not_execute,
        "external_dispatch_requested": reminder.external_dispatch_requested,
        "auto_approval_requested": reminder.auto_approval_requested,
        "research_only": reminder.research_only,
        "must_not_use_for_decision": reminder.must_not_use_for_decision,
        "content_hash": reminder.content_hash,
    }


def _event_values(event: ScenarioReviewReminderEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "escalation_level": event.escalation_level,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "actor_evidence_hash": event.actor_evidence_hash,
        "reason_code": event.reason_code,
        "idempotency_key": event.idempotency_key,
        "previous_event_hash": event.previous_event_hash,
        "delivery_scope": event.delivery_scope,
        "must_not_execute": event.must_not_execute,
        "external_dispatch_requested": event.external_dispatch_requested,
        "auto_approval_requested": event.auto_approval_requested,
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "content_hash": event.content_hash,
        "record_hash": event.record_hash,
    }


def _period_values(binding: ScenarioReviewPeriodEvidenceBinding) -> dict[str, object]:
    return {
        "period_index": binding.period_index,
        "conditional_probability_identity_hashes": list(
            binding.conditional_probability_identity_hashes
        ),
        "transition_probability_identity_hashes": list(
            binding.transition_probability_identity_hashes
        ),
        "content_hash": binding.content_hash,
    }


def _reminder_from_model(model: ScenarioReviewReminderModel) -> ScenarioReviewReminder:
    raw_period_payload = model.period_bindings
    if not isinstance(raw_period_payload, list) or any(
        not isinstance(item, Mapping) for item in raw_period_payload
    ):
        raise ValueError("persisted reminder period_bindings must be a list of objects")
    period_payload = cast(list[Mapping[str, object]], raw_period_payload)
    bindings = tuple(_period_from_values(item) for item in period_payload)
    intent = ReviewReminderIntent(
        intent_version=model.intent_version,
        intent_id=model.intent_id,
        forecast_entry_id=model.forecast_entry_id,
        forecast_group_id=model.forecast_group_id,
        forecast_observation_hash=model.forecast_observation_hash,
        policy_version=model.probability_policy_version,
        policy_content_hash=model.probability_policy_hash,
        scenario_revision_id=model.scenario_revision_id,
        scenario_set_revision_id=model.scenario_set_revision_id,
        invalidation_evidence_hash=model.invalidation_evidence_hash,
        created_at=model.created_at,
        review_due_at=model.due_at,
        reason_code=model.intent_reason_code,
        delivery_scope=model.delivery_scope,
        must_not_execute=model.must_not_execute,
        external_dispatch_requested=model.external_dispatch_requested,
        content_hash=model.intent_content_hash,
    )
    policy = ScenarioReviewReminderSchedulePolicy(
        schedule_version=model.schedule_version,
        probability_policy_version=model.probability_policy_version,
        probability_policy_hash=model.probability_policy_hash,
        expiry_delay=model.expiry_delay,
        escalation_delay=model.escalation_delay,
        maximum_escalation_level=model.maximum_escalation_level,
        path_horizon_periods=model.path_horizon_periods,
        owner_evidence_hash=model.owner_evidence_hash,
        escalation_policy_version=model.escalation_policy_version,
        escalation_policy_hash=model.escalation_policy_hash,
        content_hash=model.schedule_policy_hash,
    )
    return ScenarioReviewReminder(
        reminder_version=model.reminder_version,
        reminder_id=model.reminder_id,
        intent=intent,
        schedule_policy=policy,
        path_evidence_hash=model.path_evidence_hash,
        period_bindings=bindings,
        created_at=model.created_at,
        due_at=model.due_at,
        expires_at=model.expires_at,
        delivery_scope=model.delivery_scope,
        must_not_execute=model.must_not_execute,
        external_dispatch_requested=model.external_dispatch_requested,
        auto_approval_requested=model.auto_approval_requested,
        research_only=model.research_only,
        must_not_use_for_decision=model.must_not_use_for_decision,
        content_hash=model.content_hash,
    )


def _period_from_values(payload: Mapping[str, object]) -> ScenarioReviewPeriodEvidenceBinding:
    expected_keys = {
        "period_index",
        "conditional_probability_identity_hashes",
        "transition_probability_identity_hashes",
        "content_hash",
    }
    if set(payload) != expected_keys:
        raise ValueError("persisted reminder period binding keys are not exact")
    conditional = _string_tuple(
        payload.get("conditional_probability_identity_hashes"),
        "conditional_probability_identity_hashes",
    )
    transitions = _string_tuple(
        payload.get("transition_probability_identity_hashes"),
        "transition_probability_identity_hashes",
    )
    period_index = payload.get("period_index")
    content_hash = payload.get("content_hash")
    if isinstance(period_index, bool) or not isinstance(period_index, int):
        raise ValueError("persisted reminder period_index is invalid")
    if not isinstance(content_hash, str):
        raise ValueError("persisted reminder period content_hash is invalid")
    return ScenarioReviewPeriodEvidenceBinding(
        period_index=period_index,
        conditional_probability_identity_hashes=conditional,
        transition_probability_identity_hashes=transitions,
        content_hash=content_hash,
    )


def _event_from_model(model: ScenarioReviewReminderEventModel) -> ScenarioReviewReminderEvent:
    return ScenarioReviewReminderEvent(
        event_version=model.event_version,
        event_id=model.event_id,
        reminder_id=model.reminder_id,
        event_type=ReminderEventType(model.event_type),
        sequence=model.sequence,
        escalation_level=model.escalation_level,
        occurred_at=model.occurred_at,
        recorded_at=model.recorded_at,
        actor_evidence_hash=model.actor_evidence_hash,
        reason_code=model.reason_code,
        idempotency_key=model.idempotency_key,
        previous_event_hash=model.previous_event_hash or None,
        delivery_scope=model.delivery_scope,
        must_not_execute=model.must_not_execute,
        external_dispatch_requested=model.external_dispatch_requested,
        auto_approval_requested=model.auto_approval_requested,
        research_only=model.research_only,
        must_not_use_for_decision=model.must_not_use_for_decision,
        content_hash=model.content_hash,
        record_hash=model.record_hash,
    )


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"persisted reminder {field_name} is invalid")
    return tuple(cast(list[str], value))


def _require_same_event_request(
    existing: ScenarioReviewReminderEvent,
    requested: ScenarioReviewReminderEvent,
) -> None:
    if (
        existing.event_id != requested.event_id
        or existing.content_hash != requested.content_hash
        or existing.event_type is not requested.event_type
        or existing.occurred_at != requested.occurred_at
        or existing.actor_evidence_hash != requested.actor_evidence_hash
        or existing.reason_code != requested.reason_code
    ):
        raise ScenarioReviewReminderConflict(
            "reminder event idempotency key was reused with different evidence"
        )


__all__ = ["ScenarioReviewReminderRepository"]
