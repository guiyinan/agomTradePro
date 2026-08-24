"""Opt-in isolated PostgreSQL settings for owner/tenant authority races.

The component harness refuses production-like hosts and database names.  It
uses an in-memory SQLite fallback only so an unconfigured run can report an
explicit skip; SQLite is never reported as PostgreSQL evidence.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

_FLAG = "AGOM_OWNER_TENANT_AUTHORITY_PG_CONCURRENCY_EVIDENCE"
_URL = "AGOM_OWNER_TENANT_AUTHORITY_PG_TEST_DATABASE_URL"


def _database_config(database_url: str) -> dict[str, object]:
    """Build a PostgreSQL config after rejecting non-disposable targets."""

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(f"{_URL} must use postgres:// or postgresql://")
    if not parsed.hostname or not parsed.path or not parsed.username:
        raise RuntimeError(f"{_URL} must include host, database and user")
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"{_URL} has an invalid port") from error
    database_name = unquote(parsed.path.removeprefix("/"))
    database_lower = database_name.lower()
    if "authority" not in database_lower or "test" not in database_lower:
        raise RuntimeError(f"{_URL} database name must contain both 'authority' and 'test'")
    unsafe_tokens = ("prod", "production", "primary", "live")
    if any(token in database_lower for token in unsafe_tokens):
        raise RuntimeError(f"{_URL} must not target a production-like database")
    host_lower = parsed.hostname.lower()
    if host_lower not in {"localhost", "127.0.0.1", "::1", "postgres", "postgresql", "db"}:
        raise RuntimeError(f"{_URL} host must be local or a test-service host")
    if any(token in host_lower for token in unsafe_tokens):
        raise RuntimeError(f"{_URL} must not target a production-like host")
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


_enabled = os.environ.get(_FLAG, "").strip() == "1"
_database_url = os.environ.get(_URL, "").strip()
if _enabled and not _database_url:
    raise RuntimeError(f"{_URL} is required when {_FLAG}=1")

SECRET_KEY = "owner-tenant-authority-v1-postgres-concurrency"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "tests.owner_tenant_authority_v1app.DataCenterAuthorityTestConfig",
    "tests.owner_tenant_authority_v1app.OwnerTenantAuthorityV1TestConfig",
]
DATABASES = (
    {"default": _database_config(_database_url)}
    if _enabled and _database_url
    else {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
)
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None, "data_center": None}
