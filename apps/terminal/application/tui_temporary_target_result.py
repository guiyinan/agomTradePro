"""Add safe source and residual-cash context to temporary-target TUI results."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext

from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.terminal.application.tui_account_inspection_primary_fields import (
    build_account_inspection_primary_fields,
)

_CANONICAL_TARGET_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


def project_temporary_target_context(
    view_model: dict[str, object],
    payload: object,
    request_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Show the temporary source and exact residual cash when the owner confirms them."""

    requested_text = request_params.get("temporary_target_weights") if request_params else None
    if type(requested_text) is not str or not requested_text.strip():
        return view_model
    try:
        requested_target_record = parse_temporary_security_targets(requested_text).audit_record()
    except ValueError:
        return _blocked_target_context(view_model)
    audit_record = _temporary_target_audit_record(payload)
    if audit_record is None:
        return _blocked_target_context(view_model)
    target_weights = audit_record.get("target_weights")
    residual_text = audit_record.get("residual_cash_weight")
    if (
        not isinstance(target_weights, Mapping)
        or not target_weights
        or len(target_weights) > 50
        or type(residual_text) is not str
    ):
        return _blocked_target_context(view_model)
    try:
        residual = Decimal(residual_text)
    except (InvalidOperation, TypeError, ValueError):
        return _blocked_target_context(view_model)
    residual_exponent = residual.as_tuple().exponent
    if (
        not residual.is_finite()
        or residual.is_signed()
        or type(residual_exponent) is not int
        or -residual_exponent > 8
        or not Decimal("0") <= residual <= Decimal("1")
    ):
        return _blocked_target_context(view_model)
    target_fields = _target_weight_fields(target_weights)
    if target_fields is None or not _valid_target_weights(target_weights, residual):
        return _blocked_target_context(view_model)
    if (
        dict(target_weights) != requested_target_record["target_weights"]
        or residual_text != requested_target_record["residual_cash_weight"]
    ):
        return _blocked_target_context(view_model)
    with localcontext() as context:
        context.prec = 32
        residual_percent = residual * Decimal("100")
    percent_text = _decimal_text(residual_percent)
    section: dict[str, object] = {
        "key": "temporary_target_context",
        "title": "本次临时目标",
        "fields": [
            {
                "key": "target_source",
                "label": "目标来源",
                "value": "用户本次填写；未保存为策略配置或自动交易规则",
            },
            *target_fields,
            {
                "key": "residual_cash_weight",
                "label": "未分配目标现金权重",
                "value": f"{percent_text}%",
            },
        ],
        "body": ["目标现金权重为证券目标合计后的未分配比例。"],
    }
    updated = dict(view_model)
    sections = view_model.get("sections")
    updated["sections"] = [*sections, section] if isinstance(sections, list) else [section]
    projected_fields = updated.get("fields")
    if updated.get("kind") == "detail" and isinstance(projected_fields, list) and projected_fields:
        updated["fields"] = build_account_inspection_primary_fields(
            updated.get("fields"), updated.get("sections")
        )
    return updated


def _temporary_target_audit_record(payload: object) -> Mapping[str, object] | None:
    """Find one exact temporary-target marker without projecting raw response data."""

    if not isinstance(payload, Mapping):
        return None
    reports = payload.get("reports")
    if not isinstance(reports, list) or len(reports) != 1 or not isinstance(reports[0], Mapping):
        return None
    checks = reports[0].get("checks")
    if not isinstance(checks, list):
        return None
    records = [
        item
        for item in checks
        if isinstance(item, Mapping)
        and item.get("scope") == "temporary_target_entry"
        and item.get("source") == "user_entered_temporary"
    ]
    return records[0] if len(records) == 1 else None


def _blocked_target_context(view_model: dict[str, object]) -> dict[str, object]:
    """Fail closed if a requested temporary target cannot be tied to this result."""

    return {
        "kind": "message",
        "title": "账户调仓预览",
        "status": "预览受阻",
        "outcome": "blocked",
        "business_summary": "本次临时目标资料无法与预览结果对应；没有展示计划明细。",
        "message": "请重新选择本人账户并生成本次预览。",
        "sections": [],
        "fields": [],
    }


def _valid_target_weights(target_weights: Mapping[object, object], residual: Decimal) -> bool:
    """Check the complete audit weight map before showing its cash remainder."""

    parsed_weights: list[Decimal] = []
    seen_codes: set[str] = set()
    for raw_code, raw_weight in target_weights.items():
        if (
            type(raw_code) is not str
            or raw_code != raw_code.strip().upper()
            or not _CANONICAL_TARGET_CODE.fullmatch(raw_code)
            or raw_code in seen_codes
            or type(raw_weight) is not str
        ):
            return False
        seen_codes.add(raw_code)
        try:
            weight = Decimal(raw_weight)
        except (InvalidOperation, TypeError, ValueError):
            return False
        weight_exponent = weight.as_tuple().exponent
        if (
            not weight.is_finite()
            or weight.is_signed()
            or type(weight_exponent) is not int
            or -weight_exponent > 8
            or not Decimal("0") <= weight <= Decimal("1")
        ):
            return False
        parsed_weights.append(weight)
    with localcontext() as context:
        context.prec = 32
        return sum(parsed_weights, Decimal("0")) + residual == Decimal("1")


def _target_weight_fields(
    target_weights: Mapping[object, object],
) -> list[dict[str, str]] | None:
    """Format each validated security target as an exact user-facing percent."""

    text_weights: list[tuple[str, str]] = []
    for raw_code, raw_weight in target_weights.items():
        if type(raw_code) is not str or type(raw_weight) is not str:
            return None
        text_weights.append((raw_code, raw_weight))

    fields: list[dict[str, str]] = []
    for index, (raw_code, raw_weight) in enumerate(sorted(text_weights), start=1):
        try:
            weight = Decimal(raw_weight)
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not weight.is_finite() or not Decimal("0") <= weight <= Decimal("1"):
            return None
        with localcontext() as context:
            context.prec = 32
            percent = weight * Decimal("100")
        fields.append(
            {
                "key": f"temporary_target_{index}",
                "label": f"{raw_code} 目标比例",
                "value": f"{_decimal_text(percent)}%",
            }
        )
    return fields


def _decimal_text(value: Decimal) -> str:
    """Format an exact decimal without exponent notation or redundant zeros."""

    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
