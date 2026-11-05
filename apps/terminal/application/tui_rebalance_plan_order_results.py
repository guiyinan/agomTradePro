"""Project exact plan-order rows and owner previews without exposing action secrets."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import TypedDict, cast


class PlanOrderGridRow(TypedDict):
    """Carry hidden exact order pins beside safe, formatted grid values."""

    account_id: int
    plan_id: str
    plan_version: int
    revision_hash_id: str
    order_ordinal: int
    order_content_hash: str
    plan_order_binding_id: str
    order_label: str
    approved_label: str
    filled_label: str
    in_flight_label: str
    released_label: str
    remaining_label: str
    price_label: str
    limit_label: str
    status_label: str
    capability_label: str


class PlanOrderProjection(TypedDict, total=False):
    """Contain only user-facing display fields and private row-action bindings."""

    kind: str
    title: str
    status: str
    business_summary: str
    empty_message: str
    empty_guidance: list[str]
    columns: list[dict[str, str]]
    rows: Sequence[PlanOrderGridRow]
    total: int
    next_steps: list[str]
    debug_hidden_fields: list[str]
    read_only: bool
    must_not_execute: bool
    outcome: str
    fields: list[dict[str, str]]


_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_STATUS_LABELS = {
    "draft": "待核对",
    "ready": "可继续核对",
    "blocked": "当前受限",
    "expired": "已超过有效期限",
    "inactive": "未启用",
    "pending_review": "等待独立复核",
    "approval_pending": "等待独立复核",
    "review_requested": "已提交独立复核申请",
    "approved": "计划状态为已批准；仍需核对独立审批与当前资格",
    "reviewed": "计划状态为已复核；仍需核对当前来源和资格",
    "partial": "部分完成",
    "complete": "已完成",
    "unknown": "状态未知",
}


def project_rebalance_plan_orders(
    plan: Mapping[str, object],
    identity: Mapping[str, object],
    progress: Mapping[str, object] | None,
    account_id: int,
    *,
    can_preview_order: bool = False,
    can_cancel: bool = False,
) -> PlanOrderProjection:
    """Render one exact revision as order rows with separately verified ledger progress."""

    plan_id = _string(identity.get("plan_id"))
    version = _positive_int(identity.get("version"))
    revision_hash = _string(identity.get("revision_hash"))
    raw_orders = _sequence(plan.get("orders"))
    if (
        plan_id is None
        or version is None
        or revision_hash is None
        or not _is_sha256(revision_hash)
        or not raw_orders
    ):
        return _blocked_result()
    progress_by_ordinal: dict[int, Mapping[str, object]] = {}
    if progress is not None:
        for raw_progress_order in _sequence(progress.get("orders")):
            item = _mapping(raw_progress_order)
            order_binding = _mapping(item.get("order")) if item else None
            if item is not None and order_binding is None:
                order_binding = item
            ordinal = _nonnegative_int(order_binding.get("ordinal")) if order_binding else None
            if item is None or ordinal is None or ordinal in progress_by_ordinal:
                return _blocked_result()
            progress_by_ordinal[ordinal] = item
    rows: list[PlanOrderGridRow] = []
    for raw_order in raw_orders:
        order = _mapping(raw_order)
        if order is None:
            return _blocked_result()
        ordinal = _nonnegative_int(order.get("ordinal"))
        order_hash = _string(order.get("order_content_hash"))
        binding_id = _string(order.get("plan_order_binding_id"))
        asset = _string(order.get("asset_code"))
        side = order.get("side")
        approved = _nonnegative_int(order.get("approved_quantity"))
        if ordinal is None or order_hash is None or binding_id is None:
            return _blocked_result()
        if not _is_sha256(order_hash) or not _is_sha256(binding_id):
            return _blocked_result()
        if asset is None or side not in {"buy", "sell"} or approved is None:
            return _blocked_result()
        item = progress_by_ordinal.get(ordinal)
        progress_binding = _mapping(item.get("order")) if item else None
        if item is not None and progress_binding is None:
            progress_binding = item
        if item is not None and (
            progress_binding is None
            or progress_binding.get("order_content_hash") != order_hash
            or progress_binding.get("plan_order_binding_id") != binding_id
            or progress_binding.get("approved_quantity") != approved
            or progress_binding.get("asset_code") != asset
            or progress_binding.get("security_id") != order.get("security_id")
            or progress_binding.get("asset_type") != order.get("asset_type")
            or progress_binding.get("classification_content_hash")
            != order.get("classification_content_hash")
            or progress_binding.get("side") != side
            or progress_binding.get("quantity_unit") != order.get("quantity_unit")
            or progress_binding.get("money_unit") != order.get("money_unit")
        ):
            return _blocked_result()
        can_preview = item.get("can_preview") if item else None
        capability_label = (
            "可进入当前单笔预览"
            if can_preview is True and can_preview_order
            else (
                "当前不能继续预览"
                if can_preview is False or not can_preview_order
                else "余量资格未知；需重新核对"
            )
        )
        quantity_unit = _string(order.get("quantity_unit")) or "数量单位未知"
        money_unit = _string(order.get("money_unit")) or "金额单位未知"
        ledger = _mapping(item.get("progress")) if item else None
        rows.append(
            {
                "account_id": account_id,
                "plan_id": plan_id,
                "plan_version": version,
                "revision_hash_id": revision_hash,
                "order_ordinal": ordinal,
                "order_content_hash": order_hash,
                "plan_order_binding_id": binding_id,
                "order_label": f"{asset} {_side_label(side)}",
                "approved_label": _value(approved, quantity_unit),
                "filled_label": _value(
                    ledger.get("filled_quantity") if ledger else None, quantity_unit
                ),
                "in_flight_label": _value(
                    ledger.get("in_flight_quantity") if ledger else None, quantity_unit
                ),
                "released_label": _value(
                    ledger.get("released_quantity") if ledger else None, quantity_unit
                ),
                "remaining_label": _value(
                    ledger.get("unreserved_remaining_quantity") if ledger else None,
                    quantity_unit,
                ),
                "price_label": _value(order.get("reference_price"), money_unit),
                "limit_label": (
                    _value(order.get("approved_limit_price"), money_unit)
                    if order.get("approved_limit_price") is not None
                    else "计划未设限价；本次仍须明确输入"
                ),
                "status_label": _status_label(order.get("status")),
                "capability_label": capability_label,
            }
        )
    next_steps = ["从订单行发起单笔数量和限价预览；预览不建立预留，须另行确认。"]
    next_steps.append(
        "预留后的订单详情、成交撮合、成交回执和撤销仍在 TUI“本人模拟下单”任务中逐单处理；"
        "请先选择同一模拟账户并核对实际订单。计划不会自动撤销、撮合或成交。"
        if can_cancel
        else "只读时可在 TUI“本人模拟下单”任务查看同一账户的订单历史；此处不能撤销、撮合或入账。"
    )
    if can_cancel and any(item.get("can_cancel") is True for item in progress_by_ordinal.values()):
        next_steps.append(
            "当前存在可核验的有效预留；在“本人模拟下单”中核对对应订单后，仍须单独确认撤销或撮合。"
        )
    return {
        "kind": "datagrid",
        "title": "计划订单、真实成交与有效预留",
        "status": "已读取精确计划订单" if progress is not None else "余量核对未知",
        "business_summary": "每一行对应所选计划版本。参考价不是本次限价；确认前仍会重新核对当前事实。",
        "columns": [
            {"key": "order_label", "label": "计划订单"},
            {"key": "approved_label", "label": "批准数量"},
            {"key": "filled_label", "label": "已核实成交"},
            {"key": "in_flight_label", "label": "仍有效预留"},
            {"key": "released_label", "label": "已释放未成交量"},
            {"key": "remaining_label", "label": "尚未预留余量"},
            {"key": "price_label", "label": "计划参考价（非限价）"},
            {"key": "limit_label", "label": "批准限价"},
            {"key": "capability_label", "label": "当前单笔预览资格"},
        ],
        "rows": rows,
        "total": len(rows),
        "empty_message": "该计划没有可展示的订单行。",
        "empty_guidance": ["如果成交、预留或余量无法核实，请先刷新计划对账。"],
        "next_steps": next_steps,
        "read_only": True,
        "must_not_execute": True,
        "debug_hidden_fields": [
            "account_id",
            "plan_id",
            "plan_version",
            "revision_hash_id",
            "order_ordinal",
            "order_content_hash",
            "plan_order_binding_id",
        ],
    }


def project_rebalance_plan_order_preview(
    plan: Mapping[str, object],
    identity: Mapping[str, object],
    envelope: Mapping[str, object],
    requested: Mapping[str, object],
    account_id: int,
) -> PlanOrderProjection:
    """Render an owner preview only after rechecking every plan and order binding."""

    capabilities = _mapping(envelope.get("capabilities"))
    if (
        capabilities is None
        or capabilities.get("read_only") is not False
        or capabilities.get("can_preview_order") is not True
    ):
        return _blocked_result()

    ordinal = _nonnegative_int(requested.get("order_ordinal"))
    if ordinal is None:
        return _blocked_result()
    plan_order = _plan_order(plan, ordinal)
    preview_envelope = _mapping(envelope.get("preview"))
    binding = _mapping(preview_envelope.get("binding")) if preview_envelope else None
    owner_preview = _mapping(preview_envelope.get("preview")) if preview_envelope else None
    if plan_order is None or binding is None or owner_preview is None:
        return _blocked_result()
    if preview_envelope is None or preview_envelope.get("revision_recorded_at") != identity.get(
        "recorded_at"
    ):
        return _blocked_result()
    if not _preview_binding_matches(binding, plan_order, identity, requested, account_id):
        return _blocked_result()
    if (
        owner_preview.get("success") is not True
        or owner_preview.get("read_only") is not True
        or owner_preview.get("execution_submitted") is not False
        or owner_preview.get("purpose") != owner_preview.get("market_purpose")
    ):
        return _blocked_result()
    order = _mapping(owner_preview.get("order"))
    if order is None or not _owner_preview_order_matches(order, binding, requested):
        return _blocked_result()
    continuation = _mapping(envelope.get("continuation"))
    if continuation is None or not _preview_continuation_matches(
        continuation, owner_preview, order, binding, account_id
    ):
        return _blocked_result()
    market = _mapping(owner_preview.get("market"))
    market_notice = _string(owner_preview.get("market_notice"))
    if market is None or market_notice is None:
        return _blocked_result()
    quantity_unit = _string(binding.get("quantity_unit")) or "数量单位未知"
    money_unit = _string(binding.get("money_unit")) or "金额单位未知"
    fields = [
        _field(
            "plan_line",
            "计划订单",
            f"{_string(binding.get('asset_code')) or '证券未知'} {_side_label(binding.get('side'))}",
        ),
        _field("requested_quantity", "本次预览数量", _value(order.get("quantity"), quantity_unit)),
        _field("requested_limit", "本次预览限价", _value(order.get("limit_price"), money_unit)),
        _field("execution_permission", "当前动作", "只完成单笔预览；尚未预留或成交"),
        _field(
            "fee_estimate",
            "预计费用（不是实际费用）",
            _value(order.get("fee_estimate"), money_unit),
        ),
        _field("fee_budget", "费用上限", _value(order.get("fee_budget"), money_unit)),
        _field(
            "cash_reserved", "本次预览拟占用资金", _value(order.get("cash_reserved"), money_unit)
        ),
        _field(
            "shares_reserved",
            "本次预览拟占用数量",
            _value(order.get("shares_reserved"), quantity_unit),
        ),
        _field("available_cash", "当前可用资金", _value(order.get("available_cash"), money_unit)),
        _field(
            "withdrawable_cash", "当前可取资金", _value(order.get("withdrawable_cash"), money_unit)
        ),
        _field(
            "available_shares", "当前可用数量", _value(order.get("available_shares"), quantity_unit)
        ),
        _field(
            "market_purpose",
            "本次模拟行情用途",
            _purpose_label(owner_preview.get("market_purpose")),
        ),
        _field("market_notice", "行情限制", market_notice),
        _field(
            "market_observed_at", "行情原始观测时点", _time_label(market.get("market_observed_at"))
        ),
        _field(
            "market_available_at", "系统可用时点", _time_label(market.get("market_available_at"))
        ),
        _field("market_valid_until", "供应方有效期", _time_label(market.get("market_valid_until"))),
        _field("market_session", "行情时段状态", _string(market.get("market_session")) or "未知"),
        _field("market_trade_date", "行情交易日", _time_label(market.get("trade_date"))),
        _field(
            "market_security_state", "证券状态", _string(market.get("security_state")) or "未知"
        ),
        _field(
            "market_price_boundary",
            "价格边界",
            _string(market.get("price_boundary_mode")) or "未知",
        ),
    ]
    return {
        "kind": "detail",
        "title": "模拟订单单笔预览",
        "status": "预览已生成；尚未建立预留",
        "business_summary": "此预览绑定所选计划版本和单行订单。只有再次明确确认才会建立模拟预留，不会提交给券商。",
        "fields": fields,
        "next_steps": [
            "核对数量、限价、费用、可用资金或数量以及来源限制。",
            "如需继续，使用单独的模拟订单确认步骤；结果不确定时按原订单查询。",
        ],
        "read_only": True,
        "must_not_execute": True,
        "outcome": "单笔模拟预览",
        "debug_hidden_fields": [
            "account_id",
            "plan_id",
            "plan_version",
            "revision_hash",
            "order_ordinal",
            "order_content_hash",
            "plan_order_binding_id",
            "owner_user_id",
            "action_attempt_key",
            "order_key",
            "preview_token",
        ],
    }


def _plan_order(plan: Mapping[str, object], ordinal: int) -> Mapping[str, object] | None:
    """Find one unique immutable order line by its zero-based ordinal."""

    found: Mapping[str, object] | None = None
    for raw_order in _sequence(plan.get("orders")):
        order = _mapping(raw_order)
        if order is None:
            return None
        if order.get("ordinal") == ordinal:
            if found is not None:
                return None
            found = order
    return found


def _preview_binding_matches(
    binding: Mapping[str, object],
    order: Mapping[str, object],
    identity: Mapping[str, object],
    requested: Mapping[str, object],
    account_id: int,
) -> bool:
    """Match the owner preview to the exact saved plan, order and actor scope."""

    version = _positive_int(identity.get("version"))
    ordinal = _nonnegative_int(requested.get("order_ordinal"))
    owner_id = _positive_int(identity.get("owner_user_id"))
    expected = (
        version is not None
        and ordinal is not None
        and binding.get("plan_id") == identity.get("plan_id")
        and binding.get("family_id") == identity.get("family_id")
        and binding.get("root_plan_id") == identity.get("root_plan_id")
        and binding.get("plan_version") == version
        and binding.get("revision_hash") == identity.get("revision_hash")
        and binding.get("order_ordinal") == ordinal
        and binding.get("plan_order_binding_id") == order.get("plan_order_binding_id")
        and binding.get("order_content_hash") == order.get("order_content_hash")
        and binding.get("account_id") == account_id
        and (owner_id is None or binding.get("owner_user_id") == owner_id)
        and binding.get("asset_code") == order.get("asset_code")
        and binding.get("security_id") == order.get("security_id")
        and binding.get("asset_type") == order.get("asset_type")
        and binding.get("classification_content_hash") == order.get("classification_content_hash")
        and binding.get("side") == order.get("side")
        and binding.get("approved_quantity") == order.get("approved_quantity")
        and binding.get("approved_limit_price") == order.get("approved_limit_price")
        and binding.get("quantity_unit") == order.get("quantity_unit")
        and binding.get("money_unit") == order.get("money_unit")
        and binding.get("plan_expires_at") == identity.get("valid_until")
        and binding.get("reference_price_is_executable_limit") is False
        and binding.get("estimated_fee_is_actual_fee") is False
        and _nonempty_token(binding.get("action_attempt_key"))
    )
    return (
        expected
        and binding.get("order_content_hash") == requested.get("order_content_hash")
        and binding.get("plan_order_binding_id") == requested.get("plan_order_binding_id")
    )


def _owner_preview_order_matches(
    order: Mapping[str, object], binding: Mapping[str, object], requested: Mapping[str, object]
) -> bool:
    """Confirm the reusable owner preview carries the user's exact numeric intent."""

    quantity = _decimal_value(requested.get("quantity"))
    limit_price = _decimal_value(requested.get("limit_price"))
    returned_quantity = _decimal_value(order.get("quantity"))
    returned_limit = _decimal_value(order.get("limit_price"))
    approved_quantity = _decimal_value(str(binding.get("approved_quantity")))
    approved_limit = _decimal_value(binding.get("approved_limit_price"))
    return (
        quantity is not None
        and limit_price is not None
        and approved_quantity is not None
        and quantity <= approved_quantity
        and (
            binding.get("approved_limit_price") is None
            or (approved_limit is not None and limit_price == approved_limit)
        )
        and order.get("security_id") == binding.get("security_id")
        and order.get("side") == binding.get("side")
        and returned_quantity == quantity
        and returned_limit == limit_price
        and _nonempty_token(order.get("idempotency_key"))
    )


