"""
Django production settings for AgomSAAF project.
"""

import logging
import os
from django.core.exceptions import ImproperlyConfigured


def _validate_secret_key() -> str:
    """
    Validate SECRET_KEY for production use.

    This function MUST be called before importing from base, because base.py
    will set SECRET_KEY with a default value that we want to override.

    Raises:
        ImproperlyConfigured: If SECRET_KEY is missing or contains insecure patterns.
    """
    secret_key = os.environ.get('SECRET_KEY', '')

    # Insecure patterns that indicate development/default keys
    insecure_patterns = [
        'django-insecure',
        'change-this',
        'dev-only',
        'test-only',
        'xxx',
        'example',
        'placeholder',
    ]

    if not secret_key:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is required in production. "
            "Generate a secure key using: "
            "python -c \"import secrets; print(secrets.token_urlsafe(50))\""
        )

    secret_key_lower = secret_key.lower()
    for pattern in insecure_patterns:
        if pattern in secret_key_lower:
            raise ImproperlyConfigured(
                f"SECRET_KEY contains insecure pattern '{pattern}'. "
                "Generate a secure key using: "
                "python -c \"import secrets; print(secrets.token_urlsafe(50))\""
            )

    # Minimum length check (50 characters is a reasonable minimum for production)
    if len(secret_key) < 50:
        raise ImproperlyConfigured(
            f"SECRET_KEY is too short ({len(secret_key)} characters). "
            "Generate a secure key using: "
            "python -c \"import secrets; print(secrets.token_urlsafe(50))\""
        )

    return secret_key


# Set SECRET_KEY before importing base settings
# This ensures our validation runs and overrides the default value
SECRET_KEY = _validate_secret_key()

from .base import *  # noqa: E402

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# Database - PostgreSQL for production
DATABASES = {
    'default': {
        **env.db('DATABASE_URL', default='sqlite:///db.sqlite3'),
        'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=600),
        'CONN_HEALTH_CHECKS': True,  # Django 4.1+ auto-detect broken connections
    }
}

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# HTTPS settings - secure by default in production
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_REFERRER_POLICY = env('SECURE_REFERRER_POLICY', default='strict-origin-when-cross-origin')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS settings - only enable when using HTTPS
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)
else:
    # COOP is only meaningful on potentially trustworthy origins (HTTPS/localhost).
    # Disable it for plain HTTP deployments to avoid browser warnings like:
    # "Cross-Origin-Opener-Policy header has been ignored, because the URL's origin was untrustworthy".
    SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# CORS and CSRF trusted origins for production
# Allow VPS IP and configured domains
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=False)

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    f'http://{host}' for host in ALLOWED_HOSTS
])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    f'http://{host}' for host in ALLOWED_HOSTS
])

# If using HTTPS, add https:// versions
if SECURE_SSL_REDIRECT:
    CORS_ALLOWED_ORIGINS.extend([f'https://{host}' for host in ALLOWED_HOSTS])
    CSRF_TRUSTED_ORIGINS.extend([f'https://{host}' for host in ALLOWED_HOSTS])

# Logging configuration
# 结构化日志配置 - 生产环境默认使用 JSON 格式
LOG_TO_FILE = env.bool('LOG_TO_FILE', default=False)
USE_JSON_LOGGING = env.bool('USE_JSON_LOGGING', default=True)

handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'structured' if USE_JSON_LOGGING else 'verbose',
        'filters': ['trace_context'],
    },
    'console_json': {
        'class': 'logging.StreamHandler',
        'formatter': 'structured',
        'filters': ['trace_context'],
    },
    'in_memory': {
        'class': 'core.logging_handlers.InMemoryLogHandler',
        'formatter': 'simple',
        'filters': ['trace_context'],
    },
}

django_handlers = ['console', 'in_memory']

if LOG_TO_FILE:
    os.makedirs('/var/log/agomsaaf', exist_ok=True)
    handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': '/var/log/agomsaaf/django.log',
        'maxBytes': 1024 * 1024 * 100,
        'backupCount': 10,
        'formatter': 'structured',
        'filters': ['trace_context'],
    }
    handlers['file_json'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': '/var/log/agomsaaf/django.json.log',
        'maxBytes': 1024 * 1024 * 100,
        'backupCount': 10,
        'formatter': 'structured',
        'filters': ['trace_context'],
    }
    django_handlers.extend(['file', 'file_json'])

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'trace_context': {
            '()': 'core.logging_utils.TraceContextFilter',
        },
    },
    'formatters': {
        # 结构化 JSON 格式（生产环境推荐）
        'structured': {
            '()': 'core.logging_utils.StructuredFormatter',
        },
        # 详细结构化 JSON 格式
        'structured_verbose': {
            '()': 'core.logging_utils.StructuredFormatterVerbose',
        },
        # 文本格式（备用）
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        # 带 trace_id 的文本格式
        'simple_with_trace': {
            'format': '{levelname} {asctime} {module} [trace_id={trace_id}] {message}',
            'style': '{',
        },
    },
    'handlers': handlers,
    'root': {
        'handlers': ['console', 'in_memory'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': django_handlers,
            'level': 'WARNING',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'core': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        # Celery 日志
        'celery': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'celery.task': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ---------------------
# Sentry Error Tracking
# ---------------------
_sentry_dsn = os.environ.get('SENTRY_DSN', '')
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_RATE', '0.1')),
        send_default_pii=False,
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'production'),
        release=os.environ.get('SENTRY_RELEASE', ''),
    )

# Celery Beat settings (use database scheduler)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers.DatabaseScheduler'

# 注意: 定时任务配置通过 Django Admin 或 setup_celery_beat.py 脚本配置
