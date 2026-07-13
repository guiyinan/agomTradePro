"""OpenAI Agents SDK backed terminal agent service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentChatRequestDTO,
    TerminalAgentChatResponseDTO,
    TerminalAgentEventDTO,
    TerminalAgentService,
    TerminalCapabilityGateway,
)
from apps.ai_provider.infrastructure.repositories import (
    AIProviderRepository,
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)

logger = logging.getLogger(__name__)

AUTO_APPROVED_RISKS = {"safe", "low"}
APPROVAL_REQUIRED_RISKS = {"medium", "high", "critical"}
TERMINAL_AGENT_NAME = "AgomTradePro Terminal Agent"
TERMINAL_AGENT_MCP_SERVER_NAME = "agomtradepro"
TERMINAL_AGENT_CORE_MCP_TOOLS = frozenset(
    {
        "agom_bootstrap",
        "agom_capability_search",
        "agom_capability_schema",
        "agom_capability_call",
        "agom_confirmation_resume",
        "agom_workflow_start",
        "agom_workflow_status",
    }
)
# Some task-monitor tools take ~15-20s on local data and the model may queue
# several MCP calls in one turn, so keep the stdio client timeout comfortably
# above the default 5s SDK value.
TERMINAL_AGENT_MCP_CLIENT_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True)
class _ResolvedProvider:
    provider: Any
    api_key: str
    model: str
    provider_scope: str
    quota_charged: bool
    fallback_used: bool
    user: Any | None


@dataclass(frozen=True)
class _ToolAccessSnapshot:
    auto_allowed: dict[str, dict[str, Any]]
    gated: dict[str, dict[str, Any]]
    allowed_tool_names: frozenset[str]


class OpenAIAgentsTerminalService(TerminalAgentService):
    """Terminal agent service that delegates execution to Agents SDK + MCP."""

    def __init__(
        self,
        *,
        capability_gateway: TerminalCapabilityGateway | None = None,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._capability_gateway = capability_gateway
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository(usage_repo=self._usage_repo)

    def run_chat(self, request: TerminalAgentChatRequestDTO) -> TerminalAgentChatResponseDTO:
        """Execute a non-stream terminal chat request."""

        events = list(self.stream_chat(request))
        reply_parts: list[str] = []
        metadata: dict[str, Any] = {}

        for event in events:
            if event.event_type == "message_delta":
                reply_parts.append(str(event.data.get("delta") or ""))
            elif event.event_type == "approval_required":
                metadata = {
                    **dict(event.data),
                    "status": "approval_required",
                }
                return TerminalAgentChatResponseDTO(
                    reply=str(event.data.get("message") or ""),
                    session_id=request.session_id,
                    metadata=metadata,
                )
            elif event.event_type == "error":
                raise RuntimeError(str(event.data.get("message") or "Terminal agent failed"))
            elif event.event_type == "final":
                metadata = dict(event.data.get("metadata") or {})
                final_reply = str(event.data.get("reply") or "")
                if final_reply:
                    return TerminalAgentChatResponseDTO(
                        reply=final_reply,
                        session_id=request.session_id,
                        metadata=metadata,
                    )

        return TerminalAgentChatResponseDTO(
            reply="".join(reply_parts),
            session_id=request.session_id,
            metadata=metadata,
        )

    def stream_chat(self, request: TerminalAgentChatRequestDTO):
        """Yield normalized agent events for one request."""

        tool_access = self._build_tool_access_snapshot(request)
        gated_match = self._match_gated_tool(request, tool_access)
        if gated_match is not None:
            yield TerminalAgentEventDTO(
                event_type="approval_required",
                data={
                    "session_id": request.session_id,
                    "message": (
                        "该操作涉及受控 MCP 工具，当前不会自动执行。"
                        " 请进入审批流程后再继续。"
                    ),
                    **gated_match,
                },
            )
            return

        resolved_provider = self._resolve_provider(request)
        events = asyncio.run(self._collect_events(request, resolved_provider, tool_access))
        self._log_terminal_run(
            request=request,
            resolved_provider=resolved_provider,
            events=events,
        )
        yield from events

    async def _collect_events(
        self,
        request: TerminalAgentChatRequestDTO,
        resolved_provider: _ResolvedProvider,
        tool_access: _ToolAccessSnapshot,
    ) -> list[TerminalAgentEventDTO]:
        result_events: list[TerminalAgentEventDTO] = []

        try:
            sdk = self._import_agents_sdk()
            session = self._build_agent_session(sdk, request.session_id)
            async with self._build_mcp_server(sdk, request, tool_access) as mcp_server:
                agent = self._build_agent(
                    sdk=sdk,
                    request=request,
                    resolved_provider=resolved_provider,
                    tool_access=tool_access,
                    mcp_server=mcp_server,
                )
                streamed = sdk["Runner"].run_streamed(
                    starting_agent=agent,
                    input=request.message,
                    session=session,
                )
                async for event in streamed.stream_events():
                    result_events.extend(self._map_stream_event(event))

                final_reply = self._stringify(getattr(streamed, "final_output", ""))
                usage = self._extract_usage(streamed)
                metadata = self._build_final_metadata(
                    request=request,
                    resolved_provider=resolved_provider,
                    usage=usage,
                    tool_events=result_events,
                )
                result_events.append(
                    TerminalAgentEventDTO(
                        event_type="final",
                        data={
                            "reply": final_reply,
                            "session_id": request.session_id,
                            "metadata": metadata,
                        },
                    )
                )
                return result_events
        except Exception as exc:
            logger.exception("Terminal agent execution failed")
            return [
                TerminalAgentEventDTO(
                    event_type="error",
                    data={
                        "session_id": request.session_id,
                        "message": str(exc),
                    },
                )
            ]

    def _import_agents_sdk(self) -> dict[str, Any]:
        """Lazy-import Agents SDK types so the module can load without the dependency."""

        from agents import (
            Agent,
            Runner,
            set_default_openai_api,
            set_default_openai_client,
            set_tracing_disabled,
        )
        from agents.mcp import MCPServerStdio
        from openai import AsyncOpenAI

        session_cls = None
        for module_name, attr_name in (
            ("agents.memory.session", "SQLiteSession"),
            ("agents.memory.session", "AdvancedSQLiteSession"),
            ("agents.memory", "SQLiteSession"),
            ("agents.memory", "AdvancedSQLiteSession"),
        ):
            try:
                module = __import__(module_name, fromlist=[attr_name])
                session_cls = getattr(module, attr_name)
                break
            except (ImportError, AttributeError):
                continue

        set_tracing_disabled(True)
        return {
            "Agent": Agent,
            "Runner": Runner,
            "MCPServerStdio": MCPServerStdio,
            "AsyncOpenAI": AsyncOpenAI,
            "set_default_openai_api": set_default_openai_api,
            "set_default_openai_client": set_default_openai_client,
            "SessionClass": session_cls,
        }

    def _build_agent_session(self, sdk: dict[str, Any], session_id: str) -> Any | None:
        """Create a reusable SDK session when the dependency exposes one."""

        session_cls = sdk.get("SessionClass")
        if session_cls is None:
            return None

        session_dir = Path("var") / "agent_runtime"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_db = session_dir / "terminal_agent_sessions.sqlite3"

        try:
            return session_cls(
                session_id=session_id,
                db_path=str(session_db),
            )
        except TypeError:
            try:
                return session_cls(
                    session_id=session_id,
                    sqlite_path=str(session_db),
                )
            except TypeError:
                return None

    def _build_agent(
        self,
        *,
        sdk: dict[str, Any],
        request: TerminalAgentChatRequestDTO,
        resolved_provider: _ResolvedProvider,
        tool_access: _ToolAccessSnapshot,
        mcp_server: Any,
    ) -> Any:
        """Construct the SDK agent instance."""

        openai_client = sdk["AsyncOpenAI"](
            api_key=resolved_provider.api_key,
            base_url=resolved_provider.provider.base_url,
        )
        sdk["set_default_openai_client"](openai_client, use_for_tracing=False)
        sdk["set_default_openai_api"]("chat_completions")
        return sdk["Agent"](
            name=TERMINAL_AGENT_NAME,
            instructions=self._build_agent_instructions(request, tool_access),
            model=resolved_provider.model,
            mcp_servers=[mcp_server],
            mcp_config={
                "convert_schemas_to_strict": True,
                "include_server_in_tool_names": True,
            },
        )

    def _build_mcp_server(
        self,
        sdk: dict[str, Any],
        request: TerminalAgentChatRequestDTO,
        tool_access: _ToolAccessSnapshot,
    ) -> Any:
        """Construct the stdio MCP server wrapper."""

        env = os.environ.copy()
        repo_root = Path(__file__).resolve().parents[3]
        sdk_root = str((repo_root / "sdk").resolve())
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = sdk_root if not existing else f"{sdk_root}{os.pathsep}{existing}"
        env.setdefault("AGOMTRADEPRO_BASE_URL", "http://127.0.0.1:8000")
        env["AGOMTRADEPRO_INTERNAL_AUTH_SECRET"] = getattr(
            settings,
            "AGOMTRADEPRO_INTERNAL_AUTH_SECRET",
            "",
        )
        env["AGOMTRADEPRO_INTERNAL_USER_ID"] = str(request.user_id or "")
        env["AGOMTRADEPRO_INTERNAL_USERNAME"] = request.username
        env["AGOMTRADEPRO_INTERNAL_SOURCE"] = "terminal_mcp"
        return sdk["MCPServerStdio"](
            cache_tools_list=True,
            client_session_timeout_seconds=TERMINAL_AGENT_MCP_CLIENT_TIMEOUT_SECONDS,
            name=TERMINAL_AGENT_MCP_SERVER_NAME,
            tool_filter=self._build_tool_filter(tool_access.allowed_tool_names),
            params={
                "command": sys.executable,
                "args": ["-m", "agomtradepro_mcp.server"],
                "env": env,
            }
        )

    def _build_tool_filter(self, allowed_tool_names: frozenset[str]):
        """Build a tool filter that only exposes auto-approved MCP tools."""

        allowed_names = set(allowed_tool_names)

        def _filter(_context: Any, tool: Any) -> bool:
            runtime_name = str(getattr(tool, "name", "") or "")
            if runtime_name in allowed_names:
                return True
            normalized_name = runtime_name.split(".")[-1].split(":")[-1]
            if normalized_name in allowed_names:
                return True
            return any(runtime_name.endswith(f"_{name}") for name in allowed_names)

        return _filter

    def _build_agent_instructions(
        self,
        request: TerminalAgentChatRequestDTO,
        tool_access: _ToolAccessSnapshot,
    ) -> str:
        """Build prompt instructions for the terminal agent."""

        safe_tool_names = ", ".join(
            sorted(
                str(item.get("display_name") or key)
                for key, item in tool_access.auto_allowed.items()
            )
        ) or "none"
        gated_tool_names = ", ".join(
            sorted(
                str(item.get("display_name") or key)
                for key, item in tool_access.gated.items()
            )
        ) or "none"
        return (
            "You are the AgomTradePro terminal agent. "
            "Use MCP tools when they are available and necessary, keep answers concise, "
            "and never invent tool results.\n"
            f"Current user: {request.username} ({request.user_role}).\n"
            f"Auto-approved MCP capabilities/tools: {safe_tool_names}.\n"
            f"Gated MCP capabilities/tools not available without approval: {gated_tool_names}.\n"
            "If a gated action would be required, explain that explicit approval is needed.\n"
            "Prefer grounded tool-backed answers over generic speculation."
        )

    def _build_tool_access_snapshot(
        self,
        request: TerminalAgentChatRequestDTO,
    ) -> _ToolAccessSnapshot:
        """Resolve the current user's MCP tool visibility and risk gating."""

        if self._capability_gateway is None:
            return _ToolAccessSnapshot(
                auto_allowed={},
                gated={},
                allowed_tool_names=frozenset(),
            )

        visible = self._capability_gateway.list_terminal_mcp_capabilities(
            session_id=request.session_id,
            user_id=request.user_id,
            user_is_admin=request.user_is_admin,
            mcp_enabled=request.mcp_enabled,
            provider_name=str(request.provider_ref or ""),
            model=request.model,
            context=dict(request.context),
        )

        auto_allowed: dict[str, dict[str, Any]] = {}
        gated: dict[str, dict[str, Any]] = {}
        raw_tool_names: set[str] = set()
        has_governed_capabilities = False
        for capability in visible:
            target = dict(capability.get("execution_target") or {})
            target_type = str(target.get("type") or "mcp_tool")
            tool_name = str(target.get("tool_name") or capability.get("source_ref") or "").strip()
            if not tool_name:
                continue
            if target_type == "mcp_capability":
                has_governed_capabilities = True
                display_name = str(capability.get("capability_key") or "")
            else:
                raw_tool_names.add(tool_name)
                display_name = tool_name
            risk_level = str(capability.get("risk_level") or "low")
            payload = {
                "capability_key": str(capability.get("capability_key") or ""),
                "tool_name": tool_name,
                "display_name": display_name,
                "execution_target_type": target_type,
                "risk_level": risk_level,
                "summary": str(capability.get("summary") or ""),
            }
            if risk_level in AUTO_APPROVED_RISKS:
                auto_allowed[display_name] = payload
            else:
                gated[display_name] = payload

        allowed_tool_names = (
            TERMINAL_AGENT_CORE_MCP_TOOLS if has_governed_capabilities else frozenset(raw_tool_names)
        )
        return _ToolAccessSnapshot(
            auto_allowed=auto_allowed,
            gated=gated,
            allowed_tool_names=allowed_tool_names,
        )

    def _match_gated_tool(
        self,
        request: TerminalAgentChatRequestDTO,
        tool_access: _ToolAccessSnapshot,
    ) -> dict[str, Any] | None:
        """Detect whether the user is explicitly asking for a gated MCP tool."""

        if not tool_access.gated:
            return None

        if self._capability_gateway is None:
            return None

        matched = self._capability_gateway.match_terminal_mcp_capability(
            message=request.message,
            capability_keys=[
                str(payload.get("capability_key") or "")
                for payload in tool_access.gated.values()
                if str(payload.get("capability_key") or "")
            ],
        )
        if matched is None:
            return None

        matched_key = str(matched.get("capability_key") or "")
        for payload in tool_access.gated.values():
            if payload["capability_key"] == matched_key:
                return dict(payload)
        return None

    def _resolve_provider(self, request: TerminalAgentChatRequestDTO) -> _ResolvedProvider:
        """Resolve one provider using the existing personal/fallback semantics."""

        user = self._resolve_user(request.user_id)
        explicit = self._provider_repo.get_provider_for_reference(request.provider_ref, user=user)

        if user is None:
            candidates = (
                [explicit]
                if explicit is not None and self._provider_repo.has_usable_api_key(explicit)
                else self._provider_repo.get_active_configured_system_providers()
            )
            for provider in candidates:
                if provider is None or not self._provider_budget_allows(provider):
                    continue
                return _ResolvedProvider(
                    provider=provider,
                    api_key=self._provider_repo.get_api_key(provider),
                    model=str(request.model or provider.default_model),
                    provider_scope="system_global",
                    quota_charged=False,
                    fallback_used=False,
                    user=None,
                )
            raise RuntimeError("No active AI providers configured")

        personal = self._provider_repo.get_active_configured_user_providers(user)
        system = self._provider_repo.get_active_configured_system_providers()

        if explicit is not None and getattr(explicit, "scope", "") == "user":
            personal = self._move_provider_to_front(personal, explicit.id)
        if explicit is not None and getattr(explicit, "scope", "") == "system":
            system = self._move_provider_to_front(system, explicit.id)

        for provider in personal:
            if not self._provider_budget_allows(provider):
                continue
            return _ResolvedProvider(
                provider=provider,
                api_key=self._provider_repo.get_api_key(provider),
                model=str(request.model or provider.default_model),
                provider_scope="personal",
                quota_charged=False,
                fallback_used=False,
                user=user,
            )

        quota_status = self._get_fallback_quota_status(user)
        if system and not quota_status["allowed"]:
            raise RuntimeError(str(quota_status["message"]))

        for provider in system:
            if not self._provider_budget_allows(provider):
                continue
            return _ResolvedProvider(
                provider=provider,
                api_key=self._provider_repo.get_api_key(provider),
                model=str(request.model or provider.default_model),
                provider_scope="system_fallback",
                quota_charged=True,
                fallback_used=bool(personal),
                user=user,
            )

        raise RuntimeError("No available AI providers")

    def _resolve_user(self, user_id: int | None) -> Any | None:
        """Resolve one Django user for provider selection."""

        if user_id is None:
            return None
        user_model = get_user_model()
        try:
            return user_model._default_manager.get(pk=user_id)
        except user_model.DoesNotExist:
            return None

    def _move_provider_to_front(self, providers: list[Any], provider_id: int) -> list[Any]:
        """Return a copy with the chosen provider moved to the front."""

        selected = [provider for provider in providers if getattr(provider, "id", None) == provider_id]
        others = [provider for provider in providers if getattr(provider, "id", None) != provider_id]
        return selected + others

    def _provider_budget_allows(self, provider: Any) -> bool:
        """Check the existing provider-level budget guard."""

        budget = self._usage_repo.check_budget_limits(
            provider.id,
            float(provider.daily_budget_limit) if provider.daily_budget_limit is not None else None,
            float(provider.monthly_budget_limit)
            if provider.monthly_budget_limit is not None
            else None,
        )
        return not budget["daily"]["exceeded"] and not budget["monthly"]["exceeded"]

    def _get_fallback_quota_status(self, user: Any) -> dict[str, Any]:
        """Reuse the existing system fallback quota semantics."""

        quota, daily_spent, monthly_spent = self._quota_repo.get_with_usage(user)
        if quota is None or not quota.is_active:
            return {
                "allowed": False,
                "message": "System fallback quota is not configured for this user.",
            }
        daily_limit = float(quota.daily_limit) if quota.daily_limit is not None else None
        monthly_limit = float(quota.monthly_limit) if quota.monthly_limit is not None else None
        if daily_limit is not None and daily_spent >= daily_limit:
            return {
                "allowed": False,
                "message": "System fallback quota exhausted for today.",
            }
        if monthly_limit is not None and monthly_spent >= monthly_limit:
            return {
                "allowed": False,
                "message": "System fallback quota exhausted for this month.",
            }
        return {"allowed": True, "message": "Fallback quota available."}

    def _map_stream_event(self, event: Any) -> list[TerminalAgentEventDTO]:
        """Map SDK streaming events to the fixed terminal SSE event contract."""

        mapped: list[TerminalAgentEventDTO] = []
        event_type = str(getattr(event, "type", "") or "")
        event_name = str(getattr(event, "name", "") or "")

        if event_type == "raw_response_event":
            raw_data = getattr(event, "data", None)
            raw_type = str(getattr(raw_data, "type", "") or "")
            if raw_type == "response.output_text.delta":
                delta = self._stringify(getattr(raw_data, "delta", ""))
                if delta:
                    mapped.append(
                        TerminalAgentEventDTO(
                            event_type="message_delta",
                            data={"delta": delta},
                        )
                    )
            return mapped

        if event_type != "run_item_stream_event":
            return mapped

        item = getattr(event, "item", None)
        raw_item = getattr(item, "raw_item", None)
        item_type = str(getattr(item, "type", "") or "")
        lowered = item_type.lower()

        if event_name == "mcp_approval_requested":
            mapped.append(
                TerminalAgentEventDTO(
                    event_type="approval_required",
                    data={
                        "tool_name": self._stringify(getattr(raw_item, "name", None)),
                        "arguments": self._stringify(getattr(raw_item, "arguments", None)),
                        "approval_request_id": self._stringify(getattr(raw_item, "id", None)),
                        "server_label": self._stringify(getattr(raw_item, "server_label", None)),
                        "message": "该操作涉及受控 MCP 工具，当前不会自动执行。请进入审批流程后再继续。",
                    },
                )
            )
            return mapped

        if "call" in lowered and "output" not in lowered:
            tool_name = self._stringify(
                getattr(item, "name", None)
                or getattr(item, "tool_name", None)
                or self._dig(item, "raw_item", "name")
            )
            arguments = self._stringify(
                getattr(item, "arguments", None)
                or self._dig(item, "raw_item", "arguments")
                or ""
            )
            mapped.append(
                TerminalAgentEventDTO(
                    event_type="tool_called",
                    data={
                        "tool_name": tool_name,
                        "arguments": arguments,
                    },
                )
            )
            return mapped

        if "output" in lowered:
            tool_name = self._stringify(
                getattr(item, "name", None)
                or getattr(item, "tool_name", None)
                or self._dig(item, "raw_item", "name")
            )
            output = self._stringify(
                getattr(item, "output", None)
                or self._dig(item, "raw_item", "output")
                or self._dig(item, "raw_item", "content")
                or ""
            )
            mapped.append(
                TerminalAgentEventDTO(
                    event_type="tool_output",
                    data={
                        "tool_name": tool_name,
                        "output": output,
                    },
                )
            )
        return mapped

    def _extract_usage(self, streamed: Any) -> dict[str, int]:
        """Extract token usage from the SDK result when available."""

        candidates = [
            getattr(streamed, "usage", None),
            getattr(getattr(streamed, "result", None), "usage", None),
            getattr(getattr(streamed, "raw_responses", None), "usage", None),
        ]
        for usage in candidates:
            if usage is None:
                continue
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            if prompt_tokens is None:
                prompt_tokens = getattr(usage, "input_tokens", 0)
            if completion_tokens is None:
                completion_tokens = getattr(usage, "output_tokens", 0)
            if total_tokens is None:
                total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
            return {
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
                "total_tokens": int(total_tokens or 0),
            }
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _build_final_metadata(
        self,
        *,
        request: TerminalAgentChatRequestDTO,
        resolved_provider: _ResolvedProvider,
        usage: dict[str, int],
        tool_events: list[TerminalAgentEventDTO],
    ) -> dict[str, Any]:
        """Build the normalized metadata returned by the terminal endpoints."""

        return {
            "provider": resolved_provider.provider.name,
            "model": resolved_provider.model,
            "provider_scope": resolved_provider.provider_scope,
            "quota_charged": resolved_provider.quota_charged,
            "fallback_used": resolved_provider.fallback_used,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
            "tool_call_count": sum(1 for event in tool_events if event.event_type == "tool_called"),
            "entrypoint": "terminal",
            "username": request.username,
        }

    def _log_terminal_run(
        self,
        *,
        request: TerminalAgentChatRequestDTO,
        resolved_provider: _ResolvedProvider,
        events: list[TerminalAgentEventDTO],
    ) -> None:
        """Persist usage after the async run finishes and ORM is safe to touch."""

        final_event = next((event for event in reversed(events) if event.event_type == "final"), None)
        if final_event is not None:
            metadata = dict(final_event.data.get("metadata") or {})
            self._log_usage(
                resolved_provider=resolved_provider,
                request=request,
                usage={
                    "prompt_tokens": int(metadata.get("prompt_tokens") or 0),
                    "completion_tokens": int(metadata.get("completion_tokens") or 0),
                    "total_tokens": int(metadata.get("total_tokens") or 0),
                },
                status="success",
                error_message="",
            )
            return

        error_event = next((event for event in reversed(events) if event.event_type == "error"), None)
        if error_event is not None:
            self._log_usage(
                resolved_provider=resolved_provider,
                request=request,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                status="error",
                error_message=str(error_event.data.get("message") or ""),
            )

    def _log_usage(
        self,
        *,
        resolved_provider: _ResolvedProvider | None,
        request: TerminalAgentChatRequestDTO,
        usage: dict[str, int],
        status: str,
        error_message: str,
    ) -> None:
        """Persist one usage record using the existing repository contract."""

        if resolved_provider is None:
            return
        try:
            self._usage_repo.log_usage(
                provider=resolved_provider.provider,
                user=resolved_provider.user,
                provider_scope=resolved_provider.provider_scope,
                quota_charged=resolved_provider.quota_charged and status == "success",
                model=resolved_provider.model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                estimated_cost=0.0,
                response_time_ms=0,
                status=status,
                request_type="agent_terminal_chat",
                error_message=error_message,
                request_metadata={
                    "requested_provider_ref": request.provider_ref,
                    "fallback_used": resolved_provider.fallback_used,
                },
            )
        except Exception:
            logger.exception("Failed to persist terminal agent usage log")

    def _dig(self, obj: Any, *attrs: str) -> Any:
        """Safely drill through nested attributes."""

        current = obj
        for attr in attrs:
            current = getattr(current, attr, None)
            if current is None:
                return None
        return current

    def _stringify(self, value: Any) -> str:
        """Convert arbitrary SDK payload fragments into short strings."""

        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
