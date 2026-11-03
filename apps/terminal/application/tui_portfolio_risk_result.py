"""Read-only TUI projection for simulation-only portfolio risk reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

_OUTCOME_LABELS = {
    "allowed": "约束核对通过（仅模拟）",
    "blocked": "存在阻断约束",
    "partial": "部分核对完成，仍有缺项",
    "unknown": "关键风险数据未知",
}
_CHECK_STATUS_LABELS = {
    "allowed": "已核对",
    "blocked": "阻断",
    "partial": "部分可用",
    "unknown": "未知",
}
_DETAIL_LABELS = {
    "coverage_fraction": "数据覆盖比例",
    "coverage_basis": "覆盖口径",
    "exit_sessions_required": "预计退出所需交易日",
    "hypothetical_exitable_quantity": "压力窗口假设可退出数量",
    "stress_window_residual_quantity": "压力窗口剩余持仓数量",
    "unreleased_exposure_market_value": "尚未解除的持仓市值",
    "unreleased_exposure_quantity": "尚未解除的持仓数量",
}
_DIMENSION_LABELS = {
    "exit_pressure": "退出压力",
    "industry_concentration": "行业集中度",
    "liquidity": "流动性",
    "scenario_impact": "情景影响",
    "security_concentration": "单一证券集中度",
    "source_quality": "来源质量",
}
_PRECISION_LABELS = {
    "timestamp": "精确时刻",
    "date": "日期",
    "unknown": "未知",
}
_RESTRICTION_LABELS = {
    "close_snapshot_only": "仅限收盘快照模拟",
    "historical_only": "仅历史数据",
    "must_not_use_for_decision": "不得用于决策",
    "observation_only": "仅供观察",
    "research_only": "仅限研究",
    "same_business_date_membership_only": "仅适用于所列交易日的行业归属",
    "session_cumulative_quote": "仅为单交易日累计成交量",
    "vendor_reported_at_quote_time": "仅为供应商在报价时点报告的状态",
    "vendor_timestamped_quote": "保留供应商原报价时刻",
}
_PURPOSE_LABELS = {
    "close_snapshot_simulation": "收盘快照模拟核对",
    "historical_liquidity": "历史成交与流动性核对",
    "industry_exposure": "行业暴露核对",
    "scenario_exit_pressure": "情景退出压力核对",
    "valuation": "持仓估值核对",
}
_COVERAGE_BASIS_LABELS = {
    "positions_with_source_bars": "有来源行情记录的持仓覆盖",
    "reported_sessions": "来源明确报告的交易日数量",
}
_MISSING = "未知"

_CLOCK_PROOF_LABELS = {
    "policy_bounded_date_snapshot": "当日有界日期快照",
    "policy_bounded_timestamp_snapshot": "保留原观测时刻的快照",
    "policy_bounded_close_snapshot_state": "收盘报价时点的供应商状态",
    "policy_bounded_disclosed_report": "披露报告的有限模拟核对",
}


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one JSON object to string-keyed fields."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        return None
    return cast(Mapping[str, object], value)


def portfolio_pressure_task_outcome(payload: object) -> str:
    """Report command completion only when pressure evidence was persisted."""

    report = _mapping(payload) if isinstance(payload, dict) else None
    if report is None:
        return "blocked"
    data_value = report.get("data")
    data = _mapping(data_value) if isinstance(data_value, dict) else None
    if data is not None:
        report = data
    checks = report.get("checks")
    if not isinstance(checks, list):
        return "blocked"
    pressure_checks: list[Mapping[str, object]] = []
    for item in checks:
        check = _mapping(item) if isinstance(item, dict) else None
        if check is not None and check.get("dimension") == "exit_pressure":
            pressure_checks.append(check)
    if len(pressure_checks) != 1:
        return "blocked"
    details_value = pressure_checks[0].get("details")
    details = _mapping(details_value) if isinstance(details_value, dict) else None
    return (
        "success"
        if details is not None and details.get("run_evidence_persisted") is True
        else "blocked"
    )


def _display(value: object, *, missing: str = _MISSING) -> str:
    """Render a JSON scalar or a bounded missing-value label."""

    if value is None:
        return missing
    if type(value) is bool:
        return "是" if value else "否"
    if type(value) is str:
        text = value.strip()
        return text or missing
    if type(value) in {bool, int, float}:
        return str(value)
    return missing


def _string_values(value: object) -> tuple[str, ...]:
    """Retain nonblank strings from a JSON list without stringifying objects."""

    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if type(item) is str and item.strip())


def _safe_detail_text(value: object) -> str:
    """Show scalar explanation values while hiding implementation-shaped fields."""

    details = _mapping(value)
    if details is None:
        return ""
    rows: list[str] = []
    for key, item in details.items():
        normalized = key.strip().lower()
        label = _DETAIL_LABELS.get(normalized)
        if not label:
            continue
        display_value = _display(item, missing="")
        if not display_value:
            continue
        rows.append(f"{label}：{display_value}")
        if len(rows) == 8:
            break
    return "；".join(rows)


def _check_lines(value: object) -> tuple[str, ...]:
    """Render every constraint with status, explanation, reasons, and safe details."""

    if not isinstance(value, list):
        return ()
    rows: list[str] = []
    for item in value:
        check = _mapping(item)
        if check is None:
            continue
        raw_dimension = _display(check.get("dimension"))
        dimension = _DIMENSION_LABELS.get(
            raw_dimension,
            raw_dimension if "_" not in raw_dimension else "风险约束",
        )
        outcome = _display(check.get("status"), missing="unknown")
        outcome_label = _CHECK_STATUS_LABELS.get(outcome, _CHECK_STATUS_LABELS["unknown"])
        summary = _display(check.get("summary"), missing="未提供检查说明")
        details = _safe_detail_text(check.get("details"))
        line = f"{dimension}：{outcome_label}；{summary}"
        if details:
            line = f"{line}；补充：{details}"
        rows.append(line)
    return tuple(rows)


def _clock_proof_text(source: Mapping[str, object]) -> str:
    """Distinguish simulation acceptance from unknown supplier clock guarantees."""

    proof = _mapping(source.get("clock_evidence_proof"))
    if proof is None:
        return ""
    mode = _display(proof.get("clock_evidence_mode"))
    label = _CLOCK_PROOF_LABELS.get(mode)
    if proof.get("scope") != "simulation_only" or label is None:
        return "\n模拟接纳依据：未知"
    text = (
        f"\n模拟接纳依据：{label}；"
        f"已证实可用：{_display(proof.get('proven_available_at'))}；"
        f"本次模拟接纳至：{_display(proof.get('policy_acceptance_deadline'))}。"
        "该期限来自模拟策略，不补写供应商发布或失效时间。"
    )
    if mode == "policy_bounded_disclosed_report":
        text += (
            f"披露持仓截至：{_display(proof.get('report_period_end'))}；"
            f"发布日期：{_display(proof.get('publication_on'))}；按披露期末计算报告年龄。"
        )
    if mode == "policy_bounded_close_snapshot_state":
        text += "交易所全日停牌状态仍未知；此处仅说明报价时点的供应商状态。"
    return text


def _source_lines(value: object) -> tuple[str, ...]:
    """Render source identity, original clocks, coverage, and use restrictions."""

    if not isinstance(value, list):
        return ()
    rows: list[str] = []
    for item in value:
        source = _mapping(item)
        if source is None:
            continue
        observation = _display(source.get("observed_at"))
        observed_on = _display(source.get("observed_on"))
        if observation == _MISSING and observed_on != _MISSING:
            observation = observed_on
        restriction_labels = tuple(
            _RESTRICTION_LABELS.get(item, item.replace("_", " "))
            for item in _string_values(source.get("restrictions"))
        )
        restrictions = "、".join(restriction_labels) or "无额外限制"
        raw_purpose = _display(source.get("purpose"))
        purpose = _PURPOSE_LABELS.get(
            raw_purpose,
            raw_purpose.replace("_", " ") if raw_purpose != _MISSING else _MISSING,
        )
        raw_coverage_basis = _display(source.get("coverage_basis"))
        coverage_basis = _COVERAGE_BASIS_LABELS.get(
            raw_coverage_basis,
            raw_coverage_basis.replace("_", " ") if raw_coverage_basis != _MISSING else _MISSING,
        )
        row = (
            f"来源用途：{purpose}\n"
            f"观测：{observation}；精度："
            f"{_PRECISION_LABELS.get(_display(source.get('observation_precision')), '未知')}；"
            f"来源可用：{_display(source.get('available_at'))}；系统知悉：{_display(source.get('known_at'))}\n"
            f"截止：{_display(source.get('cutoff'))}；来源有效至：{_display(source.get('valid_until'))}；"
            f"覆盖：{_display(source.get('coverage_fraction'))}（{coverage_basis}）；"
            f"限制：{restrictions}；决策禁用：{_display(source.get('must_not_use_for_decision'))}"
            f"{_clock_proof_text(source)}"
        )
        rows.append(row)
    return tuple(rows)


def project_portfolio_risk_result(
    payload: object,
    *,
    http_status: int,
) -> dict[str, object] | None:
    """Render the actual report details; leave bounded HTTP errors to the base renderer."""

    report = _mapping(payload)
    if report is None or http_status != 200:
        return None

    raw_outcome = _display(report.get("outcome"), missing="unknown")
    outcome = raw_outcome if raw_outcome in _OUTCOME_LABELS else "unknown"
    readonly_boundary = (
        report.get("scope") == "simulation_only" and report.get("must_not_execute") is True
    )
    outcome_label = _OUTCOME_LABELS[outcome]
    if not readonly_boundary:
        outcome_label = "风险边界未知；不得据此执行"

    checks = _check_lines(report.get("checks"))
    sources = _source_lines(report.get("sources"))
    fields: list[dict[str, str]] = [
        {"key": "outcome", "label": "风险结论", "value": outcome_label, "presentation": "metadata"},
        {
            "key": "account_id",
            "label": "模拟账户编号",
            "value": _display(report.get("account_id")),
            "presentation": "metadata",
        },
        {
            "key": "as_of",
            "label": "核对时点",
            "value": _display(report.get("as_of")),
            "presentation": "metadata",
        },
        {
            "key": "policy_version",
            "label": "风险规则版本",
            "value": _display(report.get("policy_version")),
            "presentation": "metadata",
        },
        {
            "key": "execution_boundary",
            "label": "使用边界",
            "value": "只读模拟风险结果；不是交易许可，不会自动执行。",
            "presentation": "metadata",
        },
        {
            "key": "checks",
            "label": f"约束检查（{len(checks)} 项）",
            "value": "\n".join(checks) if checks else "未返回约束明细；不能据此判定通过。",
            "presentation": "multiline",
        },
        {
            "key": "sources",
            "label": f"数据来源与时点（{len(sources)} 项）",
            "value": "\n\n".join(sources) if sources else "未返回来源记录；数据覆盖与时点未知。",
            "presentation": "multiline",
        },
    ]
    summary = (
        f"模拟账户风险核对：{outcome_label}；{len(checks)} 项约束，{len(sources)} 项来源。"
        "结果只读且仅用于模拟，不代表交易许可。"
    )
    first_constraint = next(
        (line for line in checks if "阻断" in line or "未知" in line or "部分可用" in line),
        "",
    )
    return {
        "kind": "detail",
        "title": "模拟账户风险核对",
        "status": outcome_label,
        "outcome": outcome,
        "scope": "simulation_only" if readonly_boundary else "unknown",
        "must_not_execute": True,
        "fields": fields,
        "nested": [],
        "business_summary": summary,
        "blocking_reason": first_constraint if outcome in {"blocked", "partial", "unknown"} else "",
        "next_steps": [],
        "debug_hidden_fields": ["raw_payload", "internal_error", "api_path"],
    }


__all__ = ["portfolio_pressure_task_outcome", "project_portfolio_risk_result"]
