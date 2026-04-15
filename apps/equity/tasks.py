"""Celery task entrypoint for equity app autodiscovery."""

from apps.equity.application.tasks import *  # noqa: F401,F403
from apps.equity.application.tasks_valuation_sync import *  # noqa: F401,F403
