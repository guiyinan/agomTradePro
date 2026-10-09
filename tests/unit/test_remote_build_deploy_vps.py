from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml


def _load_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    spec = importlib.util.spec_from_file_location("remote_build_deploy_vps", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


remote_build_deploy_vps = _load_module()


@pytest.mark.parametrize(
    "builder_name",
    [
        "_build_remote_build_script",
        "_build_remote_git_clone_build_script",
        "_build_remote_deploy_script",
    ],
)
def test_generated_remote_docker_scripts_are_valid_bash(builder_name: str) -> None:
    """The generated remote shell must parse before it can reach Docker or release files."""

    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        git_bash = None if git is None else Path(git).parent.parent / "bin" / "bash.exe"
        bash = str(git_bash) if git_bash is not None and git_bash.is_file() else None
    if bash is None:
        pytest.skip("bash is required to parse generated remote scripts")
    script = getattr(remote_build_deploy_vps, builder_name)()

    result = subprocess.run(
        [bash, "-n"],
        check=False,
        capture_output=True,
        text=True,
        input=script,
    )

    assert result.returncode == 0, result.stderr


def _required_cli_options(source: str) -> set[str]:
    """Return literal argparse options declared with ``required=True``."""
    tree = ast.parse(source)
    required: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        is_required = any(
            keyword.arg == "required"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        option = node.args[0]
        if is_required and isinstance(option, ast.Constant) and isinstance(option.value, str):
            required.add(option.value)
    return required


def _missing_cli_options(required: set[str], argument_block: str, quote: str) -> list[str]:
    """Return required CLI options absent from one concrete argument block."""
    return sorted(option for option in required if f"{quote}{option}{quote}" not in argument_block)


def test_remote_build_report_paths_are_isolated_by_tag_and_attempt() -> None:
    """Concurrent releases and retries must not share one remote /tmp report."""
    first_tag = remote_build_deploy_vps._remote_build_report_path("20261006120001", "a" * 32)
    second_tag = remote_build_deploy_vps._remote_build_report_path("20261006120002", "a" * 32)
    retry = remote_build_deploy_vps._remote_build_report_path("20261006120001", "b" * 32)

    assert first_tag == "/tmp/agomtradepro-build-report-20261006120001-" + "a" * 32 + ".json"
    assert len({first_tag, second_tag, retry}) == 3


def test_local_build_report_paths_are_isolated_and_keep_release_glob_prefix(
    tmp_path: Path,
) -> None:
    """Downloaded reports must not overwrite a concurrent release or retry."""
    report_dir = tmp_path / "reports"
    first_tag = remote_build_deploy_vps._local_build_report_path(
        report_dir, "20261006120001", "a" * 32
    )
    second_tag = remote_build_deploy_vps._local_build_report_path(
        report_dir, "20261006120002", "a" * 32
    )
    retry = remote_build_deploy_vps._local_build_report_path(report_dir, "20261006120001", "b" * 32)

    assert len({first_tag, second_tag, retry}) == 3
    assert all(
        path.name.startswith("remote-build-report-") for path in (first_tag, second_tag, retry)
    )
    assert all(path.match("remote-build-report-*.json") for path in (first_tag, second_tag, retry))


@pytest.mark.parametrize(
    ("release_tag", "attempt_id"),
    [("20261006120001/../other", "a" * 32), ("20261006120001", "../" + "a" * 29)],
)
def test_remote_build_report_path_rejects_untrusted_components(
    release_tag: str, attempt_id: str
) -> None:
    with pytest.raises(ValueError):
        remote_build_deploy_vps._remote_build_report_path(release_tag, attempt_id)


@pytest.mark.parametrize(
    "builder_name",
    ["_build_remote_build_script", "_build_remote_git_clone_build_script"],
)
def test_remote_build_scripts_use_the_invocation_report_path(builder_name: str) -> None:
    """Both build modes must write and return the caller's isolated report path."""
    script = getattr(remote_build_deploy_vps, builder_name)()

    assert 'BUILD_REPORT_PATH="${BUILD_REPORT_PATH:?missing BUILD_REPORT_PATH}"' in script
    assert 'Path(os.environ["BUILD_REPORT_PATH"])' in script
    assert 'echo "BUILD_REPORT_PATH=$BUILD_REPORT_PATH"' in script
    assert "/tmp/agomtradepro-build-report.json" not in script

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")
    assert source.count('"BUILD_REPORT_PATH": expected_build_report_path') == 2
    assert "if reported_path != expected_build_report_path:" in source
    assert "shlex.quote(expected_build_report_path)" in source


def test_run_drains_stdout_and_stderr_without_sequential_read_deadlock() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.stdout_chunks = [b"stdout\n"]
            self.stderr_chunks = [b"stderr\n"]

        def recv_ready(self) -> bool:
            return bool(self.stdout_chunks)

        def recv_stderr_ready(self) -> bool:
            return bool(self.stderr_chunks)

        def recv(self, _size: int) -> bytes:
            return self.stdout_chunks.pop(0)

        def recv_stderr(self, _size: int) -> bytes:
            return self.stderr_chunks.pop(0)

        def exit_status_ready(self) -> bool:
            return not self.stdout_chunks and not self.stderr_chunks

        def recv_exit_status(self) -> int:
            return 0

        def close(self) -> None:
            return None

    class FakeStream:
        def __init__(self, channel: FakeChannel) -> None:
            self.channel = channel

        def read(self) -> bytes:
            raise AssertionError("sequential stream reads can deadlock")

    class FakeSSH:
        def exec_command(
            self, _command: str, timeout: int
        ) -> tuple[object, FakeStream, FakeStream]:
            assert timeout == 5
            channel = FakeChannel()
            return object(), FakeStream(channel), FakeStream(channel)

    exit_code, stdout, stderr = remote_build_deploy_vps._run(FakeSSH(), "check", timeout=5)

    assert exit_code == 0
    assert stdout == "stdout\n"
    assert stderr == "stderr\n"


def test_run_emits_safe_remote_command_heartbeat(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeChannel:
        def recv_ready(self) -> bool:
            return False

        def recv_stderr_ready(self) -> bool:
            return False

        def exit_status_ready(self) -> bool:
            return True

        def recv_exit_status(self) -> int:
            return 0

        def close(self) -> None:
            return None

    class FakeStream:
        def __init__(self, channel: FakeChannel) -> None:
            self.channel = channel

    class FakeSSH:
        def exec_command(
            self, _command: str, timeout: int
        ) -> tuple[object, FakeStream, FakeStream]:
            assert timeout == 5
            channel = FakeChannel()
            return object(), FakeStream(channel), FakeStream(channel)

    monkeypatch.setattr(remote_build_deploy_vps, "REMOTE_COMMAND_HEARTBEAT_SECONDS", 0.0)

    exit_code, stdout, stderr = remote_build_deploy_vps._run(
        FakeSSH(), "secret-command-value", timeout=5
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""
    assert "Remote command active:" in captured.out
    assert "stdout_bytes=0 stderr_bytes=0" in captured.out
    assert "secret-command-value" not in captured.out


@pytest.mark.parametrize(
    "value",
    [
        "62.171.144.39",
        "2001:db8::1",
        "https://demo.agomtrade.pro",
        "demo.agomtrade.pro/path",
        "demo.agomtrade.pro:443",
    ],
)
def test_normalize_domain_rejects_values_that_caddy_cannot_certify_safely(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        remote_build_deploy_vps._normalize_domain(value)


def test_normalize_domain_accepts_and_canonicalizes_dns_hostname() -> None:
    assert (
        remote_build_deploy_vps._normalize_domain(" Demo.AgomTrade.Pro. ") == "demo.agomtrade.pro"
    )


def test_normalize_domain_keeps_blank_http_only_mode() -> None:
    assert remote_build_deploy_vps._normalize_domain("  ") == ""


@pytest.mark.parametrize(
    "value",
    [
        "",
        "unknown",
        "A" * 40,
        "a" * 39,
        "a" * 41,
        "g" * 40,
    ],
)
def test_normalize_source_commit_rejects_noncanonical_identity(value: str) -> None:
    with pytest.raises(ValueError, match="lowercase 40-hex"):
        remote_build_deploy_vps._normalize_source_commit(value)


def test_normalize_source_commit_accepts_exact_lowercase_sha1() -> None:
    source_commit = "0123456789abcdef0123456789abcdef01234567"

    assert remote_build_deploy_vps._normalize_source_commit(source_commit) == source_commit


@pytest.mark.parametrize(
    ("release_tag", "image_id", "rehearsal_sha256"),
    [
        ("", "", ""),
        ("20260925010101", "sha256:" + "a" * 63, "b" * 64),
        ("2026092501010x", "sha256:" + "a" * 64, "b" * 64),
        ("20260925010101", "sha256:" + "a" * 64, "invalid"),
    ],
)
def test_deploy_capable_remote_run_requires_complete_prebuilt_rehearsal_identity(
    release_tag: str, image_id: str, rehearsal_sha256: str
) -> None:
    with pytest.raises(ValueError, match="Deploy-capable runs require"):
        remote_build_deploy_vps._validate_prebuilt_deployment_inputs(
            deploy_after_build=True,
            release_tag=release_tag,
            image_id=image_id,
            rehearsal_sha256=rehearsal_sha256,
            rehearsal_receipt="receipt.json",
        )


def test_deploy_capable_remote_run_accepts_exact_prebuilt_rehearsal_identity() -> None:
    assert remote_build_deploy_vps._validate_prebuilt_deployment_inputs(
        deploy_after_build=True,
        release_tag="20260925010101",
        image_id="sha256:" + "a" * 64,
        rehearsal_sha256="b" * 64,
        rehearsal_receipt="receipt.json",
    )


def test_prebuilt_receipt_binds_bundle_to_exact_deployment_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_id = "sha256:" + "a" * 64
    digest = "b" * 64
    validator_kwargs: dict[str, object] = {}
    monkeypatch.setattr(
        remote_build_deploy_vps,
        "verify_evidence_handoff_receipt",
        lambda _path: {
            "release_tag": "20260925010101",
            "candidate_image_id": image_id,
            "manifest_sha256": digest,
            "bundle_dir": str(tmp_path / "bundle"),
            "candidate_sha": "c" * 40,
            "target_trade_date": "2026-09-24",
            "universe_sha256": "d" * 64,
            "provider_identities_sha256": "e" * 64,
            "provider_settings_raw_file_sha256": "9" * 64,
            "provider_settings_canonical_payload_sha256": "8" * 64,
            "github_repository": "example/repo",
            "github_run_id": 123,
            "max_age_hours": 24.0,
        },
    )

    def fake_validator(**kwargs: object) -> dict[str, object]:
        validator_kwargs.update(kwargs)
        return {"outcome": "success"}

    monkeypatch.setattr(remote_build_deploy_vps, "validate_release_rehearsal", fake_validator)

    remote_build_deploy_vps._validate_prebuilt_rehearsal_receipt(
        receipt_path=tmp_path / "receipt.json",
        release_tag="20260925010101",
        image_id=image_id,
        rehearsal_sha256=digest,
    )

    assert validator_kwargs == {
        "manifest_path": tmp_path / "bundle" / "release-rehearsal-manifest.json",
        "expected_candidate": "c" * 40,
        "expected_target_date": "2026-09-24",
        "expected_universe_sha256": "d" * 64,
        "expected_provider_identities_sha256": "e" * 64,
        "expected_provider_settings_raw_file_sha256": "9" * 64,
        "expected_provider_settings_canonical_payload_sha256": "8" * 64,
        "expected_candidate_image_id": image_id,
        "expected_github_repository": "example/repo",
        "expected_github_run_id": 123,
        "max_age_hours": 24.0,
    }

    with pytest.raises(ValueError, match="identity does not match"):
        remote_build_deploy_vps._validate_prebuilt_rehearsal_receipt(
            receipt_path=tmp_path / "receipt.json",
            release_tag="20260925010102",
            image_id=image_id,
            rehearsal_sha256=digest,
        )


def test_prebuilt_receipt_cannot_bypass_independent_validator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_id = "sha256:" + "a" * 64
    digest = "b" * 64
    monkeypatch.setattr(
        remote_build_deploy_vps,
        "verify_evidence_handoff_receipt",
        lambda _path: {
            "release_tag": "20260925010101",
            "candidate_image_id": image_id,
            "manifest_sha256": digest,
            "bundle_dir": str(tmp_path / "bundle"),
            "candidate_sha": "c" * 40,
            "target_trade_date": "2026-09-24",
            "universe_sha256": "d" * 64,
            "provider_identities_sha256": "e" * 64,
            "provider_settings_raw_file_sha256": "9" * 64,
            "provider_settings_canonical_payload_sha256": "8" * 64,
            "github_repository": "example/repo",
            "github_run_id": 123,
            "max_age_hours": 24.0,
        },
    )
    monkeypatch.setattr(
        remote_build_deploy_vps,
        "validate_release_rehearsal",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("forged evidence")),
    )

    with pytest.raises(ValueError, match="Independent release rehearsal validation failed"):
        remote_build_deploy_vps._validate_prebuilt_rehearsal_receipt(
            receipt_path=tmp_path / "receipt.json",
            release_tag="20260925010101",
            image_id=image_id,
            rehearsal_sha256=digest,
        )


@pytest.mark.parametrize(
    ("builder_name", "source_mode"),
    [
        ("_build_remote_build_script", "source-upload"),
        ("_build_remote_git_clone_build_script", "git-clone"),
    ],
)
def test_remote_builds_fail_closed_and_write_immutable_release_manifest(
    builder_name: str,
    source_mode: str,
) -> None:
    script = getattr(remote_build_deploy_vps, builder_name)()

    assert "unknown" not in script
    assert 're.fullmatch(r"[0-9a-f]{40}", source_commit)' in script
    assert "org.opencontainers.image.revision" in script
    assert 'if [ "$IMAGE_REVISION" != "$SOURCE_COMMIT" ]; then' in script
    assert "image OCI revision does not match source commit" in script
    assert 'MANIFEST_PATH=".agom-release-manifest.json"' in script
    assert 'manifest_path.open("x", encoding="utf-8", newline="\\n")' in script
    assert "manifest_path.chmod(0o444)" in script
    assert '"version": 1' in script
    assert '"release_tag": release_tag' in script
    assert '"source_commit": source_commit' in script
    assert '"image_tag": image_tag' in script
    assert '"image_id": image_id' in script
    assert '"build_started_at": build_started_at' in script
    assert '"build_finished_at": build_finished_at' in script
    assert f'"source_mode": "{source_mode}"' in script
    assert "sort_keys=True" in script
    assert script.index('re.fullmatch(r"[0-9a-f]{40}", source_commit)') < script.index(
        "DOCKER_BUILDKIT=0 docker --context default build"
    )
    assert script.index("org.opencontainers.image.revision") < script.index(
        'manifest_path.open("x"'
    )


@pytest.mark.parametrize(
    "builder_name",
    ["_build_remote_build_script", "_build_remote_git_clone_build_script"],
)
def test_remote_builds_pin_safe_daemon_and_legacy_builder_without_fallback(
    builder_name: str,
) -> None:
    script = getattr(remote_build_deploy_vps, builder_name)()

    preflight = "docker_builder_preflight"
    docker_build = "DOCKER_BUILDKIT=0 docker --context default build --build-arg PIP_OFFLINE_ONLY=0"
    assert "__DOCKER_BUILD_PREFLIGHT__" not in script
    assert "DOCKER_BUILDER_MODE" in script
    assert "docker context inspect default --format '{{.Endpoints.docker.Host}}'" in script
    assert "docker --context default version --format '{{.Client.Version}}'" in script
    assert "docker --context default version --format '{{.Server.Version}}'" in script
    assert "unix:///var/run/docker.sock" in script
    assert "DOCKER_MINIMUM_SERVER_VERSION" in script
    assert "DOCKER_KNOWN_VULNERABLE_SERVER_VERSIONS" in script
    assert "REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED" in script
    assert "REHEARSAL_DOCKER_BUILDER_MODE_MISMATCH" in script
    assert "REHEARSAL_DOCKER_BUILD_FAILED" in script
    assert "DEPRECATED: The legacy builder is deprecated" in script
    assert "BuildKit is currently disabled" in script
    assert "BUILDKIT_INLINE_CACHE" not in script
    assert "if ! docker build" not in script
    assert script.count("docker --context default build") == 1
    assert script.index("\n" + preflight + "\n") < script.index(docker_build)
    assert script.index("REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED") < script.index(
        "docker_target images"
    )


def _run_generated_docker_preflight(
    preflight: str,
    *,
    client_version: str,
    server_version: str,
    context_name: str,
    endpoint: str,
) -> subprocess.CompletedProcess[str]:
    """Run a generated Docker guard against a deterministic fake Docker CLI."""

    bash = shutil.which("bash")
    python3 = shutil.which("python3")
    if os.name == "nt":
        git = shutil.which("git")
        git_bash = None if git is None else Path(git).parent.parent / "bin" / "bash.exe"
        bash = str(git_bash) if git_bash is not None and git_bash.is_file() else None
        python3 = shutil.which("python")
    if bash is None or python3 is None:
        pytest.skip("bash and python3 are required to execute the generated preflight")

    docker_stub = r"""docker() {
  case "$*" in
    "context show") printf '%s\n' "$MOCK_CONTEXT_NAME" ;;
    "context inspect default --format {{.Endpoints.docker.Host}}") printf '%s\n' "$MOCK_DOCKER_ENDPOINT" ;;
    "--context default version --format {{.Client.Version}}") printf '%s\n' "$MOCK_CLIENT_VERSION" ;;
    "--context default version --format {{.Server.Version}}") printf '%s\n' "$MOCK_SERVER_VERSION" ;;
    *) return 97 ;;
  esac
}"""
    python3_compatibility = 'python3() { python "$@"; }\n' if os.name == "nt" else ""
    command = f"set -eu\n{python3_compatibility}{docker_stub}\n{preflight}"
    environment = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        environment.pop(key, None)
    environment.update(
        {
            "DOCKER_BUILDER_MODE": "legacy",
            "DOCKER_DAEMON_ENDPOINT": "unix:///var/run/docker.sock",
            "DOCKER_MINIMUM_CLIENT_VERSION": "29.3.2",
            "DOCKER_MAXIMUM_CLIENT_VERSION_EXCLUSIVE": "30.0.0",
            "DOCKER_MINIMUM_SERVER_VERSION": "29.3.2",
            "DOCKER_KNOWN_VULNERABLE_SERVER_VERSIONS": "29.3.0,29.3.1",
            "MOCK_CLIENT_VERSION": client_version,
            "MOCK_SERVER_VERSION": server_version,
            "MOCK_CONTEXT_NAME": context_name,
            "MOCK_DOCKER_ENDPOINT": endpoint,
        }
    )
    return subprocess.run(
        [bash, "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize(
    ("client_version", "server_version", "context_name", "endpoint", "expected_code"),
    [
        ("29.3.2", "29.3.0", "default", "unix:///var/run/docker.sock", 1),
        ("29.3.2", "29.3.1", "default", "unix:///var/run/docker.sock", 1),
        ("30.0.0", "29.3.2", "default", "unix:///var/run/docker.sock", 1),
        ("29.3.2", "29.3.2", "desktop-linux", "unix:///var/run/docker.sock", 1),
        ("29.3.2", "29.3.2", "default", "tcp://docker:2375", 1),
        ("29.3.2", "29.3.2", "default", "unix:///var/run/docker.sock", 0),
    ],
)
def test_remote_docker_preflight_fault_injection_is_fail_closed_and_sanitized(
    client_version: str,
    server_version: str,
    context_name: str,
    endpoint: str,
    expected_code: int,
) -> None:
    """Exercise the generated shell's real version/endpoint gate with a fake Docker CLI."""

    result = _run_generated_docker_preflight(
        remote_build_deploy_vps._DOCKER_BUILD_PREFLIGHT,
        client_version=client_version,
        server_version=server_version,
        context_name=context_name,
        endpoint=endpoint,
    )

    assert result.returncode == expected_code, result.stderr
    output = result.stdout + result.stderr
    if expected_code:
        assert output.count("REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED") == 1
        assert client_version not in output
        assert server_version not in output
        assert endpoint not in output
    else:
        assert "Docker builder preflight passed" in output
        assert client_version not in output
        assert server_version not in output


@pytest.mark.parametrize(
    ("server_version", "context_name", "endpoint", "expected_code"),
    [
        ("29.3.0", "default", "unix:///var/run/docker.sock", 1),
        ("29.3.1", "default", "unix:///var/run/docker.sock", 1),
        ("invalid", "default", "unix:///var/run/docker.sock", 1),
        ("29.3.2", "desktop-linux", "unix:///var/run/docker.sock", 1),
        ("29.3.2", "default", "tcp://docker:2375", 1),
        ("29.3.2", "default", "unix:///var/run/docker.sock", 0),
    ],
)
def test_remote_deploy_engine_preflight_fault_injection_is_fail_closed(
    server_version: str,
    context_name: str,
    endpoint: str,
    expected_code: int,
) -> None:
    """Prebuilt deployments reject vulnerable engines without revealing host details."""

    result = _run_generated_docker_preflight(
        remote_build_deploy_vps._DOCKER_ENGINE_PREFLIGHT,
        client_version="29.3.0",
        server_version=server_version,
        context_name=context_name,
        endpoint=endpoint,
    )

    assert result.returncode == expected_code
    output = result.stdout + result.stderr
    if expected_code:
        assert output.count("REHEARSAL_DOCKER_ENGINE_PREFLIGHT_FAILED") == 1
        assert server_version not in output
        assert endpoint not in output
    else:
        assert "Docker Engine preflight passed" in output
        assert server_version not in output
        assert endpoint not in output


@pytest.mark.parametrize(
    "builder_name",
    ["_build_remote_build_script", "_build_remote_git_clone_build_script"],
)
def test_remote_builds_normalize_runtime_bind_mount_permissions_before_build(
    builder_name: str,
) -> None:
    """Restrictive checkout umasks must not make runtime configs unreadable."""

    script = getattr(remote_build_deploy_vps, builder_name)()

    normalizer = "normalize_runtime_source_permissions()"
    normalizer_call = "normalize_runtime_source_permissions\n"
    docker_build = "DOCKER_BUILDKIT=0 docker --context default build"
    assert normalizer in script
    assert normalizer_call in script
    assert 'chmod 0755 "$runtime_directory"' in script
    assert 'chmod 0644 "$runtime_config"' in script
    assert script.index(normalizer_call) < script.index(docker_build)
    assert "deploy/.env" not in remote_build_deploy_vps._RUNTIME_SOURCE_PERMISSION_NORMALIZER
    assert "secrets.env" not in remote_build_deploy_vps._RUNTIME_SOURCE_PERMISSION_NORMALIZER


def test_runtime_permission_contract_covers_all_compose_read_only_source_mounts() -> None:
    """Every source-controlled read-only bind mount needs an explicit mode owner."""

    repository_root = Path(__file__).resolve().parents[2]
    compose_path = repository_root / "docker/docker-compose.vps.yml"
    compose_payload = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assert isinstance(compose_payload, dict)
    services = compose_payload.get("services")
    assert isinstance(services, dict)
    readonly_sources: set[str] = set()
    unsupported_sources: set[str] = set()
    for service in services.values():
        assert isinstance(service, dict)
        for raw_mount in service.get("volumes", []):
            source = ""
            read_only = False
            if isinstance(raw_mount, str):
                parts = raw_mount.split(":")
                if len(parts) >= 3:
                    source = parts[0]
                    read_only = "ro" in parts[-1].split(",")
            elif isinstance(raw_mount, dict):
                mount: dict[str, Any] = raw_mount
                if mount.get("type") == "bind" and mount.get("read_only") is True:
                    source_value = mount.get("source")
                    source = source_value if isinstance(source_value, str) else ""
                    read_only = True
            if not read_only:
                continue
            if source.startswith("../"):
                readonly_sources.add(source[3:])
            elif source.startswith("./"):
                readonly_sources.add(f"docker/{source[2:]}")
            elif source and all(character.isalnum() or character in "._-" for character in source):
                continue
            else:
                unsupported_sources.add(source or "<missing>")

    generated_readable_sources = {
        ".agom-release-manifest.json",
        "docker/Caddyfile",
    }
    normalizer = remote_build_deploy_vps._RUNTIME_SOURCE_PERMISSION_NORMALIZER
    normalized_sources = {
        source
        for source in readonly_sources
        if source in normalizer or source in generated_readable_sources
    }

    assert not unsupported_sources
    assert readonly_sources == normalized_sources
    for builder_name in (
        "_build_remote_build_script",
        "_build_remote_git_clone_build_script",
    ):
        assert "manifest_path.chmod(0o444)" in getattr(remote_build_deploy_vps, builder_name)()
    deploy_script = remote_build_deploy_vps._build_remote_deploy_script()
    assert 'sed "s|__SITE_ADDRESS__|$SITE_ADDR|g" docker/Caddyfile.template' in deploy_script
    assert "chmod 0644 docker/Caddyfile" in deploy_script
    assert deploy_script.index("chmod 0644 docker/Caddyfile") < deploy_script.index(
        "compose up -d $SERVICES"
    )


@pytest.mark.parametrize(
    "builder_name",
    ["_build_remote_build_script", "_build_remote_git_clone_build_script"],
)
def test_remote_builds_prune_only_unused_project_images_and_require_disk_headroom(
    builder_name: str,
) -> None:
    """Builds must bound project image growth without touching volumes or other projects."""

    script = getattr(remote_build_deploy_vps, builder_name)()

    inventory = "docker_target images --filter 'reference=agomtradepro-web:*'"
    active_check = "docker_target ps -a --format '{{.Image}}'"
    removal = 'docker_target image rm "$image_ref"'
    disk_check = "df -Pk /var/lib/docker"

    assert inventory in script
    assert active_check in script
    assert removal in script
    assert "MIN_DOCKER_BUILD_FREE_KB=12582912" in script
    assert disk_check in script
    assert "Insufficient Docker disk headroom" in script
    assert "REHEARSAL_BUILD_DISK_HEADROOM_INSUFFICIENT" in script
    assert "REHEARSAL_BUILD_DISK_HEADROOM_UNAVAILABLE" in script
    assert "docker system prune" not in script
    assert "docker volume" not in script
    assert script.index(active_check) < script.index(removal)
    assert script.index(removal) < script.index(disk_check)
    assert script.index(disk_check) < script.index(
        "DOCKER_BUILDKIT=0 docker --context default build"
    )


def test_remote_source_upload_cleanup_is_scoped_to_dedicated_temp_directory() -> None:
    """The cleaner is opt-in only for the default, exact temporary upload path."""
    tag = "20260926123045"

    command = remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
        "/tmp/agomtradepro-source-upload", tag
    )

    assert command is not None
    assert command.startswith("python3 -c ")
    assert (
        remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
            "/opt/agomtradepro/current", tag
        )
        is None
    )
    assert (
        remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
            "/tmp/agomtradepro-source-upload/../current", tag
        )
        is None
    )
    assert (
        remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
            "/tmp/agomtradepro-source-upload/", tag
        )
        is None
    )
    assert (
        remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
            "/tmp//agomtradepro-source-upload", tag
        )
        is None
    )
    assert (
        remote_build_deploy_vps._build_remote_temp_artifact_cleanup_command(
            "/tmp/agomtradepro-source-upload", "current"
        )
        is None
    )


