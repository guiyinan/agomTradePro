"""
Django production settings for AgomTradePro project.
"""

import logging
import os

from django.core.exceptions import ImproperlyConfigured

from core.log_file_paths import (
    get_celery_beat_log_path,
    get_celery_log_backup_count,
    get_celery_log_max_bytes,
    get_celery_worker_log_path,
)


def _validate_secret_key() -> str:
    """
    Validate SECRET_KEY for production use.

    This function MUST be called before importing from base, because base.py
    will set SECRET_KEY with a default value that we want to override.

    Raises:
        ImproperlyConfigured: If SECRET_KEY is missing or contains insecure patterns.
    """
    secret_key = os.environ.get("SECRET_KEY", "")

    # Insecure patterns that indicate development/default keys
    insecure_patterns = [
        "django-insecure",
        "change-this",
        "dev-only",
        "test-only",
        "xxx",
        "example",
        "placeholder",
    ]

    if not secret_key:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is required in production. "
            "Generate a secure key using: "
            'python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )

    secret_key_lower = secret_key.lower()
    for pattern in insecure_patterns:
        if pattern in secret_key_lower:
            raise ImproperlyConfigured(
                f"SECRET_KEY contains insecure pattern '{pattern}'. "
                "Generate a secure key using: "
                'python -c "import secrets; print(secrets.token_urlsafe(50))"'
            )

    # Minimum length check (50 characters is a reasonable minimum for production)
    if len(secret_key) < 50:
        raise ImproperlyConfigured(
            f"SECRET_KEY is too short ({len(secret_key)} characters). "
            "Generate a secure key using: "
            'python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )

    return secret_key


# Set SECRET_KEY before importing base settings
# This ensures our validation runs and overrides the default value
SECRET_KEY = _validate_secret_key()

from .base import *  # noqa: E402, F403

if not env("REDIS_URL", default=""):
    CHANNEL_LAYERS = {}

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
# Never execute Qlib inference in the Daphne request process in production.
ALPHA_ALLOW_INLINE_INFERENCE = False
# Queue admission is explicit and requires a separate deployment authorization
# switch.  A stale environment cannot enable one half of the path, while a
# reviewed canary can enable both flags without changing application code.
_TERMINAL_RUNTIME_AUTHORIZED = env.bool("TERMINAL_RUNTIME_AUTHORIZED", default=False)
TERMINAL_QUEUED_INTAKE_ENABLED = _TERMINAL_RUNTIME_AUTHORIZED and env.bool(
    "TERMINAL_QUEUED_INTAKE_ENABLED", default=False
)
TERMINAL_QUEUED_WORKER_ENABLED = _TERMINAL_RUNTIME_AUTHORIZED and env.bool(
    "TERMINAL_QUEUED_WORKER_ENABLED", default=False
)
TERMINAL_LEGACY_INLINE_ENABLED = True
TERMINAL_LEGACY_INLINE_CONCURRENCY = 1
TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS = 60
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Keep environment-specific mutations isolated from the shared base module.
MIDDLEWARE = list(MIDDLEWARE)

# Static files
# In production we serve collected static assets via WhiteNoise by default so
# the app remains self-contained even when Nginx is not fronting /static.
if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
    security_middleware_index = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
    MIDDLEWARE.insert(
        security_middleware_index + 1,
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
WHITENOISE_MAX_AGE = env.int("WHITENOISE_MAX_AGE", default=31536000)
WHITENOISE_KEEP_ONLY_HASHED_FILES = env.bool(
    "WHITENOISE_KEEP_ONLY_HASHED_FILES",
    default=True,
)

database_url = env("DATABASE_URL", default="").strip()
if not database_url:
    raise ImproperlyConfigured(
        "DATABASE_URL is required in production and must point to PostgreSQL."
    )
allow_sqlite_migration = env.bool(
    "AGOMTRADEPRO_ALLOW_PRODUCTION_SQLITE_MIGRATION",
    default=False,
)
if not database_url.startswith(("postgres://", "postgresql://")) and not (
    allow_sqlite_migration and database_url.startswith("sqlite:")
):
    raise ImproperlyConfigured(
        "Production DATABASE_URL must use PostgreSQL; SQLite is only supported "
        "for development and the one-time migration source."
    )

# Database - PostgreSQL is mandatory for production concurrency.
DATABASES = {
    "default": {
        **env.db_url_config(database_url),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=600),
        "CONN_HEALTH_CHECKS": True,  # Django 4.1+ auto-detect broken connections
    }
}

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# HTTPS settings. Caddy owns the public HTTP-to-HTTPS redirect in the VPS
# topology; Django still publishes security headers for proxied HTTPS traffic.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SECURE_SSL_REDIRECT_EXEMPT_HOSTS = tuple(
    host.strip().lower()
    for host in env.list(
        "SECURE_SSL_REDIRECT_EXEMPT_HOSTS",
        default=["127.0.0.1", "localhost", "web"],
    )
    if host.strip()
)
SECURE_SSL_REDIRECT_EXEMPT_NETWORKS = tuple(
    network.strip()
    for network in env.list(
        "SECURE_SSL_REDIRECT_EXEMPT_NETWORKS",
        default=[
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
        ],
    )
    if network.strip()
)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_REFERRER_POLICY = env("SECURE_REFERRER_POLICY", default="strict-origin-when-cross-origin")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS remains independent from Django's redirect switch because TLS terminates
# at Caddy and SECURE_PROXY_SSL_HEADER preserves the original request scheme.
SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS",
    default=31536000 if SECURE_SSL_REDIRECT else 0,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)
