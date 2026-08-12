"""Regime-owned canonical historical-assignment contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.regime.application.historical_assignment import (
    HistoricalRegimeAssignmentUnavailable,
    MaterializeHistoricalRegimeAssignment,
    MaterializeHistoricalRegimeAssignmentCommand,
    RegisterHistoricalRegimeAssignmentDefinition,
    RegisterHistoricalRegimeAssignmentDefinitionCommand,
)
from apps.regime.domain.historical_assignment import (
    CanonicalRegimeSourceFact,
    HistoricalRegimeAssignmentDefinition,
    HistoricalRegimeAssignmentReceipt,
    PersistedHistoricalRegimeAssignmentDefinition,
    RegimeArtifactOOSProjection,
    RegimeAssignmentCell,
    RegimeAssignmentExpectedRow,
    RegimeAssignmentFactRole,
    RegimeAssignmentPolicy,
    RegimeAssignmentSourceRule,
    RegimeOOSPrediction,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
REGISTERED_AT = datetime(2023, 12, 1, tzinfo=UTC)
OBSERVATION_1 = datetime(2024, 1, 1, tzinfo=UTC)
OBSERVATION_2 = datetime(2024, 1, 2, tzinfo=UTC)
PIT_AS_OF = datetime(2024, 1, 11, tzinfo=UTC)
SERVER_NOW = PIT_AS_OF
VALID_UNTIL = datetime(2025, 1, 1, tzinfo=UTC)


def _policy() -> RegimeAssignmentPolicy:
    return RegimeAssignmentPolicy.create(
        policy_id="regime-policy:quadrant",
        policy_version="policy.v1",
        source_contract_id="source-contract:regime-r3",
        source_contract_version="contract.v1",
        source_contract_hash=HASH_A,
        growth_threshold=Decimal("0"),
        inflation_threshold=Decimal("0"),
        cells=(
            RegimeAssignmentCell(False, False, "Deflation"),
            RegimeAssignmentCell(False, True, "Stagflation"),
            RegimeAssignmentCell(True, False, "Recovery"),
            RegimeAssignmentCell(True, True, "Overheat"),
        ),
    )


def _rules(row_id: str) -> tuple[RegimeAssignmentSourceRule, ...]:
    return tuple(
        RegimeAssignmentSourceRule(
            role=role,
            dataset_key=f"regime-{role.value}",
            business_key=f"{row_id}:{role.value}",
            expected_unit="index",
        )
        for role in RegimeAssignmentFactRole
    )


def _definition() -> HistoricalRegimeAssignmentDefinition:
    return HistoricalRegimeAssignmentDefinition.create(
        definition_id="regime-assignment-definition:r3-growth",
        definition_version="definition.v1",
        artifact_id=HASH_B,
        artifact_hash=HASH_C,
        pit_manifest_id="pit-manifest:r3-growth",
        pit_manifest_hash=HASH_D,
        policy=_policy(),
        rows=(
            RegimeAssignmentExpectedRow(
                fold_id="outer-1",
                row_id="row-1",
                observation_at=OBSERVATION_1,
                source_rules=_rules("row-1"),
            ),
            RegimeAssignmentExpectedRow(
                fold_id="outer-2",
                row_id="row-2",
                observation_at=OBSERVATION_2,
                source_rules=_rules("row-2"),
            ),
        ),
        registered_at=REGISTERED_AT,
        valid_until=VALID_UNTIL,
    )


def _persisted_definition() -> PersistedHistoricalRegimeAssignmentDefinition:
    return PersistedHistoricalRegimeAssignmentDefinition.create(
        definition=_definition(),
        ledger_recorded_at=REGISTERED_AT,
    )


def _artifact() -> RegimeArtifactOOSProjection:
    return RegimeArtifactOOSProjection(
        artifact_id=HASH_B,
        artifact_hash=HASH_C,
        source_result_hash=HASH_E,
        pit_manifest_id="pit-manifest:r3-growth",
        pit_manifest_hash=HASH_D,
        predictions=(
            RegimeOOSPrediction("outer-1", "row-1", Decimal("9")),
            RegimeOOSPrediction("outer-2", "row-2", Decimal("18")),
        ),
    )


def _facts() -> tuple[CanonicalRegimeSourceFact, ...]:
    values = {
        ("row-1", RegimeAssignmentFactRole.ACTUAL): Decimal("10"),
        ("row-1", RegimeAssignmentFactRole.GROWTH): Decimal("1"),
        ("row-1", RegimeAssignmentFactRole.INFLATION): Decimal("-1"),
        ("row-2", RegimeAssignmentFactRole.ACTUAL): Decimal("20"),
        ("row-2", RegimeAssignmentFactRole.GROWTH): Decimal("-1"),
        ("row-2", RegimeAssignmentFactRole.INFLATION): Decimal("1"),
    }
    hashes = {
        RegimeAssignmentFactRole.ACTUAL: "1" * 64,
        RegimeAssignmentFactRole.GROWTH: "2" * 64,
        RegimeAssignmentFactRole.INFLATION: "3" * 64,
    }
    observations = {"row-1": OBSERVATION_1, "row-2": OBSERVATION_2}
    facts: list[CanonicalRegimeSourceFact] = []
    for row_id in ("row-1", "row-2"):
        for role in RegimeAssignmentFactRole:
            effective_at = observations[row_id]
            available_at = (
                effective_at
                if role is not RegimeAssignmentFactRole.ACTUAL
                else effective_at.replace(day=effective_at.day + 2)
            )
            facts.append(
                CanonicalRegimeSourceFact(
                    role=role,
                    dataset_key=f"regime-{role.value}",
                    business_key=f"{row_id}:{role.value}",
                    fact_id=f"fact:{row_id}:{role.value}",
                    fact_version="fact.v1",
                    content_hash=hashes[role],
                    pit_manifest_id="pit-manifest:r3-growth",
                    pit_manifest_hash=HASH_D,
                    effective_at=effective_at,
                    available_at=available_at,
                    owner_recorded_at=available_at,
                    value=values[(row_id, role)],
                    unit="index",
                    verified=True,
                )
            )
    return tuple(sorted(facts, key=lambda item: (item.business_key, item.role.value)))


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return SERVER_NOW


class _DefinitionOwner:
    unit_of_work_key = "django:default"

    def __init__(self, values: tuple[HistoricalRegimeAssignmentDefinition | None, ...]) -> None:
        self.values = list(values)
        self.calls: list[datetime] = []

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentDefinition | None:
        self.calls.append(as_of)
        return self.values.pop(0)


class _DefinitionRepository:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[PersistedHistoricalRegimeAssignmentDefinition | None, ...],
    ) -> None:
        self.values = list(values)
        self.calls: list[datetime] = []

    def get_exact_definition(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedHistoricalRegimeAssignmentDefinition | None:
        self.calls.append(as_of)
        return self.values.pop(0)


class _ArtifactProvider:
    unit_of_work_key = "django:default"

    def __init__(self, values: tuple[RegimeArtifactOOSProjection | None, ...]) -> None:
        self.values = list(values)
        self.calls = 0

    def get_exact_projection(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> RegimeArtifactOOSProjection | None:
        self.calls += 1
        return self.values.pop(0)


class _FactProvider:
    unit_of_work_key = "django:default"

    def __init__(self, values: tuple[tuple[CanonicalRegimeSourceFact, ...] | None, ...]) -> None:
        self.values = list(values)
        self.calls = 0

    def get_exact_facts(
        self,
        *,
        definition: HistoricalRegimeAssignmentDefinition,
        as_of: datetime,
    ) -> tuple[CanonicalRegimeSourceFact, ...] | None:
        self.calls += 1
        return self.values.pop(0)


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self, *, fail_receipt: bool = False) -> None:
        self.definitions: list[PersistedHistoricalRegimeAssignmentDefinition] = []
        self.receipts: list[HistoricalRegimeAssignmentReceipt] = []
        self.atomic_entries = 0
        self.fail_receipt = fail_receipt

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        definition_count = len(self.definitions)
        receipt_count = len(self.receipts)
        try:
            yield
        except Exception:
            del self.definitions[definition_count:]
            del self.receipts[receipt_count:]
            raise

    def append_definition(
        self,
        value: PersistedHistoricalRegimeAssignmentDefinition,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        self.definitions.append(value)
        return value

    def append_receipt(
        self,
        value: HistoricalRegimeAssignmentReceipt,
    ) -> HistoricalRegimeAssignmentReceipt:
        self.receipts.append(value)
        if self.fail_receipt:
            raise RuntimeError("forced receipt failure")
        return value


def _register_command() -> RegisterHistoricalRegimeAssignmentDefinitionCommand:
    definition = _definition()
    return RegisterHistoricalRegimeAssignmentDefinitionCommand(
        definition_id=definition.definition_id,
        definition_version=definition.definition_version,
        expected_content_hash=definition.content_hash,
        as_of=REGISTERED_AT,
    )


def _materialize_command() -> MaterializeHistoricalRegimeAssignmentCommand:
    definition = _definition()
    return MaterializeHistoricalRegimeAssignmentCommand(
        definition_id=definition.definition_id,
        definition_version=definition.definition_version,
        expected_content_hash=definition.content_hash,
        as_of=PIT_AS_OF,
    )


def test_definition_seals_complete_policy_calendar_and_source_rules() -> None:
    definition = _definition()

    assert definition.validated_copy() == definition
    assert definition.policy.content_hash == _policy().content_hash
    assert len(definition.rows) == 2
    assert all(len(row.source_rules) == 3 for row in definition.rows)
    assert len(definition.content_hash) == 64


def test_id_only_definition_registration_uses_server_clock_and_owner_rereads() -> None:
    definition = _definition()
    owner = _DefinitionOwner((definition,) * 4)
    store = _Store()

    persisted = RegisterHistoricalRegimeAssignmentDefinition(
        definition_provider=owner,
        store=store,
        clock=_Clock(),
    ).execute(_register_command())

    assert persisted.ledger_recorded_at == SERVER_NOW
    assert owner.calls == [REGISTERED_AT, SERVER_NOW, SERVER_NOW, SERVER_NOW]
    assert store.definitions == [persisted]
    assert store.atomic_entries == 1


def test_materialization_derives_assignments_from_exact_artifact_and_pit_facts() -> None:
    definition = _persisted_definition()
    artifact = _artifact()
    facts = _facts()
    definitions = _DefinitionRepository((definition,) * 4)
    artifacts = _ArtifactProvider((artifact,) * 4)
    fact_provider = _FactProvider((facts,) * 4)
    store = _Store()

    receipt = MaterializeHistoricalRegimeAssignment(
        definition_repository=definitions,
        artifact_provider=artifacts,
        fact_provider=fact_provider,
        store=store,
        clock=_Clock(),
    ).execute(_materialize_command())

    assert receipt.pit_as_of == PIT_AS_OF
    assert receipt.recorded_at == SERVER_NOW
    assert tuple(item.regime_code for item in receipt.assignments) == (
        "Recovery",
        "Stagflation",
    )
    assert tuple(item.actual_value for item in receipt.assignments) == (
        Decimal("10"),
        Decimal("20"),
    )
    assert definitions.calls == [PIT_AS_OF] * 4
    assert artifacts.calls == 4
    assert fact_provider.calls == 4
    assert store.receipts == [receipt]


@pytest.mark.parametrize(
    "field_name,replacement",
    (
        ("_definition_repository", _DefinitionRepository((_persisted_definition(),) * 4)),
        ("_artifact_provider", _ArtifactProvider((_artifact(),) * 4)),
        ("_fact_provider", _FactProvider((_facts(),) * 4)),
        ("_store", _Store()),
        ("_clock", _Clock()),
    ),
)
def test_materialization_rejects_live_participant_replacement_before_reads_or_writes(
    field_name: str,
    replacement: object,
) -> None:
    definitions = _DefinitionRepository((_persisted_definition(),) * 4)
    artifacts = _ArtifactProvider((_artifact(),) * 4)
    facts = _FactProvider((_facts(),) * 4)
    store = _Store()
    use_case = MaterializeHistoricalRegimeAssignment(
        definition_repository=definitions,
        artifact_provider=artifacts,
        fact_provider=facts,
        store=store,
        clock=_Clock(),
    )
    object.__setattr__(use_case, field_name, replacement)

    with pytest.raises(HistoricalRegimeAssignmentUnavailable, match="participant changed"):
        use_case.execute(_materialize_command())

    assert definitions.calls == []
    assert artifacts.calls == 0
    assert facts.calls == 0
    assert store.receipts == []
    assert store.atomic_entries == 0


def test_changed_fact_graph_and_store_failure_leave_zero_writes() -> None:
    changed_facts = list(_facts())
    object.__setattr__(changed_facts[0], "value", Decimal("99"))
    store = _Store()
    with pytest.raises(HistoricalRegimeAssignmentUnavailable, match="owner graph changed"):
        MaterializeHistoricalRegimeAssignment(
            definition_repository=_DefinitionRepository((_persisted_definition(),) * 4),
            artifact_provider=_ArtifactProvider((_artifact(),) * 4),
            fact_provider=_FactProvider((_facts(), tuple(changed_facts))),
            store=store,
            clock=_Clock(),
        ).execute(_materialize_command())
    assert store.receipts == []

    rollback_store = _Store(fail_receipt=True)
    with pytest.raises(HistoricalRegimeAssignmentUnavailable):
        MaterializeHistoricalRegimeAssignment(
            definition_repository=_DefinitionRepository((_persisted_definition(),) * 4),
            artifact_provider=_ArtifactProvider((_artifact(),) * 4),
            fact_provider=_FactProvider((_facts(),) * 4),
            store=rollback_store,
            clock=_Clock(),
        ).execute(_materialize_command())
    assert rollback_store.receipts == []
