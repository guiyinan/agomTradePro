"""Operator-oriented TUI aggregation services."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.account.application.query_services import get_account_diagnostic_summary
from apps.agent_runtime.application.repository_provider import get_operator_repository
from apps.ai_capability.application.query_services import get_ai_capability_surface_status_payload
from apps.ai_provider.application.use_cases import (
    GetOverallStatsUseCase,
    GetUserFallbackQuotaUseCase,
    ListProvidersUseCase,
    ListUsageLogsUseCase,
)
from apps.alpha.application.repository_provider import (
    get_qlib_model_registry_repository,
    inspect_latest_trade_date,
)
from apps.audit.domain.entities import mask_sensitive_text
from apps.config_center.application.query_services import has_qlib_training_runs
from apps.data_center.application.interface_services import (
    get_decision_data_readiness_payload,
    load_market_thermometer_payload,
)
from apps.data_center.application.query_services import get_active_stock_fact_coverage_payload
from apps.decision_rhythm.application.today_queue import TodayDecisionQueueQueryService
from apps.operational_readiness.application.monitor_service import (
    get_personal_readiness_monitor_summary,
)
from apps.policy.application.query_services import get_policy_status_payload
from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.regime.application.interface_services import get_regime_current_payload
from apps.signal.application.query_services import get_signal_diagnostic_summary
from apps.terminal.application.query_services import get_terminal_surface_status_payload
from core.integration.runtime_settings import get_runtime_qlib_config

SEVERITY_ORDER = {
    "blocked": 0,
    "warning": 1,
    "notice": 2,
    "ok": 3,
}

DATA_TASK_DOMAINS = {"runtime", "data-center", "agent-runtime"}
AI_CONFIG_DOMAINS = {"ai-provider", "config-center", "ai-capability"}
OPERATOR_HOME_CACHE_TTL_SECONDS = 15
OPERATOR_HOME_STALE_TTL_SECONDS = 120
OPERATOR_HOME_SECTION_KEYS = (
    "decision_queue",
    "market_context",
    "account_signal_summary",
    "system_exception_summary",
    "data_task_summary",
    "ai_config_summary",
)


def build_operator_home_payload(*, user: Any) -> dict[str, Any]:
    """Return the unified TUI home payload for one operator."""

    cache_key = _operator_home_cache_key(user=user)

    def build() -> dict[str, Any]:
        payload = {
            section_key: build_operator_home_section_payload(user=user, section_key=section_key)
            for section_key in OPERATOR_HOME_SECTION_KEYS[:3]
        }
        preview_rows = _operator_home_preview_rows(
            user=user,
            market_context=payload["market_context"],
        )
        payload.update(
            {
                "system_exception_summary": _section_payload(preview_rows["runtime"]),
                "data_task_summary": _section_payload(preview_rows["data-center"]),
                "ai_config_summary": _section_payload(preview_rows["ai-provider"]),
            }
        )
        navigation_rows = [row for rows in preview_rows.values() for row in rows]
        return {
            "status": _overall_status(
                [
                    list(payload[section_key].get("rows") or [])
                    for section_key in OPERATOR_HOME_SECTION_KEYS
                ]
            ),
            "navigation_badges": _navigation_badges(navigation_rows),
            **payload,
        }

    return _cached_operator_payload(cache_key=cache_key, builder=build)


def _operator_home_preview_rows(
    *,
    user: Any,
    market_context: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Return lightweight home summaries; full governance remains a drilldown."""

    terminal_surface = get_terminal_surface_status_payload()
    ai_surface = get_ai_capability_surface_status_payload()
    market_rows = list(market_context.get("rows") or [])
    market_severity = _highest_severity([str(row.get("severity") or "ok") for row in market_rows])
    return {
        "runtime": [
            _governance_row(
                severity=_surface_severity(terminal_surface),
                domain="runtime",
                title="Terminal/TUI 运行面状态",
                status=str(terminal_surface.get("status") or "unknown"),
                blocking_reason=_surface_reason(
                    terminal_surface,
                    "打开治理队列查看完整 readiness 详情。",
                ),
                next_action="查看完整运行时治理",
                target_screen="api-library.runtime",
                target_action_key="operator.governance.runtime_summary",
                observed_at=timezone.now(),
            )
        ],
        "data-center": [
            _governance_row(
                severity=market_severity,
                domain="data-center",
                title="数据与市场上下文预览",
                status=str(market_context.get("status") or "unknown"),
                blocking_reason="打开治理队列查看新鲜度、覆盖率与温度计详情。",
                next_action="查看完整数据治理",
                target_screen="api-library.data-center",
                target_action_key="operator.governance.data_center_summary",
                observed_at=timezone.now(),
            )
        ],
        "ai-provider": [
            _governance_row(
                severity=_surface_severity(ai_surface),
                domain="ai-provider",
                title="AI 与能力目录预览",
                status=str(ai_surface.get("status") or "unknown"),
                blocking_reason=_surface_reason(
                    ai_surface,
                    "打开治理队列查看 Provider、配额与能力目录详情。",
                ),
                next_action="查看完整 AI 治理",
                target_screen="ai-ops.providers",
                target_action_key="operator.governance.ai_provider_summary",
                observed_at=timezone.now(),
            )
        ],
    }


