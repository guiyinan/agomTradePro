"""Minimal end-to-end persistence coverage for the R7 family lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.db import connection

from apps.research.application.r7_result_family_lifecycle import (
    ApplyR7FamilyLifecycleCommand,
    R7FamilyAuthorizationRef,
    R7FamilyLifecycleUnavailable,
    R7FamilyResultIdRef,
    R7ResultFamilyRef,
)
from apps.research.application.r7_result_family_lifecycle_persistence import (
    AuditR7FamilyLifecycleCommand,
    GetExactR7FamilyAuthorizationCommand,
    GetExactR7FamilyEventCommand,
    R7FamilyEventRef,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7LocalLifecycleStreamAttestation,
    R7ResultFamilyIdentity,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleAuthorizationModel,
)
from apps.research.infrastructure.r7_result_family_lifecycle_models import (
    R7FamilyLifecycleAuditSnapshotModel,
    R7FamilyLifecycleAuthorizationModel,
    R7FamilyLifecycleEventModel,
    R7FamilyLifecycleStreamCommitModel,
)
from apps.research.r7_result_family_lifecycle_composition import (
    _build_django_r7_family_lifecycle_component_for_tests,
    build_django_r7_family_lifecycle_runtime,
)
from tests.component.research.test_r7_research_result_lifecycle_repository import (
    _apply_command as _apply_local_command,
)
from tests.component.research.test_r7_research_result_lifecycle_repository import (
    _authorization as _local_authorization,
)
from tests.component.research.test_r7_research_result_lifecycle_repository import (
    _lifecycle_runtime,
    _result_ref,
)
from tests.component.research.test_r7_research_result_repository import (
    FixedClock,
)
from tests.component.research.test_r7_research_result_repository import _command as _result_command
from tests.component.research.test_r7_research_result_repository import _runtime as _result_runtime


class _ResultProvider:
    unit_of_work_key = "django:default"

    def __init__(self, result: object) -> None:
        self.result = result

    def get_exact(self, *, result_ref: R7FamilyResultIdRef, as_of: datetime) -> object:
        result = self.result
        if (
            getattr(result, "result_id", None),
            getattr(result, "result_version", None),
        ) != (result_ref.result_id, result_ref.result_version):
            return None
        return result if result.recorded_at <= as_of else None


class _LocalLifecycleProvider:
    unit_of_work_key = "django:default"

    def __init__(self, stream: tuple[object, ...]) -> None:
        self.stream = stream

    def load_complete(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> tuple[object, ...]:
        del result_ref
        return tuple(event for event in self.stream if event.recorded_at <= as_of)

    def get_attestation(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> R7LocalLifecycleStreamAttestation | None:
        stream = self.load_complete(result_ref=result_ref, as_of=as_of)
        if not stream:
            return None
        return R7LocalLifecycleStreamAttestation.from_stream(
            attestation_id=f"r7-local-lifecycle-attestation:{result_ref.result_id}",
            attestation_version="r7-local-lifecycle-attestation.v1",
            complete_local_lifecycle_stream=stream,
            recorded_at=stream[-1].recorded_at,
        )


class _AuthorizationProvider:
    unit_of_work_key = "django:default"

    def __init__(self, authorization: R7FamilyLifecycleAuthorization) -> None:
        self.authorization = authorization

    def get_exact(self, **kwargs: object) -> R7FamilyLifecycleAuthorization | None:
        as_of = kwargs["as_of"]
        return self.authorization if self.authorization.recorded_at <= as_of else None


class _ToggleClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.fail = False

    def now(self) -> datetime:
        if self.fail:
            raise RuntimeError("clock unavailable")
        return self.value


def _persist_local_promotion() -> tuple[object, tuple[object, ...], FixedClock]:
    result_fixture = _result_runtime()
    result = result_fixture.runtime.register.execute(_result_command())
    clock = result_fixture.clock
    clock.value = result.recorded_at + timedelta(minutes=2)
    lifecycle = _lifecycle_runtime(clock)
    authorization = _local_authorization(
        result_ref=_result_ref(result),
        action=__import__(
            "apps.research.domain.r7_research_result_lifecycle",
            fromlist=["R7ResultLifecycleAction"],
        ).R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=clock.value - timedelta(seconds=1),
    )
    lifecycle.provider.authorization = authorization
    lifecycle.runtime.apply.execute(_apply_local_command(authorization))
    with lifecycle.repository.atomic():
        stream = lifecycle.repository.load_lifecycle_stream(result_ref=_result_ref(result))
    return result, stream, clock


@pytest.mark.django_db
def test_family_persistence_round_trip_commits_one_exact_three_way_winner() -> None:
    result, local_stream, clock = _persist_local_promotion()
    family = R7ResultFamilyIdentity.from_result(result)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id=f"r7-local-lifecycle-attestation:{result.result_id}",
        attestation_version="r7-local-lifecycle-attestation.v1",
        complete_local_lifecycle_stream=local_stream,
        recorded_at=local_stream[-1].recorded_at,
    )
    evidence = __import__(
        "apps.research.domain.r7_result_family_lifecycle",
        fromlist=["R7FamilyResultOwnerEvidence"],
    ).R7FamilyResultOwnerEvidence.from_owner_graph(
        result=result,
        complete_local_lifecycle_stream=local_stream,
        local_lifecycle_attestation=attestation,
        evaluated_at=local_stream[-1].recorded_at,
    )
    clock.value = local_stream[-1].recorded_at + timedelta(minutes=2)
    authorization = R7FamilyLifecycleAuthorization.create(
        authorization_id="r7-family-component-authorization:1",
        authorization_version="r7-family-authorization.v1",
        family=family,
        event_id="r7-family-component-event:1",
        event_version="r7-family-event.v1",
        action=R7FamilyLifecycleAction.PROMOTE,
        subject_ref=evidence.result_ref,
        subject_owner_attestation_hash=attestation.content_hash,
        rollback_target_ref=None,
        rollback_target_owner_attestation_hash=None,
        expected_sequence=1,
        expected_previous_event_id=None,
        expected_previous_event_version=None,
        expected_previous_event_hash=None,
        owner="research",
        issued_at=clock.value - timedelta(seconds=2),
        recorded_at=clock.value - timedelta(seconds=1),
        valid_until=clock.value + timedelta(days=1),
        reason_codes=("manual-research-governance",),
        evidence_ref="research://r7-family-component/1",
    )
    family_clock = _ToggleClock(clock.value)
    component = _build_django_r7_family_lifecycle_component_for_tests(
        result_provider=_ResultProvider(result),
        local_lifecycle_provider=_LocalLifecycleProvider(local_stream),
        authorization_provider=_AuthorizationProvider(authorization),
        using="default",
        clock=family_clock,
    )
    command = ApplyR7FamilyLifecycleCommand(
        family_ref=R7ResultFamilyRef(family.family_id, family.family_version),
        action=authorization.action,
        subject_ref=R7FamilyResultIdRef(result.result_id, result.result_version),
        rollback_target_ref=None,
        authorization_ref=R7FamilyAuthorizationRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
        as_of=authorization.recorded_at,
    )

    event = component.apply.execute(command)
    assert component.apply.execute(command) == event
    family_clock.value = event.recorded_at - timedelta(days=1)
    assert component.apply.execute(command) == event
    family_clock.fail = True
    assert component.apply.execute(command) == event
    family_clock.fail = False
    family_clock.value = clock.value
    assert (
        component.get_exact_authorization.execute(
            GetExactR7FamilyAuthorizationCommand(command.authorization_ref, clock.value)
        )
        == authorization
    )
    assert (
        component.get_exact_event.execute(
            GetExactR7FamilyEventCommand(
                R7FamilyEventRef(event.event_id, event.event_version),
                clock.value,
            )
        )
        == event
    )
    assert R7FamilyLifecycleAuthorizationModel._default_manager.count() == 1
    assert R7FamilyLifecycleEventModel._default_manager.count() == 1
    assert R7FamilyLifecycleStreamCommitModel._default_manager.count() == 1

    local_authorization = R7ResultLifecycleAuthorizationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_result_lifecycle_authorization SET evidence_ref = %s WHERE id = %s",
            ["research://tampered-owner-authorization", local_authorization.pk],
        )
    with pytest.raises(R7FamilyLifecycleUnavailable):
        component.get_exact_event.execute(
            GetExactR7FamilyEventCommand(
                R7FamilyEventRef(event.event_id, event.event_version),
                clock.value,
            )
        )


@pytest.mark.django_db
def test_family_audit_snapshot_cursor_is_stable_and_tamper_evident() -> None:
    result, local_stream, clock = _persist_local_promotion()
    family = R7ResultFamilyIdentity.from_result(result)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id=f"r7-local-lifecycle-attestation:{result.result_id}",
        attestation_version="r7-local-lifecycle-attestation.v1",
        complete_local_lifecycle_stream=local_stream,
        recorded_at=local_stream[-1].recorded_at,
    )
    evidence = __import__(
        "apps.research.domain.r7_result_family_lifecycle",
        fromlist=["R7FamilyResultOwnerEvidence"],
    ).R7FamilyResultOwnerEvidence.from_owner_graph(
        result=result,
        complete_local_lifecycle_stream=local_stream,
        local_lifecycle_attestation=attestation,
        evaluated_at=local_stream[-1].recorded_at,
    )
    clock.value = local_stream[-1].recorded_at + timedelta(minutes=2)
    root_authorization = R7FamilyLifecycleAuthorization.create(
        authorization_id="r7-family-audit-authorization:1",
        authorization_version="r7-family-authorization.v1",
        family=family,
        event_id="r7-family-audit-event:1",
        event_version="r7-family-event.v1",
        action=R7FamilyLifecycleAction.PROMOTE,
        subject_ref=evidence.result_ref,
        subject_owner_attestation_hash=attestation.content_hash,
        rollback_target_ref=None,
        rollback_target_owner_attestation_hash=None,
        expected_sequence=1,
        expected_previous_event_id=None,
        expected_previous_event_version=None,
        expected_previous_event_hash=None,
        owner="research",
        issued_at=clock.value - timedelta(seconds=2),
        recorded_at=clock.value - timedelta(seconds=1),
        valid_until=clock.value + timedelta(days=1),
        reason_codes=("manual-research-governance",),
        evidence_ref="research://r7-family-audit/1",
    )
    authorization_provider = _AuthorizationProvider(root_authorization)
    component = _build_django_r7_family_lifecycle_component_for_tests(
        result_provider=_ResultProvider(result),
        local_lifecycle_provider=_LocalLifecycleProvider(local_stream),
        authorization_provider=authorization_provider,
        using="default",
        clock=clock,
    )
    family_ref = R7ResultFamilyRef(family.family_id, family.family_version)
    subject_ref = R7FamilyResultIdRef(result.result_id, result.result_version)
    root = component.apply.execute(
        ApplyR7FamilyLifecycleCommand(
            family_ref=family_ref,
            action=root_authorization.action,
            subject_ref=subject_ref,
            rollback_target_ref=None,
            authorization_ref=R7FamilyAuthorizationRef(
                root_authorization.authorization_id,
                root_authorization.authorization_version,
            ),
            as_of=root_authorization.recorded_at,
        )
    )
    clock.value = root.recorded_at + timedelta(minutes=2)
    retirement = R7FamilyLifecycleAuthorization.create(
        authorization_id="r7-family-audit-authorization:2",
        authorization_version="r7-family-authorization.v1",
        family=family,
        event_id="r7-family-audit-event:2",
        event_version="r7-family-event.v1",
        action=R7FamilyLifecycleAction.RETIRE,
        subject_ref=evidence.result_ref,
        subject_owner_attestation_hash=attestation.content_hash,
        rollback_target_ref=None,
        rollback_target_owner_attestation_hash=None,
        expected_sequence=2,
        expected_previous_event_id=root.event_id,
        expected_previous_event_version=root.event_version,
        expected_previous_event_hash=root.content_hash,
        owner="research",
        issued_at=clock.value - timedelta(seconds=2),
        recorded_at=clock.value - timedelta(seconds=1),
        valid_until=clock.value + timedelta(days=1),
        reason_codes=("manual-research-governance",),
        evidence_ref="research://r7-family-audit/2",
    )
    authorization_provider.authorization = retirement
    component.apply.execute(
        ApplyR7FamilyLifecycleCommand(
            family_ref=family_ref,
            action=retirement.action,
            subject_ref=subject_ref,
            rollback_target_ref=None,
            authorization_ref=R7FamilyAuthorizationRef(
                retirement.authorization_id,
                retirement.authorization_version,
            ),
            as_of=retirement.recorded_at,
        )
    )

    first = component.audit.execute(AuditR7FamilyLifecycleCommand(family_ref, clock.value, 1))
    assert tuple(entry.sequence for entry in first.entries) == (1,)
    assert first.next_cursor is not None
    second = component.audit.execute(
        AuditR7FamilyLifecycleCommand(
            family_ref,
            clock.value,
            1,
            first.next_cursor,
        )
    )
    assert tuple(entry.sequence for entry in second.entries) == (2,)
    assert second.snapshot_id == first.snapshot_id
    assert second.snapshot_hash == first.snapshot_hash
    assert second.next_cursor is None
    assert R7FamilyLifecycleAuditSnapshotModel._default_manager.count() == 1

    assert first.next_cursor is not None
    tampered = first.next_cursor[:-1] + ("0" if first.next_cursor[-1] != "0" else "1")
    with pytest.raises(R7FamilyLifecycleUnavailable, match="cursor"):
        component.audit.execute(AuditR7FamilyLifecycleCommand(family_ref, clock.value, 1, tampered))


@pytest.mark.django_db
def test_production_family_apply_and_audit_are_inert_and_zero_write() -> None:
    runtime = build_django_r7_family_lifecycle_runtime()
    command = ApplyR7FamilyLifecycleCommand(
        family_ref=R7ResultFamilyRef("r7-family", "r7-result-family.v1"),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject_ref=R7FamilyResultIdRef("r7-result", "r7-result.v1"),
        rollback_target_ref=None,
        authorization_ref=R7FamilyAuthorizationRef("r7-auth", "r7-auth.v1"),
        as_of=datetime.now().astimezone(),
    )
    with pytest.raises(R7FamilyLifecycleUnavailable, match="providers are unavailable"):
        runtime.apply.execute(command)
    assert R7FamilyLifecycleAuthorizationModel._default_manager.count() == 0
    assert R7FamilyLifecycleEventModel._default_manager.count() == 0
    assert R7FamilyLifecycleStreamCommitModel._default_manager.count() == 0
    assert R7FamilyLifecycleAuditSnapshotModel._default_manager.count() == 0
