"""Retained simulation proofs must still satisfy their contracts when read back."""

from dataclasses import replace
from datetime import UTC, datetime

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
