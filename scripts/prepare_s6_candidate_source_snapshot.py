#!/usr/bin/env python3
"""Create and seal a clean, exact-candidate S6 source snapshot."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TypedDict, cast
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.data_center.application.s6_market_graph_task_result import (
    MarketGraphTaskResultError,
    validate_market_graph_task_result,
)
from scripts.rehearsal_checkpoint import (
    seal_container_input_tree,
    tree_digest,
    verify_container_input_tree,
)
from shared.runtime_log_paths import READ_ONLY_RUNTIME_LOG_DIRECTORY, RUNTIME_LOG_DIRECTORY_ENV

_CANDIDATE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_TREE_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXECUTION_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EXPORT_FAILURE_CODES = {
    "production": "S6_CANDIDATE_EXPORT_PRODUCTION_FAILED",
    "universe": "S6_CANDIDATE_EXPORT_UNIVERSE_FAILED",
    "contract": "S6_CANDIDATE_EXPORT_CONTRACT_FAILED",
}
_GRAPH_REFRESH_FAILURE_CODE = "S6_GRAPH_REFRESH_COMMAND_FAILED"


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is inside ``parent`` without filesystem access."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    """Return whether either resolved directory contains the other."""

    return _is_relative_to(left, right) or _is_relative_to(right, left)


class CandidateSourceReceipt(TypedDict):
    """Non-secret receipt binding the exact source snapshot and permission result."""

    schema: str
    outcome: str
    candidate_sha: str
    snapshot_name: str
    tree_sha256: str
    file_count: int
    directory_count: int
    container_gid: int
    receipt_sha256: str
    permission_model: str
    directory_mode: str
    file_mode: str


class CandidateSourceSnapshotError(ValueError):
    """A candidate source snapshot failure with a stable machine-readable code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class _TrackedBlob:
    """One regular-file blob in the candidate commit tree."""

    relative_path: Path
    object_id: str
    hash_name: str


@dataclass(frozen=True)
class _FinalPrepareValidation:
    """Bound inputs for final verification of one private S6 preparation."""

    candidate_sha: str
    source_directory: Path
    source_receipt: Path
    container_uid: int
    container_gid: int
    execution_image_id: str
    inputs: Path
    exports: Path
    runner_python: str
    requirements_sha256: str
    postgres_container_id: str
    redis_container_id: str
    network_id: str


def _validation_require(condition: bool, error_code: str) -> None:
    """Raise a stable helper error when a final preparation invariant fails."""

    if not condition:
        raise CandidateSourceSnapshotError(error_code)


def _read_validation_json(path: Path, error_code: str) -> dict[str, object]:
    """Read one regular JSON object at the final validation boundary."""

    try:
        if path.is_symlink() or not path.is_file():
            raise CandidateSourceSnapshotError(error_code)
        value = json.loads(path.read_text(encoding="utf-8"))
    except CandidateSourceSnapshotError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceSnapshotError(error_code) from exc
    if not isinstance(value, dict):
        raise CandidateSourceSnapshotError(error_code)
    return cast(dict[str, object], value)


def _read_validation_json_list(path: Path, error_code: str) -> list[object]:
    """Read one regular JSON array at the final validation boundary."""

    try:
        if path.is_symlink() or not path.is_file():
            raise CandidateSourceSnapshotError(error_code)
        value = json.loads(path.read_text(encoding="utf-8"))
    except CandidateSourceSnapshotError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceSnapshotError(error_code) from exc
    if not isinstance(value, list):
        raise CandidateSourceSnapshotError(error_code)
    return cast(list[object], value)


def _read_validation_env(inputs: Path, name: str) -> dict[str, str]:
    """Read a private env file while rejecting duplicate or malformed keys."""

    values: dict[str, str] = {}
    try:
        lines = (inputs / name).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CandidateSourceSnapshotError("S6_PRIVATE_ENVIRONMENT_INVALID") from exc
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise CandidateSourceSnapshotError("S6_PRIVATE_ENVIRONMENT_INVALID")
        values[key] = value
    return values


