"""Component contracts for the authoritative R3 runner-spec ledger."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector

from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec
from apps.research.application.r3_macro_factor_runner_spec import (
    GetExactMacroFactorRunnerSpecCommand,
    MacroFactorRunnerSpecConflict,
    MacroFactorRunnerSpecCorruption,
    MacroFactorRunnerSpecUnavailable,
    RegisterMacroFactorRunnerSpecCommand,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_models import (
    R3MacroFactorRunnerSpecModel,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_repository import (
    _record_values,
)
from apps.research.r3_macro_factor_runner_spec_composition import (
    _build_django_r3_macro_factor_runner_spec_test_runtime,
    _DjangoR3MacroFactorRunnerSpecTestRuntime,
    build_django_r3_macro_factor_runner_spec_runtime,
)
from tests.unit.macro_factor.runner_factories import runner_spec

COMMAND_AS_OF = datetime(2015, 1, 1, tzinfo=UTC)
SERVER_NOW = datetime(2015, 1, 2, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime = SERVER_NOW
    fail: bool = False

    def now(self) -> datetime:
        if self.fail:
            raise RuntimeError("clock unavailable")
        return self.value


class OwnerProvider:
    unit_of_work_key = "django:default"

    def __init__(self, spec: MacroFactorRunnerSpec | None = None) -> None:
        self.spec = spec or runner_spec()
        self.calls: list[datetime] = []
        self.fail = False
        self.drift_on_second_read = False
        self.uow_drift_call: int | None = None

    def get_exact(
        self,
        *,
        spec_id: str,
        spec_version: int,
        as_of: datetime,
    ) -> MacroFactorRunnerSpec | None:
        self.calls.append(as_of)
        if self.uow_drift_call == len(self.calls):
            self.unit_of_work_key = "django:other"
        if self.fail:
            raise RuntimeError("owner unavailable")
        if spec_id != self.spec.run_key or spec_version != self.spec.run_version:
            return None
        if self.drift_on_second_read and len(self.calls) == 2:
            return replace(self.spec, factor_version="macro-growth-v2")
        return self.spec


def _command() -> RegisterMacroFactorRunnerSpecCommand:
    spec = runner_spec()
    return RegisterMacroFactorRunnerSpecCommand(
        spec_id=spec.run_key,
        spec_version=spec.run_version,
        as_of=COMMAND_AS_OF,
    )


def _runtime(
    *,
    owner: OwnerProvider | None = None,
    clock: FixedClock | None = None,
) -> _DjangoR3MacroFactorRunnerSpecTestRuntime:
    return _build_django_r3_macro_factor_runner_spec_test_runtime(
        definition_provider=owner or OwnerProvider(),
        clock=clock or FixedClock(),
    )


@pytest.mark.django_db
def test_id_only_registration_rereads_owner_and_uses_server_ledger_time() -> None:
    owner = OwnerProvider()
    runtime = _runtime(owner=owner)

    record = runtime.register.execute(_command())

    assert owner.calls == [COMMAND_AS_OF, SERVER_NOW]
    assert record.ledger_recorded_at == SERVER_NOW
    assert record.spec == runner_spec()
    assert record.research_only is True
    assert record.must_not_publish_current is True
    assert record.must_not_use_for_decision is True
    assert record.must_not_execute is True
    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 1
    assert (
        runtime.get_exact.execute(
            GetExactMacroFactorRunnerSpecCommand(
                spec_id=record.spec.run_key,
                spec_version=record.spec.run_version,
                expected_content_hash=record.spec.content_hash,
                as_of=SERVER_NOW,
            )
        )
        == record
    )
    assert (
        runtime.provider.get_spec(
            spec_id=record.spec.run_key,
            spec_version=record.spec.run_version,
        )
        == record.spec
    )


@pytest.mark.django_db
def test_production_registration_is_inert_without_owner_and_writes_nothing() -> None:
    runtime = build_django_r3_macro_factor_runner_spec_runtime()

    with pytest.raises(MacroFactorRunnerSpecUnavailable, match="owner provider"):
        runtime.register.execute(_command())

    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ("owner", "clock", "drift"))
def test_owner_clock_and_reread_failures_are_unavailable_with_zero_writes(
    failure: str,
) -> None:
    owner = OwnerProvider()
    clock = FixedClock()
    if failure == "owner":
        owner.fail = True
    elif failure == "clock":
        clock.fail = True
    else:
        owner.drift_on_second_read = True
    runtime = _runtime(owner=owner, clock=clock)

    with pytest.raises(MacroFactorRunnerSpecUnavailable):
        runtime.register.execute(_command())

    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 0


@pytest.mark.django_db
def test_uow_mismatch_and_late_server_registration_fail_before_append() -> None:
    wrong_owner = OwnerProvider()
    wrong_owner.unit_of_work_key = "django:other"
    with pytest.raises(ValueError, match="shared unit of work"):
        _runtime(owner=wrong_owner)

    spec = runner_spec()
    first_selection = min(fold.selection_as_of for fold in spec.plan.outer_folds)
    runtime = _runtime(clock=FixedClock(first_selection))
    with pytest.raises(MacroFactorRunnerSpecUnavailable, match="owner, clock, or record"):
        runtime.register.execute(_command())
    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 0


@pytest.mark.django_db
def test_duplicate_identity_and_malformed_command_fail_without_extra_rows() -> None:
    owner = OwnerProvider()
    runtime = _runtime(owner=owner)
    first = runtime.register.execute(_command())
    assert runtime.register.execute(_command()) == first

    owner.spec = replace(owner.spec, factor_version="macro-growth-v2")
    with pytest.raises(MacroFactorRunnerSpecConflict, match="different evidence"):
        runtime.register.execute(_command())

    malformed = _command()
    object.__setattr__(malformed, "spec_version", True)
    with pytest.raises(MacroFactorRunnerSpecUnavailable):
        runtime.register.execute(malformed)
    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("drift_stage", ("before", "first_read", "second_read"))
def test_uow_key_is_revalidated_before_during_and_before_append(
    drift_stage: str,
) -> None:
    owner = OwnerProvider()
    runtime = _runtime(owner=owner)
    if drift_stage == "before":
        owner.unit_of_work_key = "django:other"
    elif drift_stage == "first_read":
        owner.uow_drift_call = 1
    else:
        owner.uow_drift_call = 2

    with pytest.raises(MacroFactorRunnerSpecUnavailable, match="owner, clock, or record"):
        runtime.register.execute(_command())

    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 0


@pytest.mark.django_db
def test_orm_update_delete_and_unclaimed_insert_paths_are_rejected() -> None:
    runtime = _runtime()
    record = runtime.register.execute(_command())
    row = R3MacroFactorRunnerSpecModel._default_manager.get()

    row.factor_version = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="cannot be updated"):
        R3MacroFactorRunnerSpecModel._default_manager.update(factor_version="tampered")
    with pytest.raises(ValidationError, match="exact repository appends"):
        R3MacroFactorRunnerSpecModel._default_manager.bulk_create(
            [R3MacroFactorRunnerSpecModel(**_record_values(record))]
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        R3MacroFactorRunnerSpecModel._default_manager.create(**_record_values(record))
    private_queryset = R3MacroFactorRunnerSpecModel._base_manager.filter(pk=row.pk)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        private_queryset._raw_delete("default")
    with pytest.raises(ValidationError, match="cannot be updated"):
        private_queryset._update([])
    with pytest.raises(ValidationError, match="private bulk insert"):
        private_queryset._batched_insert([], [], 1)
    collector = Collector(using="default")
    collector.collect([row])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        with transaction.atomic():
            collector.delete()
    assert R3MacroFactorRunnerSpecModel._default_manager.count() == 1


@pytest.mark.django_db
def test_header_tamper_is_detected_by_exact_query_and_provider() -> None:
    runtime = _runtime()
    record = runtime.register.execute(_command())
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r3_macro_factor_runner_spec "
            "SET target_code = %s WHERE spec_id = %s",
            ["tampered", record.spec.run_key],
        )

    with pytest.raises(MacroFactorRunnerSpecCorruption, match="header mismatch"):
        runtime.get_exact.execute(
            GetExactMacroFactorRunnerSpecCommand(
                spec_id=record.spec.run_key,
                spec_version=record.spec.run_version,
                expected_content_hash=record.spec.content_hash,
                as_of=SERVER_NOW,
            )
        )
    with pytest.raises(MacroFactorRunnerSpecCorruption, match="header mismatch"):
        runtime.provider.get_spec(
            spec_id=record.spec.run_key,
            spec_version=record.spec.run_version,
        )


@pytest.mark.django_db
def test_exact_query_is_pit_and_hash_bound() -> None:
    runtime = _runtime()
    record = runtime.register.execute(_command())

    assert (
        runtime.get_exact.execute(
            GetExactMacroFactorRunnerSpecCommand(
                spec_id=record.spec.run_key,
                spec_version=record.spec.run_version,
                expected_content_hash=record.spec.content_hash,
                as_of=SERVER_NOW - timedelta(microseconds=1),
            )
        )
        is None
    )
    assert (
        runtime.get_exact.execute(
            GetExactMacroFactorRunnerSpecCommand(
                spec_id=record.spec.run_key,
                spec_version=record.spec.run_version,
                expected_content_hash="f" * 64,
                as_of=SERVER_NOW,
            )
        )
        is None
    )
