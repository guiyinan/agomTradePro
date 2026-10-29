"""Owner-facing projections for simulated-order and retained-fill history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_ORDERS_ACTION = "simulated-trading.orders"
_FILLS_ACTION = "simulated-trading.order-fills"
_DECISIONS_ACTION = "simulated-trading.order-decisions"
_DECISION_SCOPE_NOTE = (
    "仅核对已保存的撮合决定及原成交回执；缺少回执表示入账尚未确认，不能据此重新撮合或释放预留。"
)
_RECEIPT_SCOPE_NOTE = "本页仅列已留存且完成单条核对的成交回执；空列表不能证明从未成交。"
_CURSOR_MAX_LENGTH = 4096
_PAGE_LIMIT_MAX = 100


def project_tui_order_history_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Render only the requested owner page and exact receipt fields."""

    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _blocked("订单记录", "读取状态无法核对；请重新选择本人账户并读取订单记录。")
    if action_key not in {_ORDERS_ACTION, _FILLS_ACTION, _DECISIONS_ACTION}:
        return _blocked("订单记录", "无法识别这项只读订单记录。")
    if not 200 <= http_status < 300:
        message = (
            "当前账户或订单范围无法访问；已清除本次回执内容，请重新选择本人账户。"
            if http_status in {401, 403, 404}
            else "订单记录读取失败；请稍后重新读取。"
        )
        return _blocked("订单记录", message)
    if requested_params is None:
        return _blocked("订单记录", "缺少本次查询范围；未显示订单或回执。")
    if action_key == _ORDERS_ACTION:
        return _project_orders(payload, requested_params)
    if action_key == _DECISIONS_ACTION:
        return _project_decisions(payload, requested_params)
    return _project_fills(payload, requested_params)


def _project_orders(
    payload: object,
    requested_params: Mapping[str, object],
) -> dict[str, object]:
    """Validate an owner order page and build exact read-only follow-ups."""

    account_id = _positive_int(requested_params.get("account_id"))
    limit = _page_limit(requested_params.get("limit", 5))
    response = _as_mapping(payload)
    if (
        account_id is None
        or limit is None
        or not _requested_cursor_valid(requested_params)
        or response is None
    ):
        return _blocked("模拟订单", "账户或分页范围无法核对；未显示订单。")
    page = _validate_page_envelope(response, requested_account_id=account_id, limit=limit)
    if page is None:
        return _blocked("模拟订单", "订单范围或分页状态无法核对；请重新选择本人账户。")
    items, has_more, next_cursor, membership_cutoff, read_at = page
    rows: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    seen_order_ids: set[int] = set()
    for raw in items:
        row = _as_mapping(raw)
        normalized = _validated_order(row) if row is not None else None
        if normalized is None:
            return _blocked("模拟订单", "订单记录格式无法核对；未显示本页部分结果。")
        order_id = normalized["order_id"]
        if type(order_id) is not int or order_id in seen_order_ids:
            return _blocked("模拟订单", "订单编号重复或无法核对；未显示本页部分结果。")
        seen_order_ids.add(order_id)
        rows.append(_table_row(normalized))
        steps.append(
            {
                "label": f"核对订单 {order_id} 的撮合决定",
                "action_key": _DECISIONS_ACTION,
                "params": {"account_id": account_id, "order_id": order_id, "limit": limit},
            }
        )
        steps.append(
            {
                "label": f"查看订单 {order_id} 的成交回执",
                "action_key": _FILLS_ACTION,
                "params": {"account_id": account_id, "order_id": order_id, "limit": limit},
            }
        )
    if has_more:
        steps.append(
            {
                "label": "读取下一批订单",
                "action_key": _ORDERS_ACTION,
                "params": {"account_id": account_id, "limit": limit, "cursor": next_cursor},
            }
        )
    return {
        "kind": "detail",
        "title": "模拟订单",
        "status": "已读取本人账户订单",
        "outcome": "success",
        "business_summary": f"本页显示 {len(rows)} 个订单；本页范围不表示全部订单或成交义务已解决。",
        "fields": [
            _field("account_id", "账户编号", str(account_id)),
            _field("membership_cutoff", "记录纳入截止", membership_cutoff),
            _field("read_at", "本次读取时间", read_at),
            _field("has_more", "还有下一批订单", "是" if has_more else "否"),
        ],
        "nested": [],
        "next_steps": steps,
        "sections": [
            {
                "key": "simulated_orders",
                "label": "本页订单",
                "columns": [
                    {"key": "order_id", "label": "订单编号"},
                    {"key": "asset_code", "label": "证券代码"},
                    {"key": "asset_name", "label": "证券名称"},
                    {"key": "side", "label": "方向"},
                    {"key": "status", "label": "订单状态"},
                    {"key": "quantity", "label": "委托数量"},
                    {"key": "filled_quantity", "label": "已成交数量"},
                    {"key": "limit_price", "label": "限价"},
                    {"key": "remaining_cash", "label": "剩余冻结现金"},
                    {"key": "remaining_shares", "label": "剩余冻结数量"},
                    {"key": "reserved_at", "label": "订单预留时间"},
                ],
                "rows": rows,
            }
        ],
    }


