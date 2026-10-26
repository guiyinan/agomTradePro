"""Project one owned-account inspection response into a safe TUI preview."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime

from apps.terminal.application.tui_account_inspection_primary_fields import (
    build_account_inspection_primary_fields,
)
from apps.terminal.application.tui_manual_target_policy_projection import (
    _project_strategy_policy_presentation,
    _project_strategy_risk_fields,
)

_ACCOUNT_INSPECTION_TITLE = "账户调仓预览"
_LOCAL_SIMULATED_REFERENCE_PURPOSE = "normal_simulated_current_reference"
_POSITIVE_INT_PATTERN = re.compile(r"^[0-9]+$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SOURCE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,49}$")
_RULE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NUMBER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
_SAFE_TEXT_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,160}$")

_PLAN_STATUS_LABELS: dict[str, str] = {
    "no_explicit_asset_targets": "暂无单标的目标",
    "no_rebalance_required": "无需调整",
    "blocked": "预览受阻",
    "partial": "部分建议受限",
    "ready": "预览已生成",
    "conditional": "等待资金交收后确认",
}
_ITEM_STATUS_LABELS: dict[str, str] = {
    "amount_only": "金额参考",
    "blocked": "受限",
    "conditional": "附条件",
    "no_rebalance_required": "无需调整",
    "partial": "部分受限",
    "ready": "可核对",
}
_ACTION_LABELS: dict[str, str] = {
    "blocked": "受阻",
    "buy": "建议增加",
    "hold": "保持",
    "sell": "建议减少",
}
_REASON_LABELS: dict[str, str] = {
    "ACCOUNT_MAX_POSITION_LIMIT_UNKNOWN": "账户单标的持仓上限未提供，买入建议无法核对",
    "ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED": "超过账户设置的单标的持仓上限",
    "ACCOUNT_MAX_TOTAL_POSITION_LIMIT_UNKNOWN": "账户总持仓上限或估值资料不全，买入建议无法核对",
    "ACCOUNT_MAX_TOTAL_POSITION_LIMIT_EXCEEDED": "超过账户设置的总持仓上限",
    "ACCOUNT_STOP_LOSS_EVIDENCE_UNKNOWN": "账户止损核对所需行情或持仓成本资料不足",
    "ACCOUNT_STOP_LOSS_TRIGGERED": "账户止损限制已触发，需先核对",
    "ACCOUNT_NOT_SIMULATED": "此账户类型当前不支持调仓预览",
    "ASSET_TYPE_CLASSIFICATION_UNAVAILABLE": "标的模拟资产分类资料不可用",
    "ASSET_TYPE_UNKNOWN": "资产类型无法确认",
    "BUY_FUNDING_UNKNOWN": "可用资金资料不足",
    "CASH_BALANCE_UNKNOWN": "现金资料未知",
    "CASH_SHORTFALL": "可用资金不足",
    "CURRENT_IDENTITY_UNAVAILABLE": "标的身份资料不可用",
    "FEE_POLICY_UNAVAILABLE": "费用资料不可用",
    "IDENTITY_EXECUTION_RESTRICTED": "标的资料限制执行",
    "IDENTITY_RESTRICTED_FOR_DECISION": "标的资料不可用于决策",
    "PORTFOLIO_VALUE_UNKNOWN": "账户估值资料不完整",
    "POSITION_QUANTITY_INVALID": "持仓数量资料无效",
    "POSITION_SNAPSHOT_INVALID": "持仓记录不完整",
    "POSITION_COST_BASIS_UNKNOWN": "持仓成本未知",
    "POSITION_COST_BASIS_PARTIAL": "持仓成本资料不完整",
    "POSITION_VALUATION_UNKNOWN": "持仓估值未知",
    "POSITION_RULE_BUY_NOT_TRIGGERED": "策略规则未给出本次买入触发信号",
    "POSITION_RULE_SELL_NOT_TRIGGERED": "策略规则未给出本次卖出触发信号",
    "QUOTE_UNAVAILABLE": "参考行情不可用",
    "SELL_POSITION_MISSING": "卖出持仓记录缺失",
    "SELLABLE_QUANTITY_EXCEEDS_POSITION": "可卖数量与持仓记录不一致",
    "SELLABLE_QUANTITY_INVALID": "可卖数量资料无效",
    "SELLABLE_QUANTITY_PARTIAL": "可卖数量不足以覆盖建议差量",
    "SELLABLE_QUANTITY_UNKNOWN": "可卖数量未知",
    "TARGET_WEIGHT_INVALID": "目标配置资料无效",
    "SELL_DEPENDENCY_INCOMPLETE": "买入建议依赖的卖出尚未完整满足",
    "ACTIONABLE_NOTIONAL_INVALID": "估算金额资料无效",
    "BUY_DEPENDS_ON_SETTLED_SALES": "买入数量需等待卖出资金完成交收后重新核对",
    "BUY_QUANTITY_BELOW_RULE_MINIMUM": "买入差量低于数量规则的最小值",
    "BUY_QUANTITY_MAXIMUM_LIMITED": "买入数量受单笔上限限制",
    "EXECUTION_QUANTITY_RULE_UNAVAILABLE": "下单数量规则未能确认",
    "SELL_QUANTITY_BELOW_RULE_MINIMUM": "卖出差量低于数量规则的最小值",
    "SELL_QUANTITY_LIMITED_BY_RULE": "卖出数量受数量规则限制",
    "SELL_QUANTITY_NOT_ON_RULE_STEP": "卖出数量不符合规则步长",
    "STRATEGY_MAX_POSITION_LIMIT_UNKNOWN": "选定策略的单标的持仓上限未提供，买入建议无法核对",
    "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED": "超过选定策略的单标的持仓上限",
    "STRATEGY_MAX_TOTAL_POSITION_LIMIT_UNKNOWN": "选定策略总持仓上限或估值资料不全，买入建议无法核对",
    "STRATEGY_MAX_TOTAL_POSITION_LIMIT_EXCEEDED": "超过选定策略的总持仓上限",
    "STRATEGY_RULE_CONTEXT_UNKNOWN": "策略风险规则所需数据不完整",
    "STRATEGY_RULE_EVALUATION_UNAVAILABLE": "策略风险规则评估未完成",
    "STRATEGY_STOP_LOSS_EVIDENCE_UNKNOWN": "策略止损核对所需行情或持仓成本资料不足",
    "STRATEGY_STOP_LOSS_TRIGGERED": "选定策略的止损限制已触发，需先核对",
}
_FUNDING_STATUS_LABELS: dict[str, str] = {
    "known": "估算资金资料完整（仍需核对）",
    "shortfall": "估算显示资金缺口",
    "unknown": "资金情况未知",
    "conditional": "等待卖出资金完成交收后复核",
}


def project_account_inspection_result(
    payload: object,
    *,
    requested_account_id: object,
    http_status: int,
) -> dict[str, object]:
    """Project an inspection report without exposing raw errors or trade controls."""

    if type(requested_account_id) is not int or requested_account_id < 1:
        return _blocked("账户范围无法确认，请重新选择本人账户。", http_status=400)

    transport_message = _transport_message(http_status)
    if transport_message is not None:
        return _blocked(transport_message, http_status=http_status)

    data = _as_mapping(payload)
    if data is None or data.get("success") is not True:
        return _blocked("预览结果无法确认；请重新选择账户后重试。", http_status=http_status)
    count = data.get("count")
    reports = data.get("reports")
    if type(count) is not int or count != 1 or not isinstance(reports, list) or len(reports) != 1:
        return _blocked("预览结果格式无法确认；没有展示旧结果。", http_status=http_status)

    report = _as_mapping(reports[0])
    if report is None:
        return _blocked("预览记录格式无法确认；没有展示旧结果。", http_status=http_status)
    report_id = _positive_int(report.get("report_id"))
    account_id = report.get("account_id")
    inspection_date = _date_text(report.get("inspection_date"))
    if (
        report_id is None
        or type(account_id) is not int
        or account_id != requested_account_id
        or inspection_date is None
    ):
        return _blocked("预览记录与所选账户不匹配；没有展示旧结果。", http_status=http_status)

    plan = _as_mapping(report.get("plan"))
    if (
        plan is None
        or plan.get("plan_kind") != "rebalance_preview"
        or plan.get("read_only") is not True
        or plan.get("execution_submitted") is not False
    ):
        return _blocked("本次没有可确认的只读预览；没有展示旧结果。", http_status=http_status)

    strategy_policy = _project_strategy_policy_presentation(
        plan.get("risk_context"), plan.get("asset_items")
    )
    if strategy_policy.blocking_message is not None:
        return _blocked(strategy_policy.blocking_message, http_status=http_status)

    plan_status = plan.get("status")
    status_label = _PLAN_STATUS_LABELS.get(plan_status) if type(plan_status) is str else None
    as_of = _timestamp_text(plan.get("as_of"), limit=80)
    if status_label is None or as_of is None:
        return _blocked("预览状态或来源时点无法确认；没有展示旧结果。", http_status=http_status)

    dependency = _as_mapping(plan.get("sell_before_buy"))
    settled_sale_dependency = (
        dependency.get("buy_requires_settled_sales") if dependency is not None else None
    )
    asset_rows = _project_items(
        plan.get("asset_items"),
        scope="asset",
        buy_requires_settled_sales=settled_sale_dependency,
    )
    allocation_rows = _project_items(plan.get("allocation_items"), scope="asset_class")
    fee_rows = _project_asset_review_rows(plan.get("asset_items"))
    quantity_rule_rows = _project_quantity_rule_rows(plan.get("asset_items"))
    if (
        asset_rows is None
        or allocation_rows is None
        or fee_rows is None
        or quantity_rule_rows is None
    ):
        return _blocked("预览明细格式无法确认；没有展示旧结果。", http_status=http_status)

    asset_table, provenance_fields, has_restrictions = asset_rows
    allocation_table, _, allocation_restrictions = allocation_rows
    fee_table, fee_restrictions = fee_rows
    cash_fields = _project_cash_fields(plan)
    dependency_fields = _project_dependency_fields(dependency)
    risk_fields = _project_strategy_risk_fields(
        plan.get("risk_context"),
        presentation=strategy_policy,
        row_field=_row_field,
        money_text=_money_text,
        bounded_text=_safe_text,
        date_text=_date_text,
        timestamp_text=_timestamp_text,
    )
    risk_falsification_summary = next(
        (field["value"] for field in risk_fields if field["key"] == "risk_falsification"),
        "本次响应未提供",
    )
    has_restrictions = has_restrictions or allocation_restrictions or fee_restrictions
    plan_outcome = "blocked" if plan_status == "blocked" else "success"
    summary = (
        "已生成一份只读调仓预览，尚未提交交易。数量、费用、资金与规则资料按本次记录展示；"
        "未提供的汇总币种和风险证伪条件保持未知。"
    )
    if plan_status == "blocked":
        summary = "本次预览受阻，未提交交易；请先核对明细中的资料限制。"
    elif plan_status == "conditional":
        summary = "预览已生成；买入数量需在卖出资金完成交收后重新核对，尚未提交交易。"
    elif plan_status == "partial" or has_restrictions:
        summary = "已生成只读预览，部分明细存在资料限制；尚未提交交易。"

    sections: list[dict[str, object]] = [
        {
            "key": "asset_quantity_plan",
            "title": "单标的数量建议",
            "columns": [
                {"key": "asset", "label": "标的"},
                {"key": "direction", "label": "方向"},
                {"key": "current", "label": "当前数量"},
                {"key": "target", "label": "目标数量"},
                {"key": "suggested", "label": "理论差量"},
                {"key": "actionable", "label": "规则约束后建议数量"},
                {"key": "remaining", "label": "尚未覆盖差量"},
                {"key": "sellable", "label": "可卖数量"},
                {"key": "unit", "label": "数量单位"},
                {"key": "status", "label": "状态与限制"},
            ],
            "rows": asset_table,
            "body": [
                "目标数量、理论差量与规则约束后建议数量分开呈现；这些数量只供核对，不是订单。",
                "买入若依赖卖出资金，须等资金完成交收后再确认数量。",
            ],
        },
        {
            "key": "asset_source_times",
            "title": "单标的来源时间与依据",
            "fields": provenance_fields,
            "body": [
                "只显示来源提供的时间、分类资料和风险规则入场价依据；未提供的值保持未提供。",
                "当前参考报价作为拟议入场价依据时，不代表已有持仓成本；未知成本不会按零处理。",
            ],
        },
        {
            "key": "asset_cost_identity_review",
            "title": "单标的费用、来源与限制",
            "columns": [
                {"key": "asset", "label": "标的"},
                {"key": "fees", "label": "费用估算"},
                {"key": "source", "label": "行情来源状态"},
                {"key": "identity", "label": "用途与来源限制"},
                {"key": "reasons", "label": "状态与原因"},
            ],
            "rows": fee_table,
            "body": [
                "仅展示本次记录中的估算费用和限制标记；不展示内部身份编号或费用规则标识。",
                "仅在身份用途明确为普通模拟当前名录参考时展示建议数量；来源原始限制标记独立保留。",
                "本次用途限于本地模拟参考，不适用于历史、自动或实盘用途，也不授权执行交易。",
                "费用与身份资料缺失会明确标示；估算不代表实际扣费或交易。",
            ],
        },
        {
            "key": "cash_and_cost_estimates",
            "title": "金额与资金估算",
            "fields": cash_fields,
            "body": [
                "账户账面现金、活动委托预留和当前可用现金按账户资料读取时间展示；汇总币种本次未提供。",
                "卖出后的预计资金尚未释放，不代表当前可用现金；预计买入后余额也未实际变动。",
            ],
        },
        {
            "key": "selected_strategy_and_risk_limits",
            "title": "本次采用的策略与风险限制",
            "fields": risk_fields,
            "body": (
                list(strategy_policy.risk_body)
                if strategy_policy.risk_body is not None
                else [
                    "仅展示本次记录中的策略名称、版本和风险限制；不推导目标持仓或风险结论。",
                    "账户设置与选定策略限制按来源分开展示，百分比沿用来源的 0–100% 数值；下单数量规则单独呈现，缺失的规则版本、有效期和证伪条件保持未知。",
                ]
            ),
        },
        {
            "key": "sell_then_buy_dependency",
            "title": "卖出与买入的估算依赖",
            "fields": dependency_fields,
            "body": ["顺序和标的列表来自本次记录；这里只说明估算依赖，不表示交易已发生。"],
        },
        {
            "key": "quantity_rule_evidence",
            "title": "基础数量规则来源证据",
            "columns": [
                {"key": "asset", "label": "标的"},
                {"key": "identity", "label": "规则凭据"},
                {"key": "buy", "label": "买入最小值、步长与上限"},
                {"key": "sell", "label": "卖出最小值、步长、上限与零碎处理"},
                {"key": "source_window", "label": "基础规则时点与组合窗口"},
            ],
            "rows": quantity_rule_rows,
            "body": [
                "基础执行规则与来源组合的来源时点和有效窗口分别展示；不以基础规则窗口代替组合窗口。",
                "策略风险限制在上一区单独列示；数量限制不等同于策略风险规则。",
                "规则约束后的数量仍是预览建议，不代表已下单或能够立即成交。",
            ],
        },
        {
            "key": "allocation_amount_guidance",
            "title": "资产类别金额参考",
            "columns": [
                {"key": "asset", "label": "资产类别"},
                {"key": "direction", "label": "方向"},
                {"key": "amount", "label": "建议金额"},
                {"key": "status", "label": "状态与限制"},
            ],
            "rows": allocation_table,
            "body": [
                "资产类别只展示金额参考；仅在来源明确声明 CNY 时标为元，不换算或显示为份额/股数。"
            ],
        },
    ]
    fields: list[dict[str, str]] = [
        {"key": "report_id", "label": "生成记录编号", "value": str(report_id)},
        {"key": "inspection_date", "label": "生成日期", "value": inspection_date},
        {"key": "as_of", "label": "预览时点", "value": as_of},
        {"key": "plan_status", "label": "预览状态", "value": status_label},
        {"key": "submission", "label": "交易提交状态", "value": "未提交"},
        {
            "key": "currency",
            "label": "汇总现金与费用币种",
            "value": "本次未提供" if plan.get("currency_unit") is None else "币种待核对",
        },
        {
            "key": "risk_falsification",
            "label": "风险证伪结果",
            "value": risk_falsification_summary,
        },
    ]
    fields = build_account_inspection_primary_fields(fields, sections)
    blocking_reason = ""
    if plan_status == "blocked":
        blocking_reason = "预览中存在阻断项；请核对每行限制后再重新检查。"
    elif has_restrictions:
        blocking_reason = "部分明细受限；各限制原因已用简明提示展示。"

    return {
        "kind": "detail",
        "title": _ACCOUNT_INSPECTION_TITLE,
        "status": status_label,
        "outcome": plan_outcome,
        "business_summary": summary,
        "blocking_reason": blocking_reason,
        "fields": fields,
        "sections": sections,
        "empty_message": "本次没有可展示的预览明细。",
        "empty_guidance": ["重新选择本人账户并生成一份新的调仓预览。"],
    }


def _project_items(
    raw_items: object,
    *,
    scope: str,
    buy_requires_settled_sales: object = None,
) -> tuple[list[dict[str, object]], list[dict[str, str]], bool] | None:
    if not isinstance(raw_items, list):
        return None
    rows: list[dict[str, object]] = []
    provenance: list[dict[str, str]] = []
    has_restrictions = False
    for raw_item in raw_items:
        item = _as_mapping(raw_item)
        if item is None or item.get("scope") != scope:
            return None
        action = item.get("action")
        status = item.get("status")
        action_label = _ACTION_LABELS.get(action) if type(action) is str else None
        status_label = _ITEM_STATUS_LABELS.get(status) if type(status) is str else None
        reason_labels = _reason_labels(item.get("reason_codes"))
        if action_label is None or status_label is None or reason_labels is None:
            return None
        has_restrictions = (
            has_restrictions or bool(reason_labels) or status in {"blocked", "partial"}
        )
        restriction = "；".join(reason_labels) if reason_labels else "无已记录限制"
        name = _safe_text(item.get("asset_name"), limit=96)
        code = _safe_text(item.get("asset_code"), limit=48)
        display_name = name or code or "标的名称未提供"
        if scope == "asset":
            unit_label = _quantity_unit_label(item)
            identity = _as_mapping(item.get("identity"))
            purpose_confirmed = _has_local_simulated_reference_purpose(identity)
            if not purpose_confirmed:
                has_restrictions = True
            actionable_quantity = item.get("actionable_quantity")
            if not purpose_confirmed:
                actionable_quantity_text = "用途未确认"
                if action == "buy" and buy_requires_settled_sales is True:
                    actionable_quantity_text += "；并且待卖出资金完成交收后确认"
                target_quantity_text = "用途未确认"
                suggested_quantity_text = "用途未确认"
                remaining_quantity_text = "用途未确认"
                restriction = _join_status(restriction, "身份用途未确认，未展示目标与建议数量")
            elif action == "buy" and buy_requires_settled_sales is True:
                actionable_quantity_text = "待卖出资金完成交收后确认"
                target_quantity_text = _number_text(item.get("target_quantity"))
                suggested_quantity_text = _number_text(item.get("suggested_quantity"))
                remaining_quantity_text = _number_text(item.get("remaining_quantity"))
            else:
                actionable_quantity_text = _number_text(actionable_quantity)
                target_quantity_text = _number_text(item.get("target_quantity"))
                suggested_quantity_text = _number_text(item.get("suggested_quantity"))
                remaining_quantity_text = _number_text(item.get("remaining_quantity"))
            row_fields = [
                _row_field("asset_code", "证券代码", code or "未提供"),
                _row_field("asset", "标的", display_name),
                _row_field("direction", "方向", action_label),
                _row_field("current", "当前数量", _number_text(item.get("current_quantity"))),
                _row_field("target", "目标数量", target_quantity_text),
                _row_field("suggested", "理论差量", suggested_quantity_text),
                _row_field("actionable", "规则约束后建议数量", actionable_quantity_text),
                _row_field("remaining", "尚未覆盖差量", remaining_quantity_text),
                _row_field("sellable", "可卖数量", _number_text(item.get("sellable_quantity"))),
                _row_field("unit", "数量单位", unit_label),
                _row_field("status", "状态与限制", _join_status(status_label, restriction)),
            ]
            rows.append({"fields": row_fields})
            provenance_prefix = display_name
            price_observed_at = _timestamp_text(item.get("price_observed_at"), limit=80)
            price_as_of = _date_text(item.get("price_as_of"))
            freshness = _freshness_label(item.get("price_freshness"))
            fallback = _fallback_label(item.get("price_is_fallback"))
            provenance.extend(
                [
                    _row_field(
                        "observed_at",
                        f"{provenance_prefix}来源观测时间",
                        price_observed_at or "未提供",
                    ),
                    _row_field(
                        "price_as_of", f"{provenance_prefix}参考日期", price_as_of or "未提供"
                    ),
                    _row_field("freshness", f"{provenance_prefix}时效", freshness),
                    _row_field("fallback", f"{provenance_prefix}备用来源", fallback),
                    _row_field(
                        "classification",
                        f"{provenance_prefix}本地模拟分类",
                        _classification_evidence_text(item.get("classification_evidence")),
                    ),
                    _row_field(
                        "risk_basis",
                        f"{provenance_prefix}风险规则入场价依据",
                        _risk_entry_price_basis_text(item),
                    ),
                ]
            )
        else:
            rows.append(
                {
                    "fields": [
                        _row_field("asset", "资产类别", display_name),
                        _row_field("direction", "方向", action_label),
                        _row_field("amount", "建议金额", _allocation_amount_text(item)),
                        _row_field("status", "状态与限制", _join_status(status_label, restriction)),
                    ]
                }
            )
    return rows, provenance, has_restrictions


def _project_quantity_rule_rows(raw_items: object) -> list[dict[str, object]] | None:
    """Show bounded base quantity-rule evidence without implying bundle validity."""

    if not isinstance(raw_items, list):
        return None
    rows: list[dict[str, object]] = []
    for raw_item in raw_items:
        item = _as_mapping(raw_item)
        if item is None or item.get("scope") != "asset":
            return None
        name = _safe_text(item.get("asset_name"), limit=96)
        code = _safe_text(item.get("asset_code"), limit=48)
        display_name = name or code or "标的名称未提供"
        raw_rule = item.get("quantity_rule")
        rule = _as_mapping(raw_rule)
        if rule is None:
            rule_state = "未提供" if raw_rule is None else "格式未确认"
            identity_text = f"基础规则编号、版本及校验摘要：{rule_state}"
            buy_text = f"最小值、步长和上限：{rule_state}"
            sell_text = f"最小值、步长、上限及零碎处理：{rule_state}"
            source_text = f"基础规则时点：{rule_state}；组合规则有效窗口：未提供"
        else:
            identity_text = _quantity_rule_identity_text(rule)
            buy_text = _quantity_bounds_text(rule.get("buy"))
            odd_lot = _odd_lot_label(rule.get("sell_odd_lot_mode"))
            sell_text = f"{_quantity_bounds_text(rule.get('sell'))}；零碎处理：{odd_lot}"
            source_text = _quantity_rule_source_window(rule)
        rows.append(
            {
                "fields": [
                    _row_field("asset", "标的", display_name),
                    _row_field("identity", "规则凭据", identity_text),
                    _row_field("buy", "买入数量限制", buy_text),
                    _row_field("sell", "卖出数量限制与零碎处理", sell_text),
                    _row_field("source_window", "基础规则时点与组合窗口", source_text),
                ]
            }
        )
    return rows


def _quantity_rule_identity_text(rule: Mapping[str, object]) -> str:
    rule_id = _rule_token(rule.get("rule_id"))
    rule_version = _rule_token(rule.get("rule_version"))
    rule_hash = _rule_hash(rule.get("content_hash"))
    market = _rule_token(rule.get("market"))
    board = _rule_token(rule.get("board"))
    price_tick = _number_text(rule.get("price_tick"))
    bundle = _as_mapping(rule.get("bundle"))
    bundle_id = _rule_token(bundle.get("bundle_id")) if bundle is not None else "未提供"
    bundle_version = _rule_token(bundle.get("bundle_version")) if bundle is not None else "未提供"
    bundle_hash = _rule_hash(bundle.get("content_hash")) if bundle is not None else "未提供"
    return (
        f"基础规则编号 {rule_id}；版本 {rule_version}；校验摘要 {rule_hash}；"
        f"市场 {market}；板块 {board}；价格变动单位 {price_tick}；"
        f"来源组合编号 {bundle_id}；组合版本 {bundle_version}；组合摘要 {bundle_hash}"
    )


def _quantity_bounds_text(value: object) -> str:
    constraints = _as_mapping(value)
    if constraints is None:
        return "最小值、步长和上限：未提供" if value is None else "数量限制格式未确认"
    minimum = _number_text(constraints.get("minimum"))
    step = _number_text(constraints.get("step"))
    maximum = _number_text(constraints.get("maximum"))
    return f"最小值 {minimum}；步长 {step}；上限 {maximum}"


def _quantity_rule_source_window(rule: Mapping[str, object]) -> str:
    execution = _as_mapping(rule.get("execution_rule"))
    bundle = _as_mapping(rule.get("bundle"))
    observed = _rule_timestamp(execution.get("source_observed_at")) if execution else "未提供"
    available = _rule_timestamp(execution.get("source_available_at")) if execution else "未提供"
    effective = _rule_timestamp(execution.get("effective_from")) if execution else "未提供"
    expiry = _rule_timestamp(execution.get("valid_until")) if execution else "未提供"
    bundle_values = (
        (
            _rule_timestamp(bundle.get("latest_source_observed_at")),
            _rule_timestamp(bundle.get("source_available_at")),
            _rule_timestamp(bundle.get("effective_from")),
            _rule_timestamp(bundle.get("valid_until")),
        )
        if bundle is not None
        else ("未提供",) * 4
    )
    return (
        f"基础规则观测时间 {observed}；基础规则可用时间 {available}；"
        f"基础规则生效起 {effective}；基础规则有效至 {expiry}；"
        f"组合来源最新观测 {bundle_values[0]}；组合来源可用时间 {bundle_values[1]}；"
        f"组合生效起 {bundle_values[2]}；组合有效至 {bundle_values[3]}"
    )


def _classification_evidence_text(value: object) -> str:
    """Expose only bounded classification facts, never the nested evidence payload."""

    evidence = _as_mapping(value)
    if evidence is None:
        return "本次分类未提供" if value is None else "分类资料格式待确认"
    asset_type = _rule_token(evidence.get("simulated_asset_type"))
    purpose = (
        "普通模拟当前名录参考；仅限本地模拟用途"
        if evidence.get("purpose") == _LOCAL_SIMULATED_REFERENCE_PURPOSE
        else "用途未确认"
    )
    read_at = _rule_timestamp(evidence.get("read_at"))
    flags = (
        f"上游来源原始标记：不可用于通用决策 {_boolean_source_flag(evidence.get('must_not_use_for_decision'))}；"
        f"禁止执行 {_boolean_source_flag(evidence.get('must_not_execute'))}"
    )
    return f"类型 {asset_type}；用途 {purpose}；读取时间 {read_at}；{flags}"


def _risk_entry_price_basis_text(item: Mapping[str, object]) -> str:
    """Describe the requested risk-rule basis without reproducing evaluator internals."""

    basis = item.get("risk_rule_entry_price_basis")
    result = _as_mapping(item.get("risk_rule_result"))
    reason = item.get("risk_rule_reason_code")
    evaluated = "本次规则结果已返回，仍需人工核对" if result is not None else "风险规则评价未完成"
    if basis == "prospective_current_quote":
        return f"拟用当前参考报价作为入场价依据；不是持仓成本；{evaluated}"
    if basis == "position_cost_basis":
        if reason == "POSITION_COST_BASIS_UNKNOWN" or reason == "POSITION_COST_BASIS_PARTIAL":
            label = (
                "持仓成本未知" if reason == "POSITION_COST_BASIS_UNKNOWN" else "持仓成本资料不完整"
            )
            return f"所需依据为持仓成本；{label}，不能按零处理；{evaluated}"
        return f"所需依据为已有持仓成本；{evaluated}"
    return "风险规则入场价依据未提供；评价未完成"


def _rule_timestamp(value: object) -> str:
    if value is None:
        return "未提供"
    return _timestamp_text(value, limit=80) or "格式未确认"


def _rule_token(value: object) -> str:
    token = _safe_text(value, limit=128)
    if token is None:
        return "未提供" if value is None else "格式未确认"
    lowered = token.casefold()
    if (
        _RULE_TOKEN_PATTERN.fullmatch(token) is None
        or any(
            marker in lowered
            for marker in ("apikey", "api_key", "token", "secret", "password", "credential")
        )
        or lowered.startswith(("sk-", "pk-", "bearer-"))
    ):
        return "格式未确认"
    return token


def _rule_hash(value: object) -> str:
    if value is None:
        return "未提供"
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        return "格式未确认"
    return value


def _odd_lot_label(value: object) -> str:
    if type(value) is not str:
        return "未提供" if value is None else "口径待确认"
    labels = {
        "FORBID": "不允许零碎卖出",
        "SELLABLE_BALANCE_TO_ZERO": "可卖余额清仓例外",
        "SELL_ODD_REMAINDER_ONCE": "允许一次性卖出尾数",
    }
    return labels.get(value, "口径待确认")


def _project_asset_review_rows(
    raw_items: object,
) -> tuple[list[dict[str, object]], bool] | None:
    """Project fee, source, identity and reason status without internal identifiers."""

    if not isinstance(raw_items, list):
        return None
    rows: list[dict[str, object]] = []
    has_restrictions = False
    for raw_item in raw_items:
        item = _as_mapping(raw_item)
        if item is None or item.get("scope") != "asset":
            return None
        name = _safe_text(item.get("asset_name"), limit=96)
        code = _safe_text(item.get("asset_code"), limit=48)
        display_name = name or code or "标的名称未提供"
        reason_labels = _reason_labels(item.get("reason_codes"))
        if reason_labels is None:
            return None

        fee = _as_mapping(item.get("fee"))
        fee_text = _fee_summary(fee, currency_unit=item.get("currency_unit"))
        fee_label = (
            "费用估算（来源标记 CNY）"
            if item.get("currency_unit") == "CNY"
            else "费用估算（币种未提供）"
        )
        identity_text, identity_complete, identity_restricted = _identity_status(
            item.get("identity")
        )
        source_text = _source_status(item)
        raw_status = item.get("status")
        status = _ITEM_STATUS_LABELS.get(raw_status) if type(raw_status) is str else None
        if status is None:
            return None
        reason_text = "；".join([status, *reason_labels]) if reason_labels else status
        rows.append(
            {
                "fields": [
                    _row_field("asset", "标的", display_name),
                    _row_field("fees", fee_label, fee_text),
                    _row_field("source", "行情来源状态", source_text),
                    _row_field("identity", "用途与来源限制", identity_text),
                    _row_field("reasons", "状态与原因", reason_text),
                ]
            }
        )
        has_restrictions = (
            has_restrictions
            or not _fee_details_complete(fee)
            or not identity_complete
            or identity_restricted
            or _safe_source_name(item.get("price_source")) is None
            or bool(reason_labels)
            or item.get("status") in {"blocked", "partial"}
        )
    return rows, has_restrictions


def _fee_summary(fee: Mapping[str, object] | None, *, currency_unit: object) -> str:
    """Show only supplied fee components, never policy IDs or case metadata."""

    if fee is None:
        return "费用资料未提供"
    components = (
        ("commission", "佣金"),
        ("transfer_fee", "过户费"),
        ("stamp_duty", "印花税"),
        ("slippage", "滑点估算"),
        ("total", "费用合计"),
    )
    values = [f"{label} {_money_text(fee.get(key))}" for key, label in components if key in fee]
    summary = "；".join(values) if values else "费用明细未提供"
    suffix = "（来源标记 CNY）" if currency_unit == "CNY" else "（币种未提供）"
    return f"{summary}{suffix}"


def _fee_details_complete(fee: Mapping[str, object] | None) -> bool:
    """Recognize complete FeeV2 amount fields without inspecting policy metadata."""

    if fee is None:
        return False
    return all(
        _money_text(fee.get(key)) not in {"未提供", "格式未确认"}
        for key in ("commission", "transfer_fee", "stamp_duty", "slippage", "total")
    )


def _identity_status(value: object) -> tuple[str, bool, bool]:
    """Show the current purpose separately from the source's two raw flags."""

    identity = _as_mapping(value)
    if identity is None:
        return (
            "本次身份用途：用途未确认；上游来源原始标记：" "不可用于通用决策：未知；禁止执行：未知",
            False,
            False,
        )
    decision_flag = identity.get("must_not_use_for_decision")
    execution_flag = identity.get("must_not_execute")
    purpose_confirmed = _has_local_simulated_reference_purpose(identity)
    purpose_text = "普通模拟当前名录参考；仅限本地模拟用途" if purpose_confirmed else "用途未确认"
    flags_text = (
        "上游来源原始标记："
        f"不可用于通用决策：{_boolean_source_flag(decision_flag)}；"
        f"禁止执行：{_boolean_source_flag(execution_flag)}"
    )
    identity_complete = type(decision_flag) is bool and type(execution_flag) is bool
    restricted = decision_flag is True or execution_flag is True
    return (
        f"本次身份用途：{purpose_text}；{flags_text}",
        identity_complete and purpose_confirmed,
        restricted,
    )


