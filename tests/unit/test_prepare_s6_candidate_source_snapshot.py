"""Contracts for the isolated, group-readable S6 candidate source snapshot."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.prepare_s6_candidate_source_snapshot import (
    CandidateSourceSnapshotError,
    create_candidate_source_snapshot,
    run_candidate_export,
    verify_candidate_source_snapshot,
)

EXECUTION_IMAGE_ID = "sha256:" + "a" * 64


def _git(workspace: Path, *arguments: str) -> str:
    """Run a Git command for a temporary candidate workspace."""
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    """Create a small clean repository with tracked and ignored files."""
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.name", "S6 snapshot test")
    _git(workspace, "config", "user.email", "s6-snapshot@example.invalid")
    (workspace / ".gitignore").write_text("ignored-private.txt\n", encoding="utf-8")
    (workspace / "scripts").mkdir()
    (workspace / "scripts" / "candidate.py").write_text("VALUE = 'candidate'\n", encoding="utf-8")
    (workspace / "scripts" / "postgres_role.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (workspace / "ignored-private.txt").write_text("must not enter the snapshot", encoding="utf-8")
    _git(workspace, "add", ".gitignore", "scripts/candidate.py", "scripts/postgres_role.sql")
    _git(workspace, "commit", "-qm", "candidate source")
    return workspace, _git(workspace, "rev-parse", "HEAD")


def _prepare(
    workspace: Path,
    candidate_sha: str,
    output_root: Path,
    *,
    container_gid: int | None = None,
) -> tuple[Path, Path]:
    """Prepare output paths for one candidate snapshot call."""
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / "candidate-source"
    receipt = output_root / "candidate-source-receipt.json"
    gid = container_gid
    if gid is None:
        gid = os.getgid() if os.name == "posix" else 0
    create_candidate_source_snapshot(
        workspace=workspace,
        candidate_sha=candidate_sha,
        destination=destination,
        receipt_path=receipt,
        container_gid=gid,
    )
    return destination, receipt


_PREPARE_NETWORK = "agom-s6-network-" + "b" * 32 + "-prepare"


def _export_bindings(output_root: Path) -> tuple[Path, Path, Path]:
    """Create the exact private input, output, and execution-env paths."""

    input_directory = output_root / "candidate-inputs"
    output_directory = output_root / "candidate-exports"
    execution_env = output_root / "prepare-export.env"
    input_directory.mkdir()
    output_directory.mkdir()
    execution_env.write_text("DJANGO_SETTINGS_MODULE=core.settings.production\n", encoding="utf-8")
    return input_directory, output_directory, execution_env


def _valid_export_argv(
    *,
    destination: Path,
    input_directory: Path,
    output_directory: Path,
    execution_env: Path,
    candidate_sha: str,
    mode: str = "production",
    user_arguments: list[str] | None = None,
    execution_image: str = EXECUTION_IMAGE_ID,
) -> list[str]:
    """Return the only Docker argv shape accepted by the export verifier."""

    gid = os.getgid() if os.name == "posix" else 0
    return [
        "docker",
        "run",
        "--rm",
        "--read-only",
        "--user",
        *(user_arguments if user_arguments is not None else [f"1000:{gid}"]),
        "--network",
        _PREPARE_NETWORK,
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777,size=2147483648",
        "--env-file",
        str(execution_env.resolve()),
        "-e",
        f"S6_EXPECTED_CANDIDATE={candidate_sha}",
        "-e",
        "S6_EXPECTED_DB=isolated_snapshot",
        "-e",
        "S6_NETWORK=agom-s6-network-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "-e",
        "S6_DATABASE=agom_release_rehearsal_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "-e",
        "S6_PG_CONTAINER=agom-s6-postgres-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "-e",
        "S6_REDIS_CONTAINER=agom-s6-redis-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on -c transaction_read_only=on",
        "-v",
        f"{destination.resolve()}:/candidate-src:ro",
        "-v",
        f"{input_directory.resolve()}:/candidate-inputs:ro",
        "-v",
        f"{output_directory.resolve()}:/candidate-output:rw",
        "--entrypoint",
        "python",
        execution_image,
        "/candidate-src/scripts/export_s6_rehearsal_inputs.py",
        mode,
    ]


def _run_export_kwargs(
    *,
    input_directory: Path,
    output_directory: Path,
    execution_env: Path,
) -> dict[str, object]:
    """Return shared exact binding arguments for ``run_candidate_export``."""

    return {
        "input_directory": input_directory,
        "output_directory": output_directory,
        "execution_env_file": execution_env,
        "docker_network": _PREPARE_NETWORK,
    }


def test_snapshot_uses_exact_clean_source_and_seals_only_the_copy(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    if os.name == "posix":
        workspace.chmod(0o700)
        source_mode_before = stat.S_IMODE(workspace.stat().st_mode)
        file_mode_before = stat.S_IMODE((workspace / "scripts" / "candidate.py").stat().st_mode)

    destination, receipt_path = _prepare(workspace, candidate_sha, tmp_path / "attempt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    verified = verify_candidate_source_snapshot(
        destination=destination,
        receipt_path=receipt_path,
        candidate_sha=candidate_sha,
        container_gid=os.getgid() if os.name == "posix" else 0,
    )

    assert verified == receipt
    assert receipt["schema"] == "release.s6-candidate-source-snapshot.v1"
    assert receipt["outcome"] == "success"
    assert receipt["candidate_sha"] == candidate_sha
    assert receipt["tree_sha256"]
    assert receipt["receipt_sha256"]
    assert receipt["file_count"] == 3
    assert receipt["directory_count"] == 2
    assert ".git" not in {path.name for path in destination.iterdir()}
    assert not (destination / "ignored-private.txt").exists()
    assert (destination / "scripts" / "candidate.py").read_text(encoding="utf-8") == (
        "VALUE = 'candidate'\n"
    )
    assert "must not enter the snapshot" not in receipt_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(receipt_path.stat().st_mode) & 0o222 == 0

    expected_directory_mode = 0o550 if os.name == "posix" else 0o555
    expected_file_mode = 0o440 if os.name == "posix" else 0o444
    assert stat.S_IMODE(destination.stat().st_mode) == expected_directory_mode
    assert stat.S_IMODE((destination / "scripts").stat().st_mode) == expected_directory_mode
    assert (
        stat.S_IMODE((destination / "scripts" / "candidate.py").stat().st_mode)
        == expected_file_mode
    )

    if os.name == "posix":
        assert destination.stat().st_gid == os.getgid()
        assert stat.S_IMODE(workspace.stat().st_mode) == source_mode_before == 0o700
        assert (
            stat.S_IMODE((workspace / "scripts" / "candidate.py").stat().st_mode)
            == file_mode_before
        )


def test_before_mount_verification_rejects_receipt_digest_drift(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    destination, receipt_path = _prepare(workspace, candidate_sha, tmp_path / "attempt")
    receipt_path.chmod(0o644)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["tree_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o444)

    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_SOURCE_RECEIPT_DIGEST_MISMATCH",
    ):
        verify_candidate_source_snapshot(
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode-drift revalidation contract")
def test_before_mount_verification_rejects_snapshot_permission_drift(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    destination, receipt_path = _prepare(workspace, candidate_sha, tmp_path / "attempt")
    (destination / "scripts" / "candidate.py").chmod(0o640)

    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_SOURCE_PERMISSIONS_FAILED",
    ):
        verify_candidate_source_snapshot(
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid(),
        )


def test_candidate_export_reverifies_then_runs_structured_docker_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    log_path = output_root / "candidate-export-production.log"
    docker_argv = _valid_export_argv(
        destination=destination,
        input_directory=input_directory,
        output_directory=output_directory,
        execution_env=execution_env,
        candidate_sha=candidate_sha,
    )
    real_run = subprocess.run
    calls: list[list[str]] = []

    def mock_run(command, *args, **kwargs):
        if command[0] != "docker":
            return real_run(command, *args, **kwargs)
        calls.append(list(command))
        kwargs["stdout"].write(b"safe test exporter log\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(snapshot_module.subprocess, "run", mock_run)
    run_candidate_export(
        mode="production",
        docker_argv=docker_argv,
        destination=destination,
        receipt_path=receipt_path,
        candidate_sha=candidate_sha,
        container_gid=os.getgid() if os.name == "posix" else 0,
        container_uid=1000,
        execution_image=EXECUTION_IMAGE_ID,
        log_path=log_path,
        **_run_export_kwargs(
            input_directory=input_directory,
            output_directory=output_directory,
            execution_env=execution_env,
        ),
    )

    assert calls == [docker_argv]
    assert log_path.read_bytes() == b"safe test exporter log\n"
    if os.name == "posix":
        assert stat.S_IMODE(log_path.stat().st_mode) & 0o077 == 0


@pytest.mark.parametrize(
    "execution_image",
    ["candidate:latest", "sha256:short", "SHA256:" + "a" * 64],
)
def test_candidate_export_rejects_mutable_or_malformed_execution_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_image: str,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)

    def docker_must_not_run(*_args, **_kwargs):
        raise AssertionError("docker must not run with a mutable execution image")

    monkeypatch.setattr(snapshot_module.subprocess, "run", docker_must_not_run)
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_EXPORT_EXECUTION_IMAGE_INVALID",
    ):
        run_candidate_export(
            mode="production",
            docker_argv=["docker", "run", execution_image, "true"],
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=execution_image,
            log_path=output_root / "candidate-export-production.log",
            **_run_export_kwargs(
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
            ),
        )


def test_candidate_export_maps_nonzero_to_a_stable_mode_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    log_path = output_root / "candidate-export-production.log"
    docker_argv = _valid_export_argv(
        destination=destination,
        input_directory=input_directory,
        output_directory=output_directory,
        execution_env=execution_env,
        candidate_sha=candidate_sha,
    )
    real_run = subprocess.run

    def mock_run(command, *args, **kwargs):
        if command[0] != "docker":
            return real_run(command, *args, **kwargs)
        kwargs["stdout"].write(b"private exporter details\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(snapshot_module.subprocess, "run", mock_run)
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_EXPORT_PRODUCTION_FAILED",
    ):
        run_candidate_export(
            mode="production",
            docker_argv=docker_argv,
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=EXECUTION_IMAGE_ID,
            log_path=log_path,
            **_run_export_kwargs(
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
            ),
        )
    assert log_path.read_bytes() == b"private exporter details\n"


def test_candidate_export_blocks_permission_drift_before_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    (destination / "scripts" / "candidate.py").chmod(0o640)

    def docker_must_not_run(*_args, **_kwargs):
        raise AssertionError("docker must not run after source snapshot drift")

    monkeypatch.setattr(snapshot_module.subprocess, "run", docker_must_not_run)
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_SOURCE_PERMISSIONS_FAILED",
    ):
        run_candidate_export(
            mode="production",
            docker_argv=_valid_export_argv(
                destination=destination,
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
                candidate_sha=candidate_sha,
            ),
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=EXECUTION_IMAGE_ID,
            log_path=output_root / "candidate-export-production.log",
            **_run_export_kwargs(
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
            ),
        )


@pytest.mark.parametrize(
    "user_arguments",
    [[], ["0:0"], ["1001:0"], ["1000:0", "--user", "1000:0"]],
)
def test_candidate_export_requires_unique_non_root_bound_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_arguments: list[str],
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    docker_argv = _valid_export_argv(
        destination=destination,
        input_directory=input_directory,
        output_directory=output_directory,
        execution_env=execution_env,
        candidate_sha=candidate_sha,
        user_arguments=user_arguments,
    )

    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("docker must not run without the bound non-root identity")
        ),
    )
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID|S6_CANDIDATE_EXPORT_COMMAND_INVALID",
    ):
        run_candidate_export(
            mode="production",
            docker_argv=docker_argv,
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=EXECUTION_IMAGE_ID,
            log_path=output_root / "candidate-export-production.log",
            **_run_export_kwargs(
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
            ),
        )


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("extra_volume", "S6_CANDIDATE_EXPORT_SOURCE_MOUNT_INVALID"),
        ("unsafe_tmpfs", "S6_CANDIDATE_EXPORT_COMMAND_INVALID"),
        ("wrong_network", "S6_CANDIDATE_EXPORT_ENVIRONMENT_INVALID"),
        ("post_image_option", "S6_CANDIDATE_EXPORT_COMMAND_INVALID"),
        ("unexpected_image", "S6_CANDIDATE_EXPORT_COMMAND_INVALID"),
    ],
)
def test_candidate_export_rejects_argv_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error_code: str,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    docker_argv = _valid_export_argv(
        destination=destination,
        input_directory=input_directory,
        output_directory=output_directory,
        execution_env=execution_env,
        candidate_sha=candidate_sha,
    )
    image_index = docker_argv.index(EXECUTION_IMAGE_ID)
    if mutation == "extra_volume":
        docker_argv[image_index:image_index] = ["-v", "/:/host:ro"]
    elif mutation == "unsafe_tmpfs":
        docker_argv[docker_argv.index("/tmp:rw,nosuid,nodev,mode=1777,size=2147483648")] = (
            "/tmp:rw,size=4g"
        )
    elif mutation == "wrong_network":
        docker_argv[docker_argv.index(_PREPARE_NETWORK)] = "agom-s6-network-other-prepare"
    elif mutation == "post_image_option":
        docker_argv[image_index + 1 : image_index + 1] = ["--user", "1000:0"]
    else:
        docker_argv[image_index:image_index] = ["unexpected-image"]

    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("docker must not run after argv contract drift")
        ),
    )
    with pytest.raises(CandidateSourceSnapshotError, match=error_code):
        run_candidate_export(
            mode="production",
            docker_argv=docker_argv,
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=EXECUTION_IMAGE_ID,
            log_path=output_root / "candidate-export-production.log",
            **_run_export_kwargs(
                input_directory=input_directory,
                output_directory=output_directory,
                execution_env=execution_env,
            ),
        )


@pytest.mark.parametrize("overlap", ["source_output", "input_output", "env_output"])
def test_candidate_export_rejects_overlapping_host_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlap: str,
) -> None:
    from scripts import prepare_s6_candidate_source_snapshot as snapshot_module

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    destination, receipt_path = _prepare(workspace, candidate_sha, output_root)
    input_directory, output_directory, execution_env = _export_bindings(output_root)
    if overlap == "source_output":
        output_directory = destination
    elif overlap == "input_output":
        output_directory = input_directory
    else:
        execution_env = output_directory / "prepare-export.env"
        execution_env.write_text(
            "DJANGO_SETTINGS_MODULE=core.settings.production\n", encoding="utf-8"
        )

    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("docker must not run with overlapping host paths")
        ),
    )
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_EXPORT_PATH_INVALID",
    ):
        run_candidate_export(
            mode="production",
            docker_argv=["docker", "run", EXECUTION_IMAGE_ID, "true"],
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
            container_uid=1000,
            execution_image=EXECUTION_IMAGE_ID,
            input_directory=input_directory,
            output_directory=output_directory,
            execution_env_file=execution_env,
            docker_network=_PREPARE_NETWORK,
            log_path=output_root / "candidate-export-production.log",
        )


def test_malformed_receipt_returns_stable_validation_error(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    destination, receipt_path = _prepare(workspace, candidate_sha, tmp_path / "attempt")
    receipt_path.chmod(0o644)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["permission_model"] = []
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o444)

    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_SOURCE_RECEIPT_INVALID",
    ):
        verify_candidate_source_snapshot(
            destination=destination,
            receipt_path=receipt_path,
            candidate_sha=candidate_sha,
            container_gid=os.getgid() if os.name == "posix" else 0,
        )


def test_snapshot_rejects_wrong_candidate_and_dirty_workspace(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    output_root.mkdir()

    with pytest.raises(CandidateSourceSnapshotError, match="S6_CANDIDATE_SOURCE_HEAD_MISMATCH"):
        create_candidate_source_snapshot(
            workspace=workspace,
            candidate_sha="0" * 40,
            destination=output_root / "wrong-sha",
            receipt_path=output_root / "wrong-sha-receipt.json",
            container_gid=os.getgid() if os.name == "posix" else 0,
        )

    (workspace / "scripts" / "candidate.py").write_text("VALUE = 'dirty'\n", encoding="utf-8")
    with pytest.raises(CandidateSourceSnapshotError, match="S6_CANDIDATE_SOURCE_WORKSPACE_DIRTY"):
        create_candidate_source_snapshot(
            workspace=workspace,
            candidate_sha=candidate_sha,
            destination=output_root / "dirty",
            receipt_path=output_root / "dirty-receipt.json",
            container_gid=os.getgid() if os.name == "posix" else 0,
        )
    assert not (output_root / "wrong-sha").exists()
    assert not (output_root / "dirty").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink input contract")
def test_snapshot_rejects_tracked_symlink(tmp_path: Path) -> None:
    workspace, candidate_sha = _workspace(tmp_path)
    (workspace / "candidate-link").symlink_to("scripts/candidate.py")
    _git(workspace, "add", "candidate-link")
    _git(workspace, "commit", "-qm", "tracked symlink")
    candidate_sha = _git(workspace, "rev-parse", "HEAD")
    output_root = tmp_path / "attempt"
    output_root.mkdir()

    with pytest.raises(CandidateSourceSnapshotError, match="S6_CANDIDATE_SOURCE_ENTRY_INVALID"):
        create_candidate_source_snapshot(
            workspace=workspace,
            candidate_sha=candidate_sha,
            destination=output_root / "candidate-source",
            receipt_path=output_root / "receipt.json",
            container_gid=os.getgid(),
        )
    assert not (output_root / "receipt.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor ownership failure injection")
def test_snapshot_maps_group_seal_failure_to_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import rehearsal_checkpoint

    workspace, candidate_sha = _workspace(tmp_path)
    output_root = tmp_path / "attempt"
    output_root.mkdir()

    def deny_group_change(_descriptor: int, _owner: int, _group: int) -> None:
        raise PermissionError("injected group ownership failure")

    monkeypatch.setattr(rehearsal_checkpoint.os, "fchown", deny_group_change)
    with pytest.raises(
        CandidateSourceSnapshotError,
        match="S6_CANDIDATE_SOURCE_PERMISSIONS_FAILED",
    ):
        create_candidate_source_snapshot(
            workspace=workspace,
            candidate_sha=candidate_sha,
            destination=output_root / "candidate-source",
            receipt_path=output_root / "receipt.json",
            container_gid=os.getgid(),
        )
    assert not (output_root / "receipt.json").exists()


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="Linux bash -u wrapper regression contract",
)
def test_candidate_export_error_helper_is_safe_under_bash_nounset() -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "shared"
        / "s6_candidate_export_failure.sh"
    )
    shell_source = r"""