def _project_fills(
    payload: object,
    requested_params: Mapping[str, object],
) -> dict[str, object]:
    """Validate an exact order receipt page without inferring unrecorded fills."""

    account_id = _positive_int(requested_params.get("account_id"))
    order_id = _positive_int(requested_params.get("order_id"))
    limit = _page_limit(requested_params.get("limit", 5))
    response = _as_mapping(payload)
    if (
        account_id is None
        or order_id is None
        or limit is None
        or not _requested_cursor_valid(requested_params)
        or response is None
    ):
        return _blocked("成交回执", "账户、订单或分页范围无法核对；未显示回执。")
    page = _validate_page_envelope(
        response,
        requested_account_id=account_id,
        limit=limit,
        item_key="fills",
        requested_order_id=order_id,
    )
    if page is None or response.get("receipt_scope_note") != _RECEIPT_SCOPE_NOTE:
        return _blocked("成交回执", "订单范围或回执说明无法核对；未显示回执。")
    items, has_more, next_cursor, membership_cutoff, read_at = page
    rows: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    seen_receipt_ids: set[int] = set()
    for raw in items:
        row = _as_mapping(raw)
        normalized = _validated_fill(row) if row is not None else None
        if normalized is None:
            return _blocked("成交回执", "回执记录格式无法核对；未显示本页部分结果。")
        if (
            normalized["order_id"] != order_id
            or type(normalized["receipt_id"]) is not int
            or normalized["receipt_id"] in seen_receipt_ids
        ):
            return _blocked("成交回执", "回执与所选订单不匹配；未显示本页部分结果。")
        seen_receipt_ids.add(normalized["receipt_id"])
        rows.append(_table_row(normalized))
    if has_more:
        steps.append(
            {
                "label": "读取下一批回执",
                "action_key": _FILLS_ACTION,
                "params": {
                    "account_id": account_id,
                    "order_id": order_id,
                    "limit": limit,
                    "cursor": next_cursor,
                },
            }
        )
    empty_page = not rows
    return {
        "kind": "detail",
        "title": "模拟订单成交回执",
        "status": "本页未读取到已留存回执" if empty_page else "已读取已留存回执",
        "outcome": "success",
        "business_summary": _RECEIPT_SCOPE_NOTE + "单条核对不等于完整成交链证明。",
        "fields": [
            _field("account_id", "账户编号", str(account_id)),
            _field("order_id", "订单编号", str(order_id)),
            _field("membership_cutoff", "记录纳入截止", membership_cutoff),
            _field("read_at", "本次读取时间", read_at),
            _field("has_more", "还有下一批回执", "是" if has_more else "否"),
        ],
        "nested": [],
        "next_steps": steps,
        "sections": [
            {
                "key": "simulated_order_fills",
                "label": "本页已留存成交回执",
                "restriction_message": _RECEIPT_SCOPE_NOTE,
                "columns": [
                    {"key": "receipt_id", "label": "回执编号"},
                    {"key": "trade_id", "label": "成交编号"},
                    {"key": "fill_sequence", "label": "成交序号"},
                    {"key": "asset_code", "label": "证券代码"},
                    {"key": "side", "label": "方向"},
                    {"key": "quantity", "label": "成交数量"},
                    {"key": "price", "label": "成交价格"},
                    {"key": "event_time_label", "label": "时点含义"},
                    {"key": "occurred_at", "label": "发生或区间截止时点"},
                    {"key": "recorded_at", "label": "回执入库时间"},
                    {"key": "verification_status", "label": "核对范围"},
                ],
                "rows": rows,
            }
        ],
    }


