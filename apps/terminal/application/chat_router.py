"""
Terminal chat routing service.

Terminal 自然语言先经过意图分类，再决定走内建状态查询还是普通聊天。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Any, Optional

from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from core.health_checks import is_healthy, run_readiness_checks

logger = logging.getLogger(__name__)


@dataclass
class TerminalIntentDecision:
    intent: str = "chat"
    confidence: float = 0.0
    reason: str = ""


class TerminalChatRouterService:
    """Route terminal natural language to builtin status/regime or generic chat."""

    HIGH_CONFIDENCE = 0.85
    SUGGEST_CONFIDENCE = 0.60
    ALLOWED_INTENTS = {"chat", "system_status", "market_regime"}

    def route_message(
        self,
        *,
        message: str,
        session_id: str | None,
        provider_ref: str | None,
        model: str | None,
        context: dict[str, Any] | None = None,
        answer_chain_enabled: bool = False,
        user_is_admin: bool = False,
        user: Any | None = None,
    ) -> dict[str, Any]:
        resolved_session_id = session_id or str(uuid.uuid4())
        decision = self._classify_intent(
            message=message,
            provider_ref=provider_ref,
            model=model,
            user=user,
        )

        if decision.intent == "system_status" and decision.confidence >= self.HIGH_CONFIDENCE:
            return self._build_system_status_response(
                session_id=resolved_session_id,
                decision=decision,
                answer_chain_enabled=answer_chain_enabled,
                user_is_admin=user_is_admin,
            )

        if decision.intent == "market_regime" and decision.confidence >= self.HIGH_CONFIDENCE:
            return self._build_regime_response(
                session_id=resolved_session_id,
                decision=decision,
                answer_chain_enabled=answer_chain_enabled,
                user_is_admin=user_is_admin,
            )

        if decision.intent != "chat" and decision.confidence >= self.SUGGEST_CONFIDENCE:
            suggested_command = "/status" if decision.intent == "system_status" else "/regime"
            suggested_label = "系统状态" if decision.intent == "system_status" else "市场 regime"
            return {
                "reply": (
                    f"检测到你可能想查看{suggested_label}。"
                    f"建议执行 `{suggested_command}`。"
                ),
                "session_id": resolved_session_id,
                "metadata": {
                    "provider": "terminal-router",
                    "model": "intent-router",
                    "route": "intent_suggestion",
                    "intent": decision.intent,
                    "intent_confidence": decision.confidence,
                    **self._metadata_answer_chain(
                        answer_chain_enabled,
                        self._build_router_chain(
                            decision=decision,
                            route="intent_suggestion",
                            user_is_admin=user_is_admin,
                            suggested_command=suggested_command,
                        ),
                    ),
                },
                "route_confirmation_required": True,
                "suggested_command": suggested_command,
                "suggested_intent": decision.intent,
                "suggestion_prompt": (
                    f"检测到你可能想执行 {suggested_command}。"
                    "输入 Y 执行，输入 N 取消，或继续输入其他内容。"
                ),
            }

        return self._build_chat_response(
            message=message,
            session_id=resolved_session_id,
            provider_ref=provider_ref,
            model=model,
            context=context or {},
            decision=decision,
            answer_chain_enabled=answer_chain_enabled,
            user_is_admin=user_is_admin,
            user=user,
        )

    def _classify_intent(
        self,
        *,
        message: str,
        provider_ref: str | None,
        model: str | None,
        user: Any | None = None,
    ) -> TerminalIntentDecision:
        ai_factory = AIClientFactory()
        ai_client = ai_factory.get_client(provider_ref, user=user)
        classifier_messages = [
            {
                "role": "system",
                "content": (
                    "You classify terminal user intent. "
                    "Return JSON only with keys: intent, confidence, reason. "
                    "Allowed intent values: chat, system_status, market_regime. "
                    "Choose system_status only when the user is asking about runtime health, readiness, service status, database/cache/celery health, or current system operational state. "
                    "Choose market_regime only when the user is asking about macro regime, market regime, policy regime, or current market environment. "
                    "Otherwise choose chat. Confidence must be between 0 and 1."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ]

        try:
            ai_response = ai_client.chat_completion(
                messages=classifier_messages,
                model=model,
                temperature=0,
                max_tokens=120,
            )
            if ai_response.get("status") != "success":
                return TerminalIntentDecision()

            payload = self._extract_json_object(ai_response.get("content", ""))
            intent = str(payload.get("intent", "chat")).strip()
            confidence = float(payload.get("confidence", 0.0))
            reason = str(payload.get("reason", "")).strip()

            if intent not in self.ALLOWED_INTENTS:
                return TerminalIntentDecision()

            confidence = max(0.0, min(confidence, 1.0))
            return TerminalIntentDecision(intent=intent, confidence=confidence, reason=reason)
        except Exception:
            logger.exception("Terminal intent classification failed")
            return TerminalIntentDecision()

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        if not text:
            return {}

        candidate = text.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", candidate)
        if fenced_match:
            candidate = fenced_match.group(1)
        else:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start:end + 1]

        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Terminal intent classifier returned non-JSON payload: %s", text[:300])
            return {}

    def _build_system_status_response(
        self,
        *,
        session_id: str,
        decision: TerminalIntentDecision,
        answer_chain_enabled: bool,
        user_is_admin: bool,
    ) -> dict[str, Any]:
        checks = run_readiness_checks()
        overall = "ok" if is_healthy(checks) else "error"

        def _line(label: str, result: dict[str, Any]) -> str:
            status = result.get("status", "unknown")
            detail = (
                result.get("error")
                or result.get("reason")
                or (f"{result.get('workers')} workers" if result.get("workers") else "")
                or (f"empty: {', '.join(result.get('empty_tables', []))}" if result.get("empty_tables") else "")
            )
            suffix = f" ({detail})" if detail else ""
            return f"- **{label}**: `{status}`{suffix}"

        reply = "\n".join([
            f"## System Readiness: `{overall}`",
            _line("Database", checks.get("database", {})),
            _line("Redis", checks.get("redis", {})),
            _line("Celery", checks.get("celery", {})),
            _line("Critical Data", checks.get("critical_data", {})),
            f"- **Timestamp**: `{datetime.now(UTC).isoformat()}`",
        ])

        return {
            "reply": reply,
            "session_id": session_id,
            "metadata": {
                "provider": "terminal-router",
                "model": "builtin-status",
                "route": "system_status",
                "intent": decision.intent,
                "intent_confidence": decision.confidence,
                **self._metadata_answer_chain(
                    answer_chain_enabled,
                    self._build_system_status_chain(decision, checks, user_is_admin),
                ),
            },
            "route_confirmation_required": False,
            "suggested_command": None,
            "suggested_intent": None,
            "suggestion_prompt": None,
        }

    def _build_regime_response(
        self,
        *,
        session_id: str,
        decision: TerminalIntentDecision,
        answer_chain_enabled: bool,
        user_is_admin: bool,
    ) -> dict[str, Any]:
        regime = resolve_current_regime()
        policy_repo = DjangoPolicyRepository()
        policy = policy_repo.get_current_policy_level()

        reply = "\n".join([
            "## Current Market Regime",
            f"- **Regime**: `{getattr(regime, 'dominant_regime', 'Unknown')}`",
            f"- **Confidence**: `{(getattr(regime, 'confidence', 0) or 0) * 100:.1f}%`",
            f"- **Source**: `{getattr(regime, 'source', 'N/A')}`",
            f"- **Observed At**: `{getattr(regime, 'observed_at', 'N/A')}`",
            f"- **Policy Level**: `{getattr(policy, 'value', 'N/A')}`",
        ])

        return {
            "reply": reply,
            "session_id": session_id,
            "metadata": {
                "provider": "terminal-router",
                "model": "builtin-regime",
                "route": "market_regime",
                "intent": decision.intent,
                "intent_confidence": decision.confidence,
                **self._metadata_answer_chain(
                    answer_chain_enabled,
                    self._build_regime_chain(decision, regime, policy, user_is_admin),
                ),
            },
            "route_confirmation_required": False,
            "suggested_command": None,
            "suggested_intent": None,
            "suggestion_prompt": None,
        }

    def _build_chat_response(
        self,
        *,
        message: str,
        session_id: str,
        provider_ref: str | None,
        model: str | None,
        context: dict[str, Any],
        decision: TerminalIntentDecision,
        answer_chain_enabled: bool,
        user_is_admin: bool,
        user: Any | None = None,
    ) -> dict[str, Any]:
        messages = context.get("history", [])
        messages.append({"role": "user", "content": message})

        ai_factory = AIClientFactory()
        ai_client = ai_factory.get_client(provider_ref, user=user)
        ai_response = ai_client.chat_completion(
            messages=messages,
            model=model,
        )
        if ai_response.get("status") != "success":
            raise RuntimeError(ai_response.get("error_message", "AI 调用失败"))

        return {
            "reply": ai_response.get("content", ""),
            "session_id": session_id,
            "metadata": {
                "provider": ai_response.get("provider_used", ""),
                "model": ai_response.get("model", ""),
                "tokens": ai_response.get("total_tokens", 0),
                "route": "chat",
                "intent": decision.intent,
                "intent_confidence": decision.confidence,
                **self._metadata_answer_chain(
                    answer_chain_enabled,
                    self._build_chat_chain(
                        decision=decision,
                        provider=ai_response.get("provider_used", ""),
                        model=ai_response.get("model", ""),
                        user_is_admin=user_is_admin,
                    ),
                ),
            },
            "route_confirmation_required": False,
            "suggested_command": None,
            "suggested_intent": None,
            "suggestion_prompt": None,
        }

    def _metadata_answer_chain(self, enabled: bool, chain: dict[str, Any] | None) -> dict[str, Any]:
        if not enabled or not chain:
            return {}
        return {"answer_chain": chain}

    def _build_router_chain(
        self,
        *,
        decision: TerminalIntentDecision,
        route: str,
        user_is_admin: bool,
        suggested_command: str,
    ) -> dict[str, Any]:
        steps = [
            {
                "title": "Intent classification",
                "summary": f"Classified input as {decision.intent} with confidence {decision.confidence:.2f}.",
                "source": "AI intent router",
            },
            {
                "title": "Route suggestion",
                "summary": f"Suggested command {suggested_command} instead of executing directly.",
                "source": "Terminal router policy",
            },
        ]
        if user_is_admin:
            steps[0]["technical_details"] = [
                f"intent={decision.intent}",
                f"confidence={decision.confidence:.2f}",
                f"route={route}",
            ]
        return {"label": "Answer chain", "visibility": "technical" if user_is_admin else "masked", "steps": steps}

    def _build_system_status_chain(self, decision, checks, user_is_admin: bool) -> dict[str, Any]:
        steps = [
            {
                "title": "Intent classification",
                "summary": f"Recognized a system status query with confidence {decision.confidence:.2f}.",
                "source": "AI intent router",
            },
            {
                "title": "Readiness checks",
                "summary": "Collected current database, cache, worker, and critical data readiness.",
                "source": "System readiness service",
            },
            {
                "title": "Answer assembly",
                "summary": "Summarized the current operational state for terminal display.",
                "source": "Terminal router",
            },
        ]
        if user_is_admin:
            steps[1]["technical_details"] = [
                f"checks.database.status={checks.get('database', {}).get('status', 'unknown')}",
                f"checks.redis.status={checks.get('redis', {}).get('status', 'unknown')}",
                f"checks.celery.status={checks.get('celery', {}).get('status', 'unknown')}",
                f"checks.critical_data.status={checks.get('critical_data', {}).get('status', 'unknown')}",
            ]
        return {"label": "Answer chain", "visibility": "technical" if user_is_admin else "masked", "steps": steps}

    def _build_regime_chain(self, decision, regime, policy, user_is_admin: bool) -> dict[str, Any]:
        steps = [
            {
                "title": "Intent classification",
                "summary": f"Recognized a market regime query with confidence {decision.confidence:.2f}.",
                "source": "AI intent router",
            },
            {
                "title": "Regime lookup",
                "summary": "Loaded the current regime snapshot and current policy level.",
                "source": "Regime service and policy repository",
            },
            {
                "title": "Answer assembly",
                "summary": "Prepared a user-facing summary of regime and policy context.",
                "source": "Terminal router",
            },
        ]
        if user_is_admin:
            steps[1]["technical_details"] = [
                f"RegimeSnapshot.dominant_regime={getattr(regime, 'dominant_regime', 'Unknown')}",
                f"RegimeSnapshot.confidence={getattr(regime, 'confidence', 0)}",
                f"RegimeSnapshot.source={getattr(regime, 'source', 'N/A')}",
                f"PolicyLevel.value={getattr(policy, 'value', 'N/A')}",
            ]
        return {"label": "Answer chain", "visibility": "technical" if user_is_admin else "masked", "steps": steps}

    def _build_chat_chain(self, *, decision, provider: str, model: str, user_is_admin: bool) -> dict[str, Any]:
        steps = [
            {
                "title": "Intent classification",
                "summary": f"Classified the input as general chat with confidence {decision.confidence:.2f}.",
                "source": "AI intent router",
            },
            {
                "title": "Model response",
                "summary": "Sent the request to the selected AI provider and returned the generated answer.",
                "source": provider or "AI provider",
            },
        ]
        if user_is_admin:
            steps[1]["technical_details"] = [
                f"provider={provider or 'unknown'}",
                f"model={model or 'unknown'}",
            ]
        return {"label": "Answer chain", "visibility": "technical" if user_is_admin else "masked", "steps": steps}
