"""Focused contracts for the simulated current-reference domain seam.

These tests use synthetic receipts only. They do not qualify any provider,
grant broker authority, or claim historical point-in-time evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any
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
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    SimulatedSettlementPlanBindingV1,
    SimulatedSettlementPlanBindingV2,
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
    SimulatedSettlementContractError,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)

_TARGET_MODULE = "apps.simulated_trading.domain.execution_current_reference"
AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
_OCCURRENCE_ID = UUID("1ef87e17-6501-4ce1-bdbe-550f64509b01")


@pytest.fixture
def subject() -> ModuleType:
    """Import the planned module at test time and report only a missing feature as RED."""

    try:
        module = importlib.import_module(_TARGET_MODULE)
    except ModuleNotFoundError as error:
        if error.name == _TARGET_MODULE:
            pytest.fail(f"missing required feature module: {_TARGET_MODULE}", pytrace=False)
        raise
    required_symbols = (
        "CurrentReferenceSelectionV1",
        "ExecutionInstrumentIdentityEvidenceV2",
        "SettlementExecutionPlanV3",
        "SimulatedSettlementPlanBindingV3",
        "bind_settlement_execution_plan_v3",
    )
    missing = tuple(name for name in required_symbols if not hasattr(module, name))
    if missing:
        pytest.fail(f"missing required current-reference symbols: {missing!r}", pytrace=False)
    return module


def _selection(
    subject: ModuleType,
    *,
    selected_at: datetime = AS_OF,
    profile_activated_at: datetime = AS_OF - timedelta(days=2),
    runtime_snapshot_generated_at: datetime = AS_OF - timedelta(days=1),
    max_local_reference_age_seconds: int = 10_800,
    **changes: object,
) -> Any:
    """Construct one synthetic ConfigCenter selection receipt."""

    values: dict[str, object] = {
        "purpose": "normal_simulated_current_reference",
        "profile_id": "fixture-profile-4",
        "profile_key": "instrument_reference_selector",
        "environment": "test",
        "profile_version": 4,
        "profile_content_hash": "a" * 64,
        "runtime_snapshot_id": "fixture-runtime-snapshot-4",
        "runtime_snapshot_hash": "b" * 64,
        "selector_content_hash": "c" * 64,
        "profile_activated_at": profile_activated_at,
        "runtime_snapshot_generated_at": runtime_snapshot_generated_at,
        "selected_at": selected_at,
        "max_local_reference_age_seconds": max_local_reference_age_seconds,
    }
    values.update(changes)
    selection_type = subject.CurrentReferenceSelectionV1
    return selection_type(**values)


def _legacy_source_evidence(**changes: object) -> ExecutionInstrumentIdentityEvidenceV1:
    """Build the exact existing V1 shape, preserving its original wire fields."""

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


def _current_identity(
    subject: ModuleType,
    *,
    selection_changes: dict[str, object] | None = None,
    source_changes: dict[str, object] | None = None,
    source_occurrence_id: UUID = _OCCURRENCE_ID,
    reference_response_completed_at: datetime = AS_OF - timedelta(hours=2),
    validity_changes: dict[str, object] | None = None,
) -> Any:
    """Build a V2 receipt whose validity window derives from its exact occurrence."""

    selection = _selection(subject, **(selection_changes or {}))
    source_values: dict[str, object] = {
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
        "source_observed_at": None,
        "source_available_at": None,
        "identity_valid_from": AS_OF - timedelta(hours=1),
        "identity_valid_until": AS_OF + timedelta(hours=1),
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    source_values.update(source_changes or {})
    response_completed_at = source_values["response_completed_at"]
    assert isinstance(response_completed_at, datetime)
    source_values["first_seen_at"] = response_completed_at

    window_start = max(
        selection.profile_activated_at,
        source_values["snapshot_recorded_at"],
        source_values["mapping_recorded_at"],
    )
    max_age = selection.max_local_reference_age_seconds
    if type(max_age) is int and max_age > 0:
        try:
            window_end = reference_response_completed_at + timedelta(seconds=max_age)
        except OverflowError:
            window_end = datetime.max.replace(tzinfo=UTC)
    else:
        window_end = AS_OF + timedelta(days=365)
    source_values["identity_valid_from"] = window_start
    source_values["identity_valid_until"] = window_end
    source_values.update(validity_changes or {})
    source_evidence = ExecutionInstrumentIdentityEvidenceV1(**source_values)  # type: ignore[arg-type]
    evidence_type = subject.ExecutionInstrumentIdentityEvidenceV2
    return evidence_type(
        source_evidence=source_evidence,
        selection=selection,
        source_occurrence_id=source_occurrence_id,
        reference_response_completed_at=reference_response_completed_at,
    )


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


def _base_plan(
    *,
    side: SimulatedTradeSide,
    idempotency_key: str = "current-reference-fixture-1",
    reason: str = "current-reference unit fixture",
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
        source_published_at=None,
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
    return SettlementExecutionPlan(
        intent=SimulatedTradeIntent(
            account_id=7,
            user_id=11,
            idempotency_key=idempotency_key,
            side=side,
            security_id="SH.UOW.SECURITY",
            asset_code="600000.SH",
            asset_name="Fixture Security",
            asset_type="equity",
            market="SH",
            board="MAIN",
            quantity=Decimal("100"),
            price=Decimal("10.00"),
            reason=reason,
            signal_id=23,
        ),
        market_session=date(2026, 10, 16),
        pre_read_at=AS_OF,
        settlement_lag_sessions=2,
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


def _plan_v3(
    subject: ModuleType,
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    identity_evidence: Any | None = None,
) -> Any:
    """Build a plan with a distinct Rule market and calendar exchange."""

    base = _base_plan(side=side)
    source_exchange = "SSE"
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
    if identity_evidence is None:
        identity_evidence = _current_identity(subject)
    plan_type = subject.SettlementExecutionPlanV3
    return plan_type(
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
        identity_evidence=identity_evidence,
    )


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_selection_codec_is_exact_canonical_and_round_trips(subject: ModuleType) -> None:
    selection = _selection(subject)
    payload = selection.to_payload()

    assert set(payload) == {
        "schema",
        "purpose",
        "profile_id",
        "profile_key",
        "environment",
        "profile_version",
        "profile_content_hash",
        "runtime_snapshot_id",
        "runtime_snapshot_hash",
        "selector_content_hash",
        "profile_activated_at",
        "runtime_snapshot_generated_at",
        "selected_at",
        "max_local_reference_age_seconds",
    }
    assert payload["schema"] == "simulated-current-reference-selection.v1"
    assert payload["purpose"] == "normal_simulated_current_reference"
    assert payload["profile_activated_at"] == "2026-10-14T02:00:00Z"
    assert payload["runtime_snapshot_generated_at"] == "2026-10-15T02:00:00Z"
    assert payload["selected_at"] == "2026-10-16T02:00:00Z"
    assert selection.content_hash == _canonical_sha256(payload)
    restored = type(selection).from_payload(payload)
    assert restored == selection
    assert restored.content_hash == selection.content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_version", True),
        ("profile_version", 0),
        ("max_local_reference_age_seconds", True),
        ("max_local_reference_age_seconds", 0),
        ("max_local_reference_age_seconds", -1),
        ("profile_content_hash", "sha256:" + "a" * 64),
        ("purpose", "historical_backtest"),
        ("profile_id", "bad token"),
    ),
)
def test_selection_decoder_rejects_invalid_types_values_and_purpose(
    subject: ModuleType, field: str, value: object
) -> None:
    payload = _selection(subject).to_payload()
    payload[field] = value
    with pytest.raises(SimulatedSettlementContractError):
        subject.CurrentReferenceSelectionV1.from_payload(payload)


@pytest.mark.parametrize("mutation", ("extra", "missing", "noncanonical", "reversed"))
def test_selection_decoder_rejects_malformed_keys_and_clock_order(
    subject: ModuleType, mutation: str
) -> None:
    payload = _selection(subject).to_payload()
    if mutation == "extra":
        payload["secret_copy"] = "must-not-be-retained"
    elif mutation == "missing":
        del payload["selector_content_hash"]
    elif mutation == "noncanonical":
        payload["selected_at"] = "2026-10-16T02:00:00+00:00"
    else:
        payload["profile_activated_at"] = "2026-10-16T03:00:00Z"
    with pytest.raises(SimulatedSettlementContractError):
        subject.CurrentReferenceSelectionV1.from_payload(payload)


@pytest.mark.parametrize(
    "source_changes",
    (
        {},
        {"source_observed_at": None, "source_available_at": AS_OF - timedelta(hours=3)},
        {"source_observed_at": AS_OF - timedelta(hours=4), "source_available_at": None},
    ),
)
def test_v2_round_trip_preserves_unknown_clocks_and_true_flags(
    subject: ModuleType, source_changes: dict[str, object]
) -> None:
    evidence = _current_identity(subject, source_changes=source_changes)
    payload = evidence.to_payload()
    source_payload = payload["source_evidence"]

    assert set(payload) == {
        "schema",
        "source_evidence",
        "selection",
        "source_occurrence_id",
        "reference_response_completed_at",
    }
    assert payload["schema"] == "simulated-execution-instrument-identity.v2"
    assert type(source_payload) is dict
    assert source_payload["must_not_use_for_decision"] is True
    assert source_payload["must_not_execute"] is True
    assert evidence.content_hash == _canonical_sha256(payload)
    assert type(evidence).from_payload(payload) == evidence
    assert (
        evidence.validate_for(intent=_base_plan(side=SimulatedTradeSide.BUY).intent, as_of=AS_OF)
        is None
    )


def test_unchanged_v1_validator_still_rejects_unknown_or_restricted_evidence() -> None:
    intent = _base_plan(side=SimulatedTradeSide.BUY).intent
    with pytest.raises(IdentityEvidenceValidationError) as restricted:
        _legacy_source_evidence(must_not_execute=True).validate_for(intent=intent, as_of=AS_OF)
    assert restricted.value.code == "IDENTITY_SOURCE_RESTRICTED"
    with pytest.raises(IdentityEvidenceValidationError) as unknown:
        _legacy_source_evidence(source_observed_at=None, source_available_at=None).validate_for(
            intent=intent, as_of=AS_OF
        )
    assert unknown.value.code == "IDENTITY_SOURCE_CLOCK_UNKNOWN"


def test_current_window_uses_occurrence_clock_and_reuses_old_mapping(
    subject: ModuleType,
) -> None:
    evidence = _current_identity(
        subject,
        source_changes={"mapping_recorded_at": datetime(2016, 1, 1, tzinfo=UTC)},
    )
    expected_start = AS_OF - timedelta(hours=1)
    expected_end = AS_OF + timedelta(hours=1)

    assert evidence.source_evidence.mapping_recorded_at == datetime(2016, 1, 1, tzinfo=UTC)
    assert evidence.source_evidence.identity_valid_from == expected_start
    assert evidence.source_evidence.identity_valid_until == expected_end
    with pytest.raises(IdentityEvidenceValidationError):
        evidence.validate_at(as_of=AS_OF - timedelta(microseconds=1))
    assert evidence.validate_at(as_of=AS_OF) is None
    assert evidence.validate_at(as_of=expected_end - timedelta(microseconds=1)) is None
    with pytest.raises(IdentityEvidenceValidationError):
        evidence.validate_at(as_of=expected_end)


def test_new_unrelated_batch_response_does_not_renew_old_occurrence(subject: ModuleType) -> None:
    occurrence_at = AS_OF - timedelta(hours=3)
    batch_at = AS_OF - timedelta(minutes=90)
    recorded_at = AS_OF - timedelta(minutes=80)
    age = 7_200
    selection = _selection(subject, max_local_reference_age_seconds=age)
    source = _legacy_source_evidence(
        first_seen_at=batch_at,
        response_completed_at=batch_at,
        snapshot_recorded_at=recorded_at,
        mapping_recorded_at=AS_OF - timedelta(hours=4),
        identity_valid_from=recorded_at,
        identity_valid_until=occurrence_at + timedelta(seconds=age),
        source_observed_at=None,
        source_available_at=None,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )

    assert batch_at > occurrence_at
    assert batch_at + timedelta(seconds=age) > AS_OF
    assert occurrence_at + timedelta(seconds=age) < AS_OF
    with pytest.raises(IdentityEvidenceValidationError):
        subject.ExecutionInstrumentIdentityEvidenceV2(
            source_evidence=source,
            selection=selection,
            source_occurrence_id=_OCCURRENCE_ID,
            reference_response_completed_at=occurrence_at,
        )


@pytest.mark.parametrize(
    ("source_changes", "reference_at", "selection_changes"),
    (
        ({"response_completed_at": AS_OF - timedelta(hours=3)}, AS_OF - timedelta(hours=2), {}),
        (
            {"source_observed_at": AS_OF - timedelta(minutes=30)},
            AS_OF - timedelta(hours=2),
            {},
        ),
        (
            {"source_available_at": AS_OF - timedelta(minutes=30)},
            AS_OF - timedelta(hours=2),
            {},
        ),
        (
            {
                "response_completed_at": AS_OF - timedelta(minutes=30),
                "snapshot_recorded_at": AS_OF - timedelta(minutes=20),
                "source_observed_at": AS_OF - timedelta(hours=1),
                "source_available_at": AS_OF - timedelta(hours=2),
            },
            AS_OF - timedelta(hours=1),
            {},
        ),
        ({"source_market": None}, AS_OF - timedelta(hours=2), {}),
        (
            {
                "response_completed_at": AS_OF + timedelta(seconds=2),
                "snapshot_recorded_at": AS_OF + timedelta(seconds=3),
            },
            AS_OF + timedelta(seconds=1),
            {},
        ),
        (
            {
                "response_completed_at": AS_OF - timedelta(hours=3),
                "snapshot_recorded_at": AS_OF - timedelta(hours=1),
                "mapping_recorded_at": AS_OF - timedelta(minutes=90),
            },
            AS_OF - timedelta(hours=3),
            {"selected_at": AS_OF - timedelta(hours=2)},
        ),
    ),
)
def test_v2_rejects_future_occurrence_clocks_bad_source_order_or_missing_market(
    subject: ModuleType,
    source_changes: dict[str, object],
    reference_at: datetime,
    selection_changes: dict[str, object],
) -> None:
    with pytest.raises(IdentityEvidenceValidationError):
        _current_identity(
            subject,
            source_changes=source_changes,
            reference_response_completed_at=reference_at,
            selection_changes=selection_changes,
        )


def test_v2_decoder_rejects_malformed_occurrence_and_nested_receipts(
    subject: ModuleType,
) -> None:
    evidence = _current_identity(subject)
    evidence_type = type(evidence)

    for mutation in ("bad_uuid", "extra", "missing", "noncanonical_clock", "wrong_window"):
        payload = evidence.to_payload()
        if mutation == "bad_uuid":
            payload["source_occurrence_id"] = "not-a-uuid"
        elif mutation == "extra":
            payload["unexpected"] = "value"
        elif mutation == "missing":
            del payload["selection"]
        elif mutation == "noncanonical_clock":
            payload["reference_response_completed_at"] = "2026-10-16T00:00:00+00:00"
        else:
            nested = payload["source_evidence"]
            assert type(nested) is dict
            nested["identity_valid_until"] = "2026-10-16T02:00:00Z"
        with pytest.raises(SimulatedSettlementContractError):
            evidence_type.from_payload(payload)


def test_v2_binds_exact_intent_scope_and_normal_simulation_only(subject: ModuleType) -> None:
    evidence = _current_identity(subject)
    intent = _base_plan(side=SimulatedTradeSide.BUY).intent
    for changed in (
        replace(intent, security_id="OTHER.SECURITY"),
        replace(intent, asset_code="000001.SZ"),
        replace(intent, market="SZ"),
        replace(intent, board="GEM"),
    ):
        with pytest.raises(IdentityEvidenceValidationError):
            evidence.validate_for(intent=changed, as_of=AS_OF)


def test_v3_plan_and_binding_preserve_existing_contract_for_buy_sell(subject: ModuleType) -> None:
    plan_type = subject.SettlementExecutionPlanV3
    assert plan_type.__bases__ == (SettlementExecutionPlan,)
    assert {field.name for field in fields(plan_type)} == {
        *(field.name for field in fields(SettlementExecutionPlan)),
        "identity_evidence",
    }
    bind = subject.bind_settlement_execution_plan_v3

    for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL):
        plan = _plan_v3(subject, side=side)
        assert plan.pre_read_at == plan.identity_evidence.selection.selected_at == AS_OF
        assert plan._expected_calendar_exchange == "SSE"
        assert plan.settlement_release_date == (
            date(2026, 10, 20) if side is SimulatedTradeSide.BUY else None
        )
        assert plan.validate_at(AS_OF + timedelta(minutes=1)) is None
        binding = bind(plan, executed_at=AS_OF + timedelta(minutes=1))
        payload = binding.to_payload()
        assert set(payload) == {"schema", "common_binding", "identity_evidence"}
        assert payload["schema"] == "simulated-settlement-plan-binding.v3"
        assert binding.content_hash == _canonical_sha256(payload)
        assert type(binding).from_payload(payload) == binding

    old_selection = _current_identity(
        subject, selection_changes={"selected_at": AS_OF - timedelta(minutes=1)}
    )
    with pytest.raises(IdentityEvidenceValidationError):
        _plan_v3(subject, identity_evidence=old_selection)

    plan = _plan_v3(subject)
    expiry = plan.identity_evidence.reference_response_completed_at + timedelta(
        seconds=plan.identity_evidence.selection.max_local_reference_age_seconds
    )
    with pytest.raises(IdentityEvidenceValidationError):
        plan.validate_at(expiry)


def test_v3_binding_nested_tampering_changes_hash_and_invalid_window_is_rejected(
    subject: ModuleType,
) -> None:
    binding = subject.bind_settlement_execution_plan_v3(
        _plan_v3(subject), executed_at=AS_OF + timedelta(minutes=1)
    )
    changed = binding.to_payload()
    identity = changed["identity_evidence"]
    assert type(identity) is dict
    selection = identity["selection"]
    assert type(selection) is dict
    selection["selector_content_hash"] = "f" * 64
    assert type(binding).from_payload(changed).content_hash != binding.content_hash

    invalid = binding.to_payload()
    identity = invalid["identity_evidence"]
    assert type(identity) is dict
    source = identity["source_evidence"]
    assert type(source) is dict
    source["identity_valid_from"] = "2026-10-16T00:00:00Z"
    with pytest.raises(SimulatedSettlementContractError):
        type(binding).from_payload(invalid)


def test_age_addition_overflow_is_a_stable_identity_error(subject: ModuleType) -> None:
    last = datetime.max.replace(tzinfo=UTC)
    with pytest.raises(IdentityEvidenceValidationError):
        _current_identity(
            subject,
            selection_changes={
                "profile_activated_at": last - timedelta(seconds=3),
                "runtime_snapshot_generated_at": last - timedelta(seconds=2),
                "selected_at": last,
                "max_local_reference_age_seconds": 10**30,
            },
            source_changes={
                "response_completed_at": last - timedelta(seconds=2),
                "snapshot_recorded_at": last - timedelta(seconds=1),
                "mapping_recorded_at": last - timedelta(seconds=3),
            },
            reference_response_completed_at=last - timedelta(seconds=2),
        )


def test_existing_v1_and_v2_binding_codec_golden_is_unchanged() -> None:
    base = _base_plan(
        side=SimulatedTradeSide.BUY,
        idempotency_key="settlement-binding-fixture-1",
        reason="settlement binding fixture",
    )
    snapshot = replace(
        base.calendar_evidence.snapshot,
        exchange="SSE",
        days=tuple(replace(day, exchange="SSE") for day in base.calendar_evidence.snapshot.days),
        content_hash="",
        record_digest="",
    )
    plan = SettlementExecutionPlanV2(
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
        calendar_evidence=replace(base.calendar_evidence, snapshot=snapshot),
        fee_policy_v2=base.fee_policy_v2,
        identity_evidence=_legacy_source_evidence(),
    )
    binding = bind_settlement_execution_plan_v2(plan, executed_at=AS_OF + timedelta(minutes=1))
    assert isinstance(binding, SimulatedSettlementPlanBindingV2)
    assert isinstance(binding.common_binding, SimulatedSettlementPlanBindingV1)
    assert binding.content_hash == (
        "3714e9ecae165f73154bff3ddc0ab94abdcbf1ecd85b7d14df7e9be95037e16a"
    )
    assert _canonical_sha256(binding.to_payload()) == binding.content_hash


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        (
            "schema",
            "simulated-current-reference-selection.v2",
            "CURRENT_REFERENCE_SCHEMA_UNSUPPORTED",
        ),
        ("purpose", None, "CURRENT_REFERENCE_PURPOSE_UNSUPPORTED"),
    ),
)
def test_selection_decoder_rejects_unsupported_wire_version_and_untyped_purpose(
    subject: ModuleType, field: str, value: object, code: str
) -> None:
    payload = _selection(subject).to_payload()
    payload[field] = value

    with pytest.raises(IdentityEvidenceValidationError) as error:
        subject.CurrentReferenceSelectionV1.from_payload(payload)

    assert error.value.code == code


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("source_evidence", object(), "IDENTITY_EVIDENCE_TYPE_INVALID"),
        ("selection", object(), "CURRENT_REFERENCE_SELECTION_TYPE_INVALID"),
        ("source_occurrence_id", str(_OCCURRENCE_ID), "IDENTITY_EVIDENCE_UUID_INVALID"),
    ),
)
def test_v2_identity_constructor_requires_exact_nested_receipts(
    subject: ModuleType, field: str, value: object, code: str
) -> None:
    evidence = _current_identity(subject)

    with pytest.raises(IdentityEvidenceValidationError) as error:
        replace(evidence, **{field: value})

    assert error.value.code == code


def test_v2_identity_rejects_empty_local_validity_window(subject: ModuleType) -> None:
    evidence = _current_identity(subject)
    object.__setattr__(evidence.selection, "profile_activated_at", AS_OF)
    object.__setattr__(evidence.selection, "runtime_snapshot_generated_at", AS_OF)
    object.__setattr__(evidence.selection, "max_local_reference_age_seconds", 3_600)

    with pytest.raises(IdentityEvidenceValidationError) as error:
        evidence.__post_init__()

    assert error.value.code == "IDENTITY_EVIDENCE_VALIDITY_WINDOW_INVALID"


def test_v2_decoder_rejects_unknown_wire_version_and_v1_codec_rejects_v2(
    subject: ModuleType,
) -> None:
    evidence = _current_identity(subject)
    payload = evidence.to_payload()
    payload["schema"] = "simulated-execution-instrument-identity.v1"

    with pytest.raises(IdentityEvidenceValidationError) as error:
        type(evidence).from_payload(payload)
    assert error.value.code == "IDENTITY_EVIDENCE_SCHEMA_UNSUPPORTED"

    with pytest.raises(SimulatedSettlementContractError):
        ExecutionInstrumentIdentityEvidenceV1.from_payload(evidence.to_payload())


def test_v2_intent_validation_requires_exact_revalidated_intent(subject: ModuleType) -> None:
    evidence = _current_identity(subject)
    with pytest.raises(IdentityEvidenceValidationError) as wrong_type:
        evidence.validate_for(intent=object(), as_of=AS_OF)
    assert wrong_type.value.code == "IDENTITY_INTENT_INVALID"

    corrupted_intent = _base_plan(side=SimulatedTradeSide.BUY).intent
    object.__setattr__(corrupted_intent, "quantity", Decimal("-1"))
    with pytest.raises(IdentityEvidenceValidationError) as invalid_value:
        evidence.validate_for(intent=corrupted_intent, as_of=AS_OF)
    assert invalid_value.value.code == "IDENTITY_INTENT_INVALID"
    assert invalid_value.value.__cause__ is not None


@pytest.mark.parametrize(
    ("boundary", "message"),
    (
        ("plan_identity_type", "IDENTITY_EVIDENCE_TYPE_INVALID"),
        ("binding_common_type", "common_binding must be SimulatedSettlementPlanBindingV1"),
        (
            "binding_identity_type",
            "identity_evidence must be ExecutionInstrumentIdentityEvidenceV2",
        ),
        (
            "binding_cutoff",
            "identity selection time differs from the bound plan pre-read cutoff",
        ),
        (
            "binding_exchange",
            "identity source exchange differs from the bound calendar exchange",
        ),
    ),
)
def test_v3_plan_and_binding_reject_wrong_nested_type_or_scope(
    subject: ModuleType, boundary: str, message: str
) -> None:
    bind = subject.bind_settlement_execution_plan_v3
    plan = _plan_v3(subject)
    binding = bind(plan, executed_at=AS_OF + timedelta(minutes=1))

    if boundary == "plan_identity_type":
        with pytest.raises(IdentityEvidenceValidationError) as error:
            _plan_v3(subject, identity_evidence=_legacy_source_evidence())
        assert error.value.code == message
        return

    if boundary == "binding_common_type":
        replacement = {"common_binding": plan}
    elif boundary == "binding_identity_type":
        replacement = {"identity_evidence": _legacy_source_evidence()}
    elif boundary == "binding_cutoff":
        replacement = {
            "identity_evidence": _current_identity(
                subject,
                selection_changes={"selected_at": AS_OF - timedelta(minutes=1)},
            )
        }
    else:
        replacement = {
            "identity_evidence": _current_identity(
                subject, source_changes={"source_exchange": "SH"}
            )
        }

    with pytest.raises(SettlementPlanBindingValidationError) as error:
        replace(binding, **replacement)
    assert str(error.value) == message


def test_v3_decoder_rejects_wrong_envelope_and_v2_codec_rejects_v3(
    subject: ModuleType,
) -> None:
    binding = subject.bind_settlement_execution_plan_v3(
        _plan_v3(subject), executed_at=AS_OF + timedelta(minutes=1)
    )
    payload = binding.to_payload()
    payload["schema"] = "simulated-settlement-plan-binding.v2"

    with pytest.raises(SettlementPlanBindingValidationError) as error:
        type(binding).from_payload(payload)
    assert str(error.value) == "binding_v3 schema is unsupported"

    with pytest.raises(SimulatedSettlementContractError):
        SimulatedSettlementPlanBindingV2.from_payload(binding.to_payload())


def test_v3_binder_requires_exact_plan_and_preserves_nested_validation_error(
    subject: ModuleType,
) -> None:
    bind = subject.bind_settlement_execution_plan_v3
    with pytest.raises(SettlementPlanBindingValidationError) as wrong_plan:
        bind(_base_plan(side=SimulatedTradeSide.BUY), executed_at=AS_OF + timedelta(minutes=1))
    assert str(wrong_plan.value) == "plan must be SettlementExecutionPlanV3"

    plan = _plan_v3(subject)
    object.__setattr__(plan.identity_evidence, "source_occurrence_id", "not-a-uuid")
    with pytest.raises(SettlementPlanBindingValidationError) as invalid_receipt:
        bind(plan, executed_at=AS_OF + timedelta(minutes=1))
    assert str(invalid_receipt.value) == "IDENTITY_EVIDENCE_UUID_INVALID"
    assert isinstance(invalid_receipt.value.__cause__, IdentityEvidenceValidationError)
