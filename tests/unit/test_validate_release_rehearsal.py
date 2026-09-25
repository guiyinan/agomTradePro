"""Tests for the candidate-bound release rehearsal gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_release_rehearsal.py"
    spec = importlib.util.spec_from_file_location("validate_release_rehearsal", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()
CANDIDATE = "a" * 40
ASSET_CODES = ["000001.SZ", "600000.SH", "830001.BJ"]
UNIVERSE = hashlib.sha256(
    json.dumps(ASSET_CODES, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
TARGET_DATE = "2026-09-24"
GITHUB_REPOSITORY = "guiyinan/agomTradePro"
GITHUB_RUN_ID = 123456
PROVIDERS = [
    {
        "role": "quote",
        "provider_id": 1,
        "source": "tushare",
        "version": "v1",
        "endpoint_id": "primary",
    },
    {
        "role": "valuation",
        "provider_id": 2,
        "source": "tushare",
        "version": "v1",
        "endpoint_id": "primary",
    },
]
PROVIDER_DIGEST = hashlib.sha256(
    json.dumps(PROVIDERS, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


OFFICIAL_JUNIT_FILES: dict[str, bytes] = {}


def _fake_github_run(repository: str, run_id: int) -> dict[str, Any]:
    assert repository == GITHUB_REPOSITORY
    assert run_id == GITHUB_RUN_ID
    return {
        "id": run_id,
        "head_sha": CANDIDATE,
        "name": validator.REQUIRED_GITHUB_WORKFLOW,
        "status": "completed",
        "conclusion": "success",
        "updated_at": "2026-09-24T23:58:00+00:00",
        "repository": {"full_name": repository},
    }


validator._load_github_run = _fake_github_run
validator._load_github_junit_artifacts = lambda _repository, _run_id, _candidate: dict(
    OFFICIAL_JUNIT_FILES
)


def test_github_token_is_not_forwarded_to_artifact_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str | None] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"{}"

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        assert timeout == 30
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://signed-storage.example/artifact.zip",
        )
        assert redirected is not None
        observed["authorization"] = redirected.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(validator, "_github_token", lambda: "secret-token")
    monkeypatch.setattr(validator.urllib.request, "urlopen", fake_urlopen)

    assert (
        validator._github_request_bytes(
            "https://api.github.com/repos/example/repo/actions/artifacts/1/zip",
            require_token=True,
            limit=100,
        )
        == b"{}"
    )
    assert observed["authorization"] is None


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _common(kind: str, now: datetime) -> dict[str, Any]:
    return {
        "schema": validator.REQUIRED_REPORT_SCHEMAS[kind],
        "kind": kind,
        "candidate_sha": CANDIDATE,
        "target_trade_date": TARGET_DATE,
        "universe_sha256": UNIVERSE,
        "provider_identities": PROVIDERS,
        "outcome": "success",
        "evidence_mode": validator.REQUIRED_EVIDENCE_MODES[kind],
        "started_at": (now - timedelta(minutes=10)).isoformat(),
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
    }


def _build_evidence(tmp_path: Path, now: datetime) -> tuple[Path, dict[str, Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    response_artifacts: list[dict[str, str]] = []
    for dataset, raw_unit, canonical_unit in (
        ("equity.quote.snapshot", "CNY/share", "CNY/share"),
        ("equity.valuation.fact", "CNY/10k", "CNY"),
    ):
        slug = dataset.replace(".", "-")
        response_path = tmp_path / f"{slug}-response.json"
        response_path.write_text('{"data":[{"ts_code":"000001.SZ"}]}', encoding="utf-8")
        receipt_path = tmp_path / f"{slug}-replay.json"
        receipt = {
            "schema": "release.real-provider-response-replay.v1",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "outcome": "success",
            "dataset": dataset,
            "raw_unit": raw_unit,
            "canonical_unit": canonical_unit,
            "source_observed_at": "2026-09-24T07:00:00+00:00",
            "sampled_assets": ASSET_CODES,
            "replay_cases": sorted(validator.REQUIRED_REPLAY_CASES),
            "response_body": {
                "path": response_path.name,
                "sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
            },
            "response_bodies": [
                {
                    "path": response_path.name,
                    "sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
                }
            ],
            "response_set_scope": "all_retained_responses_for_dataset",
        }
        receipt_digest = _write_json(receipt_path, receipt)
        response_artifacts.append({"path": receipt_path.name, "sha256": receipt_digest})
    replay = _common("real_response_unit_replay", now)
    replay.update(
        {
            "units_verified": True,
            "source_time_verified": True,
            "replay_case_count": 7,
            "response_artifacts": response_artifacts,
        }
    )
    capacity = _common("full_universe_capacity", now)
    capacity_receipt_path = tmp_path / "full-universe-capacity-receipt.json"
    capacity_receipt_digest = _write_json(
        capacity_receipt_path,
        {
            "schema": "release.full-universe-capacity-receipt.v1",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "outcome": "success",
            "measurement_source": "candidate_runtime_instrumentation",
            "asset_codes": ASSET_CODES,
            "measured_asset_count": len(ASSET_CODES),
            "started_at": (now - timedelta(minutes=8)).isoformat(),
            "finished_at": (now - timedelta(minutes=6)).isoformat(),
            "elapsed_seconds": 120.0,
            "provider_total_requests": 150,
            "provider_peak_requests_per_window": 50,
            "provider_request_limit_per_window": 100,
            "provider_window_seconds": 60.0,
            "task_deadline_seconds": 600.0,
            "database_peak_connections": 2,
            "database_connection_limit": 20,
            "max_lock_wait_seconds": 0.2,
            "lock_wait_limit_seconds": 5.0,
            "peak_memory_bytes": 268435456,
            "memory_limit_bytes": 1073741824,
        },
    )
    capacity.update(
        {
            "universe_count": len(ASSET_CODES),
            "measured_asset_count": len(ASSET_CODES),
            "asset_codes": ASSET_CODES,
            "provider_quota_within_limit": True,
            "task_deadline_within_limit": True,
            "database_budget_within_limit": True,
            "lock_budget_within_limit": True,
            "memory_budget_within_limit": True,
            "capacity_margin_ratio": 0.5,
            "measurement_artifact": {
                "path": capacity_receipt_path.name,
                "sha256": capacity_receipt_digest,
            },
        }
    )
    staging = _common("isolated_write_rehearsal", now)
    write_receipt = tmp_path / "staging-write-receipt.json"
    _write_json(
        write_receipt,
        {
            "schema": "release.isolated-write-receipt.v1",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "outcome": "success",
            "database_scope": "disposable",
            "written_rows": 100,
            "publication_verified": True,
            "readback_verified": True,
            "rollback_verified": True,
            "residual_rows": 0,
        },
    )
    staging.update(
        {
            "database_scope": "disposable",
            "written_rows": 100,
            "publication_verified": True,
            "rollback_verified": True,
            "residual_rows": 0,
            "write_artifacts": [
                {
                    "path": write_receipt.name,
                    "sha256": hashlib.sha256(write_receipt.read_bytes()).hexdigest(),
                }
            ],
        }
    )
    junit_artifacts: list[dict[str, str]] = []
    OFFICIAL_JUNIT_FILES.clear()
    for filename, selected_tests in (
        (
            "publication-postgres.xml",
            validator.REQUIRED_POSTGRESQL_TESTS[2:],
        ),
        (
            "backfill-control-plane-postgres.xml",
            validator.REQUIRED_POSTGRESQL_TESTS[:2],
        ),
    ):
        junit_path = tmp_path / filename
        junit_cases = "".join(
            f'<testcase classname="{test_id.rsplit("::", 1)[0]}" name="{test_id.rsplit("::", 1)[1]}"/>'
            for test_id in selected_tests
        )
        junit_path.write_text(
            f'<testsuite tests="{len(selected_tests)}" failures="0" errors="0" skipped="0" timestamp="'
            + (now - timedelta(minutes=2)).isoformat()
            + '">'
            + junit_cases
            + "</testsuite>",
            encoding="utf-8",
        )
        OFFICIAL_JUNIT_FILES[filename] = junit_path.read_bytes()
        junit_artifacts.append(
            {
                "path": junit_path.name,
                "sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
            }
        )
    regression = _common("candidate_regression_evidence", now)
    regression.update(
        {
            "postgresql_vendor_verified": True,
            "selected_by_candidate": True,
            "github_repository": GITHUB_REPOSITORY,
            "github_run_id": GITHUB_RUN_ID,
            "required_tests": list(validator.REQUIRED_POSTGRESQL_TESTS),
            "junit_artifacts": junit_artifacts,
        }
    )
    reports: dict[str, Path] = {}
    references: list[dict[str, str]] = []
    for kind, payload in (
        ("real_response_unit_replay", replay),
        ("full_universe_capacity", capacity),
        ("isolated_write_rehearsal", staging),
        ("candidate_regression_evidence", regression),
    ):
        path = tmp_path / f"{kind}.json"
        digest = _write_json(path, payload)
        reports[kind] = path
        references.append({"kind": kind, "path": path.name, "sha256": digest})
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"schema": "release.rehearsal-manifest.v1", "reports": references})
    return manifest, reports


def _validate(manifest: Path, now: datetime) -> dict[str, object]:
    return validator.validate_release_rehearsal(
        manifest_path=manifest,
        expected_candidate=CANDIDATE,
        expected_target_date=TARGET_DATE,
        expected_universe_sha256=UNIVERSE,
        expected_provider_identities_sha256=PROVIDER_DIGEST,
        expected_github_repository=GITHUB_REPOSITORY,
        expected_github_run_id=GITHUB_RUN_ID,
        max_age_hours=24,
        now=now,
    )


def _replace_report(manifest: Path, report_path: Path, payload: dict[str, Any]) -> None:
    digest = _write_json(report_path, payload)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    for reference in manifest_payload["reports"]:
        if reference["kind"] == payload["kind"]:
            reference["sha256"] = digest
    _write_json(manifest, manifest_payload)


def _replace_capacity_receipt(
    manifest: Path, capacity_report_path: Path, mutation: dict[str, Any]
) -> None:
    report = json.loads(capacity_report_path.read_text(encoding="utf-8"))
    receipt_path = capacity_report_path.parent / report["measurement_artifact"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(mutation)
    report["measurement_artifact"]["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, capacity_report_path, report)


def test_validator_accepts_complete_candidate_bound_evidence(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(tmp_path, now)

    result = _validate(manifest, now)

    assert result["outcome"] == "success"
    assert result["candidate_sha"] == CANDIDATE
    assert len(result["validated_reports"]) == 4


@pytest.mark.parametrize(
    ("kind", "mutation", "expected_code"),
    [
        ("real_response_unit_replay", {"evidence_mode": "mock"}, "REHEARSAL_EVIDENCE_MODE_INVALID"),
        (
            "real_response_unit_replay",
            {"response_artifacts": []},
            "REHEARSAL_REAL_RESPONSE_MISSING",
        ),
        ("real_response_unit_replay", {"outcome": "partial"}, "REHEARSAL_REPORT_NOT_SUCCESSFUL"),
        (
            "full_universe_capacity",
            {"measured_asset_count": 2},
            "REHEARSAL_CAPACITY_NOT_FULL_UNIVERSE",
        ),
        (
            "full_universe_capacity",
            {"universe_count": 1, "measured_asset_count": 1},
            "REHEARSAL_CAPACITY_UNIVERSE_INVALID",
        ),
        (
            "full_universe_capacity",
            {"measurement_artifact": None},
            "REHEARSAL_CAPACITY_MEASUREMENT_MISSING",
        ),
        (
            "full_universe_capacity",
            {"memory_budget_within_limit": False},
            "REHEARSAL_CAPACITY_DERIVATION_MISMATCH",
        ),
        (
            "full_universe_capacity",
            {"capacity_margin_ratio": 0.000001},
            "REHEARSAL_CAPACITY_MARGIN_MISMATCH",
        ),
        ("isolated_write_rehearsal", {"residual_rows": 1}, "REHEARSAL_ROLLBACK_RESIDUAL"),
        ("isolated_write_rehearsal", {"residual_rows": 0.0}, "REHEARSAL_ROLLBACK_RESIDUAL"),
        ("isolated_write_rehearsal", {"write_artifacts": []}, "REHEARSAL_WRITE_ARTIFACT_MISSING"),
        (
            "candidate_regression_evidence",
            {"postgresql_vendor_verified": False},
            "REHEARSAL_POSTGRESQL_UNVERIFIED",
        ),
        (
            "candidate_regression_evidence",
            {"required_tests": ["wrong.module::test_lock"]},
            "REHEARSAL_REQUIRED_TEST_SET_MISMATCH",
        ),
    ],
)
def test_validator_rejects_false_green_evidence(
    tmp_path: Path, kind: str, mutation: dict[str, Any], expected_code: str
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report = json.loads(reports[kind].read_text(encoding="utf-8"))
    report.update(mutation)
    _replace_report(manifest, reports[kind], report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            {"provider_peak_requests_per_window": 101},
            "REHEARSAL_CAPACITY_LIMIT_EXCEEDED",
        ),
        ({"elapsed_seconds": 125.0}, "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"),
        ({"peak_memory_bytes": 1073741824}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"database_peak_connections": 20}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"max_lock_wait_seconds": 5.0}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"measurement_source": "self_reported"}, "REHEARSAL_CAPACITY_RECEIPT_INVALID"),
        ({"asset_codes": ASSET_CODES[:-1]}, "REHEARSAL_CAPACITY_RECEIPT_UNIVERSE_MISMATCH"),
    ],
)
def test_validator_recomputes_capacity_from_bound_measurement_receipt(
    tmp_path: Path, mutation: dict[str, Any], expected_code: str
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    _replace_capacity_receipt(manifest, reports["full_universe_capacity"], mutation)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == expected_code


def test_validator_rejects_skipped_postgresql_junit(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    junit = tmp_path / "publication-postgres.xml"
    junit.write_text(
        '<testsuite tests="1" skipped="1" timestamp="'
        + now.isoformat()
        + '"><testcase classname="tests.pg" name="test_lock">'
        "<skipped/></testcase></testsuite>",
        encoding="utf-8",
    )
    report_path = reports["candidate_regression_evidence"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    OFFICIAL_JUNIT_FILES[junit.name] = junit.read_bytes()
    for artifact in report["junit_artifacts"]:
        if artifact["path"] == junit.name:
            artifact["sha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_JUNIT_NOT_GREEN"


def test_validator_rejects_github_run_for_another_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(tmp_path, now)
    foreign = _fake_github_run(GITHUB_REPOSITORY, GITHUB_RUN_ID)
    foreign["head_sha"] = "f" * 40
    monkeypatch.setattr(validator, "_load_github_run", lambda *_args: foreign)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_GITHUB_RUN_NOT_APPROVED"


def test_validator_rejects_locally_retagged_junit(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    junit = tmp_path / "publication-postgres.xml"
    junit.write_text(junit.read_text(encoding="utf-8") + "<!--retagged-->", encoding="utf-8")
    report_path = reports["candidate_regression_evidence"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for artifact in report["junit_artifacts"]:
        if artifact["path"] == junit.name:
            artifact["sha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_JUNIT_ARTIFACT_MISMATCH"


def test_validator_rejects_replay_sample_outside_frozen_universe(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_reference = report["response_artifacts"][0]
    receipt_path = tmp_path / receipt_reference["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sampled_assets"] = ["NOT_IN_UNIVERSE"]
    receipt_reference["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPLAY_SAMPLE_INVALID"


def test_validator_rejects_unverified_secondary_replay_response(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_reference = report["response_artifacts"][0]
    receipt_path = tmp_path / receipt_reference["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    missing = {"path": "missing-response.json", "sha256": "0" * 64}
    receipt["response_bodies"].append(missing)
    receipt_reference["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_ARTIFACT_UNREADABLE"


def test_validator_rejects_stale_and_candidate_mismatch(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(tmp_path, now - timedelta(days=2))
    with pytest.raises(validator.RehearsalValidationError) as stale:
        _validate(manifest, now)
    assert stale.value.code == "REHEARSAL_EVIDENCE_STALE"

    fresh_manifest, _reports = _build_evidence(tmp_path / "fresh", now)
    with pytest.raises(validator.RehearsalValidationError) as mismatch:
        validator.validate_release_rehearsal(
            manifest_path=fresh_manifest,
            expected_candidate="c" * 40,
            expected_target_date=TARGET_DATE,
            expected_universe_sha256=UNIVERSE,
            expected_provider_identities_sha256=PROVIDER_DIGEST,
            expected_github_repository=GITHUB_REPOSITORY,
            expected_github_run_id=GITHUB_RUN_ID,
            max_age_hours=24,
            now=now,
        )
    assert mismatch.value.code == "REHEARSAL_CANDIDATE_MISMATCH"
