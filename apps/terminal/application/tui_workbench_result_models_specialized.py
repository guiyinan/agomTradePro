"""Business-specific result-model helpers for the TUI workbench."""

from __future__ import annotations

from typing import Any


class TuiWorkbenchSpecializedResultMixin:
    """Specialized view-model builders layered on top of the base mixin."""

    def _custom_view_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        *,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        action_key = str(action.get("key") or "")
        if action_key == "advisor.today_sheet" and isinstance(payload, dict):
            return self._advisor_today_sheet_model(action, payload)
        if action_key in {
            "terminal.chat_router",
            "cli.chat_router",
            "capability-router.route-message",
        } and isinstance(payload, dict):
            return self._ai_router_result_model(action, payload, status_code)
        return None

    def _advisor_today_sheet_model(
        self, action: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        order_summary = (
            payload.get("order_summary") if isinstance(payload.get("order_summary"), dict) else {}
        )
        execution_plan = (
            payload.get("execution_plan") if isinstance(payload.get("execution_plan"), dict) else {}
        )
        blockers = list(payload.get("blockers") or [])
        next_actions = list(payload.get("next_actions") or [])
        conclusion = self._advisor_verdict_label(payload.get("today_conclusion"))
        holdings_text = (
            f"{account.get('holding_count', 0)} 个持仓 / 现金 {self._display_value(account.get('available_cash'))} "
            f"/ 总资产 {self._display_value(account.get('total_asset'))}"
        )
        blocker_text = "无明确阻断项"
        if blockers:
            blocker_text = (
                "；".join(
                    self._operator_text(item.get("message") or "") for item in blockers[:2] if item
                )
                or f"{len(blockers)} 项阻断"
            )
        action_text = (
            f"共 {order_summary.get('total', 0)} 单 / 可执行 {order_summary.get('actionable', 0)} 单 "
            f"/ 阻断 {order_summary.get('blocked', 0)} 单"
        )
        risk_text = "；".join(
            filter(
                None,
                [
                    self._advisor_data_health_message(payload.get("data_health")),
                    f"执行模式 {self._display_value(execution_plan.get('execution_mode'))}",
                    f"确认 {self._display_value(execution_plan.get('confirmation_status'))}",
                ],
            )
        )
        return {
            "kind": "detail",
            "title": self._display_value(account.get("account_name") or action.get("label")),
            "status": conclusion,
            "fields": [
                {"key": "today_conclusion", "label": "账户结论", "value": conclusion},
                {"key": "holding_summary", "label": "持仓摘要", "value": holdings_text},
                {"key": "blockers", "label": "阻断项", "value": blocker_text},
                {"key": "orders", "label": "建议动作/建议订单", "value": action_text},
                {
                    "key": "risk_hints",
                    "label": "风险提示",
                    "value": risk_text or "当前未返回额外风险提示",
                },
            ],
            "nested": [
                {
                    "key": "holdings",
                    "label": "当前持仓",
                    "count": len(payload.get("holdings") or []),
                },
                {
                    "key": "order_intents",
                    "label": "建议订单",
                    "count": len(payload.get("order_intents") or []),
                },
                {"key": "blockers", "label": "阻断清单", "count": len(blockers)},
            ],
            "business_summary": f"{conclusion}；{action_text}",
            "blocking_reason": self._advisor_blocking_reason(payload),
            "next_steps": [
                *[
                    {
                        "label": self._operator_text(item.get("label") or "下一步"),
                        "hint": self._operator_text(item.get("hint") or ""),
                    }
                    for item in next_actions[:3]
                    if isinstance(item, dict)
                ],
                {
                    "label": "建议单因子明细",
                    "action_key": "advisor.factor_breakdown",
                    "params": {"account_id": account.get("account_id")},
                    "hint": "查看市场温度与组件明细。",
                },
            ],
            "debug_hidden_fields": [
                "holdings",
                "decision_cards",
                "data_health.market_thermometer.components",
                "execution_plan.orders",
            ],
        }

    def _ai_router_result_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        reply = self._operator_text(
            payload.get("reply") or payload.get("message") or payload.get("error") or ""
        )
        error_code, mapped_reply = self._map_user_facing_ai_error(payload, reply)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        selected_capability = self._display_value(
            payload.get("selected_capability_key")
            or metadata.get("selected_capability_key")
            or metadata.get("capability_name")
        )
        route_decision = self._display_value(
            metadata.get("decision") or payload.get("decision") or metadata.get("route")
        )
        requires_confirmation = self._display_value(
            payload.get("route_confirmation_required")
            or payload.get("requires_confirmation")
            or metadata.get("requires_confirmation")
        )
        next_step = self._ai_router_next_step(payload, error_code=error_code)
        status = self._status_label(status_code, payload)
        if error_code:
            status = "需配置"
        elif 400 <= int(status_code) < 500:
            status = "错误"
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": status,
            "fields": [
                {"key": "reply", "label": "回复", "value": mapped_reply or reply or "-"},
                {
                    "key": "route",
                    "label": "已选能力/路由结论",
                    "value": f"{selected_capability} / {route_decision}",
                },
                {"key": "confirmation", "label": "是否需确认", "value": requires_confirmation},
                {"key": "next_step", "label": "建议下一步", "value": next_step},
            ],
            "nested": [],
            "business_summary": mapped_reply or reply or route_decision,
            "blocking_reason": (
                mapped_reply if error_code else self._default_blocking_reason(payload, status_code)
            ),
            "next_steps": self._ai_router_next_steps(action, error_code=error_code),
            "debug_hidden_fields": [
                "session_id",
                "metadata.provider",
                "metadata.model",
                "metadata.answer_chain",
                "missing_params",
                "suggested_command",
                "suggested_intent",
            ],
            "user_error_code": error_code,
        }

    def _advisor_verdict_label(self, verdict: Any) -> str:
        mapping = {
            "ACT": "可以行动",
            "REVIEW": "需要复核",
            "WAIT": "继续等待",
            "BLOCKED": "已阻断",
        }
        normalized = str(verdict or "").strip().upper()
        return mapping.get(normalized, self._display_value(verdict))

    def _advisor_data_health_message(self, data_health: Any) -> str:
        if not isinstance(data_health, dict):
            return ""
        blocked_reasons = list(data_health.get("blocked_reasons") or [])
        if blocked_reasons:
            return self._operator_text(blocked_reasons[0])
        return f"数据状态 {self._display_value(data_health.get('status'))}"

    def _advisor_blocking_reason(self, payload: dict[str, Any]) -> str:
        blockers = list(payload.get("blockers") or [])
        if blockers:
            return "；".join(
                self._operator_text(item.get("message") or "") for item in blockers[:2] if item
            )
        warnings = list(payload.get("warnings") or [])
        if warnings:
            return self._operator_text(str(warnings[0]))
        data_health = payload.get("data_health")
        if isinstance(data_health, dict) and str(
            data_health.get("status") or ""
        ).strip().lower() not in {
            "",
            "ok",
            "normal",
        }:
            return self._advisor_data_health_message(data_health)
        return ""

    def _map_user_facing_ai_error(self, payload: dict[str, Any], reply: str) -> tuple[str, str]:
        code = str(payload.get("code") or "").strip().upper()
        text = reply or ""
        if "System fallback quota is not configured for this user." in text:
            return (
                "AI_PROVIDER_NOT_CONFIGURED",
                "当前账号未配置默认 AI 服务，请先到 AI 服务商与用量 / 提示词与模型配置 完成配置。",
            )
        if "System fallback quota exhausted for today." in text:
            return (
                "AI_FALLBACK_QUOTA_DAILY_EXHAUSTED",
                "当前账号的默认 AI 当日额度已用完，请稍后重试或切换到个人 AI 服务商。",
            )
        if "System fallback quota exhausted for this month." in text:
            return (
                "AI_FALLBACK_QUOTA_MONTHLY_EXHAUSTED",
                "当前账号的默认 AI 当月额度已用完，请切换到个人 AI 服务商或联系管理员调整额度。",
            )
        if code == "VALIDATION_ERROR":
            return (
                "VALIDATION_ERROR",
                self._operator_text(payload.get("error") or "请求参数验证失败"),
            )
        return "", ""

    def _ai_router_next_step(self, payload: dict[str, Any], *, error_code: str) -> str:
        if error_code == "AI_PROVIDER_NOT_CONFIGURED":
            return "先完成默认 AI 服务配置，再回到当前页面重试。"
        missing_params = list(payload.get("missing_params") or [])
        if missing_params:
            return "先补全缺失参数，再重新发起请求。"
        suggestion_prompt = self._operator_text(payload.get("suggestion_prompt") or "")
        if suggestion_prompt:
            return suggestion_prompt
        return "继续等待结果，或切换到更明确的能力/配置页面。"

    def _ai_router_next_steps(
        self, action: dict[str, Any], *, error_code: str
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = [
            {"label": "重试", "action_key": str(action.get("key") or "")}
        ]
        if error_code:
            steps.extend(
                [
                    {"label": "AI 服务商与用量", "screen_key": "ai-ops.providers"},
                    {"label": "提示词与模型配置", "screen_key": "ai-ops.prompts"},
                ]
            )
        elif str(action.get("key") or "") == "cli.chat_router":
            steps.extend(
                [
                    {"label": "打开 AI 交互终端", "screen_key": "ai-ops.terminal"},
                    {"label": "打开能力路由接入", "screen_key": "capability-router.gateway"},
                ]
            )
        return steps
