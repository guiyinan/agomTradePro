"""Keep the cash-reference record date beyond seeded tax settlement changes."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.support.ash05_owner_workflow_native_world import _local_anchor


@pytest.mark.parametrize("weekday", range(7))
def test_reference_seed_settlement_precedes_the_recent_record_date(weekday: int) -> None:
    """An older retained seed leaves a zero-change record session all week."""
    local_day = date(2026, 11, 9) + timedelta(days=weekday)
    actual = datetime.combine(local_day, time(16), tzinfo=ZoneInfo("Asia/Shanghai"))
    anchor, anchor_at = _local_anchor(actual, history_weeks=2)
    sessions = tuple(
        anchor + timedelta(days=offset)
        for offset in range(1, (local_day - anchor).days + 1)
        if (anchor + timedelta(days=offset)).weekday() < 5
    )
    seeded_sale_settlement = sessions[3]
    reference_record_date = sessions[-2]

    assert seeded_sale_settlement < reference_record_date
    assert reference_record_date < sessions[-1] <= local_day
    assert anchor_at.astimezone(UTC) < actual.astimezone(UTC)
    assert _local_anchor(actual) == _local_anchor(actual, history_weeks=1)
