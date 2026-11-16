"""Pure contracts for composing a date-only v3 witness from C2 read results."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from apps.data_center import financial_availability_e1_composition as composition
from apps.data_center.application.financial_availability_current import (
    CurrentFinancialAvailabilityGovernancePair,
)
from apps.data_center.application.financial_availability_governance import (
    FinancialAvailabilityGovernanceReadResult,
    materialize_financial_availability_record,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityRecordKind,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningRule,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
    FinancialNativeRowBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from core.exceptions import DataValidationError
from tests.unit.data_center.test_financial_availability_governance import BASE as SOURCE_BASE
from tests.unit.data_center.test_financial_availability_governance import BODY as SOURCE_BODY
from tests.unit.data_center.test_financial_availability_governance import (
    _apply_event,
    _opening_record,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    DATASET as CALENDAR_DATASET,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    KNOWN_AT as CALENDAR_BASE,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    _calendar,
)
from tests.unit.data_center.test_financial_next_session_witness import _witness

_CURRENT_KNOWN_AT = CALENDAR_BASE + timedelta(minutes=2)
_NOTICE_DATE = date(2026, 11, 16)


class _Records:
    """Provide the typed test alias and a stable server-clock observation."""

    database_alias = "default"

    def now(self) -> datetime:
        """Return the synthetic server time used by these pure composition tests."""

        return _CURRENT_KNOWN_AT


class _OwnerEvents:
    """Expose only the same-alias identity needed by the isolated composition."""

    database_alias = "default"


class _SourceReader:
    """Expose only the same-alias identity needed by the isolated composition."""

    database_alias = "default"


def _pair_and_calendar(
    *,
    effective_on: date | None = None,
    open_dates: tuple[date, ...] = (_NOTICE_DATE + timedelta(days=1),),
) -> tuple[
    CurrentFinancialAvailabilityGovernancePair,
    CurrentPublishedExchangeCalendar,
    FinancialNativeRowBinding,
]:
    """Build internally consistent synthetic current reads with real Domain values."""

    opening_record = _opening_record()
    source_reference = opening_record.source
    assert source_reference is not None
    opening_event = _apply_event(opening_record)
    opening_rule = materialize_financial_availability_record(opening_record, opening_event)
    assert type(opening_rule) is ExchangeSessionOpeningRule
    source_read = FinancialAvailabilitySourceRead(
        reference=source_reference,
        body=SOURCE_BODY,
        checked_at=_CURRENT_KNOWN_AT,
        known_at=_CURRENT_KNOWN_AT,
    )
    opening_result = FinancialAvailabilityGovernanceReadResult(
        record=opening_record,
        apply_event=opening_event,
        resolved_content=opening_rule,
        known_at=_CURRENT_KNOWN_AT,
        checked_at=_CURRENT_KNOWN_AT,
        source_read=source_read,
    )

    policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id="synthetic-financial-availability-policy",
        policy_version="synthetic-v1",
        exchange=opening_rule.exchange,
        opening_phase=opening_rule.phase,
        effective_start=date(2026, 1, 1),
        effective_end=date(2027, 12, 31),
        calendar_response_max_age_seconds=600,
        first_seen_at=SOURCE_BASE,
        recorded_at=SOURCE_BASE + timedelta(seconds=4),
    )
    policy_record = FinancialAvailabilityGovernanceRecord(
        record_id=policy.policy_id,
        record_version=policy.policy_version,
        exchange=policy.exchange,
        kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
        content=policy,
        recorded_at=policy.recorded_at,
    )
    policy_event = _apply_event(policy_record)
    policy_result = FinancialAvailabilityGovernanceReadResult(
        record=policy_record,
        apply_event=policy_event,
        resolved_content=policy,
        known_at=_CURRENT_KNOWN_AT,
        checked_at=_CURRENT_KNOWN_AT,
    )
    calendar_record, pointer = _calendar(
        start=_NOTICE_DATE,
        end=_NOTICE_DATE + timedelta(days=2),
        open_dates=open_dates,
        ttl_seconds=600,
    )
    current_calendar = CurrentPublishedExchangeCalendar(
        record=calendar_record,
        pointer=pointer,
        as_of=_CURRENT_KNOWN_AT,
    )
    next_day = min(day for day in open_dates if day > _NOTICE_DATE)
    pair = CurrentFinancialAvailabilityGovernancePair(
        exchange="SZSE",
        effective_on=effective_on or next_day,
        opening_rule=opening_result,
        disclosure_policy=policy_result,
        known_at=_CURRENT_KNOWN_AT,
        checked_at=_CURRENT_KNOWN_AT,
    )
    row = _witness().financial_row
    return pair, current_calendar, row


def _prepare_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pair: CurrentFinancialAvailabilityGovernancePair,
    calendar: CurrentPublishedExchangeCalendar,
) -> None:
    """Stub only boundary readers while retaining full Domain validation."""

    monkeypatch.setattr(composition, "_require_default_caller_uow", lambda: None)

    def read_calendar(*, calendar_dataset_key: str, exchange: str, as_of: datetime):
        assert calendar_dataset_key == CALENDAR_DATASET.value
        assert exchange == "SZSE"
        return replace(calendar, as_of=as_of)

    def read_governance(query, *, records, owner_events, source_reader):
        assert query.exchange == "SZSE"
        assert records.database_alias == "default"
        assert owner_events.database_alias == "default"
        assert source_reader.database_alias == "default"
        return pair

    monkeypatch.setattr(composition, "_read_current_calendar_for_scope", read_calendar)
    monkeypatch.setattr(
        composition, "resolve_current_financial_availability_governance", read_governance
    )


def test_builder_preserves_date_only_row_source_clocks_and_real_apply_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, calendar, row = _pair_and_calendar()
    _prepare_mocks(monkeypatch, pair=pair, calendar=calendar)

    witness = composition.build_financial_next_session_witness_v3(
        row,
        exchange="SZSE",
        calendar_dataset_key=CALENDAR_DATASET.value,
        records=_Records(),
        owner_events=_OwnerEvents(),
        source_reader=_SourceReader(),
    )

    assert type(witness) is FinancialNextSessionSourceTimeWitnessV3
    assert witness.financial_row.notice_date == _NOTICE_DATE
    assert witness.financial_row.period_end == date(2026, 6, 30)
    assert witness.known_at == _CURRENT_KNOWN_AT
    assert type(witness.governance.official_source) is FinancialStatutorySourceIdentity
    assert (
        witness.governance.official_source.recorded_at
        == pair.opening_rule.record.source.capture_recorded_at
    )
    assert witness.governance.opening_rule_approval.event_id == str(
        pair.opening_rule.apply_event.event_id
    )
    assert witness.governance.policy_approval.event_id == str(
        pair.disclosure_policy.apply_event.event_id
    )
    assert witness.reference_only is True
    assert witness.must_not_use_for_decision is True


def test_builder_blocks_calendar_mapping_change_between_scope_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, calendar, row = _pair_and_calendar()
    _, changed_calendar, _ = _pair_and_calendar(open_dates=(_NOTICE_DATE + timedelta(days=2),))
    monkeypatch.setattr(composition, "_require_default_caller_uow", lambda: None)
    calls = 0

    def read_calendar(*, calendar_dataset_key: str, exchange: str, as_of: datetime):
        nonlocal calls
        calls += 1
        selected = calendar if calls == 1 else changed_calendar
        return replace(selected, as_of=as_of)

    monkeypatch.setattr(composition, "_read_current_calendar_for_scope", read_calendar)
    monkeypatch.setattr(
        composition,
        "resolve_current_financial_availability_governance",
        lambda query, **_kwargs: pair,
    )
    with pytest.raises(DataValidationError) as error:
        composition.build_financial_next_session_witness_v3(
            row,
            exchange="SZSE",
            calendar_dataset_key=CALENDAR_DATASET.value,
            records=_Records(),
            owner_events=_OwnerEvents(),
            source_reader=_SourceReader(),
        )
    assert error.value.code == "FIN_AVAILABILITY_NEXT_SESSION_MAPPING_CHANGED"


def test_builder_blocks_governance_resolved_for_another_effective_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, calendar, row = _pair_and_calendar(effective_on=_NOTICE_DATE + timedelta(days=2))
    _prepare_mocks(monkeypatch, pair=pair, calendar=calendar)

    with pytest.raises(DataValidationError) as error:
        composition.build_financial_next_session_witness_v3(
            row,
            exchange="SZSE",
            calendar_dataset_key=CALENDAR_DATASET.value,
            records=_Records(),
            owner_events=_OwnerEvents(),
            source_reader=_SourceReader(),
        )
    assert error.value.code == "FIN_AVAILABILITY_NEXT_SESSION_MAPPING_CHANGED"
