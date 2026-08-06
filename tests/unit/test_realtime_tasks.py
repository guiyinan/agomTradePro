from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from apps.realtime.application.tasks import poll_realtime_prices_task


def _price(
    asset_code: str,
    *,
    observed_at: datetime,
    source: str = "provider-a",
) -> dict[str, object]:
    return {
        "asset_code": asset_code,
        "price": 4.2,
        "timestamp": observed_at.isoformat(),
        "fetched_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "source": source,
    }


@pytest.mark.parametrize("asset_codes", ["510300.SH", [1], [object()]])
def test_poll_realtime_prices_task_rejects_invalid_input(asset_codes: object) -> None:
    """Celery callers cannot bypass list and element validation."""

    result = poll_realtime_prices_task(asset_codes=asset_codes)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["outcome"] == "failed"
    assert result["mode"] == "input"
    assert result["requested"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["must_not_use_for_decision"] is True


def test_poll_realtime_prices_task_polls_full_watchlist_successfully() -> None:
    """Full polling reports exact writes and preserves source observation clocks."""

    observed_at = datetime.now(UTC) - timedelta(seconds=10)
    use_case = Mock()
    use_case.execute_price_polling.return_value = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_assets": 2,
        "prices": [
            _price("510300.SH", observed_at=observed_at),
            _price("000001.SH", observed_at=observed_at + timedelta(seconds=2)),
        ],
        "must_not_use_for_decision": False,
    }
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task(asset_codes=[])

    use_case.execute_price_polling.assert_called_once_with()
    use_case.get_latest_prices.assert_not_called()
    assert result["success"] is True
    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 2
    assert result["observed_at"] == observed_at.isoformat()
    assert result["freshness_status"] == "fresh"
    assert result["must_not_use_for_decision"] is False


def test_poll_realtime_prices_task_normalizes_requested_assets() -> None:
    """Explicit requests are canonicalized, deduplicated, and remain read-only."""

    observed_at = datetime.now(UTC) - timedelta(seconds=5)
    use_case = Mock()
    use_case.get_latest_prices.return_value = [
        _price("510300.SH", observed_at=observed_at),
        _price("000001.SH", observed_at=observed_at),
    ]
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task(
            asset_codes=[" 510300.sh ", "510300.SH", "", "000001.sh"]
        )

    use_case.get_latest_prices.assert_called_once_with(["510300.SH", "000001.SH"])
    use_case.execute_price_polling.assert_not_called()
    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["asset_codes"] == ["510300.SH", "000001.SH"]


def test_poll_realtime_prices_task_reports_partial_requested_output() -> None:
    """A missing quote is partial rather than an unconditional success."""

    observed_at = datetime.now(UTC) - timedelta(seconds=5)
    use_case = Mock()
    use_case.get_latest_prices.return_value = [_price("510300.SH", observed_at=observed_at)]
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task(asset_codes=["510300.SH", "000001.SH"])

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["reliability_status"] == "partial"
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "realtime_price_snapshot_incomplete"


def test_poll_realtime_prices_task_rejects_all_stale_requested_output() -> None:
    """Old source timestamps cannot be washed into a fresh task result."""

    stale_at = datetime.now(UTC) - timedelta(hours=1)
    use_case = Mock()
    use_case.get_latest_prices.return_value = [_price("510300.SH", observed_at=stale_at)]
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task(asset_codes=["510300.SH"])

    assert result["success"] is False
    assert result["outcome"] == "failed"
    assert result["requested"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["prices"] == []
    assert result["observed_at"] is None
    assert result["freshness_status"] == "stale"
    assert result["is_stale"] is True
    assert result["blocked_reason"] == "realtime_price_snapshot_stale"


def test_poll_realtime_prices_task_returns_noop_for_empty_watchlist() -> None:
    """A zero-request polling pass is an explicit noop with no writes."""

    use_case = Mock()
    use_case.execute_price_polling.return_value = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_assets": 0,
        "prices": [],
        "must_not_use_for_decision": True,
        "blocked_reason": "realtime_price_snapshot_incomplete",
    }
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task(asset_codes=None)

    assert result["success"] is True
    assert result["outcome"] == "noop"
    assert result["requested"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "no_monitored_realtime_assets"


def test_poll_realtime_prices_task_preserves_upstream_business_block() -> None:
    """A blocked full snapshot cannot become successful from non-empty prices."""

    observed_at = datetime.now(UTC) - timedelta(seconds=5)
    use_case = Mock()
    use_case.execute_price_polling.return_value = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_assets": 1,
        "prices": [_price("510300.SH", observed_at=observed_at)],
        "must_not_use_for_decision": True,
        "blocked_reason": "realtime_price_snapshot_incomplete",
    }
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task()

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["requested"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["stored"] == 1
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "realtime_price_snapshot_incomplete"


def test_poll_realtime_prices_task_reports_partial_watchlist_writes() -> None:
    """Incomplete writes remain partial even though the snapshot blocks decisions."""

    observed_at = datetime.now(UTC) - timedelta(seconds=5)
    use_case = Mock()
    use_case.execute_price_polling.return_value = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_assets": 2,
        "prices": [_price("510300.SH", observed_at=observed_at)],
        "must_not_use_for_decision": True,
        "blocked_reason": "realtime_price_snapshot_incomplete",
    }
    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    ):
        result = poll_realtime_prices_task()

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["stored"] == 1
    assert result["reliability_status"] == "partial"
    assert result["must_not_use_for_decision"] is True


def test_poll_realtime_prices_task_normalizes_execution_failure() -> None:
    """Technical failures return a failed business outcome instead of escaping."""

    with patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        side_effect=RuntimeError("provider exploded"),
    ):
        result = poll_realtime_prices_task(asset_codes=["510300.SH"])

    assert result["success"] is False
    assert result["outcome"] == "failed"
    assert result["requested"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["error"] == "realtime_price_polling_failed"
    assert result["reliability_status"] == "failed"
    assert result["must_not_use_for_decision"] is True
