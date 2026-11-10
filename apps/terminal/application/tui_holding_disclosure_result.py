"""Owner-safe presentation of published financial facts for a held security."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_ACTION_KEY = "simulated-trading.holding-disclosures"
_COVERAGE_FALLBACK = "来源范围仅包括当前已发布的财务指标，不等于完整公告、修订历史或公司行为覆盖。"
_INCOMPLETE_NOTE = "资料范围不完整，来源覆盖不完整：仅展示当前已发布的财务指标。"
_RESTRICTION_NOTE = (
    "本结果仅供查阅，不用于投资决策或交易执行；不推断公司行为生效日或到账日，"
    "不会计算、分配或入账现金、股份及税费。"
)
_EMPTY_NOTE = "当前已发布资料没有返回可核对的财务指标；不能据此判断证券没有相关披露。"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def project_tui_holding_disclosure_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Project a matching, read-only disclosure response into a bounded user view."""

    if action_key != _ACTION_KEY:
        return _blocked("无法识别这项资料查询。")
    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _blocked("读取状态无法核对；未显示披露资料。")
    requested_scope = _requested_scope(requested_params)
    if requested_scope is None:
        return _blocked("缺少本次账户或证券范围；未显示披露资料。")
    if not 200 <= http_status < 300:
        return _blocked(_http_failure_message(http_status))

    response = _as_mapping(payload)
    if response is None:
        return _blocked("返回内容无法核对；未显示披露资料。")
    outcome = response.get("outcome")
    if outcome == "blocked":
        return _blocked("财务资料来源当前受阻，未返回可核对资料。")
    if outcome != "partial":
        return _blocked("资料范围或使用限制无法核对；未显示披露资料。")
    if (
        _positive_int(response.get("account_id")) != requested_scope[0]
        or _asset_code(response.get("asset_code")) != requested_scope[1]
        or response.get("scope") != "simulation_only"
        or response.get("read_only") is not True
        or response.get("must_not_use_for_decision") is not True
        or response.get("must_not_execute") is not True
    ):
        return _blocked("账户、证券或只读范围不匹配；未显示披露资料。")

    raw_rows = response.get("rows")
    if not isinstance(raw_rows, list):
        return _blocked("资料列表格式无法核对；未显示披露资料。")
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        row = _as_mapping(raw_row)
        if row is None or _asset_code(row.get("asset_code")) != requested_scope[1]:
            return _blocked("披露资料中的证券范围无法核对；未显示本次结果。")
        metric_code = _readable_identifier(row.get("metric_code"))
        if metric_code is None:
            return _blocked("财务指标名称无法核对；未显示本次结果。")
        rows.append(
            _table_row(
                {
                    "metric": metric_code,
                    "value": _value_text(row.get("value")),
                    "unit": _simple_text(row.get("unit")) or "未提供",
                    "period_type": _readable_identifier(row.get("period_type")) or "未提供",
                    "period_end": _date_text(row.get("period_end")),
                    "report_date": _date_text(row.get("report_date")),
                    "announced_at": _source_time_text(row.get("announced_at")),
                    "available_at": _source_time_text(row.get("available_at")),
                    "fetched_at": _source_time_text(row.get("fetched_at")),
                    "source": _source_text(row.get("source")),
                }
            )
        )

    account_id, asset_code = requested_scope
    coverage_note = _safe_user_note(response.get("coverage_note")) or _COVERAGE_FALLBACK
    summary_parts = [_INCOMPLETE_NOTE, coverage_note, _RESTRICTION_NOTE]
    if not rows:
        summary_parts.append(_EMPTY_NOTE)
    return {
        "kind": "detail",
        "title": "持仓证券财报披露资料核对",
        "status": "已读取部分资料",
        "outcome": "partial",
        "business_summary": " ".join(summary_parts),
        "blocking_reason": "",
        "empty_message": _EMPTY_NOTE,
        "empty_guidance": ["请确认账户和证券代码，并查看来源覆盖说明。"],
        "fields": [
            _field("account_id", "模拟账户编号", account_id),
            _field("asset_code", "持仓证券", asset_code),
            _field("freshness", "资料新鲜度（来源标注）", _status_text(response.get("freshness"))),
            _field(
                "reliability", "资料可靠性（来源标注）", _status_text(response.get("reliability"))
            ),
            _field("read_at", "本次读取时间", _source_time_text(response.get("as_of"))),
        ],
        "nested": [],
        "next_steps": [],
        "sections": [
            {
                "key": "published_financial_facts",
                "label": "当前已发布的财务指标",
                "body": [_EMPTY_NOTE] if not rows else [],
                "columns": [
                    {"key": "metric", "label": "财务指标"},
                    {"key": "value", "label": "数值"},
                    {"key": "unit", "label": "单位"},
                    {"key": "period_type", "label": "报告期类型"},
                    {"key": "period_end", "label": "报告期截止日"},
                    {"key": "report_date", "label": "报告日期"},
                    {"key": "announced_at", "label": "源公告时间"},
                    {"key": "available_at", "label": "资料可用时间"},
                    {"key": "fetched_at", "label": "资料采集时间"},
                    {"key": "source", "label": "数据来源"},
                ],
                "rows": rows,
                "restriction_message": _RESTRICTION_NOTE,
            }
        ],
        "debug_hidden_fields": [],
    }


