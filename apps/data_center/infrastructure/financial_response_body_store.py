"""Encrypted, immutable filesystem storage for original financial response bytes."""

from __future__ import annotations

import ctypes
import json
import os
import stat
import struct
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Final, NoReturn
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken

from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from core.exceptions import DataFetchError

FORMAT_VERSION: Final[str] = "financial-response-body-fernet-v1"
ENCRYPTION_ALGORITHM: Final[str] = "fernet-aes128cbc-hmacsha256"
LOCATION_SCHEME: Final[str] = "financial-response"
_MAGIC: Final[bytes] = b"FRA1"
_PREFIX_BYTES: Final[int] = len(_MAGIC) + 8
_MAX_METADATA_BYTES: Final[int] = 64 * 1024
_MOVEFILE_WRITE_THROUGH: Final[int] = 0x00000008
_ERROR_FILE_EXISTS: Final[int] = 80
_ERROR_ALREADY_EXISTS: Final[int] = 183
_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "format_version",
        "capture_id",
        "dataset_key",
        "provider_name",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "request_scope",
        "response_scope",
        "response_scope_basis",
        "body_scope",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
    }
)
_REQUEST_SCOPE_KEYS: Final[frozenset[str]] = frozenset(
    {"provider_name", "dataset_key", "asset_code", "period_limit"}
)
_RESPONSE_SCOPE_KEYS: Final[frozenset[str]] = frozenset({"asset_codes", "period_ends", "row_count"})


class FinancialResponseArtifactError(DataFetchError):
    """Base error for sanitized original-response artifact failures."""

    default_message = "金融响应原始字节原件处理失败。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_FAILED"


class FinancialResponseArtifactConfigurationError(FinancialResponseArtifactError):
    """Raised when an encrypted artifact store lacks explicit configuration."""

    default_message = "金融响应原件加密存储未配置。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"


class FinancialResponseArtifactConflictError(FinancialResponseArtifactError):
    """Raised when an immutable capture identity is reused with different data."""

    default_message = "金融响应原件不可变标识发生冲突。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_IMMUTABLE_CONFLICT"


class FinancialResponseArtifactIncompleteError(FinancialResponseArtifactError):
    """Raised when a complete authenticated artifact cannot be read."""

    default_message = "金融响应原件不完整或无法验证。"
    default_code = "FINANCIAL_RESPONSE_ARTIFACT_INCOMPLETE"


