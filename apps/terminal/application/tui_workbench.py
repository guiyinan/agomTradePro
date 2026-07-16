"""Published-metadata driven TUI workbench contracts and view models."""

from __future__ import annotations

import re
from typing import Any

from apps.ai_provider.application.query_services import has_user_personal_providers
from apps.alpha_trigger.application.query_services import (
    has_alpha_candidates,
    has_alpha_triggers,
)
from apps.asset_analysis.application.asset_name_service import resolve_asset_names
from apps.beta_gate.application.query_services import (
    has_beta_gate_configs,
    has_beta_gate_decisions,
    has_beta_gate_universe_snapshots,
)
from apps.config_center.application.query_services import has_qlib_training_runs
from apps.dashboard.application.query_services import has_dashboard_alpha_history
from apps.task_monitor.application.query_services import has_recent_task_failures
from apps.terminal.application.tui_audit import (
    TuiTerminalAuditSink,
    action_requires_audit,
    build_tui_audit_record,
    verified_reauth_evidence,
)
from apps.terminal.application.tui_errors import (
    TuiScreenForbiddenError,
    TuiScreenNotFoundError,
)
from apps.terminal.application.tui_workbench_catalog import TuiWorkbenchCatalogMixin
from apps.terminal.application.tui_workbench_result_models import (
    TuiWorkbenchResultModelMixin,
)
from apps.terminal.domain.interfaces import (
    TerminalAuditRepository,
    TuiActionExecutor,
    TuiMetadataRepository,
)
from core.integration.runtime_imports import (
    has_active_cooldowns,
    has_decision_quotas,
    has_recent_decision_requests,
)

VISIBLE_RUNTIME_RISKS = {"read", "ai", "write"}
ADMIN_RUNTIME_RISKS = {"admin"}
USER_HIDDEN_SCREEN_ACTION_KEYS = {
    "param.api.get.api.dashboard.position.str.asset_code",
    "param.api.get.api.valuation.snapshot.str.snapshot_id",
    "param.api.get.api.decision.workspace.plans.str.plan_id",
    "param.api.get.api.audit.indicator-performance.str.indicator_code",
    "param.api.get.api.system.status.str.task_id",
}
USER_CONDITIONAL_SCREEN_ACTIONS = {
    "param.api.get.api.ai.me.providers.pk": lambda user: has_user_personal_providers(user),
    "param.api.get.api.dashboard.alpha.history.int.run_id": lambda user: has_dashboard_alpha_history(
        user
    ),
    "auto.api.get.api.decision-rhythm.quotas.by-period": lambda _user: has_decision_quotas(),
    "param.api.get.api.decision-rhythm.cooldowns.by-asset.asset_code": lambda _user: has_active_cooldowns(),
    "auto.api.get.api.decision-rhythm.cooldowns.remaining-hours": lambda _user: has_active_cooldowns(),
    "param.api.get.api.decision-rhythm.requests.pk": lambda _user: has_recent_decision_requests(),
    "param.api.get.api.beta-gate.configs.pk": lambda _user: has_beta_gate_configs(),
    "param.api.get.api.beta-gate.decisions.pk": lambda _user: has_beta_gate_decisions(),
    "param.api.get.api.beta-gate.universe.pk": lambda _user: has_beta_gate_universe_snapshots(),
    "param.api.get.api.alpha-triggers.triggers.by-regime.regime": lambda _user: has_alpha_triggers(),
    "param.api.get.api.alpha-triggers.triggers.pk": lambda _user: has_alpha_triggers(),
    "param.api.get.api.alpha-triggers.candidates.pk": lambda _user: has_alpha_candidates(),
    "auto.api.get.api.system.statistics": lambda _user: has_recent_task_failures(),
    "config_center.training_run_detail": lambda _user: has_qlib_training_runs(),
}