def _set_artifact_age(
    path: Path,
    *,
    age_seconds: int,
    now: float,
    directory_payload: str | None = None,
) -> None:
    """Create a file or directory with a predictable modification age."""
    if path.name.startswith("build-"):
        path.mkdir()
        if directory_payload is not None:
            (path / "payload.txt").write_text(directory_payload, encoding="utf-8")
    else:
        path.write_bytes(b"temporary")
    modified_at = now - age_seconds
    os.utime(path, (modified_at, modified_at))


def _run_remote_temp_pruner(
    root: Path,
    *,
    expected_root: Path,
    current_tag: str,
    simulate_live_pid: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the exact cleaner program sent to the remote host against a fixture tree."""
    helper = remote_build_deploy_vps._REMOTE_TEMP_ARTIFACT_PRUNER
    if simulate_live_pid is None:
        command = [sys.executable, "-c", helper]
    else:
        bootstrap = """\
import os
import sys

live_pid = int(sys.argv[1])
helper = sys.argv[2]
real_kill = os.kill

def kill_preserving_live_process(pid, sig):
    if pid == live_pid and sig == 0:
        return None
    return real_kill(pid, sig)

os.kill = kill_preserving_live_process
sys.argv = [sys.argv[0], *sys.argv[3:]]
exec(compile(helper, "<remote-temp-artifact-pruner>", "exec"))
"""
        command = [
            sys.executable,
            "-c",
            bootstrap,
            str(simulate_live_pid),
            helper,
        ]
    return subprocess.run(
        command
        + [
            str(root),
            str(expected_root),
            current_tag,
            str(remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_MIN_AGE_SECONDS),
            str(remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_MAX_RETAINED_PER_KIND),
            remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_LOCK_NAME,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _run_remote_build_marker_helper(
    root: Path,
    *,
    operation: str,
    tag: str,
    pid: int,
    simulate_missing_pid: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the exact marker helper embedded into the remote build script."""
    helper = remote_build_deploy_vps._REMOTE_ACTIVE_BUILD_MARKER_HELPER
    if simulate_missing_pid is None:
        command = [sys.executable, "-c", helper]
    else:
        # Exercise the helper's ESRCH branch without relying on the host OS to
        # report a just-exited PID consistently or to avoid reusing that PID.
        bootstrap = """\
import os
import sys

missing_pid = int(sys.argv[1])
helper = sys.argv[2]
real_kill = os.kill

def kill_with_missing_pid(pid, sig):
    if pid == missing_pid:
        raise ProcessLookupError(pid, "No such process")
    return real_kill(pid, sig)

os.kill = kill_with_missing_pid
sys.argv = [sys.argv[0], *sys.argv[3:]]
exec(compile(helper, "<remote-build-marker-helper>", "exec"))
"""
        command = [sys.executable, "-c", bootstrap, str(simulate_missing_pid), helper]
    return subprocess.run(
        command
        + [
            str(root),
            operation,
            tag,
            str(pid),
            remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_LOCK_NAME,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_remote_source_upload_pruner_obeys_age_count_and_asset_boundaries(
    tmp_path: Path,
) -> None:
    """Only old, exact-name temp artifacts are pruned; current and outside assets survive."""
    now = time.time()
    minimum_age = remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_MIN_AGE_SECONDS
    root = tmp_path / "source-upload"
    root.mkdir()
    current_tag = "20260926123045"

    stale_source_tags = ("20260101000001", "20260101000002", "20260101000003")
    for offset, tag in enumerate(stale_source_tags, start=1):
        _set_artifact_age(
            root / f"agomtradepro-source-deploy-{tag}.tar.gz",
            age_seconds=minimum_age + 86400 * (len(stale_source_tags) - offset + 1),
            now=now,
        )
    recent_source = root / "agomtradepro-source-deploy-20260926000001.tar.gz"
    _set_artifact_age(recent_source, age_seconds=minimum_age - 300, now=now)
    current_source = root / f"agomtradepro-source-deploy-{current_tag}.tar.gz"
    _set_artifact_age(current_source, age_seconds=minimum_age + 86400 * 10, now=now)
    current_image = root / f"agomtradepro-web-{current_tag}.tar"
    _set_artifact_age(current_image, age_seconds=minimum_age + 86400 * 10, now=now)
    current_build = root / f"build-{current_tag}"
    _set_artifact_age(current_build, age_seconds=minimum_age + 86400 * 10, now=now)

    stale_image_tags = ("20260102000001", "20260102000002", "20260102000003")
    for offset, tag in enumerate(stale_image_tags, start=1):
        _set_artifact_age(
            root / f"agomtradepro-web-{tag}.tar",
            age_seconds=minimum_age + 86400 * (len(stale_image_tags) - offset + 1),
            now=now,
        )
    stale_build_tags = ("20260103000001", "20260103000002", "20260103000003")
    for offset, tag in enumerate(stale_build_tags, start=1):
        build_dir = root / f"build-{tag}"
        _set_artifact_age(
            build_dir,
            age_seconds=minimum_age + 86400 * (len(stale_build_tags) - offset + 1),
            now=now,
            directory_payload="temporary build source",
        )

    unmatched = root / "agomtradepro-source-deploy-current.tar.gz"
    _set_artifact_age(unmatched, age_seconds=minimum_age + 86400 * 10, now=now)
    production_asset = tmp_path / "production-current-release.txt"
    production_asset.write_text("protected", encoding="utf-8")

    result = _run_remote_temp_pruner(root, expected_root=root, current_tag=current_tag)

    assert result.returncode == 0, result.stderr
    assert not (root / f"agomtradepro-source-deploy-{stale_source_tags[0]}.tar.gz").exists()
    assert (root / f"agomtradepro-source-deploy-{stale_source_tags[1]}.tar.gz").exists()
    assert (root / f"agomtradepro-source-deploy-{stale_source_tags[2]}.tar.gz").exists()
    assert recent_source.exists()
    assert current_source.exists()
    assert current_image.exists()
    assert current_build.exists()
    assert unmatched.exists()
    assert not (root / f"agomtradepro-web-{stale_image_tags[0]}.tar").exists()
    assert (root / f"agomtradepro-web-{stale_image_tags[1]}.tar").exists()
    assert (root / f"agomtradepro-web-{stale_image_tags[2]}.tar").exists()
    assert not (root / f"build-{stale_build_tags[0]}").exists()
    assert (root / f"build-{stale_build_tags[1]}").exists()
    assert (root / f"build-{stale_build_tags[2]}").exists()
    assert production_asset.read_text(encoding="utf-8") == "protected"


def test_remote_source_upload_pruner_protects_active_builds_and_rejects_wrong_root(
    tmp_path: Path,
) -> None:
    """Active markers and root identity keep builds outside the cleanup scope."""
    now = time.time()
    minimum_age = remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_MIN_AGE_SECONDS
    root = tmp_path / "source-upload"
    root.mkdir()
    active_tag = "20260104000001"
    active_archive = root / f"agomtradepro-web-{active_tag}.tar"
    _set_artifact_age(active_archive, age_seconds=minimum_age + 86400 * 3, now=now)
    claim_result = _run_remote_build_marker_helper(
        root, operation="claim", tag=active_tag, pid=os.getpid()
    )
    assert claim_result.returncode == 0, claim_result.stderr
    ordinary_tag = "20260104000002"
    ordinary_archive = root / f"agomtradepro-web-{ordinary_tag}.tar"
    _set_artifact_age(ordinary_archive, age_seconds=minimum_age + 86400 * 2, now=now)
    newest_tag = "20260104000003"
    newest_archive = root / f"agomtradepro-web-{newest_tag}.tar"
    _set_artifact_age(newest_archive, age_seconds=minimum_age + 86400, now=now)

    wrong_root_result = _run_remote_temp_pruner(
        root,
        expected_root=tmp_path,
        current_tag="20260926123045",
        simulate_live_pid=os.getpid() if os.name == "nt" else None,
    )
    assert wrong_root_result.returncode == 0, wrong_root_result.stderr
    assert active_archive.exists()
    assert ordinary_archive.exists()

    result = _run_remote_temp_pruner(
        root,
        expected_root=root,
        current_tag="20260926123045",
        simulate_live_pid=os.getpid() if os.name == "nt" else None,
    )

    assert result.returncode == 0, result.stderr
    assert active_archive.exists()
    assert ordinary_archive.exists()
    assert newest_archive.exists()


def test_remote_build_marker_claim_is_concurrent_and_release_is_owner_checked(
    tmp_path: Path,
) -> None:
    """One claimant wins; a mismatched release cannot remove the winning marker."""
    root = tmp_path / "source-upload"
    root.mkdir()
    tag = "20260105000001"
    helper = remote_build_deploy_vps._REMOTE_ACTIVE_BUILD_MARKER_HELPER
    helper_arguments = [
        str(root),
        "claim",
        tag,
        str(os.getpid()),
        remote_build_deploy_vps.REMOTE_TEMP_ARTIFACT_LOCK_NAME,
    ]
    if os.name == "nt":
        # The helper runs on Linux in production. CPython implements
        # os.kill(pid, 0) differently on Windows and may terminate the target,
        # so emulate POSIX's successful liveness probe while still executing
        # the real marker and Windows lock code concurrently.
        bootstrap = """\
import os
import sys

active_pid = int(sys.argv[1])
helper = sys.argv[2]
real_kill = os.kill

def kill_preserving_active_process(pid, sig):
    if pid == active_pid and sig == 0:
        return None
    return real_kill(pid, sig)

os.kill = kill_preserving_active_process
sys.argv = [sys.argv[0], *sys.argv[3:]]
exec(compile(helper, "<remote-build-marker-helper>", "exec"))
"""
        command = [
            sys.executable,
            "-c",
            bootstrap,
            str(os.getpid()),
            helper,
            *helper_arguments,
        ]
    else:
        command = [sys.executable, "-c", helper, *helper_arguments]
    first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    first_output = first.communicate(timeout=10)
    second_output = second.communicate(timeout=10)

    assert sorted((first.returncode, second.returncode)) == [0, 1]
    active_marker = root / f".agomtradepro-build-active-{tag}"
    assert active_marker.read_text(encoding="ascii").strip() == str(os.getpid())
    loser_stderr = first_output[1] + second_output[1]
    if os.name == "nt":
        # Windows msvcrt uses a non-blocking one-byte lock here, so the
        # concurrent loser can fail at the lock boundary before it observes
        # the marker. Both paths fail closed and leave the winning marker.
        assert (
            loser_stderr.count("REHEARSAL_BUILD_TAG_ALREADY_ACTIVE")
            + loser_stderr.count("REHEARSAL_BUILD_MARKER_LOCK_FAILED")
            == 1
        )
    else:
        assert loser_stderr.count("REHEARSAL_BUILD_TAG_ALREADY_ACTIVE") == 1

    wrong_owner_release = _run_remote_build_marker_helper(
        root, operation="release", tag=tag, pid=os.getpid() + 1
    )
    assert wrong_owner_release.returncode == 0, wrong_owner_release.stderr
    assert active_marker.exists()

    owner_release = _run_remote_build_marker_helper(
        root, operation="release", tag=tag, pid=os.getpid()
    )
    assert owner_release.returncode == 0, owner_release.stderr
    assert not active_marker.exists()
    assert first_output[0] or first_output[1] or second_output[0] or second_output[1]


def test_remote_build_marker_recovers_stale_pid_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    """Dead markers can be reclaimed while marker and artifact symlinks stay protected."""
    root = tmp_path / "source-upload"
    root.mkdir()
    stale_tag = "20260106000001"
    stale_marker = root / f".agomtradepro-build-active-{stale_tag}"
    stale_pid = 987_654_321
    stale_marker.write_text(f"{stale_pid}\n", encoding="ascii")

    reclaimed = _run_remote_build_marker_helper(
        root,
        operation="claim",
        tag=stale_tag,
        pid=os.getpid(),
        simulate_missing_pid=stale_pid,
    )
    assert reclaimed.returncode == 0, reclaimed.stderr
    assert stale_marker.read_text(encoding="ascii").strip() == str(os.getpid())
    assert (
        _run_remote_build_marker_helper(
            root, operation="release", tag=stale_tag, pid=os.getpid()
        ).returncode
        == 0
    )

    protected_target = tmp_path / "protected.txt"
    protected_target.write_text("outside", encoding="utf-8")
    symlink_tag = "20260106000002"
    active_marker = root / f".agomtradepro-build-active-{symlink_tag}"
    symlink_artifact = root / f"agomtradepro-source-deploy-{symlink_tag}.tar.gz"
    try:
        active_marker.symlink_to(protected_target)
        symlink_artifact.symlink_to(protected_target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable in this test environment: {exc}")

    claim = _run_remote_build_marker_helper(
        root, operation="claim", tag=symlink_tag, pid=os.getpid()
    )
    assert claim.returncode != 0
    prune = _run_remote_temp_pruner(root, expected_root=root, current_tag="20260926123045")

    assert prune.returncode == 0, prune.stderr
    assert active_marker.is_symlink()
    assert symlink_artifact.is_symlink()
    assert protected_target.read_text(encoding="utf-8") == "outside"


def test_remote_build_marker_command_validates_release_tag_before_path_use() -> None:
    """The generated source build claims/releases markers through the shared lock."""
    script = remote_build_deploy_vps._build_remote_build_script()

    assert "release_tag = sys.argv[2]" in script
    assert 're.fullmatch(r"[0-9]{14}", release_tag)' in script
    assert "fcntl.flock(lock_fd, fcntl.LOCK_EX)" in script
    assert "release_active_build_marker" in script
    assert "trap cleanup_remote_build EXIT" in script
    assert "docker system prune" not in script
    assert "docker volume" not in script
    assert "/opt/agomtradepro" not in remote_build_deploy_vps._REMOTE_TEMP_ARTIFACT_PRUNER


def test_upload_mode_passes_exact_local_source_commit_without_unknown_fallback() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert 'source_commit = "unknown"' not in source
    assert '"SOURCE_COMMIT": source_commit' in source
    upload_branch = source.split("else:\n            remote_bundle =", 1)[1]
    upload_build_env = upload_branch.split("exports =", 1)[0]
    assert '"SOURCE_COMMIT": source_commit' in upload_build_env


def test_upload_mode_rejects_tracked_or_untracked_worktree_changes_before_bundle_or_ssh() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    status_command = '["git", "status", "--porcelain", "--untracked-files=all"]'
    dirty_error = "Source-upload mode requires a clean Git worktree"
    bundle_start = '_info(f"Creating source bundle: {local_bundle}")'
    ssh_start = '_info(f"Connecting to {user}@{host}:{args.port}")'

    assert status_command in source
    assert dirty_error in source
    assert source.index(status_command) < source.index(bundle_start)
    assert source.index(status_command) < source.index(ssh_start)


def test_git_clone_mode_pins_remote_clone_to_requested_local_candidate() -> None:
    script = remote_build_deploy_vps._build_remote_git_clone_build_script()

    expected_assignment = 'EXPECTED_SOURCE_COMMIT="${SOURCE_COMMIT:?missing SOURCE_COMMIT}"'
    cloned_assignment = 'CLONED_SOURCE_COMMIT="$(git rev-parse --verify HEAD)"'
    comparison = 'if [ "$CLONED_SOURCE_COMMIT" != "$EXPECTED_SOURCE_COMMIT" ]; then'

    assert expected_assignment in script
    assert cloned_assignment in script
    assert comparison in script
    assert "cloned source commit does not match requested candidate" in script
    assert script.index(expected_assignment) < script.index("git clone")
    assert script.index(cloned_assignment) < script.index(comparison)
    assert script.index(comparison) < script.index(
        "DOCKER_BUILDKIT=0 docker --context default build"
    )


def test_remote_deploy_validates_manifest_and_image_before_any_start_or_switch() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    validation = 'MANIFEST_PATH="$RELEASE_DIR/.agom-release-manifest.json"'
    first_start = "compose up -d runtime_ns redis postgres"
    final_start = "compose up -d $SERVICES"
    current_switch = 'mv -Tf "$TARGET_DIR/.current-next" "$TARGET_DIR/current"'

    assert validation in script
    assert "release manifest must contain exactly" in script
    assert "expected_keys = {" in script
    assert 'manifest["release_tag"] != release_tag' in script
    assert 'manifest["image_tag"] != expected_image_tag' in script
    assert 'image_id != manifest["image_id"]' in script
    assert 'image_revision != manifest["source_commit"]' in script
    assert "rehearsal_image_id != image_id" in script
    assert "release rehearsal manifest digest must be exact lowercase SHA-256" in script
    assert "release manifest must be read-only (0444)" in script
    assert script.index(validation) < script.index(first_start)
    assert script.index(validation) < script.index(final_start)
    assert script.index(validation) < script.index(current_switch)


def test_remote_deploy_rejects_persistent_asgi_database_connections_before_shutdown() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    policy_error = "ASGI database policy requires CONN_MAX_AGE=0"
    shutdown = 'if [ "$ACTION" = "fresh" ]; then'

    assert "CONN_MAX_AGE" in script
    assert "docker run --rm --env-file deploy/.env --entrypoint python" in script
    assert policy_error in script
    assert script.index(policy_error) < script.index(shutdown)


def test_deployment_report_retains_validated_release_identity() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))' in script
    assert '"release_manifest": release_manifest' in script
    assert '"version": release_manifest["version"]' in script
    assert '"image_tag": release_manifest["image_tag"]' in script
    assert '"source_mode": release_manifest["source_mode"]' in script


def test_remote_deploy_blocks_release_on_macro_governance_drift() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "python manage.py init_macro_indicator_governance --check" in script
    assert "python manage.py normalize_macro_fact_units --check" in script
    assert "macro data-governance drift check failed" in script
    assert "python manage.py verify_canonical_schema --json" in script
    assert script.index("verify_canonical_schema --json") < script.index(
        "python manage.py check --deploy"
    )


def test_data_center_catalog_preservation_is_explicit_and_after_schema_verify() -> None:
    """The opt-in preserve flag skips only catalog sync after schema validation."""

    repository_root = Path(__file__).resolve().parents[2]
    remote_source = (repository_root / "scripts" / "remote_build_deploy_vps.py").read_text(
        encoding="utf-8"
    )
    remote_script = remote_build_deploy_vps._build_remote_deploy_script()
    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")

    preserve_assignment = 'PRESERVE_DATA_CENTER_CATALOG="${PRESERVE_DATA_CENTER_CATALOG:-0}"'
    preserve_branch = 'if [ "$PRESERVE_DATA_CENTER_CATALOG" = "1" ]; then'
    catalog_sync = "python manage.py initialize_data_center_catalog"

    assert '"--preserve-data-center-catalog"' in remote_source
    assert (
        '"PRESERVE_DATA_CENTER_CATALOG": _bool_env(args.preserve_data_center_catalog)'
        in remote_source
    )
    assert preserve_assignment in remote_script
    assert preserve_branch in remote_script
    assert "Preserving existing Data Center runtime catalog" in remote_script
    assert catalog_sync in remote_script
    assert remote_script.index("verify_canonical_schema --json") < remote_script.index(
        preserve_branch
    )
    assert remote_script.index(preserve_branch) < remote_script.index(catalog_sync)
    assert remote_script.index(catalog_sync) < remote_script.index(
        "python manage.py check --deploy"
    )
    assert "[switch]$PreserveDataCenterCatalog" in wrapper
    assert "'--preserve-data-center-catalog'" in wrapper


def test_one_click_deploy_pins_expected_commit_before_remote_work() -> None:
    """Post-deploy verification must use the candidate pinned before deployment."""

    repository_root = Path(__file__).resolve().parents[2]
    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")

    assignment = "$expectedCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()"
    launch = "& $PythonExe @pyArgs"
    verification = "'--expected-commit', $expectedCommit"
    builder_binding = "'--expected-source-commit', $expectedCommit"
    rehearsal_validation = 'Write-Info "Validating candidate-bound release rehearsal evidence..."'
    password_creation = "Set-Content -Path $passFile -Value $VpsPass -NoNewline"

    assert wrapper.count(assignment) == 1
    assert wrapper.index(assignment) < wrapper.index(launch)
    assert wrapper.index(assignment) < wrapper.index(rehearsal_validation)
    assert wrapper.index(rehearsal_validation) < wrapper.index(password_creation)
    assert wrapper.index(assignment) < wrapper.index(builder_binding) < wrapper.index(launch)
    assert wrapper.index(launch) < wrapper.index(verification)


def test_one_click_deploy_requires_explicit_release_rehearsal_inputs() -> None:
    """The deployment wrapper must not create credentials before rehearsal validation."""

    wrapper = (Path(__file__).resolve().parents[2] / "scripts" / "deploy-vps.ps1").read_text(
        encoding="utf-8"
    )
    required = (
        "$ReleaseRehearsalManifest",
        "$PrebuiltReleaseTag",
        "$PrebuiltImageId",
        "$RehearsalTargetDate",
        "$RehearsalUniverseSha256",
        "$RehearsalProviderIdentitiesSha256",
        "$RehearsalProviderSettingsRawFileSha256",
        "$RehearsalProviderSettingsCanonicalPayloadSha256",
        "$GitHubRepository",
        "$GitHubRunId",
    )
    assert "[string]$RehearsalProviderSettingsRawFileSha256," in wrapper
    assert "[string]$RehearsalProviderSettingsCanonicalPayloadSha256," in wrapper
    assert "-RawFileSha256 $RehearsalProviderSettingsRawFileSha256" in wrapper
    assert "-CanonicalPayloadSha256 $RehearsalProviderSettingsCanonicalPayloadSha256" in wrapper
    validation = "& $PythonExe @rehearsalArgs"
    password_creation = "Set-Content -Path $passFile -Value $VpsPass -NoNewline"

    for parameter in required:
        assert parameter in wrapper
    assert wrapper.index(validation) < wrapper.index("git push origin $GitBranch")
    assert wrapper.index(validation) < wrapper.index("npm ci")
    assert wrapper.index(validation) < wrapper.index(password_creation)
    assert "Release rehearsal validation failed." in wrapper
    assert wrapper.index("$providerSettingsDigestValidatorArgs = @(") < wrapper.index(
        "$VpsHost = $env:AGOM_VPS_HOST"
    )
    assert "$rehearsalArgs += $providerSettingsDigestValidatorArgs" in wrapper
    assert "'--expected-candidate-image-id', $PrebuiltImageId" in wrapper
    assert "'--prebuilt-image-id', $PrebuiltImageId" in wrapper
    assert "'--release-rehearsal-sha256', $rehearsalManifestHash" in wrapper


def test_release_validator_required_options_reach_every_cli_consumer() -> None:
    """A new required validator option must update every cross-language caller."""
    repository_root = Path(__file__).resolve().parents[2]
    validator_source = (repository_root / "scripts" / "validate_release_rehearsal.py").read_text(
        encoding="utf-8"
    )
    required_options = _required_cli_options(validator_source)
    assert required_options

    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    wrapper_end = wrapper.index('Write-Info "Validating candidate-bound')
    rehearsal = (repository_root / "scripts" / "run_release_rehearsal.py").read_text(
        encoding="utf-8"
    )
    rehearsal_start = rehearsal.index("validator_argv = (")
    rehearsal_end = rehearsal.index("_invoke(", rehearsal_start)
    consumers = {
        "one-click-deploy": (wrapper[:wrapper_end], "'"),
        "release-rehearsal": (rehearsal[rehearsal_start:rehearsal_end], '"'),
    }
    for consumer, (argument_block, quote) in consumers.items():
        missing = _missing_cli_options(required_options, argument_block, quote)
        assert not missing, f"{consumer} does not forward required validator options: {missing}"

    omitted = sorted(required_options)[0]
    wrapper_block, quote = consumers["one-click-deploy"]
    mutated_block = wrapper_block.replace(f"{quote}{omitted}{quote}", "'--omitted-by-fixture'")
    assert omitted in _missing_cli_options(required_options, mutated_block, quote)


def test_remote_builder_reuses_only_the_rehearsed_prebuilt_image() -> None:
    """Deployment must validate and reuse the exact image exercised by S6."""

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert 'ap.add_argument("--prebuilt-release-tag"' in source
    assert 'ap.add_argument("--prebuilt-image-id"' in source
    assert 'ap.add_argument("--release-rehearsal-sha256"' in source
    assert "Prebuilt candidate validation failed" in source
    assert "actual_image_id != expected_image_id" in source
    assert "actual_revision != source_commit" in source
    assert '"REHEARSAL_IMAGE_ID": args.prebuilt_image_id' in source
    assert '"RELEASE_REHEARSAL_SHA256": args.release_rehearsal_sha256' in source


def test_prebuilt_verification_script_is_valid_python() -> None:
    """The remote python -c payload must retain the quoted Docker label template."""
    script = remote_build_deploy_vps._build_prebuilt_verification_script()

    compile(script, "<prebuilt-verification>", "exec")

    assert '{{index .Config.Labels "org.opencontainers.image.revision"}}' in script


def test_prebuilt_verification_script_executes_with_exact_docker_label_and_writes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The quoted Docker template must survive execution and bind the report to S6 inputs."""
    release_tag = "20260926010101"
    source_commit = "c" * 40
    image_id = "sha256:" + "a" * 64
    rehearsal_sha256 = "b" * 64
    attempt_id = "c" * 32
    manifest_path = tmp_path / ".agom-release-manifest.json"
    report_path = remote_build_deploy_vps._remote_build_report_path(release_tag, attempt_id)
    local_report_path = tmp_path / Path(report_path).name
    manifest_path.write_text(
        json.dumps(
            {
                "release_tag": release_tag,
                "source_commit": source_commit,
                "image_tag": f"agomtradepro-web:{release_tag}",
                "image_id": image_id,
            }
        ),
        encoding="utf-8",
    )
    script = remote_build_deploy_vps._build_prebuilt_verification_script().replace(
        "Path(report_path).write_text(",
        f"(Path({str(tmp_path)!r}) / Path(report_path).name).write_text(",
    )
    commands: list[list[str]] = []

    def fake_check_output(command: list[str], *, text: bool) -> str:
        assert text is True
        commands.append(command)
        if command[-1] == "{{.Id}}":
            return image_id
        if command[-1] == '{{index .Config.Labels "org.opencontainers.image.revision"}}':
            return source_commit
        raise AssertionError(f"Unexpected docker inspect format: {command[-1]}")

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "-c",
            str(manifest_path),
            release_tag,
            source_commit,
            image_id,
            rehearsal_sha256,
            report_path,
        ],
    )

    exec(compile(script, "<prebuilt-verification>", "exec"), {})

    report = json.loads(local_report_path.read_text(encoding="utf-8"))
    assert [command[-1] for command in commands] == [
        "{{.Id}}",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
    ]
    assert report == {
        "version": 1,
        "release_tag": release_tag,
        "source_commit": source_commit,
        "image_tag": f"agomtradepro-web:{release_tag}",
        "image_id": image_id,
        "release_rehearsal_sha256": rehearsal_sha256,
        "deploy_after_build": True,
        "source_mode": "prebuilt-rehearsed-image",
    }


def test_prebuilt_verification_keeps_reports_for_two_release_tags_separate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A later tag must not overwrite the earlier invocation's remote report."""
    source_commit = "c" * 40
    image_id = "sha256:" + "a" * 64
    verifier = remote_build_deploy_vps._build_prebuilt_verification_script().replace(
        "Path(report_path).write_text(",
        f"(Path({str(tmp_path)!r}) / Path(report_path).name).write_text(",
    )
    report_paths: list[Path] = []

    def fake_check_output(command: list[str], *, text: bool) -> str:
        assert text is True
        return image_id if command[-1] == "{{.Id}}" else source_commit

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    for release_tag, attempt_id, digest in (
        ("20261006120001", "a" * 32, "b" * 64),
        ("20261006120002", "d" * 32, "e" * 64),
    ):
        manifest_path = tmp_path / f"manifest-{release_tag}.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "release_tag": release_tag,
                    "source_commit": source_commit,
                    "image_tag": f"agomtradepro-web:{release_tag}",
                    "image_id": image_id,
                }
            ),
            encoding="utf-8",
        )
        report_path = remote_build_deploy_vps._remote_build_report_path(release_tag, attempt_id)
        report_paths.append(tmp_path / Path(report_path).name)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "-c",
                str(manifest_path),
                release_tag,
                source_commit,
                image_id,
                digest,
                report_path,
            ],
        )
        exec(compile(verifier, "<prebuilt-verification>", "exec"), {})

    assert report_paths[0] != report_paths[1]
    assert [
        json.loads(path.read_text(encoding="utf-8"))["release_tag"] for path in report_paths
    ] == [
        "20261006120001",
        "20261006120002",
    ]