class FinancialResponseBodyStore:
    """Store exact response bytes in an authenticated encrypted envelope.

    The caller must provide every storage setting, including the mounted root,
    Fernet key, key reference, key version, and byte limit.  The class has no
    plaintext fallback and does not derive locations from provider data.
    """

    def __init__(
        self,
        root: Path,
        *,
        encryption_key: bytes,
        encryption_key_ref: str,
        encryption_key_version: str,
        max_body_bytes: int,
    ) -> None:
        """Initialize an explicitly configured encrypted response store."""

        if not isinstance(root, Path) or not str(root).strip():
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件存储根目录无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            )
        _require_config_text(encryption_key_ref, "encryption_key_ref")
        _require_config_text(encryption_key_version, "encryption_key_version")
        if type(encryption_key) is not bytes or not encryption_key:
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件加密密钥无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            )
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件大小上限无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            )
        try:
            fernet = Fernet(encryption_key)
        except (TypeError, ValueError) as exc:
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件加密密钥无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            ) from exc
        try:
            root_path = root.expanduser()
            _reject_symlink_components(root_path)
            if root_path.exists() and not root_path.is_dir():
                raise OSError("artifact root is not a directory")
            root_path.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(root_path)
            self._root = root_path.resolve()
            if not self._root.is_dir():
                raise OSError("artifact root is not a directory")
        except FinancialResponseArtifactError:
            raise
        except OSError as exc:
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件存储根目录不可用。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            ) from exc
        self._fernet = fernet
        self._encryption_key_ref = encryption_key_ref
        self._encryption_key_version = encryption_key_version
        self._max_body_bytes = max_body_bytes
        plaintext_limit = _PREFIX_BYTES + _MAX_METADATA_BYTES + max_body_bytes
        self._max_token_bytes = ((plaintext_limit + 73 + 2) // 3) * 4

    def store(self, artifact: FinancialResponseArtifact) -> FinancialResponseArtifactRef:
        """Atomically publish one exact body or return an identical replay."""

        self._validate_artifact(artifact)
        expected = self._reference_for_artifact(artifact)
        final_path = self._path_for(expected.location)
        if final_path.exists():
            return self._inspect_existing(expected, final_path)

        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(final_path.parent)
            final_path = self._path_for(expected.location)
            partial_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.partial")
            encrypted = self._encode_envelope(artifact)
            self._write_partial(partial_path, encrypted)
            try:
                _publish_no_replace(partial_path, final_path)
                _sync_directory_chain(final_path.parent, self._root)
            except FileExistsError:
                _cleanup_partial(partial_path)
                return self._inspect_existing(expected, final_path)
            except Exception:
                _cleanup_partial(partial_path)
                raise
        except FinancialResponseArtifactError:
            raise
        except Exception as exc:
            if "partial_path" in locals():
                _cleanup_partial(partial_path)
            raise FinancialResponseArtifactError(
                "金融响应原件写入失败。", code="FINANCIAL_RESPONSE_ARTIFACT_WRITE_FAILED"
            ) from exc

        return self._inspect_existing(expected, final_path)

    def _write_partial(self, partial_path: Path, encrypted: bytes) -> None:
        """Write one private binary staging file with an explicit short-write check."""

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        binary_flag = getattr(os, "O_BINARY", 0)
        no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
        fd = -1
        try:
            fd = os.open(partial_path, flags | binary_flag | no_follow_flag, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as raw_file:
                fd = -1
                written = raw_file.write(encrypted)
                if written != len(encrypted):
                    raise OSError("artifact encrypted token short write")
                raw_file.flush()
                os.fsync(raw_file.fileno())
        finally:
            if fd >= 0:
                os.close(fd)

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Read and verify the exact original bytes for an opaque reference."""

        stored_reference, body = self._read_verified(reference)
        if stored_reference != reference:
            raise FinancialResponseArtifactConflictError(
                "金融响应原件引用元数据不一致。",
                code="FINANCIAL_RESPONSE_ARTIFACT_REFERENCE_MISMATCH",
            )
        return body

    def inspect(self, reference: FinancialResponseArtifactRef) -> FinancialResponseArtifactRef:
        """Verify an artifact envelope without returning its body."""

        stored_reference, _body = self._read_verified(reference)
        if stored_reference != reference:
            raise FinancialResponseArtifactConflictError(
                "金融响应原件引用元数据不一致。",
                code="FINANCIAL_RESPONSE_ARTIFACT_REFERENCE_MISMATCH",
            )
        return stored_reference

    def _validate_artifact(self, artifact: FinancialResponseArtifact) -> None:
        """Apply the store's explicit byte ceiling after domain validation."""

        if not isinstance(artifact, FinancialResponseArtifact):
            raise FinancialResponseArtifactConfigurationError(
                "金融响应原件类型无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
            )
        if artifact.evidence.body_size_bytes > self._max_body_bytes:
            raise FinancialResponseArtifactError(
                "金融响应原件超过大小上限。", code="FINANCIAL_RESPONSE_ARTIFACT_TOO_LARGE"
            )

    def _reference_for_artifact(
        self, artifact: FinancialResponseArtifact
    ) -> FinancialResponseArtifactRef:
        """Project an artifact into a body-free immutable reference."""

        return FinancialResponseArtifactRef(
            capture_id=artifact.capture_id,
            location=_location_for(artifact.capture_id),
            evidence=artifact.evidence,
            format_version=FORMAT_VERSION,
            encryption_algorithm=ENCRYPTION_ALGORITHM,
            encryption_key_ref=self._encryption_key_ref,
            encryption_key_version=self._encryption_key_version,
        )

    def _encode_envelope(self, artifact: FinancialResponseArtifact) -> bytes:
        """Encrypt metadata and exact body bytes as one authenticated token."""

        metadata = _metadata_for_artifact(
            artifact,
            encryption_key_ref=self._encryption_key_ref,
            encryption_key_version=self._encryption_key_version,
        )
        metadata_bytes = _json_bytes(metadata)
        if len(metadata_bytes) > _MAX_METADATA_BYTES:
            raise FinancialResponseArtifactError(
                "金融响应原件元数据超过大小上限。",
                code="FINANCIAL_RESPONSE_ARTIFACT_METADATA_TOO_LARGE",
            )
        plaintext = _MAGIC + struct.pack(">Q", len(metadata_bytes)) + metadata_bytes + artifact.body
        try:
            encrypted = self._fernet.encrypt(plaintext)
        except Exception as exc:
            raise FinancialResponseArtifactError(
                "金融响应原件加密失败。", code="FINANCIAL_RESPONSE_ARTIFACT_WRITE_FAILED"
            ) from exc
        if not isinstance(encrypted, bytes):
            raise FinancialResponseArtifactError(
                "金融响应原件加密结果无效。", code="FINANCIAL_RESPONSE_ARTIFACT_WRITE_FAILED"
            )
        if len(encrypted) > self._max_token_bytes:
            raise FinancialResponseArtifactError(
                "金融响应原件超过大小上限。", code="FINANCIAL_RESPONSE_ARTIFACT_TOO_LARGE"
            )
        return encrypted

    def _inspect_existing(
        self,
        expected: FinancialResponseArtifactRef,
        final_path: Path,
    ) -> FinancialResponseArtifactRef:
        """Read a completed winner and require exact immutable equality."""

        actual, _body = self._read_path(final_path)
        if actual != expected:
            raise FinancialResponseArtifactConflictError(
                "金融响应原件不可变元数据发生冲突。",
                code="FINANCIAL_RESPONSE_ARTIFACT_IMMUTABLE_CONFLICT",
            )
        return actual

    def _read_verified(
        self, reference: FinancialResponseArtifactRef
    ) -> tuple[FinancialResponseArtifactRef, bytes]:
        """Resolve one reference and verify its authenticated envelope."""

        self._validate_reference(reference)
        path = self._path_for(reference.location)
        return self._read_path(path, expected=reference)

    def _validate_reference(self, reference: FinancialResponseArtifactRef) -> None:
        """Reject forged locations and references for another encryption version."""

        if not isinstance(reference, FinancialResponseArtifactRef):
            raise FinancialResponseArtifactError(
                "金融响应原件引用无效。", code="FINANCIAL_RESPONSE_ARTIFACT_REFERENCE_INVALID"
            )
        if reference.location != _location_for(reference.capture_id):
            raise FinancialResponseArtifactError(
                "金融响应原件位置无效。", code="FINANCIAL_RESPONSE_ARTIFACT_LOCATION_INVALID"
            )
        if (
            reference.format_version != FORMAT_VERSION
            or reference.encryption_algorithm != ENCRYPTION_ALGORITHM
            or reference.encryption_key_ref != self._encryption_key_ref
            or reference.encryption_key_version != self._encryption_key_version
        ):
            raise FinancialResponseArtifactError(
                "金融响应原件加密元数据不匹配。",
                code="FINANCIAL_RESPONSE_ARTIFACT_ENCRYPTION_MISMATCH",
            )

    def _path_for(self, location: str) -> Path:
        """Resolve an opaque location without allowing traversal or symlinks."""

        try:
            parsed = urlparse(location)
            if (
                parsed.scheme != LOCATION_SCHEME
                or parsed.netloc
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            relative_text = unquote(parsed.path).lstrip("/")
            if (
                not relative_text
                or "\\" in relative_text
                or any(ord(character) < 32 for character in relative_text)
            ):
                raise ValueError
            parts = relative_text.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise ValueError
            relative = Path(*parts)
            if relative.is_absolute() or relative.anchor:
                raise ValueError
            candidate = self._root / relative
            _reject_symlink_components(candidate.parent)
            if candidate.is_symlink() or _is_windows_reparse_point(candidate):
                raise ValueError
            # The path components were checked for symlinks above.  Avoid
            # ``Path.resolve`` here: on Windows a concurrently-created final
            # path can be returned with the extended ``\\?\`` prefix, which
            # is unequal to the already-resolved configured root.
            resolved = candidate.absolute()
            resolved.relative_to(self._root)
            return resolved
        except (OSError, ValueError) as exc:
            raise FinancialResponseArtifactError(
                "金融响应原件位置无效。", code="FINANCIAL_RESPONSE_ARTIFACT_LOCATION_INVALID"
            ) from exc

    def _read_path(
        self,
        path: Path,
        *,
        expected: FinancialResponseArtifactRef | None = None,
    ) -> tuple[FinancialResponseArtifactRef, bytes]:
        """Read, decrypt, parse, and hash one final artifact file."""

        if not path.exists():
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件不存在。", code="FINANCIAL_RESPONSE_ARTIFACT_MISSING"
            )
        if path.is_symlink() or _is_windows_reparse_point(path) or not path.is_file():
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件文件无效。", code="FINANCIAL_RESPONSE_ARTIFACT_INCOMPLETE"
            )
        try:
            declared_size = path.stat().st_size
            if declared_size <= 0 or declared_size > self._max_token_bytes:
                raise ValueError
            with path.open("rb") as source:
                encrypted = source.read(self._max_token_bytes + 1)
            if len(encrypted) > self._max_token_bytes or len(encrypted) != declared_size:
                raise ValueError
            plaintext = self._fernet.decrypt(encrypted)
        except InvalidToken as exc:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件认证失败。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            ) from exc
        except (OSError, ValueError) as exc:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件无法读取。", code="FINANCIAL_RESPONSE_ARTIFACT_INCOMPLETE"
            ) from exc
        stored_reference, body = self._decode_envelope(plaintext)
        if expected is not None and stored_reference.capture_id != expected.capture_id:
            raise FinancialResponseArtifactConflictError(
                "金融响应原件捕获标识不一致。",
                code="FINANCIAL_RESPONSE_ARTIFACT_REFERENCE_MISMATCH",
            )
        return stored_reference, body

    def _decode_envelope(self, plaintext: bytes) -> tuple[FinancialResponseArtifactRef, bytes]:
        """Validate framing, typed metadata, and exact body hash/size."""

        if len(plaintext) < _PREFIX_BYTES or plaintext[: len(_MAGIC)] != _MAGIC:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件封装无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            )
        metadata_length = struct.unpack(">Q", plaintext[len(_MAGIC) : _PREFIX_BYTES])[0]
        metadata_start = _PREFIX_BYTES
        metadata_end = metadata_start + metadata_length
        if metadata_length > _MAX_METADATA_BYTES or metadata_end > len(plaintext):
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件元数据无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            )
        metadata_bytes = plaintext[metadata_start:metadata_end]
        try:
            metadata = _decode_json_object(metadata_bytes)
            canonical_metadata = _json_bytes(metadata)
        except ValueError as exc:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件元数据无法解析。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            ) from exc
        if canonical_metadata != metadata_bytes:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件元数据编码无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            )
        body = plaintext[metadata_end:]
        if len(body) > self._max_body_bytes:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件超过大小上限。", code="FINANCIAL_RESPONSE_ARTIFACT_TOO_LARGE"
            )
        try:
            reference = _reference_from_metadata(metadata)
        except ValueError as exc:
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件元数据无法验证.", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            ) from exc
        if reference.body_size_bytes != len(body) or reference.body_sha256 != raw_body_sha256(body):
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件摘要无法验证。", code="FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
            )
        if (
            reference.format_version != FORMAT_VERSION
            or reference.encryption_algorithm != ENCRYPTION_ALGORITHM
            or reference.encryption_key_ref != self._encryption_key_ref
            or reference.encryption_key_version != self._encryption_key_version
        ):
            raise FinancialResponseArtifactIncompleteError(
                "金融响应原件加密元数据不匹配。",
                code="FINANCIAL_RESPONSE_ARTIFACT_ENCRYPTION_MISMATCH",
            )
        return reference, body