def _preview_continuation_matches(
    continuation: Mapping[str, object],
    preview: Mapping[str, object],
    order: Mapping[str, object],
    binding: Mapping[str, object],
    account_id: int,
) -> bool:
    """Require the hidden ordinary confirmation handoff to match the same attempt."""

    continuation_input = _mapping(continuation.get("input"))
    if continuation_input is None or set(continuation_input) != {
        "account_id",
        "order_key",
        "preview_token",
    }:
        return False
    order_key = continuation_input.get("order_key")
    token = continuation_input.get("preview_token")
    expiry = continuation.get("expires_at")
    return (
        continuation.get("action_key") == "simulated-trading.order-confirm"
        and continuation_input.get("account_id") == str(account_id)
        and _nonempty_token(order_key)
        and order.get("idempotency_key") == order_key
        and _nonempty_token(token)
        and type(expiry) is str
        and bool(expiry)
        and "continuation" not in preview
        and "preview_token" not in preview
    )


def _blocked_result() -> PlanOrderProjection:
    """Return no stale or mismatched plan-order content."""

    return {
        "kind": "detail",
        "title": "计划订单暂不可展示",
        "status": "需要重新读取",
        "business_summary": "订单、预览或账户范围无法与所选计划版本对应；没有沿用旧结果。",
        "fields": [_field("permission", "计划订单", "当前数据无法与所选计划版本对应。")],
        "next_steps": ["重新读取本人或已授权查看的计划版本和订单进度。"],
        "read_only": True,
        "must_not_execute": True,
        "outcome": "unknown",
        "debug_hidden_fields": ["plan_id", "revision_hash", "owner_user_id"],
    }


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow JSON objects before reading a business field."""

    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object]:
    """Return a JSON array and nothing else."""

    return cast(Sequence[object], value) if isinstance(value, list) else ()


def _string(value: object) -> str | None:
    """Retain non-empty display strings without coercing arbitrary objects."""

    return value.strip()[:160] if isinstance(value, str) and value.strip() else None


def _is_sha256(value: object) -> bool:
    """Accept only exact lower-case plan digest text."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_int(value: object) -> int | None:
    """Accept positive integer identifiers without string or boolean coercion."""

    return value if type(value) is int and value > 0 else None