@pytest.mark.parametrize(
    ("actual_image_id", "actual_revision", "manifest_image_id", "rehearsal_sha256"),
    [
        ("sha256:" + "f" * 64, "c" * 40, "sha256:" + "a" * 64, "b" * 64),
        ("sha256:" + "a" * 64, "d" * 40, "sha256:" + "a" * 64, "b" * 64),
        ("sha256:" + "a" * 64, "c" * 40, "sha256:" + "f" * 64, "b" * 64),
        ("sha256:" + "a" * 64, "c" * 40, "sha256:" + "a" * 64, "invalid"),
    ],
)
def test_prebuilt_verification_script_rejects_image_manifest_or_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actual_image_id: str,
    actual_revision: str,
    manifest_image_id: str,
    rehearsal_sha256: str,
) -> None:
    """The remote verifier must stop before reporting success when any bound identity drifts."""
    release_tag = "20260926010101"
    source_commit = "c" * 40
    expected_image_id = "sha256:" + "a" * 64
    manifest_path = tmp_path / ".agom-release-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release_tag": release_tag,
                "source_commit": source_commit,
                "image_tag": f"agomtradepro-web:{release_tag}",
                "image_id": manifest_image_id,
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_check_output(command: list[str], *, text: bool) -> str:
        assert text is True
        commands.append(command)
        return actual_image_id if command[-1] == "{{.Id}}" else actual_revision

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "-c",
            str(manifest_path),
            release_tag,
            source_commit,
            expected_image_id,
            rehearsal_sha256,
            remote_build_deploy_vps._remote_build_report_path(release_tag, "f" * 32),
        ],
    )

    with pytest.raises(SystemExit, match="prebuilt candidate identity mismatch"):
        exec(
            compile(
                remote_build_deploy_vps._build_prebuilt_verification_script(),
                "<prebuilt-verification>",
                "exec",
            ),
            {},
        )

    assert [command[-1] for command in commands] == [
        "{{.Id}}",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
    ]


