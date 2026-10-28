"""Portable output contracts and bounded scalar encoding for TUX-09 results.

This module contains only view-model types and display-safe scalar helpers.
Task-specific response validation remains in ``tui_task_focus_result`` so this
contract can be reused by the workbench boundary without importing an owner,
ORM, provider, or renderer implementation.
"""

from __future__ import annotations

import math
from typing import Literal, NotRequired, TypedDict

from .tui_workbench_constants import VALUE_LABELS

TaskStatus = Literal["已读取", "已阻断"]
TaskScreenKey = Literal["command-center.decision-flow", "execution.accounts"]
TaskActionKey = Literal[
    "auto.api.get.api.decision.workspace.recommendations",
    "account.portfolio-recorded-facts",
]
TaskOutcome = Literal["success", "partial", "noop", "blocked", "failed"]


class TuiTaskFocusField(TypedDict):
    """One existing detail field with a bounded display value."""

    key: str
    label: str
    value: str


class TuiTaskFocusNested(TypedDict):
    """One existing detail nested-count entry."""

    key: str
    label: str
    count: int


class TuiTaskFocusColumn(TypedDict):
    """One column in an existing expandable detail section."""

    key: str
    label: str


class TuiTaskFocusSectionRow(TypedDict):
    """One bounded section row made from existing detail fields."""

    fields: list[TuiTaskFocusField]


class TuiTaskFocusSection(TypedDict, total=False):
    """A typed optional section consumed by the generic detail renderer."""

    key: str
    label: str
    columns: list[TuiTaskFocusColumn]
    rows: list[TuiTaskFocusSectionRow]
    fields: list[TuiTaskFocusField]
    restriction_message: str


class TuiTaskFocusPager(TypedDict):
    """Server-page facts retained by the generic datagrid pager."""

    client_side: Literal[False]
    pagination_mode: Literal["page"]
    page: int
    page_size: int
    total_rows: int
    total_pages: int
    has_previous: bool
    has_next: bool


class TuiTaskFocusParams(TypedDict, total=False):
    """Prevalidated integer parameters safe for a user-selected next step."""

    account_id: int
    pk: int


class TuiTaskFocusProfessionalTarget(TypedDict):
    """A closed, already-authorized professional target supplied by a caller."""

    screen_key: TaskScreenKey
    action_key: TaskActionKey
    label: NotRequired[str]
    hint: NotRequired[str]


class TuiTaskFocusNextStep(TypedDict):
    """An existing next-step target, never auto-executed here."""

    label: str
    hint: str
    screen_key: TaskScreenKey
    action_key: TaskActionKey
    params: TuiTaskFocusParams


class TuiTaskFocusDetailView(TypedDict):
    """Existing detail view used for successful task projections."""

    kind: Literal["detail"]
    title: str
    status: str
    fields: list[TuiTaskFocusField]
    nested: list[TuiTaskFocusNested]
    business_summary: str
    blocking_reason: str
    next_steps: list[TuiTaskFocusNextStep]
    debug_hidden_fields: list[str]
    owner_status: NotRequired[str]
    outcome: NotRequired[str]
    sections: NotRequired[list[TuiTaskFocusSection]]
    pager: NotRequired[TuiTaskFocusPager]


class TuiTaskFocusMessageView(TypedDict):
    """Existing bounded message view for failed transport or owner shape."""

    kind: Literal["message"]
    title: str
    status: Literal["已阻断"]
    message: str
    outcome: Literal["blocked"]
    blocking_reason: str
    business_summary: str
    next_steps: list[TuiTaskFocusNextStep]
    raw_hint: str
    owner_outcome: NotRequired[str]


TuiTaskFocusResult = TuiTaskFocusDetailView | TuiTaskFocusMessageView

_MAX_TEXT = 240


