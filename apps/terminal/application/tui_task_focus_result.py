"""Pure TUI projections for bounded TUX-09 task read actions.

Account applications remain responsible for authentication, authorization,
querying, and business outcome semantics.  This module only validates an
already-decoded response and turns selected facts into existing detail and
message view-model shapes.  It never fetches, retries, fills a default
account, infers a currency, or treats a record clock as a source clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from shared.numeric import safe_float

from .tui_decision_data_presentation import build_market_context_detail
from .tui_task_focus_result_contracts import (
    TaskActionKey,
    TaskOutcome,
    TaskScreenKey,
    TaskStatus,
    TuiTaskFocusColumn,
    TuiTaskFocusDetailView,
    TuiTaskFocusField,
    TuiTaskFocusMessageView,
    TuiTaskFocusNested,
    TuiTaskFocusNextStep,
    TuiTaskFocusPager,
    TuiTaskFocusParams,
    TuiTaskFocusProfessionalTarget,
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

_MAX_QUEUE_ITEMS = 100
_MAX_PAGE_SIZE = 100
_KNOWN_ACTIONS = frozenset(
    {
        "today-focus.queue",
        "today-focus.market-context",
        "portfolio-check.recorded-facts",
        "account.portfolio-recorded-facts",
    }
)
_OUTCOMES = frozenset({"success", "partial", "noop", "blocked", "failed"})


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one decoded JSON object without importing an owner module."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _required_text(value: object) -> str | None:
    """Read one required bounded string field."""

    return _text(value)


def _positive_id(value: object) -> int | None:
    """Read an exact positive integer without accepting booleans or floats."""

    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 18:
        try:
            normalized = int(value)
        except (ValueError, OverflowError):
            return None
        return normalized if normalized > 0 else None
    return None


def _nonnegative_int(value: object) -> int | None:
    """Read one exact non-negative JSON integer."""

    if type(value) is not int or value < 0:
        return None
    return value


def _finite_number(value: object) -> bool:
    """Validate a JSON number without changing its displayed native value."""

    return type(value) in {int, float} and safe_float(value) is not None


def _owner_success(data: Mapping[str, object]) -> bool | None:
    """Read the service success flag without treating missing as success."""

    value = data.get("success")
    return value if type(value) is bool else None


def _owner_outcome(data: Mapping[str, object]) -> str | None:
    """Preserve a canonical service outcome without deriving one."""

    value = _text(data.get("outcome"))
    return value if value in _OUTCOMES else None


def _has_invalid_outcome(data: Mapping[str, object]) -> bool:
    """Detect an explicitly present outcome outside the public vocabulary."""

    return "outcome" in data and _owner_outcome(data) is None


def _transport_message(kind: str, http_status: int) -> str | None:
    """Return bounded text for a non-success transport response."""

    if type(http_status) is not int:
        return f"{kind}响应状态无法识别。"
    if 200 <= http_status < 300:
        return None
    if http_status in {401, 403}:
        return f"当前用户没有访问{kind}的权限。"
    if http_status == 404:
        return f"{kind}不存在或已不可用。"
    if http_status >= 500:
        return f"{kind}服务暂时不可用。"
    return f"{kind}请求未完成。"


def _owner_gate(
    data: Mapping[str, object],
    *,
    title: str,
    require_success: bool = True,
) -> tuple[str | None, TuiTaskFocusMessageView | None]:
    """Reject failed or unknown service envelopes before displaying facts."""

    success = _owner_success(data)
    if require_success and success is not True:
        return None, _blocked(
            title,
            f"{title}暂不可用。",
            "服务未返回成功结果。",
            owner_outcome=_owner_outcome(data),
        )
    if not require_success and "success" in data and success is not True:
        return None, _blocked(
            title,
            f"{title}暂不可用。",
            "服务未返回成功结果。",
            owner_outcome=_owner_outcome(data),
        )
    outcome = _owner_outcome(data)
    if _has_invalid_outcome(data):
        return None, _blocked(title, f"{title}暂不可用。", "服务结果状态无法确认。")
    if outcome in {"blocked", "failed"}:
        return None, _blocked(
            title,
            f"{title}暂不可用。",
            "本次读取受到限制，未展示完整事实。",
            owner_outcome=outcome,
        )
    return outcome, None


def _professional_next_step(
    target: TuiTaskFocusProfessionalTarget | None,
    *,
    expected_screen: TaskScreenKey,
    expected_action: TaskActionKey,
    parameter_key: Literal["account_id", "pk"],
    selected_id: int,
) -> list[TuiTaskFocusNextStep]:
    """Create a safe continuation only for a caller-supplied closed target."""

    if target is None:
        return []
    mapping = _as_mapping(target)
    if mapping is None:
        return []
    if mapping.get("screen_key") != expected_screen or mapping.get("action_key") != expected_action:
        return []
    if "params" in mapping:
        return []
    label = _text(mapping.get("label"), allow_empty=False) or "继续查看专业记录"
    hint = (
        _text(mapping.get("hint"), allow_empty=False) or "仅在用户主动选择后继续；这里不执行写入。"
    )
    params: TuiTaskFocusParams = (
        {"account_id": selected_id} if parameter_key == "account_id" else {"pk": selected_id}
    )
    return [
        {
            "label": label,
            "hint": hint,
            "screen_key": expected_screen,
            "action_key": expected_action,
            "params": params,
        }
    ]


def project_today_focus_queue_payload(
    payload: object,
    *,
    requested_account_id: object,
    http_status: int,
    professional_target: TuiTaskFocusProfessionalTarget | None = None,
) -> TuiTaskFocusResult:
    """Project one explicitly selected account's decision queue."""

    account_id = _positive_id(requested_account_id)
    if account_id is None:
        return _blocked("账户今日待办", "请先选择有效账户。", "账户编号不是正整数。")
    transport_message = _transport_message("账户今日待办", http_status)
    if transport_message is not None:
        return _blocked(transport_message, transport_message, "账户待办读取未完成。")

    data = _as_mapping(payload)
    if data is None:
        return _blocked("账户今日待办", "账户今日待办返回格式无法识别。", "服务响应不是对象。")
    outcome, gate_error = _owner_gate(data, title="账户今日待办")
    if gate_error is not None:
        return gate_error
    if data.get("account_id") != str(account_id):
        return _blocked("账户今日待办", "账户选择与返回结果不一致。", "服务返回了不同的账户范围。")

    raw_items = data.get("items")
    total = _nonnegative_int(data.get("total"))
    if (
        not isinstance(raw_items, list)
        or total is None
        or total != len(raw_items)
        or total > _MAX_QUEUE_ITEMS
    ):
        return _blocked("账户今日待办", "账户今日待办返回格式无法识别。", "待办列表形状不受支持。")

    account_name = _optional_string(data.get("account_name"))
    fields: list[TuiTaskFocusField] = []
    if account_name:
        fields.append({"key": "account_name", "label": "账户名称", "value": account_name})
    fields.extend(
        [
            {"key": "account_id", "label": "已选择账户编号", "value": str(account_id)},
            {"key": "queue_count", "label": "待办记录数", "value": str(total)},
            {
                "key": "record_time_limit",
                "label": "时间限制",
                "value": "事项时间按记录/生成时间显示，不代表行情观测时间。",
            },
        ]
    )
    rows: list[TuiTaskFocusSectionRow] = []
    seen_item_ids: set[str] = set()
    for raw_item in raw_items:
        item = _as_mapping(raw_item)
        if item is None:
            return _blocked(
                "账户今日待办", "账户今日待办返回格式无法识别。", "待办条目形状不受支持。"
            )
        item_id = _required_text(item.get("item_id"))
        item_type = _required_text(item.get("type"))
        title = _required_text(item.get("title"))
        status = _required_text(item.get("status"))
        next_action = _required_text(item.get("next_action"))
        target_screen = _required_text(item.get("target_screen"))
        created_at = _required_text(item.get("created_at"))
        priority = _nonnegative_int(item.get("priority"))
        item_account = item.get("account_id")
        if (
            item_id is None
            or item_id in seen_item_ids
            or item_type is None
            or title is None
            or status is None
            or next_action is None
            or target_screen is None
            or created_at is None
            or priority is None
            or item_account != str(account_id)
        ):
            return _blocked(
                "账户今日待办",
                "账户今日待办返回格式无法识别。",
                "待办条目不属于所选账户或缺少必要字段。",
            )
        seen_item_ids.add(item_id)
        rows.append(
            _row(
                [
                    {"key": "title", "label": "事项", "value": title},
                    {"key": "item_id", "label": "事项编号", "value": item_id},
                    {"key": "status", "label": "状态", "value": status},
                    {"key": "priority", "label": "优先级", "value": str(priority)},
                    {"key": "type", "label": "事项类型", "value": item_type},
                    {"key": "next_action", "label": "下一步", "value": next_action},
                    {
                        "key": "security_code",
                        "label": "标的",
                        "value": _display_scalar(item.get("security_code")),
                    },
                    {"key": "created_at", "label": "事项记录/生成时间", "value": created_at},
                ]
            )
        )

    fields.extend(_preview(rows, "queue", "title", ("status", "next_action"), 3))
    summary = (
        f"已读取账户 {account_id} 的今日待办，共 {total} 项。"
        if total
        else f"账户 {account_id} 当前没有待处理事项；未使用默认账户替代所选账户。"
    )
    return _detail(
        title="账户今日待办",
        fields=fields,
        nested=[{"key": "queue_items", "label": "待办条目", "count": total}],
        summary=summary,
        next_steps=(
            _professional_next_step(
                professional_target,
                expected_screen="command-center.decision-flow",
                expected_action="auto.api.get.api.decision.workspace.recommendations",
                parameter_key="account_id",
                selected_id=account_id,
            )
            if outcome in {None, "success"}
            else []
        ),
        owner_status=_text(data.get("status")),
        outcome=outcome,
        sections=[
            {
                "key": "queue_items",
                "label": "待办记录",
                "columns": [
                    _column("title", "事项"),
                    _column("item_id", "事项编号"),
                    _column("status", "状态"),
                    _column("priority", "优先级"),
                    _column("type", "事项类型"),
                    _column("next_action", "下一步"),
                    _column("security_code", "标的"),
                    _column("created_at", "事项记录/生成时间"),
                ],
                "rows": rows,
                "restriction_message": "事项时间按记录/生成时间显示，不代表行情观测时间。",
            }
        ],
    )