def test_remote_builder_rejects_candidate_drift_before_credentials() -> None:
    """The builder must compare its local HEAD with the wrapper-approved candidate."""

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    parser_option = '"--expected-source-commit"'
    comparison = "if source_commit != expected_source_commit:"
    credential_prompt = 'host = args.host or _prompt("VPS host/IP")'
    assert parser_option in source
    assert comparison in source
    assert source.index(comparison) < source.index(credential_prompt)


def test_remote_deploy_publishes_canonical_https_origin_and_validates_tls() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'EFFECTIVE_APP_BASE_URL="https://$EFFECTIVE_DOMAIN"' in script
    assert 'set_env_kv "APP_BASE_URL" "$EFFECTIVE_APP_BASE_URL"' in script
    assert "redir https://$EFFECTIVE_DOMAIN{uri} permanent" in script
    assert 'HEALTH_URL="https://$EFFECTIVE_DOMAIN/api/health/"' in script
    assert 'HEALTH_RESOLVE="--resolve $EFFECTIVE_DOMAIN:443:127.0.0.1"' in script
    assert "curl -fsS --max-time 10 $HEALTH_RESOLVE" in script


def test_remote_deploy_preflights_governed_engine_before_compose_or_release_access() -> None:
    """Prebuilt and regular deploys share the vulnerable-engine stop line."""

    script = remote_build_deploy_vps._build_remote_deploy_script()
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "__DOCKER_ENGINE_PREFLIGHT__" not in script
    assert "REHEARSAL_DOCKER_ENGINE_PREFLIGHT_FAILED" in script
    assert "docker_engine_preflight" in script
    assert script.index("docker_engine_preflight\n") < script.index("docker compose version")
    assert script.index("docker compose version") < script.index(
        'RELEASE_DIR="$TARGET_DIR/releases/'
    )
    assert (
        "docker_engine_environment = _docker_engine_policy_environment(docker_build_policy)"
        in source
    )
    assert "**docker_engine_environment" in source


