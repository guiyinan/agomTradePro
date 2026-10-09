"""Race-resistant bounded reads for immutable S6 evidence files."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class RehearsalFileReadError(ValueError):
    """A path failed the S6 regular-file and identity checks."""


def read_regular_file(root: Path, relative: str, limit: int) -> bytes:
    """Read one bounded regular file beneath root without following links."""
    if limit <= 0 or not relative or "\\" in relative:
        raise RehearsalFileReadError("file_invalid")
    relative_path = Path(relative)
    if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
        raise RehearsalFileReadError("file_invalid")
    root_path = root.absolute()
    parts = relative_path.parts
    if not parts or any(part in {"", "."} for part in parts):
        raise RehearsalFileReadError("file_invalid")
    try:
        if (
            os.name != "nt"
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
        ):
            return _read_with_directory_descriptors(root_path, parts, limit)
        return _read_with_path_rechecks(root_path, parts, limit)
    except RehearsalFileReadError:
        raise
    except OSError as exc:
        raise RehearsalFileReadError("file_invalid") from exc


def _read_with_directory_descriptors(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    file_flags = os.O_RDONLY | no_follow | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    root_fd = os.open(root.anchor, directory_flags)
    opened_directories = [root_fd]
    directory_fd = root_fd
    file_fd = -1
    try:
        for part in root.parts[1:]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened_directories.append(directory_fd)
        for part in parts[:-1]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened_directories.append(directory_fd)
        filename = parts[-1]
        before = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise RehearsalFileReadError("file_invalid")
        file_fd = os.open(filename, file_flags, dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        if not _same_file(before, opened):
            raise RehearsalFileReadError("file_changed")
        raw = _read_descriptor(file_fd, limit)
        after = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(after.st_mode) or not _same_file(opened, after):
            raise RehearsalFileReadError("file_changed")
        return raw
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _read_with_path_rechecks(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    root_metadata: list[tuple[Path, os.stat_result]] = []
    current_root = Path(root.anchor)
    for root_part in root.parts[1:]:
        current_root /= root_part
        metadata = current_root.lstat()
        if _is_link_or_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise RehearsalFileReadError("symlink_forbidden")
        root_metadata.append((current_root, metadata))
    path = root
    path_metadata: list[tuple[Path, os.stat_result]] = []
    for part in parts:
        path /= part
        metadata = path.lstat()
        if _is_link_or_reparse_point(metadata):
            raise RehearsalFileReadError("symlink_forbidden")
        if part != parts[-1] and not stat.S_ISDIR(metadata.st_mode):
            raise RehearsalFileReadError("file_invalid")
        path_metadata.append((path, metadata))
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not path.resolve(strict=True).is_relative_to(
        root.resolve()
    ):
        raise RehearsalFileReadError("file_invalid")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not _same_file(before, opened):
            raise RehearsalFileReadError("file_changed")
        raw = _read_descriptor(descriptor, limit)
        after = path.lstat()
        if _is_link_or_reparse_point(after) or not _same_file(opened, after):
            raise RehearsalFileReadError("file_changed")
        for checked_path, before_metadata in (*root_metadata, *path_metadata[:-1]):
            current_metadata = checked_path.lstat()
            if _is_link_or_reparse_point(current_metadata) or not _same_directory(
                before_metadata, current_metadata
            ):
                raise RehearsalFileReadError("file_changed")
        return raw
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RehearsalFileReadError("file_too_large")
        chunks.append(chunk)
    if total == 0:
        raise RehearsalFileReadError("file_invalid")
    return b"".join(chunks)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
    )


def _same_directory(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
    )


def _is_link_or_reparse_point(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)
