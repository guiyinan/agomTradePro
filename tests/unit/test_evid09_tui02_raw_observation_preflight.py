"""Exact raw TUI-02 observation query cannot inherit rule vectors."""

from __future__ import annotations

import json

import pytest

from scripts.evid09_tui02_raw_observation_preflight import (
    RAW_METRIC,
    Tui02ObservationError,
    build_report,
    raw_vector_count,
)


def _body(items: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"status": "success", "data": {"resultType": "vector", "result": items}}
    ).encode()


def test_empty_exact_raw_instant_vector_is_only_safe_pre_action_case() -> None:
    report = build_report(200, _body([]))

    assert report["decision"] == "PASS_NO_RAW_SAMPLE"
    assert report["raw_vector_count"] == 0
    assert report["first_retained_sample_inferred"] is False


def test_real_raw_series_denies_candidate_changing_exercise() -> None:
    body = _body([{"metric": {"__name__": RAW_METRIC}, "value": [1789488000, "1"]}])

    assert raw_vector_count(body) == 1
    assert build_report(200, body)["decision"] == "DENY_RAW_SAMPLE_OR_QUERY"
    assert "1789488000" not in json.dumps(build_report(200, body))


def test_recording_rule_or_unknown_query_result_denies() -> None:
    with pytest.raises(Tui02ObservationError, match="different metric"):
        raw_vector_count(_body([{"metric": {"__name__": "historical_recording_rule"}}]))
    with pytest.raises(Tui02ObservationError, match="not an instant vector"):
        raw_vector_count(
            json.dumps(
                {"status": "success", "data": {"resultType": "matrix", "result": []}}
            ).encode()
        )
    assert build_report(401, b"blocked")["decision"] == "DENY_RAW_SAMPLE_OR_QUERY"
