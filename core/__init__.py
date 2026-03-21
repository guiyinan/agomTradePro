# AgomTradePro Core Package

# Ensure the Celery app is always imported when Django starts,
# so that @shared_task uses this app and its Redis broker config.
from .celery import app as celery_app

__all__ = ('celery_app',)
