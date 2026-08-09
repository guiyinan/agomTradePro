"""Component contracts for the Research-owned R6 monitoring ledgers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.deletion import Collector

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
)
from apps.research.application.state_model_monitoring_persistence import (
    GetExactR6MonitoringAssessmentCommand,
    R6MonitoringPersistenceConflict,
    R6MonitoringPersistenceCorruption,
    R6MonitoringPersistenceUnavailable,
    RegisterR6MonitoringAssessmentCommand,
)
from apps.research.application.state_model_qualification_persistence import (
    r6_qualification_assessment_id,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessmentStatus,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef
from apps.research.infrastructure import state_model_monitoring_repository as repository_module
from apps.research.infrastructure.state_model_monitoring_models import (
    R6MonitoringAssessmentModel,
    R6MonitoringObservationModel,
)
from apps.research.infrastructure.state_model_monitoring_repository import _encode_cursor
from apps.research.infrastructure.state_model_qualification_repository import (
    _DjangoR6QualificationStore,
)
from apps.research.state_model_monitoring_composition import (
    DjangoR6MonitoringRuntime,
    build_django_r6_monitoring_runtime,
)
from tests.unit.research.state_model_monitoring_factories import (
    NOW,
    active_qualification,
    observation,
    period_calendar,
    policy,
)
from tests.unit.research.test_state_model_qualification_persistence import _assessment


@dataclass
class MutableClock:
    """Deterministic authoritative server clock."""

    value: datetime

    def now(self) -> datetime:
        """Return the current test-controlled server time."""

        return self.value


@dataclass
class StaticQualificationProvider:
    """Exact active-qualification owner double."""

    evidence: ActiveR6QualificationEvidence | None
    unit_of_work_key: str = "django:default"

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return only the requested, PIT-known qualification."""

        item = self.evidence
        if item is None or item.qualification_ref != qualification_ref or item.known_at > as_of:
            return None
        return item


@dataclass
class StaticPolicyProvider:
    """Exact monitoring-policy owner double."""

    monitoring_policy: R6MonitoringPolicy | None
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> R6MonitoringPolicy | None:
        """Return only one exact policy identity/seal valid at the cutoff."""

        item = self.monitoring_policy
        if (
            item is None
            or item.policy_id != policy_id
            or item.policy_version != policy_version
            or item.content_hash.lower() != expected_policy_hash.lower()
            or item.qualification_ref != qualification_ref
            or item.recorded_at > as_of
            or not item.is_active_at(as_of)
        ):
            return None
        return item


@dataclass
class StaticCalendarProvider:
    """Exact canonical period-calendar owner double."""

    calendar: R6MonitoringPeriodCalendar | None
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R6MonitoringPeriodCalendar | None:
        """Return only one exact owner-recorded calendar manifest."""

        item = self.calendar
        if (
            item is None
            or item.source_owner != source_owner
            or item.calendar_id != calendar_id
            or item.calendar_version != calendar_version
            or item.content_hash.lower() != expected_calendar_hash.lower()
            or item.recorded_at > as_of
            or not item.is_active_at(as_of)
        ):
            return None
        return item


@dataclass
class StaticRawFactProvider:
    """Canonical raw-observation owner double."""

    observations: tuple[R6MonitoringObservation, ...]
    unit_of_work_key: str = "django:default"

    def list_exact(
        self,
        *,
        qualification_ref: R6QualificationRef,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        period_calendar_id: str,
        period_calendar_version: str,
        period_calendar_hash: str,
        as_of: datetime,
    ) -> tuple[R6MonitoringObservation, ...]:
        """Return the owner's complete bounded fact set without mutation."""

        return self.observations


def _persist_qualification(clock: MutableClock) -> R6QualificationRef:
    qualification = _assessment(assessed_at=NOW - timedelta(days=10))
    store = _DjangoR6QualificationStore(clock=clock)
    original_clock = clock.value
    clock.value = NOW - timedelta(days=9)
    try:
        with store.atomic():
            store.append_assessment(qualification)
    finally:
        clock.value = original_clock
    return R6QualificationRef(
        assessment_id=r6_qualification_assessment_id(
            study_id=qualification.study_id,
            assessed_at=qualification.assessed_at,
            content_hash=qualification.content_hash,
        ),
        assessment_hash=qualification.content_hash,
    )


