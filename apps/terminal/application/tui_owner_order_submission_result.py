"""Owner-safe projections for local simulated-order entry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.terminal.application.tui_order_history_result import (
    _ORDER_ENTRY_CONFIRM_ACTION,
    _ORDERS_ACTION,
    _as_mapping,
    _aware_iso,
    _blocked,
    _blocked_operation,
    _bounded_text,
    _field,
    _nonnegative_decimal_text,
    _order_status_label,
    _parse_aware_datetime,
    _positive_decimal_text,
    _positive_int,
    _project_orders,
    _side_label,
)

_ORDER_ENTRY_ORDERS_ACTION = "simulated-trading.order-entry-orders"
_ORDER_ENTRY_PREVIEW_ACTION = "simulated-trading.order-preview"
_ORDER_ENTRY_READBACK_ACTION = "simulated-trading.order-by-key"
_ACCOUNT_STOP_LOSS_ACTION = "simulated-trading.account-stop-loss-check"
_LOCAL_MARKET_PURPOSE = "local_simulation_only"
_CLOSE_MARKET_PURPOSE = "close_snapshot_simulation"
_CLOSE_SNAPSHOT_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_ACCOUNT_STOP_LOSS_SCOPE = "account_stop_loss_only"


def project_tui_owner_order_submission_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Show only verified owner-order facts and preserve local-simulation limits."""

    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _blocked_operation("模拟订单", "订单读取状态无法核对；未显示订单结果。")
    if action_key == _ACCOUNT_STOP_LOSS_ACTION:
        return _project_account_stop_loss_result(
            payload,
            requested_params,
            http_status=http_status,
        )
    if action_key not in {
        _ORDER_ENTRY_ORDERS_ACTION,
        _ORDER_ENTRY_PREVIEW_ACTION,
        _ORDER_ENTRY_CONFIRM_ACTION,
        _ORDER_ENTRY_READBACK_ACTION,
    }:
        return _blocked_operation("模拟订单", "无法识别这项模拟订单操作。")
    if action_key == _ORDER_ENTRY_ORDERS_ACTION:
        if not 200 <= http_status < 300 or requested_params is None:
            return _owner_order_failure(action_key, payload, http_status, requested_params)
        result = _project_orders(payload, requested_params)
        result["next_steps"] = []
        return result
    if action_key == _ORDER_ENTRY_PREVIEW_ACTION:
        if not 200 <= http_status < 300:
            return _owner_order_failure(action_key, payload, http_status, requested_params)
        return _project_owner_order_preview(payload, requested_params)
    if action_key == _ORDER_ENTRY_CONFIRM_ACTION:
        if not 200 <= http_status < 300:
            return _owner_order_failure(action_key, payload, http_status, requested_params)
        return _project_owner_order_reservation(
            payload,
            requested_params,
            title="模拟订单预留结果",
            readback=False,
        )
    if not 200 <= http_status < 300:
        return _owner_order_failure(action_key, payload, http_status, requested_params)
    result = _project_owner_order_reservation(
        payload,
        requested_params,
        title="原模拟订单核对结果",
        readback=True,
    )
    result["read_only"] = True
    result["must_not_execute"] = True
    return result