def _has_local_simulated_reference_purpose(identity: Mapping[str, object] | None) -> bool:
    """Accept only the explicitly approved local simulated-reference purpose."""

    return (
        identity is not None
        and type(identity.get("purpose")) is str
        and identity.get("purpose") == _LOCAL_SIMULATED_REFERENCE_PURPOSE
    )


def _boolean_source_flag(value: object) -> str:
    if type(value) is not bool:
        return "未知"
    return "是" if value else "否"


def _source_status(item: Mapping[str, object]) -> str:
    """Show a safe source code alongside its supplied clock and freshness."""

    source = _safe_source_name(item.get("price_source"))
    observed_at = _timestamp_text(item.get("price_observed_at"), limit=80)
    price_as_of = _date_text(item.get("price_as_of"))
    freshness = _freshness_label(item.get("price_freshness"))
    fallback = _fallback_label(item.get("price_is_fallback"))
    source_text = f"行情来源：{source}" if source else "行情来源名称未提供或格式未确认"
    return (
        f"{source_text}；观测时间：{observed_at or '未提供'}；"
        f"参考日期：{price_as_of or '未提供'}；时效：{freshness}；备用来源：{fallback}"
    )


def _safe_source_name(value: object) -> str | None:
    """Allow bounded provider-code tokens, not URLs, query strings, or credentials."""

    text = _safe_text(value, limit=50)
    if text is None or _SOURCE_CODE_PATTERN.fullmatch(text) is None:
        return None
    lowered = text.casefold()
    if any(
        marker in lowered
        for marker in ("apikey", "api_key", "token", "secret", "password", "credential")
    ):
        return None
    if lowered.startswith(("sk-", "pk-", "bearer-")):
        return None
    return text