def _runtime(
    *,
    clock: MutableClock,
    qualification_ref: R6QualificationRef,
    facts: tuple[R6MonitoringObservation, ...] | None = None,
) -> tuple[DjangoR6MonitoringRuntime, StaticRawFactProvider, R6MonitoringPolicy]:
    monitoring_policy = policy(qualification_ref=qualification_ref)
    raw_source = StaticRawFactProvider(
        facts
        if facts is not None
        else (
            observation(sequence=1, monitoring_policy=monitoring_policy),
            observation(sequence=2, monitoring_policy=monitoring_policy),
        )
    )
    runtime = build_django_r6_monitoring_runtime(
        active_qualification_provider=StaticQualificationProvider(
            active_qualification(qualification_ref=qualification_ref)
        ),
        policy_provider=StaticPolicyProvider(monitoring_policy),
        period_calendar_provider=StaticCalendarProvider(period_calendar()),
        raw_fact_provider=raw_source,
        clock=clock,
    )
    return runtime, raw_source, monitoring_policy


def _command(
    qualification_ref: R6QualificationRef,
    monitoring_policy: R6MonitoringPolicy,
    *,
    as_of: datetime = NOW,
) -> RegisterR6MonitoringAssessmentCommand:
    return RegisterR6MonitoringAssessmentCommand(
        qualification_ref=qualification_ref,
        policy_id=monitoring_policy.policy_id,
        policy_version=monitoring_policy.policy_version,
        expected_policy_hash=monitoring_policy.content_hash,
        as_of=as_of,
    )


