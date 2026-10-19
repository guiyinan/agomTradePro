"""Present published pool read restrictions without changing source qualification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

_POOL_ACTION_KEYS = frozenset(
    {"equity.pool-summary", "equity.pool-list", "equity.pool-sector-distribution"}
)
_SUMMARY_FIELDS = (
    ("restriction_message", "使用范围"),
    ("requested_count", "本次请求股票数"),
    ("blocked_count", "估值资料受限股票数"),
    ("avg_roe", "平均 ROE"),
    ("avg_pe", "平均 PE"),
    ("regime", "市场环境"),
    ("update_time", "更新时间"),
)


def project_equity_pool_view_model(
    *,
    action_key: str,
    payload: object,
    view_model: Mapping[str, object],
    http_status: int,
) -> dict[str, object]:
    """Keep pool usage limits visible on the existing read-task result models.

    This projection formats an owner's result. It does not validate publication
    evidence or grant decision permission. Other actions and transport errors
    retain their existing presentation.
    """

    model = dict(view_model)
    if action_key not in _POOL_ACTION_KEYS or not 200 <= http_status < 300:
        return model
    envelope = _mapping(payload)
    if envelope is None or envelope.get("mode") == "historical":
        return model
    outcome = _text(envelope.get("outcome"))
    state = _text(envelope.get("status"))
    uncertain = outcome not in {"success", "partial", "blocked", "failed"}
    if uncertain:
        if (
            state not in {"partial", "blocked"}
            and envelope.get("must_not_use_for_decision") is not True
        ):
            return model
        outcome = "blocked"

    blocked = outcome in {"blocked", "failed"} or envelope.get("success") is False
    partial = outcome == "partial"
    restricted = blocked or partial or envelope.get("must_not_use_for_decision") is True
    message = _text(envelope.get("restriction_message"))
    if restricted and (uncertain or not message):
        if uncertain or (outcome == "success" and restricted):
            message = "股票池资料状态无法确认，当前结果不可用于决策。"
        elif blocked:
            message = "当前股票池资料不可用，请补齐资料后重试。"
        else:
            message = "部分估值资料不可用，完整股票池仅供观察，暂不用于决策。"
    if not restricted:
        message = ""

    model["outcome"] = outcome
    owner_restriction = envelope.get("must_not_use_for_decision")
    if restricted:
        model["must_not_use_for_decision"] = True
    elif isinstance(owner_restriction, bool):
        model["must_not_use_for_decision"] = owner_restriction
    if restricted:
        model["status"] = "不可用于决策" if outcome != "failed" else "读取失败"
        model["business_summary"] = message
        model["blocking_reason"] = message
        if str(model.get("kind") or "") != "detail":
            title = _text(model.get("title")) or "股票池"
            model["title"] = f"{title} · {message}"
    else:
        known_count = envelope.get("requested_count")
        scope_text = (
            f"；本次读取 {known_count} 只股票"
            if type(known_count) is int and known_count >= 0
            else ""
        )
        model["business_summary"] = f"股票池资料已发布{scope_text}。"
        model["blocking_reason"] = ""

    if str(model.get("kind") or "") == "detail":
        model["fields"] = _summary_fields(envelope, model.get("fields"), message)
        model["nested"] = []
    if blocked:
        model["empty_message"] = message
        model["empty_guidance"] = ["先核对资料缺口，再重新读取股票池。"]
        if str(model.get("kind") or "") == "datagrid":
            model["rows"] = []
            old_pager = _mapping(model.get("pager"))
            pager = dict(old_pager) if old_pager is not None else {}
            pager.update(total_rows=0, total_pages=1, has_next=False, has_previous=False)
            model["pager"] = pager

    hidden = model.get("debug_hidden_fields")
    hidden_keys = (
        [value for value in hidden if isinstance(value, str)] if isinstance(hidden, list) else []
    )
    model["debug_hidden_fields"] = list(
        dict.fromkeys(
            [*hidden_keys, "outcome", "blocked_reason", "publication_gates", "source_times"]
        )
    )
    return model


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow a JSON mapping before inspecting owner or result-model fields."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _text(value: object) -> str:
    """Retain only explicit text; do not stringify metadata mappings."""

    return value.strip() if isinstance(value, str) else ""


def _summary_fields(
    envelope: Mapping[str, object], old_fields: object, message: str
) -> list[dict[str, str]]:
    """Place the usage warning and known scope counts before detail overflow."""

    displayed: dict[str, str] = {}
    if isinstance(old_fields, list):
        for value in old_fields:
            field = _mapping(value)
            if field is None:
                continue
            key = _text(field.get("key"))
            text = _text(field.get("value"))
            if key and text:
                displayed[key] = text
    fields: list[dict[str, str]] = []
    for key, label in _SUMMARY_FIELDS:
        raw = envelope.get(key)
        if key == "restriction_message":
            value = message or "-"
        elif key in {"requested_count", "blocked_count"}:
            value = str(raw) if type(raw) is int and raw >= 0 else "未提供"
        elif key in displayed:
            value = displayed[key]
        elif raw is None:
            value = "-"
        elif isinstance(raw, str | int | float) and not isinstance(raw, bool):
            value = str(raw)
        else:
            value = "未提供"
        fields.append({"key": key, "label": label, "value": value, "presentation": "metadata"})
    return fields
