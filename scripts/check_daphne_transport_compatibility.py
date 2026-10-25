"""Check pinned Daphne HTTP, TLS, WebSocket, and secure WebSocket transports."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.metadata
import importlib.util
import ipaddress
import json
import os
import platform
import re
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, cast

HOST = "127.0.0.1"
EXPECTED_PYTHON = "3.11.14"
DISTRIBUTIONS = (
    ("Twisted", "twisted"),
    ("djangorestframework", "rest_framework"),
    ("Daphne", "daphne"),
    ("channels", "channels"),
    ("zope.interface", "zope.interface"),
    ("pyOpenSSL", "OpenSSL"),
    ("cryptography", "cryptography"),
    ("websockets", "websockets"),
)
PROTOCOLS = ("http", "https", "ws", "wss")
TARGET_VERSIONS = {"twisted": "26.10.0rc1", "djangorestframework": "3.18.3"}
PIN_LINE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?:\s*;[^\r\n]+)?\s*$"
)
COMMIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]
_lazy_app: ASGIApp | None = None


class CompatibilityError(RuntimeError):
    """Stable non-sensitive failure code."""

    def __init__(self, code: str) -> None:
        """Store a safe code without environment values."""
        super().__init__(code)
        self.code = code


class _BinaryLogStream(Protocol):
    """Methods shared by binary temporary streams on Windows and Linux."""

    def flush(self) -> None:
        """Flush buffered log bytes."""
        ...

    def seek(self, offset: int, whence: int = 0) -> int:
        """Move to a byte position in the temporary stream."""
        ...

    def read(self, size: int = -1) -> bytes:
        """Read the retained binary log content."""
        ...


def _name(value: str) -> str:
    """Normalize a distribution name for lock comparison."""
    return re.sub(r"[-_.]+", "-", value).lower()


REQUIRED_PINS = frozenset(_name(name) for name, _module in DISTRIBUTIONS)


def _parse_expected_lock(text: str) -> dict[str, str]:
    """Read unique exact pins from pip-compile output and require all targets."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN_LINE.fullmatch(line)
        if match is None:
            raise CompatibilityError("LOCK_LINE_INVALID")
        key = _name(match.group(1))
        if key in pins:
            raise CompatibilityError("LOCK_DUPLICATE_PIN")
        pins[key] = match.group(2)
    if REQUIRED_PINS.difference(pins):
        raise CompatibilityError("LOCK_REQUIRED_PIN_MISSING")
    if any(pins.get(name) != version for name, version in TARGET_VERSIONS.items()):
        raise CompatibilityError("LOCK_TARGET_VERSION_MISMATCH")
    return pins


def _validate_locked_versions(expected: Mapping[str, str], actual: Mapping[str, str]) -> None:
    """Require installed Twisted, DRF, and transport packages to match the lock."""
    installed = {_name(key): value for key, value in actual.items()}
    if any(installed.get(key) != expected.get(key) for key in REQUIRED_PINS):
        raise CompatibilityError("INSTALLED_VERSION_DIFFERS_FROM_LOCK")