def project_today_focus_market_context_payload(
    payload: object,
    *,
    http_status: int,
) -> TuiTaskFocusResult:
    """Project existing market-context rows while retaining each row clock."""

    transport_message = _transport_message("市场环境", http_status)
    if transport_message is not None:
        return _blocked(transport_message, transport_message, "市场环境读取未完成。")
    data = _as_mapping(payload)
    if data is None:
        return _blocked("市场环境", "市场环境返回格式无法识别。", "市场环境响应不是对象。")
    outcome, gate_error = _owner_gate(data, title="市场环境", require_success=False)
    if gate_error is not None:
        return gate_error

    return build_market_context_detail(data, outcome=outcome)


def _required_money_text(value: object) -> str | None:
    """Require the service JSON money encoding and preserve its exact text."""

    if not isinstance(value, str) or not value or len(value) > 240:
        return None
    try:
        return value if Decimal(value).is_finite() else None
    except InvalidOperation:
        return None


def _optional_string(value: object) -> str | None:
    """Preserve a nullable JSON string, including a legal null."""

    if value is None:
        return None
    return _text(value, allow_empty=True)


def _valid_clock(value: object) -> bool:
    """Validate the recorded-facts application-boundary clock shape."""

    data = _as_mapping(value)
    if data is None:
        return False
    return (
        _required_text(data.get("read_started_at")) is not None
        and _required_text(data.get("read_finished_at")) is not None
        and data.get("clock_kind") == "application_read_boundary"
        and data.get("source_time_status") == "not_provided"
    )


