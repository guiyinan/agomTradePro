"""Synthetic mechanics checks; these fixtures are not observed deployment evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from scripts import legacy_observed_runtime_baseline as baseline


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(
    path: str,
    realpath: str,
    kind: baseline.FilesystemKind,
    *,
    device: int,
    inode: int,
    mode: int,
    empty: bool | None = None,
    link_target: str | None = None,
) -> baseline.FilesystemIdentity:
    return baseline.FilesystemIdentity(
        path=path,
        realpath=realpath,
        kind=kind,
        device=device,
        inode=inode,
        mode=mode,
        uid=0,
        gid=0,
        size_bytes=4096,
        empty=empty,
        link_target=link_target,
    )


def _manifest_mount_index(service: baseline.RuntimeServiceIdentity) -> int:
    return next(
        index
        for index, mount in enumerate(service.mounts)
        if mount.container_target == baseline.MANIFEST_CONTAINER_PATH
    )


def _valid_snapshot() -> baseline.LegacyRuntimeSnapshot:
    observed_at = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)
    current = _identity(
        baseline.LEGACY_CURRENT_PATH,
        baseline.LEGACY_RELEASE_PATH,
        "symlink",
        device=1,
        inode=100,
        mode=0o777,
        link_target="releases/20261101013730",
    )
    release = _identity(
        baseline.LEGACY_RELEASE_PATH,
        baseline.LEGACY_RELEASE_PATH,
        "directory",
        device=1,
        inode=200,
        mode=0o755,
    )
    manifest = _identity(
        baseline.LEGACY_MANIFEST_PATH,
        baseline.LEGACY_MANIFEST_PATH,
        "directory",
        device=1,
        inode=201,
        mode=0o755,
        empty=True,
    )
    config_files = tuple(
        baseline.ConfigurationFileIdentity(
            path=path,
            sha256=_digest(path),
            mode=0o600 if path.endswith((".env", "secrets.env")) else 0o644,
            uid=0,
            gid=0,
            size_bytes=100,
        )
        for path in baseline.REQUIRED_CONFIG_PATHS
    )
    runtime_code_sha256 = _digest("runtime-code")
    compatibility_sha256 = _digest("compatibility-source")
    services = tuple(
        baseline.RuntimeServiceIdentity(
            service_name=name,
            container_id=f"{index:064x}",
            state="running",
            configured_image_tag=baseline.LEGACY_IMAGE_TAG,
            image_id=baseline.LEGACY_IMAGE_ID,
            image_oci_revision=baseline.LEGACY_IMAGE_OCI_REVISION,
            started_at=observed_at - timedelta(hours=1),
            runtime_code_sha256=runtime_code_sha256,
            environment_sha256=_digest(f"env-{name}"),
            process_configuration_sha256=_digest(f"process-{name}"),
            mounts=(
                baseline.RuntimeMountIdentity(
                    mount_type="volume",
                    host_source_path="/var/lib/docker/volumes/agomtradepro-runtime-data/_data",
                    host_source_realpath="/var/lib/docker/volumes/agomtradepro-runtime-data/_data",
                    host_source_kind="directory",
                    host_source_device=1,
                    host_source_inode=401,
                    container_target="/app/runtime-data",
                    container_target_kind="directory",
                    container_target_device=2,
                    container_target_inode=402,
                    read_only=False,
                ),
                baseline.RuntimeMountIdentity(
                    mount_type="bind",
                    host_source_path=(
                        baseline.LEGACY_CURRENT_PATH + "/.agom-release-manifest.json"
                    ),
                    host_source_realpath=baseline.LEGACY_MANIFEST_PATH,
                    host_source_kind="directory",
                    host_source_device=manifest.device,
                    host_source_inode=manifest.inode,
                    container_target=baseline.MANIFEST_CONTAINER_PATH,
                    container_target_kind="directory",
                    container_target_device=2,
                    container_target_inode=301,
                    read_only=True,
                ),
                baseline.RuntimeMountIdentity(
                    mount_type="bind",
                    host_source_path=baseline.LEGACY_RELEASE_PATH + "/deploy/.env",
                    host_source_realpath=baseline.LEGACY_RELEASE_PATH + "/deploy/.env",
                    host_source_kind="file",
                    host_source_device=1,
                    host_source_inode=403,
                    container_target="/run/config/deploy.env",
                    container_target_kind="file",
                    container_target_device=2,
                    container_target_inode=404,
                    read_only=True,
                ),
            ),
        )
        for index, name in enumerate(baseline.REQUIRED_SERVICE_NAMES, start=1)
    )
    return baseline.LegacyRuntimeSnapshot(
        observed_at=observed_at,
        current_link=current,
        release_root=release,
        manifest_path=manifest,
        source_commit=baseline.LEGACY_SOURCE_COMMIT,
        image_tag=baseline.LEGACY_IMAGE_TAG,
        image_id=baseline.LEGACY_IMAGE_ID,
        image_oci_revision=baseline.LEGACY_IMAGE_OCI_REVISION,
        compatibility_source_paths=baseline.COMPATIBILITY_SOURCE_PATHS,
        compatibility_source_sha256=compatibility_sha256,
        image_compatibility_source_sha256=compatibility_sha256,
        runtime_code_scope=baseline.RUNTIME_CODE_SCOPE,
        image_runtime_code_sha256=runtime_code_sha256,
        configuration_files=config_files,
        runtime_config_sha256=baseline.hash_runtime_configuration_inventory(config_files),
        services=services,
    )


def test_capture_marks_history_unknown_and_encodes_observation_only_schema() -> None:
    snapshot = _valid_snapshot()

    receipt = baseline.capture_legacy_observed_runtime_baseline(
        snapshot,
        observed_at=snapshot.observed_at,
    )
    encoded = baseline.encode_legacy_observed_runtime_baseline(receipt)
    decoded = baseline.decode_legacy_observed_runtime_baseline(encoded)

    assert decoded == receipt
    assert decoded.schema == "legacy-observed-runtime-baseline.v1"
    assert decoded.kind == "observed_runtime_rollback_only"
    assert decoded.historical_build.source_mode is None
    assert decoded.historical_build.build_started_at is None
    assert decoded.historical_build.build_finished_at is None


def test_runtime_code_scope_excludes_persistent_data_but_keeps_source_roots() -> None:
    description = baseline.RUNTIME_CODE_SCOPE_DESCRIPTION

    assert "data/" in description
    assert "apps/, shared/, config/, and static/ remain included" in description


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("current", "current_target_mismatch"),
        ("release_kind", "filesystem_kind_mismatch"),
        ("manifest_empty", "legacy_manifest_directory_not_empty"),
        ("source_hash", "compatibility_source_digest_mismatch"),
        ("code_hash", "runtime_service_code_digest_mismatch"),
        ("manifest_mount", "runtime_manifest_mount_identity_mismatch"),
        ("services", "runtime_service_set_mismatch"),
    ),
)
def test_capture_blocks_ambiguous_or_drifted_observations(
    field: str,
    reason: str,
) -> None:
    snapshot = _valid_snapshot()
    if field == "current":
        snapshot = replace(
            snapshot,
            current_link=replace(
                snapshot.current_link, realpath="/opt/agomtradepro/releases/other"
            ),
        )
    elif field == "release_kind":
        snapshot = replace(snapshot, release_root=replace(snapshot.release_root, kind="symlink"))
    elif field == "manifest_empty":
        snapshot = replace(snapshot, manifest_path=replace(snapshot.manifest_path, empty=False))
    elif field == "source_hash":
        snapshot = replace(snapshot, image_compatibility_source_sha256=_digest("other-source"))
    elif field == "code_hash":
        first = replace(snapshot.services[0], runtime_code_sha256=_digest("other-code"))
        snapshot = replace(snapshot, services=(first, *snapshot.services[1:]))
    elif field == "manifest_mount":
        first = snapshot.services[0]
        mount_index = _manifest_mount_index(first)
        mounts = list(first.mounts)
        mounts[mount_index] = replace(mounts[mount_index], host_source_inode=999)
        snapshot = replace(
            snapshot,
            services=(replace(first, mounts=tuple(mounts)), *snapshot.services[1:]),
        )
    else:
        snapshot = replace(snapshot, services=snapshot.services[:-1])

    assert reason in baseline.validate_legacy_runtime_snapshot(snapshot)
    with pytest.raises(baseline.LegacyBaselineBlocked):
        baseline.capture_legacy_observed_runtime_baseline(
            snapshot, observed_at=snapshot.observed_at
        )


def test_restore_allows_new_containers_and_current_link_inode_but_keeps_physical_mount() -> None:
    snapshot = _valid_snapshot()
    receipt = baseline.capture_legacy_observed_runtime_baseline(
        snapshot, observed_at=snapshot.observed_at
    )
    restored_services = tuple(
        replace(
            service,
            container_id=f"{100 + index:064x}",
            started_at=service.started_at + timedelta(minutes=20),
            mounts=tuple(
                (
                    replace(mount, host_source_path=baseline.LEGACY_MANIFEST_PATH)
                    if mount.container_target == baseline.MANIFEST_CONTAINER_PATH
                    else mount
                )
                for mount in service.mounts
            ),
        )
        for index, service in enumerate(snapshot.services, start=1)
    )
    restored = replace(
        snapshot,
        observed_at=snapshot.observed_at + timedelta(minutes=30),
        current_link=replace(
            snapshot.current_link,
            inode=snapshot.current_link.inode + 1,
            link_target=baseline.LEGACY_RELEASE_PATH,
        ),
        services=restored_services,
    )

    assert baseline.compare_legacy_baseline_runtime(receipt, restored, phase="after_restore") == ()
    assert "current_pointer_identity_drift" in baseline.compare_legacy_baseline_runtime(
        receipt,
        restored,
        phase="pre_cutover",
    )


def test_restore_rejects_changed_manifest_inode_or_mount_inode() -> None:
    snapshot = _valid_snapshot()
    receipt = baseline.capture_legacy_observed_runtime_baseline(
        snapshot, observed_at=snapshot.observed_at
    )
    changed_manifest = replace(snapshot.manifest_path, inode=snapshot.manifest_path.inode + 1)
    first_service = snapshot.services[0]
    first_mounts = list(first_service.mounts)
    manifest_mount_index = _manifest_mount_index(first_service)
    first_mounts[manifest_mount_index] = replace(
        first_mounts[manifest_mount_index], host_source_inode=changed_manifest.inode
    )
    changed_service = replace(
        first_service,
        container_id=f"{99:064x}",
        started_at=first_service.started_at + timedelta(minutes=1),
        mounts=tuple(first_mounts),
    )
    restored = replace(
        snapshot,
        observed_at=snapshot.observed_at + timedelta(minutes=2),
        current_link=replace(snapshot.current_link, inode=snapshot.current_link.inode + 1),
        manifest_path=changed_manifest,
        services=(changed_service, *snapshot.services[1:]),
    )

    reasons = baseline.compare_legacy_baseline_runtime(receipt, restored, phase="after_restore")
    assert "manifest_physical_identity_drift" in reasons
    assert "runtime_mount_identity_drift" in reasons


def test_json_decoder_rejects_unknown_duplicate_and_non_null_build_metadata() -> None:
    snapshot = _valid_snapshot()
    receipt = baseline.capture_legacy_observed_runtime_baseline(
        snapshot, observed_at=snapshot.observed_at
    )
    encoded = baseline.encode_legacy_observed_runtime_baseline(receipt)
    payload = json.loads(encoded)

    payload["unexpected"] = True
    with pytest.raises(baseline.LegacyBaselineBlocked, match="baseline_keys_invalid"):
        baseline.decode_legacy_observed_runtime_baseline(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )

    duplicate = encoded.replace(
        b'"kind":"observed_runtime_rollback_only"',
        b'"kind":"observed_runtime_rollback_only","kind":"observed_runtime_rollback_only"',
        1,
    )
    with pytest.raises(baseline.LegacyBaselineBlocked, match="duplicate_key"):
        baseline.decode_legacy_observed_runtime_baseline(duplicate)

    payload = json.loads(encoded)
    payload["historical_build"]["source_mode"] = "git-clone"
    with pytest.raises(baseline.LegacyBaselineBlocked, match="must_remain_unknown"):
        baseline.decode_legacy_observed_runtime_baseline(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )


def test_capture_rejects_naive_observation_clock() -> None:
    snapshot = _valid_snapshot()
    naive = replace(snapshot, observed_at=datetime(2026, 11, 17, 1, 0))

    assert "observation_clock_invalid" in baseline.validate_legacy_runtime_snapshot(naive)


def test_capture_requires_the_complete_compatibility_source_inventory() -> None:
    snapshot = _valid_snapshot()
    incomplete = replace(
        snapshot,
        compatibility_source_paths=snapshot.compatibility_source_paths[:-1],
    )

    assert "compatibility_source_inventory_invalid" in baseline.validate_legacy_runtime_snapshot(
        incomplete
    )


def test_capture_rejects_unsupported_mount_type() -> None:
    snapshot = _valid_snapshot()
    first_service = snapshot.services[0]
    volume_index = next(
        index for index, mount in enumerate(first_service.mounts) if mount.mount_type == "volume"
    )
    mounts = list(first_service.mounts)
    mounts[volume_index] = replace(mounts[volume_index], mount_type="tmpfs")
    snapshot = replace(
        snapshot,
        services=(
            replace(first_service, mounts=tuple(mounts)),
            *snapshot.services[1:],
        ),
    )

    assert "runtime_mount_type_invalid" in baseline.validate_legacy_runtime_snapshot(snapshot)


def test_restore_rejects_process_configuration_drift() -> None:
    snapshot = _valid_snapshot()
    receipt = baseline.capture_legacy_observed_runtime_baseline(
        snapshot, observed_at=snapshot.observed_at
    )
    changed_service = replace(
        snapshot.services[0], process_configuration_sha256=_digest("changed command")
    )
    changed = replace(snapshot, services=(changed_service, *snapshot.services[1:]))
    assert "runtime_service_identity_drift" in baseline.compare_legacy_baseline_runtime(
        receipt, changed, phase="after_restore"
    )
