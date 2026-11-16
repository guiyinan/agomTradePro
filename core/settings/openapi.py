"""Generate production-shaped OpenAPI metadata without a business database.

DRF derives integer limits from the selected database backend. Always use
PostgreSQL metadata here, regardless of the local development database. The
unavailable local endpoint makes accidental database access fail promptly.
"""

from .development import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "openapi_schema",
        "HOST": "127.0.0.1",
        "PORT": "1",
        "OPTIONS": {"connect_timeout": 1},
    }
}