def _valid_breakdown(value: object) -> bool:
    """Validate grouping numbers without interpreting them as weights."""

    if value is None:
        return True
    data = _as_mapping(value)
    return data is not None and all(
        isinstance(key, str) and _text(key, allow_empty=True) == key and _finite_number(item)
        for key, item in data.items()
    )


def _valid_valuation_state(data: Mapping[str, object], fields: tuple[str, ...]) -> bool:
    """Require an explicit knowledge status and owner-consistent nullable values."""

    known = data.get("valuation_known")
    return (
        type(known) is bool
        and data.get("valuation_status") == ("unconfirmed" if known else "unknown")
        and all(key in data for key in fields)
        and (known is True or all(data[key] is None for key in fields))
    )


def _validate_position(
    value: object,
    *,
    portfolio_id: int,
    portfolio_name: str,
    seen_ids: set[int],
) -> Mapping[str, object] | None:
    """Validate one position and enforce portfolio identity."""

    position = _as_mapping(value)
    if position is None:
        return None
    position_id = _positive_id(position.get("id"))
    if position_id is None or position_id in seen_ids:
        return None
    if (
        position.get("portfolio") != portfolio_id
        or position.get("portfolio_name") != portfolio_name
    ):
        return None
    required_text_keys = ("portfolio_name", "asset_code", "asset_name", "asset_class", "source")
    if any(_required_text(position.get(key)) is None for key in required_text_keys):
        return None
    valuation_fields = ("current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct")
    if not _valid_valuation_state(position, valuation_fields):
        return None
    if not _finite_number(position.get("shares")) or (
        position.get("unrealized_pnl_pct") is not None
        and not _finite_number(position.get("unrealized_pnl_pct"))
    ):
        return None
    if _required_money_text(position.get("avg_cost")) is None or any(
        position[key] is not None and _required_money_text(position[key]) is None
        for key in valuation_fields[:3]
    ):
        return None
    if "source_id" not in position or (
        position.get("source_id") is not None and type(position.get("source_id")) is not int
    ):
        return None
    for key in ("currency_code", "currency_name", "currency_symbol", "opened_at", "updated_at"):
        if key not in position or (
            _optional_string(position.get(key)) is None and position.get(key) is not None
        ):
            return None
    seen_ids.add(position_id)
    return position


