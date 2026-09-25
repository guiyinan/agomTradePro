#!/usr/bin/env python
"""Fail-closed validation for candidate-bound production rehearsal evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast
from zoneinfo import ZoneInfo

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
REQUIRED_REPORT_SCHEMAS = {
    "real_response_unit_replay": "release.real-response-unit-replay.v1",
    "full_universe_capacity": "release.full-universe-capacity.v1",
    "isolated_write_rehearsal": "release.isolated-write-rehearsal.v1",
    "candidate_regression_evidence": "release.candidate-regression-evidence.v1",
}
REQUIRED_EVIDENCE_MODES = {
    "real_response_unit_replay": "real_provider",
    "full_universe_capacity": "measured_full_universe",
    "isolated_write_rehearsal": "isolated_postgresql",
    "candidate_regression_evidence": "candidate_ci",
}
REQUIRED_POSTGRESQL_TESTS = (
    "tests.component.data_center.test_core_data_backfill_control_plane::test_postgresql_backfill_first_run_and_same_parameter_retry_are_idempotent",
    "tests.component.data_center.test_core_data_backfill_control_plane::test_postgresql_backfill_provider_domain_failure_persists_partial_outcome",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_market_rehearsal_database_enforces_read_only_on_provider_write",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_outer_read_only_snapshot_keeps_gate_and_rows_consistent_after_concurrent_commit",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_read_committed_locks_remain_until_outer_unit_of_work_ends",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_read_committed_locks_dataset_contract_insert_until_outer_unit_of_work_ends",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_read_committed_locks_asset_master_insert_until_outer_unit_of_work_ends",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_read_committed_locks_asset_alias_insert_until_outer_unit_of_work_ends",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_repeatable_read_reuses_snapshot_without_share_table_locks",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_nested_read_only_read_committed_fails_closed_without_poisoning_parent",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_versioned_publish_locks_facts_and_commits_complete_members_atomically",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_forged_frozen_provenance_with_real_row_digest_never_replaces_current",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_postgres_refetch_retains_frozen_publication_and_excludes_parallel_writer",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_postgres_fact_refresh_honors_stricter_lock_timeout_and_rolls_back",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_postgres_revision_migration_preserves_rows_and_refuses_lossy_downgrade",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_postgres_financial_revision_preserves_frozen_rows_and_past_knowledge",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_financial_repository_round_trip_and_replay_count_on_postgresql",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_repository_float_ties_match_direct_postgresql_writer[positive_12_03125]",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_repository_float_ties_match_direct_postgresql_writer[negative_12_03125]",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_repository_float_ties_match_direct_postgresql_writer[positive_12_34505]",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_repository_float_ties_match_direct_postgresql_writer[positive_12_34525]",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_repository_float_ties_match_direct_postgresql_writer[positive_12_34535]",
    "tests.component.data_center.test_financial_fact_repository_postgres_provenance::test_financial_repository_stale_witness_rolls_back_postgresql_batch",
)
REQUIRED_REPLAY_CASES = {
    "valid",
    "missing",
    "truncated",
    "stale",
    "duplicate",
    "unit_error",
    "subsequent_fact_update",
}
REQUIRED_GITHUB_WORKFLOW = "Publication PostgreSQL contracts"
REQUIRED_GITHUB_ARTIFACT = "publication-postgres-evidence"
REQUIRED_JUNIT_FILES = {
    "publication-postgres.xml",
    "backfill-control-plane-postgres.xml",
}


class RehearsalValidationError(ValueError):
    """Stable, safe release-rehearsal validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> NoReturn:
    raise RehearsalValidationError(code)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload: object = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail(code)
    if not raw or not isinstance(payload, dict):
        _fail(code)
    return cast(dict[str, Any], payload)