def _metadata_for_artifact(
    artifact: FinancialResponseArtifact,
    *,
    encryption_key_ref: str,
    encryption_key_version: str,
) -> dict[str, object]:
    """Build an allowlisted metadata envelope without source-time fields."""

    evidence = artifact.evidence
    request_scope = evidence.request_scope.to_dict()
    response_scope = evidence.response_scope.to_dict()
    return {
        "kind": "financial_response_artifact",
        "format_version": FORMAT_VERSION,
        "capture_id": str(artifact.capture_id),
        "dataset_key": evidence.request_scope.dataset_key,
        "provider_name": evidence.request_scope.provider_name,
        "body_sha256": evidence.body_sha256,
        "body_size_bytes": evidence.body_size_bytes,
        "response_completed_at": evidence.response_completed_at.isoformat(),
        "request_scope": request_scope,
        "response_scope": response_scope,
        "response_scope_basis": "caller_declared",
        "body_scope": evidence.body_scope.value,
        "encryption_algorithm": ENCRYPTION_ALGORITHM,
        "encryption_key_ref": encryption_key_ref,
        "encryption_key_version": encryption_key_version,
    }


def _reference_from_metadata(metadata: Mapping[str, object]) -> FinancialResponseArtifactRef:
    """Narrow authenticated JSON metadata into typed domain evidence."""

    _expect_keys(metadata, _METADATA_KEYS, "metadata")
    kind = _required_text(metadata, "kind")
    if kind != "financial_response_artifact":
        raise ValueError("metadata kind is invalid")
    format_version = _required_text(metadata, "format_version")
    encryption_algorithm = _required_text(metadata, "encryption_algorithm")
    encryption_key_ref = _required_text(metadata, "encryption_key_ref")
    encryption_key_version = _required_text(metadata, "encryption_key_version")
    capture_id = _parse_uuid(_required_text(metadata, "capture_id"))
    body_sha256 = _required_text(metadata, "body_sha256")
    body_size_bytes = _required_int(metadata, "body_size_bytes")
    response_completed_at = _parse_datetime(
        _required_text(metadata, "response_completed_at"), "response_completed_at"
    )
    request_scope = _request_scope_from_metadata(metadata["request_scope"])
    response_scope = _response_scope_from_metadata(metadata["response_scope"])
    if _required_text(metadata, "dataset_key") != request_scope.dataset_key:
        raise ValueError("metadata dataset key mismatch")
    if _required_text(metadata, "provider_name") != request_scope.provider_name:
        raise ValueError("metadata provider mismatch")
    if _required_text(metadata, "response_scope_basis") != "caller_declared":
        raise ValueError("metadata response scope basis is invalid")
    try:
        body_scope = FinancialResponseBodyScope(_required_text(metadata, "body_scope"))
        evidence = FinancialResponseEvidence(
            body_sha256=body_sha256,
            body_size_bytes=body_size_bytes,
            response_completed_at=response_completed_at,
            request_scope=request_scope,
            response_scope=response_scope,
            body_scope=body_scope,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata evidence is invalid") from exc
    return FinancialResponseArtifactRef(
        capture_id=capture_id,
        location=_location_for(capture_id),
        evidence=evidence,
        format_version=format_version,
        encryption_algorithm=encryption_algorithm,
        encryption_key_ref=encryption_key_ref,
        encryption_key_version=encryption_key_version,
    )


def _request_scope_from_metadata(value: object) -> FinancialRequestScope:
    """Narrow request-scope metadata without accepting arbitrary JSON."""

    mapping = _as_object_mapping(value, "request_scope")
    _expect_keys(mapping, _REQUEST_SCOPE_KEYS, "request_scope")
    return FinancialRequestScope(
        provider_name=_required_text(mapping, "provider_name"),
        dataset_key=_required_text(mapping, "dataset_key"),
        asset_code=_required_text(mapping, "asset_code"),
        period_limit=_required_positive_int(mapping, "period_limit"),
    )


def _response_scope_from_metadata(value: object) -> FinancialResponseScope:
    """Narrow response-scope metadata without deriving source identity."""

    mapping = _as_object_mapping(value, "response_scope")
    _expect_keys(mapping, _RESPONSE_SCOPE_KEYS, "response_scope")
    assets = _string_tuple(mapping.get("asset_codes"), "asset_codes")
    period_values = mapping.get("period_ends")
    if not isinstance(period_values, list):
        raise ValueError("period_ends must be a list")
    periods = tuple(_parse_date(value, "period_ends") for value in period_values)
    return FinancialResponseScope(
        asset_codes=assets,
        period_ends=periods,
        row_count=_required_nonnegative_int(mapping, "row_count"),
    )


def _decode_json_object(value: bytes) -> dict[str, object]:
    """Decode authenticated metadata with duplicate-key and constant rejection."""

    try:
        decoded = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("metadata JSON is invalid") from exc
    return _as_object_mapping(decoded, "metadata")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys rather than silently choosing the last value."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    """Reject non-standard JSON numeric constants in authenticated metadata."""

    raise ValueError(f"invalid JSON constant: {value}")


def _json_bytes(value: Mapping[str, object]) -> bytes:
    """Encode allowlisted metadata canonically for envelope framing."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata JSON cannot be encoded") from exc


