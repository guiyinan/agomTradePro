#!/usr/bin/env python3
"""Check unchanged infrastructure and exact app identity during legacy cutover."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import stat
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import capture_legacy_observed_runtime as observer  # noqa: E402
from scripts.legacy_observed_runtime_baseline import (  # noqa: E402
    COMPATIBILITY_SOURCE_PATHS,
    MANIFEST_CONTAINER_PATH,
    REQUIRED_SERVICE_NAMES,
    LegacyBaselineBlocked,
)

_INFRASTRUCTURE = ("runtime_ns", "redis", "postgres", "caddy")
_INFRA_SCHEMA = "legacy-observed-unchanged-infrastructure.v1"


def _digest(value: object) -> str:
    """Hash effective Docker JSON without retaining plaintext configuration."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _container(service: str, *, stopped: bool = False) -> dict[str, object]:
    """Require a unique project/service container, including stopped apps if asked."""
    arguments = ("docker", "ps", "-a") if stopped else ("docker", "ps")
    ids = observer._command(
        (
            *arguments,
            "--filter",
            "label=com.docker.compose.project=agomtradepro",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
            "--no-trunc",
        )
    ).splitlines()
    if len(ids) != 1:
        raise LegacyBaselineBlocked("OBSERVED_SERVICE_IDENTITY_AMBIGUOUS")
    return observer._inspect(("docker", "inspect", ids[0]), observer._command)


def infrastructure_snapshot() -> dict[str, object]:
    """Bind four existing infra containers without starting or reconfiguring them."""
    services: list[dict[str, object]] = []
    for name in _INFRASTRUCTURE:
        container = _container(name)
        state = observer._object(container.get("State"))
        if (
            state.get("Running") is not True
            or state.get("Paused") is not False
            or state.get("Restarting") is not False
        ):
            raise LegacyBaselineBlocked("OBSERVED_INFRASTRUCTURE_NOT_RUNNING")
        mounts: list[dict[str, object]] = []
        for raw in observer._array(container.get("Mounts")):
            mount = observer._object(raw)
            source = Path(observer._string(mount.get("Source")))
            info = source.stat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise LegacyBaselineBlocked("OBSERVED_INFRASTRUCTURE_MOUNT_INVALID")
            mounts.append(
                {
                    "mount": mount,
                    "physical_source": source.resolve(strict=True).as_posix(),
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "mode": stat.S_IMODE(info.st_mode),
                    "uid": info.st_uid,
                    "gid": info.st_gid,
                    "file_sha256": (
                        hashlib.sha256(source.read_bytes()).hexdigest()
                        if stat.S_ISREG(info.st_mode)
                        else None
                    ),
                }
            )
        services.append(
            {
                "service": name,
                "container_id": observer._string(container.get("Id")),
                "image_id": observer._string(container.get("Image")),
                "started_at": observer._string(state.get("StartedAt")),
                "configuration_sha256": _digest(
                    {"config": container.get("Config"), "host": container.get("HostConfig")}
                ),
                "network_sha256": _digest(container.get("NetworkSettings")),
                "mounts_sha256": _digest(
                    sorted(mounts, key=lambda item: str(item["physical_source"]))
                ),
            }
        )
    return {"schema": _INFRA_SCHEMA, "services": services}


def compare_infrastructure(path: Path) -> None:
    """Fail unless all captured infrastructure identities remain exactly unchanged."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise LegacyBaselineBlocked("OBSERVED_INFRASTRUCTURE_SNAPSHOT_INVALID")
    prior: object = json.loads(path.read_bytes())
    current = infrastructure_snapshot()
    if prior != current:
        raise LegacyBaselineBlocked("OBSERVED_INFRASTRUCTURE_DRIFT")


def _argv(value: object) -> list[str]:
    """Normalize Compose's string/list command form without executing a shell."""
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    return [observer._string(item) for item in observer._array(value)]


def _environment(value: object) -> dict[str, str]:
    """Narrow Docker environment strings only in memory, rejecting duplicates."""
    result: dict[str, str] = {}
    for raw in observer._array(value):
        key, separator, text = observer._string(raw).partition("=")
        if not separator or not key or key in result:
            raise LegacyBaselineBlocked("OBSERVED_APP_ENVIRONMENT_INVALID")
        result[key] = text
    return result


