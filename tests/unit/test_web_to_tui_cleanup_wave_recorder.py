from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest import MonkeyPatch, raises

from scripts import build_web_to_tui_production_telemetry as production_telemetry
from scripts import check_web_to_tui_cleanup_guard as cleanup_guard
from scripts import record_web_to_tui_cleanup_wave as recorder
from scripts import start_web_to_tui_observation as observation_start
from scripts.web_to_tui_candidate_binding import CandidateBinding

AUTHORIZATION_COMMIT = "a" * 40
CANDIDATE_COMMIT = "b" * 40
ROLLBACK_COMMIT = "c" * 40
SHA256 = "d" * 64
OBSERVED_FROM = "2026-08-04T00:00:00+00:00"
OBSERVED_UNTIL = "2026-08-06T00:00:00+00:00"
COLLECTED_AT = "2026-08-06T01:00:00+00:00"
RECORDED_AT = datetime(2026, 8, 6, 2, tzinfo=UTC)
MATRIX_FIELDS = (
    "template_path",
    "template_role",
    "destination_class",
    "status",
    "wave",
    "rollback_commit",
    "owner",
    "reviewer",
)


def _binding(commit: str = CANDIDATE_COMMIT) -> CandidateBinding:
    return {
        "version": cleanup_guard.BINDING_VERSION,
        "candidate_version": "0.9.0-m5-b",
        "candidate_commit": commit,
        "matrix_sha256": "1" * 64,
        "graph_sha256": "2" * 64,
        "schema_version": "tui-operation-graph.v1",
        "runtime_version": "agomtui-runtime-0.9.0",
        "runtime_build_id": "cleanup-test",
        "runtime_manifest_sha256": "3" * 64,
    }


def _path(index: int) -> str:
    return f"apps/example/templates/example/page_{index}.html"


def _row(
    index: int,
    *,
    status: str = "deleted",
    wave: str = "M5-B-W1",
) -> dict[str, str]:
    return {
        "template_path": _path(index),
        "template_role": "route_page",
        "destination_class": "A",
        "status": status,
        "wave": wave,
        "rollback_commit": ROLLBACK_COMMIT,
        "owner": "owner-a",
        "reviewer": "reviewer-b",
    }