def _sha256(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        _fail("REHEARSAL_ARTIFACT_UNREADABLE")
    if not raw:
        _fail("REHEARSAL_ARTIFACT_EMPTY")
    return hashlib.sha256(raw).hexdigest()


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _github_request_bytes(url: str, *, require_token: bool, limit: int) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AgomTradePro-release-rehearsal-validator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token()
    if require_token and not token:
        _fail("REHEARSAL_GITHUB_TOKEN_UNAVAILABLE")
    request = urllib.request.Request(url, headers=headers)
    if token:
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw: object = response.read(limit + 1)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        _fail("REHEARSAL_GITHUB_ATTESTATION_UNAVAILABLE")
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        _fail("REHEARSAL_GITHUB_ATTESTATION_INVALID")
    return raw


def _load_github_json(url: str) -> dict[str, Any]:
    raw = _github_request_bytes(url, require_token=False, limit=1_048_576)
    try:
        payload: object = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        _fail("REHEARSAL_GITHUB_ATTESTATION_INVALID")
    if not isinstance(payload, dict):
        _fail("REHEARSAL_GITHUB_ATTESTATION_INVALID")
    return cast(dict[str, Any], payload)


def _load_github_run(repository: str, run_id: int) -> dict[str, Any]:
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        _fail("REHEARSAL_GITHUB_REPOSITORY_INVALID")
    if isinstance(run_id, bool) or run_id <= 0:
        _fail("REHEARSAL_GITHUB_RUN_INVALID")
    return _load_github_json(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}")


def _load_github_junit_artifacts(
    repository: str, run_id: int, expected_candidate: str
) -> dict[str, bytes]:
    listing = _load_github_json(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts"
    )
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("name") == REQUIRED_GITHUB_ARTIFACT
        and item.get("expired") is False
    ]
    if len(matches) != 1:
        _fail("REHEARSAL_GITHUB_ARTIFACT_MISSING")
    artifact = cast(dict[str, Any], matches[0])
    workflow_run = artifact.get("workflow_run")
    if (
        not isinstance(workflow_run, dict)
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != expected_candidate
    ):
        _fail("REHEARSAL_GITHUB_ARTIFACT_CANDIDATE_MISMATCH")
    archive_url = artifact.get("archive_download_url")
    if not isinstance(archive_url, str) or not archive_url.startswith("https://api.github.com/"):
        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
    archive = _github_request_bytes(archive_url, require_token=True, limit=10_485_760)
    expected_digest = artifact.get("digest")
    if (
        not isinstance(expected_digest, str)
        or expected_digest != f"sha256:{hashlib.sha256(archive).hexdigest()}"
    ):
        _fail("REHEARSAL_GITHUB_ARTIFACT_DIGEST_MISMATCH")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files: dict[str, bytes] = {}
            for member in bundle.infolist():
                name = Path(member.filename).name
                if name in REQUIRED_JUNIT_FILES:
                    if name in files or member.file_size > 5_242_880:
                        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
                    files[name] = bundle.read(member)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
    if set(files) != REQUIRED_JUNIT_FILES:
        _fail("REHEARSAL_GITHUB_ARTIFACT_INCOMPLETE")
    return files


