"""Contracts for integrity-binding a complete settlement execution plan."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import cast

import pytest

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    SimulatedSettlementPlanBindingV1,
    bind_settlement_execution_plan,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    RawCalendarReference,
    SettlementExecutionPlan,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _fee_policy() -> SimulatedFeePolicyV2:
    schedule = ExecutionFeeSchedule(
        config_id=17,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        min_commission=Decimal("5"),
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="fixture-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=AS_OF - timedelta(days=2),
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=AS_OF - timedelta(days=3),
        transaction_cases=(
            FeeTransactionCase(
                asset_type="equity",
                market="SH",
                board="MAIN",
                side=SimulatedTradeSide.BUY,
                commission=FeeApplicability.APPLIES,
                transfer_fee=FeeApplicability.APPLIES,
                stamp_duty=FeeApplicability.APPLIES,
                slippage=FeeApplicability.APPLIES,
            ),
        ),
    )


def _execution_plan(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    source_published_at: datetime | None = None,
) -> SettlementExecutionPlan:
    days = (
        ExchangeCalendarDay("SH", date(2026, 10, 16), True, date(2026, 10, 15)),
        ExchangeCalendarDay("SH", date(2026, 10, 17), False, date(2026, 10, 16)),
        ExchangeCalendarDay("SH", date(2026, 10, 18), False, date(2026, 10, 16)),
        ExchangeCalendarDay("SH", date(2026, 10, 19), True, date(2026, 10, 16)),
        ExchangeCalendarDay("SH", date(2026, 10, 20), True, date(2026, 10, 19)),
        ExchangeCalendarDay("SH", date(2026, 10, 21), True, date(2026, 10, 20)),
    )
    response_completed_at = AS_OF - timedelta(hours=2)
    raw_reference = RawCalendarReference(
        payload_id="a14940ad-00fb-4a7b-8c2d-51e6d2b90722",
        payload_hash="sha256:" + "a" * 64,
        record_digest="sha256:" + "b" * 64,
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        request_scope_sha256="d" * 64,
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-calendar-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="323a9f13-96ce-4a0c-b3a3-5cc5085aac45",
        exchange="SH",
        coverage_start=days[0].calendar_date,
        coverage_end=days[-1].calendar_date,
        days=days,
        provider_name="fixture-calendar-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=AS_OF - timedelta(hours=1),
        source_published_at=source_published_at,
    )
    publication = CalendarPublicationReference(
        publication_id="fixture-calendar-publication",
        member_id=snapshot.snapshot_id,
        publication_hash="e" * 64,
        fact_content_hash="f" * 64,
        policy_hash="1" * 64,
        published_at=AS_OF - timedelta(minutes=30),
        recorded_at=AS_OF - timedelta(minutes=20),
        reference_valid_from=AS_OF - timedelta(days=1),
        reference_valid_until=AS_OF + timedelta(days=10),
        timezone_name="Asia/Shanghai",
    )
    calendar = ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)
    lag = 2
    return SettlementExecutionPlan(
        intent=SimulatedTradeIntent(
            account_id=7,
            user_id=11,
            idempotency_key="settlement-binding-fixture-1",
            side=side,
            security_id="SH.UOW.SECURITY",
            asset_code="600000.SH",
            asset_name="Fixture Security",
            asset_type="equity",
            market="SH",
            board="MAIN",
            quantity=Decimal("100"),
            price=Decimal("10.00"),
            reason="settlement binding fixture",
            signal_id=23,
        ),
        market_session=date(2026, 10, 16),
        pre_read_at=AS_OF,
        settlement_lag_sessions=lag,
        settlement_release_date=(date(2026, 10, 20) if side is SimulatedTradeSide.BUY else None),
        settlement_bundle_id="fixture-settlement-bundle",
        settlement_bundle_version="v3.1",
        settlement_bundle_hash="2" * 64,
        settlement_policy_id="fixture-settlement-policy",
        settlement_policy_version="policy-v1",
        settlement_policy_hash="3" * 64,
        execution_rule_v2_hash="4" * 64,
        bundle_source_observed_at=AS_OF - timedelta(days=3),
        bundle_source_available_at=AS_OF - timedelta(hours=1),
        bundle_effective_from=AS_OF - timedelta(days=1),
        bundle_valid_until=AS_OF + timedelta(days=30),
        calendar_evidence=calendar,
        fee_policy_v2=_fee_policy(),
    )


def test_binding_round_trips_the_exact_plan_and_all_evidence_identities() -> None:
    plan = _execution_plan()
    binding = bind_settlement_execution_plan(
        plan,
        executed_at=AS_OF + timedelta(minutes=1),
    )

    payload = binding.to_payload()
    restored = SimulatedSettlementPlanBindingV1.from_payload(payload)

    assert restored == binding
    assert restored.content_hash == binding.content_hash
    assert payload["schema"] == "simulated-settlement-plan-binding.v1"
    assert "content_hash" not in payload
    assert payload["request_payload_hash"] == plan.intent.request_payload_hash
    assert payload["settlement_lag_sessions"] == 2
    assert payload["settlement_release_date"] == "2026-10-20"
    assert payload["calendar_evidence_hash"] == plan.calendar_evidence.evidence_hash
    snapshot = payload["calendar_snapshot"]
    raw = payload["calendar_raw_reference"]
    publication = payload["calendar_publication"]
    assert type(snapshot) is dict
    assert snapshot["snapshot_id"] == plan.calendar_evidence.snapshot.snapshot_id
    assert snapshot["content_hash"] == plan.calendar_evidence.snapshot.content_hash
    assert snapshot["record_digest"] == plan.calendar_evidence.snapshot.record_digest
    assert snapshot["source_published_at"] is None
    assert type(raw) is dict
    assert raw["response_time_semantics"] == "local_response_body_completion"
    assert raw["original_body_retained"] is True
    assert type(publication) is dict
    assert publication["member_id"] == snapshot["snapshot_id"]
    assert publication["fact_content_hash"] == "f" * 64
    assert payload["fee_policy_schema"] == "simulated-fee-policy.v2"
    assert payload["fee_policy_content_hash"] == plan.fee_policy_v2.content_hash


def test_binding_hash_is_stable_canonical_and_separate_from_payload() -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )

    independently_encoded = json.dumps(
        binding.to_payload(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    independently_calculated = hashlib.sha256(independently_encoded).hexdigest()
    assert (
        binding.content_hash == "7d4b9878b3e82a78770212d04550559eadf68b23d64831fe0276319677e57e9c"
    )
    assert binding.content_hash == independently_calculated
    assert len(binding.content_hash) == 64
    assert all(character in "0123456789abcdef" for character in binding.content_hash)
    first = binding.to_payload()
    second = binding.to_payload()
    assert first == second
    assert first is not second
    assert first["calendar_snapshot"] is not second["calendar_snapshot"]


def test_sell_binding_preserves_the_absent_buy_settlement_date() -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(side=SimulatedTradeSide.SELL),
        executed_at=AS_OF + timedelta(minutes=1),
    )

    assert binding.to_payload()["settlement_release_date"] is None
    assert SimulatedSettlementPlanBindingV1.from_payload(binding.to_payload()) == binding


def test_payload_mutation_does_not_mutate_binding_and_hash_tracks_new_payload() -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )
    original_hash = binding.content_hash
    payload = binding.to_payload()
    changed = deepcopy(payload)
    changed["settlement_lag_sessions"] = 3
    nested_snapshot = changed["calendar_snapshot"]
    assert type(nested_snapshot) is dict
    nested_snapshot["exchange"] = "SZ"

    restored = SimulatedSettlementPlanBindingV1.from_payload(changed)

    assert restored.content_hash != original_hash
    assert binding.content_hash == original_hash
    assert binding.to_payload()["settlement_lag_sessions"] == 2


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_top_level_key",
        "unknown_top_level_key",
        "wrong_schema",
        "boolean_integer",
        "malformed_hash",
        "naive_wire_time",
        "noncanonical_wire_time",
        "invalid_wire_time",
        "zero_fraction_wire_time",
        "invalid_date_text",
        "week_date_text",
        "unknown_snapshot_key",
        "snapshot_field_wrong_type",
        "nullable_source_time_wrong_type",
        "raw_retained_not_boolean",
        "raw_field_wrong_type",
        "wrong_raw_time_semantics",
        "wrong_publication_member",
        "publication_field_wrong_type",
    ),
)
def test_from_payload_rejects_noncanonical_or_incomplete_wire_values(mutation: str) -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )
    payload = deepcopy(binding.to_payload())
    snapshot = payload["calendar_snapshot"]
    raw = payload["calendar_raw_reference"]
    publication = payload["calendar_publication"]
    assert type(snapshot) is dict
    assert type(raw) is dict
    assert type(publication) is dict
    if mutation == "missing_top_level_key":
        payload.pop("settlement_lag_sessions")
    elif mutation == "unknown_top_level_key":
        payload["unexpected"] = False
    elif mutation == "wrong_schema":
        payload["schema"] = "simulated-settlement-plan-binding.v2"
    elif mutation == "boolean_integer":
        payload["settlement_lag_sessions"] = True
    elif mutation == "malformed_hash":
        payload["execution_rule_v2_hash"] = "sha256:" + "4" * 64
    elif mutation == "naive_wire_time":
        payload["executed_at"] = "2026-10-16T02:01:00"
    elif mutation == "noncanonical_wire_time":
        payload["executed_at"] = "2026-10-16T10:01:00+08:00"
    elif mutation == "invalid_wire_time":
        payload["executed_at"] = "not-a-timeZ"
    elif mutation == "zero_fraction_wire_time":
        payload["executed_at"] = "2026-10-16T02:01:00.000000Z"
    elif mutation == "invalid_date_text":
        payload["market_session"] = "not-a-date"
    elif mutation == "week_date_text":
        payload["market_session"] = "2026-W42-5"
    elif mutation == "unknown_snapshot_key":
        snapshot["days"] = []
    elif mutation == "snapshot_field_wrong_type":
        snapshot["snapshot_id"] = 123
    elif mutation == "nullable_source_time_wrong_type":
        snapshot["source_published_at"] = 0
    elif mutation == "raw_retained_not_boolean":
        raw["original_body_retained"] = 1
    elif mutation == "raw_field_wrong_type":
        raw["provider_name"] = 12
    elif mutation == "wrong_raw_time_semantics":
        raw["response_time_semantics"] = "upstream_observed_at"
    elif mutation == "wrong_publication_member":
        publication["member_id"] = "another-calendar-snapshot"
    elif mutation == "publication_field_wrong_type":
        publication["published_at"] = 0

    with pytest.raises(SettlementPlanBindingValidationError):
        SimulatedSettlementPlanBindingV1.from_payload(payload)


@pytest.mark.parametrize(
    "executed_at",
    (
        datetime(2026, 10, 16, 1, 59, tzinfo=UTC),
        datetime(2026, 10, 16, 3, 1),
    ),
)
def test_bind_rejects_clock_before_plan_or_naive_clock(
    executed_at: datetime,
) -> None:
    with pytest.raises(SettlementPlanBindingValidationError):
        bind_settlement_execution_plan(_execution_plan(), executed_at=executed_at)


def test_bind_normalizes_valid_non_utc_offset_to_the_same_canonical_instant() -> None:
    offset_time = datetime(2026, 10, 16, 10, 1, tzinfo=timezone(timedelta(hours=8)))

    binding = bind_settlement_execution_plan(_execution_plan(), executed_at=offset_time)

    assert binding.to_payload()["executed_at"] == "2026-10-16T02:01:00Z"


def test_bind_preserves_a_real_calendar_source_publication_clock() -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(source_published_at=AS_OF - timedelta(days=1)),
        executed_at=AS_OF + timedelta(minutes=1),
    )

    snapshot_payload = binding.to_payload()["calendar_snapshot"]
    assert type(snapshot_payload) is dict
    assert snapshot_payload["source_published_at"] == "2026-10-15T02:00:00Z"


def test_bind_rejects_a_non_plan_object() -> None:
    with pytest.raises(SettlementPlanBindingValidationError):
        bind_settlement_execution_plan(cast(SettlementExecutionPlan, object()), executed_at=AS_OF)


class _NoOffsetTimezone(tzinfo):
    """Test timezone whose aware datetime has no usable UTC offset."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "NO-OFFSET"