def _project_cash_fields(plan: Mapping[str, object]) -> list[dict[str, str]]:
    """Project cash and estimate amounts as returned, with explicit unknown currency."""

    specifications = (
        ("cash_before", "账户账面现金（币种未提供）"),
        ("reserved_cash", "所有活动委托预留现金（币种未提供）"),
        ("available_cash_before", "当前可用现金（扣除活动委托预留；币种未提供）"),
        (
            "projected_cash_after_sells",
            "卖出完成后预计资金（尚未释放；不代表当前可用现金；币种未提供）",
        ),
        ("estimated_sell_gross", "卖出金额估算（币种未提供）"),
        ("estimated_sell_fees", "卖出费用估算（币种未提供）"),
        ("estimated_sell_net", "卖出净额估算（币种未提供）"),
        ("estimated_buy_gross", "买入金额估算（币种未提供）"),
        ("estimated_buy_fees", "买入费用估算（币种未提供）"),
        ("estimated_buy_total", "买入合计估算（币种未提供）"),
        (
            "projected_cash_after_buys",
            "估算买入后余额（未发生交易；币种未提供）",
        ),
    )
    read_at = _timestamp_text(plan.get("financial_snapshot_read_at"), limit=80)
    fields = [
        _row_field("financial_snapshot_read_at", "账户资料读取时间", read_at or "未提供"),
        *[_row_field(key, label, _money_text(plan.get(key))) for key, label in specifications],
    ]
    raw_status = plan.get("funding_status")
    status_label = _FUNDING_STATUS_LABELS.get(raw_status) if type(raw_status) is str else None
    fields.append(
        _row_field(
            "funding_status",
            "资金估算状态",
            status_label or "状态待确认",
        )
    )
    return fields


