"""policy runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_get_policy_status() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    status = client.policy.get_status()
    return {
        "current_gear": status.current_gear,
        "observed_at": status.observed_at.isoformat(),
        "recent_events_count": len(status.recent_events),
    }


def _fallback_get_policy_events(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    events = client.policy.get_events(
        start_date=parsed_start,
        end_date=parsed_end,
        limit=limit,
    )
    payload = [
        {
            "id": item.id,
            "event_date": item.event_date.isoformat(),
            "event_type": item.event_type,
            "description": item.description,
            "gear": item.gear,
        }
        for item in events
    ]
    return {
        "events": payload,
        "total_count": len(payload),
    }


def _fallback_get_workbench_bootstrap() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.get_workbench_bootstrap()


def _fallback_get_workbench_summary() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    summary = client.policy.get_workbench_summary()
    return {
        "policy_level": summary.policy_level,
        "policy_level_name": summary.policy_level_name,
        "gate_level": summary.gate_level,
        "gate_level_name": summary.gate_level_name,
        "global_heat": summary.global_heat,
        "global_sentiment": summary.global_sentiment,
        "pending_review_count": summary.pending_review_count,
        "sla_exceeded_count": summary.sla_exceeded_count,
        "today_events_count": summary.today_events_count,
    }


def _fallback_get_workbench_event_detail(event_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.get_workbench_event_detail(event_id)


def _fallback_get_workbench_items(
    tab: str = "pending",
    event_type: str | None = None,
    level: str | None = None,
    gate_level: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.policy.get_workbench_items(
        tab=tab,
        event_type=event_type,
        level=level,
        gate_level=gate_level,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [
            {
                "id": item.id,
                "event_date": item.event_date.isoformat(),
                "event_type": item.event_type,
                "level": item.level,
                "title": item.title,
                "description": item.description,
                "gate_level": item.gate_level,
                "gate_effective": item.gate_effective,
                "audit_status": item.audit_status,
                "ai_confidence": item.ai_confidence,
                "heat_score": item.heat_score,
                "sentiment_score": item.sentiment_score,
                "asset_class": item.asset_class,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in result.items
        ],
        "total_count": result.total_count,
        "page": result.page,
        "page_size": result.page_size,
    }


def _fallback_get_sentiment_gate_state(asset_class: str = "all") -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    state = client.policy.get_sentiment_gate_state(asset_class=asset_class)
    return {
        "asset_class": asset_class,
        "gate_level": state.gate_level,
        "global_heat": state.global_heat,
        "global_sentiment": state.global_sentiment,
        "max_position_cap": state.max_position_cap,
        "signal_paused": state.signal_paused,
    }


def _fallback_approve_workbench_event(
    event_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.approve_event(event_id)


def _fallback_reject_workbench_event(
    event_id: int,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.reject_event(event_id, reason)


def _fallback_rollback_workbench_event(
    event_id: int,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.rollback_event(event_id, reason)


def _fallback_override_workbench_event(
    event_id: int,
    reason: str,
    new_level: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.policy.override_event(event_id, reason, new_level=new_level)


def _internal_handler_policy_create_event(
    event_date: str,
    level: str,
    title: str,
    description: str,
    evidence_url: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date
    from urllib.parse import urlparse

    from agomtradepro import AgomTradeProClient

    try:
        parsed_event_date = date.fromisoformat(str(event_date or "").strip())
    except ValueError as exc:
        raise ValueError("event_date must use YYYY-MM-DD format") from exc

    normalized_level = str(level or "").strip().upper()
    if normalized_level not in {"PX", "P0", "P1", "P2", "P3"}:
        raise ValueError("level must be one of: PX, P0, P1, P2, P3")

    normalized_title = str(title or "").strip()
    normalized_description = str(description or "").strip()
    normalized_evidence_url = str(evidence_url or "").strip()
    if not normalized_title:
        raise ValueError("title must be a non-empty string")
    if not normalized_description:
        raise ValueError("description must be a non-empty string")
    if normalized_level in {"P2", "P3"} and len(normalized_description) < 20:
        raise ValueError(f"{normalized_level} description must contain at least 20 characters")
    parsed_evidence_url = urlparse(normalized_evidence_url)
    if parsed_evidence_url.scheme not in {"http", "https"} or not parsed_evidence_url.netloc:
        raise ValueError("evidence_url must be an absolute HTTP or HTTPS URL")

    client = AgomTradeProClient()
    if preview_only:
        existing_events = client.policy.get_events(
            start_date=parsed_event_date,
            end_date=parsed_event_date,
            limit=100,
        )
        return {
            "success": True,
            "preview_only": True,
            "event_summary": {
                "event_date": parsed_event_date.isoformat(),
                "level": normalized_level,
                "title": normalized_title,
                "description_length": len(normalized_description),
                "evidence_url": normalized_evidence_url,
                "existing_event_count": len(existing_events),
                "may_trigger_alert": normalized_level in {"P2", "P3"},
            },
            "existing_events": [
                {
                    "id": getattr(item, "id", None),
                    "event_date": item.event_date.isoformat(),
                    "gear": item.gear,
                    "description": item.description,
                }
                for item in existing_events
            ],
            "summary": {
                "event_date": parsed_event_date.isoformat(),
                "level": normalized_level,
                "existing_event_count": len(existing_events),
            },
            "message": (
                "Preview generated. Confirm to create the policy event. "
                "P2/P3 creation may trigger the configured policy alert service."
            ),
        }

    gear_by_level = {
        "PX": "neutral",
        "P0": "neutral",
        "P1": "tightening",
        "P2": "stimulus",
        "P3": "stimulus",
    }
    created = client.policy.create_event(
        parsed_event_date,
        normalized_title,
        normalized_description,
        gear_by_level[normalized_level],
        level=normalized_level,
        title=normalized_title,
        evidence_url=normalized_evidence_url,
    )
    return {
        "success": True,
        "event": {
            "id": created.id,
            "event_date": parsed_event_date.isoformat(),
            "level": normalized_level,
            "title": normalized_title,
            "description": normalized_description,
            "evidence_url": normalized_evidence_url,
        },
    }


def _internal_handler_policy_start_rss_fetch(
    source_id: int | None = None,
    force_refetch: bool = False,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if source_id is not None and (
        isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0
    ):
        raise ValueError("source_id must be a positive integer")
    if not isinstance(force_refetch, bool):
        raise ValueError("force_refetch must be a boolean")

    client = AgomTradeProClient()
    mode = "single" if source_id is not None else "all"

    if preview_only:
        if source_id is not None:
            sources = [client.policy.get_rss_source(source_id)]
            if not sources[0].get("is_active", False):
                raise ValueError(f"RSS source {source_id} is inactive")
        else:
            sources = client.policy.list_rss_sources(is_active=True)

        targets = [
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "category": source.get("category"),
                "is_active": bool(source.get("is_active")),
                "extract_content": bool(source.get("extract_content")),
                "parser_type": source.get("parser_type"),
                "rsshub_enabled": bool(source.get("rsshub_enabled")),
                "last_fetch_at": source.get("last_fetch_at"),
                "last_fetch_status": source.get("last_fetch_status"),
            }
            for source in sources
        ]
        if not targets:
            raise ValueError("No active RSS sources are available for fetch")

        summary = {
            "mode": mode,
            "source_count": len(targets),
            "source_ids": [target["id"] for target in targets],
            "force_refetch": force_refetch,
            "external_network_io": True,
            "may_invoke_ai": True,
            "may_send_alerts": True,
            "partial_success_possible": True,
            "writes": [
                "raw_policy_logs",
                "policy_events",
                "rss_fetch_logs",
                "rss_source_last_fetch_status",
            ],
        }
        return {
            "success": True,
            "preview_only": True,
            "mode": mode,
            "targets": targets,
            "summary": summary,
            "message": (
                "Preview generated without fetching RSS, invoking AI, writing policy data, "
                "updating source status, sending alerts, or submitting tasks. Confirm to run "
                "the canonical synchronous fetch; per-source or per-item partial success is possible."
            ),
        }

    return client.policy.trigger_fetch(
        source_id=source_id,
        force_refetch=force_refetch,
    )


def _internal_handler_policy_approve_workbench_event(
    event_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        event = client.policy.get_workbench_event_detail(event_id)
        return {
            "success": True,
            "preview_only": True,
            "event_id": event_id,
            "event_summary": {
                "title": event.get("title"),
                "event_date": event.get("event_date"),
                "level": event.get("level"),
                "event_type": event.get("event_type"),
                "audit_status": event.get("audit_status"),
                "source_type": event.get("source_type"),
                "source_name": event.get("source_name") or event.get("rss_source_name"),
            },
            "target_status": "manual_approved",
            "message": (
                "Preview generated. Confirm to approve the selected policy workbench event."
            ),
        }

    return _call_registered_tool(
        "approve_workbench_event",
        {
            "event_id": event_id,
        },
    )


def _internal_handler_policy_reject_workbench_event(
    event_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        event = client.policy.get_workbench_event_detail(event_id)
        return {
            "success": True,
            "preview_only": True,
            "event_id": event_id,
            "event_summary": {
                "title": event.get("title"),
                "event_date": event.get("event_date"),
                "level": event.get("level"),
                "event_type": event.get("event_type"),
                "audit_status": event.get("audit_status"),
                "source_type": event.get("source_type"),
                "source_name": event.get("source_name") or event.get("rss_source_name"),
            },
            "reason": reason,
            "target_status": "rejected",
            "message": (
                "Preview generated. Confirm to reject the selected policy workbench event."
            ),
        }

    return _call_registered_tool(
        "reject_workbench_event",
        {
            "event_id": event_id,
            "reason": reason,
        },
    )


def _internal_handler_policy_rollback_workbench_event(
    event_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        event = client.policy.get_workbench_event_detail(event_id)
        return {
            "success": True,
            "preview_only": True,
            "event_id": event_id,
            "event_summary": {
                "title": event.get("title"),
                "event_date": event.get("event_date"),
                "level": event.get("level"),
                "event_type": event.get("event_type"),
                "audit_status": event.get("audit_status"),
                "gate_effective": event.get("gate_effective"),
                "effective_at": event.get("effective_at"),
                "source_type": event.get("source_type"),
                "source_name": event.get("source_name") or event.get("rss_source_name"),
            },
            "reason": reason,
            "target_status": "rolled_back",
            "message": (
                "Preview generated. Confirm to roll back the selected policy workbench event."
            ),
        }

    return _call_registered_tool(
        "rollback_workbench_event",
        {
            "event_id": event_id,
            "reason": reason,
        },
    )


def _internal_handler_policy_override_workbench_event(
    event_id: int,
    reason: str,
    new_level: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        event = client.policy.get_workbench_event_detail(event_id)
        current_level = event.get("level")
        return {
            "success": True,
            "preview_only": True,
            "event_id": event_id,
            "event_summary": {
                "title": event.get("title"),
                "event_date": event.get("event_date"),
                "level": current_level,
                "event_type": event.get("event_type"),
                "audit_status": event.get("audit_status"),
                "gate_effective": event.get("gate_effective"),
                "effective_at": event.get("effective_at"),
                "source_type": event.get("source_type"),
                "source_name": event.get("source_name") or event.get("rss_source_name"),
            },
            "override_summary": {
                "current_level": current_level,
                "requested_level": new_level,
                "level_changed": new_level is not None and str(new_level) != str(current_level),
            },
            "reason": reason,
            "target_status": "overridden",
            "message": (
                "Preview generated. Confirm to override the selected policy workbench event."
            ),
        }

    return _call_registered_tool(
        "override_workbench_event",
        {
            "event_id": event_id,
            "reason": reason,
            "new_level": new_level,
        },
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_policy_status": _fallback_get_policy_status,
    "get_policy_events": _fallback_get_policy_events,
    "get_workbench_bootstrap": _fallback_get_workbench_bootstrap,
    "get_workbench_summary": _fallback_get_workbench_summary,
    "get_workbench_event_detail": _fallback_get_workbench_event_detail,
    "get_workbench_items": _fallback_get_workbench_items,
    "get_sentiment_gate_state": _fallback_get_sentiment_gate_state,
    "approve_workbench_event": _fallback_approve_workbench_event,
    "reject_workbench_event": _fallback_reject_workbench_event,
    "rollback_workbench_event": _fallback_rollback_workbench_event,
    "override_workbench_event": _fallback_override_workbench_event,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "policy_create_event": _internal_handler_policy_create_event,
    "policy_start_rss_fetch": _internal_handler_policy_start_rss_fetch,
    "policy_approve_workbench_event": _internal_handler_policy_approve_workbench_event,
    "policy_reject_workbench_event": _internal_handler_policy_reject_workbench_event,
    "policy_rollback_workbench_event": _internal_handler_policy_rollback_workbench_event,
    "policy_override_workbench_event": _internal_handler_policy_override_workbench_event,
}
