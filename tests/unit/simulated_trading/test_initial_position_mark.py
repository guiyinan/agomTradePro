"""Pure contract tests for a sealed initial-position valuation mark."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import cast

import pytest

from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.initial_position_mark import (
    InitialPositionMarkProof,
    InitialPositionMarkValidationError,
)

READ_AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 10, 20, 1, 55, tzinfo=UTC)


class _DailyObservationBasisAlias(StrEnum):
    DAILY_INTERVAL_END = "daily_interval_end"


def _intent() -> SimulatedTradeIntent:
    """Build one fully valid owner-scoped intent for identity binding tests."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key="first-buy-1",
        side=SimulatedTradeSide.BUY,
        security_id="security-000001",
        asset_code="000001.SZ",
        asset_name="Example",
        asset_type="equity",
        market="CN",
        board="main",
        quantity=Decimal("100"),
        price=Decimal("12.3500"),
        reason="test initial position",
        signal_id=None,
    )


def _proof() -> InitialPositionMarkProof:
    """Build one exact, current, source-bound mark proof."""

    return InitialPositionMarkProof(
        security_id="security-000001",
        asset_code="000001.SZ",
        asset_type="equity",
        market="CN",
        board="main",
        price=Decimal("12.3456"),
        source_observed_at=OBSERVED_AT,
        source_available_at=None,
        read_at=READ_AT,
        publication_as_of=datetime(2026, 10, 20, 1, 56, tzinfo=UTC),
        published_at=datetime(2026, 10, 20, 1, 57, tzinfo=UTC),
        valid_until=datetime(2026, 10, 20, 2, 5, tzinfo=UTC),
        freshness_window_seconds=600,
        source_identity="market-data:primary",
        source_record_id="quote-row-123",
        source_content_hash="a" * 64,
        publication_id="publication-123",
        publication_hash="b" * 64,
        policy_identity="execution-quote-policy:v1",
        policy_content_hash="c" * 64,
    )


def test_valid_mark_binds_exact_intent_and_preserves_unknown_availability() -> None:
    proof = _proof()

    proof.validate_for(intent=_intent(), read_at=READ_AT)

    assert proof.source_available_at is None
    assert proof.to_payload()["source_available_at"] is None
    assert proof.to_payload()["purpose"] == "apply_time_initial_position_mark"
    assert len(proof.proof_hash) == 64


def _daily_interval_proof() -> InitialPositionMarkProof:
    """Build an explicit daily interval mark with independent source clocks."""

    interval_end = datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
    local_known = datetime(2026, 10, 20, 1, 40, tzinfo=UTC)
    return replace(
        _proof(),
        source_observed_at=None,
        source_available_at=None,
        read_at=READ_AT,
        publication_as_of=interval_end + timedelta(minutes=5),
        published_at=datetime(2026, 10, 20, 1, 50, tzinfo=UTC),
        valid_until=interval_end + timedelta(hours=1),
        freshness_window_seconds=3600,
        observation_basis="daily_interval_end",
        interval_end_at=interval_end,
        local_known_at=local_known,
    )


def test_daily_interval_mark_keeps_supplier_observation_unknown_and_anchors_ttl() -> None:
    proof = _daily_interval_proof()

    proof.validate_for(intent=_intent(), read_at=READ_AT)

    assert proof.source_observed_at is None
    assert proof.observation_basis == "daily_interval_end"
    assert proof.interval_end_at == datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
    assert proof.local_known_at == datetime(2026, 10, 20, 1, 40, tzinfo=UTC)
    assert proof.source_available_at is None
    assert proof.valid_until == proof.interval_end_at + timedelta(seconds=3600)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_observed_at", OBSERVED_AT),
        ("interval_end_at", None),
        ("local_known_at", None),
        ("interval_end_at", READ_AT + timedelta(microseconds=1)),
        ("interval_end_at", datetime(2026, 10, 20, 1, 30)),
        ("local_known_at", datetime(2026, 10, 20, 1, 40)),
        ("local_known_at", datetime(2026, 10, 20, 1, 29, 59, tzinfo=UTC)),
        ("local_known_at", datetime(2026, 10, 20, 1, 51, tzinfo=UTC)),
        ("publication_as_of", datetime(2026, 10, 20, 1, 29, tzinfo=UTC)),
        ("source_available_at", datetime(2026, 10, 20, 1, 29, tzinfo=UTC)),
        ("source_available_at", datetime(2026, 10, 20, 1, 41, tzinfo=UTC)),
        ("valid_until", datetime(2026, 10, 20, 2, 29, 59, tzinfo=UTC)),
    ),
)
def test_daily_interval_mark_rejects_missing_or_inconsistent_basis_clocks(
    field_name: str, value: object
) -> None:
    proof = _daily_interval_proof()

    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, **{field_name: value})


def test_legacy_mark_rejects_interval_and_local_knowledge_clocks() -> None:
    proof = _proof()

    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, interval_end_at=OBSERVED_AT)
    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, local_known_at=OBSERVED_AT)


