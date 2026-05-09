"""Celery tasks for precomputing decision workspace snapshots."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)
from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase
from apps.regime.application.orchestration import calculate_regime_after_sync
from apps.rotation.application.repository_provider import generate_rotation_signals
from core.integration.pulse_refresh import refresh_pulse_snapshot

logger = get_task_logger(__name__)


def _parse_target_date(as_of_date: str | None) -> date:
    """Parse snapshot target date, defaulting to today."""

    return date.fromisoformat(as_of_date) if as_of_date else date.today()


def _sync_macro_inputs(*, target_date: date, source: str, days_back: int) -> dict[str, Any]:
    """Synchronously refresh macro inputs before nightly snapshot generation."""

    use_case = build_sync_macro_data_use_case(source)
    result = use_case.execute(
        SyncMacroDataRequest(
            start_date=target_date - timedelta(days=days_back),
            end_date=target_date,
            indicators=None,
        )
    )
    return {
        "status": "success",
        "source": source,
        "start_date": (target_date - timedelta(days=days_back)).isoformat(),
        "end_date": target_date.isoformat(),
        "synced_count": int(result.synced_count),
        "skipped_count": int(result.skipped_count),
        "errors": list(result.errors or []),
    }


def _build_overall_status(component_payloads: dict[str, dict[str, Any]]) -> str:
    """Collapse component results into an overall workspace snapshot status."""

    statuses = [str(payload.get("status") or "") for payload in component_payloads.values()]
    if statuses and all(status == "success" for status in statuses):
        return "success"
    if any(status in {"success", "blocked"} for status in statuses):
        return "partial_success"
    return "error"


@shared_task(time_limit=1800, soft_time_limit=1700)
def refresh_decision_workspace_snapshots(
    as_of_date: str | None = None,
    *,
    source: str = "akshare",
    days_back: int = 60,
    use_pit: bool = True,
) -> dict[str, Any]:
    """Precompute Step 1-3 workspace snapshots once per night."""

    target_date = _parse_target_date(as_of_date)
    logger.info(
        "Refreshing decision workspace snapshots for %s (source=%s, days_back=%s)",
        target_date.isoformat(),
        source,
        days_back,
    )

    components: dict[str, dict[str, Any]] = {}
    sync_result: dict[str, Any] = {"status": "success", "source": "existing_store"}

    try:
        sync_result = _sync_macro_inputs(
            target_date=target_date,
            source=source,
            days_back=days_back,
        )
        components["macro_sync"] = sync_result
    except Exception as exc:
        logger.exception("Workspace snapshot macro sync failed for %s", target_date.isoformat())
        components["macro_sync"] = {
            "status": "error",
            "error": str(exc),
            "source": source,
        }

    try:
        regime_result = calculate_regime_after_sync.run(
            sync_result=sync_result,
            as_of_date=target_date.isoformat(),
            use_pit=use_pit,
        )
        components["regime_snapshot"] = dict(regime_result or {})
    except Exception as exc:
        logger.exception("Workspace snapshot regime refresh failed for %s", target_date.isoformat())
        components["regime_snapshot"] = {
            "status": "error",
            "error": str(exc),
        }

    try:
        pulse_snapshot = refresh_pulse_snapshot(target_date=target_date)
        if pulse_snapshot is None:
            components["pulse_snapshot"] = {
                "status": "error",
                "error": "pulse_snapshot_unavailable",
            }
        else:
            components["pulse_snapshot"] = {
                "status": "success",
                "observed_at": pulse_snapshot.observed_at.isoformat(),
                "composite_score": float(pulse_snapshot.composite_score),
                "regime_strength": str(pulse_snapshot.regime_strength),
                "is_reliable": bool(getattr(pulse_snapshot, "is_reliable", False)),
            }
    except Exception as exc:
        logger.exception("Workspace snapshot pulse refresh failed for %s", target_date.isoformat())
        components["pulse_snapshot"] = {
            "status": "error",
            "error": str(exc),
        }

    try:
        action = GetActionRecommendationUseCase().execute(
            target_date,
            refresh_pulse_if_stale=False,
            prefer_cached=False,
        )
        if action is None:
            components["action_recommendation"] = {
                "status": "error",
                "error": "action_recommendation_unavailable",
            }
        elif bool(getattr(action, "must_not_use_for_decision", False)):
            components["action_recommendation"] = {
                "status": "blocked",
                "observed_at": (
                    getattr(action, "context_observed_at", None) or target_date
                ).isoformat(),
                "source": str(getattr(action, "context_source", "live_action_fallback")),
                "blocked_reason": str(getattr(action, "blocked_reason", "") or ""),
            }
        else:
            components["action_recommendation"] = {
                "status": "success",
                "observed_at": (
                    getattr(action, "context_observed_at", None) or target_date
                ).isoformat(),
                "source": str(getattr(action, "context_source", "live_action_fallback")),
                "risk_budget_pct": float(getattr(action, "risk_budget_pct", 0.0) or 0.0),
                "recommended_sectors": list(
                    getattr(action, "recommended_sectors", []) or []
                ),
            }
    except Exception as exc:
        logger.exception(
            "Workspace snapshot action recommendation refresh failed for %s",
            target_date.isoformat(),
        )
        components["action_recommendation"] = {
            "status": "error",
            "error": str(exc),
        }

    try:
        rotation_summary = generate_rotation_signals(target_date)
        failed_count = int(rotation_summary.get("failed", 0) or 0)
        components["rotation_signals"] = {
            **dict(rotation_summary or {}),
            "status": "success" if failed_count == 0 else "partial_success",
        }
    except Exception as exc:
        logger.exception(
            "Workspace snapshot rotation refresh failed for %s",
            target_date.isoformat(),
        )
        components["rotation_signals"] = {
            "status": "error",
            "error": str(exc),
        }

    overall_status = _build_overall_status(components)
    logger.info(
        "Decision workspace snapshots finished for %s with status=%s",
        target_date.isoformat(),
        overall_status,
    )
    return {
        "status": overall_status,
        "as_of_date": target_date.isoformat(),
        "components": components,
    }
