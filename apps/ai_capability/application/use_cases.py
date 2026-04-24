"""
AI Capability Catalog Application Use Cases.
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from apps.terminal.infrastructure.repositories import get_terminal_runtime_settings_repository
from core.health_checks import is_healthy, run_readiness_checks

from ..application.dtos import (
    CapabilitySummaryDTO,
    RouteRequestDTO,
    RouteResponseDTO,
    SyncResultDTO,
)
from ..domain.entities import (
    CapabilityDecision,
    CapabilityDefinition,
    CapabilityRoutingLog,
    CapabilitySyncLog,
    RiskLevel,
    RouteGroup,
    RoutingContext,
    RoutingDecision,
    SourceType,
    Visibility,
)
from ..domain.services import (
    BuiltinCapabilityRegistry,
    CapabilityFilter,
    CapabilityRetrievalScorer,
)
from ..infrastructure.repositories import (
    DjangoCapabilityRepository,
    DjangoRoutingLogRepository,
    DjangoSyncLogRepository,
    get_capability_execution_support_repository,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "sdk"
_MCP_CONFIG_PATH = _REPO_ROOT / ".mcp.json"

_MCP_MUTATING_KEYWORDS = (
    "activate",
    "add",
    "approve",
    "backfill",
    "cancel",
    "close",
    "create",
    "deactivate",
    "delete",
    "disable",
    "enable",
    "execute",
    "export",
    "fix",
    "import",
    "open",
    "patch",
    "rebalance",
    "refresh",
    "reject",
    "remove",
    "repair",
    "reset",
    "rollback",
    "run",
    "save",
    "set",
    "submit",
    "sync",
    "trade",
    "update",
    "upsert",
    "write",
)


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


def _ensure_sdk_on_path() -> None:
    sdk_path = str(_SDK_ROOT)
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)


def _load_mcp_env_from_repo_config() -> None:
    if not _MCP_CONFIG_PATH.exists():
        return

    try:
        payload = json.loads(_MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load MCP config from %s", _MCP_CONFIG_PATH)
        return

    server_conf = (payload.get("mcpServers") or {}).get("agomtradepro_local") or {}
    for key, value in (server_conf.get("env") or {}).items():
        if value is not None:
            os.environ.setdefault(str(key), str(value))


def _list_sdk_mcp_tools() -> list[Any]:
    _ensure_sdk_on_path()
    from agomtradepro_mcp.server import server

    return asyncio.run(server.list_tools())


def _call_sdk_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    _ensure_sdk_on_path()
    _load_mcp_env_from_repo_config()
    from agomtradepro_mcp.server import server

    return asyncio.run(server.call_tool(tool_name, params))


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
    settings_data = get_terminal_runtime_settings_repository().get_settings()
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

    def get_routable_capabilities(self, context: RoutingContext) -> list[CapabilityDefinition]:
        capabilities = self.capability_repo.get_all_for_routing()
        return self.filter_service.filter_by_context(capabilities, context)


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

    def __init__(self, high_confidence: float = 0.85, suggest_confidence: float = 0.60):
        self.high_confidence = high_confidence
        self.suggest_confidence = suggest_confidence

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
        params = context.context.get("params", {}) or {}
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

    def dispatch(
        self,
        capability: CapabilityDefinition,
        request: RouteRequestDTO,
        context: RoutingContext,
    ) -> dict[str, Any]:
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
            policy_repo = DjangoPolicyRepository()
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
        from apps.terminal.application.services import CommandExecutionService
        from apps.terminal.application.use_cases import ExecuteCommandRequest, ExecuteCommandUseCase
        from apps.terminal.infrastructure.repositories import (
            get_terminal_audit_repository,
            get_terminal_command_repository,
        )

        command_name = capability.capability_key.split(".", 1)[-1]
        use_case = ExecuteCommandUseCase(
            repository=get_terminal_command_repository(),
            execution_service=CommandExecutionService(),
            audit_repository=get_terminal_audit_repository(),
        )
        response = use_case.execute(
            ExecuteCommandRequest(
                command_name=command_name,
                params=context.context.get("params", {}) or {},
                session_id=request.session_id,
                provider_name=request.provider_name,
                model_name=request.model,
                user_id=context.user_id,
                username=context.context.get("username", "unknown"),
                user_role=context.context.get("user_role", "read_only"),
                mcp_enabled=context.mcp_enabled,
                terminal_mode=context.context.get("terminal_mode", "confirm_each"),
                confirmation_token=context.context.get("confirmation_token"),
            )
        )
        if response.confirmation_required:
            return {
                "reply": response.confirmation_prompt or "",
                "confirmation_required": True,
            }
        if response.success:
            return {"reply": response.output, "metadata": response.metadata}
        return {
            "reply": response.error or "Terminal command execution failed.",
            "missing_params": [
                item.get("name")
                for item in response.metadata.get("missing_params", [])
                if isinstance(item, dict) and item.get("name")
            ],
        }

    def _execute_mcp_tool(
        self,
        capability: CapabilityDefinition,
        context: RoutingContext,
    ) -> dict[str, Any]:
        tool_name = capability.execution_target.get("tool_name")
        params = context.context.get("params", {}) or {}

        try:
            result = _call_sdk_mcp_tool(tool_name, params)
        except Exception:
            logger.exception("SDK MCP tool execution failed for %s; falling back to builtin registry", tool_name)
            from apps.macro.infrastructure.adapters.akshare_adapter import AKShareAdapter
            from apps.prompt.infrastructure.adapters.function_registry import create_builtin_tools

            registry = create_builtin_tools(AKShareAdapter(), _CapabilityRegimeAdapter())
            result = registry.execute(tool_name, params)

        reply = json.dumps(result, indent=2, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
        return {"reply": reply}

    def _execute_api(
        self,
        capability: CapabilityDefinition,
        context: RoutingContext,
    ) -> dict[str, Any]:
        params = dict(context.context.get("params", {}) or {})
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
                "reply": (
                    f"无法执行该能力，请检查参数是否有效。"
                    f"当前路径: /{path}"
                ),
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
        reply = json.dumps(payload, indent=2, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
        return {
            "reply": reply,
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

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        routing_log_repo: DjangoRoutingLogRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.routing_log_repo = routing_log_repo or DjangoRoutingLogRepository()
        self.registry = CapabilityRegistryService(self.capability_repo)
        self.retrieval = CapabilityRetrievalService()
        self.decision_service = CapabilityDecisionService(
            high_confidence=self.HIGH_CONFIDENCE_THRESHOLD,
            suggest_confidence=self.SUGGEST_CONFIDENCE_THRESHOLD,
        )
        self.dispatcher = CapabilityExecutionDispatcher()

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
        elif decision_payload["decision"] == CapabilityDecision.ASK_CONFIRMATION and selected_capability:
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
            },
            answer_chain=answer_chain,
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
            messages = [{
                "role": "system",
                "content": _get_fallback_chat_system_prompt(),
            }]
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
    ) -> RouteResponseDTO:
        """Build response DTO from decision."""
        suggested_command = None
        suggested_intent = None
        suggestion_prompt = None

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


class SyncCapabilitiesUseCase:
    """Use case for synchronizing capabilities from sources."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        sync_log_repo: DjangoSyncLogRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.sync_log_repo = sync_log_repo or DjangoSyncLogRepository()

    def execute(self, sync_type: str = "full", source: str | None = None) -> SyncResultDTO:
        """Execute capability synchronization."""
        start_time = time.time()
        started_at = datetime.now(UTC)

        total_discovered = 0
        created_count = 0
        updated_count = 0
        disabled_count = 0
        error_count = 0
        summary = {}

        try:
            sources = {
                "builtin": self._sync_builtin,
                "terminal_command": self._sync_terminal_commands,
                "mcp_tool": self._sync_mcp_tools,
                "api": self._sync_apis,
            }
            source_names = [source] if source else list(sources.keys())

            for source_name in source_names:
                sync_func = sources[source_name]
                capabilities = sync_func()
                total_discovered += len(capabilities)
                result = self.capability_repo.bulk_upsert(capabilities)
                created_count += result["created"]
                updated_count += result["updated"]
                disabled = self.capability_repo.disable_missing(
                    source_name,
                    [cap.capability_key for cap in capabilities],
                )
                disabled_count += disabled
                summary[source_name] = {**result, "disabled": disabled}

        except Exception as e:
            logger.exception("Capability sync failed")
            error_count += 1
            summary["error"] = str(e)

        finished_at = datetime.now(UTC)
        duration = time.time() - start_time

        sync_log = CapabilitySyncLog(
            sync_type=sync_type,
            started_at=started_at,
            finished_at=finished_at,
            total_discovered=total_discovered,
            created_count=created_count,
            updated_count=updated_count,
            disabled_count=disabled_count,
            error_count=error_count,
            summary_payload=summary,
        )
        self.sync_log_repo.save(sync_log)

        return SyncResultDTO(
            sync_type=sync_type,
            total_discovered=total_discovered,
            created_count=created_count,
            updated_count=updated_count,
            disabled_count=disabled_count,
            error_count=error_count,
            duration_seconds=duration,
            summary=summary,
        )

    def _sync_builtin(self) -> list[CapabilityDefinition]:
        """Sync builtin capabilities."""
        capabilities = []
        for cap_data in BuiltinCapabilityRegistry.get_all():
            cap = CapabilityDefinition.from_dict(cap_data)
            capabilities.append(cap)
        return capabilities

    def _sync_terminal_commands(self) -> list[CapabilityDefinition]:
        """Sync terminal commands."""
        from apps.terminal.infrastructure.repositories import get_terminal_command_repository

        capabilities = []
        commands = get_terminal_command_repository().get_all_active()

        for cmd in commands:
            cap = CapabilityDefinition(
                capability_key=f"terminal_command.{cmd.name}",
                source_type=SourceType.TERMINAL_COMMAND,
                source_ref=str(cmd.pk),
                name=cmd.name,
                summary=cmd.description or f"Terminal command: {cmd.name}",
                description=cmd.description,
                route_group=RouteGroup.TOOL,
                category=cmd.category,
                tags=cmd.tags or [],
                when_to_use=[],
                when_not_to_use=[],
                examples=[],
                input_schema={},
                execution_target={
                    "type": "terminal_command",
                    "command_id": str(cmd.pk),
                },
                risk_level=self._map_risk_level(cmd.risk_level),
                requires_mcp=cmd.requires_mcp,
                requires_confirmation=cmd.risk_level in ("write_high", "admin"),
                enabled_for_routing=cmd.enabled_in_terminal,
                enabled_for_terminal=True,
                enabled_for_chat=False,
                enabled_for_agent=True,
                auto_collected=True,
                review_status="auto",
            )
            capabilities.append(cap)

        return capabilities

    def _map_risk_level(self, terminal_risk: str) -> str:
        """Map terminal risk level to capability risk level."""
        mapping = {
            "read": "safe",
            "write_low": "low",
            "write_high": "high",
            "admin": "critical",
        }
        return mapping.get(terminal_risk, "medium")

    def _classify_mcp_tool(self, tool_name: str) -> tuple[RiskLevel, bool, bool]:
        normalized = (tool_name or "").lower()
        is_mutating = any(keyword in normalized for keyword in _MCP_MUTATING_KEYWORDS)
        if is_mutating:
            return (RiskLevel.HIGH, True, False)
        return (RiskLevel.LOW, True, True)

    def _sync_mcp_tools(self) -> list[CapabilityDefinition]:
        """Sync MCP tools."""
        capabilities = []

        try:
            for tool in _list_sdk_mcp_tools():
                risk_level, requires_confirmation, enabled_for_routing = self._classify_mcp_tool(
                    tool.name
                )
                cap = CapabilityDefinition(
                    capability_key=f"mcp_tool.{tool.name}",
                    source_type=SourceType.MCP_TOOL,
                    source_ref=tool.name,
                    name=tool.name,
                    summary=tool.description,
                    description=tool.description,
                    route_group=RouteGroup.TOOL,
                    category="mcp",
                    tags=["mcp", "tool"],
                    when_to_use=[],
                    when_not_to_use=[],
                    examples=[],
                    input_schema=getattr(tool, "inputSchema", {}) or {},
                    execution_target={
                        "type": "mcp_tool",
                        "tool_name": tool.name,
                    },
                    risk_level=risk_level,
                    requires_mcp=True,
                    requires_confirmation=requires_confirmation,
                    enabled_for_routing=enabled_for_routing,
                    enabled_for_terminal=True,
                    enabled_for_chat=True,
                    enabled_for_agent=True,
                    visibility=Visibility.ADMIN,
                    auto_collected=True,
                    review_status="auto",
                )
                capabilities.append(cap)
        except Exception as e:
            logger.warning(f"Failed to sync MCP tools: {e}")

        return capabilities

    def _sync_apis(self) -> list[CapabilityDefinition]:
        """Sync internal APIs."""
        from ..infrastructure.collectors.api_collector import ApiCapabilityCollector

        collector = ApiCapabilityCollector()
        return collector.collect()


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
