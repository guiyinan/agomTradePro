"""Project strategy applicability for the read-only account-inspection screen."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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


class _TimestampFormatter(Protocol):
    """Return a validated aware timestamp or None using the owning projector."""

    def __call__(self, value: object, *, limit: int) -> str | None:
        """Return a timezone-aware timestamp only when it passes the source check."""
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
    timestamp_text: _TimestampFormatter,
) -> list[dict[str, str]]:
    """Show source limits and exact M1 version evidence without old-version fallback."""

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

    raw_policy_version = context.get("risk_policy_version") if context is not None else None
    policy_version = "未知（本次预览未提供）"
    if raw_policy_version is not None:
        version_candidate = bounded_text(raw_policy_version, limit=36)
        try:
            policy_version = str(UUID(version_candidate or ""))
        except ValueError:
            policy_version = "格式未确认"
    raw_legacy_policy_version = context.get("legacy_rule_version") if context is not None else None
    legacy_policy_version = (
        bounded_text(raw_legacy_policy_version, limit=80) or "格式未确认"
        if raw_legacy_policy_version is not None
        else "未知（本次预览未提供旧版风险版本）"
    )
    qualification_status = (
        context.get("risk_policy_qualification_status") if context is not None else None
    )
    qualification_labels = {
        "qualified": "版本与来源已核验",
        "missing": "没有可用的 M1 风险版本",
        "not_effective": "当前时点不在生效窗口内",
        "source_changed": "风险来源已变化",
        "revoked": "风险版本已撤销",
        "unknown": "版本或来源无法核验",
    }
    qualification_text = (
        qualification_labels.get(qualification_status, "状态未确认")
        if type(qualification_status) is str
        else "状态未确认"
    )
    effective_from_text = _risk_timestamp_text(
        context.get("risk_policy_effective_from") if context is not None else None,
        timestamp_text=timestamp_text,
    )
    effective_until_text = _risk_timestamp_text(
        context.get("risk_policy_effective_until") if context is not None else None,
        timestamp_text=timestamp_text,
    )
    known_at_text = _risk_timestamp_text(
        context.get("risk_policy_known_at") if context is not None else None,
        timestamp_text=timestamp_text,
    )
    falsification_status, falsification_conditions = _m1_falsification_text(
        context.get("risk_falsification") if context is not None else None,
        money_text=money_text,
    )

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
            row_field("risk_policy_version", "M1 风险版本", policy_version),
            row_field(
                "legacy_risk_policy_version",
                "旧版风险版本",
                legacy_policy_version,
            ),
            row_field("risk_policy_qualification_status", "风险版本核验状态", qualification_text),
            row_field("risk_policy_effective_from", "风险版本生效时间", effective_from_text),
            row_field("risk_policy_effective_until", "风险版本失效时间", effective_until_text),
            row_field("risk_policy_known_at", "风险版本记录时间", known_at_text),
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
    fields.append(row_field("risk_falsification", "风险证伪结果", falsification_status))
    for dimension in (
        "max_single_position",
        "max_total_position",
        "max_stop_loss",
    ):
        fields.append(
            row_field(
                f"risk_falsification_{dimension}",
                _RISK_DIMENSION_LABELS[dimension],
                falsification_conditions.get(dimension, "本次响应未提供"),
            )
        )
    return fields


_RISK_DIMENSION_LABELS: dict[str, str] = {
    "max_single_position": "单标的风险证伪条件",
    "max_total_position": "总持仓风险证伪条件",
    "max_stop_loss": "止损风险证伪条件",
}
_RISK_OUTCOME_LABELS: dict[str, str] = {
    "not_falsified": "当前观察未证伪",
    "falsified": "观察已证伪",
    "unknown": "资料未知，无法判定",
    "not_applicable": "本项不适用",
}
_RISK_APPLICABILITY_LABELS: dict[str, str] = {
    "applicable": "适用",
    "not_applicable": "不适用",
    "unknown": "未知",
}
_RISK_FALSIFICATION_STATUS_LABELS: dict[str, str] = {
    "not_evaluated": "本次尚未评估",
    "not_applicable": "没有适用的观察项",
    "not_falsified": "当前观察未证伪",
    "falsified": "观察已证伪",
    "unknown": "资料未知，无法判定",
}


def _risk_timestamp_text(
    value: object,
    *,
    timestamp_text: _TimestampFormatter,
) -> str:
    """Keep an absent or malformed M1 timestamp distinct from a known one."""

    if value is None:
        return "未提供"
    return timestamp_text(value, limit=80) or "格式未确认"


def _m1_falsification_text(
    value: object,
    *,
    money_text: _MoneyFormatter,
) -> tuple[str, dict[str, str]]:
    """Project validated falsification status and per-condition observations."""

    context = _as_mapping(value)
    if context is None:
        return "本次响应未提供", {}
    status = context.get("status")
    status_text = (
        _RISK_FALSIFICATION_STATUS_LABELS.get(status, "状态未确认")
        if type(status) is str
        else "状态未确认"
    )
    raw_conditions = context.get("conditions")
    if not isinstance(raw_conditions, list):
        return status_text, {}
    conditions: dict[str, str] = {}
    for raw_condition in raw_conditions:
        condition = _as_mapping(raw_condition)
        dimension = condition.get("dimension") if condition is not None else None
        if (
            condition is None
            or type(dimension) is not str
            or dimension not in _RISK_DIMENSION_LABELS
            or dimension in conditions
        ):
            continue
        outcome = condition.get("outcome")
        outcome_text = (
            _RISK_OUTCOME_LABELS.get(outcome, "状态未确认")
            if type(outcome) is str
            else "状态未确认"
        )
        policy_state = condition.get("policy_applicability")
        observation_state = condition.get("observation_applicability")
        policy_text = (
            _RISK_APPLICABILITY_LABELS.get(policy_state, "未知")
            if type(policy_state) is str
            else "未知"
        )
        observation_text = (
            _RISK_APPLICABILITY_LABELS.get(observation_state, "未知")
            if type(observation_state) is str
            else "未知"
        )
        threshold_text = _risk_percentage_text(condition.get("threshold_pct"), money_text)
        observed_text = _risk_percentage_text(condition.get("observed_pct"), money_text)
        conditions[dimension] = (
            f"{outcome_text}；限额{policy_text}、观察{observation_text}；"
            f"阈值 {threshold_text}，观察值 {observed_text}"
        )
    return status_text, conditions


def _risk_percentage_text(value: object, money_text: _MoneyFormatter) -> str:
    """Render only a bounded percentage value supplied by the risk contract."""

    rendered = money_text(value)
    if rendered in {"未提供", "格式未确认"}:
        return rendered
    return f"{rendered}%"