def _project_decisions(
    payload: object, requested_params: Mapping[str, object]
) -> dict[str, object]:
    """Show retained decisions without confusing an absent receipt with a failed write."""
    account_id = _positive_int(requested_params.get("account_id"))
    order_id = _positive_int(requested_params.get("order_id"))
    limit = _page_limit(requested_params.get("limit", 5))
    response = _as_mapping(payload)
    failure = "撮合决定或入账范围无法核对；未显示本页部分结果。"
    if (
        account_id is None
        or order_id is None
        or limit is None
        or response is None
        or not _requested_cursor_valid(requested_params)
        or response.get("decision_scope_note") != _DECISION_SCOPE_NOTE
    ):
        return _blocked("撮合决定", failure)
    page = _validate_page_envelope(
        response,
        requested_account_id=account_id,
        requested_order_id=order_id,
        limit=limit,
        item_key="decisions",
    )
    if page is None:
        return _blocked("撮合决定", failure)
    items, has_more, next_cursor, membership_cutoff, read_at = page
    cutoff = _parse_aware_datetime(membership_cutoff)
    if cutoff is None:
        return _blocked("撮合决定", failure)
    rows: list[dict[str, object]] = []
    seen: set[int] = set()
    for raw in items:
        row = _as_mapping(raw)
        normalized = _validated_decision(row, order_id=order_id, cutoff=cutoff) if row else None
        if normalized is None:
            return _blocked("撮合决定", failure)
        decision_id = normalized["decision_id"]
        if type(decision_id) is not int or decision_id in seen:
            return _blocked("撮合决定", failure)
        seen.add(decision_id)
        rows.append(_table_row(normalized))
    steps: list[dict[str, object]] = [
        {
            "label": "核对本订单成交回执",
            "action_key": _FILLS_ACTION,
            "params": {"account_id": account_id, "order_id": order_id, "limit": limit},
        }
    ]
    if has_more:
        steps.append(
            {
                "label": "读取下一批撮合决定",
                "action_key": _DECISIONS_ACTION,
                "params": {
                    "account_id": account_id,
                    "order_id": order_id,
                    "limit": limit,
                    "cursor": next_cursor,
                },
            }
        )
    return {
        "kind": "detail",
        "title": "模拟订单撮合决定",
        "outcome": "success",
        "status": "已读取原撮合决定" if rows else "本页未读取到撮合决定",
        "business_summary": _DECISION_SCOPE_NOTE + "本页范围不代表全部待处理事项已解决。",
        "fields": [
            _field("account_id", "账户编号", str(account_id)),
            _field("order_id", "订单编号", str(order_id)),
            _field("membership_cutoff", "记录纳入截止", membership_cutoff),
            _field("read_at", "本次核对时间", read_at),
            _field("has_more", "还有下一批决定", "是" if has_more else "否"),
        ],
        "nested": [],
        "next_steps": steps,
        "sections": [
            {
                "key": "simulated_order_decisions",
                "label": "本页原撮合决定",
                "restriction_message": _DECISION_SCOPE_NOTE,
                "columns": [
                    {"key": key, "label": label}
                    for key, label in (
                        ("decision_id", "决定编号"),
                        ("session_date", "撮合交易日"),
                        ("outcome", "原撮合结果"),
                        ("posting_state", "入账核对状态"),
                        ("matched_quantity", "撮合数量"),
                        ("matched_price", "撮合价格"),
                        ("occurred_at", "日线区间截止"),
                        ("recorded_at", "决定保存时间"),
                        ("receipt_id", "原回执编号"),
                        ("trade_id", "原成交编号"),
                    )
                ],
                "rows": rows,
            }
        ],
    }


