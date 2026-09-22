"""Authenticated immutable storage for provider-native financial source-time bytes."""

from __future__ import annotations

import hashlib
import os
import struct
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken

from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialSourceTimeArtifactRef,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    _cleanup_partial,
    _decode_json_object,
    _is_windows_reparse_point,
    _json_bytes,
    _publish_no_replace,
    _reject_symlink_components,
    _sync_directory_chain,
)
from core.exceptions import DataFetchError

FORMAT_VERSION: Final[str] = "financial-source-time-artifact.v1"
ENCRYPTION_ALGORITHM: Final[str] = "fernet-aes128cbc-hmacsha256"
_MAGIC: Final[bytes] = b"FST1"
_PREFIX_BYTES: Final[int] = len(_MAGIC) + 8
_MAX_METADATA_BYTES: Final[int] = 64 * 1024
_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "capture_id",
        "location",
        "provider_name",
        "dataset_key",
        "requested_asset_code",
        "requested_announcement_date",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "response_row_count",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
    }
)


class FinancialSourceTimeArtifactError(DataFetchError):
    """Raised when a source-time artifact cannot be stored or verified exactly."""

    default_message = "财务来源时间原件无法验证。"
    default_code = "FINANCIAL_SOURCE_TIME_ARTIFACT_INVALID"


