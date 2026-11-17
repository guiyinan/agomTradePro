#!/usr/bin/env python3
"""Observe the exact legacy Docker runtime without inventing release provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.legacy_observed_runtime_baseline import (  # noqa: E402
    COMPATIBILITY_SOURCE_PATHS,
    LEGACY_CURRENT_PATH,
    LEGACY_IMAGE_ID,
    LEGACY_IMAGE_TAG,
    LEGACY_RELEASE_PATH,
    REQUIRED_CONFIG_PATHS,
    REQUIRED_SERVICE_NAMES,
    RUNTIME_CODE_SCOPE,
    ConfigurationFileIdentity,
    FilesystemIdentity,
    FilesystemKind,
    LegacyBaselineBlocked,
    LegacyRuntimeSnapshot,
    MountKind,
    RuntimeMountIdentity,
    RuntimeServiceIdentity,
    capture_legacy_observed_runtime_baseline,
    compare_legacy_baseline_runtime,
    decode_legacy_observed_runtime_baseline,
    encode_legacy_observed_runtime_baseline,
    hash_runtime_configuration_inventory,
)

# The same program runs in the immutable image and every live app container.
# It imports only stdlib and neither imports Django nor contacts any service.
_CONTAINER_OBSERVATION_PROGRAM = r"""
import hashlib, json, os, stat, sys
from pathlib import Path
root = Path('/app')
root_excluded = {'.git', 'logs', 'log', 'cache', '.cache', '.pytest_cache',
                 '.mypy_cache', '.ruff_cache', 'staticfiles', 'data', 'media',
                 'var', 'backups', 'reports'}
def walk_error(error):
    raise SystemExit('LEGACY_RUNTIME_CODE_READ_FAILED')
digest = hashlib.sha256(b'agomtradepro-app-runtime-code.v1\0')
count = 0
for base, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
    directories[:] = sorted(name for name in directories
                            if name != '__pycache__'
                            and (Path(base) != root or name not in root_excluded))
    if any((Path(base) / name).is_symlink() for name in directories):
        raise SystemExit('LEGACY_RUNTIME_CODE_NONREGULAR')
    for name in sorted(files):
        path = Path(base) / name
        if (name.endswith(('.pyc', '.pyo')) or name == '.env' or name.startswith('.env.')
            or name == '.agom-release-manifest.json'):
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise SystemExit('LEGACY_RUNTIME_CODE_NONREGULAR')
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode()); digest.update(b'\0')
        digest.update(path.read_bytes()); digest.update(b'\0'); count += 1
compat = hashlib.sha256()
for name in json.loads(sys.argv[1]):
    data = (root / name).read_bytes()
    compat.update(name.encode()); compat.update(b'\0'); compat.update(data); compat.update(b'\0')
mounts = {}
for name in json.loads(sys.argv[2]):
    info = Path(name).stat()
    kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else None
    if kind is None: raise SystemExit('LEGACY_RUNTIME_MOUNT_KIND_INVALID')
    mounts[name] = {'kind': kind, 'device': info.st_dev, 'inode': info.st_ino}
print(json.dumps({'runtime_code_sha256': digest.hexdigest(), 'code_file_count': count,
                  'compatibility_source_sha256': compat.hexdigest(), 'mounts': mounts}, sort_keys=True))
"""


class ObservationCommand(Protocol):
    """Run only the observer's explicit read-only command arguments."""

    def __call__(self, arguments: tuple[str, ...]) -> str:
        """Return stdout without retaining command output on failure."""
        ...


def _command(arguments: tuple[str, ...]) -> str:
    """Run a bounded identity command, never printing raw Docker output."""
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_COMMAND_FAILED") from exc
    if result.returncode != 0:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_COMMAND_FAILED")
    return result.stdout.strip()


