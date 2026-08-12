"""R3 Data Center-owned source-definition and PIT projection contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.application.macro_factor_research_source import (
    MacroFactorResearchSourceUnavailable,
    RegisterMacroFactorResearchSource,
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
    PersistedMacroFactorResearchSourceDefinition,
)
from apps.data_center.infrastructure.macro_factor_research_source_codec import (
    MacroFactorResearchSourceCodecError,
    decode_persisted_macro_factor_research_source,
    encode_persisted_macro_factor_research_source,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
REGISTERED_AT = datetime(2024, 1, 1, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 1, 1, tzinfo=UTC)
SERVER_NOW = datetime(2024, 1, 3, tzinfo=UTC)
AS_OF = datetime(2024, 1, 2, tzinfo=UTC)


def _periods() -> tuple[MacroFactorResearchPeriodRule, ...]:
    return (
        MacroFactorResearchPeriodRule(
            row_id="row-2024-01",
            period_id="target-2024-02",
            kind=MacroFactorResearchPeriodKind.HISTORICAL,
            observation_date=date(2024, 1, 31),
            target_period_start=date(2024, 2, 1),
            target_period_end=date(2024, 2, 29),
        ),
        MacroFactorResearchPeriodRule(
            row_id="row-2024-02",
            period_id="target-2024-03",
            kind=MacroFactorResearchPeriodKind.HISTORICAL,
            observation_date=date(2024, 2, 29),
            target_period_start=date(2024, 3, 1),
            target_period_end=date(2024, 3, 31),
        ),
        MacroFactorResearchPeriodRule(
            row_id="inference-2024-03",
            period_id="target-2024-04",
            kind=MacroFactorResearchPeriodKind.INFERENCE,
            observation_date=date(2024, 3, 29),
            target_period_start=date(2024, 4, 1),
            target_period_end=date(2024, 4, 30),
        ),
    )


def _members() -> tuple[MacroFactorResearchMemberRule, ...]:
    members: list[MacroFactorResearchMemberRule] = []
    for period in _periods():
        for asset_code in ("AU", "CU"):
            members.append(
                MacroFactorResearchMemberRule(
                    row_id=period.row_id,
                    role=MacroFactorResearchMemberRole.PROXY,
                    member_code=asset_code,
                    dataset_key="proxy-price",
                    business_key=f"{asset_code}:{period.observation_date.isoformat()}",
                    value_field="value",
                    unit_field="unit",
                    expected_unit="index",
                    value_encoding=MacroFactorValueEncoding.DECIMAL_TEXT,
                )
            )
        if period.kind is MacroFactorResearchPeriodKind.HISTORICAL:
            members.append(
                MacroFactorResearchMemberRule(
                    row_id=period.row_id,
                    role=MacroFactorResearchMemberRole.TARGET,
                    member_code="growth",
                    dataset_key="macro-target",
                    business_key=f"growth:{period.period_id}",
                    value_field="value",
                    unit_field="unit",
                    expected_unit="pct",
                    value_encoding=MacroFactorValueEncoding.DECIMAL_TEXT,
                )
            )
    return tuple(members)


def _definition() -> MacroFactorResearchSourceDefinition:
    return MacroFactorResearchSourceDefinition.create(
        source_id="macro-factor-source:growth",
        source_version="source.v1",
        target_code="growth",
        candidate_asset_codes=("AU", "CU"),
        manifest_calendar_version="mf-growth-v1",
        calendar=MacroFactorResearchCalendar.create(
            calendar_id="calendar:growth",
            calendar_version="calendar.v1",
            periods=_periods(),
        ),
        source_contract=MacroFactorSourceSeal(
            "dataset-contract:macro-factor",
            "contract.v1",
            HASH_B,
        ),
        knowledge_scope="public",
        members=_members(),
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


def test_definition_seals_complete_calendar_period_and_member_rules() -> None:
    definition = _definition()

    assert definition.validated_copy() == definition
    assert len(definition.periods) == 3
    assert len(definition.members) == 8
    assert definition.inference_period.row_id == "inference-2024-03"
    assert definition.coverage_policy.minimum_coverage_ratio == Decimal("1")
    assert len(definition.content_hash) == 64


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return SERVER_NOW


class _DefinitionProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[MacroFactorResearchSourceDefinition | None, ...],
    ) -> None:
        self.values = list(values)
        self.calls: list[datetime] = []

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> MacroFactorResearchSourceDefinition | None:
        assert source_id == "macro-factor-source:growth"
        assert source_version == "source.v1"
        assert expected_content_hash == _definition().content_hash
        self.calls.append(as_of)
        return self.values.pop(0)


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.records: list[object] = []
        self.atomic_entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        before = len(self.records)
        try:
            yield
        except Exception:
            del self.records[before:]
            raise

    def append_source_definition(self, record: object) -> object:
        self.records.append(record)
        return record


def _command() -> RegisterMacroFactorResearchSourceCommand:
    definition = _definition()
    return RegisterMacroFactorResearchSourceCommand(
        source_id=definition.source_id,
        source_version=definition.source_version,
        expected_content_hash=definition.content_hash,
        as_of=AS_OF,
    )


def test_id_only_registration_uses_server_clock_and_full_owner_rereads() -> None:
    definition = _definition()
    provider = _DefinitionProvider((definition,) * 4)
    store = _Store()

    record = RegisterMacroFactorResearchSource(
        definition_provider=provider,
        store=store,
        clock=_Clock(),
    ).execute(_command())

    assert record.ledger_recorded_at == SERVER_NOW
    assert provider.calls == [AS_OF, SERVER_NOW, SERVER_NOW, SERVER_NOW]
    assert store.records == [record]
    assert store.atomic_entries == 1


def test_live_command_and_owner_substitution_fail_before_persisting() -> None:
    definition = _definition()
    store = _Store()
    command = _command()
    object.__setattr__(command, "expected_content_hash", "")

    with pytest.raises(MacroFactorResearchSourceUnavailable, match="command"):
        RegisterMacroFactorResearchSource(
            definition_provider=_DefinitionProvider((definition,) * 4),
            store=store,
            clock=_Clock(),
        ).execute(command)

    changed = _definition()
    object.__setattr__(changed, "target_code", "substituted")
    with pytest.raises(MacroFactorResearchSourceUnavailable, match="owner"):
        RegisterMacroFactorResearchSource(
            definition_provider=_DefinitionProvider((definition, changed, changed, changed)),
            store=store,
            clock=_Clock(),
        ).execute(_command())

    assert store.records == []


def test_command_subclass_and_dynamic_uow_substitution_fail_before_reads_or_writes() -> None:
    class _CommandSubclass(RegisterMacroFactorResearchSourceCommand):
        pass

    definition = _definition()
    provider = _DefinitionProvider((definition,) * 4)
    store = _Store()
    use_case = RegisterMacroFactorResearchSource(
        definition_provider=provider,
        store=store,
        clock=_Clock(),
    )
    subclass = _CommandSubclass(
        source_id=definition.source_id,
        source_version=definition.source_version,
        expected_content_hash=definition.content_hash,
        as_of=AS_OF,
    )

    with pytest.raises(MacroFactorResearchSourceUnavailable, match="command"):
        use_case.execute(subclass)
    assert provider.calls == []
    assert store.records == []
    assert store.atomic_entries == 0

    provider.unit_of_work_key = "django:substituted"
    with pytest.raises(MacroFactorResearchSourceUnavailable, match="unit of work"):
        use_case.execute(_command())
    assert provider.calls == []
    assert store.records == []
    assert store.atomic_entries == 0


@pytest.mark.parametrize(
    "field_name,replacement_name",
    (
        ("_definition_provider", "provider"),
        ("_store", "store"),
        ("_clock", "clock"),
    ),
)
def test_registration_rejects_replaced_business_participants_before_reads_or_writes(
    field_name: str,
    replacement_name: str,
) -> None:
    definition = _definition()
    original_provider = _DefinitionProvider((definition,) * 4)
    replacement_provider = _DefinitionProvider((definition,) * 4)
    original_store = _Store()
    replacement_store = _Store()
    original_clock = _Clock()
    replacement_clock = _Clock()
    use_case = RegisterMacroFactorResearchSource(
        definition_provider=original_provider,
        store=original_store,
        clock=original_clock,
    )
    replacements = {
        "provider": replacement_provider,
        "store": replacement_store,
        "clock": replacement_clock,
    }
    object.__setattr__(use_case, field_name, replacements[replacement_name])

    with pytest.raises(MacroFactorResearchSourceUnavailable, match="participant changed"):
        use_case.execute(_command())

    assert original_provider.calls == []
    assert replacement_provider.calls == []
    assert original_store.records == []
    assert replacement_store.records == []


def test_future_cutoff_fails_before_owner_reads_and_writes() -> None:
    definition = _definition()
    provider = _DefinitionProvider((definition,) * 4)
    store = _Store()
    command = _command()
    object.__setattr__(
        command,
        "as_of",
        datetime(2024, 1, 4, tzinfo=UTC),
    )

    with pytest.raises(MacroFactorResearchSourceUnavailable, match="future"):
        RegisterMacroFactorResearchSource(
            definition_provider=provider,
            store=store,
            clock=_Clock(),
        ).execute(command)

    assert provider.calls == []
    assert store.records == []
    assert store.atomic_entries == 1


def test_persisted_definition_codec_roundtrip_and_live_tamper_rejection() -> None:
    record = PersistedMacroFactorResearchSourceDefinition.create(
        definition=_definition(),
        ledger_recorded_at=SERVER_NOW,
    )

    payload = encode_persisted_macro_factor_research_source(record)

    assert decode_persisted_macro_factor_research_source(payload) == record
    definition_payload = cast(dict[str, object], payload["definition"])
    definition_payload["target_code"] = "substituted"
    with pytest.raises(MacroFactorResearchSourceCodecError):
        decode_persisted_macro_factor_research_source(payload)