def _as_object_mapping(value: object, field_name: str) -> dict[str, object]:
    """Narrow a JSON object and reject non-string or duplicate-shaped keys."""

    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        result[key] = item
    return result


def _expect_keys(mapping: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Require an exact metadata schema to prevent hidden sensitive fields."""

    if frozenset(mapping) != expected:
        raise ValueError(f"{field_name} keys are invalid")


def _required_text(mapping: Mapping[str, object], field_name: str) -> str:
    """Read one non-empty bounded metadata string."""

    value = mapping.get(field_name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be text")
    if len(value) > 512 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _required_int(mapping: Mapping[str, object], field_name: str) -> int:
    """Read one integer metadata field without accepting booleans."""

    value = mapping.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _required_positive_int(mapping: Mapping[str, object], field_name: str) -> int:
    """Read one positive integer metadata field."""

    value = _required_int(mapping, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _required_nonnegative_int(mapping: Mapping[str, object], field_name: str) -> int:
    """Read one non-negative integer metadata field."""

    return _required_int(mapping, field_name)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    """Narrow a JSON string array into an immutable tuple."""

    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain strings")
        result.append(item)
    return tuple(result)


def _parse_uuid(value: str) -> UUID:
    """Parse the canonical lowercase capture UUID representation."""

    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("capture_id is invalid") from exc
    if str(parsed) != value:
        raise ValueError("capture_id must be canonical")
    return parsed


def _parse_date(value: object, field_name: str) -> date:
    """Parse a date-only response period without accepting an instant."""

    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{field_name} must be a date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be canonical")
    return parsed


def _parse_datetime(value: str, field_name: str) -> datetime:
    """Parse one serialized aware timestamp; the domain enforces UTC."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be canonical")
    return parsed


