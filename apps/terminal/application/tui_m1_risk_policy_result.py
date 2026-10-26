"""Human-readable projections for owner M1 risk publication and revocation receipts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

_PUBLISH_ACTION = "account-inspection.m1-risk-policy.publish"
_REVOKE_ACTION = "account-inspection.m1-risk-policy.revoke"
_DIMENSION_LABELS = {
    "max_single_position": "单个标的限额",
    "max_total_position": "账户总持仓限额",
    "max_stop_loss": "止损限额",
}
_APPLICABILITY_LABELS = {
    "applicable": "适用",
    "not_applicable": "不适用",
    "unknown": "未知（当前将阻止买入）",
}


def project_m1_risk_policy_mutation_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project owner-facing facts, binding a revoke receipt to its submitted target."""

    if action_key == _PUBLISH_ACTION:
        return _project_publish(payload, http_status=http_status)
    if action_key == _REVOKE_ACTION:
        return _project_revoke(
            payload,
            http_status=http_status,
            requested_params=requested_params,
        )
    return _blocked("风险约束", "无法识别这项风险约束操作。")


def _project_publish(payload: object, *, http_status: int) -> dict[str, object]:
    if http_status != 201 or not isinstance(payload, Mapping):
        return _blocked(
            "风险约束发布",
            "没有取得可核对的发布回执。请先重新读取账户调仓预览，再决定是否重试本次提交。",
        )

    version = _uuid_text(payload.get("risk_policy_version"))
    account_id = _positive_int(payload.get("account_id"))
    effective_from = _aware_time(payload.get("effective_from"))
    effective_until = _aware_time(payload.get("effective_until"))
    known_at = _aware_time(payload.get("known_at"))
    start_value = _aware_datetime(payload.get("effective_from"))
    end_value = _aware_datetime(payload.get("effective_until"))
    source_binding = payload.get("source_binding")
    strategy_context = _strategy_context(source_binding)
    risk_falsification = payload.get("risk_falsification")
    if (
        version is None
        or account_id is None
        or effective_from is None
        or effective_until is None
        or known_at is None
        or start_value is None
        or end_value is None
        or start_value >= end_value
        or payload.get("publication_status") != "published"
        or payload.get("legacy_rule_version") is not None
        or strategy_context is None
        or not isinstance(risk_falsification, Mapping)
        or risk_falsification.get("schema_version") != "m1-risk-falsification.v1"
        or risk_falsification.get("status") != "not_evaluated"
    ):
        return _blocked(
            "风险约束发布",
            "发布回执中的版本、生效时间或策略状态不完整；请重新读取账户调仓预览核对。",
        )

    raw_conditions = risk_falsification.get("conditions")
    if not isinstance(raw_conditions, list):
        return _blocked(
            "风险约束发布",
            "发布回执中的限额状态不完整；请重新读取账户调仓预览核对。",
        )
    conditions: dict[str, Mapping[str, object]] = {}
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, Mapping):
            return _blocked(
                "风险约束发布",
                "发布回执中的限额状态无法核对；请重新读取账户调仓预览核对。",
            )
        dimension = raw_condition.get("dimension")
        if (
            not isinstance(dimension, str)
            or dimension not in _DIMENSION_LABELS
            or dimension in conditions
        ):
            return _blocked(
                "风险约束发布",
                "发布回执中的限额状态无法核对；请重新读取账户调仓预览核对。",
            )
        conditions[dimension] = raw_condition
    if set(conditions) != set(_DIMENSION_LABELS):
        return _blocked(
            "风险约束发布",
            "发布回执未包含全部限额状态；请重新读取账户调仓预览核对。",
        )

    fields: list[dict[str, str]] = [
        _field("risk_policy_version", "风险版本编号", version, "copyable"),
        _field("account_id", "账户编号", str(account_id)),
        _field("strategy_context", "提交时的策略状态", strategy_context),
        _field("effective_from", "生效时间", effective_from),
        _field("effective_until", "失效时间", effective_until),
        _field("known_at", "记录时间", known_at),
    ]
    for dimension, label in _DIMENSION_LABELS.items():
        value = _condition_value(conditions[dimension])
        if value is None:
            return _blocked(
                "风险约束发布",
                "发布回执中的限额状态无法核对；请重新读取账户调仓预览核对。",
            )
        fields.append(_field(dimension, label, value))

    binding_state = _mapping_value(source_binding, "strategy_selection_state")
    strategy_unavailable = binding_state == "unavailable"
    return {
        "kind": "detail",
        "title": "账户风险约束发布回执",
        "status": "已发布，策略状态无法核验" if strategy_unavailable else "已发布",
        "outcome": "partial" if strategy_unavailable else "success",
        "fields": fields,
        "nested": [],
        "business_summary": (
            f"账户 {account_id} 的风险约束已发布；提交时的策略状态和生效时间以回执为准。"
        ),
        "blocking_reason": (
            "提交时无法核验当前策略或仓位规则；请重新读取账户调仓预览确认是否可用于买入。"
            if strategy_unavailable
            else ""
        ),
        "next_steps": (
            ["重新读取账户调仓预览，确认当前账户和策略规则与发布时一致。"]
            if strategy_unavailable
            else []
        ),
        "debug_hidden_fields": [],
    }


