"""Deterministic compressed RawPayload archive store with safe staging restore."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet, InvalidToken

from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.domain.retention import ArchiveArtifact, ArchiveMember

FORMAT_VERSION = "raw-payload-fernet-jsonl-gzip-v1"
ENCRYPTION_ALGORITHM = "fernet-aes128cbc-hmacsha256"
_MAX_OBJECTS = 10_000
_MAX_RESTORED_BYTES = 8 * 1024 * 1024 * 1024
_MAX_HEADER_LINE_BYTES = 64 * 1024
_MAX_ENCRYPTED_LINE_BYTES = 128 * 1024 * 1024


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode one canonical JSON line for deterministic archive checksums."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _aware_iso(value: datetime, field_name: str) -> str:
    """Serialize only timezone-aware timestamps."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.isoformat()


def _parse_datetime(value: object, field_name: str) -> datetime:
    """Parse and validate one archive timestamp."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _payload_record(payload: RawPayload) -> dict[str, Any]:
    """Project one redacted payload into the versioned archive schema."""

    return {
        "kind": "raw_payload",
        "payload_id": payload.payload_id,
        "dataset_key": payload.dataset_key,
        "provider_name": payload.provider_name,
        "payload_hash": payload.payload_hash,
        "schema_fingerprint": payload.schema_fingerprint,
        "payload": payload.payload,
        "fetched_at": _aware_iso(payload.fetched_at, "RawPayload.fetched_at"),
        "request_params": payload.request_params,
        "run_id": payload.run_id,
        "batch_id": payload.batch_id,
        "content_type": payload.content_type,
        "parser_version": payload.parser_version,
        "redacted": payload.redacted,
        "payload_size_bytes": payload.payload_size_bytes,
        "retention_until": (
            _aware_iso(payload.retention_until, "RawPayload.retention_until")
            if payload.retention_until is not None
            else None
        ),
    }


def _require_json_object(value: object, field_name: str) -> dict[str, Any]:
    """Narrow untrusted JSON values at the archive boundary."""

    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _raw_payload(record: Mapping[str, Any]) -> RawPayload:
    """Reconstruct and validate one payload from untrusted archive JSON."""

    if record.get("kind") != "raw_payload":
        raise ValueError("archive_record_kind_invalid")
    retention_raw = record.get("retention_until")
    return RawPayload(
        payload_id=str(record.get("payload_id") or ""),
        dataset_key=str(record.get("dataset_key") or ""),
        provider_name=str(record.get("provider_name") or ""),
        payload_hash=str(record.get("payload_hash") or ""),
        schema_fingerprint=str(record.get("schema_fingerprint") or ""),
        payload=_require_json_object(record.get("payload"), "payload"),
        fetched_at=_parse_datetime(record.get("fetched_at"), "fetched_at"),
        request_params=_require_json_object(record.get("request_params"), "request_params"),
        run_id=str(record.get("run_id") or ""),
        batch_id=str(record.get("batch_id") or ""),
        content_type=str(record.get("content_type") or "application/json"),
        parser_version=str(record.get("parser_version") or ""),
        redacted=record.get("redacted") is True,
        payload_size_bytes=int(record.get("payload_size_bytes") or 0),
        retention_until=(
            _parse_datetime(retention_raw, "retention_until") if retention_raw is not None else None
        ),
    )


def _fsync_directory(path: Path) -> None:
    """Persist a rename on platforms that support opening directories."""

    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class FilesystemRawArchiveStore:
    """Cold archive adapter rooted at an explicitly configured mounted path."""

    def __init__(
        self,
        root: Path,
        *,
        encryption_key: bytes,
        encryption_key_ref: str,
        encryption_key_version: str,
    ) -> None:
        if not str(root).strip():
            raise ValueError("archive_root is required")
        self._root = root.expanduser().resolve()
        if not encryption_key_ref.strip() or not encryption_key_version.strip():
            raise ValueError("archive_encryption_metadata is required")
        try:
            self._fernet = Fernet(encryption_key)
        except (TypeError, ValueError) as exc:
            raise ValueError("archive_encryption_key_invalid") from exc
        self._encryption_key_ref = encryption_key_ref
        self._encryption_key_version = encryption_key_version

    def _dataset_segment(self, dataset_key: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", dataset_key).strip("-.") or "dataset"
        digest = hashlib.sha256(dataset_key.encode("utf-8")).hexdigest()[:12]
        return f"{slug[:80]}-{digest}"

    def _location_for(self, relative: Path) -> str:
        return "archive:///" + relative.as_posix().lstrip("/")

    def _path_for(self, location: str) -> Path:
        parsed = urlparse(location)
        if parsed.scheme != "archive" or parsed.netloc:
            raise ValueError("archive_location_scheme_not_allowed")
        relative_text = unquote(parsed.path).lstrip("/")
        relative = Path(relative_text)
        if not relative_text or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("archive_location_outside_root")
        resolved = (self._root / relative).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("archive_location_outside_root") from exc
        relative_parts = resolved.relative_to(self._root).parts
        cursor = self._root
        for part in relative_parts[:-1]:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise ValueError("archive_location_symlink_not_allowed")
        return resolved

    def write(
        self,
        *,
        archive_id: str,
        dataset_key: str,
        contract_version: str,
        schema_version: str,
        payloads: tuple[RawPayload, ...],
        created_at: datetime,
    ) -> ArchiveArtifact:
        """Atomically write one deterministic compressed JSONL archive."""

        if not archive_id.strip() or not dataset_key.strip():
            raise ValueError("archive identifiers are required")
        if not contract_version.strip() or not schema_version.strip():
            raise ValueError("archive contract metadata is required")
        if not payloads or len(payloads) > _MAX_OBJECTS:
            raise ValueError("archive payload count must be between 1 and 10000")
        _aware_iso(created_at, "created_at")
        ordered = tuple(sorted(payloads, key=lambda item: (item.fetched_at, item.payload_id)))
        if any(payload.dataset_key != dataset_key for payload in ordered):
            raise ValueError("archive_cross_dataset_payload")
        if len({payload.payload_id for payload in ordered}) != len(ordered):
            raise ValueError("archive_payload_ids_must_be_unique")
        relative = (
            Path("raw")
            / self._dataset_segment(dataset_key)
            / f"{archive_id}.{FORMAT_VERSION}.jsonl.gz"
        )
        location = self._location_for(relative)
        final_path = self._path_for(location)
        if final_path.exists():
            artifact = self.inspect(location)
            if artifact.archive_id != archive_id or artifact.dataset_key != dataset_key:
                raise ValueError("archive_existing_artifact_conflict")
            return artifact
        final_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = final_path.with_suffix(final_path.suffix + ".partial")
        header = {
            "kind": "manifest",
            "format_version": FORMAT_VERSION,
            "archive_id": archive_id,
            "dataset_key": dataset_key,
            "contract_version": contract_version,
            "schema_version": schema_version,
            "created_at": _aware_iso(created_at, "created_at"),
            "object_count": len(ordered),
            "encryption_algorithm": ENCRYPTION_ALGORITHM,
            "encryption_key_ref": self._encryption_key_ref,
            "encryption_key_version": self._encryption_key_version,
        }
        try:
            with partial_path.open("xb") as raw_file:
                with gzip.GzipFile(fileobj=raw_file, mode="wb", filename="", mtime=0) as stream:
                    stream.write(_json_bytes(header) + b"\n")
                    for payload in ordered:
                        encrypted = self._fernet.encrypt(_json_bytes(_payload_record(payload)))
                        stream.write(encrypted + b"\n")
                raw_file.flush()
                os.fsync(raw_file.fileno())
            os.replace(partial_path, final_path)
            _fsync_directory(final_path.parent)
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise
        return self.inspect(location)

    def _read(
        self,
        location: str,
        *,
        staging_path: Path | None = None,
    ) -> ArchiveArtifact:
        path = self._path_for(location)
        if not path.is_file():
            raise FileNotFoundError("archive_artifact_missing")
        size_bytes = path.stat().st_size
        if size_bytes < 1:
            raise ValueError("archive_artifact_empty")
        checksum_hasher = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checksum_hasher.update(chunk)
        checksum = f"sha256:{checksum_hasher.hexdigest()}"
        records: list[RawPayload] = []
        restored_bytes = 0
        with gzip.open(path, mode="rb") as stream:
            header_line = stream.readline(_MAX_HEADER_LINE_BYTES + 1)
            if not header_line:
                raise ValueError("archive_header_missing")
            if len(header_line) > _MAX_HEADER_LINE_BYTES:
                raise ValueError("archive_header_line_limit_exceeded")
            header_raw = json.loads(header_line)
            if not isinstance(header_raw, dict) or header_raw.get("kind") != "manifest":
                raise ValueError("archive_header_invalid")
            index = 0
            while True:
                line = stream.readline(_MAX_ENCRYPTED_LINE_BYTES + 1)
                if not line:
                    break
                index += 1
                if len(line) > _MAX_ENCRYPTED_LINE_BYTES:
                    raise ValueError("archive_record_line_limit_exceeded")
                restored_bytes += len(line)
                if restored_bytes > _MAX_RESTORED_BYTES:
                    raise ValueError("archive_restored_bytes_limit_exceeded")
                try:
                    decrypted = self._fernet.decrypt(line.rstrip(b"\n"))
                except InvalidToken as exc:
                    raise ValueError("archive_record_authentication_failed") from exc
                record_raw = json.loads(decrypted)
                if not isinstance(record_raw, dict):
                    raise ValueError("archive_record_invalid")
                payload = _raw_payload(record_raw)
                records.append(payload)
                if len(records) > _MAX_OBJECTS:
                    raise ValueError("archive_object_count_limit_exceeded")
                if staging_path is not None:
                    staged = staging_path / f"{index:08d}.json"
                    staged.write_bytes(_json_bytes(record_raw))
                    reconstructed_raw = json.loads(staged.read_bytes())
                    if not isinstance(reconstructed_raw, dict):
                        raise ValueError("archive_staging_record_invalid")
                    if _raw_payload(reconstructed_raw) != payload:
                        raise ValueError("archive_staging_round_trip_mismatch")
        object_count = int(header_raw.get("object_count") or 0)
        if object_count != len(records) or object_count < 1:
            raise ValueError("archive_object_count_mismatch")
        archive_id = str(header_raw.get("archive_id") or "")
        dataset_key = str(header_raw.get("dataset_key") or "")
        if (
            header_raw.get("encryption_algorithm") != ENCRYPTION_ALGORITHM
            or header_raw.get("encryption_key_ref") != self._encryption_key_ref
            or header_raw.get("encryption_key_version") != self._encryption_key_version
        ):
            raise ValueError("archive_encryption_metadata_mismatch")
        if any(payload.dataset_key != dataset_key for payload in records):
            raise ValueError("archive_cross_dataset_payload")
        members = tuple(
            ArchiveMember(
                payload_id=payload.payload_id,
                payload_hash=payload.payload_hash,
                record_digest=raw_payload_record_digest(payload),
                schema_fingerprint=payload.schema_fingerprint,
                fetched_at=payload.fetched_at,
                size_bytes=payload.payload_size_bytes,
            )
            for payload in records
        )
        return ArchiveArtifact(
            archive_id=archive_id,
            dataset_key=dataset_key,
            contract_version=str(header_raw.get("contract_version") or ""),
            schema_version=str(header_raw.get("schema_version") or ""),
            format_version=str(header_raw.get("format_version") or ""),
            encryption_algorithm=str(header_raw.get("encryption_algorithm") or ""),
            encryption_key_ref=str(header_raw.get("encryption_key_ref") or ""),
            encryption_key_version=str(header_raw.get("encryption_key_version") or ""),
            location=location,
            checksum=checksum,
            object_count=object_count,
            size_bytes=size_bytes,
            created_at=_parse_datetime(header_raw.get("created_at"), "created_at"),
            coverage_started_at=min(member.fetched_at for member in members),
            coverage_ended_at=max(member.fetched_at for member in members),
            members=members,
        )

    def inspect(self, location: str) -> ArchiveArtifact:
        """Independently read and validate all configured archive bytes."""

        return self._read(location)

    def restore_to_staging(self, location: str) -> ArchiveArtifact:
        """Restore every record to an isolated directory and validate round trips."""

        staging_root = self._root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="restore-", dir=staging_root) as directory:
            return self._read(location, staging_path=Path(directory))


__all__ = ["FORMAT_VERSION", "FilesystemRawArchiveStore"]
