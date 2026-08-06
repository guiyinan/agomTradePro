"""Component coverage for the R5 cross-owner append-only audit ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta
from typing import Generic, TypeVar, cast

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction

from apps.fixed_income import relative_value_composition as composition_module
from apps.fixed_income.application.relative_value import (
    R5AuthoritativeRelativeValueRun,
    RunR5RelativeValueResearch,
    RunR5RelativeValueResearchCommand,
)
from apps.fixed_income.application.relative_value_persistence import (
    GetExactR5RelativeValueCommand,
    PersistR5RelativeValueCommand,
    R5RelativeValuePersistenceConflict,
    R5RelativeValuePersistenceCorruption,
    R5RelativeValuePersistenceDraft,
    collect_r5_persistence_evidence,
)
from apps.fixed_income.domain.evidence import EvidenceLocator
from apps.fixed_income.domain.relative_value_assessment import R5RelativeValueStatus
from apps.fixed_income.infrastructure import (
    relative_value_repository as relative_value_repository_module,
)
from apps.fixed_income.infrastructure.relative_value_models import (
    FixedIncomeR5InputReceiptModel,
    FixedIncomeR5ResultModel,
)
from apps.fixed_income.infrastructure.relative_value_repository import (
    DjangoR5RelativeValueRepository,
)
from apps.fixed_income.relative_value_composition import (
    DjangoR5RelativeValueRuntime,
    build_django_r5_relative_value_runtime,
)
from tests.unit.fixed_income.test_relative_value_use_case import (
    _EVALUATED_AT,
    _command,
    _fixture_graph,
    _FixtureGraph,
    _Provider,
    _runner_graph,
)

pytestmark = pytest.mark.django_db

_RECORDED_AT = _EVALUATED_AT + timedelta(minutes=1)
T = TypeVar("T")


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _OwnerUnitOfWork:
    def __init__(self, owner: str, key: str = "django:default") -> None:
        self.owner = owner
        self.unit_of_work_key = key
        self.active = 0
        self.entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        with transaction.atomic():
            self.active += 1
            self.entries += 1
            try:
                yield
            finally:
                self.active -= 1

    def require_active_unit_of_work(self) -> None:
        if self.active <= 0 or not transaction.get_connection().in_atomic_block:
            raise R5RelativeValuePersistenceConflict(f"{self.owner} owner unit of work is inactive")


class _InactiveOwnerUnitOfWork(_OwnerUnitOfWork):
    @contextmanager
    def atomic(self) -> Iterator[None]:
        with transaction.atomic():
            yield


class _CheckedProvider(Generic[T]):
    def __init__(
        self,
        delegate: _Provider[T],
        owner_ports: tuple[_OwnerUnitOfWork, ...],
    ) -> None:
        self._delegate = delegate
        self._owner_ports = owner_ports

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> T | None:
        for port in self._owner_ports:
            port.require_active_unit_of_work()
        return self._delegate.get_exact(locator, evaluated_at=evaluated_at)


@dataclass(frozen=True)
class _RuntimeFixture:
    runtime: DjangoR5RelativeValueRuntime
    clock: _Clock
    owner_ports: tuple[_OwnerUnitOfWork, ...]


def _runtime(
    graph: _FixtureGraph,
    *,
    clock: _Clock | None = None,
    key: str = "django:default",
    missing_owner_evidence: bool = False,
) -> _RuntimeFixture:
    providers = _runner_graph(graph)
    if missing_owner_evidence:
        missing = graph.input_set.owner_exact_sources[0]
        providers.exact_owner_provider.values.pop(missing.locator)
    owner_ports = (
        _OwnerUnitOfWork("data_center", key),
        _OwnerUnitOfWork("portfolio", key),
        _OwnerUnitOfWork("research", key),
    )

    def checked(provider: _Provider[T]) -> _CheckedProvider[T]:
        return _CheckedProvider(provider, owner_ports)

    actual_clock = clock or _Clock(_RECORDED_AT)
    runtime = build_django_r5_relative_value_runtime(
        input_provider=checked(providers.input_provider),
        policy_provider=checked(providers.policy_provider),
        publication_provider=checked(providers.publication_provider),
        bond_master_provider=checked(providers.bond_master_provider),
        cash_flow_provider=checked(providers.cash_flow_provider),
        calendar_provider=checked(providers.calendar_provider),
        exact_owner_provider=checked(providers.exact_owner_provider),
        data_center_unit_of_work=owner_ports[0],
        portfolio_unit_of_work=owner_ports[1],
        research_unit_of_work=owner_ports[2],
        clock=actual_clock,
    )
    return _RuntimeFixture(runtime, actual_clock, owner_ports)


def _persist_command(
    graph: _FixtureGraph,
    *,
    assessment_id: str = "r5-assessment",
) -> PersistR5RelativeValueCommand:
    return PersistR5RelativeValueCommand(
        assessment_id=assessment_id,
        input_set=graph.input_set.source.locator,
        policy_set=graph.policy_set.source.locator,
        evaluated_at=_EVALUATED_AT,
    )


def test_id_only_command_persists_and_queries_one_exact_server_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    fixture = _runtime(graph)
    command = _persist_command(graph)

    first = fixture.runtime.persist.execute(command)
    replay = fixture.runtime.persist.execute(command)

    assert replay == first
    assert first.receipt.owner == first.result.owner == "fixed_income"
    assert first.receipt.recorded_at == _RECORDED_AT
    assert first.receipt.command_hash == command.command_hash
    assert first.result.assessment.status is R5RelativeValueStatus.AVAILABLE
    assert fixture.clock.calls == 1
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 1
    assert FixedIncomeR5ResultModel._default_manager.count() == 1
    assert all(port.entries == 2 and port.active == 0 for port in fixture.owner_ports)
    assert tuple(item.name for item in fields(PersistR5RelativeValueCommand)) == (
        "assessment_id",
        "input_set",
        "policy_set",
        "evaluated_at",
    )

    exact = fixture.runtime.query.execute(
        GetExactR5RelativeValueCommand(
            result_id=first.result.result_id,
            result_version=first.result.result_version,
            expected_record_hash=first.result.record_hash,
            as_of=first.result.recorded_at,
        )
    )
    assert exact == first
    assert (
        fixture.runtime.query.execute(
            GetExactR5RelativeValueCommand(
                result_id=first.result.result_id,
                result_version=first.result.result_version,
                expected_record_hash=first.result.record_hash,
                as_of=first.result.recorded_at - timedelta(microseconds=1),
            )
        )
        is None
    )


def test_complete_but_business_blocked_result_is_persisted_for_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch, omit_short_capacity=True)

    bundle = _runtime(graph).runtime.persist.execute(_persist_command(graph))

    assert bundle.result.assessment.status is R5RelativeValueStatus.BLOCKED
    assert bundle.result.assessment.blockers


def test_historical_owner_expiry_before_server_recording_remains_auditable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    historical_expiry = min(
        item.valid_until
        for item in collect_r5_persistence_evidence(
            graph.input_set,
            graph.policy_set,
        )
    )
    assert _EVALUATED_AT < historical_expiry
    clock = _Clock(historical_expiry + timedelta(days=1))
    runtime = _runtime(graph, clock=clock).runtime

    bundle = runtime.persist.execute(_persist_command(graph))
    restored = runtime.query.execute(
        GetExactR5RelativeValueCommand(
            result_id=bundle.result.result_id,
            result_version=bundle.result.result_version,
            expected_record_hash=bundle.result.record_hash,
            as_of=clock.value,
        )
    )

    assert bundle.receipt.recorded_at > historical_expiry
    assert restored == bundle


@pytest.mark.parametrize(
    "server_time",
    (
        _EVALUATED_AT - timedelta(microseconds=1),
        datetime(2026, 6, 10, 10, 1),
    ),
)
def test_backdated_or_naive_server_clock_rolls_back_every_row(
    monkeypatch: pytest.MonkeyPatch,
    server_time: datetime,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph, clock=_Clock(server_time)).runtime

    with pytest.raises(R5RelativeValuePersistenceConflict):
        runtime.persist.execute(_persist_command(graph))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_missing_nested_owner_graph_rolls_back_without_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph, missing_owner_evidence=True).runtime

    with pytest.raises(R5RelativeValuePersistenceConflict, match="fully verified"):
        runtime.persist.execute(_persist_command(graph))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_mismatched_owner_transaction_key_is_rejected_before_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    providers = _runner_graph(graph)
    data_center = _OwnerUnitOfWork("data_center")
    portfolio = _OwnerUnitOfWork("portfolio", "django:other")
    research = _OwnerUnitOfWork("research")

    with pytest.raises(R5RelativeValuePersistenceConflict, match="share one"):
        build_django_r5_relative_value_runtime(
            input_provider=providers.input_provider,
            policy_provider=providers.policy_provider,
            publication_provider=providers.publication_provider,
            bond_master_provider=providers.bond_master_provider,
            cash_flow_provider=providers.cash_flow_provider,
            calendar_provider=providers.calendar_provider,
            exact_owner_provider=providers.exact_owner_provider,
            data_center_unit_of_work=data_center,
            portfolio_unit_of_work=portfolio,
            research_unit_of_work=research,
        )


def test_owner_transaction_key_must_also_match_fixed_income_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    providers = _runner_graph(graph)
    data_center = _OwnerUnitOfWork("data_center", "django:other")
    portfolio = _OwnerUnitOfWork("portfolio", "django:other")
    research = _OwnerUnitOfWork("research", "django:other")

    with pytest.raises(
        R5RelativeValuePersistenceConflict,
        match="repository and owner ports",
    ):
        build_django_r5_relative_value_runtime(
            input_provider=providers.input_provider,
            policy_provider=providers.policy_provider,
            publication_provider=providers.publication_provider,
            bond_master_provider=providers.bond_master_provider,
            cash_flow_provider=providers.cash_flow_provider,
            calendar_provider=providers.calendar_provider,
            exact_owner_provider=providers.exact_owner_provider,
            data_center_unit_of_work=data_center,
            portfolio_unit_of_work=portfolio,
            research_unit_of_work=research,
        )
    assert all(not provider.calls for provider in providers.providers)


def test_missing_owner_unit_of_work_rolls_back_before_authoritative_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    providers = _runner_graph(graph)
    data_center = _OwnerUnitOfWork("data_center")
    portfolio = _InactiveOwnerUnitOfWork("portfolio")
    research = _OwnerUnitOfWork("research")
    runtime = build_django_r5_relative_value_runtime(
        input_provider=providers.input_provider,
        policy_provider=providers.policy_provider,
        publication_provider=providers.publication_provider,
        bond_master_provider=providers.bond_master_provider,
        cash_flow_provider=providers.cash_flow_provider,
        calendar_provider=providers.calendar_provider,
        exact_owner_provider=providers.exact_owner_provider,
        data_center_unit_of_work=data_center,
        portfolio_unit_of_work=portfolio,
        research_unit_of_work=research,
    )

    with pytest.raises(R5RelativeValuePersistenceConflict, match="inactive"):
        runtime.persist.execute(_persist_command(graph))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_public_query_repository_cannot_be_escalated_to_append_a_fabricated_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    run = _runner_graph(graph).runner.execute_authoritative(_command(graph))
    draft = R5RelativeValuePersistenceDraft.from_authoritative_run(run)
    repository = DjangoR5RelativeValueRepository()

    assert draft.expected_command_hash
    with pytest.raises(AttributeError):
        object.__setattr__(repository, "_write_capability", object())
    for old_write_surface in (
        "_atomic",
        "_authorize_owner_graph",
        "_append_verified",
        "_unit_of_work_token",
    ):
        with pytest.raises(AttributeError):
            object.__getattribute__(repository, old_write_surface)
    with pytest.raises(AttributeError):
        object.__getattribute__(
            relative_value_repository_module,
            "_build_r5_writable_repository",
        )
    runtime = _runtime(graph).runtime
    with pytest.raises(AttributeError):
        runtime.persist.execute(cast(PersistR5RelativeValueCommand, draft))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_runtime_writer_exposes_only_id_only_persist_and_no_mutable_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph).runtime
    writer = runtime.persist._writer

    assert not hasattr(writer, "__dict__")
    assert callable(writer.persist)
    for forbidden in (
        "append",
        "append_verified",
        "authorize",
        "atomic",
        "draft",
        "repository",
        "token",
        "write_capability",
        "_append_verified",
        "_authorize_owner_graph",
        "_atomic",
        "_repository",
        "_unit_of_work_token",
        "_write_capability",
    ):
        assert not hasattr(writer, forbidden)
    with pytest.raises(AttributeError):
        object.__setattr__(writer, "_unit_of_work_token", object())
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_trusted_path_rejects_command_a_when_phase_a_returns_run_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    original_execute = RunR5RelativeValueResearch.execute_authoritative

    def return_different_semantic_run(
        runner: RunR5RelativeValueResearch,
        command: RunR5RelativeValueResearchCommand,
    ) -> R5AuthoritativeRelativeValueRun:
        return original_execute(
            runner,
            replace(command, assessment_id=f"{command.assessment_id}-other"),
        )

    monkeypatch.setattr(
        RunR5RelativeValueResearch,
        "execute_authoritative",
        return_different_semantic_run,
    )
    runtime = _runtime(graph).runtime

    with pytest.raises(R5RelativeValuePersistenceConflict, match="does not authorize"):
        runtime.persist.execute(_persist_command(graph))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_different_graph_cannot_replay_same_assessment_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_graph = _fixture_graph(monkeypatch)
    _runtime(first_graph).runtime.persist.execute(_persist_command(first_graph))
    changed_graph = _fixture_graph(monkeypatch, omit_short_capacity=True)

    with pytest.raises(R5RelativeValuePersistenceConflict, match="different evidence"):
        _runtime(changed_graph).runtime.persist.execute(_persist_command(changed_graph))


def test_result_failure_rolls_back_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph).runtime

    def fail_save(self: FixedIncomeR5ResultModel, **kwargs: object) -> None:
        raise ValidationError("fault injection")

    monkeypatch.setattr(FixedIncomeR5ResultModel, "save", fail_save)
    with pytest.raises(R5RelativeValuePersistenceConflict, match="append conflict"):
        runtime.persist.execute(_persist_command(graph))
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 0
    assert FixedIncomeR5ResultModel._default_manager.count() == 0


def test_first_lookup_miss_replays_exact_persisted_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    first = _runtime(graph).runtime.persist.execute(_persist_command(graph))
    losing = _runtime(
        graph,
        clock=_Clock(_RECORDED_AT + timedelta(minutes=5)),
    )
    original_get = composition_module._get_r5_result_by_assessment_id
    first_call = True
    calls = 0

    def first_lookup_misses(
        assessment_id: str,
        *,
        using: str,
    ):
        nonlocal calls, first_call
        calls += 1
        if first_call:
            first_call = False
            return None
        return original_get(assessment_id, using=using)

    monkeypatch.setattr(
        composition_module,
        "_get_r5_result_by_assessment_id",
        first_lookup_misses,
    )
    replay = losing.runtime.persist.execute(_persist_command(graph))

    assert replay == first
    assert calls == 2
    assert FixedIncomeR5ResultModel._default_manager.count() == 1


def test_default_base_related_direct_and_bulk_paths_are_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    bundle = _runtime(graph).runtime.persist.execute(_persist_command(graph))
    receipt = FixedIncomeR5InputReceiptModel._default_manager.get(
        receipt_id=bundle.receipt.receipt_id
    )
    result = FixedIncomeR5ResultModel._default_manager.get(result_id=bundle.result.result_id)

    for manager, row in (
        (FixedIncomeR5InputReceiptModel._default_manager, receipt),
        (FixedIncomeR5InputReceiptModel._base_manager, receipt),
        (FixedIncomeR5ResultModel._default_manager, result),
        (FixedIncomeR5ResultModel._base_manager, result),
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.filter(pk=row.pk).update(content_hash="0" * 64)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError, match="bulk updated"):
            manager.bulk_update([row], [row._meta.pk.name])
        for kwargs in (
            {},
            {"ignore_conflicts": True},
            {
                "update_conflicts": True,
                "update_fields": [row._meta.pk.name],
                "unique_fields": [row._meta.pk.name],
            },
        ):
            with pytest.raises(ValidationError, match="exact append"):
                manager.all().bulk_create([type(row)()], **kwargs)
        with pytest.raises(ValidationError, match="exact repository insert claim"):
            manager.create()
        existing, created = manager.get_or_create(pk=row.pk)
        assert existing.pk == row.pk
        assert created is False
        with pytest.raises(ValidationError, match="exact repository insert claim"):
            manager.get_or_create(
                assessment_id=f"missing:{row._meta.label_lower}",
            )
        with pytest.raises(ValidationError, match="append-only"):
            manager.update_or_create(
                defaults={"content_hash": "0" * 64},
                pk=row.pk,
            )
        with pytest.raises(ValidationError, match="exact repository insert claim"):
            manager.update_or_create(
                defaults={"content_hash": "0" * 64},
                assessment_id=f"missing:{row._meta.label_lower}",
            )
    with pytest.raises(ValidationError, match="exact repository insert claim"):
        FixedIncomeR5InputReceiptModel._default_manager.create()
    with pytest.raises(ValidationError, match="exact repository insert claim"):
        receipt.relative_value_results.create()
    with pytest.raises(ValidationError, match="exact append"):
        receipt.relative_value_results.bulk_create([FixedIncomeR5ResultModel()])
    with pytest.raises(ValidationError, match="cannot be updated"):
        receipt.relative_value_results.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        receipt.relative_value_results.all().delete()
    with pytest.raises(ValidationError, match="bulk updated"):
        receipt.relative_value_results.bulk_update([result], ["output_hash"])
    existing_related, related_created = receipt.relative_value_results.get_or_create(pk=result.pk)
    assert existing_related.pk == result.pk
    assert related_created is False
    with pytest.raises(ValidationError, match="exact repository insert claim"):
        receipt.relative_value_results.get_or_create(
            assessment_id="missing:fixed-income-related-result",
        )
    with pytest.raises(ValidationError, match="append-only"):
        receipt.relative_value_results.update_or_create(
            defaults={"content_hash": "0" * 64},
            pk=result.pk,
        )
    with pytest.raises(ValidationError, match="exact repository insert claim"):
        receipt.relative_value_results.update_or_create(
            defaults={"content_hash": "0" * 64},
            assessment_id="missing:fixed-income-related-result",
        )
    with pytest.raises(ValidationError, match="append-only"):
        receipt.save()
    with pytest.raises(ValidationError, match="append-only"):
        result.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        receipt.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        result.delete()
    for model_type in (
        FixedIncomeR5InputReceiptModel,
        FixedIncomeR5ResultModel,
    ):
        with pytest.raises(ValidationError, match="append-only"):
            model_type(pk=0).save()
    for bulk, message in ((True, "cannot be updated"), (False, "append-only")):
        with pytest.raises(ValidationError, match=message):
            with transaction.atomic():
                receipt.relative_value_results.add(result, bulk=bulk)
        with pytest.raises(ValidationError, match=message):
            with transaction.atomic():
                receipt.relative_value_results.set([result], bulk=bulk)
    for row in (receipt, result):
        original_hash = row.content_hash
        row.content_hash = "0" * 64
        with pytest.raises(ValidationError, match="append-only"):
            row.save_base(
                force_update=True,
                update_fields={"content_hash"},
            )
        with pytest.raises(ValidationError, match="append-only"):
            models.Model.save(
                row,
                force_update=True,
                update_fields={"content_hash"},
            )
        row.refresh_from_db()
        assert row.content_hash == original_hash

        fabricated = type(row)()
        with pytest.raises(ValidationError, match="append-only"):
            fabricated.save_base(raw=True, force_insert=True)
        with pytest.raises(ValidationError, match="exact repository insert claim"):
            models.Model.save(fabricated, force_insert=True)
    assert FixedIncomeR5InputReceiptModel._default_manager.count() == 1
    assert FixedIncomeR5ResultModel._default_manager.count() == 1


def test_unbound_django_save_base_tamper_is_detected_by_exact_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat unbound Django base methods as boundary-external, then fail closed."""

    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph).runtime
    first = runtime.persist.execute(_persist_command(graph))
    result = FixedIncomeR5ResultModel._default_manager.get(result_id=first.result.result_id)

    result.output_hash = "0" * 64
    models.Model.save_base(
        result,
        force_update=True,
        update_fields={"output_hash"},
    )

    with pytest.raises(R5RelativeValuePersistenceCorruption):
        runtime.query.execute(
            GetExactR5RelativeValueCommand(
                result_id=first.result.result_id,
                result_version=first.result.result_version,
                expected_record_hash=first.result.record_hash,
                as_of=_RECORDED_AT + timedelta(hours=1),
            )
        )


