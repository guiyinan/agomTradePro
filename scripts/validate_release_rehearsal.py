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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, cast
from zoneinfo import ZoneInfo

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
REQUIRED_REPORT_SCHEMAS = {
    "real_response_unit_replay": "release.real-response-unit-replay.v1",
    "full_universe_capacity": "release.full-universe-capacity.v2",
    "isolated_write_rehearsal": "release.isolated-write-rehearsal.v1",
    "candidate_regression_evidence": "release.candidate-regression-evidence.v1",
}
REQUIRED_EVIDENCE_MODES = {
    "real_response_unit_replay": "real_provider",
    "full_universe_capacity": "measured_full_universe",
    "isolated_write_rehearsal": "isolated_postgresql",
    "candidate_regression_evidence": "candidate_ci",
}
IMAGE_BOUND_REPORTS = frozenset(
    {"real_response_unit_replay", "full_universe_capacity", "isolated_write_rehearsal"}
)
PROVIDER_IDENTITY_DIGEST_ONLY_REPORTS = frozenset(
    {"full_universe_capacity", "isolated_write_rehearsal"}
)
REQUIRED_POSTGRESQL_TESTS = (
    "tests.component.data_center.test_core_data_backfill_control_plane::test_postgresql_backfill_first_run_and_same_parameter_retry_are_idempotent",
    "tests.component.data_center.test_core_data_backfill_control_plane::test_postgresql_backfill_provider_domain_failure_persists_partial_outcome",
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_connected_database_identity_returns_real_postgres_address_without_cidr",
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
    "tests.component.data_center.test_publication_read_snapshot_postgres::test_isolated_write_rehearsal_uses_production_publication_and_rolls_back",
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
REQUIRED_REPLAY_UNIT_CONTRACTS = {
    "equity.quote.snapshot": {
        "close": ("CNY_per_share", "CNY_per_share", 1.0, False),
        "vol": ("lot", "share", 100.0, True),
        "amount": ("thousand_CNY", "CNY", 1000.0, True),
    },
    "equity.valuation.fact": {
        "total_mv": ("万元", "元", 10000.0, False),
        "circ_mv": ("万元", "元", 10000.0, False),
    },
}
REQUIRED_GITHUB_WORKFLOW = "Publication PostgreSQL contracts"
REQUIRED_GITHUB_ARTIFACT = "publication-postgres-evidence"
REQUIRED_JUNIT_FILES = {
    "publication-postgres.xml",
    "backfill-control-plane-postgres.xml",
}
RELEASE_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "governance" / "release_rehearsal_policy.json"
)