def _project_account_stop_loss_result(
    payload: object,
    requested_params: Mapping[str, object] | None,
    *,
    http_status: int,
) -> dict[str, object]:
    """Display only verified stop-loss scope, purpose, aggregate counts, and stable issues."""

    response = _as_mapping(payload)
    requested_ids = _requested_account_ids(requested_params)
    trade_date = _iso_date_text(requested_params.get("trade_date")) if requested_params else None
    purpose = requested_params.get("market_purpose") if requested_params else None
    if (
        not 200 <= http_status < 300
        or response is None
        or requested_ids is None
        or trade_date is None
        or type(purpose) is not str
        or purpose not in {_LOCAL_MARKET_PURPOSE, _CLOSE_MARKET_PURPOSE}
        or requested_params is None
        or requested_params.get("execution_scope") != _ACCOUNT_STOP_LOSS_SCOPE
        or requested_params.get("confirmed") is not True
    ):
        return _blocked_operation(
            "模拟止损检查结果待核对",
            "没有取得可核对的本人模拟止损结果；请保留原操作并核对本次运行状态。",
        )

    notice = _bounded_text(response.get("market_notice"), 240)
    if not _stop_loss_notice_matches(purpose, notice):
        return _blocked_operation(
            "模拟止损检查结果待核对",
            "模拟行情用途说明或运行范围无法核对；未显示账户结果。",
        )
    outcome = response.get("outcome")
    success = response.get("success")
    if (
        type(outcome) is not str
        or outcome not in {"success", "partial", "noop", "blocked", "failed"}
        or type(success) is not bool
        or success is not (outcome in {"success", "partial", "noop"})
        or response.get("execution_scope") != _ACCOUNT_STOP_LOSS_SCOPE
        or response.get("market_purpose") != purpose
        or response.get("trade_date") != trade_date
    ):
        return _blocked_operation(
            "模拟止损检查结果待核对",
            "服务器返回的止损范围或交易日期与本次选择不一致；未显示账户结果。",
        )

    counts = _validated_stop_loss_counts(response, requested_ids)
    if counts is None:
        return _blocked_operation(
            "模拟止损检查结果待核对",
            "账户结果、卖出笔数或入账计数无法核对；未显示成交结论。",
        )
    account_rows, issues = counts
    purpose_label = (
        "收盘快照模拟（非官方供应商末笔报价）"
        if purpose == _CLOSE_MARKET_PURPOSE
        else "盘中本地模拟"
    )
    outcome_label = {
        "success": "完成",
        "partial": "部分完成",
        "noop": "检查完成，无止损成交",
        "blocked": "规则阻断",
        "failed": "执行失败",
    }[str(outcome)]
    total = len(requested_ids)
    fields = [
        _field("market_purpose", "模拟行情用途", purpose_label),
        _field("execution_scope", "本次执行范围", "仅检查所选账户止损；不运行策略或买入"),
        _field("trade_date", "交易日期", trade_date),
        _field("market_notice", "报价用途说明", notice),
        _field("requested_accounts", "所选账户数", total),
        _field("outcome", "检查结果", outcome_label),
        _field("sell_count", "确认的模拟卖出笔数", str(response["sell_count"])),
        _field(
            "confirmed_trade_count", "确认的模拟成交笔数", str(response["confirmed_trade_count"])
        ),
        _field(
            "stored_count",
            "已入账笔数",
            "无法确定" if response["stored"] is None else str(response["stored"]),
        ),
        _field(
            "counts_unavailable",
            "入账计数状态",
            "无法确定" if response["counts_unavailable"] else "可核对",
        ),
    ]
    summary = (
        f"{trade_date} {purpose_label}；仅完成本次所选账户止损检查，"
        f"确认模拟卖出 {response['sell_count']} 笔。"
        "本操作不会开启自动交易、运行策略或买入；这里只显示模拟运行结果，"
        "不代表券商成交或独立成交回执。"
    )
    return {
        "kind": "detail",
        "title": "本次模拟止损检查",
        "status": outcome_label,
        "outcome": str(outcome),
        "business_summary": summary,
        "fields": fields,
        "nested": [],
        "sections": [
            {
                "key": "account_stop_loss_results",
                "label": "所选账户处理结果",
                "columns": [
                    {"key": "account_id", "label": "模拟账户编号"},
                    {"key": "outcome", "label": "结果"},
                    {"key": "sell_count", "label": "确认卖出笔数"},
                    {"key": "reason_code", "label": "稳定原因码"},
                    {"key": "issues", "label": "问题"},
                ],
                "rows": account_rows,
            }
        ],
        "next_steps": [],
        "blocking_reason": "；".join(issues),
    }


def _requested_account_ids(params: Mapping[str, object] | None) -> tuple[int, ...] | None:
    """Require an explicit bounded, duplicate-free account scope from the form."""

    if params is None:
        return None
    value = params.get("account_ids")
    if not isinstance(value, list | tuple) or not 1 <= len(value) <= 100:
        return None
    if any(type(account_id) is not int or account_id <= 0 for account_id in value):
        return None
    account_ids = tuple(value)
    return account_ids if len(set(account_ids)) == len(account_ids) else None


def _iso_date_text(value: object) -> str | None:
    """Preserve one exact ISO calendar date without accepting normalized variants."""

    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _stop_loss_notice_matches(purpose: object, notice: str | None) -> bool:
    """Require purpose-specific owner wording from the server response."""

    if notice is None:
        return False
    if purpose == _CLOSE_MARKET_PURPOSE:
        return "非官方" in notice and "末笔" in notice and "模拟" in notice
    return purpose == _LOCAL_MARKET_PURPOSE and "止损检查" in notice and "不运行" in notice


