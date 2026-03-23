"""Celery task entrypoint for alpha app autodiscovery.

Celery `autodiscover_tasks()` only imports `<app>.tasks` by default.
This module re-exports tasks defined under `application/`.
"""

from apps.alpha.application.monitoring_tasks import *  # noqa: F401,F403
from apps.alpha.application.tasks import *  # noqa: F401,F403