def _position_row(position: Mapping[str, object]) -> TuiTaskFocusSectionRow:
    """Build a detailed position row without inventing availability or clocks."""

    return _row(
        [
            {
                "key": "asset_name",
                "label": "标的名称",
                "value": _display_scalar(position.get("asset_name")),
            },
            {
                "key": "asset_code",
                "label": "标的代码",
                "value": _display_scalar(position.get("asset_code")),
            },
            {
                "key": "asset_class",
                "label": "资产类别",
                "value": _display_scalar(position.get("asset_class")),
            },
            {"key": "id", "label": "记录编号", "value": _display_scalar(position.get("id"))},
            {
                "key": "shares",
                "label": "记录数量",
                "value": _display_scalar(position.get("shares")),
            },
            {
                "key": "currency_code",
                "label": "币种代码",
                "value": _display_scalar(position.get("currency_code")),
            },
            {
                "key": "currency_name",
                "label": "币种名称",
                "value": _display_scalar(position.get("currency_name")),
            },
            {
                "key": "currency_symbol",
                "label": "币种符号",
                "value": _display_scalar(position.get("currency_symbol")),
            },
            {
                "key": "avg_cost",
                "label": "记录成本",
                "value": _display_scalar(position.get("avg_cost")),
            },
            {
                "key": "current_price",
                "label": "记录现价",
                "value": _recorded_valuation(position.get("current_price"), position),
            },
            {
                "key": "market_value",
                "label": "记录市值",
                "value": _recorded_valuation(position.get("market_value"), position),
            },
            {
                "key": "unrealized_pnl",
                "label": "未实现损益",
                "value": _recorded_valuation(position.get("unrealized_pnl"), position),
            },
            {
                "key": "unrealized_pnl_pct",
                "label": "记录损益率",
                "value": _recorded_valuation(position.get("unrealized_pnl_pct"), position),
            },
            {
                "key": "source",
                "label": "记录来源",
                "value": _display_scalar(position.get("source")),
            },
            {
                "key": "source_id",
                "label": "来源编号",
                "value": _display_scalar(position.get("source_id")),
            },
            {
                "key": "opened_at",
                "label": "记录开始时间",
                "value": _display_scalar(position.get("opened_at")),
            },
            {
                "key": "updated_at",
                "label": "记录更新时间",
                "value": _display_scalar(position.get("updated_at")),
            },
            {"key": "available_quantity", "label": "可卖数量", "value": "未提供"},
            {"key": "source_observation_time", "label": "源观测时间", "value": "未提供"},
        ]
    )