def _project_dependency_fields(value: object) -> list[dict[str, str]]:
    """Render the owner-supplied sell-before-buy estimate with no execution claim."""

    dependency = _as_mapping(value)
    if dependency is None:
        return [
            _row_field("sequence", "估算顺序", "顺序资料待确认"),
            _row_field("buy_requires_settled_sales", "买入资金交收依赖", "本次未提供"),
        ]
    required = dependency.get("required")
    buy_requires_settled_sales = dependency.get("buy_requires_settled_sales")
    sells = _safe_code_list(dependency.get("sell_asset_codes"))
    buys = _safe_code_list(dependency.get("buy_asset_codes"))
    sequence = dependency.get("sequence")
    if required is False and sells == [] and buys == [] and sequence == "sell_then_buy":
        return [
            _row_field("sequence", "估算顺序", "本次未记录卖出后买入依赖"),
            _row_field(
                "buy_requires_settled_sales",
                "买入资金交收依赖",
                _settled_sales_label(buy_requires_settled_sales),
            ),
            _row_field("execution", "交易状态", "未发生交易"),
        ]
    if required is True and sells is not None and buys is not None and sequence == "sell_then_buy":
        return [
            _row_field("sequence", "估算顺序", "先卖出，再核对买入资金；未发生交易"),
            _row_field("sell_assets", "估算卖出标的", "、".join(sells) or "未提供"),
            _row_field("buy_assets", "估算买入标的", "、".join(buys) or "未提供"),
            _row_field(
                "buy_requires_settled_sales",
                "买入资金交收依赖",
                _settled_sales_label(buy_requires_settled_sales),
            ),
        ]
    return [
        _row_field("sequence", "估算顺序", "顺序资料待确认；未发生交易"),
        _row_field(
            "buy_requires_settled_sales",
            "买入资金交收依赖",
            _settled_sales_label(buy_requires_settled_sales),
        ),
    ]


