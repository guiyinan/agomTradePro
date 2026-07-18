"""Capability dispatcher behind MCP core tools."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from agomtradepro_mcp.audit import AuditContext, get_audit_logger
from agomtradepro_mcp.rbac import get_current_role, role_matches_required_roles

from .manifest import CapabilityManifest

CAPABILITY_SEARCH_DEFAULT_RESULTS = 10
CAPABILITY_SEARCH_MAX_RESULTS = 20

# Search aliases are protocol-routing metadata, not business rules. They keep
# Chinese user questions on the bounded discovery path without duplicating
# capability manifests or requiring every Agent client to translate first.
CAPABILITY_SEARCH_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "账户": ("account",),
    "持仓": ("position", "positions", "portfolio"),
    "组合": ("portfolio", "allocation"),
    "交易": ("trading", "trade", "execution"),
    "宏观": ("macro", "regime"),
    "象限": ("regime",),
    "政策": ("policy",),
    "信号": ("signal",),
    "行情": ("market", "price", "quote"),
    "报价": ("quote", "price"),
    "价格": ("price",),
    "股票": ("equity", "stock"),
    "个股": ("equity", "stock"),
    "基金": ("fund",),
    "板块": ("sector", "rotation"),
    "行业": ("sector",),
    "轮动": ("rotation",),
    "策略": ("strategy",),
    "回测": ("backtest",),
    "因子": ("factor",),
    "风险": ("risk",),
    "对冲": ("hedge",),
    "舆情": ("sentiment",),
    "情绪": ("sentiment",),
    "事件": ("event", "events"),
    "任务": ("task",),
    "监控": ("monitor", "monitoring"),
    "数据源": ("data", "provider"),
    "数据": ("data",),
    "配置": ("config", "configuration"),
    "审计": ("audit",),
    "告警": ("alert",),
}


class CapabilityDispatcher:
    """Discover, inspect, and execute registered capabilities."""

    def __init__(
        self,
        *,
        registry: dict[str, CapabilityManifest],
        legacy_tool_caller: Callable[[str, dict[str, Any]], Any],
        internal_handler_caller: Callable[[str, dict[str, Any]], Any] | None = None,
        audit_logger: Any | None = None,
        role_provider: Callable[[], str] | None = None,
    ) -> None:
        self._registry = dict(registry)
        self._legacy_tool_caller = legacy_tool_caller
        self._internal_handler_caller = internal_handler_caller
        self._audit_logger = audit_logger
        self._role_provider = role_provider or get_current_role
        self._pending_confirmations: dict[str, dict[str, Any]] = {}
        self._idempotency_records: dict[tuple[str, str], dict[str, Any]] = {}

    def list_capabilities(self) -> list[CapabilityManifest]:
        """Return enabled capabilities visible to the trusted runtime role."""
        role = self._role_provider()
        return [
            manifest
            for manifest in self._registry.values()
            if manifest.enabled and self._is_authorized(manifest, role=role)
        ]

    def search(
        self,
        *,
        query: str = "",
        tags: Sequence[str] | None = None,
        owner_app: str | None = None,
        risk_level: str | None = None,
        limit: int = CAPABILITY_SEARCH_DEFAULT_RESULTS,
    ) -> list[dict[str, Any]]:
        """Search capabilities using simple token overlap ranking."""
        normalized_tags = {tag.strip().lower() for tag in (tags or []) if str(tag).strip()}
        query_tokens = self._tokenize(query)
        matches: list[tuple[int, CapabilityManifest]] = []

        for manifest in self.list_capabilities():
            if owner_app and manifest.owner_app != owner_app:
                continue
            if risk_level and manifest.risk_level != risk_level:
                continue
            if normalized_tags and not normalized_tags.issubset(
                {tag.lower() for tag in manifest.tags}
            ):
                continue

            haystack = " ".join(
                [
                    manifest.capability_key,
                    manifest.title,
                    manifest.summary,
                    manifest.description,
                    " ".join(manifest.tags),
                ]
            ).lower()
            score = 1
            if query_tokens:
                score = sum(3 for token in query_tokens if token in haystack)
                score += sum(
                    1 for token in query_tokens if token in manifest.capability_key.lower()
                )
                if score <= 0:
                    continue
            matches.append((score, manifest))

        matches.sort(key=lambda item: (-item[0], item[1].capability_key))
        effective_limit = max(1, min(int(limit), CAPABILITY_SEARCH_MAX_RESULTS))
        return [manifest.to_discovery_dict() for _, manifest in matches[:effective_limit]]

    def get_schema(self, capability_key: str) -> dict[str, Any]:
        """Return full schema metadata for one capability."""
        manifest = self._registry.get(capability_key)
        if manifest is None or not manifest.enabled or not self._is_authorized(manifest):
            raise KeyError(f"Unknown capability_key: {capability_key}")
        return manifest.to_schema_dict()

    def call(
        self,
        *,
        capability_key: str,
        arguments: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one capability and return a unified envelope."""
        manifest = self._registry.get(capability_key)
        if manifest is None or not manifest.enabled:
            return self._error_envelope(
                code="capability_not_found",
                message=f"Unknown capability_key: {capability_key}",
                capability_key=capability_key,
            )

        safe_arguments = dict(arguments or {})
        safe_context = dict(context or {})
        audit_context = self._build_audit_context(safe_context)
        safe_context.setdefault("request_id", audit_context.request_id)
        if not self._is_authorized(manifest):
            payload = self._error_envelope(
                code="capability_forbidden",
                message="The authenticated MCP role cannot execute this capability.",
                capability_key=capability_key,
                required_roles=list(manifest.required_roles),
            )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="authorization_failed",
                confirmation_status="rejected",
                arguments=safe_arguments,
                request_arguments=safe_arguments,
                response=payload,
            )
            return payload
        missing = self._validate_required_arguments(manifest, safe_arguments)
        if missing:
            payload = self._error_envelope(
                code="missing_required_arguments",
                message=f"Missing required arguments: {', '.join(missing)}",
                capability_key=capability_key,
                missing_required=list(missing),
            )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="validation_failed",
                confirmation_status="rejected",
                arguments=safe_arguments,
                request_arguments=safe_arguments,
                response=payload,
            )
            return payload

        idempotency_error = self._validate_idempotency_arguments(manifest, safe_arguments)
        if idempotency_error is not None:
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="validation_failed",
                confirmation_status="rejected",
                arguments=safe_arguments,
                request_arguments=safe_arguments,
                response=idempotency_error,
            )
            return idempotency_error

        idempotency_key = self._extract_idempotency_key(manifest, safe_arguments)
        record_key = self._build_idempotency_record_key(manifest, idempotency_key)
        existing_response = self._resolve_existing_idempotent_response(
            manifest=manifest,
            arguments=safe_arguments,
            record_key=record_key,
        )
        if existing_response is not None:
            self._audit_existing_idempotent_response(
                manifest=manifest,
                audit_context=audit_context,
                arguments=safe_arguments,
                response=existing_response,
                idempotency_key=idempotency_key,
            )
            return existing_response

        if manifest.requires_confirmation:
            preview_result = None
            if manifest.confirmation_preview_arguments:
                preview_arguments = self._merge_arguments(
                    safe_arguments,
                    manifest.confirmation_preview_arguments,
                )
                try:
                    preview_result = self._execute_manifest(manifest, preview_arguments)
                except Exception as exc:
                    payload = self._error_envelope(
                        code="capability_preview_failed",
                        message=str(exc),
                        capability_key=capability_key,
                    )
                    self._audit_capability_event(
                        manifest=manifest,
                        audit_context=audit_context,
                        tool_name="agom_capability_call",
                        event_type="preview_failed",
                        confirmation_status="failed",
                        arguments=safe_arguments,
                        request_arguments=safe_arguments,
                        response=payload,
                        error=exc,
                    )
                    return payload

            committed_arguments = self._merge_arguments(
                safe_arguments,
                manifest.confirmation_commit_arguments,
            )
            response = {
                "ok": False,
                "status": "confirmation_required",
                "capability_key": capability_key,
                "confirmation_token": self._store_pending_confirmation(
                    manifest,
                    committed_arguments,
                    safe_context,
                    record_key=record_key,
                    request_arguments=safe_arguments,
                ),
                "message": "This capability requires explicit confirmation before execution.",
            }
            if preview_result is not None:
                response["preview_result"] = preview_result
            if idempotency_key is not None:
                response["idempotency_key"] = idempotency_key
                self._store_idempotency_pending(
                    manifest=manifest,
                    arguments=safe_arguments,
                    record_key=record_key,
                    response=response,
                )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="preview_staged",
                confirmation_status="pending",
                arguments=safe_arguments,
                request_arguments=safe_arguments,
                response=response,
                preview_result=preview_result,
            )
            return response

        try:
            result = self._execute_manifest(manifest, safe_arguments)
        except Exception as exc:
            payload = self._error_envelope(
                code="capability_execution_failed",
                message=str(exc),
                capability_key=capability_key,
            )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="execution_failed",
                confirmation_status="failed",
                arguments=safe_arguments,
                request_arguments=safe_arguments,
                response=payload,
                error=exc,
            )
            return payload
        response = self._success_envelope(capability_key=capability_key, result=result)
        if idempotency_key is not None:
            response["idempotency_key"] = idempotency_key
            self._store_idempotency_completed(
                manifest=manifest,
                arguments=safe_arguments,
                record_key=record_key,
                response=response,
            )
        self._audit_capability_event(
            manifest=manifest,
            audit_context=audit_context,
            tool_name="agom_capability_call",
            event_type="completed",
            confirmation_status="not_required",
            arguments=safe_arguments,
            request_arguments=safe_arguments,
            response=response,
        )
        return response

    def resume_confirmation(
        self,
        *,
        confirmation_token: str,
        approve: bool = True,
    ) -> dict[str, Any]:
        """Resume a previously staged write call."""
        pending = self._pending_confirmations.get(confirmation_token)
        if pending is None:
            return self._error_envelope(
                code="confirmation_not_found",
                message=(
                    "Unknown or expired confirmation token. Resume it in the same MCP "
                    "server process that staged the confirmation."
                ),
                confirmation_token=confirmation_token,
            )
        pending_context = dict(pending.get("context") or {})
        audit_context = self._build_audit_context(pending_context)
        if not approve:
            self._pending_confirmations.pop(confirmation_token, None)
            record_key = pending.get("record_key")
            if record_key is not None:
                self._idempotency_records.pop(record_key, None)
            payload = {
                "ok": True,
                "status": "cancelled",
                "confirmation_token": confirmation_token,
                "message": "Confirmation cancelled.",
            }
            self._audit_capability_event(
                manifest=pending["manifest"],
                audit_context=audit_context,
                tool_name="agom_confirmation_resume",
                event_type="confirmation_cancelled",
                confirmation_status="cancelled",
                arguments=pending.get("request_arguments") or pending["arguments"],
                request_arguments=pending.get("request_arguments") or pending["arguments"],
                response=payload,
                confirmation_token=confirmation_token,
            )
            return payload

        manifest = pending["manifest"]
        arguments = pending["arguments"]
        record_key = pending.get("record_key")
        request_arguments = pending.get("request_arguments") or arguments
        if not self._is_authorized(manifest):
            self._pending_confirmations.pop(confirmation_token, None)
            if record_key is not None:
                self._idempotency_records.pop(record_key, None)
            payload = self._error_envelope(
                code="capability_forbidden",
                message="The authenticated MCP role cannot execute this capability.",
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
                required_roles=list(manifest.required_roles),
            )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_confirmation_resume",
                event_type="authorization_failed",
                confirmation_status="rejected",
                arguments=request_arguments,
                request_arguments=request_arguments,
                response=payload,
                confirmation_token=confirmation_token,
            )
            return payload
        self._pending_confirmations.pop(confirmation_token, None)
        try:
            result = self._execute_manifest(manifest, arguments)
        except Exception as exc:
            if record_key is not None:
                self._idempotency_records.pop(record_key, None)
            payload = self._error_envelope(
                code="capability_execution_failed",
                message=str(exc),
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_confirmation_resume",
                event_type="confirmation_failed",
                confirmation_status="failed",
                arguments=request_arguments,
                request_arguments=request_arguments,
                response=payload,
                error=exc,
                confirmation_token=confirmation_token,
            )
            return payload
        payload = self._success_envelope(capability_key=manifest.capability_key, result=result)
        payload["confirmation_token"] = confirmation_token
        payload["status"] = "completed"
        idempotency_key = self._extract_idempotency_key(manifest, arguments)
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
            self._store_idempotency_completed(
                manifest=manifest,
                arguments=request_arguments,
                record_key=record_key,
                response=payload,
            )
        self._audit_capability_event(
            manifest=manifest,
            audit_context=audit_context,
            tool_name="agom_confirmation_resume",
            event_type="confirmation_completed",
            confirmation_status="completed",
            arguments=request_arguments,
            request_arguments=request_arguments,
            response=payload,
            confirmation_token=confirmation_token,
        )
        return payload

    def _execute_manifest(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
    ) -> Any:
        if manifest.executor_kind == "legacy_tool":
            return self._legacy_tool_caller(manifest.executor_ref, arguments)
        if manifest.executor_kind == "internal_handler":
            if self._internal_handler_caller is None:
                raise RuntimeError("Internal handler caller is not configured")
            return self._internal_handler_caller(manifest.executor_ref, arguments)
        raise RuntimeError(f"Unsupported executor_kind: {manifest.executor_kind}")

    def _validate_required_arguments(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
    ) -> list[str]:
        required = manifest.input_schema.get("required", []) or []
        return [name for name in required if name not in arguments]

    def _is_authorized(
        self,
        manifest: CapabilityManifest,
        *,
        role: str | None = None,
    ) -> bool:
        """Check manifest roles against trusted process/backend identity only."""

        return role_matches_required_roles(
            role if role is not None else self._role_provider(),
            manifest.required_roles,
        )

    def _store_pending_confirmation(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        record_key: tuple[str, str] | None = None,
        request_arguments: dict[str, Any] | None = None,
    ) -> str:
        token = secrets.token_urlsafe(16)
        self._pending_confirmations[token] = {
            "manifest": manifest,
            "arguments": deepcopy(arguments),
            "context": deepcopy(context),
            "record_key": record_key,
            "request_arguments": deepcopy(request_arguments or arguments),
        }
        return token

    def _success_envelope(self, *, capability_key: str, result: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "completed",
            "capability_key": capability_key,
            "result": result,
        }

    def _merge_arguments(
        self,
        base_arguments: dict[str, Any],
        override_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        merged = deepcopy(base_arguments)
        merged.update(deepcopy(override_arguments))
        return merged

    def _error_envelope(
        self,
        *,
        code: str,
        message: str,
        capability_key: str | None = None,
        confirmation_token: str | None = None,
        missing_required: list[str] | None = None,
        required_roles: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "ok": False,
            "status": "error",
            "error": {
                "code": code,
                "message": message,
            },
        }
        if capability_key is not None:
            payload["capability_key"] = capability_key
        if confirmation_token is not None:
            payload["confirmation_token"] = confirmation_token
        if missing_required:
            payload["missing_required"] = missing_required
        if required_roles:
            payload["required_roles"] = required_roles
        return payload

    def _validate_idempotency_arguments(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        if manifest.idempotency != "required":
            return None

        argument_name = manifest.idempotency_argument_name
        raw_value = arguments.get(argument_name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return self._error_envelope(
                code="missing_idempotency_key",
                message=(
                    "This capability requires a non-empty idempotency key via "
                    f"'{argument_name}'."
                ),
                capability_key=manifest.capability_key,
            )
        return None

    def _extract_idempotency_key(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
    ) -> str | None:
        argument_name = manifest.idempotency_argument_name
        raw_value = arguments.get(argument_name)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        return normalized or None

    def _build_idempotency_record_key(
        self,
        manifest: CapabilityManifest,
        idempotency_key: str | None,
    ) -> tuple[str, str] | None:
        if manifest.idempotency == "none" or not idempotency_key:
            return None
        return (manifest.capability_key, idempotency_key)

    def _resolve_existing_idempotent_response(
        self,
        *,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        record_key: tuple[str, str] | None,
    ) -> dict[str, Any] | None:
        if record_key is None:
            return None

        record = self._idempotency_records.get(record_key)
        if record is None:
            return None

        stored_arguments = record.get("arguments") or {}
        if stored_arguments != arguments:
            return self._error_envelope(
                code="idempotency_key_conflict",
                message=("The provided idempotency key was already used with different arguments."),
                capability_key=manifest.capability_key,
            )

        if record["status"] == "pending":
            response = deepcopy(record["response"])
            response["idempotency_reused"] = True
            return response

        if record["status"] == "completed":
            response = deepcopy(record["response"])
            response["status"] = "idempotent_replay"
            response["idempotency_reused"] = True
            return response

        return None

    def _store_idempotency_pending(
        self,
        *,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        record_key: tuple[str, str] | None,
        response: dict[str, Any],
    ) -> None:
        if record_key is None:
            return
        self._idempotency_records[record_key] = {
            "status": "pending",
            "manifest": manifest.capability_key,
            "arguments": deepcopy(arguments),
            "response": deepcopy(response),
        }

    def _store_idempotency_completed(
        self,
        *,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        record_key: tuple[str, str] | None,
        response: dict[str, Any],
    ) -> None:
        if record_key is None:
            return
        self._idempotency_records[record_key] = {
            "status": "completed",
            "manifest": manifest.capability_key,
            "arguments": deepcopy(arguments),
            "response": deepcopy(response),
        }

    def _tokenize(self, text: str) -> set[str]:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return set()
        tokens = {
            token for token in normalized.replace("-", " ").replace("_", " ").split() if token
        }
        for alias, expanded_tokens in CAPABILITY_SEARCH_QUERY_ALIASES.items():
            if alias in normalized:
                tokens.update(expanded_tokens)
        return tokens

    def _build_audit_context(self, context: dict[str, Any]) -> AuditContext:
        return AuditContext.create(
            request_id=context.get("request_id"),
            user_id=context.get("user_id"),
            username=context.get("username", "anonymous"),
            ip_address=context.get("ip_address"),
            user_agent=context.get("user_agent", ""),
            client_id=context.get("client_id", ""),
            mcp_role=context.get("mcp_role", ""),
            sdk_version=context.get("sdk_version", ""),
        )

    def _get_audit_logger(self) -> Any:
        if self._audit_logger is None:
            self._audit_logger = get_audit_logger()
        return self._audit_logger

    def _audit_existing_idempotent_response(
        self,
        *,
        manifest: CapabilityManifest,
        audit_context: AuditContext,
        arguments: dict[str, Any],
        response: dict[str, Any],
        idempotency_key: str | None,
    ) -> None:
        error_code = (
            ((response.get("error") or {}) if isinstance(response, dict) else {}) or {}
        ).get("code")
        if error_code == "idempotency_key_conflict":
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="idempotency_conflict",
                confirmation_status="rejected",
                arguments=arguments,
                request_arguments=arguments,
                response=response,
                idempotency_key=idempotency_key,
            )
            return

        if response.get("status") == "idempotent_replay":
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="idempotent_replay",
                confirmation_status="reused",
                arguments=arguments,
                request_arguments=arguments,
                response=response,
                idempotency_key=idempotency_key,
            )
            return

        if response.get("status") == "confirmation_required" and response.get("idempotency_reused"):
            self._audit_capability_event(
                manifest=manifest,
                audit_context=audit_context,
                tool_name="agom_capability_call",
                event_type="confirmation_reused",
                confirmation_status="pending",
                arguments=arguments,
                request_arguments=arguments,
                response=response,
                idempotency_key=idempotency_key,
            )

    def _audit_capability_event(
        self,
        *,
        manifest: CapabilityManifest,
        audit_context: AuditContext,
        tool_name: str,
        event_type: str,
        confirmation_status: str,
        arguments: dict[str, Any],
        request_arguments: dict[str, Any],
        response: dict[str, Any],
        error: Exception | None = None,
        idempotency_key: str | None = None,
        preview_result: Any | None = None,
        confirmation_token: str | None = None,
    ) -> None:
        if not self._should_audit_manifest(manifest):
            return

        try:
            payload = deepcopy(response)
            if preview_result is not None:
                payload["preview_result"] = preview_result
            if confirmation_token is not None:
                payload["confirmation_token"] = confirmation_token

            self._get_audit_logger().log_governed_capability_event(
                tool_name=tool_name,
                capability_key=manifest.capability_key,
                params=arguments,
                result=payload,
                error=error,
                context=audit_context,
                owner_app=manifest.owner_app,
                risk_level=manifest.risk_level,
                event_type=event_type,
                confirmation_status=confirmation_status,
                idempotency_key=idempotency_key
                or self._extract_idempotency_key(manifest, request_arguments),
                request_arguments=request_arguments,
                affected_objects=self._summarize_affected_objects(
                    manifest=manifest,
                    arguments=request_arguments,
                    response=payload,
                ),
            )
        except Exception:
            return

    def _should_audit_manifest(self, manifest: CapabilityManifest) -> bool:
        return (
            manifest.requires_confirmation
            or manifest.idempotency != "none"
            or "write" in {tag.lower() for tag in manifest.tags}
        )

    def _summarize_affected_objects(
        self,
        *,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "capability_key": manifest.capability_key,
            "owner_app": manifest.owner_app,
        }
        for key in (
            "account_id",
            "new_initial_capital",
            "trade_date",
            "as_of_date",
            "strategy_id",
            "inspection_date",
            "auto_create_proposal",
            "portfolio_id",
            "provider_id",
            "config_id",
            "partial",
            "rule_id",
            "plan_id",
            "recommendation_id",
            "mode",
            "name",
            "account_name",
            "asset_code",
            "side",
            "quantity",
            "price",
            "strategy_type",
            "target_regime",
            "code",
            "signal_id",
            "candidate_id",
            "template_key",
            "publisher_code",
            "indicator_code",
            "alert_id",
            "request_id",
            "event_id",
            "field_name",
            "expires_at",
            "is_active",
        ):
            if key in arguments:
                summary[key] = arguments[key]
        for key in ("proposal_type", "task_id", "risk_level", "approval_required"):
            if key in arguments:
                summary[key] = arguments[key]
        if "proposal_id" in arguments:
            summary["proposal_id"] = arguments["proposal_id"]
        payload = arguments.get("payload")
        if isinstance(payload, dict):
            requests = payload.get("requests")
            if isinstance(requests, list):
                summary["payload_request_count"] = len(requests)
            if "quota_period" in payload:
                summary["quota_period"] = payload.get("quota_period")
            for key in ("target", "asset_code", "action", "portfolio_id", "sim_account_id"):
                if key in payload:
                    summary[f"payload_{key}"] = payload.get(key)

        positions = arguments.get("positions")
        if isinstance(positions, list):
            summary["position_count"] = len(positions)
        account_ids = arguments.get("account_ids")
        if isinstance(account_ids, list):
            summary["account_count"] = len(account_ids)
        transactions = arguments.get("transactions")
        if isinstance(transactions, list):
            summary["transaction_count"] = len(transactions)
        capital_flows = arguments.get("capital_flows")
        if isinstance(capital_flows, list):
            summary["capital_flow_count"] = len(capital_flows)
        proposal_payload = arguments.get("proposal_payload")
        if isinstance(proposal_payload, dict):
            summary["proposal_payload_keys"] = sorted(proposal_payload)

        result = response.get("result")
        if isinstance(result, dict):
            for key in ("portfolio_id", "mode", "dry_run"):
                if key in result:
                    summary[key] = result[key]
            nested_data = result.get("data")
            if isinstance(nested_data, dict) and "request_id" in nested_data:
                summary["generated_request_id"] = nested_data.get("request_id")
            nested_summary = result.get("summary")
            if isinstance(nested_summary, dict):
                summary["summary"] = nested_summary

        preview_result = response.get("preview_result")
        if isinstance(preview_result, dict):
            preview_summary = preview_result.get("summary")
            if isinstance(preview_summary, dict):
                summary["preview_summary"] = preview_summary

        return summary
