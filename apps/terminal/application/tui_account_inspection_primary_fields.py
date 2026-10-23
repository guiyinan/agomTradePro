"""Format a compact first-view summary from an inspected account result."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeGuard

_PRIMARY_FIELD_KEYS = frozenset(
    {
        "p0_scope_time",
        "p0_target_cash",
        "p0_fees_cash",
        "p0_first_asset",
        "p0_applicable_limits",
    }
)


def build_account_inspection_primary_fields(
    fields: object,
    sections: object,
) -> list[dict[str, str]]:
    """Prepend concise facts without changing, calculating, or dropping source values.

    Args:
        fields: Already validated summary fields produced by the result projector.
        sections: Already projected display rows produced by that same projector.

    Returns:
        Five primary display fields followed by the original metadata fields.
    """

    field_rows = _mapping_sequence(fields)
    section_rows = _mapping_sequence(sections)
    field_values = _field_values(field_rows)
    section_values = _section_values(section_rows)
    quantity_section = section_values.get("asset_quantity_plan", {})
    source_section = section_values.get("asset_source_times", {})
    cash_section = section_values.get("cash_and_cost_estimates", {})
    risk_section = section_values.get("selected_strategy_and_risk_limits", {})
    target_section = section_values.get("temporary_target_context", {})

    quantity_rows = _rows(quantity_section)
    first_row = _row_values(quantity_rows[0]) if quantity_rows else {}
    source_fields = _field_values(_mapping_sequence(source_section.get("fields")))
    cash_fields = _field_values(_mapping_sequence(cash_section.get("fields")))
    risk_fields = _field_values(_mapping_sequence(risk_section.get("fields")))
    target_field_rows = _original_field_values(_mapping_sequence(target_section.get("fields")))

    primary = [
        _field(
            "p0_scope_time",
            "用途与时点",
            _scope_and_time(field_values, source_fields, cash_fields),
        ),
        _field(
            "p0_target_cash",
            "目标与未分配现金",
            _target_and_cash(target_field_rows, first_row, cash_fields),
        ),
        _field("p0_fees_cash", "费用与现金估算", _fees_and_cash(field_values, cash_fields)),
        _field(
            "p0_first_asset",
            "首项标的建议",
            _first_asset_summary(first_row, len(quantity_rows)),
        ),
        _field("p0_applicable_limits", "适用限制", _limits_summary(risk_fields)),
    ]
    metadata = [
        {"key": key, "label": label, "value": value}
        for key, (label, value) in _original_field_values(field_rows).items()
        if key not in _PRIMARY_FIELD_KEYS
    ]
    return [*primary, *metadata]


def _field_values(fields: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """Read only string-valued fields from the projected presentation contract."""

    values: dict[str, str] = {}
    for field in fields:
        key = field.get("key")
        value = field.get("value")
        if type(key) is str and type(value) is str:
            values.setdefault(key, value)
    return values


def _original_field_values(
    fields: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, str]]:
    """Keep the original label/value pairs in their original order."""

    values: dict[str, tuple[str, str]] = {}
    for field in fields:
        key = field.get("key")
        label = field.get("label")
        value = field.get("value")
        if type(key) is str and type(label) is str and type(value) is str:
            values.setdefault(key, (label, value))
    return values


def _section_values(
    sections: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    """Index projected sections by their stable display key."""

    values: dict[str, Mapping[str, object]] = {}
    for section in sections:
        key = section.get("key")
        if type(key) is str:
            values.setdefault(key, section)
    return values


def _mapping_sequence(value: object) -> list[Mapping[str, object]]:
    """Narrow a list of projected objects for field extraction."""

    if not isinstance(value, list):
        return []
    return [item for item in value if _is_string_keyed_mapping(item)]


def _is_string_keyed_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Narrow a dynamic presentation object to string-keyed values."""

    return isinstance(value, Mapping) and all(type(key) is str for key in value)