def check_service_role(
    actual: dict[str, object],
    expected: dict[str, object],
    image: dict[str, object],
    *,
    phase: str,
    network_names: set[str],
    namespace_container_id: str,
) -> None:
    """Bind each effective app process and environment to its resolved Compose role."""
    config = observer._object(actual.get("Config"))
    host = observer._object(actual.get("HostConfig"))
    for compose_key, image_key in (("command", "Cmd"), ("entrypoint", "Entrypoint")):
        value = expected.get(compose_key)
        if value is None:
            value = image.get(image_key)
        if _argv(config.get(image_key)) != _argv(value):
            raise LegacyBaselineBlocked("OBSERVED_APP_SERVICE_ROLE_MISMATCH")
    for compose_key, image_key in (("working_dir", "WorkingDir"), ("user", "User")):
        if config.get(image_key, "") != expected.get(compose_key, image.get(image_key, "")):
            raise LegacyBaselineBlocked("OBSERVED_APP_SERVICE_ROLE_MISMATCH")
    wanted = _environment(image.get("Env", []))
    for key, value in observer._object(expected.get("environment", {})).items():
        if value is None:
            wanted.pop(key, None)
        elif isinstance(value, (str, int, float, bool)):
            wanted[key] = str(value)
        else:
            raise LegacyBaselineBlocked("OBSERVED_APP_ENVIRONMENT_INVALID")
    if phase == "a":
        wanted["PGOPTIONS"] = "-c default_transaction_read_only=on"
    if _environment(config.get("Env")) != wanted:
        raise LegacyBaselineBlocked("OBSERVED_APP_ENVIRONMENT_MISMATCH")
    health = observer._object(expected.get("healthcheck", {}))
    wanted_test = ["NONE"] if health.get("disable") is True else health.get("test")
    if wanted_test is None:
        wanted_test = observer._object(image.get("Healthcheck", {})).get("Test")
    if _argv(observer._object(config.get("Healthcheck", {})).get("Test")) != _argv(wanted_test):
        raise LegacyBaselineBlocked("OBSERVED_APP_HEALTH_CONFIGURATION_MISMATCH")
    if (
        expected.get("pid") != "service:runtime_ns"
        or host.get("PidMode") != f"container:{namespace_container_id}"
    ):
        raise LegacyBaselineBlocked("OBSERVED_APP_NAMESPACE_MISMATCH")
    restart = observer._object(host.get("RestartPolicy"))
    if restart.get("Name") != expected.get("restart", "no"):
        raise LegacyBaselineBlocked("OBSERVED_APP_RESTART_POLICY_MISMATCH")
    actual_networks = observer._object(
        observer._object(actual.get("NetworkSettings")).get("Networks")
    )
    if set(actual_networks) != network_names:
        raise LegacyBaselineBlocked("OBSERVED_APP_NETWORK_MEMBERSHIP_MISMATCH")
    if "mem_limit" in expected and str(host.get("Memory")) != str(expected["mem_limit"]):
        raise LegacyBaselineBlocked("OBSERVED_APP_RESOURCE_CONFIGURATION_MISMATCH")
    if "cpus" in expected:
        try:
            cpus = Decimal(str(expected["cpus"]))
            wanted_nanos = int(cpus * 1_000_000_000)
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise LegacyBaselineBlocked("OBSERVED_APP_RESOURCE_CONFIGURATION_INVALID") from exc
        if host.get("NanoCpus") != wanted_nanos:
            raise LegacyBaselineBlocked("OBSERVED_APP_RESOURCE_CONFIGURATION_MISMATCH")
    if host.get("ReadonlyRootfs") is not expected.get("read_only", False) or host.get(
        "Privileged"
    ) is not expected.get("privileged", False):
        raise LegacyBaselineBlocked("OBSERVED_APP_SECURITY_CONFIGURATION_MISMATCH")


def check_writers_stopped(*, include_web: bool = True) -> None:
    """Confirm all app writers, or the four background workers, are stopped."""
    names = REQUIRED_SERVICE_NAMES if include_web else REQUIRED_SERVICE_NAMES[1:]
    for name in names:
        state = observer._object(_container(name, stopped=True).get("State"))
        if (
            state.get("Running") is not False
            or state.get("Restarting") is not False
            or state.get("Status") not in {"exited", "created"}
        ):
            raise LegacyBaselineBlocked("OBSERVED_APP_WRITERS_NOT_STOPPED")


