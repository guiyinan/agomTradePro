"""Strict audit-archive JSON codec and append-only local artifact store."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from apps.audit.application.system_audit_archive import (
    AUDIT_ARCHIVE_SCHEMA_VERSION,
    SystemAuditArchiveBundle,
    SystemAuditArchiveCandidate,
    SystemAuditArchiveCorruption,
    SystemAuditArchiveManifest,
    SystemAuditArchiveStreamAnchor,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, JSONValue
from apps.audit.infrastructure.system_audit_event_codec import decode as decode_event

AUDIT_ARCHIVE_MAX_PAYLOAD_BYTES: Final[int] = 64 * 1024 * 1024

_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOP_KEYS: Final[frozenset[str]] = frozenset({"events", "manifest", "schema_version"})
_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "candidate",
        "created_at",
        "manifest_sha256",
        "member_count",
        "schema_version",
        "scope",
        "source_sha256",
        "streams",
        "window_ended_at",
        "window_started_at",
    }
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"commit", "matrix_sha256", "oci_revision", "version"}
)
_SCOPE_KEYS: Final[frozenset[str]] = frozenset({"owner_id", "tenant_id"})
_STREAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "first_predecessor_hash",
        "first_sequence_no",
        "last_content_hash",
        "last_sequence_no",
        "member_count",
        "replay_sha256",
        "stream_id",
    }
)


class SystemAuditArchiveStoreError(RuntimeError):
    """An append-only artifact cannot be written or restored exactly."""


def _pairs_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise SystemAuditArchiveCorruption("archive_duplicate_json_key")
        value[key] = child
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise SystemAuditArchiveCorruption(f"archive_{field}_must_be_object")
    return cast(Mapping[str, object], value)


def _exact(value: Mapping[str, object], keys: frozenset[str], field: str) -> None:
    if frozenset(value) != keys:
        if field == "bundle":
            raise SystemAuditArchiveCorruption("archive_unknown_or_missing_keys")
        raise SystemAuditArchiveCorruption(f"archive_{field}_unknown_or_missing_keys")


def _text(value: object, field: str) -> str:
    if type(value) is not str:
        raise SystemAuditArchiveCorruption(f"archive_{field}_must_be_text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise SystemAuditArchiveCorruption(f"archive_{field}_must_be_integer")
    return value


def _nullable_text(value: object, field: str) -> str | None:
    if value is not None and type(value) is not str:
        raise SystemAuditArchiveCorruption(f"archive_{field}_must_be_text_or_null")
    return value


def _time(value: object, field: str) -> datetime:
    text = _text(value, field)
    if len(text) != 27 or not text.endswith("Z") or "." not in text:
        raise SystemAuditArchiveCorruption(f"archive_{field}_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        raise SystemAuditArchiveCorruption(f"archive_{field}_timestamp_invalid") from None
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise SystemAuditArchiveCorruption(f"archive_{field}_timestamp_not_canonical")
    return parsed


def _normalized_json(value: JSONValue) -> JSONValue:
    if isinstance(value, Mapping):
        return {key: _normalized_json(child) for key, child in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalized_json(child) for child in value]
    return value


def encode_archive(bundle: SystemAuditArchiveBundle) -> bytes:
    """Encode one fully revalidated archive into canonical UTF-8 JSON bytes."""

    bundle.__post_init__()
    return json.dumps(
        _normalized_json(bundle.to_payload()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_archive(payload: bytes) -> SystemAuditArchiveBundle:
    """Decode one exact closed-schema archive and reject byte substitution."""

    if type(payload) is not bytes or not payload or len(payload) > AUDIT_ARCHIVE_MAX_PAYLOAD_BYTES:
        raise SystemAuditArchiveCorruption("archive_payload_size_invalid")
    try:
        decoded: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs_object)
    except SystemAuditArchiveCorruption:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SystemAuditArchiveCorruption("archive_payload_json_invalid") from None
    top = _mapping(decoded, "bundle")
    _exact(top, _TOP_KEYS, "bundle")
    if _text(top["schema_version"], "schema_version") != AUDIT_ARCHIVE_SCHEMA_VERSION:
        raise SystemAuditArchiveCorruption("archive_schema_version_invalid")

    raw_manifest = _mapping(top["manifest"], "manifest")
    _exact(raw_manifest, _MANIFEST_KEYS, "manifest")
    raw_candidate = _mapping(raw_manifest["candidate"], "candidate")
    _exact(raw_candidate, _CANDIDATE_KEYS, "candidate")
    candidate = SystemAuditArchiveCandidate(
        commit=_text(raw_candidate["commit"], "candidate_commit"),
        version=_text(raw_candidate["version"], "candidate_version"),
        oci_revision=_text(raw_candidate["oci_revision"], "candidate_oci_revision"),
        matrix_sha256=_text(raw_candidate["matrix_sha256"], "candidate_matrix_sha256"),
    )
    raw_scope = _mapping(raw_manifest["scope"], "scope")
    _exact(raw_scope, _SCOPE_KEYS, "scope")
    try:
        scope = AuditScopeRef(
            tenant_id=_text(raw_scope["tenant_id"], "scope_tenant_id"),
            owner_id=_text(raw_scope["owner_id"], "scope_owner_id"),
        )
    except ValueError:
        raise SystemAuditArchiveCorruption("archive_scope_invalid") from None

    raw_streams = raw_manifest["streams"]
    if not isinstance(raw_streams, list):
        raise SystemAuditArchiveCorruption("archive_streams_must_be_array")
    streams: list[SystemAuditArchiveStreamAnchor] = []
    for index, raw_stream in enumerate(raw_streams):
        stream = _mapping(raw_stream, f"streams_{index}")
        _exact(stream, _STREAM_KEYS, f"streams_{index}")
        streams.append(
            SystemAuditArchiveStreamAnchor(
                stream_id=_text(stream["stream_id"], f"streams_{index}_stream_id"),
                first_sequence_no=_integer(
                    stream["first_sequence_no"],
                    f"streams_{index}_first_sequence_no",
                ),
                first_predecessor_hash=_nullable_text(
                    stream["first_predecessor_hash"],
                    f"streams_{index}_first_predecessor_hash",
                ),
                last_sequence_no=_integer(
                    stream["last_sequence_no"],
                    f"streams_{index}_last_sequence_no",
                ),
                last_content_hash=_text(
                    stream["last_content_hash"],
                    f"streams_{index}_last_content_hash",
                ),
                member_count=_integer(
                    stream["member_count"],
                    f"streams_{index}_member_count",
                ),
                replay_sha256=_text(
                    stream["replay_sha256"],
                    f"streams_{index}_replay_sha256",
                ),
            )
        )
    manifest = SystemAuditArchiveManifest(
        schema_version=_text(raw_manifest["schema_version"], "manifest_schema_version"),
        candidate=candidate,
        scope=scope,
        window_started_at=_time(
            raw_manifest["window_started_at"],
            "window_started_at",
        ),
        window_ended_at=_time(raw_manifest["window_ended_at"], "window_ended_at"),
        created_at=_time(raw_manifest["created_at"], "created_at"),
        member_count=_integer(raw_manifest["member_count"], "member_count"),
        source_sha256=_text(raw_manifest["source_sha256"], "source_sha256"),
        streams=tuple(streams),
        manifest_sha256=_text(
            raw_manifest["manifest_sha256"],
            "manifest_sha256",
        ),
    )

    raw_events = top["events"]
    if not isinstance(raw_events, list):
        raise SystemAuditArchiveCorruption("archive_events_must_be_array")
    events = []
    for raw_event in raw_events:
        event_payload = _mapping(raw_event, "event")
        try:
            events.append(decode_event(cast(Mapping[str, JSONValue], event_payload)))
        except (TypeError, ValueError):
            raise SystemAuditArchiveCorruption("archive_event_invalid") from None
    bundle = SystemAuditArchiveBundle(manifest=manifest, events=tuple(events))
    if encode_archive(bundle) != payload:
        raise SystemAuditArchiveCorruption("archive_payload_not_canonical")
    return bundle


class CanonicalSystemAuditArchiveCodec:
    """Concrete strict codec for Application archive and restore use cases."""

    def encode(self, bundle: SystemAuditArchiveBundle) -> bytes:
        """Encode one canonical archive bundle."""

        return encode_archive(bundle)

    def decode(self, payload: bytes) -> SystemAuditArchiveBundle:
        """Decode one canonical archive bundle."""

        return decode_archive(payload)


@dataclass(frozen=True, slots=True)
class StoredSystemAuditArchiveArtifact:
    """Content-addressed file and sidecar written by the append-only store."""

    artifact_sha256: str
    path: Path
    sidecar_path: Path
    size_bytes: int


class AppendOnlySystemAuditArchiveStore:
    """Write canonical archive bytes once under a bounded absolute directory."""

    def __init__(
        self,
        *,
        root: Path,
        codec: CanonicalSystemAuditArchiveCodec | None = None,
    ) -> None:
        raw_root = Path(root)
        if not raw_root.is_absolute() or (raw_root.exists() and raw_root.is_symlink()):
            raise ValueError("archive root must be a bounded absolute directory")
        resolved = raw_root.resolve(strict=False)
        if resolved == Path(resolved.anchor):
            raise ValueError("archive root must be a bounded absolute directory")
        if resolved.exists() and (not resolved.is_dir() or resolved.is_symlink()):
            raise ValueError("archive root must be a bounded absolute directory")
        self._root = resolved
        self._codec = codec or CanonicalSystemAuditArchiveCodec()

    def write(self, bundle: SystemAuditArchiveBundle) -> StoredSystemAuditArchiveArtifact:
        """Create or idempotently verify one content-addressed artifact."""

        payload = self._codec.encode(bundle)
        artifact_sha256 = hashlib.sha256(payload).hexdigest()
        path, sidecar_path = self._paths(artifact_sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise SystemAuditArchiveStoreError("archive_bucket_symlink_forbidden")
        self._write_once(path, payload, reason="artifact_hash_mismatch")
        sidecar = f"{artifact_sha256}  {path.name}\n".encode("ascii")
        self._write_once(sidecar_path, sidecar, reason="sidecar_mismatch")
        return StoredSystemAuditArchiveArtifact(
            artifact_sha256=artifact_sha256,
            path=path,
            sidecar_path=sidecar_path,
            size_bytes=len(payload),
        )

    def read(self, artifact_sha256: str) -> SystemAuditArchiveBundle:
        """Read and revalidate an exact artifact and its SHA-256 sidecar."""

        if _DIGEST_RE.fullmatch(artifact_sha256) is None:
            raise SystemAuditArchiveStoreError("artifact_identity_invalid")
        path, sidecar_path = self._paths(artifact_sha256)
        if (
            not path.is_file()
            or path.is_symlink()
            or not sidecar_path.is_file()
            or sidecar_path.is_symlink()
        ):
            raise SystemAuditArchiveStoreError("artifact_or_sidecar_unavailable")
        expected_sidecar = f"{artifact_sha256}  {path.name}\n".encode("ascii")
        if sidecar_path.read_bytes() != expected_sidecar:
            raise SystemAuditArchiveStoreError("sidecar_mismatch")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != artifact_sha256:
            raise SystemAuditArchiveStoreError("artifact_hash_mismatch")
        try:
            return self._codec.decode(payload)
        except SystemAuditArchiveCorruption:
            raise SystemAuditArchiveStoreError("artifact_payload_invalid") from None

    def _paths(self, artifact_sha256: str) -> tuple[Path, Path]:
        bucket = (self._root / artifact_sha256[:2]).resolve(strict=False)
        try:
            bucket.relative_to(self._root)
        except ValueError:
            raise SystemAuditArchiveStoreError("artifact_path_outside_root") from None
        path = bucket / f"{artifact_sha256}.json"
        return path, path.with_suffix(".json.sha256")

    @staticmethod
    def _write_once(path: Path, payload: bytes, *, reason: str) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise SystemAuditArchiveStoreError(reason)
            return
        try:
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise SystemAuditArchiveStoreError(reason) from None


__all__ = [
    "AUDIT_ARCHIVE_MAX_PAYLOAD_BYTES",
    "AppendOnlySystemAuditArchiveStore",
    "CanonicalSystemAuditArchiveCodec",
    "StoredSystemAuditArchiveArtifact",
    "SystemAuditArchiveStoreError",
    "decode_archive",
    "encode_archive",
]
