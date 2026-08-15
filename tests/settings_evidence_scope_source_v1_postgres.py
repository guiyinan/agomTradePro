"""Explicitly isolated PostgreSQL settings for Evidence scope-source races.

This settings module is never selected by the default pytest configuration.  A
caller must opt in with ``AGOM_EVIDENCE_SCOPE_PG_CONCURRENCY_EVIDENCE=1`` and a
dedicated local/test-service URL in ``AGOM_EVIDENCE_SCOPE_PG_TEST_DATABASE_URL``.
When the opt-in is absent, the component test uses an in-memory SQLite
database only so its fixture can report an explicit skip; SQLite is never
reported as PostgreSQL evidence.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

_EVIDENCE_FLAG = "AGOM_EVIDENCE_SCOPE_PG_CONCURRENCY_EVIDENCE"
_EVIDENCE_URL = "AGOM_EVIDENCE_SCOPE_PG_TEST_DATABASE_URL"


def _database_config(database_url: str) -> dict[str, object]:
    """Build a PostgreSQL config after rejecting non-disposable targets."""

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: "
            f"{_EVIDENCE_URL} must use postgres:// or postgresql://"
        )
    if not parsed.hostname or not parsed.path or not parsed.username:
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: "
            "the dedicated URL must include host, database and user"
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: URL port is invalid"
        ) from error

    database_name = unquote(parsed.path.removeprefix("/"))
    database_name_lower = database_name.lower()
    if "evidence" not in database_name_lower or "test" not in database_name_lower:
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: database name must contain "
            "both 'evidence' and 'test'"
        )
    unsafe_tokens = ("prod", "production", "primary", "live")
    if any(token in database_name_lower for token in unsafe_tokens):
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: production-like database name"
        )

    host_lower = parsed.hostname.lower()
    allowed_local_hosts = {"localhost", "127.0.0.1", "::1", "postgres", "postgresql", "db"}
    if host_lower not in allowed_local_hosts:
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: "
            "host must be a local or test-service host"
        )
    if any(token in host_lower for token in unsafe_tokens):
        raise RuntimeError(
            "Evidence scope PostgreSQL evidence is denied: production-like database host"
        )

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


_flag_enabled = os.environ.get(_EVIDENCE_FLAG, "").strip() == "1"
_database_url = os.environ.get(_EVIDENCE_URL, "").strip()
if _flag_enabled and not _database_url:
    raise RuntimeError(
        "Evidence scope PostgreSQL evidence is denied: "
        f"{_EVIDENCE_URL} must be set when {_EVIDENCE_FLAG}=1"
    )

SECRET_KEY = "evidence-scope-source-v1-postgres-concurrency"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.researchscopesourcev1app.EvidenceScopeSourceV1TestConfig",
]
DATABASES = (
    {"default": _database_config(_database_url)}
    if _flag_enabled and _database_url
    else {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
)
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"research": None}
