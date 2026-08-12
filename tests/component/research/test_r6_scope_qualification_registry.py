"""Component proof for the canonical R6 scope-qualification owner registry."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.research.application.r6_scope_qualification_registry import (
    R6ScopeQualificationRegistryUnavailable,
    RegisterR6ScopeQualificationBindingCommand,
)
from apps.research.domain.r6_scope_qualification_registry import (
    BINDING_SOURCE_RECEIPT_VERSION,
    R6ScopeQualificationSourceReceipt,
)
from apps.research.infrastructure.r6_scope_qualification_models import (
    R6ScopeQualificationRegistryModel,
)
from apps.research.infrastructure.r6_scope_qualification_repository import (
    R6ScopeQualificationRepositoryConflict,
    R6ScopeQualificationRepositoryCorruption,
)
from apps.research.r6_scope_qualification_composition import (
    _build_django_r6_scope_qualification_registration_runtime,
    build_django_r6_scope_qualification_registry_runtime,
)
from tests.unit.research.test_r6_scope_qualification_registry import NOW, _definition


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value

    def get_exact(self, **kwargs: object) -> object:
        del kwargs
        return self.value


class _Clock:
    unit_of_work_key = "django:default"

    def now(self):  # type: ignore[no-untyped-def]
        return NOW


def _source(*, evidence_ref: str = "research:r6-scope-binding:source"):
    definition = _definition()
    return R6ScopeQualificationSourceReceipt.create(
        source_receipt_id="r6-scope-binding-source-1",
        source_receipt_version=BINDING_SOURCE_RECEIPT_VERSION,
        binding_id=definition.binding_id,
        binding_version=definition.binding_version,
        definition_hash=definition.content_hash,
        available_at=NOW - timedelta(hours=1),
        valid_until=definition.valid_until,
        evidence_ref=evidence_ref,
    )


def _runtime(*, source: object | None = None):  # type: ignore[no-untyped-def]
    return _build_django_r6_scope_qualification_registration_runtime(
        definition_provider=_Provider(_definition()),
        source_provider=_Provider(_source() if source is None else source),
        clock=_Clock(),
    )


def _command() -> RegisterR6ScopeQualificationBindingCommand:
    definition = _definition()
    return RegisterR6ScopeQualificationBindingCommand(
        definition.binding_id,
        definition.binding_version,
    )


@pytest.mark.django_db(transaction=True)
def test_registry_round_trip_exact_pit_and_orm_guards() -> None:
    runtime = _runtime()
    definition = runtime.register.execute(_command())
    assert runtime.register.execute(_command()) == definition
    assert R6ScopeQualificationRegistryModel._default_manager.count() == 1
    provider = runtime.owner_provider
    assert provider.get_exact(scope_id=definition.scope.scope_id, as_of=NOW) == definition.scope
    assert (
        provider.get_latest_active_ref(scope=definition.scope, as_of=NOW)
        == definition.qualification_ref
    )
    assert (
        provider.get_exact_binding(
            binding_id=definition.binding_id,
            binding_version=definition.binding_version,
            expected_definition_hash=definition.content_hash,
            as_of=NOW,
        )
        == definition
    )
    assert (
        provider.get_exact(
            scope_id=definition.scope.scope_id,
            as_of=definition.effective_at - timedelta(microseconds=1),
        )
        is None
    )

    row = R6ScopeQualificationRegistryModel._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R6ScopeQualificationRegistryModel._default_manager.update(scope_id="tampered")
    with pytest.raises(ValidationError):
        R6ScopeQualificationRegistryModel._base_manager.all().delete()
    with pytest.raises(ValidationError):
        R6ScopeQualificationRegistryModel._default_manager.bulk_create([row])


@pytest.mark.django_db(transaction=True)
def test_missing_fork_and_outer_rollback_are_zero_write() -> None:
    with pytest.raises(R6ScopeQualificationRegistryUnavailable):
        _runtime(source=False).register.execute(_command())
    assert R6ScopeQualificationRegistryModel._default_manager.count() == 0

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _runtime().register.execute(_command())
            raise RuntimeError("outer rollback")
    assert R6ScopeQualificationRegistryModel._default_manager.count() == 0

    _runtime().register.execute(_command())
    fork = _source(evidence_ref="research:r6-scope-binding:fork")
    with pytest.raises(R6ScopeQualificationRegistryUnavailable) as raised:
        _runtime(source=fork).register.execute(_command())
    assert isinstance(raised.value.__cause__, R6ScopeQualificationRepositoryConflict)
    assert R6ScopeQualificationRegistryModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_tamper_fails_closed_and_public_registration_is_zero_write() -> None:
    definition = _runtime().register.execute(_command())
    table = connection.ops.quote_name(R6ScopeQualificationRegistryModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET qualification_id = %s WHERE definition_hash = %s",
            ["tampered", definition.content_hash],
        )
    public = build_django_r6_scope_qualification_registry_runtime()
    with pytest.raises(R6ScopeQualificationRepositoryCorruption):
        public.owner_provider.get_exact(
            scope_id=definition.scope.scope_id,
            as_of=NOW,
        )
    with pytest.raises(R6ScopeQualificationRegistryUnavailable):
        public.register.execute(_command())
    assert R6ScopeQualificationRegistryModel._default_manager.count() == 1
