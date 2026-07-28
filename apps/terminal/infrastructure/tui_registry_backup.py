"""Verified backup and restore primitives for the published TUI registry."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, TypedDict, cast

from apps.terminal.infrastructure.models import TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

BACKUP_FORMAT = "tui-registry-backup.v1"


class RegistryBackupRecord(TypedDict):
    """Recoverable fields for one published registry generation."""

    generation: int
    registry_key: str
    version: str
    schema_version: str
    status: str
    review_status: str
    generation_source: str
    backend_version: str
    payload: dict[str, Any]
    source_hash: str
    source_evidence_hash: str
    changed_fields: list[str]
    review_note: str
    rollback_of_id: int | None
    approved_by_id: int | None
    published_at: str | None
    created_at: str
    updated_at: str


class RuntimeBackupRecord(TypedDict):
    """Runtime identity required to assess restore compatibility."""

    version: str
    build_id: str
    upstream_commit: str


class RegistryBackupIntegrity(TypedDict):
    """Hashes independently recomputed before restore."""

    registry_sha256: str
    payload_sha256: str


class RegistryBackupBundle(TypedDict):
    """Versioned, self-describing TUI registry backup bundle."""

    format: str
    exported_at: str
    registry: RegistryBackupRecord
    runtime: RuntimeBackupRecord
    integrity: RegistryBackupIntegrity


def _canonical_json_bytes(payload: object) -> bytes:
    """Serialize one JSON-compatible value deterministically."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest for bytes."""

    return hashlib.sha256(payload).hexdigest()


def build_registry_backup_bundle(
    *,
    model: TuiMetadataRegistryORM,
    runtime_manifest: dict[str, Any],
    exported_at: str,
) -> RegistryBackupBundle:
    """Build and internally verify one backup bundle from an active model."""

    if model.pk is None:
        raise ValueError("Published registry generation must have a primary key")
    payload = cast(dict[str, Any], dict(model.payload or {}))
    payload_sha256 = PublishedTuiMetadataRepository.payload_hash(payload)
    source_hash = str(model.source_hash or "").strip()
    if not source_hash:
        raise ValueError("Published registry is missing source_hash")
    if source_hash != payload_sha256:
        raise ValueError("Published registry source_hash does not match its stored payload")

    changed_fields = [str(value) for value in list(model.changed_fields or [])]
    record: RegistryBackupRecord = {
        "generation": int(model.pk),
        "registry_key": str(model.registry_key),
        "version": str(model.version),
        "schema_version": str(model.schema_version),
        "status": str(model.status),
        "review_status": str(model.review_status),
        "generation_source": str(model.generation_source),
        "backend_version": str(model.backend_version or ""),
        "payload": payload,
        "source_hash": source_hash,
        "source_evidence_hash": str(model.source_evidence_hash or ""),
        "changed_fields": changed_fields,
        "review_note": str(model.review_note or ""),
        "rollback_of_id": model.rollback_of_id,
        "approved_by_id": model.approved_by_id,
        "published_at": model.published_at.isoformat() if model.published_at else None,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
    }
    runtime: RuntimeBackupRecord = {
        "version": str(runtime_manifest.get("version") or ""),
        "build_id": str(runtime_manifest.get("build_id") or ""),
        "upstream_commit": str(runtime_manifest.get("upstream_commit") or ""),
    }
    if not runtime["build_id"]:
        raise ValueError("Runtime manifest is missing build_id")

    return {
        "format": BACKUP_FORMAT,
        "exported_at": exported_at,
        "registry": record,
        "runtime": runtime,
        "integrity": {
            "registry_sha256": sha256_bytes(_canonical_json_bytes(record)),
            "payload_sha256": payload_sha256,
        },
    }


def write_registry_backup_bundle(
    *,
    output_path: Path,
    bundle: RegistryBackupBundle,
) -> tuple[Path, str]:
    """Atomically write a bundle and its SHA-256 sidecar."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    serialized_bytes = serialized.encode("utf-8")
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    temporary_path.write_bytes(serialized_bytes)
    os.replace(temporary_path, output_path)

    bundle_sha256 = sha256_bytes(serialized_bytes)
    sidecar_path = output_path.with_suffix(f"{output_path.suffix}.sha256")
    temporary_sidecar = sidecar_path.with_name(f".{sidecar_path.name}.tmp")
    temporary_sidecar.write_bytes(f"{bundle_sha256}  {output_path.name}\n".encode("ascii"))
    os.replace(temporary_sidecar, sidecar_path)
    return sidecar_path, bundle_sha256


def load_verified_registry_backup(
    *,
    input_path: Path,
    sidecar_path: Path,
) -> RegistryBackupBundle:
    """Verify the bundle file, sidecar, registry record and payload hashes."""

    serialized = input_path.read_bytes()
    sidecar_parts = sidecar_path.read_text(encoding="ascii").strip().split()
    if len(sidecar_parts) != 2 or sidecar_parts[1] != input_path.name:
        raise ValueError("Invalid registry backup SHA-256 sidecar")
    if sha256_bytes(serialized) != sidecar_parts[0].lower():
        raise ValueError("Registry backup bundle SHA-256 mismatch")

    raw = cast(Any, json.loads(serialized.decode("utf-8")))
    if not isinstance(raw, dict) or raw.get("format") != BACKUP_FORMAT:
        raise ValueError(f"Unsupported registry backup format: {raw!r}")
    bundle = cast(RegistryBackupBundle, raw)
    record = bundle.get("registry")
    runtime = bundle.get("runtime")
    integrity = bundle.get("integrity")
    if (
        not isinstance(record, dict)
        or not isinstance(runtime, dict)
        or not isinstance(integrity, dict)
    ):
        raise ValueError("Registry backup bundle is missing required objects")
    if not str(runtime.get("build_id") or "").strip():
        raise ValueError("Registry backup runtime build_id is missing")

    expected_registry_hash = str(integrity.get("registry_sha256") or "").strip()
    if sha256_bytes(_canonical_json_bytes(record)) != expected_registry_hash:
        raise ValueError("Registry backup record SHA-256 mismatch")
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Registry backup payload must be a JSON object")
    payload_sha256 = PublishedTuiMetadataRepository.payload_hash(payload)
    if payload_sha256 != str(integrity.get("payload_sha256") or "").strip():
        raise ValueError("Registry backup payload SHA-256 mismatch")
    if payload_sha256 != str(record.get("source_hash") or "").strip():
        raise ValueError("Registry backup source_hash does not match its payload")
    return bundle
