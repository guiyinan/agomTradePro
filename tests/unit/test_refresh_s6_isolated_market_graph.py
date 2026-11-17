"""Isolated S6 current-market refresh launcher contracts."""

import os
import secrets
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts import refresh_s6_isolated_market_graph as launcher


def test_require_isolated_target_session_returns_resolved_date() -> None:
    """The launcher binds the exact ready session selected by the calendar resolver."""

    now = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)

    resolved = launcher._require_isolated_target_session(
        now,
        resolver=lambda _now: date(2026, 10, 13),
    )

    assert resolved == date(2026, 10, 13)


def test_require_isolated_target_session_blocks_without_provider_evidence() -> None:
    """The launcher stops before task execution when no ready session exists."""

    now = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="S6_GRAPH_REFRESH_TARGET_SESSION_UNAVAILABLE"):
        launcher._require_isolated_target_session(now, resolver=lambda _now: None)


def test_isolated_refresh_uses_target_session_capable_provider_route() -> None:
    """An intraday rehearsal must not source yesterday from a live-only quote route."""

    assert launcher._isolated_task_kwargs() == {"source": "tushare"}


def test_cold_startup_uses_default_authentication_without_db_or_http(tmp_path: Path) -> None:
    """Execute the real startup prefix in a fresh interpreter before any task import."""
    import django

    root = Path(__file__).resolve().parents[2]
    dependency_root = Path(django.__file__).resolve().parent.parent
    child = r"""
import ast, importlib.util, socket, sys
from pathlib import Path
from types import SimpleNamespace
root = Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
attempts = []
def deny(*args, **kwargs):
    attempts.append(True)
    raise RuntimeError('COLD_STARTUP_IO_FORBIDDEN')
# Windows reactors use local socketpairs during setup; block HTTP transports
# and outbound create_connection while retaining their internal wakeup pipes.
import http.client
import requests
socket.create_connection = deny
requests.Session.send = deny
http.client.HTTPConnection.connect = deny
http.client.HTTPSConnection.connect = deny
from django.db.backends.base.base import BaseDatabaseWrapper
BaseDatabaseWrapper.ensure_connection = deny
BaseDatabaseWrapper.connect = deny
BaseDatabaseWrapper.cursor = deny
path = root / 'scripts/refresh_s6_isolated_market_graph.py'
spec = importlib.util.spec_from_file_location('cold_graph_launcher', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._CANDIDATE_SOURCE = root
module._validate_runtime_identity = lambda *_args: None
tree = ast.parse(path.read_text(encoding='utf-8'))
body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run').body
setup_index = next(i for i,n in enumerate(body) if isinstance(n, ast.Expr)
    and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
    and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == 'django'
    and n.value.func.attr == 'setup')
capture_index = next(i for i,n in enumerate(body) if isinstance(n, ast.ImportFrom)
    and n.module == 'apps.data_center.infrastructure.rehearsal_http_capture')
prefix = ast.Module(body=body[:max(setup_index,capture_index)+1], type_ignores=[])
assert not any(isinstance(n, ast.ImportFrom) and n.module == 'apps.data_center.application.tasks'
    for n in ast.walk(prefix))
namespace = module.__dict__
namespace.update(args=SimpleNamespace(), environ={})
exec(compile(prefix, str(path), 'exec'), namespace)
from django.apps import apps
from django.conf import settings
from rest_framework.settings import api_settings
assert apps.ready
assert settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] == [
    'rest_framework.authentication.SessionAuthentication',
    'apps.account.interface.authentication.TerminalInternalAuthentication',
    'apps.account.interface.authentication.MultiTokenAuthentication',
]
assert len(api_settings.DEFAULT_AUTHENTICATION_CLASSES) == 3
assert namespace['RehearsalHttpCapture'].__module__ == 'apps.data_center.infrastructure.rehearsal_http_capture'
assert not attempts
print('COLD_GRAPH_STARTUP_OK')
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="core.settings.production",
        DATABASE_URL="postgresql://startup:unused@127.0.0.1:1/startup",
        SECRET_KEY=secrets.token_hex(40),
        ALLOWED_HOSTS="localhost",
        AGOM_LOG_DIR=str(tmp_path / "logs"),
        CELERY_BROKER_URL="memory://",
        REDIS_URL="",
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", child, str(root), str(dependency_root)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLD_GRAPH_STARTUP_OK" in result.stdout
