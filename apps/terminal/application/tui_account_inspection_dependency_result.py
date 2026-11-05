"""Project the account-inspection sell and buy funding explanation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class _RowFieldFormatter(Protocol):
    """Build the owner projector's established label/value row."""

    def __call__(self, key: str, label: str, value: str) -> dict[str, str]:
        """Return a safe serialized result field."""
        ...


class _SafeTextFormatter(Protocol):
    """Validate a bounded text value using the owning projector's policy."""

    def __call__(self, value: object, *, limit: int) -> str | None:
        """Return bounded safe text or ``None``."""
        ...


def project_account_inspection_dependency_fields(
    value: Mapping[str, object] | None,
    *,
    row_field: _RowFieldFormatter,
    safe_text: _SafeTextFormatter,
) -> list[dict[str, str]]:
    """Render estimated sell/buy sequencing without implying an executed order."""

    if value is None:
        return [
            row_field("sequence", "估算顺序", "顺序资料待确认"),
            row_field("buy_requires_settled_sales", "买入资金交收依赖", "本次未提供"),
        ]
    required = value.get("required")
    buy_requires_settled_sales = value.get("buy_requires_settled_sales")
    sells = _safe_code_list(value.get("sell_asset_codes"), safe_text=safe_text)
    buys = _safe_code_list(value.get("buy_asset_codes"), safe_text=safe_text)
    settled_sales_label = _settled_sales_label(buy_requires_settled_sales)
    settled_sales_field = row_field(
        "buy_requires_settled_sales", "买入资金交收依赖", settled_sales_label
    )
    unknown_fields = [
        row_field("sequence", "估算顺序", "顺序资料待确认；未发生交易"),
        settled_sales_field,
    ]
    if sells is None or buys is None or value.get("sequence") != "sell_then_buy":
        return unknown_fields
    if required is False and buy_requires_settled_sales is False:
        if not sells and not buys:
            return [
                row_field("sequence", "估算顺序", "本次未记录卖出后买入依赖"),
                settled_sales_field,
                row_field("execution", "交易状态", "未发生交易"),
            ]
        if sells and buys:
            sequence_label = "建议先核对卖出，再核对买入；顺序仅作估算。"
        elif sells:
            sequence_label = "本次仅列出卖出方向；顺序仅作估算。"
        else:
            sequence_label = "本次仅列出买入方向；顺序仅作估算。"
        return [
            row_field("sequence", "估算顺序", sequence_label),
            row_field("sell_assets", "估算卖出标的", "、".join(sells) or "本次无卖出标的"),
            row_field("buy_assets", "估算买入标的", "、".join(buys) or "本次无买入标的"),
            settled_sales_field,
            row_field(
                "execution",
                "交易状态与核对",
                "未发生交易；实际可用资金、风险和费用仍须逐笔核对",
            ),
        ]
    if required is True and buy_requires_settled_sales is True:
        return [
            row_field(
                "sequence",
                "估算顺序",
                "买入依赖预计卖款；到账后逐笔复核，不要求全部卖出完成；未发生交易。",
            ),
            row_field("sell_assets", "估算卖出标的", "、".join(sells) or "未提供"),
            row_field("buy_assets", "估算买入标的", "、".join(buys) or "未提供"),
            settled_sales_field,
        ]
    return unknown_fields


def _settled_sales_label(value: object) -> str:
    if value is True:
        return "是；卖款实际交收后按当前资金、风险和费用重核；不要求全部卖出完成"
    return (
        "否；本次未标记卖款依赖；实际可用资金、风险和费用仍须逐笔核对"
        if value is False
        else "本次未提供"
    )


def _safe_code_list(value: object, *, safe_text: _SafeTextFormatter) -> list[str] | None:
    if not isinstance(value, list):
        return None
    codes: list[str] = []
    for item in value:
        code = safe_text(item, limit=48)
        if code is None:
            return None
        codes.append(code)
    return codes