def test_remote_deploy_publishes_and_verifies_tui_release_metadata() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert 'sh scripts/publish-tui-release.sh "$RELEASE_TAG"' in script
    assert "TUI metadata publish or verification failed" in script
    assert 'rollback-$(basename "$PREVIOUS_RELEASE")' in script
    assert "Automatic rollback publish" in script
    assert "Previous release TUI registry restore failed" in script

    deploy_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh"
    ).read_text(encoding="utf-8")
    release_helper = (
        Path(__file__).resolve().parents[2] / "scripts" / "publish-tui-release.sh"
    ).read_text(encoding="utf-8")

    assert 'sh scripts/publish-tui-release.sh "$release_name"' in deploy_script
    assert "--approve" in release_helper
    assert "--check" in release_helper
    assert "reviewed TUI metadata is missing" in release_helper


def test_remote_deploy_rollback_retries_and_verifies_required_services_and_health() -> None:
    """A failed deployment cannot describe an unverified rollback as restored."""

    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'while [ "$rollback_attempt" -le 3 ]' in script
    assert "for rollback_service in postgres redis web caddy" in script
    assert "docker inspect -f '{{.State.Running}}'" in script
    assert "urllib.request.urlopen('http://127.0.0.1:8000/api/health/'" in script
    assert 'while [ "$rollback_check" -le 30 ]' in script
    assert "Previous release restore verified" in script
    assert "Automatic rollback failed service and health verification" in script
    assert "Previous release restore attempted" not in script


