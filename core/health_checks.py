"""
Health Check Functions for AgomTradePro

Provides health check functions for Kubernetes liveness and readiness probes.
"""

import logging
import os
from typing import Any

from django.conf import settings
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
    # Check if Redis cache is configured.
    cache_backend = settings.CACHES.get("default", {}).get("BACKEND", "")

    if "redis" in cache_backend.lower():
        try:
            test_key = "_health_check_test"
            cache.set(test_key, "test", timeout=10)
            result = cache.get(test_key)
            cache.delete(test_key)

            if result == "test":
                return {"status": "ok", "source": "cache"}
            return {"status": "error", "error": "Cache read/write failed"}
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return {"status": "error", "error": str(e)}

    redis_url = _get_configured_redis_url()
    if not redis_url:
        return {"status": "skipped", "reason": "Redis not configured"}

    try:
        import redis

        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        if client.ping():
            return {"status": "ok", "source": "redis_url"}
        return {"status": "error", "error": "Redis ping failed"}
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return {"status": "error", "error": str(e)}


def _get_configured_redis_url() -> str | None:
    """Return a Redis URL configured for broker/backend health checks."""

    candidates = [
        os.environ.get("REDIS_URL"),
        getattr(settings, "CELERY_BROKER_URL", None),
        getattr(settings, "CELERY_RESULT_BACKEND", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith(("redis://", "rediss://")):
            return candidate
    return None


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
        logger.debug(f"Celery health check failed: {e}")
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


def check_alpha_workspace_consistency() -> dict[str, Any]:
    """
    Check Alpha ranking and decision workspace recommendation consistency.

    Returns warning instead of failing readiness when recommendations lag behind
    rankings, because the site can still serve traffic while operators refresh
    the recommendation chain.
    """
    try:
        from apps.decision_rhythm.infrastructure.consistency_snapshots import (
            check_alpha_workspace_consistency_health,
        )

        return check_alpha_workspace_consistency_health()
    except Exception as e:
        logger.warning(f"Alpha/workspace consistency check failed: {e}")
        return {"status": "error", "error": str(e)}


def check_decision_data_readiness() -> dict[str, Any]:
    """Check decision-grade quote and market thermometer readiness."""

    try:
        from apps.data_center.application.interface_services import (
            get_decision_data_readiness_payload,
        )

        payload = get_decision_data_readiness_payload(
            asset_codes=list(getattr(settings, "DECISION_READINESS_ASSET_CODES", [])),
            quote_max_age_hours=float(
                getattr(settings, "DECISION_QUOTE_MAX_AGE_HOURS", 4.0)
            ),
        )
        readiness_status = payload.get("status")
        if payload.get("must_not_use_for_decision"):
            return {**payload, "status": "warning", "readiness_status": readiness_status}
        return {**payload, "status": "ok", "readiness_status": readiness_status}
    except Exception as e:
        logger.warning(f"Decision data readiness check failed: {e}")
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
        "decision_data": check_decision_data_readiness(),
        "alpha_workspace_consistency": check_alpha_workspace_consistency(),
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
    strict_readiness = bool(getattr(settings, "PRODUCTION_STRICT_READINESS", False))
    strict_warning_checks = {"critical_data", "decision_data"}
    for check_name, result in checks.items():
        status = result.get("status")
        # "skipped" and "warning" are acceptable (e.g., Redis not configured, empty tables)
        if strict_readiness and check_name in strict_warning_checks and status == "warning":
            return False
        if status not in ("ok", "skipped", "warning"):
            return False
    return True
