"""Pure prerequisite checks for calendar-bound financial availability."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
    ExchangeSessionOpeningRule,
    FinancialNextSessionAvailabilityError,
    exchange_session_opening_rule_sha256,
    resolve_financial_next_session_availability,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
    CalendarPublicationPointerExpectation,
    create_calendar_formal_publication_seal,
)

KNOWN_AT = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
SOURCE_DATE = date(2026, 8, 15)
DATASET = DatasetKey("data_center.exchange_calendar_snapshot", "calendar.v1", "schema.v1")


def _calendar(
    *,
    exchange: str = "SZSE",
    start: date = SOURCE_DATE,
    end: date = date(2026, 8, 18),
    open_dates: tuple[date, ...] = (date(2026, 8, 17), date(2026, 8, 18)),
    first_seen_at: datetime = KNOWN_AT - timedelta(minutes=5),
    recorded_at: datetime = KNOWN_AT - timedelta(minutes=4),
    published_at: datetime = KNOWN_AT - timedelta(minutes=3),
    ttl_seconds: int = 600,
) -> tuple[CalendarFormalPublicationRecord, CalendarPublicationPointerExpectation]:
    """Build one exact retained calendar publication spanning every requested day."""

    days: list[ExchangeCalendarDay] = []
    previous_open = start - timedelta(days=1)
    for offset in range((end - start).days + 1):
        calendar_date = start + timedelta(days=offset)
        is_open = calendar_date in open_dates
        days.append(
            ExchangeCalendarDay(
                exchange=exchange,
                calendar_date=calendar_date,
                is_open=is_open,
                previous_open_date=previous_open,
            )
        )
        if is_open:
            previous_open = calendar_date
    raw = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(exchange, start, end),
        original_body_retained=True,
        response_completed_at=first_seen_at,
        provider_name="tushare",
        dataset_key=DATASET.value,
        transport="direct",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange=exchange,
        coverage_start=start,
        coverage_end=end,
        days=tuple(days),
        provider_name="tushare",
        raw_reference=raw,
        first_seen_at=first_seen_at,
    )
    snapshot = make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at,
    )
    policy = PublicationPolicy(
        dataset=DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fetched_at", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-policy.v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    member = PublicationMember(
        member_id="calendar-member",
        publication_id="publication-placeholder",
        dataset_key=DATASET.value,
        natural_key=f"{exchange}:{start.isoformat()}:{end.isoformat()}",
        source="tushare",
        source_record_id=snapshot.snapshot_id,
        fact_table="data_center_exchange_calendar_snapshot_fact",
        fact_pk=snapshot.snapshot_id,
        observed_at=None,
        raw_payload_hash=snapshot.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    member_reference = CalendarPublicationMemberReference(
        member=member,
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    seal = create_calendar_formal_publication_seal(
        dataset=DATASET,
        exchange=exchange,
        calendar_response_max_age_seconds=ttl_seconds,
        contract_recorded_at=KNOWN_AT - timedelta(minutes=6),
        policy=policy,
        policy_recorded_at=KNOWN_AT - timedelta(minutes=5, seconds=30),
        snapshot=snapshot,
        member_reference=member_reference,
    )
    record = CalendarFormalPublicationRecord(
        seal=seal,
        publication_id=str(uuid4()),
        activation_id="activation-calendar-v1",
        lifecycle=CalendarPublicationLifecycle.PUBLISHED,
        published_at=published_at,
    )
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=record.seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        activation_id=record.activation_id,
        updated_at=published_at,
    )
    return record, pointer


def _opening_rule(
    *,
    exchange: str = "SZSE",
    phase: ExchangeSessionOpeningPhase = ExchangeSessionOpeningPhase.OPENING_CALL_AUCTION,
    timezone_name: str = "Asia/Shanghai",
    local_open_time: time = time(9, 15),
    effective_start: date = date(2026, 1, 1),
    effective_end: date = date(2027, 12, 31),
    first_seen_at: datetime = KNOWN_AT - timedelta(minutes=6),
    recorded_at: datetime = KNOWN_AT - timedelta(minutes=5),
    approved_at: datetime = KNOWN_AT - timedelta(minutes=4),
) -> ExchangeSessionOpeningRule:
    """Build a content-hashed rule without asserting that a real rule is approved."""

    payload: dict[str, object] = {
        "exchange": exchange,
        "phase": phase.value,
        "rule_version": "szse-trading-rules-2026.2.3.2.v1",
        "source_uri": "https://www.szse.cn/lawrules/rule/trading-rules-2026.pdf",
        "source_body_sha256": "b" * 64,
        "effective_start": effective_start.isoformat(),
        "effective_end": effective_end.isoformat(),
        "timezone_name": timezone_name,
        "local_open_time": local_open_time.isoformat(),
        "first_seen_at": first_seen_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "approved_at": approved_at.isoformat(),
    }
    return ExchangeSessionOpeningRule(
        exchange=exchange,
        phase=phase,
        rule_version=str(payload["rule_version"]),
        source_uri=str(payload["source_uri"]),
        source_body_sha256=str(payload["source_body_sha256"]),
        effective_start=effective_start,
        effective_end=effective_end,
        timezone_name=timezone_name,
        local_open_time=local_open_time,
        first_seen_at=first_seen_at,
        recorded_at=recorded_at,
        approved_at=approved_at,
        rule_sha256=exchange_session_opening_rule_sha256(payload),
    )


def test_resolves_next_open_session_and_returns_only_reference_binding() -> None:
    calendar, pointer = _calendar()
    rule = _opening_rule()

    result = resolve_financial_next_session_availability(
        source_date=SOURCE_DATE,
        known_at=KNOWN_AT,
        calendar_record=calendar,
        calendar_pointer=pointer,
        opening_rule=rule,
    )

    assert result.next_session == date(2026, 8, 17)
    assert result.available_at == datetime(2026, 8, 17, 1, 15, tzinfo=UTC)
    assert result.opening_rule_identity == rule.identity
    assert result.calendar_publication_hash == calendar.seal.publication_hash
    assert result.reference_only is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True


def test_phase_is_required_and_never_defaults_to_a_market_clock() -> None:
    with pytest.raises(TypeError):
        ExchangeSessionOpeningRule()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("calendar_changes", "rule_changes", "source_date", "known_at", "code"),
    [
        ({"exchange": "SSE"}, {}, SOURCE_DATE, KNOWN_AT, "EXCHANGE_MISMATCH"),
        ({}, {"exchange": "SSE"}, SOURCE_DATE, KNOWN_AT, "EXCHANGE_MISMATCH"),
        ({}, {"effective_start": date(2026, 8, 18)}, SOURCE_DATE, KNOWN_AT, "RULE_NOT_EFFECTIVE"),
        ({}, {}, SOURCE_DATE, KNOWN_AT + timedelta(minutes=5), "CALENDAR_NOT_CURRENT_OR_FRESH"),
        ({}, {}, date(2026, 8, 18), KNOWN_AT, "CALENDAR_COVERAGE_INCOMPLETE"),
        (
            {},
            {"approved_at": KNOWN_AT + timedelta(seconds=1)},
            SOURCE_DATE,
            KNOWN_AT,
            "RULE_NOT_KNOWN",
        ),
        ({}, {}, SOURCE_DATE, KNOWN_AT - timedelta(minutes=4), "CALENDAR_NOT_CURRENT_OR_FRESH"),
    ],
)
def test_missing_mismatched_stale_or_future_evidence_fails_closed(
    calendar_changes: dict[str, object],
    rule_changes: dict[str, object],
    source_date: date,
    known_at: datetime,
    code: str,
) -> None:
    calendar, pointer = _calendar(**calendar_changes)
    rule = _opening_rule(**rule_changes)
    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=source_date,
            known_at=known_at,
            calendar_record=calendar,
            calendar_pointer=pointer,
            opening_rule=rule,
        )
    assert error.value.code == code


def test_wrong_pointer_identity_is_not_accepted_as_exact_current_publication() -> None:
    calendar, pointer = _calendar()
    mismatched = replace(pointer, publication_hash="f" * 64)

    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=SOURCE_DATE,
            known_at=KNOWN_AT,
            calendar_record=calendar,
            calendar_pointer=mismatched,
            opening_rule=_opening_rule(),
        )

    assert error.value.code == "CALENDAR_NOT_CURRENT_OR_FRESH"


def test_opening_rule_cannot_be_used_before_its_recorded_approval() -> None:
    rule = _opening_rule(approved_at=KNOWN_AT + timedelta(seconds=1))
    calendar, pointer = _calendar()

    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=SOURCE_DATE,
            known_at=KNOWN_AT,
            calendar_record=calendar,
            calendar_pointer=pointer,
            opening_rule=rule,
        )

    assert error.value.code == "RULE_NOT_KNOWN"


def test_ambiguous_local_clock_fails_closed_instead_of_guessing_fold() -> None:
    sunday = date(2026, 11, 1)
    calendar, pointer = _calendar(
        start=date(2026, 10, 31),
        end=sunday,
        open_dates=(sunday,),
    )
    rule = _opening_rule(
        timezone_name="America/New_York",
        local_open_time=time(1, 30),
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
    )

    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=date(2026, 10, 31),
            known_at=KNOWN_AT,
            calendar_record=calendar,
            calendar_pointer=pointer,
            opening_rule=rule,
        )

    assert error.value.code == "OPENING_CLOCK_AMBIGUOUS"


def test_hash_binds_phase_source_and_knowledge_clocks() -> None:
    original = _opening_rule()
    changed = _opening_rule(phase=ExchangeSessionOpeningPhase.CONTINUOUS_AUCTION)

    assert original.identity != changed.identity
    with pytest.raises(ValueError, match="hash"):
        replace(original, source_body_sha256="c" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {"exchange": None},
        {"exchange": "invalid/exchange"},
        {"exchange": ""},
        {"phase": "opening_call_auction"},
        {"rule_version": "not a version"},
        {"source_uri": "http://www.szse.cn/rules.pdf"},
        {"source_uri": "https://user:secret@www.szse.cn/rules.pdf"},
        {"source_uri": ""},
        {"source_uri": "https://www.szse.cn/bad path.pdf"},
        {"source_uri": "https://szse.cn/" + "r" * 2050},
        {"source_body_sha256": "B" * 64},
        {"effective_start": date(2027, 1, 1), "effective_end": date(2026, 1, 1)},
        {"timezone_name": "Not/A-Timezone"},
        {"timezone_name": None},
        {"local_open_time": time(9, 15, tzinfo=UTC)},
        {"recorded_at": KNOWN_AT - timedelta(minutes=7)},
    ],
)
def test_opening_rule_rejects_incomplete_or_ambiguous_configuration(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(_opening_rule(), **changes)


def test_reference_projection_retains_calendar_and_rule_identity() -> None:
    calendar, pointer = _calendar()
    result = resolve_financial_next_session_availability(
        source_date=SOURCE_DATE,
        known_at=KNOWN_AT,
        calendar_record=calendar,
        calendar_pointer=pointer,
        opening_rule=_opening_rule(),
    )

    payload = result.to_dict()
    assert payload["schema"] == "financial-next-session-availability.reference.v1"
    assert payload["calendar"]["publication_id"] == calendar.publication_id
    assert payload["calendar"]["snapshot_reference"]["snapshot_id"] == (
        calendar.seal.snapshot.snapshot_id
    )
    assert payload["opening_rule"]["identity"] == result.opening_rule_identity
    assert payload["reference_only"] is True
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True


def test_result_revalidates_the_exact_next_open_date_and_calendar_window() -> None:
    calendar, pointer = _calendar()
    result = resolve_financial_next_session_availability(
        source_date=SOURCE_DATE,
        known_at=KNOWN_AT,
        calendar_record=calendar,
        calendar_pointer=pointer,
        opening_rule=_opening_rule(),
    )

    with pytest.raises(ValueError, match="exact next calendar session"):
        replace(result, next_session=date(2026, 8, 18))
    with pytest.raises(TypeError, match="exact current calendar pointer"):
        replace(result, calendar_pointer=object())
    with pytest.raises(TypeError, match="exact typed opening rule"):
        replace(result, opening_rule=object())
    with pytest.raises(ValueError, match="response-age window"):
        replace(result, known_at=KNOWN_AT + timedelta(minutes=5))
    with pytest.raises(ValueError, match="strictly follow"):
        replace(result, next_session=SOURCE_DATE)
    with pytest.raises(TypeError, match="formal calendar record"):
        replace(result, calendar_record=object())
    with pytest.raises(ValueError, match="exchanges differ"):
        replace(result, opening_rule=_opening_rule(exchange="SSE"))
    with pytest.raises(ValueError, match="outside opening rule"):
        replace(
            result,
            opening_rule=_opening_rule(effective_start=date(2026, 8, 18)),
        )
    with pytest.raises(ValueError, match="not known"):
        replace(result, opening_rule=_opening_rule(approved_at=KNOWN_AT + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="does not match"):
        replace(result, available_at=result.available_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="date"):
        replace(result, source_date=datetime(2026, 8, 15, tzinfo=UTC))


@pytest.mark.parametrize(
    ("source_date", "known_at", "calendar_record", "calendar_pointer", "opening_rule", "code"),
    [
        (datetime(2026, 8, 15, tzinfo=UTC), KNOWN_AT, None, None, None, "SOURCE_DATE_INVALID"),
        (SOURCE_DATE, datetime(2026, 11, 16), None, None, None, "KNOWLEDGE_TIME_INVALID"),
        (SOURCE_DATE, KNOWN_AT, None, None, None, "CALENDAR_REFERENCE_INVALID"),
        (SOURCE_DATE, KNOWN_AT, *_calendar(), object(), "RULE_REFERENCE_INVALID"),
    ],
)
def test_untyped_inputs_fail_before_resolution(
    source_date: date,
    known_at: datetime,
    calendar_record: object,
    calendar_pointer: object,
    opening_rule: object,
    code: str,
) -> None:
    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=source_date,  # type: ignore[arg-type]
            known_at=known_at,
            calendar_record=calendar_record,  # type: ignore[arg-type]
            calendar_pointer=calendar_pointer,  # type: ignore[arg-type]
            opening_rule=opening_rule,  # type: ignore[arg-type]
        )
    assert error.value.code == code


def test_nonexistent_local_clock_fails_closed() -> None:
    spring_forward = date(2026, 3, 8)
    calendar, pointer = _calendar(
        start=spring_forward - timedelta(days=1),
        end=spring_forward,
        open_dates=(spring_forward,),
    )
    rule = _opening_rule(
        timezone_name="America/New_York",
        local_open_time=time(2, 30),
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
    )

    with pytest.raises(FinancialNextSessionAvailabilityError) as error:
        resolve_financial_next_session_availability(
            source_date=spring_forward - timedelta(days=1),
            known_at=KNOWN_AT,
            calendar_record=calendar,
            calendar_pointer=pointer,
            opening_rule=rule,
        )

    assert error.value.code == "OPENING_CLOCK_NONEXISTENT"


def test_opening_rule_hash_helper_rejects_extra_or_nontext_fields() -> None:
    rule = _opening_rule()
    with pytest.raises(ValueError, match="keys"):
        exchange_session_opening_rule_sha256({**rule._payload(), "extra": "value"})
    with pytest.raises(ValueError, match="text"):
        exchange_session_opening_rule_sha256({**rule._payload(), "exchange": None})
