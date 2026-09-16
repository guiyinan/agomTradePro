"""True source-time and candidate-bound TUI raw sample derivation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.evid09_tui02_retained_source_probe import (
    MINIMUM_OBSERVATION_SECONDS,
    RetainedSourceError,
    parse_source_range,
)


def _body(series: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"status": "success", "data": {"resultType": "matrix", "result": series}}
    ).encode()


def test_first_real_source_timestamp_not_evaluation_or_old_lookback() -> None:
    started = datetime.fromtimestamp(1000, UTC)
    observed = datetime.fromtimestamp(1300, UTC)
    body = _body(
        [
            {
                "metric": {
                    "job": "agomtradepro",
                    "instance": "web:8000",
                    "task_key": "signal.list",
                },
                "values": [[1000, "990"], [1060, "1030"], [1120, "1090"]],
            },
            {
                "metric": {"job": "other", "instance": "web:8000", "task_key": "ignored"},
                "values": [[1040, "1010"]],
            },
        ]
    )

    report = parse_source_range(body, web_start=started, observed_at=observed)

    first = datetime.fromtimestamp(1030, UTC)
    assert report["first_retained_raw_sample_at_utc"] == first.isoformat().replace("+00:00", "Z")
    assert report["earliest_full_14d_telemetry_at_utc"] == (
        first + timedelta(seconds=MINIMUM_OBSERVATION_SECONDS)
    ).isoformat().replace("+00:00", "Z")
    assert report["task_keys"] == ["signal.list"]
    assert report["evaluations_with_candidate_source"] == 2


def test_no_candidate_source_or_future_timestamp_denies() -> None:
    started = datetime.fromtimestamp(1000, UTC)
    observed = datetime.fromtimestamp(1300, UTC)
    with pytest.raises(RetainedSourceError, match="no candidate-bound"):
        parse_source_range(
            _body(
                [
                    {
                        "metric": {"job": "agomtradepro", "instance": "web:8000"},
                        "values": [[1100, "990"]],
                    }
                ]
            ),
            web_start=started,
            observed_at=observed,
        )
    with pytest.raises(RetainedSourceError, match="time skew"):
        parse_source_range(
            _body(
                [
                    {
                        "metric": {"job": "agomtradepro", "instance": "web:8000"},
                        "values": [[1100, "1200"]],
                    }
                ]
            ),
            web_start=started,
            observed_at=observed,
        )


def test_matrix_shape_and_status_fail_closed() -> None:
    started = datetime.fromtimestamp(1000, UTC)
    observed = datetime.fromtimestamp(1300, UTC)
    with pytest.raises(RetainedSourceError, match="not a matrix"):
        parse_source_range(
            json.dumps(
                {"status": "success", "data": {"resultType": "vector", "result": []}}
            ).encode(),
            web_start=started,
            observed_at=observed,
        )
    with pytest.raises(RetainedSourceError, match="not successful"):
        parse_source_range(
            json.dumps(
                {"status": "error", "data": {"resultType": "matrix", "result": []}}
            ).encode(),
            web_start=started,
            observed_at=observed,
        )