def _object(value: object) -> dict[str, object]:
    """Narrow one Docker JSON object before consuming identity fields."""
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_JSON_INVALID")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    """Require one nonempty Docker string field."""
    if type(value) is not str or not value:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_STRING_INVALID")
    return value


def _integer(value: object) -> int:
    """Require an exact nonnegative integer, excluding JSON booleans."""
    if type(value) is not int or value < 0:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_INTEGER_INVALID")
    return value


def _array(value: object) -> list[object]:
    """Require an array at the Docker JSON boundary."""
    if not isinstance(value, list):
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_ARRAY_INVALID")
    return cast(list[object], value)


def _inspect(arguments: tuple[str, ...], command: ObservationCommand) -> dict[str, object]:
    """Require exactly one Docker identity, rejecting empty or ambiguous results."""
    values = _array(json.loads(command(arguments)))
    if len(values) != 1:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_OBSERVATION_IDENTITY_AMBIGUOUS")
    return _object(values[0])


def _filesystem(path: Path) -> FilesystemIdentity:
    """Record both a host path and its physical identity without following lstat."""
    info = path.lstat()
    kind: FilesystemKind
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "regular_file"
    else:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_FILESYSTEM_KIND_INVALID")
    return FilesystemIdentity(
        path=path.as_posix(),
        realpath=path.resolve(strict=True).as_posix(),
        kind=kind,
        device=info.st_dev,
        inode=info.st_ino,
        mode=stat.S_IMODE(info.st_mode),
        uid=info.st_uid,
        gid=info.st_gid,
        size_bytes=info.st_size,
        empty=not any(path.iterdir()) if kind == "directory" else None,
        link_target=os.readlink(path) if kind == "symlink" else None,
    )


def _configuration(path: Path) -> ConfigurationFileIdentity:
    """Hash one real regular configuration file without emitting its contents."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_CONFIG_NOT_REGULAR")
    return ConfigurationFileIdentity(
        path=path.as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        mode=stat.S_IMODE(info.st_mode),
        uid=info.st_uid,
        gid=info.st_gid,
        size_bytes=info.st_size,
    )


def _container_code(
    prefix: tuple[str, ...],
    source_paths: tuple[str, ...],
    targets: tuple[str, ...],
    command: ObservationCommand,
) -> dict[str, object]:
    """Apply the identical declared code scope inside an image or live container."""
    return _object(
        json.loads(
            command(
                (
                    *prefix,
                    "-c",
                    _CONTAINER_OBSERVATION_PROGRAM,
                    json.dumps(source_paths),
                    json.dumps(targets),
                )
            )
        )
    )