def build_operator_home_section_payload(*, user: Any, section_key: str) -> dict[str, Any]:
    """Return one operator home section payload."""

    normalized_key = str(section_key or "").strip()
    if normalized_key not in OPERATOR_HOME_SECTION_KEYS:
        raise KeyError(normalized_key)

    cache_key = _operator_home_section_cache_key(user=user, section_key=normalized_key)
    return _cached_operator_payload(
        cache_key=cache_key,
        builder=lambda: _section_payload(
            _operator_home_section_rows(user=user, section_key=normalized_key)
        ),
    )


def build_operator_governance_queue_payload(
    *,
    user: Any,
    domain: str = "",
) -> dict[str, Any]:
    """Return sorted governance exceptions for TUI drilldown."""

    cache_key = _operator_governance_cache_key(user=user, domain=domain)

    def build() -> dict[str, Any]:
        rows = [
            *_runtime_governance_rows(),
            *_data_center_governance_rows(),
            *_ai_provider_governance_rows(user=user),
            *_agent_runtime_governance_rows(),
            *_account_settings_governance_rows(),
            *_config_center_governance_rows(user=user),
        ]
        filtered_domain = str(domain or "").strip().lower()
        if filtered_domain:
            rows = [row for row in rows if str(row["domain"]).lower() == filtered_domain]
        if not rows:
            rows = [
                _governance_row(
                    severity="ok",
                    domain=filtered_domain or "runtime",
                    title="当前没有待处理治理异常。",
                    status="ok",
                    blocking_reason="",
                    next_action="继续当前工作区",
                    target_screen=_domain_screen(filtered_domain or "runtime"),
                    target_action_key=_domain_action(filtered_domain or "runtime"),
                    observed_at=timezone.now(),
                )
            ]
        rows.sort(key=_governance_sort_key)
        return {
            "status": rows[0]["severity"] if rows else "ok",
            "items": rows,
            "total": len(rows),
            "summary": dict(Counter(row["severity"] for row in rows)),
        }

    return _cached_operator_payload(cache_key=cache_key, builder=build)


