"""Project strategy applicability for the read-only account-inspection screen."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class _RowFieldFormatter(Protocol):
    """Format one label/value row using the owning projector's established shape."""

    def __call__(self, key: str, label: str, value: str, /) -> dict[str, str]:
        """Return the established serialized label/value row."""
        ...


class _MoneyFormatter(Protocol):
    """Preserve a source money/percentage value without converting it."""

    def __call__(self, value: object, /) -> str:
        """Return safe display text for a source value."""
        ...


class _BoundedTextFormatter(Protocol):
    """Return safe bounded text or None using the owning projector's policy."""

    def __call__(self, value: object, *, limit: int) -> str | None:
        """Return validated text within the requested character bound."""
        ...


class _DateFormatter(Protocol):
    """Return a validated source date or None using the owning projector's policy."""

    def __call__(self, value: object, /) -> str | None:
        """Return a source date only when it passes the existing date check."""
        ...


@dataclass(frozen=True)
class _StrategyPolicyPresentation:
    """Typed, user-facing strategy state derived from the owner preview contract."""

    selection_label: str | None
    confirmed_unconfigured: bool
    manual_target_difference: bool
    risk_body: tuple[str, str] | None
    blocking_message: str | None


def _project_strategy_policy_presentation(
    value: object, asset_items: object
) -> _StrategyPolicyPresentation:
    """Keep unknown strategy state restrictive and label only confirmed absence."""

    context = _as_mapping(value)
    if context is None:
        return _StrategyPolicyPresentation(None, False, False, None, None)
    state_present = "strategy_selection_state" in context
    applicability_present = "strategy_policy_applicability" in context
    if not state_present and not applicability_present:
        return _StrategyPolicyPresentation(None, False, False, None, None)

    state = context.get("strategy_selection_state")
    applicability = context.get("strategy_policy_applicability")
    if state == "configured" and applicability == "applicable":
        if _has_target_mode(asset_items, "user_target_difference"):
            return _blocked_presentation(
                "本次目标口径与策略配置不匹配；策略相关预览已阻断，请重新生成。"
            )
        return _StrategyPolicyPresentation("已配置", False, False, None, None)
    if state == "confirmed_unconfigured" and applicability == "not_applicable":
        strategy_only_fields = (
            "strategy_id",
            "position_rule_id",
            "strategy_name",
            "strategy_version",
            "rule_name",
            "rule_version",
            "rule_effective_from",
            "rule_effective_until",
            "max_position_pct",
            "max_total_position_pct",
            "stop_loss_pct",
            "strategy_max_position_pct",
            "strategy_max_total_position_pct",
            "strategy_stop_loss_pct",
        )
        if any(context.get(key) is not None for key in strategy_only_fields):
            return _blocked_presentation(
                "未配置策略状态与返回的策略限制资料不一致；相关预览已阻断，请重新核对。"
            )
        if _has_target_mode(asset_items, "strategy_rule"):
            return _blocked_presentation(
                "本次目标口径与策略配置不匹配；策略相关预览已阻断，请重新生成。"
            )
        manual_mode = _all_manual_target_rows(asset_items)
        if isinstance(asset_items, list) and asset_items and not manual_mode:
            return _blocked_presentation(
                "本次标的目标口径与未配置策略状态不匹配；相关预览已阻断，请重新生成。"
            )
        selection_label = "未配置；本次按你提供的目标估算差额" if manual_mode else "未配置"
        if manual_mode:
            body = (
                "本次按你明确提供的目标估算差额，仅为只读预览，未采用策略规则；账户限制仍适用，来源限制和数量规则也仍适用。",
                "账户设置与策略限制分开展示；未配置策略的策略专属限制不适用，不以账户限制代替。",
            )
        else:
            body = (
                "本次未配置可用策略；策略专属规则不适用，账户限制仍按其来源单独展示。",
                "数量规则、来源限制和未知资料仍按本次记录展示；未提供的值保持未知。",
            )
        return _StrategyPolicyPresentation(selection_label, True, manual_mode, body, None)
    return _blocked_presentation(
        "无法确认本次策略配置或规则适用性；策略相关预览已阻断，请检查账户策略配置后重试。"
    )