def task_text(value: object, *, allow_empty: bool = False) -> str | None:
    """Return bounded service text, refusing non-text values."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized and not allow_empty:
        return None
    if len(normalized) <= _MAX_TEXT:
        return normalized
    return f"{normalized[: _MAX_TEXT - 1]}…"


def display_task_scalar(value: object) -> str:
    """Display a scalar while preserving zero and making null explicit."""

    if value is None:
        return "未提供"
    if type(value) is bool:
        return "是" if value else "否"
    if isinstance(value, str):
        return task_text(value, allow_empty=True) or "未提供"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else "未提供"
    return "未提供"


def section_row(fields: list[TuiTaskFocusField]) -> TuiTaskFocusSectionRow:
    """Wrap validated fields in the existing expandable-row shape."""

    return {"fields": fields}


def section_column(key: str, label: str) -> TuiTaskFocusColumn:
    """Build one portable section column."""

    return {"key": key, "label": label}


def section_preview_fields(
    rows: list[TuiTaskFocusSectionRow],
    prefix: str,
    heading_key: str,
    value_keys: tuple[str, ...],
    limit: int,
) -> list[TuiTaskFocusField]:
    """Keep a bounded first-screen preview; full facts remain in sections."""

    fields: list[TuiTaskFocusField] = []
    for index, row in enumerate(rows[:limit]):
        by_key = {field["key"]: field for field in row["fields"]}
        heading = by_key[heading_key]["value"]
        parts: list[str] = []
        for key in value_keys:
            value = by_key[key]["value"]
            if key == "status":
                value = {"UNKNOWN": "未知", "NO_DATA": "暂无数据"}.get(
                    value, VALUE_LABELS.get(value.lower(), value)
                )
            parts.append(f"{by_key[key]['label']}：{value}")
        fields.append(
            {
                "key": f"{prefix}_preview_{index}",
                "label": heading,
                "value": task_text("；".join(parts)) or "未提供",
            }
        )
    return fields


def blocked_task_result(
    title: str,
    message: str,
    reason: str,
    *,
    owner_outcome: str | None = None,
) -> TuiTaskFocusMessageView:
    """Build a bounded message without copying an error or prior data."""

    view: TuiTaskFocusMessageView = {
        "kind": "message",
        "title": title,
        "status": "已阻断",
        "message": message,
        "outcome": "blocked",
        "blocking_reason": reason,
        "business_summary": "本次读取未形成可展示事实，未保留上一条结果。",
        "next_steps": [],
        "raw_hint": "原始响应仅在受控调试信息中查看。",
    }
    if isinstance(owner_outcome, str) and owner_outcome in {
        "success",
        "partial",
        "noop",
        "blocked",
        "failed",
    }:
        view["owner_outcome"] = owner_outcome
    return view


def detail_task_result(
    *,
    title: str,
    fields: list[TuiTaskFocusField],
    nested: list[TuiTaskFocusNested],
    summary: str,
    next_steps: list[TuiTaskFocusNextStep],
    owner_status: str | None = None,
    outcome: str | None = None,
    sections: list[TuiTaskFocusSection] | None = None,
    pager: TuiTaskFocusPager | None = None,
) -> TuiTaskFocusDetailView:
    """Build the existing detail view and preserve service metadata."""

    status = {
        "success": "已读取",
        "partial": "部分读取",
        "noop": "未产生记录",
        "blocked": "已阻断",
        "failed": "读取失败",
    }.get(outcome or "", "结果状态未提供")
    if outcome == "success":
        summary_with_outcome = summary
    elif outcome == "partial":
        summary_with_outcome = f"{summary} 结果状态为部分读取，未覆盖的范围仍需保留限制。"
    elif outcome == "noop":
        summary_with_outcome = f"{summary} 结果状态为未产生记录。"
    else:
        summary_with_outcome = f"{summary} 结果状态未提供，不能据此判断完整性。"
    view: TuiTaskFocusDetailView = {
        "kind": "detail",
        "title": title,
        "status": status,
        "fields": fields,
        "nested": nested,
        "business_summary": summary_with_outcome,
        "blocking_reason": "",
        "next_steps": next_steps,
        "debug_hidden_fields": ["raw_service_response", "service_error_detail"],
    }
    if owner_status is not None:
        view["owner_status"] = owner_status
    if outcome is not None:
        view["outcome"] = outcome
    if sections:
        view["sections"] = sections
    if pager is not None:
        view["pager"] = pager
    return view


__all__ = [
    "TaskActionKey",
    "TaskOutcome",
    "TaskScreenKey",
    "TaskStatus",
    "blocked_task_result",
    "detail_task_result",
    "TuiTaskFocusColumn",
    "TuiTaskFocusDetailView",
    "TuiTaskFocusField",
    "TuiTaskFocusMessageView",
    "TuiTaskFocusNested",
    "TuiTaskFocusNextStep",
    "TuiTaskFocusPager",
    "TuiTaskFocusParams",
    "TuiTaskFocusProfessionalTarget",
    "TuiTaskFocusResult",
    "TuiTaskFocusSection",
    "TuiTaskFocusSectionRow",
    "display_task_scalar",
    "task_text",
]
