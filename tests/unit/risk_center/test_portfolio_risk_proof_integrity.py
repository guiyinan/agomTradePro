"""Retained simulation proofs must still satisfy their contracts when read back."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.unit.risk_center import test_portfolio_risk_close_snapshot_state_clock as close_fixture
from tests.unit.risk_center import test_portfolio_risk_date_snapshot_clock as date_fixture
from tests.unit.risk_center import test_portfolio_risk_timestamp_snapshot_clock as timestamp_fixture


@pytest.fixture(params=["industry_date", "valuation_timestamp", "close_state"])
def retained_proof(request):
    if request.param == "industry_date":
        result = date_fixture._decision()
        assert result.qualified and result.proof is not None
        return result.proof.to_domain()
    if request.param == "valuation_timestamp":
        result = timestamp_fixture._qualify()
        assert result.qualified and result.proof is not None
        return result.proof
    proof, reasons = close_fixture._qualify()
    assert proof is not None and not reasons
    return proof


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("scope", "live", "simulation-only"),
        ("source_reference_hash", "0" * 64, "source_reference_hash"),
        ("original_body_sha256", "G" * 64, "original_body_sha256"),
        ("source_record_id", "", "source_record_id"),
        ("profile_version", False, "profile_version"),
        ("account_id", 0, "account_id"),
        ("http_status", 304, "successful"),
        ("body_size_bytes", 0, "body|size"),
        ("body_complete", False, "complete"),
        ("as_of", datetime(2026, 11, 3), "aware datetime"),
        ("policy_deadlines", (datetime(2026, 11, 3),), "aware instants"),
        ("business_timezone_name", "Unknown/Exchange", "IANA timezone"),
        ("policy_known_at", datetime(2026, 12, 1, tzinfo=UTC), "decision cutoff"),
        ("source_available_at", datetime(2026, 11, 3, tzinfo=UTC), "source-origin"),
        ("policy_acceptance_deadline", datetime(2026, 12, 1, tzinfo=UTC), "earliest"),
    ],
)
def test_retained_proof_rejects_corrupted_identity_transport_and_clock_fields(
    retained_proof, field, value, reason
) -> None:
    with pytest.raises(ValueError, match=reason):
        replace(retained_proof, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_max_date_age_days", -1, "nonnegative"),
        ("source_max_date_age_days", 10**10, "supported date range"),
        ("observed_on", datetime(2026, 11, 3, tzinfo=UTC), "exact dates"),
        ("observed_on", date(2026, 11, 2), "equal the business date"),
        ("effective_until", date(2026, 11, 4), "bounded to the same business date"),
        ("known_at", datetime(2026, 1, 1, tzinfo=UTC), "decision cutoffs"),
    ],
)
def test_industry_date_proof_cannot_extend_observation_or_membership(field, value, reason):
    proof = date_fixture._decision().proof
    assert proof is not None
    with pytest.raises((TypeError, ValueError), match=reason):
        replace(proof.to_domain(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_kind", "daily_quote", "source kind"),
        ("clock_evidence_mode", "source_clocks_required", "mode"),
        ("business_date", datetime(2026, 11, 3, tzinfo=UTC), "exact dates"),
        ("observed_at", datetime(2026, 12, 1, tzinfo=UTC), "decision cutoff"),
        ("observed_at", datetime(2026, 1, 1, tzinfo=UTC), "current business date"),
        ("source_max_timestamp_age_seconds", -1, "nonnegative"),
        ("market_window_deadline", datetime(2026, 12, 1, tzinfo=UTC), "inclusive business date"),
        ("valuation_price_unit", None, "explicit quantity and price units"),
        ("capacity_window_sessions", 1, "capacity"),
        ("timestamp_age_deadline", datetime(2026, 12, 1, tzinfo=UTC), "configured source age"),
    ],
)
def test_valuation_timestamp_proof_stays_bound_to_its_mark_and_session(field, value, reason):
    proof = timestamp_fixture._qualify().proof
    assert proof is not None
    with pytest.raises((TypeError, ValueError), match=reason):
        replace(proof, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("valuation_price_unit", "CNY", "exact execution session"),
        ("capacity_measure", "price", "must be explicit"),
        ("capacity_policy_unit", None, "must be explicit"),
        ("capacity_policy_unit", "other", "must match"),
    ],
)
def test_capacity_proof_binds_a_single_session_to_the_policy_measure(field, value, reason):
    proof = timestamp_fixture._qualify(
        kind="capacity_window", purpose=timestamp_fixture._CAPACITY_PURPOSE
    ).proof
    assert proof is not None
    with pytest.raises(ValueError, match=reason):
        replace(proof, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("clock_evidence_mode", "realtime", "mode"),
        ("full_session_state", "TRADING", "quote-time and close-only"),
        ("required_restrictions", (), "incomplete or unordered"),
        ("trusted_vendor_status_codes", (), "must be explicit"),
        ("reported_status_code", "invented", "not trusted"),
        ("close_market_session_state", "OPEN", "explicitly scoped"),
        ("execution_session", datetime(2026, 11, 3, tzinfo=UTC), "must be dates"),
        ("execution_session", date(2027, 1, 1), "execution business date"),
        ("observed_at", datetime(2027, 1, 1, tzinfo=UTC), "must precede"),
        ("close_calendar_available_at", datetime(2027, 1, 1, tzinfo=UTC), "availability clocks"),
        ("observed_at", datetime(2026, 1, 1, tzinfo=UTC), "exact business date"),
        ("business_date_deadline", datetime(2027, 1, 1, tzinfo=UTC), "inclusive session date"),
        ("close_usage_ttl_seconds", 86400, "shorter than one day"),
        ("source_max_timestamp_age_seconds", -1, "nonnegative"),
        ("close_usage_deadline", datetime(2027, 1, 1, tzinfo=UTC), "receipt TTL"),
        ("source_age_deadline", datetime(2027, 1, 1, tzinfo=UTC), "configured source age"),
    ],
)
def test_close_state_proof_cannot_expand_a_vendor_quote_to_a_session_claim(field, value, reason):
    proof, reasons = close_fixture._qualify()
    assert proof is not None and not reasons
    with pytest.raises((TypeError, ValueError), match=reason):
        replace(proof, **{field: value})


def test_close_state_proof_expires_at_the_earliest_retained_deadline():
    proof, reasons = close_fixture._qualify()
    assert proof is not None and not reasons
    expired = proof.as_of - timedelta(microseconds=1)
    with pytest.raises(ValueError, match="already expired"):
        replace(proof, policy_deadlines=(expired,), policy_acceptance_deadline=expired)
