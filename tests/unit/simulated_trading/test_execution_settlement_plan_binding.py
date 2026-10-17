"""Contracts for integrity-binding a complete settlement execution plan."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    IdentityEvidenceValidationError,
    PendingSettlementScopeV1,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    SimulatedSettlementPlanBindingV1,
    SimulatedSettlementPlanBindingV2,
    bind_settlement_execution_plan,
    bind_settlement_execution_plan_v2,
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


def _identity_evidence(
    **changes: object,
) -> ExecutionInstrumentIdentityEvidenceV1:
    """Build clearly synthetic identity evidence for Domain contract tests only."""

    values: dict[str, object] = {
        "security_id": "SH.UOW.SECURITY",
        "asset_code": "600000.SH",
        "source_code": "SYNTHETIC:600000",
        "source_exchange": "SSE",
        "source_market": "MAIN",
        "rule_market": "SH",
        "board": "MAIN",
        "snapshot_id": UUID("6b22d9e0-b61b-43fd-8ac4-8112a86f8101"),
        "snapshot_content_hash": "sha256:" + "a" * 64,
        "snapshot_record_digest": "sha256:" + "b" * 64,
        "first_seen_at": AS_OF - timedelta(hours=2),
        "snapshot_recorded_at": AS_OF - timedelta(hours=1),
        "mapping_record_id": UUID("10f8edaf-9eb3-4d81-9090-b2c9d95f81d0"),
        "mapping_id": "synthetic-market-map",
        "mapping_version": "map-v1",
        "mapping_content_hash": "sha256:" + "c" * 64,
        "mapping_record_digest": "sha256:" + "d" * 64,
        "mapping_recorded_at": AS_OF - timedelta(hours=3),
        "response_completed_at": AS_OF - timedelta(hours=2),
        "source_observed_at": AS_OF - timedelta(hours=4),
        "source_available_at": AS_OF - timedelta(hours=3),
        "identity_valid_from": AS_OF - timedelta(days=1),
        "identity_valid_until": AS_OF + timedelta(days=10),
        "must_not_use_for_decision": False,
        "must_not_execute": False,
    }
    values.update(changes)
    return ExecutionInstrumentIdentityEvidenceV1(**values)  # type: ignore[arg-type]


def _execution_plan_v2(
    *,
    identity_evidence: ExecutionInstrumentIdentityEvidenceV1 | None = None,
    source_exchange: str = "SSE",
) -> SettlementExecutionPlanV2:
    """Build a synthetic V2 plan with distinct Rule market and source exchange."""

    base = _execution_plan()
    snapshot = replace(
        base.calendar_evidence.snapshot,
        exchange=source_exchange,
        days=tuple(
            replace(day, exchange=source_exchange) for day in base.calendar_evidence.snapshot.days
        ),
        content_hash="",
        record_digest="",
    )
    calendar = replace(base.calendar_evidence, snapshot=snapshot)
    return SettlementExecutionPlanV2(
        intent=base.intent,
        market_session=base.market_session,
        pre_read_at=base.pre_read_at,
        settlement_lag_sessions=base.settlement_lag_sessions,
        settlement_release_date=base.settlement_release_date,
        settlement_bundle_id=base.settlement_bundle_id,
        settlement_bundle_version=base.settlement_bundle_version,
        settlement_bundle_hash=base.settlement_bundle_hash,
        settlement_policy_id=base.settlement_policy_id,
        settlement_policy_version=base.settlement_policy_version,
        settlement_policy_hash=base.settlement_policy_hash,
        execution_rule_v2_hash=base.execution_rule_v2_hash,
        bundle_source_observed_at=base.bundle_source_observed_at,
        bundle_source_available_at=base.bundle_source_available_at,
        bundle_effective_from=base.bundle_effective_from,
        bundle_valid_until=base.bundle_valid_until,
        calendar_evidence=calendar,
        fee_policy_v2=base.fee_policy_v2,
        identity_evidence=identity_evidence or _identity_evidence(source_exchange=source_exchange),
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


def test_v2_plan_separates_rule_market_from_calendar_exchange_and_round_trips() -> None:
    plan = _execution_plan_v2()

    assert plan.intent.market == "SH"
    assert plan.identity_evidence.rule_market == "SH"
    assert plan.identity_evidence.source_exchange == "SSE"
    assert plan.calendar_evidence.snapshot.exchange == "SSE"
    assert plan.identity_evidence.asset_code != plan.identity_evidence.source_code
    assert plan.amount == Decimal("1000.00")
    plan.validate_at(AS_OF + timedelta(minutes=1))

    binding = bind_settlement_execution_plan_v2(
        plan,
        executed_at=AS_OF + timedelta(minutes=1),
    )
    payload = binding.to_payload()
    restored = SimulatedSettlementPlanBindingV2.from_payload(payload)

    assert payload["schema"] == "simulated-settlement-plan-binding.v2"
    assert set(payload) == {"schema", "common_binding", "identity_evidence"}
    assert "content_hash" not in payload
    assert restored == binding
    assert restored.content_hash == binding.content_hash
    assert len(binding.content_hash) == 64
    assert binding.common_binding.calendar_snapshot.exchange == "SSE"
    assert binding.identity_evidence.source_code == "SYNTHETIC:600000"


def test_v2_binding_has_a_stable_independent_canonical_golden_hash() -> None:
    binding = bind_settlement_execution_plan_v2(
        _execution_plan_v2(),
        executed_at=AS_OF + timedelta(minutes=1),
    )
    encoded = json.dumps(
        binding.to_payload(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert hashlib.sha256(encoded).hexdigest() == (
        "3714e9ecae165f73154bff3ddc0ab94abdcbf1ecd85b7d14df7e9be95037e16a"
    )
    assert binding.content_hash == (
        "3714e9ecae165f73154bff3ddc0ab94abdcbf1ecd85b7d14df7e9be95037e16a"
    )
    assert binding.content_hash not in binding.to_payload()


def test_v1_plan_and_binding_keep_the_existing_market_exchange_contract() -> None:
    plan = _execution_plan()
    binding = bind_settlement_execution_plan(
        plan,
        executed_at=AS_OF + timedelta(minutes=1),
    )
    assert binding.calendar_snapshot.exchange == plan.intent.market
    with pytest.raises(ValueError):
        replace(
            plan,
            calendar_evidence=_execution_plan_v2(source_exchange="SSE").calendar_evidence,
        )


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    (
        ({"must_not_use_for_decision": True}, "IDENTITY_SOURCE_RESTRICTED"),
        ({"must_not_execute": True}, "IDENTITY_SOURCE_RESTRICTED"),
        ({"source_observed_at": None}, "IDENTITY_SOURCE_CLOCK_UNKNOWN"),
        ({"source_available_at": None}, "IDENTITY_SOURCE_CLOCK_UNKNOWN"),
        ({"source_market": None}, "IDENTITY_SOURCE_MARKET_UNKNOWN"),
        (
            {
                "source_available_at": AS_OF + timedelta(seconds=1),
                "first_seen_at": AS_OF + timedelta(seconds=2),
                "response_completed_at": AS_OF + timedelta(seconds=2),
                "snapshot_recorded_at": AS_OF + timedelta(seconds=3),
            },
            "IDENTITY_EVIDENCE_NOT_KNOWN_AT_CUTOFF",
        ),
        (
            {"identity_valid_from": AS_OF + timedelta(seconds=1)},
            "IDENTITY_EVIDENCE_OUTSIDE_VALIDITY_WINDOW",
        ),
    ),
)
def test_v2_plan_fails_closed_for_restricted_unknown_or_out_of_window_identity(
    changes: dict[str, object],
    expected_code: str,
) -> None:
    evidence = _identity_evidence(**changes)
    assert evidence.to_payload()["must_not_execute"] is evidence.must_not_execute
    assert evidence.to_payload()["source_observed_at"] == (
        evidence.source_observed_at.isoformat().replace("+00:00", "Z")
        if evidence.source_observed_at is not None
        else None
    )
    with pytest.raises(IdentityEvidenceValidationError) as error:
        evidence.validate_for(intent=_execution_plan().intent, as_of=AS_OF)
    assert error.value.code == expected_code


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("source_code", " 600000.SH", "IDENTITY_EVIDENCE_TOKEN_INVALID"),
        ("snapshot_content_hash", "a" * 64, "IDENTITY_EVIDENCE_HASH_INVALID"),
        ("must_not_execute", 1, "IDENTITY_EVIDENCE_FLAG_INVALID"),
        ("source_observed_at", "2026-10-16T02:00:00+00:00", "IDENTITY_EVIDENCE_TIME_INVALID"),
    ),
)
def test_identity_payload_rejects_invalid_typed_fields(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    payload = _identity_evidence().to_payload()
    payload[field] = value
    with pytest.raises(IdentityEvidenceValidationError) as error:
        ExecutionInstrumentIdentityEvidenceV1.from_payload(payload)
    assert error.value.code == expected_code


def test_identity_payload_preserves_unknown_clocks_and_restrictive_flags() -> None:
    evidence = _identity_evidence(
        source_observed_at=None,
        source_available_at=None,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )

    payload = evidence.to_payload()
    restored = ExecutionInstrumentIdentityEvidenceV1.from_payload(payload)

    assert restored == evidence
    assert payload["source_observed_at"] is None
    assert payload["source_available_at"] is None
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True


def test_identity_source_availability_cannot_follow_the_captured_response() -> None:
    response_completed_at = AS_OF - timedelta(minutes=10)
    evidence = _identity_evidence(
        first_seen_at=response_completed_at,
        snapshot_recorded_at=AS_OF - timedelta(minutes=5),
        response_completed_at=response_completed_at,
        source_observed_at=AS_OF - timedelta(minutes=20),
        source_available_at=AS_OF - timedelta(minutes=1),
    )

    with pytest.raises(IdentityEvidenceValidationError) as error:
        evidence.validate_at(as_of=AS_OF)
    assert error.value.code == "IDENTITY_SOURCE_CLOCK_ORDER_INVALID"


def test_identity_source_availability_equal_to_response_completion_is_valid() -> None:
    response_completed_at = AS_OF - timedelta(minutes=10)
    evidence = _identity_evidence(
        first_seen_at=response_completed_at,
        snapshot_recorded_at=AS_OF - timedelta(minutes=5),
        response_completed_at=response_completed_at,
        source_observed_at=response_completed_at,
        source_available_at=response_completed_at,
    )

    evidence.validate_for(intent=_execution_plan().intent, as_of=AS_OF)


def test_identity_payload_rejects_unknown_or_missing_fields_and_wrong_schema() -> None:
    payload = _identity_evidence().to_payload()
    for invalid in (
        {**payload, "extra": "ignored fields are forbidden"},
        {key: value for key, value in payload.items() if key != "source_code"},
        {**payload, "schema": "simulated-execution-instrument-identity.v2"},
        [],
    ):
        with pytest.raises(IdentityEvidenceValidationError):
            ExecutionInstrumentIdentityEvidenceV1.from_payload(invalid)


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("snapshot_id", 7, "IDENTITY_EVIDENCE_UUID_INVALID"),
        ("snapshot_id", "not-a-uuid", "IDENTITY_EVIDENCE_UUID_INVALID"),
        (
            "snapshot_id",
            "6B22D9E0-B61B-43FD-8AC4-8112A86F8101",
            "IDENTITY_EVIDENCE_UUID_NOT_CANONICAL",
        ),
        ("first_seen_at", "2026-10-16T00:00:00+00:00", "IDENTITY_EVIDENCE_TIME_INVALID"),
        ("first_seen_at", "not-a-timeZ", "IDENTITY_EVIDENCE_TIME_INVALID"),
        (
            "first_seen_at",
            "2026-10-16T00:00:00.000000Z",
            "IDENTITY_EVIDENCE_TIME_NOT_CANONICAL",
        ),
        ("source_market", 1, "IDENTITY_EVIDENCE_PAYLOAD_INVALID"),
        ("source_code", 600000, "IDENTITY_EVIDENCE_PAYLOAD_INVALID"),
        ("source_available_at", 1, "IDENTITY_EVIDENCE_PAYLOAD_INVALID"),
        ("source_observed_at", 1, "IDENTITY_EVIDENCE_PAYLOAD_INVALID"),
    ),
)
def test_identity_decoder_rejects_noncanonical_uuid_time_and_nullable_types(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    payload = _identity_evidence().to_payload()
    payload[field] = value

    with pytest.raises(IdentityEvidenceValidationError) as error:
        ExecutionInstrumentIdentityEvidenceV1.from_payload(payload)
    assert error.value.code == expected_code


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("security_id", "", "IDENTITY_EVIDENCE_TOKEN_INVALID"),
        ("source_exchange", "E" * 33, "IDENTITY_SOURCE_EXCHANGE_INVALID"),
        ("snapshot_id", "6b22d9e0-b61b-43fd-8ac4-8112a86f8101", "IDENTITY_EVIDENCE_UUID_INVALID"),
        ("snapshot_content_hash", "x" * 64, "IDENTITY_EVIDENCE_HASH_INVALID"),
        ("first_seen_at", AS_OF, "IDENTITY_RESPONSE_CLOCK_MISMATCH"),
        (
            "snapshot_recorded_at",
            AS_OF - timedelta(hours=3),
            "IDENTITY_KNOWLEDGE_CLOCK_ORDER_INVALID",
        ),
        (
            "mapping_recorded_at",
            AS_OF - timedelta(minutes=30),
            "IDENTITY_KNOWLEDGE_CLOCK_ORDER_INVALID",
        ),
        (
            "identity_valid_until",
            AS_OF - timedelta(days=1),
            "IDENTITY_VALIDITY_WINDOW_INVALID",
        ),
        ("must_not_execute", 1, "IDENTITY_EVIDENCE_FLAG_INVALID"),
    ),
)
def test_identity_value_rejects_invalid_identity_clock_flag_and_exchange_fields(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    with pytest.raises(IdentityEvidenceValidationError) as error:
        replace(_identity_evidence(), **{field: value})
    assert error.value.code == expected_code


def test_identity_exchange_length_matches_storage_and_api_boundary() -> None:
    exact = "E" * 32
    evidence = _identity_evidence(source_exchange=exact)
    assert ExecutionInstrumentIdentityEvidenceV1.from_payload(evidence.to_payload()) == evidence
    with pytest.raises(IdentityEvidenceValidationError) as error:
        PendingSettlementScopeV1(
            earliest_session=date(2026, 10, 16),
            source_exchange="E" * 33,
        )
    assert error.value.code == "PENDING_SETTLEMENT_SCOPE_INVALID"


@pytest.mark.parametrize(
    "invalid_time",
    (
        datetime(2026, 10, 16, 2, 0),
        datetime(2026, 10, 16, 2, 0, tzinfo=_NoOffsetTimezone()),
        datetime(2026, 10, 16, 2, 0, tzinfo=_BrokenTimezone()),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-14))),
        cast(datetime, "not a datetime"),
    ),
)
def test_identity_value_rejects_unsafe_datetime_normalization(invalid_time: datetime) -> None:
    with pytest.raises(IdentityEvidenceValidationError) as error:
        replace(_identity_evidence(), first_seen_at=invalid_time)
    assert error.value.code == "IDENTITY_EVIDENCE_TIME_INVALID"


def test_identity_validator_rejects_reversed_source_clocks_and_accepts_window_start() -> None:
    reversed_clocks = _identity_evidence(
        source_observed_at=AS_OF - timedelta(minutes=2),
        source_available_at=AS_OF - timedelta(minutes=3),
    )
    with pytest.raises(IdentityEvidenceValidationError) as error:
        reversed_clocks.validate_at(as_of=AS_OF)
    assert error.value.code == "IDENTITY_SOURCE_CLOCK_ORDER_INVALID"

    at_start = _identity_evidence(identity_valid_from=AS_OF)
    at_start.validate_at(as_of=AS_OF)
    at_end = _identity_evidence(identity_valid_until=AS_OF)
    with pytest.raises(IdentityEvidenceValidationError) as end_error:
        at_end.validate_at(as_of=AS_OF)
    assert end_error.value.code == "IDENTITY_EVIDENCE_OUTSIDE_VALIDITY_WINDOW"


@pytest.mark.parametrize(
    "invalid_cutoff",
    (
        datetime(2026, 10, 16, 2, 0),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-14))),
    ),
)
def test_identity_validator_rejects_naive_or_unrepresentable_cutoff(
    invalid_cutoff: datetime,
) -> None:
    with pytest.raises(IdentityEvidenceValidationError) as error:
        _identity_evidence().validate_at(as_of=invalid_cutoff)
    assert error.value.code == "IDENTITY_EVIDENCE_TIME_INVALID"


def test_identity_intent_validation_is_exact_and_revalidates_mutated_intents() -> None:
    evidence = _identity_evidence()
    valid_intent = _execution_plan().intent
    evidence.validate_for(intent=valid_intent, as_of=AS_OF)
    with pytest.raises(IdentityEvidenceValidationError) as asset_error:
        evidence.validate_for(
            intent=replace(valid_intent, asset_code="000001.SZ"),
            as_of=AS_OF,
        )
    assert asset_error.value.code == "IDENTITY_INTENT_MISMATCH"
    with pytest.raises(IdentityEvidenceValidationError) as board_error:
        evidence.validate_for(
            intent=replace(valid_intent, board="STAR"),
            as_of=AS_OF,
        )
    assert board_error.value.code == "IDENTITY_BOARD_MISMATCH"
    with pytest.raises(IdentityEvidenceValidationError) as type_error:
        evidence.validate_for(intent=cast(SimulatedTradeIntent, object()), as_of=AS_OF)
    assert type_error.value.code == "IDENTITY_INTENT_INVALID"

    corrupted_intent = replace(valid_intent)
    object.__setattr__(corrupted_intent, "quantity", Decimal("NaN"))
    with pytest.raises(IdentityEvidenceValidationError) as corrupted_error:
        evidence.validate_for(intent=corrupted_intent, as_of=AS_OF)
    assert corrupted_error.value.code == "IDENTITY_INTENT_INVALID"


def test_identity_payload_revalidates_mutated_frozen_evidence_before_serializing() -> None:
    evidence = _identity_evidence()
    object.__setattr__(evidence, "source_code", "bad source code")

    with pytest.raises(IdentityEvidenceValidationError) as error:
        evidence.to_payload()
    assert error.value.code == "IDENTITY_EVIDENCE_TOKEN_INVALID"


def test_v2_plan_rejects_non_identity_receipt_and_revalidates_at_execution_cutoff() -> None:
    with pytest.raises(IdentityEvidenceValidationError) as type_error:
        replace(
            _execution_plan_v2(),
            identity_evidence=cast(ExecutionInstrumentIdentityEvidenceV1, object()),
        )
    assert type_error.value.code == "IDENTITY_EVIDENCE_TYPE_INVALID"

    plan = _execution_plan_v2()
    object.__setattr__(plan.identity_evidence, "must_not_execute", True)
    with pytest.raises(IdentityEvidenceValidationError) as evidence_error:
        plan.validate_at(AS_OF + timedelta(minutes=1))
    assert evidence_error.value.code == "IDENTITY_SOURCE_RESTRICTED"


def test_identity_payload_rejects_scope_mismatch_and_v2_rejects_wrong_calendar_exchange() -> None:
    with pytest.raises(IdentityEvidenceValidationError) as security_error:
        _identity_evidence().validate_for(
            intent=replace(_execution_plan().intent, security_id="SZ.UOW.SECURITY"),
            as_of=AS_OF,
        )
    assert security_error.value.code == "IDENTITY_INTENT_MISMATCH"

    with pytest.raises(IdentityEvidenceValidationError) as market_error:
        _identity_evidence().validate_for(
            intent=replace(_execution_plan().intent, market="SZ"),
            as_of=AS_OF,
        )
    assert market_error.value.code == "IDENTITY_RULE_MARKET_MISMATCH"

    plan = _execution_plan_v2(
        identity_evidence=_identity_evidence(source_exchange="SZSE"),
        source_exchange="SZSE",
    )
    assert plan.intent.market == "SH"
    assert plan.calendar_evidence.snapshot.exchange == "SZSE"
    assert plan.identity_evidence.source_exchange == "SZSE"

    with pytest.raises(ValueError):
        _execution_plan_v2(
            identity_evidence=_identity_evidence(source_exchange="SZSE"),
            source_exchange="SSE",
        )


def test_v2_binding_rejects_tampered_envelopes_and_old_factory_rejects_v2_plan() -> None:
    plan = _execution_plan_v2()
    with pytest.raises(SettlementPlanBindingValidationError):
        bind_settlement_execution_plan(
            cast(SettlementExecutionPlan, plan),
            executed_at=AS_OF + timedelta(minutes=1),
        )
    binding = bind_settlement_execution_plan_v2(
        plan,
        executed_at=AS_OF + timedelta(minutes=1),
    )
    payload = binding.to_payload()
    for invalid in (
        {**payload, "extra": "not allowed"},
        {key: value for key, value in payload.items() if key != "identity_evidence"},
        {**payload, "schema": "simulated-settlement-plan-binding.v1"},
    ):
        with pytest.raises(SettlementPlanBindingValidationError):
            SimulatedSettlementPlanBindingV2.from_payload(invalid)


def test_pending_settlement_scope_is_exact_and_exchange_specific() -> None:
    scope = PendingSettlementScopeV1(
        earliest_session=date(2026, 10, 16),
        source_exchange="SSE",
    )
    assert scope.to_payload() == {
        "schema": "simulated-pending-settlement-scope.v1",
        "earliest_session": "2026-10-16",
        "source_exchange": "SSE",
    }
    with pytest.raises(IdentityEvidenceValidationError):
        PendingSettlementScopeV1(earliest_session=AS_OF, source_exchange="SSE")  # type: ignore[arg-type]
    with pytest.raises(IdentityEvidenceValidationError):
        PendingSettlementScopeV1(earliest_session=date(2026, 10, 16), source_exchange=" ")


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
