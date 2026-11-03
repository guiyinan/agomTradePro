"""Contract tests for strict source-payload to risk-evidence narrowing."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.risk_center.application.portfolio_risk_source_codec import (
    PortfolioRiskSourcePayload,
    decode_portfolio_risk_source_evidence,
    encode_portfolio_risk_source_payload,
    evidence_from_portfolio_risk_source_payload,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_DECISION_CUTOFF = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
_DECISION_DATE = date(2026, 11, 3)
_OBSERVED_AT = "2026-11-03T15:55:00+08:00"
_AVAILABLE_AT = "2026-11-03T15:56:00+08:00"
_KNOWN_AT = "2026-11-03T15:57:00+08:00"
_VALID_UNTIL = "2026-11-03T16:30:00+08:00"


def _timestamp_payload(**overrides: object) -> dict[str, object]:
    """Build a JSON-shaped source payload with exact fields and real source clocks."""

    payload: dict[str, object] = {
        "source_id": "market:daily-bars",
        "source_record_id": "row:000001.SZ:2026-11-03",
        "original_payload_sha256": "a" * 64,
        "observation_precision": "timestamp",
        "observed_at": _OBSERVED_AT,
        "observed_on": None,
        "available_at": _AVAILABLE_AT,
        "known_at": _KNOWN_AT,
        "valid_until": _VALID_UNTIL,
        "source_purpose": "market_liquidity",
        "allowed_purposes": ["ash07_portfolio_capacity"],
        "restrictions": ["session_only"],
        "must_not_use_for_decision": False,
        "coverage": {
            "status": "complete",
            "precision_basis": "complete_session_rows",
            "reported_weight_fraction": "1.00",
            "expected_item_count": 5,
            "observed_item_count": 5,
        },
        "effective_on": "2026-11-03",
        "effective_until": "2026-11-05",
    }
    payload.update(overrides)
    return payload


def test_timestamp_payload_roundtrips_without_changing_source_clocks_or_purpose() -> None:
    """The codec preserves exact offsets, source hashes, clocks, restrictions and coverage."""

    evidence = decode_portfolio_risk_source_evidence(
        _timestamp_payload(),
        decision_cutoff=_DECISION_CUTOFF,
        decision_date_cutoff=None,
    )

    assert isinstance(evidence, PortfolioRiskSourceEvidence)
    assert evidence.observation_precision is SourceObservationPrecision.TIMESTAMP
    assert evidence.observed_at == datetime.fromisoformat(_OBSERVED_AT)
    assert evidence.observed_at is not None and evidence.observed_at.utcoffset() is not None
    assert evidence.available_at == datetime.fromisoformat(_AVAILABLE_AT)
    assert evidence.known_at == datetime.fromisoformat(_KNOWN_AT)
    assert evidence.valid_until == datetime.fromisoformat(_VALID_UNTIL)
    assert evidence.original_payload_sha256 == "a" * 64
    assert evidence.allowed_purposes == ("ash07_portfolio_capacity",)
    assert evidence.restrictions == ("session_only",)
    assert evidence.coverage.reported_weight_fraction == Decimal("1.00")
    assert evidence.effective_on == date(2026, 11, 3)
    assert evidence.effective_until == date(2026, 11, 5)
    assert evidence.decision_cutoff == _DECISION_CUTOFF
    assert evidence.decision_date_cutoff is None

    payload = encode_portfolio_risk_source_payload(evidence)
    assert isinstance(payload, PortfolioRiskSourcePayload)
    assert payload.observed_at == evidence.observed_at
    assert payload.available_at == evidence.available_at
    assert payload.known_at == evidence.known_at
    assert payload.valid_until == evidence.valid_until
    assert payload.restrictions == evidence.restrictions
    assert payload.coverage == evidence.coverage
    assert payload.effective_on == evidence.effective_on
    assert payload.effective_until == evidence.effective_until


def test_missing_unknown_clocks_and_hash_remain_none_without_request_time_defaults() -> None:
    """Missing source clocks and hash stay unknown instead of borrowing decision time."""

    evidence = decode_portfolio_risk_source_evidence(
        {
            "source_id": "market:unknown",
            "source_record_id": "record:unknown",
            "original_payload_sha256": None,
            "observation_precision": "unknown",
            "source_purpose": "market_liquidity",
            "allowed_purposes": ["ash07_portfolio_capacity"],
            "restrictions": [],
            "must_not_use_for_decision": False,
            "coverage": {"status": "unknown", "precision_basis": "unknown"},
        },
        decision_cutoff=_DECISION_CUTOFF,
        decision_date_cutoff=None,
    )

    assert evidence.original_payload_sha256 is None
    assert evidence.observed_at is None
    assert evidence.observed_on is None
    assert evidence.available_at is None
    assert evidence.known_at is None
    assert evidence.valid_until is None
    assert evidence.decision_cutoff == _DECISION_CUTOFF
    assert evidence.coverage.status is CoverageStatus.UNKNOWN


def test_date_precision_keeps_date_without_synthetic_midnight() -> None:
    """Date-only evidence requires its explicit business-date cutoff and stays date-only."""

    payload = _timestamp_payload(
        observation_precision="date",
        observed_at=None,
        observed_on="2026-11-03",
    )
    evidence = decode_portfolio_risk_source_evidence(
        payload,
        decision_cutoff=_DECISION_CUTOFF,
        decision_date_cutoff=_DECISION_DATE,
    )

    assert evidence.observation_precision is SourceObservationPrecision.DATE
    assert evidence.observed_on == _DECISION_DATE
    assert evidence.observed_at is None
    assert evidence.decision_date_cutoff == _DECISION_DATE

    payload_object = encode_portfolio_risk_source_payload(evidence)
    rebound = evidence_from_portfolio_risk_source_payload(
        payload_object,
        decision_cutoff=_DECISION_CUTOFF,
        decision_date_cutoff=_DECISION_DATE,
    )
    assert rebound.observed_on == _DECISION_DATE
    assert rebound.observed_at is None


@pytest.mark.parametrize(
    ("precision", "observed_at", "observed_on"),
    [
        ("date", _OBSERVED_AT, "2026-11-03"),
        ("timestamp", "2026-11-03", None),
        ("timestamp", date(2026, 11, 3), None),
        ("date", None, datetime(2026, 11, 3, tzinfo=timezone.utc)),
    ],
)
def test_codec_rejects_date_datetime_confusion(
    precision: str,
    observed_at: object,
    observed_on: object,
) -> None:
    """Dates never become timestamps and timestamps never become dates implicitly."""

    payload = _timestamp_payload(
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=observed_on,
    )
    with pytest.raises((TypeError, ValueError)):
        decode_portfolio_risk_source_evidence(
            payload,
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=_DECISION_DATE,
        )


def test_codec_rejects_naive_datetime_float_and_invalid_payload_hash() -> None:
    """Lossy numeric values, naive clocks and malformed hashes are not normalized."""

    with pytest.raises(ValueError):
        decode_portfolio_risk_source_evidence(
            _timestamp_payload(known_at="2026-11-03T15:57:00"),
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=None,
        )

    with pytest.raises((TypeError, ValueError)):
        decode_portfolio_risk_source_evidence(
            _timestamp_payload(
                coverage={
                    "status": "complete",
                    "precision_basis": "complete_session_rows",
                    "reported_weight_fraction": 1.0,
                }
            ),
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=None,
        )

    with pytest.raises(ValueError):
        decode_portfolio_risk_source_evidence(
            _timestamp_payload(original_payload_sha256="not-a-sha256"),
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=None,
        )


def test_valid_until_is_never_invented_and_source_prohibitions_are_preserved() -> None:
    """No TTL is manufactured; prohibition flags and tokens survive the codec exactly."""

    evidence = decode_portfolio_risk_source_evidence(
        _timestamp_payload(
            valid_until=None,
            must_not_use_for_decision=True,
            restrictions=["research_only", "observation_only"],
        ),
        decision_cutoff=_DECISION_CUTOFF,
        decision_date_cutoff=None,
    )
    payload = encode_portfolio_risk_source_payload(evidence)

    assert evidence.valid_until is None
    assert payload.valid_until is None
    assert evidence.must_not_use_for_decision is True
    assert evidence.restrictions == ("research_only", "observation_only")
    assert payload.must_not_use_for_decision is True
    assert payload.restrictions == evidence.restrictions


def test_decision_cutoffs_are_service_bound_and_unknown_source_fields_are_rejected() -> None:
    """Caller payloads cannot override cutoffs or smuggle unmodeled fields through."""

    with pytest.raises(ValueError):
        decode_portfolio_risk_source_evidence(
            _timestamp_payload(decision_cutoff="2026-11-03T08:00:00+00:00"),
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=None,
        )

    with pytest.raises(ValueError):
        decode_portfolio_risk_source_evidence(
            _timestamp_payload(unrecognized_clock="2026-11-03T15:00:00+08:00"),
            decision_cutoff=_DECISION_CUTOFF,
            decision_date_cutoff=None,
        )
