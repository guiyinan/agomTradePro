"""Unit contracts for Web-to-TUI M5 production telemetry evidence generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from scripts import build_web_to_tui_production_telemetry as production_telemetry

SOURCE_SHA256 = "a" * 64
CANDIDATE_COMMIT = "b" * 40


@pytest.fixture(autouse=True)
def usable_candidate_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat the synthetic full commit as part of the current branch history."""

    monkeypatch.setattr(
        production_telemetry,
        "_git_commit_is_usable",
        lambda *args, **kwargs: True,
    )


def _catalog() -> dict[str, Any]:
    """Build a minimal bounded telemetry catalog."""

    return {
        "source_sha256": SOURCE_SHA256,
        "classic_routes": [
            {"task_key": "task.one"},
            {"task_key": "task.two"},
        ],
        "tui_task_keys": ["task.one", "task.two", "tui.only"],
    }


def _evidence() -> dict[str, Any]:
    """Build candidate-bound cutover evidence."""

    return {
        "source_sha256": SOURCE_SHA256,
        "candidate": {
            "stable_version": "0.9.0-rc1",
            "candidate_commit": CANDIDATE_COMMIT,
            "released_at": "2026-07-28",
            "observation_end": "2026-08-11",
            "retained_observation": {
                "version": "web-to-tui-retained-observation-binding.v1",
                "evidence": "docs/deployment/retained-checkpoint.json",
                "evidence_sha256": "d" * 64,
                "first_retained_sample_at": "2026-07-28T12:00:00Z",
                "minimum_observation_seconds": 1209600,
                "eligible_at": "2026-08-11T12:00:00Z",
            },
        },
        "telemetry": {"tasks": []},
    }


def _task(task_key: str) -> dict[str, Any]:
    """Build one passing production task record."""

    return {
        "task_key": task_key,
        "classic_entries": 1,
        "tui_entries": 19,
        "classic_task_requests": 20,
        "tui_task_requests": 20,
        "classic_task_errors": 0,
        "tui_task_errors": 0,
        "low_frequency_exception": None,
    }


def _snapshot() -> dict[str, Any]:
    """Build one complete reviewed Prometheus snapshot."""

    return {
        "version": production_telemetry.SNAPSHOT_VERSION,
        "source_sha256": SOURCE_SHA256,
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": CANDIDATE_COMMIT,
        "environment": "production",
        "window_start": "2026-07-28",
        "window_end": "2026-08-11",
        "collected_at": "2026-08-11T12:00:00Z",
        "collection": {
            "system": "prometheus",
            "endpoint": "https://prometheus.example.test",
            "queries": dict(production_telemetry.APPROVED_QUERIES),
        },
        "tasks": [_task("task.one"), _task("task.two")],
    }


def _build(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build telemetry evidence from one synthetic snapshot."""

    return production_telemetry.build_production_telemetry_evidence(
        snapshot=snapshot,
        catalog=_catalog(),
        evidence=_evidence(),
        snapshot_evidence_path="docs/plans/production-telemetry.json",
        snapshot_sha256="c" * 64,
        as_of=datetime(2026, 8, 11, 13, tzinfo=UTC),
    )


def test_builds_exact_candidate_bound_telemetry_evidence() -> None:
    """Only Classic-comparable tasks enter checker-compatible evidence."""

    prepared = _build(_snapshot())

    assert prepared["telemetry"]["environment"] == "production"
    assert prepared["telemetry"]["snapshot_sha256"] == "c" * 64
    assert [record["task_key"] for record in prepared["telemetry"]["tasks"]] == [
        "task.one",
        "task.two",
    ]


def test_checked_in_catalog_requires_only_classic_comparable_tasks() -> None:
    """TUI-only actions must not inflate the 101-task production denominator."""

    catalog = json.loads(production_telemetry.DEFAULT_CATALOG.read_text(encoding="utf-8"))

    assert len(production_telemetry._required_task_keys(catalog)) == 101
    assert len(catalog["tui_task_keys"]) > 101


def test_rejects_missing_extra_or_duplicate_task_keys() -> None:
    """The snapshot cannot shrink, expand, or duplicate the bounded catalog."""

    missing = _snapshot()
    missing["tasks"].pop()
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="coverage mismatch"):
        _build(missing)

    duplicate = _snapshot()
    duplicate["tasks"].append(_task("task.one"))
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="duplicate task"):
        _build(duplicate)


def test_rejects_snapshot_for_another_candidate_or_window() -> None:
    """Production samples cannot carry across candidate versions or windows."""

    snapshot = _snapshot()
    snapshot["candidate_version"] = "0.9.0-rc2"
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="different candidate"):
        _build(snapshot)

    snapshot = _snapshot()
    snapshot["window_start"] = "2026-07-27"
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="exactly match"):
        _build(snapshot)


@pytest.mark.parametrize(
    "collected_at",
    ("2026-08-11", "2026-08-11T11:59:59.999999Z"),
)
def test_rejects_date_only_or_premature_collection_timestamp(collected_at: str) -> None:
    """The final telemetry snapshot cannot pass before 14 exact retained days."""

    snapshot = _snapshot()
    snapshot["collected_at"] = collected_at

    with pytest.raises(
        production_telemetry.ProductionTelemetryError,
        match="timestamp|UTC",
    ):
        _build(snapshot)


def test_rejects_legacy_ratio_and_error_rate_regression() -> None:
    """A task above either approved production threshold cannot be written."""

    legacy_high = _snapshot()
    legacy_high["tasks"][0]["classic_entries"] = 2
    legacy_high["tasks"][0]["tui_entries"] = 18
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="thresholds failed"):
        _build(legacy_high)

    error_high = _snapshot()
    error_high["tasks"][0]["tui_task_errors"] = 1
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="thresholds failed"):
        _build(error_high)


def test_low_frequency_exception_waives_only_entry_sample_threshold() -> None:
    """Dual sign-off can waive entry volume but never request/error samples."""

    snapshot = _snapshot()
    record = snapshot["tasks"][0]
    record["classic_entries"] = 0
    record["tui_entries"] = 10
    record["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }
    assert len(_build(snapshot)["telemetry"]["tasks"]) == 2

    record["tui_task_requests"] = 19
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="thresholds failed"):
        _build(snapshot)


def test_rejects_unsafe_or_incomplete_collection_metadata() -> None:
    """Snapshots must identify auditable queries without embedding credentials."""

    unsafe = _snapshot()
    unsafe["collection"]["endpoint"] = "https://user:secret@prometheus.example.test"
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="credential-free"):
        _build(unsafe)

    incomplete = _snapshot()
    incomplete["collection"]["queries"].pop("tui_task_errors")
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="exact six"):
        _build(incomplete)

    wrong_query = _snapshot()
    wrong_query["collection"]["queries"]["tui_task_errors"] = wrong_query["collection"]["queries"][
        "tui_entries"
    ]
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="approved contract"):
        _build(wrong_query)
