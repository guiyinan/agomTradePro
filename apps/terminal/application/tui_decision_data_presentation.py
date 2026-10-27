"""Source-clock evidence and bounded TUI presentation for decision-data consumers.

The owner determines freshness and usability. This module validates shapes,
keeps independent source clocks and translates restrictions without querying,
comparing clocks or selecting a fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import TypedDict, cast

from apps.audit.domain.entities import mask_sensitive_text

from .tui_task_focus_result_contracts import (
    TuiTaskFocusField,
    TuiTaskFocusResult,
    TuiTaskFocusSection,
    TuiTaskFocusSectionRow,
)
from .tui_task_focus_result_contracts import blocked_task_result as _blocked
from .tui_task_focus_result_contracts import detail_task_result as _detail
from .tui_task_focus_result_contracts import display_task_scalar as _display_scalar
from .tui_task_focus_result_contracts import section_column as _column
from .tui_task_focus_result_contracts import section_preview_fields as _preview
from .tui_task_focus_result_contracts import section_row as _row
from .tui_task_focus_result_contracts import task_text as _text


def _required_text(value: object) -> str | None:
    """Read a required bounded string using the existing TUI contract."""

    return _text(value)


def _optional_string(value: object) -> str | None:
    """Preserve an optional owner string without substituting a source fact."""

    return None if value is None else _text(value, allow_empty=True)


_DECISION_DATA_BLOCKING_REASON_LABELS: dict[str, str] = {
    "quote_observation_from_future": "行情观测时间晚于本次判断时点，当前资料不可用于决策。",
    "quote_fetch_from_future": "行情抓取时间晚于本次判断时点，时间资料待核验，当前资料不可用于决策。",
}


_DECISION_DATA_FRESHNESS_LABELS: dict[str, str] = {
    "fresh": "已核验",
    "stale": "已过期",
    "future_observation": "观测时间待核验",
    "future_fetch": "抓取时间待核验",
    "unverified_observation": "来源时间未核验",
    "latest_completed_session": "最近已完成交易时段",
}


class DecisionDataEvidence(TypedDict):
    """Bounded presentation evidence without deriving source freshness."""

    must_not_use_for_decision: bool
    blocked_reasons: list[str]
    blocking_reason: str
    quote_evidence: list[DecisionQuoteEvidence]
    quote_source_times: str
    checked_at: str
    thermometer_observed_at: str | None
    thermometer_as_of_date: str | None
    thermometer_snapshot_date: str | None


def _decision_mapping(value: object) -> Mapping[str, object]:
    """Narrow decoded owner JSON at the presentation boundary."""

    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return cast(Mapping[str, object], value)
    return {}


def _decision_text(value: object) -> str:
    """Bound and redact an owner string without interpreting its meaning."""

    return mask_sensitive_text(value.strip())[:2_000] if isinstance(value, str) else ""


def _decision_clock(value: object) -> str | None:
    """Copy an available clock without inventing a date, timezone or fallback."""

    if isinstance(value, datetime):
        return value.isoformat() if value.utcoffset() is not None else None
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 128:
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return text if parsed.utcoffset() is not None else None


def _decision_reference_date(value: object) -> str | None:
    """Validate an owner date separately from timezone-aware observation clocks."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _decision_blocking_reason_label(value: str) -> str:
    """Translate known owner codes while keeping internal codes out of user copy."""

    text = _decision_text(value)
    for code, label in _DECISION_DATA_BLOCKING_REASON_LABELS.items():
        text = text.replace(code, label)
    candidate = text.rsplit(": ", 1)[-1]
    if "_" in candidate or (
        candidate
        and not any("一" <= character <= "鿿" for character in candidate)
        and " " not in candidate
    ):
        return "资料受限，当前不可用于决策；请重新读取，持续受限时请联系管理员。"
    return text


