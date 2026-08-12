"""Component contracts for the append-only R7 analogy/path owner registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from inspect import signature

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.research.application.r7_analogy_path_owner import (
    R7AnalogyPathOwnerUnavailable,
    RegisterHistoricalAnalogyDefinitionCommand,
    RegisterHistoricalAnalogyReceiptCommand,
    RegisterScenarioPathDefinitionCommand,
    RegisterScenarioPathReceiptCommand,
)
from apps.research.domain.r7_analogy_path_owner import (
    HistoricalAnalogyRawSource,
)
from apps.research.infrastructure.r7_analogy_path_owner_models import (
    R7HistoricalAnalogyCandidateModel,
    R7HistoricalAnalogyDefinitionModel,
    R7HistoricalAnalogyReceiptModel,
    R7ScenarioPathDefinitionModel,
    R7ScenarioPathMemberModel,
    R7ScenarioPathReceiptModel,
)
from apps.research.infrastructure.r7_analogy_path_owner_repository import (
    R7AnalogyPathOwnerConflict,
    _analogy_receipt_values,
)
from apps.research.r7_analogy_path_owner_composition import (
    _build_django_r7_analogy_path_owner_test_runtime,
    build_django_r7_analogy_path_owner_runtime,
)
from tests.unit.research.test_r7_analogy_path_owner import (
    NOW,
    _analogy_definition,
    _analogy_receipt,
    _path_definition,
    _path_receipt,
)


@dataclass
class _Clock:
    value: datetime = NOW
    unit_of_work_key: str = "django:default"

    def now(self) -> datetime:
        return self.value


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value

    def get_exact(self, **selectors: object) -> object:
        del selectors
        return self.value


def _runtime():  # type: ignore[no-untyped-def]
    return _build_django_r7_analogy_path_owner_test_runtime(
        analogy_definition_source=_Provider(_analogy_definition()),
        analogy_raw_source=_Provider(_analogy_receipt().source),
        path_definition_source=_Provider(_path_definition()),
        path_raw_source=_Provider(_path_receipt().source),
        clock=_Clock(),
    )


def _register_all(runtime):  # type: ignore[no-untyped-def]
    analogy_definition = _analogy_definition()
    path_definition = _path_definition()
    runtime.register_analogy_definition.execute(
        RegisterHistoricalAnalogyDefinitionCommand(
            definition_id=analogy_definition.definition_id,
            definition_version=analogy_definition.definition_version,
            as_of=NOW,
        )
    )
    runtime.register_path_definition.execute(
        RegisterScenarioPathDefinitionCommand(
            definition_id=path_definition.definition_id,
            definition_version=path_definition.definition_version,
            as_of=NOW,
        )
    )
    analogy = _analogy_receipt()
    path = _path_receipt()
    runtime.register_analogy_receipt.execute(
        RegisterHistoricalAnalogyReceiptCommand(
            definition_id=analogy.definition.definition_id,
            definition_version=analogy.definition.definition_version,
            receipt_id=analogy.receipt_id,
            receipt_version=analogy.receipt_version,
            as_of=analogy.source.query_manifest.as_of,
        )
    )
    runtime.register_path_receipt.execute(
        RegisterScenarioPathReceiptCommand(
            definition_id=path.definition.definition_id,
            definition_version=path.definition.definition_version,
            receipt_id=path.receipt_id,
            receipt_version=path.receipt_version,
            as_of=path.source.pit_manifest.as_of,
        )
    )
    return analogy, path


@pytest.mark.django_db
def test_empty_public_readers_return_none_and_mutation_is_inert() -> None:
    runtime = build_django_r7_analogy_path_owner_runtime()

    assert tuple(signature(build_django_r7_analogy_path_owner_runtime).parameters) == ("using",)
    assert (
        runtime.historical_analogy_provider.get_exact(scope=_analogy_definition().scope, as_of=NOW)
        is None
    )
    assert runtime.path_study_provider.get_exact(scope=_path_definition().scope, as_of=NOW) is None
    facade = runtime.register_analogy_definition
    assert type(facade).__slots__ == ()
    assert not hasattr(facade, "__dict__")
    with pytest.raises(R7AnalogyPathOwnerUnavailable, match="unavailable"):
        facade.execute(
            RegisterHistoricalAnalogyDefinitionCommand(
                definition_id="r7-analogy:macro-regime",
                definition_version="r7-analogy-definition.v1",
                as_of=NOW,
            )
        )
    assert R7HistoricalAnalogyDefinitionModel._default_manager.count() == 0


@pytest.mark.django_db
def test_private_id_only_registration_roundtrips_both_exact_pit_adapters() -> None:
    runtime = _runtime()
    analogy, path = _register_all(runtime)

    assert R7HistoricalAnalogyDefinitionModel._default_manager.count() == 1
    assert R7HistoricalAnalogyReceiptModel._default_manager.count() == 1
    assert R7HistoricalAnalogyCandidateModel._default_manager.count() == len(
        analogy.source.candidates
    )
    assert R7ScenarioPathDefinitionModel._default_manager.count() == 1
    assert R7ScenarioPathReceiptModel._default_manager.count() == 1
    assert R7ScenarioPathMemberModel._default_manager.count() == len(
        path.source.sample_members
    ) + len(path.source.shocks)
    assert (
        runtime.historical_analogy_provider.get_exact(scope=analogy.definition.scope, as_of=NOW)
        == analogy.to_study_evidence()
    )
    assert (
        runtime.path_study_provider.get_exact(scope=path.definition.scope, as_of=NOW)
        == path.to_study_evidence()
    )
    assert (
        runtime.historical_analogy_provider.get_exact(
            scope=analogy.definition.scope,
            as_of=analogy.recorded_at - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_exact_replay_is_idempotent_and_identity_fork_fails_closed() -> None:
    runtime = _runtime()
    analogy, _ = _register_all(runtime)
    before = R7HistoricalAnalogyReceiptModel._default_manager.count()

    runtime.register_analogy_receipt.execute(
        RegisterHistoricalAnalogyReceiptCommand(
            definition_id=analogy.definition.definition_id,
            definition_version=analogy.definition.definition_version,
            receipt_id=analogy.receipt_id,
            receipt_version=analogy.receipt_version,
            as_of=analogy.source.query_manifest.as_of,
        )
    )
    assert R7HistoricalAnalogyReceiptModel._default_manager.count() == before

    source = analogy.source
    runtime.analogy_raw_source.value = HistoricalAnalogyRawSource.create(
        query_manifest=source.query_manifest,
        query_features=source.query_features,
        candidates=source.candidates,
        available_at=source.available_at,
        evidence_refs=(*source.evidence_refs, "data-center:analogy-fork"),
    )
    with pytest.raises((R7AnalogyPathOwnerConflict, R7AnalogyPathOwnerUnavailable)):
        runtime.register_analogy_receipt.execute(
            RegisterHistoricalAnalogyReceiptCommand(
                definition_id=analogy.definition.definition_id,
                definition_version=analogy.definition.definition_version,
                receipt_id=analogy.receipt_id,
                receipt_version=analogy.receipt_version,
                as_of=analogy.source.query_manifest.as_of,
            )
        )
    assert R7HistoricalAnalogyReceiptModel._default_manager.count() == before


@pytest.mark.django_db
def test_member_failure_rolls_back_receipt_and_all_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    analogy_definition = _analogy_definition()
    runtime.register_analogy_definition.execute(
        RegisterHistoricalAnalogyDefinitionCommand(
            definition_id=analogy_definition.definition_id,
            definition_version=analogy_definition.definition_version,
            as_of=NOW,
        )
    )

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise IntegrityError("candidate insert failed")

    monkeypatch.setattr(R7HistoricalAnalogyCandidateModel, "save", fail)
    analogy = _analogy_receipt()
    with pytest.raises((R7AnalogyPathOwnerConflict, R7AnalogyPathOwnerUnavailable)):
        runtime.register_analogy_receipt.execute(
            RegisterHistoricalAnalogyReceiptCommand(
                definition_id=analogy.definition.definition_id,
                definition_version=analogy.definition.definition_version,
                receipt_id=analogy.receipt_id,
                receipt_version=analogy.receipt_version,
                as_of=analogy.source.query_manifest.as_of,
            )
        )
    assert R7HistoricalAnalogyReceiptModel._default_manager.count() == 0
    assert R7HistoricalAnalogyCandidateModel._default_manager.count() == 0


@pytest.mark.django_db
def test_header_tamper_and_public_orm_mutation_paths_fail_closed() -> None:
    runtime = _runtime()
    analogy, _ = _register_all(runtime)
    row = R7HistoricalAnalogyReceiptModel._default_manager.get()

    row.receipt_hash = "0" * 64
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError):
        R7HistoricalAnalogyReceiptModel._default_manager.update(receipt_hash="0" * 64)
    with pytest.raises(ValidationError):
        row.delete()

    values = _analogy_receipt_values(analogy, row.definition_id)
    assert values["receipt_hash"] == analogy.content_hash