def _mapping_display(value: object, *, valuation_known: bool) -> str:
    """Display a validated grouping without presenting it as a percentage."""

    if value is None:
        return "未提供" if valuation_known else "未知"
    data = cast(Mapping[str, object], value)
    return "；".join(f"{key}：{_display_scalar(item)}" for key, item in data.items()) or "未提供"


def _recorded_valuation(value: object, record: Mapping[str, object]) -> str:
    """Distinguish explicitly unknown values from known records with null fields."""

    return (
        "未知" if value is None and record["valuation_known"] is False else _display_scalar(value)
    )


def _statistics_field(
    key: str,
    label: str,
    value: object,
    *,
    mode: Literal["plain", "valuation", "breakdown"],
    record: Mapping[str, object],
) -> TuiTaskFocusField:
    """Build a statistics field without coercing nullable owner values."""

    if mode == "plain":
        text = _display_scalar(value)
    elif mode == "breakdown":
        text = _mapping_display(value, valuation_known=cast(bool, record["valuation_known"]))
    else:
        text = _recorded_valuation(value, record)
    return {"key": key, "label": label, "value": text}


def _statistics_section(statistics: Mapping[str, object]) -> TuiTaskFocusSection:
    """Build expandable recorded statistics with explicit unit limitations."""

    field_specs: tuple[tuple[str, str, Literal["plain", "valuation", "breakdown"]], ...] = (
        ("total_value", "记录总额（原始单位）", "valuation"),
        ("total_cost", "记录总成本（原始单位）", "plain"),
        ("total_pnl", "记录损益（原始单位）", "valuation"),
        ("total_pnl_pct", "记录损益率", "valuation"),
        ("position_count", "统计持仓数量", "plain"),
        ("total_capital_inflow", "记录资金流入（原始单位）", "plain"),
        ("total_capital_outflow", "记录资金流出（原始单位）", "plain"),
        ("net_capital_flow", "记录净资金流（原始单位）", "plain"),
        ("asset_class_breakdown", "资产分类记录汇总（非比例）", "breakdown"),
        ("region_breakdown", "地区分类记录汇总（非比例）", "breakdown"),
    )
    fields: list[TuiTaskFocusField] = [
        _statistics_field(key, label, statistics[key], mode=mode, record=statistics)
        for key, label, mode in field_specs
    ]
    return {
        "key": "statistics",
        "label": "记录统计",
        "fields": fields,
        "restriction_message": "估值未知或未确认时不可用于决策；统计金额保留原始单位，未做跨币种换算；分类数字是记录汇总，不表示统一币种总值或比例。",
    }


def _statistics_nested(
    statistics: Mapping[str, object], *, key: str, label: str
) -> list[TuiTaskFocusNested]:
    """Publish a grouping count only when the owner supplied that grouping."""

    data = _as_mapping(statistics.get(key))
    return [] if data is None else [{"key": key, "label": label, "count": len(data)}]


