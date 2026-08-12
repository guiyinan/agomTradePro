"""SQLite contract for the canonical R3 macro-factor PIT source."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import Collector

from apps.data_center.application.macro_factor_research_source import (
    MacroFactorResearchSourceConflict,
    MacroFactorResearchSourceUnavailable,
    RegisterMacroFactorResearchSourceCommand,
)
from apps.data_center.domain.macro_factor_research_source import (
    MacroFactorResearchCalendar,
    MacroFactorResearchCoveragePolicy,
    MacroFactorResearchMemberRole,
    MacroFactorResearchMemberRule,
    MacroFactorResearchPeriodKind,
    MacroFactorResearchPeriodRule,
    MacroFactorResearchSourceDefinition,
    MacroFactorSourceSeal,
    MacroFactorValueEncoding,
)
from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    calculate_pit_manifest_hash,
)
from apps.data_center.infrastructure.macro_factor_research_source_models import (
    MacroFactorResearchCalendarPeriodModel,
    MacroFactorResearchMemberRuleModel,
    MacroFactorResearchSourceDefinitionModel,
)
from apps.data_center.infrastructure.pit_models import (
    PITDatasetManifestModel,
    PITFactVersionModel,
)
from apps.data_center.macro_factor_research_source_composition import (
    _build_django_macro_factor_research_source_test_runtime,
    _DjangoMacroFactorResearchSourceTestRuntime,
    build_django_macro_factor_research_source_runtime,
)
from apps.macro_factor.r3_pit_projection_composition import (
    build_macro_factor_r3_pit_read_runtime,
)

pytestmark = pytest.mark.django_db(transaction=True)

HASH_A = "a" * 64
HASH_B = "b" * 64
REGISTERED_AT = datetime(2025, 1, 1, 9, tzinfo=UTC)
CUTOFF = datetime(2025, 3, 3, 9, tzinfo=UTC)
VALID_UNTIL = datetime(2030, 1, 1, 9, tzinfo=UTC)


def _definition(
    *,
    source_contract_hash: str = HASH_A,
) -> MacroFactorResearchSourceDefinition:
    periods = (
        MacroFactorResearchPeriodRule(
            row_id="row-2025-01",
            period_id="target-2025-01",
            kind=MacroFactorResearchPeriodKind.HISTORICAL,
            observation_date=date(2025, 1, 31),
            target_period_start=date(2025, 2, 1),
            target_period_end=date(2025, 2, 28),
        ),
        MacroFactorResearchPeriodRule(
            row_id="row-2025-02",
            period_id="target-2025-02",
            kind=MacroFactorResearchPeriodKind.INFERENCE,
            observation_date=date(2025, 2, 28),
            target_period_start=date(2025, 3, 1),
            target_period_end=date(2025, 3, 31),
        ),
    )
    calendar = MacroFactorResearchCalendar.create(
        calendar_id="calendar:macro-monthly",
        calendar_version="calendar.v1",
        periods=periods,
    )
    members = (
        MacroFactorResearchMemberRule(
            row_id="row-2025-01",
            role=MacroFactorResearchMemberRole.TARGET,
            member_code="CPI_YOY",
            dataset_key="macro-target",
            business_key="CPI_YOY:2025-02",
            value_field="value",
            unit_field="unit",
            expected_unit="percent",
            value_encoding=MacroFactorValueEncoding.DECIMAL_TEXT,
        ),
        *tuple(
            MacroFactorResearchMemberRule(
                row_id=row_id,
                role=MacroFactorResearchMemberRole.PROXY,
                member_code=asset,
                dataset_key="market-proxy",
                business_key=f"{asset}:{row_id}",
                value_field="close",
                unit_field="unit",
                expected_unit="index",
                value_encoding=MacroFactorValueEncoding.JSON_NUMBER,
            )
            for row_id in ("row-2025-01", "row-2025-02")
            for asset in ("AU", "CU")
        ),
    )
    return MacroFactorResearchSourceDefinition.create(
        source_id="macro-factor-source:cpi",
        source_version="source.v1",
        target_code="CPI_YOY",
        candidate_asset_codes=("AU", "CU"),
        manifest_calendar_version="r3-calendar-manifest.v1",
        calendar=calendar,
        source_contract=MacroFactorSourceSeal(
            stable_id="pit-source-contract",
            version="contract.v1",
            content_hash=source_contract_hash,
        ),
        knowledge_scope="public",
        members=members,
        coverage_policy=MacroFactorResearchCoveragePolicy(
            require_verified=True,
            minimum_coverage_ratio=Decimal("1"),
            maximum_missing_count=0,
            maximum_estimated_count=0,
            maximum_unknown_count=0,
        ),
        registered_at=REGISTERED_AT,
        valid_until=VALID_UNTIL,
    )


class _Owner:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        definition: MacroFactorResearchSourceDefinition | None = None,
    ) -> None:
        self.definition = definition or _definition()

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> MacroFactorResearchSourceDefinition | None:
        definition = self.definition
        if (
            source_id != definition.source_id
            or source_version != definition.source_version
            or expected_content_hash != definition.content_hash
            or not definition.is_active_at(as_of)
        ):
            return None
        return definition


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return CUTOFF


def _command(
    definition: MacroFactorResearchSourceDefinition | None = None,
) -> RegisterMacroFactorResearchSourceCommand:
    definition = definition or _definition()
    return RegisterMacroFactorResearchSourceCommand(
        source_id=definition.source_id,
        source_version=definition.source_version,
        expected_content_hash=definition.content_hash,
        as_of=CUTOFF,
    )


def _runtime(
    owner: _Owner | None = None,
) -> _DjangoMacroFactorResearchSourceTestRuntime:
    return _build_django_macro_factor_research_source_test_runtime(
        definition_provider=owner or _Owner(),
        clock=_Clock(),
    )


def test_public_runtime_is_read_only_and_empty_state_blocks() -> None:
    runtime = build_django_macro_factor_research_source_runtime()
    macro_runtime = build_macro_factor_r3_pit_read_runtime()

    assert runtime.projection_provider.get_exact_projection(manifest_id="missing-manifest") is None
    with pytest.raises(MacroFactorResearchSourceUnavailable, match="owner"):
        runtime.register_source.execute(_command())
    assert macro_runtime.pit_provider.get_manifest("missing-manifest") is None
    for forbidden_surface in ("run", "current", "decision", "execute"):
        assert not hasattr(macro_runtime, forbidden_surface)
    assert not hasattr(runtime.register_source, "_store")
    assert MacroFactorResearchSourceDefinitionModel._default_manager.count() == 0
    assert MacroFactorResearchCalendarPeriodModel._default_manager.count() == 0
    assert MacroFactorResearchMemberRuleModel._default_manager.count() == 0


def test_private_runtime_registers_and_reads_exact_definition() -> None:
    runtime = _runtime()

    record = runtime.register_source.execute(_command())
    restored = runtime.source_repository.get_exact_source_definition(
        source_id=record.definition.source_id,
        source_version=record.definition.source_version,
        expected_content_hash=record.definition.content_hash,
        as_of=CUTOFF,
    )

    assert restored == record
    assert (
        runtime.source_repository.get_exact_source_definition(
            source_id=record.definition.source_id,
            source_version=record.definition.source_version,
            expected_content_hash=record.definition.content_hash,
            as_of=record.ledger_recorded_at.replace(microsecond=0).replace(day=2),
        )
        is None
    )


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _insert_fact(
    member: MacroFactorResearchMemberRule,
    *,
    revision: int = 0,
    omit_unit: bool = False,
) -> PITFactVersionModel:
    definition = _definition()
    period = next(item for item in definition.periods if item.row_id == member.row_id)
    effective_date = (
        period.target_period_end
        if member.role is MacroFactorResearchMemberRole.TARGET
        else period.observation_date
    )
    effective_at = datetime.combine(effective_date, time(9), tzinfo=UTC)
    payload: dict[str, object] = {
        member.value_field: (
            "2.50" if member.value_encoding is MacroFactorValueEncoding.DECIMAL_TEXT else 100.0
        )
    }
    if not omit_unit:
        payload[member.unit_field] = member.expected_unit
    content_hash = _stable_hash([member.dataset_key, member.business_key, revision, payload])
    return PITFactVersionModel._default_manager.create(
        dataset=member.dataset_key,
        business_key=member.business_key,
        effective_at=effective_at,
        effective_to=None,
        available_at=effective_at.replace(hour=10),
        ingested_at=effective_at.replace(hour=11),
        superseded_at=None,
        revision_number=revision,
        source_record_id=f"owner:{member.business_key}:{revision}",
        content_hash=content_hash,
        pit_quality="verified",
        payload=payload,
    )


def _manifest(
    *,
    manifest_id: str,
    selected_rows: tuple[PITFactVersionModel, ...],
    coverage: dict[str, float] | None = None,
) -> PITDatasetManifestModel:
    definition = _definition()
    query_spec: dict[str, dict[str, object]] = {}
    for member in definition.members:
        query_spec.setdefault(member.dataset_key, {"business_key__in": []})
        keys = query_spec[member.dataset_key]["business_key__in"]
        assert isinstance(keys, list)
        keys.append(member.business_key)
    query_spec = {
        dataset: {"business_key__in": sorted(value["business_key__in"])}
        for dataset, value in sorted(query_spec.items())
    }
    selected = [
        {
            "id": row.pk,
            "dataset": row.dataset,
            "business_key": row.business_key,
            "content_hash": row.content_hash,
            "payload_hash": _stable_hash(row.payload),
            "pit_quality": row.pit_quality,
        }
        for row in sorted(
            selected_rows,
            key=lambda item: (item.dataset, item.business_key, item.pk),
        )
    ]
    coverage = coverage or dict.fromkeys(query_spec, 1.0)
    unsigned = PITDatasetManifest(
        manifest_id=manifest_id,
        as_of_time=CUTOFF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version=definition.manifest_calendar_version,
        query_spec=query_spec,
        selected_versions=tuple(selected),
        coverage=coverage,
        missing=(),
        estimated=(),
        unknown=(),
        manifest_hash="",
    )
    manifest_hash = calculate_pit_manifest_hash(unsigned)
    return PITDatasetManifestModel._default_manager.create(
        manifest_id=manifest_id,
        as_of_time=CUTOFF,
        knowledge_scope="public",
        calendar_version=definition.manifest_calendar_version,
        query_spec=query_spec,
        selected_versions=selected,
        coverage=coverage,
        missing=[],
        estimated=[],
        unknown=[],
        manifest_hash=manifest_hash,
    )


def _registered_projection_runtime() -> tuple[
    _DjangoMacroFactorResearchSourceTestRuntime,
    tuple[PITFactVersionModel, ...],
]:
    runtime = _runtime()
    runtime.register_source.execute(_command())
    rows = tuple(_insert_fact(member) for member in _definition().members)
    return runtime, rows


def test_private_runtime_rebuilds_complete_exact_pit_projection() -> None:
    runtime, rows = _registered_projection_runtime()
    manifest = _manifest(manifest_id="manifest-r3-complete", selected_rows=rows)

    projection = runtime.projection_provider.get_exact_projection(
        manifest_id=manifest.manifest_id,
        expected_manifest_hash=manifest.manifest_hash,
    )

    assert projection is not None
    assert projection.source.definition == _definition()
    assert len(projection.facts) == len(_definition().members)
    assert projection.coverage_ratio == Decimal("1.0")
    assert all(item.pit_quality == "verified" for item in projection.facts)
    assert (
        runtime.projection_provider.get_exact_projection(
            manifest_id=manifest.manifest_id,
            expected_manifest_hash=HASH_B,
        )
        is None
    )


def test_projection_fails_closed_for_missing_value_coverage_or_multiple_versions() -> None:
    runtime, rows = _registered_projection_runtime()
    first_member = _definition().members[0]
    bad_unit = _insert_fact(first_member, revision=9, omit_unit=True)
    bad_rows = (bad_unit,) + tuple(
        row
        for row in rows
        if (row.dataset, row.business_key) != (first_member.dataset_key, first_member.business_key)
    )
    bad_manifest = _manifest(
        manifest_id="manifest-r3-missing-unit",
        selected_rows=bad_rows,
    )
    partial = _manifest(
        manifest_id="manifest-r3-partial-coverage",
        selected_rows=rows,
        coverage={"macro-target": 1.0, "market-proxy": 0.5},
    )
    forked = _manifest(
        manifest_id="manifest-r3-multiple-revisions",
        selected_rows=rows + (bad_unit,),
    )

    assert (
        runtime.projection_provider.get_exact_projection(manifest_id=bad_manifest.manifest_id)
        is None
    )
    assert runtime.projection_provider.get_exact_projection(manifest_id=partial.manifest_id) is None
    assert runtime.projection_provider.get_exact_projection(manifest_id=forked.manifest_id) is None


def test_identical_registration_wins_and_owner_fork_conflicts() -> None:
    owner = _Owner()
    runtime = _runtime(owner)
    first = runtime.register_source.execute(_command(owner.definition))

    assert runtime.register_source.execute(_command(owner.definition)) == first
    owner.definition = _definition(source_contract_hash=HASH_B)
    with pytest.raises(MacroFactorResearchSourceConflict):
        runtime.register_source.execute(_command(owner.definition))
    assert MacroFactorResearchSourceDefinitionModel._default_manager.count() == 1
    assert MacroFactorResearchCalendarPeriodModel._default_manager.count() == 2
    assert MacroFactorResearchMemberRuleModel._default_manager.count() == 5


def test_outer_transaction_rollback_removes_the_complete_registration_graph() -> None:
    runtime = _runtime()
    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            runtime.register_source.execute(_command())
            raise RuntimeError("outer rollback")
    assert MacroFactorResearchSourceDefinitionModel._default_manager.count() == 0
    assert MacroFactorResearchCalendarPeriodModel._default_manager.count() == 0
    assert MacroFactorResearchMemberRuleModel._default_manager.count() == 0


def test_all_source_ledger_mutation_paths_are_guarded() -> None:
    runtime = _runtime()
    runtime.register_source.execute(_command())
    rows = (
        MacroFactorResearchSourceDefinitionModel._default_manager.get(),
        MacroFactorResearchCalendarPeriodModel._default_manager.first(),
        MacroFactorResearchMemberRuleModel._default_manager.first(),
    )
    assert all(row is not None for row in rows)
    for row in rows:
        assert row is not None
        with pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError):
            row.delete()
        with pytest.raises(ValidationError):
            type(row)._default_manager.filter(pk=row.pk).update(canonical_payload={})
        with pytest.raises(ValidationError):
            type(row)._default_manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError):
            type(row)._default_manager.bulk_create([row])
        with pytest.raises(ValidationError):
            type(row)._default_manager.create()
        with pytest.raises(ValidationError):
            row.save_base(force_update=True)
        private_queryset = type(row)._base_manager.filter(pk=row.pk)
        with pytest.raises(ValidationError):
            private_queryset._raw_delete("default")
        with pytest.raises(ValidationError):
            private_queryset._update([])
        with pytest.raises(ValidationError):
            private_queryset._batched_insert([], [], 1)

    member = rows[2]
    assert member is not None
    collector = Collector(using="default")
    collector.collect([member])
    with pytest.raises(ValidationError):
        with transaction.atomic():
            collector.delete()
    assert MacroFactorResearchMemberRuleModel._default_manager.count() == 5
