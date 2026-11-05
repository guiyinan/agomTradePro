"""Contract tests for exact, published calendar bindings used by plan preparation."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.rebalance_journey_preparation_support import (
    bind_plan_execution_calendar,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable

_CUTOFF = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
_PREPARED = _CUTOFF + timedelta(minutes=1)
_SESSION = date(2026, 11, 6)
_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _calendar(
    *,
    as_of: datetime = _CUTOFF,
    requested_exchange: str = "XSHG",
    snapshot_exchange: str = "XSHG",
    recorded_at: datetime | None = _CUTOFF - timedelta(minutes=2),
    reference_until: datetime = _CUTOFF + timedelta(days=1),
    result_valid_until: datetime = _CUTOFF + timedelta(hours=1),
    qualified: bool = True,
) -> PortfolioRiskCalendarReadResult:
    """Create a fully hashed source-publication response with explicit clocks."""

    document: dict[str, object] = {
        "requested_session": _SESSION.isoformat(),
        "as_of": as_of.isoformat(),
        "identity_evidence": [],
        "calendar_evidence": [
            {
                "requested_exchange": requested_exchange,
                "evidence_hash": _HASH_A,
                "snapshot": {"exchange": snapshot_exchange, "sessions": [_SESSION.isoformat()]},
                "publication": {
                    "publication_id": "calendar-publication-1",
                    "member_id": "calendar-member-1",
                    "policy_hash": _HASH_B,
                    "timezone_name": "Asia/Shanghai",
                    "published_at": (
                        (recorded_at - timedelta(minutes=1))
                        if recorded_at is not None
                        else as_of - timedelta(minutes=3)
                    ).isoformat(),
                    "recorded_at": recorded_at.isoformat() if recorded_at is not None else None,
                    "reference_valid_from": (
                        (recorded_at - timedelta(days=1))
                        if recorded_at is not None
                        else as_of - timedelta(days=1)
                    ).isoformat(),
                    "reference_valid_until": reference_until.isoformat(),
                },
            }
        ],
    }
    encoded = canonical_portfolio_risk_json(document)
    return PortfolioRiskCalendarReadResult(
        requested_session_qualified=qualified,
        open_sessions=(_SESSION,),
        reason_codes=() if qualified else ("CALENDAR_NOT_QUALIFIED",),
        canonical_evidence_json=encoded,
        evidence_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        valid_until=result_valid_until,
    )


def test_published_calendar_binding_preserves_real_member_clocks() -> None:
    """The stable binding contains true publication clocks, not the outer read time."""

    calendar = _calendar()

    binding = bind_plan_execution_calendar(
        calendar,
        prepared_at=_PREPARED,
        expected_session=_SESSION,
    )

    assert binding.status == "qualified"
    assert binding.known_at == _CUTOFF - timedelta(minutes=2)
    assert binding.effective_at == _CUTOFF - timedelta(days=1, minutes=2)
    assert binding.valid_until == _CUTOFF + timedelta(hours=1)
    assert binding.content_hash is not None


def test_published_calendar_stable_binding_ignores_only_outer_read_cutoff() -> None:
    """A fresh wrapper read of unchanged published members keeps the same pin."""

    later_cutoff = _CUTOFF + timedelta(seconds=30)
    first = bind_plan_execution_calendar(
        _calendar(),
        prepared_at=_PREPARED,
        expected_session=_SESSION,
    )
    second = bind_plan_execution_calendar(
        _calendar(as_of=later_cutoff),
        prepared_at=_PREPARED,
        expected_session=_SESSION,
    )

    assert first.content_hash == second.content_hash
    assert first.known_at == second.known_at
    assert first.effective_at == second.effective_at


@pytest.mark.parametrize(
    ("calendar", "prepared_at"),
    (
        (_calendar(qualified=False), _PREPARED),
        (_calendar(snapshot_exchange="XHKG"), _PREPARED),
        (_calendar(recorded_at=None), _PREPARED),
        (_calendar(reference_until=_PREPARED), _PREPARED),
        (_calendar(result_valid_until=_PREPARED), _PREPARED),
        (_calendar(as_of=_PREPARED + timedelta(seconds=1)), _PREPARED),
    ),
)
def test_published_calendar_rejects_unqualified_or_mismatched_members(
    calendar: PortfolioRiskCalendarReadResult,
    prepared_at: datetime,
) -> None:
    """Unknown status, identity, future cutoff, and expired references fail closed."""

    with pytest.raises(RebalanceJourneyUnavailable):
        bind_plan_execution_calendar(calendar, prepared_at=prepared_at)


def test_published_calendar_rejects_session_mismatch() -> None:
    """A complete source calendar for another session cannot back this plan."""

    with pytest.raises(RebalanceJourneyUnavailable):
        bind_plan_execution_calendar(
            _calendar(),
            prepared_at=_PREPARED,
            expected_session=date(2026, 11, 9),
        )
