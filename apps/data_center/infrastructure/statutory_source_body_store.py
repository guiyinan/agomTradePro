"""Bounded immutable storage for public statutory bytes in a private configured root.

References identify captures, never caller-selected paths. Metadata persistence
and official-source qualification belong to their separate owning contracts.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import sys
from pathlib import Path
from uuid import UUID, uuid4

from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from core.exceptions import DataValidationError

logger = logging.getLogger(__name__)


class StatutorySourceBodyStorageError(DataValidationError):
    """Report invalid, unavailable, conflicting or corrupted retained public bytes."""

    default_message = "Statutory source body storage is unavailable or invalid."
    default_code = "STATUTORY_SOURCE_BODY_STORAGE_INVALID"


def _reject_links(path: Path) -> None:
    """Reject symlinks and Windows reparse points in existing path components."""

    for component in (*reversed(path.parents), path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise StatutorySourceBodyStorageError(
                "Statutory source storage path contains a link.",
                code="STATUTORY_SOURCE_BODY_LOCATION_INVALID",
            )


def _location(capture_id: UUID) -> str:
    """Return the single opaque location issued for this capture identity."""

    return f"statutory-source-body:///v1/{capture_id}.body"


def _sync_directory(root: Path) -> None:
    """Flush a published directory entry where directory fsync is supported."""

    if os.name == "nt":
        return
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class StatutorySourceBodyStore(StatutorySourceDocumentBodyStorePort):
    """Retain public exact bodies without replacing any completed capture.

    The caller owns a private root and its access controls. This adapter does
    not treat its reference or a content hash as official-source authority.
    """

    def __init__(self, root: Path, *, max_body_bytes: int) -> None:
        """Bind an explicit private directory and a positive bounded byte ceiling."""

        if (
            not isinstance(root, Path)
            or type(max_body_bytes) is not int
            or not 0 < max_body_bytes < sys.maxsize
        ):
            raise StatutorySourceBodyStorageError(
                "Statutory source storage configuration is invalid.",
                code="STATUTORY_SOURCE_BODY_CONFIG_INVALID",
            )
        try:
            absolute = root.absolute()
            _reject_links(absolute)
            absolute.mkdir(parents=True, exist_ok=True)
            _reject_links(absolute)
            self._root = absolute.resolve(strict=True)
            if not self._root.is_dir():
                raise OSError("Configured statutory root is not a directory")
            metadata = self._root.stat()
            self._root_identity = (metadata.st_dev, metadata.st_ino)
        except OSError as error:
            raise StatutorySourceBodyStorageError(
                "Statutory source storage root is unavailable.",
                code="STATUTORY_SOURCE_BODY_LOCATION_INVALID",
            ) from error
        self._max_body_bytes = max_body_bytes

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        """Publish exact bytes once, independently read back, and issue their reference."""

        if (
            type(capture_id) is not UUID
            or type(body) is not bytes
            or not body
            or len(body) > self._max_body_bytes
        ):
            raise StatutorySourceBodyStorageError(
                "Statutory source body or capture identity is invalid.",
                code="STATUTORY_SOURCE_BODY_INPUT_INVALID",
            )
        reference = StatutorySourceBodyReference(
            capture_id=capture_id,
            reference=_location(capture_id),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
        )
        temporary = self._root / f".{capture_id}.{uuid4().hex}.partial"
        temporary_created = False
        try:
            self._check_root()
            target = self._root / f"{capture_id}.body"
            _reject_links(target)
            with temporary.open("xb") as stream:
                temporary_created = True
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            _sync_directory(self._root)
            if self.read(reference) != body:
                raise StatutorySourceBodyStorageError(
                    "Statutory source capture identity already has different bytes.",
                    code="STATUTORY_SOURCE_BODY_CAPTURE_CONFLICT",
                )
        except OSError as error:
            raise StatutorySourceBodyStorageError(
                "Statutory source body could not be retained.",
                code="STATUTORY_SOURCE_BODY_WRITE_FAILED",
            ) from error
        finally:
            if temporary_created:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Statutory source private staging cleanup failed")
        return reference

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        """Return bounded regular-file bytes only after exact reference/size/SHA checks."""

        if (
            type(reference) is not StatutorySourceBodyReference
            or reference.reference != _location(reference.capture_id)
            or reference.body_size_bytes > self._max_body_bytes
        ):
            raise StatutorySourceBodyStorageError(
                "Statutory source body reference is invalid for this store.",
                code="STATUTORY_SOURCE_BODY_LOCATION_INVALID",
            )
        try:
            self._check_root()
            target = self._root / f"{reference.capture_id}.body"
            _reject_links(target)
            flags = os.O_RDONLY
            for name in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK"):
                flags |= getattr(os, name, 0)
            descriptor = os.open(target, flags)
            try:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_size > self._max_body_bytes
                    or metadata.st_size != reference.body_size_bytes
                ):
                    raise StatutorySourceBodyStorageError(
                        "Statutory source body file is invalid.",
                        code="STATUTORY_SOURCE_BODY_INTEGRITY_FAILED",
                    )
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    body = stream.read(reference.body_size_bytes + 1)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise StatutorySourceBodyStorageError(
                "Retained statutory source body is unavailable.",
                code="STATUTORY_SOURCE_BODY_READ_FAILED",
            ) from error
        if (
            len(body) != reference.body_size_bytes
            or hashlib.sha256(body).hexdigest() != reference.body_sha256
        ):
            raise StatutorySourceBodyStorageError(
                "Retained statutory source body failed integrity verification.",
                code="STATUTORY_SOURCE_BODY_INTEGRITY_FAILED",
            )
        return body

    def _check_root(self) -> None:
        """Reject a removed, replaced or linked configured storage root."""

        _reject_links(self._root)
        metadata = self._root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != self._root_identity
            or self._root.resolve(strict=True) != self._root
        ):
            raise StatutorySourceBodyStorageError(
                "Statutory source storage root changed or is unavailable.",
                code="STATUTORY_SOURCE_BODY_LOCATION_INVALID",
            )


__all__ = ["StatutorySourceBodyStorageError", "StatutorySourceBodyStore"]
