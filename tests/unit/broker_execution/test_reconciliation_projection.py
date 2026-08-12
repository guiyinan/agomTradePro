"""Pure tests for Broker reconciliation current-evidence projections."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from apps.broker_execution.application.reconciliation_projection import (
    project_broker_reconciliation,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _run() -> dict[str, object]:
    return {
        "id": 9,
        "account_id": 7,
        "status": "review_required",
        "order_difference_count": 1,
        "fill_difference_count": 0,
        "cash_difference_count": 1,
        "position_difference_count": 0,
        "summary": {
            "source": "qmt_snapshot_reconciliation",
            "snapshot_id": 3,
            "snapshot_captured_at": "2026-08-13T11:58:00+00:00",
            "difference_count": 2,
            "p0_auto_stop": True,
        },
        "differences": [
            {
                "dimension": "order",
                "difference_key": "order-1",
                "severity": "P1",
                "expected": {"status": "SUBMITTING"},
                "actual": {"status": "CANCELED"},
                "reason": "VPS and QMT order statuses differ",
                "status": "open",
            },
            {
                "dimension": "cash",
                "difference_key": "cash_available",
                "severity": "P0",
                "expected": {"cash_available": "100.00"},
                "actual": {"cash_available": "90.00"},
                "reason": "Unified ledger and QMT available cash differ",
                "status": "open",
            },
        ],
        "started_at": "2026-08-13T11:59:00+00:00",
        "completed_at": None,
    }


def test_valid_reconciliation_is_display_only_and_content_bound() -> None:
    first = project_broker_reconciliation(_run(), evaluated_at=NOW).to_payload()
    second = project_broker_reconciliation(_run(), evaluated_at=NOW).to_payload()

    assert first == second
    assert first["status"] == "review_required"
    assert first["difference_counts"] == {
        "order": 1,
        "fill": 0,
        "cash": 1,
        "position": 0,
    }
    assert len(first["content_hash"]) == 64
    assert first["permission"] == "display_only"
    assert first["must_not_execute"] is True


def test_unknown_nested_json_is_fail_closed_without_raw_passthrough() -> None:
    raw = _run()
    raw["differences"][0]["actual"]["token"] = "secret"

    result = project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()

    assert result["status"] == "blocked"
    assert result["summary"] == {}
    assert result["differences"] == []
    assert result["blocker_codes"] == ["broker_reconciliation_invalid"]


def test_counts_duplicate_identity_and_p0_flag_are_conserved() -> None:
    for mutate in (
        lambda row: row.update(order_difference_count=2),
        lambda row: row["differences"].append(deepcopy(row["differences"][0])),
        lambda row: row["summary"].update(p0_auto_stop=False),
    ):
        raw = _run()
        mutate(raw)
        assert (
            project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()["status"] == "blocked"
        )


def test_unknown_enums_and_inverted_clocks_are_blocked() -> None:
    cases: list[tuple[str, object]] = [
        ("status", "review"),
        ("started_at", "2026-08-13T12:01:00+00:00"),
        ("started_at", "2026-08-13T11:59:00"),
    ]
    for key, value in cases:
        raw = _run()
        raw[key] = value
        assert (
            project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()["status"] == "blocked"
        )

    raw = _run()
    raw["differences"][0]["severity"] = "P2"
    assert project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()["status"] == "blocked"


def test_closed_resolution_keeps_only_bounded_resolution_identity() -> None:
    raw = _run()
    raw["status"] = "resolved"
    raw["completed_at"] = "2026-08-13T12:00:00+00:00"
    raw["summary"].update(
        resolution="manual_adjustment",
        resolution_reason="operator text",
        resolved_by=99,
    )
    for difference in raw["differences"]:
        difference["status"] = "resolved"

    result = project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()

    assert result["status"] == "resolved"
    assert result["summary"]["resolution"] == "manual_adjustment"
    assert "resolution_reason" not in result["summary"]
    assert "resolved_by" not in result["summary"]


def test_completed_zero_difference_run_is_consistent() -> None:
    raw = _run()
    raw.update(
        status="completed",
        order_difference_count=0,
        cash_difference_count=0,
        differences=[],
        completed_at="2026-08-13T11:59:00+00:00",
    )
    raw["summary"].update(difference_count=0, p0_auto_stop=False)

    result = project_broker_reconciliation(raw, evaluated_at=NOW).to_payload()

    assert result["status"] == "completed"
    assert result["differences"] == []
    assert result["blocker_codes"] == []