def _matrix(rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=MATRIX_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _catalog(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "classic_routes": [
            {
                "template_path": row["template_path"],
                "task_key": f"task-{index}",
            }
            for index, row in enumerate(rows, start=1)
        ]
    }


def _always_ancestor(
    commit: str,
    *,
    root: Path,
    descendant: str = "HEAD",
) -> bool:
    del root, descendant
    return bool(commit)


def _scope(task_keys: frozenset[str] = frozenset({"task-1"})) -> recorder.WaveScope:
    return recorder.WaveScope(
        wave="M5-B-W1",
        deleted_paths=(_path(1),),
        route_count=1,
        task_keys=task_keys,
        rollback_commits={_path(1): ROLLBACK_COMMIT},
        owners=("owner-a",),
        reviewers=("reviewer-b",),
    )


def _candidate(scope: recorder.WaveScope | None = None) -> cleanup_guard.CandidateSnapshot:
    rows = [_row(1)]
    return cleanup_guard.CandidateSnapshot(
        binding=_binding(),
        matrix_bytes=_matrix(rows),
        catalog={
            "sha256": SHA256,
            "task_count": 2,
            "task_keys": frozenset({"task-1", "task-global"}),
            "known_task_keys": frozenset({"task-1", "task-global"}),
            "routes": (
                ("task:page", "task-1", _path(1)),
                ("task:page-alias", "task-1", _path(1)),
                ("global:page", "task-global", _path(2)),
            ),
        },
    )


def _authorization() -> cleanup_guard.FinalAuthorization:
    return cleanup_guard.FinalAuthorization(
        binding=_binding(AUTHORIZATION_COMMIT),
        approved_at=date(2026, 8, 4),
        artifact_digests=(),
    )


def _telemetry(binding: CandidateBinding | None = None) -> dict[str, Any]:
    return {
        "version": recorder.TELEMETRY_VERSION,
        "environment": "production",
        "wave": "M5-B-W1",
        "candidate_binding": binding or _binding(),
        "baseline_window": {
            "start": "2026-08-02T00:00:00+00:00",
            "end": OBSERVED_FROM,
        },
        "candidate_window": {
            "start": OBSERVED_FROM,
            "end": OBSERVED_UNTIL,
        },
        "collected_at": COLLECTED_AT,
        "collection": {
            "system": "production-metrics",
            "endpoint": "https://metrics.example.invalid/export",
            "query_id": recorder.TELEMETRY_QUERY_ID,
            "collected_by": "scheduled-exporter",
        },
        "tasks": [
            {
                "task_key": "task-1",
                "baseline_requests": 100,
                "baseline_errors": 1,
                "candidate_requests": 100,
                "candidate_errors": 1,
            }
        ],
    }


def _deployment(commit: str = CANDIDATE_COMMIT) -> dict[str, Any]:
    return {
        "version": observation_start.DEPLOYMENT_ATTESTATION_VERSION,
        "environment": "production",
        "release": {
            "stable_version": "0.9.0-m5-b",
            "release_id": "release-20260804-1",
            "source_commit": commit,
            "deployed_at": "2026-08-03T23:50:00+00:00",
        },
        "oci_image": {
            "image_id": "sha256:" + "4" * 64,
            "revision": commit,
        },
        "production_health": {
            "checked_at": "2026-08-03T23:59:00+00:00",
            "health": {
                "http_status": 200,
                "status": "ok",
                "response_sha256": "5" * 64,
            },
            "readiness": {
                "http_status": 200,
                "status": "ok",
                "response_sha256": "6" * 64,
            },
        },
        "verified_at": OBSERVED_FROM,
    }


def _defects() -> dict[str, Any]:
    return {
        "version": recorder.DEFECT_VERSION,
        "environment": "production",
        "wave": "M5-B-W1",
        "candidate_binding": _binding(),
        "window_start": OBSERVED_FROM,
        "window_end": OBSERVED_UNTIL,
        "queried_at": COLLECTED_AT,
        "query_scope": recorder.DEFECT_QUERY_SCOPE,
        "tracker": {
            "system": "production-defect-tracker",
            "endpoint": "https://defects.example.invalid/export",
            "project": "web-to-tui",
            "query_filter": "priority in (P0, P1)",
            "queried_by": "scheduled-exporter",
        },
        "issues": [],
    }


def _cycles() -> dict[str, Any]:
    return {
        "version": recorder.SCHEDULED_CYCLE_VERSION,
        "environment": "production",
        "wave": "M5-B-W1",
        "candidate_binding": _binding(),
        "window_start": OBSERVED_FROM,
        "window_end": OBSERVED_UNTIL,
        "collected_at": COLLECTED_AT,
        "collection": {
            "system": "production-task-monitor",
            "endpoint": "https://tasks.example.invalid/export",
            "query_id": recorder.SCHEDULED_CYCLE_QUERY_ID,
            "collected_by": "scheduled-exporter",
        },
        "cycles": [
            {
                "task_key": "task-1",
                "run_id": "run-20260805-1",
                "observed_at": "2026-08-05T00:00:00+00:00",
                "outcome": "success",
            }
        ],
    }


def _raw(name: str, payload: dict[str, Any]) -> recorder.RawArtifact:
    return recorder.RawArtifact(
        path=recorder.ROOT / "reports" / name,
        reference=f"reports/{name}",
        sha256="e" * 64,
        payload=payload,
        git_commit="7" * 40,
        git_committed_at=datetime.fromisoformat(OBSERVED_FROM),
    )


def _write_digest_json(root: Path, name: str, payload: dict[str, Any]) -> dict[str, str]:
    """Write a real byte-backed fixture reference for production evidence helpers."""

    content = recorder._json_bytes(payload)
    (root / name).write_bytes(content)
    return {"evidence": name, "sha256": recorder._sha256(content)}


def _low_frequency_telemetry(root: Path) -> dict[str, Any]:
    """Build a v2 snapshot with one unknown baseline count and real global traffic."""

    baseline_window = {
        "start": "2026-08-02T00:00:00Z",
        "end": "2026-08-04T00:00:00Z",
    }
    candidate_window = {
        "start": OBSERVED_FROM,
        "end": OBSERVED_UNTIL,
    }
    query_at = {
        "baseline_requests": baseline_window["end"],
        "baseline_errors": baseline_window["end"],
        "candidate_requests": candidate_window["end"],
        "candidate_errors": candidate_window["end"],
    }
    uat_evidence = {
        scope: {
            "passed": True,
            "evidence": _write_digest_json(
                root, f"uat-{scope}.json", {"steps": [scope], "result": "passed"}
            ),
        }
        for scope in ("primary_task", "clear_result", "error_recovery", "permission")
    }
    acceptance = {
        "version": production_telemetry.LOW_FREQUENCY_ACCEPTANCE_VERSION,
        "candidate_binding": dict(_binding()),
        "task_key": "task-1",
        "route_pages": ["task:page", "task:page-alias"],
        "wave_id": "M5-B-W1",
        "reason": "Natural request count is insufficient; task UAT and independent risk review completed.",
        "sample_status": "insufficient_sample",
        "error_comparison": "not_applicable",
        "performed_by": "performer",
        "performed_at": "2026-08-05T00:00:00Z",
        "expires_at": "2026-08-10T00:00:00Z",
        "owner": {
            "actor": "owner-a",
            "risk_accepted": True,
            "accepted_at": "2026-08-06T01:10:00Z",
        },
        "reviewer": {
            "actor": "independent-reviewer",
            "approved": True,
            "reviewed_at": "2026-08-06T01:20:00Z",
        },
        "uat": uat_evidence,
    }
    raw_reference = _write_digest_json(
        root,
        "cleanup-raw-results.json",
        {
            "version": production_telemetry.RAW_RESULTS_VERSION,
            "candidate_binding": dict(_binding()),
            "endpoint": "https://metrics.example.invalid/export",
            "queries": dict(production_telemetry.CLEANUP_LOW_FREQUENCY_QUERIES),
            "query_at": query_at,
            "collected_at": COLLECTED_AT,
            "baseline_window": baseline_window,
            "candidate_window": candidate_window,
            "results": {
                "baseline_requests": {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {"task_key": "task-1"},
                                "value": [datetime(2026, 8, 4, tzinfo=UTC).timestamp(), "8"],
                            }
                        ],
                    },
                },
                "baseline_errors": {
                    "status": "success",
                    "data": {"resultType": "vector", "result": []},
                },
                "candidate_requests": {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {"task_key": "task-1"},
                                "value": [datetime(2026, 8, 6, tzinfo=UTC).timestamp(), "3"],
                            },
                            {
                                "metric": {"task_key": "task-global"},
                                "value": [datetime(2026, 8, 6, tzinfo=UTC).timestamp(), "100"],
                            },
                        ],
                    },
                },
                "candidate_errors": {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {"task_key": "task-1"},
                                "value": [datetime(2026, 8, 6, tzinfo=UTC).timestamp(), "0"],
                            }
                        ],
                    },
                },
            },
        },
    )
    return {
        "version": recorder.LOW_FREQUENCY_TELEMETRY_VERSION,
        "environment": "production",
        "wave": "M5-B-W1",
        "candidate_binding": dict(_binding()),
        "baseline_window": baseline_window,
        "candidate_window": candidate_window,
        "collected_at": COLLECTED_AT,
        "collection": {
            "system": "prometheus",
            "endpoint": "https://metrics.example.invalid/export",
            "query_id": "web-to-tui-wave-error-rate-by-task.v2",
            "collected_by": "scheduled-exporter",
        },
        "queries": dict(production_telemetry.CLEANUP_LOW_FREQUENCY_QUERIES),
        "query_at": query_at,
        "raw_results": raw_reference,
        "tasks": [
            {
                "task_key": "task-1",
                "baseline_requests": 8,
                "baseline_errors": None,
                "candidate_requests": 3,
                "candidate_errors": 0,
                "low_frequency_exception": _write_digest_json(
                    root, "cleanup-task-acceptance.json", acceptance
                ),
            }
        ],
    }


