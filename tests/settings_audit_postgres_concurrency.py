"""Explicitly isolated PostgreSQL settings for audit concurrency evidence.

This module is intentionally not selected by ``pytest.ini``.  It must be
selected explicitly together with a disposable, dedicated PostgreSQL URL.
The URL is never read from ``DATABASE_URL`` so production configuration cannot
silently become a concurrency-test target.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("PostgreSQL audit evidence is denied: " f"{name} must be set explicitly")
    return value


def _database_config(database_url: str) -> dict[str, object]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(
            "PostgreSQL audit evidence is denied: "
            "AGOM_AUDIT_PG_TEST_DATABASE_URL must use postgres:// or postgresql://"
        )
    if not parsed.hostname or not parsed.path or not parsed.username:
        raise RuntimeError(
            "PostgreSQL audit evidence is denied: "
            "the dedicated URL must include host, database and user"
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("PostgreSQL audit evidence is denied: URL port is invalid") from error

    database_name = unquote(parsed.path.removeprefix("/"))
    database_name_lower = database_name.lower()
    if "audit" not in database_name_lower or "test" not in database_name_lower:
        raise RuntimeError(
            "PostgreSQL audit evidence is denied: database name must contain "
            "both 'audit' and 'test'"
        )
    unsafe_tokens = ("prod", "production", "primary", "live")
    if any(token in database_name_lower for token in unsafe_tokens):
        raise RuntimeError("PostgreSQL audit evidence is denied: production-like database name")
    host_lower = parsed.hostname.lower()
    allowed_local_hosts = {"localhost", "127.0.0.1", "::1", "postgres", "postgresql", "db"}
    if host_lower not in allowed_local_hosts:
        raise RuntimeError(
            "PostgreSQL audit evidence is denied: host must be a local or test-service host"
        )
    if any(token in host_lower for token in unsafe_tokens):
        raise RuntimeError("PostgreSQL audit evidence is denied: production-like database host")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_name,
        "USER": unquote(parsed.username),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(port) if port is not None else "",
        "CONN_MAX_AGE": 0,
        "TEST": {"NAME": f"test_{database_name}"},
    }


if os.environ.get("AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE", "").strip() != "1":
    raise RuntimeError(
        "PostgreSQL audit evidence is denied: set " "AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE=1 to opt in"
    )

_DATABASE_URL = _required_environment("AGOM_AUDIT_PG_TEST_DATABASE_URL")

SECRET_KEY = "audit-postgres-concurrency-evidence"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.auditsystemapp.apps.AuditSystemTestConfig",
]
DATABASES = {"default": _database_config(_DATABASE_URL)}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"audit": None}