set -eu
source "$1"
for mode in production universe contract; do
  actual="$(s6_candidate_export_failure_code "$mode")"
  case "$mode" in
    production) test "$actual" = "S6_CANDIDATE_EXPORT_PRODUCTION_FAILED" ;;
    universe) test "$actual" = "S6_CANDIDATE_EXPORT_UNIVERSE_FAILED" ;;
    contract) test "$actual" = "S6_CANDIDATE_EXPORT_CONTRACT_FAILED" ;;
  esac
done
if invalid="$(s6_candidate_export_failure_code unknown)"; then
  exit 1
else
  status=$?
  test "$status" -eq 2
  test "$invalid" = "S6_CANDIDATE_EXPORT_MODE_INVALID"
fi
"""
    result = subprocess.run(
        ["bash", "-u", "-c", shell_source, "s6-candidate-export-test", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("python3") is None,
    reason="sealed candidate helper bytecode contract requires POSIX Python",
)
def test_sealed_candidate_helper_clis_disable_bytecode_writes(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate-source"
    scripts = candidate / "scripts"
    scripts.mkdir(parents=True)
    project_scripts = Path(__file__).resolve().parents[2] / "scripts"
    for name in ("prepare_s6_candidate_source_snapshot.py", "rehearsal_checkpoint.py"):
        shutil.copy2(project_scripts / name, scripts / name)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(candidate)
    verify_result = subprocess.run(
        [
            shutil.which("python3") or "python3",
            "-B",
            str(scripts / "prepare_s6_candidate_source_snapshot.py"),
            "--help",
        ],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    export_result = subprocess.run(
        [
            shutil.which("python3") or "python3",
            "-B",
            str(scripts / "prepare_s6_candidate_source_snapshot.py"),
            "--candidate-sha",
            "a" * 40,
            "--destination",
            str(candidate),
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--container-gid",
            "1000",
            "--run-export",
        ],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert verify_result.returncode == 0, verify_result.stderr
    assert export_result.returncode == 2
    assert "S6_CANDIDATE_EXPORT_LOG_INVALID" in export_result.stderr
    assert not list(candidate.rglob("__pycache__"))
    assert not list(candidate.rglob("*.pyc"))
