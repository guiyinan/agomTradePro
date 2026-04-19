#!/usr/bin/env python
"""
Start a Django live server, run a pytest suite against it, and verify it really executed.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_MODULE = "core.settings.development_sqlite"
DEFAULT_HEALTH_PATH = "/account/login/"
DEFAULT_HEALTH_TIMEOUT = 120
DEFAULT_STARTUP_DELAY = 0.5


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pytest suites against an explicitly managed Django live server."
    )
    parser.add_argument("--suite-name", required=True, help="Logical suite name for logs and summaries.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Target base URL passed to pytest.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host used when starting Django runserver.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port used when starting Django runserver. Defaults to the port in --base-url.",
    )
    parser.add_argument(
        "--settings-module",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE),
        help="DJANGO_SETTINGS_MODULE used for the managed runserver.",
    )
    parser.add_argument(
        "--health-path",
        default=DEFAULT_HEALTH_PATH,
        help="HTTP path used to verify the live server is ready.",
    )
    parser.add_argument(
        "--health-timeout",
        type=int,
        default=DEFAULT_HEALTH_TIMEOUT,
        help="Seconds to wait for the live server to become reachable.",
    )
    parser.add_argument(
        "--junitxml",
        required=True,
        help="JUnit XML output path. Required so execution counts can be validated.",
    )
    parser.add_argument(
        "--min-tests",
        type=int,
        default=1,
        help="Minimum number of collected tests required for the suite to count as executed.",
    )
    parser.add_argument(
        "--skip-server",
        action="store_true",
        help="Do not manage Django runserver. Still performs live-server reachability checks.",
    )
    parser.add_argument(
        "--server-log",
        help="Optional file path for server stdout/stderr logs.",
    )
    parser.add_argument(
        "--pytest-log",
        help="Optional file path for pytest stdout/stderr logs.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional environment variable passed to both runserver and pytest.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to pytest after `--`.",
    )
    return parser.parse_args()


def _normalize_pytest_args(pytest_args: Sequence[str]) -> list[str]:
    args = list(pytest_args)
    if args and args[0] == "--":
        args = args[1:]
    return args


def _resolve_port(base_url: str, explicit_port: int | None) -> int:
    if explicit_port is not None:
        return explicit_port
    parsed = urlparse(base_url)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def _build_env(settings_module: str, pairs: Sequence[str]) -> dict[str, str]:
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = settings_module
    env["PYTHONUNBUFFERED"] = "1"
    env["AGOM_PLAYWRIGHT_REQUIRE_SERVER"] = "1"
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Invalid --env value {item!r}; expected KEY=VALUE.")
        key, value = item.split("=", 1)
        env[key] = value
    return env


def _wait_for_server(base_url: str, health_path: str, timeout_seconds: int) -> None:
    health_url = urljoin(f"{base_url.rstrip('/')}/", health_path.lstrip("/"))
    deadline = time.time() + timeout_seconds
    last_error = "server did not become reachable"

    while time.time() < deadline:
        try:
            with urlopen(health_url, timeout=5) as response:
                status_code = getattr(response, "status", response.getcode())
                if 200 <= status_code < 400:
                    print(f"[live-server] Ready: {health_url} ({status_code})")
                    return
                last_error = f"unexpected status {status_code} from {health_url}"
        except HTTPError as exc:
            if 200 <= exc.code < 400:
                print(f"[live-server] Ready: {health_url} ({exc.code})")
                return
            last_error = f"HTTP {exc.code} from {health_url}"
        except URLError as exc:
            last_error = str(exc.reason)
        except OSError as exc:
            last_error = str(exc)

        time.sleep(DEFAULT_STARTUP_DELAY)

    raise RuntimeError(f"Live server was not reachable at {health_url}: {last_error}")


def _start_server(
    host: str,
    port: int,
    env: dict[str, str],
    log_path: Path | None,
) -> tuple[subprocess.Popen[str], object | None]:
    command = [
        sys.executable,
        "manage.py",
        "runserver",
        f"{host}:{port}",
        "--noreload",
        "--nothreading",
    ]
    stdout_target: object
    server_log_handle: object | None = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        server_log_handle = log_path.open("w", encoding="utf-8")
        stdout_target = server_log_handle
    else:
        stdout_target = subprocess.DEVNULL

    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdout=stdout_target,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, server_log_handle


def _stop_server(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "nt":
        process.send_signal(signal.SIGTERM)
    else:
        process.kill()
    process.wait(timeout=10)


def _contains_option(args: Sequence[str], option_name: str) -> bool:
    return any(arg == option_name or arg.startswith(f"{option_name}=") for arg in args)


def _run_pytest(
    pytest_args: Sequence[str],
    *,
    base_url: str,
    junitxml: Path,
    env: dict[str, str],
    log_path: Path | None,
) -> int:
    junitxml.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", *pytest_args]

    if not _contains_option(command, "--base-url"):
        command.append(f"--base-url={base_url}")
    if not _contains_option(command, "--junitxml"):
        command.append(f"--junitxml={junitxml}")

    print("[pytest] Running:")
    print(" ".join(command))

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                handle.write(line)
            return process.wait()

    return subprocess.call(command, cwd=REPO_ROOT, env=env)


def _parse_junit_summary(junitxml: Path) -> dict[str, int]:
    if not junitxml.exists():
        raise RuntimeError(f"JUnit XML was not generated: {junitxml}")

    root = ET.parse(junitxml).getroot()
    testcases = list(root.iter("testcase"))
    skipped = sum(1 for testcase in testcases if testcase.find("skipped") is not None)
    failures = sum(1 for testcase in testcases if testcase.find("failure") is not None)
    errors = sum(1 for testcase in testcases if testcase.find("error") is not None)
    passed = max(len(testcases) - skipped - failures - errors, 0)
    executed = len(testcases) - skipped
    return {
        "total": len(testcases),
        "passed": passed,
        "skipped": skipped,
        "failures": failures,
        "errors": errors,
        "executed": executed,
    }


def _validate_summary(suite_name: str, summary: dict[str, int], min_tests: int) -> None:
    total = summary["total"]
    executed = summary["executed"]
    if total < min_tests:
        raise RuntimeError(
            f"{suite_name} collected only {total} tests, below required minimum {min_tests}."
        )
    if executed <= 0:
        raise RuntimeError(
            f"{suite_name} did not execute any tests; all collected cases were skipped."
        )


def main() -> int:
    args = _parse_args()
    pytest_args = _normalize_pytest_args(args.pytest_args)
    if not pytest_args:
        print("No pytest arguments supplied. Pass the suite after `--`.", file=sys.stderr)
        return 2

    port = _resolve_port(args.base_url, args.port)
    junitxml = (REPO_ROOT / args.junitxml).resolve()
    server_log = (REPO_ROOT / args.server_log).resolve() if args.server_log else None
    pytest_log = (REPO_ROOT / args.pytest_log).resolve() if args.pytest_log else None
    env = _build_env(args.settings_module, args.env)

    server_process: subprocess.Popen[str] | None = None
    server_log_handle = None
    try:
        if not args.skip_server:
            print(
                f"[live-server] Starting Django server for {args.suite_name} at "
                f"{args.host}:{port} with {args.settings_module}"
            )
            server_process, server_log_handle = _start_server(args.host, port, env, server_log)

        _wait_for_server(args.base_url, args.health_path, args.health_timeout)
        exit_code = _run_pytest(
            pytest_args,
            base_url=args.base_url,
            junitxml=junitxml,
            env=env,
            log_path=pytest_log,
        )
        summary = _parse_junit_summary(junitxml)
        _validate_summary(args.suite_name, summary, args.min_tests)
        print(
            "[pytest] Summary: "
            f"total={summary['total']} executed={summary['executed']} "
            f"passed={summary['passed']} skipped={summary['skipped']} "
            f"failures={summary['failures']} errors={summary['errors']}"
        )
        return exit_code
    except Exception as exc:
        print(f"[live-server] {args.suite_name} failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _stop_server(server_process)
        if server_log_handle is not None:
            server_log_handle.close()


if __name__ == "__main__":
    sys.exit(main())
