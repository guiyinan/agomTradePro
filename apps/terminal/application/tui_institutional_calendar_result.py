"""Compact provenance and research limits for the calendar reference result."""

from __future__ import annotations

from collections.abc import Mapping


def project_institutional_calendar_context(payload: Mapping[str, object]) -> dict[str, object]:
    """Keep knowledge mode, cutoff and source gaps visible above the generic grid."""
    status = payload.get("status")
    if not isinstance(status, Mapping):
        return {
            "outcome": "blocked",
            "business_summary": "来源状态缺失，无法核验日历。",
            "blocking_reason": "请重新查询并核对来源。",
        }
    required = ("known_at", "knowledge_mode", "gaps", "research_status")
    if (
        any(not isinstance(status.get(key), str) or not status.get(key) for key in required)
        or status.get("must_not_use_for_decision") is not True
    ):
        return {
            "outcome": "blocked",
            "business_summary": "来源状态不完整，无法核验日历。",
            "blocking_reason": "请重新查询并核对知识截止点。",
        }
    return {
        "outcome": "partial",
        "business_summary": f"知识截止：{status['known_at']}；{status['knowledge_mode']}。来源资格截至：{status.get('source_valid_until') or '未知'}。{status['gaps']}",
        "blocking_reason": status["research_status"],
    }


__all__ = ["project_institutional_calendar_context"]