@pytest.mark.parametrize(
    "target",
    (
        "receipt_header",
        "result_header",
        "result_content_hash",
        "result_recorded_at",
        "payload",
        "fk",
    ),
)
def test_raw_header_payload_and_fk_tamper_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runtime = _runtime(graph).runtime
    first = runtime.persist.execute(_persist_command(graph))
    first_result = FixedIncomeR5ResultModel._default_manager.get(result_id=first.result.result_id)
    if target == "receipt_header":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE fixed_income_r5_input_receipt " "SET input_set_hash = %s WHERE id = %s",
                ["0" * 64, first_result.receipt_id],
            )
    elif target == "result_header":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE fixed_income_r5_result SET output_hash = %s WHERE id = %s",
                ["0" * 64, first_result.pk],
            )
    elif target == "result_content_hash":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE fixed_income_r5_result SET content_hash = %s WHERE id = %s",
                ["0" * 64, first_result.pk],
            )
    elif target == "result_recorded_at":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE fixed_income_r5_result SET recorded_at = %s WHERE id = %s",
                [_RECORDED_AT + timedelta(days=1), first_result.pk],
            )
    elif target == "payload":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE fixed_income_r5_result SET canonical_payload = %s WHERE id = %s",
                [json.dumps({"schema": "tampered"}), first_result.pk],
            )
    else:
        second = runtime.persist.execute(
            _persist_command(graph, assessment_id="r5-assessment-second")
        )
        second_result = FixedIncomeR5ResultModel._default_manager.get(
            result_id=second.result.result_id
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM fixed_income_r5_result WHERE id = %s",
                [second_result.pk],
            )
            cursor.execute(
                "UPDATE fixed_income_r5_result SET receipt_id = %s WHERE id = %s",
                [second_result.receipt_id, first_result.pk],
            )

    with pytest.raises(R5RelativeValuePersistenceCorruption):
        runtime.query.execute(
            GetExactR5RelativeValueCommand(
                result_id=first.result.result_id,
                result_version=first.result.result_version,
                expected_record_hash=first.result.record_hash,
                as_of=_RECORDED_AT + timedelta(hours=1),
            )
        )