def _clock_section(
    position_clock: Mapping[str, object],
    statistics_clock: Mapping[str, object],
) -> TuiTaskFocusSection:
    """Build a simple section for application read-boundary clocks."""

    return {
        "key": "read_clocks",
        "label": "应用读取边界",
        "fields": [
            {
                "key": "position_read_clock",
                "label": "持仓读取边界",
                "value": f"开始：{cast(str, position_clock['read_started_at'])}；结束：{cast(str, position_clock['read_finished_at'])}",
            },
            {
                "key": "statistics_read_clock",
                "label": "统计读取边界",
                "value": f"开始：{cast(str, statistics_clock['read_started_at'])}；结束：{cast(str, statistics_clock['read_finished_at'])}",
            },
            {
                "key": "source_time_status",
                "label": "源时间限制",
                "value": "持仓未提供源观测时间；以上时间仅表示本次应用读取边界。",
            },
        ],
        "restriction_message": "应用读取边界不等于源观测时间，也不构成统一时点。",
    }


def project_portfolio_recorded_facts_payload(
    payload: object,
    *,
    requested_portfolio_id: object,
    http_status: int,
    requested_page: object = 1,
    requested_page_size: object = 20,
    professional_target: TuiTaskFocusProfessionalTarget | None = None,
) -> TuiTaskFocusResult:
    """Project one complete recorded-facts read with reachable server paging."""

    portfolio_id = _positive_id(requested_portfolio_id)
    page = _positive_id(requested_page)
    page_size = _positive_id(requested_page_size)
    if portfolio_id is None or page is None or page_size is None or page_size > _MAX_PAGE_SIZE:
        return _blocked(
            "组合记录事实", "请先选择有效组合和分页条件。", "组合编号或分页参数不是有效正整数。"
        )
    transport_message = _transport_message("组合记录事实", http_status)
    if transport_message is not None:
        return _blocked(transport_message, transport_message, "组合事实读取未完成。")

    data = _as_mapping(payload)
    if data is None:
        return _blocked("组合记录事实", "组合记录事实返回格式无法识别。", "服务响应不是对象。")
    outcome, gate_error = _owner_gate(data, title="组合记录事实")
    if gate_error is not None:
        return gate_error
    if data.get("portfolio_id") != portfolio_id:
        return _blocked("组合记录事实", "组合选择与返回结果不一致。", "服务返回了不同的组合范围。")
    portfolio_name = _required_text(data.get("portfolio_name"))
    portfolio_is_active = data.get("portfolio_is_active")
    owner_user_id = _positive_id(data.get("owner_user_id"))
    owner_username = _required_text(data.get("owner_username"))
    access_role = data.get("access_role")
    if (
        portfolio_name is None
        or type(portfolio_is_active) is not bool
        or owner_user_id is None
        or owner_username is None
        or access_role not in {"owner", "observer"}
    ):
        return _blocked("组合记录事实", "组合记录事实返回格式无法识别。", "组合身份字段不受支持。")

    positions = _as_mapping(data.get("positions"))
    statistics = _as_mapping(data.get("statistics"))
    if positions is None or statistics is None:
        return _blocked("组合记录事实", "组合记录事实返回格式无法识别。", "持仓或统计区块缺失。")
    count = _nonnegative_int(positions.get("count"))
    owner_page = _positive_id(positions.get("page"))
    owner_page_size = _positive_id(positions.get("page_size"))
    has_next = positions.get("has_next")
    raw_items = positions.get("items")
    if (
        count is None
        or owner_page != page
        or owner_page_size != page_size
        or type(has_next) is not bool
        or not isinstance(raw_items, list)
        or len(raw_items) > page_size
    ):
        return _blocked(
            "组合记录事实", "组合持仓分页结果无法识别。", "服务返回的分页条件与本次选择不一致。"
        )
    total_pages = max(1, (count + page_size - 1) // page_size)
    out_of_range = page > total_pages
    if out_of_range:
        if raw_items or has_next:
            return _blocked(
                "组合记录事实", "组合持仓分页结果无法识别。", "超出页码时仍返回了记录或下一页标记。"
            )
    else:
        expected_rows = 0 if count == 0 else min(page_size, count - (page - 1) * page_size)
        if len(raw_items) != expected_rows or has_next != (page < total_pages):
            return _blocked(
                "组合记录事实", "组合持仓分页结果无法识别。", "服务返回了相互矛盾的分页事实。"
            )

    seen_ids: set[int] = set()
    positions_for_display: list[Mapping[str, object]] = []
    for raw_position in raw_items:
        position = _validate_position(
            raw_position,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            seen_ids=seen_ids,
        )
        if position is None:
            return _blocked(
                "组合记录事实",
                "组合记录事实返回格式无法识别。",
                "持仓不属于所选组合或缺少原始字段。",
            )
        positions_for_display.append(position)

    nullable_statistics = (
        "total_value",
        "total_pnl",
        "total_pnl_pct",
        "asset_class_breakdown",
        "region_breakdown",
    )
    if not _valid_valuation_state(statistics, nullable_statistics):
        return _blocked(
            "组合记录事实", "组合统计估值状态无法确认。", "统计知识状态与原始字段不一致。"
        )
    if (
        _required_money_text(statistics.get("total_cost")) is None
        or any(
            statistics.get(key) is not None and _required_money_text(statistics.get(key)) is None
            for key in ("total_value", "total_pnl")
        )
        or any(
            _required_money_text(statistics.get(key)) is None
            for key in ("total_capital_inflow", "total_capital_outflow", "net_capital_flow")
        )
    ):
        return _blocked(
            "组合记录事实", "组合统计返回格式无法识别。", "统计金额不是保留精度的字符串。"
        )
    if statistics.get("total_pnl_pct") is not None and not _finite_number(
        statistics.get("total_pnl_pct")
    ):
        return _blocked("组合记录事实", "组合统计返回格式无法识别。", "统计比例不是有效数字。")
    position_count = _nonnegative_int(statistics.get("position_count"))
    if (
        position_count is None
        or not _valid_breakdown(statistics.get("asset_class_breakdown"))
        or not _valid_breakdown(statistics.get("region_breakdown"))
    ):
        return _blocked("组合记录事实", "组合统计返回格式无法识别。", "统计分组字段形状不受支持。")
    if statistics.get("currency_status") != "stored_values_without_fx_normalization":
        return _blocked(
            "组合记录事实", "组合统计单位状态无法确认。", "服务未明确声明统计未做跨币种换算。"
        )
    if not _valid_clock(data.get("position_read_clock")) or not _valid_clock(
        data.get("statistics_read_clock")
    ):
        return _blocked(
            "组合记录事实", "组合读取时间边界无法确认。", "服务未提供完整的应用读取边界。"
        )

    position_clock = cast(Mapping[str, object], data["position_read_clock"])
    statistics_clock = cast(Mapping[str, object], data["statistics_read_clock"])
    access_label = "持有人" if access_role == "owner" else "观察者"
    fields: list[TuiTaskFocusField] = [
        {"key": "portfolio_name", "label": "组合名称", "value": portfolio_name},
        {"key": "portfolio_id", "label": "组合编号", "value": str(portfolio_id)},
        {"key": "access_role", "label": "访问身份", "value": access_label},
        {"key": "owner_username", "label": "持有人名称", "value": owner_username},
        {
            "key": "portfolio_is_active",
            "label": "组合状态",
            "value": "启用" if portfolio_is_active else "停用",
        },
        {"key": "positions_count", "label": "持仓记录数", "value": str(count)},
        {
            "key": "native_unit_limit",
            "label": "金额单位限制",
            "value": "各记录保留原始单位，未做跨币种换算；不可视为统一币种估值。",
        },
        {
            "key": "source_time_limit",
            "label": "源时间限制",
            "value": "持仓未提供源观测时间；下方时间仅表示应用读取边界。",
        },
    ]
    if out_of_range:
        page_summary = f"第 {page} 页没有记录；组合共有 {count} 条记录，可见页数为 {total_pages}。请返回选择或选择有效页码。"
    else:
        page_summary = (
            f"当前第 {page} 页，本页 {len(positions_for_display)} 条，组合共有 {count} 条记录。"
        )
    pager: TuiTaskFocusPager = {
        "client_side": False,
        "pagination_mode": "page",
        "page": page,
        "page_size": page_size,
        "total_rows": count,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": bool(has_next) if not out_of_range else False,
    }
    position_columns = [
        _column("asset_name", "标的名称"),
        _column("asset_code", "标的代码"),
        _column("asset_class", "资产类别"),
        _column("id", "记录编号"),
        _column("shares", "记录数量"),
        _column("currency_code", "币种代码"),
        _column("currency_name", "币种名称"),
        _column("currency_symbol", "币种符号"),
        _column("avg_cost", "记录成本"),
        _column("current_price", "记录现价"),
        _column("market_value", "记录市值"),
        _column("unrealized_pnl", "未实现损益"),
        _column("unrealized_pnl_pct", "记录损益率"),
        _column("source", "记录来源"),
        _column("source_id", "来源编号"),
        _column("opened_at", "记录开始时间"),
        _column("updated_at", "记录更新时间"),
        _column("available_quantity", "可卖数量"),
        _column("source_observation_time", "源观测时间"),
    ]
    sections: list[TuiTaskFocusSection] = [
        {
            "key": "positions",
            "label": "记录持仓",
            "columns": position_columns,
            "rows": [_position_row(position) for position in positions_for_display],
            "restriction_message": "数量是记录数量，不代表可卖数量；估值未知或未确认时不可用于决策，且价格源观测时间未提供。",
        },
        _statistics_section(statistics),
        _clock_section(position_clock, statistics_clock),
    ]
    summary = (
        f"已读取组合 {portfolio_name}。{page_summary} 金额保留各记录原始单位，统计未做跨币种换算；"
        "分类统计是记录汇总，不表示统一币种总值或比例。估值未知或未确认时不可用于决策；读取边界不代表源观测时间、可卖数量、风险结论或交易资格。"
    )
    return _detail(
        title="组合已记录事实",
        fields=fields,
        nested=[
            {"key": "positions", "label": "记录持仓", "count": count},
            *_statistics_nested(statistics, key="asset_class_breakdown", label="资产分类记录"),
            *_statistics_nested(statistics, key="region_breakdown", label="地区分类记录"),
        ],
        summary=summary,
        next_steps=(
            _professional_next_step(
                professional_target,
                expected_screen="execution.accounts",
                expected_action="account.portfolio-recorded-facts",
                parameter_key="pk",
                selected_id=portfolio_id,
            )
            if outcome in {None, "success"}
            else []
        ),
        owner_status=_text(data.get("status")),
        outcome=outcome,
        sections=sections,
        pager=pager,
    )


def project_tui_task_focus_result(
    action_key: str,
    payload: object,
    *,
    requested_params: Mapping[str, object] | None,
    http_status: int,
    professional_target: TuiTaskFocusProfessionalTarget | None = None,
) -> TuiTaskFocusResult:
    """Dispatch one known task result without contacting an owner."""

    if action_key not in _KNOWN_ACTIONS:
        return _blocked("任务读取结果", "当前任务结果不受支持。", "未知任务动作。")
    params = requested_params or {}
    if action_key == "today-focus.market-context":
        if params:
            return _blocked("市场环境", "市场环境不接受额外选择参数。", "请求包含未声明参数。")
        return project_today_focus_market_context_payload(payload, http_status=http_status)
    if action_key == "today-focus.queue":
        return project_today_focus_queue_payload(
            payload,
            requested_account_id=params.get("account_id"),
            http_status=http_status,
            professional_target=professional_target,
        )
    if action_key in {"portfolio-check.recorded-facts", "account.portfolio-recorded-facts"}:
        return project_portfolio_recorded_facts_payload(
            payload,
            requested_portfolio_id=params.get("pk"),
            requested_page=params.get("page", 1),
            requested_page_size=params.get("page_size", 20),
            http_status=http_status,
            professional_target=professional_target,
        )
    return _blocked("任务读取结果", "当前任务结果不受支持。", "任务动作未映射。")


__all__ = [
    "TaskActionKey",
    "TaskOutcome",
    "TaskScreenKey",
    "TaskStatus",
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
    "project_portfolio_recorded_facts_payload",
    "project_today_focus_market_context_payload",
    "project_today_focus_queue_payload",
    "project_tui_task_focus_result",
]
