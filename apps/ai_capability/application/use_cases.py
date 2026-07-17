"""
AI Capability Catalog Application Use Cases.
"""

import json
import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.ai_capability.application.repository_provider import (
    DjangoCapabilityRepository,
    DjangoRoutingLogRepository,
    get_capability_execution_support_repository,
    get_confirmation_codec,
)
from apps.ai_provider.application.repository_provider import AIClientFactory
from apps.policy.application.repository_provider import get_current_policy_repository
from apps.prompt.application.runtime_provider import execute_builtin_tool
from apps.regime.application.current_regime import resolve_current_regime
from core.health_checks import is_healthy, run_readiness_checks

from ..application.dtos import (
    CapabilitySummaryDTO,
    RouteRequestDTO,
    RouteResponseDTO,
)
from ..domain.entities import (
    CapabilityDecision,
    CapabilityDefinition,
    CapabilityRoutingLog,
    RoutingContext,
    RoutingDecision,
    SourceType,
)
from ..domain.interfaces import ConfirmationCodecProtocol
from ..domain.services import (
    CapabilityFilter,
    CapabilityParameterPolicy,
    CapabilityRetrievalScorer,
    CapabilitySemanticDeduper,
)
from . import sync_use_cases as _sync_use_cases
from .mcp_runtime_gateway import call_sdk_mcp_tool as _call_sdk_mcp_tool
from .result_enrichment import enrich_security_names
from .terminal_gateway import get_terminal_capability_gateway

logger = logging.getLogger(__name__)

_list_sdk_mcp_capability_manifests = _sync_use_cases._list_sdk_mcp_capability_manifests
_list_sdk_mcp_core_tool_names = _sync_use_cases._list_sdk_mcp_core_tool_names
_list_sdk_mcp_tools = _sync_use_cases._list_sdk_mcp_tools


class SyncCapabilitiesUseCase(_sync_use_cases.SyncCapabilitiesUseCase):
    """Compatibility wrapper for tests and callers patching the legacy module path."""

    def _sync_mcp_tools(self) -> list[CapabilityDefinition]:
        original_manifest_loader = _sync_use_cases._list_sdk_mcp_capability_manifests
        original_core_names_loader = _sync_use_cases._list_sdk_mcp_core_tool_names
        original_tools_loader = _sync_use_cases._list_sdk_mcp_tools
        try:
            _sync_use_cases._list_sdk_mcp_capability_manifests = _list_sdk_mcp_capability_manifests
            _sync_use_cases._list_sdk_mcp_core_tool_names = _list_sdk_mcp_core_tool_names
            _sync_use_cases._list_sdk_mcp_tools = _list_sdk_mcp_tools
            return super()._sync_mcp_tools()
        finally:
            _sync_use_cases._list_sdk_mcp_capability_manifests = original_manifest_loader
            _sync_use_cases._list_sdk_mcp_core_tool_names = original_core_names_loader
            _sync_use_cases._list_sdk_mcp_tools = original_tools_loader


class _CapabilityRegimeAdapter:
    """Adapter for exposing regime queries to tool registry."""

    def get_current_regime(self, as_of_date=None):
        result = resolve_current_regime(as_of_date=as_of_date)
        return {
            "dominant_regime": result.dominant_regime,
            "confidence": result.confidence,
            "observed_at": result.observed_at.isoformat() if result.observed_at else None,
            "data_source": result.data_source,
            "warnings": result.warnings,
            "distribution": result.distribution or {},
            "is_fallback": result.is_fallback,
        }

    def get_regime_distribution(self, as_of_date=None):
        result = resolve_current_regime(as_of_date=as_of_date)
        return {
            "observed_at": result.observed_at.isoformat() if result.observed_at else None,
            "distribution": result.distribution or {},
            "dominant_regime": result.dominant_regime,
            "confidence": result.confidence,
            "data_source": result.data_source,
            "warnings": result.warnings,
            "is_fallback": result.is_fallback,
        }


_DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT = (
    "You are the AgomTradePro system assistant for an investment decision platform. "
    "Prioritize answers within AgomTradePro operational context, including system status, "
    "macro environment, market regime, policy level, portfolio, positions, signals, "
    "backtest, audit, AI provider configuration, terminal commands, RSS ingestion, "
    "policy news, hotspot events, and other system modules already present in the platform. "
    "If the user asks an ambiguous question such as recommendations, interpret it in this platform context first. "
    "Do not drift into unrelated lifestyle topics like fitness, travel, entertainment, or generic life coaching. "
    "If the request is underspecified, ask a short clarifying question tied to the platform context, "
    "or provide the most relevant system-oriented answer."
)


