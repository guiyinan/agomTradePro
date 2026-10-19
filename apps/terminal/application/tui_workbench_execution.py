"""Action execution helpers for the TUI workbench."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict

from django.utils import timezone

from apps.terminal.application.tui_audit import verified_reauth_evidence
from apps.terminal.application.tui_research_snapshot_result import (
    TuiResearchProfessionalTarget,
)
from apps.terminal.application.tui_task_focus_result import TuiTaskFocusProfessionalTarget
from apps.terminal.application.tui_task_scope_contracts import (
    TuiTaskScopeError,
    validate_task_action_scope,
)


class _OwnerResultContinuation(TypedDict):
    """Validated runtime-only handoff returned by a declared owner action."""

    action_key: str
    input: dict[str, str]
    expires_at: str


class TuiWorkbenchExecutionMixin:
    """Execution and preflight response helpers for the TUI workbench."""

    if TYPE_CHECKING:
        from apps.terminal.domain.interfaces import TuiActionExecutor

        action_executor: TuiActionExecutor | None

        def _action_by_key(
            self, action_key: str, *, user: Any | None = None
        ) -> dict[str, Any] | None: ...

        def _diagnostics_allowed(self, user: Any | None) -> bool: ...

        def _allowed_runtime_risks(self, user: Any | None) -> set[str]: ...

        def _ensure_tui_audit_sink(self, action: dict[str, Any]) -> None: ...

        def _requires_confirmation(self, action: dict[str, Any]) -> bool: ...

        def _requires_password(self, action: dict[str, Any]) -> bool: ...

        def _reauth_verified(self, user: Any | None, reauth: dict[str, Any] | None) -> bool: ...

        def _append_tui_audit(
            self,
            action: dict[str, Any],
            params: dict[str, Any],
            *,
            user: Any | None,
            session: Any | None,
            outcome: str,
            confirmation_evidence: dict[str, Any] | None = None,
            reauth_evidence: dict[str, Any] | None = None,
            result: dict[str, Any] | None = None,
            error: str = "",
        ) -> None: ...

        def _metadata(self) -> dict[str, Any]: ...

        def _screen_by_key(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]: ...

        def _operator_text(self, value: Any) -> str: ...

        def _resolved_field_default(
            self, action: dict[str, Any] | None, field: dict[str, Any]
        ) -> Any: ...

        def _field_payload(
            self,
            field: dict[str, Any],
            *,
            action: dict[str, Any] | None = None,
            user: Any | None = None,
            preserve_label: bool = False,
        ) -> dict[str, Any]: ...

        def _message_model(
            self,
            action: dict[str, Any],
            message: str,
            status_code: int,
        ) -> dict[str, Any]: ...

        def _action_payload(
            self,
            action: dict[str, Any],
            *,
            include_technical: bool = False,
            user: Any | None = None,
        ) -> dict[str, Any]: ...

        def _to_view_model(
            self,
            *,
            action: dict[str, Any],
            payload: Any,
            status_code: int,
            request_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]: ...

    def run_action(
        self,
        *,
        action_key: str,
        params: dict[str, Any],
        user: Any,
        session: Any | None = None,
        confirmed: bool = False,
        confirmation: dict[str, Any] | None = None,
        reauth: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute one published action and return a business-first view model."""

        if idempotency_key is not None and (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 192
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValueError("Invalid action idempotency key")
        if self.action_executor is None:
            raise ValueError("TUI action executor is not configured")

        action = self._action_by_key(action_key, user=user)
        if action is None:
            raise KeyError(action_key)
        if str(action["risk"]) not in self._allowed_runtime_risks(user):
            raise PermissionError(
                "Only read/AI/confirmed write actions are enabled in this TUI surface"
            )
        self._ensure_tui_audit_sink(action)
        try:
            task_scope = validate_task_action_scope(action_key, params)
        except TuiTaskScopeError as error:
            result = self._invalid_task_scope_payload(action, error.message, user=user)
            missing_fields = (
                self._missing_required_fields(action, params, user=user)
                if isinstance(params, Mapping)
                else []
            )
            if missing_fields:
                result = self._missing_required_fields_payload(action, missing_fields, user=user)
                result["outcome"] = "blocked"
                result["view_model"]["outcome"] = "blocked"
                result["view_model"]["user_error_code"] = "TUI_TASK_SCOPE_INVALID"
                result.update(self._result_head_payload(result["view_model"]))
            self._append_tui_audit(
                action,
                {},
                user=user,
                session=session,
                outcome="rejected_invalid_scope",
                result=result,
                error="TUI_TASK_SCOPE_INVALID",
            )
            return result
        resolved_params = (
            dict(task_scope.params)
            if task_scope is not None
            else self._apply_default_field_values(action, params or {})
        )
        missing_fields = self._missing_required_fields(action, resolved_params, user=user)
        if missing_fields:
            result = self._missing_required_fields_payload(action, missing_fields, user=user)
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="rejected_missing_fields",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result
        if self._requires_confirmation(action) and not confirmed:
            result = self._confirmation_required_payload(action, user=user)
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="blocked_confirmation_required",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result
        if self._requires_password(action) and not self._reauth_verified(user, reauth):
            result = self._password_challenge_required_payload(
                action, attempted=bool(reauth), user=user
            )
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="blocked_reauth_failed" if reauth else "blocked_reauth_required",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result

        reauth_evidence = (
            verified_reauth_evidence(reauth) if self._requires_password(action) else reauth
        )
        method = str(action["method"]).upper()
        try:
            endpoint, request_params = self._bind_endpoint_params(
                endpoint=str(action["endpoint"]),
                params=resolved_params,
            )
            executor_params = dict(request_params)
            if method != "GET" and self._requires_password(action):
                executor_params["reauth"] = dict(reauth or {})
            identity_options: dict[str, Any] = (
                {"idempotency_key": idempotency_key} if idempotency_key is not None else {}
            )
            result = self.action_executor.execute(
                method=method,
                endpoint=endpoint,
                params=executor_params if method == "GET" else {},
                body=executor_params if method != "GET" else {},
                user=user,
                session=session,
                **identity_options,
            )
            if task_scope is not None and (
                not isinstance(result, Mapping)
                or type(result.get("status_code")) is not int
                or not 100 <= result["status_code"] <= 599
            ):
                # A missing/invalid transport status is not an implicit 200.
                status_code = 502
                payload = None
            else:
                status_code = int(result.get("status_code", 200))
                payload = result.get("payload")
            safe_payload, owner_continuation, continuation_error = (
                self._validate_owner_result_continuation(
                    action=action,
                    payload=payload,
                    status_code=status_code,
                )
            )
            if continuation_error is not None:
                failure = self._result_continuation_failure_payload(
                    action=action,
                    user=user,
                    error_code=continuation_error,
                )
                self._append_tui_audit(
                    action,
                    resolved_params,
                    user=user,
                    session=session,
                    outcome="failed_continuation_contract",
                    confirmation_evidence=confirmation,
                    reauth_evidence=reauth_evidence,
                    result=failure,
                    error=continuation_error,
                )
                return failure
            projection_action = self._action_with_empty_state_context(action)
            if action_key == "equity.research-snapshot":
                professional_target = self._research_professional_target(
                    payload=safe_payload,
                    status_code=status_code,
                    user=user,
                )
                if professional_target is not None:
                    projection_action["_research_professional_target"] = professional_target
            if task_scope is not None:
                task_target = self._task_focus_professional_target(
                    action_key=action_key,
                    payload=safe_payload,
                    status_code=status_code,
                    user=user,
                )
                if task_target is not None:
                    projection_action["_task_focus_professional_target"] = task_target
            view_model = self._to_view_model(
                action=projection_action,
                payload=safe_payload,
                status_code=status_code,
                request_params=(resolved_params if task_scope is not None else request_params),
            )
            outcome = self._execution_outcome(safe_payload, status_code)
            if task_scope is not None and outcome not in {"blocked", "failed"}:
                projected_outcome = view_model.get("outcome")
                if projected_outcome in {"blocked", "failed"}:
                    # A malformed successful owner payload cannot complete the
                    # UI operation merely because its HTTP transport succeeded.
                    outcome = projected_outcome
            raw_allowed = self._diagnostics_allowed(user) and action.get("raw_debug", True) is True
            envelope = {
                "version": "tui-workbench.v2",
                "outcome": outcome,
                "action": self._action_payload(action, user=user),
                "confirmation_required": False,
                "response": {
                    "status_code": status_code,
                },
                "view_model": view_model,
                "debug": {
                    "raw_available": raw_allowed,
                    "raw_response": safe_payload if raw_allowed else None,
                },
            }
            envelope.update(self._result_head_payload(view_model))
        except Exception as exc:
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="failed_exception",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth_evidence,
                error=str(exc),
            )
            raise

        self._append_tui_audit(
            action,
            resolved_params,
            user=user,
            session=session,
            outcome=(
                "succeeded"
                if 200 <= status_code < (300 if task_scope is not None else 400)
                else "failed"
            ),
            confirmation_evidence=confirmation,
            reauth_evidence=reauth_evidence,
            result=envelope,
        )
        if owner_continuation is not None:
            envelope["continuation"] = owner_continuation
        return envelope

    def _invalid_task_scope_payload(
        self, action: dict[str, Any], message: str, *, user: Any
    ) -> dict[str, Any]:
        """Return the existing bounded preflight shape without an owner call."""

        model = self._message_model(action, message, 400)
        model.update(
            {
                "status": "需要重新选择",
                "outcome": "blocked",
                "business_summary": message,
                "blocking_reason": message,
                "user_error_code": "TUI_TASK_SCOPE_INVALID",
                "next_steps": [],
            }
        )
        return {
            "version": "tui-workbench.v2",
            "outcome": "blocked",
            "action": self._action_payload(action, user=user),
            "confirmation_required": False,
            "response": {"status_code": 400},
            "view_model": model,
            "debug": {"raw_available": False, "raw_response": None},
            **self._result_head_payload(model),
        }

    def _task_focus_professional_target(
        self,
        *,
        action_key: str,
        payload: Any,
        status_code: int,
        user: Any,
    ) -> TuiTaskFocusProfessionalTarget | None:
        """Offer one fresh visible passive target without granting owner authority."""

        if (
            user is None
            or getattr(user, "is_authenticated", False) is not True
            or getattr(user, "is_active", False) is not True
            or getattr(user, "pk", None) in (None, "")
            or not 200 <= status_code < 300
            or not isinstance(payload, Mapping)
            or payload.get("success") is not True
        ):
            return None
        if action_key == "today-focus.queue":
            target_key = "decision.workspace.summary"
            screen_key = "command-center.decision-flow"
            field_key, binding = "account_id", "query"
        elif action_key in {"portfolio-check.recorded-facts", "account.portfolio-recorded-facts"}:
            target_key = "account.portfolio-recorded-facts"
            screen_key = "execution.accounts"
            field_key, binding = "pk", "path"
        else:
            return None
        target = self._action_by_key(target_key, user=user)
        if target is None or (
            target.get("screen_key") != screen_key
            or str(target.get("method") or "").upper() != "GET"
            or target.get("risk") != "read"
            or target.get("effect", "read") != "read"
            or bool(target.get("confirmation_required"))
            or bool(target.get("requires_password"))
            or target.get("sensitive_level", "none") != "none"
        ):
            return None
        fields = target.get("fields")
        if not isinstance(fields, list):
            return None
        safe_field = False
        for field in fields:
            if not isinstance(field, dict):
                return None
            if field.get("key") == field_key:
                safe_field = (
                    field.get("binding") == binding
                    and field.get("value_type", "string") in {"integer", "string"}
                    and str(field.get("input_type", "text")) in {"text", "number"}
                    and field.get("presentation_semantic")
                    not in {"api_token", "copyable_secret", "endpoint_url", "prompt_text", "secret"}
                    and field.get("secret") is not True
                    and field.get("sensitive") is not True
                    and field.get("sensitive_level", "none") == "none"
                )
            elif field.get("required") is True and field.get("default") in (None, ""):
                return None
        if not safe_field:
            return None
        # The closed keys are server-selected; only the label comes from the
        # freshly authorized metadata and no target is automatically executed.
        if target_key == "decision.workspace.summary":
            return {
                "screen_key": "command-center.decision-flow",
                "action_key": "decision.workspace.summary",
                "label": f"进入专业工作区：{target.get('label') or '查看账户详情'}",
            }
        return {
            "screen_key": "execution.accounts",
            "action_key": "account.portfolio-recorded-facts",
            "label": f"进入专业工作区：{target.get('label') or '查看组合详情'}",
        }

    def _validate_owner_result_continuation(
        self,
        *,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> tuple[Any, _OwnerResultContinuation | None, str | None]:
        """Validate a declared owner handoff and remove it from renderable payload data."""

        descriptor = action.get("result_continuation")
        declared = isinstance(descriptor, dict)
        if not isinstance(payload, dict):
            if (
                declared
                and status_code < 400
                and self._execution_outcome(payload, status_code) == "success"
            ):
                return payload, None, "tui_result_continuation_missing"
            return payload, None, None

        if "continuation" not in payload:
            if (
                declared
                and status_code < 400
                and self._execution_outcome(payload, status_code) == "success"
                and not any(
                    payload.get(key)
                    for key in (
                        "confirmation_required",
                        "password_challenge_required",
                        "missing_fields",
                    )
                )
            ):
                return payload, None, "tui_result_continuation_missing"
            return payload, None, None

        if not isinstance(descriptor, dict):
            return payload, None, "tui_result_continuation_unexpected"
        if (
            status_code >= 400
            or self._execution_outcome(payload, status_code) != "success"
            or any(
                payload.get(key)
                for key in (
                    "confirmation_required",
                    "password_challenge_required",
                    "missing_fields",
                )
            )
        ):
            return payload, None, "tui_result_continuation_invalid"

        continuation = payload.get("continuation")
        if not isinstance(continuation, dict) or set(continuation) != {
            "action_key",
            "input",
            "expires_at",
        }:
            return payload, None, "tui_result_continuation_invalid"
        target_action_key = descriptor.get("target_action_key")
        field_map = descriptor.get("field_map")
        continuation_input = continuation.get("input")
        if (
            not isinstance(target_action_key, str)
            or not isinstance(field_map, dict)
            or continuation.get("action_key") != target_action_key
            or not isinstance(continuation_input, dict)
            or set(continuation_input) != set(field_map)
            or any(type(value) is not str or not value for value in continuation_input.values())
        ):
            return payload, None, "tui_result_continuation_invalid"

        expires_at_text = continuation.get("expires_at")
        if not isinstance(expires_at_text, str) or not expires_at_text:
            return payload, None, "tui_result_continuation_invalid"
        try:
            normalized_expiry = (
                expires_at_text[:-1] + "+00:00"
                if expires_at_text.endswith("Z")
                else expires_at_text
            )
            expires_at = datetime.fromisoformat(normalized_expiry)
        except ValueError:
            return payload, None, "tui_result_continuation_invalid"
        if expires_at.tzinfo is None or expires_at.utcoffset() != timedelta(0):
            return payload, None, "tui_result_continuation_invalid"
        if expires_at.astimezone(UTC) <= timezone.now().astimezone(UTC):
            return payload, None, "tui_result_continuation_expired"

        token_values = {value for value in continuation_input.values() if value}
        safe_payload = {key: value for key, value in payload.items() if key != "continuation"}
        if self._contains_continuation_value(safe_payload, token_values):
            return payload, None, "tui_result_continuation_leaked"
        validated: _OwnerResultContinuation = {
            "action_key": target_action_key,
            "input": dict(continuation_input),
            "expires_at": expires_at_text,
        }
        return safe_payload, validated, None

    @staticmethod
    def _contains_continuation_value(value: Any, token_values: set[str]) -> bool:
        """Return whether an owner handoff value is duplicated into display data."""

        if isinstance(value, str):
            return value in token_values
        if isinstance(value, Mapping):
            return any(
                TuiWorkbenchExecutionMixin._contains_continuation_value(item, token_values)
                for item in value.values()
            )
        if isinstance(value, list | tuple):
            return any(
                TuiWorkbenchExecutionMixin._contains_continuation_value(item, token_values)
                for item in value
            )
        return False

    def _result_continuation_failure_payload(
        self,
        *,
        action: dict[str, Any],
        user: Any,
        error_code: str,
    ) -> dict[str, Any]:
        """Build a bounded failure without retaining any owner response content."""

        message = "当前结果未能安全交接，尚未继续后续操作。请重新运行准备步骤。"
        view_model = self._message_model(action, message, 502)
        view_model["status"] = "未完成"
        view_model["user_error_code"] = error_code
        return {
            "version": "tui-workbench.v2",
            "outcome": "failed",
            "error_code": error_code,
            "action": self._action_payload(action, user=user),
            "confirmation_required": False,
            "response": {"status_code": 502},
            "view_model": view_model,
            "debug": {"raw_available": False, "raw_response": None},
            **self._result_head_payload(view_model),
        }

    def _execution_outcome(self, payload: Any, status_code: int) -> str:
        """Preserve a bounded owner outcome separately from transport success."""
        if status_code >= 400:
            return "failed"
        if isinstance(payload, dict):
            data = payload.get("data")
            source = (
                payload if "outcome" in payload else data if isinstance(data, dict) else payload
            )
            outcome = source.get("outcome")
            if outcome in ("success", "partial", "noop", "blocked", "failed"):
                return str(outcome)
            if source.get("success") is False:
                if (
                    200 <= status_code < 300
                    and source.get("status") == "blocked"
                    and source.get("must_not_use_for_decision") is True
                ):
                    return "blocked"
                return "failed"
            if payload.get("success") is False:
                return "failed"
        return "success"

    def _action_with_empty_state_context(self, action: dict[str, Any]) -> dict[str, Any]:
        """Attach reviewed screen guidance to one result projection.

        The extra key is runtime-only and is never published as action metadata.
        It lets every empty result retain the user task context defined on its
        owning screen instead of falling back to a generic renderer message.
        """

        projected = dict(action)
        screen_key = str(action.get("screen_key") or "")
        screen = self._screen_by_key(self._metadata()).get(screen_key) or {}
        experience = dict(screen.get("user_experience") or {})
        guidance: list[str] = []
        for key in ("empty_state_hint", "next_step_hint"):
            value = self._operator_text(experience.get(key) or "").strip()
            if value and value not in guidance:
                guidance.append(value)
        projected["_empty_state_guidance"] = guidance
        return projected

    def _research_professional_target(
        self,
        *,
        payload: Any,
        status_code: int,
        user: Any,
    ) -> TuiResearchProfessionalTarget | None:
        """Return a fresh permission-filtered professional target for one research result."""

        if (
            user is None
            or getattr(user, "is_authenticated", False) is not True
            or getattr(user, "is_active", False) is not True
            or getattr(user, "pk", None) in (None, "")
        ):
            return None
        if not 200 <= status_code < 300 or not isinstance(payload, Mapping):
            return None
        if not (
            isinstance(payload.get("status"), str)
            and isinstance(payload.get("outcome"), str)
            and isinstance(payload.get("identity"), Mapping)
            and isinstance(payload.get("sections"), Mapping)
            and isinstance(payload.get("must_not_use_for_decision"), bool)
        ):
            return None
        stock_code = payload.get("stock_code")
        if not isinstance(stock_code, str) or not stock_code.strip():
            return None
        target_action = self._action_by_key("equity.valuation-overview", user=user)
        if target_action is None:
            return None
        if (
            str(target_action.get("screen_key") or "") != "research.asset-lab"
            or str(target_action.get("method") or "").upper() != "GET"
            or str(target_action.get("risk") or "").lower() != "read"
            or str(target_action.get("effect") or "read").lower() != "read"
            or bool(target_action.get("confirmation_required"))
            or bool(target_action.get("requires_password"))
            or str(target_action.get("sensitive_level") or "none").lower() != "none"
        ):
            return None
        fields = target_action.get("fields")
        if not isinstance(fields, list):
            return None
        has_safe_stock_path = any(
            isinstance(field, dict)
            and field.get("key") == "stock_code"
            and field.get("binding") == "path"
            and field.get("value_type", "string") == "string"
            and str(field.get("input_type") or "text").lower() == "text"
            and str(field.get("presentation_semantic") or "").lower()
            not in {"api_token", "copyable_secret", "endpoint_url", "prompt_text", "secret"}
            and field.get("sensitive") is not True
            and field.get("secret") is not True
            and str(field.get("sensitive_level") or "none").lower() == "none"
            for field in fields
        )
        if not has_safe_stock_path:
            return None
        label = target_action.get("label")
        target: TuiResearchProfessionalTarget = {
            "screen_key": "research.asset-lab",
            "action_key": "equity.valuation-overview",
        }
        if isinstance(label, str) and label.strip():
            target["label"] = label.strip()
        return target

    def _apply_default_field_values(
        self,
        action: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = dict(params or {})
        for field in action.get("fields") or []:
            key = str(field.get("key") or "").strip()
            if not key:
                continue
            default = self._resolved_field_default(action, field)
            if default in (None, ""):
                continue
            if resolved.get(key) in (None, ""):
                resolved[key] = default
        return resolved

    def _confirmation_required_payload(
        self, action: dict[str, Any], *, user: Any | None = None
    ) -> dict[str, Any]:
        message = f"此操作会修改系统状态：{action['label']}。确认后才会执行。"
        view_model = self._message_model(action, message, 409)
        view_model["status"] = "待确认"
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action, user=user),
            "confirmation_required": True,
            "confirmation": {
                "title": "确认操作",
                "message": message,
                "confirm_label": "确认执行",
                "cancel_label": "取消",
            },
            "response": {"status_code": 409},
            "view_model": view_model,
            "debug": {"raw_available": False, "raw_response": None},
            **self._result_head_payload(view_model),
        }

    def _password_challenge_required_payload(
        self,
        action: dict[str, Any],
        *,
        attempted: bool = False,
        user: Any | None = None,
    ) -> dict[str, Any]:
        message = (
            "密码验证未通过，请重新输入当前登录用户密码。"
            if attempted
            else f"此操作需要重新验证身份：{action['label']}。"
        )
        view_model = self._message_model(action, message, 401)
        view_model["status"] = "需要密码"
        view_model["sections"] = [
            {
                "title": "身份验证",
                "rows": [],
                "body": [message, "验证通过前不会执行后端动作。"],
            }
        ]
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action, user=user),
            "confirmation_required": False,
            "password_challenge_required": True,
            "password_challenge": {
                "challenge_id": str(action.get("key") or ""),
                "message": message,
                "field": {
                    "key": "password",
                    "label": "密码",
                    "input_type": "password",
                    "required": True,
                },
            },
            "response": {"status_code": 401},
            "view_model": view_model,
            "debug": {"raw_available": False, "raw_response": None},
            **self._result_head_payload(view_model),
        }

    def _missing_required_fields(
        self,
        action: dict[str, Any],
        params: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for field in action.get("fields") or []:
            if not field.get("required"):
                continue
            key = str(field.get("key") or "")
            if not key:
                continue
            if self._resolved_field_default(action, field) not in (None, ""):
                continue
            value = params.get(key)
            if value in (None, "") or (isinstance(value, list) and not value):
                missing.append(self._field_payload(field, action=action, user=user))
        return missing

    def _missing_required_fields_payload(
        self,
        action: dict[str, Any],
        missing_fields: list[dict[str, Any]],
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        labels = [str(field.get("label") or field.get("key") or "") for field in missing_fields]
        message = f"执行“{action['label']}”前需要补充参数：{', '.join(labels)}。"
        view_model = self._message_model(action, message, 400)
        view_model["status"] = "需要参数"
        view_model["sections"] = [
            {
                "title": "需要补充参数",
                "rows": [
                    {
                        "label": str(field.get("label") or field.get("key") or ""),
                        "value": str(
                            field.get("placeholder")
                            or f"请输入{field.get('label') or field.get('key')}"
                        ),
                    }
                    for field in missing_fields
                ],
                "body": [
                    "在左侧任务表单填写后再执行。",
                    "如果当前表格已有对应记录，可先选中一行，再按 F9 进入任务区使用“从选中行填参”，或用右侧“选中行可做”自动填参。",
                ],
            }
        ]
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action, user=user),
            "confirmation_required": False,
            "response": {"status_code": 400},
            "view_model": view_model,
            "missing_fields": missing_fields,
            "debug": {"raw_available": False, "raw_response": None},
            **self._result_head_payload(view_model),
        }

    def _result_head_payload(self, view_model: dict[str, Any] | None) -> dict[str, Any]:
        model = view_model if isinstance(view_model, dict) else {}
        return {
            "business_summary": str(model.get("business_summary") or ""),
            "blocking_reason": str(model.get("blocking_reason") or ""),
            "next_steps": list(model.get("next_steps") or []),
            "debug_hidden_fields": list(model.get("debug_hidden_fields") or []),
            "user_error_code": str(model.get("user_error_code") or ""),
        }

    def _bind_endpoint_params(
        self, *, endpoint: str, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Substitute reviewed path placeholders and leave the rest as query/body params."""

        bound = "/" + endpoint.lstrip("/")
        remaining = dict(params)

        def replace_converter(match: re.Match[str]) -> str:
            name = match.group("name")
            return self._pop_path_value(remaining, name)

        def replace_braced(match: re.Match[str]) -> str:
            name = match.group("name")
            return self._pop_path_value(remaining, name)

        def replace_colon(match: re.Match[str]) -> str:
            name = match.group("name")
            return f"/{self._pop_path_value(remaining, name)}"

        bound = re.sub(
            r"<(?:(?P<converter>[a-zA-Z_][a-zA-Z0-9_]*):)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>",
            replace_converter,
            bound,
        )
        bound = re.sub(r"\{(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\}", replace_braced, bound)
        bound = re.sub(r"/:(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)", replace_colon, bound)
        if re.search(r"(<[^>]+>|\{[^}]+\}|/:[a-zA-Z_][a-zA-Z0-9_]*)", bound):
            raise ValueError("Action requires path parameters before it can run")
        return bound, remaining

    def _pop_path_value(self, params: dict[str, Any], name: str) -> str:
        value = params.pop(name, None)
        if value in (None, ""):
            raise ValueError(f"Missing required path parameter: {name}")
        text = str(value).strip()
        if "/" in text or "?" in text or "#" in text:
            raise ValueError(f"Unsafe path parameter: {name}")
        return text