class FinancialSourceTimeBodyStore:
    """Store and read source-time bodies in a distinct authenticated envelope."""

    def __init__(
        self,
        root: Path,
        *,
        encryption_key: bytes,
        encryption_key_ref: str,
        encryption_key_version: str,
        max_body_bytes: int,
    ) -> None:
        """Initialize an explicitly configured encrypted source-time store."""

        if not isinstance(root, Path) or not str(root).strip():
            raise FinancialSourceTimeArtifactError("financial source-time root is invalid")
        _config_text(encryption_key_ref, "encryption_key_ref")
        _config_text(encryption_key_version, "encryption_key_version")
        if type(encryption_key) is not bytes or not encryption_key:
            raise FinancialSourceTimeArtifactError("financial source-time key is invalid")
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise FinancialSourceTimeArtifactError("financial source-time size limit is invalid")
        try:
            fernet = Fernet(encryption_key)
            expanded = root.expanduser()
            _reject_symlink_components(expanded)
            if expanded.exists() and not expanded.is_dir():
                raise OSError("artifact root is not a directory")
            expanded.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(expanded)
            resolved = expanded.resolve()
        except (OSError, TypeError, ValueError) as exc:
            raise FinancialSourceTimeArtifactError(
                "financial source-time store configuration is invalid"
            ) from exc
        self._root = resolved
        self._fernet = fernet
        self._encryption_key_ref = encryption_key_ref
        self._encryption_key_version = encryption_key_version
        self._max_body_bytes = max_body_bytes
        plaintext_limit = _PREFIX_BYTES + _MAX_METADATA_BYTES + max_body_bytes
        self._max_token_bytes = ((plaintext_limit + 73 + 2) // 3) * 4

    def build_reference(
        self,
        *,
        capture_id: UUID,
        provider_name: str,
        requested_asset_code: str,
        requested_announcement_date: date,
        body: bytes,
        response_completed_at: datetime,
        response_row_count: int,
    ) -> FinancialSourceTimeArtifactRef:
        """Build the only reference shape accepted by this configured store."""

        if type(body) is not bytes:
            raise FinancialSourceTimeArtifactError("financial source-time body must be exact bytes")
        return FinancialSourceTimeArtifactRef(
            capture_id=capture_id,
            location=source_time_location_for(capture_id),
            provider_name=provider_name,
            dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
            requested_asset_code=requested_asset_code,
            requested_announcement_date=requested_announcement_date,
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=response_completed_at,
            response_row_count=response_row_count,
            format_version=FORMAT_VERSION,
            encryption_algorithm=ENCRYPTION_ALGORITHM,
            encryption_key_ref=self._encryption_key_ref,
            encryption_key_version=self._encryption_key_version,
        )

    def store(
        self,
        reference: FinancialSourceTimeArtifactRef,
        body: bytes,
    ) -> FinancialSourceTimeArtifactRef:
        """Atomically retain exact source-time bytes for a precomputed reference."""

        self._validate_reference(reference)
        self._validate_body(reference, body)
        final_path = self._path_for(reference)
        if final_path.exists():
            return self._inspect_existing(reference, final_path)
        partial_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.partial")
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(final_path.parent)
            encrypted = self._encode(reference, body)
            self._write_partial(partial_path, encrypted)
            try:
                _publish_no_replace(partial_path, final_path)
                _sync_directory_chain(final_path.parent, self._root)
            except FileExistsError:
                _cleanup_partial(partial_path)
                return self._inspect_existing(reference, final_path)
        except FinancialSourceTimeArtifactError:
            _cleanup_partial(partial_path)
            raise
        except Exception as exc:
            _cleanup_partial(partial_path)
            raise FinancialSourceTimeArtifactError(
                "financial source-time artifact write failed"
            ) from exc
        return self._inspect_existing(reference, final_path)

    def read(self, reference: FinancialSourceTimeArtifactRef) -> bytes:
        """Return exact decrypted bytes only when the full reference matches."""

        stored, body = self._read_verified(reference)
        if stored != reference:
            raise FinancialSourceTimeArtifactError(
                "financial source-time artifact reference mismatch"
            )
        return body

    def inspect(
        self,
        reference: FinancialSourceTimeArtifactRef,
    ) -> FinancialSourceTimeArtifactRef:
        """Verify an encrypted source-time envelope without returning its body."""

        stored, _body = self._read_verified(reference)
        if stored != reference:
            raise FinancialSourceTimeArtifactError(
                "financial source-time artifact reference mismatch"
            )
        return stored

    def _validate_reference(self, reference: FinancialSourceTimeArtifactRef) -> None:
        """Reject another artifact kind, location, or key identity."""

        if not isinstance(reference, FinancialSourceTimeArtifactRef):
            raise FinancialSourceTimeArtifactError("financial source-time reference is invalid")
        if reference.location != source_time_location_for(reference.capture_id):
            raise FinancialSourceTimeArtifactError("financial source-time location is invalid")
        if (
            reference.format_version != FORMAT_VERSION
            or reference.encryption_algorithm != ENCRYPTION_ALGORITHM
            or reference.encryption_key_ref != self._encryption_key_ref
            or reference.encryption_key_version != self._encryption_key_version
        ):
            raise FinancialSourceTimeArtifactError(
                "financial source-time encryption metadata mismatch"
            )
        if reference.body_size_bytes > self._max_body_bytes:
            raise FinancialSourceTimeArtifactError("financial source-time body is too large")

    def _validate_body(self, reference: FinancialSourceTimeArtifactRef, body: bytes) -> None:
        """Require exact byte count and digest before encryption."""

        if (
            type(body) is not bytes
            or len(body) != reference.body_size_bytes
            or hashlib.sha256(body).hexdigest() != reference.body_sha256
        ):
            raise FinancialSourceTimeArtifactError("financial source-time body mismatch")

    def _path_for(self, reference: FinancialSourceTimeArtifactRef) -> Path:
        """Resolve the canonical capture path below the configured root."""

        parts = reference.location.split("/")
        if any(part in {"", ".", ".."} for part in parts) or any(
            "\\" in part or any(ord(character) < 32 for character in part) for part in parts
        ):
            raise FinancialSourceTimeArtifactError("financial source-time location is invalid")
        candidate = self._root.joinpath(*parts)
        try:
            _reject_symlink_components(candidate.parent)
            if candidate.is_symlink() or _is_windows_reparse_point(candidate):
                raise OSError("artifact path is a link")
            candidate.absolute().relative_to(self._root)
        except (OSError, ValueError) as exc:
            raise FinancialSourceTimeArtifactError(
                "financial source-time location is invalid"
            ) from exc
        return candidate

    def _encode(self, reference: FinancialSourceTimeArtifactRef, body: bytes) -> bytes:
        """Encrypt canonical metadata and body as one authenticated token."""

        metadata = {"kind": "financial_source_time_artifact", **reference.to_dict()}
        metadata_bytes = _json_bytes(metadata)
        if len(metadata_bytes) > _MAX_METADATA_BYTES:
            raise FinancialSourceTimeArtifactError("financial source-time metadata is too large")
        plaintext = _MAGIC + struct.pack(">Q", len(metadata_bytes)) + metadata_bytes + body
        encrypted = bytes(self._fernet.encrypt(plaintext))
        if len(encrypted) > self._max_token_bytes:
            raise FinancialSourceTimeArtifactError("financial source-time token is too large")
        return encrypted

    def _write_partial(self, path: Path, encrypted: bytes) -> None:
        """Write one private staging file and verify the byte count."""

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as target:
                descriptor = -1
                if target.write(encrypted) != len(encrypted):
                    raise OSError("artifact token short write")
                target.flush()
                os.fsync(target.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _inspect_existing(
        self,
        reference: FinancialSourceTimeArtifactRef,
        path: Path,
    ) -> FinancialSourceTimeArtifactRef:
        """Require an existing immutable winner to be byte-for-byte equivalent."""

        stored, _body = self._read_path(path)
        if stored != reference:
            raise FinancialSourceTimeArtifactError(
                "financial source-time immutable artifact conflict"
            )
        return stored

    def _read_verified(
        self,
        reference: FinancialSourceTimeArtifactRef,
    ) -> tuple[FinancialSourceTimeArtifactRef, bytes]:
        """Resolve, decrypt, and validate one exact reference."""

        self._validate_reference(reference)
        stored, body = self._read_path(self._path_for(reference))
        if stored.capture_id != reference.capture_id:
            raise FinancialSourceTimeArtifactError(
                "financial source-time capture identity mismatch"
            )
        return stored, body

    def _read_path(self, path: Path) -> tuple[FinancialSourceTimeArtifactRef, bytes]:
        """Read a bounded token and validate its authenticated envelope."""

        if not path.exists() or path.is_symlink() or _is_windows_reparse_point(path):
            raise FinancialSourceTimeArtifactError("financial source-time artifact is missing")
        try:
            declared_size = path.stat().st_size
            if declared_size <= 0 or declared_size > self._max_token_bytes:
                raise ValueError("artifact token size is invalid")
            encrypted = path.read_bytes()
            if len(encrypted) != declared_size:
                raise ValueError("artifact token changed while reading")
            plaintext = bytes(self._fernet.decrypt(encrypted))
        except (InvalidToken, OSError, ValueError) as exc:
            raise FinancialSourceTimeArtifactError(
                "financial source-time artifact cannot be authenticated"
            ) from exc
        if len(plaintext) < _PREFIX_BYTES or plaintext[: len(_MAGIC)] != _MAGIC:
            raise FinancialSourceTimeArtifactError("financial source-time envelope is invalid")
        metadata_length = struct.unpack(">Q", plaintext[len(_MAGIC) : _PREFIX_BYTES])[0]
        metadata_end = _PREFIX_BYTES + metadata_length
        if metadata_length > _MAX_METADATA_BYTES or metadata_end > len(plaintext):
            raise FinancialSourceTimeArtifactError("financial source-time metadata is invalid")
        metadata_bytes = plaintext[_PREFIX_BYTES:metadata_end]
        try:
            metadata = _decode_json_object(metadata_bytes)
            if _json_bytes(metadata) != metadata_bytes:
                raise ValueError("metadata is not canonical")
            reference = _reference_from_metadata(metadata)
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancialSourceTimeArtifactError(
                "financial source-time metadata cannot be decoded"
            ) from exc
        body = plaintext[metadata_end:]
        self._validate_reference(reference)
        self._validate_body(reference, body)
        return reference, body


def source_time_location_for(capture_id: UUID) -> str:
    """Return the only allowed opaque relative location for a capture UUID."""

    if not isinstance(capture_id, UUID):
        raise ValueError("capture_id must be a UUID")
    text = str(capture_id)
    return f"financial-source-time/{text[:2]}/{text}.bin"


def _reference_from_metadata(
    metadata: Mapping[str, object],
) -> FinancialSourceTimeArtifactRef:
    """Decode strict authenticated metadata into a typed reference."""

    if frozenset(metadata) != _METADATA_KEYS:
        raise ValueError("financial source-time metadata keys are invalid")
    if metadata.get("kind") != "financial_source_time_artifact":
        raise ValueError("financial source-time metadata kind is invalid")
    return FinancialSourceTimeArtifactRef(
        capture_id=UUID(_text(metadata, "capture_id")),
        location=_text(metadata, "location"),
        provider_name=_text(metadata, "provider_name"),
        dataset_key=_text(metadata, "dataset_key"),
        requested_asset_code=_text(metadata, "requested_asset_code"),
        requested_announcement_date=date.fromisoformat(
            _text(metadata, "requested_announcement_date")
        ),
        body_sha256=_text(metadata, "body_sha256"),
        body_size_bytes=_integer(metadata, "body_size_bytes"),
        response_completed_at=datetime.fromisoformat(_text(metadata, "response_completed_at")),
        response_row_count=_integer(metadata, "response_row_count"),
        format_version=_text(metadata, "format_version"),
        encryption_algorithm=_text(metadata, "encryption_algorithm"),
        encryption_key_ref=_text(metadata, "encryption_key_ref"),
        encryption_key_version=_text(metadata, "encryption_key_version"),
    )


def _text(metadata: Mapping[str, object], key: str) -> str:
    """Narrow an authenticated metadata field to exact text."""

    value = metadata[key]
    if not isinstance(value, str):
        raise ValueError(f"financial source-time metadata {key} must be text")
    return value


def _integer(metadata: Mapping[str, object], key: str) -> int:
    """Narrow an authenticated metadata field to a strict integer."""

    value = metadata[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"financial source-time metadata {key} must be an integer")
    return value


def _config_text(value: object, name: str) -> None:
    """Validate explicit store configuration text."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise FinancialSourceTimeArtifactError(f"financial source-time {name} is invalid")


__all__ = [
    "ENCRYPTION_ALGORITHM",
    "FORMAT_VERSION",
    "FinancialSourceTimeArtifactError",
    "FinancialSourceTimeBodyStore",
    "source_time_location_for",
]
