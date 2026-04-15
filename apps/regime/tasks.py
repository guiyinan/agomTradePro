"""Celery task entrypoint for regime app autodiscovery."""

from apps.regime.application.orchestration import *  # noqa: F401,F403
from apps.regime.application.tasks import *  # noqa: F401,F403