def _validated_decision(
    row: Mapping[str, object], *, order_id: int, cutoff: datetime
) -> dict[str, object] | None:
    """Whitelist consistent outcome/receipt states and preserve source decimal text."""
    decision_id = _positive_int(row.get("decision_id"))
    quantity = _decimal_text(row.get("matched_quantity"))
    recorded_at = _aware_iso(row.get("recorded_at"))
    recorded = _parse_aware_datetime(recorded_at)
    session = row.get("session_date")
    if (
        decision_id is None
        or _positive_int(row.get("order_id")) != order_id
        or quantity is None
        or recorded is None
        or recorded > cutoff
        or type(session) is not str
    ):
        return None
    try:
        if date.fromisoformat(session).isoformat() != session:
            return None
    except ValueError:
        return None
    outcome = row.get("outcome")
    state = row.get("posting_state")
    receipt_id = _positive_int(row.get("receipt_id"))
    trade_id = _positive_int(row.get("trade_id"))
    price = _decimal_text(row.get("matched_price"))
    occurred_at = _aware_iso(row.get("occurred_at"))
    occurred = _parse_aware_datetime(occurred_at)
    if outcome == "matched":
        if (
            Decimal(quantity) <= 0
            or price is None
            or Decimal(price) <= 0
            or occurred is None
            or occurred > recorded
            or state not in ("applied", "unconfirmed")
        ):
            return None
        if state == "applied" and (receipt_id is None or trade_id is None):
            return None
    elif outcome == "no_match":
        if (
            Decimal(quantity) != 0
            or row.get("matched_price") is not None
            or row.get("occurred_at") is not None
            or state != "not_applicable"
        ):
            return None
    else:
        return None
    if state != "applied" and (
        row.get("receipt_id") is not None or row.get("trade_id") is not None
    ):
        return None
    label = (
        "已核对原成交回执"
        if state == "applied"
        else "入账尚未确认" if state == "unconfirmed" else "本次未撮合成交"
    )
    return {
        "decision_id": decision_id,
        "session_date": session,
        "outcome": "已生成模拟成交" if outcome == "matched" else "本次未撮合成交",
        "posting_state": label,
        "matched_quantity": quantity,
        "matched_price": price,
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "receipt_id": receipt_id,
        "trade_id": trade_id,
    }


def _validate_page_envelope(
    response: Mapping[str, object],
    *,
    requested_account_id: int,
    limit: int,
    item_key: str = "orders",
    requested_order_id: int | None = None,
) -> tuple[list[object], bool, str | None, str, str] | None:
    """Require response identity, page bounds, and both explicit page clocks."""

    response_account_id = _positive_int(response.get("account_id"))
    response_order_id = (
        _positive_int(response.get("order_id")) if requested_order_id is not None else None
    )
    items = response.get(item_key)
    has_more = response.get("has_more")
    cursor_value = response.get("next_cursor")
    membership = _aware_iso(response.get("membership_cutoff"))
    read_at = _aware_iso(response.get("read_at"))
    membership_datetime = _parse_aware_datetime(membership)
    read_datetime = _parse_aware_datetime(read_at)
    if (
        response.get("success") is not True
        or response_account_id != requested_account_id
        or (requested_order_id is not None and response_order_id != requested_order_id)
        or not isinstance(items, list)
        or len(items) > limit
        or type(has_more) is not bool
        or membership is None
        or read_at is None
        or membership_datetime is None
        or read_datetime is None
        or membership_datetime > read_datetime
        or not _valid_cursor(cursor_value)
        or has_more != (cursor_value is not None)
        or (has_more and not items)
    ):
        return None
    cursor = cursor_value if type(cursor_value) is str else None
    return items, has_more, cursor, membership, read_at


def _validated_order(row: Mapping[str, object]) -> dict[str, object] | None:
    """Whitelist display-safe order fields and preserve exact decimal strings."""

    order_id = _positive_int(row.get("order_id"))
    asset_code = _bounded_text(row.get("asset_code"), 20)
    asset_name = _bounded_text(row.get("asset_name"), 100)
    side = _side_label(row.get("side"))
    status = _order_status_label(row.get("status"))
    reserved_at = _aware_iso(row.get("reserved_at"))
    quantity = _decimal_text(row.get("quantity"))
    filled_quantity = _decimal_text(row.get("filled_quantity"))
    limit_price = _decimal_text(row.get("limit_price"))
    remaining_cash = _decimal_text(row.get("remaining_cash"))
    remaining_shares = _decimal_text(row.get("remaining_shares"))
    values = (
        order_id,
        asset_code,
        asset_name,
        side,
        status,
        quantity,
        filled_quantity,
        limit_price,
        remaining_cash,
        remaining_shares,
        reserved_at,
    )
    if any(value is None for value in values):
        return None
    return {
        "order_id": order_id,
        "asset_code": asset_code,
        "asset_name": asset_name,
        "side": side,
        "status": status,
        "quantity": quantity,
        "filled_quantity": filled_quantity,
        "limit_price": limit_price,
        "remaining_cash": remaining_cash,
        "remaining_shares": remaining_shares,
        "reserved_at": reserved_at,
    }