def build_decision_data_evidence(
    payload: Mapping[str, object], *, checked_at: datetime
) -> DecisionDataEvidence:
    """Project owner restrictions and separate clocks for the two decision consumers."""

    blocked = payload.get("must_not_use_for_decision") is not False
    invalid_shape = type(payload.get("must_not_use_for_decision")) is not bool
    raw_reasons = payload.get("blocked_reasons")
    if raw_reasons is not None and (
        not isinstance(raw_reasons, list)
        or any(not isinstance(reason, str) for reason in raw_reasons)
    ):
        invalid_shape = True
    reasons = (
        [_decision_text(item) for item in raw_reasons if isinstance(item, str)]
        if isinstance(raw_reasons, list)
        else []
    )
    quotes: list[DecisionQuoteEvidence] = []
    raw_quotes = payload.get("quotes")
    if (
        not isinstance(raw_quotes, Mapping)
        or any(not isinstance(key, str) for key in raw_quotes)
        or (payload.get("must_not_use_for_decision") is False and not raw_quotes)
    ):
        invalid_shape = True
    for asset_code, raw_quote in _decision_mapping(raw_quotes).items():
        quote = _decision_mapping(raw_quote)
        if not quote or type(quote.get("must_not_use_for_decision")) is not bool:
            invalid_shape = True
        code = _decision_text(asset_code)
        reason = _decision_text(quote.get("blocked_reason"))
        freshness_status = _decision_text(quote.get("freshness_status"))
        quote_blocked = quote.get("must_not_use_for_decision") is not False
        snapshot_at = _decision_clock(quote.get("snapshot_at"))
        fetched_at = _decision_clock(quote.get("fetched_at"))
        if any(
            quote.get(key) not in (None, "") and parsed_clock is None
            for key, parsed_clock in (("snapshot_at", snapshot_at), ("fetched_at", fetched_at))
        ):
            invalid_shape = True
        if not quote_blocked and (snapshot_at is None or fetched_at is None):
            invalid_shape = True
        if quote_blocked and payload.get("must_not_use_for_decision") is False:
            invalid_shape = True
        quotes.append(
            {
                "asset_code": code,
                "snapshot_at": snapshot_at,
                "fetched_at": fetched_at,
                "freshness_status": freshness_status,
                "freshness": _DECISION_DATA_FRESHNESS_LABELS.get(freshness_status, "时效未确认"),
                "must_not_use_for_decision": quote_blocked,
                "blocked_reason": reason,
                "blocking_reason": _decision_blocking_reason_label(reason)
                or ("资料受限，当前不可用于决策。" if quote_blocked else ""),
            }
        )
    displayed_reasons = [_decision_blocking_reason_label(reason) for reason in reasons if reason]
    for quote in quotes:
        if quote["must_not_use_for_decision"] and quote["blocking_reason"]:
            label = f"{quote['asset_code']}: {quote['blocking_reason']}"
            if label not in displayed_reasons:
                displayed_reasons.append(label)
    raw_thermometer = payload.get("market_thermometer")
    if not isinstance(raw_thermometer, Mapping) or (
        payload.get("must_not_use_for_decision") is False and not raw_thermometer
    ):
        invalid_shape = True
    if invalid_shape:
        blocked = True
        displayed_reasons.append("决策资料的使用限制未确认，当前不可用于决策。")
    if blocked and not displayed_reasons:
        displayed_reasons.append("资料受限，当前不可用于决策。")
    thermometer = _decision_mapping(raw_thermometer)
    return {
        "must_not_use_for_decision": blocked,
        "blocked_reasons": reasons,
        "blocking_reason": "；".join(displayed_reasons),
        "quote_evidence": quotes,
        "quote_source_times": "\n".join(
            f"{quote['asset_code']}｜观测：{quote['snapshot_at'] or '未提供'}｜抓取：{quote['fetched_at'] or '未提供'}｜时效：{quote['freshness']}｜限制：{quote['blocking_reason'] or ('不可用于决策' if quote['must_not_use_for_decision'] else '未标记限制')}"
            for quote in quotes
        )
        or "未提供逐证券报价来源资料",
        "checked_at": checked_at.isoformat(),
        "thermometer_observed_at": _decision_reference_date(thermometer.get("observed_at"))
        or _decision_clock(thermometer.get("observed_at")),
        "thermometer_as_of_date": _decision_reference_date(thermometer.get("as_of_date")),
        "thermometer_snapshot_date": _decision_reference_date(thermometer.get("snapshot_date")),
    }