def _blocked(message: str) -> dict[str, Any]:
    """Clear all facts after a failed, mismatched or unbounded read."""

    return {
        "kind": "detail",
        "title": "持仓证券财报披露资料核对",
        "status": "未能核对资料",
        "outcome": "blocked",
        "business_summary": message,
        "blocking_reason": message,
        "fields": [],
        "nested": [],
        "next_steps": [],
        "sections": [],
        "debug_hidden_fields": [],
    }


def _http_failure_message(http_status: int) -> str:
    """Return safe scope or source copy without repeating an API error payload."""

    if http_status in {400, 422}:
        return "证券代码或查询范围有误；请重新核对本人模拟账户和持仓证券。"
    if http_status in {401, 403, 404}:
        return "账户或持仓范围无法确认；请确认这是本人有权查看且仍持有的模拟账户与证券。"
    if http_status >= 500:
        return "财务资料读取失败；未返回可核对的披露资料，请稍后重试。"
    return "本次资料读取未完成；未显示披露资料。"


def _requested_scope(
    params: Mapping[str, object] | None,
) -> tuple[int, str] | None:
    """Require one exact positive account and security selection."""

    if params is None:
        return None
    account_id = _positive_int(params.get("account_id"))
    asset_code = _asset_code(params.get("asset_code"))
    if account_id is None or asset_code is None:
        return None
    return account_id, asset_code


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Accept a JSON object with string keys only."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        return None
    return value


def _positive_int(value: object) -> int | None:
    """Parse an exact positive account identifier without accepting booleans."""

    if type(value) is int and value > 0:
        return value
    if type(value) is str and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _asset_code(value: object) -> str | None:
    """Normalize one bounded security code for exact scope comparison."""

    if type(value) is not str:
        return None
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > 32
        or any(character.isspace() for character in normalized)
    ):
        return None
    return normalized


def _simple_text(value: object) -> str | None:
    """Return bounded text values while excluding structured or control data."""

    if type(value) is not str:
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 200
        or any(ord(character) < 32 for character in normalized)
    ):
        return None
    return normalized


def _safe_user_note(value: object) -> str | None:
    """Keep owner-provided scope prose while filtering routes and address-like values."""

    text = _simple_text(value)
    if text is None or "/api/" in text.lower() or "://" in text or "\\" in text:
        return None
    return text[:500]


def _readable_identifier(value: object) -> str | None:
    """Humanize separators in a source metric name without inventing its meaning."""

    text = _simple_text(value)
    if text is None or "/" in text or "\\" in text or "://" in text:
        return None
    return re.sub(r"[_-]+", " ", text).strip().title()


def _value_text(value: object) -> str:
    """Retain source numeric text and never format values as inferred cash or shares."""

    if value is None:
        return "未提供"
    if type(value) is float and not math.isfinite(value):
        return "未知"
    if type(value) in {str, int, float}:
        text = str(value)
        return text if len(text) <= 128 else "未知"
    if isinstance(value, Decimal):
        if not value.is_finite():
            return "未知"
        text = str(value)
        return text if len(text) <= 128 else "未知"
    return "未知"


def _date_text(value: object) -> str:
    """Preserve date-only report and period values without adding a clock."""

    if isinstance(value, datetime):
        return "未知"
    if isinstance(value, date):
        return value.isoformat()
    if type(value) is str and _DATE_PATTERN.fullmatch(value):
        try:
            return value if date.fromisoformat(value).isoformat() == value else "未知"
        except ValueError:
            return "未知"
    return "未提供" if value is None else "未知"


def _source_time_text(value: object) -> str:
    """Retain valid source dates or offset-bearing timestamps without conversion."""

    if value is None:
        return "未提供"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return "未知"
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if type(value) is not str:
        return "未知"
    if _DATE_PATTERN.fullmatch(value):
        try:
            return value if date.fromisoformat(value).isoformat() == value else "未知"
        except ValueError:
            return "未知"
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except (OverflowError, TypeError, ValueError):
        return "未知"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "未知"
    return value


def _status_text(value: object) -> str:
    """Show only the source-owned freshness or reliability label."""

    text = _simple_text(value)
    if text is not None and text.casefold() == "unknown":
        return "未知"
    return _readable_identifier(text) or "未知"


def _source_text(value: object) -> str:
    """Show a readable source name while excluding endpoints and record IDs."""

    text = _simple_text(value)
    if text is None or "/" in text or "\\" in text or "://" in text:
        return "未提供"
    if len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text):
        return "未提供"
    return re.sub(r"[_-]+", " ", text).strip().title()


def _field(key: str, label: str, value: object) -> dict[str, object]:
    """Build one safe detail field."""

    return {"key": key, "label": label, "value": value}


def _table_row(values: Mapping[str, object]) -> dict[str, object]:
    """Build one explicit table row from the approved display columns only."""

    labels = {
        "metric": "财务指标",
        "value": "数值",
        "unit": "单位",
        "period_type": "报告期类型",
        "period_end": "报告期截止日",
        "report_date": "报告日期",
        "announced_at": "源公告时间",
        "available_at": "资料可用时间",
        "fetched_at": "资料采集时间",
        "source": "数据来源",
    }
    return {
        "fields": [
            {"key": key, "label": labels[key], "value": value}
            for key, value in values.items()
            if key in labels
        ]
    }


__all__ = ("project_tui_holding_disclosure_result",)
