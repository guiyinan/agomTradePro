"""Present owner-reported research uses without deriving financial eligibility."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict


class TuiResearchField(TypedDict):
    """One curated, readable research fact."""

    key: str
    label: str
    value: str


_CAPABILITY_LABELS = {
    "market_research": "行情研究",
    "technical_scoring": "技术评分",
    "financial_valuation": "财务估值",
    "plan_calculation": "计划计算",
    "order_submission": "下单",
}
_NEXT_STEPS = {
    "market_research": "核对行情来源与限制",
    "technical_scoring": "需实际技术评分结果",
    "financial_valuation": "需估值分析确认",
    "plan_calculation": "需选择账户并检查计划",
    "order_submission": "需账户及委托检查",
}


def append_research_capabilities(
    fields: list[TuiResearchField], payload: object
) -> list[TuiResearchField]:
    """Append readable owner states; malformed supplied data remains unknown."""
    capabilities = payload if isinstance(payload, Mapping) else {}
    asset_type = next((field["value"] for field in fields if field["key"] == "asset_type"), None)
    presented_fields: list[TuiResearchField] = []
    for field in fields:
        if field["key"] == "asset_type":
            continue
        if field["key"] == "security" and asset_type:
            presented_fields.append({**field, "value": f"{field['value']}；资产类型：{asset_type}"})
        else:
            presented_fields.append(field)
    descriptions: list[str] = []
    for key, label in _CAPABILITY_LABELS.items():
        capability = capabilities.get(key)
        status = capability.get("status") if isinstance(capability, Mapping) else None
        if key == "market_research" and status == "observation_only":
            description = "资料可查看（仅供观察）"
        elif status == "blocked":
            description = "资料受限，请查看来源与限制"
        elif status == "not_evaluated":
            description = f"未评估，{_NEXT_STEPS[key]}"
        else:
            description = "状态未知，请核对原始研究结果"
        descriptions.append(f"{label}：{description}")
    return [
        *presented_fields,
        {"key": "capabilities", "label": "用途说明", "value": "；".join(descriptions)},
    ]
