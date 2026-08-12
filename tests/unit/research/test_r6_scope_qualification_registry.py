"""Contracts for the canonical R6 scope-to-qualification owner registry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from apps.research.application.r6_scope_qualification_registry import (
    RegisterR6ScopeQualificationBinding,
    RegisterR6ScopeQualificationBindingCommand,
)
from apps.research.domain.r6_scope_qualification_registry import (
    BINDING_SOURCE_RECEIPT_VERSION,
    R6ScopeQualificationBindingDefinition,
    R6ScopeQualificationSourceReceipt,
)
from apps.research.domain.state_model_activation import R6ActivationScope
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)

NOW = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)


def _definition() -> R6ScopeQualificationBindingDefinition:
    return R6ScopeQualificationBindingDefinition.create(
        binding_id="r6-scope-binding-1",
        binding_version="v1",
        scope=R6ActivationScope(
            scope_id="r6-state-model-advisory",
            scope_version="v1",
            purpose="manual-activation-review",
            label_protocol_version="labels-v1",
        ),
        qualification_ref=R6QualificationRef("qualification-1", "a" * 64),
        effective_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
    )


def _source() -> R6ScopeQualificationSourceReceipt:
    definition = _definition()
    return R6ScopeQualificationSourceReceipt.create(
        source_receipt_id="r6-scope-binding-source-1",
        source_receipt_version=BINDING_SOURCE_RECEIPT_VERSION,
        binding_id=definition.binding_id,
        binding_version=definition.binding_version,
        definition_hash=definition.content_hash,
        available_at=NOW - timedelta(hours=1),
        valid_until=definition.valid_until,
        evidence_ref="research:r6-scope-binding:owner-source",
    )


class _Provider:
    unit_of_work_key = "django:test"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.value


class _Clock:
    unit_of_work_key = "django:test"

    def __init__(self) -> None:
        self.inside_atomic = False

    def now(self) -> datetime:
        assert self.inside_atomic is True
        return NOW


class _Store:
    unit_of_work_key = "django:test"

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.append_calls = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.clock.inside_atomic = True
        try:
            yield
        finally:
            self.clock.inside_atomic = False

    def append(
        self,
        *,
        definition: R6ScopeQualificationBindingDefinition,
        source: R6ScopeQualificationSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R6ScopeQualificationBindingDefinition:
        assert source == _source()
        assert ledger_recorded_at == NOW
        self.append_calls += 1
        return definition


def test_registration_double_reads_owner_graph_inside_shared_uow() -> None:
    definition_provider = _Provider(_definition())
    source_provider = _Provider(_source())
    clock = _Clock()
    store = _Store(clock)
    service = RegisterR6ScopeQualificationBinding(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=clock,
    )

    result = service.execute(
        RegisterR6ScopeQualificationBindingCommand(
            binding_id="r6-scope-binding-1",
            binding_version="v1",
        )
    )

    assert result == _definition()
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.append_calls == 1