class RehearsalValidationError(ValueError):
    """Stable, safe release-rehearsal validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _ValidatedPolicyEvidence:
    """Canonical policy content and its recomputed decision identity."""

    snapshot: dict[str, Any]
    identity: str
    content_sha256: str
    minimum_coverage_ratio: float


@dataclass(frozen=True)
class _ValidatedCapacityEvidence:
    """Full registered/eligible scope and policy proven by a capacity receipt."""

    registered_asset_codes: tuple[str, ...]
    eligible_asset_codes: tuple[str, ...]
    excluded_asset_codes: tuple[str, ...]
    exclusion_reason: str
    exclusion_rule_version: str
    policy: _ValidatedPolicyEvidence


def _fail(code: str) -> NoReturn:
    raise RehearsalValidationError(code)


def _require_candidate_attestation(payload: dict[str, Any]) -> None:
    if payload.get("candidate_source_attestation") not in {
        "image_release_manifest",
        "clean_git_checkout",
    }:
        _fail("REHEARSAL_CANDIDATE_SOURCE_UNATTESTED")


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload: object = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail(code)
    if not raw or not isinstance(payload, dict):
        _fail(code)
    return cast(dict[str, Any], payload)


def _minimum_capacity_margin() -> float:
    payload = _read_json(RELEASE_POLICY_PATH, "REHEARSAL_CAPACITY_POLICY_INVALID")
    value = payload.get("minimum_capacity_margin_ratio")
    if (
        payload.get("schema") != "release.rehearsal-policy.v1"
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) < 1
    ):
        _fail("REHEARSAL_CAPACITY_POLICY_INVALID")
    return float(value)


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


def _require_finite_number(
    payload: dict[str, Any], key: str, code: str, *, allow_zero: bool = False
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(code)
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or (not allow_zero and parsed <= 0):
        _fail(code)
    return parsed


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
    relative = Path(reference)
    if relative.is_absolute() or relative.drive or ".." in relative.parts or "\\" in reference:
        _fail("REHEARSAL_ARTIFACT_REFERENCE_INVALID")
    unresolved = base.resolve()
    for part in relative.parts:
        unresolved /= part
        if unresolved.is_symlink():
            _fail("REHEARSAL_ARTIFACT_REFERENCE_INVALID")
    path = unresolved.resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        _fail("REHEARSAL_ARTIFACT_REFERENCE_INVALID")
    if _sha256(path) != expected_sha:
        _fail("REHEARSAL_ARTIFACT_DIGEST_MISMATCH")
    return path


def _validate_common_report(
    *,
    report: dict[str, Any],
    kind: str,
    expected_candidate: str,
    expected_image_id: str,
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
    if kind in IMAGE_BOUND_REPORTS and (
        report.get("candidate_image_id") != expected_image_id
        or report.get("candidate_source_attestation") != "image_release_manifest"
    ):
        _fail("REHEARSAL_REPORT_IMAGE_MISMATCH")
    if report.get("target_trade_date") != expected_date:
        _fail("REHEARSAL_TARGET_DATE_MISMATCH")
    if report.get("universe_sha256") != expected_universe:
        _fail("REHEARSAL_UNIVERSE_MISMATCH")
    if report.get("outcome") != "success":
        _fail("REHEARSAL_REPORT_NOT_SUCCESSFUL")
    if report.get("evidence_mode") != REQUIRED_EVIDENCE_MODES[kind]:
        _fail("REHEARSAL_EVIDENCE_MODE_INVALID")
    if report.get("provider_identities_sha256") != expected_provider_digest:
        _fail("REHEARSAL_PROVIDER_MISMATCH")
    provider_identities = report.get("provider_identities")
    if provider_identities is None:
        if kind not in PROVIDER_IDENTITY_DIGEST_ONLY_REPORTS:
            _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    elif _validate_provider_identities(provider_identities) != expected_provider_digest:
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
    expected_image_id: str,
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
    if receipt.get("candidate_image_id") != expected_image_id:
        _fail("REHEARSAL_RECEIPT_IMAGE_MISMATCH")
    if receipt.get("candidate_source_attestation") != "image_release_manifest":
        _fail("REHEARSAL_RECEIPT_IMAGE_MISMATCH")
    if receipt.get("outcome") != "success":
        _fail("REHEARSAL_RECEIPT_NOT_SUCCESSFUL")


def _validated_policy_evidence(
    value: object,
    *,
    error_code: str = "REHEARSAL_POLICY_EVIDENCE_INVALID",
) -> _ValidatedPolicyEvidence:
    """Recompute policy content hash and identity from its canonical JSON snapshot."""

    if not isinstance(value, dict) or set(value) != {"content", "content_sha256", "identity"}:
        _fail(error_code)
    snapshot = cast(dict[str, Any], value)
    content_value = snapshot.get("content")
    if not isinstance(content_value, dict):
        _fail(error_code)
    content = cast(dict[str, Any], content_value)
    expected_keys = {
        "encoding",
        "dataset_key",
        "contract_version",
        "schema_version",
        "policy_version",
        "minimum_coverage_ratio",
        "allow_partial",
        "conflict_action",
        "required_evidence",
        "retention_days",
    }
    ratio = content.get("minimum_coverage_ratio")
    version = content.get("policy_version")
    evidence = content.get("required_evidence")
    if (
        set(content) != expected_keys
        or content.get("encoding") != "publication-policy-v1"
        or content.get("dataset_key") != "equity.valuation.fact"
        or not isinstance(content.get("contract_version"), str)
        or not cast(str, content.get("contract_version")).strip()
        or not isinstance(content.get("schema_version"), str)
        or not cast(str, content.get("schema_version")).strip()
        or not isinstance(version, str)
        or not version
        or len(version) > 40
        or ":" in version
        or any(character.isspace() for character in version)
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not math.isfinite(float(ratio))
        or not 0 <= float(ratio) <= 1
        or type(content.get("allow_partial")) is not bool
        or content.get("conflict_action") not in {"block", "quarantine", "prefer_governed_source"}
        or not isinstance(evidence, list)
        or not evidence
        or any(not isinstance(item, str) or not item.strip() for item in evidence)
        or len(evidence) != len(set(evidence))
        or type(content.get("retention_days")) is not int
        or cast(int, content.get("retention_days")) <= 0
    ):
        _fail(error_code)
    try:
        raw = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail(error_code)
    digest = hashlib.sha256(raw).hexdigest()
    contract_version = cast(str, content["contract_version"])
    schema_version = cast(str, content["schema_version"])
    identity = (
        f"{contract_version}:{schema_version}" if version == "legacy" else f"p2:{version}:{digest}"
    )
    if snapshot.get("content_sha256") != digest or snapshot.get("identity") != identity:
        _fail(error_code)
    return _ValidatedPolicyEvidence(
        snapshot=snapshot,
        identity=identity,
        content_sha256=digest,
        minimum_coverage_ratio=float(ratio),
    )


def _validate_policy_fields(
    payload: dict[str, Any],
    evidence: _ValidatedPolicyEvidence,
    *,
    error_code: str,
) -> None:
    """Require duplicated policy summary fields to match canonical policy content."""

    if (
        payload.get("valuation_policy_identity") != evidence.identity
        or payload.get("valuation_policy_sha256") != evidence.content_sha256
        or payload.get("valuation_minimum_coverage_ratio") != evidence.minimum_coverage_ratio
    ):
        _fail(error_code)


def _replay_number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
    return float(value)


def _read_tushare_response_rows(path: Path) -> list[dict[str, object]]:
    payload = _read_json(path, "REHEARSAL_REPLAY_RESPONSE_BODY_INVALID")
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, dict):
        _fail("REHEARSAL_REPLAY_RESPONSE_BODY_INVALID")
    fields = data.get("fields")
    items = data.get("items")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(field, str) or not field for field in fields)
        or len(set(fields)) != len(fields)
        or not isinstance(items, list)
    ):
        _fail("REHEARSAL_REPLAY_RESPONSE_BODY_INVALID")
    rows: list[dict[str, object]] = []
    for item in cast(list[object], items):
        if not isinstance(item, list) or len(item) != len(fields):
            _fail("REHEARSAL_REPLAY_RESPONSE_BODY_INVALID")
        rows.append(dict(zip(cast(list[str], fields), cast(list[object], item), strict=True)))
    return rows


def _validate_unit_contract_artifact(
    payload: dict[str, Any],
    *,
    expected_candidate: str,
    expected_provider_digest: str,
) -> None:
    if (
        payload.get("schema") != "release.provider-unit-contract.v1"
        or payload.get("candidate_sha") != expected_candidate
        or payload.get("provider_identities_sha256") != expected_provider_digest
    ):
        _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
    _require_string(payload, "source_reference", "REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(REQUIRED_REPLAY_UNIT_CONTRACTS):
        _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
    for dataset, expected_fields in REQUIRED_REPLAY_UNIT_CONTRACTS.items():
        values = datasets.get(dataset)
        if not isinstance(values, list) or len(values) != len(expected_fields):
            _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        observed: dict[str, tuple[object, object, object]] = {}
        for value in cast(list[object], values):
            if not isinstance(value, dict):
                _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
            record = cast(dict[str, object], value)
            if set(record) != {"field", "raw_unit", "canonical_unit", "multiplier"}:
                _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
            field = record.get("field")
            if not isinstance(field, str) or field in observed:
                _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
            observed[field] = (
                record.get("raw_unit"),
                record.get("canonical_unit"),
                record.get("multiplier"),
            )
        if set(observed) != set(expected_fields):
            _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        for field, (raw_unit, canonical_unit, multiplier, _allow_zero) in expected_fields.items():
            observed_raw, observed_canonical, observed_multiplier = observed[field]
            if (
                observed_raw != raw_unit
                or observed_canonical != canonical_unit
                or isinstance(observed_multiplier, bool)
                or not isinstance(observed_multiplier, (int, float))
                or float(observed_multiplier) != multiplier
            ):
                _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")


def _validate_unit_observations(
    receipt: dict[str, Any],
    *,
    dataset: str,
    expected_sample: list[str],
    expected_date: str,
    response_rows_by_hash: dict[str, list[dict[str, object]]],
) -> None:
    observations = receipt.get("observations")
    if not isinstance(observations, list) or len(observations) != len(expected_sample):
        _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
    expected_fields = REQUIRED_REPLAY_UNIT_CONTRACTS[dataset]
    observed_assets: set[str] = set()
    receipt_observed_at = receipt.get("source_observed_at")
    for value in cast(list[object], observations):
        if not isinstance(value, dict):
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        observation = cast(dict[str, object], value)
        asset_code = observation.get("asset_code")
        body_sha = observation.get("body_sha256")
        if (
            not isinstance(asset_code, str)
            or asset_code in observed_assets
            or asset_code not in expected_sample
            or not isinstance(body_sha, str)
            or body_sha not in response_rows_by_hash
            or observation.get("source_observed_at") != receipt_observed_at
        ):
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        observed_assets.add(asset_code)
        source_observed = _parse_datetime(
            observation.get("source_observed_at"), "REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID"
        )
        transport_received = _parse_datetime(
            observation.get("transport_received_at"),
            "REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID",
        )
        normalization_completed = _parse_datetime(
            observation.get("normalization_completed_at"),
            "REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID",
        )
        if (
            source_observed.astimezone(ZoneInfo("Asia/Shanghai")).date()
            != date.fromisoformat(expected_date)
            or not source_observed <= transport_received <= normalization_completed
            or observation.get("response_completed_at")
            != observation.get("normalization_completed_at")
        ):
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        units = observation.get("units")
        if not isinstance(units, list) or len(units) != len(expected_fields):
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        units_by_field: dict[str, dict[str, object]] = {}
        for unit_value in cast(list[object], units):
            if not isinstance(unit_value, dict):
                _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
            unit = cast(dict[str, object], unit_value)
            field = unit.get("field")
            if not isinstance(field, str) or field in units_by_field:
                _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
            units_by_field[field] = unit
        if set(units_by_field) != set(expected_fields):
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        source_rows = [
            row
            for row in response_rows_by_hash[body_sha]
            if row.get("ts_code") == asset_code
            and row.get("trade_date") == expected_date.replace("-", "")
        ]
        if len(source_rows) != 1:
            _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
        source_row = source_rows[0]
        for field, (raw_unit, canonical_unit, multiplier, allow_zero) in expected_fields.items():
            unit = units_by_field[field]
            observed_multiplier = _replay_number(unit.get("multiplier"))
            raw = _replay_number(unit.get("raw"))
            canonical = _replay_number(unit.get("canonical"))
            response_raw = _replay_number(source_row.get(field))
            if (
                unit.get("raw_unit") != raw_unit
                or unit.get("canonical_unit") != canonical_unit
                or observed_multiplier != multiplier
                or not math.isclose(response_raw, raw, rel_tol=1e-12, abs_tol=1e-12)
                or (not allow_zero and (raw <= 0 or canonical <= 0))
                or not math.isclose(
                    float(Decimal(str(raw)) * Decimal(str(multiplier))),
                    canonical,
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                )
            ):
                _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")
    if observed_assets != set(expected_sample):
        _fail("REHEARSAL_REPLAY_UNIT_OBSERVATION_INVALID")


def _validate_real_replay(
    report: dict[str, Any],
    base: Path,
    *,
    expected_candidate: str,
    expected_image_id: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
    capacity: _ValidatedCapacityEvidence,
) -> None:
    _require_candidate_attestation(report)
    _require_true(report, "units_verified", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    _require_true(report, "source_time_verified", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    _require_positive_int(report, "replay_case_count", "REHEARSAL_UNIT_REPLAY_INCOMPLETE")
    artifacts = report.get("response_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _fail("REHEARSAL_REAL_RESPONSE_MISSING")
    datasets: set[str] = set()
    replayed_cases: set[str] = set()
    provider_values = report.get("provider_identities")
    if not isinstance(provider_values, list):
        _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    provider_identities: dict[str, dict[str, object]] = {}
    for provider_value in cast(list[object], provider_values):
        if not isinstance(provider_value, dict):
            _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        identity = cast(dict[str, object], provider_value)
        role = identity.get("role")
        if not isinstance(role, str) or role in provider_identities:
            _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        provider_identities[role] = identity
    if set(provider_identities) != {"quote", "valuation"}:
        _fail("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    claimed_response_datasets: dict[str, str] = {}
    expected_assets = capacity.eligible_asset_codes
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
    _validate_policy_fields(report, capacity.policy, error_code="REHEARSAL_REPLAY_POLICY_MISMATCH")
    report_policy = _validated_policy_evidence(
        report.get("valuation_policy_snapshot"),
        error_code="REHEARSAL_REPLAY_POLICY_MISMATCH",
    )
    if report_policy != capacity.policy or report.get("candidate_image_id") != expected_image_id:
        _fail("REHEARSAL_REPLAY_POLICY_MISMATCH")
    if (
        report.get("eligible_asset_codes") != list(capacity.eligible_asset_codes)
        or report.get("eligible_asset_count") != len(capacity.eligible_asset_codes)
        or report.get("excluded_asset_codes") != list(capacity.excluded_asset_codes)
        or report.get("excluded_asset_count") != len(capacity.excluded_asset_codes)
        or report.get("exclusion_reason") != capacity.exclusion_reason
        or report.get("exclusion_rule_version") != capacity.exclusion_rule_version
    ):
        _fail("REHEARSAL_REPLAY_SCOPE_MISMATCH")
    probe_reference = report.get("probe_capture")
    if not isinstance(probe_reference, dict):
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    probe_reference_payload = cast(dict[str, object], probe_reference)
    probe_path = _resolve_artifact(
        base,
        probe_reference_payload.get("path"),
        probe_reference_payload.get("sha256"),
    )
    if report.get("probe_sha256") != probe_reference_payload.get("sha256"):
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    probe = _read_json(probe_path, "REHEARSAL_REPLAY_PROBE_INVALID")
    registered_assets = probe.get("asset_codes")
    if (
        probe.get("schema") != "market.provider-rehearsal.v1"
        or probe.get("outcome") != "success"
        or probe.get("mode") != "read_only_live_provider"
        or probe.get("database_read_only") is not True
        or probe.get("candidate_sha") != expected_candidate
        or probe.get("target_trade_date") != expected_date
        or probe.get("universe_sha256") != expected_universe
        or probe.get("provider_identities_sha256") != expected_provider_digest
        or probe.get("candidate_image_id") != expected_image_id
        or probe.get("sample") != expected_sample
        or probe.get("provider_identities") != provider_values
        or probe.get("eligible_asset_codes") != list(capacity.eligible_asset_codes)
        or probe.get("eligible_asset_count") != len(capacity.eligible_asset_codes)
        or probe.get("excluded_asset_codes") != list(capacity.excluded_asset_codes)
        or probe.get("excluded_asset_count") != len(capacity.excluded_asset_codes)
        or probe.get("exclusion_reason") != capacity.exclusion_reason
        or probe.get("exclusion_rule_version") != capacity.exclusion_rule_version
        or not isinstance(registered_assets, list)
        or registered_assets != sorted(set(registered_assets))
        or hashlib.sha256(
            json.dumps(
                registered_assets,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        != expected_universe
    ):
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    probe_policy = _validated_policy_evidence(
        probe.get("valuation_policy_snapshot"),
        error_code="REHEARSAL_REPLAY_PROBE_INVALID",
    )
    _validate_policy_fields(probe, capacity.policy, error_code="REHEARSAL_REPLAY_PROBE_INVALID")
    if probe_policy != capacity.policy:
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    if registered_assets != list(capacity.registered_asset_codes):
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    probe_rows = probe.get("probes")
    transport = probe.get("transport")
    transport_receipts = transport.get("receipts") if isinstance(transport, dict) else None
    if (
        not isinstance(probe_rows, list)
        or len(probe_rows) != 2
        or not isinstance(transport_receipts, list)
    ):
        _fail("REHEARSAL_REPLAY_PROBE_INVALID")
    captured_response_datasets: dict[str, str] = {}
    claimed_indexes: set[int] = set()
    for probe_row_value in cast(list[object], probe_rows):
        if not isinstance(probe_row_value, dict):
            _fail("REHEARSAL_REPLAY_PROBE_INVALID")
        probe_row = cast(dict[str, object], probe_row_value)
        dataset_value = probe_row.get("dataset")
        indexes = probe_row.get("receipt_indexes")
        if (
            dataset_value not in {"equity.quote.snapshot", "equity.valuation.fact"}
            or probe_row.get("outcome") != "success"
            or not isinstance(indexes, list)
            or not indexes
        ):
            _fail("REHEARSAL_REPLAY_PROBE_INVALID")
        for index in cast(list[object], indexes):
            if (
                type(index) is not int
                or index in claimed_indexes
                or index < 0
                or index >= len(transport_receipts)
            ):
                _fail("REHEARSAL_REPLAY_PROBE_INVALID")
            claimed_indexes.add(index)
            receipt_value = cast(list[object], transport_receipts)[index]
            if not isinstance(receipt_value, dict):
                _fail("REHEARSAL_REPLAY_PROBE_INVALID")
            receipt_payload = cast(dict[str, object], receipt_value)
            artifact_value = receipt_payload.get("response_artifact")
            if not isinstance(artifact_value, dict):
                _fail("REHEARSAL_REPLAY_PROBE_INVALID")
            artifact_payload = cast(dict[str, object], artifact_value)
            body_sha = artifact_payload.get("body_sha256")
            role = "quote" if dataset_value == "equity.quote.snapshot" else "valuation"
            provider_identity = provider_identities[role]
            expected_context_sample = expected_sample if role == "quote" else registered_assets
            if (
                SHA256_PATTERN.fullmatch(str(body_sha or "")) is None
                or artifact_payload.get("dataset") != dataset_value
                or artifact_payload.get("candidate_sha") != expected_candidate
                or artifact_payload.get("target_trade_date") != expected_date
                or artifact_payload.get("universe_sha256") != expected_universe
                or artifact_payload.get("provider_identities_sha256") != expected_provider_digest
                or artifact_payload.get("provider_id") != provider_identity.get("provider_id")
                or artifact_payload.get("provider_source") != provider_identity.get("source")
                or artifact_payload.get("endpoint_id") != provider_identity.get("endpoint_id")
                or artifact_payload.get("sample_codes") != expected_context_sample
                or receipt_payload.get("body_sha256") != body_sha
                or body_sha in captured_response_datasets
            ):
                _fail("REHEARSAL_REPLAY_PROBE_INVALID")
            captured_response_datasets[cast(str, body_sha)] = cast(str, dataset_value)
    for artifact in cast(list[object], artifacts):
        if not isinstance(artifact, dict):
            _fail("REHEARSAL_REAL_RESPONSE_MISSING")
        artifact_payload = cast(dict[str, object], artifact)
        receipt_path = _resolve_artifact(
            base, artifact_payload.get("path"), artifact_payload.get("sha256")
        )
        receipt = _read_json(receipt_path, "REHEARSAL_REPLAY_RECEIPT_INVALID")
        if receipt.get("schema") != "release.real-provider-response-replay.v2":
            _fail("REHEARSAL_REPLAY_RECEIPT_INVALID")
        _validate_receipt_identity(
            receipt,
            expected_candidate=expected_candidate,
            expected_image_id=expected_image_id,
            expected_date=expected_date,
            expected_universe=expected_universe,
            expected_provider_digest=expected_provider_digest,
        )
        if (
            receipt.get("eligible_asset_codes") != list(capacity.eligible_asset_codes)
            or receipt.get("eligible_asset_count") != len(capacity.eligible_asset_codes)
            or receipt.get("excluded_asset_codes") != list(capacity.excluded_asset_codes)
            or receipt.get("excluded_asset_count") != len(capacity.excluded_asset_codes)
            or receipt.get("exclusion_reason") != capacity.exclusion_reason
            or receipt.get("exclusion_rule_version") != capacity.exclusion_rule_version
        ):
            _fail("REHEARSAL_REPLAY_SCOPE_MISMATCH")
        replay_policy = _validated_policy_evidence(
            receipt.get("valuation_policy_snapshot"),
            error_code="REHEARSAL_REPLAY_POLICY_MISMATCH",
        )
        _validate_policy_fields(
            receipt, capacity.policy, error_code="REHEARSAL_REPLAY_POLICY_MISMATCH"
        )
        if replay_policy != capacity.policy:
            _fail("REHEARSAL_REPLAY_POLICY_MISMATCH")
        dataset = receipt.get("dataset")
        if dataset not in {"equity.quote.snapshot", "equity.valuation.fact"}:
            _fail("REHEARSAL_REPLAY_DATASET_INVALID")
        dataset_name = cast(str, dataset)
        datasets.add(dataset_name)
        role = "quote" if dataset_name == "equity.quote.snapshot" else "valuation"
        provider_identity = provider_identities[role]
        expected_operation = "daily" if role == "quote" else "daily_basic"
        expected_scope = "full_market_trade_date"
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
        response_rows_by_hash: dict[str, list[dict[str, object]]] = {}
        for response_value in cast(list[object], responses):
            if not isinstance(response_value, dict):
                _fail("REHEARSAL_REAL_RESPONSE_MISSING")
            response_payload = cast(dict[str, object], response_value)
            if set(response_payload) != {
                "path",
                "sha256",
                "dataset",
                "role",
                "provider_id",
                "provider_source",
                "provider_version",
                "endpoint_id",
                "operation",
                "response_scope",
            } or any(
                response_payload.get(key) != expected
                for key, expected in (
                    ("dataset", dataset_name),
                    ("role", role),
                    ("provider_id", provider_identity.get("provider_id")),
                    ("provider_source", provider_identity.get("source")),
                    ("provider_version", provider_identity.get("version")),
                    ("endpoint_id", provider_identity.get("endpoint_id")),
                    ("operation", expected_operation),
                    ("response_scope", expected_scope),
                )
            ):
                _fail("REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID")
            response_path = response_payload.get("path")
            if not isinstance(response_path, str) or response_path in response_paths:
                _fail("REHEARSAL_REPLAY_RESPONSE_SET_INVALID")
            response_paths.add(response_path)
            response_sha = response_payload.get("sha256")
            if not isinstance(response_sha, str):
                _fail("REHEARSAL_REPLAY_RESPONSE_SET_INVALID")
            if response_sha in response_rows_by_hash:
                _fail("REHEARSAL_REPLAY_RESPONSE_SET_INVALID")
            claimed_dataset = claimed_response_datasets.get(response_sha)
            if claimed_dataset is not None and claimed_dataset != dataset_name:
                _fail("REHEARSAL_REPLAY_RESPONSE_BINDING_INVALID")
            claimed_response_datasets[response_sha] = dataset_name
            resolved_response = _resolve_artifact(
                receipt_path.parent,
                response_path,
                response_sha,
            )
            response_rows_by_hash[response_sha] = _read_tushare_response_rows(resolved_response)
        target_compact = expected_date.replace("-", "")
        response_scope_counts = {
            asset: sum(
                1
                for rows in response_rows_by_hash.values()
                for row in rows
                if row.get("ts_code") == asset and row.get("trade_date") == target_compact
            )
            for asset in expected_sample
        }
        if any(count != 1 for count in response_scope_counts.values()):
            _fail("REHEARSAL_REPLAY_RESPONSE_SET_INVALID")
        contract_reference = receipt.get("unit_contract")
        if not isinstance(contract_reference, dict):
            _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        contract_payload = cast(dict[str, object], contract_reference)
        contract_path = _resolve_artifact(
            receipt_path.parent,
            contract_payload.get("path"),
            contract_payload.get("sha256"),
        )
        if receipt.get("unit_contract_sha256") != contract_payload.get("sha256"):
            _fail("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        _validate_unit_contract_artifact(
            _read_json(contract_path, "REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID"),
            expected_candidate=expected_candidate,
            expected_provider_digest=expected_provider_digest,
        )
        _validate_unit_observations(
            receipt,
            dataset=dataset_name,
            expected_sample=expected_sample,
            expected_date=expected_date,
            response_rows_by_hash=response_rows_by_hash,
        )
    if datasets != {"equity.quote.snapshot", "equity.valuation.fact"}:
        _fail("REHEARSAL_REPLAY_DATASET_INCOMPLETE")
    if claimed_response_datasets != captured_response_datasets:
        _fail("REHEARSAL_REPLAY_PROBE_MISMATCH")
    if replayed_cases != REQUIRED_REPLAY_CASES:
        _fail("REHEARSAL_REPLAY_CASES_INCOMPLETE")


def _validate_capacity(
    report: dict[str, Any],
    base: Path,
    *,
    expected_candidate: str,
    expected_image_id: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
) -> _ValidatedCapacityEvidence:
    _require_candidate_attestation(report)
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

    artifact = report.get("measurement_artifact")
    if not isinstance(artifact, dict):
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_MISSING")
    artifact_payload = cast(dict[str, object], artifact)
    receipt_path = _resolve_artifact(
        base, artifact_payload.get("path"), artifact_payload.get("sha256")
    )
    receipt = _read_json(receipt_path, "REHEARSAL_CAPACITY_RECEIPT_INVALID")
    _require_candidate_attestation(receipt)
    if (
        receipt.get("schema") != "release.full-universe-capacity-receipt.v1"
        or receipt.get("measurement_source") != "candidate_runtime_instrumentation"
        or receipt.get("measurement_scope")
        != "production_valuation_seed_and_eligible_quote_dispatch"
    ):
        _fail("REHEARSAL_CAPACITY_RECEIPT_INVALID")
    _validate_receipt_identity(
        receipt,
        expected_candidate=expected_candidate,
        expected_image_id=expected_image_id,
        expected_date=expected_date,
        expected_universe=expected_universe,
        expected_provider_digest=expected_provider_digest,
    )
    if (
        receipt.get("asset_codes") != asset_codes
        or receipt.get("measured_asset_count") != universe_count
        or receipt.get("requested_asset_count") != universe_count
        or receipt.get("registered_asset_count") != universe_count
    ):
        _fail("REHEARSAL_CAPACITY_RECEIPT_UNIVERSE_MISMATCH")
    eligible_codes = receipt.get("eligible_asset_codes")
    excluded_codes = receipt.get("excluded_asset_codes")
    if (
        not isinstance(eligible_codes, list)
        or not isinstance(excluded_codes, list)
        or eligible_codes != sorted(set(eligible_codes))
        or excluded_codes != sorted(set(excluded_codes))
        or not all(isinstance(code, str) and code for code in eligible_codes + excluded_codes)
        or set(eligible_codes) & set(excluded_codes)
        or sorted(eligible_codes + excluded_codes) != asset_codes
        or receipt.get("eligible_asset_count") != len(eligible_codes)
        or receipt.get("excluded_asset_count") != len(excluded_codes)
        or receipt.get("exclusion_reason") != "valuation_not_returned_for_target_session"
        or receipt.get("exclusion_rule_version") != "valuation-target-session-v1"
        or not isinstance(receipt.get("valuation_policy_identity"), str)
        or not str(receipt.get("valuation_policy_identity")).strip()
        or SHA256_PATTERN.fullmatch(str(receipt.get("valuation_policy_sha256") or "")) is None
        or not eligible_codes
    ):
        _fail("REHEARSAL_CAPACITY_ELIGIBLE_SCOPE_INVALID")
    policy = _validated_policy_evidence(
        receipt.get("valuation_policy_snapshot"),
        error_code="REHEARSAL_CAPACITY_POLICY_INVALID",
    )
    report_policy = _validated_policy_evidence(
        report.get("valuation_policy_snapshot"),
        error_code="REHEARSAL_CAPACITY_POLICY_INVALID",
    )
    _validate_policy_fields(receipt, policy, error_code="REHEARSAL_CAPACITY_POLICY_INVALID")
    _validate_policy_fields(report, policy, error_code="REHEARSAL_CAPACITY_POLICY_INVALID")
    if report_policy != policy:
        _fail("REHEARSAL_CAPACITY_POLICY_INVALID")
    valuation_minimum = policy.minimum_coverage_ratio
    valuation_ratio = _require_finite_number(
        receipt,
        "valuation_coverage_ratio",
        "REHEARSAL_CAPACITY_COVERAGE_INVALID",
        allow_zero=True,
    )
    derived_valuation_ratio = len(eligible_codes) / universe_count
    if (
        valuation_minimum > 1
        or valuation_ratio > 1
        or not math.isclose(valuation_ratio, derived_valuation_ratio, abs_tol=1e-12)
        or valuation_ratio < valuation_minimum
    ):
        _fail("REHEARSAL_CAPACITY_COVERAGE_INVALID")
    if (
        report.get("eligible_asset_codes") != eligible_codes
        or report.get("eligible_asset_count") != len(eligible_codes)
        or report.get("excluded_asset_codes") != excluded_codes
        or report.get("excluded_asset_count") != len(excluded_codes)
        or report.get("exclusion_reason") != receipt.get("exclusion_reason")
        or report.get("exclusion_rule_version") != receipt.get("exclusion_rule_version")
    ):
        _fail("REHEARSAL_CAPACITY_ELIGIBLE_SCOPE_INVALID")
    coverage_expectations = {
        "valuation_coverage": (universe_count, len(eligible_codes), excluded_codes),
        "quote_coverage": (len(eligible_codes), len(eligible_codes), []),
    }
    for key, (
        expected_requested,
        expected_target,
        expected_missing_codes,
    ) in coverage_expectations.items():
        coverage = receipt.get(key)
        if not isinstance(coverage, dict):
            _fail("REHEARSAL_CAPACITY_COVERAGE_INVALID")
        coverage_payload = cast(dict[str, object], coverage)
        requested = coverage_payload.get("requested_count")
        returned = coverage_payload.get("returned_count")
        target_count = coverage_payload.get("target_session_count")
        missing_count = coverage_payload.get("missing_target_session_count")
        missing_codes = coverage_payload.get("missing_target_session_codes")
        if (
            type(requested) is not int
            or requested != expected_requested
            or type(returned) is not int
            or not 0 <= returned <= expected_requested
            or type(target_count) is not int
            or target_count != expected_target
            or not 0 <= target_count <= returned
            or type(missing_count) is not int
            or missing_count != expected_requested - target_count
            or not isinstance(missing_codes, list)
            or missing_codes != expected_missing_codes
            or not set(cast(list[str], missing_codes)).issubset(set(asset_codes))
            or coverage_payload.get("extra_count") != 0
            or coverage_payload.get("duplicate_count") != 0
        ):
            _fail("REHEARSAL_CAPACITY_COVERAGE_INVALID")
        fact_count_key = "quote_fact_count" if key == "quote_coverage" else "valuation_fact_count"
        if receipt.get(fact_count_key) != returned:
            _fail("REHEARSAL_CAPACITY_COVERAGE_INVALID")

    receipt_started = _parse_datetime(
        receipt.get("started_at"), "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    receipt_finished = _parse_datetime(
        receipt.get("finished_at"), "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    report_started = _parse_datetime(report.get("started_at"), "REHEARSAL_TIME_INVALID")
    report_finished = _parse_datetime(report.get("finished_at"), "REHEARSAL_TIME_INVALID")
    if (
        receipt_finished < receipt_started
        or receipt_started < report_started - timedelta(seconds=1)
        or receipt_finished > report_finished + timedelta(seconds=1)
    ):
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_INVALID")

    elapsed = _require_finite_number(
        receipt, "elapsed_seconds", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    measured_elapsed = (receipt_finished - receipt_started).total_seconds()
    if not math.isclose(elapsed, measured_elapsed, rel_tol=0.01, abs_tol=0.1):
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_INVALID")
    total_requests = _require_positive_int(
        receipt, "provider_total_requests", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    peak_requests = _require_positive_int(
        receipt, "provider_peak_requests_per_window", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    provider_limit = _require_positive_int(
        receipt, "provider_request_limit_per_window", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    _require_finite_number(
        receipt, "provider_window_seconds", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    if peak_requests > total_requests:
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_INVALID")
    deadline = _require_finite_number(
        receipt, "task_deadline_seconds", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    database_peak = _require_positive_int(
        receipt, "database_peak_connections", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    database_limit = _require_positive_int(
        receipt, "database_connection_limit", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    if receipt.get("database_connection_scope") != "postgresql_cluster_all_databases":
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_INVALID")
    if (
        receipt.get("database_peak_measurement_method") != "sampled_pg_stat_activity_cluster_count"
        or receipt.get("memory_peak_measurement_method") != "linux_proc_status_vmhwm"
        or receipt.get("memory_limit_measurement_method") != "cgroup_effective_or_host_physical"
    ):
        _fail("REHEARSAL_CAPACITY_MEASUREMENT_INVALID")
    _require_finite_number(
        receipt, "sampling_interval_seconds", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    lock_wait = _require_finite_number(
        receipt,
        "max_lock_wait_seconds",
        "REHEARSAL_CAPACITY_MEASUREMENT_INVALID",
        allow_zero=True,
    )
    lock_limit = _require_finite_number(
        receipt, "lock_wait_limit_seconds", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    peak_memory = _require_positive_int(
        receipt, "peak_memory_bytes", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )
    memory_limit = _require_positive_int(
        receipt, "memory_limit_bytes", "REHEARSAL_CAPACITY_MEASUREMENT_INVALID"
    )

    ratios = {
        "provider_quota_within_limit": peak_requests / provider_limit,
        "task_deadline_within_limit": elapsed / deadline,
        "database_budget_within_limit": database_peak / database_limit,
        "lock_budget_within_limit": lock_wait / lock_limit,
        "memory_budget_within_limit": peak_memory / memory_limit,
    }
    for key, ratio in ratios.items():
        derived = ratio < 1.0
        if not derived:
            _fail("REHEARSAL_CAPACITY_LIMIT_EXCEEDED")
        if report.get(key) is not derived:
            _fail("REHEARSAL_CAPACITY_DERIVATION_MISMATCH")
    derived_margin = min(1.0 - ratio for ratio in ratios.values())
    governed_margin = _minimum_capacity_margin()
    receipt_margin = _require_finite_number(
        receipt,
        "minimum_capacity_margin_ratio",
        "REHEARSAL_CAPACITY_POLICY_INVALID",
    )
    if not math.isclose(receipt_margin, governed_margin, abs_tol=0.0) or (
        derived_margin < governed_margin
    ):
        _fail("REHEARSAL_CAPACITY_MARGIN_INSUFFICIENT")
    margin = _require_finite_number(
        report, "capacity_margin_ratio", "REHEARSAL_CAPACITY_MARGIN_INVALID"
    )
    if not math.isclose(margin, derived_margin, rel_tol=1e-9, abs_tol=1e-9):
        _fail("REHEARSAL_CAPACITY_MARGIN_MISMATCH")
    return _ValidatedCapacityEvidence(
        registered_asset_codes=tuple(cast(list[str], asset_codes)),
        eligible_asset_codes=tuple(cast(list[str], eligible_codes)),
        excluded_asset_codes=tuple(cast(list[str], excluded_codes)),
        exclusion_reason=cast(str, receipt.get("exclusion_reason")),
        exclusion_rule_version=cast(str, receipt.get("exclusion_rule_version")),
        policy=policy,
    )


def _validate_isolated_write(
    report: dict[str, Any],
    base: Path,
    *,
    expected_candidate: str,
    expected_image_id: str,
    expected_date: str,
    expected_universe: str,
    expected_provider_digest: str,
) -> None:
    _require_candidate_attestation(report)
    if report.get("database_scope") not in {"disposable", "isolated_staging"}:
        _fail("REHEARSAL_WRITE_SCOPE_INVALID")
    written_rows = _require_positive_int(report, "written_rows", "REHEARSAL_WRITE_NOT_EXERCISED")
    if written_rows != 4:
        _fail("REHEARSAL_WRITE_COUNT_INVALID")
    _require_true(report, "publication_verified", "REHEARSAL_WRITE_INCOMPLETE")
    _require_true(report, "readback_verified", "REHEARSAL_WRITE_INCOMPLETE")
    _require_true(report, "tamper_guard_verified", "REHEARSAL_WRITE_INCOMPLETE")
    _require_true(report, "rollback_verified", "REHEARSAL_ROLLBACK_INCOMPLETE")
    residual = report.get("residual_rows")
    if type(residual) is not int or residual != 0:
        _fail("REHEARSAL_ROLLBACK_RESIDUAL")
    identity_fields = (
        "publication_id",
        "publication_key",
        "publication_hash",
        "member_id",
        "member_fact_pk",
        "member_fact_content_hash",
        "database_identity_sha256",
        "catalog_seed_sha256",
        "payload_evidence_mode",
        "synthetic_payload_sha256",
    )
    if (
        UUID_PATTERN.fullmatch(str(report.get("publication_id") or "")) is None
        or UUID_PATTERN.fullmatch(str(report.get("member_id") or "")) is None
        or report.get("publication_key") != "current"
        or report.get("payload_evidence_mode") != "synthetic_isolated_writer_path"
        or not isinstance(report.get("member_fact_pk"), str)
        or not str(report.get("member_fact_pk")).strip()
        or any(
            SHA256_PATTERN.fullmatch(str(report.get(key) or "")) is None
            for key in (
                "publication_hash",
                "member_fact_content_hash",
                "database_identity_sha256",
                "catalog_seed_sha256",
                "synthetic_payload_sha256",
            )
        )
    ):
        _fail("REHEARSAL_WRITE_IDENTITY_INVALID")
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
        _require_candidate_attestation(receipt)
        if receipt.get("schema") != "release.isolated-write-receipt.v1":
            _fail("REHEARSAL_WRITE_RECEIPT_INVALID")
        _validate_receipt_identity(
            receipt,
            expected_candidate=expected_candidate,
            expected_image_id=expected_image_id,
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
        if any(receipt.get(key) != report.get(key) for key in identity_fields):
            _fail("REHEARSAL_WRITE_RECEIPT_MISMATCH")
        for key in (
            "publication_verified",
            "readback_verified",
            "tamper_guard_verified",
            "rollback_verified",
        ):
            _require_true(receipt, key, "REHEARSAL_WRITE_RECEIPT_INCOMPLETE")
            if receipt.get(key) is not report.get(key):
                _fail("REHEARSAL_WRITE_RECEIPT_MISMATCH")


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
    expected_candidate_image_id: str,
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
    if IMAGE_ID_PATTERN.fullmatch(expected_candidate_image_id) is None:
        _fail("REHEARSAL_EXPECTED_IMAGE_INVALID")
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
    if (
        manifest.get("candidate_sha") != expected_candidate
        or manifest.get("target_trade_date") != expected_target_date
        or manifest.get("universe_sha256") != expected_universe_sha256
        or manifest.get("provider_identities_sha256") != expected_provider_identities_sha256
        or manifest.get("candidate_image_id") != expected_candidate_image_id
    ):
        _fail("REHEARSAL_MANIFEST_IDENTITY_MISMATCH")
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
            expected_image_id=expected_candidate_image_id,
            expected_date=expected_target_date,
            expected_universe=expected_universe_sha256,
            expected_provider_digest=expected_provider_identities_sha256,
            now=observed_now,
            max_age=timedelta(hours=max_age_hours),
        )
        loaded_reports[kind] = report
        report_paths[kind] = report_path
    capacity = _validate_capacity(
        loaded_reports["full_universe_capacity"],
        report_paths["full_universe_capacity"].parent,
        expected_candidate=expected_candidate,
        expected_image_id=expected_candidate_image_id,
        expected_date=expected_target_date,
        expected_universe=expected_universe_sha256,
        expected_provider_digest=expected_provider_identities_sha256,
    )
    _validate_real_replay(
        loaded_reports["real_response_unit_replay"],
        report_paths["real_response_unit_replay"].parent,
        expected_candidate=expected_candidate,
        expected_image_id=expected_candidate_image_id,
        expected_date=expected_target_date,
        expected_universe=expected_universe_sha256,
        expected_provider_digest=expected_provider_identities_sha256,
        capacity=capacity,
    )
    _validate_isolated_write(
        loaded_reports["isolated_write_rehearsal"],
        report_paths["isolated_write_rehearsal"].parent,
        expected_candidate=expected_candidate,
        expected_image_id=expected_candidate_image_id,
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
        "candidate_image_id": expected_candidate_image_id,
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
    parser.add_argument("--expected-candidate-image-id", required=True)
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
            expected_candidate_image_id=args.expected_candidate_image_id,
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
