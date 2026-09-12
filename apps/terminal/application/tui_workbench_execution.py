"""Action execution helpers for the TUI workbench."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from apps.terminal.application.tui_audit import verified_reauth_evidence


class TuiWorkbenchExecutionMixin:
    """Execution and preflight response helpers for the TUI workbench."""

    if TYPE_CHECKING:
        from apps.terminal.domain.interfaces import TuiActionExecutor

        action_executor: TuiActionExecutor | None

        def _action_by_key(
            self, action_key: str, *, user: Any | None = None
        ) -> dict[str, Any] | None: ...

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
        resolved_params = self._apply_default_field_values(action, params or {})
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
            status_code = int(result.get("status_code", 200))
            payload = result.get("payload")
            projection_action = self._action_with_empty_state_context(action)
            view_model = self._to_view_model(
                action=projection_action,
                payload=payload,
                status_code=status_code,
                request_params=request_params,
            )
            envelope = {
                "version": "tui-workbench.v2",
                "outcome": self._execution_outcome(payload, status_code),
                "action": self._action_payload(action, user=user),
                "confirmation_required": False,
                "response": {
                    "status_code": status_code,
                },
                "view_model": view_model,
                "debug": {
                    "raw_available": bool(action.get("raw_debug", True)),
                    "raw_response": payload if action.get("raw_debug", True) else None,
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
            outcome=("succeeded" if 200 <= status_code < 400 else "failed"),
            confirmation_evidence=confirmation,
            reauth_evidence=reauth_evidence,
            result=envelope,
        )
        return envelope

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
            if payload.get("success") is False or source.get("success") is False:
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