def test_legacy_deploy_verifies_canonical_schema_after_migrations() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh").read_text(
        encoding="utf-8"
    )

    assert "python manage.py verify_canonical_schema --json" in script
    assert script.index("verify_canonical_schema --json") > script.index(
        'COMPOSE_PROJECT_NAME="$PROJECT_NAME" sh scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$release_dir"'
    )


def test_remote_deploy_forces_import_for_included_sqlite_snapshot() -> None:
    """A supplied snapshot must invalidate the marker before the import helper runs."""

    script = remote_build_deploy_vps._build_remote_deploy_script()

    snapshot_copy = "chmod 664 /dest/db.sqlite3"
    marker_reset = 'rm -f "$TARGET_DIR/.postgres-migration-complete"'
    migration_helper = (
        "COMPOSE_PROJECT_NAME=agomtradepro sh "
        'scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$RELEASE_DIR"'
    )

    assert script.index(snapshot_copy) < script.index(marker_reset)
    assert script.index(marker_reset) < script.index(migration_helper)


def test_remote_deploy_synchronizes_mcp_catalog_before_release_publish() -> None:
    remote_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")
    legacy_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh"
    ).read_text(encoding="utf-8")
    sync_command = (
        "python manage.py sync_ai_capability_catalog --type incremental "
        "--source mcp_tool --fail-on-error"
    )

    assert sync_command in remote_script
    assert remote_script.index(sync_command) < remote_script.index(
        'sh scripts/publish-tui-release.sh "$RELEASE_TAG"'
    )
    assert sync_command in legacy_script
    assert legacy_script.index(sync_command) < legacy_script.index(
        'sh scripts/publish-tui-release.sh "$release_name"'
    )