def _cached_operator_payload(
    *,
    cache_key: str,
    builder: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return a fresh payload, or a stale snapshot while another worker rebuilds it."""

    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached
    stale_key = f"{cache_key}:stale"
    stale = cache.get(stale_key)
    lock_key = f"{cache_key}:refresh-lock"
    acquired = bool(cache.add(lock_key, 1, timeout=30))
    if not acquired and isinstance(stale, dict):
        return stale
    try:
        payload = builder()
        cache.set(cache_key, payload, OPERATOR_HOME_CACHE_TTL_SECONDS)
        cache.set(stale_key, payload, OPERATOR_HOME_STALE_TTL_SECONDS)
        return payload
    finally:
        if acquired:
            cache.delete(lock_key)


def _navigation_badges(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build compact navigation counts without exposing full governance rows."""

    counts_by_screen: dict[str, dict[str, int]] = {}
    for row in rows:
        severity = str(row.get("severity") or "").strip().lower()
        screen_key = str(row.get("target_screen") or "").strip()
        if severity not in {"blocked", "warning"} or not screen_key:
            continue
        counts = counts_by_screen.setdefault(
            screen_key,
            {"blocked_count": 0, "warning_count": 0},
        )
        counts[f"{severity}_count"] += 1
    return {"counts_by_screen": counts_by_screen}


def _operator_home_section_rows(*, user: Any, section_key: str) -> list[dict[str, Any]]:
    if section_key == "decision_queue":
        return _decision_queue_rows()
    if section_key == "market_context":
        return _market_context_rows()
    if section_key == "account_signal_summary":
        return _account_signal_rows()

    governance_rows = list(build_operator_governance_queue_payload(user=user).get("items") or [])
    if section_key == "system_exception_summary":
        return _section_rows(
            governance_rows,
            domains=None,
            fallback_title="当前没有系统治理阻断项。",
            fallback_screen="api-library.runtime",
            fallback_action_key="operator.governance.runtime_summary",
        )
    if section_key == "data_task_summary":
        return _section_rows(
            governance_rows,
            domains=DATA_TASK_DOMAINS,
            fallback_title="数据、任务与运行时链路当前正常。",
            fallback_screen="api-library.runtime",
            fallback_action_key="operator.governance.runtime_summary",
        )
    if section_key == "ai_config_summary":
        return _section_rows(
            governance_rows,
            domains=AI_CONFIG_DOMAINS,
            fallback_title="AI、MCP 与配置链路当前正常。",
            fallback_screen="ai-ops.providers",
            fallback_action_key="operator.governance.ai_provider_summary",
        )
    raise KeyError(section_key)


def _operator_home_cache_key(*, user: Any) -> str:
    return f"terminal:tui:operator-home:v1:user:{_operator_cache_user_fragment(user)}"


def _operator_home_section_cache_key(*, user: Any, section_key: str) -> str:
    return (
        "terminal:tui:operator-home-section:v1:"
        f"user:{_operator_cache_user_fragment(user)}:section:{section_key}"
    )


def _operator_governance_cache_key(*, user: Any, domain: str) -> str:
    normalized_domain = str(domain or "").strip().lower() or "all"
    return (
        "terminal:tui:operator-governance:v1:"
        f"user:{_operator_cache_user_fragment(user)}:domain:{normalized_domain}"
    )


def _operator_cache_user_fragment(user: Any) -> str:
    user_id = getattr(user, "pk", None)
    return str(user_id if user_id is not None else "anon")


def _decision_queue_rows() -> list[dict[str, Any]]:
    result = TodayDecisionQueueQueryService().execute(
        account_id="default",
        include_system_health=False,
    )
    rows = [dict(item.to_dict()) for item in result.items]
    if rows:
        for row in rows:
            row["severity"] = _decision_queue_severity(str(row.get("status") or ""))
        return rows
    return [
        {
            "priority": 0,
            "status": "CLEAR",
            "type": "decision_queue",
            "title": "今日没有待补齐的投研待办。",
            "next_action": "继续今日决策流程",
            "security_code": "",
            "target_screen": "macro-regime.overview",
            "severity": "ok",
        }
    ]


def _market_context_rows() -> list[dict[str, Any]]:
    rows = [
        _regime_market_row(),
        _policy_market_row(),
        _pulse_market_row(),
        _decision_data_market_row(),
    ]
    return rows


def _regime_market_row() -> dict[str, Any]:
    payload = get_regime_current_payload(as_of_date=date.today())
    data = dict(payload.get("data") or {})
    warnings = list(data.get("warnings") or [])
    regime = str(data.get("dominant_regime") or "UNKNOWN")
    confidence = float(data.get("confidence") or 0.0)
    contract = dict(data.get("contract") or {})
    is_stale = bool(data.get("is_stale") or contract.get("is_stale"))
    must_not_use = bool(
        data.get("must_not_use_for_decision") or contract.get("must_not_use_for_decision")
    )
    blocked_reason = str(data.get("blocked_reason") or contract.get("blocked_reason") or "").strip()
    severity = "ok"
    if regime == "UNKNOWN" or must_not_use:
        severity = "blocked"
    elif warnings or confidence < 0.5 or bool(data.get("is_fallback")):
        severity = "warning"
    freshness = "已过期" if is_stale else "新鲜"
    reliability = "不可用于决策" if must_not_use else ("降级" if severity == "warning" else "可靠")
    summary = (
        blocked_reason
        or (str(warnings[0]) if warnings else "")
        or (f"置信度 {confidence:.2f}" if confidence else "当前环境不可用")
    )
    return {
        "area": "Regime",
        "status": regime,
        "summary": summary,
        "freshness": freshness,
        "reliability": reliability,
        "must_not_use_for_decision": must_not_use,
        "blocking_reason": blocked_reason,
        "observed_at": _iso(data.get("observed_at")),
        "next_action": "查看环境判断",
        "target_screen": "macro-regime.overview",
        "severity": severity,
    }


def _policy_market_row() -> dict[str, Any]:
    payload = get_policy_status_payload(as_of_date=date.today())
    level = str(payload.get("current_level") or "UNKNOWN")
    intervention = bool(payload.get("is_intervention_active"))
    severity = "warning" if intervention else ("blocked" if level == "UNKNOWN" else "ok")
    return {
        "area": "Policy",
        "status": level,
        "summary": "当前存在政策干预" if intervention else "政策状态可用",
        "freshness": "新鲜",
        "reliability": "不可用于决策" if level == "UNKNOWN" else "可靠",
        "observed_at": _iso(payload.get("as_of_date")),
        "next_action": "查看政策档位",
        "target_screen": "macro-regime.policy",
        "severity": severity,
    }


def _pulse_market_row() -> dict[str, Any]:
    snapshot = GetLatestPulseUseCase().execute(as_of_date=date.today())
    if snapshot is None:
        return {
            "area": "Pulse",
            "status": "NO_DATA",
            "summary": "当前没有可用脉搏快照。",
            "freshness": "无数据",
            "reliability": "不可用于决策",
            "observed_at": "",
            "next_action": "查看脉搏层",
            "target_screen": "macro-regime.pulse",
            "severity": "blocked",
        }
    severity = "warning" if snapshot.transition_warning or not snapshot.is_reliable else "ok"
    return {
        "area": "Pulse",
        "status": str(snapshot.regime_strength or "unknown").upper(),
        "summary": "存在转折预警" if snapshot.transition_warning else "脉搏层正常",
        "freshness": "新鲜",
        "reliability": "可靠" if snapshot.is_reliable else "降级",
        "observed_at": _iso(snapshot.observed_at),
        "next_action": "查看脉搏层",
        "target_screen": "macro-regime.pulse",
        "severity": severity,
    }


def _decision_data_market_row() -> dict[str, Any]:
    payload = get_decision_data_readiness_payload()
    blocked = bool(payload.get("must_not_use_for_decision"))
    blocked_reasons = list(payload.get("blocked_reasons") or [])
    thermometer = dict(payload.get("market_thermometer") or {})
    return {
        "area": "Decision Data",
        "status": str(payload.get("status") or "unknown").upper(),
        "summary": blocked_reasons[0] if blocked_reasons else "决策数据链路可用",
        "freshness": str(payload.get("freshness_status") or "待确认"),
        "reliability": "不可用于决策" if blocked else "可靠",
        "observed_at": _iso(
            thermometer.get("as_of_date")
            or thermometer.get("snapshot_date")
            or thermometer.get("observed_at")
        ),
        "next_action": "查看数据中心",
        "target_screen": "api-library.data-center",
        "severity": "blocked" if blocked else "ok",
    }


def _account_signal_rows() -> list[dict[str, Any]]:
    account_summary = get_account_diagnostic_summary()
    signal_summary = get_signal_diagnostic_summary()
    open_position_count = int(account_summary.get("open_position_count") or 0)
    portfolio_count = int(account_summary.get("portfolio_count") or 0)
    active_signal_count = int(signal_summary.get("active_count") or 0)
    invalidated_count = int(signal_summary.get("invalidated_count") or 0)

    return [
        {
            "area": "Accounts",
            "status": "READY" if portfolio_count > 0 else "SETUP",
            "value": portfolio_count,
            "summary": f"活跃持仓 {open_position_count} 笔",
            "next_action": "查看账户与持仓",
            "target_screen": "execution.accounts",
            "severity": "warning" if portfolio_count == 0 else "ok",
        },
        {
            "area": "Signals",
            "status": "ACTIVE" if active_signal_count > 0 else "EMPTY",
            "value": active_signal_count,
            "summary": f"已失效 {invalidated_count} 条",
            "next_action": "查看信号工作区",
            "target_screen": "research.alpha",
            "severity": "notice" if active_signal_count == 0 else "ok",
        },
    ]


def _runtime_governance_rows() -> list[dict[str, Any]]:
    summary = get_personal_readiness_monitor_summary(strict_runtime=False)
    terminal_surface = get_terminal_surface_status_payload()
    rows = [
        _governance_row(
            severity=_monitor_severity(summary),
            domain="runtime",
            title=str(((summary.get("daily_state") or {}).get("title")) or "Readiness monitor"),
            status=str(summary.get("status") or "unknown"),
            blocking_reason=_first_text(
                (summary.get("blocking_issues") or []),
                (summary.get("daily_state") or {}).get("message"),
                (summary.get("monitor_gate") or {}).get("reason"),
            ),
            next_action="查看运行时与 readiness",
            target_screen="api-library.runtime",
            target_action_key="auto.api.get.api.ready",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity=_surface_severity(terminal_surface),
            domain="runtime",
            title="Terminal/TUI 运行面状态",
            status=str(terminal_surface.get("status") or "unknown"),
            blocking_reason=_surface_reason(terminal_surface, "operator surface incomplete"),
            next_action="查看系统运行状态",
            target_screen="api-library.runtime",
            target_action_key="auto.api.get.api.system",
            observed_at=timezone.now(),
        ),
    ]
    return rows


def _data_center_governance_rows() -> list[dict[str, Any]]:
    coverage = get_active_stock_fact_coverage_payload()
    readiness = get_decision_data_readiness_payload()
    thermometer = load_market_thermometer_payload(user_id=None, use_personal_thresholds=False)
    blocked_reasons = list(readiness.get("blocked_reasons") or [])
    thermometer_status = str(thermometer.get("status") or "unknown").lower()
    thermometer_blocked = bool(thermometer.get("must_not_use_for_decision"))
    thermometer_reason = str(
        thermometer.get("blocked_reason")
        or thermometer.get("status_note")
        or thermometer.get("warning")
        or ""
    )

    rows = [
        _governance_row(
            severity="blocked" if readiness.get("must_not_use_for_decision") else "ok",
            domain="data-center",
            title="决策数据新鲜度",
            status=str(readiness.get("status") or "unknown"),
            blocking_reason=_first_text(blocked_reasons, "行情与温度计数据可用于决策。"),
            next_action="查看数据中心异常",
            target_screen="api-library.data-center",
            target_action_key="operator.governance.data_center_summary",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity=_coverage_severity(coverage),
            domain="data-center",
            title="生产覆盖与数据治理",
            status=str(coverage.get("status") or "unknown"),
            blocking_reason=_coverage_reason(coverage),
            next_action="查看数据中心异常",
            target_screen="api-library.data-center",
            target_action_key="operator.governance.data_center_summary",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity=(
                "warning"
                if thermometer_blocked or thermometer_status not in {"ok", "success"}
                else "ok"
            ),
            domain="data-center",
            title="市场温度计状态",
            status=str(thermometer.get("status") or "unknown"),
            blocking_reason=thermometer_reason,
            next_action="查看市场温度计",
            target_screen="api-library.data-center",
            target_action_key="auto.api.get.api.data-center.providers",
            observed_at=timezone.now(),
        ),
    ]
    return rows


def _ai_provider_governance_rows(*, user: Any) -> list[dict[str, Any]]:
    providers = ListProvidersUseCase().execute(include_inactive=False, scope="system")
    overall = GetOverallStatsUseCase().execute()
    recent_failures = ListUsageLogsUseCase().execute(
        limit=10,
        status="error",
        provider_scope="system",
    )
    ai_surface = get_ai_capability_surface_status_payload()
    fallback_quota = None
    if getattr(user, "is_authenticated", False):
        fallback_quota = GetUserFallbackQuotaUseCase().execute(user=user)

    active_provider_count = len([item for item in providers if item.is_active])
    failed_provider_names = sorted(
        {
            str(getattr(item, "provider_name", "") or "")
            for item in recent_failures
            if str(getattr(item, "provider_name", "") or "").strip()
        }
    )
    quota_reason = ""
    quota_severity = "ok"
    if fallback_quota is not None and bool(fallback_quota.is_active):
        daily_remaining = fallback_quota.daily_remaining
        monthly_remaining = fallback_quota.monthly_remaining
        if daily_remaining == 0 or monthly_remaining == 0:
            quota_severity = "warning"
            quota_reason = "系统兜底额度已耗尽。"
    elif fallback_quota is not None:
        quota_severity = "notice"
        quota_reason = "当前用户未启用系统兜底额度。"

    return [
        _governance_row(
            severity="blocked" if active_provider_count == 0 else "ok",
            domain="ai-provider",
            title="AI 服务商可用性",
            status=f"{active_provider_count}/{overall.total_providers}",
            blocking_reason="当前没有可用系统 Provider。" if active_provider_count == 0 else "",
            next_action="查看 AI 服务商",
            target_screen="ai-ops.providers",
            target_action_key="auto.api.get.api.prompt.chat.providers",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity="warning" if recent_failures else "ok",
            domain="ai-provider",
            title="AI 调用失败摘要",
            status=str(len(recent_failures)),
            blocking_reason=(
                f"最近失败 Provider: {', '.join(failed_provider_names[:3])}"
                if failed_provider_names
                else ""
            ),
            next_action="查看 AI 日志",
            target_screen="ai-ops.providers",
            target_action_key="auto.api.get.api.ai.me.logs",
            observed_at=_latest_created_at(recent_failures),
        ),
        _governance_row(
            severity=quota_severity,
            domain="ai-provider",
            title="AI 配额与兜底额度",
            status="quota",
            blocking_reason=quota_reason,
            next_action="查看 AI 服务商配置",
            target_screen="ai-ops.providers",
            target_action_key="auto.api.get.api.ai.me.providers",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity=_surface_severity(ai_surface),
            domain="ai-capability",
            title="MCP / AI 能力目录状态",
            status=str(ai_surface.get("status") or "unknown"),
            blocking_reason=_surface_reason(ai_surface, "AI capability surface incomplete"),
            next_action="查看 AI 服务商",
            target_screen="ai-ops.providers",
            target_action_key="auto.api.get.api.prompt.chat.providers",
            observed_at=timezone.now(),
        ),
    ]


def _agent_runtime_governance_rows() -> list[dict[str, Any]]:
    summary = get_operator_repository().get_summary()
    needs_attention = int(summary.get("needs_attention_count") or 0)
    failed = int((summary.get("task_counts") or {}).get("failed", 0) or 0)
    active = int(summary.get("total_tasks") or 0)
    severity = "blocked" if failed > 0 else ("warning" if needs_attention > 0 else "ok")
    reason = ""
    if failed > 0:
        reason = f"失败任务 {failed} 条。"
    elif needs_attention > 0:
        reason = f"待人工处理任务 {needs_attention} 条。"
    return [
        _governance_row(
            severity=severity,
            domain="agent-runtime",
            title="Agent 运行时队列与阻断项",
            status=f"tasks={active}",
            blocking_reason=reason,
            next_action="查看待处理任务",
            target_screen="ai-ops.agent-runtime",
            target_action_key=(
                "agent_runtime.needs_attention"
                if needs_attention > 0
                else "auto.api.get.api.agent-runtime.tasks"
            ),
            observed_at=timezone.now(),
        )
    ]


def _account_settings_governance_rows() -> list[dict[str, Any]]:
    summary = get_account_diagnostic_summary()
    missing = []
    if int(summary.get("active_currency_count") or 0) == 0:
        missing.append("缺少启用币种")
    if int(summary.get("asset_category_count") or 0) == 0:
        missing.append("缺少资产分类")
    if int(summary.get("portfolio_count") or 0) == 0:
        missing.append("没有组合")
    severity = "blocked" if missing[:2] else ("warning" if missing else "ok")
    return [
        _governance_row(
            severity=severity,
            domain="account-settings",
            title="执行参数与账户前置条件",
            status="ready" if not missing else "attention",
            blocking_reason="；".join(missing),
            next_action="查看账户参数",
            target_screen="execution.account-settings",
            target_action_key="auto.api.get.api.account.categories",
            observed_at=timezone.now(),
        )
    ]


def _config_center_governance_rows(*, user: Any) -> list[dict[str, Any]]:
    if not _is_admin_user(user):
        return []
    runtime = dict(get_runtime_qlib_config() or {})
    active_model = get_qlib_model_registry_repository().get_active_model()
    lag_days = None
    provider_uri = runtime.get("provider_uri")
    if runtime.get("enabled") and provider_uri:
        try:
            latest_local_trade_date = inspect_latest_trade_date(str(provider_uri))
            if latest_local_trade_date is not None:
                lag_days = max((timezone.localdate() - latest_local_trade_date).days, 0)
        except Exception:
            lag_days = None
    lag_warning = isinstance(lag_days, int) and lag_days > 3
    has_training_runs = has_qlib_training_runs()
    enabled = bool(runtime.get("enabled"))
    rows = [
        _governance_row(
            severity=(
                "blocked"
                if enabled and active_model is None
                else ("notice" if not enabled else "ok")
            ),
            domain="config-center",
            title="Qlib Runtime 与当前模型",
            status="enabled" if enabled else "disabled",
            blocking_reason=(
                "Qlib Runtime 已启用但没有活动模型。"
                if enabled and active_model is None
                else ("当前未启用 Qlib Runtime。" if not enabled else "")
            ),
            next_action="查看 Qlib 运行配置",
            target_screen="api-library.config-center",
            target_action_key="config_center.qlib_runtime",
            observed_at=timezone.now(),
        ),
        _governance_row(
            severity="warning" if lag_warning else ("notice" if not has_training_runs else "ok"),
            domain="config-center",
            title="训练记录与本地数据滞后",
            status="lag" if lag_warning else "ok",
            blocking_reason=(
                f"本地 Qlib 数据滞后 {lag_days} 天。"
                if lag_warning
                else ("当前没有训练运行记录。" if not has_training_runs else "")
            ),
            next_action="查看训练运行记录",
            target_screen="api-library.config-center",
            target_action_key="config_center.training_runs",
            observed_at=timezone.now(),
        ),
    ]
    return rows


def _section_rows(
    rows: list[dict[str, Any]],
    *,
    domains: set[str] | None,
    fallback_title: str,
    fallback_screen: str,
    fallback_action_key: str,
) -> list[dict[str, Any]]:
    if domains is None:
        selected = [row for row in rows if row["severity"] != "ok"][:6]
    else:
        selected = [
            row for row in rows if str(row["domain"]).lower() in domains and row["severity"] != "ok"
        ][:6]
    if selected:
        return selected
    return [
        _governance_row(
            severity="ok",
            domain=(next(iter(domains)) if domains else "runtime"),
            title=fallback_title,
            status="ok",
            blocking_reason="",
            next_action="继续处理",
            target_screen=fallback_screen,
            target_action_key=fallback_action_key,
            observed_at=timezone.now(),
        )
    ]


def _section_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    severities = [str(row.get("severity") or "ok").lower() for row in rows]
    blocked_count = sum(1 for severity in severities if severity == "blocked")
    warning_count = sum(1 for severity in severities if severity == "warning")
    return {
        "rows": rows,
        "total": len(rows),
        "status": _highest_severity(severities),
        "badge": {
            "blocked_count": blocked_count,
            "warning_count": warning_count,
        },
    }


def _governance_row(
    *,
    severity: str,
    domain: str,
    title: str,
    status: str,
    blocking_reason: str,
    next_action: str,
    target_screen: str,
    target_action_key: str,
    observed_at: Any,
) -> dict[str, Any]:
    return {
        "severity": _normalize_severity(severity),
        "domain": str(domain or "").strip() or "runtime",
        "title": str(title or "").strip() or "未命名异常",
        "status": str(status or "").strip() or "unknown",
        "blocking_reason": str(blocking_reason or "").strip(),
        "next_action": str(next_action or "").strip(),
        "target_screen": str(target_screen or "").strip(),
        "target_action_key": str(target_action_key or "").strip(),
        "observed_at": _iso(observed_at),
    }


def _governance_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    severity = _normalize_severity(str(row.get("severity") or "ok"))
    observed_at = str(row.get("observed_at") or "")
    return (SEVERITY_ORDER[severity], _descending_iso(observed_at))


def _descending_iso(value: str) -> str:
    return "".join(chr(255 - ord(ch)) for ch in value)


def _decision_queue_severity(status: str) -> str:
    normalized = str(status or "").upper()
    if normalized.startswith(("CONFLICT", "ERROR", "BLOCKED", "FAIL")):
        return "blocked"
    if normalized.startswith(("DEGRADED", "PENDING", "WARN", "WAIT")):
        return "warning"
    if normalized.startswith(("CLEAR", "DONE", "SUCCESS")):
        return "ok"
    return "notice"


def _monitor_severity(summary: dict[str, Any]) -> str:
    daily_state = dict(summary.get("daily_state") or {})
    return _map_external_severity(str(daily_state.get("severity") or ""))


def _map_external_severity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"danger", "blocked", "error"}:
        return "blocked"
    if normalized in {"warn", "warning"}:
        return "warning"
    if normalized in {"neutral", "notice", "info"}:
        return "notice"
    return "ok"


