"""Project saved rebalance-plan responses into a safe task-focused TUI result."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import NotRequired, TypedDict, cast

from apps.terminal.application.tui_rebalance_plan_order_results import (
    PlanOrderGridRow,
    _status_label,
    project_rebalance_plan_order_preview,
    project_rebalance_plan_orders,
)


class _Field(TypedDict):
    key: str
    label: str
    value: str


class _Column(TypedDict):
    key: str
    label: str


class _GridRow(TypedDict):
    account_id: int
    account_name: NotRequired[str]
    plan_id: str
    plan_version: int
    revision_hash_id: str
    version_label: str
    recorded_label: str
    status_label: str
    orders_label: str
    progress_label: str
    validity_label: str


class RebalancePlanTaskResult(TypedDict, total=False):
    """Contain only safe, already formatted user-facing result values."""

    kind: str
    title: str
    status: str
    business_summary: str
    blocking_reason: str
    empty_message: str
    empty_guidance: list[str]
    fields: list[_Field]
    columns: list[_Column]
    rows: Sequence[_GridRow | PlanOrderGridRow]
    total: int
    sections: list[dict[str, object]]
    next_steps: list[str]
    debug_hidden_fields: list[str]
    outcome: str
    read_only: bool
    must_not_execute: bool


_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_SOURCE_LABELS = {
    "industry_membership": "行业分类",
    "valuation": "估值参考",
    "etf_report": "基金披露",
    "capacity_window": "成交容量",
    "execution_session_state": "报价时点状态",
    "scenario_market": "情景参考",
}
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


def project_rebalance_plan_result(
    action_key: str,
    payload: object,
    *,
    requested_params: Mapping[str, object] | None,
    http_status: int,
) -> RebalancePlanTaskResult:
    """Render saved plans and actual progress without exposing internal pins.

    The projection does not infer execution permission from plan status. It uses
    only server-produced capabilities and exact revision identity supplied in
    the response. Financial `None` values stay visibly unknown.
    """

    if http_status < 200 or http_status >= 300:
        return _blocked_result()
    envelope = _mapping(payload)
    if envelope is None or envelope.get("success") is not True:
        return _blocked_result()
    if action_key == "rebalance-plan.accounts":
        return _project_accounts(envelope)
    if action_key == "rebalance-plan.account-detail":
        return _project_account_detail(envelope, requested_params)
    account_id = _positive_int(envelope.get("account_id"))
    expected_account = _positive_int((requested_params or {}).get("account_id"))
    if account_id is None or expected_account not in {None, account_id}:
        return _blocked_result()
    if action_key == "rebalance-plan.list":
        return _project_list(envelope, account_id)
    plan = _mapping(envelope.get("plan"))
    if plan is None or not _plan_account_matches(plan, account_id) or not _trusted_plan_shape(plan):
        return _blocked_result()
    identity = _mapping(plan.get("identity"))
    if identity is None:
        return _blocked_result()
    if action_key in {
        "rebalance-plan.read",
        "rebalance-plan.reconcile",
    } and not _matches_requested_revision(identity, requested_params or {}):
        return _blocked_result()
    if action_key in {
        "rebalance-plan.orders",
        "rebalance-plan.preview-order",
    } and not _matches_requested_revision(identity, requested_params or {}):
        return _blocked_result()
    progress = _verified_progress(envelope.get("progress"), identity, plan)
    if action_key == "rebalance-plan.orders":
        capabilities = _mapping(envelope.get("capabilities")) or {}
        writable = capabilities.get("read_only") is False
        return cast(
            RebalancePlanTaskResult,
            project_rebalance_plan_orders(
                plan,
                identity,
                progress,
                account_id,
                can_preview_order=writable and capabilities.get("can_preview_order") is True,
                can_cancel=writable,
            ),
        )
    if action_key == "rebalance-plan.preview-order":
        return cast(
            RebalancePlanTaskResult,
            project_rebalance_plan_order_preview(
                plan, identity, envelope, requested_params or {}, account_id
            ),
        )
    return _project_revision(action_key, plan, identity, progress, envelope)


def _project_accounts(envelope: Mapping[str, object]) -> RebalancePlanTaskResult:
    """Provide an owned simulated-account entry without showing operational flags."""

    raw_accounts = _sequence(envelope.get("accounts"))
    rows: list[_GridRow] = []
    for raw_account in raw_accounts:
        account = _mapping(raw_account)
        if account is None:
            continue
        account_id = _positive_int(account.get("account_id"))
        if account_id is None:
            continue
        cash = account.get("current_cash") if account.get("cash_known") is True else None
        market_value = account.get("current_market_value")
        rows.append(
            {
                "account_id": account_id,
                "plan_id": "",
                "plan_version": 0,
                "revision_hash_id": "",
                "account_name": _string(account.get("account_name")) or "模拟账户",
                "version_label": _string(account.get("account_name")) or "模拟账户",
                "recorded_label": "账户摘要读取",
                "status_label": _account_cash_status(account.get("cash_reconciliation_status")),
                "orders_label": _value(cash, "单位未提供"),
                "progress_label": _value(market_value, "单位与估值时点未提供"),
                "validity_label": "现有账本摘要；不代表实时行情",
            }
        )
    return {
        "kind": "datagrid",
        "title": "本人模拟账户",
        "status": "已读取模拟账户" if rows else "没有可用的本人活跃模拟账户",
        "business_summary": "选择本人模拟账户后查看现金、持仓估值状态与已保存计划。",
        "columns": [
            {"key": "version_label", "label": "模拟账户"},
            {"key": "status_label", "label": "现金核对"},
            {"key": "orders_label", "label": "账面现金"},
            {"key": "progress_label", "label": "持仓估值"},
            {"key": "validity_label", "label": "数据说明"},
        ],
        "rows": rows,
        "total": len(rows),
        "empty_message": "当前没有可用的本人活跃模拟账户。",
        "empty_guidance": ["账户资料缺少币种或估值时点时，金额按未知单位或未知时点展示。"],
        "next_steps": ["从账户行打开计划；系统会再读取该账户的实际来源、风险和规则。"],
        "read_only": True,
        "must_not_execute": True,
        "debug_hidden_fields": ["account_id"],
    }


def _project_account_detail(
    envelope: Mapping[str, object], requested_params: Mapping[str, object] | None
) -> RebalancePlanTaskResult:
    """Show ledger cash and stored valuation with explicit missing unit/time limits."""

    account = _mapping(envelope.get("account"))
    if account is None:
        return _blocked_result()
    account_id = _positive_int(account.get("account_id"))
    expected_account = _positive_int((requested_params or {}).get("account_id"))
    if account_id is None or expected_account not in {None, account_id}:
        return _blocked_result()
    cash = account.get("current_cash") if account.get("cash_known") is True else None
    fields = [
        _field("account_name", "模拟账户", _string(account.get("account_name")) or "本人模拟账户"),
        _field("current_cash", "账面现金", _value(cash, "单位未提供")),
        _field(
            "cash_reconciliation",
            "现金核对状态",
            _account_cash_status(account.get("cash_reconciliation_status")),
        ),
        _field(
            "current_market_value",
            "账户摘要中的持仓估值",
            _value(account.get("current_market_value"), "单位未提供"),
        ),
        _field("valuation_time", "持仓估值时点", "账户摘要未提供；不标为实时行情"),
        _field("total_value", "账面总值", _value(account.get("total_value"), "单位未提供")),
        _field("automatic_execution", "自动执行", "此计划任务不启动自动交易"),
    ]
    return {
        "kind": "detail",
        "title": "模拟账户资金与估值摘要",
        "status": "已读取账户记录",
        "business_summary": "现金与持仓估值来自现有账户摘要；金额单位或估值时点缺失时明确保持未知。",
        "fields": fields,
        "next_steps": [
            "查看该账户计划和来源限制；需要逐项操作时仍按当前来源、资金和费用重新核对。",
            "按需读取持仓明细或风险来源，不自动发起额外行情查询。",
        ],
        "read_only": True,
        "must_not_execute": True,
        "debug_hidden_fields": ["account_id", "owner_user_id"],
    }


def _project_list(envelope: Mapping[str, object], account_id: int) -> RebalancePlanTaskResult:
    """Build a bounded list with hidden revision pins for row navigation."""

    raw_plans = envelope.get("plans")
    if not isinstance(raw_plans, list) or len(raw_plans) > 20:
        return _blocked_result()
    rows: list[_GridRow] = []
    for raw_plan in raw_plans:
        plan = _mapping(raw_plan)
        if (
            plan is None
            or not _plan_account_matches(plan, account_id)
            or not _trusted_plan_shape(plan)
        ):
            return _blocked_result()
        identity = _mapping(plan.get("identity"))
        if identity is None:
            return _blocked_result()
        plan_id = _string(identity.get("plan_id"))
        version = _positive_int(identity.get("version"))
        revision_hash = _string(identity.get("revision_hash"))
        if plan_id is None or version is None or revision_hash is None:
            return _blocked_result()
        progress = _verified_progress(envelope.get("progress"), identity, plan)
        orders = _sequence(plan.get("orders"))
        rows.append(
            {
                "account_id": account_id,
                "plan_id": plan_id,
                "plan_version": version,
                "revision_hash_id": revision_hash,
                "version_label": f"第 {version} 版",
                "recorded_label": _time_label(identity.get("recorded_at")),
                "status_label": _status_label(plan.get("status")),
                "orders_label": f"{len(orders)} 项",
                "progress_label": _list_progress_label(progress),
                "validity_label": _time_label(identity.get("valid_until")),
            }
        )
    return {
        "kind": "datagrid",
        "title": "模拟调仓计划",
        "status": "已读取本人或已授权查看的计划" if rows else "当前没有已保存的计划",
        "business_summary": (
            f"已读取 {len(rows)} 个计划版本。计划仅用于模拟核对，不会自动提交订单。"
            if rows
            else "当前账户还没有已保存的调仓计划；可以按当前账户事实生成新计划。"
        ),
        "columns": [
            {"key": "version_label", "label": "计划版本"},
            {"key": "recorded_label", "label": "生成时间"},
            {"key": "status_label", "label": "状态"},
            {"key": "orders_label", "label": "订单目标"},
            {"key": "progress_label", "label": "成交与余量"},
            {"key": "validity_label", "label": "有效期限"},
        ],
        "rows": rows,
        "total": len(rows),
        "empty_message": "当前账户还没有已保存的调仓计划。",
        "empty_guidance": [
            "选择“生成调仓计划”后，系统会重新读取账户、来源、风险、费用和结算规则。"
        ],
        "next_steps": [
            "逐个查看版本，核对原目标、依据和实际成交进度。",
            "计划版本到期或成交事实变化时，需要重新复核。",
        ],
        "read_only": True,
        "must_not_execute": True,
        "debug_hidden_fields": ["plan_id", "plan_version", "revision_hash_id"],
    }


def _project_revision(
    action_key: str,
    plan: Mapping[str, object],
    identity: Mapping[str, object],
    progress: Mapping[str, object] | None,
    envelope: Mapping[str, object],
) -> RebalancePlanTaskResult:
    """Render one exact revision, original evidence times, and ledger progress."""

    version = _positive_int(identity.get("version"))
    if version is None:
        return _blocked_result()
    fields: list[_Field] = [
        _field("plan_version", "计划版本", f"第 {version} 版"),
        _field("plan_status", "保存状态", _status_label(plan.get("status"))),
        _field("recorded_at", "计划生成时间", _time_label(identity.get("recorded_at"))),
        _field("valid_until", "计划有效期限", _time_label(identity.get("valid_until"))),
        _field("execution_permission", "执行权限", "未启用；计划不会自动提交或成交"),
    ]
    fields.extend(_source_fields(plan))
    fields.extend(_position_fields(plan))
    fields.extend(_policy_fields(plan))
    fields.extend(_order_fields(plan))
    next_steps: list[str] = ["计划保存的是原批准目标；当前价格、成交量和预留以重新读取的结果为准。"]
    if progress is not None:
        fields.extend(
            _progress_fields(
                progress,
                can_preview_order=_write_capability(envelope, "can_preview_order"),
            )
        )
        next_steps.extend(_capability_guidance(progress, envelope))
    else:
        fields.append(_field("progress", "实际成交进度", "暂不可核实；请重新读取对账。"))
        next_steps.append("在成交与预留状态可核实前，不要沿用计划余量继续操作。")
    if action_key == "rebalance-plan.reconcile":
        title = "计划成交与余量对账"
        summary = "以下进度来自当前可核实的成交与有效预留；未知数据保持未知。"
    elif action_key == "rebalance-plan.review":
        title = "已提交人工复核申请"
        summary = "申请已提交至既有独立审批流程；申请本身不会启用任何执行权限。"
    elif action_key == "rebalance-plan.successor":
        title = "后继调仓计划"
        summary = "后继版本按当前来源和实际成交重新生成；旧版本不会继承执行资格。"
    elif action_key == "rebalance-plan.create":
        title = "已生成模拟调仓计划"
        summary = "计划已保存供逐项核对；它不会提交或自动执行订单。"
    else:
        title = "调仓计划详情"
        summary = "查看保存时的目标、来源与规则，再与当前成交和预留对账。"
    outcome = _risk_outcome(plan)
    result: RebalancePlanTaskResult = {
        "kind": "detail",
        "title": title,
        "status": _status_label(plan.get("status")),
        "business_summary": summary,
        "fields": fields,
        "next_steps": next_steps,
        "read_only": True,
        "must_not_execute": True,
        "outcome": outcome,
        "debug_hidden_fields": [
            "plan_id",
            "revision_hash",
            "transition_plan_hash",
            "owner_user_id",
        ],
    }
    if progress is None:
        result["blocking_reason"] = "当前成交、预留或账户事实尚不能与此计划版本完整对应。"
    return result


def _source_fields(plan: Mapping[str, object]) -> list[_Field]:
    """Show supplier and policy clocks separately without manufacturing freshness."""

    basis = _mapping(plan.get("basis"))
    sources = _sequence(basis.get("source_bindings") if basis else None)
    fields: list[_Field] = []
    if not sources:
        return [_field("sources", "来源", "未提供可展示的来源时点；当前计划应按限制状态核对。")]
    for index, raw_source in enumerate(sources, start=1):
        source = _mapping(raw_source)
        if source is None:
            fields.append(_field(f"source_{index}", "来源", "来源信息未知。"))
            continue
        kind = _string(source.get("kind"))
        kind_label = _SOURCE_LABELS.get(kind or "", "风险与市场来源")
        observation = source.get("observed_at") or source.get("observed_on")
        supplier_expiry = source.get("source_valid_until")
        supplier_available = source.get("available_at")
        known = source.get("known_at")
        precision = source.get("observation_precision")
        precision_label = (
            "精确时点" if precision == "timestamp" else "仅日期" if precision == "date" else "未知"
        )
        restrictions = source.get("restrictions")
        restriction_label = (
            "来源带有用途限制，需按计划说明核对。"
            if isinstance(restrictions, list) and restrictions
            else "未提供限制信息；保持未知。" if restrictions is None else "来源限制已记录。"
        )
        fields.extend(
            [
                _field(f"source_{index}_name", f"来源 {index}", kind_label),
                _field(f"source_{index}_precision", "观测精度", precision_label),
                _field(f"source_{index}_observed", "原始观测", _time_label(observation)),
                _field(
                    f"source_{index}_available", "供应方可用时间", _time_label(supplier_available)
                ),
                _field(f"source_{index}_known", "系统首次已知", _time_label(known)),
                _field(
                    f"source_{index}_valid_until",
                    "供应方有效期",
                    _time_label(supplier_expiry),
                ),
                _field(f"source_{index}_restrictions", "来源用途限制", restriction_label),
                _field(
                    f"source_{index}_qualification",
                    "计划保存时来源资格",
                    "已进入此可信计划版本" if source.get("qualified") is True else "资格未知",
                ),
            ]
        )
        fields.extend(
            [
                _field(
                    f"source_{index}_cutoff",
                    "来源核对截止时点",
                    _time_label(source.get("decision_cutoff")),
                ),
                _field(
                    f"source_{index}_policy_deadline",
                    "该版本来源接纳期限",
                    _time_label(source.get("admission_until")),
                ),
            ]
        )
    return fields


def _order_fields(plan: Mapping[str, object]) -> list[_Field]:
    """Render approved and unapproved order quantities without exposing binding IDs."""

    raw_orders = _sequence(plan.get("orders"))
    if not raw_orders:
        return [_field("orders", "计划订单", "没有可展示的订单目标。")]
    fields: list[_Field] = []
    for index, raw_order in enumerate(raw_orders, start=1):
        order = _mapping(raw_order)
        if order is None:
            fields.append(_field(f"order_{index}", "计划订单", "订单内容未知。"))
            continue
        side = order.get("side")
        side_label = "买入" if side == "buy" else "卖出" if side == "sell" else "方向未知"
        asset = _string(order.get("asset_code")) or "证券未知"
        name = _string(order.get("asset_name"))
        display_asset = f"{name}（{asset}）" if name else asset
        unit = _string(order.get("quantity_unit")) or "数量单位未知"
        money_unit = _string(order.get("money_unit")) or "金额单位未知"
        prefix = f"第 {index} 项 {display_asset} {side_label}"
        fields.extend(
            [
                _field(
                    f"order_{index}_approved",
                    f"{prefix}批准数量",
                    _value(order.get("approved_quantity"), unit),
                ),
                _field(
                    f"order_{index}_requested",
                    "目标数量",
                    _value(order.get("requested_quantity"), unit),
                ),
                _field(
                    f"order_{index}_unapproved",
                    "未批准数量",
                    _value(order.get("unapproved_quantity"), unit),
                ),
                _field(
                    f"order_{index}_asset_type",
                    "资产分类",
                    _asset_type_label(order.get("asset_type")),
                ),
                _field(
                    f"order_{index}_price",
                    "计划参考价（仅供核对）",
                    _value(order.get("reference_price"), money_unit),
                ),
                _field(
                    f"order_{index}_fee",
                    "计划费用估算（非成交费用）",
                    _value(order.get("estimated_fee"), money_unit),
                ),
                _field(
                    f"order_{index}_approved_limit",
                    "计划中的批准限价",
                    (
                        _value(order.get("approved_limit_price"), money_unit)
                        if order.get("approved_limit_price") is not None
                        else "未设置；仍须逐笔普通订单预览"
                    ),
                ),
                _field(
                    f"order_{index}_status",
                    "计划订单状态",
                    _status_label(order.get("status")),
                ),
                _field(
                    f"order_{index}_reasons",
                    "订单限制",
                    (
                        "有未解决限制，需按当前事实复核。"
                        if _sequence(order.get("reason_codes"))
                        else "未记录未解决限制；仍须按当前事实复核。"
                    ),
                ),
            ]
        )
    return fields


def _policy_fields(plan: Mapping[str, object]) -> list[_Field]:
    """Expose the saved risk and fee basis without treating it as live permission."""

    basis = _mapping(plan.get("basis"))
    if basis is None:
        return [_field("policy_basis", "适用规则", "未提供；计划不能替代当前规则核对。")]
    snapshot = _mapping(basis.get("portfolio_snapshot"))
    policy = _mapping(basis.get("planning_policy"))
    version = _string(policy.get("version")) if policy else None
    effective_at = _string(policy.get("effective_at")) if policy else None
    planning_status = _policy_status_label(policy.get("status") if policy else None)
    money_unit = _string(basis.get("money_unit"))
    risk_outcome = _risk_outcome(plan)
    fields = [
        _field(
            "saved_snapshot_at",
            "计划采用的账户事实时点",
            _time_label(snapshot.get("as_of") if snapshot else None),
        ),
        _field("saved_money_unit", "计划金额单位", money_unit or "未知；不补默认币种"),
        _field("saved_planning_policy_status", "目标策略状态", planning_status),
        _field("saved_policy_version", "计划采用的规则版本", version or "未提供；保持未知"),
        _field("saved_policy_effective", "规则生效时点", _time_label(effective_at)),
        _field("saved_risk_status", "计划风险核对", risk_outcome),
        _field("saved_business_date", "计划业务日期", _time_label(basis.get("business_date"))),
        _field(
            "saved_execution_session", "计划执行交易日", _time_label(basis.get("execution_session"))
        ),
        _field("simulation_scope", "计划范围", "仅模拟；不授予订单执行权限"),
    ]
    for key, label in (
        ("fee_policy", "费用规则"),
        ("quantity_rule", "数量规则"),
        ("settlement_rule", "结算规则"),
        ("execution_calendar", "交易日历"),
    ):
        fields.append(_policy_binding_field(key, label, basis.get(key)))
    return fields


def _policy_binding_field(key: str, label: str, value: object) -> _Field:
    """Summarize a saved rule binding without exposing references or hashes."""

    binding = _mapping(value)
    if binding is None:
        return _field(f"saved_{key}", label, "未提供；保持未知")
    status_label = _policy_status_label(binding.get("status"))
    version = _string(binding.get("version"))
    effective = _time_label(binding.get("effective_at"))
    known = _time_label(binding.get("known_at"))
    validity = _time_label(binding.get("valid_until"))
    version_text = f"；版本 {version}" if version else "；版本未知"
    return _field(
        f"saved_{key}",
        label,
        f"{status_label}{version_text}；生效 {effective}；系统已知 {known}；有效至 {validity}",
    )


def _position_fields(plan: Mapping[str, object]) -> list[_Field]:
    """Show saved positions and targets as quantities, not as current account facts."""

    fields: list[_Field] = []
    basis = _mapping(plan.get("basis"))
    current_positions = _sequence(basis.get("current_positions") if basis else None)
    target_positions = _sequence(basis.get("target_positions") if basis else None)
    for heading, key, rows in (
        ("计划保存时持仓", "saved_position", current_positions),
        ("计划目标持仓", "target_position", target_positions),
    ):
        if not rows:
            fields.append(_field(f"{key}_empty", heading, "没有已保存的行；不补造数量。"))
            continue
        for index, raw_position in enumerate(rows, start=1):
            position = _mapping(raw_position)
            if position is None:
                fields.append(_field(f"{key}_{index}", heading, "数量未知。"))
                continue
            code = _string(position.get("asset_code")) or "证券未知"
            name = _string(position.get("asset_name"))
            label = f"{name}（{code}）" if name else code
            unit = _string(position.get("quantity_unit")) or "数量单位未知"
            quantity = (
                position.get("target_quantity")
                if key == "target_position"
                else position.get("quantity")
            )
            fields.append(_field(f"{key}_{index}", f"{heading} {label}", _value(quantity, unit)))
    return fields


def _verified_progress(
    raw_progress: object,
    identity: Mapping[str, object],
    plan: Mapping[str, object],
) -> Mapping[str, object] | None:
    """Accept progress only when the server binds it to the exact saved revision."""

    progress = _mapping(raw_progress)
    if progress is None:
        return None
    progress_identity = _mapping(progress.get("plan_identity"))
    if progress_identity is None:
        return None
    for key in ("plan_id", "family_id", "root_plan_id", "version", "revision_hash"):
        if progress_identity.get(key) != identity.get(key):
            return None
    expected_valid_until = identity.get("valid_until")
    if progress_identity.get("valid_until") != expected_valid_until:
        return None
    expected_orders = _sequence(plan.get("orders"))
    progress_orders = _sequence(progress.get("orders"))
    if len(expected_orders) != len(progress_orders):
        return None
    expected_by_ordinal: dict[int, Mapping[str, object]] = {}
    for raw_order in expected_orders:
        order = _mapping(raw_order)
        ordinal = _nonnegative_int(order.get("ordinal")) if order else None
        if order is None or ordinal is None or ordinal in expected_by_ordinal:
            return None
        expected_by_ordinal[ordinal] = order
    seen_ordinals: set[int] = set()
    for raw_order in progress_orders:
        item = _mapping(raw_order)
        binding = _mapping(item.get("order")) if item else None
        if item is not None and binding is None:
            binding = item
        live_progress = _mapping(item.get("progress")) if item else None
        attempts = item.get("attempts") if item else None
        ordinal = _nonnegative_int(binding.get("ordinal")) if binding else None
        expected = expected_by_ordinal.get(ordinal) if ordinal is not None else None
        if (
            item is None
            or binding is None
            or live_progress is None
            or not isinstance(attempts, list)
            or expected is None
            or ordinal is None
            or ordinal in seen_ordinals
        ):
            return None
        seen_ordinals.add(ordinal)
        for progress_key, plan_key in (
            ("plan_order_binding_id", "plan_order_binding_id"),
            ("order_content_hash", "order_content_hash"),
            ("asset_code", "asset_code"),
            ("security_id", "security_id"),
            ("asset_type", "asset_type"),
            ("classification_content_hash", "classification_content_hash"),
            ("side", "side"),
            ("approved_quantity", "approved_quantity"),
        ):
            if binding.get(progress_key) != expected.get(plan_key):
                return None
    if seen_ordinals != set(expected_by_ordinal):
        return None
    return progress


def _progress_fields(progress: Mapping[str, object], *, can_preview_order: bool) -> list[_Field]:
    """Project real account reconciliation and per-order ledger transitions."""

    account = _mapping(progress.get("account_reconciliation"))
    fields: list[_Field] = []
    if account is None:
        fields.append(_field("account_reconciliation", "当前账户核对", "未知；请重新读取。"))
    else:
        unit = _string(account.get("money_unit")) or "金额单位未知"
        fields.extend(
            [
                _field("account_read_at", "账户事实读取时点", _time_label(account.get("read_at"))),
                _field(
                    "cash_available", "当前可用资金", _value(account.get("cash_available"), unit)
                ),
                _field(
                    "active_buy_cash_reserved",
                    "买入仍占用资金",
                    _value(account.get("active_buy_cash_reserved"), unit),
                ),
                _field(
                    "active_sell_quantity_reserved",
                    "卖出仍占用数量",
                    _value(account.get("active_sell_quantity_reserved"), "数量单位未提供"),
                ),
                _field(
                    "actual_fees_paid", "已确认费用", _value(account.get("actual_fees_paid"), unit)
                ),
                _field(
                    "fees_complete", "费用记录完整性", _boolean_label(account.get("fees_complete"))
                ),
            ]
        )
        for index, raw_position in enumerate(_sequence(account.get("positions")), start=1):
            position = _mapping(raw_position)
            if position is None:
                fields.append(_field(f"position_{index}", "当前持仓", "未知。"))
                continue
            code = _string(position.get("asset_code")) or "证券未知"
            quantity_unit = _string(position.get("quantity_unit")) or "数量单位未知"
            fields.append(
                _field(
                    f"position_{index}",
                    f"当前持仓 {code}",
                    _value(position.get("quantity"), quantity_unit),
                )
            )
    for index, raw_order in enumerate(_sequence(progress.get("orders")), start=1):
        row = _mapping(raw_order)
        binding = _mapping(row.get("order")) if row else None
        ledger = _mapping(row.get("progress")) if row else None
        if row is not None and binding is None:
            binding = row
        if row is None or binding is None or ledger is None:
            fields.append(_field(f"progress_{index}", "订单进度", "未知。"))
            continue
        code = _string(binding.get("asset_code")) or "证券未知"
        unit = _string(binding.get("quantity_unit")) or "数量单位未知"
        fields.extend(
            [
                _field(
                    f"progress_{index}_asset",
                    f"第 {index} 项 {code}",
                    _side_label(binding.get("side")),
                ),
                _field(
                    f"progress_{index}_filled",
                    "已核实成交",
                    _value(ledger.get("filled_quantity"), unit),
                ),
                _field(
                    f"progress_{index}_active",
                    "仍有效预留",
                    _value(ledger.get("in_flight_quantity"), unit),
                ),
                _field(
                    f"progress_{index}_released",
                    "已释放未成交量",
                    _value(ledger.get("released_quantity"), unit),
                ),
                _field(
                    f"progress_{index}_remaining",
                    "尚未预留的计划余量",
                    _value(ledger.get("unreserved_remaining_quantity"), unit),
                ),
            ]
        )
        fields.append(
            _field(
                f"progress_{index}_can_reserve",
                "是否可进入单笔预览",
                _boolean_label(can_preview_order and row.get("can_preview") is True),
            )
        )
    return fields


def _capability_guidance(
    progress: Mapping[str, object], envelope: Mapping[str, object]
) -> list[str]:
    """Describe only server-declared next actions; never infer from plan status."""

    steps: list[str] = ["成交与预留须逐项核对；本任务不会批量提交或自动执行。"]
    capabilities = _mapping(envelope.get("capabilities")) or {}
    writable = capabilities.get("read_only") is False
    if writable and capabilities.get("can_request_review") is True:
        steps.append("服务器允许提交该精确版本的人工复核申请；申请不会开启执行权限。")
    if writable and capabilities.get("can_create_successor") is True:
        steps.append("服务器允许按当前成交事实和来源重新生成后继版本。")
    orders = _sequence(progress.get("orders"))
    if (
        writable
        and capabilities.get("can_preview_order") is True
        and any(_order_can(order, "can_preview") for order in orders)
    ):
        steps.append("至少一项可继续单笔订单预览；确认前仍会重新核对资金、费用、来源和风险。")
    if writable and any(_order_can(order, "can_cancel") for order in orders):
        steps.append("存在仍有效的预留，可通过原订单入口单独申请撤销。")
    if any(_order_can(order, "requires_successor") for order in orders):
        steps.append("成交或撤销已改变原目标；需按当前事实生成新的后继版本并重新复核。")
    steps.append("成交只能走既有模拟订单撮合和成交核验流程；未成交卖出不计入可用资金。")
    return steps


def _list_progress_label(progress: Mapping[str, object] | None) -> str:
    """Summarize only verified progress, preserving an incomplete chain as unknown."""

    if progress is None:
        return "需重新读取"
    orders = _sequence(progress.get("orders"))
    if not orders:
        return "没有订单进度"
    return "打开版本查看实际进度"


def _plan_account_matches(plan: Mapping[str, object], account_id: int) -> bool:
    """Require response and immutable revision account identities to agree."""

    identity = _mapping(plan.get("identity"))
    return identity is not None and _positive_int(identity.get("account_id")) == account_id


def _trusted_plan_shape(plan: Mapping[str, object]) -> bool:
    """Fail closed unless the immutable payload identifies a non-executing trusted revision."""

    identity = _mapping(plan.get("identity"))
    basis = _mapping(plan.get("basis"))
    risk = _mapping(basis.get("risk")) if basis is not None else None
    account = _mapping(basis.get("account")) if basis is not None else None
    source_bindings = _sequence(basis.get("source_bindings")) if basis is not None else ()
    orders = _sequence(plan.get("orders"))
    valid_sources = bool(source_bindings) and all(
        _trusted_source_binding(item) for item in source_bindings
    )
    valid_orders = all(_trusted_order_binding(item, ordinal) for ordinal, item in enumerate(orders))
    return (
        plan.get("automatic_submission") is False
        and identity is not None
        and _positive_int(identity.get("version")) is not None
        and _is_sha256(identity.get("revision_hash"))
        and _string(identity.get("recorded_at")) is not None
        and _string(identity.get("valid_until")) is not None
        and basis is not None
        and account is not None
        and account.get("account_id") == identity.get("account_id")
        and account.get("owner_user_id") == identity.get("owner_user_id")
        and _string(basis.get("money_unit")) is not None
        and valid_sources
        and isinstance(basis.get("current_positions"), list)
        and isinstance(basis.get("target_positions"), list)
        and isinstance(plan.get("orders"), list)
        and valid_orders
        and risk is not None
        and risk.get("outcome") == "allowed"
        and risk.get("must_not_use_for_decision") is False
    )


def _trusted_source_binding(value: object) -> bool:
    """Require the source identity and both immutable content pins before display."""

    source = _mapping(value)
    return (
        source is not None
        and source.get("qualified") is True
        and all(
            _string(source.get(key)) is not None
            for key in ("kind", "source_id", "source_record_id")
        )
        and _is_sha256(source.get("manifest_sha256"))
        and _is_sha256(source.get("body_sha256"))
    )


def _trusted_order_binding(value: object, ordinal: int) -> bool:
    """Require the complete immutable order binding before showing its target."""

    order = _mapping(value)
    return (
        order is not None
        and order.get("ordinal") == ordinal
        and type(order.get("requested_quantity")) is int
        and type(order.get("approved_quantity")) is int
        and type(order.get("unapproved_quantity")) is int
        and order.get("side") in {"buy", "sell"}
        and all(
            _string(order.get(key)) is not None
            for key in (
                "asset_code",
                "security_id",
                "asset_type",
                "quantity_unit",
                "money_unit",
                "status",
            )
        )
        and _is_sha256(order.get("order_content_hash"))
        and _is_sha256(order.get("plan_order_binding_id"))
        and _is_sha256(order.get("classification_content_hash"))
    )


def _matches_requested_revision(
    identity: Mapping[str, object], requested: Mapping[str, object]
) -> bool:
    """Require one exact revision to match all user-selected read pins."""

    version = _positive_int(requested.get("plan_version"))
    plan_id = _string(requested.get("plan_id"))
    revision_hash = _string(requested.get("revision_hash"))
    return (
        version is not None
        and plan_id is not None
        and revision_hash is not None
        and identity.get("version") == version
        and identity.get("plan_id") == plan_id
        and identity.get("revision_hash") == revision_hash
    )


def _blocked_result() -> RebalancePlanTaskResult:
    """Return no stale financial content when a response or pin is malformed."""

    return {
        "kind": "detail",
        "title": "调仓计划暂不可展示",
        "status": "需要重新读取",
        "business_summary": "计划版本、账户范围或实际进度无法核实；没有沿用旧结果。",
        "blocking_reason": "请从本人或已授权查看的账户重新打开计划列表。",
        "fields": [_field("permission", "账户与版本", "当前数据无法与所选账户和计划版本对应。")],
        "next_steps": ["重新读取本人或已授权查看的账户计划。"],
        "read_only": True,
        "must_not_execute": True,
        "outcome": "unknown",
        "debug_hidden_fields": ["plan_id", "revision_hash", "owner_user_id"],
    }


def _field(key: str, label: str, value: str) -> _Field:
    """Build one bounded, user-facing result field."""

    return {"key": key, "label": label, "value": value}


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow JSON objects before reading any business field."""

    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object]:
    """Return JSON arrays and nothing else."""

    return cast(Sequence[object], value) if isinstance(value, list) else ()


