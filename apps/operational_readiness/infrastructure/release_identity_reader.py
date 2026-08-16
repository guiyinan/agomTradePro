"""Filesystem adapter for immutable deployment identity artifacts."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from apps.operational_readiness.domain.release_identity import (
    BuildIdentity,
    BuildIdentityEvidence,
    ReleaseIdentityEvidence,
    ReleaseManifest,
    ReleaseManifestEvidence,
)

_MAX_ARTIFACT_BYTES = 16 * 1024
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_RELEASE_TAG_PATTERN = re.compile(r"[0-9]{14}")
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_TIMESTAMP_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_APP_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")


class ReleaseArtifactError(ValueError):
    """Raised internally when an identity artifact is malformed."""


class FileReleaseIdentityEvidenceReader:
    """Read and validate the image identity and mounted release manifest."""

    def __init__(self, *, build_identity_path: Path, release_manifest_path: Path) -> None:
        self._build_identity_path = build_identity_path
        self._release_manifest_path = release_manifest_path

    def read(self) -> ReleaseIdentityEvidence:
        """Return normalized evidence and keep malformed artifacts fail-closed."""

        return ReleaseIdentityEvidence(
            build=self._read_build_identity(),
            release=self._read_release_manifest(),
        )

    def _read_build_identity(self) -> BuildIdentityEvidence:
        if not self._build_identity_path.exists():
            return BuildIdentityEvidence(status="missing")
        try:
            payload = _read_json_object(self._build_identity_path)
            expected_keys = {"schema_version", "app_version", "source_commit"}
            _require_exact_keys(payload, expected_keys)
            schema_version = _require_integer(payload, "schema_version")
            app_version = _require_string(payload, "app_version")
            source_commit = _require_string(payload, "source_commit")
            if schema_version != 1:
                raise ReleaseArtifactError("unsupported build identity schema")
            if _APP_VERSION_PATTERN.fullmatch(app_version) is None:
                raise ReleaseArtifactError("invalid application version")
            if _COMMIT_PATTERN.fullmatch(source_commit) is None:
                raise ReleaseArtifactError("invalid build source commit")
            return BuildIdentityEvidence(
                status="valid",
                value=BuildIdentity(
                    schema_version=schema_version,
                    app_version=app_version,
                    source_commit=source_commit,
                ),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ReleaseArtifactError):
            return BuildIdentityEvidence(status="invalid")

    def _read_release_manifest(self) -> ReleaseManifestEvidence:
        if not self._release_manifest_path.exists():
            return ReleaseManifestEvidence(status="missing")
        try:
            payload = _read_json_object(self._release_manifest_path)
            expected_keys = {
                "version",
                "release_tag",
                "source_commit",
                "image_tag",
                "image_id",
                "build_started_at",
                "build_finished_at",
                "source_mode",
            }
            _require_exact_keys(payload, expected_keys)
            schema_version = _require_integer(payload, "version")
            release_tag = _require_string(payload, "release_tag")
            source_commit = _require_string(payload, "source_commit")
            image_tag = _require_string(payload, "image_tag")
            image_id = _require_string(payload, "image_id")
            build_started_at = _require_string(payload, "build_started_at")
            build_finished_at = _require_string(payload, "build_finished_at")
            source_mode = _require_string(payload, "source_mode")
            _validate_release_manifest(
                schema_version=schema_version,
                release_tag=release_tag,
                source_commit=source_commit,
                image_tag=image_tag,
                image_id=image_id,
                build_started_at=build_started_at,
                build_finished_at=build_finished_at,
                source_mode=source_mode,
            )
            return ReleaseManifestEvidence(
                status="valid",
                value=ReleaseManifest(
                    schema_version=schema_version,
                    release_tag=release_tag,
                    source_commit=source_commit,
                    image_tag=image_tag,
                    image_id=image_id,
                    build_started_at=build_started_at,
                    build_finished_at=build_finished_at,
                    source_mode=source_mode,
                ),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ReleaseArtifactError):
            return ReleaseManifestEvidence(status="invalid")


def _read_json_object(path: Path) -> dict[str, object]:
    """Read one bounded regular JSON file with string keys."""

    if path.is_symlink() or not path.is_file():
        raise ReleaseArtifactError("identity artifact must be a regular file")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_ARTIFACT_BYTES:
        raise ReleaseArtifactError("identity artifact size is invalid")
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise ReleaseArtifactError("identity artifact must be a JSON object")
    return cast(dict[str, object], decoded)


def _require_exact_keys(payload: dict[str, object], expected_keys: set[str]) -> None:
    """Reject missing and unexpected provenance fields."""

    if set(payload) != expected_keys:
        raise ReleaseArtifactError("identity artifact keys are invalid")


def _require_integer(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise ReleaseArtifactError(f"{key} must be an integer")
    return value


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if type(value) is not str or not value:
        raise ReleaseArtifactError(f"{key} must be a non-empty string")
    return value


def _validate_release_manifest(
    *,
    schema_version: int,
    release_tag: str,
    source_commit: str,
    image_tag: str,
    image_id: str,
    build_started_at: str,
    build_finished_at: str,
    source_mode: str,
) -> None:
    """Apply the same immutable provenance contract as the VPS deploy script."""

    if schema_version != 1:
        raise ReleaseArtifactError("unsupported release manifest schema")
    if _RELEASE_TAG_PATTERN.fullmatch(release_tag) is None:
        raise ReleaseArtifactError("invalid release tag")
    if _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ReleaseArtifactError("invalid release source commit")
    if image_tag != f"agomtradepro-web:{release_tag}":
        raise ReleaseArtifactError("release image tag does not match release tag")
    if _IMAGE_ID_PATTERN.fullmatch(image_id) is None:
        raise ReleaseArtifactError("invalid release image identity")
    if source_mode not in {"source-upload", "git-clone"}:
        raise ReleaseArtifactError("unsupported release source mode")
    if _TIMESTAMP_PATTERN.fullmatch(build_started_at) is None:
        raise ReleaseArtifactError("invalid build start timestamp")
    if _TIMESTAMP_PATTERN.fullmatch(build_finished_at) is None:
        raise ReleaseArtifactError("invalid build finish timestamp")
    started = datetime.strptime(build_started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    finished = datetime.strptime(build_finished_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    if finished < started:
        raise ReleaseArtifactError("build timestamps are not monotonic")


__all__ = ["FileReleaseIdentityEvidenceReader"]