def _surface_severity(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "blocked", "unavailable"}:
        return "blocked"
    if status in {"incomplete", "warning", "attention", "empty"}:
        return "warning"
    if status in {"loading", "unknown"}:
        return "notice"
    return "ok"


def _surface_reason(payload: dict[str, Any], fallback: str) -> str:
    return _first_text(
        payload.get("error"),
        payload.get("message"),
        payload.get("detail"),
        fallback if _surface_severity(payload) != "ok" else "",
    )


def _coverage_severity(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "blocked"}:
        return "blocked"
    if status in {"incomplete", "warning", "loading"}:
        return "warning"
    return "ok"


def _coverage_reason(payload: dict[str, Any]) -> str:
    universe_quality = dict(payload.get("universe_quality") or {})
    domains = dict(payload.get("domains") or {})
    issues = list(universe_quality.get("issues") or [])
    if issues:
        return _first_text(issues[0])
    for domain_name, detail in domains.items():
        if int((detail or {}).get("missing_count") or 0) > 0:
            return f"{domain_name} missing {(detail or {}).get('missing_count')} assets"
    return str(payload.get("error") or "")


def _latest_created_at(items: list[Any]) -> str:
    if not items:
        return _iso(timezone.now())
    latest = None
    for item in items:
        created_at = getattr(item, "created_at", None)
        if created_at is None:
            continue
        if latest is None or created_at > latest:
            latest = created_at
    return _iso(latest or timezone.now())