@pytest.mark.django_db(transaction=True)
def test_register_recomputes_and_appends_exact_pit_graph() -> None:
    """ID-only registration stores raw facts and the locally replayed result."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )

    persisted = runtime.register.execute(_command(qualification_ref, monitoring_policy))

    assert persisted.assessment.status is R6MonitoringAssessmentStatus.HEALTHY
    assert persisted.recorded_at == NOW
    assert persisted.assessment.automatic_retirement is False
    assert persisted.assessment.must_not_use_for_decision is True
    assert persisted.assessment.must_not_replace_regime is True
    assert persisted.assessment.must_not_publish_current is True
    assert persisted.assessment.must_not_execute is True
    assert R6MonitoringObservationModel._default_manager.count() == 2
    assert R6MonitoringAssessmentModel._default_manager.count() == 1

    raw_models = tuple(R6MonitoringObservationModel._default_manager.order_by("observation_id"))
    assert all(item.ledger_recorded_at == NOW for item in raw_models)
    assert tuple(item.owner_recorded_at for item in raw_models) == tuple(
        item.recorded_at for item in persisted.observations
    )
    assert any(item.owner_recorded_at != item.ledger_recorded_at for item in raw_models)

    exact = runtime.get_exact.execute(
        GetExactR6MonitoringAssessmentCommand(
            assessment_ref=persisted.assessment_ref,
            as_of=NOW,
        )
    )
    assert exact == persisted
    assert (
        runtime.get_exact.execute(
            GetExactR6MonitoringAssessmentCommand(
                assessment_ref=persisted.assessment_ref,
                as_of=NOW - timedelta(microseconds=1),
            )
        )
        is None
    )
    audit = runtime.audit.execute(as_of=NOW, limit=1)
    assert len(audit.entries) == 1
    assert audit.entries[0].assessment_ref == persisted.assessment_ref
    assert set(DjangoR6MonitoringRuntime.__dataclass_fields__) == {
        "register",
        "get_exact",
        "audit",
    }
    assert not hasattr(runtime, "repository")
    assert "_DjangoR6MonitoringStore" not in repository_module.__all__

    bound_cursor = _encode_cursor(
        as_of=NOW,
        recorded_at=NOW,
        assessment_id=persisted.assessment_ref.assessment_id,
    )
    with pytest.raises(ValueError, match="cursor cutoff"):
        runtime.audit.execute(
            as_of=NOW - timedelta(microseconds=1),
            cursor=bound_cursor,
            limit=1,
        )
    decoded_cursor = base64.urlsafe_b64decode(bound_cursor + "=" * (-len(bound_cursor) % 4))
    wrong_version_cursor = (
        base64.urlsafe_b64encode(decoded_cursor.replace(b"cursor.v1", b"cursor.v2"))
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(ValueError, match="non-canonical"):
        runtime.audit.execute(
            as_of=NOW,
            cursor=wrong_version_cursor,
            limit=1,
        )


@pytest.mark.django_db(transaction=True)
def test_exact_replay_is_idempotent_and_fork_rolls_back_new_raw_fact() -> None:
    """The first command winner replays; a different fork leaves no partial row."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, raw_source, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )
    command = _command(qualification_ref, monitoring_policy)
    first = runtime.register.execute(command)

    assert runtime.register.execute(command) == first
    assert R6MonitoringObservationModel._default_manager.count() == 2
    raw_source.observations = (
        observation(sequence=0, monitoring_policy=monitoring_policy),
        *raw_source.observations,
    )

    with pytest.raises(R6MonitoringPersistenceConflict, match="already sealed"):
        runtime.register.execute(command)

    assert R6MonitoringObservationModel._default_manager.count() == 2
    assert R6MonitoringAssessmentModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_missing_raw_evidence_is_persisted_fail_closed() -> None:
    """A canonical empty fact set yields a blocked internal assessment."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
        facts=(),
    )

    persisted = runtime.register.execute(_command(qualification_ref, monitoring_policy))

    assert persisted.assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert persisted.observations == ()
    assert R6MonitoringObservationModel._default_manager.count() == 0
    assert R6MonitoringAssessmentModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_future_cutoff_and_missing_canonical_provider_are_unavailable() -> None:
    """No registration can fabricate owners or query future knowledge."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )

    with pytest.raises(R6MonitoringPersistenceUnavailable, match="future"):
        runtime.register.execute(
            _command(
                qualification_ref,
                monitoring_policy,
                as_of=NOW + timedelta(microseconds=1),
            )
        )
    with pytest.raises(R6MonitoringPersistenceUnavailable, match="unavailable"):
        build_django_r6_monitoring_runtime(
            active_qualification_provider=None,
            policy_provider=StaticPolicyProvider(monitoring_policy),
            period_calendar_provider=StaticCalendarProvider(period_calendar()),
            raw_fact_provider=StaticRawFactProvider(()),
            clock=clock,
        )
    assert R6MonitoringAssessmentModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_missing_or_mismatched_uow_attestation_blocks_composition() -> None:
    """A provider cannot inherit or fake the store's transaction identity."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    monitoring_policy = policy(qualification_ref=qualification_ref)

    class MissingUowQualificationProvider:
        def get_exact_active(self, *, qualification_ref, as_of):
            return active_qualification(qualification_ref=qualification_ref)

    with pytest.raises(ValueError, match="unit_of_work_key"):
        build_django_r6_monitoring_runtime(
            active_qualification_provider=MissingUowQualificationProvider(),
            policy_provider=StaticPolicyProvider(monitoring_policy),
            period_calendar_provider=StaticCalendarProvider(period_calendar()),
            raw_fact_provider=StaticRawFactProvider(()),
            clock=clock,
        )

    with pytest.raises(ValueError, match="different units of work"):
        build_django_r6_monitoring_runtime(
            active_qualification_provider=StaticQualificationProvider(
                active_qualification(qualification_ref=qualification_ref)
            ),
            policy_provider=StaticPolicyProvider(monitoring_policy),
            period_calendar_provider=StaticCalendarProvider(period_calendar()),
            raw_fact_provider=StaticRawFactProvider(
                (),
                unit_of_work_key="django:attacker",
            ),
            clock=clock,
        )


@pytest.mark.django_db(transaction=True)
def test_raw_header_tamper_is_detected_by_exact_replay() -> None:
    """Raw SQL cannot turn a changed owner fact into trusted evidence."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )
    persisted = runtime.register.execute(_command(qualification_ref, monitoring_policy))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r6_monitoring_observation "
            "SET source_owner = %s WHERE content_hash = %s",
            ["tampered-owner", persisted.observations[0].content_hash],
        )

    with pytest.raises(R6MonitoringPersistenceCorruption, match="header mismatch"):
        runtime.get_exact.execute(
            GetExactR6MonitoringAssessmentCommand(
                assessment_ref=persisted.assessment_ref,
                as_of=NOW,
            )
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("update_sql", "is_observation"),
    [
        (
            "UPDATE research_r6_monitoring_observation "
            "SET ledger_recorded_at = %s WHERE content_hash = %s",
            True,
        ),
        (
            "UPDATE research_r6_monitoring_assessment "
            "SET ledger_recorded_at = %s WHERE content_hash = %s",
            False,
        ),
    ],
)
def test_ledger_recorded_at_raw_tamper_breaks_row_header_seal(
    update_sql: str,
    is_observation: bool,
) -> None:
    """The server insertion clock is sealed independently of owner evidence."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )
    persisted = runtime.register.execute(_command(qualification_ref, monitoring_policy))
    identity = (
        persisted.observations[0].content_hash
        if is_observation
        else persisted.assessment_ref.assessment_hash
    )
    with connection.cursor() as cursor:
        cursor.execute(
            update_sql,
            [NOW + timedelta(microseconds=1), identity],
        )

    command = GetExactR6MonitoringAssessmentCommand(
        assessment_ref=persisted.assessment_ref,
        as_of=NOW,
    )
    if is_observation:
        with pytest.raises(R6MonitoringPersistenceCorruption):
            runtime.get_exact.execute(command)
    else:
        assert runtime.get_exact.execute(command) is None


@pytest.mark.django_db(transaction=True)
def test_future_damaged_assessment_is_filtered_before_restore() -> None:
    """A future ledger row cannot corrupt an earlier exact PIT query."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )
    persisted = runtime.register.execute(_command(qualification_ref, monitoring_policy))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r6_monitoring_assessment "
            "SET ledger_recorded_at = %s, canonical_payload = %s "
            "WHERE content_hash = %s",
            [
                NOW + timedelta(microseconds=1),
                "{}",
                persisted.assessment_ref.assessment_hash,
            ],
        )

    assert (
        runtime.get_exact.execute(
            GetExactR6MonitoringAssessmentCommand(
                assessment_ref=persisted.assessment_ref,
                as_of=NOW,
            )
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_all_orm_mutation_shortcuts_are_guarded() -> None:
    """Default/base/related/instance/queryset/private/Collector paths all fail."""

    clock = MutableClock(NOW)
    qualification_ref = _persist_qualification(clock)
    runtime, _, monitoring_policy = _runtime(
        clock=clock,
        qualification_ref=qualification_ref,
    )
    runtime.register.execute(_command(qualification_ref, monitoring_policy))
    model = R6MonitoringObservationModel._default_manager.order_by("pk").first()
    assert model is not None
    query = R6MonitoringObservationModel._default_manager.filter(pk=model.pk)

    for mutation in (
        model.save,
        model.save_base,
        lambda: model.save_base(raw=True),
        model.delete,
        lambda: query.update(source_owner="changed"),
        query.delete,
        lambda: query.bulk_update([model], ["source_owner"]),
        lambda: R6MonitoringObservationModel._default_manager.create(),
        lambda: R6MonitoringObservationModel._base_manager.create(),
        lambda: R6MonitoringObservationModel._default_manager.bulk_create([model]),
        lambda: R6MonitoringObservationModel._base_manager.bulk_create([model]),
        lambda: R6MonitoringObservationModel._default_manager.get_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
        lambda: R6MonitoringObservationModel._base_manager.get_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
        lambda: R6MonitoringObservationModel._default_manager.update_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
        lambda: R6MonitoringObservationModel._base_manager.update_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
        lambda: query._update([]),
        lambda: query._raw_delete("default"),
        lambda: query._batched_insert([], [], None),
        lambda: query._insert([model], []),
        lambda: model.qualification.monitoring_observations.create(),
        lambda: model.qualification.monitoring_observations.get_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
        lambda: model.qualification.monitoring_observations.update_or_create(
            observation_id=model.observation_id,
            observation_version=model.observation_version,
        ),
    ):
        with pytest.raises(ValidationError):
            mutation()

    collector = Collector(using="default")
    collector.collect([model])
    with pytest.raises(ValidationError):
        collector.delete()


def test_r6_monitoring_migration_is_schema_only_and_depends_on_0010() -> None:
    """Phase B creates zero seed/backfill data and follows the R7 schema."""

    migration = __import__(
        "apps.research.migrations.0011_r6_monitoring_ledgers",
        fromlist=["Migration"],
    ).Migration
    assert migration.dependencies == [("research", "0010_r7_result_promotion_lifecycle")]
    assert [operation.__class__.__name__ for operation in migration.operations] == [
        "CreateModel",
        "CreateModel",
    ]
    assert not any(
        operation.__class__.__name__ in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
    assert all(
        "ledger_header_hash" in {field_name for field_name, _ in operation.fields}
        for operation in migration.operations
    )
