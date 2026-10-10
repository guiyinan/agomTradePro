"""Red/green contracts for the aggregate S6 stage environment preflight."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.run_release_rehearsal import STAGES
from shared.release_rehearsal_stage_environment import (
    ALLOWED_ISSUE_CODES,
    BUILD_DISK_RESERVE_BYTES,
    CATEGORIES,
    CONTRACT_STAGES,
    MINIMUM_AVAILABLE_MEMORY_BYTES,
    MINIMUM_FREE_DISK_BYTES,
    MINIMUM_PREBUILD_FREE_DISK_BYTES,
    StageEnvironmentInputs,
    StageEnvironmentIssue,
    evaluate_stage_environment,
    load_docker_build_policy,
    parse_docker_build_observation,
    parse_docker_build_policy,
)


def _inputs(tmp_path: Path) -> StageEnvironmentInputs:
    transport = tmp_path / "prepare.sh"
    transport.write_bytes(b"#!/bin/sh\nset -eu\n")
    return StageEnvironmentInputs(
        stages=("provider_probe", "akshare_financial_slice"),
        filesystem_paths=(tmp_path, transport),
        text_transport_paths=(transport,),
        missing_identity_keys=(),
        free_disk_bytes=MINIMUM_FREE_DISK_BYTES,
        available_memory_bytes=MINIMUM_AVAILABLE_MEMORY_BYTES,
        observed_at=datetime.now(UTC),
        build_timeout_seconds=9000,
        stage_timeout_seconds=9000,
        provider_timeout_seconds=3600,
        task_deadline_seconds=5400,
        lock_wait_limit_seconds=10,
    )


def _docker_build_policy():
    policy_path = (
        Path(__file__).resolve().parents[2] / "governance" / "release_rehearsal_policy.json"
    )
    return load_docker_build_policy(policy_path)


def test_governed_stage_environment_contract_matches_runtime_registry() -> None:
    policy_path = (
        Path(__file__).resolve().parents[2] / "governance" / "release_rehearsal_policy.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    contract = policy["stage_environment_contract"]

    assert contract["schema"] == "release.s6-stage-environment-contract.v1"
    assert contract["categories"] == list(CATEGORIES)
    assert contract["stages"] == list(CONTRACT_STAGES)
    assert contract["minimum_free_disk_bytes"] == MINIMUM_FREE_DISK_BYTES
    assert contract["minimum_prebuild_free_disk_bytes"] == MINIMUM_PREBUILD_FREE_DISK_BYTES
    assert MINIMUM_PREBUILD_FREE_DISK_BYTES == (MINIMUM_FREE_DISK_BYTES + BUILD_DISK_RESERVE_BYTES)
    assert contract["minimum_available_memory_bytes"] == MINIMUM_AVAILABLE_MEMORY_BYTES
    docker_policy = load_docker_build_policy(policy_path)
    assert docker_policy.builder_mode == "legacy"
    assert docker_policy.minimum_server_version == "29.3.2"
    assert policy["docker_build_policy"]["known_vulnerable_server_versions"] == [
        "29.3.0",
        "29.3.1",
    ]


@pytest.mark.parametrize("category", CATEGORIES)
def test_each_registered_category_has_a_passing_cell(tmp_path: Path, category: str) -> None:
    report = evaluate_stage_environment(_inputs(tmp_path))

    cell = next(
        item
        for item in report["matrix"]
        if item["stage"] == "provider_probe" and item["category"] == category
    )
    assert report["outcome"] == "pass"
    assert cell == {
        "stage": "provider_probe",
        "category": category,
        "outcome": "pass",
        "codes": [],
    }


def test_missing_runner_dependency_fails_build_only_without_leaking_name(tmp_path: Path) -> None:
    inputs = replace(
        _inputs(tmp_path),
        stages=("build_only", "docker_identity"),
        missing_runtime_dependencies=("paramiko",),
        docker_build_policy=_docker_build_policy(),
    )

    report = evaluate_stage_environment(inputs)

    assert report["outcome"] == "blocked"
    assert report["issues"] == [
        {
            "category": "identity_and_secrets",
            "code": "REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING",
            "stages": ["build_only"],
        }
    ]
    assert "paramiko" not in json.dumps(report)


def test_prebuild_reserve_preserves_post_build_stage_headroom(tmp_path: Path) -> None:
    inputs = replace(
        _inputs(tmp_path),
        stages=("build_only", "docker_identity"),
        free_disk_bytes=MINIMUM_PREBUILD_FREE_DISK_BYTES - 1,
        minimum_free_disk_bytes=MINIMUM_PREBUILD_FREE_DISK_BYTES,
        docker_build_policy=_docker_build_policy(),
    )

    report = evaluate_stage_environment(inputs)

    assert report["outcome"] == "blocked"
    assert report["observations"]["minimum_free_disk_bytes"] == (MINIMUM_PREBUILD_FREE_DISK_BYTES)
    assert report["issues"] == [
        {
            "category": "resources_and_time",
            "code": "REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT",
            "stages": ["build_only", "docker_identity"],
        }
    ]


@pytest.mark.parametrize(
    "defect",
    [
        {"builder_mode": "buildkit"},
        {"daemon_endpoint": "tcp://docker:2375"},
        {"minimum_server_version": "29.3.1"},
        {"minimum_client_version": "29.3.0"},
        {"maximum_client_version_exclusive": "31.0.0"},
        {"known_vulnerable_server_versions": ["29.3.0"]},
    ],
)
def test_docker_build_policy_rejects_unsafe_or_unmodeled_values(defect: dict[str, object]) -> None:
    policy_path = (
        Path(__file__).resolve().parents[2] / "governance" / "release_rehearsal_policy.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))["docker_build_policy"]
    policy.update(defect)

    with pytest.raises(ValueError, match="REHEARSAL_DOCKER_BUILDER_POLICY_INVALID"):
        parse_docker_build_policy(policy)


@pytest.mark.parametrize(
    ("client_version", "server_version", "mode", "endpoint", "confirmed"),
    [
        ("29.3.2", "29.3.0", "legacy", "unix:///var/run/docker.sock", True),
        ("29.3.2", "29.3.1", "legacy", "unix:///var/run/docker.sock", True),
        ("29.3.2", "invalid", "legacy", "unix:///var/run/docker.sock", True),
        ("30.0.0", "29.3.2", "legacy", "unix:///var/run/docker.sock", True),
        ("29.3.2", "29.3.2", "buildkit", "unix:///var/run/docker.sock", True),
        ("29.3.2", "29.3.2", "legacy", "tcp://docker:2375", True),
        ("29.3.2", "29.3.2", "legacy", "unix:///var/run/docker.sock", False),
    ],
)
def test_docker_build_observation_faults_fail_closed(
    client_version: str,
    server_version: str,
    mode: str,
    endpoint: str,
    confirmed: bool,
) -> None:
    observation = {
        "builder_mode": mode,
        "daemon_endpoint": endpoint,
        "client_version": client_version,
        "server_version": server_version,
        "legacy_mode_confirmed": confirmed,
    }

    with pytest.raises(ValueError, match="REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED"):
        parse_docker_build_observation(observation, _docker_build_policy())


@pytest.mark.parametrize(
    ("category", "mutator", "expected_code"),
    [
        (
            "filesystem",
            lambda value, root: replace(value, filesystem_paths=(root / "missing",)),
            "REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID",
        ),
        (
            "transfer_encoding",
            lambda value, root: _with_cr_transport(value, root),
            "REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID",
        ),
        (
            "network_egress",
            lambda value, _root: replace(
                value,
                dynamic_issues=(
                    StageEnvironmentIssue(
                        "network_egress",
                        "REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID",
                        ("provider_probe",),
                    ),
                ),
            ),
            "REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID",
        ),
        (
            "identity_and_secrets",
            lambda value, _root: replace(value, missing_identity_keys=("SECRET_REF",)),
            "REHEARSAL_STAGE_IDENTITY_OR_SECRET_CONTRACT_INVALID",
        ),
        (
            "resources_and_time",
            lambda value, _root: replace(value, free_disk_bytes=0),
            "REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT",
        ),
        (
            "external_state",
            lambda value, _root: replace(
                value,
                dynamic_issues=(
                    StageEnvironmentIssue(
                        "external_state",
                        "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
                        ("akshare_financial_slice",),
                    ),
                ),
            ),
            "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
        ),
    ],
)
def test_each_category_fails_closed(
    tmp_path: Path,
    category: str,
    mutator: Callable[[StageEnvironmentInputs, Path], StageEnvironmentInputs],
    expected_code: str,
) -> None:
    changed = mutator(_inputs(tmp_path), tmp_path)
    report = evaluate_stage_environment(changed)

    issues = report["issues"]
    assert report["outcome"] == "blocked"
    assert any(item["category"] == category and item["code"] == expected_code for item in issues)


def test_candidate_runtime_log_directory_issue_blocks_filesystem_stage_cell(
    tmp_path: Path,
) -> None:
    inputs = replace(
        _inputs(tmp_path),
        dynamic_issues=(
            StageEnvironmentIssue(
                "filesystem",
                "REHEARSAL_STAGE_RUNTIME_LOG_DIRECTORY_INVALID",
                ("provider_probe",),
            ),
        ),
    )

    report = evaluate_stage_environment(inputs)

    cell = next(
        item
        for item in report["matrix"]
        if item["stage"] == "provider_probe" and item["category"] == "filesystem"
    )
    assert report["outcome"] == "blocked"
    assert cell == {
        "stage": "provider_probe",
        "category": "filesystem",
        "outcome": "blocked",
        "codes": ["REHEARSAL_STAGE_RUNTIME_LOG_DIRECTORY_INVALID"],
    }


def _with_cr_transport(value: StageEnvironmentInputs, root: Path) -> StageEnvironmentInputs:
    path = root / "prepare-crlf.sh"
    path.write_bytes(b"#!/bin/sh\r\nset -eu\r\n")
    return replace(value, filesystem_paths=(root, path), text_transport_paths=(path,))


def test_preflight_lists_all_six_category_gaps_in_one_report(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    crlf = tmp_path / "prepare-crlf.sh"
    crlf.write_bytes(b"#!/bin/sh\r\n")
    dynamic = (
        StageEnvironmentIssue(
            "network_egress",
            "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED",
            ("akshare_financial_slice",),
        ),
        StageEnvironmentIssue(
            "external_state",
            "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
            ("akshare_financial_slice",),
        ),
    )
    inputs = replace(
        _inputs(tmp_path),
        filesystem_paths=(missing,),
        text_transport_paths=(crlf,),
        missing_identity_keys=("SECRET_REF",),
        free_disk_bytes=0,
        available_memory_bytes=0,
        observed_at=datetime.now(),
        build_timeout_seconds=0,
        dynamic_issues=dynamic,
    )

    report = evaluate_stage_environment(inputs)

    assert report["outcome"] == "blocked"
    assert {item["category"] for item in report["issues"]} == set(CATEGORIES)


def test_unregistered_stage_is_rejected(tmp_path: Path) -> None:
    inputs = replace(_inputs(tmp_path), stages=("new_unregistered_stage",))

    report = evaluate_stage_environment(inputs)

    assert report["outcome"] == "blocked"
    assert report["issues"] == [
        {
            "category": "external_state",
            "code": "REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING",
            "stages": ["new_unregistered_stage"],
        }
    ]


def test_dynamic_report_rejects_unregistered_codes_and_stages() -> None:
    from shared.release_rehearsal_stage_environment import parse_dynamic_issues

    with pytest.raises(ValueError, match="REHEARSAL_STAGE_ENVIRONMENT_ISSUE_INVALID"):
        parse_dynamic_issues(
            {
                "schema": "release.s6-stage-environment-preflight.v1",
                "issues": [
                    {
                        "category": "external_state",
                        "code": "REHEARSAL_UNREGISTERED_CODE",
                        "stages": ["provider_probe"],
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID"):
        parse_dynamic_issues(
            {
                "schema": "release.s6-stage-environment-preflight.v1",
                "issues": [
                    {
                        "category": "external_state",
                        "code": next(iter(ALLOWED_ISSUE_CODES)),
                        "stages": ["unknown_stage"],
                    }
                ],
            }
        )


def test_runner_stages_and_documented_matrix_are_registered() -> None:
    document = Path("docs/development/s6-stage-environment-contract.md").read_text(encoding="utf-8")

    assert set(STAGES).issubset(CONTRACT_STAGES)
    assert "AGOM_LOG_DIR=/tmp/agomtradepro/logs" in document
    assert "REHEARSAL_STAGE_RUNTIME_LOG_DIRECTORY_INVALID" in document
    for stage in CONTRACT_STAGES:
        assert f"| `{stage}` |" in document
    for category in CATEGORIES:
        assert category in document or category.replace("_", "") in document
