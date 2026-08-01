"""Unified current-data reliability contract tests."""

from datetime import UTC, datetime

import pytest

from shared.domain.reliability import ReliabilityContract, ReliabilityStatus


def test_fresh_contract_preserves_observation_and_fetch_times() -> None:
    observed_at = datetime(2026, 7, 31, 7, 0, tzinfo=UTC)
    fetched_at = datetime(2026, 7, 31, 7, 0, 2, tzinfo=UTC)

    contract = ReliabilityContract.fresh(
        observed_at=observed_at,
        fetched_at=fetched_at,
        source="tencent",
    )

    assert contract.status is ReliabilityStatus.FRESH
    assert contract.observed_at is observed_at
    assert contract.fetched_at is fetched_at
    assert contract.must_not_use_for_decision is False
    assert contract.to_dict()["observed_at"] == "2026-07-31T07:00:00+00:00"


@pytest.mark.parametrize(
    "status",
    [
        ReliabilityStatus.STALE,
        ReliabilityStatus.MISSING,
        ReliabilityStatus.PARTIAL,
        ReliabilityStatus.CONFLICT,
        ReliabilityStatus.MAINTENANCE,
        ReliabilityStatus.FAILED,
    ],
)
def test_non_fresh_contracts_fail_closed(status: ReliabilityStatus) -> None:
    contract = ReliabilityContract.blocked(
        status=status,
        source="data_center",
        reason_code="test_block",
        reason="测试阻断",
    )

    assert contract.must_not_use_for_decision is True
    assert contract.to_dict()["block_reason_code"] == "test_block"


def test_contract_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ReliabilityContract.fresh(
            observed_at=datetime(2026, 7, 31, 15, 0),
            fetched_at=datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
            source="tencent",
        )


def test_fetched_time_cannot_precede_observation_time() -> None:
    with pytest.raises(ValueError, match="fetched_at"):
        ReliabilityContract.fresh(
            observed_at=datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 31, 14, 59, tzinfo=UTC),
            source="tencent",
        )