def _validation_file_sha256(path: Path) -> str:
    """Hash one file in bounded memory for the prepare receipt."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_attempt_plan(
    context: _FinalPrepareValidation,
) -> tuple[dict[str, object], str]:
    """Rebuild the immutable plan and return its SHA-256 binding."""

    from scripts.plan_release_rehearsal_attempt import (
        AttemptPlan,
        AttemptPlanError,
        _canonical_plan,
    )

    attempt_root = context.inputs.parent
    plan_path = attempt_root / "attempt-plan.json"
    try:
        metadata = plan_path.lstat()
        raw = plan_path.read_bytes()
        plan_value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceSnapshotError("S6_ATTEMPT_PLAN_INVALID") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o222
        or not isinstance(plan_value, dict)
    ):
        raise CandidateSourceSnapshotError("S6_ATTEMPT_PLAN_INVALID")
    try:
        canonical_plan, canonical_bytes = _canonical_plan(cast(AttemptPlan, plan_value))
    except AttemptPlanError as exc:
        raise CandidateSourceSnapshotError("S6_ATTEMPT_PLAN_INVALID") from exc
    if (
        raw != canonical_bytes
        or Path(canonical_plan["root"]) != attempt_root
        or canonical_plan["candidate_sha"] != context.candidate_sha
        or Path(canonical_plan["candidate_source_snapshot_path"]) != context.source_directory
        or Path(canonical_plan["candidate_source_receipt_path"]) != context.source_receipt
        or Path(canonical_plan["provider_settings_export_path"]).parent != context.exports
    ):
        raise CandidateSourceSnapshotError("S6_ATTEMPT_PLAN_BINDING_MISMATCH")
    return cast(dict[str, object], canonical_plan), hashlib.sha256(raw).hexdigest()


def validate_final_prepare_receipt(context: _FinalPrepareValidation) -> dict[str, object]:
    """Validate all staged S6 inputs and write the immutable prepare receipt."""

    from apps.data_center.infrastructure.rehearsal_identity import (
        parse_complete_rehearsal_identities,
    )

    plan, attempt_plan_sha256 = _canonical_attempt_plan(context)
    inputs = context.inputs
    exports = context.exports
    attempt_root = inputs.parent
    expected_database = cast(str, plan["database"])
    expected_network = cast(str, plan["network"])
    postgres = cast(str, plan["postgres_container"])
    redis = cast(str, plan["redis_container"])
    advance_graph = plan["advance_isolated_market_graph"] is True
    graph_name = "current-market-graph-refresh.json"
    expected = {
        "provider-settings.json",
        "provider-identities.json",
        "unit-contract.json",
        "provider-policy-preflight.json",
        "universe-summary.json",
    }
    if advance_graph:
        expected.add(graph_name)
    _validation_require(
        context.inputs == attempt_root / "inputs-private"
        and inputs.is_dir()
        and not inputs.is_symlink(),
        "S6_PRIVATE_INPUT_DIRECTORY_INVALID",
    )
    _validation_require(
        exports.is_dir() and not exports.is_symlink(), "S6_EXPORT_DIRECTORY_INVALID"
    )
    try:
        export_info = exports.lstat()
        _validation_require(
            stat.S_ISDIR(export_info.st_mode) and stat.S_IMODE(export_info.st_mode) == 0o700,
            "S6_EXPORT_DIRECTORY_INVALID",
        )
        _validation_require(
            (export_info.st_uid, export_info.st_gid)
            == (context.container_uid, context.container_gid),
            "S6_EXPORT_DIRECTORY_OWNER_INVALID",
        )
        found: set[str] = set()
        for entry in os.scandir(exports):
            info = entry.stat(follow_symlinks=False)
            _validation_require(
                stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
                "S6_EXPORT_FILE_INVALID",
            )
            _validation_require(
                (info.st_uid, info.st_gid) == (context.container_uid, context.container_gid),
                "S6_EXPORT_FILE_OWNER_INVALID",
            )
            found.add(entry.name)
        _validation_require(found == expected, "S6_EXPORT_FILE_SET_INVALID")
        input_info = inputs.lstat()
        _validation_require(
            stat.S_ISDIR(input_info.st_mode) and stat.S_IMODE(input_info.st_mode) == 0o700,
            "S6_PRIVATE_INPUT_DIRECTORY_INVALID",
        )
        private_expected = {
            "runner.env",
            "vps-password.txt",
            "provider.env",
            "isolated-postgres.env",
            "isolated-migrator.env",
            *expected,
        }
        _validation_require(
            {entry.name for entry in os.scandir(inputs)} == private_expected,
            "S6_PRIVATE_INPUT_SET_INVALID",
        )
        for name in private_expected:
            info = (inputs / name).lstat()
            expected_mode = 0o400 if name == graph_name else 0o600
            _validation_require(
                stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == expected_mode,
                "S6_PRIVATE_INPUT_MODE_INVALID",
            )
        for name in expected:
            _validation_require(
                (exports / name).read_bytes() == (inputs / name).read_bytes(),
                "S6_PRIVATE_EXPORT_COPY_MISMATCH",
            )
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_EXPORT_FILE_INVALID") from exc

    provider = _read_validation_env(inputs, "provider.env")
    provider_allowlist = {
        "DJANGO_SETTINGS_MODULE",
        "TUSHARE_TOKEN",
        "TUSHARE_HTTP_URL",
        "TUSHARE_REQUEST_MODE",
        "DATA_CENTER_DEPLOYMENT_REGION",
        "AGOMTRADEPRO_DEPLOYMENT_REGION",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
    _validation_require(
        provider.get("DJANGO_SETTINGS_MODULE") == "core.settings.production"
        and set(provider) <= provider_allowlist
        and not (
            {
                "SECRET_KEY",
                "AGOMTRADEPRO_ENCRYPTION_KEY",
                "DATABASE_URL",
                "REDIS_URL",
                "REDIS_HOST",
            }
            & set(provider)
        ),
        "S6_PROVIDER_ENVIRONMENT_INVALID",
    )
    _validation_require(
        not (inputs / "prepare-export.env").exists()
        and not (inputs / "prepare-export.env").is_symlink(),
        "S6_PREPARE_ENV_CLEANUP_FAILED",
    )
    isolated = _read_validation_env(inputs, "isolated-postgres.env")
    _validation_require(
        isolated.get("POSTGRES_HOST") == postgres
        and isolated.get("POSTGRES_DB") == expected_database,
        "S6_ISOLATED_DATABASE_ENVIRONMENT_INVALID",
    )
    _validation_require(
        isolated.get("REDIS_HOST") == redis
        and isolated.get("REDIS_URL") == f"redis://{redis}:6379/0",
        "S6_ISOLATED_REDIS_ENVIRONMENT_INVALID",
    )

    settings = _read_validation_json(
        exports / "provider-settings.json", "S6_PROVIDER_SETTINGS_INVALID"
    )
    identities_value = _read_validation_json_list(
        exports / "provider-identities.json", "S6_PROVIDER_IDENTITIES_INVALID"
    )
    unit = _read_validation_json(exports / "unit-contract.json", "S6_UNIT_CONTRACT_INVALID")
    policy = _read_validation_json(
        exports / "provider-policy-preflight.json", "S6_PROVIDER_POLICY_PREFLIGHT_INVALID"
    )
    universe = _read_validation_json(exports / "universe-summary.json", "S6_UNIVERSE_SCOPE_INVALID")
    _validation_require(bool(settings), "S6_PROVIDER_SETTINGS_INVALID")
    if not identities_value:
        raise CandidateSourceSnapshotError("S6_PROVIDER_IDENTITIES_INVALID")
    try:
        parse_complete_rehearsal_identities(identities_value)
    except ValueError as exc:
        raise CandidateSourceSnapshotError("S6_PROVIDER_IDENTITIES_INVALID") from exc
    _validation_require(
        unit.get("candidate_sha") == context.candidate_sha,
        "S6_UNIT_CONTRACT_INVALID",
    )
    _validation_require(policy.get("outcome") == "pass", "S6_PROVIDER_POLICY_PREFLIGHT_INVALID")
    target_trade_date = universe.get("target_trade_date")
    universe_count = universe.get("universe_count")
    universe_sha256 = universe.get("universe_sha256")
    try:
        _validation_require(
            isinstance(target_trade_date, str)
            and datetime.date.fromisoformat(target_trade_date).isoformat() == target_trade_date,
            "S6_UNIVERSE_SCOPE_INVALID",
        )
    except ValueError as exc:
        raise CandidateSourceSnapshotError("S6_UNIVERSE_SCOPE_INVALID") from exc
    _validation_require(
        isinstance(universe_count, int)
        and not isinstance(universe_count, bool)
        and universe_count > 0,
        "S6_UNIVERSE_SCOPE_INVALID",
    )
    _validation_require(
        isinstance(universe_sha256, str) and _TREE_SHA_RE.fullmatch(universe_sha256) is not None,
        "S6_UNIVERSE_SCOPE_INVALID",
    )

    graph_receipt: dict[str, object] | None = None
    graph_receipt_sha256: str | None = None
    if advance_graph:
        graph_path = inputs / graph_name
        try:
            graph_raw = graph_path.read_bytes()
            graph_value = json.loads(graph_raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_RECEIPT_INVALID") from exc
        if not isinstance(graph_value, dict):
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
        graph_receipt = cast(dict[str, object], graph_value)
        graph_canonical = (
            json.dumps(
                graph_receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _validation_require(graph_raw == graph_canonical, "S6_GRAPH_REFRESH_RECEIPT_INVALID")
        graph_unsigned = dict(graph_receipt)
        receipt_hash_value = graph_unsigned.pop("receipt_sha256", None)
        graph_receipt_sha256 = receipt_hash_value if isinstance(receipt_hash_value, str) else None
        unsigned_canonical = (
            json.dumps(
                graph_unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _validation_require(
            graph_receipt_sha256 is not None
            and _TREE_SHA_RE.fullmatch(graph_receipt_sha256) is not None
            and hashlib.sha256(unsigned_canonical).hexdigest() == graph_receipt_sha256,
            "S6_GRAPH_REFRESH_RECEIPT_INVALID",
        )
        expected_graph_identity = {
            "candidate_sha": context.candidate_sha,
            "attempt_id": plan["attempt_id"],
            "attempt_plan_sha256": attempt_plan_sha256,
            "database": expected_database,
            "postgres_container": postgres,
            "redis_container": redis,
            "network": expected_network,
            "network_id": context.network_id,
            "postgres_container_id": context.postgres_container_id,
            "redis_container_id": context.redis_container_id,
            "execution_image_id": context.execution_image_id,
        }
        _validation_require(
            all(graph_receipt.get(key) == value for key, value in expected_graph_identity.items()),
            "S6_GRAPH_REFRESH_IDENTITY_INVALID",
        )
        _validation_require(
            graph_receipt.get("schema") == "release.s6-isolated-market-graph-refresh.v1"
            and graph_receipt.get("outcome") == "success"
            and graph_receipt.get("target_trade_date") == target_trade_date,
            "S6_GRAPH_REFRESH_RECEIPT_MISMATCH",
        )
        task_id = f"s6-market-refresh-{plan['attempt_id']}"
        task_attempt_id = graph_receipt.get("task_attempt_id")
        task_result_sha256 = graph_receipt.get("task_result_sha256")
        _validation_require(
            graph_receipt.get("task_name") == "data_center.refresh_full_market_publications"
            and graph_receipt.get("task_id") == task_id
            and isinstance(task_attempt_id, str)
            and re.fullmatch(r"[0-9a-f]{32}", task_attempt_id) is not None
            and isinstance(task_result_sha256, str)
            and _TREE_SHA_RE.fullmatch(task_result_sha256) is not None,
            "S6_GRAPH_REFRESH_TASK_MONITOR_INVALID",
        )
        task_result = graph_receipt.get("task_result")
        graph_publications = graph_receipt.get("publications")
        graph_run_id = graph_receipt.get("run_id")
        _validation_require(
            isinstance(task_result, dict)
            and isinstance(graph_publications, list)
            and all(isinstance(item, dict) for item in graph_publications)
            and isinstance(graph_run_id, str),
            "S6_GRAPH_REFRESH_TASK_RESULT_INVALID",
        )
        task_result_map = cast(dict[str, object], task_result)
        try:
            validate_market_graph_task_result(
                task_result_map,
                cast(list[dict[str, object]], graph_publications),
                target_trade_date=cast(str, target_trade_date),
                run_id=cast(str, graph_run_id),
            )
        except MarketGraphTaskResultError as exc:
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_TASK_RESULT_INVALID") from exc
        run_id = graph_receipt.get("run_id")
        activation_id = graph_receipt.get("activation_id")
        _validation_require(
            isinstance(run_id, str)
            and re.fullmatch(r"[0-9a-f-]{36}", run_id) is not None
            and isinstance(activation_id, str)
            and re.fullmatch(r"[0-9a-f-]{36}", activation_id) is not None,
            "S6_GRAPH_REFRESH_GRAPH_INVALID",
        )
        try:
            source_min = datetime.datetime.fromisoformat(
                cast(str, graph_receipt.get("source_time_min"))
            )
            source_max = datetime.datetime.fromisoformat(
                cast(str, graph_receipt.get("source_time_max"))
            )
        except (TypeError, ValueError) as exc:
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_SOURCE_TIME_INVALID") from exc
        _validation_require(
            source_min.tzinfo is not None
            and source_min.utcoffset() is not None
            and source_max.tzinfo is not None
            and source_max.utcoffset() is not None
            and source_min <= source_max,
            "S6_GRAPH_REFRESH_SOURCE_TIME_INVALID",
        )
        graph_pointers = graph_receipt.get("pointers")
        graph_publications = graph_receipt.get("publications")
        member_hashes = graph_receipt.get("member_hashes")
        fact_hashes = graph_receipt.get("fact_hashes")
        graph_datasets = {
            "equity.price.bar",
            "equity.quote.snapshot",
            "equity.valuation.fact",
        }
        _validation_require(
            isinstance(graph_pointers, list)
            and len(graph_pointers) == 3
            and all(isinstance(item, dict) for item in graph_pointers)
            and {item.get("dataset_key") for item in graph_pointers} == graph_datasets
            and isinstance(graph_publications, list)
            and len(graph_publications) == 3
            and all(isinstance(item, dict) for item in graph_publications)
            and {item.get("dataset_key") for item in graph_publications} == graph_datasets,
            "S6_GRAPH_REFRESH_GRAPH_INVALID",
        )
        _validation_require(
            isinstance(member_hashes, dict)
            and set(member_hashes) == graph_datasets
            and all(
                isinstance(value, str) and _TREE_SHA_RE.fullmatch(value) is not None
                for value in member_hashes.values()
            )
            and isinstance(fact_hashes, dict)
            and set(fact_hashes) == graph_datasets
            and all(
                isinstance(value, str) and _TREE_SHA_RE.fullmatch(value) is not None
                for value in fact_hashes.values()
            ),
            "S6_GRAPH_REFRESH_GRAPH_INVALID",
        )
        pointer_items = cast(list[dict[str, object]], graph_pointers)
        publication_items = cast(list[dict[str, object]], graph_publications)
        member_hash_map = cast(dict[str, object], member_hashes)
        pointer_map = {cast(str, item["dataset_key"]): item for item in pointer_items}
        for publication in publication_items:
            dataset_key = publication.get("dataset_key")
            pointer = pointer_map.get(cast(str, dataset_key))
            _validation_require(
                pointer is not None
                and publication.get("run_id") == run_id
                and publication.get("state") == "published"
                and publication.get("must_not_use_for_decision") is False
                and publication.get("publication_id") == pointer.get("publication_id")
                and publication.get("publication_hash") == pointer.get("publication_hash")
                and publication.get("member_manifest_hash")
                == member_hash_map.get(cast(str, dataset_key))
                and pointer.get("activation_id") == activation_id,
                "S6_GRAPH_REFRESH_GRAPH_INVALID",
            )

    source_receipt = _read_validation_json(
        context.source_receipt, "S6_CANDIDATE_SOURCE_RECEIPT_INVALID"
    )
    _validation_require(
        source_receipt.get("candidate_sha") == context.candidate_sha
        and source_receipt.get("container_gid") == context.container_gid,
        "S6_CANDIDATE_SOURCE_RECEIPT_INVALID",
    )
    tree_sha = source_receipt.get("tree_sha256")
    source_receipt_sha = source_receipt.get("receipt_sha256")
    _validation_require(
        isinstance(tree_sha, str)
        and _TREE_SHA_RE.fullmatch(tree_sha) is not None
        and isinstance(source_receipt_sha, str)
        and _TREE_SHA_RE.fullmatch(source_receipt_sha) is not None,
        "S6_CANDIDATE_SOURCE_RECEIPT_INVALID",
    )
    _validation_require(
        _EXECUTION_IMAGE_ID_RE.fullmatch(context.execution_image_id) is not None,
        "S6_EXECUTION_IMAGE_ID_INVALID",
    )
    runner_receipt_path = attempt_root / "runner-runtime-receipt.json"
    runner_receipt = _read_validation_json(runner_receipt_path, "S6_RUNNER_RUNTIME_RECEIPT_INVALID")
    _validation_require(
        runner_receipt.get("schema") == "release.s6-runner-runtime.v1"
        and runner_receipt.get("runner_python") == context.runner_python
        and runner_receipt.get("requirements_ops_sha256") == context.requirements_sha256
        and runner_receipt.get("paramiko_version") == "5.0.0"
        and runner_receipt.get("paramiko_commit") == "a4489456b6f65281e172380cc4826cee5e851dbb",
        "S6_RUNNER_RUNTIME_RECEIPT_INVALID",
    )
    output_hashes = {name: _validation_file_sha256(exports / name) for name in sorted(expected)}
    prepare_receipt: dict[str, object] = {
        "schema": "release.s6-prepare-receipt.v3",
        "outcome": "success",
        "candidate_sha": context.candidate_sha,
        "attempt_id": plan["attempt_id"],
        "attempt_plan_sha256": attempt_plan_sha256,
        "advance_isolated_market_graph": advance_graph,
        "attempt_namespace": plan["namespace"],
        "database": expected_database,
        "network": expected_network,
        "postgres_container": postgres,
        "redis_container": redis,
        "prepare_network": f"{expected_network}-prepare",
        "prepare_postgres_alias": f"{postgres}-prepare",
        "prepare_network_removed": True,
        "evidence_dir": plan["evidence_dir"],
        "provider_settings_export_path": plan["provider_settings_export_path"],
        "provider_identities_export_path": plan["provider_identities_export_path"],
        "candidate_source_tree_sha256": tree_sha,
        "candidate_source_receipt_sha256": source_receipt_sha,
        "execution_image_id": context.execution_image_id,
        "provider_settings_sha256": output_hashes["provider-settings.json"],
        "provider_identities_sha256": output_hashes["provider-identities.json"],
        "unit_contract_sha256": output_hashes["unit-contract.json"],
        "provider_policy_preflight_sha256": output_hashes["provider-policy-preflight.json"],
        "target_trade_date": target_trade_date,
        "universe_count": universe_count,
        "universe_sha256": universe_sha256,
    }
    if advance_graph and graph_receipt is not None:
        prepare_receipt.update(
            {
                "current_market_graph_refresh_sha256": output_hashes[graph_name],
                "current_market_graph_refresh_receipt_sha256": graph_receipt_sha256,
                "current_market_graph_refresh_task_id": graph_receipt["task_id"],
                "current_market_graph_refresh_attempt_id": graph_receipt["task_attempt_id"],
                "current_market_graph_refresh_run_id": graph_receipt["run_id"],
                "current_market_graph_refresh_activation_id": graph_receipt["activation_id"],
                "current_market_graph_refresh_source_time_min": graph_receipt["source_time_min"],
                "current_market_graph_refresh_source_time_max": graph_receipt["source_time_max"],
            }
        )
    receipt_path = attempt_root / "prepare-receipt.json"
    _validation_require(
        not receipt_path.exists() and not receipt_path.is_symlink(),
        "S6_PREPARE_RECEIPT_REUSE_REJECTED",
    )
    try:
        descriptor = os.open(
            receipt_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(prepare_receipt, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_PREPARE_RECEIPT_WRITE_FAILED") from exc
    return prepare_receipt


def _run_git(workspace: Path, arguments: Sequence[str], error_code: str) -> bytes:
    """Run a local Git query while hiding command diagnostics from receipts and logs."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise CandidateSourceSnapshotError(error_code) from exc
    if result.returncode != 0:
        raise CandidateSourceSnapshotError(error_code)
    return result.stdout