def _require_config_text(value: str, field_name: str) -> None:
    """Validate non-secret configuration labels without normalizing them."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise FinancialResponseArtifactConfigurationError(
            f"金融响应原件配置 {field_name} 无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    if len(value) > 512 or any(ord(character) < 32 for character in value):
        raise FinancialResponseArtifactConfigurationError(
            f"金融响应原件配置 {field_name} 无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )


def _location_for(capture_id: UUID) -> str:
    """Derive only the opaque server-issued capture location."""

    return f"{LOCATION_SCHEME}:///v1/{capture_id}.frb"


def _reject_symlink_components(path: Path) -> None:
    """Reject symlinked root or parent components before file operations."""

    absolute = path.absolute()
    current = Path(absolute.anchor) if absolute.anchor else Path()
    for part in absolute.parts:
        if part == absolute.anchor:
            continue
        current /= part
        if current.is_symlink() or _is_windows_reparse_point(current):
            raise FinancialResponseArtifactError(
                "金融响应原件路径包含符号链接。",
                code="FINANCIAL_RESPONSE_ARTIFACT_LOCATION_INVALID",
            )


def _is_windows_reparse_point(path: Path) -> bool:
    """Reject Windows junctions as well as ordinary symbolic links."""

    if sys.platform == "win32":
        try:
            attributes = path.lstat().st_file_attributes
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise FinancialResponseArtifactError(
                "金融响应原件路径无法检查。",
                code="FINANCIAL_RESPONSE_ARTIFACT_LOCATION_INVALID",
            ) from exc
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _cleanup_partial(path: Path) -> None:
    """Best-effort cleanup of only this operation's private staging path."""

    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _publish_no_replace(source: Path, target: Path) -> None:
    """Publish atomically without replacing an existing completed artifact."""

    if os.name == "nt":
        _move_file_windows_no_replace(source, target)
        return
    os.link(source, target)
    source.unlink()