PUBLIC_HTTPS_ENABLED = SECURE_SSL_REDIRECT or SECURE_HSTS_SECONDS > 0
if not PUBLIC_HTTPS_ENABLED:
    # COOP is only meaningful on potentially trustworthy origins (HTTPS/localhost).
    # Disable it for plain HTTP deployments to avoid browser warnings like:
    # "Cross-Origin-Opener-Policy header has been ignored, because the URL's origin was untrustworthy".
    SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# Caddy is the only public listener in the VPS topology and owns the edge
# HTTP-to-HTTPS redirect. Django's deploy check cannot observe that proxy
# boundary, so suppress only its redirect-specific false positive.
SILENCED_SYSTEM_CHECKS = ["security.W008"]

# CORS and CSRF trusted origins for production
# Allow VPS IP and configured domains
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=[f"http://{host}" for host in ALLOWED_HOSTS]
)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=[f"http://{host}" for host in ALLOWED_HOSTS]
)

# If using HTTPS, add https:// versions
if PUBLIC_HTTPS_ENABLED:
    CORS_ALLOWED_ORIGINS.extend([f"https://{host}" for host in ALLOWED_HOSTS])
    CSRF_TRUSTED_ORIGINS.extend([f"https://{host}" for host in ALLOWED_HOSTS])

# Logging configuration
# 结构化日志配置 - 生产环境默认使用 JSON 格式
LOG_TO_FILE = env.bool("LOG_TO_FILE", default=False)
USE_JSON_LOGGING = env.bool("USE_JSON_LOGGING", default=True)
CELERY_WORKER_LOG_FILE = get_celery_worker_log_path(BASE_DIR)
CELERY_BEAT_LOG_FILE = get_celery_beat_log_path(BASE_DIR)
CELERY_LOG_MAX_BYTES = get_celery_log_max_bytes()
CELERY_LOG_BACKUP_COUNT = get_celery_log_backup_count()

handlers = {
    "console": {
        "class": "logging.StreamHandler",
        "formatter": "structured" if USE_JSON_LOGGING else "verbose",
        "filters": ["trace_context"],
    },
    "console_json": {
        "class": "logging.StreamHandler",
        "formatter": "structured",
        "filters": ["trace_context"],
    },
    "in_memory": {
        "class": "core.logging_handlers.InMemoryLogHandler",
        "formatter": "simple",
        "filters": ["trace_context"],
    },
    "celery_worker_file": {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(CELERY_WORKER_LOG_FILE),
        "maxBytes": CELERY_LOG_MAX_BYTES,
        "backupCount": CELERY_LOG_BACKUP_COUNT,
        "formatter": "structured" if USE_JSON_LOGGING else "simple_with_trace",
        "filters": ["trace_context"],
    },
    "celery_beat_file": {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(CELERY_BEAT_LOG_FILE),
        "maxBytes": CELERY_LOG_MAX_BYTES,
        "backupCount": CELERY_LOG_BACKUP_COUNT,
        "formatter": "structured" if USE_JSON_LOGGING else "simple_with_trace",
        "filters": ["trace_context"],
    },
}

django_handlers = ["console", "in_memory"]
celery_worker_handlers = ["console", "in_memory", "celery_worker_file"]
celery_beat_handlers = ["console", "in_memory", "celery_beat_file"]

if LOG_TO_FILE:
    os.makedirs("/var/log/agomtradepro", exist_ok=True)
    handlers["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/agomtradepro/django.log",
        "maxBytes": 1024 * 1024 * 100,
        "backupCount": 10,
        "formatter": "structured",
        "filters": ["trace_context"],
    }
    handlers["file_json"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/agomtradepro/django.json.log",
        "maxBytes": 1024 * 1024 * 100,
        "backupCount": 10,
        "formatter": "structured",
        "filters": ["trace_context"],
    }
    django_handlers.extend(["file", "file_json"])
    celery_worker_handlers.extend(["file", "file_json"])
    celery_beat_handlers.extend(["file", "file_json"])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "trace_context": {
            "()": "core.logging_utils.TraceContextFilter",
        },
    },
    "formatters": {
        # 结构化 JSON 格式（生产环境推荐）
        "structured": {
            "()": "core.logging_utils.StructuredFormatter",
        },
        # 详细结构化 JSON 格式
        "structured_verbose": {
            "()": "core.logging_utils.StructuredFormatterVerbose",
        },
        # 文本格式（备用）
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        # 带 trace_id 的文本格式
        "simple_with_trace": {
            "format": "{levelname} {asctime} {module} [trace_id={trace_id}] {message}",
            "style": "{",
        },
    },
    "handlers": handlers,
    "root": {
        "handlers": ["console", "in_memory"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": django_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": django_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": django_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "core": {
            "handlers": django_handlers,
            "level": "INFO",
            "propagate": False,
        },
        # Celery 日志
        "celery": {
            "handlers": celery_worker_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "celery.task": {
            "handlers": celery_worker_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "celery.worker": {
            "handlers": celery_worker_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "celery.app.trace": {
            "handlers": celery_worker_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "celery.beat": {
            "handlers": celery_beat_handlers,
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ---------------------
# Sentry Error Tracking
# ---------------------
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.celery import (
        CeleryIntegration,
    )
    from sentry_sdk.integrations.django import (
        DjangoIntegration,
    )
    from sentry_sdk.integrations.logging import (
        LoggingIntegration,
    )

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
        send_default_pii=False,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE", ""),
    )

# Celery Beat settings (use database scheduler)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers.DatabaseScheduler"
PRODUCTION_STRICT_READINESS = env.bool("PRODUCTION_STRICT_READINESS", default=True)

# 注意: 定时任务配置通过 Django Admin 或 setup_celery_beat.py 脚本配置