def _require_string(payload: dict[str, Any], key: str, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail(code)
    return value


def _require_true(payload: dict[str, Any], key: str, code: str) -> None:
    if payload.get(key) is not True:
        _fail(code)


def _require_positive_int(payload: dict[str, Any], key: str, code: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(code)
    return value


def _parse_datetime(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(code)
    if parsed.utcoffset() is None:
        _fail(code)
    return parsed.astimezone(UTC)


def _validate_provider_identities(value: object) -> str:
    if not isinstance(value, list) or not value:
        _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    normalized: list[dict[str, object]] = []
    roles: set[str] = set()
    identities: set[tuple[object, ...]] = set()
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        identity_item = cast(dict[str, object], item)
        role = identity_item.get("role")
        provider_id = identity_item.get("provider_id")
        source = identity_item.get("source")
        version = identity_item.get("version")
        endpoint_id = identity_item.get("endpoint_id")
        if (
            not isinstance(role, str)
            or not role.strip()
            or isinstance(provider_id, bool)
            or not isinstance(provider_id, int)
            or provider_id <= 0
            or not isinstance(source, str)
            or not source.strip()
            or not isinstance(version, str)
            or not version.strip()
            or not isinstance(endpoint_id, str)
            or not endpoint_id.strip()
        ):
            _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        identity = (role, provider_id, source, version, endpoint_id)
        if role in roles or identity in identities:
            _fail("REHEARSAL_PROVIDER_IDENTITY_DUPLICATE")
        roles.add(role)
        identities.add(identity)
        normalized.append(
            {
                "endpoint_id": endpoint_id,
                "provider_id": provider_id,
                "role": role,
                "source": source,
                "version": version,
            }
        )
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _resolve_artifact(base: Path, reference: object, expected_sha: object) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        _fail("REHEARSAL_ARTIFACT_REFERENCE_INVALID")
    if not isinstance(expected_sha, str) or SHA256_PATTERN.fullmatch(expected_sha) is None:
        _fail("REHEARSAL_ARTIFACT_DIGEST_INVALID")
    path = Path(reference)
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if _sha256(path) != expected_sha:
        _fail("REHEARSAL_ARTIFACT_DIGEST_MISMATCH")
    return path


def _validate_common_report(
    *,
    report: dict[str, Any],
    kind: str,
    expected_candidate: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
    now: datetime,
    max_age: timedelta,
) -> None:
    if report.get("schema") != REQUIRED_REPORT_SCHEMAS[kind]:
        _fail("REHEARSAL_REPORT_SCHEMA_INVALID")
    if report.get("kind") != kind:
        _fail("REHEARSAL_REPORT_KIND_MISMATCH")
    if report.get("candidate_sha") != expected_candidate:
        _fail("REHEARSAL_CANDIDATE_MISMATCH")
    if report.get("target_trade_date") != expected_date:
        _fail("REHEARSAL_TARGET_DATE_MISMATCH")
    if report.get("universe_sha256") != expected_universe:
        _fail("REHEARSAL_UNIVERSE_MISMATCH")
    if report.get("outcome") != "success":
        _fail("REHEARSAL_REPORT_NOT_SUCCESSFUL")
    if report.get("evidence_mode") != REQUIRED_EVIDENCE_MODES[kind]:
        _fail("REHEARSAL_EVIDENCE_MODE_INVALID")
    provider_digest = _validate_provider_identities(report.get("provider_identities"))
    if provider_digest != expected_provider_digest:
        _fail("REHEARSAL_PROVIDER_MISMATCH")
    started = _parse_datetime(report.get("started_at"), "REHEARSAL_TIME_INVALID")
    finished = _parse_datetime(report.get("finished_at"), "REHEARSAL_TIME_INVALID")
    if finished < started or finished > now + timedelta(minutes=5):
        _fail("REHEARSAL_TIME_INVALID")
    if now - finished > max_age:
        _fail("REHEARSAL_EVIDENCE_STALE")


def _validate_receipt_identity(
    receipt: dict[str, Any],
    *,
    expected_candidate: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
) -> None:
    if receipt.get("candidate_sha") != expected_candidate:
        _fail("REHEARSAL_RECEIPT_CANDIDATE_MISMATCH")
    if receipt.get("target_trade_date") != expected_date:
        _fail("REHEARSAL_RECEIPT_DATE_MISMATCH")
    if receipt.get("universe_sha256") != expected_universe:
        _fail("REHEARSAL_RECEIPT_UNIVERSE_MISMATCH")
    if receipt.get("provider_identities_sha256") != expected_provider_digest:
        _fail("REHEARSAL_RECEIPT_PROVIDER_MISMATCH")
    if receipt.get("outcome") != "success":
        _fail("REHEARSAL_RECEIPT_NOT_SUCCESSFUL")


def _validate_real_replay(
    report: dict[str, Any],
    base: Path,
    *,
    expected_candidate: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
    expected_assets: tuple[str, ...],
) -> None:
    _require_true(report, "units_verified", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    _require_true(report, "source_time_verified", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    _require_positive_int(report, "replay_case_count", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    artifacts = report.get("response_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _fail("REHEARSAL_REAL_RESPONSE_MISSING")
    datasets: set[str] = set()
    replayed_cases: set[str] = set()
    ranked = sorted(expected_assets, key=lambda code: hashlib.sha256(code.encode()).hexdigest())
    groups: dict[str, str] = {}
    for code in ranked:
        groups.setdefault(code.rsplit(".", 1)[-1], code)
    selected = set(groups.values())
    for code in ranked:
        if len(selected) >= min(50, len(expected_assets)):
            break
        selected.add(code)
    expected_sample = sorted(selected)
    for artifact in cast(list[object], artifacts):
        if not isinstance(artifact, dict):
            _fail("REHEARSAL_REAL_RESPONSE_MISSING")
        artifact_payload = cast(dict[str, object], artifact)
        receipt_path = _resolve_artifact(
            base, artifact_payload.get("path"), artifact_payload.get("sha256")
        )
        receipt = _read_json(receipt_path, "REHEARSAL_REPLAY_RECEIPT_INVALID")
        if receipt.get("schema") != "release.real-provider-response-replay.v1":
            _fail("REHEARSAL_REPLAY_RECEIPT_INVALID")
        _validate_receipt_identity(
            receipt,
            expected_candidate=expected_candidate,
            expected_date=expected_date,
            expected_universe=expected_universe,
            expected_provider_digest=expected_provider_digest,
        )
        dataset = receipt.get("dataset")
        if dataset not in {"equity.quote.snapshot", "equity.valuation.fact"}:
            _fail("REHEARSAL_REPLAY_DATASET_INVALID")
        datasets.add(cast(str, dataset))
        for unit_key in ("raw_unit", "canonical_unit"):
            _require_string(receipt, unit_key, "REHEARSAL_REPLAY_UNIT_MISSING")
        observed = _parse_datetime(
            receipt.get("source_observed_at"), "REHEARSAL_REPLAY_SOURCE_TIME_INVALID"
        )
        if observed.astimezone(ZoneInfo("Asia/Shanghai")).date() != date.fromisoformat(
            expected_date
        ):
            _fail("REHEARSAL_REPLAY_SOURCE_DATE_MISMATCH")
        sampled_assets = receipt.get("sampled_assets")
        if (
            not isinstance(sampled_assets, list)
            or any(not isinstance(asset, str) or not asset.strip() for asset in sampled_assets)
            or sampled_assets != expected_sample
        ):
            _fail("REHEARSAL_REPLAY_SAMPLE_INVALID")
        cases = receipt.get("replay_cases")
        if not isinstance(cases, list) or any(not isinstance(case, str) for case in cases):
            _fail("REHEARSAL_REPLAY_CASES_INVALID")
        replayed_cases.update(cast(list[str], cases))
        response = receipt.get("response_body")
        responses = receipt.get("response_bodies")
        if (
            not isinstance(response, dict)
            or not isinstance(responses, list)
            or not responses
            or receipt.get("response_set_scope") != "all_retained_responses_for_dataset"
            or response != responses[0]
        ):
            _fail("REHEARSAL_REAL_RESPONSE_MISSING")
        response_paths: set[str] = set()
        for response_value in cast(list[object], responses):
            if not isinstance(response_value, dict):
                _fail("REHEARSAL_REAL_RESPONSE_MISSING")
            response_payload = cast(dict[str, object], response_value)
            response_path = response_payload.get("path")
            if not isinstance(response_path, str) or response_path in response_paths:
                _fail("REHEARSAL_REPLAY_RESPONSE_SET_INVALID")
            response_paths.add(response_path)
            _resolve_artifact(
                receipt_path.parent,
                response_path,
                response_payload.get("sha256"),
            )
    if datasets != {"equity.quote.snapshot", "equity.valuation.fact"}:
        _fail("REHEARSAL_REPLAY_DATASET_INCOMPLETE")
    if replayed_cases != REQUIRED_REPLAY_CASES:
        _fail("REHEARSAL_REPLAY_CASES_INCOMPLETE")


def _validate_capacity(report: dict[str, Any]) -> tuple[str, ...]:
    universe_count = _require_positive_int(
        report, "universe_count", "REHEARSAL_CAPACITY_INCOMPLETE"
    )
    measured_count = _require_positive_int(
        report, "measured_asset_count", "REHEARSAL_CAPACITY_INCOMPLETE"
    )
    if measured_count != universe_count:
        _fail("REHEARSAL_CAPACITY_NOT_FULL_UNIVERSE")
    asset_codes = report.get("asset_codes")
    if (
        not isinstance(asset_codes, list)
        or len(asset_codes) != universe_count
        or any(not isinstance(code, str) or not code.strip() for code in asset_codes)
        or asset_codes != sorted(set(asset_codes))
    ):
        _fail("REHEARSAL_CAPACITY_UNIVERSE_INVALID")
    encoded_universe = json.dumps(
        asset_codes, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if hashlib.sha256(encoded_universe).hexdigest() != report.get("universe_sha256"):
        _fail("REHEARSAL_CAPACITY_UNIVERSE_MISMATCH")
    for key in (
        "provider_quota_within_limit",
        "task_deadline_within_limit",
        "database_budget_within_limit",
        "lock_budget_within_limit",
    ):
        _require_true(report, key, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED")
    margin = report.get("capacity_margin_ratio")
    if (
        isinstance(margin, bool)
        or not isinstance(margin, (int, float))
        or not math.isfinite(float(margin))
        or float(margin) <= 0
    ):
        _fail("REHEARSAL_CAPACITY_MARGIN_INVALID")
    return tuple(cast(list[str], asset_codes))


def _validate_isolated_write(
    report: dict[str, Any],
    base: Path,
    *,
    expected_candidate: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
) -> None:
    if report.get("database_scope") not in {"disposable", "isolated_staging"}:
        _fail("REHEARSAL_WRITE_SCOPE_INVALID")
    _require_positive_int(report, "written_rows", "REHEARSAL_WRITE_NOT_EXERCISED")
    _require_true(report, "publication_verified", "REHEARSAL_WRITE_INCOMPLETE")
    _require_true(report, "rollback_verified", "REHEARSAL_ROLLBACK_INCOMPLETE")
    residual = report.get("residual_rows")
    if type(residual) is not int or residual != 0:
        _fail("REHEARSAL_ROLLBACK_RESIDUAL")
    artifacts = report.get("write_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _fail("REHEARSAL_WRITE_ARTIFACT_MISSING")
    for artifact in cast(list[object], artifacts):
        if not isinstance(artifact, dict):
            _fail("REHEARSAL_WRITE_ARTIFACT_MISSING")
        artifact_payload = cast(dict[str, object], artifact)
        receipt_path = _resolve_artifact(
            base, artifact_payload.get("path"), artifact_payload.get("sha256")
        )
        receipt = _read_json(receipt_path, "REHEARSAL_WRITE_RECEIPT_INVALID")
        if receipt.get("schema") != "release.isolated-write-receipt.v1":
            _fail("REHEARSAL_WRITE_RECEIPT_INVALID")
        _validate_receipt_identity(
            receipt,
            expected_candidate=expected_candidate,
            expected_date=expected_date,
            expected_universe=expected_universe,
            expected_provider_digest=expected_provider_digest,
        )
        if receipt.get("database_scope") not in {"disposable", "isolated_staging"}:
            _fail("REHEARSAL_WRITE_SCOPE_INVALID")
        receipt_written = receipt.get("written_rows")
        receipt_residual = receipt.get("residual_rows")
        if type(receipt_written) is not int or receipt_written != report.get("written_rows"):
            _fail("REHEARSAL_WRITE_RECEIPT_MISMATCH")
        if type(receipt_residual) is not int or receipt_residual != 0:
            _fail("REHEARSAL_ROLLBACK_RESIDUAL")
        for key in ("publication_verified", "readback_verified", "rollback_verified"):
            _require_true(receipt, key, "REHEARSAL_WRITE_RECEIPT_INCOMPLETE")


def _validate_regression(
    report: dict[str, Any],
    base: Path,
    expected_candidate: str,
    expected_github_repository: str,
    expected_github_run_id: int,
    now: datetime,
    max_age: timedelta,
) -> None:
    _require_true(report, "postgresql_vendor_verified", "REHEARSAL_POSTGRESQL_UNVERIFIED")
    _require_true(report, "selected_by_candidate", "REHEARSAL_SELECTION_UNVERIFIED")
    if report.get("github_repository") != expected_github_repository:
        _fail("REHEARSAL_GITHUB_REPOSITORY_MISMATCH")
    if report.get("github_run_id") != expected_github_run_id:
        _fail("REHEARSAL_GITHUB_RUN_MISMATCH")
    attestation = _load_github_run(expected_github_repository, expected_github_run_id)
    repository = attestation.get("repository")
    if (
        not isinstance(repository, dict)
        or repository.get("full_name") != expected_github_repository
    ):
        _fail("REHEARSAL_GITHUB_REPOSITORY_MISMATCH")
    if (
        attestation.get("id") != expected_github_run_id
        or attestation.get("head_sha") != expected_candidate
        or attestation.get("name") != REQUIRED_GITHUB_WORKFLOW
        or attestation.get("status") != "completed"
        or attestation.get("conclusion") != "success"
    ):
        _fail("REHEARSAL_GITHUB_RUN_NOT_APPROVED")
    github_finished = _parse_datetime(
        attestation.get("updated_at"), "REHEARSAL_GITHUB_TIME_INVALID"
    )
    if github_finished > now + timedelta(minutes=5) or now - github_finished > max_age:
        _fail("REHEARSAL_GITHUB_RUN_STALE")
    required = report.get("required_tests")
    if not isinstance(required, list) or any(
        not isinstance(item, str) or "::" not in item or not item.strip() for item in required
    ):
        _fail("REHEARSAL_REQUIRED_TESTS_INVALID")
    if tuple(required) != REQUIRED_POSTGRESQL_TESTS:
        _fail("REHEARSAL_REQUIRED_TEST_SET_MISMATCH")
    junit_artifacts = report.get("junit_artifacts")
    if not isinstance(junit_artifacts, list) or len(junit_artifacts) != len(REQUIRED_JUNIT_FILES):
        _fail("REHEARSAL_JUNIT_INVALID")
    official_files = _load_github_junit_artifacts(
        expected_github_repository, expected_github_run_id, expected_candidate
    )
    roots: list[ET.Element] = []
    observed_names: set[str] = set()
    for junit in cast(list[object], junit_artifacts):
        if not isinstance(junit, dict):
            _fail("REHEARSAL_JUNIT_INVALID")
        junit_payload = cast(dict[str, object], junit)
        junit_path = _resolve_artifact(base, junit_payload.get("path"), junit_payload.get("sha256"))
        artifact_name = junit_path.name
        if artifact_name in observed_names or artifact_name not in REQUIRED_JUNIT_FILES:
            _fail("REHEARSAL_JUNIT_INVALID")
        observed_names.add(artifact_name)
        try:
            local_bytes = junit_path.read_bytes()
        except OSError:
            _fail("REHEARSAL_JUNIT_INVALID")
        if official_files.get(artifact_name) != local_bytes:
            _fail("REHEARSAL_JUNIT_ARTIFACT_MISMATCH")
        try:
            roots.append(ET.fromstring(local_bytes))
        except ET.ParseError:
            _fail("REHEARSAL_JUNIT_INVALID")
    if observed_names != REQUIRED_JUNIT_FILES:
        _fail("REHEARSAL_JUNIT_INVALID")
    cases = [case for root in roots for case in root.findall(".//testcase")]
    if not cases:
        _fail("REHEARSAL_JUNIT_EMPTY")
    if any(
        root.findall(".//failure") or root.findall(".//error") or root.findall(".//skipped")
        for root in roots
    ):
        _fail("REHEARSAL_JUNIT_NOT_GREEN")
    suite_timestamps = [
        suite.get("timestamp") for root in roots for suite in root.findall(".//testsuite")
    ]
    if any(value is None for value in suite_timestamps):
        _fail("REHEARSAL_JUNIT_TIME_INVALID")
    for value in suite_timestamps:
        observed_at = _parse_datetime(value, "REHEARSAL_JUNIT_TIME_INVALID")
        if observed_at > now + timedelta(minutes=5) or now - observed_at > max_age:
            _fail("REHEARSAL_JUNIT_STALE")
    observed: set[str] = set()
    for case in cases:
        name = case.get("name", "")
        classname = case.get("classname", "")
        observed.add(f"{classname}::{name}")
    if not set(cast(list[str], required)) <= observed:
        _fail("REHEARSAL_REQUIRED_TEST_MISSING")


def validate_release_rehearsal(
    *,
    manifest_path: Path,
    expected_candidate: str,
    expected_target_date: str,
    expected_universe_sha256: str,
    expected_provider_identities_sha256: str,
    expected_github_repository: str,
    expected_github_run_id: int,
    max_age_hours: float,
    now: datetime | None = None,
) -> dict[str, object]:
    """Validate four real evidence reports and return a safe release summary."""
    if COMMIT_PATTERN.fullmatch(expected_candidate) is None:
        _fail("REHEARSAL_EXPECTED_CANDIDATE_INVALID")
    try:
        date.fromisoformat(expected_target_date)
    except ValueError:
        _fail("REHEARSAL_EXPECTED_DATE_INVALID")
    if SHA256_PATTERN.fullmatch(expected_universe_sha256) is None:
        _fail("REHEARSAL_EXPECTED_UNIVERSE_INVALID")
    if SHA256_PATTERN.fullmatch(expected_provider_identities_sha256) is None:
        _fail("REHEARSAL_EXPECTED_PROVIDER_INVALID")
    if (
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_github_repository) is None
        or isinstance(expected_github_run_id, bool)
        or expected_github_run_id <= 0
    ):
        _fail("REHEARSAL_EXPECTED_GITHUB_RUN_INVALID")
    if not math.isfinite(max_age_hours) or max_age_hours <= 0:
        _fail("REHEARSAL_MAX_AGE_INVALID")
    raw_now = now or datetime.now(UTC)
    if raw_now.utcoffset() is None:
        _fail("REHEARSAL_NOW_INVALID")
    observed_now = raw_now.astimezone(UTC)
    manifest = _read_json(manifest_path, "REHEARSAL_MANIFEST_INVALID")
    if manifest.get("schema") != "release.rehearsal-manifest.v1":
        _fail("REHEARSAL_MANIFEST_SCHEMA_INVALID")
    reports = manifest.get("reports")
    if not isinstance(reports, list) or len(reports) != len(REQUIRED_REPORT_SCHEMAS):
        _fail("REHEARSAL_REPORT_SET_INCOMPLETE")
    references: dict[str, dict[str, Any]] = {}
    for reference in cast(list[object], reports):
        if not isinstance(reference, dict):
            _fail("REHEARSAL_REPORT_REFERENCE_INVALID")
        reference_payload = cast(dict[str, Any], reference)
        kind = reference_payload.get("kind")
        if not isinstance(kind, str) or kind not in REQUIRED_REPORT_SCHEMAS or kind in references:
            _fail("REHEARSAL_REPORT_SET_INVALID")
        references[kind] = reference_payload
    if set(references) != set(REQUIRED_REPORT_SCHEMAS):
        _fail("REHEARSAL_REPORT_SET_INCOMPLETE")
    base = manifest_path.resolve().parent
    loaded_reports: dict[str, dict[str, Any]] = {}
    report_paths: dict[str, Path] = {}
    for kind in REQUIRED_REPORT_SCHEMAS:
        reference = references[kind]
        report_path = _resolve_artifact(base, reference.get("path"), reference.get("sha256"))
        report = _read_json(report_path, "REHEARSAL_REPORT_INVALID")
        _validate_common_report(
            report=report,
            kind=kind,
            expected_candidate=expected_candidate,
            expected_date=expected_target_date,
            expected_universe=expected_universe_sha256,
            expected_provider_digest=expected_provider_identities_sha256,
            now=observed_now,
            max_age=timedelta(hours=max_age_hours),
        )
        loaded_reports[kind] = report
        report_paths[kind] = report_path
    expected_assets = _validate_capacity(loaded_reports["full_universe_capacity"])
    _validate_real_replay(
        loaded_reports["real_response_unit_replay"],
        report_paths["real_response_unit_replay"].parent,
        expected_candidate=expected_candidate,
        expected_date=expected_target_date,
        expected_universe=expected_universe_sha256,
        expected_provider_digest=expected_provider_identities_sha256,
        expected_assets=expected_assets,
    )
    _validate_isolated_write(
        loaded_reports["isolated_write_rehearsal"],
        report_paths["isolated_write_rehearsal"].parent,
        expected_candidate=expected_candidate,
        expected_date=expected_target_date,
        expected_universe=expected_universe_sha256,
        expected_provider_digest=expected_provider_identities_sha256,
    )
    _validate_regression(
        loaded_reports["candidate_regression_evidence"],
        report_paths["candidate_regression_evidence"].parent,
        expected_candidate,
        expected_github_repository,
        expected_github_run_id,
        observed_now,
        timedelta(hours=max_age_hours),
    )
    return {
        "outcome": "success",
        "candidate_sha": expected_candidate,
        "target_trade_date": expected_target_date,
        "universe_sha256": expected_universe_sha256,
        "validated_reports": sorted(REQUIRED_REPORT_SCHEMAS),
    }


def main() -> int:
    """Validate command-line release evidence without collecting or mutating data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-candidate", required=True)
    parser.add_argument("--expected-target-date", required=True)
    parser.add_argument("--expected-universe-sha256", required=True)
    parser.add_argument("--expected-provider-identities-sha256", required=True)
    parser.add_argument("--expected-github-repository", required=True)
    parser.add_argument("--expected-github-run-id", required=True, type=int)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    try:
        result = validate_release_rehearsal(
            manifest_path=args.manifest,
            expected_candidate=args.expected_candidate,
            expected_target_date=args.expected_target_date,
            expected_universe_sha256=args.expected_universe_sha256,
            expected_provider_identities_sha256=args.expected_provider_identities_sha256,
            expected_github_repository=args.expected_github_repository,
            expected_github_run_id=args.expected_github_run_id,
            max_age_hours=args.max_age_hours,
        )
    except RehearsalValidationError as exc:
        print(json.dumps({"outcome": "blocked", "code": exc.code}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