def test_observation_basis_requires_a_literal_string() -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        replace(
            _daily_interval_proof(),
            observation_basis=_DailyObservationBasisAlias.DAILY_INTERVAL_END,
        )


def test_legacy_v1_proof_hash_is_pinned() -> None:
    proof = _proof()

    assert proof.observation_basis == "legacy_source_observed"
    assert proof.interval_end_at is None
    assert proof.local_known_at is None
    assert proof.proof_hash == "9047d080c436a787334c31f468d08584a6bff0ded4a852fd22790f8f5b286821"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("security_id", "another-security"),
        ("asset_code", "000002.SZ"),
        ("asset_type", "fund"),
        ("market", "another-market"),
        ("board", "another-board"),
    ),
)
def test_mark_requires_every_exact_intent_identity_field(field_name: str, value: str) -> None:
    proof = _proof()
    mismatched = replace(proof, **{field_name: value})

    with pytest.raises(InitialPositionMarkValidationError):
        mismatched.validate_for(intent=_intent(), read_at=READ_AT)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_observed_at", READ_AT + timedelta(microseconds=1)),
        ("source_available_at", READ_AT + timedelta(microseconds=1)),
        ("publication_as_of", READ_AT + timedelta(microseconds=1)),
        ("published_at", READ_AT + timedelta(microseconds=1)),
        ("valid_until", READ_AT - timedelta(microseconds=1)),
    ),
)
def test_mark_rejects_future_clocks_and_expired_policy_window(
    field_name: str, value: datetime
) -> None:
    proof = _proof()

    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, **{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_observed_at", cast(datetime, None)),
        ("read_at", datetime(2026, 10, 20, 2, 0)),
        ("published_at", datetime(2026, 10, 20, 1, 57)),
    ),
)
def test_mark_requires_observation_and_all_supplied_clocks_to_be_aware(
    field_name: str, value: datetime
) -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        replace(_proof(), **{field_name: value})


@pytest.mark.parametrize(
    ("price",),
    ((Decimal("0"),), (Decimal("NaN"),), (Decimal("12.34567"),)),
)
def test_mark_price_uses_exact_positive_ledger_price_validation(price: Decimal) -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        replace(_proof(), price=price)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_content_hash", "A" * 64),
        ("publication_hash", "not-a-digest"),
        ("policy_content_hash", "f" * 63),
        ("source_identity", "source with whitespace"),
    ),
)
def test_mark_requires_canonical_source_publication_and_policy_evidence(
    field_name: str, value: str
) -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        replace(_proof(), **{field_name: value})


def test_policy_window_is_explicit_and_must_match_the_sealed_deadline() -> None:
    proof = _proof()
    proof.validate_for(intent=_intent(), read_at=READ_AT)

    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, freshness_window_seconds=True)
    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, freshness_window_seconds=601)


def test_reader_cutoff_must_equal_the_proof_read_time() -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        _proof().validate_for(
            intent=_intent(),
            read_at=READ_AT + timedelta(seconds=1),
        )


def test_mark_can_be_revalidated_from_exact_instrument_fields_without_intent() -> None:
    _proof().validate_for_instrument(
        security_id="security-000001",
        asset_code="000001.SZ",
        asset_type="equity",
        market="CN",
        board="main",
        read_at=READ_AT,
    )


def test_canonical_hash_ignores_equivalent_decimal_scale_and_timezone_offset() -> None:
    proof = _proof()
    local_zone = timezone(timedelta(hours=8))
    equivalent = replace(
        proof,
        price=Decimal("12.3456000"),
        source_observed_at=OBSERVED_AT.astimezone(local_zone),
        read_at=READ_AT.astimezone(local_zone),
        publication_as_of=proof.publication_as_of.astimezone(local_zone),
        published_at=proof.published_at.astimezone(local_zone),
        valid_until=proof.valid_until.astimezone(local_zone),
    )

    assert equivalent.proof_hash == proof.proof_hash
    equivalent.validate_for(intent=_intent(), read_at=READ_AT)


def test_deadline_equal_to_read_time_is_expired() -> None:
    deadline = READ_AT
    observed = deadline - timedelta(seconds=300)
    just_before = deadline - timedelta(microseconds=1)
    proof = replace(
        _proof(),
        source_observed_at=observed,
        read_at=just_before,
        publication_as_of=observed + timedelta(seconds=30),
        published_at=observed + timedelta(seconds=60),
        valid_until=deadline,
        freshness_window_seconds=300,
    )

    proof.validate_for(intent=_intent(), read_at=just_before)
    with pytest.raises(InitialPositionMarkValidationError):
        replace(proof, read_at=deadline)


def test_known_source_availability_cannot_precede_observation() -> None:
    with pytest.raises(InitialPositionMarkValidationError):
        replace(
            _proof(),
            source_available_at=OBSERVED_AT - timedelta(microseconds=1),
        )