def _validate_workspace(workspace: Path, candidate_sha: str) -> None:
    """Require the exact candidate at a clean Git repository root."""
    if workspace.is_symlink() or not workspace.is_dir():
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_WORKSPACE_INVALID")
    try:
        resolved_workspace = workspace.resolve(strict=True)
        git_root_raw = _run_git(
            workspace, ["rev-parse", "--show-toplevel"], "S6_CANDIDATE_SOURCE_HEAD_UNAVAILABLE"
        )
        git_root = Path(os.fsdecode(git_root_raw).strip()).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_WORKSPACE_INVALID") from exc
    if resolved_workspace != git_root:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_WORKSPACE_INVALID")

    head = _run_git(
        workspace,
        ["rev-parse", "--verify", "HEAD^{commit}"],
        "S6_CANDIDATE_SOURCE_HEAD_UNAVAILABLE",
    )
    if head.decode("ascii", errors="replace").strip() != candidate_sha:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_HEAD_MISMATCH")
    status = _run_git(
        workspace,
        ["status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"],
        "S6_CANDIDATE_SOURCE_STATUS_UNAVAILABLE",
    )
    if status:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_WORKSPACE_DIRTY")


def _tracked_files(workspace: Path, candidate_sha: str) -> tuple[_TrackedBlob, ...]:
    """Return exact commit blobs, rejecting symlinks, submodules, and unsafe names."""
    raw = _run_git(
        workspace,
        ["ls-tree", "-r", "-z", "--full-tree", candidate_sha],
        "S6_CANDIDATE_SOURCE_TREE_UNAVAILABLE",
    )
    files: list[_TrackedBlob] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, relative_raw = record.split(b"\t", 1)
            mode, object_type, object_id_raw = metadata.split(b" ", 2)
            relative_text = relative_raw.decode("utf-8", errors="strict")
            object_id = object_id_raw.decode("ascii", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_ENTRY_INVALID") from exc
        relative = PurePosixPath(relative_text)
        if (
            mode not in {b"100644", b"100755"}
            or object_type != b"blob"
            or relative.is_absolute()
            or "\\" in relative_text
            or any(part in {"", ".", "..", ".git"} for part in relative.parts)
            or len(object_id) not in {40, 64}
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_ENTRY_INVALID")
        files.append(
            _TrackedBlob(
                relative_path=Path(*relative.parts),
                object_id=object_id,
                hash_name="sha1" if len(object_id) == 40 else "sha256",
            )
        )
    if not files:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_TREE_EMPTY")
    return tuple(files)


def _copy_blob(
    stream: BinaryIO,
    destination: Path,
    tracked_blob: _TrackedBlob,
) -> None:
    """Write one exact Git blob and verify its canonical object identifier."""
    try:
        header = stream.readline()
        parts = header.rstrip(b"\n").split(b" ")
        if (
            len(parts) != 3
            or parts[0].decode("ascii") != tracked_blob.object_id
            or parts[1] != b"blob"
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH")
        size = int(parts[2])
        if size < 0:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH")
        digest = hashlib.new(tracked_blob.hash_name)
        digest.update(b"blob " + str(size).encode("ascii") + b"\0")
        with destination.open("xb") as output:
            remaining = size
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH")
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1) != b"\n" or digest.hexdigest() != tracked_blob.object_id:
                raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH")
            output.flush()
            os.fsync(output.fileno())
    except CandidateSourceSnapshotError:
        raise
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH") from exc


def _copy_tracked_tree(
    workspace: Path,
    destination: Path,
    files: tuple[_TrackedBlob, ...],
) -> tuple[int, int]:
    """Copy exact Git blobs into a new snapshot without reading clone file modes."""
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_SNAPSHOT_FAILED") from exc

    directories: set[Path] = {Path(".")}
    batch_input = b"".join(blob.object_id.encode("ascii") + b"\n" for blob in files)
    try:
        with tempfile.TemporaryFile() as temporary_blob_stream:
            blob_stream = cast(BinaryIO, temporary_blob_stream)
            result = subprocess.run(
                ["git", "-C", str(workspace), "cat-file", "--batch"],
                input=batch_input,
                stdout=blob_stream,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode != 0:
                raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_BLOB_UNAVAILABLE")
            blob_stream.seek(0)
            for tracked in files:
                relative = tracked.relative_path
                for parent in relative.parents:
                    if parent == Path("."):
                        continue
                    directories.add(parent)
                target = destination / relative
                try:
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                except OSError as exc:
                    raise CandidateSourceSnapshotError(
                        "S6_CANDIDATE_SOURCE_SNAPSHOT_FAILED"
                    ) from exc
                _copy_blob(blob_stream, target, tracked)
            if blob_stream.read(1):
                raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_OBJECT_MISMATCH")
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_BLOB_UNAVAILABLE") from exc
    return len(files), len(directories)


def _seal_error_factory(_stage: str, source_code: str) -> Exception:
    """Map shared input-tree sealing diagnostics to candidate-source stable codes."""
    if source_code == "S6_CONTAINER_INPUT_TREE_INVALID":
        return CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_ENTRY_INVALID")
    if source_code == "S6_CONTAINER_INPUT_TREE_CHANGED":
        return CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_TREE_CHANGED")
    return CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_PERMISSIONS_FAILED")


def _write_receipt(path: Path, receipt: CandidateSourceReceipt) -> None:
    """Write one exclusive, read-only JSON receipt without exposing source contents."""
    raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        path.chmod(0o444)
        if stat.S_IMODE(path.stat().st_mode) != 0o444:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_FAILED")
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_FAILED") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _receipt_digest(fields: dict[str, object]) -> str:
    """Hash canonical receipt fields, excluding the digest field itself."""
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_receipt(path: Path) -> CandidateSourceReceipt:
    """Load and structurally validate the non-secret source snapshot receipt."""
    if path.is_symlink() or not path.is_file():
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o222:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except CandidateSourceSnapshotError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID") from exc
    if not isinstance(value, dict):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")

    schema = value.get("schema")
    outcome = value.get("outcome")
    candidate_sha = value.get("candidate_sha")
    snapshot_name = value.get("snapshot_name")
    tree_sha256 = value.get("tree_sha256")
    file_count = value.get("file_count")
    directory_count = value.get("directory_count")
    container_gid = value.get("container_gid")
    receipt_sha256 = value.get("receipt_sha256")
    permission_model = value.get("permission_model")
    directory_mode = value.get("directory_mode")
    file_mode = value.get("file_mode")
    expected_keys = {
        "schema",
        "outcome",
        "candidate_sha",
        "snapshot_name",
        "tree_sha256",
        "file_count",
        "directory_count",
        "container_gid",
        "receipt_sha256",
        "permission_model",
        "directory_mode",
        "file_mode",
    }
    if (
        set(value) != expected_keys
        or schema != "release.s6-candidate-source-snapshot.v1"
        or outcome != "success"
        or not isinstance(candidate_sha, str)
        or _CANDIDATE_SHA_RE.fullmatch(candidate_sha) is None
        or not isinstance(snapshot_name, str)
        or not snapshot_name
        or not isinstance(tree_sha256, str)
        or _TREE_SHA_RE.fullmatch(tree_sha256) is None
        or isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 1
        or isinstance(directory_count, bool)
        or not isinstance(directory_count, int)
        or directory_count < 1
        or isinstance(container_gid, bool)
        or not isinstance(container_gid, int)
        or container_gid < 0
        or not isinstance(receipt_sha256, str)
        or _TREE_SHA_RE.fullmatch(receipt_sha256) is None
        or not isinstance(permission_model, str)
        or permission_model not in {"posix_descriptor_group", "portable_mode_only"}
        or not isinstance(directory_mode, str)
        or directory_mode not in {"0550", "0555"}
        or not isinstance(file_mode, str)
        or file_mode not in {"0440", "0444"}
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
    receipt_fields: dict[str, object] = {
        "schema": schema,
        "outcome": outcome,
        "candidate_sha": candidate_sha,
        "snapshot_name": snapshot_name,
        "tree_sha256": tree_sha256,
        "file_count": file_count,
        "directory_count": directory_count,
        "container_gid": container_gid,
        "permission_model": permission_model,
        "directory_mode": directory_mode,
        "file_mode": file_mode,
    }
    if _receipt_digest(receipt_fields) != receipt_sha256:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_DIGEST_MISMATCH")
    return {
        "schema": schema,
        "outcome": outcome,
        "candidate_sha": candidate_sha,
        "snapshot_name": snapshot_name,
        "tree_sha256": tree_sha256,
        "file_count": file_count,
        "directory_count": directory_count,
        "container_gid": container_gid,
        "receipt_sha256": receipt_sha256,
        "permission_model": permission_model,
        "directory_mode": directory_mode,
        "file_mode": file_mode,
    }


def verify_candidate_source_snapshot(
    *,
    destination: Path,
    receipt_path: Path,
    candidate_sha: str,
    container_gid: int,
) -> CandidateSourceReceipt:
    """Recheck snapshot identity, receipt digest, group, and read-only modes before mounting."""
    if _CANDIDATE_SHA_RE.fullmatch(candidate_sha) is None:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_SHA_INVALID")
    if isinstance(container_gid, bool) or not isinstance(container_gid, int) or container_gid < 0:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_GID_INVALID")
    receipt = _load_receipt(receipt_path)
    expected_permission_model = (
        "posix_descriptor_group" if os.name == "posix" else "portable_mode_only"
    )
    expected_directory_mode = "0550" if os.name == "posix" else "0555"
    expected_file_mode = "0440" if os.name == "posix" else "0444"
    if (
        receipt["candidate_sha"] != candidate_sha
        or receipt["snapshot_name"] != destination.name
        or receipt["container_gid"] != container_gid
        or receipt["permission_model"] != expected_permission_model
        or receipt["directory_mode"] != expected_directory_mode
        or receipt["file_mode"] != expected_file_mode
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_BINDING_MISMATCH")
    try:
        verify_container_input_tree(destination, container_gid, _seal_error_factory)
        actual_digest = tree_digest(destination)
    except CandidateSourceSnapshotError:
        raise
    except (OSError, ValueError) as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_ENTRY_INVALID") from exc
    if actual_digest != receipt["tree_sha256"]:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_TREE_DIGEST_MISMATCH")
    return receipt


def run_candidate_export(
    *,
    mode: str,
    docker_argv: Sequence[str],
    destination: Path,
    receipt_path: Path,
    candidate_sha: str,
    container_gid: int,
    container_uid: int,
    execution_image: str,
    input_directory: Path,
    output_directory: Path,
    execution_env_file: Path,
    docker_network: str,
    log_path: Path,
) -> None:
    """Run sealed candidate code in one immutable dependency execution image."""
    error_code = _EXPORT_FAILURE_CODES.get(mode)
    if error_code is None:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_MODE_INVALID")
    if isinstance(container_uid, bool) or not isinstance(container_uid, int) or container_uid <= 0:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID")
    if (
        not isinstance(execution_image, str)
        or _EXECUTION_IMAGE_ID_RE.fullmatch(execution_image) is None
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_EXECUTION_IMAGE_INVALID")
    if (
        not isinstance(docker_network, str)
        or re.fullmatch(r"agom-s6-network-[a-z0-9-]+-prepare", docker_network) is None
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_NETWORK_INVALID")
    try:
        resolved_input = input_directory.resolve(strict=True)
        resolved_output = output_directory.resolve(strict=True)
        resolved_env = execution_env_file.resolve(strict=True)
        resolved_source = destination.resolve(strict=True)
        if (
            input_directory.is_symlink()
            or output_directory.is_symlink()
            or execution_env_file.is_symlink()
            or not resolved_input.is_dir()
            or not resolved_output.is_dir()
            or not resolved_env.is_file()
            or _paths_overlap(resolved_source, resolved_input)
            or _paths_overlap(resolved_source, resolved_output)
            or _paths_overlap(resolved_input, resolved_output)
            or _is_relative_to(resolved_env, resolved_output)
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_PATH_INVALID")
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_PATH_INVALID") from exc
    verify_candidate_source_snapshot(
        destination=destination,
        receipt_path=receipt_path,
        candidate_sha=candidate_sha,
        container_gid=container_gid,
    )
    if (
        not docker_argv
        or Path(docker_argv[0]).name not in {"docker", "docker.exe"}
        or len(docker_argv) < 3
        or docker_argv[1] != "run"
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")

    image_positions = [
        index
        for index, argument in enumerate(docker_argv[2:], start=2)
        if argument == execution_image
    ]
    if len(image_positions) != 1:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_EXECUTION_IMAGE_INVALID")
    image_index = image_positions[0]
    docker_options = docker_argv[2:image_index]

    expected_mount = f"{resolved_source}:/candidate-src:ro"
    docker_users: list[str] = []
    volume_values: list[str] = []
    env_file_values: list[str] = []
    entrypoint_values: list[str] = []
    network_values: list[str] = []
    tmpfs_values: list[str] = []
    environment_values: list[str] = []
    flags: list[str] = []
    flag_options = {"--rm", "--read-only"}
    value_options = {
        "--env-file",
        "--entrypoint",
        "--network",
        "--tmpfs",
        "--user",
        "--volume",
        "-e",
        "-u",
        "-v",
    }
    index = 0
    while index < len(docker_options):
        argument = docker_options[index]
        if argument in flag_options:
            flags.append(argument)
            index += 1
            continue
        if argument == "--mount" or argument.startswith("--mount="):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_SOURCE_MOUNT_INVALID")
        if argument in value_options:
            if index + 1 >= len(docker_options):
                raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")
            value = docker_options[index + 1]
            if argument in {"--user", "-u"}:
                docker_users.append(value)
            elif argument in {"--volume", "-v"}:
                volume_values.append(value)
            elif argument == "--env-file":
                env_file_values.append(value)
            elif argument == "--entrypoint":
                entrypoint_values.append(value)
            elif argument == "--network":
                network_values.append(value)
            elif argument == "--tmpfs":
                tmpfs_values.append(value)
            elif argument == "-e":
                environment_values.append(value)
            index += 2
            continue
        matched_option = next(
            (
                option
                for option in value_options
                if option.startswith("--") and argument.startswith(f"{option}=")
            ),
            None,
        )
        if matched_option is not None:
            value = argument.partition("=")[2]
            if matched_option == "--user":
                docker_users.append(value)
            elif matched_option == "--volume":
                volume_values.append(value)
            elif matched_option == "--env-file":
                env_file_values.append(value)
            elif matched_option == "--entrypoint":
                entrypoint_values.append(value)
            elif matched_option == "--network":
                network_values.append(value)
            elif matched_option == "--tmpfs":
                tmpfs_values.append(value)
            index += 1
            continue
        if argument.startswith("-u") and len(argument) > 2:
            docker_users.append(argument[2:].removeprefix("="))
            index += 1
            continue
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")
    if docker_users != [f"{container_uid}:{container_gid}"]:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID")
    expected_volumes = [
        expected_mount,
        f"{resolved_input}:/candidate-inputs:ro",
        f"{resolved_output}:/candidate-output:rw",
    ]
    expected_environment_keys = {
        RUNTIME_LOG_DIRECTORY_ENV,
        "PGOPTIONS",
        "S6_ADVANCE_ISOLATED_MARKET_GRAPH",
        "S6_ATTEMPT_ID",
        "S6_ATTEMPT_PLAN_SHA256",
        "S6_DATABASE",
        "S6_EXECUTION_IMAGE_ID",
        "S6_EXPECTED_CANDIDATE",
        "S6_EXPECTED_DB",
        "S6_NETWORK",
        "S6_NETWORK_ID",
        "S6_PG_CONTAINER",
        "S6_PG_CONTAINER_ID",
        "S6_REDIS_CONTAINER",
        "S6_REDIS_CONTAINER_ID",
    }
    environment: dict[str, str] = {}
    for value in environment_values:
        key, separator, content = value.partition("=")
        if not separator or key in environment:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_ENVIRONMENT_INVALID")
        environment[key] = content
    if volume_values != expected_volumes:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_SOURCE_MOUNT_INVALID")
    if (
        env_file_values != [str(resolved_env)]
        or network_values != [docker_network]
        or set(environment) != expected_environment_keys
        or environment.get("S6_EXPECTED_CANDIDATE") != candidate_sha
        or environment.get(RUNTIME_LOG_DIRECTORY_ENV) != READ_ONLY_RUNTIME_LOG_DIRECTORY
        or environment.get("S6_ADVANCE_ISOLATED_MARKET_GRAPH") not in {"0", "1"}
        or re.fullmatch(r"[0-9a-f]{32}", environment.get("S6_ATTEMPT_ID", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", environment.get("S6_ATTEMPT_PLAN_SHA256", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", environment.get("S6_PG_CONTAINER_ID", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", environment.get("S6_REDIS_CONTAINER_ID", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", environment.get("S6_NETWORK_ID", "")) is None
        or environment.get("S6_EXECUTION_IMAGE_ID") != execution_image
        or environment.get("S6_DATABASE") != environment.get("S6_EXPECTED_DB")
        or environment.get("PGOPTIONS")
        != "-c default_transaction_read_only=on -c transaction_read_only=on"
        or any(not value for key, value in environment.items() if key != "PGOPTIONS")
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_ENVIRONMENT_INVALID")
    if (
        flags != ["--rm", "--read-only"]
        or entrypoint_values != ["python"]
        or tmpfs_values != ["/tmp:rw,nosuid,nodev,mode=1777,size=2147483648"]
        or docker_argv[image_index + 1 :]
        != ["/candidate-src/scripts/export_s6_rehearsal_inputs.py", mode]
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")

    try:
        log_parent = log_path.parent.resolve(strict=True)
        receipt_parent = receipt_path.parent.resolve(strict=True)
        if (
            log_parent != receipt_parent
            or log_path.is_symlink()
            or log_path.exists()
            or log_path.parent.is_symlink()
            or receipt_path.parent.is_symlink()
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_LOG_INVALID")
        descriptor = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_LOG_INVALID") from exc

    try:
        with os.fdopen(descriptor, "wb") as log_stream:
            try:
                result = subprocess.run(
                    list(docker_argv),
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            except OSError as exc:
                raise CandidateSourceSnapshotError(error_code) from exc
            log_stream.flush()
            os.fsync(log_stream.fileno())
        if result.returncode != 0:
            raise CandidateSourceSnapshotError(error_code)
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError(error_code) from exc


def run_candidate_market_graph_refresh(
    *,
    docker_argv: Sequence[str],
    destination: Path,
    receipt_path: Path,
    candidate_sha: str,
    container_gid: int,
    container_uid: int,
    execution_image: str,
    input_directory: Path,
    output_directory: Path,
    execution_env_file: Path,
    docker_network: str,
    attempt_id: str,
    attempt_plan_sha256: str,
    database: str,
    postgres_container: str,
    redis_container: str,
    postgres_container_id: str,
    redis_container_id: str,
    network_id: str,
    log_path: Path,
) -> None:
    """Run the fixed plan-bound refresh command against the disposable S6 runtime."""

    if isinstance(container_uid, bool) or not isinstance(container_uid, int) or container_uid <= 0:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID")
    if (
        not isinstance(execution_image, str)
        or _EXECUTION_IMAGE_ID_RE.fullmatch(execution_image) is None
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_EXECUTION_IMAGE_INVALID")
    if re.fullmatch(r"agom-s6-network-[a-z0-9-]+", docker_network) is None:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_NETWORK_INVALID")
    if (
        re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", attempt_plan_sha256) is None
    ):
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if re.fullmatch(r"agom_release_rehearsal_[a-f0-9]{32}", database) is None:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (
            postgres_container_id,
            redis_container_id,
            network_id,
        )
    ):
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_CONTAINER_IDENTITY_INVALID")
    try:
        resolved_input = input_directory.resolve(strict=True)
        resolved_output = output_directory.resolve(strict=True)
        resolved_env = execution_env_file.resolve(strict=True)
        resolved_source = destination.resolve(strict=True)
        if (
            input_directory.is_symlink()
            or output_directory.is_symlink()
            or execution_env_file.is_symlink()
            or not resolved_input.is_dir()
            or not resolved_output.is_dir()
            or not resolved_env.is_file()
            or _paths_overlap(resolved_source, resolved_input)
            or _paths_overlap(resolved_source, resolved_output)
            or _paths_overlap(resolved_input, resolved_output)
            or _is_relative_to(resolved_env, resolved_output)
        ):
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_PATH_INVALID")
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_PATH_INVALID") from exc
    verify_candidate_source_snapshot(
        destination=destination,
        receipt_path=receipt_path,
        candidate_sha=candidate_sha,
        container_gid=container_gid,
    )
    task_id = f"s6-market-refresh-{attempt_id}"
    expected_argv = [
        "docker",
        "run",
        "--rm",
        "--read-only",
        "--user",
        f"{container_uid}:{container_gid}",
        "--network",
        docker_network,
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777,size=2147483648",
        "--env-file",
        str(resolved_env),
        "-e",
        f"{RUNTIME_LOG_DIRECTORY_ENV}={READ_ONLY_RUNTIME_LOG_DIRECTORY}",
        "-e",
        "S6_GRAPH_REFRESH_ENABLED=1",
        "-v",
        f"{resolved_source}:/candidate-src:ro",
        "-v",
        f"{resolved_input}:/candidate-inputs:ro",
        "-v",
        f"{resolved_output}:/candidate-output:rw",
        "--entrypoint",
        "python",
        execution_image,
        "/candidate-src/scripts/refresh_s6_isolated_market_graph.py",
        "--candidate-sha",
        candidate_sha,
        "--attempt-id",
        attempt_id,
        "--attempt-plan-sha256",
        attempt_plan_sha256,
        "--database",
        database,
        "--postgres-container",
        postgres_container,
        "--redis-container",
        redis_container,
        "--database-container-id",
        postgres_container_id,
        "--redis-container-id",
        redis_container_id,
        "--network",
        docker_network,
        "--network-id",
        network_id,
        "--execution-image-id",
        execution_image,
        "--task-id",
        task_id,
    ]
    if list(docker_argv) != expected_argv:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_COMMAND_INVALID")
    expected_report = resolved_output / "current-market-graph-refresh.json"
    try:
        if (
            log_path.is_symlink()
            or log_path.exists()
            or log_path.parent.is_symlink()
            or not log_path.parent.is_dir()
            or expected_report.is_symlink()
            or expected_report.exists()
        ):
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_OUTPUT_COLLISION")
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_LOG_INVALID") from exc
    try:
        with os.fdopen(descriptor, "wb") as log_stream:
            try:
                result = subprocess.run(
                    list(docker_argv),
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            except OSError as exc:
                raise CandidateSourceSnapshotError(_GRAPH_REFRESH_FAILURE_CODE) from exc
            log_stream.flush()
            os.fsync(log_stream.fileno())
        if result.returncode != 0:
            raise CandidateSourceSnapshotError(_GRAPH_REFRESH_FAILURE_CODE)
        metadata = expected_report.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
        value = json.loads(expected_report.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "release.s6-isolated-market-graph-refresh.v1"
            or value.get("outcome") != "success"
            or value.get("candidate_sha") != candidate_sha
            or value.get("attempt_id") != attempt_id
            or value.get("attempt_plan_sha256") != attempt_plan_sha256
            or value.get("database") != database
            or value.get("task_id") != task_id
        ):
            raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
    except CandidateSourceSnapshotError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_RECEIPT_INVALID") from exc


def create_candidate_source_snapshot(
    *,
    workspace: Path,
    candidate_sha: str,
    destination: Path,
    receipt_path: Path,
    container_gid: int,
) -> CandidateSourceReceipt:
    """Copy a clean exact-candidate tree, seal it for candidate GID, and publish a receipt."""
    if _CANDIDATE_SHA_RE.fullmatch(candidate_sha) is None:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_SHA_INVALID")
    if isinstance(container_gid, bool) or not isinstance(container_gid, int) or container_gid < 0:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_GID_INVALID")

    try:
        resolved_workspace = workspace.resolve(strict=True)
        resolved_destination = destination.resolve(strict=False)
        resolved_receipt = receipt_path.resolve(strict=False)
        if (
            resolved_destination == resolved_workspace
            or resolved_workspace in resolved_destination.parents
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_DESTINATION_INVALID")
        if resolved_receipt == resolved_workspace or resolved_workspace in resolved_receipt.parents:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
        if (
            resolved_receipt == resolved_destination
            or resolved_destination in resolved_receipt.parents
            or resolved_receipt in resolved_destination.parents
        ):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
        if destination.is_symlink() or destination.exists():
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_SNAPSHOT_EXISTS")
        if receipt_path.is_symlink() or receipt_path.exists():
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_EXISTS")
        if destination.parent.is_symlink() or not destination.parent.is_dir():
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_DESTINATION_INVALID")
        if receipt_path.parent.is_symlink() or not receipt_path.parent.is_dir():
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
    except CandidateSourceSnapshotError:
        raise
    except OSError as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_PATH_INVALID") from exc

    _validate_workspace(workspace, candidate_sha)
    tracked = _tracked_files(workspace, candidate_sha)
    file_count, directory_count = _copy_tracked_tree(workspace, destination, tracked)
    _validate_workspace(workspace, candidate_sha)

    try:
        seal_container_input_tree(destination, container_gid, _seal_error_factory)
        tree_sha256 = tree_digest(destination)
    except CandidateSourceSnapshotError:
        raise
    except (OSError, ValueError) as exc:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_PERMISSIONS_FAILED") from exc

    posix = os.name == "posix"
    receipt: CandidateSourceReceipt = {
        "schema": "release.s6-candidate-source-snapshot.v1",
        "outcome": "success",
        "candidate_sha": candidate_sha,
        "snapshot_name": destination.name,
        "tree_sha256": tree_sha256,
        "file_count": file_count,
        "directory_count": directory_count,
        "container_gid": container_gid,
        "receipt_sha256": "",
        "permission_model": "posix_descriptor_group" if posix else "portable_mode_only",
        "directory_mode": "0550" if posix else "0555",
        "file_mode": "0440" if posix else "0444",
    }
    receipt["receipt_sha256"] = _receipt_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    _write_receipt(receipt_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    """Create a candidate source snapshot and emit only a non-secret receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--container-gid", type=int, required=True)
    parser.add_argument("--container-uid", type=int)
    parser.add_argument("--execution-image")
    parser.add_argument("--input-directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--execution-env-file", type=Path)
    parser.add_argument("--docker-network")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--run-export", action="store_true")
    parser.add_argument("--run-market-graph-refresh", action="store_true")
    parser.add_argument("--validate-final-receipt", action="store_true")
    parser.add_argument("--export-mode")
    parser.add_argument("--docker-arg", action="append", default=[])
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--attempt-plan-sha256")
    parser.add_argument("--database")
    parser.add_argument("--postgres-container")
    parser.add_argument("--redis-container")
    parser.add_argument("--postgres-container-id")
    parser.add_argument("--redis-container-id")
    parser.add_argument("--network-id")
    parser.add_argument("--runner-python")
    parser.add_argument("--requirements-sha256")
    args = parser.parse_args(argv)

    receipt: dict[str, object] | CandidateSourceReceipt
    try:
        selected_modes = sum(
            bool(value)
            for value in (
                args.verify_only,
                args.run_export,
                args.run_market_graph_refresh,
                args.validate_final_receipt,
            )
        )
        if selected_modes > 1 or (args.run_export and args.run_market_graph_refresh):
            raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")
        if args.validate_final_receipt:
            required = (
                args.container_uid,
                args.execution_image,
                args.input_directory,
                args.output_directory,
                args.postgres_container_id,
                args.redis_container_id,
                args.network_id,
                args.runner_python,
                args.requirements_sha256,
            )
            if any(value is None for value in required):
                raise CandidateSourceSnapshotError("S6_PREPARE_FINAL_VALIDATION_FAILED")
            if any(
                _TREE_SHA_RE.fullmatch(value) is None
                for value in (
                    args.postgres_container_id,
                    args.redis_container_id,
                    args.network_id,
                    args.requirements_sha256,
                )
            ):
                raise CandidateSourceSnapshotError("S6_PREPARE_FINAL_VALIDATION_FAILED")
            receipt = validate_final_prepare_receipt(
                _FinalPrepareValidation(
                    candidate_sha=args.candidate_sha,
                    source_directory=args.destination,
                    source_receipt=args.receipt,
                    container_uid=args.container_uid,
                    container_gid=args.container_gid,
                    execution_image_id=args.execution_image,
                    inputs=args.input_directory,
                    exports=args.output_directory,
                    runner_python=args.runner_python,
                    requirements_sha256=args.requirements_sha256,
                    postgres_container_id=args.postgres_container_id,
                    redis_container_id=args.redis_container_id,
                    network_id=args.network_id,
                )
            )
        elif args.run_market_graph_refresh:
            if any(
                value is None
                for value in (
                    args.log_path,
                    args.attempt_id,
                    args.attempt_plan_sha256,
                    args.database,
                    args.postgres_container,
                    args.redis_container,
                    args.postgres_container_id,
                    args.redis_container_id,
                    args.network_id,
                )
            ):
                raise CandidateSourceSnapshotError("S6_GRAPH_REFRESH_COMMAND_INVALID")
            run_candidate_market_graph_refresh(
                docker_argv=args.docker_arg,
                destination=args.destination,
                receipt_path=args.receipt,
                candidate_sha=args.candidate_sha,
                container_gid=args.container_gid,
                container_uid=args.container_uid if args.container_uid is not None else 0,
                execution_image=args.execution_image or "",
                input_directory=args.input_directory or Path(""),
                output_directory=args.output_directory or Path(""),
                execution_env_file=args.execution_env_file or Path(""),
                docker_network=args.docker_network or "",
                attempt_id=args.attempt_id,
                attempt_plan_sha256=args.attempt_plan_sha256,
                database=args.database,
                postgres_container=args.postgres_container,
                redis_container=args.redis_container,
                postgres_container_id=args.postgres_container_id,
                redis_container_id=args.redis_container_id,
                network_id=args.network_id,
                log_path=args.log_path,
            )
            receipt = _load_receipt(args.receipt)
        elif args.run_export:
            if args.log_path is None:
                raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_LOG_INVALID")
            run_candidate_export(
                mode=args.export_mode or "",
                docker_argv=args.docker_arg,
                destination=args.destination,
                receipt_path=args.receipt,
                candidate_sha=args.candidate_sha,
                container_gid=args.container_gid,
                container_uid=args.container_uid if args.container_uid is not None else 0,
                execution_image=args.execution_image or "",
                input_directory=args.input_directory or Path(""),
                output_directory=args.output_directory or Path(""),
                execution_env_file=args.execution_env_file or Path(""),
                docker_network=args.docker_network or "",
                log_path=args.log_path,
            )
            receipt = _load_receipt(args.receipt)
        elif args.verify_only:
            receipt = verify_candidate_source_snapshot(
                destination=args.destination,
                receipt_path=args.receipt,
                candidate_sha=args.candidate_sha,
                container_gid=args.container_gid,
            )
        elif args.workspace is None:
            raise CandidateSourceSnapshotError("S6_CANDIDATE_SOURCE_WORKSPACE_REQUIRED")
        else:
            receipt = create_candidate_source_snapshot(
                workspace=args.workspace,
                candidate_sha=args.candidate_sha,
                destination=args.destination,
                receipt_path=args.receipt,
                container_gid=args.container_gid,
            )
    except CandidateSourceSnapshotError as exc:
        print(
            json.dumps({"outcome": "failed", "error": exc.error_code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(
            json.dumps(
                {"outcome": "failed", "error": "S6_CANDIDATE_SOURCE_FAILED"}, sort_keys=True
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps({"outcome": "success", "receipt": receipt}, ensure_ascii=False, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
