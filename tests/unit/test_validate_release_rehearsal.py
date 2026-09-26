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
IMAGE_ID = "sha256:" + "f" * 64
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
POLICY_CONTENT = {
    "encoding": "publication-policy-v1",
    "dataset_key": "equity.valuation.fact",
    "contract_version": "1.0",
    "schema_version": "1.0",
    "policy_version": "production",
    "minimum_coverage_ratio": 0.95,
    "allow_partial": False,
    "conflict_action": "block",
    "required_evidence": ["source"],
    "retention_days": 30,
}
POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        POLICY_CONTENT, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
).hexdigest()
POLICY_EVIDENCE = {
    "content": POLICY_CONTENT,
    "content_sha256": POLICY_SHA256,
    "identity": f"p2:production:{POLICY_SHA256}",
}


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


def test_missing_github_token_blocks_artifact_download_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private CI artifacts must remain unavailable when no GitHub token is configured."""

    def forbidden_urlopen(_request: urllib.request.Request, _timeout: int) -> object:
        raise AssertionError("artifact download must not run without a GitHub token")

    monkeypatch.setattr(validator, "_github_token", lambda: "")
    monkeypatch.setattr(validator.urllib.request, "urlopen", forbidden_urlopen)

    with pytest.raises(
        validator.RehearsalValidationError, match="REHEARSAL_GITHUB_TOKEN_UNAVAILABLE"
    ):
        validator._github_request_bytes(
            "https://api.github.com/repos/example/repo/actions/runs/1/artifacts/1/zip",
            require_token=True,
            limit=100,
        )


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
        "provider_identities_sha256": PROVIDER_DIGEST,
        "outcome": "success",
        "candidate_source_attestation": "image_release_manifest",
        "candidate_image_id": IMAGE_ID,
        "evidence_mode": validator.REQUIRED_EVIDENCE_MODES[kind],
        "started_at": (now - timedelta(minutes=10)).isoformat(),
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
    }


def _build_evidence(tmp_path: Path, now: datetime) -> tuple[Path, dict[str, Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    unit_contract_path = tmp_path / "unit-contract.json"
    unit_contract_digest = _write_json(
        unit_contract_path,
        {
            "schema": "release.provider-unit-contract.v1",
            "candidate_sha": CANDIDATE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "source_reference": "unit-test-contract",
            "datasets": {
                "equity.quote.snapshot": [
                    {
                        "field": "close",
                        "raw_unit": "CNY_per_share",
                        "canonical_unit": "CNY_per_share",
                        "multiplier": 1.0,
                    },
                    {
                        "field": "vol",
                        "raw_unit": "lot",
                        "canonical_unit": "share",
                        "multiplier": 100.0,
                    },
                    {
                        "field": "amount",
                        "raw_unit": "thousand_CNY",
                        "canonical_unit": "CNY",
                        "multiplier": 1000.0,
                    },
                ],
                "equity.valuation.fact": [
                    {
                        "field": "total_mv",
                        "raw_unit": "万元",
                        "canonical_unit": "元",
                        "multiplier": 10000.0,
                    },
                    {
                        "field": "circ_mv",
                        "raw_unit": "万元",
                        "canonical_unit": "元",
                        "multiplier": 10000.0,
                    },
                ],
            },
        },
    )
    response_artifacts: list[dict[str, str]] = []
    capture_receipts: list[dict[str, object]] = []
    for dataset in ("equity.quote.snapshot", "equity.valuation.fact"):
        slug = dataset.replace(".", "-")
        response_path = tmp_path / f"{slug}-response.json"
        response_fields = (
            ["ts_code", "trade_date", "close", "vol", "amount"]
            if dataset == "equity.quote.snapshot"
            else ["ts_code", "trade_date", "total_mv", "circ_mv"]
        )
        response_values = (
            [TARGET_DATE.replace("-", ""), 10.0, 2.0, 3.0]
            if dataset == "equity.quote.snapshot"
            else [TARGET_DATE.replace("-", ""), 3.0, 2.0]
        )
        response_path.write_text(
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": response_fields,
                        "items": [[code, *response_values] for code in ASSET_CODES],
                    },
                }
            ),
            encoding="utf-8",
        )
        response_digest = hashlib.sha256(response_path.read_bytes()).hexdigest()
        if dataset == "equity.quote.snapshot":
            units = [
                {
                    "field": "close",
                    "raw": 10.0,
                    "canonical": 10.0,
                    "raw_unit": "CNY_per_share",
                    "canonical_unit": "CNY_per_share",
                    "multiplier": 1.0,
                },
                {
                    "field": "vol",
                    "raw": 2.0,
                    "canonical": 200.0,
                    "raw_unit": "lot",
                    "canonical_unit": "share",
                    "multiplier": 100.0,
                },
                {
                    "field": "amount",
                    "raw": 3.0,
                    "canonical": 3000.0,
                    "raw_unit": "thousand_CNY",
                    "canonical_unit": "CNY",
                    "multiplier": 1000.0,
                },
            ]
        else:
            units = [
                {
                    "field": "total_mv",
                    "raw": 3.0,
                    "canonical": 30000.0,
                    "raw_unit": "万元",
                    "canonical_unit": "元",
                    "multiplier": 10000.0,
                },
                {
                    "field": "circ_mv",
                    "raw": 2.0,
                    "canonical": 20000.0,
                    "raw_unit": "万元",
                    "canonical_unit": "元",
                    "multiplier": 10000.0,
                },
            ]
        role = "quote" if dataset == "equity.quote.snapshot" else "valuation"
        provider = next(item for item in PROVIDERS if item["role"] == role)
        response_reference = {
            "path": response_path.name,
            "sha256": response_digest,
            "dataset": dataset,
            "role": role,
            "provider_id": provider["provider_id"],
            "provider_source": provider["source"],
            "provider_version": provider["version"],
            "endpoint_id": provider["endpoint_id"],
            "operation": "daily" if role == "quote" else "daily_basic",
            "response_scope": ("full_market_trade_date"),
        }
        receipt_path = tmp_path / f"{slug}-replay.json"
        receipt = {
            "schema": "release.real-provider-response-replay.v2",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "candidate_image_id": IMAGE_ID,
            "candidate_source_attestation": "image_release_manifest",
            "outcome": "success",
            "dataset": dataset,
            "source_observed_at": "2026-09-24T07:00:00+00:00",
            "sampled_assets": ASSET_CODES,
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "valuation_missing_target_session_codes": [],
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            "observations": [
                {
                    "asset_code": code,
                    "source_observed_at": "2026-09-24T07:00:00+00:00",
                    "transport_received_at": "2026-09-24T23:55:00+00:00",
                    "normalization_completed_at": "2026-09-24T23:55:01+00:00",
                    "response_completed_at": "2026-09-24T23:55:01+00:00",
                    "body_sha256": response_digest,
                    "units": units,
                }
                for code in ASSET_CODES
            ],
            "replay_cases": sorted(validator.REQUIRED_REPLAY_CASES),
            "response_body": response_reference,
            "response_bodies": [response_reference],
            "response_set_scope": "all_retained_responses_for_dataset",
            "unit_contract_sha256": unit_contract_digest,
            "unit_contract": {
                "path": unit_contract_path.name,
                "sha256": unit_contract_digest,
            },
        }
        receipt_digest = _write_json(receipt_path, receipt)
        response_artifacts.append({"path": receipt_path.name, "sha256": receipt_digest})
        capture_receipts.append(
            {
                "body_sha256": response_digest,
                "response_artifact": {
                    "body_sha256": response_digest,
                    "dataset": dataset,
                    "candidate_sha": CANDIDATE,
                    "target_trade_date": TARGET_DATE,
                    "universe_sha256": UNIVERSE,
                    "provider_identities_sha256": PROVIDER_DIGEST,
                    "provider_id": provider["provider_id"],
                    "provider_source": provider["source"],
                    "endpoint_id": provider["endpoint_id"],
                    "sample_codes": ASSET_CODES,
                },
            }
        )
    probe_path = tmp_path / "probe-capture.json"
    probe_digest = _write_json(
        probe_path,
        {
            "schema": "market.provider-rehearsal.v1",
            "outcome": "success",
            "mode": "read_only_live_provider",
            "database_read_only": True,
            "candidate_sha": CANDIDATE,
            "candidate_image_id": IMAGE_ID,
            "candidate_source_attestation": "image_release_manifest",
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "provider_identities": PROVIDERS,
            "asset_codes": ASSET_CODES,
            "sample": ASSET_CODES,
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "valuation_missing_target_session_codes": [],
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            "probes": [
                {
                    "dataset": dataset,
                    "outcome": "success",
                    "receipt_indexes": [index],
                }
                for index, dataset in enumerate(("equity.quote.snapshot", "equity.valuation.fact"))
            ],
            "transport": {"receipts": capture_receipts},
        },
    )
    replay = _common("real_response_unit_replay", now)
    replay.update(
        {
            "units_verified": True,
            "source_time_verified": True,
            "replay_case_count": 7,
            "response_artifacts": response_artifacts,
            "probe_sha256": probe_digest,
            "probe_capture": {"path": probe_path.name, "sha256": probe_digest},
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "valuation_missing_target_session_codes": [],
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
        }
    )
    capacity = _common("full_universe_capacity", now)
    capacity.pop("provider_identities")
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
            "measurement_scope": "production_full_active_valuation_and_quote_dispatch",
            "candidate_source_attestation": "image_release_manifest",
            "candidate_image_id": IMAGE_ID,
            "asset_codes": ASSET_CODES,
            "requested_asset_count": len(ASSET_CODES),
            "registered_asset_count": len(ASSET_CODES),
            "measured_asset_count": len(ASSET_CODES),
            "eligible_asset_count": len(ASSET_CODES),
            "eligible_asset_codes": ASSET_CODES,
            "excluded_asset_count": 0,
            "excluded_asset_codes": [],
            "valuation_missing_target_session_codes": [],
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            "valuation_coverage_ratio": 1.0,
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "quote_fact_count": len(ASSET_CODES),
            "valuation_fact_count": len(ASSET_CODES),
            "quote_coverage": {
                "requested_count": len(ASSET_CODES),
                "returned_count": len(ASSET_CODES),
                "target_session_count": len(ASSET_CODES),
                "missing_target_session_count": 0,
                "missing_target_session_codes": [],
                "extra_count": 0,
                "duplicate_count": 0,
            },
            "valuation_coverage": {
                "requested_count": len(ASSET_CODES),
                "returned_count": len(ASSET_CODES),
                "target_session_count": len(ASSET_CODES),
                "missing_target_session_count": 0,
                "missing_target_session_codes": [],
                "extra_count": 0,
                "duplicate_count": 0,
            },
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
            "database_connection_scope": "postgresql_cluster_all_databases",
            "database_peak_measurement_method": "sampled_pg_stat_activity_cluster_count",
            "sampling_interval_seconds": 0.05,
            "max_lock_wait_seconds": 0.2,
            "lock_wait_limit_seconds": 5.0,
            "peak_memory_bytes": 268435456,
            "memory_limit_bytes": 1073741824,
            "memory_peak_measurement_method": "linux_proc_status_vmhwm",
            "memory_limit_measurement_method": "cgroup_effective_or_host_physical",
            "minimum_capacity_margin_ratio": 0.15,
        },
    )
    capacity.update(
        {
            "universe_count": len(ASSET_CODES),
            "measured_asset_count": len(ASSET_CODES),
            "asset_codes": ASSET_CODES,
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "valuation_missing_target_session_codes": [],
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
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
    staging.pop("provider_identities")
    write_receipt = tmp_path / "staging-write-receipt.json"
    write_identity = {
        "candidate_image_id": IMAGE_ID,
        "publication_id": "123e4567-e89b-42d3-a456-426614174000",
        "publication_key": "current",
        "publication_hash": "1" * 64,
        "member_id": "123e4567-e89b-42d3-b456-426614174001",
        "member_fact_pk": "42",
        "member_fact_content_hash": "2" * 64,
        "database_identity_sha256": "3" * 64,
        "catalog_seed_sha256": "4" * 64,
        "payload_evidence_mode": "synthetic_isolated_writer_path",
        "synthetic_payload_sha256": "5" * 64,
    }
    _write_json(
        write_receipt,
        {
            "schema": "release.isolated-write-receipt.v1",
            "candidate_source_attestation": "image_release_manifest",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "outcome": "success",
            "database_scope": "disposable",
            "written_rows": 4,
            "publication_verified": True,
            "readback_verified": True,
            "tamper_guard_verified": True,
            "rollback_verified": True,
            "residual_rows": 0,
            **write_identity,
        },
    )
    staging.update(
        {
            "database_scope": "disposable",
            "written_rows": 4,
            "publication_verified": True,
            "readback_verified": True,
            "tamper_guard_verified": True,
            "rollback_verified": True,
            "residual_rows": 0,
            **write_identity,
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
    _write_json(
        manifest,
        {
            "schema": "release.rehearsal-manifest.v1",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "candidate_image_id": IMAGE_ID,
            "reports": references,
        },
    )
    return manifest, reports


def _validate(manifest: Path, now: datetime) -> dict[str, object]:
    return validator.validate_release_rehearsal(
        manifest_path=manifest,
        expected_candidate=CANDIDATE,
        expected_target_date=TARGET_DATE,
        expected_universe_sha256=UNIVERSE,
        expected_provider_identities_sha256=PROVIDER_DIGEST,
        expected_candidate_image_id=IMAGE_ID,
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


def _write_replay_receipt(
    manifest: Path,
    replay_report_path: Path,
    report: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
) -> None:
    report["response_artifacts"][0]["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, replay_report_path, report)


def test_validator_accepts_complete_candidate_bound_evidence(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(tmp_path, now)

    result = _validate(manifest, now)

    assert result["outcome"] == "success"
    assert result["candidate_sha"] == CANDIDATE
    assert len(result["validated_reports"]) == 4


@pytest.mark.parametrize("kind", validator.REQUIRED_REPORT_SCHEMAS)
def test_validator_requires_declared_provider_digest_on_every_report(
    tmp_path: Path,
    kind: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports[kind]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload.pop("provider_identities_sha256")
    _replace_report(manifest, report_path, payload)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_PROVIDER_MISMATCH"


@pytest.mark.parametrize(
    "kind",
    ("real_response_unit_replay", "candidate_regression_evidence"),
)
def test_validator_requires_full_provider_identities_for_source_evidence(
    tmp_path: Path,
    kind: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports[kind]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload.pop("provider_identities")
    _replace_report(manifest, report_path, payload)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_PROVIDER_IDENTITY_INVALID"


@pytest.mark.parametrize(
    ("field", "raw_unit", "canonical_unit"),
    [
        ("close", "元", "元"),
        ("vol", "手", "股"),
        ("amount", "千元", "元"),
    ],
)
def test_validator_rejects_legacy_chinese_quote_units_in_contract(
    tmp_path: Path,
    field: str,
    raw_unit: str,
    canonical_unit: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / report["response_artifacts"][0]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    contract_path = tmp_path / receipt["unit_contract"]["path"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    quote_fields = contract["datasets"]["equity.quote.snapshot"]
    unit = next(value for value in quote_fields if value["field"] == field)
    unit["raw_unit"] = raw_unit
    unit["canonical_unit"] = canonical_unit
    contract_digest = _write_json(contract_path, contract)
    receipt["unit_contract"]["sha256"] = contract_digest
    receipt["unit_contract_sha256"] = contract_digest
    _write_replay_receipt(manifest, report_path, report, receipt_path, receipt)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("equity.quote.snapshot", "close"),
        ("equity.quote.snapshot", "vol"),
        ("equity.quote.snapshot", "amount"),
        ("equity.valuation.fact", "total_mv"),
        ("equity.valuation.fact", "circ_mv"),
    ],
)
def test_validator_rejects_any_unit_contract_multiplier_drift(
    tmp_path: Path,
    dataset: str,
    field: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / report["response_artifacts"][0]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    contract_path = tmp_path / receipt["unit_contract"]["path"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    unit = next(value for value in contract["datasets"][dataset] if value["field"] == field)
    unit["multiplier"] *= 1 + 1e-10
    contract_digest = _write_json(contract_path, contract)
    receipt["unit_contract"]["sha256"] = contract_digest
    receipt["unit_contract_sha256"] = contract_digest
    _write_replay_receipt(manifest, report_path, report, receipt_path, receipt)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID"


def test_validator_rejects_absolute_bundle_artifact_reference(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["reports"][0]["path"] = str(reports[payload["reports"][0]["kind"]].resolve())
    _write_json(manifest, payload)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_ARTIFACT_REFERENCE_INVALID"


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
        (
            "isolated_write_rehearsal",
            {"written_rows": 3},
            "REHEARSAL_WRITE_COUNT_INVALID",
        ),
        (
            "isolated_write_rehearsal",
            {"written_rows": 5},
            "REHEARSAL_WRITE_COUNT_INVALID",
        ),
        (
            "isolated_write_rehearsal",
            {"readback_verified": False},
            "REHEARSAL_WRITE_INCOMPLETE",
        ),
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
    ("defect", "expected_code"),
    [
        ("candidate", "REHEARSAL_REPLAY_PROBE_INVALID"),
        ("duplicate_index", "REHEARSAL_REPLAY_PROBE_INVALID"),
        ("body_hash", "REHEARSAL_REPLAY_PROBE_MISMATCH"),
        ("provider_context", "REHEARSAL_REPLAY_PROBE_INVALID"),
    ],
)
def test_validator_rejects_tampered_probe_capture(
    tmp_path: Path, defect: str, expected_code: str
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    probe_path = report_path.parent / report["probe_capture"]["path"]
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    if defect == "candidate":
        probe["candidate_sha"] = "c" * 40
    elif defect == "duplicate_index":
        probe["probes"][1]["receipt_indexes"] = [0]
    elif defect == "body_hash":
        replacement = "c" * 64
        probe["transport"]["receipts"][0]["body_sha256"] = replacement
        probe["transport"]["receipts"][0]["response_artifact"]["body_sha256"] = replacement
    else:
        probe["transport"]["receipts"][0]["response_artifact"]["provider_id"] = 999
    digest = _write_json(probe_path, probe)
    report["probe_sha256"] = digest
    report["probe_capture"]["sha256"] = digest
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize("defect", ["eligible_scope", "policy_snapshot"])
def test_validator_rejects_self_consistent_probe_scope_or_policy_tamper(
    tmp_path: Path, defect: str
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    probe_path = report_path.parent / report["probe_capture"]["path"]
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    if defect == "eligible_scope":
        moved = probe["eligible_asset_codes"].pop()
        probe["excluded_asset_codes"].append(moved)
        probe["eligible_asset_count"] = len(probe["eligible_asset_codes"])
        probe["excluded_asset_count"] = len(probe["excluded_asset_codes"])
    else:
        content = probe["valuation_policy_snapshot"]["content"]
        content["minimum_coverage_ratio"] = 0.5
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        probe["valuation_policy_snapshot"]["content_sha256"] = digest
        probe["valuation_policy_snapshot"]["identity"] = f"p2:production:{digest}"
        probe["valuation_policy_sha256"] = digest
        probe["valuation_policy_identity"] = f"p2:production:{digest}"
        probe["valuation_minimum_coverage_ratio"] = 0.5
    digest = _write_json(probe_path, probe)
    report["probe_sha256"] = digest
    report["probe_capture"]["sha256"] = digest
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPLAY_PROBE_INVALID"


def test_validator_rejects_false_readback_in_bound_write_receipt(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["isolated_write_rehearsal"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_path = report_path.parent / report["write_artifacts"][0]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["readback_verified"] = False
    report["write_artifacts"][0]["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_WRITE_RECEIPT_INCOMPLETE"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            {"provider_peak_requests_per_window": 101},
            "REHEARSAL_CAPACITY_LIMIT_EXCEEDED",
        ),
        (
            {"provider_peak_requests_per_window": 90},
            "REHEARSAL_CAPACITY_MARGIN_INSUFFICIENT",
        ),
        ({"elapsed_seconds": 125.0}, "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"),
        ({"peak_memory_bytes": 1073741824}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"database_peak_connections": 20}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"max_lock_wait_seconds": 5.0}, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED"),
        ({"measurement_source": "self_reported"}, "REHEARSAL_CAPACITY_RECEIPT_INVALID"),
        ({"asset_codes": ASSET_CODES[:-1]}, "REHEARSAL_CAPACITY_RECEIPT_UNIVERSE_MISMATCH"),
        ({"valuation_policy_sha256": "invalid"}, "REHEARSAL_CAPACITY_ELIGIBLE_SCOPE_INVALID"),
        (
            {
                "eligible_asset_codes": ASSET_CODES[:-1],
                "eligible_asset_count": len(ASSET_CODES) - 1,
                "excluded_asset_codes": [ASSET_CODES[-1]],
                "excluded_asset_count": 1,
                "valuation_missing_target_session_codes": [ASSET_CODES[-1]],
                "valuation_coverage_ratio": (len(ASSET_CODES) - 1) / len(ASSET_CODES),
            },
            "REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE",
        ),
        (
            {
                "quote_coverage": {
                    "requested_count": len(ASSET_CODES),
                    "returned_count": len(ASSET_CODES) - 1,
                    "target_session_count": len(ASSET_CODES) - 1,
                    "missing_target_session_count": 1,
                    "missing_target_session_codes": [ASSET_CODES[-1]],
                    "extra_count": 0,
                    "duplicate_count": 0,
                },
                "quote_fact_count": len(ASSET_CODES) - 1,
            },
            "REHEARSAL_CAPACITY_COVERAGE_INVALID",
        ),
        (
            {"valuation_coverage_ratio": 0.5},
            "REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE",
        ),
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


@pytest.mark.parametrize(
    "defect",
    [
        "missing_observations",
        "null_raw",
        "nan_canonical",
        "infinite_raw",
        "wrong_multiplier",
        "tiny_multiplier_drift",
        "opaque_unit",
        "duplicate_field",
        "missing_asset",
        "extra_asset",
        "unknown_body",
        "tampered_contract",
        "legacy_schema",
        "body_raw_drift",
        "body_scope_missing",
        "body_scope_duplicate",
        "body_wrong_date",
        "response_binding_dataset",
    ],
)
def test_validator_recomputes_every_replayed_unit_observation(tmp_path: Path, defect: str) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / report["response_artifacts"][0]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected_code = "REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID"
    if defect == "missing_observations":
        receipt.pop("observations")
    elif defect == "null_raw":
        receipt["observations"][0]["units"][1]["raw"] = None
    elif defect == "nan_canonical":
        receipt["observations"][0]["units"][1]["canonical"] = float("nan")
    elif defect == "infinite_raw":
        receipt["observations"][0]["units"][1]["raw"] = float("inf")
    elif defect == "wrong_multiplier":
        receipt["observations"][0]["units"][1]["multiplier"] = 1.0
    elif defect == "tiny_multiplier_drift":
        receipt["observations"][0]["units"][1]["multiplier"] = 100.00000001
    elif defect == "opaque_unit":
        receipt["observations"][0]["units"][1]["raw_unit"] = "opaque"
    elif defect == "duplicate_field":
        receipt["observations"][0]["units"][2]["field"] = "vol"
    elif defect == "missing_asset":
        receipt["observations"].pop()
    elif defect == "extra_asset":
        extra = dict(receipt["observations"][0])
        extra["asset_code"] = "999999.SZ"
        receipt["observations"].append(extra)
    elif defect == "unknown_body":
        receipt["observations"][0]["body_sha256"] = "f" * 64
    elif defect == "tampered_contract":
        expected_code = "REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID"
        contract_path = tmp_path / receipt["unit_contract"]["path"]
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["datasets"]["equity.quote.snapshot"][1]["raw_unit"] = "opaque"
        digest = _write_json(contract_path, contract)
        receipt["unit_contract"]["sha256"] = digest
        receipt["unit_contract_sha256"] = digest
    elif defect == "legacy_schema":
        expected_code = "REHEARSAL_REPLAY_RECEIPT_INVALID"
        receipt["schema"] = "release.real-provider-response-replay.v1"
    elif defect in {
        "body_raw_drift",
        "body_scope_missing",
        "body_scope_duplicate",
        "body_wrong_date",
    }:
        response_path = tmp_path / receipt["response_body"]["path"]
        response = json.loads(response_path.read_text(encoding="utf-8"))
        if defect == "body_raw_drift":
            response["data"]["items"][0][3] = 9.0
        elif defect == "body_scope_missing":
            expected_code = "REHEARSAL_REPLAY_RESPONSE_SET_INVALID"
            response["data"]["items"].pop()
        elif defect == "body_scope_duplicate":
            expected_code = "REHEARSAL_REPLAY_RESPONSE_SET_INVALID"
            response["data"]["items"].append(list(response["data"]["items"][0]))
        else:
            expected_code = "REHEARSAL_REPLAY_RESPONSE_SET_INVALID"
            response["data"]["items"][0][1] = "20260923"
        response_digest = _write_json(response_path, response)
        receipt["response_body"]["sha256"] = response_digest
        receipt["response_bodies"][0]["sha256"] = response_digest
        for observation in receipt["observations"]:
            observation["body_sha256"] = response_digest
    elif defect == "response_binding_dataset":
        expected_code = "REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID"
        receipt["response_body"]["dataset"] = "equity.valuation.fact"
        receipt["response_bodies"][0]["dataset"] = "equity.valuation.fact"
    _write_replay_receipt(manifest, report_path, report, receipt_path, receipt)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == expected_code


def test_validator_rejects_one_response_hash_claimed_by_both_datasets(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["real_response_unit_replay"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt_paths = [tmp_path / artifact["path"] for artifact in report["response_artifacts"]]
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in receipt_paths]
    union_path = tmp_path / "union-provider-response.json"
    union_digest = _write_json(
        union_path,
        {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "close",
                    "vol",
                    "amount",
                    "total_mv",
                    "circ_mv",
                ],
                "items": [[code, "20260924", 10.0, 2.0, 3.0, 3.0, 2.0] for code in ASSET_CODES],
            },
        },
    )
    for receipt, receipt_path, artifact in zip(
        receipts, receipt_paths, report["response_artifacts"], strict=True
    ):
        for reference in [receipt["response_body"], *receipt["response_bodies"]]:
            reference["path"] = union_path.name
            reference["sha256"] = union_digest
        for observation in receipt["observations"]:
            observation["body_sha256"] = union_digest
        artifact["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID"


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
    missing = dict(receipt["response_bodies"][0])
    missing.update({"path": "missing-response.json", "sha256": "0" * 64})
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
            expected_candidate_image_id=IMAGE_ID,
            expected_github_repository=GITHUB_REPOSITORY,
            expected_github_run_id=GITHUB_RUN_ID,
            max_age_hours=24,
            now=now,
        )
    assert mismatch.value.code == "REHEARSAL_MANIFEST_IDENTITY_MISMATCH"