def _settled_sales_label(value: object) -> str:
    if value is True:
        return "是；卖出资金完成交收前，买入数量暂不确认"
    if value is False:
        return "否；本次未标记等待卖出资金交收"
    return "本次未提供"


def _safe_code_list(value: object) -> list[str] | None:
    """Keep only safe, bounded asset-code strings from the dependency payload."""

    if not isinstance(value, list):
        return None
    codes: list[str] = []
    for item in value:
        code = _safe_text(item, limit=48)
        if code is None:
            return None
        codes.append(code)
    return codes


def _allocation_amount_text(item: Mapping[str, object]) -> str:
    """Display an allocation amount only with the exact source-declared CNY unit."""

    amount = _number_text(item.get("suggested_amount"))
    if item.get("currency_unit") == "CNY":
        if amount == "未提供":
            return "未提供（来源标记 CNY）"
        if amount == "格式未确认":
            return "格式未确认（来源标记 CNY）"
        return f"{amount} 元（来源标记 CNY）"
    return f"{amount}（币种待确认）" if amount not in {"未提供", "格式未确认"} else amount


def _money_text(value: object) -> str:
    """Preserve a decimal string, including a negative estimate, without conversion."""

    if value is None:
        return "未提供"
    if type(value) is not str or len(value) > 96 or _NUMBER_PATTERN.fullmatch(value) is None:
        return "格式未确认"
    return value