def _rows(section: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Return the already projected rows for one section."""

    return _mapping_sequence(section.get("rows"))


def _row_values(row: Mapping[str, object]) -> dict[str, str]:
    """Read one projected row without inspecting source payloads."""

    return _field_values(_mapping_sequence(row.get("fields")))


def _scope_and_time(
    fields: Mapping[str, str],
    source_fields: Mapping[str, str],
    cash_fields: Mapping[str, str],
) -> str:
    """Describe preview scope and real source/snapshot clocks already projected."""

    status = fields.get("plan_status", "预览状态未提供")
    date_text = fields.get("inspection_date", "未提供")
    as_of = fields.get("as_of", "未提供")
    observed_at = source_fields.get("observed_at", "未提供")
    snapshot_at = cash_fields.get("financial_snapshot_read_at", "未提供")
    return (
        f"{status}；只读预览，未提交交易；生成日期 {date_text}；预览时点 {as_of}；"
        f"首项行情来源观测 {observed_at}；账户资料读取 {snapshot_at}"
    )


def _target_and_cash(
    target_fields: Mapping[str, tuple[str, str]],
    first_row: Mapping[str, str],
    cash_fields: Mapping[str, str],
) -> str:
    """Summarize a validated target marker, or state that its weight is absent."""

    targets = [
        (key, label, value)
        for key, (label, value) in target_fields.items()
        if key.startswith("temporary_target_")
    ]
    residual_row = target_fields.get("residual_cash_weight")
    if targets and residual_row is not None:
        _key, label, value = targets[0]
        remainder = len(targets) - 1
        more = f"；其余{remainder}项目标比例见下方本次临时目标" if remainder else ""
        return f"{label} {value}；未分配目标现金 {residual_row[1]}{more}"

    target_quantity = first_row.get("target", "未提供")
    post_buy_cash = cash_fields.get("projected_cash_after_buys", "未提供")
    return (
        f"目标比例与未分配现金比例本次未提供；首项目标数量 {target_quantity}；"
        f"买入后余额估算 {post_buy_cash}（未发生交易）"
    )


def _fees_and_cash(fields: Mapping[str, str], cash_fields: Mapping[str, str]) -> str:
    """Combine only values already rendered by the cash projection."""

    currency = fields.get("currency", "币种待核对")
    currency_text = "币种本次未提供" if currency == "本次未提供" else currency
    available = cash_fields.get("available_cash_before", "未提供")
    sell_fees = cash_fields.get("estimated_sell_fees", "未提供")
    buy_fees = cash_fields.get("estimated_buy_fees", "未提供")
    after_buys = cash_fields.get("projected_cash_after_buys", "未提供")
    return (
        f"当前可用现金 {available}；卖出费用 {sell_fees}；买入费用 {buy_fees}；"
        f"买入后预计余额 {after_buys}；{currency_text}；未发生交易"
    )


def _first_asset_summary(first_row: Mapping[str, str], row_count: int) -> str:
    """Present the first safe quantity row and point to every remaining row."""

    if not first_row:
        return "本次未提供单标的数量建议"
    code = first_row.get("asset_code", "未提供")
    asset_name = first_row.get("asset", "标的名称未提供")
    identifier = f"{code}（{asset_name}）" if code != "未提供" else asset_name
    unit = first_row.get("unit", "数量单位未提供")
    details = (
        f"{identifier} {first_row.get('direction', '方向未提供')}；"
        f"当前 {first_row.get('current', '未提供')}，可卖 {first_row.get('sellable', '未提供')}；"
        f"目标 {first_row.get('target', '未提供')}，理论差量 {first_row.get('suggested', '未提供')}；"
        f"规则后建议 {first_row.get('actionable', '未提供')} {unit}；"
        f"{first_row.get('status', '状态与原因未提供')}"
    )
    other_count = max(row_count - 1, 0)
    return f"{details}；另有{other_count}项见完整数量建议" if other_count else details


def _limits_summary(risk_fields: Mapping[str, str]) -> str:
    """Summarize translated applicability and source-provided limits."""

    selection = risk_fields.get("strategy_selection")
    if selection is None:
        selection = risk_fields.get("strategy_name", "策略状态未提供")
    account = (
        f"账户单标的 {risk_fields.get('account_max_position_pct', '未提供')}；"
        f"总持仓 {risk_fields.get('account_max_total_position_pct', '未提供')}；"
        f"止损 {risk_fields.get('account_stop_loss_pct', '未提供')}"
    )
    strategy_limits = (
        f"策略单标的 {risk_fields.get('strategy_max_position_pct', '未提供')}；"
        f"总持仓 {risk_fields.get('strategy_max_total_position_pct', '未提供')}；"
        f"止损 {risk_fields.get('strategy_stop_loss_pct', '未提供')}"
    )
    return f"{selection}。{account}。{strategy_limits}"


def _field(key: str, label: str, value: str) -> dict[str, str]:
    """Create one renderer-compatible field row."""

    return {"key": key, "label": label, "value": value}
