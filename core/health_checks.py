"""
Health Check Functions for AgomSAAF

Provides health check functions for Kubernetes liveness and readiness probes.
"""

import logging
from typing import Dict, Any, Optional
from django.db import connections, DatabaseError
from django.core.cache import cache

logger = logging.getLogger(__name__)


def check_database(using: str = "default") -> Dict[str, Any]:
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


def check_redis() -> Dict[str, Any]:
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


def run_readiness_checks() -> Dict[str, Dict[str, Any]]:
    """
    Run all readiness checks.

    Returns:
        Dict of check results keyed by check name:
        {
            "database": {"status": "ok"},
            "redis": {"status": "ok"}
        }
    """
    checks = {
        "database": check_database(),
        "redis": check_redis(),
    }
    return checks


def is_healthy(checks: Dict[str, Dict[str, Any]]) -> bool:
    """
    Determine if all readiness checks passed.

    Args:
        checks: Dict of check results from run_readiness_checks()

    Returns:
        True if all checks are "ok" or "skipped", False otherwise
    """
    for check_name, result in checks.items():
        status = result.get("status")
        # "skipped" is acceptable (e.g., Redis not configured)
        if status not in ("ok", "skipped"):
            return False
    return True