def _is_inside_prefix(path: Path, prefix: Path) -> bool:
    """Return whether an existing resolved path is within the active venv."""
    try:
        path.resolve(strict=True).relative_to(prefix.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _package_identity(name: str, module: str, expected: str, prefix: Path) -> dict[str, object]:
    """Read one installed distribution version and module/metadata location."""
    dist = importlib.metadata.distribution(name)
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise CompatibilityError("PACKAGE_MODULE_NOT_FOUND")
    module_path = Path(spec.origin).resolve(strict=True)
    metadata_root = Path(str(dist.locate_file(""))).resolve(strict=True)
    return {
        "expected_version": expected,
        "installed_version": dist.version,
        "module_path": str(module_path),
        "metadata_root": str(metadata_root),
        "module_in_prefix": _is_inside_prefix(module_path, prefix),
        "metadata_in_prefix": _is_inside_prefix(metadata_root, prefix),
    }


def _assert_echo(actual: bytes | str, expected: bytes | str, protocol: str) -> None:
    """Require an exact byte or text echo for one protocol."""
    if actual != expected:
        raise CompatibilityError(f"{protocol.upper()}_ECHO_MISMATCH")


def _success_eligible(checks: Mapping[str, bool], cleanup_ok: bool, cancelled: bool) -> bool:
    """Pass only when all four transports, cleanup, and cancellation checks pass."""
    return (
        not cancelled
        and cleanup_ok
        and set(checks) == set(PROTOCOLS)
        and all(checks[name] is True for name in PROTOCOLS)
    )


def _check_cancelled(signals: Sequence[int]) -> None:
    """Convert a recorded CI cancellation at a safe bounded-operation boundary."""
    if signals:
        raise CompatibilityError("RUN_CANCELLED")


async def _http_echo(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Echo one HTTP request body using only the ASGI protocol boundary."""
    body_parts: list[bytes] = []
    while True:
        event = await receive()
        if event.get("type") != "http.request":
            return
        part = event.get("body", b"")
        if isinstance(part, bytes):
            body_parts.append(part)
        if not event.get("more_body", False):
            break
    status = 200 if scope.get("path") == "/transport/http/" else 404
    body = b"".join(body_parts) if status == 200 else b""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/octet-stream")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _websocket_echo(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Accept and echo text or bytes on one synthetic ASGI WebSocket route."""
    if scope.get("path") != "/transport/ws/":
        await send({"type": "websocket.close", "code": 1008})
        return
    event = await receive()
    if event.get("type") != "websocket.connect":
        return
    await send({"type": "websocket.accept"})
    while True:
        event = await receive()
        if event.get("type") == "websocket.disconnect":
            return
        text = event.get("text")
        data = event.get("bytes")
        if isinstance(text, str):
            await send({"type": "websocket.send", "text": text})
        elif isinstance(data, bytes):
            await send({"type": "websocket.send", "bytes": data})
        else:
            await send({"type": "websocket.close", "code": 1003})
            return


def _build_application() -> ASGIApp:
    """Load Channels' router at the typed third-party boundary, without Django setup."""
    routing = import_module("channels.routing")
    router_type = cast(Callable[[dict[str, ASGIApp]], ASGIApp], routing.ProtocolTypeRouter)
    return router_type({"http": _http_echo, "websocket": _websocket_echo})


async def application(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Lazily expose the synthetic Channels transport app to Daphne."""
    global _lazy_app
    if _lazy_app is None:
        _lazy_app = _build_application()
    await _lazy_app(scope, receive, send)


def _port() -> int:
    """Return one available loopback TCP port."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _tls_files(directory: Path, redactions: list[bytes]) -> tuple[Path, Path, Path]:
    """Create a local CA and IP-SAN certificate; keep the server key mode 0600."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_key, key = (rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2))
    now = datetime.now(UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Native Daphne check CA")])
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (directory / n for n in ("ca.pem", "server.pem", "server.key"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    redactions.append(key_bytes)
    key_path.write_bytes(key_bytes)
    os.chmod(key_path, 0o600)
    return ca_path, cert_path, key_path


def _wait_listener(
    server: subprocess.Popen[bytes], port: int, deadline: float, cancelled: Sequence[int]
) -> None:
    """Wait at most 25 seconds for each loopback listener."""
    while time.monotonic() < deadline:
        _check_cancelled(cancelled)
        if server.poll() is not None:
            raise CompatibilityError("DAPHNE_EXITED_BEFORE_LISTENING")
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise CompatibilityError("DAPHNE_STARTUP_TIMEOUT")


def _http_probe(
    port: int, secure: bool, context: ssl.SSLContext | None, redactions: list[bytes]
) -> dict[str, object]:
    """Verify a bounded HTTP or strictly verified HTTPS body echo."""
    challenge = secrets.token_hex(16).encode("ascii")
    redactions.append(challenge)
    if secure and context is None:
        raise CompatibilityError("TLS_CONTEXT_MISSING")
    conn: http.client.HTTPConnection = (
        http.client.HTTPSConnection(HOST, port, context=context, timeout=5)
        if secure
        else http.client.HTTPConnection(HOST, port, timeout=5)
    )
    try:
        conn.request(
            "POST",
            "/transport/http/",
            body=challenge,
            headers={"Content-Type": "application/octet-stream"},
        )
        response = conn.getresponse()
        body = response.read()
        if (
            response.status != 200
            or response.getheader("content-type") != "application/octet-stream"
        ):
            raise CompatibilityError("HTTP_RESPONSE_INVALID")
        _assert_echo(body, challenge, "https" if secure else "http")
        return {"status": response.status, "echo_sha256": hashlib.sha256(body).hexdigest()}
    finally:
        conn.close()


def _websocket_probe(
    port: int, secure: bool, context: ssl.SSLContext | None, redactions: list[bytes]
) -> dict[str, str]:
    """Verify one bounded bidirectional WS or strictly verified WSS echo."""
    from websockets.sync.client import connect

    challenge = secrets.token_hex(16)
    redactions.append(challenge.encode("ascii"))
    if secure and context is None:
        raise CompatibilityError("TLS_CONTEXT_MISSING")
    scheme = "wss" if secure else "ws"
    options: dict[str, Any] = {"open_timeout": 2, "close_timeout": 1, "proxy": None}
    if secure:
        options["ssl"] = context
    with connect(f"{scheme}://{HOST}:{port}/transport/ws/", **options) as ws:
        ws.send(challenge)
        echo = ws.recv(timeout=2)
    if not isinstance(echo, str):
        raise CompatibilityError("WEBSOCKET_RESPONSE_INVALID")
    _assert_echo(echo, challenge, scheme)
    return {"echo_sha256": hashlib.sha256(echo.encode("ascii")).hexdigest()}


def _signal_owned_group(pid: int, *, force: bool) -> None:
    """Signal the Linux process group created for this check's Daphne child."""
    if sys.platform != "linux":
        raise OSError("Linux process groups are required")
    os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)


def _termination_signals() -> tuple[int, ...]:
    """Return signals available on the host while preserving Linux cancellation."""
    values = [int(signal.SIGINT), int(signal.SIGTERM)]
    if sys.platform == "linux":
        values.extend((int(signal.SIGHUP), int(signal.SIGQUIT)))
    return tuple(values)


def _stop_server(server: subprocess.Popen[bytes] | None) -> dict[str, object]:
    """TERM the owned process group for 8s, then KILL for 3s and reap it."""
    if server is None or server.returncode is not None:
        return {
            "attempted": server is not None,
            "term_sent": False,
            "kill_sent": False,
            "reaped": True,
            "returncode": server.returncode if server else None,
            "ok": True,
        }
    term_ok = True
    kill_ok = True
    kill_sent = False
    try:
        _signal_owned_group(server.pid, force=False)
    except ProcessLookupError:
        pass
    except OSError:
        term_ok = False
        try:
            server.terminate()
        except OSError:
            pass
    try:
        server.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            _signal_owned_group(server.pid, force=True)
            kill_sent = True
        except ProcessLookupError:
            kill_sent = True
        except OSError:
            kill_ok = False
            try:
                server.kill()
                kill_sent = True
            except OSError:
                pass
        try:
            server.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        term_ok = False
        kill_ok = False
        try:
            _signal_owned_group(server.pid, force=True)
            kill_sent = True
        except (OSError, ProcessLookupError):
            pass
        try:
            server.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
    reaped = server.returncode is not None
    return {
        "attempted": True,
        "term_sent": term_ok,
        "kill_sent": kill_sent,
        "reaped": reaped,
        "returncode": server.returncode,
        "ok": reaped and term_ok and kill_ok,
    }


def _logs(stream: _BinaryLogStream, markers: Sequence[bytes]) -> bytes:
    """Read a temporary Daphne log after removing secret markers."""
    stream.flush()
    stream.seek(0)
    data = stream.read()
    for marker in markers:
        if marker:
            data = data.replace(marker, b"[REDACTED]")
    return data


def _output_dir(path: Path) -> Path:
    """Create or require an empty mode-0700 private report directory."""
    if path.is_symlink():
        raise CompatibilityError("OUTPUT_DIRECTORY_NOT_PRIVATE_AND_EMPTY")
    if not path.exists():
        path.mkdir(mode=0o700)
    if not path.is_dir() or any(path.iterdir()):
        raise CompatibilityError("OUTPUT_DIRECTORY_NOT_PRIVATE_AND_EMPTY")
    os.chmod(path, 0o700)
    return path.resolve(strict=True)


def _run(lock_path: Path, output: Path) -> int:
    """Validate native pins, exercise four real transports, and record safe evidence."""
    started = time.monotonic()
    commit = os.environ.get("DEPENDENCY_PREFLIGHT_SOURCE_SHA", "")
    github_sha = os.environ.get("GITHUB_SHA", "")
    report: dict[str, object] = {
        "schema": "daphne.transport-compatibility.v1",
        "status": "failed",
        "scope": "synthetic ASGI transport only; no project application, authentication, or database validation",
        "candidate_sha": commit or None,
        "candidate_sha_env": "DEPENDENCY_PREFLIGHT_SOURCE_SHA",
        "python": platform.python_version(),
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "locked_versions": {},
        "installed_packages": {},
        "checks": dict.fromkeys(PROTOCOLS, False),
    }
    checks = dict.fromkeys(PROTOCOLS, False)
    packages: dict[str, dict[str, object]] = {}
    probes: dict[str, dict[str, object]] = {}
    cancellations: list[int] = []
    collect_cancellation = True
    redactions: list[bytes] = []
    server: subprocess.Popen[bytes] | None = None
    tls_temp: tempfile.TemporaryDirectory[str] | None = None
    stdout = tempfile.TemporaryFile(mode="w+b")
    stderr = tempfile.TemporaryFile(mode="w+b")
    prior: dict[int, Callable[[int, FrameType | None], object] | int | None] = {}
    stage = "environment"

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        """Record CI cancellation without interrupting bounded subprocess cleanup."""
        if collect_cancellation and not cancellations:
            cancellations.append(signum)

    try:
        for sig in _termination_signals():
            prior[sig] = signal.signal(sig, on_signal)
        _check_cancelled(cancellations)
        if sys.platform != "linux" or platform.python_version() != EXPECTED_PYTHON:
            raise CompatibilityError("NATIVE_PYTHON_RUNTIME_MISMATCH")
        if COMMIT_SHA.fullmatch(commit) is None or (github_sha and commit != github_sha):
            raise CompatibilityError("SOURCE_SHA_MISSING_OR_INVALID")
        stage = "lock"
        if lock_path.is_symlink() or not lock_path.is_file():
            raise CompatibilityError("EXPECTED_LOCK_INVALID")
        raw_lock = lock_path.read_bytes()
        report["lock_sha256"] = hashlib.sha256(raw_lock).hexdigest()
        pins = _parse_expected_lock(raw_lock.decode("utf-8"))
        report["locked_versions"] = {key: pins[key] for key in sorted(REQUIRED_PINS)}
        _check_cancelled(cancellations)
        stage = "installed_packages"
        prefix = Path(sys.prefix).resolve(strict=True)
        for name, module in DISTRIBUTIONS:
            key = _name(name)
            identity = _package_identity(name, module, pins[key], prefix)
            packages[key] = identity
            if (
                identity["installed_version"] != pins[key]
                or not identity["module_in_prefix"]
                or not identity["metadata_in_prefix"]
            ):
                raise CompatibilityError("INSTALLED_PACKAGE_IDENTITY_MISMATCH")
        _validate_locked_versions(
            pins, {key: str(value["installed_version"]) for key, value in packages.items()}
        )
        report["installed_packages"] = packages
        _check_cancelled(cancellations)
        stage = "tls_material"
        tls_temp = tempfile.TemporaryDirectory(prefix="daphne-transport-")
        tls_dir = Path(tls_temp.name)
        os.chmod(tls_dir, 0o700)
        ca, cert, key = _tls_files(tls_dir, redactions)
        _check_cancelled(cancellations)
        http_port, tls_port = _port(), _port()
        while http_port == tls_port:
            tls_port = _port()
        endpoints = (
            f"tcp:port={http_port}:interface={HOST}",
            f"ssl:port={tls_port}:interface={HOST}:privateKey={key}:certKey={cert}",
        )
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        command = [
            sys.executable,
            "-B",
            "-u",
            "-m",
            "daphne",
            "-e",
            endpoints[0],
            "-e",
            endpoints[1],
            "scripts.check_daphne_transport_compatibility:application",
        ]
        stage = "server_startup"
        server = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )
        report["server_pid"] = server.pid
        report["ports"] = {"http": http_port, "tls": tls_port}
        _check_cancelled(cancellations)
        deadline = time.monotonic() + 25
        _wait_listener(server, http_port, deadline, cancellations)
        _wait_listener(server, tls_port, deadline, cancellations)
        trust = ssl.create_default_context(cafile=str(ca))
        if not trust.check_hostname or trust.verify_mode != ssl.CERT_REQUIRED:
            raise CompatibilityError("TLS_VERIFICATION_NOT_STRICT")
        for name, port, secure in (("http", http_port, False), ("https", tls_port, True)):
            stage = name
            result = _http_probe(port, secure, trust if secure else None, redactions)
            _check_cancelled(cancellations)
            checks[name] = True
            probes[name] = result
        for name, port, secure in (("ws", http_port, False), ("wss", tls_port, True)):
            stage = name
            result = _websocket_probe(port, secure, trust if secure else None, redactions)
            _check_cancelled(cancellations)
            checks[name] = True
            probes[name] = result
    except BaseException as exc:
        report["failed_stage"] = stage
        report["error_type"] = type(exc).__name__
        report["error_code"] = exc.code if isinstance(exc, CompatibilityError) else "CHECK_FAILED"
    finally:
        cleanup = _stop_server(server)
        tls_ok = True
        if tls_temp is not None:
            try:
                tls_temp.cleanup()
            except OSError:
                tls_ok = False
        collect_cancellation = False
        out_log, err_log = _logs(stdout, redactions), _logs(stderr, redactions)
        for name, data in (("daphne.stdout.log", out_log), ("daphne.stderr.log", err_log)):
            (output / name).write_bytes(data)
            os.chmod(output / name, 0o600)
        report.update(
            {
                "installed_packages": packages,
                "checks": checks,
                "probe_results": probes,
                "server_cleanup": cleanup,
                "tls_material_cleanup": {"ok": tls_ok},
                "cancelled": bool(cancellations),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "server_logs": {
                    n: {"path": n, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)}
                    for n, d in (("daphne.stdout.log", out_log), ("daphne.stderr.log", err_log))
                },
            }
        )
        if cancellations:
            report.setdefault("failed_stage", stage)
            report.setdefault("error_code", "RUN_CANCELLED")
        if _success_eligible(checks, bool(cleanup.get("ok")) and tls_ok, bool(cancellations)):
            report["status"] = "passed"
        stdout.close()
        stderr.close()
        try:
            result_path = output / "report.json"
            result_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.chmod(result_path, 0o600)
        finally:
            for sig, handler in prior.items():
                signal.signal(sig, handler)
    print(
        json.dumps(
            {
                "status": report["status"],
                "failed_stage": report.get("failed_stage"),
                "error_code": report.get("error_code"),
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the native transport check from an exact lock and empty report directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = _output_dir(args.output_dir)
    except CompatibilityError as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code}))
        return 2
    return _run(args.expected_lock, output)


if __name__ == "__main__":
    raise SystemExit(main())