_MAX_QUOTE_EVIDENCE = 100


_DECISION_ROW_MARKERS = frozenset(
    {
        "blocked_reasons",
        "checked_at",
        "quote_evidence",
        "quote_source_times",
        "thermometer_as_of_date",
        "thermometer_observed_at",
        "thermometer_snapshot_date",
    }
)


class DecisionQuoteEvidence(TypedDict):
    """Validated quote evidence; raw owner codes stay outside the result model."""

    asset_code: str
    snapshot_at: str | None
    fetched_at: str | None
    freshness_status: str
    freshness: str
    must_not_use_for_decision: bool
    blocked_reason: str | None
    blocking_reason: str


class DecisionMarketEvidence(TypedDict):
    """Validated decision-row values needed by the user-facing projection."""

    blocking_reason: str
    checked_at: str
    thermometer_observed_at: str | None
    thermometer_as_of_date: str | None
    thermometer_snapshot_date: str | None
    quote_evidence: list[DecisionQuoteEvidence]


def display_decision_clock(value: str | None) -> str:
    """Show an absent source clock as unknown without inventing a timestamp."""

    return value if value else "未提供"


def _validated_decision_quote(value: object) -> DecisionQuoteEvidence | None:
    """Narrow one decision quote while keeping owner codes out of display data."""

    data = _decision_mapping(value)
    if not data:
        return None
    required_keys = (
        "asset_code",
        "snapshot_at",
        "fetched_at",
        "freshness_status",
        "freshness",
        "must_not_use_for_decision",
        "blocked_reason",
        "blocking_reason",
    )
    if any(key not in data for key in required_keys):
        return None

    asset_code = _required_text(data.get("asset_code"))
    snapshot_value = data.get("snapshot_at")
    fetched_value = data.get("fetched_at")
    freshness_status = _text(data.get("freshness_status"), allow_empty=True)
    freshness = _required_text(data.get("freshness"))
    must_not_use = data.get("must_not_use_for_decision")
    blocked_reason_value = data.get("blocked_reason")
    blocking_reason = _text(data.get("blocking_reason"), allow_empty=True)
    if (
        asset_code is None
        or (snapshot_value is not None and not isinstance(snapshot_value, str))
        or (fetched_value is not None and not isinstance(fetched_value, str))
        or freshness_status is None
        or freshness is None
        or type(must_not_use) is not bool
        or (blocked_reason_value is not None and not isinstance(blocked_reason_value, str))
        or blocking_reason is None
        or (must_not_use is True and not blocking_reason)
    ):
        return None

    snapshot_at = _optional_string(snapshot_value)
    fetched_at = _optional_string(fetched_value)
    blocked_reason = _optional_string(blocked_reason_value)
    if (
        (snapshot_value is not None and snapshot_at is None)
        or (fetched_value is not None and fetched_at is None)
        or (blocked_reason_value is not None and blocked_reason is None)
    ):
        return None

    return {
        "asset_code": asset_code,
        "snapshot_at": snapshot_at,
        "fetched_at": fetched_at,
        "freshness_status": freshness_status,
        "freshness": freshness,
        "must_not_use_for_decision": must_not_use,
        "blocked_reason": blocked_reason,
        "blocking_reason": blocking_reason,
    }