def _validated_stop_loss_counts(
    response: Mapping[str, object],
    requested_ids: tuple[int, ...],
) -> tuple[list[dict[str, object]], list[str]] | None:
    """Bind typed account rows and aggregate counts to the explicitly requested scope."""

    top_counts: dict[str, int] = {}
    for field_name in (
        "requested",
        "total_accounts",
        "buy_count",
        "sell_count",
        "confirmed_trade_count",
    ):
        value = response.get(field_name)
        if type(value) is not int or value < 0:
            return None
        top_counts[field_name] = value
    if (
        top_counts["requested"] != len(requested_ids)
        or top_counts["total_accounts"] != len(requested_ids)
        or top_counts["buy_count"] != 0
        or top_counts["sell_count"] != top_counts["confirmed_trade_count"]
    ):
        return None
    stored_value = response.get("stored")
    counts_unavailable = response.get("counts_unavailable")
    if type(counts_unavailable) is not bool:
        return None
    if counts_unavailable:
        if stored_value is not None:
            return None
    elif type(stored_value) is not int or stored_value < 0:
        return None

    raw_accounts = response.get("accounts")
    if not isinstance(raw_accounts, list) or len(raw_accounts) != len(requested_ids):
        return None
    rows: list[dict[str, object]] = []
    all_issues: list[str] = []
    summed_sells = 0
    summed_trades = 0
    summed_stored = 0
    any_counts_unavailable = False
    for raw_account, expected_id in zip(raw_accounts, requested_ids, strict=True):
        account = _as_mapping(raw_account)
        account_id = account.get("account_id") if account is not None else None
        if account is None or type(account_id) is not int or account_id != expected_id:
            return None
        account_outcome = account.get("outcome")
        if type(account_outcome) is not str or account_outcome not in {
            "success",
            "partial",
            "noop",
            "blocked",
            "failed",
        }:
            return None
        account_success = account.get("success")
        if type(account_success) is not bool or account_success is not (
            account_outcome in {"success", "partial", "noop"}
        ):
            return None
        account_counts: dict[str, int] = {}
        for field_name in ("buy_count", "sell_count", "confirmed_trade_count"):
            value = account.get(field_name)
            if type(value) is not int or value < 0:
                return None
            account_counts[field_name] = value
        if (
            account_counts["buy_count"] != 0
            or account_counts["sell_count"] != account_counts["confirmed_trade_count"]
        ):
            return None
        account_unavailable = account.get("counts_unavailable")
        account_stored = account.get("stored")
        if type(account_unavailable) is not bool or (
            account_unavailable and account_stored is not None
        ):
            return None
        if not account_unavailable and (type(account_stored) is not int or account_stored < 0):
            return None
        reason_value = account.get("reason_code")
        reason_code = None if reason_value is None else _bounded_text(reason_value, 80)
        if reason_value is not None and reason_code is None:
            return None
        raw_issues = account.get("issues")
        if not isinstance(raw_issues, list):
            return None
        issue_labels: list[str] = []
        for raw_issue in raw_issues:
            issue = _as_mapping(raw_issue)
            if issue is None:
                return None
            kind = issue.get("kind")
            stage = _bounded_text(issue.get("stage"), 80)
            code = _bounded_text(issue.get("code"), 100)
            asset_value = issue.get("asset_code")
            asset_code = None if asset_value is None else _bounded_text(asset_value, 100)
            indeterminate = issue.get("effects_indeterminate")
            if (
                type(kind) is not str
                or kind not in {"blocked", "failed"}
                or stage is None
                or code is None
                or (asset_value is not None and asset_code is None)
                or type(indeterminate) is not bool
            ):
                return None
            label = f"{stage}/{code}"
            if asset_code:
                label = f"{label}（{asset_code}）"
            issue_labels.append(label)
            all_issues.append(f"账户 {expected_id}：{label}")
        rows.append(
            {
                "account_id": expected_id,
                "outcome": _stop_loss_outcome_label(str(account_outcome)),
                "sell_count": account_counts["sell_count"],
                "reason_code": reason_code or "无",
                "issues": "；".join(issue_labels) or "无",
            }
        )
        summed_sells += account_counts["sell_count"]
        summed_trades += account_counts["confirmed_trade_count"]
        if type(account_stored) is int:
            summed_stored += account_stored
        any_counts_unavailable = any_counts_unavailable or account_unavailable
    if (
        summed_sells != top_counts["sell_count"]
        or summed_trades != top_counts["confirmed_trade_count"]
        or any_counts_unavailable is not counts_unavailable
        or (not counts_unavailable and summed_stored != stored_value)
    ):
        return None
    return rows, all_issues


def _stop_loss_outcome_label(value: str) -> str:
    """Translate only known aggregate account outcomes."""

    return {
        "success": "完成",
        "partial": "部分完成",
        "noop": "无止损成交",
        "blocked": "规则阻断",
        "failed": "执行失败",
    }[value]


