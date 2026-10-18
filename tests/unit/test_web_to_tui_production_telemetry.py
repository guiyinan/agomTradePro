"""Unit contracts for Web-to-TUI M5 production telemetry evidence generation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts import build_web_to_tui_production_telemetry as production_telemetry
from scripts.build_web_to_tui_telemetry_catalog import build_catalog

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
            {"task_key": "task.one", "url_name": "one:page"},
            {"task_key": "task.two", "url_name": "two:page"},
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
            "binding": {
                "version": "web-to-tui-candidate-binding.v1",
                "candidate_version": "0.9.0-rc1",
                "candidate_commit": CANDIDATE_COMMIT,
                "matrix_sha256": SOURCE_SHA256,
                "graph_sha256": "e" * 64,
                "schema_version": "3",
                "runtime_version": "1",
                "runtime_build_id": "test",
                "runtime_manifest_sha256": "f" * 64,
            },
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


def _build(snapshot: dict[str, Any], *, root: Path = production_telemetry.ROOT) -> dict[str, Any]:
    """Build telemetry evidence from one synthetic snapshot."""

    return production_telemetry.build_production_telemetry_evidence(
        snapshot=snapshot,
        catalog=_catalog(),
        evidence=_evidence(),
        snapshot_evidence_path="docs/plans/production-telemetry.json",
        snapshot_sha256="c" * 64,
        as_of=datetime(2026, 8, 11, 13, tzinfo=UTC),
        evidence_root=root,
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
    """Only tasks projected from the current matrix enter the denominator."""

    catalog = json.loads(production_telemetry.DEFAULT_CATALOG.read_text(encoding="utf-8"))

    projected = build_catalog(production_telemetry.ROOT / catalog["source_matrix"])
    expected = {row["task_key"] for row in projected["classic_routes"]}
    assert production_telemetry._required_task_keys(catalog) == expected
    assert len(catalog["tui_task_keys"]) > len(expected)


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


def test_legacy_three_strings_cannot_authorize_low_frequency_acceptance() -> None:
    """A reason and two names cannot replace candidate-bound task acceptance."""

    snapshot = _snapshot()
    record = snapshot["tasks"][0]
    record["classic_entries"] = 0
    record["tui_entries"] = 10
    record["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }
    with pytest.raises(production_telemetry.ProductionTelemetryError, match="thresholds failed"):
        _build(snapshot)


def _artifact(root: Path, name: str, payload: dict[str, Any]) -> dict[str, str]:
    path = root / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"evidence": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _v3_fixture(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Model independently recorded raw query responses and task acceptance."""
    snapshot = _snapshot()
    snapshot["version"] = production_telemetry.LOW_FREQUENCY_SNAPSHOT_VERSION
    snapshot["acceptance_wave_id"] = "wave-1"
    snapshot["collection"]["query_at"] = snapshot["collected_at"]
    task = snapshot["tasks"][0]
    task.update(
        classic_entries=None,
        tui_entries=10,
        classic_task_requests=None,
        tui_task_requests=3,
        classic_task_errors=None,
        tui_task_errors=None,
    )
    uat_reference = _artifact(
        root,
        "task-uat-run.json",
        {
            "candidate_binding": _evidence()["candidate"]["binding"],
            "task_key": "task.one",
            "observations": {
                scope: f"Synthetic recorded steps and observed result for {scope}"
                for scope in ("primary_task", "clear_result", "error_recovery", "permission")
            },
        },
    )
    report = {
        "version": production_telemetry.LOW_FREQUENCY_ACCEPTANCE_VERSION,
        "candidate_binding": _evidence()["candidate"]["binding"],
        "task_key": "task.one",
        "route_pages": ["one:page"],
        "wave_id": "wave-1",
        "reason": "Low natural use; accept statistical uncertainty after task UAT",
        "sample_status": "insufficient_sample",
        "error_comparison": "not_applicable",
        "performed_by": "task-owner",
        "performed_at": "2026-08-10T12:00:00Z",
        "expires_at": "2026-08-12T12:00:00Z",
        "owner": {
            "actor": "task-owner",
            "risk_accepted": True,
            "accepted_at": "2026-08-11T12:10:00Z",
        },
        "reviewer": {
            "actor": "independent-reviewer",
            "approved": True,
            "reviewed_at": "2026-08-11T12:20:00Z",
        },
        "uat": {
            scope: {"passed": True, "evidence": uat_reference}
            for scope in ("primary_task", "clear_result", "error_recovery", "permission")
        },
    }
    task["low_frequency_exception"] = _artifact(root, "task-acceptance.json", report)
    raw = {
        "version": production_telemetry.RAW_RESULTS_VERSION,
        "candidate_binding": _evidence()["candidate"]["binding"],
        "endpoint": snapshot["collection"]["endpoint"],
        "queries": snapshot["collection"]["queries"],
        "query_at": snapshot["collection"]["query_at"],
        **{key: snapshot[key] for key in ("window_start", "window_end", "collected_at")},
        "results": {
            key: {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"task_key": row["task_key"]},
                            "value": [
                                datetime(2026, 8, 11, 12, tzinfo=UTC).timestamp(),
                                str(row[key]),
                            ],
                        }
                        for row in snapshot["tasks"]
                        if row[key] is not None
                    ],
                },
            }
            for key in production_telemetry.QUERY_KEYS
        },
    }
    snapshot["collection"]["raw_results"] = _artifact(root, "raw-results.json", raw)
    return snapshot, report, raw


