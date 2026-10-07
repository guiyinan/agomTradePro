"""Local, same-candidate S6 checkpoints; never authorize a deployment."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4


def atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    """Publish a complete status atomically, tolerating brief Windows reader locks."""
    if path.is_symlink():
        raise ValueError("S6_CHECKPOINT_INVALID")
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for attempt in range(5):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


def file_digest(path: Path) -> str:
    """Hash a regular file in bounded memory, refusing symlinks."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("S6_CHECKPOINT_ARTIFACT_CHANGED")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(path: Path) -> str:
    """Bind every file and directory, including empty directories, in an artifact."""
    if path.is_symlink() or not path.exists():
        raise ValueError("S6_CHECKPOINT_ARTIFACT_CHANGED")
    if path.is_file():
        return file_digest(path)
    entries: list[tuple[str, str]] = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError("S6_CHECKPOINT_ARTIFACT_CHANGED")
        entries.append(
            (item.relative_to(path).as_posix(), "directory" if item.is_dir() else file_digest(item))
        )
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def seal_container_input_tree(
    root: Path,
    container_gid: int,
    error_factory: Callable[[str, str], Exception],
) -> None:
    """Seal generated evidence while granting the candidate group read access."""

    if root.is_symlink() or not root.is_dir():
        raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
    entries = tuple(sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True))
    if not entries or not any(item.is_file() for item in entries):
        raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
    for path in (*entries, root):
        if path.is_symlink():
            raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
        metadata = path.lstat()
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if not is_directory and not stat.S_ISREG(metadata.st_mode):
            raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
        expected_mode = 0o550 if is_directory else 0o440
        if os.name == "posix":
            fchown = cast(Callable[[int, int, int], None] | None, getattr(os, "fchown", None))
            fchmod = cast(Callable[[int, int], None] | None, getattr(os, "fchmod", None))
            if fchown is None or fchmod is None:
                raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if is_directory:
                flags |= getattr(os, "O_DIRECTORY", 0)
            descriptor: int | None = None
            try:
                descriptor = os.open(path, flags)
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_CHANGED")
                fchown(descriptor, -1, container_gid)
                fchmod(descriptor, expected_mode)
                sealed = os.fstat(descriptor)
            except OSError as exc:
                raise error_factory(
                    "github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED"
                ) from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            if (
                sealed.st_gid != container_gid
                or stat.S_IMODE(sealed.st_mode) != expected_mode
                or (sealed.st_dev, sealed.st_ino) != (metadata.st_dev, metadata.st_ino)
            ):
                raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED")
        else:
            portable_mode = 0o555 if is_directory else 0o444
            path.chmod(portable_mode)
            sealed = path.lstat()
            if stat.S_IMODE(sealed.st_mode) != portable_mode:
                raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED")
    verify_container_input_tree(root, container_gid, error_factory)


