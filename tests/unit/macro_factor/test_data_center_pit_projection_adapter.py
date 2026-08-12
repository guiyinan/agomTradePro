"""Narrow Macro Factor read adapter over Data Center canonical R3 evidence."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

from apps.data_center.domain.macro_factor_research_source import (
    CanonicalMacroFactorPITFact,
    CanonicalMacroFactorPITProjection,
    MacroFactorResearchMemberRole,
    PersistedMacroFactorResearchSourceDefinition,
)
from apps.macro_factor.infrastructure.data_center_pit_projection_adapter import (
    DataCenterMacroFactorPITProjectionAdapter,
)
from tests.unit.data_center.test_macro_factor_research_source import _definition

MANIFEST_AS_OF = datetime(2024, 5, 1, tzinfo=UTC)
MANIFEST_CREATED_AT = datetime(2024, 5, 2, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _projection() -> CanonicalMacroFactorPITProjection:
    definition = _definition()
    source = PersistedMacroFactorResearchSourceDefinition.create(
        definition=definition,
        ledger_recorded_at=datetime(2024, 1, 3, tzinfo=UTC),
    )
    periods = {item.row_id: item for item in definition.periods}
    facts = []
    for number, member in enumerate(definition.members, start=1):
        period = periods[member.row_id]
        effective_date = (
            period.target_period_end
            if member.role is MacroFactorResearchMemberRole.TARGET
            else period.observation_date
        )
        effective_at = datetime.combine(effective_date, time(9), tzinfo=UTC)
        available_at = datetime.combine(effective_date, time(10), tzinfo=UTC)
        facts.append(
            CanonicalMacroFactorPITFact(
                row_id=member.row_id,
                role=member.role,
                member_code=member.member_code,
                dataset_key=member.dataset_key,
                business_key=member.business_key,
                version_id=number,
                content_hash=HASH_A,
                payload_hash=HASH_B,
                source_record_id=f"source-record-{number}",
                revision_number=0,
                effective_at=effective_at,
                available_at=available_at,
                ingested_at=available_at,
                pit_quality="verified",
                value=Decimal(str(number)),
                unit=member.expected_unit,
            )
        )
    return CanonicalMacroFactorPITProjection(
        source=source,
        manifest_id="manifest-r3-growth",
        manifest_hash=HASH_A,
        manifest_as_of=MANIFEST_AS_OF,
        manifest_created_at=MANIFEST_CREATED_AT,
        knowledge_scope="public",
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        is_verified=True,
        facts=tuple(facts),
    )


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: CanonicalMacroFactorPITProjection | None) -> None:
        self.value = value
        self.calls: list[tuple[str, str | None]] = []

    def get_exact_projection(
        self,
        *,
        manifest_id: str,
        expected_manifest_hash: str | None = None,
    ) -> CanonicalMacroFactorPITProjection | None:
        self.calls.append((manifest_id, expected_manifest_hash))
        return self.value


def test_adapter_projects_manifest_and_label_free_dataset_without_writes() -> None:
    projection = _projection()
    provider = _Provider(projection)
    adapter = DataCenterMacroFactorPITProjectionAdapter(provider)

    manifest = adapter.get_manifest(projection.manifest_id)
    dataset = adapter.get_dataset(
        manifest_id=projection.manifest_id,
        manifest_hash=projection.manifest_hash,
        target_code="growth",
        candidate_asset_codes=("AU", "CU"),
    )

    assert manifest is not None
    assert manifest.manifest_hash == projection.manifest_hash
    assert manifest.calendar_hash == projection.source.definition.calendar.content_hash
    assert dataset is not None
    assert len(dataset.rows) == 2
    assert dataset.inference_row is not None
    assert dataset.inference_row.row_id == "inference-2024-03"
    assert provider.calls == [
        (projection.manifest_id, None),
        (projection.manifest_id, projection.manifest_hash),
    ]


def test_adapter_fails_closed_for_missing_or_substituted_exact_inputs() -> None:
    projection = _projection()
    adapter = DataCenterMacroFactorPITProjectionAdapter(_Provider(projection))

    assert (
        adapter.get_dataset(
            manifest_id=projection.manifest_id,
            manifest_hash=projection.manifest_hash,
            target_code="growth",
            candidate_asset_codes=("AU",),
        )
        is None
    )
    assert (
        DataCenterMacroFactorPITProjectionAdapter(_Provider(None)).get_manifest(
            projection.manifest_id
        )
        is None
    )
    assert adapter.get_manifest(" malformed ") is None

    object.__setattr__(projection.facts[0], "member_code", "substituted")
    assert (
        DataCenterMacroFactorPITProjectionAdapter(_Provider(projection)).get_manifest(
            projection.manifest_id
        )
        is None
    )