def validate_decision_market_row(
    row: Mapping[str, object],
) -> DecisionMarketEvidence | None:
    """Validate the decision-row contract without interpreting its time values."""

    required_keys = (
        "must_not_use_for_decision",
        "blocking_reason",
        "blocked_reasons",
        "checked_at",
        "observed_at",
        "thermometer_observed_at",
        "thermometer_as_of_date",
        "thermometer_snapshot_date",
        "quote_evidence",
    )
    if any(key not in row for key in required_keys):
        return None

    must_not_use = row.get("must_not_use_for_decision")
    blocking_reason = _text(row.get("blocking_reason"), allow_empty=True)
    blocked_reasons = row.get("blocked_reasons")
    checked_at = _text(row.get("checked_at"), allow_empty=True)
    observed_at = row.get("observed_at")
    thermometer_observed_at_value = row.get("thermometer_observed_at")
    thermometer_as_of_date_value = row.get("thermometer_as_of_date")
    thermometer_snapshot_date_value = row.get("thermometer_snapshot_date")
    raw_quotes = row.get("quote_evidence")

    if (
        type(must_not_use) is not bool
        or blocking_reason is None
        or (must_not_use is True and not blocking_reason)
        or not isinstance(blocked_reasons, list)
        or len(blocked_reasons) > _MAX_QUOTE_EVIDENCE
        or any(_required_text(reason) is None for reason in blocked_reasons)
        or checked_at is None
        or observed_at != ""
        or not isinstance(raw_quotes, list)
        or len(raw_quotes) > _MAX_QUOTE_EVIDENCE
    ):
        return None

    thermometer_observed_at = _optional_string(thermometer_observed_at_value)
    thermometer_as_of_date = _optional_string(thermometer_as_of_date_value)
    thermometer_snapshot_date = _optional_string(thermometer_snapshot_date_value)
    if (
        (thermometer_observed_at_value is not None and thermometer_observed_at is None)
        or (thermometer_as_of_date_value is not None and thermometer_as_of_date is None)
        or (thermometer_snapshot_date_value is not None and thermometer_snapshot_date is None)
    ):
        return None

    if "quote_source_times" in row:
        quote_source_times = row.get("quote_source_times")
        if quote_source_times is not None and not isinstance(quote_source_times, str):
            return None

    quote_evidence: list[DecisionQuoteEvidence] = []
    for raw_quote in raw_quotes:
        quote = _validated_decision_quote(raw_quote)
        if quote is None:
            return None
        quote_evidence.append(quote)

    return {
        "blocking_reason": blocking_reason,
        "checked_at": checked_at,
        "thermometer_observed_at": thermometer_observed_at,
        "thermometer_as_of_date": thermometer_as_of_date,
        "thermometer_snapshot_date": thermometer_snapshot_date,
        "quote_evidence": quote_evidence,
    }


def decision_quote_section(
    evidence: list[DecisionQuoteEvidence],
) -> TuiTaskFocusSection:
    """Project each quote's own clocks and friendly restriction into one section."""

    rows: list[TuiTaskFocusSectionRow] = []
    for quote in evidence:
        restriction = "不可用于决策" if quote["must_not_use_for_decision"] else "未标记不可用于决策"
        rows.append(
            _row(
                [
                    {"key": "asset_code", "label": "证券", "value": quote["asset_code"]},
                    {
                        "key": "snapshot_at",
                        "label": "行情观测时间",
                        "value": display_decision_clock(quote["snapshot_at"]),
                    },
                    {
                        "key": "fetched_at",
                        "label": "行情抓取时间",
                        "value": display_decision_clock(quote["fetched_at"]),
                    },
                    {"key": "freshness", "label": "行情时效", "value": quote["freshness"]},
                    {
                        "key": "must_not_use_for_decision",
                        "label": "决策使用限制",
                        "value": restriction,
                    },
                    {
                        "key": "blocking_reason",
                        "label": "限制说明",
                        "value": display_decision_clock(quote["blocking_reason"]),
                    },
                ]
            )
        )
    return {
        "key": "quote_evidence",
        "label": "逐只证券行情证据",
        "columns": [
            _column("asset_code", "证券"),
            _column("snapshot_at", "行情观测时间"),
            _column("fetched_at", "行情抓取时间"),
            _column("freshness", "行情时效"),
            _column("must_not_use_for_decision", "决策使用限制"),
            _column("blocking_reason", "限制说明"),
        ],
        "rows": rows,
        "restriction_message": "行情观测时间和抓取时间按证券分别显示，未合成为统一时间。",
    }