def check_candidate_apps(
    release_root: Path,
    *,
    phase: str,
    image_id: str,
    candidate_sha: str,
) -> dict[str, object]:
    """Verify read-only PhaseA web or all five PhaseB apps against the actual image."""
    if phase not in {"a", "b"}:
        raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_PHASE_INVALID")
    root = release_root.resolve(strict=True)
    if (
        root != release_root
        or root.parent != Path("/opt/agomtradepro/releases")
        or not root.name.startswith("source-")
    ):
        raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_ROOT_INVALID")
    path = root / ".agom-release-manifest.json"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o444:
        raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_MANIFEST_INVALID")
    manifest = observer._object(json.loads(path.read_bytes()))
    if manifest.get("source_commit") != candidate_sha or manifest.get("image_id") != image_id:
        raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_MANIFEST_DRIFT")
    tag = observer._string(manifest.get("image_tag"))
    compose = observer._object(
        json.loads(
            observer._command(
                (
                    "docker",
                    "compose",
                    "-p",
                    "agomtradepro",
                    "-f",
                    str(root / "docker/docker-compose.vps.yml"),
                    "--env-file",
                    str(root / "deploy/.env"),
                    "config",
                    "--format",
                    "json",
                )
            )
        )
    )
    expected_services = observer._object(compose.get("services"))
    expected_networks = observer._object(compose.get("networks"))
    image_config = observer._object(
        observer._inspect(("docker", "image", "inspect", image_id), observer._command).get("Config")
    )
    namespace_id = observer._string(_container("runtime_ns").get("Id"))
    immutable = observer._container_code(
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
            image_id,
        ),
        COMPATIBILITY_SOURCE_PATHS,
        (),
        observer._command,
    )
    expected_code = observer._string(immutable.get("runtime_code_sha256"))
    inspected: list[str] = []
    for name in REQUIRED_SERVICE_NAMES:
        if phase == "a" and name != "web":
            container = _container(name, stopped=True)
            state = observer._object(container.get("State"))
            if state.get("Running") is not False or state.get("Status") not in {
                "created",
                "exited",
            }:
                raise LegacyBaselineBlocked("OBSERVED_PHASE_A_WRITER_RUNNING")
            continue
        service = observer._service(name, COMPATIBILITY_SOURCE_PATHS, observer._command)
        expected_service = observer._object(expected_services.get(name))
        service_networks = observer._object(expected_service.get("networks"))
        network_names = {
            observer._string(observer._object(expected_networks.get(key)).get("name"))
            for key in service_networks
        }
        check_service_role(
            _container(name),
            expected_service,
            image_config,
            phase=phase,
            network_names=network_names,
            namespace_container_id=namespace_id,
        )
        if (
            service.state != "running"
            or service.configured_image_tag != tag
            or service.image_id != image_id
            or service.image_oci_revision != candidate_sha
            or service.runtime_code_sha256 != expected_code
        ):
            raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_APP_IDENTITY_MISMATCH")
        mounts = tuple(
            mount for mount in service.mounts if mount.container_target == MANIFEST_CONTAINER_PATH
        )
        if len(mounts) != 1:
            raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_MANIFEST_MOUNT_INVALID")
        mount = mounts[0]
        if (
            mount.mount_type != "bind"
            or mount.host_source_realpath != path.as_posix()
            or mount.host_source_kind != "file"
            or mount.host_source_device != info.st_dev
            or mount.host_source_inode != info.st_ino
            or mount.container_target_kind != "file"
            or not mount.read_only
        ):
            raise LegacyBaselineBlocked("OBSERVED_CANDIDATE_MANIFEST_MOUNT_INVALID")
        if phase == "a":
            data_mounts = tuple(
                item for item in service.mounts if item.container_target == "/app/data"
            )
            if len(data_mounts) != 1 or not data_mounts[0].read_only:
                raise LegacyBaselineBlocked("OBSERVED_PHASE_A_SHARED_DATA_WRITABLE")
        inspected.append(name)
        if phase == "a":
            program = (
                "import django; django.setup(); from django.db import connection; "
                "c=connection.cursor(); c.execute('SHOW default_transaction_read_only'); "
                "default=c.fetchone()[0]; c.execute('SHOW transaction_read_only'); "
                "current=c.fetchone()[0]; "
                "raise SystemExit(0 if default == current == 'on' else 2)"
            )
            observer._command(("docker", "exec", service.container_id, "python", "-c", program))
    return {
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "phase": phase,
        "runtime_code_sha256": expected_code,
        "running_services": inspected,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run only one explicit identity check; never recreate a container or write DB data."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    capture = commands.add_parser("infra-capture")
    capture.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("infra-compare")
    compare.add_argument("--snapshot", type=Path, required=True)
    commands.add_parser("writers-stopped")
    commands.add_parser("workers-stopped")
    candidate = commands.add_parser("candidate-app-check")
    candidate.add_argument("--release-root", type=Path, required=True)
    candidate.add_argument("--phase", choices=("a", "b"), required=True)
    candidate.add_argument("--image-id", required=True)
    candidate.add_argument("--candidate-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "infra-capture":
            payload = infrastructure_snapshot()
            with args.output.open("xb") as stream:
                stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
            args.output.chmod(0o444)
        elif args.action == "infra-compare":
            compare_infrastructure(args.snapshot)
        elif args.action == "writers-stopped":
            check_writers_stopped()
        elif args.action == "workers-stopped":
            check_writers_stopped(include_web=False)
        else:
            check_candidate_apps(
                args.release_root,
                phase=args.phase,
                image_id=args.image_id,
                candidate_sha=args.candidate_sha,
            )
        print("OBSERVED_RUNTIME_IDENTITY_CHECK_PASSED")
        return 0
    except LegacyBaselineBlocked as exc:
        code = str(exc)
        if re.fullmatch(r"[A-Za-z0-9_,]+", code) is None:
            code = "OBSERVED_RUNTIME_IDENTITY_INVALID"
        print(f"OBSERVED_RUNTIME_IDENTITY_CHECK_BLOCKED code={code}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "OBSERVED_RUNTIME_IDENTITY_CHECK_BLOCKED code=OBSERVED_RUNTIME_INPUT_INVALID",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