def _all_manual_target_rows(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(_item_target_mode(item) == "user_target_difference" for item in value)


def _has_target_mode(value: object, expected: str) -> bool:
    if not isinstance(value, list):
        return False
    return any(_item_target_mode(item) == expected for item in value)


def _item_target_mode(value: object) -> str | None:
    item = _as_mapping(value)
    mode = item.get("target_mode") if item is not None else None
    return mode if type(mode) is str else None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        return None
    return value


def _blocked_presentation(message: str) -> _StrategyPolicyPresentation:
    return _StrategyPolicyPresentation(None, False, False, None, message)


def _project_strategy_risk_fields(
    value: object,
    *,
    presentation: _StrategyPolicyPresentation,
    row_field: _RowFieldFormatter,
    money_text: _MoneyFormatter,
    bounded_text: _BoundedTextFormatter,
    date_text: _DateFormatter,
) -> list[dict[str, str]]:
    """Show account and strategy limits with only verified applicability labels."""

    context = _as_mapping(value)
    strategy_version = context.get("strategy_version") if context is not None else None
    strategy_name = (
        bounded_text(context.get("strategy_name"), limit=96) if context is not None else None
    )
    rule_name = bounded_text(context.get("rule_name"), limit=96) if context is not None else None
    rule_version = (
        bounded_text(context.get("rule_version"), limit=80) if context is not None else None
    )
    rule_from = date_text(context.get("rule_effective_from")) if context is not None else None
    rule_until = date_text(context.get("rule_effective_until")) if context is not None else None
    version_text = (
        str(strategy_version)
        if type(strategy_version) is int and strategy_version > 0
        else "未提供"
    )
    if presentation.confirmed_unconfigured:
        absent_text = "不适用" if presentation.manual_target_difference else "未配置"
        strategy_name_text = "未配置"
        strategy_version_text = absent_text
        rule_name_text = absent_text
        rule_version_text = absent_text
        rule_from_text = absent_text
        rule_until_text = absent_text
    else:
        strategy_name_text = strategy_name or "未提供"
        strategy_version_text = version_text
        rule_name_text = rule_name or "未提供"
        rule_version_text = rule_version or "未提供"
        rule_from_text = rule_from or "未提供"
        rule_until_text = rule_until or "未提供"

    fields: list[dict[str, str]] = []
    if presentation.selection_label is not None:
        fields.append(row_field("strategy_selection", "策略配置状态", presentation.selection_label))
    fields.extend(
        [
            row_field("strategy_name", "采用策略", strategy_name_text),
            row_field("strategy_version", "策略版本", strategy_version_text),
            row_field("rule_name", "采用规则", rule_name_text),
            row_field("rule_version", "策略规则版本", rule_version_text),
            row_field("rule_effective_from", "策略规则生效日期", rule_from_text),
            row_field("rule_effective_until", "策略规则截止日期", rule_until_text),
        ]
    )
    limits = (
        ("account_max_position_pct", "账户设置的单标的持仓上限（0–100%）"),
        ("account_max_total_position_pct", "账户设置的总持仓上限（0–100%）"),
        ("account_stop_loss_pct", "账户设置的止损比例（0–100%）"),
        ("strategy_max_position_pct", "选定策略的单标的持仓上限（0–100%）"),
        ("strategy_max_total_position_pct", "选定策略的总持仓上限（0–100%）"),
        ("strategy_stop_loss_pct", "选定策略的止损比例（0–100%）"),
    )
    for key, label in limits:
        amount = money_text(context.get(key) if context is not None else None)
        if presentation.confirmed_unconfigured and key.startswith("strategy_"):
            amount_text = (
                "不适用（未配置策略）" if presentation.manual_target_difference else "未配置"
            )
        else:
            amount_text = amount if amount in {"未提供", "格式未确认"} else f"{amount}%"
        fields.append(row_field(key, label, amount_text))
    fields.append(row_field("falsification", "证伪条件", "本次响应未提供"))
    return fields
