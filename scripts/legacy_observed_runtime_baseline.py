"""Validate one narrowly scoped legacy runtime rollback observation.

This is an isolated operations proposal, not a release manifest or a release
qualification. Runtime/Docker observations are supplied by the caller; this
module performs no SSH, Docker, database, HTTP, or deployment operation.

The code digest scope is ``agomtradepro-app-runtime-code.v1``: regular files
under the immutable application root ``/app``; exclude the fixed top-level
``data/``, ``staticfiles/``, ``media/``, ``var/``, ``backups/``, ``reports/``,
``logs/``, and cache paths, plus bytecode, runtime ``.env`` files, and
``.agom-release-manifest.json``. Source roots such as ``apps/``, ``shared/``,
``config/``, and ``static/`` remain included. The observer must apply this same
declared scope to the immutable image and to each live service. The host release
tree is not compared wholesale with the image because it also contains Git
metadata and runtime configuration.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeVar, cast

LEGACY_BASELINE_SCHEMA: Literal["legacy-observed-runtime-baseline.v1"] = (
    "legacy-observed-runtime-baseline.v1"
)
LEGACY_BASELINE_KIND: Literal["observed_runtime_rollback_only"] = "observed_runtime_rollback_only"
LEGACY_CURRENT_PATH = "/opt/agomtradepro/current"
LEGACY_RELEASE_PATH = "/opt/agomtradepro/releases/20261101013730"
LEGACY_MANIFEST_PATH = f"{LEGACY_RELEASE_PATH}/.agom-release-manifest.json"
LEGACY_SOURCE_COMMIT = "4149a9cf4a3738f38d0ca62979fa9bfed56a6a07"
LEGACY_IMAGE_TAG = "agomtradepro-web:20261101013730"
LEGACY_IMAGE_ID = "sha256:8fb8281c9551f28611ee9a0cf6d5503792077eeddff9a917aee1793d8559ea92"
LEGACY_IMAGE_OCI_REVISION = LEGACY_SOURCE_COMMIT
RUNTIME_CODE_SCOPE = "agomtradepro-app-runtime-code.v1"
RUNTIME_CODE_SCOPE_DESCRIPTION = (
    "regular files under /app; fixed top-level exclusions: .git/, data/, staticfiles/, media/, "
    "var/, backups/, reports/, logs/, log/, cache/, .cache/, .pytest_cache/, .mypy_cache/, .ruff_cache/; "
    "also exclude any __pycache__/, *.pyc, *.pyo, runtime .env files, and .agom-release-manifest.json; "
    "apps/, shared/, config/, and static/ remain included"
)
REQUIRED_SERVICE_NAMES = (
    "web",
    "celery_worker",
    "celery_qlib_worker",
    "celery_beat",
    "terminal_agent_worker",
)
COMPATIBILITY_SOURCE_PATHS = (
    "apps/data_center/migrations/0085_published_market_fact_revisions.py",
    "apps/data_center/infrastructure/models.py",
    "apps/data_center/infrastructure/quote_snapshot_models.py",
    "apps/data_center/infrastructure/fact_and_operational_models.py",
    "apps/data_center/infrastructure/published_fact_versions.py",
    "apps/data_center/infrastructure/financial_fact_write_guard.py",
)
REQUIRED_CONFIG_PATHS = (
    f"{LEGACY_RELEASE_PATH}/deploy/.env",
    f"{LEGACY_RELEASE_PATH}/docker/Caddyfile",
    f"{LEGACY_RELEASE_PATH}/docker/docker-compose.vps.yml",
    "/opt/agomtradepro/secrets.env",
)
MANIFEST_CONTAINER_PATH = "/run/agomtradepro/release-manifest.json"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
_ArrayItem = TypeVar("_ArrayItem")

FilesystemKind = Literal["symlink", "directory", "regular_file"]
MountKind = Literal["file", "directory"]
MountType = Literal["bind", "volume"]
VerificationPhase = Literal["pre_cutover", "after_restore"]


@dataclass(frozen=True, slots=True)
class FilesystemIdentity:
    """One lstat/stat observation, including both link and physical target identity."""

    path: str
    realpath: str
    kind: FilesystemKind
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    size_bytes: int
    empty: bool | None
    link_target: str | None


@dataclass(frozen=True, slots=True)
class ConfigurationFileIdentity:
    """Secret-safe configuration identity; only a content digest is retained."""

    path: str
    sha256: str
    mode: int
    uid: int
    gid: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RuntimeMountIdentity:
    """Host and in-container identities for one Docker mount."""

    mount_type: MountType
    host_source_path: str
    host_source_realpath: str
    host_source_kind: MountKind
    host_source_device: int
    host_source_inode: int
    container_target: str
    container_target_kind: MountKind
    container_target_device: int
    container_target_inode: int
    read_only: bool


@dataclass(frozen=True, slots=True)
class RuntimeServiceIdentity:
    """Service identity plus the complete mount list sorted by container target."""

    service_name: str
    container_id: str
    state: str
    configured_image_tag: str
    image_id: str
    image_oci_revision: str
    started_at: datetime
    runtime_code_sha256: str
    environment_sha256: str
    process_configuration_sha256: str
    mounts: tuple[RuntimeMountIdentity, ...]


@dataclass(frozen=True, slots=True)
class LegacyRuntimeSnapshot:
    """Typed inputs from the operator-owned read-only runtime observer."""

    observed_at: datetime
    current_link: FilesystemIdentity
    release_root: FilesystemIdentity
    manifest_path: FilesystemIdentity
    source_commit: str
    image_tag: str
    image_id: str
    image_oci_revision: str
    compatibility_source_paths: tuple[str, ...]
    compatibility_source_sha256: str
    image_compatibility_source_sha256: str
    runtime_code_scope: str
    image_runtime_code_sha256: str
    configuration_files: tuple[ConfigurationFileIdentity, ...]
    runtime_config_sha256: str
    services: tuple[RuntimeServiceIdentity, ...]


@dataclass(frozen=True, slots=True)
class HistoricalBuildMetadata:
    """Unavailable historical build facts; never inferred from runtime clocks."""

    source_mode: None
    build_started_at: None
    build_finished_at: None


@dataclass(frozen=True, slots=True)
class LegacyObservedRuntimeBaselineV1:
    """Observation-only rollback baseline; it grants no release qualification."""

    schema: Literal["legacy-observed-runtime-baseline.v1"]
    kind: Literal["observed_runtime_rollback_only"]
    snapshot: LegacyRuntimeSnapshot
    historical_build: HistoricalBuildMetadata


class LegacyBaselineBlocked(ValueError):
    """Raised when an observed snapshot cannot serve as this exact rollback baseline."""


def _is_aware_utc(value: datetime) -> bool:
    """Return whether a datetime is explicitly aware and has a UTC offset."""

    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _is_sha256(value: str) -> bool:
    """Return whether a string is an exact lowercase SHA-256 digest."""

    return _SHA256_PATTERN.fullmatch(value) is not None


def _is_absolute_normalized_path(value: str) -> bool:
    """Return whether a POSIX path is absolute, normalized, and NUL-free."""

    return value.startswith("/") and posixpath.normpath(value) == value and "\x00" not in value


def hash_runtime_configuration_inventory(
    files: tuple[ConfigurationFileIdentity, ...],
) -> str:
    """Hash an ordered-independent inventory of file paths, metadata, and content hashes."""

    digest = hashlib.sha256(b"agomtradepro-legacy-runtime-config.v1\0")
    for item in sorted(files, key=lambda entry: entry.path):
        for value in (
            item.path,
            item.sha256,
            str(item.mode),
            str(item.uid),
            str(item.gid),
            str(item.size_bytes),
        ):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _filesystem_reasons(
    value: FilesystemIdentity,
    *,
    expected_path: str,
    expected_kind: FilesystemKind,
) -> list[str]:
    """Validate safe path and stat field shapes for one filesystem identity."""

    reasons: list[str] = []
    if value.path != expected_path or not _is_absolute_normalized_path(value.path):
        reasons.append("filesystem_path_mismatch")
    if not _is_absolute_normalized_path(value.realpath):
        reasons.append("filesystem_realpath_invalid")
    if value.kind != expected_kind:
        reasons.append("filesystem_kind_mismatch")
    if any(
        type(item) is not int or item < 0
        for item in (value.device, value.inode, value.uid, value.gid)
    ):
        reasons.append("filesystem_stat_invalid")
    if type(value.mode) is not int or value.mode < 0 or value.mode > 0o7777:
        reasons.append("filesystem_mode_invalid")
    if type(value.size_bytes) is not int or value.size_bytes < 0:
        reasons.append("filesystem_size_invalid")
    if expected_kind == "symlink":
        if (
            not isinstance(value.link_target, str)
            or not value.link_target
            or "\x00" in value.link_target
        ):
            reasons.append("current_symlink_target_missing")
    elif value.link_target is not None:
        reasons.append("unexpected_symlink_target")
    return reasons


def validate_legacy_runtime_snapshot(snapshot: LegacyRuntimeSnapshot) -> tuple[str, ...]:
    """Return stable reasons when a live observation fails this legacy baseline contract."""

    reasons: list[str] = []
    if not _is_aware_utc(snapshot.observed_at):
        reasons.append("observation_clock_invalid")
    reasons.extend(
        _filesystem_reasons(
            snapshot.current_link,
            expected_path=LEGACY_CURRENT_PATH,
            expected_kind="symlink",
        )
    )
    reasons.extend(
        _filesystem_reasons(
            snapshot.release_root,
            expected_path=LEGACY_RELEASE_PATH,
            expected_kind="directory",
        )
    )
    reasons.extend(
        _filesystem_reasons(
            snapshot.manifest_path,
            expected_path=LEGACY_MANIFEST_PATH,
            expected_kind="directory",
        )
    )
    if snapshot.current_link.realpath != LEGACY_RELEASE_PATH:
        reasons.append("current_target_mismatch")
    if isinstance(snapshot.current_link.link_target, str):
        lexical_target = (
            snapshot.current_link.link_target
            if snapshot.current_link.link_target.startswith("/")
            else posixpath.normpath(
                posixpath.join(
                    posixpath.dirname(LEGACY_CURRENT_PATH),
                    snapshot.current_link.link_target,
                )
            )
        )
        if lexical_target != LEGACY_RELEASE_PATH:
            reasons.append("current_symlink_text_target_mismatch")
    if snapshot.release_root.realpath != LEGACY_RELEASE_PATH:
        reasons.append("release_root_target_mismatch")
    if snapshot.manifest_path.realpath != LEGACY_MANIFEST_PATH:
        reasons.append("manifest_target_mismatch")
    if snapshot.release_root.device != snapshot.manifest_path.device:
        reasons.append("manifest_device_mismatch")
    if snapshot.manifest_path.empty is not True:
        reasons.append("legacy_manifest_directory_not_empty")
    if (snapshot.manifest_path.mode, snapshot.manifest_path.uid, snapshot.manifest_path.gid) != (
        0o755,
        0,
        0,
    ):
        reasons.append("legacy_manifest_directory_metadata_mismatch")

    if snapshot.source_commit != LEGACY_SOURCE_COMMIT:
        reasons.append("source_commit_mismatch")
    if snapshot.image_tag != LEGACY_IMAGE_TAG:
        reasons.append("image_tag_mismatch")
    if snapshot.image_id != LEGACY_IMAGE_ID:
        reasons.append("image_id_mismatch")
    if snapshot.image_oci_revision != LEGACY_IMAGE_OCI_REVISION:
        reasons.append("image_revision_mismatch")

    supplied_paths = snapshot.compatibility_source_paths
    if supplied_paths != COMPATIBILITY_SOURCE_PATHS:
        reasons.append("compatibility_source_inventory_invalid")
    if not _is_sha256(snapshot.compatibility_source_sha256) or not _is_sha256(
        snapshot.image_compatibility_source_sha256
    ):
        reasons.append("compatibility_source_digest_invalid")
    elif snapshot.compatibility_source_sha256 != snapshot.image_compatibility_source_sha256:
        reasons.append("compatibility_source_digest_mismatch")

    if snapshot.runtime_code_scope != RUNTIME_CODE_SCOPE:
        reasons.append("runtime_code_scope_mismatch")
    if not _is_sha256(snapshot.image_runtime_code_sha256):
        reasons.append("image_runtime_code_digest_invalid")
    if not _is_sha256(snapshot.runtime_config_sha256):
        reasons.append("runtime_config_digest_invalid")

    config_paths = tuple(item.path for item in snapshot.configuration_files)
    if len(config_paths) != len(set(config_paths)):
        reasons.append("runtime_config_inventory_duplicate")
    if config_paths != tuple(sorted(config_paths)):
        reasons.append("runtime_config_inventory_order_invalid")
    if set(config_paths) != set(REQUIRED_CONFIG_PATHS):
        reasons.append("runtime_config_inventory_incomplete")
    for item in snapshot.configuration_files:
        if not _is_absolute_normalized_path(item.path) or not _is_sha256(item.sha256):
            reasons.append("runtime_config_file_identity_invalid")
        if type(item.mode) is not int or item.mode < 0 or item.mode > 0o7777:
            reasons.append("runtime_config_file_mode_invalid")
        if any(
            type(value) is not int or value < 0 for value in (item.uid, item.gid, item.size_bytes)
        ):
            reasons.append("runtime_config_file_metadata_invalid")
    if snapshot.runtime_config_sha256 != hash_runtime_configuration_inventory(
        snapshot.configuration_files
    ):
        reasons.append("runtime_config_digest_mismatch")

    service_names = tuple(service.service_name for service in snapshot.services)
    if service_names != REQUIRED_SERVICE_NAMES:
        reasons.append("runtime_service_set_mismatch")
    for service in snapshot.services:
        if _CONTAINER_ID_PATTERN.fullmatch(service.container_id) is None:
            reasons.append("runtime_container_id_invalid")
        if service.state != "running":
            reasons.append("runtime_service_not_running")
        if service.configured_image_tag != LEGACY_IMAGE_TAG:
            reasons.append("runtime_service_tag_mismatch")
        if service.image_id != LEGACY_IMAGE_ID:
            reasons.append("runtime_service_image_mismatch")
        if service.image_oci_revision != LEGACY_IMAGE_OCI_REVISION:
            reasons.append("runtime_service_revision_mismatch")
        if not _is_aware_utc(service.started_at):
            reasons.append("runtime_service_clock_invalid")
        if not _is_sha256(service.environment_sha256):
            reasons.append("runtime_service_environment_digest_invalid")
        if not _is_sha256(service.process_configuration_sha256):
            reasons.append("runtime_service_process_digest_invalid")
        if not _is_sha256(service.runtime_code_sha256):
            reasons.append("runtime_service_code_digest_invalid")
        elif service.runtime_code_sha256 != snapshot.image_runtime_code_sha256:
            reasons.append("runtime_service_code_digest_mismatch")
        destinations = tuple(mount.container_target for mount in service.mounts)
        if len(destinations) != len(set(destinations)):
            reasons.append("runtime_mount_destination_duplicate")
        if destinations != tuple(sorted(destinations)):
            reasons.append("runtime_mount_order_invalid")
        manifest_mounts = tuple(
            mount for mount in service.mounts if mount.container_target == MANIFEST_CONTAINER_PATH
        )
        if len(manifest_mounts) != 1:
            reasons.append("runtime_manifest_mount_missing_or_ambiguous")
        for mount in service.mounts:
            reasons.extend(_validate_mount(mount, snapshot.manifest_path))
    return tuple(sorted(set(reasons)))


def _validate_mount(
    mount: RuntimeMountIdentity,
    manifest_path: FilesystemIdentity,
) -> list[str]:
    """Validate one mount and bind the legacy manifest mount to its physical directory."""

    reasons: list[str] = []
    if mount.mount_type not in {"bind", "volume"}:
        reasons.append("runtime_mount_type_invalid")
    if mount.host_source_kind not in {"file", "directory"}:
        reasons.append("runtime_mount_source_kind_invalid")
    if mount.container_target_kind not in {"file", "directory"}:
        reasons.append("runtime_mount_target_kind_invalid")
    if not _is_absolute_normalized_path(mount.host_source_path):
        reasons.append("runtime_mount_source_path_invalid")
    if not _is_absolute_normalized_path(mount.host_source_realpath):
        reasons.append("runtime_mount_source_realpath_invalid")
    if any(
        type(value) is not int or value < 0
        for value in (
            mount.host_source_device,
            mount.host_source_inode,
            mount.container_target_device,
            mount.container_target_inode,
        )
    ):
        reasons.append("runtime_mount_inode_invalid")
    if not _is_absolute_normalized_path(mount.container_target):
        reasons.append("runtime_mount_target_invalid")
    if type(mount.read_only) is not bool:
        reasons.append("runtime_mount_read_only_invalid")
    if mount.container_target == MANIFEST_CONTAINER_PATH:
        if (
            mount.mount_type != "bind"
            or mount.host_source_path
            not in {
                LEGACY_CURRENT_PATH + "/.agom-release-manifest.json",
                LEGACY_MANIFEST_PATH,
            }
            or mount.host_source_realpath != LEGACY_MANIFEST_PATH
            or mount.host_source_kind != "directory"
            or mount.host_source_device != manifest_path.device
            or mount.host_source_inode != manifest_path.inode
            or mount.container_target_kind != "directory"
            or mount.read_only is not True
        ):
            reasons.append("runtime_manifest_mount_identity_mismatch")
    return reasons


def capture_legacy_observed_runtime_baseline(
    snapshot: LegacyRuntimeSnapshot,
    *,
    observed_at: datetime,
) -> LegacyObservedRuntimeBaselineV1:
    """Wrap a validated runtime observation without manufacturing historical build facts."""

    if snapshot.observed_at != observed_at:
        raise LegacyBaselineBlocked("observation_clock_mismatch")
    reasons = validate_legacy_runtime_snapshot(snapshot)
    if reasons:
        raise LegacyBaselineBlocked(",".join(reasons))
    return LegacyObservedRuntimeBaselineV1(
        schema=LEGACY_BASELINE_SCHEMA,
        kind=LEGACY_BASELINE_KIND,
        snapshot=snapshot,
        historical_build=HistoricalBuildMetadata(
            source_mode=None,
            build_started_at=None,
            build_finished_at=None,
        ),
    )


def validate_legacy_observed_runtime_baseline(
    baseline: LegacyObservedRuntimeBaselineV1,
) -> tuple[str, ...]:
    """Validate the schema and no-qualification boundary of one stored baseline."""

    reasons: list[str] = []
    if baseline.schema != LEGACY_BASELINE_SCHEMA:
        reasons.append("baseline_schema_mismatch")
    if baseline.kind != LEGACY_BASELINE_KIND:
        reasons.append("baseline_kind_mismatch")
    if (
        baseline.historical_build.source_mode is not None
        or baseline.historical_build.build_started_at is not None
        or baseline.historical_build.build_finished_at is not None
    ):
        reasons.append("historical_build_facts_must_remain_unknown")
    reasons.extend(validate_legacy_runtime_snapshot(baseline.snapshot))
    return tuple(sorted(set(reasons)))


def compare_legacy_baseline_runtime(
    baseline: LegacyObservedRuntimeBaselineV1,
    live: LegacyRuntimeSnapshot,
    *,
    phase: VerificationPhase,
) -> tuple[str, ...]:
    """Compare a fresh observation against the baseline for one exact deployment phase."""

    reasons = list(validate_legacy_observed_runtime_baseline(baseline))
    reasons.extend(validate_legacy_runtime_snapshot(live))
    if phase not in {"pre_cutover", "after_restore"}:
        reasons.append("verification_phase_invalid")
        return tuple(sorted(set(reasons)))
    original = baseline.snapshot
    reasons.extend(
        _compare_filesystem_identity(original.release_root, live.release_root, "release")
    )
    reasons.extend(
        _compare_filesystem_identity(original.manifest_path, live.manifest_path, "manifest")
    )
    if (
        original.current_link.path != live.current_link.path
        or original.current_link.realpath != live.current_link.realpath
    ):
        reasons.append("current_pointer_target_drift")
    if phase == "pre_cutover" and (
        original.current_link.device != live.current_link.device
        or original.current_link.inode != live.current_link.inode
        or original.current_link.link_target != live.current_link.link_target
    ):
        reasons.append("current_pointer_identity_drift")

    if (
        original.source_commit != live.source_commit
        or original.image_tag != live.image_tag
        or original.image_id != live.image_id
        or original.image_oci_revision != live.image_oci_revision
        or original.compatibility_source_paths != live.compatibility_source_paths
        or original.compatibility_source_sha256 != live.compatibility_source_sha256
        or original.image_compatibility_source_sha256 != live.image_compatibility_source_sha256
        or original.runtime_code_scope != live.runtime_code_scope
        or original.image_runtime_code_sha256 != live.image_runtime_code_sha256
    ):
        reasons.append("runtime_source_or_image_drift")
    if (
        original.configuration_files != live.configuration_files
        or original.runtime_config_sha256 != live.runtime_config_sha256
    ):
        reasons.append("runtime_configuration_drift")

    if len(original.services) != len(live.services):
        reasons.append("runtime_service_set_drift")
    else:
        for previous_service, current_service in zip(original.services, live.services, strict=True):
            if previous_service.service_name != current_service.service_name:
                reasons.append("runtime_service_order_drift")
                continue
            if (
                previous_service.state != current_service.state
                or previous_service.configured_image_tag != current_service.configured_image_tag
                or previous_service.image_id != current_service.image_id
                or previous_service.image_oci_revision != current_service.image_oci_revision
                or previous_service.runtime_code_sha256 != current_service.runtime_code_sha256
                or previous_service.environment_sha256 != current_service.environment_sha256
                or previous_service.process_configuration_sha256
                != current_service.process_configuration_sha256
            ):
                reasons.append("runtime_service_identity_drift")
            if phase == "pre_cutover" and (
                previous_service.container_id != current_service.container_id
                or previous_service.started_at != current_service.started_at
            ):
                reasons.append("runtime_container_changed_before_cutover")
            reasons.extend(_compare_mounts(previous_service, current_service))
    return tuple(sorted(set(reasons)))


def encode_legacy_observed_runtime_baseline(
    baseline: LegacyObservedRuntimeBaselineV1,
) -> bytes:
    """Encode a validated observation as canonical UTF-8 JSON bytes."""

    reasons = validate_legacy_observed_runtime_baseline(baseline)
    if reasons:
        raise LegacyBaselineBlocked(",".join(reasons))
    payload = _baseline_to_json_value(baseline)
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_legacy_observed_runtime_baseline(raw: bytes) -> LegacyObservedRuntimeBaselineV1:
    """Decode strict baseline JSON and reject duplicate, unknown, or malformed fields."""

    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except LegacyBaselineBlocked:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise LegacyBaselineBlocked("baseline_json_invalid") from exc
    payload = _expect_object(
        value,
        {"schema", "kind", "snapshot", "historical_build"},
        "baseline",
    )
    snapshot = _snapshot_from_json_value(payload["snapshot"])
    historical = _expect_object(
        payload["historical_build"],
        {"source_mode", "build_started_at", "build_finished_at"},
        "historical_build",
    )
    for key, item in historical.items():
        _expect_none(item, f"historical_build.{key}")
    baseline = LegacyObservedRuntimeBaselineV1(
        schema=cast(
            Literal["legacy-observed-runtime-baseline.v1"],
            _expect_string(payload["schema"], "schema"),
        ),
        kind=cast(
            Literal["observed_runtime_rollback_only"], _expect_string(payload["kind"], "kind")
        ),
        snapshot=snapshot,
        historical_build=HistoricalBuildMetadata(
            source_mode=None,
            build_started_at=None,
            build_finished_at=None,
        ),
    )
    reasons = validate_legacy_observed_runtime_baseline(baseline)
    if reasons:
        raise LegacyBaselineBlocked(",".join(reasons))
    return baseline


def _compare_filesystem_identity(
    expected: FilesystemIdentity,
    actual: FilesystemIdentity,
    label: str,
) -> list[str]:
    """Require stable release or manifest physical identity across a restore."""

    if expected != actual:
        return [f"{label}_physical_identity_drift"]
    return []


def _compare_mounts(
    expected_service: RuntimeServiceIdentity,
    actual_service: RuntimeServiceIdentity,
) -> list[str]:
    """Compare complete ordered mount observations while allowing a manifest path alias."""

    reasons: list[str] = []
    if len(expected_service.mounts) != len(actual_service.mounts):
        return ["runtime_mount_set_drift"]
    for expected, actual in zip(expected_service.mounts, actual_service.mounts, strict=True):
        manifest_mount = expected.container_target == MANIFEST_CONTAINER_PATH
        if (
            expected.mount_type != actual.mount_type
            or expected.host_source_realpath != actual.host_source_realpath
            or expected.host_source_kind != actual.host_source_kind
            or expected.host_source_device != actual.host_source_device
            or expected.host_source_inode != actual.host_source_inode
            or expected.container_target != actual.container_target
            or expected.container_target_kind != actual.container_target_kind
            or expected.container_target_device != actual.container_target_device
            or expected.container_target_inode != actual.container_target_inode
            or expected.read_only != actual.read_only
            or (not manifest_mount and expected.host_source_path != actual.host_source_path)
        ):
            reasons.append("runtime_mount_identity_drift")
    return reasons


def _baseline_to_json_value(baseline: LegacyObservedRuntimeBaselineV1) -> dict[str, object]:
    """Build the exact JSON object shape for a baseline receipt."""

    return {
        "schema": baseline.schema,
        "kind": baseline.kind,
        "snapshot": _snapshot_to_json_value(baseline.snapshot),
        "historical_build": {
            "source_mode": baseline.historical_build.source_mode,
            "build_started_at": baseline.historical_build.build_started_at,
            "build_finished_at": baseline.historical_build.build_finished_at,
        },
    }


def _snapshot_to_json_value(snapshot: LegacyRuntimeSnapshot) -> dict[str, object]:
    """Build the exact JSON object shape for a runtime snapshot."""

    return {
        "observed_at": _datetime_to_json(snapshot.observed_at),
        "current_link": _filesystem_to_json(snapshot.current_link),
        "release_root": _filesystem_to_json(snapshot.release_root),
        "manifest_path": _filesystem_to_json(snapshot.manifest_path),
        "source_commit": snapshot.source_commit,
        "image_tag": snapshot.image_tag,
        "image_id": snapshot.image_id,
        "image_oci_revision": snapshot.image_oci_revision,
        "compatibility_source_paths": list(snapshot.compatibility_source_paths),
        "compatibility_source_sha256": snapshot.compatibility_source_sha256,
        "image_compatibility_source_sha256": snapshot.image_compatibility_source_sha256,
        "runtime_code_scope": snapshot.runtime_code_scope,
        "image_runtime_code_sha256": snapshot.image_runtime_code_sha256,
        "configuration_files": [
            _configuration_to_json(item) for item in snapshot.configuration_files
        ],
        "runtime_config_sha256": snapshot.runtime_config_sha256,
        "services": [_service_to_json(service) for service in snapshot.services],
    }


def _filesystem_to_json(value: FilesystemIdentity) -> dict[str, object]:
    """Convert one filesystem identity to its exact JSON form."""

    return {
        "path": value.path,
        "realpath": value.realpath,
        "kind": value.kind,
        "device": value.device,
        "inode": value.inode,
        "mode": value.mode,
        "uid": value.uid,
        "gid": value.gid,
        "size_bytes": value.size_bytes,
        "empty": value.empty,
        "link_target": value.link_target,
    }


def _configuration_to_json(value: ConfigurationFileIdentity) -> dict[str, object]:
    """Convert a secret-safe configuration identity to its exact JSON form."""

    return {
        "path": value.path,
        "sha256": value.sha256,
        "mode": value.mode,
        "uid": value.uid,
        "gid": value.gid,
        "size_bytes": value.size_bytes,
    }


def _mount_to_json(value: RuntimeMountIdentity) -> dict[str, object]:
    """Convert one mount identity to its exact JSON form."""

    return {
        "mount_type": value.mount_type,
        "host_source_path": value.host_source_path,
        "host_source_realpath": value.host_source_realpath,
        "host_source_kind": value.host_source_kind,
        "host_source_device": value.host_source_device,
        "host_source_inode": value.host_source_inode,
        "container_target": value.container_target,
        "container_target_kind": value.container_target_kind,
        "container_target_device": value.container_target_device,
        "container_target_inode": value.container_target_inode,
        "read_only": value.read_only,
    }


def _service_to_json(value: RuntimeServiceIdentity) -> dict[str, object]:
    """Convert one running service identity to its exact JSON form."""

    return {
        "service_name": value.service_name,
        "container_id": value.container_id,
        "state": value.state,
        "configured_image_tag": value.configured_image_tag,
        "image_id": value.image_id,
        "image_oci_revision": value.image_oci_revision,
        "started_at": _datetime_to_json(value.started_at),
        "runtime_code_sha256": value.runtime_code_sha256,
        "environment_sha256": value.environment_sha256,
        "process_configuration_sha256": value.process_configuration_sha256,
        "mounts": [_mount_to_json(mount) for mount in value.mounts],
    }


def _snapshot_from_json_value(value: object) -> LegacyRuntimeSnapshot:
    """Decode the exact snapshot schema from a generic JSON value."""

    payload = _expect_object(
        value,
        {
            "observed_at",
            "current_link",
            "release_root",
            "manifest_path",
            "source_commit",
            "image_tag",
            "image_id",
            "image_oci_revision",
            "compatibility_source_paths",
            "compatibility_source_sha256",
            "image_compatibility_source_sha256",
            "runtime_code_scope",
            "image_runtime_code_sha256",
            "configuration_files",
            "runtime_config_sha256",
            "services",
        },
        "snapshot",
    )
    return LegacyRuntimeSnapshot(
        observed_at=_datetime_from_json(payload["observed_at"], "snapshot.observed_at"),
        current_link=_filesystem_from_json(payload["current_link"], "snapshot.current_link"),
        release_root=_filesystem_from_json(payload["release_root"], "snapshot.release_root"),
        manifest_path=_filesystem_from_json(payload["manifest_path"], "snapshot.manifest_path"),
        source_commit=_expect_string(payload["source_commit"], "snapshot.source_commit"),
        image_tag=_expect_string(payload["image_tag"], "snapshot.image_tag"),
        image_id=_expect_string(payload["image_id"], "snapshot.image_id"),
        image_oci_revision=_expect_string(
            payload["image_oci_revision"], "snapshot.image_oci_revision"
        ),
        compatibility_source_paths=_expect_string_array(
            payload["compatibility_source_paths"], "snapshot.compatibility_source_paths"
        ),
        compatibility_source_sha256=_expect_string(
            payload["compatibility_source_sha256"], "snapshot.compatibility_source_sha256"
        ),
        image_compatibility_source_sha256=_expect_string(
            payload["image_compatibility_source_sha256"],
            "snapshot.image_compatibility_source_sha256",
        ),
        runtime_code_scope=_expect_string(
            payload["runtime_code_scope"], "snapshot.runtime_code_scope"
        ),
        image_runtime_code_sha256=_expect_string(
            payload["image_runtime_code_sha256"], "snapshot.image_runtime_code_sha256"
        ),
        configuration_files=_expect_array(
            payload["configuration_files"], "snapshot.configuration_files", _configuration_from_json
        ),
        runtime_config_sha256=_expect_string(
            payload["runtime_config_sha256"], "snapshot.runtime_config_sha256"
        ),
        services=_expect_array(payload["services"], "snapshot.services", _service_from_json),
    )


def _filesystem_from_json(value: object, label: str) -> FilesystemIdentity:
    """Decode one exact filesystem identity object."""

    payload = _expect_object(
        value,
        {
            "path",
            "realpath",
            "kind",
            "device",
            "inode",
            "mode",
            "uid",
            "gid",
            "size_bytes",
            "empty",
            "link_target",
        },
        label,
    )
    kind = _expect_string(payload["kind"], f"{label}.kind")
    if kind not in {"symlink", "directory", "regular_file"}:
        raise LegacyBaselineBlocked(f"{label}.kind_invalid")
    empty = payload["empty"]
    if empty is not None and type(empty) is not bool:
        raise LegacyBaselineBlocked(f"{label}.empty_invalid")
    link_target = payload["link_target"]
    if link_target is not None and not isinstance(link_target, str):
        raise LegacyBaselineBlocked(f"{label}.link_target_invalid")
    return FilesystemIdentity(
        path=_expect_string(payload["path"], f"{label}.path"),
        realpath=_expect_string(payload["realpath"], f"{label}.realpath"),
        kind=cast(FilesystemKind, kind),
        device=_expect_exact_int(payload["device"], f"{label}.device"),
        inode=_expect_exact_int(payload["inode"], f"{label}.inode"),
        mode=_expect_exact_int(payload["mode"], f"{label}.mode"),
        uid=_expect_exact_int(payload["uid"], f"{label}.uid"),
        gid=_expect_exact_int(payload["gid"], f"{label}.gid"),
        size_bytes=_expect_exact_int(payload["size_bytes"], f"{label}.size_bytes"),
        empty=empty,
        link_target=link_target,
    )


def _configuration_from_json(value: object) -> ConfigurationFileIdentity:
    """Decode one exact secret-safe configuration identity."""

    payload = _expect_object(
        value,
        {"path", "sha256", "mode", "uid", "gid", "size_bytes"},
        "configuration_file",
    )
    return ConfigurationFileIdentity(
        path=_expect_string(payload["path"], "configuration_file.path"),
        sha256=_expect_string(payload["sha256"], "configuration_file.sha256"),
        mode=_expect_exact_int(payload["mode"], "configuration_file.mode"),
        uid=_expect_exact_int(payload["uid"], "configuration_file.uid"),
        gid=_expect_exact_int(payload["gid"], "configuration_file.gid"),
        size_bytes=_expect_exact_int(payload["size_bytes"], "configuration_file.size_bytes"),
    )


def _mount_from_json(value: object) -> RuntimeMountIdentity:
    """Decode one exact Docker mount identity."""

    payload = _expect_object(
        value,
        {
            "mount_type",
            "host_source_path",
            "host_source_realpath",
            "host_source_kind",
            "host_source_device",
            "host_source_inode",
            "container_target",
            "container_target_kind",
            "container_target_device",
            "container_target_inode",
            "read_only",
        },
        "runtime_mount",
    )
    mount_type = _expect_string(payload["mount_type"], "runtime_mount.mount_type")
    if mount_type not in {"bind", "volume"}:
        raise LegacyBaselineBlocked("runtime_mount.mount_type_invalid")
    host_kind = _expect_string(payload["host_source_kind"], "runtime_mount.host_source_kind")
    target_kind = _expect_string(
        payload["container_target_kind"], "runtime_mount.container_target_kind"
    )
    if host_kind not in {"file", "directory"} or target_kind not in {"file", "directory"}:
        raise LegacyBaselineBlocked("runtime_mount.kind_invalid")
    read_only = payload["read_only"]
    if type(read_only) is not bool:
        raise LegacyBaselineBlocked("runtime_mount.read_only_invalid")
    return RuntimeMountIdentity(
        mount_type=cast(MountType, mount_type),
        host_source_path=_expect_string(
            payload["host_source_path"], "runtime_mount.host_source_path"
        ),
        host_source_realpath=_expect_string(
            payload["host_source_realpath"], "runtime_mount.host_source_realpath"
        ),
        host_source_kind=cast(MountKind, host_kind),
        host_source_device=_expect_exact_int(
            payload["host_source_device"], "runtime_mount.host_source_device"
        ),
        host_source_inode=_expect_exact_int(
            payload["host_source_inode"], "runtime_mount.host_source_inode"
        ),
        container_target=_expect_string(
            payload["container_target"], "runtime_mount.container_target"
        ),
        container_target_kind=cast(MountKind, target_kind),
        container_target_device=_expect_exact_int(
            payload["container_target_device"], "runtime_mount.container_target_device"
        ),
        container_target_inode=_expect_exact_int(
            payload["container_target_inode"], "runtime_mount.container_target_inode"
        ),
        read_only=read_only,
    )


def _service_from_json(value: object) -> RuntimeServiceIdentity:
    """Decode one exact service identity and its full mount tuple."""

    payload = _expect_object(
        value,
        {
            "service_name",
            "container_id",
            "state",
            "configured_image_tag",
            "image_id",
            "image_oci_revision",
            "started_at",
            "runtime_code_sha256",
            "environment_sha256",
            "process_configuration_sha256",
            "mounts",
        },
        "runtime_service",
    )
    return RuntimeServiceIdentity(
        service_name=_expect_string(payload["service_name"], "runtime_service.service_name"),
        container_id=_expect_string(payload["container_id"], "runtime_service.container_id"),
        state=_expect_string(payload["state"], "runtime_service.state"),
        configured_image_tag=_expect_string(
            payload["configured_image_tag"], "runtime_service.configured_image_tag"
        ),
        image_id=_expect_string(payload["image_id"], "runtime_service.image_id"),
        image_oci_revision=_expect_string(
            payload["image_oci_revision"], "runtime_service.image_oci_revision"
        ),
        started_at=_datetime_from_json(payload["started_at"], "runtime_service.started_at"),
        runtime_code_sha256=_expect_string(
            payload["runtime_code_sha256"], "runtime_service.runtime_code_sha256"
        ),
        environment_sha256=_expect_string(
            payload["environment_sha256"], "runtime_service.environment_sha256"
        ),
        process_configuration_sha256=_expect_string(
            payload["process_configuration_sha256"], "runtime_service.process_configuration_sha256"
        ),
        mounts=_expect_array(payload["mounts"], "runtime_service.mounts", _mount_from_json),
    )


def _datetime_to_json(value: datetime) -> str:
    """Format an aware UTC datetime with an explicit Z suffix."""

    if not _is_aware_utc(value):
        raise LegacyBaselineBlocked("datetime_must_be_aware_utc")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_json(value: object, label: str) -> datetime:
    """Parse one canonical aware UTC timestamp."""

    text = _expect_string(value, label)
    if not text.endswith("Z"):
        raise LegacyBaselineBlocked(f"{label}_must_use_utc_z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise LegacyBaselineBlocked(f"{label}_invalid") from exc
    if not _is_aware_utc(parsed):
        raise LegacyBaselineBlocked(f"{label}_must_be_aware_utc")
    return parsed


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys at every nesting level."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LegacyBaselineBlocked("baseline_json_duplicate_key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    """Reject JSON NaN and Infinity tokens."""

    raise LegacyBaselineBlocked(f"baseline_json_constant_{value.lower()}_forbidden")


def _expect_object(value: object, expected_keys: set[str], label: str) -> dict[str, object]:
    """Require an object with an exact key set and string keys."""

    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise LegacyBaselineBlocked(f"{label}_object_invalid")
    if set(value) != expected_keys:
        raise LegacyBaselineBlocked(f"{label}_keys_invalid")
    return cast(dict[str, object], value)


def _expect_string(value: object, label: str) -> str:
    """Require one nonempty string value."""

    if not isinstance(value, str) or not value:
        raise LegacyBaselineBlocked(f"{label}_string_invalid")
    return value


def _expect_exact_int(value: object, label: str) -> int:
    """Require an integer and reject booleans."""

    if type(value) is not int:
        raise LegacyBaselineBlocked(f"{label}_integer_invalid")
    return value


def _expect_none(value: object, label: str) -> None:
    """Require an explicit JSON null for unavailable historical facts."""

    if value is not None:
        raise LegacyBaselineBlocked(f"{label}_must_remain_unknown")
    return None


def _expect_string_array(value: object, label: str) -> tuple[str, ...]:
    """Decode an array of nonempty strings."""

    if not isinstance(value, list):
        raise LegacyBaselineBlocked(f"{label}_array_invalid")
    return tuple(_expect_string(item, label) for item in value)


def _expect_array(
    value: object,
    label: str,
    parser: Callable[[object], _ArrayItem],
) -> tuple[_ArrayItem, ...]:
    """Decode an array through a typed item parser."""

    if not isinstance(value, list):
        raise LegacyBaselineBlocked(f"{label}_array_invalid")
    return tuple(parser(item) for item in value)
