from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from pytest import MonkeyPatch, raises

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
RECORDED_AT = datetime(2026, 8, 6, 2, tzinfo=timezone.utc)
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
    selected_scope = scope or _scope()
    rows = [_row(1)]
    return cleanup_guard.CandidateSnapshot(
        binding=_binding(),
        matrix_bytes=_matrix(rows),
        catalog={
            "sha256": SHA256,
            "task_count": len(selected_scope.task_keys),
            "task_keys": selected_scope.task_keys,
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
