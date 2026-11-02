"""Owner-safe projections for local simulated-order entry."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

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
    return _project_owner_order_reservation(
        payload,
        requested_params,
        title="原模拟订单核对结果",
        readback=True,
    )


def _project_owner_order_preview(
    payload: object,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate the exact local-only preview, its source clocks, and its price bounds."""

    response = _as_mapping(payload)
    if requested_params is None or response is None:
        return _blocked_operation("模拟订单预览", "本次账户或订单意图无法核对；未生成可确认预览。")
    account_id = _positive_int(requested_params.get("account_id"))
    requested_code = _bounded_text(requested_params.get("asset_code"), 100)
    requested_name = _bounded_text(requested_params.get("asset_name"), 100)
    requested_side = _side_label(requested_params.get("side"))
    requested_quantity = _positive_decimal_text(requested_params.get("quantity"))
    requested_limit = _positive_decimal_text(requested_params.get("limit_price"))
    order = _as_mapping(response.get("order"))
    market = _as_mapping(response.get("market"))
    order_values = _validated_owner_submission_order(order)
    market_values = _validated_owner_submission_market(market)
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
        or response.get("success") is not True
        or _positive_int(response.get("account_id")) != account_id
        or response.get("outcome") != "success"
        or response.get("read_only") is not True
        or response.get("execution_submitted") is not False
        or response.get("purpose") != "local_simulation_only"
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
    ):
        return _blocked_operation(
            "模拟订单预览",
            "订单意图、来源时点或模拟价界无法核对；未显示可确认预览。请重新读取本人账户和当前市场来源。",
        )
    notice = _bounded_text(response.get("market_notice"), 240)
    if notice is None or "仅用于本地模拟" not in notice:
        return _blocked_operation("模拟订单预览", "市场来源用途说明缺失；未显示可确认预览。")
    account_orders = {
        "label": "查看本人模拟订单",
        "action_key": _ORDER_ENTRY_ORDERS_ACTION,
        "params": {"account_id": account_id, "limit": 5},
    }

    fields = [
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
        _field("market_observed_at", "来源观测时间", market_values["market_observed_at"]),
        _field("market_available_at", "本地收到完整报价", market_values["market_available_at"]),
        _field("market_valid_until", "来源有效截止", market_values["market_valid_until"]),
        _field("continuation_expires_at", "本次确认有效截止", confirmation_expires_at),
        _field("security_state", "行情源报告证券状态", market_values["security_state"]),
        _field("session_state", "交易日历时段状态", market_values["session_state"]),
        _field("reference_price", "行情源参考价（元）", market_values["reference_price"]),
        _field(
            "lower_limit_price", "模拟下界（元）", market_values["lower_limit_price"] or "未配置"
        ),
        _field(
            "upper_limit_price", "模拟上界（元）", market_values["upper_limit_price"] or "未配置"
        ),
        _field("price_boundary_mode", "价界用途", market_values["price_boundary_mode"]),
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
            f"新浪报价时间 {market_values['market_observed_at']}，"
            f"本次确认截止 {confirmation_expires_at}。确认仅用于本地模拟，不会提交券商。"
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
    if (
        account_id is None
        or order_key is None
        or response is None
        or response.get("success") is not True
        or _positive_int(response.get("account_id")) != account_id
        or response.get("outcome") != "success"
        or response.get("read_only") is not expected_read_only
        or response.get("execution_submitted") is not False
        or response.get("purpose") != "local_simulation_only"
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
) -> dict[str, object] | None:
    """Whitelist source clocks and explicitly configured paper price boundaries."""

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
        or session_state != "OPEN"
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
    return {
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
        steps = (
            [
                {
                    "label": "只读核对同一原订单",
                    "action_key": _ORDER_ENTRY_READBACK_ACTION,
                    "params": {"account_id": account_id, "order_key": order_key},
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