def _validated_fill(row: Mapping[str, object]) -> dict[str, object] | None:
    """Whitelist one receipt while preserving basis and clock distinctions."""

    receipt_id = _positive_int(row.get("receipt_id"))
    trade_id = _positive_int(row.get("trade_id"))
    order_id = _positive_int(row.get("order_id"))
    fill_sequence = _positive_int(row.get("fill_sequence"))
    asset_code = _bounded_text(row.get("asset_code"), 20)
    side = _side_label(row.get("side"))
    quantity = _decimal_text(row.get("quantity"))
    price = _decimal_text(row.get("price"))
    occurred_at = _aware_iso(row.get("occurred_at"))
    recorded_at = _aware_iso(row.get("recorded_at"))
    basis = row.get("observation_basis")
    verification = row.get("verification_status")
    if (
        receipt_id is None
        or trade_id is None
        or order_id is None
        or fill_sequence is None
        or asset_code is None
        or side is None
        or quantity is None
        or price is None
        or occurred_at is None
        or recorded_at is None
        or type(basis) is not str
        or basis not in {"legacy_source_observed", "daily_interval_end"}
        or verification != "single_receipt_verified"
    ):
        return None
    return {
        "receipt_id": receipt_id,
        "trade_id": trade_id,
        "order_id": order_id,
        "fill_sequence": fill_sequence,
        "asset_code": asset_code,
        "side": side,
        "quantity": quantity,
        "price": price,
        "event_time_label": ("日线区间截止" if basis == "daily_interval_end" else "模拟成交时刻"),
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "verification_status": "单条回执已核对",
    }


def _table_row(values: Mapping[str, object]) -> dict[str, object]:
    """Return one section-table row without adding numeric conversions."""

    return {"fields": [{"key": key, "label": key, "value": value} for key, value in values.items()]}


def _field(key: str, label: str, value: object) -> dict[str, object]:
    """Build one safe scalar detail field."""

    return {"key": key, "label": label, "value": value}


def _blocked(title: str, message: str) -> dict[str, object]:
    """Return an empty bounded result so stale rows cannot survive a bad scope."""

    return {
        "kind": "detail",
        "title": title,
        "status": "读取受限",
        "outcome": "blocked",
        "business_summary": message,
        "blocking_reason": message,
        "fields": [],
        "nested": [],
        "sections": [],
        "next_steps": [],
    }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Return a string-keyed JSON object without coercing its members."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        return None
    return value


def _positive_int(value: object) -> int | None:
    """Parse one positive JSON integer without accepting booleans or floats."""

    if type(value) is int:
        return value if value > 0 else None
    if type(value) is str and value.isascii() and value.isdigit():
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return None
        return parsed if parsed > 0 else None
    return None


def _page_limit(value: object) -> int | None:
    """Use the visible default while keeping the API's bounded page contract."""

    parsed = _positive_int(value)
    return parsed if parsed is not None and parsed <= _PAGE_LIMIT_MAX else None


def _valid_cursor(value: object) -> bool:
    """Require the server's opaque cursor shape without decoding or displaying it."""

    return value is None or (
        type(value) is str
        and bool(value)
        and len(value) <= _CURSOR_MAX_LENGTH
        and not any(character.isspace() for character in value)
    )


def _requested_cursor_valid(params: Mapping[str, object]) -> bool:
    """Validate a supplied hidden cursor without making it visible to the owner."""

    return "cursor" not in params or _valid_cursor(params.get("cursor"))


def _bounded_text(value: object, maximum: int) -> str | None:
    """Require one bounded exact text value."""

    if type(value) is not str or not value or len(value) > maximum or value.strip() != value:
        return None
    return value


def _side_label(value: object) -> str | None:
    """Translate the two canonical order directions for the owner view."""

    return {"buy": "买入", "sell": "卖出"}.get(value) if type(value) is str else None


def _order_status_label(value: object) -> str | None:
    """Translate only the existing reservation states."""

    if type(value) is not str:
        return None
    return {"active": "有效", "completed": "已完成", "cancelled": "已取消"}.get(value)


def _decimal_text(value: object) -> str | None:
    """Validate finite decimal text and preserve its original precision and scale."""

    if type(value) is not str or not value or len(value) > 64 or value.strip() != value:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return value if parsed.is_finite() else None


def _aware_iso(value: object) -> str | None:
    """Require an offset-bearing ISO timestamp and retain its received spelling."""

    if type(value) is not str or not value:
        return None
    return value if _parse_aware_datetime(value) is not None else None


def _parse_aware_datetime(value: str | None) -> datetime | None:
    """Parse one aware timestamp only for chronology validation."""

    if value is None:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
    except (OverflowError, TypeError, ValueError):
        return None
    return parsed


__all__ = ("project_tui_order_history_result",)
