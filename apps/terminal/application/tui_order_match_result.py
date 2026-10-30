"""Present a recorded order match without implying that its fill is posted."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from apps.terminal.application.tui_order_history_result import (
    _as_mapping,
    _blocked_operation,
    _field,
    _match_session_date,
    _nonnegative_decimal_text,
    _positive_decimal_text,
    _positive_int,
    _positive_json_int,
)

_INDETERMINATE_MESSAGE = (
    "撮合结果暂不能确认。请先读取该订单原决定，再对同一交易日显式重试；"
    "不要另选交易日替代结果核对。"
)
_KNOWN_REJECTION_MESSAGES = {
    "OWNER_ORDER_MATCH_QMT_BINDING_UNAVAILABLE": (
        "当前证券没有唯一可用的 QMT 绑定，本次未生成新的撮合决定。请先核对绑定。"
    ),
    "OWNER_ORDER_MATCH_QMT_BINDING_AMBIGUOUS": (
        "当前证券有多个可用的 QMT 绑定，本次未生成新的撮合决定。请先核对绑定。"
    ),
    "OWNER_ORDER_MATCH_ORDER_NOT_ACTIVE": "订单已终结，本次未生成新的撮合决定。请核对订单历史。",
    "ORDER_RESERVATION_TERMINAL": "订单已终结，本次未生成新的撮合决定。请核对订单历史。",
    "LOCAL_DAILY_MATCH_PENDING_FILL": (
        "订单已有待处理的撮合决定，本次未生成新的决定。请先核对原决定。"
    ),
}


def project_tui_order_match_result(
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate the exact requested order/day before showing any saved-decision facts."""
    title = "模拟订单日线撮合"
    if requested_params is None or type(http_status) is not int:
        return _blocked_operation(title, "缺少本次订单和交易日范围；未显示撮合结果。")
    account_id = _positive_int(requested_params.get("account_id"))
    order_id = _positive_int(requested_params.get("order_id"))
    session_date = _match_session_date(requested_params.get("session_date"))
    if account_id is None or order_id is None or session_date is None:
        return _blocked_operation(title, "本次账户、订单或交易日无法核对；未显示结果。")
    next_steps = [
        {
            "label": "核对该订单已保存的撮合决定",
            "action_key": "simulated-trading.order-decisions",
            "params": {"account_id": account_id, "order_id": order_id, "limit": 5},
        }
    ]
    if not 200 <= http_status < 300:
        error_payload = _as_mapping(payload)
        indeterminate = (
            error_payload is not None and error_payload.get("effects_indeterminate") is True
        )
        result_status, message = _match_error_presentation(
            http_status=http_status,
            error_payload=error_payload,
            indeterminate=indeterminate,
            account_id=account_id,
            order_id=order_id,
            session_date=session_date,
        )
        blocked = _blocked_operation(title, message)
        blocked["status"] = result_status
        if http_status not in {401, 403, 404}:
            blocked["next_steps"] = next_steps
        return blocked
    response = _as_mapping(payload)
    if response is None:
        return _blocked_operation(title, "撮合结果无法核对；未显示结果。")
    decision_outcome = response.get("decision_outcome")
    quantity = _nonnegative_decimal_text(response.get("matched_quantity"))
    price = _positive_decimal_text(response.get("matched_price"))
    replayed = response.get("replayed")
    if (
        response.get("success") is not True
        or response.get("outcome") != "success"
        or response.get("decision_recorded") is not True
        or _positive_json_int(response.get("account_id")) != account_id
        or _positive_json_int(response.get("order_id")) != order_id
        or _match_session_date(response.get("session_date")) != session_date
        or type(replayed) is not bool
        or response.get("effects_indeterminate", False) is not False
        or quantity is None
        or decision_outcome not in ("matched", "no_match")
        or (decision_outcome == "matched" and (Decimal(quantity) <= 0 or price is None))
        or (
            decision_outcome == "no_match"
            and (Decimal(quantity) != 0 or response.get("matched_price") is not None)
        )
    ):
        return _blocked_operation(title, "撮合决定与本次订单、交易日或数量无法核对；未显示结果。")
    return {
        "kind": "detail",
        "title": title,
        "status": "已保存撮合决定" if decision_outcome == "matched" else "已保存未撮合决定",
        "outcome": "success",
        "business_summary": (
            "仅保存或核对了原撮合决定，本操作不执行入账。请先打开该订单的原决定；"
            "有匹配事件时，仍须单独确认入账。"
        ),
        "fields": [
            _field("account_id", "账户编号", str(account_id)),
            _field("order_id", "订单编号", str(order_id)),
            _field("session_date", "撮合交易日", session_date),
            _field("matched_quantity", "原决定匹配数量", quantity),
            _field("matched_price", "原决定匹配价格", price if price is not None else "不适用"),
            _field("replayed", "是否核对已保存决定", "是" if replayed else "否"),
        ],
        "nested": [],
        "sections": [],
        "next_steps": next_steps,
    }


def _match_error_presentation(
    *,
    http_status: int,
    error_payload: Mapping[str, object] | None,
    indeterminate: bool,
    account_id: int,
    order_id: int,
    session_date: str,
) -> tuple[str, str]:
    """Use only known pre-write gates for a definite rejection presentation."""

    if http_status in {401, 403, 404}:
        return (
            "操作结果未确认",
            "当前账户或订单范围无法访问；已清除本次撮合结果。",
        )
    if indeterminate:
        return "操作结果未确认", _INDETERMINATE_MESSAGE
    if http_status == 400:
        return (
            "请求校验未通过",
            "本次撮合请求未通过校验。请核对所选订单和交易日后重试。",
        )
    if http_status == 409 and error_payload is not None:
        code = error_payload.get("code")
        if type(code) is str:
            known_message = _KNOWN_REJECTION_MESSAGES.get(code)
            if known_message is not None:
                return "撮合条件未满足", known_message
    return "操作结果未确认", (
        f"账户 {account_id}、订单 {order_id} 在 {session_date} 的撮合结果不能确认。"
        "请先读取该订单原决定，再对同一交易日显式重试；不要另选交易日替代结果核对。"
    )