def _get_fallback_chat_system_prompt() -> str:
    settings_data = get_terminal_capability_gateway().get_runtime_settings()
    custom_prompt = str(settings_data.get("fallback_chat_system_prompt", "") or "").strip()
    return custom_prompt or _DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT


class CapabilityRegistryService:
    """System-level capability registry service."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        filter_service: CapabilityFilter | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.filter_service = filter_service or CapabilityFilter()
        self.semantic_deduper = CapabilitySemanticDeduper()

    def get_routable_capabilities(self, context: RoutingContext) -> list[CapabilityDefinition]:
        capabilities = self.capability_repo.get_all_for_routing()
        filtered = self.filter_service.filter_by_context(capabilities, context)
        return self._apply_entrypoint_source_policy(filtered, context)

    def _apply_entrypoint_source_policy(
        self,
        capabilities: list[CapabilityDefinition],
        context: RoutingContext,
    ) -> list[CapabilityDefinition]:
        """Apply entrypoint-specific source preference and MCP de-dup policy."""
        deduped = self.semantic_deduper.deduplicate(
            capabilities,
            entrypoint=context.entrypoint,
        )
        if context.entrypoint in {"web", "chat"}:
            non_mcp = [cap for cap in deduped if cap.source_type != SourceType.MCP_TOOL]
            if non_mcp:
                return non_mcp
            return []
        return deduped


class CapabilityRetrievalService:
    """Deterministic capability retrieval service."""

    def __init__(self, scorer: CapabilityRetrievalScorer | None = None):
        self.scorer = scorer or CapabilityRetrievalScorer()

    def retrieve(
        self,
        capabilities: list[CapabilityDefinition],
        message: str,
        k: int,
    ) -> list[Any]:
        return self.scorer.retrieve_top_k(capabilities, message, k=k)


class CapabilityDecisionService:
    """Structured routing decision service."""

    PATH_PARAM_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

    def __init__(
        self,
        high_confidence: float = 0.85,
        suggest_confidence: float = 0.60,
        parameter_policy: CapabilityParameterPolicy | None = None,
    ):
        self.high_confidence = high_confidence
        self.suggest_confidence = suggest_confidence
        self.parameter_policy = parameter_policy or CapabilityParameterPolicy()

    def decide(
        self,
        scores: list[Any],
        context: RoutingContext,
    ) -> dict[str, Any]:
        if not scores:
            return {
                "decision": CapabilityDecision.CHAT,
                "capability": None,
                "confidence": 0.0,
                "candidates": [],
                "reason": "No capability candidates matched the current message.",
                "rejected_candidates": [],
                "missing_params": [],
            }

        top_score = scores[0]
        capability = top_score.capability
        confidence = top_score.score / 10
        candidates = [score.capability.to_summary_dict() for score in scores]
        rejected_candidates = [score.capability.capability_key for score in scores[1:]]
        params = self.parameter_policy.normalize(
            capability,
            context.context.get("params", {}) or {},
            default_account_id=context.context.get("default_account_id"),
        )
        context.context["params"] = params
        missing_params = self._collect_missing_params(capability, params)

        if missing_params:
            return {
                "decision": CapabilityDecision.ASK_CONFIRMATION,
                "capability": capability,
                "confidence": confidence,
                "candidates": candidates,
                "reason": "Capability matched, but execution still needs required parameters.",
                "rejected_candidates": rejected_candidates,
                "missing_params": missing_params,
            }

        if capability.requires_confirmation:
            return {
                "decision": CapabilityDecision.ASK_CONFIRMATION,
                "capability": capability,
                "confidence": confidence,
                "candidates": candidates,
                "reason": "Capability matched but requires confirmation before execution.",
                "rejected_candidates": rejected_candidates,
                "missing_params": [],
            }

        if confidence >= self.high_confidence:
            return {
                "decision": CapabilityDecision.CAPABILITY,
                "capability": capability,
                "confidence": confidence,
                "candidates": candidates,
                "reason": "Top capability exceeded the execution confidence threshold.",
                "rejected_candidates": rejected_candidates,
                "missing_params": [],
            }

        if confidence >= self.suggest_confidence:
            return {
                "decision": CapabilityDecision.ASK_CONFIRMATION,
                "capability": capability,
                "confidence": confidence,
                "candidates": candidates,
                "reason": "Top capability is plausible but below the direct execution threshold.",
                "rejected_candidates": rejected_candidates,
                "missing_params": [],
            }

        return {
            "decision": CapabilityDecision.CHAT,
            "capability": capability,
            "confidence": confidence,
            "candidates": candidates,
            "reason": "No capability exceeded the routing confidence threshold.",
            "rejected_candidates": rejected_candidates,
            "missing_params": [],
        }

    def _collect_missing_params(
        self,
        capability: CapabilityDefinition,
        params: dict[str, Any],
    ) -> list[str]:
        missing: list[str] = []
        required = capability.input_schema.get("required", []) or []
        for name in required:
            if name not in params:
                missing.append(name)

        path = capability.execution_target.get("path", "")
        for name in self.PATH_PARAM_RE.findall(path):
            if name not in params and name not in missing:
                missing.append(name)
        return missing


class CapabilityExecutionDispatcher:
    """Execute selected capabilities through the correct backend."""

    PATH_PARAM_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
    PATH_SEGMENT_RE = re.compile(r"<(?:(?P<converter>[^:>]+):)?(?P<name>[^>]+)>")

    def __init__(self, parameter_policy: CapabilityParameterPolicy | None = None):
        self.parameter_policy = parameter_policy or CapabilityParameterPolicy()

    def dispatch(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
        context: RoutingContext,
    ) -> dict[str, Any]:
        context.context["params"] = self.parameter_policy.normalize(
            capability,
            context.context.get("params", {}) or {},
            default_account_id=context.context.get("default_account_id"),
        )
        if capability.source_type == SourceType.BUILTIN:
            return self._execute_builtin(capability)
        if capability.source_type == SourceType.TERMINAL_COMMAND:
            return self._execute_terminal_command(capability, request, context)
        if capability.source_type == SourceType.MCP_TOOL:
            return self._execute_mcp_tool(capability, context)
        if capability.source_type == SourceType.API:
            return self._execute_api(capability, context)
        return {"reply": f"Unknown capability type: {capability.source_type}"}

    def _execute_builtin(self, capability: CapabilityDefinition) -> dict[str, Any]:
        handler = capability.execution_target.get("handler")

        if handler == "system_status":
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

            return {
                "reply": "\n".join(
                    [
                        f"## System Readiness: `{overall}`",
                        _line("Database", checks.get("database", {})),
                        _line("Redis", checks.get("redis", {})),
                        _line("Celery", checks.get("celery", {})),
                        _line("Critical Data", checks.get("critical_data", {})),
                        f"- **Timestamp**: `{datetime.now(UTC).isoformat()}`",
                    ]
                )
            }

        if handler == "market_regime":
            regime = resolve_current_regime()
            policy_repo = get_current_policy_repository()
            policy = policy_repo.get_current_policy_level()
            return {
                "reply": "\n".join(
                    [
                        "## Current Market Regime",
                        f"- **Regime**: `{getattr(regime, 'dominant_regime', 'Unknown')}`",
                        f"- **Confidence**: `{(getattr(regime, 'confidence', 0) or 0) * 100:.1f}%`",
                        f"- **Source**: `{getattr(regime, 'source', 'N/A')}`",
                        f"- **Observed At**: `{getattr(regime, 'observed_at', 'N/A')}`",
                        f"- **Policy Level**: `{getattr(policy, 'value', 'N/A')}`",
                    ]
                )
            }

        return {"reply": f"Unknown builtin handler: {handler}"}

    def _execute_terminal_command(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
        context: RoutingContext,
    ) -> dict[str, Any]:
        command_name = capability.capability_key.split(".", 1)[-1]
        response = get_terminal_capability_gateway().execute_command(
            {
                "command_name": command_name,
                "params": context.context.get("params", {}) or {},
                "session_id": request.session_id,
                "provider_name": request.provider_name,
                "model_name": request.model,
                "user_id": context.user_id,
                "username": context.context.get("username", "unknown"),
                "user_role": context.context.get("user_role", "read_only"),
                "mcp_enabled": context.mcp_enabled,
                "terminal_mode": context.context.get("terminal_mode", "confirm_each"),
                "confirmation_token": context.context.get("confirmation_token"),
            }
        )
        if response.get("confirmation_required"):
            return {
                "reply": response.get("confirmation_prompt") or "",
                "confirmation_required": True,
            }
        if response.get("success"):
            metadata = response.get("metadata", {}) or {}
            return {
                "reply": response.get("output", ""),
                "metadata": metadata,
                "result": metadata.get("structured_output"),
            }
        metadata = response.get("metadata", {}) or {}
        return {
            "reply": response.get("error") or "Terminal command execution failed.",
            "missing_params": [
                item.get("name")
                for item in metadata.get("missing_params", [])
                if isinstance(item, dict) and item.get("name")
            ],
        }

    def _execute_mcp_tool(
        self,
        capability: CapabilityDefinition,
        context: RoutingContext,
    ) -> dict[str, Any]:
        target_type = capability.execution_target.get("type", "mcp_tool")
        tool_name = capability.execution_target.get("tool_name")
        params = context.context.get("params", {}) or {}
        call_params = params
        if target_type == "mcp_capability":
            call_params = {
                "capability_key": capability.execution_target.get("capability_key"),
                "arguments": params,
            }

        try:
            result = _call_sdk_mcp_tool(tool_name, call_params)
        except Exception:
            logger.exception(
                "SDK MCP tool execution failed for %s; falling back to builtin registry", tool_name
            )
            result = execute_builtin_tool(tool_name, params)

        result = enrich_security_names(result)

        reply = (
            json.dumps(result, indent=2, ensure_ascii=False)
            if isinstance(result, (dict, list))
            else str(result)
        )
        return {"reply": reply, "result": result}

    def _execute_api(
        self,
        capability: CapabilityDefinition,
        context: RoutingContext,
    ) -> dict[str, Any]:
        params = self.parameter_policy.normalize(
            capability,
            context.context.get("params", {}) or {},
            default_account_id=context.context.get("default_account_id"),
        )
        context.context["params"] = dict(params)
        path_template = capability.execution_target.get("path", "")
        path_segments = list(self.PATH_SEGMENT_RE.finditer(path_template))
        path_params = [match.group("name") for match in path_segments]
        missing = [name for name in path_params if name not in params]
        if missing:
            return {
                "reply": f"Missing required parameters: {', '.join(missing)}",
                "missing_params": missing,
            }

        path = path_template
        for segment in path_segments:
            name = segment.group("name")
            converter = segment.group("converter") or "str"
            value = params.pop(name)
            validation_error = self._validate_path_param(name, value, converter)
            if validation_error:
                return {
                    "reply": validation_error,
                    "missing_params": [name],
                }
            path = path.replace(segment.group(0), str(value), 1)

        factory = APIRequestFactory()
        method = capability.execution_target.get("method", "GET").upper()
        request_builder = getattr(factory, method.lower())
        request = (
            request_builder(f"/{path}", params, format="json")
            if method in {"GET", "HEAD", "OPTIONS"}
            else request_builder(f"/{path}", params, format="json")
        )

        if context.user_id:
            user = get_capability_execution_support_repository().get_user_by_id(context.user_id)
            if user is not None:
                force_authenticate(request, user=user)

        try:
            match = resolve(f"/{path}")
        except Resolver404:
            return {
                "reply": (f"无法执行该能力，请检查参数是否有效。" f"当前路径: /{path}"),
                "missing_params": [],
                "metadata": {"path": f"/{path}", "status_code": 404},
            }

        try:
            response = match.func(request, **match.kwargs)
            if hasattr(response, "render"):
                response.render()
        except Exception as exc:
            logger.exception("Capability API execution failed for path %s", path)
            return {
                "reply": f"能力执行失败: {str(exc)}",
                "missing_params": [],
                "metadata": {"path": f"/{path}", "status_code": 500},
            }

        payload = getattr(response, "data", None)
        if payload is None:
            payload = response.content.decode("utf-8")
        payload = enrich_security_names(payload)
        reply = (
            json.dumps(payload, indent=2, ensure_ascii=False)
            if isinstance(payload, (dict, list))
            else str(payload)
        )
        return {
            "reply": reply,
            "result": payload,
            "metadata": {"status_code": getattr(response, "status_code", 200)},
        }

    def _validate_path_param(self, name: str, value: Any, converter: str) -> str | None:
        if converter == "int":
            value_str = str(value).strip()
            if not value_str.isdigit():
                return (
                    f"参数 `{name}` 必须是整数。"
                    f"请输入实际 ID，例如 `1`；如果你想先查询可用 ID，请先取消当前操作再单独查询。"
                )
        return None


class RouteMessageUseCase:
    """Use case for routing messages through the capability catalog."""

    HIGH_CONFIDENCE_THRESHOLD = 0.85
    SUGGEST_CONFIDENCE_THRESHOLD = 0.60
    TOP_K_CANDIDATES = 5
    APPROVAL_MESSAGES = {"y", "yes", "确认", "同意", "批准", "执行"}
    REJECTION_MESSAGES = {"n", "no", "取消", "拒绝"}

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        routing_log_repo: DjangoRoutingLogRepository | None = None,
        confirmation_codec: ConfirmationCodecProtocol | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.routing_log_repo = routing_log_repo or DjangoRoutingLogRepository()
        self.registry = CapabilityRegistryService(self.capability_repo)
        self.retrieval = CapabilityRetrievalService()
        self.parameter_policy = CapabilityParameterPolicy()
        self.decision_service = CapabilityDecisionService(
            high_confidence=self.HIGH_CONFIDENCE_THRESHOLD,
            suggest_confidence=self.SUGGEST_CONFIDENCE_THRESHOLD,
            parameter_policy=self.parameter_policy,
        )
        self.dispatcher = CapabilityExecutionDispatcher(self.parameter_policy)
        self.confirmation_codec = confirmation_codec or get_confirmation_codec()

    def execute(self, request: RouteRequestDTO) -> RouteResponseDTO:
        """Execute routing for a message."""
        session_id = request.session_id or str(uuid.uuid4())

        context = RoutingContext(
            entrypoint=request.entrypoint,
            session_id=session_id,
            user_id=request.context.get("user_id"),
            user_is_admin=request.context.get("user_is_admin", False),
            mcp_enabled=request.context.get("mcp_enabled", True),
            provider_name=request.provider_name,
            model=request.model,
            context=request.context,
            answer_chain_enabled=request.context.get("answer_chain_enabled", False),
        )

        confirmation_id, approved = self._extract_confirmation_request(request)
        if confirmation_id:
            return self._resume_confirmation(
                request=request,
                session_id=session_id,
                context=context,
                confirmation_id=confirmation_id,
                approved=approved,
            )

        filtered = self.registry.get_routable_capabilities(context)
        scores = self.retrieval.retrieve(filtered, request.message, k=self.TOP_K_CANDIDATES)

        if not scores:
            return self._handle_no_candidates(request, session_id, context)

        decision_payload = self.decision_service.decide(scores, context)
        selected_capability = decision_payload["capability"]
        candidates = decision_payload["candidates"]
        rejected_candidates = decision_payload["rejected_candidates"]
        missing_params = decision_payload["missing_params"]
        reason = decision_payload["reason"]
        confidence = decision_payload["confidence"]

        if decision_payload["decision"] == CapabilityDecision.CAPABILITY and selected_capability:
            decision = self._build_capability_decision(
                selected_capability,
                candidates,
                confidence,
                request,
                context,
                reason=reason,
                rejected_candidates=rejected_candidates,
            )
        elif (
            decision_payload["decision"] == CapabilityDecision.ASK_CONFIRMATION
            and selected_capability
        ):
            decision = self._build_suggestion_decision(
                selected_capability,
                candidates,
                confidence,
                request,
                context,
                reason=reason,
                rejected_candidates=rejected_candidates,
                missing_params=missing_params,
            )
        else:
            decision = self._build_chat_decision(
                candidates,
                request,
                context,
                reason=reason,
                rejected_candidates=rejected_candidates,
            )

        self._log_routing(
            context=context,
            raw_message=request.message,
            scores=scores,
            decision=decision,
        )

        return self._build_response(decision, session_id, context)

    def _extract_confirmation_request(
        self,
        request: RouteRequestDTO,
    ) -> tuple[str | None, bool | None]:
        """Normalize explicit and context-carried confirmation requests."""

        confirmation = request.context.get("confirmation") or {}
        confirmation_id = request.confirmation_id
        approved = request.approved
        if isinstance(confirmation, dict):
            confirmation_id = confirmation_id or confirmation.get("confirmation_id")
            if approved is None and "approved" in confirmation:
                approved = bool(confirmation.get("approved"))

        normalized_message = request.message.strip().lower()
        if approved is None and normalized_message in self.APPROVAL_MESSAGES:
            approved = True
        elif approved is None and normalized_message in self.REJECTION_MESSAGES:
            approved = False
        return str(confirmation_id) if confirmation_id else None, approved

    def _resume_confirmation(
        self,
        *,
        request: RouteRequestDTO,
        session_id: str,
        context: RoutingContext,
        confirmation_id: str,
        approved: bool | None,
    ) -> RouteResponseDTO:
        """Execute the signed, locked capability without semantic re-routing."""

        try:
            payload = self.confirmation_codec.verify(confirmation_id)
        except ValueError as exc:
            return self._build_confirmation_terminal_response(
                session_id=session_id,
                context=context,
                reply=str(exc),
                reason="Confirmation verification failed.",
            )

        if payload.get("session_id") != session_id or payload.get("user_id") != context.user_id:
            return self._build_confirmation_terminal_response(
                session_id=session_id,
                context=context,
                reply="确认上下文与当前会话或用户不匹配，请重新发起请求。",
                reason="Confirmation context mismatch.",
            )
        if approved is not True:
            reply = "已取消上一项能力执行。" if approved is False else "请确认是否执行上一项能力。"
            return self._build_confirmation_terminal_response(
                session_id=session_id,
                context=context,
                reply=reply,
                reason="Confirmation was not approved.",
            )

        capability_key = str(payload.get("capability_key") or "")
        capability = self.capability_repo.get_by_key(capability_key)
        if capability is None:
            return self._build_confirmation_terminal_response(
                session_id=session_id,
                context=context,
                reply="待确认能力已不存在或已下线，请重新发起请求。",
                reason="Confirmed capability is unavailable.",
            )
        if not CapabilityFilter().filter_by_context([capability], context):
            raise PermissionError(
                f"Capability is not available in {context.entrypoint} for this user: {capability_key}"
            )

        supplied_params = dict(payload.get("normalized_params") or {})
        supplied_params.update(request.context.get("params", {}) or {})
        context.context["params"] = self.parameter_policy.normalize(
            capability,
            supplied_params,
            default_account_id=context.context.get("default_account_id"),
        )
        confirmed_capability = replace(capability, requires_confirmation=False)
        decision = self._build_capability_decision(
            confirmed_capability,
            [capability.to_summary_dict()],
            1.0,
            request,
            context,
            reason="User approved the signed pending capability.",
            rejected_candidates=[],
        )
        self._log_routing(
            context=context,
            raw_message=request.message,
            scores=[],
            decision=decision,
        )
        return self._build_response(decision, session_id, context)

    def _build_confirmation_terminal_response(
        self,
        *,
        session_id: str,
        context: RoutingContext,
        reply: str,
        reason: str,
    ) -> RouteResponseDTO:
        decision = RoutingDecision(
            decision=CapabilityDecision.CHAT,
            reply=reply,
            reason=reason,
            metadata={
                "route": "confirmation",
                "provider": "capability-router",
                "model": "router",
            },
        )
        return self._build_response(decision, session_id, context)

    def _handle_no_candidates(
        self,
        request: RouteRequestDTO,
        session_id: str,
        context: RoutingContext,
    ) -> RouteResponseDTO:
        """Handle case when no candidates are found."""
        decision = self._build_chat_decision([], request, context)

        self._log_routing(
            context=context,
            raw_message=request.message,
            scores=[],
            decision=decision,
        )

        return self._build_response(decision, session_id, context)

    def _build_capability_decision(
        self,
        capability: CapabilityDefinition,
        candidates: list[dict[str, Any]],
        confidence: float,
        request: RouteRequestDTO,
        context: RoutingContext,
        reason: str = "",
        rejected_candidates: list[str] | None = None,
    ) -> RoutingDecision:
        """Build decision for high-confidence capability match."""
        execution_result = self._execute_capability(capability, request, context)
        missing_params = execution_result.get("missing_params", [])
        if execution_result.get("confirmation_required") or missing_params:
            return self._build_suggestion_decision(
                capability,
                candidates,
                confidence,
                request,
                context,
                reason=reason or "Execution requires confirmation before proceeding.",
                rejected_candidates=rejected_candidates,
                missing_params=missing_params,
                execution_result=execution_result,
            )

        answer_chain = self._build_answer_chain(
            capability=capability,
            candidates=candidates,
            confidence=confidence,
            context=context,
            route="capability",
            reason=reason,
            rejected_candidates=rejected_candidates or [],
        )

        return RoutingDecision(
            decision=CapabilityDecision.CAPABILITY,
            selected_capability_key=capability.capability_key,
            confidence=confidence,
            candidate_capabilities=candidates,
            requires_confirmation=capability.requires_confirmation,
            reply=execution_result.get("reply", ""),
            reason=reason,
            rejected_candidates=rejected_candidates or [],
            filled_params=context.context.get("params", {}) or {},
            missing_params=missing_params,
            metadata={
                "route": "capability",
                "provider": "capability-router",
                "model": "router",
                "capability_name": capability.name,
                **(execution_result.get("metadata") or {}),
            },
            answer_chain=answer_chain,
            result=execution_result.get("result"),
        )

    def _build_suggestion_decision(
        self,
        capability: CapabilityDefinition,
        candidates: list[dict[str, Any]],
        confidence: float,
        request: RouteRequestDTO,
        context: RoutingContext,
        reason: str = "",
        rejected_candidates: list[str] | None = None,
        missing_params: list[str] | None = None,
        execution_result: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """Build decision for medium-confidence suggestion."""
        answer_chain = self._build_answer_chain(
            capability=capability,
            candidates=candidates,
            confidence=confidence,
            context=context,
            route="intent_suggestion",
            reason=reason,
            rejected_candidates=rejected_candidates or [],
        )

        missing_params = missing_params or []
        suggested_command = self._build_suggested_command(capability)
        if missing_params:
            reply = (
                f"检测到你可能想执行 {capability.name}，"
                f"但还缺少参数: {', '.join(missing_params)}。"
            )
        else:
            reply = (
                execution_result.get("reply")
                if execution_result and execution_result.get("reply")
                else f"检测到你可能想执行 {capability.name}。建议执行 `{suggested_command}`。"
            )

        return RoutingDecision(
            decision=CapabilityDecision.ASK_CONFIRMATION,
            selected_capability_key=capability.capability_key,
            confidence=confidence,
            candidate_capabilities=candidates,
            requires_confirmation=True,
            reply=reply,
            reason=reason,
            rejected_candidates=rejected_candidates or [],
            filled_params=context.context.get("params", {}) or {},
            missing_params=missing_params,
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
        request: RouteRequestDTO,
        context: RoutingContext,
        reason: str = "",
        rejected_candidates: list[str] | None = None,
    ) -> RoutingDecision:
        """Build decision for general chat."""
        reply = self._execute_chat(request, context)

        answer_chain = self._build_chat_answer_chain(context, reason=reason)

        return RoutingDecision(
            decision=CapabilityDecision.CHAT,
            selected_capability_key=None,
            confidence=0.0,
            candidate_capabilities=candidates,
            requires_confirmation=False,
            reply=reply,
            reason=reason,
            rejected_candidates=rejected_candidates or [],
            filled_params=context.context.get("params", {}) or {},
            metadata={
                "route": "chat",
                "provider": request.provider_name or "default",
                "model": request.model or "default",
            },
            answer_chain=answer_chain,
        )

    def _execute_capability(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
        context: RoutingContext,
    ) -> dict[str, Any]:
        """Execute a capability and return result."""
        return self.dispatcher.dispatch(capability, request, context)

    def _execute_builtin(self, capability: CapabilityDefinition) -> dict[str, Any]:
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
        policy_repo = get_current_policy_repository()
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
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
    ) -> dict[str, Any]:
        """Execute a terminal command capability."""
        return {"reply": f"Terminal command execution not implemented for {capability.name}"}

    def _execute_mcp_tool(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
    ) -> dict[str, Any]:
        """Execute an MCP tool capability."""
        return {"reply": f"MCP tool execution not implemented for {capability.name}"}

    def _execute_api(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
    ) -> dict[str, Any]:
        """Execute an internal API capability."""
        return {"reply": f"API execution not implemented for {capability.name}"}

    def _execute_chat(
        self,
        request: RouteRequestDTO,
        context: RoutingContext,
    ) -> str:
        """Execute general chat using AI provider."""
        try:
            ai_factory = AIClientFactory()
            ai_client = ai_factory.get_client(
                request.provider_name,
                user=context.user_id,
            )

            history = request.context.get("history", []) or []
            messages = [
                {
                    "role": "system",
                    "content": _get_fallback_chat_system_prompt(),
                }
            ]
            messages.extend(history)
            messages.append({"role": "user", "content": request.message})

            ai_response = ai_client.chat_completion(
                messages=messages,
                model=request.model,
            )

            if ai_response.get("status") != "success":
                return f"AI 调用失败: {ai_response.get('error_message', 'Unknown error')}"

            return ai_response.get("content", "")
        except Exception as e:
            logger.exception("Chat execution failed")
            return f"Chat execution failed: {str(e)}"

    def _build_answer_chain(
        self,
        capability: CapabilityDefinition,
        candidates: list[dict[str, Any]],
        confidence: float,
        context: RoutingContext,
        route: str,
        reason: str = "",
        rejected_candidates: list[str] | None = None,
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
                "summary": (
                    f"Selected {capability.name} with confidence {confidence:.2f}"
                    if not context.user_is_admin
                    else f"Selected {capability.capability_key} with confidence {confidence:.2f}"
                ),
                "source": "Capability Router",
            },
        ]
        if reason:
            steps[1]["summary"] += f". {reason}"

        if context.user_is_admin:
            steps[0]["technical_details"] = [
                f"candidates={[c['capability_key'] for c in candidates]}",
                f"top_score={confidence:.2f}",
                f"route={route}",
            ]
            if rejected_candidates:
                steps[1]["technical_details"] = [
                    f"rejected_candidates={rejected_candidates}",
                ]

        return {
            "label": "Answer chain",
            "visibility": "technical" if context.user_is_admin else "masked",
            "steps": steps,
        }

    def _build_chat_answer_chain(self, context: RoutingContext, reason: str = "") -> dict[str, Any]:
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
        if reason:
            steps[1]["summary"] += f". {reason}"

        return {
            "label": "Answer chain",
            "visibility": "technical" if context.user_is_admin else "masked",
            "steps": steps,
        }

    def _build_suggested_command(self, capability: CapabilityDefinition) -> str:
        if capability.capability_key == "builtin.system_status":
            return "/status"
        if capability.capability_key == "builtin.market_regime":
            return "/regime"
        return f"/{capability.capability_key.split('.')[-1]}"

    def _log_routing(
        self,
        context: RoutingContext,
        raw_message: str,
        scores: list[Any],
        decision: RoutingDecision,
    ) -> None:
        """Log routing decision for audit."""
        log = CapabilityRoutingLog(
            entrypoint=context.entrypoint,
            user_id=context.user_id,
            session_id=context.session_id,
            raw_message=raw_message,
            retrieved_candidates=[s.capability.capability_key for s in scores],
            selected_capability_key=decision.selected_capability_key,
            confidence=decision.confidence,
            decision=decision.decision,
            fallback_reason=(
                "" if decision.decision == CapabilityDecision.CAPABILITY else "low_confidence"
            ),
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
    ) -> RouteResponseDTO:
        """Build response DTO from decision."""
        suggested_command = None
        suggested_intent = None
        suggestion_prompt = None
        confirmation = None

        if (
            decision.decision == CapabilityDecision.ASK_CONFIRMATION
            and decision.selected_capability_key
        ):
            suggested_command = self._build_suggested_command(
                self.capability_repo.get_by_key(decision.selected_capability_key)
                or CapabilityDefinition(
                    capability_key=decision.selected_capability_key,
                    source_type=SourceType.BUILTIN,
                    source_ref="",
                    name=decision.selected_capability_key,
                    summary="",
                )
            )
            suggested_intent = decision.selected_capability_key.split(".")[-1]
            suggestion_prompt = f"检测到你可能想执行 {suggested_command}。输入 Y 执行，输入 N 取消，或继续输入其他内容。"
            normalized_params = self.parameter_policy.normalize(
                self.capability_repo.get_by_key(decision.selected_capability_key)
                or CapabilityDefinition(
                    capability_key=decision.selected_capability_key,
                    source_type=SourceType.BUILTIN,
                    source_ref="",
                    name=decision.selected_capability_key,
                    summary="",
                ),
                decision.filled_params,
                default_account_id=context.context.get("default_account_id"),
            )
            confirmation_id = self.confirmation_codec.issue(
                {
                    "session_id": session_id,
                    "user_id": context.user_id,
                    "capability_key": decision.selected_capability_key,
                    "normalized_params": normalized_params,
                }
            )
            confirmation = {
                "confirmation_id": confirmation_id,
                "capability_key": decision.selected_capability_key,
                "normalized_params": normalized_params,
                "expires_in_seconds": 300,
            }

        return RouteResponseDTO(
            decision=decision.decision.value,
            selected_capability_key=decision.selected_capability_key,
            confidence=decision.confidence,
            candidate_capabilities=decision.candidate_capabilities,
            requires_confirmation=decision.requires_confirmation,
            reply=decision.reply,
            session_id=session_id,
            metadata=decision.metadata,
            answer_chain=decision.answer_chain if context.answer_chain_enabled else {},
            reason=decision.reason,
            rejected_candidates=decision.rejected_candidates,
            filled_params=decision.filled_params,
            missing_params=decision.missing_params,
            suggested_command=suggested_command,
            suggested_intent=suggested_intent,
            suggestion_prompt=suggestion_prompt,
            confirmation=confirmation,
            result=decision.result,
        )


class GetCapabilityListUseCase:
    """Use case for getting capability list."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(
        self,
        source_type: str | None = None,
        route_group: str | None = None,
        category: str | None = None,
        enabled_only: bool = True,
    ) -> list[CapabilitySummaryDTO]:
        """Get list of capabilities."""
        capabilities = self.capability_repo.list_capabilities(
            source_type=source_type,
            route_group=route_group,
            category=category,
            enabled_only=enabled_only,
        )

        return [
            CapabilitySummaryDTO(
                capability_key=cap.capability_key,
                name=cap.name,
                summary=cap.summary,
                source_type=cap.source_type.value,
                route_group=cap.route_group.value,
                category=cap.category,
                risk_level=cap.risk_level.value,
                enabled_for_routing=cap.enabled_for_routing,
                requires_confirmation=cap.requires_confirmation,
            )
            for cap in capabilities
        ]


class GetCapabilityDetailUseCase:
    """Use case for getting a capability by key."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(self, capability_key: str) -> CapabilityDefinition | None:
        """Get a single capability definition."""
        return self.capability_repo.get_by_key(capability_key)


class GetCatalogStatsUseCase:
    """Use case for fetching catalog statistics."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()

    def execute(self) -> dict[str, Any]:
        """Get catalog statistics."""
        return self.capability_repo.get_stats()


__all__ = [
    "CapabilityRegistryService",
    "CapabilityRetrievalService",
    "CapabilityDecisionService",
    "CapabilityExecutionDispatcher",
    "RouteMessageUseCase",
    "GetCapabilityListUseCase",
    "GetCapabilityDetailUseCase",
    "GetCatalogStatsUseCase",
    "SyncCapabilitiesUseCase",
]
