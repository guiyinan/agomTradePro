"""Contracts for isolated, immutable S6 attempt plans."""

import json
import os
import stat
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from scripts.plan_release_rehearsal_attempt import (
    AttemptPlanError,
    build_attempt_plan,
    reserve_attempt,
    reserve_prepared_attempt,
    resume_attempt,
)

CANDIDATE_SHA = "a" * 40
ATTEMPT_ID = "12345678123456781234567812345678"


def test_same_candidate_retries_get_disjoint_resources_and_export_paths(
    tmp_path: Path,
) -> None:
    first = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "attempts",
    )
    second = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id="87654321876543218765432187654321",
        attempts_dir=tmp_path / "attempts",
    )

    unique_fields = (
        "attempt_id",
        "namespace",
        "root",
        "evidence_dir",
        "network",
        "postgres_container",
        "redis_container",
        "postgres_volume",
        "database",
        "provider_settings_export_path",
        "provider_identities_export_path",
        "candidate_source_snapshot_path",
        "candidate_source_receipt_path",
    )
    for field in unique_fields:
        assert first[field] != second[field]
    assert first["candidate_sha"] == second["candidate_sha"] == CANDIDATE_SHA
    assert first["evidence_dir"] == str(Path(first["root"]) / "evidence")
    assert first["provider_settings_export_path"].startswith("/tmp/")
    assert first["provider_identities_export_path"].startswith("/tmp/")
    assert first["postgres_container"].startswith("agom-s6-postgres-")
    assert first["redis_container"].startswith("agom-s6-redis-")
    assert first["database"].startswith("agom_release_rehearsal_")
    assert all(
        len(first[field]) <= 63
        for field in (
            "namespace",
            "network",
            "postgres_container",
            "redis_container",
            "postgres_volume",
            "database",
        )
    )


def test_default_attempt_id_is_a_fresh_uuid4(tmp_path: Path) -> None:
    first = build_attempt_plan(candidate_sha=CANDIDATE_SHA, attempts_dir=tmp_path)
    second = build_attempt_plan(candidate_sha=CANDIDATE_SHA, attempts_dir=tmp_path)

    assert UUID(first["attempt_id"]).version == 4
    assert UUID(second["attempt_id"]).version == 4
    assert first["attempt_id"] != second["attempt_id"]


def test_isolated_market_graph_refresh_requires_explicit_plan_opt_in(
    tmp_path: Path,
) -> None:
    default_plan = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "default",
    )
    opted_in_plan = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "opt-in",
        advance_isolated_market_graph=True,
    )

    assert default_plan["advance_isolated_market_graph"] is False
    assert opted_in_plan["advance_isolated_market_graph"] is True
    assert default_plan["schema"] == opted_in_plan["schema"] == "release.s6-attempt-plan.v3"

    reserved_path = reserve_attempt(opted_in_plan)
    assert json.loads(reserved_path.read_text(encoding="utf-8")) == opted_in_plan
    assert resume_attempt(opted_in_plan) == reserved_path


def test_same_attempt_requires_explicit_resume_and_resume_is_read_only(
    tmp_path: Path,
) -> None:
    plan = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "attempts",
    )

    plan_file = reserve_attempt(plan)
    assert plan_file == Path(plan["root"]) / "attempt-plan.json"
    assert json.loads(plan_file.read_text(encoding="utf-8")) == plan
    assert stat.S_IMODE(plan_file.stat().st_mode) & 0o222 == 0
    with pytest.raises(AttemptPlanError, match="S6_ATTEMPT_ROOT_EXISTS"):
        reserve_attempt(plan)

    assert resume_attempt(plan) == plan_file


def test_resume_rejects_input_drift_for_the_same_attempt(tmp_path: Path) -> None:
    attempts_dir = tmp_path / "attempts"
    original = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=attempts_dir,
    )
    reserve_attempt(original)
    drifted = original.copy()
    drifted["network"] = "agom-s6-stale-network"

    assert drifted["root"] == original["root"]
    with pytest.raises(AttemptPlanError, match="S6_ATTEMPT_PLAN_INVALID"):
        resume_attempt(drifted)