def _reason_labels(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    labels: list[str] = []
    for raw_reason in value:
        reason = _safe_text(raw_reason, limit=80)
        if reason is None:
            return None
        label = _REASON_LABELS.get(reason, "存在未细分的资料限制")
        if label not in labels:
            labels.append(label)
    if len(labels) > 4:
        return [*labels[:3], "还有其他资料限制"]
    return labels


def _row_field(key: str, label: str, value: str) -> dict[str, str]:
    return {"key": key, "label": label, "value": value}


def _join_status(status: str, restriction: str) -> str:
    return status if restriction == "无已记录限制" else f"{status}；{restriction}"


def _freshness_label(value: object) -> str:
    raw = _safe_text(value, limit=40)
    if raw is None:
        return "未提供"
    known = {
        "historical": "历史行情（非实时）",
        "realtime": "实时行情",
        "close_fallback": "收盘价备用行情",
    }
    return known.get(raw.lower(), "时效状态未确认")


def _quantity_unit_label(item: Mapping[str, object]) -> str:
    unit = item.get("quantity_unit")
    if unit == "shares":
        return "股（来源单位）"
    if unit == "units":
        asset_type = item.get("asset_type")
        if asset_type == "fund":
            return "基金份额/单位（口径待确认）"
        if asset_type == "bond":
            return "债券单位（口径待确认）"
        return "份/单位（口径待确认）"
    return "单位未确认"


def _fallback_label(value: object) -> str:
    if type(value) is not bool:
        return "未提供"
    return "是" if value else "否（来源未标记为备用）"


def _number_text(value: object) -> str:
    if value is None:
        return "未提供"
    if (
        type(value) is not str
        or len(value) > 96
        or value.startswith("-")
        or _NUMBER_PATTERN.fullmatch(value) is None
    ):
        return "格式未确认"
    return value


def _positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    if (
        type(value) is str
        and len(value) <= 18
        and _POSITIVE_INT_PATTERN.fullmatch(value) is not None
    ):
        try:
            normalized = int(value)
        except (ValueError, OverflowError):
            return None
        return normalized if normalized > 0 else None
    return None


def _date_text(value: object) -> str | None:
    if type(value) is not str or _DATE_PATTERN.fullmatch(value) is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _timestamp_text(value: object, *, limit: int) -> str | None:
    text = _safe_text(value, limit=limit)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


def _safe_text(value: object, *, limit: int) -> str | None:
    if type(value) is not str:
        return None
    text = value.strip()
    if len(text) > limit or _SAFE_TEXT_PATTERN.fullmatch(text) is None:
        return None
    return text


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if any(type(key) is not str for key in value):
        return None
    return value


def _transport_message(http_status: int) -> str | None:
    if 200 <= http_status < 300:
        return None
    if http_status == 401:
        return "登录状态已失效；本次未展示旧预览，请重新登录后选择本人账户。"
    if http_status == 403:
        return "当前无法读取所选账户的预览；本次未展示旧结果，请重新选择本人账户。"
    if http_status == 404:
        return "所选账户或预览记录当前不可用；本次未展示旧结果，请重新选择本人账户。"
    return "预览未完成，当前没有展示旧结果；请稍后重新生成。"


def _blocked(message: str, *, http_status: int) -> dict[str, object]:
    safe_message = message if "旧结果" in message else f"{message} 本次未展示旧结果。"
    status = (
        "需重新登录"
        if http_status == 401
        else ("账户不可用" if http_status in {403, 404} else "未完成")
    )
    return {
        "kind": "detail",
        "title": _ACCOUNT_INSPECTION_TITLE,
        "status": status,
        "outcome": "blocked",
        "business_summary": safe_message,
        "blocking_reason": safe_message,
        "fields": [],
        "sections": [{"key": "blocked", "title": "处理提示", "body": [safe_message]}],
        "empty_message": "本次没有可展示的预览明细。",
        "empty_guidance": ["重新选择本人账户并生成一份新的调仓预览。"],
    }


__all__ = ["project_account_inspection_result"]
