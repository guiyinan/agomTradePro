"""Human-readable, explicit source and knowledge-clock projection for calendar TUI."""

from __future__ import annotations

from apps.data_center.application.institutional_calendar_task import InstitutionalCalendarTaskResult
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    KnowledgeMode,
)

_EVIDENCE = {
    EvidenceGrade.CONFIRMED: "已确认",
    EvidenceGrade.DERIVED: "规则派生",
    EvidenceGrade.TENTATIVE: "暂定",
    EvidenceGrade.HYPOTHESIS: "行为假说",
    EvidenceGrade.UNKNOWN: "未知",
}
_LIFECYCLE = {
    EventLifecycle.SCHEDULED: "计划发布",
    EventLifecycle.OCCURRED: "已实际发布",
    EventLifecycle.CANCELLED: "已取消",
    EventLifecycle.SUPERSEDED: "已被替代",
}
_GAPS = {
    "EVENT_STUDY_NOT_COMPLETED": "事件波动研究尚未完成，未产生研究结论。",
    "UNQUALIFIED_EVENT_CLASSES_NOT_COVERED": "本期仅覆盖国家统计局CPI日程及已留存实际发布；中金所、MSCI等其他事件尚未取得接入资格。",
    "SOURCE_POLICY_UNAVAILABLE": "来源资格配置缺失或不唯一，请联系管理员核对。",
    "SOURCE_POLICY_EXPIRED": "来源资格已过期，请联系管理员复核；历史事实不代表当前资格。",
    "SOURCE_POLICY_CHANGED": "读取期间来源配置已变化，请重新查询并核对来源。",
    "ORIGINAL_UNAVAILABLE": "对应原文缺失，不能核验该事件。",
    "ORIGINAL_INVALID": "原文或其时间、来源绑定校验失败，不能核验该事件。",
}


def present_institutional_calendar(result: InstitutionalCalendarTaskResult) -> dict[str, object]:
    """Keep evidence, lifecycle, real source clocks and decision prohibition visible."""
    mode = (
        "系统已知重放"
        if result.mode is KnowledgeMode.SYSTEM_KNOWN
        else "市场可得重建（不等于系统当时已知）"
    )
    events: list[dict[str, object]] = []
    for item in result.events:
        event, original = item.event, item.original
        events.append(
            {
                "event_on": item.event_on.isoformat(),
                "title": event.title,
                "event_type": event.event_type,
                "evidence_label": (
                    _EVIDENCE[event.evidence] if item.source_gap is None else "未知（来源待核验）"
                ),
                "lifecycle_label": _LIFECYCLE[event.lifecycle],
                "revision": event.revision,
                "source_published_at": (
                    event.source_published_at.isoformat() if event.source_published_at else None
                ),
                "source_published_on": (
                    event.source_published_on.isoformat() if event.source_published_on else None
                ),
                "available_at": event.available_at.isoformat(),
                "first_seen_at": event.first_seen_at.isoformat(),
                "recorded_at": event.recorded_at.isoformat(),
                "source_url": original.url if original else None,
                "original_sha256": event.original_sha256,
                "attribution": original.policy.attribution if original else "原文未核验",
                "source_status": (
                    "原文已核验；来源资格有效"
                    if item.source_gap is None
                    else _GAPS[item.source_gap]
                ),
                "known_at": result.known_at.isoformat(),
                "knowledge_mode": mode,
                "must_not_use_for_decision": True,
                "source_observed_at": None,
                "research_status": "研究未完成；仅参考，不可用于决策。",
            }
        )
    payload: dict[str, object] = {
        "status": {
            "known_at": result.known_at.isoformat(),
            "checked_at": result.checked_at.isoformat(),
            "source_valid_until": (
                result.policy.valid_until.isoformat() if result.policy is not None else None
            ),
            "knowledge_mode": mode,
            "source_status": (
                "来源资格有效"
                if result.policy is not None
                and not {"SOURCE_POLICY_EXPIRED", "SOURCE_POLICY_CHANGED"}.intersection(result.gaps)
                else "来源资格待复核"
            ),
            "gaps": " ".join(_GAPS[gap] for gap in result.gaps),
            "research_status": "研究未完成；仅供参考，不可用于投资或交易决策。",
            "must_not_use_for_decision": True,
        },
        "events": events,
        "windows": [
            {
                "start_date": window.start_date.isoformat(),
                "end_date": window.end_date.isoformat(),
                "category": window.category.value,
                "rule_version": window.rule_version,
                "calendar_note": "自然日窗口；国家统计局使用行政日历。未猜测交易日或将节假日移位。",
            }
            for window in result.windows
        ],
    }
    rows: list[dict[str, object]] = [
        {
            "row_kind": "来源与研究边界",
            "title": "本次查询的来源缺口与用途限制",
            "evidence_label": "来源核对",
            "source_status": " ".join(_GAPS[gap] for gap in result.gaps),
            "known_at": result.known_at.isoformat(),
            "knowledge_mode": mode,
            "research_status": "研究未完成；仅参考，不可用于投资或交易决策。",
            "must_not_use_for_decision": True,
        }
    ]
    calendar_rows: list[dict[str, object]] = [
        {
            "row_kind": "自然日窗口",
            "event_on": window.start_date.isoformat(),
            "end_date": window.end_date.isoformat(),
            "title": "六候自然日窗口 " + window.category.value,
            "event_type": "自然日观察窗口",
            "evidence_label": "规则派生",
            "lifecycle_label": "观察窗口",
            "source_status": "自然日划分；尚未对齐交易日，不推断市场行为。",
            "attribution": "规则版本 " + window.rule_version,
            "known_at": result.known_at.isoformat(),
            "knowledge_mode": mode,
            "research_status": "研究未完成；仅参考，不可用于决策。",
            "must_not_use_for_decision": True,
        }
        for window in result.windows
    ]
    calendar_rows.extend({**event, "row_kind": "官方发布"} for event in events)
    rows.extend(
        sorted(calendar_rows, key=lambda item: (str(item["event_on"]), str(item["row_kind"])))
    )
    payload["rows"] = rows
    return payload


__all__ = ["present_institutional_calendar"]