def test_remote_deploy_removes_duplicate_backup_cron_and_keeps_beat_as_owner() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "BACKUP_CRON_JOB=" not in script
    assert 'grep -v "vps-backup.sh" | crontab -' in script
    assert "Django Beat is the daily owner" in script
    assert "--keep-days 14" not in script
    assert "--keep-days 1" in script


def _extract_powershell_function(script: str, function_name: str) -> str:
    """Extract one balanced PowerShell function for isolated contract testing."""
    signature = f"function {function_name} {{"
    start = script.index(signature)
    opening_brace = script.index("{", start)
    depth = 0
    for index in range(opening_brace, len(script)):
        if script[index] == "{":
            depth += 1
        elif script[index] == "}":
            depth -= 1
            if depth == 0:
                return script[start : index + 1]
    raise AssertionError(f"unterminated {function_name} function")


def _extract_post_deploy_verification_function(script: str) -> str:
    """Extract only the pure post-deploy result boundary, not the deploy script."""
    return _extract_powershell_function(script, "Invoke-PostDeployVerification")


@pytest.mark.parametrize(
    ("raw_digest", "canonical_digest", "error_message"),
    [
        (None, "b" * 64, "raw-file SHA-256 is required"),
        ("a" * 64, "", "canonical-payload SHA-256 is required"),
        ("a" * 63, "b" * 64, "raw-file SHA-256 must be lowercase 64-hex"),
        ("A" * 64, "b" * 64, "raw-file SHA-256 must be lowercase 64-hex"),
        ("a" * 64, "g" * 64, "canonical-payload SHA-256 must be lowercase 64-hex"),
    ],
    ids=[
        "missing-raw",
        "missing-canonical",
        "invalid-raw",
        "uppercase-raw",
        "invalid-canonical",
    ],
)
def test_provider_settings_digest_validator_arguments_fail_closed(
    raw_digest: str | None,
    canonical_digest: str,
    error_message: str,
) -> None:
    """Missing or malformed policy digests must fail before deployment can start."""
    repository_root = Path(__file__).resolve().parents[2]
    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    helper = _extract_powershell_function(wrapper, "Get-ProviderSettingsDigestValidatorArguments")
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this deployment-wrapper contract gate"

    def quote(value: str | None) -> str:
        if value is None:
            return "$null"
        return "'" + value.replace("'", "''") + "'"

    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            helper,
            "try {",
            "    Get-ProviderSettingsDigestValidatorArguments "
            f"-RawFileSha256 {quote(raw_digest)} "
            f"-CanonicalPayloadSha256 {quote(canonical_digest)} | Out-Null",
            "    exit 0",
            "} catch {",
            "    Write-Output $_.Exception.Message",
            "    exit 23",
            "}",
        ]
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 23
    assert error_message in completed.stdout


def test_provider_settings_digest_validator_arguments_forward_exact_values() -> None:
    """The exact supplied hashes and validator option names must be preserved."""
    repository_root = Path(__file__).resolve().parents[2]
    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    helper = _extract_powershell_function(wrapper, "Get-ProviderSettingsDigestValidatorArguments")
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this deployment-wrapper contract gate"
    raw_digest = "a" * 64
    canonical_digest = "b" * 64
    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            helper,
            "$result = @(Get-ProviderSettingsDigestValidatorArguments "
            f"-RawFileSha256 '{raw_digest}' "
            f"-CanonicalPayloadSha256 '{canonical_digest}')",
            "ConvertTo-Json -InputObject $result -Compress",
        ]
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "--expected-provider-settings-raw-file-sha256",
        raw_digest,
        "--expected-provider-settings-canonical-payload-sha256",
        canonical_digest,
    ]


@pytest.mark.parametrize(
    ("verifier_body", "expected_exit_code"),
    [
        ("& $NativePwsh -NoProfile -NonInteractive -Command 'exit 0'", 0),
        ("& $NativePwsh -NoProfile -NonInteractive -Command 'exit 23'", 23),
        ("throw [System.InvalidOperationException]::new('stub failure')", 1),
    ],
    ids=["success", "nonzero-exit", "thrown-exception"],
)
def test_one_click_post_deploy_verification_is_fail_closed(
    verifier_body: str, expected_exit_code: int
) -> None:
    """Run only the isolated result helper with a stubbed verifier scriptblock."""
    repository_root = Path(__file__).resolve().parents[2]
    wrapper = (repository_root / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    assert wrapper.count("Invoke-PostDeployVerification -Verifier {") == 1
    assert "-ExitCode ([ref]$exitCode)" in wrapper
    helper = _extract_post_deploy_verification_function(wrapper)
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this deployment-wrapper CI regression gate"
    native_pwsh_literal = "'" + pwsh.replace("'", "''") + "'"
    verifier_body = verifier_body.replace("$NativePwsh", native_pwsh_literal)

    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "function Write-Err { param([string]$Message) }",
            helper,
            "$global:LASTEXITCODE = 0",
            "$exitCode = 0",
            "Invoke-PostDeployVerification -Verifier {",
            verifier_body,
            "} -ExitCode ([ref]$exitCode)",
            "exit $exitCode",
        ]
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert completed.returncode == expected_exit_code, (
        f"expected isolated verification exit {expected_exit_code}, "
        f"got {completed.returncode}; stdout={completed.stdout!r}; "
        f"stderr={completed.stderr!r}"
    )


