#!/usr/bin/env python3
"""Create and seal a clean, exact-candidate S6 source snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TypedDict, cast
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rehearsal_checkpoint import (
    seal_container_input_tree,
    tree_digest,
    verify_container_input_tree,
)

_CANDIDATE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_TREE_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXPORT_FAILURE_CODES = {
    "production": "S6_CANDIDATE_EXPORT_PRODUCTION_FAILED",
    "universe": "S6_CANDIDATE_EXPORT_UNIVERSE_FAILED",
    "contract": "S6_CANDIDATE_EXPORT_CONTRACT_FAILED",
}


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
    candidate_image: str,
    log_path: Path,
) -> None:
    """Reverify the sealed source immediately before a structured Docker export call."""
    error_code = _EXPORT_FAILURE_CODES.get(mode)
    if error_code is None:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_MODE_INVALID")
    if isinstance(container_uid, bool) or not isinstance(container_uid, int) or container_uid <= 0:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID")
    if (
        not isinstance(candidate_image, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,511}", candidate_image) is None
    ):
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_IMAGE_INVALID")
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
        if argument == candidate_image
    ]
    if len(image_positions) != 1:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_IMAGE_INVALID")
    image_index = image_positions[0]
    docker_options = docker_argv[2:image_index]

    expected_mount = f"{destination.resolve(strict=True)}:/candidate-src:ro"
    docker_users: list[str] = []
    volume_values: list[str] = []
    flag_options = {"--rm", "--read-only", "--init"}
    value_options = {
        "--env-file",
        "--entrypoint",
        "--label",
        "--name",
        "--network",
        "--security-opt",
        "--user",
        "--volume",
        "--workdir",
        "-e",
        "-u",
        "-v",
        "-w",
    }
    index = 0
    while index < len(docker_options):
        argument = docker_options[index]
        if argument in flag_options:
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
            index += 1
            continue
        if argument.startswith("-u") and len(argument) > 2:
            docker_users.append(argument[2:].removeprefix("="))
            index += 1
            continue
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_COMMAND_INVALID")
    if docker_users != [f"{container_uid}:{container_gid}"]:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_CONTAINER_IDENTITY_INVALID")
    candidate_source_mounts = [
        value
        for value in volume_values
        if len(value.split(":")) >= 2 and value.split(":")[-2] == "/candidate-src"
    ]
    if candidate_source_mounts != [expected_mount]:
        raise CandidateSourceSnapshotError("S6_CANDIDATE_EXPORT_SOURCE_MOUNT_INVALID")

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
    parser.add_argument("--candidate-image")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--run-export", action="store_true")
    parser.add_argument("--export-mode")
    parser.add_argument("--docker-arg", action="append", default=[])
    parser.add_argument("--log-path", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.run_export:
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
                candidate_image=args.candidate_image or "",
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