def test_reserve_fails_closed_on_existing_directory_and_symlink(tmp_path: Path) -> None:
    attempts_dir = tmp_path / "attempts"
    directory_collision = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=attempts_dir,
    )
    Path(directory_collision["root"]).mkdir(parents=True)
    with pytest.raises(AttemptPlanError, match="S6_ATTEMPT_ROOT_EXISTS"):
        reserve_attempt(directory_collision)

    symlink_plan = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        attempts_dir=attempts_dir,
    )
    symlink_root = Path(symlink_plan["root"])
    symlink_root.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside"
    target.mkdir()
    try:
        symlink_root.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Directory symlinks are unavailable on this platform")

    with pytest.raises(AttemptPlanError, match="S6_ATTEMPT_ROOT_SYMLINK"):
        reserve_attempt(symlink_plan)


def test_plan_contains_only_non_secret_identifiers_and_paths(tmp_path: Path) -> None:
    plan = build_attempt_plan(
        candidate_sha=CANDIDATE_SHA,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "attempts",
    )
    serialized = json.dumps(plan, sort_keys=True)

    assert set(plan) == {
        "schema",
        "candidate_sha",
        "attempt_id",
        "namespace",
        "root",
        "evidence_dir",
        "network",
        "postgres_container",
        "redis_container",
        "postgres_volume",
        "database",
        "provider_settings_export_path",
        "provider_identities_export_path",
        "candidate_source_snapshot_path",
        "candidate_source_receipt_path",
        "advance_isolated_market_graph",
    }
    assert plan["advance_isolated_market_graph"] is False
    assert not any(term in serialized.lower() for term in ("password", "credential", "secret"))


@pytest.mark.parametrize("candidate_sha", ["A" * 40, "a" * 39, "z" * 40])
def test_candidate_sha_must_be_lowercase_full_git_sha(
    tmp_path: Path,
    candidate_sha: str,
) -> None:
    with pytest.raises(AttemptPlanError, match="S6_CANDIDATE_SHA_INVALID"):
        build_attempt_plan(candidate_sha=candidate_sha, attempts_dir=tmp_path)


def test_explicit_resume_requires_the_attempt_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.plan_release_rehearsal_attempt import main

    exit_code = main(
        [
            "--candidate-sha",
            CANDIDATE_SHA,
            "--attempts-dir",
            os.fspath(tmp_path),
            "--resume",
        ]
    )

    assert exit_code == 2
    assert "S6_ATTEMPT_RESUME_ID_REQUIRED" in capsys.readouterr().err


def _candidate_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    commands = (
        ("init", "-q"),
        ("config", "user.name", "S6 planner test"),
        ("config", "user.email", "s6-planner@example.invalid"),
    )
    for command in commands:
        subprocess.run(["git", "-C", str(workspace), *command], check=True)
    (workspace / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-qm", "candidate"],
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return workspace, result.stdout.strip()


def test_prepared_reservation_creates_bound_source_snapshot(tmp_path: Path) -> None:
    workspace, candidate_sha = _candidate_workspace(tmp_path)
    plan = build_attempt_plan(
        candidate_sha=candidate_sha,
        attempt_id=ATTEMPT_ID,
        attempts_dir=tmp_path / "attempts",
    )

    plan_file = reserve_prepared_attempt(
        plan,
        workspace=workspace,
        container_gid=os.getgid() if os.name == "posix" else 0,
    )

    assert plan_file.is_file()
    assert (
        Path(plan["candidate_source_snapshot_path"], "candidate.py").read_text(encoding="utf-8")
        == "VALUE = 1\n"
    )
    receipt = json.loads(Path(plan["candidate_source_receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["candidate_sha"] == candidate_sha


def test_reserve_cli_requires_source_snapshot_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.plan_release_rehearsal_attempt import main

    exit_code = main(
        [
            "--candidate-sha",
            CANDIDATE_SHA,
            "--attempts-dir",
            os.fspath(tmp_path),
            "--reserve",
        ]
    )

    assert exit_code == 2
    assert "S6_ATTEMPT_SOURCE_SNAPSHOT_REQUIRED" in capsys.readouterr().err