def is_decision_market_row(row: Mapping[str, object]) -> bool:
    """Recognize both current evidence rows and an unsupported cached aggregate."""

    return row.get("area") == "决策数据" or any(key in row for key in _DECISION_ROW_MARKERS)


_MAX_MARKET_ROWS = 12


def _nonnegative_int(value: object) -> int | None:
    """Accept only an exact non-negative owner count."""

    return value if type(value) is int and value >= 0 else None


def build_market_context_detail(
    data: Mapping[str, object], *, outcome: str | None
) -> TuiTaskFocusResult:
    """Render a validated market envelope with each source clock kept separate."""

    raw_rows = data.get("rows")
    total = _nonnegative_int(data.get("total"))
    if (
        not isinstance(raw_rows, list)
        or total is None
        or total != len(raw_rows)
        or total > _MAX_MARKET_ROWS
    ):
        return _blocked("市场环境", "市场环境返回格式无法识别。", "市场环境行列表形状不受支持。")

    rows: list[TuiTaskFocusSectionRow] = []
    blocked_rows = 0
    owner_restrictions: list[str] = []
    decision_clock_fields: list[TuiTaskFocusField] = []
    quote_evidence: list[DecisionQuoteEvidence] = []
    has_decision_row = False
    for raw_row in raw_rows:
        row = _decision_mapping(raw_row)
        if not row:
            return _blocked("市场环境", "市场环境返回格式无法识别。", "市场环境行形状不受支持。")
        area = _required_text(row.get("area"))
        status = _required_text(row.get("status"))
        if area is None or status is None:
            return _blocked("市场环境", "市场环境返回格式无法识别。", "市场环境行缺少范围或状态。")
        severity = _text(row.get("severity"), allow_empty=True) or "未提供"
        is_decision_row = is_decision_market_row(row)
        decision_evidence = validate_decision_market_row(row) if is_decision_row else None
        if is_decision_row and decision_evidence is None:
            return _blocked(
                "市场环境",
                "市场环境返回格式无法识别。",
                "决策资料或单只证券行情证据形状不受支持。",
            )
        if decision_evidence is not None:
            has_decision_row = True
            quote_evidence.extend(decision_evidence["quote_evidence"])
            decision_clock_fields.extend(
                [
                    {
                        "key": "checked_at",
                        "label": "检查时间",
                        "value": display_decision_clock(decision_evidence["checked_at"]),
                    },
                    {
                        "key": "thermometer_observed_at",
                        "label": "温度计观测时间",
                        "value": display_decision_clock(
                            decision_evidence["thermometer_observed_at"]
                        ),
                    },
                    {
                        "key": "thermometer_as_of_date",
                        "label": "温度计数据基准日",
                        "value": display_decision_clock(
                            decision_evidence["thermometer_as_of_date"]
                        ),
                    },
                    {
                        "key": "thermometer_snapshot_date",
                        "label": "温度计快照日期",
                        "value": display_decision_clock(
                            decision_evidence["thermometer_snapshot_date"]
                        ),
                    },
                ]
            )
        must_not_use = row.get("must_not_use_for_decision")
        if must_not_use is not None and type(must_not_use) is not bool:
            return _blocked(
                "市场环境", "市场环境返回格式无法识别。", "市场环境限制字段形状不受支持。"
            )
        if severity.lower() == "blocked" or must_not_use is True:
            if (
                decision_evidence is not None
                and severity.lower() == "blocked"
                and not decision_evidence["blocking_reason"]
            ):
                return _blocked(
                    "市场环境",
                    "市场环境返回格式无法识别。",
                    "受限决策资料缺少可展示的使用说明。",
                )
            blocked_rows += 1
            restriction = "不可用于决策" if must_not_use is True else "已受阻"
            blocking_reason = (
                decision_evidence["blocking_reason"]
                if decision_evidence is not None
                else _display_scalar(row.get("blocking_reason"))
            )
            owner_restrictions.append(f"{area}（{restriction}）：{blocking_reason}")
        market_fields: list[TuiTaskFocusField] = [
            {"key": "area", "label": "范围", "value": area},
            {"key": "status", "label": "状态", "value": status},
            {
                "key": "freshness",
                "label": "时效",
                "value": _display_scalar(row.get("freshness")),
            },
            {
                "key": "reliability",
                "label": "可靠性",
                "value": _display_scalar(row.get("reliability")),
            },
            {
                "key": "summary",
                "label": "摘要",
                "value": _display_scalar(row.get("summary")),
            },
            {
                "key": "observed_at",
                "label": "观测时间",
                "value": _display_scalar(row.get("observed_at")),
            },
            {
                "key": "blocking_reason",
                "label": "限制说明",
                "value": (
                    decision_evidence["blocking_reason"] or "未提供"
                    if decision_evidence is not None
                    else _display_scalar(row.get("blocking_reason"))
                ),
            },
            {
                "key": "must_not_use_for_decision",
                "label": "使用限制",
                "value": (
                    "不可用于决策"
                    if must_not_use is True and decision_evidence is not None
                    else (
                        "未标记不可用于决策"
                        if must_not_use is False and decision_evidence is not None
                        else _display_scalar(must_not_use)
                    )
                ),
            },
        ]
        rows.append(_row(market_fields))

    summary = (
        f"已读取 {total} 条市场环境事实，其中 {blocked_rows} 条带有使用限制；各条目保留自身观测时间，未合成为统一时点。"
        if total
        else "当前没有市场环境条目；未生成市场结论。"
    )
    if owner_restrictions:
        summary += " 受限范围与原因：" + "；".join(owner_restrictions) + "。"
    market_section: TuiTaskFocusSection = {
        "key": "market_context",
        "label": "市场环境记录",
        "columns": [
            _column("area", "范围"),
            _column("status", "状态"),
            _column("freshness", "时效"),
            _column("reliability", "可靠性"),
            _column("summary", "摘要"),
            _column("observed_at", "观测时间"),
            _column("blocking_reason", "限制说明"),
            _column("must_not_use_for_decision", "使用限制"),
        ],
        "rows": rows,
    }
    sections: list[TuiTaskFocusSection] = [market_section]
    if has_decision_row:
        sections.append(
            {
                "key": "decision_timing",
                "label": "检查与温度计时间",
                "fields": decision_clock_fields,
            }
        )
        sections.append(decision_quote_section(quote_evidence))

    return _detail(
        title="今日市场环境事实",
        fields=[
            {"key": "market_count", "label": "市场环境记录数", "value": str(total)},
            *_preview(
                rows,
                "market",
                "area",
                ("status", "observed_at", "freshness", "reliability", "must_not_use_for_decision"),
                4,
            ),
            *decision_clock_fields,
            {
                "key": "market_time_limit",
                "label": "时间限制",
                "value": "各条目保留自身观测时间，未合成为统一时点。",
            },
        ],
        nested=[{"key": "market_context", "label": "市场环境条目", "count": total}],
        summary=summary,
        next_steps=[],
        owner_status=_text(data.get("status")),
        outcome=outcome,
        sections=sections,
    )
