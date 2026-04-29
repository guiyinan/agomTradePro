"""
Health Check Functions for AgomTradePro

Provides health check functions for Kubernetes liveness and readiness probes.
"""

import logging
from typing import Any, Dict, Optional

from django.core.cache import cache
from django.db import DatabaseError, connections

logger = logging.getLogger(__name__)


def check_database(using: str = "default") -> dict[str, Any]:
    """
    Check database connection health.

    Args:
        using: Database connection name to check (default: 'default')

    Returns:
        Dict with status and optional error message:
        - {"status": "ok"} if healthy
        - {"status": "error", "error": "..."} if unhealthy
    """
    try:
        db_conn = connections[using]
        db_conn.ensure_connection()

        # Execute a simple query to verify connection
        with db_conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        return {"status": "ok"}
    except DatabaseError as e:
        logger.warning(f"Database health check failed for '{using}': {e}")
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.warning(f"Unexpected error during database health check for '{using}': {e}")
        return {"status": "error", "error": str(e)}


def check_redis() -> dict[str, Any]:
    """
    Check Redis connection health (if configured).

    Returns:
        Dict with status and optional error message:
        - {"status": "ok"} if healthy
        - {"status": "skipped"} if Redis not configured
        - {"status": "error", "error": "..."} if unhealthy
    """
    from django.conf import settings

    # Check if Redis cache is configured
    cache_backend = settings.CACHES.get("default", {}).get("BACKEND", "")

    # If using LocMemCache or no cache configured, skip Redis check
    if "locmem" in cache_backend.lower() or "dummy" in cache_backend.lower() or not cache_backend:
        return {"status": "skipped", "reason": "Redis not configured"}

    try:
        # Try to set and get a value from cache
        test_key = "_health_check_test"
        cache.set(test_key, "test", timeout=10)
        result = cache.get(test_key)
        cache.delete(test_key)

        if result == "test":
            return {"status": "ok"}
        else:
            return {"status": "error", "error": "Cache read/write failed"}
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return {"status": "error", "error": str(e)}


def check_celery() -> dict[str, Any]:
    """
    Check Celery worker availability by sending a ping.

    Returns:
        Dict with status:
        - {"status": "ok", "workers": N} if workers respond
        - {"status": "skipped"} if Celery not configured
        - {"status": "error", "error": "..."} if unhealthy
    """
    from django.conf import settings

    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        return {"status": "skipped", "reason": "Celery in eager mode"}

    try:
        from core.celery import app as celery_app

        result = celery_app.control.ping(timeout=3.0)
        if result:
            return {"status": "ok", "workers": len(result)}
        return {"status": "error", "error": "No Celery workers responded"}
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
        return {"status": "error", "error": str(e)}


def check_critical_data() -> dict[str, Any]:
    """
    Check that critical data tables are non-empty.

    Verifies macro_indicator and regime tables have data,
    which are required for the system to function correctly.

    Returns:
        Dict with status and detail on checked tables.
    """
    try:
        from django.apps import apps

        checks: dict[str, bool] = {}

        # Check macro indicators
        try:
            MacroFact = apps.get_model('data_center', 'MacroFactModel')
            checks['macro_indicator'] = MacroFact.objects.exists()
        except Exception:
            checks['macro_indicator'] = False

        # Check regime state
        try:
            RegimeLog = apps.get_model('regime', 'RegimeLog')
            checks['regime_state'] = RegimeLog.objects.exists()
        except Exception:
            checks['regime_state'] = False

        empty_tables = [k for k, v in checks.items() if not v]
        if empty_tables:
            return {
                "status": "warning",
                "empty_tables": empty_tables,
                "detail": checks,
            }
        return {"status": "ok", "detail": checks}
    except Exception as e:
        logger.warning(f"Critical data check failed: {e}")
        return {"status": "error", "error": str(e)}


def run_readiness_checks() -> dict[str, dict[str, Any]]:
    """
    Run all readiness checks.

    Returns:
        Dict of check results keyed by check name:
        {
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
            "celery": {"status": "ok"},
            "critical_data": {"status": "ok"}
        }
    """
    checks = {
        "database": check_database(),
        "redis": check_redis(),
        "celery": check_celery(),
        "critical_data": check_critical_data(),
    }
    return checks


def is_healthy(checks: dict[str, dict[str, Any]]) -> bool:
    """
    Determine if all readiness checks passed.

    Args:
        checks: Dict of check results from run_readiness_checks()

    Returns:
        True if all checks are "ok" or "skipped", False otherwise
    """
    for check_name, result in checks.items():
        status = result.get("status")
        # "skipped" and "warning" are acceptable (e.g., Redis not configured, empty tables)
        if status not in ("ok", "skipped", "warning"):
            return False
    return True