def _overall_status(sections: list[list[dict[str, Any]]]) -> str:
    severities = [
        _normalize_severity(str(row.get("severity") or "ok"))
        for section in sections
        for row in section
    ]
    return _highest_severity(severities)


def _highest_severity(severities: list[str]) -> str:
    if any(severity == "blocked" for severity in severities):
        return "blocked"
    if any(severity == "warning" for severity in severities):
        return "warning"
    if any(severity == "notice" for severity in severities):
        return "notice"
    return "ok"


def _normalize_severity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SEVERITY_ORDER:
        return normalized
    return "ok"


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = _first_text(item)
                if text:
                    return text
            continue
        text = str(value or "").strip()
        if text:
            return mask_sensitive_text(text)[:2_000]
    return ""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text


def _domain_screen(domain: str) -> str:
    mapping = {
        "runtime": "api-library.runtime",
        "data-center": "api-library.data-center",
        "ai-provider": "ai-ops.providers",
        "ai-capability": "ai-ops.providers",
        "agent-runtime": "ai-ops.agent-runtime",
        "account-settings": "execution.account-settings",
        "config-center": "api-library.config-center",
    }
    return mapping.get(domain, "api-library.runtime")


def _domain_action(domain: str) -> str:
    mapping = {
        "runtime": "operator.governance.runtime_summary",
        "data-center": "operator.governance.data_center_summary",
        "ai-provider": "operator.governance.ai_provider_summary",
        "ai-capability": "operator.governance.ai_provider_summary",
        "agent-runtime": "operator.governance.agent_runtime_summary",
        "account-settings": "operator.governance.account_settings_summary",
        "config-center": "operator.governance.config_center_summary",
    }
    return mapping.get(domain, "operator.governance.runtime_summary")


def _is_admin_user(user: Any | None) -> bool:
    if user is None:
        return False
    if bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
        return True
    role = str(getattr(user, "rbac_role", "") or "").strip().lower()
    if role == "admin":
        return True
    profile = getattr(user, "account_profile", None)
    profile_role = str(getattr(profile, "rbac_role", "") or "").strip().lower()
    return profile_role == "admin"
