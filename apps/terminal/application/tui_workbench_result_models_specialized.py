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
            "terminal.agent_chat",
            "terminal.agent_stream",
            "cli.chat_router",
            "cli.agent_chat",
            "cli.agent_stream",
            "capability-router.route-message",
        } and isinstance(payload, dict):
            return self._ai_router_result_model(action, payload, status_code)
        if action_key in {
            "capability-router.mcp-self-status",
            "capability-router.mcp-self-endpoints",
            "capability-router.mcp-self-prompt-guide",
        } and isinstance(payload, dict):
            return self._mcp_self_service_result_model(action, payload)
        if action_key in {
            "capability-router.create-my-mcp-token",
            "capability-router.revoke-my-mcp-token",
        } and isinstance(payload, dict):
            return self._mcp_self_service_mutation_result_model(action, payload)
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
        elif str(action.get("key") or "") in {"cli.chat_router", "cli.agent_chat", "cli.agent_stream"}:
            steps.extend(
                [
                    {"label": "打开 AI 交互终端", "screen_key": "ai-ops.terminal"},
                    {"label": "打开能力路由接入", "screen_key": "capability-router.gateway"},
                ]
            )
        return steps

    def _mcp_self_service_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action_key = str(action.get("key") or "")
        username = self._display_value(payload.get("username") or action.get("label"))
        mcp_status = "已开启" if bool(payload.get("mcp_enabled")) else "已关闭"
        preferred_token = (
            payload.get("preferred_token") if isinstance(payload.get("preferred_token"), dict) else {}
        )
        token_name = self._display_value(
            preferred_token.get("name") or payload.get("agent_bootstrap_token_name") or "未配置"
        )
        token_display = self._display_value(
            payload.get("current_token_value")
            or payload.get("current_token_display")
            or preferred_token.get("display_token")
            or preferred_token.get("plaintext")
            or preferred_token.get("preview")
            or "未生成"
        )
        token_level = self._display_value(
            preferred_token.get("access_level_label")
            or payload.get("agent_bootstrap_access_level_label")
            or "-"
        )
        default_account = self._display_value(
            payload.get("default_account_name") or payload.get("default_account_id") or "未设置"
        )
        prompt_ready = "已就绪" if bool(payload.get("agent_bootstrap_token_ready")) else "待生成令牌"
        operator_hint = (
            "先创建只读令牌，再把下方智能路由地址与接入提示词交给助手。"
            if bool(payload.get("mcp_enabled"))
            else "当前账号未开通 MCP/SDK 接入，请先让管理员开启权限。"
        )

        if action_key == "capability-router.mcp-self-endpoints":
            return {
                "kind": "detail",
                "title": username,
                "status": mcp_status,
                "fields": [
                    {"key": "base_url", "label": "基础地址", "value": str(payload.get("base_url") or "-")},
                    {"key": "api_root_endpoint", "label": "系统入口", "value": str(payload.get("api_root_endpoint") or "-")},
                    {"key": "route_endpoint", "label": "智能路由地址", "value": str(payload.get("route_endpoint") or "-")},
                    {"key": "web_endpoint", "label": "网页对话地址", "value": str(payload.get("web_endpoint") or "-")},
                    {"key": "capability_endpoint", "label": "能力目录地址", "value": str(payload.get("capability_endpoint") or "-")},
                    {"key": "operator_hint", "label": "接入顺序", "value": "优先走智能路由地址；只在排障时读取能力目录或网页对话地址。"},
                ],
                "nested": [],
                "business_summary": "已提供个人接入所需地址。",
            }

        if action_key == "capability-router.mcp-self-prompt-guide":
            return {
                "kind": "detail",
                "title": username,
                "status": prompt_ready,
                "fields": [
                    {"key": "prompt_ready", "label": "提示词状态", "value": prompt_ready},
                    {"key": "token_name", "label": "当前令牌", "value": token_name},
                    {"key": "token_level", "label": "令牌级别", "value": token_level},
                    {"key": "operator_hint", "label": "操作提示", "value": operator_hint},
                    {"key": "agent_bootstrap_prompt", "label": "接入提示词", "value": self._display_value(payload.get("agent_bootstrap_prompt") or "-")},
                ],
                "nested": [],
                "business_summary": "已生成可直接交给助手的接入提示词。",
            }

        return {
            "kind": "detail",
            "title": username,
            "status": mcp_status,
            "fields": [
                {"key": "rbac_role", "label": "角色", "value": self._display_value(payload.get("rbac_role") or "-")},
                {"key": "mcp_enabled", "label": "MCP 接入", "value": mcp_status},
                {"key": "active_token_count", "label": "活跃令牌", "value": self._display_value(payload.get("active_token_count"))},
                {"key": "token_plaintext_allowed", "label": "明文显示", "value": self._display_value(payload.get("token_plaintext_allowed"))},
                {"key": "current_token", "label": "当前令牌", "value": token_display},
                {"key": "current_token_level", "label": "当前令牌级别", "value": token_level},
                {"key": "default_account", "label": "默认账户", "value": default_account},
                {"key": "base_url", "label": "基础地址", "value": self._display_value(payload.get("base_url"))},
            ],
            "nested": [
                {
                    "key": "access_tokens",
                    "label": "令牌列表",
                    "count": len(payload.get("access_tokens") or []),
                }
            ],
            "business_summary": f"{mcp_status}；令牌 {self._display_value(payload.get('active_token_count'))} 个。",
        }

    def _mcp_self_service_mutation_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action_key = str(action.get("key") or "")
        self_service = (
            payload.get("self_service") if isinstance(payload.get("self_service"), dict) else {}
        )
        token_payload = (
            payload.get("token_payload") if isinstance(payload.get("token_payload"), dict) else {}
        )
        created_prompt = (
            payload.get("created_agent_prompt")
            if isinstance(payload.get("created_agent_prompt"), dict)
            else {}
        )
        username = self._display_value(
            self_service.get("username") or token_payload.get("username") or action.get("label")
        )
        active_token_count = self._display_value(self_service.get("active_token_count"))
        route_endpoint = str(self_service.get("route_endpoint") or "-")

        if action_key == "capability-router.create-my-mcp-token":
            token_name = self._display_value(
                token_payload.get("token_name")
                or self_service.get("agent_bootstrap_token_name")
                or "未命名令牌"
            )
            token_level = self._display_value(
                token_payload.get("access_level_label")
                or created_prompt.get("agent_bootstrap_access_level_label")
                or self_service.get("agent_bootstrap_access_level_label")
                or "-"
            )
            token_value = self._display_value(
                token_payload.get("token")
                or self_service.get("current_token_value")
                or self_service.get("current_token_display")
                or "未返回明文令牌"
            )
            prompt_value = self._display_value(
                created_prompt.get("agent_bootstrap_prompt")
                or self_service.get("agent_bootstrap_prompt")
                or "-"
            )
            return {
                "kind": "detail",
                "title": username,
                "status": "已创建",
                "fields": [
                    {
                        "key": "message",
                        "label": "处理结果",
                        "value": self._display_value(payload.get("message") or "MCP 令牌已创建"),
                    },
                    {"key": "token_name", "label": "新令牌", "value": token_name},
                    {"key": "token_level", "label": "访问级别", "value": token_level},
                    {"key": "token_value", "label": "令牌明文", "value": token_value},
                    {
                        "key": "active_token_count",
                        "label": "活跃令牌",
                        "value": active_token_count,
                    },
                    {
                        "key": "route_endpoint",
                        "label": "智能路由地址",
                        "value": route_endpoint,
                    },
                    {
                        "key": "agent_bootstrap_prompt",
                        "label": "接入提示词",
                        "value": prompt_value,
                    },
                ],
                "nested": [
                    {
                        "key": "access_tokens",
                        "label": "令牌列表",
                        "count": len(self_service.get("access_tokens") or []),
                    }
                ],
                "business_summary": self._display_value(
                    payload.get("message") or f"已创建 {token_name}"
                ),
            }

        preferred_token = (
            self_service.get("preferred_token")
            if isinstance(self_service.get("preferred_token"), dict)
            else {}
        )
        token_display = self._display_value(
            self_service.get("current_token_value")
            or self_service.get("current_token_display")
            or preferred_token.get("display_token")
            or preferred_token.get("plaintext")
            or preferred_token.get("preview")
            or "未生成"
        )
        return {
            "kind": "detail",
            "title": username,
            "status": "已撤销",
            "fields": [
                {
                    "key": "message",
                    "label": "处理结果",
                    "value": self._display_value(payload.get("message") or "MCP 令牌已撤销"),
                },
                {"key": "active_token_count", "label": "剩余活跃令牌", "value": active_token_count},
                {"key": "current_token", "label": "当前令牌", "value": token_display},
                {"key": "route_endpoint", "label": "智能路由地址", "value": route_endpoint},
            ],
            "nested": [
                {
                    "key": "access_tokens",
                    "label": "令牌列表",
                    "count": len(self_service.get("access_tokens") or []),
                }
            ],
            "business_summary": self._display_value(
                payload.get("message") or "令牌已撤销，请复制新的可用令牌。"
            ),
        }