def _project_revoke(
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Show a revoke receipt only when it matches the exact submitted target."""

    if http_status != 200 or not isinstance(payload, Mapping) or requested_params is None:
        return _blocked(
            "风险约束撤销",
            "撤销回执无法核对；请重新读取账户风险约束状态，不要直接重复撤销操作。",
        )

    version = _uuid_text(payload.get("risk_policy_version"))
    requested_version = _uuid_text(requested_params.get("risk_policy_version"))
    account_id = _positive_int(payload.get("account_id"))
    requested_account_id = _requested_positive_int(requested_params.get("account_id"))
    revoked_at = _aware_time(payload.get("revoked_at"))
    actor_id = _positive_int(payload.get("revoked_by_user_id"))
    reason = _safe_reason(payload.get("revocation_reason"))
    if (
        version is None
        or requested_version is None
        or version != requested_version
        or account_id is None
        or requested_account_id is None
        or account_id != requested_account_id
        or revoked_at is None
        or actor_id is None
        or reason is None
        or payload.get("revocation_status") != "revoked"
    ):
        return _blocked(
            "风险约束撤销",
            "撤销回执与提交的账户或版本不一致，或缺少可核对信息；"
            "请重新读取账户风险约束状态，不要直接重复撤销操作。",
        )

    fields: list[dict[str, str]] = [
        _field("risk_policy_version", "风险版本编号", version, "copyable"),
        _field("account_id", "账户编号", str(account_id)),
        _field("revoked_at", "撤销时间", revoked_at),
        _field("revocation_reason", "撤销原因", reason),
    ]
    return {
        "kind": "detail",
        "title": "账户风险约束撤销回执",
        "status": "已撤销",
        "outcome": "success",
        "fields": fields,
        "nested": [],
        "business_summary": f"账户 {account_id} 的风险版本 {version} 已撤销。",
        "blocking_reason": "",
        "next_steps": [],
        "debug_hidden_fields": [],
    }


def _strategy_context(source_binding: object) -> str | None:
    if not isinstance(source_binding, Mapping):
        return None
    state = source_binding.get("strategy_selection_state")
    strategy_id = source_binding.get("strategy_id")
    strategy_version = source_binding.get("strategy_version")
    position_rule_id = source_binding.get("position_rule_id")
    if state == "configured":
        if _positive_int(strategy_id) is None:
            return None
        identifiers = [f"策略编号 {strategy_id}"]
        if strategy_version is not None:
            if _positive_int(strategy_version) is None:
                return None
            identifiers.append(f"策略版本 {strategy_version}")
        if position_rule_id is not None:
            if _positive_int(position_rule_id) is None:
                return None
            identifiers.append(f"仓位规则编号 {position_rule_id}")
        return "当前策略已识别（" + "；".join(identifiers) + "）"
    if state == "confirmed_unconfigured":
        if any(value is not None for value in (strategy_id, strategy_version, position_rule_id)):
            return None
        return "提交时已核验：当前账户未配置策略"
    if state == "unavailable":
        if any(value is not None for value in (strategy_id, strategy_version, position_rule_id)):
            return None
        return "提交时无法核验当前策略或仓位规则"
    return None


def _condition_value(condition: Mapping[str, object]) -> str | None:
    applicability = condition.get("applicability")
    if not isinstance(applicability, str) or applicability not in _APPLICABILITY_LABELS:
        return None
    if applicability == "unknown":
        if condition.get("threshold_pct") is not None or condition.get("owner_reason") is not None:
            return None
        return _APPLICABILITY_LABELS[applicability]
    if applicability == "not_applicable":
        reason = _safe_reason(condition.get("owner_reason"))
        if condition.get("threshold_pct") is not None or reason is None:
            return None
        return f"不适用：{reason}"
    limit = _percentage(condition.get("threshold_pct"))
    if limit is None or condition.get("owner_reason") is not None:
        return None
    return f"{_APPLICABILITY_LABELS[applicability]}：{limit}%"


def _field(
    key: str,
    label: str,
    value: str,
    presentation: str = "metadata",
) -> dict[str, str]:
    field = {"key": key, "label": label, "value": value}
    if presentation == "copyable":
        field["presentation"] = presentation
    return field


def _blocked(title: str, message: str) -> dict[str, object]:
    return {
        "kind": "message",
        "title": title,
        "status": "结果待核对",
        "outcome": "blocked",
        "message": message,
        "business_summary": message,
        "blocking_reason": "没有取得完整、可核对的风险约束回执。",
        "fields": [],
        "nested": [],
        "next_steps": [],
        "debug_hidden_fields": [],
    }


def _uuid_text(value: object) -> str | None:
    if not isinstance(value, UUID | str):
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError):
        return None


def _positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _requested_positive_int(value: object) -> int | None:
    """Normalize the positive account path value used by TUI endpoint binding."""

    if type(value) is int:
        return _positive_int(value)
    if type(value) is not str or not value.isascii() or not value.isdigit():
        return None
    try:
        return _positive_int(int(value))
    except (ValueError, OverflowError):
        return None


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.endswith(("Z", "+00:00")) and not _has_numeric_offset(text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _aware_time(value: object) -> str | None:
    parsed = _aware_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _has_numeric_offset(value: str) -> bool:
    if len(value) < 6:
        return False
    offset = value[-6:]
    return (
        offset[0] in {"+", "-"}
        and offset[1:3].isdigit()
        and offset[3] == ":"
        and offset[4:6].isdigit()
    )


def _percentage(value: object) -> str | None:
    if not isinstance(value, str | Decimal | int):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0 or parsed > 100:
        return None
    return format(parsed.normalize(), "f")


def _safe_reason(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    reason = value.strip()
    if not reason or any(ord(character) < 32 or ord(character) == 127 for character in reason):
        return None
    return reason


def _mapping_value(mapping: object, key: str) -> object:
    return mapping.get(key) if isinstance(mapping, Mapping) else None


__all__: tuple[str, ...] = ("project_m1_risk_policy_mutation_result",)
