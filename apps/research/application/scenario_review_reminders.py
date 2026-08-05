"""Application orchestration for the internal-only R7 reminder ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
)
from apps.research.domain.scenario_research_evidence import ScenarioPathStudyEvidence
from apps.research.domain.scenario_review_intent import ReviewReminderIntent
from apps.research.domain.scenario_review_reminders import (
    ReminderEventType,
    ReminderLifecycleBlocked,
    ScenarioReviewReminder,
    ScenarioReviewReminderConflict,
    ScenarioReviewReminderEvent,
    ScenarioReviewReminderLedger,
    ScenarioReviewReminderSchedulePolicy,
    acknowledge_scenario_review_reminder,
    build_scenario_review_period_evidence_bindings,
    is_scenario_review_reminder_due,
    reconcile_scenario_review_reminder,
)


class ScenarioReviewReminderGateway(Protocol):
    """Persistence port for immutable reminder headers and events."""

    def save(
        self,
        reminder: ScenarioReviewReminder,
        root_event: ScenarioReviewReminderEvent,
    ) -> ScenarioReviewReminderLedger: ...

    def append_events(
        self,
        reminder_id: str,
        events: tuple[ScenarioReviewReminderEvent, ...],
    ) -> ScenarioReviewReminderLedger: ...

    def get_required(self, reminder_id: str) -> ScenarioReviewReminderLedger: ...

    def list_reconciliation_ids(
        self,
        *,
        due_before: datetime,
    ) -> tuple[str, ...]: ...


class HumanReviewActorAuthorizer(Protocol):
    """Verify an exact human-review actor artifact; no implicit owner fallback."""

    def is_authorized(
        self,
        *,
        reminder_id: str,
        owner_evidence_hash: str,
        actor_evidence_hash: str,
        as_of: datetime,
    ) -> bool:
        """Return whether the exact actor evidence may acknowledge this reminder."""


class ScheduleScenarioReviewReminderUseCase:
    """Persist one exact schedule and its deterministic root atomically."""

    def __init__(self, repository: ScenarioReviewReminderGateway) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        intent: ReviewReminderIntent,
        probability_policy: ScenarioProbabilityResearchPolicy,
        schedule_policy: ScenarioReviewReminderSchedulePolicy,
        path_evidence: ScenarioPathStudyEvidence,
        recorded_at: datetime,
    ) -> ScenarioReviewReminderLedger:
        """Schedule an internal pull reminder without delivery or decision effects."""

        if (
            probability_policy.policy_version != intent.policy_version
            or probability_policy.content_hash != intent.policy_content_hash
        ):
            raise ValueError("typed probability policy does not match review intent")
        if schedule_policy.path_horizon_periods != probability_policy.path_horizon_periods:
            raise ValueError("reminder path horizon does not match typed probability policy")
        period_bindings = build_scenario_review_period_evidence_bindings(
            intent=intent,
            schedule_policy=schedule_policy,
            path_evidence=path_evidence,
        )
        reminder = ScenarioReviewReminder.create(
            intent=intent,
            schedule_policy=schedule_policy,
            path_evidence_hash=path_evidence.content_hash,
            period_bindings=period_bindings,
        )
        root = reconcile_scenario_review_reminder(
            reminder=reminder,
            events=(),
            as_of=reminder.created_at,
            recorded_at=recorded_at,
        )
        if len(root) != 1 or root[0].event_type is not ReminderEventType.SCHEDULED:
            raise ValueError("reminder schedule did not create exactly one root event")
        return self._repository.save(reminder, root[0])


class ReconcileScenarioReviewReminderUseCase:
    """Append deterministic due/escalation/expiry occurrences only."""

    def __init__(self, repository: ScenarioReviewReminderGateway) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        reminder_id: str,
        as_of: datetime,
        recorded_at: datetime,
    ) -> ScenarioReviewReminderLedger:
        """Reconcile one internal ledger; no messages, retries, or channels exist."""

        ledger = self._repository.get_required(reminder_id)
        desired = reconcile_scenario_review_reminder(
            reminder=ledger.reminder,
            events=ledger.events,
            as_of=as_of,
            recorded_at=recorded_at,
        )
        additions = desired[len(ledger.events) :]
        if not additions:
            return ledger
        return self._repository.append_events(reminder_id, additions)


class AcknowledgeScenarioReviewReminderUseCase:
    """Append owner-authorized human acknowledgement research evidence."""

    def __init__(
        self,
        *,
        repository: ScenarioReviewReminderGateway,
        actor_authorizer: HumanReviewActorAuthorizer,
    ) -> None:
        self._repository = repository
        self._actor_authorizer = actor_authorizer

    def execute(
        self,
        *,
        reminder_id: str,
        acknowledged_at: datetime,
        recorded_at: datetime,
        actor_evidence_hash: str,
        reason_code: str,
        idempotency_key: str,
    ) -> ScenarioReviewReminderLedger:
        """Record acknowledgement only; it never approves or executes a strategy."""

        ledger = self._repository.get_required(reminder_id)
        if not self._actor_authorizer.is_authorized(
            reminder_id=reminder_id,
            owner_evidence_hash=ledger.reminder.schedule_policy.owner_evidence_hash,
            actor_evidence_hash=actor_evidence_hash,
            as_of=acknowledged_at,
        ):
            raise ReminderLifecycleBlocked(
                "scenario_review_reminder.actor.unauthorized",
                "actor evidence is not authorized for human review acknowledgement",
            )
        prior = next(
            (item for item in ledger.events if item.idempotency_key == idempotency_key),
            None,
        )
        if prior is not None:
            if (
                prior.event_type is not ReminderEventType.ACKNOWLEDGED
                or prior.occurred_at != acknowledged_at
                or prior.actor_evidence_hash != actor_evidence_hash
                or prior.reason_code != reason_code
            ):
                raise ScenarioReviewReminderConflict(
                    "acknowledgement idempotency key was reused with different evidence"
                )
            return ledger
        reconciled = ReconcileScenarioReviewReminderUseCase(self._repository).execute(
            reminder_id=reminder_id,
            as_of=acknowledged_at,
            recorded_at=recorded_at,
        )
        event = acknowledge_scenario_review_reminder(
            reminder=reconciled.reminder,
            events=reconciled.events,
            acknowledged_at=acknowledged_at,
            recorded_at=recorded_at,
            actor_evidence_hash=actor_evidence_hash,
            reason_code=reason_code,
            idempotency_key=idempotency_key,
        )
        return self._repository.append_events(reminder_id, (event,))


class PullDueScenarioReviewRemindersUseCase:
    """Return open internal-review items after deterministic reconciliation."""

    def __init__(self, repository: ScenarioReviewReminderGateway) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        as_of: datetime,
        recorded_at: datetime,
    ) -> tuple[ScenarioReviewReminderLedger, ...]:
        """Pull due evidence internally; never dispatch to any recipient or channel."""

        due: list[ScenarioReviewReminderLedger] = []
        for reminder_id in self._repository.list_reconciliation_ids(
            due_before=as_of,
        ):
            ledger = ReconcileScenarioReviewReminderUseCase(self._repository).execute(
                reminder_id=reminder_id,
                as_of=as_of,
                recorded_at=recorded_at,
            )
            if is_scenario_review_reminder_due(ledger.reminder, ledger.events, as_of):
                due.append(ledger)
        return tuple(due)


__all__ = [
    "AcknowledgeScenarioReviewReminderUseCase",
    "HumanReviewActorAuthorizer",
    "PullDueScenarioReviewRemindersUseCase",
    "ReconcileScenarioReviewReminderUseCase",
    "ScenarioReviewReminderGateway",
    "ScheduleScenarioReviewReminderUseCase",
]
