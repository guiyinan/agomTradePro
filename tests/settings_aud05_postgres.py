"""Opt-in isolated PostgreSQL settings for AUD-05 transaction evidence.

The settings module is intentionally unusable without the explicit evidence
flag.  The normal component run uses the repository's default settings; an
evidence run reads individual connection fields only, never ``DATABASE_URL``,
and refuses non-local or production-like targets.
"""

from __future__ import annotations

import os

from django.apps import AppConfig

from core.settings.base import *  # noqa: F403

_FLAG = "AGOM_AUD05_PG_CONCURRENCY_EVIDENCE"


class Aud05ConfigCenterTestConfig(AppConfig):
    """Register Config Center models without running the production composition root."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.config_center"
    label = "config_center"

    def ready(self) -> None:
        """Keep this isolated database test free of application-wide side effects."""

        return None


INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "tests.settings_aud05_postgres.Aud05ConfigCenterTestConfig",
]
MIGRATION_MODULES = {"config_center": None}
if os.environ.get(_FLAG, "").strip() != "1":
    raise RuntimeError(
        "AUD-05 PostgreSQL evidence is opt-in; "
        f"set {_FLAG}=1 before selecting tests.settings_aud05_postgres"
    )

_host = os.environ.get("AGOM_AUD05_PG_HOST", "127.0.0.1").strip()
_port = os.environ.get("AGOM_AUD05_PG_PORT", "55439").strip()
_name = os.environ.get("AGOM_AUD05_PG_NAME", "aud05_test").strip()
_user = os.environ.get("AGOM_AUD05_PG_USER", "postgres").strip()
_password = os.environ.get("AGOM_AUD05_PG_PASSWORD", "")
_host_lower = _host.lower()
_name_lower = _name.lower()
if _host_lower not in {"127.0.0.1", "localhost", "::1"}:
    raise RuntimeError("AUD-05 PostgreSQL evidence requires a loopback host")
if any(token in _host_lower for token in ("prod", "production", "primary", "live")):
    raise RuntimeError("AUD-05 PostgreSQL evidence refuses a production-like host")
if "aud05" not in _name_lower or "test" not in _name_lower:
    raise RuntimeError("AUD-05 PostgreSQL evidence requires an aud05 test database")
if any(token in _name_lower for token in ("prod", "production", "primary", "live")):
    raise RuntimeError("AUD-05 PostgreSQL evidence refuses a production-like database")
if not _user:
    raise RuntimeError("AUD-05 PostgreSQL evidence requires an explicit database user")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _name,
        "USER": _user,
        "PASSWORD": _password,
        "HOST": _host,
        "PORT": _port,
        "CONN_MAX_AGE": 0,
        "TEST": {"NAME": f"test_{_name}"},
    }
}