def verify_container_input_tree(
    root: Path,
    container_gid: int,
    error_factory: Callable[[str, str], Exception],
) -> None:
    """Recheck a sealed input tree by descriptor without changing any metadata."""

    if root.is_symlink() or not root.is_dir():
        raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
    entries = tuple(sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True))
    if not entries or not any(item.is_file() for item in entries):
        raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
    for path in (*entries, root):
        if path.is_symlink():
            raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
        metadata = path.lstat()
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if not is_directory and not stat.S_ISREG(metadata.st_mode):
            raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_TREE_INVALID")
        expected_mode = 0o550 if is_directory else 0o440
        if os.name != "posix":
            expected_mode = 0o555 if is_directory else 0o444
            if stat.S_IMODE(metadata.st_mode) != expected_mode:
                raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED")
            continue
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if is_directory:
                flags |= getattr(os, "O_DIRECTORY", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
        except OSError as exc:
            raise error_factory(
                "github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or stat.S_IMODE(opened.st_mode) != expected_mode
            or os.name == "posix"
            and opened.st_gid != container_gid
        ):
            raise error_factory("github_ci_evidence", "S6_CONTAINER_INPUT_PERMISSIONS_FAILED")


@contextmanager
def run_lock(root: Path) -> Iterator[None]:
    """Hold an OS lock for this run; process death releases it without manual deletion."""
    path = root / ".launcher.lock"
    if path.is_symlink():
        raise ValueError("S6_RUN_LOCK_INVALID")
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("S6_RUN_ALREADY_ACTIVE") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Checkpoint:
    """Validate a successful prefix and retain failed attempts without overwriting evidence."""

    def __init__(
        self,
        root: Path,
        binding: Mapping[str, object],
        *,
        resume: bool,
        max_age_hours: float,
        stage_order: Sequence[str],
    ) -> None:
        self.root = root
        self.path = root / "checkpoint.json"
        self.binding = dict(binding)
        self.records: dict[str, dict[str, object]] = {}
        if resume:
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("S6_CHECKPOINT_MISSING")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema") != "release.rehearsal-checkpoint.v1"
            ):
                raise ValueError("S6_CHECKPOINT_INVALID")
            if value.get("binding") != self.binding:
                raise ValueError("S6_CHECKPOINT_INPUT_CHANGED")
            records = value.get("stages")
            if not isinstance(records, dict):
                raise ValueError("S6_CHECKPOINT_INVALID")
            if len(records) > len(stage_order) or set(records) != set(stage_order[: len(records)]):
                raise ValueError("S6_CHECKPOINT_INVALID")
            for name, record in records.items():
                if not isinstance(name, str) or not isinstance(record, dict):
                    raise ValueError("S6_CHECKPOINT_INVALID")
                finished = datetime.fromisoformat(str(record.get("completed_at", "")))
                if (
                    finished.utcoffset() is None
                    or not 0
                    <= (datetime.now(UTC) - finished).total_seconds()
                    <= max_age_hours * 3600
                ):
                    raise ValueError("S6_CHECKPOINT_EXPIRED")
                artifacts = record.get("artifacts")
                if not isinstance(artifacts, dict):
                    raise ValueError("S6_CHECKPOINT_INVALID")
                for relative, digest in artifacts.items():
                    if not isinstance(relative, str) or Path(relative).name != relative:
                        raise ValueError("S6_CHECKPOINT_INVALID")
                    if tree_digest(root / relative) != digest:
                        raise ValueError("S6_CHECKPOINT_ARTIFACT_CHANGED")
                self.records[name] = cast(dict[str, object], record)
        else:
            self._save()

    def _save(self) -> None:
        payload = {
            "schema": "release.rehearsal-checkpoint.v1",
            "binding": self.binding,
            "stages": self.records,
        }
        atomic_json(self.path, payload)

    def done(self, stage: str) -> bool:
        """Return whether this stage has verified immutable artifacts."""
        return stage in self.records

    def complete(self, stage: str, artifacts: Sequence[Path]) -> None:
        """Persist success only after the caller's stage contract checks passed."""
        if self.done(stage):
            return
        self.records[stage] = {
            "completed_at": datetime.now(UTC).isoformat(),
            "artifacts": {
                path.relative_to(self.root).as_posix(): tree_digest(path) for path in artifacts
            },
        }
        self._save()

    def prepare(self, stage: str, paths: Sequence[Path], *, resume: bool) -> None:
        """Move incomplete outputs into a unique failed-attempt directory on resume."""
        if not resume or self.done(stage):
            return
        present = [path for path in paths if path.exists() or path.is_symlink()]
        if not present:
            return
        archive = self.root / "failed-attempts" / f"{stage}-{uuid4().hex}"
        if archive.parent.is_symlink():
            raise ValueError("S6_CHECKPOINT_INVALID")
        archive.mkdir(parents=True)
        for path in present:
            if path.is_symlink() or path.parent.resolve() != self.root.resolve():
                raise ValueError("S6_CHECKPOINT_ARTIFACT_CHANGED")
            path.rename(archive / path.name)
