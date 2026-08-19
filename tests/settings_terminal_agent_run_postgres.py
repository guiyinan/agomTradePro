"""Explicitly isolated PostgreSQL settings for TAR-02 concurrency evidence.

This settings module is never selected by the default pytest configuration.  A
caller must opt in with a disposable local PostgreSQL URL and an explicit
evidence flag.  The URL and database-name guards prevent an accidental run
against a production-like target.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit


def _required_environment(name: str) -> str:
    """Require an explicit evidence-only environment variable."""

    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"TAR-02 PostgreSQL evidence is denied: {name} must be set explicitly")
    return value


def _database_config(database_url: str) -> dict[str, object]:
    """Validate a local disposable URL and return Django's database config."""

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("TAR-02 PostgreSQL evidence requires a PostgreSQL URL")
    if not parsed.hostname or not parsed.path or not parsed.username:
        raise RuntimeError("TAR-02 PostgreSQL evidence URL must include host, database and user")
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("TAR-02 PostgreSQL evidence URL has an invalid port") from error

    database_name = unquote(parsed.path.removeprefix("/"))
    database_name_lower = database_name.lower()
    if "terminal" not in database_name_lower or "test" not in database_name_lower:
        raise RuntimeError(
            "TAR-02 PostgreSQL evidence database name must contain both 'terminal' and 'test'"
        )
    unsafe_tokens = ("prod", "production", "primary", "live")
    if any(token in database_name_lower for token in unsafe_tokens):
        raise RuntimeError("TAR-02 PostgreSQL evidence refuses a production-like database name")

    host_lower = parsed.hostname.lower()
    allowed_local_hosts = {"localhost", "127.0.0.1", "::1", "postgres", "postgresql", "db"}
    if host_lower not in allowed_local_hosts or any(token in host_lower for token in unsafe_tokens):
        raise RuntimeError("TAR-02 PostgreSQL evidence requires a local/test-service host")

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


if os.environ.get("AGOM_TERMINAL_AGENT_PG_CONCURRENCY_EVIDENCE", "").strip() != "1":
    raise RuntimeError(
        "TAR-02 PostgreSQL evidence is denied: set "
        "AGOM_TERMINAL_AGENT_PG_CONCURRENCY_EVIDENCE=1 to opt in"
    )

_DATABASE_URL = _required_environment("AGOM_TERMINAL_AGENT_PG_TEST_DATABASE_URL")

SECRET_KEY = "terminal-agent-postgres-concurrency-evidence"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "apps.agent_runtime",
]
DATABASES = {"default": _database_config(_DATABASE_URL)}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
