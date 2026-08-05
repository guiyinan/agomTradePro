"""Component coverage for the internal-only R7 review reminder ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import QuerySet

from apps.research.application.scenario_review_reminders import (
    AcknowledgeScenarioReviewReminderUseCase,
    PullDueScenarioReviewRemindersUseCase,
    ReconcileScenarioReviewReminderUseCase,
    ScheduleScenarioReviewReminderUseCase,
)
from apps.research.domain.scenario_review_reminders import (
    ReminderEventType,
    ReminderLifecycleBlocked,
    ReminderLifecycleState,
    ScenarioReviewReminderConflict,
    ScenarioReviewReminderLedger,
    ScenarioReviewReminderSchedulePolicy,
    acknowledge_scenario_review_reminder,
    derive_scenario_review_reminder_state,
    reconcile_scenario_review_reminder,
)
from apps.research.infrastructure.scenario_review_reminder_models import (
    ScenarioReviewReminderEventModel,
    ScenarioReviewReminderModel,
)
from apps.research.infrastructure.scenario_review_reminder_repository import (
    ScenarioReviewReminderRepository,
)
from tests.unit.research.scenario_review_reminder_factories import (
    NOW,
    make_path_study,
    make_policy,
    make_review_intent,
)


def _schedule_policy() -> ScenarioReviewReminderSchedulePolicy:
    return ScenarioReviewReminderSchedulePolicy.from_probability_policy(
        probability_policy=make_policy(),
        schedule_version="scenario-review-schedule.v1",
        expiry_delay=timedelta(days=5),
        escalation_delay=timedelta(days=1),
        maximum_escalation_level=2,
        path_horizon_periods=2,
        owner_evidence_hash="b" * 64,
        escalation_policy_version="scenario-escalation.v1",
        escalation_policy_hash="c" * 64,
    )


def _schedule(
    repository: ScenarioReviewReminderRepository,
) -> tuple[ScheduleScenarioReviewReminderUseCase, ScenarioReviewReminderLedger]:
    use_case = ScheduleScenarioReviewReminderUseCase(repository)
    ledger = use_case.execute(
        intent=make_review_intent(),
        probability_policy=make_policy(),
        schedule_policy=_schedule_policy(),
        path_evidence=make_path_study(),
        recorded_at=NOW,
    )
    return use_case, ledger


class _OwnerAuthorizer:
    def __init__(self, *, allowed_actor_hash: str) -> None:
        self.allowed_actor_hash = allowed_actor_hash
        self.calls: list[tuple[str, str, str, datetime]] = []

    def is_authorized(
        self,
        *,
        reminder_id: str,
        owner_evidence_hash: str,
        actor_evidence_hash: str,
        as_of: datetime,
    ) -> bool:
        self.calls.append((reminder_id, owner_evidence_hash, actor_evidence_hash, as_of))
        return owner_evidence_hash == "b" * 64 and actor_evidence_hash == self.allowed_actor_hash


@pytest.mark.django_db
def test_schedule_reconcile_pull_ack_and_idempotent_replay_are_internal_only() -> None:
    repository = ScenarioReviewReminderRepository()
    use_case, scheduled = _schedule(repository)
    reminder_id = scheduled.reminder.reminder_id

    replay = use_case.execute(
        intent=make_review_intent(),
        probability_policy=make_policy(),
        schedule_policy=_schedule_policy(),
        path_evidence=make_path_study(),
        recorded_at=NOW,
    )
    assert replay.reminder.reminder_id == reminder_id
    assert ScenarioReviewReminderModel._default_manager.count() == 1
    assert ScenarioReviewReminderEventModel._default_manager.count() == 1

    due_at = replay.reminder.due_at
    due = PullDueScenarioReviewRemindersUseCase(repository).execute(
        as_of=due_at,
        recorded_at=due_at,
    )
    assert len(due) == 1
    assert due[0].events[-1].event_type is ReminderEventType.DUE

    actor_hash = "9" * 64
    authorizer = _OwnerAuthorizer(allowed_actor_hash=actor_hash)
    acknowledge = AcknowledgeScenarioReviewReminderUseCase(
        repository=repository,
        actor_authorizer=authorizer,
    )
    acknowledged_at = due_at + timedelta(hours=1)
    result = acknowledge.execute(
        reminder_id=reminder_id,
        acknowledged_at=acknowledged_at,
        recorded_at=acknowledged_at,
        actor_evidence_hash=actor_hash,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-request-1",
    )
    replay_ack = acknowledge.execute(
        reminder_id=reminder_id,
        acknowledged_at=acknowledged_at,
        recorded_at=acknowledged_at + timedelta(hours=2),
        actor_evidence_hash=actor_hash,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-request-1",
    )

    assert result == replay_ack
    assert authorizer.calls[-1] == (
        reminder_id,
        "b" * 64,
        actor_hash,
        acknowledged_at,
    )
    assert (
        derive_scenario_review_reminder_state(result.reminder, result.events)
        is ReminderLifecycleState.ACKNOWLEDGED
    )
    assert all(item.external_dispatch_requested is False for item in result.events)
    assert all(item.must_not_execute is True for item in result.events)
    assert all(item.must_not_use_for_decision is True for item in result.events)
    assert (
        PullDueScenarioReviewRemindersUseCase(repository).execute(
            as_of=due_at + timedelta(days=1),
            recorded_at=due_at + timedelta(days=1),
        )
        == ()
    )
    with pytest.raises(ScenarioReviewReminderConflict):
        acknowledge.execute(
            reminder_id=reminder_id,
            acknowledged_at=acknowledged_at,
            recorded_at=acknowledged_at,
            actor_evidence_hash=actor_hash,
            reason_code="human_review.changed",
            idempotency_key="ack-request-1",
        )


@pytest.mark.django_db
def test_wrong_actor_is_blocked_before_any_lifecycle_append() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    before = ScenarioReviewReminderEventModel._default_manager.count()
    use_case = AcknowledgeScenarioReviewReminderUseCase(
        repository=repository,
        actor_authorizer=_OwnerAuthorizer(allowed_actor_hash="9" * 64),
    )

    with pytest.raises(ReminderLifecycleBlocked) as exc_info:
        use_case.execute(
            reminder_id=ledger.reminder.reminder_id,
            acknowledged_at=ledger.reminder.due_at,
            recorded_at=ledger.reminder.due_at,
            actor_evidence_hash="8" * 64,
            reason_code="human_review.acknowledged",
            idempotency_key="wrong-actor",
        )

    assert exc_info.value.reason_code == "scenario_review_reminder.actor.unauthorized"
    assert ScenarioReviewReminderEventModel._default_manager.count() == before


@pytest.mark.django_db
def test_pull_at_exact_expiry_reconciles_expired_but_returns_no_due_item() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)

    pulled = PullDueScenarioReviewRemindersUseCase(repository).execute(
        as_of=ledger.reminder.expires_at,
        recorded_at=ledger.reminder.expires_at,
    )
    persisted = repository.get_required(ledger.reminder.reminder_id)

    assert pulled == ()
    assert persisted.events[-1].event_type is ReminderEventType.EXPIRED
    assert persisted.events[-1].occurred_at == ledger.reminder.expires_at


@pytest.mark.django_db
def test_stale_ack_loses_to_concurrent_expiry_with_stable_conflict() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    due = ReconcileScenarioReviewReminderUseCase(repository).execute(
        reminder_id=ledger.reminder.reminder_id,
        as_of=ledger.reminder.due_at,
        recorded_at=ledger.reminder.due_at,
    )
    stale_ack = acknowledge_scenario_review_reminder(
        reminder=due.reminder,
        events=due.events,
        acknowledged_at=due.reminder.due_at + timedelta(hours=1),
        recorded_at=due.reminder.due_at + timedelta(hours=1),
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="stale-ack",
    )
    expired = ReconcileScenarioReviewReminderUseCase(repository).execute(
        reminder_id=ledger.reminder.reminder_id,
        as_of=ledger.reminder.expires_at,
        recorded_at=ledger.reminder.expires_at,
    )

    with pytest.raises(ScenarioReviewReminderConflict):
        repository.append_events(ledger.reminder.reminder_id, (stale_ack,))
    persisted = repository.get_required(ledger.reminder.reminder_id)
    assert persisted == expired
    assert (
        sum(
            item.event_type in {ReminderEventType.ACKNOWLEDGED, ReminderEventType.EXPIRED}
            for item in persisted.events
        )
        == 1
    )


@pytest.mark.django_db
def test_repository_rolls_back_header_when_root_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ScenarioReviewReminderRepository()

    def fail_create(**_kwargs: object) -> object:
        raise RuntimeError("root insert failed")

    monkeypatch.setattr(
        ScenarioReviewReminderEventModel._default_manager,
        "create",
        fail_create,
    )
    with pytest.raises(RuntimeError, match="root insert failed"):
        _schedule(repository)
    assert ScenarioReviewReminderModel._default_manager.count() == 0
    assert ScenarioReviewReminderEventModel._default_manager.count() == 0


def _force_first_header_lookup_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ScenarioReviewReminderModel._default_manager
    original = manager.select_for_update
    first_call = True

    def select_for_update(
        *args: object,
        **kwargs: object,
    ) -> QuerySet[ScenarioReviewReminderModel]:
        nonlocal first_call
        queryset = original(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    monkeypatch.setattr(manager, "select_for_update", select_for_update)


@pytest.mark.django_db
def test_concurrent_unique_winner_replays_identical_and_rejects_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ScenarioReviewReminderRepository()
    use_case, first = _schedule(repository)
    _force_first_header_lookup_miss(monkeypatch)

    replay = use_case.execute(
        intent=make_review_intent(),
        probability_policy=make_policy(),
        schedule_policy=_schedule_policy(),
        path_evidence=make_path_study(),
        recorded_at=NOW,
    )
    assert replay == first
    assert ScenarioReviewReminderModel._default_manager.count() == 1

    with pytest.raises(ScenarioReviewReminderConflict):
        use_case.execute(
            intent=make_review_intent(),
            probability_policy=make_policy(),
            schedule_policy=_schedule_policy(),
            path_evidence=make_path_study(generated_at=NOW - timedelta(hours=3)),
            recorded_at=NOW,
        )


@pytest.mark.django_db
def test_event_validation_race_replays_winner_and_rejects_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ScenarioReviewReminderRepository()
    _, scheduled = _schedule(repository)
    reminder_id = scheduled.reminder.reminder_id
    due_history = reconcile_scenario_review_reminder(
        reminder=scheduled.reminder,
        events=scheduled.events,
        as_of=scheduled.reminder.due_at,
        recorded_at=scheduled.reminder.due_at,
    )
    due_ledger = repository.append_events(reminder_id, (due_history[-1],))
    winning_ack = acknowledge_scenario_review_reminder(
        reminder=due_ledger.reminder,
        events=due_ledger.events,
        acknowledged_at=due_ledger.reminder.due_at + timedelta(hours=1),
        recorded_at=due_ledger.reminder.due_at + timedelta(hours=1),
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="event-race-ack",
    )
    winner = repository.append_events(reminder_id, (winning_ack,))
    original_ledger_from_model = repository._ledger_from_model

    def hide_winner_once() -> None:
        first_call = True

        def ledger_from_model(
            model: ScenarioReviewReminderModel,
            *,
            for_update: bool,
        ) -> ScenarioReviewReminderLedger:
            nonlocal first_call
            if first_call:
                first_call = False
                return due_ledger
            return original_ledger_from_model(model, for_update=for_update)

        monkeypatch.setattr(repository, "_ledger_from_model", ledger_from_model)

    hide_winner_once()
    assert repository.append_events(reminder_id, (winning_ack,)) == winner

    conflicting_ack = acknowledge_scenario_review_reminder(
        reminder=due_ledger.reminder,
        events=due_ledger.events,
        acknowledged_at=due_ledger.reminder.due_at + timedelta(hours=1),
        recorded_at=due_ledger.reminder.due_at + timedelta(hours=1),
        actor_evidence_hash="8" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key=winning_ack.idempotency_key,
    )
    assert conflicting_ack.event_id == winning_ack.event_id
    assert conflicting_ack.content_hash != winning_ack.content_hash
    hide_winner_once()
    with pytest.raises(ScenarioReviewReminderConflict):
        repository.append_events(reminder_id, (conflicting_ack,))

    persisted = repository.get_required(reminder_id)
    assert persisted == winner
    assert [event.sequence for event in persisted.events] == [1, 2, 3]
    assert (
        ScenarioReviewReminderEventModel._default_manager.filter(
            reminder_id=reminder_id,
            idempotency_key=winning_ack.idempotency_key,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_default_base_related_and_conflict_update_paths_are_append_only() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    header = ScenarioReviewReminderModel._default_manager.get(
        reminder_id=ledger.reminder.reminder_id
    )
    event = ScenarioReviewReminderEventModel._default_manager.get()

    for manager in (
        ScenarioReviewReminderModel._default_manager,
        ScenarioReviewReminderModel._base_manager,
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.filter(pk=header.pk).update(path_evidence_hash="0" * 64)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.filter(pk=header.pk).delete()
        with pytest.raises(ValidationError, match="bulk updated"):
            manager.bulk_update([header], ["path_evidence_hash"])
        with pytest.raises(ValidationError, match="update on conflict"):
            manager.all().bulk_create(
                [ScenarioReviewReminderModel(reminder_id=header.reminder_id)],
                update_conflicts=True,
                update_fields=["content_hash"],
                unique_fields=["reminder_id"],
            )
    with pytest.raises(ValidationError, match="cannot be updated"):
        header.events.all().update(reason_code="tampered")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        header.events.all().delete()
    with pytest.raises(ValidationError, match="bulk updated"):
        header.events.bulk_update([event], ["reason_code"])
    with pytest.raises(ValidationError, match="update on conflict"):
        header.events.all().bulk_create(
            [ScenarioReviewReminderEventModel(event_id=event.event_id)],
            update_conflicts=True,
            update_fields=["content_hash"],
            unique_fields=["event_id"],
        )
    for manager in (
        ScenarioReviewReminderEventModel._default_manager,
        ScenarioReviewReminderEventModel._base_manager,
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.filter(pk=event.pk).update(reason_code="tampered")
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.filter(pk=event.pk).delete()
        with pytest.raises(ValidationError, match="bulk updated"):
            manager.bulk_update([event], ["reason_code"])
        with pytest.raises(ValidationError, match="update on conflict"):
            manager.all().bulk_create(
                [ScenarioReviewReminderEventModel(event_id=event.event_id)],
                update_conflicts=True,
                update_fields=["content_hash"],
                unique_fields=["event_id"],
            )
    header.path_evidence_hash = "0" * 64
    with pytest.raises(ValidationError, match="append-only"):
        header.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        event.delete()


@pytest.mark.django_db
def test_raw_source_and_record_tamper_are_detected_on_read() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    reminder_id = ledger.reminder.reminder_id
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_scenario_review_reminder "
            "SET path_evidence_hash = %s WHERE reminder_id = %s",
            ["0" * 64, reminder_id],
        )
    with pytest.raises(ValueError, match="reminder_id mismatch"):
        repository.get_required(reminder_id)

    # Restore the immutable source only to isolate the event-record seal check.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_scenario_review_reminder "
            "SET path_evidence_hash = %s WHERE reminder_id = %s",
            [ledger.reminder.path_evidence_hash, reminder_id],
        )
        cursor.execute(
            "UPDATE research_scenario_review_reminder_event "
            "SET record_hash = %s WHERE reminder_id = %s",
            ["0" * 64, reminder_id],
        )
    with pytest.raises(ValueError, match="record_hash mismatch"):
        repository.get_required(reminder_id)


@pytest.mark.django_db
def test_raw_period_payload_container_and_extra_key_tamper_are_rejected() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    reminder_id = ledger.reminder.reminder_id
    model = ScenarioReviewReminderModel._default_manager.get(pk=reminder_id)
    payload = list(model.period_bindings)
    payload[0] = {**payload[0], "unsealed": "forged"}
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_scenario_review_reminder "
            "SET period_bindings = %s WHERE reminder_id = %s",
            [json.dumps(payload), reminder_id],
        )
    with pytest.raises(ValueError, match="keys are not exact"):
        repository.get_required(reminder_id)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_scenario_review_reminder "
            "SET period_bindings = %s WHERE reminder_id = %s",
            [json.dumps({"not": "a-list"}), reminder_id],
        )
    with pytest.raises(ValueError, match="list of objects"):
        repository.get_required(reminder_id)


@pytest.mark.django_db
def test_forged_terminal_event_cannot_suppress_pull_validation() -> None:
    repository = ScenarioReviewReminderRepository()
    _, ledger = _schedule(repository)
    ReconcileScenarioReviewReminderUseCase(repository).execute(
        reminder_id=ledger.reminder.reminder_id,
        as_of=ledger.reminder.due_at,
        recorded_at=ledger.reminder.due_at,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_scenario_review_reminder_event "
            "SET event_type = %s WHERE reminder_id = %s AND sequence = 2",
            [
                ReminderEventType.ACKNOWLEDGED.value,
                ledger.reminder.reminder_id,
            ],
        )

    with pytest.raises(ValueError, match="content_hash mismatch"):
        PullDueScenarioReviewRemindersUseCase(repository).execute(
            as_of=ledger.reminder.due_at,
            recorded_at=ledger.reminder.due_at,
        )