def _nonnegative_int(value: object) -> int | None:
    """Accept a zero-based ordinal without string or boolean coercion."""

    return value if type(value) is int and value >= 0 else None


def _field(key: str, label: str, value: str) -> dict[str, str]:
    """Build a bounded user-facing field."""

    return {"key": key, "label": label, "value": value}


def _value(value: object, unit: str) -> str:
    """Format an exact number with its declared unit and keep None unknown."""

    if value is None:
        return "未知"
    if type(value) is int:
        numeric = str(value)
    elif isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
        try:
            numeric = format(Decimal(value.strip()), "f")
        except InvalidOperation:
            return "未知"
    else:
        return "未知"
    return f"{numeric} {unit}"


def _decimal_value(value: object) -> Decimal | None:
    """Parse finite decimal text without a binary floating-point conversion."""

    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if not isinstance(value, str) or not _NUMBER.fullmatch(value.strip()):
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _nonempty_token(value: object) -> bool:
    """Check a private protocol token without copying it into display values."""

    return isinstance(value, str) and bool(value) and value.strip() == value


def _time_label(value: object) -> str:
    """Preserve the original ISO clock and keep a missing clock unknown."""

    text = _string(value)
    return text if text is not None else "未提供；保持未知"


def _status_label(value: object) -> str:
    """Translate only established lifecycle states."""

    token = value.strip().lower() if isinstance(value, str) else ""
    return _STATUS_LABELS.get(token, "状态未知")


def _side_label(value: object) -> str:
    """Translate supported directions."""

    return "买入" if value == "buy" else "卖出" if value == "sell" else "方向未知"


def _purpose_label(value: object) -> str:
    """Translate a market-use token without surfacing permission internals."""

    if value == "close_snapshot_simulation":
        return "受限盘后模拟参考"
    if value == "ash07_capacity":
        return "模拟计划参考"
    if isinstance(value, str) and value:
        return "受限模拟用途"
    return "用途未知"