def _project_owner_order_preview(
    payload: object,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate an explicitly selected intraday or close-snapshot simulation preview."""

    response = _as_mapping(payload)
    if requested_params is None or response is None:
        return _blocked_operation("模拟订单预览", "本次账户或订单意图无法核对；未生成可确认预览。")
    account_id = _positive_int(requested_params.get("account_id"))
    requested_code = _bounded_text(requested_params.get("asset_code"), 100)
    requested_name = _bounded_text(requested_params.get("asset_name"), 100)
    requested_side = _side_label(requested_params.get("side"))
    requested_quantity = _positive_decimal_text(requested_params.get("quantity"))
    requested_limit = _positive_decimal_text(requested_params.get("limit_price"))
    market_purpose = requested_params.get("market_purpose", _LOCAL_MARKET_PURPOSE)
    is_close_snapshot = market_purpose == _CLOSE_MARKET_PURPOSE
    order = _as_mapping(response.get("order"))
    market = _as_mapping(response.get("market"))
    order_values = _validated_owner_submission_order(order)
    market_values = _validated_owner_submission_market(
        market,
        expected_session_state="CLOSED" if is_close_snapshot else "OPEN",
    )
    close_qualification = (
        _validated_close_snapshot_qualification(response, market, market_values)
        if is_close_snapshot
        else None
    )
    confirmation_expires_at = _aware_iso(response.get("continuation_expires_at"))
    confirmation_expiry = _parse_aware_datetime(confirmation_expires_at)
    market_valid_until_value = (
        market_values.get("market_valid_until") if market_values is not None else None
    )
    market_expiry = _parse_aware_datetime(
        market_valid_until_value if type(market_valid_until_value) is str else None
    )
    if (
        account_id is None
        or requested_code is None
        or requested_name is None
        or requested_side is None
        or requested_quantity is None
        or requested_limit is None
        or type(market_purpose) is not str
        or market_purpose not in {_LOCAL_MARKET_PURPOSE, _CLOSE_MARKET_PURPOSE}
        or response.get("success") is not True
        or _positive_int(response.get("account_id")) != account_id
        or response.get("outcome") != "success"
        or response.get("read_only") is not True
        or response.get("execution_submitted") is not False
        or response.get("market_purpose") != market_purpose
        or order_values is None
        or market_values is None
        or confirmation_expires_at is None
        or confirmation_expiry is None
        or market_expiry is None
        or confirmation_expiry > market_expiry
        or order_values["side"] != requested_side
        or Decimal(str(order_values["quantity"])) != Decimal(requested_quantity)
        or Decimal(str(order_values["limit_price"])) != Decimal(requested_limit)
        or not _limit_inside_market_bounds(
            Decimal(requested_limit),
            market_values["lower_limit_price"],
            market_values["upper_limit_price"],
        )
        or (
            is_close_snapshot
            and (
                close_qualification is None
                or Decimal(requested_limit) != Decimal(str(market_values["reference_price"]))
            )
        )
    ):
        return _blocked_operation(
            "模拟订单预览",
            "订单意图、来源时点或模拟价界无法核对；未显示可确认预览。请重新读取本人账户和当前市场来源。",
        )
    notice = _bounded_text(response.get("market_notice"), 240)
    if not _market_notice_matches(market_purpose, notice):
        return _blocked_operation("模拟订单预览", "市场来源用途说明缺失；未显示可确认预览。")
    account_orders = {
        "label": "查看本人模拟订单",
        "action_key": _ORDER_ENTRY_ORDERS_ACTION,
        "params": {"account_id": account_id, "limit": 5},
    }

    purpose_label = "收盘快照模拟（非官方收盘价）" if is_close_snapshot else "盘中本地模拟"
    fields = [
        _field("market_purpose", "模拟行情用途", purpose_label),
        _field("account_id", "模拟账户编号", str(account_id)),
        _field("asset_code", "证券代码", requested_code),
        _field("asset_name", "证券名称", requested_name),
        _field("side", "方向", order_values["side"]),
        _field("quantity", "委托数量", order_values["quantity"]),
        _field("limit_price", "限价（元）", order_values["limit_price"]),
        _field("notional", "委托金额（元）", order_values["notional"]),
        _field("fee_estimate", "预估费用（元）", order_values["fee_estimate"]),
        _field("fee_budget", "费用预算（元）", order_values["fee_budget"] or "未单独设置"),
        _field("cash_reserved", "预留现金（元）", order_values["cash_reserved"]),
        _field("shares_reserved", "预留数量", order_values["shares_reserved"]),
        _field("available_cash", "预留后可用现金（元）", order_values["available_cash"] or "未知"),
        _field("available_shares", "预留后可用数量", order_values["available_shares"] or "未知"),
        _field("market_source_id", "行情来源", market_values["market_source_id"]),
        _field(
            "market_observed_at",
            "原报价观测时间" if is_close_snapshot else "来源观测时间",
            market_values["market_observed_at"],
        ),
        _field(
            "market_available_at",
            "本地实际收到完整报价" if is_close_snapshot else "本地收到完整报价",
            market_values["market_available_at"],
        ),
        _field(
            "market_valid_until",
            "本用途有效截止" if is_close_snapshot else "来源有效截止",
            market_values["market_valid_until"],
        ),
        _field("continuation_expires_at", "本次确认有效截止", confirmation_expires_at),
        _field(
            "security_state",
            "供应商原证券状态（不代表当前可交易）" if is_close_snapshot else "行情源报告证券状态",
            market_values["security_state"],
        ),
        _field(
            "session_state",
            "来源交易时段" if is_close_snapshot else "交易日历时段状态",
            "已收市" if is_close_snapshot else market_values["session_state"],
        ),
        _field(
            "reference_price",
            "收盘后末笔快照价（元）" if is_close_snapshot else "行情源参考价（元）",
            market_values["reference_price"],
        ),
        _field(
            "lower_limit_price", "模拟下界（元）", market_values["lower_limit_price"] or "未配置"
        ),
        _field(
            "upper_limit_price", "模拟上界（元）", market_values["upper_limit_price"] or "未配置"
        ),
        _field("price_boundary_mode", "价界用途", market_values["price_boundary_mode"]),
        *(
            [
                _field("trade_date", "来源交易日", market_values["trade_date"]),
                _field(
                    "snapshot_kind",
                    "快照类型",
                    "供应商收盘后末笔报价；不是官方收盘价",
                ),
                _field("price_rule", "快照价格规则", "仅限供应商末笔快照价"),
                _field("freshness", "数据新鲜度", "收盘快照（非实时、非新鲜报价）"),
                _field(
                    "reliability",
                    "来源可靠性口径",
                    "供应商报告的收盘后末笔快照",
                ),
                _field(
                    "local_simulation_qualified",
                    "本地模拟用途资格",
                    "已通过；仅限本地模拟",
                ),
                _field(
                    "market_available_at_basis",
                    "本地可用时点含义",
                    "本地完整响应接收时间；不是供应商发布时间",
                ),
                _field("must_not_use_for_decision", "决策限制", "不得用于投资决策"),
                _field("must_not_execute", "执行限制", "不得提交外部执行"),
            ]
            if is_close_snapshot and close_qualification is not None
            else []
        ),
        _field("market_notice", "来源说明", notice),
    ]
    return {
        "kind": "detail",
        "title": "模拟订单预览",
        "status": "只读预览，可核对后明确确认",
        "outcome": "success",
        "business_summary": (
            f"{requested_code} {requested_side} {requested_quantity} 股，限价 {requested_limit} 元，"
            f"预估费用 {order_values['fee_estimate']} 元；只读预览，尚未预留，未成交。"
            + (
                f"来源交易日 {market_values['trade_date']}；收盘后末笔报价为非官方收盘价，"
                f"限价仅按该快照价用于本地模拟；报价时间 {market_values['market_observed_at']}，"
                f"本地可用时间 {market_values['market_available_at']}；当前不是实时新鲜行情。"
                if is_close_snapshot
                else (
                    f"新浪报价时间 {market_values['market_observed_at']}，"
                    f"本次确认截止 {confirmation_expires_at}。"
                )
            )
            + "确认仅用于本地模拟，不会提交券商。"
        ),
        "fields": fields,
        "nested": [],
        "sections": [],
        "next_steps": [account_orders],
    }


def _project_owner_order_reservation(
    payload: object,
    requested_params: Mapping[str, object] | None,
    *,
    title: str,
    readback: bool,
) -> dict[str, object]:
    """Validate a persisted reservation without claiming the order has filled."""

    response = _as_mapping(payload)
    account_id = _positive_int(requested_params.get("account_id")) if requested_params else None
    order_key = _bounded_text(requested_params.get("order_key"), 256) if requested_params else None
    order_id = _positive_int(response.get("order_id")) if response else None
    order = _as_mapping(response.get("order")) if response else None
    replayed = response.get("replayed") if response is not None else None
    order_values = _validated_owner_submission_order(
        order,
        readback=readback,
        allow_terminal_status=readback or replayed is True,
    )
    expected_read_only = readback
    market_purpose = _validated_reservation_market_purpose(response, requested_params)
    if (
        account_id is None
        or order_key is None
        or response is None
        or response.get("success") is not True
        or _positive_int(response.get("account_id")) != account_id
        or response.get("outcome") != "success"
        or response.get("read_only") is not expected_read_only
        or response.get("execution_submitted") is not False
        or market_purpose is None
        or type(replayed) is not bool
        or order_id is None
        or order_values is None
        or order_values["idempotency_key"] != order_key
        or (readback and response.get("order_key") != order_key)
        or (not readback and replayed is False and order_values["status"] != "active")
    ):
        return _blocked_operation(title, "原订单身份或预留状态无法核对；不能认定订单已成交。")
    order_status = _order_status_label(order_values["status"])
    filled_quantity = order_values["filled_quantity"]
    if order_status is None:
        return _blocked_operation(title, "原订单状态无法核对；没有显示订单结果。")
    if readback:
        if filled_quantity is None:
            return _blocked_operation(title, "原订单累计成交数量无法核对；没有显示订单结果。")
        message = (
            f"已找到同一原订单，当前状态为{order_status}，累计成交数量 {filled_quantity}。"
            "本次只读核对未重新读取行情或创建新单；请到订单历史核对成交回执。"
        )
    elif replayed is True:
        message = (
            f"已找到此前同一模拟订单，当前状态为{order_status}；没有创建第二笔订单。"
            "请到订单历史核对成交回执。"
        )
    else:
        message = "模拟订单已预留，尚未成交；后续撮合需要单独操作。"
    if market_purpose == _CLOSE_MARKET_PURPOSE:
        message = (
            f"{message}该订单用途为收盘快照模拟（供应商盘后末笔报价，非官方收盘价）；"
            "仅限本地模拟，不代表实时行情或券商成交。"
        )
    next_steps = [
        {
            "label": "查看本人模拟订单",
            "action_key": _ORDER_ENTRY_ORDERS_ACTION,
            "params": {"account_id": account_id, "limit": 5},
        },
        {
            "label": "进入订单历史并继续撮合",
            "screen_key": "execution.accounts",
            "action_key": _ORDERS_ACTION,
            "params": {"account_id": account_id, "limit": 5},
        },
    ]
    status = (
        f"已核对原订单：{order_status}"
        if readback
        else f"已读取原订单：{order_status}" if replayed is True else "已预留，尚未成交"
    )
    reservation_fields: list[dict[str, object]] = [
        _field("order_id", "订单编号", order_id),
        _field("side", "方向", order_values["side"]),
        _field("quantity", "委托数量", order_values["quantity"]),
        _field("limit_price", "限价（元）", order_values["limit_price"]),
        _field("notional", "委托金额（元）", order_values["notional"] or "未提供"),
        _field("fee_estimate", "预估费用（元）", order_values["fee_estimate"]),
        _field("cash_reserved", "预留现金（元）", order_values["cash_reserved"]),
        _field("shares_reserved", "预留数量", order_values["shares_reserved"]),
        _field("order_status", "订单状态", order_status),
        _field("replayed", "原确认已存在", "是" if replayed else "否"),
    ]
    if market_purpose == _CLOSE_MARKET_PURPOSE:
        reservation_fields.insert(
            0,
            _field("market_purpose", "模拟行情用途", "收盘快照模拟（非官方收盘价）"),
        )
    if readback:
        reservation_fields.extend(
            [
                _field("filled_quantity", "累计成交数量", filled_quantity or "未提供"),
                _field("reserved_at", "原预留时间", order_values["reserved_at"] or "未提供"),
            ]
        )
    return {
        "kind": "detail",
        "title": title,
        "status": status,
        "outcome": "success",
        "business_summary": message,
        "fields": reservation_fields,
        "nested": [],
        "sections": [],
        "next_steps": next_steps,
    }


def _validated_reservation_market_purpose(
    response: Mapping[str, object] | None,
    requested_params: Mapping[str, object] | None,
) -> str | None:
    """Require response and any preserved TUI purpose to agree with the signed record."""

    if response is None:
        return None
    response_purpose = response.get("purpose")
    market_purpose = response.get("market_purpose")
    requested_purpose = (
        requested_params.get("market_purpose") if requested_params is not None else None
    )
    expected = requested_purpose or market_purpose or response_purpose
    if (
        type(expected) is not str
        or expected not in {_LOCAL_MARKET_PURPOSE, _CLOSE_MARKET_PURPOSE}
        or response_purpose != expected
        or (market_purpose is not None and market_purpose != expected)
        or (expected == _CLOSE_MARKET_PURPOSE and market_purpose != expected)
        or (requested_purpose is not None and requested_purpose != expected)
    ):
        return None
    return expected


def _validated_owner_submission_order(
    order: Mapping[str, object] | None,
    *,
    readback: bool = False,
    allow_terminal_status: bool = False,
) -> dict[str, object] | None:
    """Whitelist safe reservation values while keeping the private order key internal."""

    if order is None:
        return None
    idempotency_key = _bounded_text(order.get("idempotency_key"), 256)
    side_code = order.get("side")
    side = _side_label(side_code)
    quantity = _positive_decimal_text(order.get("quantity"))
    limit_price = _positive_decimal_text(order.get("limit_price"))
    notional_value = order.get("notional")
    notional = (
        None if readback and notional_value is None else _nonnegative_decimal_text(notional_value)
    )
    fee_estimate = _nonnegative_decimal_text(order.get("fee_estimate"))
    fee_budget_value = order.get("fee_budget")
    fee_budget = None if fee_budget_value is None else _nonnegative_decimal_text(fee_budget_value)
    cash_reserved = _nonnegative_decimal_text(order.get("cash_reserved"))
    shares_reserved = _nonnegative_decimal_text(order.get("shares_reserved"))
    available_cash_value = order.get("available_cash")
    available_shares_value = order.get("available_shares")
    available_cash = (
        None if available_cash_value is None else _nonnegative_decimal_text(available_cash_value)
    )
    available_shares = (
        None
        if available_shares_value is None
        else _nonnegative_decimal_text(available_shares_value)
    )
    status = order.get("status")
    filled_quantity_value = order.get("filled_quantity")
    filled_quantity = _nonnegative_decimal_text(filled_quantity_value) if readback else None
    reserved_at = _aware_iso(order.get("reserved_at")) if readback else None
    allowed_statuses = {"active", "completed", "cancelled"} if allow_terminal_status else {"active"}
    if (
        idempotency_key is None
        or side is None
        or type(side_code) is not str
        or quantity is None
        or limit_price is None
        or (notional is None and not (readback and notional_value is None))
        or fee_estimate is None
        or (fee_budget_value is not None and fee_budget is None)
        or cash_reserved is None
        or shares_reserved is None
        or (available_cash_value is not None and available_cash is None)
        or (available_shares_value is not None and available_shares is None)
        or type(status) is not str
        or status not in allowed_statuses
        or (readback and filled_quantity is None)
        or (readback and reserved_at is None)
    ):
        return None
    if not allow_terminal_status and side_code == "buy" and available_cash is None:
        return None
    if not allow_terminal_status and side_code == "sell" and available_shares is None:
        return None
    return {
        "idempotency_key": idempotency_key,
        "side": side,
        "quantity": quantity,
        "limit_price": limit_price,
        "notional": notional,
        "fee_estimate": fee_estimate,
        "fee_budget": fee_budget,
        "cash_reserved": cash_reserved,
        "shares_reserved": shares_reserved,
        "available_cash": available_cash,
        "available_shares": available_shares,
        "status": status,
        "filled_quantity": filled_quantity,
        "reserved_at": reserved_at,
    }


def _validated_owner_submission_market(
    market: Mapping[str, object] | None,
    *,
    expected_session_state: str = "OPEN",
) -> dict[str, object] | None:
    """Whitelist source clocks and price bounds for the selected market session."""

    if market is None:
        return None
    source_id = _bounded_text(market.get("market_source_id"), 200)
    observed_at = _aware_iso(market.get("market_observed_at"))
    available_at = _aware_iso(market.get("market_available_at"))
    valid_until = _aware_iso(market.get("market_valid_until"))
    security_state = market.get("security_state")
    session_state = market.get("session_state")
    boundary_mode = market.get("price_boundary_mode")
    reference_price = _positive_decimal_text(market.get("reference_price"))
    lower_value = market.get("lower_limit_price")
    upper_value = market.get("upper_limit_price")
    lower = None if lower_value is None else _positive_decimal_text(lower_value)
    upper = None if upper_value is None else _positive_decimal_text(upper_value)
    observed_datetime = _parse_aware_datetime(observed_at)
    available_datetime = _parse_aware_datetime(available_at)
    valid_datetime = _parse_aware_datetime(valid_until)
    if (
        source_id is None
        or observed_at is None
        or available_at is None
        or valid_until is None
        or observed_datetime is None
        or available_datetime is None
        or valid_datetime is None
        or not observed_datetime <= available_datetime < valid_datetime
        or security_state != "TRADING"
        or session_state != expected_session_state
        or type(boundary_mode) is not str
        or boundary_mode not in {"LIMITED", "UNRESTRICTED"}
        or reference_price is None
    ):
        return None
    if boundary_mode == "LIMITED" and (
        lower is None or upper is None or Decimal(lower) > Decimal(upper)
    ):
        return None
    if boundary_mode == "UNRESTRICTED" and (lower is not None or upper is not None):
        return None
    result: dict[str, object] = {
        "market_source_id": source_id,
        "market_observed_at": observed_at,
        "market_available_at": available_at,
        "market_valid_until": valid_until,
        "security_state": security_state,
        "session_state": session_state,
        "reference_price": reference_price,
        "lower_limit_price": lower,
        "upper_limit_price": upper,
        "price_boundary_mode": boundary_mode,
    }
    if expected_session_state == "CLOSED":
        trade_date = _iso_date_text(market.get("trade_date"))
        if (
            trade_date is None
            or observed_datetime.astimezone(_CLOSE_SNAPSHOT_MARKET_TIMEZONE).date().isoformat()
            != trade_date
            or market.get("market_session") != "CLOSED"
            or market.get("snapshot_kind") != "vendor_last_quote_after_close_not_official_close"
            or market.get("price_rule") != "exact_vendor_last_after_close.v1"
        ):
            return None
        result.update(
            {
                "trade_date": trade_date,
                "market_session": "CLOSED",
                "snapshot_kind": market["snapshot_kind"],
                "price_rule": market["price_rule"],
            }
        )
    return result


def _validated_close_snapshot_qualification(
    response: Mapping[str, object],
    market: Mapping[str, object] | None,
    market_values: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Require the explicit closed-snapshot simulation qualification and real clocks."""

    if market is None or market_values is None:
        return None
    qualification = _as_mapping(response.get("market_qualification"))
    qualified_at = _aware_iso(
        qualification.get("qualified_at") if qualification is not None else None
    )
    observed_at = _parse_aware_datetime(str(market_values.get("market_observed_at")))
    available_at = _parse_aware_datetime(str(market_values.get("market_available_at")))
    valid_until = _parse_aware_datetime(str(market_values.get("market_valid_until")))
    qualified_datetime = _parse_aware_datetime(qualified_at)
    reasons = qualification.get("blocking_reasons") if qualification is not None else None
    available_basis = (
        qualification.get("market_available_at_basis") if qualification is not None else None
    )
    if (
        qualification is None
        or qualification.get("decision_scope") != "close_snapshot_simulation"
        or qualified_at is None
        or qualified_datetime is None
        or qualified_datetime.utcoffset() != timedelta(0)
        or observed_at is None
        or available_at is None
        or valid_until is None
        or not observed_at <= available_at <= qualified_datetime < valid_until
        or qualification.get("freshness") != "close_snapshot"
        or qualification.get("reliability") != "vendor_reported_close_snapshot"
        or qualification.get("must_not_use_for_decision") is not True
        or qualification.get("must_not_execute") is not True
        or qualification.get("local_simulation_qualified") is not True
        or reasons != []
        or available_basis != "local_response_completed_at_not_vendor_published_at"
    ):
        return None
    return {
        "qualified_at": qualified_at,
        "freshness": "close_snapshot",
        "reliability": "vendor_reported_close_snapshot",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "local_simulation_qualified": True,
        "market_available_at_basis": available_basis,
    }


def _market_notice_matches(purpose: object, notice: str | None) -> bool:
    """Require a notice that matches the selected local simulation purpose."""

    if notice is None:
        return False
    if purpose == _CLOSE_MARKET_PURPOSE:
        return (
            "末笔" in notice
            and ("非官方" in notice or "不是官方" in notice)
            and "本地模拟" in notice
        )
    return purpose == _LOCAL_MARKET_PURPOSE and "仅用于本地模拟" in notice


def _limit_inside_market_bounds(
    limit_price: Decimal,
    lower_limit: object,
    upper_limit: object,
) -> bool:
    """Check a previewed limit against present limited-market bounds without rounding."""

    if lower_limit is None and upper_limit is None:
        return True
    if type(lower_limit) is not str or type(upper_limit) is not str:
        return False
    return Decimal(lower_limit) <= limit_price <= Decimal(upper_limit)


def _owner_order_failure(
    action_key: str,
    payload: object,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Keep source blocks and uncertain confirmation separate from an accepted order."""

    response = _as_mapping(payload)
    if action_key == _ORDER_ENTRY_CONFIRM_ACTION and (
        http_status >= 500
        or (response is not None and response.get("effects_indeterminate") is True)
    ):
        account_id = _positive_int(requested_params.get("account_id")) if requested_params else None
        order_key = (
            _bounded_text(requested_params.get("order_key"), 256) if requested_params else None
        )
        readback_params: dict[str, object] = {
            "account_id": account_id,
            "order_key": order_key,
        }
        steps = (
            [
                {
                    "label": "只读核对同一原订单",
                    "action_key": _ORDER_ENTRY_READBACK_ACTION,
                    "params": readback_params,
                }
            ]
            if account_id is not None and order_key is not None
            else []
        )
        message = (
            "确认响应未能证明原订单是否已预留；请先只读核对同一原订单。"
            "不要重新预览、另建订单或据此认定没有提交。"
        )
        return {
            "kind": "detail",
            "title": "模拟订单结果待核对",
            "status": "原订单结果未确认",
            "outcome": "blocked",
            "business_summary": message,
            "blocking_reason": message,
            "fields": [],
            "nested": [],
            "sections": [],
            "next_steps": steps,
        }
    if action_key == _ORDER_ENTRY_READBACK_ACTION:
        message = (
            "暂未核对到同一原订单的已保存预留；这不表示原请求未提交。"
            "请保留原请求并重试只读核对，不要重新预览或创建替代订单。"
            if http_status in {404, 503} or http_status >= 500
            else "当前身份或账户范围无法核对原订单；没有显示其他账户的订单。"
        )
        return _blocked_operation("原模拟订单待核对", message)
    if action_key == _ORDER_ENTRY_PREVIEW_ACTION:
        message = (
            "当前账户、行情来源或交易时段不满足模拟预览；未创建订单预留。"
            "请重新读取本人模拟账户和当前行情，不要使用旧报价。"
        )
        return _blocked_operation("模拟订单未生成预览", message)
    if action_key == _ORDER_ENTRY_CONFIRM_ACTION:
        return _blocked_operation(
            "模拟订单确认未完成",
            "本次确认未获得可核对的订单预留回执；请先核对原订单结果后再决定下一步。",
        )
    return _blocked("模拟订单", "本人模拟订单暂不可读取；请稍后重新读取。")


__all__ = ("project_tui_owner_order_submission_result",)