def _string(value: object) -> str | None:
    """Retain non-empty string scalars while rejecting arbitrary objects."""

    return value.strip()[:160] if isinstance(value, str) and value.strip() else None


def _is_sha256(value: object) -> bool:
    """Accept the exact lower-case digest shape used by the plan contracts."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_int(value: object) -> int | None:
    """Accept positive integer identifiers without coercing string or boolean input."""

    return value if type(value) is int and value > 0 else None


def _nonnegative_int(value: object) -> int | None:
    """Accept zero-based ordinals without coercing strings or booleans."""

    return value if type(value) is int and value >= 0 else None


def _time_label(value: object) -> str:
    """Preserve an explicit ISO source or policy time; keep absent values unknown."""

    text = _string(value)
    return text if text is not None else "未提供；保持未知"


def _value(value: object, unit: str) -> str:
    """Format an exact numeric value with its declared unit, never zero-fill None."""

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


def _policy_status_label(value: object) -> str:
    """Describe applicability without inventing a target-policy identity."""

    if value == "qualified":
        return "已记录为适用"
    if value == "not_applicable":
        return "本计划未使用目标策略；保留原因为据"
    return "状态未知；不补默认策略"


def _asset_type_label(value: object) -> str:
    """Translate common classification tokens and keep all other types explicit."""

    labels = {"equity": "股票", "etf": "交易型基金", "fund": "基金"}
    token = _string(value)
    return labels.get(token or "", "分类未知")


def _side_label(value: object) -> str:
    """Translate supported order direction tokens."""

    return "买入" if value == "buy" else "卖出" if value == "sell" else "方向未知"


def _boolean_label(value: object) -> str:
    """Render a server boolean or preserve the result as unknown."""

    return "是" if value is True else "否" if value is False else "未知"


def _account_cash_status(value: object) -> str:
    """Translate only known ledger reconciliation states."""

    if value == "balanced" or value == "reconciled" or value == "known":
        return "已核对"
    if value == "unknown" or value == "incomplete" or value is None:
        return "未知或未完整核对"
    if value == "mismatch" or value == "conflict" or value == "blocked":
        return "存在未解决差异"
    return "状态未知"


def _risk_outcome(plan: Mapping[str, object]) -> str:
    """Translate a saved risk verdict without turning it into action permission."""

    basis = _mapping(plan.get("basis"))
    risk = _mapping(basis.get("risk")) if basis else None
    value = risk.get("outcome") if risk else None
    if value == "allowed":
        return "风险检查通过；订单仍须逐项按当前事实重新核对"
    if value == "blocked":
        return "风险检查受阻；当前版本不可继续处理"
    if value == "partial":
        return "风险结果不完整；仅可参考明确可用部分"
    return "风险状态未知；不按通过处理"


def _order_can(order_value: object, capability_name: str) -> bool:
    """Read one explicit per-order server capability without status inference."""

    order = _mapping(order_value)
    return order is not None and order.get(capability_name) is True


def _write_capability(envelope: Mapping[str, object], key: str) -> bool:
    """Require server write scope and an exact capability before showing an action."""

    capabilities = _mapping(envelope.get("capabilities"))
    return (
        capabilities is not None
        and capabilities.get("read_only") is False
        and capabilities.get(key) is True
    )


__all__ = ["RebalancePlanTaskResult", "project_rebalance_plan_result"]
