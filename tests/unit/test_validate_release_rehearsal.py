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

from shared.release_rehearsal_stage_environment import CATEGORIES as STAGE_ENVIRONMENT_CATEGORIES
from shared.release_rehearsal_stage_environment import (
    CONTRACT_STAGES as STAGE_ENVIRONMENT_CONTRACT_STAGES,
)
from shared.release_rehearsal_stage_environment import (
    load_docker_build_policy,
)


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_release_rehearsal.py"
    spec = importlib.util.spec_from_file_location("validate_release_rehearsal", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()
DOCKER_BUILD_POLICY = load_docker_build_policy(validator.RELEASE_POLICY_PATH)
CANDIDATE = "a" * 40
IMAGE_ID = "sha256:" + "f" * 64
ASSET_CODES = sorted(
    ["000001.SZ", "600000.SH", "830001.BJ"] + [f"{index:06d}.SZ" for index in range(2, 50)]
)
UNIVERSE = hashlib.sha256(
    json.dumps(ASSET_CODES, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _deterministic_sample(asset_codes: list[str]) -> list[str]:
    """Mirror the governed provider sample over a larger frozen universe."""

    ranked = sorted(asset_codes, key=lambda code: hashlib.sha256(code.encode()).hexdigest())
    groups: dict[str, str] = {}
    for code in ranked:
        groups.setdefault(code.rsplit(".", 1)[-1], code)
    selected = set(groups.values())
    for code in ranked:
        if len(selected) >= min(50, len(asset_codes)):
            break
        selected.add(code)
    return sorted(selected)


SAMPLE_CODES = _deterministic_sample(ASSET_CODES)
TARGET_DATE = "2026-09-24"
GITHUB_REPOSITORY = "guiyinan/agomTradePro"
GITHUB_RUN_ID = 123456
FINANCIAL_SOURCE_TIME_CONTRACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "governance"
        / "financial_source_time_match_contracts.json"
    ).read_text(encoding="utf-8")
)["contracts"][0]
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
    {
        "role": "akshare_financial_route:3",
        "provider_id": 3,
        "source": "akshare_financial",
        "version": (
            "akshare-financial-v1-requests-2.32.5-contract-"
            f"{FINANCIAL_SOURCE_TIME_CONTRACT['contract_sha256'][:12]}"
        ),
        "endpoint_id": "akshare-financial-test-route",
    },
]
PROVIDER_DIGEST = hashlib.sha256(
    json.dumps(PROVIDERS, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
POLICY_SETTINGS_RAW_SHA256 = hashlib.sha256(b"provider-settings-snapshot-test-bytes").hexdigest()
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


def _build_evidence(
    tmp_path: Path,
    now: datetime,
    *,
    out_of_target_response_code: str | None = None,
) -> tuple[Path, dict[str, Path]]:
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
        response_asset_codes = [
            *ASSET_CODES,
            *([out_of_target_response_code] if out_of_target_response_code is not None else []),
        ]
        response_path.write_text(
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": response_fields,
                        "items": [[code, *response_values] for code in response_asset_codes],
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
            "provider_format": "tushare_pro_table.v1",
            "response_asset_codes": response_asset_codes,
            "response_asset_count": len(response_asset_codes),
            "target_scope_asset_codes": ASSET_CODES,
            "target_scope_asset_count": len(ASSET_CODES),
            "out_of_target_asset_codes": (
                [] if out_of_target_response_code is None else [out_of_target_response_code]
            ),
            "out_of_target_asset_count": 0 if out_of_target_response_code is None else 1,
            "operation": "daily" if role == "quote" else "daily_basic",
            "response_scope": ("full_market_trade_date"),
        }
        receipt_path = tmp_path / f"{slug}-replay.json"
        receipt = {
            "schema": "release.real-provider-response-replay.v3",
            "candidate_sha": CANDIDATE,
            "target_trade_date": TARGET_DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDER_DIGEST,
            "candidate_image_id": IMAGE_ID,
            "candidate_source_attestation": "image_release_manifest",
            "outcome": "success",
            "dataset": dataset,
            "source_observed_at": "2026-09-24T07:00:00+00:00",
            "sampled_assets": SAMPLE_CODES,
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "excluded_asset_reasons": [],
            "valuation_missing_target_session_codes": [],
            "valuation_missing_target_session_reasons": [],
            "valuation_requested_count": len(ASSET_CODES),
            "valuation_returned_count": len(ASSET_CODES),
            "valuation_coverage_ratio": 1.0,
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            **(
                {
                    "requested": len(ASSET_CODES),
                    "succeeded": len(ASSET_CODES),
                    "failed": 0,
                }
                if dataset == "equity.valuation.fact"
                else {}
            ),
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
                for code in SAMPLE_CODES
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
                    "provider_format": "tushare_pro_table.v1",
                    "sample_codes": response_asset_codes,
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
            "sample": SAMPLE_CODES,
            "valuation_sample": SAMPLE_CODES,
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "excluded_asset_reasons": [],
            "valuation_missing_target_session_codes": [],
            "valuation_missing_target_session_reasons": [],
            "valuation_requested_count": len(ASSET_CODES),
            "valuation_returned_count": len(ASSET_CODES),
            "valuation_coverage_ratio": 1.0,
            "valuation_outcome": "success",
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            "probes": [
                {
                    "dataset": dataset,
                    "outcome": "success",
                    "receipt_indexes": [index],
                    **(
                        {
                            "requested": len(ASSET_CODES),
                            "succeeded": len(ASSET_CODES),
                            "failed": 0,
                            "valuation_missing_target_session_codes": [],
                            "valuation_missing_target_session_reasons": [],
                        }
                        if dataset == "equity.valuation.fact"
                        else {}
                    ),
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
            "excluded_asset_reasons": [],
            "valuation_missing_target_session_codes": [],
            "valuation_missing_target_session_reasons": [],
            "valuation_requested_count": len(ASSET_CODES),
            "valuation_returned_count": len(ASSET_CODES),
            "valuation_coverage_ratio": 1.0,
            "valuation_outcome": "success",
            "valuation_sample": SAMPLE_CODES,
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
            "measurement_scope": "production_target_date_eligible_valuation_and_quote_dispatch",
            "candidate_source_attestation": "image_release_manifest",
            "candidate_image_id": IMAGE_ID,
            "asset_codes": ASSET_CODES,
            "scope_policy": "exclude_only_verified_list_date_after_target",
            "candidate_active_asset_count": len(ASSET_CODES),
            "candidate_active_asset_codes_sha256": UNIVERSE,
            "target_requested_asset_count": len(ASSET_CODES),
            "target_requested_asset_codes_sha256": UNIVERSE,
            "excluded_not_yet_listed_count": 0,
            "excluded_not_yet_listed_evidence": [],
            "unknown_listing_date_count": 0,
            "unknown_listing_date_codes": [],
            "unknown_listing_date_codes_sha256": hashlib.sha256(b"[]").hexdigest(),
            "unknown_listing_date_codes_sample": [],
            "requested_asset_count": len(ASSET_CODES),
            "registered_asset_count": len(ASSET_CODES),
            "measured_asset_count": len(ASSET_CODES),
            "eligible_asset_count": len(ASSET_CODES),
            "eligible_asset_codes": ASSET_CODES,
            "excluded_asset_count": 0,
            "excluded_asset_codes": [],
            "excluded_asset_reasons": [],
            "quote_missing_target_session_codes": [],
            "quote_missing_target_session_reasons": [],
            "quote_requested_count": len(ASSET_CODES),
            "quote_returned_count": len(ASSET_CODES),
            "quote_fact_count": len(ASSET_CODES),
            "quote_coverage": {
                "requested_count": len(ASSET_CODES),
                "returned_count": len(ASSET_CODES),
                "target_session_count": len(ASSET_CODES),
                "missing_target_session_count": 0,
                "missing_target_session_codes": [],
                "extra_count": 0,
                "duplicate_count": 0,
            },
            "valuation_missing_target_session_codes": [],
            "valuation_missing_target_session_reasons": [],
            "valuation_requested_count": len(ASSET_CODES),
            "valuation_returned_count": len(ASSET_CODES),
            "valuation_outcome": "success",
            "valuation_minimum_coverage_ratio": POLICY_CONTENT["minimum_coverage_ratio"],
            "valuation_coverage_ratio": 1.0,
            "valuation_policy_identity": POLICY_EVIDENCE["identity"],
            "valuation_policy_sha256": POLICY_SHA256,
            "valuation_policy_snapshot": POLICY_EVIDENCE,
            "valuation_fact_count": len(ASSET_CODES),
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
            "scope_policy": "exclude_only_verified_list_date_after_target",
            "candidate_active_asset_count": len(ASSET_CODES),
            "candidate_active_asset_codes_sha256": UNIVERSE,
            "target_requested_asset_count": len(ASSET_CODES),
            "target_requested_asset_codes_sha256": UNIVERSE,
            "excluded_not_yet_listed_count": 0,
            "excluded_not_yet_listed_evidence": [],
            "unknown_listing_date_count": 0,
            "unknown_listing_date_codes": [],
            "unknown_listing_date_codes_sha256": hashlib.sha256(b"[]").hexdigest(),
            "unknown_listing_date_codes_sample": [],
            "eligible_asset_codes": ASSET_CODES,
            "eligible_asset_count": len(ASSET_CODES),
            "excluded_asset_codes": [],
            "excluded_asset_count": 0,
            "excluded_asset_reasons": [],
            "quote_missing_target_session_codes": [],
            "quote_missing_target_session_reasons": [],
            "quote_requested_count": len(ASSET_CODES),
            "quote_returned_count": len(ASSET_CODES),
            "quote_fact_count": len(ASSET_CODES),
            "quote_coverage": {
                "requested_count": len(ASSET_CODES),
                "returned_count": len(ASSET_CODES),
                "target_session_count": len(ASSET_CODES),
                "missing_target_session_count": 0,
                "missing_target_session_codes": [],
                "extra_count": 0,
                "duplicate_count": 0,
            },
            "valuation_missing_target_session_codes": [],
            "valuation_missing_target_session_reasons": [],
            "valuation_requested_count": len(ASSET_CODES),
            "valuation_returned_count": len(ASSET_CODES),
            "valuation_coverage_ratio": 1.0,
            "valuation_outcome": "success",
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
    publication_clock = (now - timedelta(seconds=30)).isoformat()
    prior_publication_clock = (now - timedelta(minutes=1)).isoformat()
    publication_clock_evidence = {
        "current_pointer_preserved_verified": True,
        "current_pointer_rollback_verified": True,
        "publication_graph_rollback_verified": True,
        "publication_clock_source": "database_clock_timestamp",
        "publication_clock_cutoff": publication_clock,
        "prior_current_published_at": prior_publication_clock,
        "publication_published_at": publication_clock,
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
            **publication_clock_evidence,
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
            **publication_clock_evidence,
            **write_identity,
            "write_artifacts": [
                {
                    "path": write_receipt.name,
                    "sha256": hashlib.sha256(write_receipt.read_bytes()).hexdigest(),
                }
            ],
        }
    )
    policy_settings = {
        "status": "active",
        "default_source": "tushare",
        "enable_failover": True,
        "failover_tolerance": 0.01,
    }
    settings_digest = validator._provider_settings_digest(policy_settings)
    settings_canonical_digest = settings_digest
    parity = _common("production_policy_parity", now)
    parity.update(
        {
            "provider_settings": policy_settings,
            "provider_settings_raw_file_sha256": POLICY_SETTINGS_RAW_SHA256,
            "provider_settings_canonical_payload_sha256": settings_canonical_digest,
            "preflight": {
                "name": "provider_policy_and_routes",
                "status": "pass",
                "blocked_codes": [],
                "detail": "",
                "evidence": {
                    "default_source": "tushare",
                    "enable_failover": True,
                    "failover_tolerance": 0.01,
                    "provider_settings_sha256": settings_digest,
                    "preferred_route": "tushare",
                    "probe_asset_count": 2,
                    "route_capabilities": [
                        {
                            "route": "tushare",
                            "source_type": "tushare",
                            "provider_id": 1,
                            "batch_preparation": True,
                            "audited_per_asset_fetch": False,
                            "provider_identity": True,
                        }
                    ],
                },
            },
        }
    )
    junit_artifacts: list[dict[str, str]] = []
    OFFICIAL_JUNIT_FILES.clear()
    required_tests = set(validator.REQUIRED_POSTGRESQL_TESTS)
    backfill_tests = {
        test_id
        for test_id in required_tests
        if "test_core_data_backfill_control_plane" in test_id
        or "test_current_publication_staging" in test_id
    }
    account_final_tests = {
        test_id
        for test_id in required_tests
        if "test_account_authority_final_revalidator_v3_postgres" in test_id
    }
    financial_capacity_tests = {
        test_id
        for test_id in required_tests
        if "test_publication_read_snapshot_postgres" in test_id and "financial_capacity" in test_id
    }
    financial_slice_tests = {
        test_id
        for test_id in required_tests
        if "test_akshare_financial_capture" in test_id
        or "test_financial_publication_capacity_workflow" in test_id
        or "test_financial_capacity_manifest" in test_id
    }
    publication_tests = required_tests.difference(
        backfill_tests,
        account_final_tests,
        financial_capacity_tests,
        financial_slice_tests,
    )
    junit_partitions = {
        "publication-postgres.xml": publication_tests,
        "backfill-control-plane-postgres.xml": backfill_tests,
        "account-authority-final-revalidation-postgres.xml": account_final_tests,
        "financial-capacity-postgres.xml": financial_capacity_tests,
        "financial-slice-sync-contracts.xml": financial_slice_tests,
    }
    assert all(junit_partitions.values())
    assert set().union(*junit_partitions.values()) == required_tests
    assert sum(len(tests) for tests in junit_partitions.values()) == len(required_tests)
    for filename, selected_test_set in junit_partitions.items():
        selected_tests = sorted(selected_test_set)
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
    financial_route_identity = PROVIDERS[2]
    financial_route_digest = hashlib.sha256(
        json.dumps(
            financial_route_identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    financial_junit_digest = next(
        item["sha256"]
        for item in junit_artifacts
        if item["path"] == "financial-slice-sync-contracts.xml"
    )
    financial_slice = _common("akshare_financial_slice", now)
    financial_slice.update(
        {
            "database": {
                "vendor": "postgresql",
                "scope": "disposable",
                "release_rehearsal_guard": True,
                "host": "agom-s6-postgres-run-01",
                "name": "agom_release_rehearsal_run01",
                "identity_sha256": hashlib.sha256(b"financial-database").hexdigest(),
            },
            "redis": {
                "scope": "disposable",
                "host": "agom-s6-redis-run-01",
                "expected_host": "agom-s6-redis-run-01",
                "ping_verified": True,
            },
            "selected_provider": {
                "provider_id": 3,
                "source_type": "akshare",
                "frozen_identity_role": financial_route_identity["role"],
                "frozen_identity_source": financial_route_identity["source"],
                "frozen_route_identity_sha256": financial_route_digest,
            },
            "financial_route": {
                "provider_route_identity": financial_route_identity,
                "provider_route_identity_sha256": financial_route_digest,
                "endpoint": FINANCIAL_SOURCE_TIME_CONTRACT["endpoint"],
                "source_time_contract": FINANCIAL_SOURCE_TIME_CONTRACT,
            },
            "egress_routes": [
                {
                    "dataset_key": dataset,
                    "rule_id": 100 + index,
                    "strategy": "direct",
                    "matched_domain": "datacenter.eastmoney.com",
                    "candidate_count": 1,
                    "deployment_region": "unknown",
                }
                for index, dataset in enumerate(
                    ("equity.financial.fact", "equity.financial.source-time"),
                    start=1,
                )
            ],
            "request_seed": {
                "asset_code": ASSET_CODES[0],
                "announcement_date": "2026-09-23",
                "basis": "legacy_available_at_date_untrusted",
                "source": "akshare",
                "provenance_is_seed_only": True,
                "legacy_fact_id_sha256": hashlib.sha256(b"legacy-fact").hexdigest(),
                "selection_sha256": hashlib.sha256(b"selection").hexdigest(),
            },
            "sync": {
                "requested": 1,
                "succeeded": 1,
                "failed": 0,
                "stored": 3,
                "planned_provider_requests": 2,
                "provider_request_count": 2,
                "atomic_fact_write_count": 1,
                "typed_fact_evidence_count": 3,
                "source_time_witness_count": 3,
            },
            "captures": [
                {
                    "dataset_key": dataset,
                    "capture_id": f"00000000-0000-4000-8000-{index:012d}",
                    "raw_audit_id": str(index),
                    "raw_audit_count": 1,
                    "raw_audit_status": "ok",
                    "raw_audit_provider_id": 3,
                    "body_sha256": body_digest,
                    "raw_audit_body_sha256": body_digest,
                    "body_size_bytes": 100 + index,
                    "typed_evidence_count": 3,
                    "witness_coverage_count": 3,
                }
                for index, dataset, body_digest in (
                    (1, "equity.financial.fact", hashlib.sha256(b"financial").hexdigest()),
                    (2, "equity.financial.source-time", hashlib.sha256(b"source-time").hexdigest()),
                )
            ],
            "failure_evidence": {
                "source": "candidate_regression_evidence",
                "failure_isolated_before_real_provider_egress": True,
                "zero_fact_write_test_cases": list(validator.FINANCIAL_ZERO_WRITE_PROOF_CASES),
                "junit_sha256": financial_junit_digest,
            },
        }
    )

    def stage_environment_payload(stages: tuple[str, ...], outcome: str) -> dict[str, Any]:
        observations: dict[str, Any] = {
            "observed_at": (now - timedelta(minutes=2)).isoformat(),
            "free_disk_bytes": 13 * 1024 * 1024 * 1024,
            "minimum_free_disk_bytes": 12 * 1024 * 1024 * 1024,
            "available_memory_bytes": 1024 * 1024 * 1024,
            "build_timeout_seconds": 3600,
            "stage_timeout_seconds": 3600,
            "provider_timeout_seconds": 1800,
            "task_deadline_seconds": 600,
            "lock_wait_limit_seconds": 5,
        }
        if "build_only" in stages:
            observations["docker_build_policy"] = DOCKER_BUILD_POLICY.to_dict()
        return {
            "schema": "release.s6-stage-environment-preflight.v1",
            "outcome": outcome,
            "observations": observations,
            "categories": list(STAGE_ENVIRONMENT_CATEGORIES),
            "stages": list(stages),
            "issues": [],
            "matrix": [
                {
                    "stage": stage,
                    "category": category,
                    "outcome": "pass",
                    "codes": [],
                }
                for stage in stages
                for category in STAGE_ENVIRONMENT_CATEGORIES
            ],
        }

    prebuild_path = tmp_path / "prebuild-stage-environment-preflight.json"
    prebuild_payload = stage_environment_payload(STAGE_ENVIRONMENT_CONTRACT_STAGES[:2], "pass")
    prebuild_payload["observations"]["free_disk_bytes"] = 25 * 1024 * 1024 * 1024
    prebuild_payload["observations"]["minimum_free_disk_bytes"] = 24 * 1024 * 1024 * 1024
    prebuild_digest = _write_json(
        prebuild_path,
        prebuild_payload,
    )
    stage_environment = _common("stage_environment_preflight", now)
    stage_environment.pop("provider_identities")
    stage_environment.update(
        stage_environment_payload(STAGE_ENVIRONMENT_CONTRACT_STAGES[2:], "success")
    )
    stage_environment["prebuild_report"] = {
        "path": prebuild_path.name,
        "sha256": prebuild_digest,
    }
    stage_environment["docker_builder"] = {
        "builder_mode": "legacy",
        "daemon_endpoint": "unix:///var/run/docker.sock",
        "client_version": "29.3.2",
        "server_version": "29.3.2",
        "legacy_mode_confirmed": True,
    }

    migration_pending = [
        "data_center.0090_financial_publication_capacity_workflow",
        "data_center.0091_financial_capacity_governance_record",
        "data_center.0092_financial_capacity_owner_approval_events",
        "data_center.0093_financial_capacity_slice_ledger",
    ]
    isolated_database_migrations = _common("isolated_database_migrations", now)
    isolated_database_migrations.pop("provider_identities")
    isolated_database_migrations.update(
        {
            "candidate_source_attestation": "image_release_manifest",
            "database_name": "agom_release_rehearsal_attempt_1234",
            "database_host": "agom-s6-postgres-attempt-1234",
            "database_address": "172.20.0.3",
            "database_port": 5432,
            "database_container_id": "e" * 64,
            "migration_command": ("python -m scripts.manage_vps_migrations migrate --noinput"),
            "migrator_database_role": "agomtradepro_migrator",
            "pending_before": migration_pending,
            "pending_after": [],
            "applied_migrations": migration_pending,
        }
    )

    reports: dict[str, Path] = {}
    references: list[dict[str, str]] = []
    for kind, payload in (
        ("real_response_unit_replay", replay),
        ("full_universe_capacity", capacity),
        ("production_policy_parity", parity),
        ("isolated_write_rehearsal", staging),
        ("akshare_financial_slice", financial_slice),
        ("stage_environment_preflight", stage_environment),
        ("isolated_database_migrations", isolated_database_migrations),
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
            "provider_settings_raw_file_sha256": POLICY_SETTINGS_RAW_SHA256,
            "provider_settings_canonical_payload_sha256": settings_canonical_digest,
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
        expected_provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
        expected_provider_settings_canonical_payload_sha256=(
            validator._provider_settings_digest(
                {
                    "status": "active",
                    "default_source": "tushare",
                    "enable_failover": True,
                    "failover_tolerance": 0.01,
                }
            )
        ),
        expected_candidate_image_id=IMAGE_ID,
        expected_github_repository=GITHUB_REPOSITORY,
        expected_github_run_id=GITHUB_RUN_ID,
        max_age_hours=24,
        now=now,
    )


def test_legacy_policy_evidence_cannot_authorize_partial_release() -> None:
    """The validator preserves whether canonical policy evidence is versioned."""

    content = {**POLICY_CONTENT, "policy_version": "legacy", "allow_partial": True}
    digest = hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    evidence = validator._validated_policy_evidence(
        {
            "content": content,
            "content_sha256": digest,
            "identity": "1.0:1.0",
        }
    )

    assert evidence.allow_partial is True
    assert evidence.uses_versioned_evidence is False


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
    manifest, reports = _build_evidence(tmp_path, now)

    replay = json.loads(reports["real_response_unit_replay"].read_text(encoding="utf-8"))
    probe_path = tmp_path / replay["probe_capture"]["path"]
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    quote_receipt_path = tmp_path / replay["response_artifacts"][0]["path"]
    quote_receipt = json.loads(quote_receipt_path.read_text(encoding="utf-8"))
    quote_body_path = tmp_path / quote_receipt["response_body"]["path"]
    quote_body = json.loads(quote_body_path.read_text(encoding="utf-8"))

    assert len(probe["asset_codes"]) == 51
    assert len(probe["sample"]) == 50
    assert probe["transport"]["receipts"][0]["response_artifact"]["sample_codes"] == ASSET_CODES
    assert len(quote_body["data"]["items"]) == 51
    assert len(quote_receipt["observations"]) == 50

    result = _validate(manifest, now)

    assert result["outcome"] == "success"
    assert result["candidate_sha"] == CANDIDATE
    assert len(result["validated_reports"]) == 8


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            {"pending_after": ["data_center.0093_financial_capacity_slice_ledger"]},
            "REHEARSAL_DATABASE_MIGRATION_PENDING_INVALID",
        ),
        (
            {"applied_migrations": ["data_center.0090_financial_publication_capacity_workflow"]},
            "REHEARSAL_DATABASE_MIGRATION_PENDING_INVALID",
        ),
        (
            {"pending_before": ["data_center.0093_financial_capacity_slice_ledger"]},
            "REHEARSAL_DATABASE_MIGRATION_PENDING_INVALID",
        ),
        (
            {
                "pending_before": [
                    "data_center.0091_financial_capacity_governance_record",
                    "data_center.0090_financial_publication_capacity_workflow",
                    "data_center.0092_financial_capacity_owner_approval_events",
                    "data_center.0093_financial_capacity_slice_ledger",
                ]
            },
            "REHEARSAL_DATABASE_MIGRATION_PENDING_INVALID",
        ),
        (
            {"database_name": "production"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"candidate_image_id": "sha256:" + "0" * 64},
            "REHEARSAL_REPORT_IMAGE_MISMATCH",
        ),
        (
            {"database_host": "production-db.internal"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_address": "production-db.internal"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_address": "172.20.0.3/24"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_address": "postgresql://172.20.0.3/db"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_port": 0},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_port": True},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_container_id": "g" * 64},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"migration_command": "python manage.py migrate"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"migrator_database_role": "agomtradepro_owner"},
            "REHEARSAL_DATABASE_MIGRATION_IDENTITY_INVALID",
        ),
        (
            {"database_url": "postgresql://user:secret@production/db"},
            "REHEARSAL_DATABASE_MIGRATION_FIELDS_INVALID",
        ),
    ],
)
def test_validator_rejects_invalid_isolated_database_migration_report(
    tmp_path: Path,
    mutation: dict[str, object],
    expected_code: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["isolated_database_migrations"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(mutation)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == expected_code


def test_validator_requires_isolated_database_migration_report(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(tmp_path, now)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["reports"] = [
        item for item in payload["reports"] if item["kind"] != "isolated_database_migrations"
    ]
    _write_json(manifest, payload)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_REPORT_SET_INCOMPLETE"


def test_validator_accepts_noop_candidate_migration_evidence(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["isolated_database_migrations"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "database_address": "2001:db8::1",
            "pending_before": [],
            "pending_after": [],
            "applied_migrations": [],
        }
    )
    _replace_report(manifest, report_path, report)

    assert _validate(manifest, now)["outcome"] == "success"


def test_validator_rejects_nonpassing_stage_environment_matrix(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["stage_environment_preflight"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["matrix"][0]["outcome"] = "blocked"
    report["matrix"][0]["codes"] = ["REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_UNAVAILABLE"]
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_STAGE_ENVIRONMENT_MATRIX_INVALID"


def test_validator_rejects_incomplete_prebuild_environment_matrix(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["stage_environment_preflight"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    prebuild_path = tmp_path / report["prebuild_report"]["path"]
    prebuild = json.loads(prebuild_path.read_text(encoding="utf-8"))
    prebuild["matrix"].pop()
    report["prebuild_report"]["sha256"] = _write_json(prebuild_path, prebuild)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_STAGE_ENVIRONMENT_MATRIX_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_version", "29.3.0"),
        ("server_version", "29.3.1"),
        ("builder_mode", "buildkit"),
        ("daemon_endpoint", "tcp://docker:2375"),
        ("legacy_mode_confirmed", False),
    ],
)
def test_validator_rejects_unsafe_docker_builder_observation(
    tmp_path: Path, field: str, value: object
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["stage_environment_preflight"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["docker_builder"][field] = value
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_STAGE_ENVIRONMENT_DOCKER_BUILDER_INVALID"


def test_validator_rejects_prebuild_policy_that_does_not_match_governance(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    report_path = reports["stage_environment_preflight"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    prebuild_path = tmp_path / report["prebuild_report"]["path"]
    prebuild = json.loads(prebuild_path.read_text(encoding="utf-8"))
    prebuild["observations"]["docker_build_policy"]["minimum_server_version"] = "29.3.1"
    report["prebuild_report"]["sha256"] = _write_json(prebuild_path, prebuild)
    _replace_report(manifest, report_path, report)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_STAGE_ENVIRONMENT_DOCKER_BUILDER_INVALID"


def test_validator_recomputes_candidate_universe_digest_from_target_partition(
    tmp_path: Path,
) -> None:
    """A matching report/receipt lie cannot replace the reconstructable candidate scope."""

    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    capacity_path = reports["full_universe_capacity"]
    capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / capacity["measurement_artifact"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    false_digest = "f" * 64
    capacity["candidate_active_asset_codes_sha256"] = false_digest
    receipt["candidate_active_asset_codes_sha256"] = false_digest
    capacity["measurement_artifact"]["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, capacity_path, capacity)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_TARGET_SCOPE_INVALID"


def test_validator_recomputes_unknown_listing_date_digest_from_full_scope(
    tmp_path: Path,
) -> None:
    """The full unknown-date list must bind its count, sample and digest."""

    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    capacity_path = reports["full_universe_capacity"]
    capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / capacity["measurement_artifact"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutation = {
        "unknown_listing_date_count": 1,
        "unknown_listing_date_codes": [ASSET_CODES[0]],
        "unknown_listing_date_codes_sample": [ASSET_CODES[0]],
        "unknown_listing_date_codes_sha256": "f" * 64,
    }
    capacity.update(mutation)
    receipt.update(mutation)
    capacity["measurement_artifact"]["sha256"] = _write_json(receipt_path, receipt)
    _replace_report(manifest, capacity_path, capacity)

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_TARGET_SCOPE_INVALID"


def test_validator_accepts_evidence_backed_quote_scope_exclusion(tmp_path: Path) -> None:
    """A confirmed suspension may narrow quote scope without shrinking the universe."""
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    capacity_path = reports["full_universe_capacity"]
    capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / capacity["measurement_artifact"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    eligible = ASSET_CODES[:-1]
    excluded = ASSET_CODES[-1]
    reasons = [{"asset_code": excluded, "reason_code": "quote_full_day_suspension"}]
    quote_coverage = {
        "requested_count": len(eligible),
        "returned_count": len(eligible),
        "target_session_count": len(eligible),
        "missing_target_session_count": 0,
        "missing_target_session_codes": [],
        "extra_count": 0,
        "duplicate_count": 0,
    }
    receipt.update(
        {
            "eligible_asset_codes": eligible,
            "eligible_asset_count": len(eligible),
            "excluded_asset_codes": [excluded],
            "excluded_asset_count": 1,
            "excluded_asset_reasons": reasons,
            "quote_requested_count": len(eligible),
            "quote_returned_count": len(eligible),
            "quote_fact_count": len(eligible),
            "quote_coverage": quote_coverage,
        }
    )
    receipt_digest = _write_json(receipt_path, receipt)
    capacity.update(
        {
            "eligible_asset_codes": eligible,
            "eligible_asset_count": len(eligible),
            "excluded_asset_codes": [excluded],
            "excluded_asset_count": 1,
            "excluded_asset_reasons": reasons,
            "quote_requested_count": len(eligible),
            "quote_returned_count": len(eligible),
            "quote_fact_count": len(eligible),
            "quote_coverage": quote_coverage,
        }
    )
    capacity["measurement_artifact"]["sha256"] = receipt_digest
    _replace_report(manifest, capacity_path, capacity)

    result = _validate(manifest, now)

    assert result["outcome"] == "success"


def test_validator_rejects_unverified_quote_scope_exclusion_reason(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)

    _replace_capacity_receipt(
        manifest,
        reports["full_universe_capacity"],
        {
            "eligible_asset_codes": ASSET_CODES[:-1],
            "eligible_asset_count": len(ASSET_CODES) - 1,
            "excluded_asset_codes": [ASSET_CODES[-1]],
            "excluded_asset_count": 1,
            "excluded_asset_reasons": [
                {"asset_code": ASSET_CODES[-1], "reason_code": "quote_data_missing"}
            ],
            "quote_requested_count": len(ASSET_CODES) - 1,
            "quote_returned_count": len(ASSET_CODES) - 1,
            "quote_fact_count": len(ASSET_CODES) - 1,
            "quote_coverage": {
                "requested_count": len(ASSET_CODES) - 1,
                "returned_count": len(ASSET_CODES) - 1,
                "target_session_count": len(ASSET_CODES) - 1,
                "missing_target_session_count": 0,
                "missing_target_session_codes": [],
                "extra_count": 0,
                "duplicate_count": 0,
            },
        },
    )

    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        _validate(manifest, now)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE"


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
    (
        "real_response_unit_replay",
        "production_policy_parity",
        "candidate_regression_evidence",
    ),
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
        (
            "production_policy_parity",
            {"provider_settings": None},
            "REHEARSAL_POLICY_SETTINGS_INVALID",
        ),
        (
            "production_policy_parity",
            {"provider_settings_canonical_payload_sha256": "0" * 64},
            "REHEARSAL_POLICY_SETTINGS_MISMATCH",
        ),
        (
            "production_policy_parity",
            {
                "preflight": {
                    "name": "provider_policy_and_routes",
                    "status": "blocked",
                    "blocked_codes": ["MODEL_MARKET_BULK_PREPARATION_REQUIRED"],
                    "detail": "x",
                    "evidence": {},
                }
            },
            "REHEARSAL_POLICY_PARITY_NOT_PASS",
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
        (
            "isolated_write_rehearsal",
            {"current_pointer_preserved_verified": False},
            "REHEARSAL_WRITE_POINTER_NOT_PRESERVED",
        ),
        (
            "isolated_write_rehearsal",
            {"publication_published_at": "2026-09-24T23:59:00+00:00"},
            "REHEARSAL_WRITE_PUBLICATION_CLOCK_MISMATCH",
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


def test_retained_full_market_response_scope_can_include_provider_extras() -> None:
    """Raw full-market responses may include canonical codes outside the frozen target scope."""

    registered_assets = ["000001.SZ", "600000.SH", "830001.BJ"]
    probe_sample = ["000001.SZ"]

    assert not set(registered_assets).issubset(probe_sample)
    assert validator._provider_response_codes_are_well_formed(registered_assets)
    assert validator._provider_response_codes_are_well_formed(
        ["000001.SZ", "999999.SH"],
    )
    assert not validator._provider_response_codes_are_well_formed(
        ["600000.SH", "000001.SZ"],
    )
    assert not validator._provider_response_codes_are_well_formed(
        ["000001.SZ", "000001.SZ"],
    )
    assert not validator._provider_response_codes_are_well_formed(
        ["000001.SZ", 600000],
    )
    assert not validator._provider_response_codes_are_well_formed(["NOT_A_SECURITY"])


def test_validator_accepts_classified_provider_extras_without_expanding_publication_scope(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, _reports = _build_evidence(
        tmp_path,
        now,
        out_of_target_response_code="999999.SH",
    )

    _validate(manifest, now)


def test_source_observation_uses_per_asset_response_time_before_receipt_fallback() -> None:
    """Tencent row timestamps may differ while Tushare keeps one dataset-level time."""

    source_observed = datetime(2026, 9, 24, 8, 14, 24, tzinfo=UTC)

    assert validator._source_observation_matches_response(
        source_observed,
        response_observed_at="2026-09-24T16:14:24+08:00",
        receipt_observed_at="2026-09-24T08:15:00+00:00",
    )
    assert validator._source_observation_matches_response(
        source_observed,
        response_observed_at=None,
        receipt_observed_at="2026-09-24T08:14:24+00:00",
    )
    assert not validator._source_observation_matches_response(
        source_observed,
        response_observed_at="2026-09-24T16:14:25+08:00",
        receipt_observed_at="2026-09-24T08:14:24+00:00",
    )


def test_unit_observations_accept_distinct_per_asset_response_times() -> None:
    """A batch receipt keeps its scalar time while each Tencent row keeps its own time."""

    codes = ["000001.SZ", "600000.SH"]
    observed_at = ["2026-09-24T16:14:24+08:00", "2026-09-24T16:14:25+08:00"]
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
    receipt = {
        "source_observed_at": observed_at[0],
        "observations": [
            {
                "asset_code": code,
                "source_observed_at": source_time,
                "transport_received_at": "2026-09-24T08:15:00+00:00",
                "normalization_completed_at": "2026-09-24T08:15:01+00:00",
                "response_completed_at": "2026-09-24T08:15:01+00:00",
                "body_sha256": "response-body",
                "units": units,
            }
            for code, source_time in zip(codes, observed_at, strict=True)
        ],
    }
    response_rows = {
        "response-body": [
            {
                "ts_code": code,
                "trade_date": "20260924",
                "observed_at": source_time,
                "total_mv": 3.0,
                "circ_mv": 2.0,
            }
            for code, source_time in zip(codes, observed_at, strict=True)
        ]
    }

    validator._validate_unit_observations(
        receipt,
        dataset="equity.valuation.fact",
        expected_sample=codes,
        expected_date=TARGET_DATE,
        response_rows_by_hash=response_rows,
        expected_fields=validator.REQUIRED_REPLAY_UNIT_CONTRACTS["equity.valuation.fact"],
    )

    receipt["observations"][1]["source_observed_at"] = observed_at[0]
    with pytest.raises(validator.RehearsalValidationError) as exc_info:
        validator._validate_unit_observations(
            receipt,
            dataset="equity.valuation.fact",
            expected_sample=codes,
            expected_date=TARGET_DATE,
            response_rows_by_hash=response_rows,
            expected_fields=validator.REQUIRED_REPLAY_UNIT_CONTRACTS["equity.valuation.fact"],
        )

    assert exc_info.value.code == "REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID"


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
                "excluded_asset_reasons": [
                    {
                        "asset_code": ASSET_CODES[-1],
                        "reason_code": "quote_full_day_suspension",
                    }
                ],
                "quote_requested_count": len(ASSET_CODES) - 1,
                "quote_returned_count": len(ASSET_CODES) - 1,
                "quote_fact_count": len(ASSET_CODES) - 1,
                "quote_coverage": {
                    "requested_count": len(ASSET_CODES) - 1,
                    "returned_count": len(ASSET_CODES) - 1,
                    "target_session_count": len(ASSET_CODES) - 1,
                    "missing_target_session_count": 0,
                    "missing_target_session_codes": [],
                    "extra_count": 0,
                    "duplicate_count": 0,
                },
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
            expected_code = "REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID"
            response["data"]["items"].pop()
        elif defect == "body_scope_duplicate":
            expected_code = "REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID"
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
            expected_provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            expected_provider_settings_canonical_payload_sha256=(
                validator._provider_settings_digest(
                    {
                        "status": "active",
                        "default_source": "tushare",
                        "enable_failover": True,
                        "failover_tolerance": 0.01,
                    }
                )
            ),
            expected_candidate_image_id=IMAGE_ID,
            expected_github_repository=GITHUB_REPOSITORY,
            expected_github_run_id=GITHUB_RUN_ID,
            max_age_hours=24,
            now=now,
        )
    assert mismatch.value.code == "REHEARSAL_MANIFEST_IDENTITY_MISMATCH"


def test_self_consistent_policy_report_must_match_external_expected_hashes(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    parity_path = reports["production_policy_parity"]
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    replacement_settings = {
        "status": "active",
        "default_source": "tushare",
        "enable_failover": False,
        "failover_tolerance": 0.01,
    }
    replacement_canonical = validator._provider_settings_digest(replacement_settings)
    parity["provider_settings"] = replacement_settings
    parity["provider_settings_raw_file_sha256"] = hashlib.sha256(
        b"different-but-valid-settings-snapshot"
    ).hexdigest()
    parity["provider_settings_canonical_payload_sha256"] = replacement_canonical
    parity["preflight"]["evidence"]["provider_settings_sha256"] = replacement_canonical
    _replace_report(manifest, parity_path, parity)

    with pytest.raises(validator.RehearsalValidationError) as mismatch:
        _validate(manifest, now)

    assert mismatch.value.code == "REHEARSAL_POLICY_SETTINGS_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("provider_id", 999, "REHEARSAL_PROVIDER_MISMATCH"),
        ("source_type", "unknown", "REHEARSAL_PROVIDER_MISMATCH"),
        ("provider_id", None, "REHEARSAL_POLICY_PARITY_INVALID"),
    ),
)
def test_policy_route_must_match_frozen_provider_identity(
    tmp_path: Path,
    field: str,
    value: object,
    expected_code: str,
) -> None:
    now = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    manifest, reports = _build_evidence(tmp_path, now)
    parity_path = reports["production_policy_parity"]
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    parity["preflight"]["evidence"]["route_capabilities"][0][field] = value
    _replace_report(manifest, parity_path, parity)

    with pytest.raises(validator.RehearsalValidationError) as mismatch:
        _validate(manifest, now)

    assert mismatch.value.code == expected_code


def test_provider_identity_validator_accepts_bounded_failover_routes() -> None:
    identities = [
        *PROVIDERS,
        {
            "role": "model_market_route:31",
            "provider_id": 31,
            "source": "tencent",
            "version": "requests-test",
            "endpoint_id": "provider-config-failover",
        },
    ]

    digest = validator._validate_provider_identities(identities)

    assert (
        digest
        == hashlib.sha256(
            json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_provider_identity_validator_rejects_unbound_route_role() -> None:
    identities = [
        *PROVIDERS,
        {
            "role": "model_market_route:99",
            "provider_id": 31,
            "source": "tencent",
            "version": "requests-test",
            "endpoint_id": "provider-config-failover",
        },
    ]

    with pytest.raises(validator.RehearsalValidationError) as invalid:
        validator._validate_provider_identities(identities)

    assert invalid.value.code == "REHEARSAL_PROVIDER_IDENTITY_INVALID"