@pytest.mark.parametrize(
    "builder_name",
    ["_build_remote_build_script", "_build_remote_git_clone_build_script"],
)
def test_remote_builds_overlap_predeploy_backup_with_image_build(builder_name: str) -> None:
    """The verified pre-deploy backup runs in the background during the image build."""

    script = getattr(remote_build_deploy_vps, builder_name)()

    launch = "PREDEPLOY_BACKUP_PID=$!"
    wait_gate = 'if wait "$PREDEPLOY_BACKUP_PID"; then'
    marker = 'echo "PREDEPLOY_BACKUP_DONE=1"'
    marker_of = 'echo "PREDEPLOY_BACKUP_OF=$PREDEPLOY_BACKUP_SOURCE"'

    assert 'PREDEPLOY_BACKUP="${PREDEPLOY_BACKUP:-0}"' in script
    assert 'if [ "$PREDEPLOY_BACKUP" = "1" ] && [ -L "$TARGET_DIR/current" ]; then' in script
    assert "--keep-days 1 &" in script
    assert launch in script
    assert wait_gate in script
    assert marker in script
    assert marker_of in script
    assert script.index(marker) < script.index(marker_of)
    assert "Pre-deploy backup failed during the image build" in script
    # The backup is launched before the image build and only awaited afterwards,
    # so the backup still precedes any writer stop or migration in the deploy phase.
    docker_build = "DOCKER_BUILDKIT=0 docker --context default build"
    assert script.index(launch) < script.index(docker_build)
    assert script.index(docker_build) < script.index(wait_gate)
    # The completion marker is emitted only after a successful wait, before the
    # build report is written.
    assert script.index(wait_gate) < script.index(marker)
    assert script.index(marker) < script.index('Path(os.environ["BUILD_REPORT_PATH"]).write_text(')


def test_remote_build_cleanup_removes_only_the_current_attempt_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleaning one build must not delete another attempt's report."""
    report_path = remote_build_deploy_vps._remote_build_report_path("20261006120001", "a" * 32)
    commands: list[str] = []

    def fake_run(_ssh: object, command: str, *, timeout: int) -> tuple[int, str, str]:
        assert timeout == 10
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(remote_build_deploy_vps, "_run", fake_run)
    remote_build_deploy_vps._cleanup_remote_build_artifacts(
        object(),
        tag="20261006120001",
        build_report_path=report_path,
        remote_image_tar=None,
        remote_dir="/tmp/build-remote",
        target_dir="/opt/agomtradepro",
        timeout=10,
    )

    assert len(commands) == 1
    assert report_path in commands[0]
    assert "/tmp/agomtradepro-build-report.json" not in commands[0]


def test_remote_deploy_reuses_build_phase_backup_without_repeating_it() -> None:
    """A backup completed during the build phase is not repeated in the deploy phase."""

    script = remote_build_deploy_vps._build_remote_deploy_script()

    skip = 'echo "[WARN] Pre-deploy backup skipped by explicit emergency option" >&2'
    reuse = 'elif [ "$PREDEPLOY_BACKUP_DONE" = "1" ] && [ "$PREDEPLOY_BACKUP_OF" = "$PREVIOUS_RELEASE" ]; then'
    fallback = 'bash "$RELEASE_DIR/scripts/vps-backup.sh"'

    assert 'PREDEPLOY_BACKUP_DONE="${PREDEPLOY_BACKUP_DONE:-0}"' in script
    assert 'PREDEPLOY_BACKUP_OF="${PREDEPLOY_BACKUP_OF:-}"' in script
    assert reuse in script
    assert fallback in script
    assert script.index(skip) < script.index(reuse) < script.index(fallback)
    # Rollback readiness is still armed only after the backup gate.
    assert script.index(fallback) < script.index("ROLLBACK_READY=1")


def test_remote_deploy_runs_static_checks_in_background_with_explicit_wait() -> None:
    """check --deploy and collectstatic overlap the MCP catalog sync and gate publish."""

    script = remote_build_deploy_vps._build_remote_deploy_script()

    launch = "STATIC_CHECKS_PID=$!"
    gate = 'if ! wait "$STATIC_CHECKS_PID"; then'
    publish = 'sh scripts/publish-tui-release.sh "$RELEASE_TAG"'
    sync = "python manage.py sync_ai_capability_catalog --type incremental --source mcp_tool --fail-on-error"
    catalog = "python manage.py initialize_data_center_catalog"

    assert ") &" in script
    assert launch in script
    assert gate in script
    assert 'wait "$STATIC_CHECKS_PID" || true' in script
    # The background block starts only after the catalog sync point, runs while
    # the MCP capability catalog syncs, and is awaited before the TUI publish.
    assert script.index(catalog) < script.index(launch)
    assert script.index(launch) < script.index(sync)
    assert script.index(sync) < script.index(gate)
    assert script.index(gate) < script.index(publish)


def test_remote_deploy_bootstrap_preserves_protected_publication_stop_lines() -> None:
    """Deployment repair may create defaults but must keep both refresh schedules disabled."""

    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert (
        'BOOTSTRAP_CMD="python manage.py bootstrap_cold_start '
        '--preserve-protected-schedules-disabled"'
    ) in script

    project_root = Path(__file__).resolve().parents[2]
    shell_bundle_deploy = (project_root / "scripts" / "deploy-on-vps.sh").read_text(
        encoding="utf-8"
    )
    powershell_bundle_deploy = (project_root / "scripts" / "deploy-on-vps.ps1").read_text(
        encoding="utf-8"
    )

    protected_flag = "--preserve-protected-schedules-disabled"
    assert protected_flag in shell_bundle_deploy
    assert protected_flag in powershell_bundle_deploy


def test_built_image_download_overlaps_deploy_and_is_joined_before_cleanup() -> None:
    """The image tar download runs on a thread during the deploy and joins before cleanup."""

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "from concurrent.futures import Future, ThreadPoolExecutor" in source
    assert "download_pool.submit(" in source
    assert '"PREDEPLOY_BACKUP": _bool_env(' in source
    assert '"PREDEPLOY_BACKUP_DONE": _bool_env(predeploy_backup_done)' in source
    assert '"PREDEPLOY_BACKUP_OF": predeploy_backup_of,' in source
    assert source.index('if line.startswith("PREDEPLOY_BACKUP_OF="):') < source.index(
        '"PREDEPLOY_BACKUP_OF": predeploy_backup_of,'
    )
    assert source.index('if line.startswith("PREDEPLOY_BACKUP_DONE="):') < source.index(
        '"PREDEPLOY_BACKUP_DONE": _bool_env(predeploy_backup_done)'
    )
    deploy_phase = 'deploy_cmd = f"{deploy_exports} bash -lc'
    join = "download_future.result()"
    report_download = "if args.download_report and report_path:"
    cleanup_call = "            _cleanup_remote_build_artifacts("
    assert source.index("download_pool.submit(") < source.index(deploy_phase)
    assert source.index(deploy_phase) < source.index(join) < source.index(report_download)
    assert source.index(join) < source.index(cleanup_call)


def test_download_and_package_built_image_uses_dedicated_ssh_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The worker downloads over its own SSH connection and always closes it."""

    calls: dict[str, Any] = {}

    class FakeSFTP:
        closed = False

        def get(self, remote: str, local: str) -> None:
            calls["get"] = (remote, local)

        def close(self) -> None:
            self.closed = True

    class FakeSSH:
        def __init__(self) -> None:
            self.sftp = FakeSFTP()
            self.closed = False

        def open_sftp(self) -> FakeSFTP:
            return self.sftp

        def close(self) -> None:
            self.closed = True

    fake_ssh = FakeSSH()

    def fake_connect(
        *, host: str, port: int, username: str, password: str, timeout: int
    ) -> FakeSSH:
        calls["connect"] = (host, port, username, password, timeout)
        return fake_ssh

    def fake_bundle(**kwargs: Any) -> Path:
        calls["bundle"] = kwargs
        return tmp_path / "bundle.zip"

    monkeypatch.setattr(remote_build_deploy_vps, "_ssh_connect", fake_connect)
    monkeypatch.setattr(remote_build_deploy_vps, "_create_local_runtime_bundle", fake_bundle)

    image_path = tmp_path / "dist" / "agomtradepro-web-20240101000000.tar"
    result = remote_build_deploy_vps._download_and_package_built_image(
        host="vps.example",
        port=22,
        username="root",
        password="secret",
        timeout=60,
        remote_image_tar="/tmp/agomtradepro-web-20240101000000.tar",
        local_image_path=image_path,
        project_root=tmp_path,
        tag="20240101000000",
        include_sqlite=False,
        sqlite_file=None,
    )

    assert result == tmp_path / "bundle.zip"
    assert calls["connect"] == ("vps.example", 22, "root", "secret", 60)
    assert calls["get"] == ("/tmp/agomtradepro-web-20240101000000.tar", str(image_path))
    assert calls["bundle"]["local_image_path"] == image_path
    assert fake_ssh.closed
    assert fake_ssh.sftp.closed
    assert image_path.parent.is_dir()
