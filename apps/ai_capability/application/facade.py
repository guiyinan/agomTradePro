"""
AI Capability Catalog Application Facade for Terminal Integration.

Provides a simplified interface for terminal to use the unified routing system.
"""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timezone
from typing import Any, Optional

from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from core.health_checks import is_healthy, run_readiness_checks

from ..application.dtos import RouteRequestDTO
from ..application.use_cases import RouteMessageUseCase
from ..domain.entities import (
    CapabilityDecision,
    RoutingContext,
    RoutingDecision,
    SourceType,
)
from ..domain.services import CapabilityFilter
from ..infrastructure.repositories import (
    DjangoCapabilityRepository,
    DjangoRoutingLogRepository,
)

logger = logging.getLogger(__name__)


class CapabilityRoutingFacade:
    """
    Unified routing facade for terminal and other entrypoints.

    This is the main entry point for all AI routing decisions.
    It replaces the old TerminalChatRouterService with a catalog-based approach.
    """

    HIGH_CONFIDENCE_THRESHOLD = 0.85
    SUGGEST_CONFIDENCE_THRESHOLD = 0.60
    TOP_K_CANDIDATES = 5

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        routing_log_repo: DjangoRoutingLogRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.routing_log_repo = routing_log_repo or DjangoRoutingLogRepository()
        self.route_use_case = RouteMessageUseCase(
            capability_repo=self.capability_repo,
            routing_log_repo=self.routing_log_repo,
        )

    def route(
        self,
        message: str,
        entrypoint: str = "terminal",
        session_id: str | None = None,
        user_id: int | None = None,
        user_is_admin: bool = False,
        mcp_enabled: bool = True,
        provider_name: str | None = None,
        model: str | None = None,
        context: dict[str, Any] | None = None,
        answer_chain_enabled: bool = False,
    ) -> dict[str, Any]:
        request_dto = RouteRequestDTO(
            message=message,
            entrypoint=entrypoint,
            session_id=session_id,
            provider_name=provider_name,
            model=model,
            context={
                **(context or {}),
                "user_id": user_id,
                "user_is_admin": user_is_admin,
                "mcp_enabled": mcp_enabled,
                "answer_chain_enabled": answer_chain_enabled,
            },
        )
        return self.route_use_case.execute(request_dto).to_dict()

    def execute_capability(
        self,
        capability_key: str,
        message: str,
        entrypoint: str = "web",
        session_id: str | None = None,
        user_id: int | None = None,
        user_is_admin: bool = False,
        mcp_enabled: bool = True,
        provider_name: str | None = None,
        model: str | None = None,
        context: dict[str, Any] | None = None,
        answer_chain_enabled: bool = False,
    ) -> dict[str, Any]:
        capability = self.capability_repo.get_by_key(capability_key)
        if capability is None:
            raise ValueError(f"Capability not found: {capability_key}")

        session_id = session_id or str(uuid.uuid4())
        request_context = {
            **(context or {}),
            "user_id": user_id,
            "user_is_admin": user_is_admin,
            "mcp_enabled": mcp_enabled,
            "answer_chain_enabled": answer_chain_enabled,
        }
        request_dto = RouteRequestDTO(
            message=message,
            entrypoint=entrypoint,
            session_id=session_id,
            provider_name=provider_name,
            model=model,
            context=request_context,
        )
        routing_context = RoutingContext(
            entrypoint=entrypoint,
            session_id=session_id,
            user_id=user_id,
            user_is_admin=user_is_admin,
            mcp_enabled=mcp_enabled,
            provider_name=provider_name,
            model=model,
            context=request_context,
            answer_chain_enabled=answer_chain_enabled,
        )

        allowed = CapabilityFilter().filter_by_context([capability], routing_context)
        if not allowed:
            raise PermissionError(f"Capability is not available in {entrypoint} for this user: {capability_key}")

        # The user has already confirmed the suggestion in the web UI.
        confirmed_capability = replace(capability, requires_confirmation=False)
        decision = self.route_use_case._build_capability_decision(
            confirmed_capability,
            [capability.to_summary_dict()],
            1.0,
            request_dto,
            routing_context,
            reason="User explicitly executed the suggested action.",
            rejected_candidates=[],
        )
        self.route_use_case._log_routing(
            context=routing_context,
            raw_message=message,
            scores=[],
            decision=decision,
        )
        return self.route_use_case._build_response(
            decision,
            session_id,
            routing_context,
        ).to_dict()

    def _handle_no_candidates(
        self,
        message: str,
        session_id: str,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Handle case when no candidates are found."""
        decision = self._build_chat_decision([], message, context)

        self._log_routing(
            context=context,
            raw_message=message,
            scores=[],
            decision=decision,
        )

        return self._build_response(decision, session_id, context)

    def _build_capability_decision(
        self,
        capability: Any,
        candidates: list[dict[str, Any]],
        confidence: float,
        message: str,
        context: RoutingContext,
    ) -> RoutingDecision:
        """Build decision for high-confidence capability match."""
        execution_result = self._execute_capability(capability, message, context)

        answer_chain = self._build_answer_chain(
            capability=capability,
            candidates=candidates,
            confidence=confidence,
            context=context,
            route="capability",
        )

        return RoutingDecision(
            decision=CapabilityDecision.CAPABILITY,
            selected_capability_key=capability.capability_key,
            confidence=confidence,
            candidate_capabilities=candidates,
            requires_confirmation=capability.requires_confirmation,
            reply=execution_result.get("reply", ""),
            filled_params={},
            metadata={
                "route": "capability",
                "provider": "capability-router",
                "model": "router",
                "capability_name": capability.name,
            },
            answer_chain=answer_chain,
        )

    def _build_suggestion_decision(
        self,
        capability: Any,
        candidates: list[dict[str, Any]],
        confidence: float,
        message: str,
        context: RoutingContext,
    ) -> RoutingDecision:
        """Build decision for medium-confidence suggestion."""
        answer_chain = self._build_answer_chain(
            capability=capability,
            candidates=candidates,
            confidence=confidence,
            context=context,
            route="intent_suggestion",
        )

        suggested_command = f"/{capability.capability_key.split('.')[-1]}"

        return RoutingDecision(
            decision=CapabilityDecision.ASK_CONFIRMATION,
            selected_capability_key=capability.capability_key,
            confidence=confidence,
            candidate_capabilities=candidates,
            requires_confirmation=True,
            reply=f"检测到你可能想执行 {capability.name}。建议执行 `{suggested_command}`。",
            filled_params={},
            metadata={
                "route": "intent_suggestion",
                "provider": "capability-router",
                "model": "router",
            },
            answer_chain=answer_chain,
        )

    def _build_chat_decision(
        self,
        candidates: list[dict[str, Any]],
        message: str,
        context: RoutingContext,
    ) -> RoutingDecision:
        """Build decision for general chat."""
        reply = self._execute_chat(message, context)

        answer_chain = self._build_chat_answer_chain(context)

        return RoutingDecision(
            decision=CapabilityDecision.CHAT,
            selected_capability_key=None,
            confidence=0.0,
            candidate_capabilities=candidates,
            requires_confirmation=False,
            reply=reply,
            filled_params={},
            metadata={
                "route": "chat",
                "provider": context.provider_name or "default",
                "model": context.model or "default",
            },
            answer_chain=answer_chain,
        )

    def _execute_capability(
        self,
        capability: Any,
        message: str,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Execute a capability and return result."""
        if capability.source_type == SourceType.BUILTIN:
            return self._execute_builtin(capability)
        elif capability.source_type == SourceType.TERMINAL_COMMAND:
            return self._execute_terminal_command(capability, context)
        elif capability.source_type == SourceType.MCP_TOOL:
            return self._execute_mcp_tool(capability, context)
        elif capability.source_type == SourceType.API:
            return self._execute_api(capability, context)
        else:
            return {"reply": f"Unknown capability type: {capability.source_type}"}

    def _execute_builtin(self, capability: Any) -> dict[str, Any]:
        """Execute a builtin capability."""
        handler = capability.execution_target.get("handler")

        if handler == "system_status":
            return self._execute_system_status()
        elif handler == "market_regime":
            return self._execute_market_regime()
        else:
            return {"reply": f"Unknown builtin handler: {handler}"}

    def _execute_system_status(self) -> dict[str, Any]:
        """Execute system status check."""
        checks = run_readiness_checks()
        overall = "ok" if is_healthy(checks) else "error"

        def _line(label: str, result: dict[str, Any]) -> str:
            status = result.get("status", "unknown")
            detail = (
                result.get("error")
                or result.get("reason")
                or (f"{result.get('workers')} workers" if result.get("workers") else "")
                or (
                    f"empty: {', '.join(result.get('empty_tables', []))}"
                    if result.get("empty_tables")
                    else ""
                )
            )
            suffix = f" ({detail})" if detail else ""
            return f"- **{label}**: `{status}`{suffix}"

        reply = "\n".join(
            [
                f"## System Readiness: `{overall}`",
                _line("Database", checks.get("database", {})),
                _line("Redis", checks.get("redis", {})),
                _line("Celery", checks.get("celery", {})),
                _line("Critical Data", checks.get("critical_data", {})),
                f"- **Timestamp**: `{datetime.now(UTC).isoformat()}`",
            ]
        )

        return {"reply": reply}

    def _execute_market_regime(self) -> dict[str, Any]:
        """Execute market regime check."""
        regime = resolve_current_regime()
        policy_repo = DjangoPolicyRepository()
        policy = policy_repo.get_current_policy_level()

        reply = "\n".join(
            [
                "## Current Market Regime",
                f"- **Regime**: `{getattr(regime, 'dominant_regime', 'Unknown')}`",
                f"- **Confidence**: `{(getattr(regime, 'confidence', 0) or 0) * 100:.1f}%`",
                f"- **Source**: `{getattr(regime, 'source', 'N/A')}`",
                f"- **Observed At**: `{getattr(regime, 'observed_at', 'N/A')}`",
                f"- **Policy Level**: `{getattr(policy, 'value', 'N/A')}`",
            ]
        )

        return {"reply": reply}

    def _execute_terminal_command(
        self,
        capability: Any,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Execute a terminal command capability."""
        return {"reply": f"Terminal command execution: {capability.name}"}

    def _execute_mcp_tool(
        self,
        capability: Any,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Execute an MCP tool capability."""
        return {"reply": f"MCP tool execution: {capability.name}"}

    def _execute_api(
        self,
        capability: Any,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Execute an internal API capability."""
        return {"reply": f"API execution: {capability.name}"}

    def _execute_chat(
        self,
        message: str,
        context: RoutingContext,
    ) -> str:
        """Execute general chat using AI provider."""
        try:
            ai_factory = AIClientFactory()
            ai_client = ai_factory.get_client(
                context.provider_name,
                user=context.user_id,
            )

            messages = context.context.get("history", [])
            messages.append({"role": "user", "content": message})

            ai_response = ai_client.chat_completion(
                messages=messages,
                model=context.model,
            )

            if ai_response.get("status") != "success":
                return f"AI 调用失败: {ai_response.get('error_message', 'Unknown error')}"

            return ai_response.get("content", "")
        except Exception as e:
            logger.exception("Chat execution failed")
            return f"Chat execution failed: {str(e)}"

    def _build_answer_chain(
        self,
        capability: Any,
        candidates: list[dict[str, Any]],
        confidence: float,
        context: RoutingContext,
        route: str,
    ) -> dict[str, Any]:
        """Build answer chain for debugging."""
        steps = [
            {
                "title": "Capability Retrieval",
                "summary": f"Retrieved {len(candidates)} candidates, top: {capability.name}",
                "source": "Capability Catalog",
            },
            {
                "title": "Routing Decision",
                "summary": f"Selected {capability.capability_key} with confidence {confidence:.2f}",
                "source": "Capability Router",
            },
        ]

        if context.user_is_admin:
            steps[0]["technical_details"] = [
                f"candidates={[c['capability_key'] for c in candidates]}",
                f"top_score={confidence:.2f}",
                f"route={route}",
            ]

        return {
            "label": "Answer chain",
            "visibility": "technical" if context.user_is_admin else "masked",
            "steps": steps,
        }

    def _build_chat_answer_chain(self, context: RoutingContext) -> dict[str, Any]:
        """Build answer chain for chat fallback."""
        steps = [
            {
                "title": "Capability Retrieval",
                "summary": "No high-confidence capability match found",
                "source": "Capability Catalog",
            },
            {
                "title": "Routing Decision",
                "summary": "Falling back to general chat",
                "source": "Capability Router",
            },
        ]

        return {
            "label": "Answer chain",
            "visibility": "technical" if context.user_is_admin else "masked",
            "steps": steps,
        }

    def _log_routing(
        self,
        context: RoutingContext,
        raw_message: str,
        scores: list[Any],
        decision: RoutingDecision,
    ) -> None:
        """Log routing decision for audit."""
        from ..domain.entities import CapabilityRoutingLog

        log = CapabilityRoutingLog(
            entrypoint=context.entrypoint,
            user_id=context.user_id,
            session_id=context.session_id,
            raw_message=raw_message,
            retrieved_candidates=[s.capability.capability_key for s in scores],
            selected_capability_key=decision.selected_capability_key,
            confidence=decision.confidence,
            decision=decision.decision,
            fallback_reason=""
            if decision.decision == CapabilityDecision.CAPABILITY
            else "low_confidence",
            execution_result=decision.reply[:500] if decision.reply else "",
        )

        try:
            self.routing_log_repo.save(log)
        except Exception:
            logger.exception("Failed to save routing log")

    def _build_response(
        self,
        decision: RoutingDecision,
        session_id: str,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Build response dict from decision."""
        suggested_command = None
        suggested_intent = None
        suggestion_prompt = None

        if (
            decision.decision == CapabilityDecision.ASK_CONFIRMATION
            and decision.selected_capability_key
        ):
            suggested_command = f"/{decision.selected_capability_key.split('.')[-1]}"
            suggested_intent = decision.selected_capability_key.split(".")[0]
            suggestion_prompt = f"检测到你可能想执行 {suggested_command}。输入 Y 执行，输入 N 取消，或继续输入其他内容。"

        return {
            "decision": decision.decision.value,
            "selected_capability_key": decision.selected_capability_key,
            "confidence": decision.confidence,
            "candidate_capabilities": decision.candidate_capabilities,
            "requires_confirmation": decision.requires_confirmation,
            "reply": decision.reply,
            "session_id": session_id,
            "metadata": decision.metadata,
            "answer_chain": decision.answer_chain if context.answer_chain_enabled else {},
            "suggested_command": suggested_command,
            "suggested_intent": suggested_intent,
            "suggestion_prompt": suggestion_prompt,
        }


__all__ = ["CapabilityRoutingFacade"]