def _service(
    name: str,
    source_paths: tuple[str, ...],
    command: ObservationCommand,
) -> RuntimeServiceIdentity:
    """Observe one uniquely labelled running service and every Docker mount."""
    ids = command(
        (
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=agomtradepro",
            "--filter",
            f"label=com.docker.compose.service={name}",
            "--format",
            "{{.ID}}",
            "--no-trunc",
        )
    ).splitlines()
    if len(ids) != 1:
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_SERVICE_NOT_UNIQUE")
    container = _inspect(("docker", "inspect", ids[0]), command)
    config = _object(container.get("Config"))
    state = _object(container.get("State"))
    image_id = _string(container.get("Image"))
    image = _inspect(("docker", "image", "inspect", image_id), command)
    labels = _object(_object(image.get("Config")).get("Labels"))
    docker_mounts = tuple(_object(item) for item in _array(container.get("Mounts")))
    targets = tuple(_string(mount.get("Destination")) for mount in docker_mounts)
    code = _container_code(("docker", "exec", ids[0], "python"), source_paths, targets, command)
    inside_mounts = _object(code.get("mounts"))
    mounts: list[RuntimeMountIdentity] = []
    for mount, target in zip(docker_mounts, targets, strict=True):
        source = Path(_string(mount.get("Source")))
        source_info = source.stat()
        source_kind: MountKind = "directory" if stat.S_ISDIR(source_info.st_mode) else "file"
        if not (stat.S_ISDIR(source_info.st_mode) or stat.S_ISREG(source_info.st_mode)):
            raise LegacyBaselineBlocked("LEGACY_RUNTIME_MOUNT_KIND_INVALID")
        inside = _object(inside_mounts.get(target))
        inside_kind = _string(inside.get("kind"))
        if inside_kind not in {"file", "directory"} or type(mount.get("RW")) is not bool:
            raise LegacyBaselineBlocked("LEGACY_RUNTIME_MOUNT_KIND_INVALID")
        mount_type = _string(mount.get("Type"))
        if mount_type not in {"bind", "volume"}:
            raise LegacyBaselineBlocked("LEGACY_RUNTIME_MOUNT_TYPE_INVALID")
        mounts.append(
            RuntimeMountIdentity(
                mount_type=cast(Literal["bind", "volume"], mount_type),
                host_source_path=source.as_posix(),
                host_source_realpath=source.resolve(strict=True).as_posix(),
                host_source_kind=source_kind,
                host_source_device=source_info.st_dev,
                host_source_inode=source_info.st_ino,
                container_target=target,
                container_target_kind=cast(MountKind, inside_kind),
                container_target_device=_integer(inside.get("device")),
                container_target_inode=_integer(inside.get("inode")),
                read_only=not mount["RW"],
            )
        )
    environment = tuple(_string(value) for value in _array(config.get("Env")))
    return RuntimeServiceIdentity(
        service_name=name,
        container_id=_string(container.get("Id")),
        state=_string(state.get("Status")),
        configured_image_tag=_string(config.get("Image")),
        image_id=image_id,
        image_oci_revision=_string(labels.get("org.opencontainers.image.revision")),
        started_at=datetime.fromisoformat(_string(state.get("StartedAt")).replace("Z", "+00:00")),
        runtime_code_sha256=_string(code.get("runtime_code_sha256")),
        environment_sha256=hashlib.sha256(
            json.dumps(sorted(environment), separators=(",", ":")).encode()
        ).hexdigest(),
        process_configuration_sha256=process_configuration_digest(container),
        mounts=tuple(sorted(mounts, key=lambda mount: mount.container_target)),
    )