class TuiWorkbenchRegistry:
    """Compatibility facade for the first TUI workbench endpoints."""

    def __init__(self, metadata_repository: TuiMetadataRepository) -> None:
        self._service = TuiWorkbenchService(metadata_repository=metadata_repository)

    def list_modules(self, *, user: Any | None = None) -> dict[str, Any]:
        """Return the legacy registry shape using the published catalog."""

        catalog = self._service.get_catalog(user=user)
        return {
            "version": "tui-workbench.v2",
            "default_module": catalog["default_screen"].split(".")[0],
            "interaction_model": catalog["interaction_model"],
            "principles": catalog["principles"],
            "groups": [
                {
                    "key": group["key"],
                    "label": group["label"].upper(),
                    "modules": group["modules"],
                }
                for group in catalog["groups"]
            ],
        }

    def get_module_snapshot(self, module_key: str, *, user: Any | None = None) -> dict[str, Any]:
        """Return a legacy snapshot mapped from the first screen in a module."""

        catalog = self._service.get_catalog(user=user)
        screen_key = catalog["default_screen"]
        for group in catalog["groups"]:
            for module in group["modules"]:
                if module["key"] == module_key and module.get("screens"):
                    screen_key = module["screens"][0]["key"]
                    break
        screen = self._service.get_screen(
            screen_key,
            include_technical_actions=True,
            user=user,
        )
        return {
            "version": "tui-workbench.v2",
            "module": screen["module"],
            "layout": screen["layout"],
            "blocks": screen["blocks"],
            "actions": screen["actions"],
        }