def test_v3_accepts_independently_reviewed_task_without_inventing_zero(tmp_path: Path) -> None:
    snapshot, _, _ = _v3_fixture(tmp_path)
    task = _build(snapshot, root=tmp_path)["telemetry"]["tasks"][0]
    assert task["sample_status"] == "insufficient_sample"
    assert task["error_comparison"] == "not_applicable"
    assert task["classic_task_requests"] is None
    assert task["tui_task_requests"] == 3
    assert task["tui_task_errors"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "performer",
        "risk",
        "review",
        "expired",
        "future",
        "binding",
        "task",
        "wave",
        "routes",
        "uat",
        "status",
        "uat_text_only",
    ],
)
def test_v3_rejects_incomplete_nonindependent_or_wrong_candidate_acceptance(
    tmp_path: Path, fault: str
) -> None:
    snapshot, report, _ = _v3_fixture(tmp_path)
    if fault == "owner":
        report["reviewer"]["actor"] = "TASK-OWNER"
    elif fault == "performer":
        report["performed_by"] = report["reviewer"]["actor"]
    elif fault == "risk":
        report["owner"]["risk_accepted"] = False
    elif fault == "review":
        report["reviewer"]["approved"] = "true"
    elif fault == "expired":
        report["expires_at"] = "2026-08-11T12:59:59Z"
    elif fault == "future":
        report["reviewer"]["reviewed_at"] = "2026-08-11T14:00:00Z"
    elif fault == "binding":
        report["candidate_binding"]["graph_sha256"] = "1" * 64
    elif fault == "task":
        report["task_key"] = "task.two"
    elif fault == "wave":
        report["wave_id"] = "wave-2"
    elif fault == "routes":
        report["route_pages"] = []
    elif fault == "uat":
        report["uat"]["permission"]["passed"] = False
    elif fault == "status":
        report["error_comparison"] = "passed"
    elif fault == "uat_text_only":
        report["uat"]["primary_task"]["evidence"] = "unverified narrative"
    snapshot["tasks"][0]["low_frequency_exception"] = _artifact(
        tmp_path, "task-acceptance.json", report
    )
    with pytest.raises(production_telemetry.ProductionTelemetryError):
        _build(snapshot, root=tmp_path)


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "zero_for_unknown",
        "mismatch",
        "stale",
        "duplicate",
        "query_failure",
        "traversal",
        "hash",
        "observed_error",
        "high_share",
        "query_late",
    ],
)
def test_v3_rejects_bad_collection_or_statistics_despite_task_acceptance(
    tmp_path: Path, fault: str
) -> None:
    snapshot, _, raw = _v3_fixture(tmp_path)
    if fault == "empty":
        for response in raw["results"].values():
            response["data"]["result"] = []
    elif fault == "zero_for_unknown":
        snapshot["tasks"][0]["classic_task_requests"] = 0
    elif fault == "mismatch":
        snapshot["tasks"][0]["tui_task_requests"] = 4
    elif fault == "stale":
        raw["results"]["tui_task_requests"]["data"]["result"][0]["value"][0] -= 60
    elif fault == "duplicate":
        raw["results"]["tui_entries"]["data"]["result"].append(
            raw["results"]["tui_entries"]["data"]["result"][0]
        )
    elif fault == "query_failure":
        raw["results"]["tui_entries"]["status"] = "error"
    elif fault == "traversal":
        snapshot["tasks"][0]["low_frequency_exception"]["evidence"] = "../outside.json"
    elif fault == "hash":
        snapshot["tasks"][0]["low_frequency_exception"]["sha256"] = "1" * 64
    elif fault == "observed_error":
        snapshot["tasks"][0]["tui_task_errors"] = 1
        raw["results"]["tui_task_errors"]["data"]["result"].append(
            {
                "metric": {"task_key": "task.one"},
                "value": [datetime(2026, 8, 11, 12, tzinfo=UTC).timestamp(), "1"],
            }
        )
    elif fault == "high_share":
        snapshot["tasks"][1].update(classic_entries=2, tui_entries=18)
        raw["results"]["classic_entries"]["data"]["result"][0]["value"][1] = "2"
        raw["results"]["tui_entries"]["data"]["result"][1]["value"][1] = "18"
    elif fault == "query_late":
        snapshot["collection"]["query_at"] = "2026-08-12T12:00:00Z"
        raw["query_at"] = snapshot["collection"]["query_at"]
    snapshot["collection"]["raw_results"] = _artifact(tmp_path, "raw-results.json", raw)
    with pytest.raises(production_telemetry.ProductionTelemetryError):
        _build(snapshot, root=tmp_path)


def test_verified_artifact_is_parsed_from_the_same_hashed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _artifact(tmp_path, "verified.json", {"verified": True})
    monkeypatch.setattr(production_telemetry, "_load_object", lambda path: {"unverified": True})
    assert production_telemetry._verified_json_reference(reference, root=tmp_path) == {
        "verified": True
    }


def test_builder_cli_parses_the_snapshot_bytes_it_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, payload in (
        ("snapshot.json", _snapshot()),
        ("catalog.json", _catalog()),
        ("evidence.json", _evidence()),
    ):
        _artifact(tmp_path, name, payload)
    original_load = production_telemetry._load_object

    def guarded_load(path: Path) -> dict[str, Any]:
        assert path.name != "snapshot.json", "snapshot must not be reopened after hashing"
        return original_load(path)

    monkeypatch.setattr(production_telemetry, "_load_object", guarded_load)
    monkeypatch.setattr(
        production_telemetry, "_repository_evidence_path", lambda path: "snapshot.json"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "builder",
            "--snapshot",
            str(tmp_path / "snapshot.json"),
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--as-of",
            "2026-08-11T13:00:00Z",
        ],
    )
    assert production_telemetry.main() == 0


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
