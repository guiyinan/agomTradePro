"""R3 Data Center-owned source-definition and PIT projection contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
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
    CanonicalMacroFactorPITFact,
    CanonicalMacroFactorPITProjection,
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


def _projection() -> CanonicalMacroFactorPITProjection:
    definition = _definition()
    source = PersistedMacroFactorResearchSourceDefinition.create(
        definition=definition,
        ledger_recorded_at=SERVER_NOW,
    )
    facts = tuple(
        CanonicalMacroFactorPITFact(
            row_id=rule.row_id,
            role=rule.role,
            member_code=rule.member_code,
            dataset_key=rule.dataset_key,
            business_key=rule.business_key,
            version_id=index,
            content_hash=f"{index:x}" * 64,
            payload_hash=f"{index + 1:x}" * 64,
            source_record_id=f"source-record-{index}",
            revision_number=0,
            effective_at=datetime(2024, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 4, 1, tzinfo=UTC),
            ingested_at=datetime(2024, 4, 1, tzinfo=UTC),
            pit_quality="verified",
            value=Decimal(index),
            unit=rule.expected_unit,
        )
        for index, rule in enumerate(definition.members, start=1)
    )
    return CanonicalMacroFactorPITProjection(
        source=source,
        manifest_id="macro-factor-manifest:growth",
        manifest_hash=HASH_A,
        manifest_as_of=datetime(2024, 4, 2, tzinfo=UTC),
        manifest_created_at=datetime(2024, 4, 3, tzinfo=UTC),
        knowledge_scope="public",
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        is_verified=True,
        facts=facts,
    )


def _assert_contract_error(
    factory: Callable[[], object],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        factory()


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


def test_period_calendar_member_and_policy_contracts_reject_invalid_boundaries() -> None:
    period = _periods()[0]
    calendar = _definition().calendar
    member = _definition().members[0]
    policy = _definition().coverage_policy
    duplicate_period = replace(_periods()[1], row_id=period.row_id)

    cases: tuple[tuple[Callable[[], object], type[Exception], str], ...] = (
        (
            lambda: MacroFactorSourceSeal("", "v1", HASH_A),
            ValueError,
            "bounded token",
        ),
        (
            lambda: MacroFactorSourceSeal("source", "v1", "bad"),
            ValueError,
            "SHA-256",
        ),
        (
            lambda: replace(
                period,
                kind=cast(MacroFactorResearchPeriodKind, "historical"),
            ),
            TypeError,
            "kind must be exact",
        ),
        (
            lambda: replace(
                period,
                observation_date=cast(date, datetime(2024, 1, 31, tzinfo=UTC)),
            ),
            ValueError,
            "exact date",
        ),
        (
            lambda: replace(
                period,
                target_period_start=date(2024, 3, 1),
            ),
            ValueError,
            "target period is invalid",
        ),
        (
            lambda: replace(
                period,
                observation_date=date(2024, 3, 1),
            ),
            ValueError,
            "observation cannot follow",
        ),
        (
            lambda: replace(calendar, periods=()),
            ValueError,
            "non-empty tuple",
        ),
        (
            lambda: replace(calendar, periods=tuple(reversed(calendar.periods))),
            ValueError,
            "must be canonical",
        ),
        (
            lambda: replace(
                calendar,
                periods=(period, duplicate_period, _periods()[2]),
            ),
            ValueError,
            "identities must be unique",
        ),
        (
            lambda: replace(
                calendar,
                periods=tuple(
                    replace(item, kind=MacroFactorResearchPeriodKind.HISTORICAL)
                    for item in calendar.periods
                ),
            ),
            ValueError,
            "exactly one inference",
        ),
        (
            lambda: replace(calendar, content_hash=HASH_A),
            ValueError,
            "content_hash differs",
        ),
        (
            lambda: replace(
                member,
                role=cast(MacroFactorResearchMemberRole, "proxy"),
            ),
            TypeError,
            "member role must be exact",
        ),
        (
            lambda: replace(
                member,
                value_encoding=cast(MacroFactorValueEncoding, "decimal_text.v1"),
            ),
            TypeError,
            "value encoding must be exact",
        ),
        (
            lambda: replace(member, unit_field=member.value_field),
            ValueError,
            "fields must differ",
        ),
        (
            lambda: replace(policy, require_verified=cast(bool, 1)),
            TypeError,
            "exact bool",
        ),
        (
            lambda: replace(policy, minimum_coverage_ratio=cast(Decimal, 1)),
            ValueError,
            "finite Decimal",
        ),
        (
            lambda: replace(policy, minimum_coverage_ratio=Decimal("1.1")),
            ValueError,
            "between zero and one",
        ),
        (
            lambda: replace(policy, maximum_missing_count=-1),
            ValueError,
            "non-negative exact int",
        ),
    )

    for factory, error_type, message in cases:
        _assert_contract_error(factory, error_type, message)

    tampered_calendar = calendar
    object.__setattr__(tampered_calendar, "content_hash", HASH_A)
    with pytest.raises(ValueError, match="differs after replay"):
        tampered_calendar.validated_copy()


def test_source_definition_contract_rejects_substitution_and_incomplete_graphs() -> None:
    definition = _definition()
    duplicate_members = list(definition.members)
    duplicate_members[1] = replace(
        duplicate_members[1],
        business_key=duplicate_members[0].business_key,
    )
    unknown_row_members = list(definition.members)
    unknown_row_members[0] = replace(unknown_row_members[0], row_id="unknown-row")
    unknown_row_members.sort(key=lambda item: (item.row_id, item.role.value, item.member_code))
    missing_proxy_members = tuple(
        item
        for index, item in enumerate(definition.members)
        if not (index == 0 and item.role is MacroFactorResearchMemberRole.PROXY)
    )
    inference = definition.inference_period
    target_template = next(
        item for item in definition.members if item.role is MacroFactorResearchMemberRole.TARGET
    )
    inference_target = replace(
        target_template,
        row_id=inference.row_id,
        business_key="growth:target-2024-04",
    )
    inference_target_members = tuple(
        sorted(
            (*definition.members, inference_target),
            key=lambda item: (item.row_id, item.role.value, item.member_code),
        )
    )

    cases: tuple[tuple[Callable[[], object], type[Exception], str], ...] = (
        (
            lambda: replace(definition, owner="research"),
            ValueError,
            "owner must be data_center",
        ),
        (
            lambda: replace(
                definition,
                candidate_asset_codes=cast(tuple[str, ...], []),
            ),
            ValueError,
            "non-empty tuple",
        ),
        (
            lambda: replace(definition, candidate_asset_codes=("CU", "AU")),
            ValueError,
            "must be canonical",
        ),
        (
            lambda: replace(
                definition,
                calendar=cast(MacroFactorResearchCalendar, object()),
            ),
            TypeError,
            "calendar type differs",
        ),
        (
            lambda: replace(
                definition,
                source_contract=cast(MacroFactorSourceSeal, object()),
            ),
            TypeError,
            "source contract type differs",
        ),
        (
            lambda: replace(definition, knowledge_scope="private"),
            ValueError,
            "public knowledge scope",
        ),
        (
            lambda: replace(definition, members=()),
            ValueError,
            "non-empty tuple",
        ),
        (
            lambda: replace(
                definition,
                members=tuple(reversed(definition.members)),
            ),
            ValueError,
            "members must be canonical",
        ),
        (
            lambda: replace(definition, members=tuple(duplicate_members)),
            ValueError,
            "fact identities must be unique",
        ),
        (
            lambda: replace(
                definition,
                coverage_policy=cast(MacroFactorResearchCoveragePolicy, object()),
            ),
            TypeError,
            "coverage policy type differs",
        ),
        (
            lambda: replace(definition, valid_until=definition.registered_at),
            ValueError,
            "validity window is invalid",
        ),
        (
            lambda: replace(definition, research_only=False),
            ValueError,
            "safety flags",
        ),
        (
            lambda: replace(definition, members=tuple(unknown_row_members)),
            ValueError,
            "unknown calendar row",
        ),
        (
            lambda: replace(definition, members=missing_proxy_members),
            ValueError,
            "exact proxy universe",
        ),
        (
            lambda: replace(definition, members=inference_target_members),
            ValueError,
            "inference row cannot include",
        ),
        (
            lambda: replace(
                definition,
                manifest_calendar_version="mf-growth-v2",
            ),
            ValueError,
            "content_hash differs",
        ),
    )

    for factory, error_type, message in cases:
        _assert_contract_error(factory, error_type, message)

    tampered_definition = _definition()
    object.__setattr__(tampered_definition, "content_hash", HASH_A)
    with pytest.raises(ValueError, match="differs after replay"):
        tampered_definition.validated_copy()


def test_persisted_fact_and_projection_contracts_fail_closed() -> None:
    projection = _projection()
    source = projection.source
    fact = projection.facts[0]
    mismatched_fact = replace(fact, member_code="SUBSTITUTED")
    estimated_fact = replace(fact, pit_quality="estimated")
    estimated_facts = (estimated_fact, *projection.facts[1:])

    cases: tuple[tuple[Callable[[], object], type[Exception], str], ...] = (
        (
            lambda: replace(
                source,
                definition=cast(MacroFactorResearchSourceDefinition, object()),
            ),
            TypeError,
            "definition type differs",
        ),
        (
            lambda: PersistedMacroFactorResearchSourceDefinition.create(
                definition=_definition(),
                ledger_recorded_at=datetime(2024, 1, 3),
            ),
            ValueError,
            "timezone-aware",
        ),
        (
            lambda: replace(source, ledger_recorded_at=VALID_UNTIL),
            ValueError,
            "ledger clock is invalid",
        ),
        (
            lambda: replace(source, record_hash=HASH_B),
            ValueError,
            "record_hash differs",
        ),
        (
            lambda: replace(source, must_not_execute=False),
            ValueError,
            "safety flags",
        ),
        (
            lambda: replace(
                fact,
                role=cast(MacroFactorResearchMemberRole, "proxy"),
            ),
            TypeError,
            "fact role must be exact",
        ),
        (
            lambda: replace(fact, version_id=0),
            ValueError,
            "version_id must be",
        ),
        (
            lambda: replace(fact, revision_number=-1),
            ValueError,
            "revision_number",
        ),
        (
            lambda: replace(
                fact,
                ingested_at=fact.available_at.replace(year=2023),
            ),
            ValueError,
            "ingested before availability",
        ),
        (
            lambda: replace(
                projection,
                source=cast(PersistedMacroFactorResearchSourceDefinition, object()),
            ),
            TypeError,
            "projection source type differs",
        ),
        (
            lambda: replace(projection, coverage_ratio=Decimal("1.1")),
            ValueError,
            "outside zero and one",
        ),
        (
            lambda: replace(projection, missing_count=-1),
            ValueError,
            "missing_count is invalid",
        ),
        (
            lambda: replace(projection, is_verified=cast(bool, 1)),
            TypeError,
            "is_verified must be exact bool",
        ),
        (
            lambda: replace(projection, facts=()),
            ValueError,
            "non-empty tuple",
        ),
        (
            lambda: replace(projection, facts=projection.facts[:-1]),
            ValueError,
            "exact member rules",
        ),
        (
            lambda: replace(
                projection,
                facts=(mismatched_fact, *projection.facts[1:]),
            ),
            ValueError,
            "differs from its exact member rule",
        ),
        (
            lambda: replace(projection, knowledge_scope="private"),
            ValueError,
            "clock/source graph differs",
        ),
        (
            lambda: replace(projection, facts=estimated_facts),
            ValueError,
            "verified status differs",
        ),
        (
            lambda: replace(
                projection,
                facts=estimated_facts,
                is_verified=False,
                estimated_count=1,
            ),
            ValueError,
            "violates its coverage policy",
        ),
        (
            lambda: replace(projection, must_not_use_for_decision=False),
            ValueError,
            "safety flags",
        ),
    )

    for factory, error_type, message in cases:
        _assert_contract_error(factory, error_type, message)

    tampered_source = projection.source
    object.__setattr__(tampered_source, "record_hash", HASH_B)
    with pytest.raises(ValueError, match="differs after replay"):
        tampered_source.validated_copy()