def _move_file_windows_no_replace(source: Path, target: Path) -> None:
    """Use Windows MoveFileEx write-through semantics without overwrite."""

    if sys.platform == "win32":
        move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file_ex.restype = ctypes.c_int
        moved = move_file_ex(
            str(source),
            str(target),
            _MOVEFILE_WRITE_THROUGH,
        )
        if moved:
            return
        error_code = ctypes.get_last_error()
        if error_code in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
            raise FileExistsError(error_code, "artifact target exists", str(target))
        raise OSError(error_code, "artifact atomic publish failed", str(target))
    raise OSError("Windows artifact publication is unavailable on this platform")


def _sync_directory(path: Path) -> None:
    """Persist a POSIX directory rename; Windows uses write-through rename."""

    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _sync_directory_chain(directory: Path, root: Path) -> None:
    """Persist a new artifact directory and each newly-created parent entry."""

    if os.name == "nt":
        return
    cursor = directory
    while True:
        _sync_directory(cursor)
        if cursor == root:
            return
        try:
            cursor.relative_to(root)
        except ValueError as exc:
            raise OSError("artifact directory escaped configured root") from exc
        cursor = cursor.parent


__all__ = [
    "ENCRYPTION_ALGORITHM",
    "FORMAT_VERSION",
    "FinancialResponseArtifactConfigurationError",
    "FinancialResponseArtifactConflictError",
    "FinancialResponseArtifactError",
    "FinancialResponseArtifactIncompleteError",
    "FinancialResponseBodyStore",
]