def test_derive_wave_scope_uses_candidate_matrix_catalog_and_rollback_history(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    candidate_rows = [_row(1), _row(2)]

    scope = recorder.derive_wave_scope(
        authorized_matrix=_matrix(
            [_row(1, status="migrated", wave="M3"), _row(2, status="migrated", wave="M3")]
        ),
        candidate_matrix=_matrix(candidate_rows),
        candidate_catalog=_catalog(candidate_rows),
        candidate_binding=_binding(),
        existing_wave_values=[],
    )

    assert scope.wave == "M5-B-W1"
    assert scope.deleted_paths == (_path(1), _path(2))
    assert scope.route_count == 2
    assert scope.task_keys == frozenset({"task-1", "task-2"})
    assert scope.rollback_commits == {
        _path(1): ROLLBACK_COMMIT,
        _path(2): ROLLBACK_COMMIT,
    }


def test_derive_wave_scope_rejects_more_than_ten_route_pages(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    candidate_rows = [_row(index) for index in range(1, 12)]
    authorized_rows = [_row(index, status="migrated", wave="M3") for index in range(1, 12)]

    with raises(recorder.CleanupWaveRecordingError, match="within 1..10"):
        recorder.derive_wave_scope(
            authorized_matrix=_matrix(authorized_rows),
            candidate_matrix=_matrix(candidate_rows),
            candidate_catalog=_catalog(candidate_rows),
            candidate_binding=_binding(),
            existing_wave_values=[],
        )


def test_derive_wave_scope_rejects_two_unrecorded_waves(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    candidate_rows = [_row(1), _row(2, wave="M5-B-W2")]
    authorized_rows = [
        _row(1, status="migrated", wave="M3"),
        _row(2, status="migrated", wave="M3"),
    ]

    with raises(recorder.CleanupWaveRecordingError, match="exactly one cleanup wave"):
        recorder.derive_wave_scope(
            authorized_matrix=_matrix(authorized_rows),
            candidate_matrix=_matrix(candidate_rows),
            candidate_catalog=_catalog(candidate_rows),
            candidate_binding=_binding(),
            existing_wave_values=[],
        )


def test_build_wave_bundle_derives_guard_artifacts_from_raw_snapshots(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    scope = _scope()
    bundle = recorder.build_wave_bundle(
        scope=scope,
        authorization=_authorization(),
        candidate=_candidate(scope),
        deployment_preflight=_raw("deployment.json", _deployment()),
        telemetry=_raw("telemetry.json", _telemetry()),
        defects=_raw("defects.json", _defects()),
        scheduled_cycles=_raw("cycles.json", _cycles()),
        artifact_directory=(
            recorder.ROOT / "config/tui/migration/evidence/cleanup-waves/m5-b-w1-test"
        ),
        recorded_at=RECORDED_AT,
    )

    assert bundle.projection["wave"] == "M5-B-W1"
    assert bundle.projection["deleted_paths"] == [_path(1)]
    assert bundle.projection["owner"] == "owner-a"
    assert bundle.projection["reviewer"] == "reviewer-b"
    assert bundle.observation_ledger["defects"] == {
        "new_p0": 0,
        "new_p1": 0,
        "open_p0": 0,
        "open_p1": 0,
    }
    assert bundle.wave_record["derived_summary"]["observation_seconds"] == 172800
    assert bundle.wave_record["source_artifacts"]["deployment_preflight"] == {
        "path": "reports/deployment.json",
        "sha256": "e" * 64,
    }
    assert bundle.wave_record["deployment"]["source_commit"] == CANDIDATE_COMMIT
    assert bundle.rollback_manifest["route_rollback_commits"] == {_path(1): ROLLBACK_COMMIT}
    assert "passed" not in json.dumps(bundle.wave_record)
    assert bundle.projection["evidence_sha256"] == recorder._sha256(
        recorder._json_bytes(bundle.wave_record)
    )


def _build_low_frequency_bundle(
    root: Path,
    telemetry: dict[str, Any] | None = None,
) -> tuple[recorder.WaveBundle, dict[str, Any], cleanup_guard.CandidateSnapshot]:
    """Build a low-frequency wave using actual hash-bound fixture files."""

    scope = _scope()
    candidate = _candidate(scope)
    snapshot = telemetry or _low_frequency_telemetry(root)
    bundle = recorder.build_wave_bundle(
        scope=scope,
        authorization=_authorization(),
        candidate=candidate,
        deployment_preflight=_raw("deployment.json", _deployment()),
        telemetry=_raw("telemetry-v2.json", snapshot),
        defects=_raw("defects.json", _defects()),
        scheduled_cycles=_raw("cycles.json", _cycles()),
        artifact_directory=recorder.ROOT / ".tmp" / "t3-lf" / "test-artifacts" / "m5-b-w1",
        recorded_at=RECORDED_AT,
        evidence_root=root,
    )
    return bundle, snapshot, candidate


def test_low_frequency_wave_bundle_preserves_unknown_counts_and_binds_ledger_to_raw(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The v2 ledger preserves null and repeats metrics derived from raw bytes."""

    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    bundle, telemetry, candidate = _build_low_frequency_bundle(tmp_path)
    metric = bundle.observation_ledger["error_metrics"][0]
    assert metric["baseline_errors"] is None
    assert metric["candidate_errors"] == 0
    assert metric["sample_status"] == "insufficient_sample"
    assert metric["error_comparison"] == "not_applicable"
    assert bundle.observation_ledger["telemetry"] == {
        "path": "reports/telemetry-v2.json",
        "sha256": "e" * 64,
    }
    assert (
        cleanup_guard._observation_window(
            bundle.observation_ledger,
            wave="M5-B-W1",
            candidate=candidate,
            as_of=RECORDED_AT.date(),
            evaluated_at=RECORDED_AT,
            telemetry_snapshot=telemetry,
            telemetry_reference=bundle.observation_ledger["telemetry"],
            deployed_at=datetime.fromisoformat(bundle.wave_record["deployment"]["deployed_at"]),
            evidence_root=tmp_path,
        )
        is not None
    )

    changed_ledger = dict(bundle.observation_ledger)
    changed_metric = dict(metric)
    changed_metric["candidate_requests"] = 4
    changed_ledger["error_metrics"] = [changed_metric]
    assert (
        cleanup_guard._observation_window(
            changed_ledger,
            wave="M5-B-W1",
            candidate=candidate,
            as_of=RECORDED_AT.date(),
            evaluated_at=RECORDED_AT,
            telemetry_snapshot=telemetry,
            telemetry_reference=bundle.observation_ledger["telemetry"],
            deployed_at=datetime.fromisoformat(bundle.wave_record["deployment"]["deployed_at"]),
            evidence_root=tmp_path,
        )
        is None
    )


def test_low_frequency_wave_guard_rejects_expired_exception_and_observed_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Expired UAT or any observed error blocks the low-frequency exception."""

    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    bundle, telemetry, candidate = _build_low_frequency_bundle(tmp_path)
    deployment = datetime.fromisoformat(bundle.wave_record["deployment"]["deployed_at"])
    assert (
        cleanup_guard._observation_window(
            bundle.observation_ledger,
            wave="M5-B-W1",
            candidate=candidate,
            as_of=date(2026, 8, 11),
            evaluated_at=datetime(2026, 8, 11, tzinfo=UTC),
            telemetry_snapshot=telemetry,
            telemetry_reference=bundle.observation_ledger["telemetry"],
            deployed_at=deployment,
            evidence_root=tmp_path,
        )
        is None
    )

    raw_reference = telemetry["raw_results"]
    raw_path = tmp_path / raw_reference["evidence"]
    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_payload["results"]["candidate_errors"]["data"]["result"] = [
        item
        for item in raw_payload["results"]["candidate_errors"]["data"]["result"]
        if item["metric"]["task_key"] != "task-1"
    ] + [
        {
            "metric": {"task_key": "task-1"},
            "value": [datetime(2026, 8, 6, tzinfo=UTC).timestamp(), "1"],
        }
    ]
    raw_bytes = recorder._json_bytes(raw_payload)
    raw_path.write_bytes(raw_bytes)
    telemetry["raw_results"]["sha256"] = recorder._sha256(raw_bytes)
    telemetry["tasks"][0]["candidate_errors"] = 1
    with raises(recorder.CleanupWaveRecordingError, match="Observed cleanup telemetry errors"):
        _build_low_frequency_bundle(tmp_path, telemetry)


def test_telemetry_rejects_a_forty_seven_hour_candidate_window() -> None:
    telemetry = _telemetry()
    candidate_window = cast(dict[str, Any], telemetry["candidate_window"])
    candidate_window["start"] = "2026-08-04T01:00:00+00:00"

    with raises(recorder.CleanupWaveRecordingError, match="48-hour windows"):
        recorder.derive_error_metrics(
            telemetry,
            scope=_scope(),
            binding=_binding(),
            recorded_at=RECORDED_AT,
        )


def test_schema_rejects_caller_authored_passed_flag() -> None:
    telemetry = _telemetry()
    telemetry["passed"] = True

    with raises(recorder.CleanupWaveRecordingError, match="schema validation"):
        recorder._validate_schema(telemetry, recorder.DEFAULT_SCHEMA)


def test_deployment_schema_rejects_caller_authored_passed_flag() -> None:
    deployment = _deployment()
    deployment["passed"] = True

    with raises(recorder.CleanupWaveRecordingError, match="schema validation"):
        recorder._validate_schema(deployment, recorder.DEFAULT_DEPLOYMENT_SCHEMA)


def test_missing_deployment_preflight_is_denied() -> None:
    with raises(recorder.CleanupWaveRecordingError, match="snapshot is required"):
        recorder.build_wave_bundle(
            scope=_scope(),
            authorization=_authorization(),
            candidate=_candidate(),
            deployment_preflight=None,
            telemetry=_raw("telemetry.json", _telemetry()),
            defects=_raw("defects.json", _defects()),
            scheduled_cycles=_raw("cycles.json", _cycles()),
            artifact_directory=(
                recorder.ROOT
                / "config/tui/migration/evidence/cleanup-waves/missing-deployment-test"
            ),
            recorded_at=RECORDED_AT,
        )


def test_deployment_preflight_must_match_exact_candidate() -> None:
    with raises(recorder.CleanupWaveRecordingError, match="exact cleanup candidate"):
        recorder.validate_deployment_preflight(
            _raw("deployment.json", _deployment("f" * 40)),
            binding=_binding(),
            observed_from=datetime.fromisoformat(OBSERVED_FROM),
            recorded_at=RECORDED_AT,
        )


def test_observation_cannot_start_before_deployment_verification() -> None:
    deployment = _deployment()
    health = cast(dict[str, Any], deployment["production_health"])
    health["checked_at"] = "2026-08-04T00:04:00+00:00"
    deployment["verified_at"] = "2026-08-04T00:05:00+00:00"

    with raises(recorder.CleanupWaveRecordingError, match="before production deployment"):
        recorder.validate_deployment_preflight(
            _raw("deployment.json", deployment),
            binding=_binding(),
            observed_from=datetime.fromisoformat(OBSERVED_FROM),
            recorded_at=RECORDED_AT,
        )


def test_defect_records_recompute_a_blocking_issue() -> None:
    defects = _defects()
    defects["issues"] = [
        {
            "id": "P1-123",
            "priority": "P1",
            "state": "open",
            "created_at": "2026-08-05T00:00:00+00:00",
            "closed_at": None,
        }
    ]

    with raises(recorder.CleanupWaveRecordingError, match="blocking defects remain"):
        recorder.derive_defect_counts(
            defects,
            wave="M5-B-W1",
            binding=_binding(),
            observed_from=datetime.fromisoformat(OBSERVED_FROM),
            observed_until=datetime.fromisoformat(OBSERVED_UNTIL),
            recorded_at=RECORDED_AT,
        )


def test_scheduled_cycles_require_every_wave_task() -> None:
    with raises(recorder.CleanupWaveRecordingError, match="coverage differs"):
        recorder.derive_scheduled_cycles(
            _cycles(),
            scope=_scope(frozenset({"task-1", "task-2"})),
            binding=_binding(),
            observed_from=datetime.fromisoformat(OBSERVED_FROM),
            observed_until=datetime.fromisoformat(OBSERVED_UNTIL),
            recorded_at=RECORDED_AT,
        )


def test_old_raw_evidence_is_not_reused_for_a_new_candidate() -> None:
    previous_binding = _binding("f" * 40)
    telemetry = _telemetry(previous_binding)

    with raises(recorder.CleanupWaveRecordingError, match="binding mismatch"):
        recorder.derive_error_metrics(
            telemetry,
            scope=_scope(),
            binding=_binding(),
            recorded_at=RECORDED_AT,
        )


def test_evidence_write_failure_removes_new_external_artifacts(
    monkeypatch: MonkeyPatch,
) -> None:
    bundle = recorder.WaveBundle(
        rollback_manifest={"artifact": "rollback"},
        observation_ledger={"artifact": "observation"},
        wave_record={"artifact": "wave"},
        projection={"wave": "M5-B-W1"},
    )
    with TemporaryDirectory(dir=recorder.ROOT) as raw_directory:
        root = Path(raw_directory)
        evidence_path = root / "evidence.json"
        evidence_path.write_text('{"cleanup":{"waves":[]}}', encoding="utf-8")
        artifact_directory = root / "artifacts" / "m5-b-w1"

        def fail_on_evidence(path: Path, value: dict[str, Any]) -> None:
            if path.resolve() == evidence_path.resolve():
                raise OSError("simulated evidence replacement failure")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(recorder._json_bytes(value))

        monkeypatch.setattr(recorder, "_write_atomic", fail_on_evidence)
        with raises(OSError, match="simulated evidence replacement failure"):
            recorder.write_wave_bundle(
                bundle=bundle,
                evidence={"cleanup": {"waves": []}},
                evidence_path=evidence_path,
                artifact_directory=artifact_directory,
            )

        assert evidence_path.read_text(encoding="utf-8") == '{"cleanup":{"waves":[]}}'
        assert not artifact_directory.exists()


@pytest.mark.parametrize("committed", [False, True])
def test_artifact_loaders_parse_and_hash_one_read(
    tmp_path: Path, monkeypatch: MonkeyPatch, committed: bool
) -> None:
    """Neither raw counts nor committed deployment JSON can change after hashing."""
    monkeypatch.setattr(recorder, "ROOT", tmp_path)
    payload = _deployment() if committed else _telemetry()
    path = tmp_path / "snapshot.json"
    content = recorder._json_bytes(payload)
    path.write_bytes(content)
    original_read = Path.read_bytes
    reads = 0

    def once(candidate: Path) -> bytes:
        nonlocal reads
        if candidate.resolve() == path.resolve():
            reads += 1
            if reads > 1:
                raise AssertionError("artifact reopened after identity check")
            return content
        return original_read(candidate)

    monkeypatch.setattr(Path, "read_bytes", once)
    if committed:
        monkeypatch.setattr(cleanup_guard, "_git_source_bytes", lambda *args, **kwargs: content)
        monkeypatch.setattr(
            recorder,
            "_latest_blob_commit",
            lambda *args: ("e" * 40, datetime(2026, 8, 3, 23, 59, tzinfo=UTC)),
        )
        artifact = recorder.load_committed_deployment_preflight(path)
    else:
        artifact = recorder.load_raw_artifact(path, schema_path=recorder.DEFAULT_SCHEMA)
    assert artifact.payload == payload
    assert artifact.sha256 == recorder._sha256(recorder._normalized_bytes(content))
    assert reads == 1


@pytest.mark.parametrize(
    "fault", [None, "defect", "cycle_failed", "cycle_missing", "hash", "wrong_window", "late"]
)
def test_guard_rebuilds_raw_defects_and_cycles(
    tmp_path: Path, monkeypatch: MonkeyPatch, fault: str | None
) -> None:
    """A zero-defect/success ledger must agree with its original source files."""
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    bundle, _, candidate = _build_low_frequency_bundle(tmp_path)
    defects = _defects()
    cycles = _cycles()
    if fault == "defect":
        defects["issues"] = [
            {
                "id": "P1-bad",
                "priority": "P1",
                "state": "open",
                "created_at": "2026-08-05T00:00:00Z",
                "closed_at": None,
            }
        ]
    elif fault == "cycle_failed":
        cycles["cycles"][0]["outcome"] = "failed"
    elif fault == "cycle_missing":
        cycles["cycles"] = []
    elif fault == "wrong_window":
        defects["window_start"] = "2026-08-03T00:00:00Z"
    elif fault == "late":
        cycles["collected_at"] = "2026-08-08T00:00:00Z"
    sources: dict[str, Any] = {}
    for key, payload in (("defects", defects), ("scheduled_cycles", cycles)):
        content = recorder._json_bytes(payload)
        reference = key + ".json"
        (tmp_path / reference).write_bytes(content)
        sources[key] = {"path": reference, "sha256": recorder._sha256(content)}
    if fault == "hash":
        sources["defects"]["sha256"] = "a" * 64
    assert cleanup_guard._raw_wave_outcomes_match(
        sources,
        bundle.observation_ledger,
        wave="M5-B-W1",
        candidate=candidate,
        evidence_root=tmp_path,
        evaluated_at=RECORDED_AT,
    ) is (fault is None)


def test_v1_guard_cannot_omit_another_task_in_the_same_wave() -> None:
    """Legacy sufficient-sample ledgers cannot bypass per-task coverage."""
    original = _candidate()
    candidate = cleanup_guard.CandidateSnapshot(
        binding=original.binding,
        matrix_bytes=_matrix([_row(1), _row(2)]),
        catalog=original.catalog,
    )
    start, end, metrics = recorder.derive_error_metrics(
        _telemetry(),
        scope=_scope(),
        binding=candidate.binding,
        recorded_at=RECORDED_AT,
    )
    observation = {
        "version": cleanup_guard.CLEANUP_OBSERVATION_VERSION,
        "wave": "M5-B-W1",
        "candidate_binding": candidate.binding,
        "observed_from": start.isoformat(),
        "observed_until": end.isoformat(),
        "scheduled_cycles": [
            {"task_key": "task-1", "observed_at": "2026-08-05T00:00:00+00:00", "outcome": "success"}
        ],
        "defects": {"new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0},
        "error_metrics": metrics,
    }
    assert (
        cleanup_guard._observation_window(
            observation,
            wave="M5-B-W1",
            candidate=candidate,
            as_of=RECORDED_AT.date(),
        )
        is None
    )


_V2_ATTESTATION_COMMIT = "7" * 40
_V2_ATTESTATION_TIME = datetime.fromisoformat(OBSERVED_FROM)


def _write_v2_source_artifact(
    root: Path,
    reference: str,
    payload: dict[str, Any],
    *,
    git_commit: str | None = None,
    git_committed_at: datetime | None = None,
) -> tuple[recorder.RawArtifact, bytes]:
    """Persist one source artifact and return its true digest-bound reference."""

    content = recorder._json_bytes(payload)
    path = root / reference
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    artifact = recorder.RawArtifact(
        path=path,
        reference=reference,
        sha256=recorder._sha256(recorder._normalized_bytes(content)),
        payload=payload,
        git_commit=git_commit,
        git_committed_at=git_committed_at,
    )
    return artifact, content


def _build_hash_bound_v2_chain(
    root: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[
    recorder.WaveBundle,
    cleanup_guard.CandidateSnapshot,
    dict[str, Any],
    Path,
    bytes,
]:
    """Build the real-file v2 evidence chain used by the guard helper test."""

    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    telemetry = _low_frequency_telemetry(root)
    telemetry_artifact, _ = _write_v2_source_artifact(root, "reports/telemetry-v2.json", telemetry)
    deployment_artifact, deployment_bytes = _write_v2_source_artifact(
        root,
        "reports/deployment.json",
        _deployment(),
        git_commit=_V2_ATTESTATION_COMMIT,
        git_committed_at=_V2_ATTESTATION_TIME,
    )
    defects_artifact, _ = _write_v2_source_artifact(root, "reports/defects.json", _defects())
    cycles_artifact, _ = _write_v2_source_artifact(root, "reports/scheduled-cycles.json", _cycles())
    candidate = _candidate()
    bundle = recorder.build_wave_bundle(
        scope=_scope(),
        authorization=_authorization(),
        candidate=candidate,
        deployment_preflight=deployment_artifact,
        telemetry=telemetry_artifact,
        defects=defects_artifact,
        scheduled_cycles=cycles_artifact,
        artifact_directory=recorder.ROOT / ".tmp" / "t3-lf" / "test-artifacts" / "m5-b-w1",
        recorded_at=RECORDED_AT,
        evidence_root=root,
    )
    for reference, payload in (
        (bundle.projection["evidence"], bundle.wave_record),
        (bundle.projection["observation_ledger"], bundle.observation_ledger),
        (bundle.projection["rollback_manifest"], bundle.rollback_manifest),
    ):
        content = recorder._json_bytes(payload)
        destination = root / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return (
        bundle,
        candidate,
        telemetry,
        deployment_artifact.path,
        deployment_bytes,
    )


def _install_v2_git_boundary(
    monkeypatch: MonkeyPatch,
    *,
    root: Path,
    deployment_path: Path,
    deployment_bytes: bytes,
    commit_time: str = OBSERVED_FROM,
    committed_blob: bytes | None = None,
) -> None:
    """Mock only immutable Git blob, ancestry, and commit-time reads."""

    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", _always_ancestor)
    source_bytes = deployment_bytes if committed_blob is None else committed_blob

    def fake_source_bytes(commit: str, path: Path, *, root: Path) -> bytes | None:
        if (
            commit == _V2_ATTESTATION_COMMIT
            and path.resolve() == deployment_path.resolve()
            and root.resolve() == deployment_path.parents[1].resolve()
        ):
            return source_bytes
        return None

    def fake_git_show(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert command == [
            "git",
            "show",
            "-s",
            "--format=%cI",
            _V2_ATTESTATION_COMMIT,
        ]
        assert Path(kwargs["cwd"]).resolve() == root.resolve()
        return SimpleNamespace(returncode=0, stdout=commit_time + "\n")

    monkeypatch.setattr(cleanup_guard, "_git_source_bytes", fake_source_bytes)
    monkeypatch.setattr(cleanup_guard.subprocess, "run", fake_git_show)


def _load_v2_observation(
    bundle: recorder.WaveBundle,
    *,
    root: Path,
) -> dict[str, Any]:
    """Load the ledger through its actual path and projection digest."""

    artifact = cleanup_guard._verified_repo_json(
        bundle.projection["observation_ledger"],
        bundle.projection["observation_ledger_sha256"],
        evidence_root=root,
    )
    assert artifact is not None
    return artifact[1]


def test_v2_wave_telemetry_inputs_follows_real_hash_bound_source_chain(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The exact wave, four raw sources, deployment blob, and commit time are reverified."""

    bundle, candidate, telemetry, deployment_path, deployment_bytes = _build_hash_bound_v2_chain(
        tmp_path, monkeypatch
    )
    _install_v2_git_boundary(
        monkeypatch,
        root=tmp_path,
        deployment_path=deployment_path,
        deployment_bytes=deployment_bytes,
    )
    observation = _load_v2_observation(bundle, root=tmp_path)
    result = cleanup_guard._v2_wave_telemetry_inputs(
        bundle.projection,
        observation,
        wave="M5-B-W1",
        candidate=candidate,
        deleted_paths=set(bundle.projection["deleted_paths"]),
        evidence_root=tmp_path,
        repository_root=tmp_path,
        evaluated_at=RECORDED_AT,
    )

    assert result is not None
    snapshot, deployed_at, telemetry_reference = result
    assert snapshot == telemetry
    assert deployed_at == datetime(2026, 8, 3, 23, 50, tzinfo=UTC)
    assert telemetry_reference == bundle.observation_ledger["telemetry"]
    assert (
        cleanup_guard._observation_window(
            observation,
            wave="M5-B-W1",
            candidate=candidate,
            as_of=RECORDED_AT.date(),
            evaluated_at=RECORDED_AT,
            telemetry_snapshot=snapshot,
            telemetry_reference=telemetry_reference,
            deployed_at=deployed_at,
            evidence_root=tmp_path,
        )
        is not None
    )


@pytest.mark.parametrize(
    "fault",
    (
        "telemetry_source_bytes",
        "telemetry_source_hash",
        "deployment_source_bytes",
        "committed_deployment_blob",
        "deployment_commit_time",
    ),
)
def test_v2_wave_telemetry_inputs_rejects_source_or_commit_tampering(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    fault: str,
) -> None:
    """Every v2 source, digest, committed blob, and commit time must match."""

    bundle, candidate, _telemetry, deployment_path, deployment_bytes = _build_hash_bound_v2_chain(
        tmp_path, monkeypatch
    )
    commit_time = OBSERVED_FROM
    committed_blob = deployment_bytes
    if fault == "telemetry_source_bytes":
        telemetry_reference = bundle.observation_ledger["telemetry"]
        source = tmp_path / telemetry_reference["path"]
        source.write_bytes(source.read_bytes() + b" ")
    elif fault == "telemetry_source_hash":
        projection = dict(bundle.projection)
        wave_path = tmp_path / projection["evidence"]
        wave_record = json.loads(wave_path.read_text(encoding="utf-8"))
        observation = dict(bundle.observation_ledger)
        forged_reference = dict(observation["telemetry"])
        forged_reference["sha256"] = "f" * 64
        observation["telemetry"] = forged_reference
        wave_record["source_artifacts"]["telemetry"] = forged_reference
        ledger_bytes = recorder._json_bytes(observation)
        ledger_path = tmp_path / projection["observation_ledger"]
        ledger_path.write_bytes(ledger_bytes)
        ledger_sha = recorder._sha256(recorder._normalized_bytes(ledger_bytes))
        wave_record["observation_ledger"]["sha256"] = ledger_sha
        projection["observation_ledger_sha256"] = ledger_sha
        wave_bytes = recorder._json_bytes(wave_record)
        wave_path.write_bytes(wave_bytes)
        projection["evidence_sha256"] = recorder._sha256(recorder._normalized_bytes(wave_bytes))
        bundle.projection.update(projection)
    elif fault == "deployment_source_bytes":
        deployment_path.write_bytes(deployment_path.read_bytes() + b" ")
    elif fault == "committed_deployment_blob":
        committed_blob = b"different committed deployment blob\n"
    elif fault == "deployment_commit_time":
        commit_time = "2026-08-03T23:59:59+00:00"
    else:
        raise AssertionError(f"unhandled v2 chain fault: {fault}")

    _install_v2_git_boundary(
        monkeypatch,
        root=tmp_path,
        deployment_path=deployment_path,
        deployment_bytes=deployment_bytes,
        commit_time=commit_time,
        committed_blob=committed_blob,
    )
    observation = _load_v2_observation(bundle, root=tmp_path)
    assert (
        cleanup_guard._v2_wave_telemetry_inputs(
            bundle.projection,
            observation,
            wave="M5-B-W1",
            candidate=candidate,
            deleted_paths=set(bundle.projection["deleted_paths"]),
            evidence_root=tmp_path,
            repository_root=tmp_path,
            evaluated_at=RECORDED_AT,
        )
        is None
    )