def process_configuration_digest(container: dict[str, object]) -> str:
    """Bind effective command, user, health, security, resources and network membership.

    Docker-generated hostname and Compose labels may change on recreation.
    Environment and physical mounts have separate complete identity checks.
    Network endpoint IDs and IPs are ephemeral; network names and IDs are bound.
    """
    config = _object(container.get("Config"))
    host = _object(container.get("HostConfig"))
    networks = _object(_object(container.get("NetworkSettings")).get("Networks"))
    if not networks or not {"Cmd", "Entrypoint", "WorkingDir", "User"}.issubset(config):
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_PROCESS_CONFIGURATION_INCOMPLETE")
    if not {"RestartPolicy", "PidMode", "NetworkMode", "PortBindings"}.issubset(host):
        raise LegacyBaselineBlocked("LEGACY_RUNTIME_PROCESS_CONFIGURATION_INCOMPLETE")
    payload = {
        "schema": "legacy-effective-container-configuration.v1",
        "config": {
            key: value for key, value in config.items() if key not in {"Env", "Hostname", "Labels"}
        },
        "host_config": {
            key: value for key, value in host.items() if key not in {"Binds", "Mounts"}
        },
        "networks": {
            name: _string(_object(value).get("NetworkID")) for name, value in networks.items()
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def observe_legacy_runtime(*, command: ObservationCommand = _command) -> LegacyRuntimeSnapshot:
    """Capture actual host/image/service identities for this one legacy release."""
    root = Path(LEGACY_RELEASE_PATH)
    source_paths = tuple(name for name in COMPATIBILITY_SOURCE_PATHS if (root / name).is_file())
    host_digest = hashlib.sha256()
    for name in source_paths:
        path = root / name
        if path.is_symlink():
            raise LegacyBaselineBlocked("LEGACY_RUNTIME_COMPATIBILITY_SOURCE_SYMLINK")
        host_digest.update(name.encode())
        host_digest.update(b"\0")
        host_digest.update(path.read_bytes())
        host_digest.update(b"\0")
    image = _inspect(("docker", "image", "inspect", LEGACY_IMAGE_TAG), command)
    labels = _object(_object(image.get("Config")).get("Labels"))
    code = _container_code(
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cpus",
            "0.5",
            "--memory",
            "256m",
            "--pids-limit",
            "64",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "python",
            LEGACY_IMAGE_ID,
        ),
        source_paths,
        (),
        command,
    )
    config = tuple(_configuration(Path(name)) for name in sorted(REQUIRED_CONFIG_PATHS))
    services = tuple(_service(name, source_paths, command) for name in REQUIRED_SERVICE_NAMES)
    return LegacyRuntimeSnapshot(
        observed_at=datetime.now(UTC),
        current_link=_filesystem(Path(LEGACY_CURRENT_PATH)),
        release_root=_filesystem(root),
        manifest_path=_filesystem(root / ".agom-release-manifest.json"),
        source_commit=command(("git", "-C", LEGACY_RELEASE_PATH, "rev-parse", "HEAD")),
        image_tag=LEGACY_IMAGE_TAG,
        image_id=_string(image.get("Id")),
        image_oci_revision=_string(labels.get("org.opencontainers.image.revision")),
        compatibility_source_paths=source_paths,
        compatibility_source_sha256=host_digest.hexdigest(),
        image_compatibility_source_sha256=_string(code.get("compatibility_source_sha256")),
        runtime_code_scope=RUNTIME_CODE_SCOPE,
        image_runtime_code_sha256=_string(code.get("runtime_code_sha256")),
        configuration_files=config,
        runtime_config_sha256=hash_runtime_configuration_inventory(config),
        services=services,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Capture a new observation or compare pinned bytes with the actual live runtime."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "compare"))
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--baseline-sha256", default="")
    parser.add_argument("--phase", choices=("pre_cutover", "after_restore"), default="pre_cutover")
    args = parser.parse_args(argv)
    try:
        if args.action == "compare":
            info = args.baseline_json.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise LegacyBaselineBlocked("LEGACY_BASELINE_NOT_REGULAR")
            raw = args.baseline_json.read_bytes()
            if not args.baseline_sha256 or hashlib.sha256(raw).hexdigest() != args.baseline_sha256:
                raise LegacyBaselineBlocked("LEGACY_BASELINE_DIGEST_MISMATCH")
            baseline = decode_legacy_observed_runtime_baseline(raw)
            reasons = compare_legacy_baseline_runtime(
                baseline, observe_legacy_runtime(), phase=args.phase
            )
            if reasons:
                raise LegacyBaselineBlocked(",".join(reasons))
            print("LEGACY_OBSERVED_RUNTIME_MATCH")
            return 0
        snapshot = observe_legacy_runtime()
        raw = encode_legacy_observed_runtime_baseline(
            capture_legacy_observed_runtime_baseline(
                snapshot,
                observed_at=snapshot.observed_at,
            )
        )
        with args.baseline_json.open("xb") as output:
            output.write(raw)
        args.baseline_json.chmod(0o444)
        print(f"LEGACY_OBSERVED_RUNTIME_CAPTURED sha256={hashlib.sha256(raw).hexdigest()}")
        return 0
    except LegacyBaselineBlocked as exc:
        code = str(exc)
        if re.fullmatch(r"[A-Za-z0-9_,]+", code) is None:
            code = "LEGACY_RUNTIME_OBSERVATION_FAILED"
        print(f"LEGACY_OBSERVED_RUNTIME_BLOCKED code={code}", file=sys.stderr)
        return 2
    except OSError:
        print(
            "LEGACY_OBSERVED_RUNTIME_BLOCKED code=LEGACY_RUNTIME_FILESYSTEM_IO_FAILED",
            file=sys.stderr,
        )
        return 2
    except (ValueError, KeyError, TypeError):
        # Filesystem/Docker fields may contain credentials; never expose raw exceptions.
        print(
            "LEGACY_OBSERVED_RUNTIME_BLOCKED code=LEGACY_RUNTIME_OBSERVATION_INPUT_INVALID",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