class TuiWorkbenchService(TuiWorkbenchCatalogMixin, TuiWorkbenchResultModelMixin):
    """Application service for metadata-published TUI catalog and actions."""

    def __init__(
        self,
        *,
        metadata_repository: TuiMetadataRepository,
        action_executor: TuiActionExecutor | None = None,
        audit_repository: TerminalAuditRepository | None = None,
        require_audit_sink: bool = False,
        registry_key: str = "default",
    ) -> None:
        self.metadata_repository = metadata_repository
        self.action_executor = action_executor
        self.audit_sink = (
            TuiTerminalAuditSink(audit_repository) if audit_repository is not None else None
        )
        self.require_audit_sink = require_audit_sink
        self.registry_key = registry_key
        self._account_options_cache: dict[int, list[dict[str, Any]]] = {}
        self._metadata_snapshot: dict[str, Any] | None = None
        self._action_index: dict[str, dict[str, Any]] | None = None
        self._screen_index: dict[str, dict[str, Any]] | None = None
        self._module_index: dict[str, dict[str, Any]] | None = None
        self._action_availability_cache: dict[tuple[str, str, int, int], bool] = {}

    def get_catalog(self, *, user: Any | None = None) -> dict[str, Any]:
        """Return grouped modules and screens from published metadata only."""

        metadata = self._metadata()
        actions = self._catalog_visible_actions(metadata, user=user)
        actions_by_screen = self._actions_by_screen(actions)
        screens_by_module = self._screens_by_module(metadata)
        groups: list[dict[str, Any]] = []

        for group in metadata["groups"]:
            group_modules = []
            for module in metadata["modules"]:
                if module["group"] != group["key"]:
                    continue
                screens = []
                for screen in screens_by_module.get(module["key"], []):
                    if not self._screen_is_available_for_user(screen, user=user):
                        continue
                    screen_actions = actions_by_screen.get(screen["key"], [])
                    if not screen_actions and screen["key"] != metadata["default_screen"]:
                        continue
                    screens.append(self._screen_summary(screen, screen_actions, user=user))
                if not screens:
                    continue
                group_modules.append(
                    {
                        **self._module_summary(module),
                        "screens": screens,
                        "action_count": sum(screen["action_count"] for screen in screens),
                    }
                )
            if group_modules:
                groups.append(
                    {"key": group["key"], "label": group["label"], "modules": group_modules}
                )

        return {
            "version": metadata["version"],
            "registry_key": metadata.get("registry_key", self.registry_key),
            "interaction_model": metadata.get(
                "interaction_model", "published-metadata-to-pc-tools"
            ),
            "default_screen": metadata["default_screen"],
            "principles": metadata.get("principles", []),
            "stats": self._catalog_stats(metadata, actions),
            "groups": groups,
            "modules": [self._module_summary(module) for module in metadata["modules"]],
        }

    def get_bootstrap(
        self,
        *,
        requested_screen: str = "",
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Return catalog and the initial screen from one metadata snapshot."""

        catalog = self.get_catalog(user=user)
        requested = str(requested_screen or "").strip()
        resolved = requested or str(catalog["default_screen"])
        try:
            screen = self.get_screen(resolved, user=user)
        except TuiScreenNotFoundError:
            resolved = str(catalog["default_screen"])
            screen = self.get_screen(resolved, user=user)
        return {
            "contract": "tui-bootstrap.v1",
            "catalog": catalog,
            "screen": screen,
            "requested_screen": requested,
            "resolved_screen": resolved,
            "restored": bool(
                requested and requested == resolved and requested != catalog["default_screen"]
            ),
        }

    def get_screen(
        self,
        screen_key: str,
        *,
        include_technical_actions: bool = False,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Return a renderable screen contract from published metadata."""

        metadata = self._metadata()
        screen = self._screen_by_key(metadata).get(screen_key)
        if screen is None:
            raise TuiScreenNotFoundError(screen_key)
        if not self._screen_is_available_for_user(screen, user=user):
            raise TuiScreenForbiddenError(screen_key)
        module = self._module_by_key(metadata)[screen["module_key"]]
        actions = list(
            self._screen_visible_actions(
                metadata,
                user=user,
                include_technical=include_technical_actions,
                screen_key=screen["key"],
            )
        )
        return {
            "version": metadata["version"],
            "registry_key": metadata.get("registry_key", self.registry_key),
            "screen": self._screen_summary(screen, actions, user=user),
            "module": self._module_summary(module),
            "layout": {
                "type": "pc-tools-workbench",
                "regions": ("module_tree", "workspace", "inspector", "status_bar", "raw_drawer"),
                "default_view": screen["view_type"],
            },
            "blocks": [
                {
                    "type": "screen-context",
                    "title": self._operator_text(screen["label"]),
                    "body": self._operator_text(screen["summary"]),
                    "status": screen.get("status", "online"),
                },
                {
                    "type": "actions",
                    "title": "任务",
                    "items": [
                        self._action_payload(
                            action,
                            include_technical=include_technical_actions,
                            user=user,
                        )
                        for action in actions
                    ],
                },
            ],
            "actions": [
                self._action_payload(
                    action,
                    include_technical=include_technical_actions,
                    user=user,
                )
                for action in actions
            ],
        }

    def search_agent_actions(
        self,
        *,
        query: str = "",
        limit: int = 10,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Search published user actions with a bounded, token-light payload."""

        effective_limit = max(1, min(int(limit), 20))
        normalized_query = str(query or "").strip().lower()
        query_terms = {
            term for term in normalized_query.replace("-", " ").replace("_", " ").split() if term
        }
        matches: list[tuple[int, dict[str, Any]]] = []
        for action in self._visible_actions(self._metadata(), user=user):
            haystack = " ".join(
                str(action.get(key) or "")
                for key in (
                    "key",
                    "label",
                    "description",
                    "intent",
                    "screen_key",
                    "module_key",
                    "task_group",
                )
            ).lower()
            score = 1
            if normalized_query:
                score = 5 if normalized_query in haystack else 0
                score += sum(2 for term in query_terms if term in haystack)
                if score <= 0:
                    continue
            matches.append((score, action))

        matches.sort(key=lambda item: (-item[0], str(item[1].get("key") or "")))
        actions = [
            self._agent_action_summary(action, user=user) for _, action in matches[:effective_limit]
        ]
        return {
            "query": str(query or ""),
            "actions": actions,
            "returned_count": len(actions),
            "limit": effective_limit,
        }

    def get_agent_action_schema(
        self,
        action_key: str,
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Return one visible action schema without exposing its raw endpoint."""

        action = self._action_by_key(action_key, user=user)
        if action is None:
            raise KeyError(action_key)
        payload = self._action_payload(action, user=user)
        return {
            "action_key": payload["key"],
            "label": payload["label"],
            "description": payload["description"],
            "intent": payload["intent"],
            "screen_key": payload["screen_key"],
            "risk": payload["risk"],
            "requires_confirmation": payload["confirmation_required"],
            "fields": payload["fields"],
            "result_semantics": payload["result_semantics"],
        }

    def _agent_action_summary(
        self,
        action: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Return compact discovery metadata for one published action."""

        payload = self._action_payload(action, user=user)
        return {
            "action_key": payload["key"],
            "label": payload["label"],
            "description": payload["description"],
            "intent": payload["intent"],
            "screen_key": payload["screen_key"],
            "risk": payload["risk"],
            "requires_confirmation": payload["confirmation_required"],
            "required_fields": [
                {
                    "key": str(field.get("key") or ""),
                    "label": str(field.get("label") or ""),
                }
                for field in payload["fields"]
                if bool(field.get("required"))
            ],
        }

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
    ) -> dict[str, Any]:
        """Execute one published action and return a business-first view model."""

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
            result = self.action_executor.execute(
                method=method,
                endpoint=endpoint,
                params=request_params if method == "GET" else {},
                body=request_params if method != "GET" else {},
                user=user,
                session=session,
            )
            status_code = int(result.get("status_code", 200))
            payload = result.get("payload")
            view_model = self._to_view_model(
                action=action,
                payload=payload,
                status_code=status_code,
                request_params=request_params,
            )
            envelope = {
                "version": "tui-workbench.v2",
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
            outcome=(
                "succeeded" if 200 <= int(envelope["response"]["status_code"]) < 400 else "failed"
            ),
            confirmation_evidence=confirmation,
            reauth_evidence=reauth_evidence,
            result=envelope,
        )
        return envelope

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

    def _metadata(self) -> dict[str, Any]:
        if self._metadata_snapshot is None:
            self._metadata_snapshot = self.metadata_repository.load_published(self.registry_key)
        return self._metadata_snapshot

    def _allowed_runtime_risks(self, user: Any | None) -> set[str]:
        allowed = set(VISIBLE_RUNTIME_RISKS)
        if self._is_admin_user(user):
            allowed |= ADMIN_RUNTIME_RISKS
        return allowed

    def _is_admin_user(self, user: Any | None) -> bool:
        if user is None:
            return False
        if bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
            return True
        role = str(getattr(user, "rbac_role", "") or "").strip().lower()
        if role == "admin":
            return True
        profile = getattr(user, "account_profile", None)
        profile_role = str(getattr(profile, "rbac_role", "") or "").strip().lower()
        return profile_role == "admin"

    def _screen_is_available_for_user(
        self, screen: dict[str, Any], *, user: Any | None = None
    ) -> bool:
        """Return whether one published screen belongs to the user's audience."""

        audience = str(screen.get("audience") or "authenticated")
        if audience == "admin":
            return self._is_admin_user(user)
        return audience == "authenticated"

    def _visible_actions(
        self, metadata: dict[str, Any], *, user: Any | None = None
    ) -> list[dict[str, Any]]:
        return [
            action
            for action in metadata["actions"]
            if str(action.get("risk")) in self._allowed_runtime_risks(user)
            and self._action_is_available_for_user(action, user=user)
        ]

    def _catalog_visible_actions(
        self,
        metadata: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return potential catalog actions without evaluating row-dependent providers."""

        return [
            action
            for action in metadata["actions"]
            if str(action.get("risk")) in self._allowed_runtime_risks(user)
            and str(action.get("key") or "") not in USER_HIDDEN_SCREEN_ACTION_KEYS
        ]

    def _screen_visible_actions(
        self,
        metadata: dict[str, Any],
        *,
        user: Any | None = None,
        include_technical: bool = False,
        screen_key: str = "",
    ) -> list[dict[str, Any]]:
        candidates = list(metadata["actions"])
        if screen_key:
            candidates = [
                action for action in candidates if str(action.get("screen_key") or "") == screen_key
            ]
        actions = [
            action
            for action in candidates
            if str(action.get("risk")) in self._allowed_runtime_risks(user)
            and self._action_is_available_for_user(action, user=user)
        ]
        if include_technical:
            return actions
        return [
            action
            for action in actions
            if str(action.get("key") or "") not in USER_HIDDEN_SCREEN_ACTION_KEYS
        ]

    def _action_is_available_for_user(
        self,
        action: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> bool:
        action_key = str(action.get("key") or "")
        predicate = USER_CONDITIONAL_SCREEN_ACTIONS.get(action_key)
        if predicate is not None:
            user_fragment = self._availability_user_fragment(user)
            cache_key = (
                action_key,
                user_fragment,
                id(predicate),
                self._availability_provider_version(action_key),
            )
            if cache_key in self._action_availability_cache:
                return self._action_availability_cache[cache_key]
            available = bool(predicate(user))
            self._action_availability_cache[cache_key] = available
            return available
        return True

    @staticmethod
    def _availability_provider_version(action_key: str) -> int:
        """Return the live provider identity so tests and hot reloads cannot reuse stale values."""

        if action_key == "param.api.get.api.ai.me.providers.pk":
            return id(has_user_personal_providers)
        if action_key == "param.api.get.api.dashboard.alpha.history.int.run_id":
            return id(has_dashboard_alpha_history)
        if "decision-rhythm.quotas" in action_key:
            return id(has_decision_quotas)
        if "decision-rhythm.cooldowns" in action_key:
            return id(has_active_cooldowns)
        if "decision-rhythm.requests.pk" in action_key:
            return id(has_recent_decision_requests)
        if "beta-gate.configs" in action_key:
            return id(has_beta_gate_configs)
        if "beta-gate.decisions" in action_key:
            return id(has_beta_gate_decisions)
        if "beta-gate.universe" in action_key:
            return id(has_beta_gate_universe_snapshots)
        if "alpha-triggers.triggers" in action_key:
            return id(has_alpha_triggers)
        if "alpha-triggers.candidates" in action_key:
            return id(has_alpha_candidates)
        if action_key == "auto.api.get.api.system.statistics":
            return id(has_recent_task_failures)
        if action_key == "config_center.training_run_detail":
            return id(has_qlib_training_runs)
        return 0

    def _availability_user_fragment(self, user: Any | None) -> str:
        user_id = getattr(user, "pk", None)
        role = str(getattr(user, "rbac_role", "") or "")
        return (
            f"{user_id if user_id is not None else 'anon'}:{role}:{int(self._is_admin_user(user))}"
        )

    def _action_by_key(self, action_key: str, *, user: Any | None = None) -> dict[str, Any] | None:
        if self._action_index is None:
            self._action_index = {
                str(action["key"]): action for action in self._metadata()["actions"]
            }
        action = self._action_index.get(action_key)
        if action is None:
            return None
        if str(action.get("risk")) not in self._allowed_runtime_risks(user):
            return None
        return action if self._action_is_available_for_user(action, user=user) else None

    def _requires_confirmation(self, action: dict[str, Any]) -> bool:
        if bool(action.get("confirmation_required")):
            return True
        risk = str(action.get("risk") or "").lower()
        method = str(action.get("method") or "GET").upper()
        return risk == "write" or (risk == "admin" and method != "GET")

    def _requires_password(self, action: dict[str, Any]) -> bool:
        return bool(action.get("requires_password"))

    def _reauth_verified(self, user: Any | None, reauth: dict[str, Any] | None) -> bool:
        if not isinstance(reauth, dict):
            return False
        if str(reauth.get("method") or "").lower() != "password":
            return False
        credential = str(reauth.get("credential") or "")
        if not credential:
            return False
        checker = getattr(user, "check_password", None)
        if not callable(checker):
            return False
        return bool(checker(credential))

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
    ) -> None:
        if not action_requires_audit(action) or self.audit_sink is None:
            return
        try:
            username = str(getattr(user, "username", "") or "anonymous")
            record = build_tui_audit_record(
                action,
                params,
                actor=username,
                outcome=outcome,
                confirmation_evidence=confirmation_evidence,
                reauth_evidence=reauth_evidence,
                result=result,
                error=error,
            )
            self.audit_sink.append(
                record,
                user_id=getattr(user, "id", None),
                username=username,
                session_id=self._session_id(session),
            )
        except Exception:
            if self.require_audit_sink:
                raise
            return

    def _ensure_tui_audit_sink(self, action: dict[str, Any]) -> None:
        if self.require_audit_sink and action_requires_audit(action) and self.audit_sink is None:
            raise RuntimeError(
                f"Audit sink is required for audit_required action: {action.get('key')}"
            )

    def _session_id(self, session: Any | None) -> str:
        if session is None:
            return ""
        return str(getattr(session, "session_key", "") or "")

    def _actions_by_screen(self, actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for action in actions:
            grouped.setdefault(action["screen_key"], []).append(action)
        return grouped

    def _screens_by_module(self, metadata: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for screen in metadata["screens"]:
            grouped.setdefault(screen["module_key"], []).append(screen)
        return grouped

    def _module_by_key(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if self._module_index is None:
            self._module_index = {module["key"]: module for module in metadata["modules"]}
        return self._module_index

    def _screen_by_key(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if self._screen_index is None:
            self._screen_index = {screen["key"]: screen for screen in metadata["screens"]}
        return self._screen_index

    def _resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        return resolve_asset_names(codes)