class _BrokenTimezone(tzinfo):
    """Test timezone that raises while its offset is read."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        raise ValueError("invalid timezone")

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "BROKEN"


@pytest.mark.parametrize(
    "executed_at",
    (
        datetime(2026, 10, 16, 2, 1, tzinfo=_NoOffsetTimezone()),
        datetime(2026, 10, 16, 2, 1, tzinfo=_BrokenTimezone()),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=14))),
    ),
)
def test_bind_rejects_aware_datetimes_without_a_safe_utc_representation(
    executed_at: datetime,
) -> None:
    with pytest.raises(SettlementPlanBindingValidationError):
        bind_settlement_execution_plan(_execution_plan(), executed_at=executed_at)


def test_bind_revalidates_a_mutated_frozen_plan_before_creating_a_binding() -> None:
    plan = _execution_plan()
    object.__setattr__(plan, "settlement_lag_sessions", True)

    with pytest.raises(SettlementPlanBindingValidationError):
        bind_settlement_execution_plan(plan, executed_at=AS_OF + timedelta(minutes=1))


@pytest.mark.parametrize(
    "changes",
    (
        {"account_id": 0},
        {"user_id": True},
        {"idempotency_key": ""},
        {"request_payload_hash": "g" * 64},
        {"market_session": datetime(2026, 10, 16)},
        {"settlement_lag_sessions": True},
        {"settlement_lag_sessions": -1},
        {"settlement_release_date": datetime(2026, 10, 20)},
        {"executed_at": AS_OF - timedelta(seconds=1)},
        {"bundle_source_available_at": AS_OF + timedelta(seconds=1)},
        {"bundle_effective_from": AS_OF + timedelta(seconds=1)},
        {"bundle_valid_until": AS_OF},
        {"fee_policy_schema": "simulated-fee-policy.v3"},
        {"calendar_snapshot": object()},
        {"calendar_raw_reference": object()},
        {"calendar_publication": object()},
    ),
)
def test_binding_constructor_rejects_incomplete_or_invalid_plan_identity(
    changes: dict[str, object],
) -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(SettlementPlanBindingValidationError):
        replace(binding, **changes)


@pytest.mark.parametrize(
    "part,changes",
    (
        ("calendar_snapshot", {"snapshot_id": "not-a-uuid"}),
        ("calendar_snapshot", {"exchange": " SH"}),
        ("calendar_snapshot", {"coverage_start": datetime(2026, 10, 16)}),
        ("calendar_snapshot", {"coverage_end": date(2026, 10, 15)}),
        ("calendar_snapshot", {"content_hash": "f" * 64}),
        ("calendar_snapshot", {"record_digest": "sha256:bad"}),
        ("calendar_snapshot", {"recorded_at": AS_OF - timedelta(days=1)}),
        ("calendar_snapshot", {"source_published_at": object()}),
        ("calendar_raw_reference", {"payload_id": "not-a-uuid"}),
        ("calendar_raw_reference", {"payload_hash": "a" * 64}),
        ("calendar_raw_reference", {"body_sha256": "z" * 64}),
        ("calendar_raw_reference", {"retained_content_sha256": "0" * 64}),
        ("calendar_raw_reference", {"original_body_retained": 1}),
        ("calendar_raw_reference", {"response_completed_at": datetime(2026, 10, 16)}),
        ("calendar_raw_reference", {"response_time_semantics": "upstream_time"}),
        ("calendar_raw_reference", {"transport": "cache"}),
        ("calendar_publication", {"publication_id": ""}),
        ("calendar_publication", {"publication_hash": "sha256:" + "a" * 64}),
        ("calendar_publication", {"recorded_at": AS_OF - timedelta(days=1)}),
        ("calendar_publication", {"reference_valid_from": AS_OF + timedelta(days=1)}),
        ("calendar_publication", {"timezone_name": ""}),
    ),
)
def test_nested_binding_values_reject_invalid_public_fields(
    part: str,
    changes: dict[str, object],
) -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )
    nested = getattr(binding, part)

    with pytest.raises(SettlementPlanBindingValidationError):
        replace(binding, **{part: replace(nested, **changes)})


def test_publication_binding_rejects_unknown_timezone() -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(SettlementPlanBindingValidationError):
        replace(
            binding,
            calendar_publication=replace(
                binding.calendar_publication,
                timezone_name="Unknown/CalendarZone",
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "object_payload",
        "account_wrong_type",
        "invalid_market_session",
        "release_date_wrong_type",
        "raw_nested_wrong_type",
        "publication_nested_wrong_type",
        "bad_source_clock",
        "uncovered_session",
        "snapshot_provider_mismatch",
        "first_seen_mismatch",
        "publication_unknown_at_pre_read",
        "publication_window_misses_execution",
        "source_published_after_cutoff",
    ),
)
def test_from_payload_rejects_invalid_nested_links_and_cutoff_relations(
    mutation: str,
) -> None:
    binding = bind_settlement_execution_plan(
        _execution_plan(),
        executed_at=AS_OF + timedelta(minutes=1),
    )
    payload = deepcopy(binding.to_payload())
    snapshot = payload["calendar_snapshot"]
    raw = payload["calendar_raw_reference"]
    publication = payload["calendar_publication"]
    assert type(snapshot) is dict
    assert type(raw) is dict
    assert type(publication) is dict
    if mutation == "object_payload":
        invalid_payload: object = []
    else:
        invalid_payload = payload
        if mutation == "account_wrong_type":
            payload["account_id"] = "7"
        elif mutation == "invalid_market_session":
            payload["market_session"] = "2026-10-16T00:00:00"
        elif mutation == "release_date_wrong_type":
            payload["settlement_release_date"] = 20
        elif mutation == "raw_nested_wrong_type":
            payload["calendar_raw_reference"] = []
        elif mutation == "publication_nested_wrong_type":
            payload["calendar_publication"] = []
        elif mutation == "bad_source_clock":
            payload["bundle_source_observed_at"] = "2026-10-16"
        elif mutation == "uncovered_session":
            payload["market_session"] = "2026-10-15"
        elif mutation == "snapshot_provider_mismatch":
            snapshot["provider_name"] = "other-provider"
        elif mutation == "first_seen_mismatch":
            raw["response_completed_at"] = "2026-10-16T00:30:00Z"
        elif mutation == "publication_unknown_at_pre_read":
            publication["recorded_at"] = "2026-10-16T02:30:00Z"
        elif mutation == "publication_window_misses_execution":
            publication["reference_valid_until"] = "2026-10-16T02:00:30Z"
        elif mutation == "source_published_after_cutoff":
            snapshot["source_published_at"] = "2026-10-16T02:00:30Z"

    with pytest.raises(SettlementPlanBindingValidationError):
        SimulatedSettlementPlanBindingV1.from_payload(invalid_payload)
