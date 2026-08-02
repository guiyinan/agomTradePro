"""
MCP/SDK Operation Audit Logger.

This module provides audit logging for MCP tool calls and SDK operations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_RESPONSE_TEXT_LENGTH = 200000
DEFAULT_AUDIT_TIMEOUT_SECONDS = 5.0
DEFAULT_AUDIT_MAX_ATTEMPTS = 2
DEFAULT_AUDIT_RETRY_BACKOFF_SECONDS = 0.25
AuditSink = Callable[[dict[str, Any]], str | None]
_AUDIT_SINK: ContextVar[AuditSink | None] = ContextVar("agom_mcp_audit_sink", default=None)


def get_audit_sink() -> AuditSink | None:
    """Return the audit sink scoped to the current execution context."""

    return _AUDIT_SINK.get()


@contextmanager
def use_audit_sink(sink: AuditSink) -> Iterator[None]:
    """Persist audit events through ``sink`` for the current context only."""

    token = _AUDIT_SINK.set(sink)
    try:
        yield
    finally:
        _AUDIT_SINK.reset(token)


def _default_audit_backend_url() -> str:
    """Resolve audit ingest beside the configured AgomTradePro API."""

    explicit_url = os.getenv("AGOMTRADEPRO_AUDIT_URL", "").strip()
    if explicit_url:
        return explicit_url

    base_url = (
        os.getenv("AGOMTRADEPRO_BASE_URL")
        or os.getenv("AGOMTRADEPRO_API_BASE_URL")
        or "http://127.0.0.1:8000"
    )
    return f"{base_url.rstrip('/')}/api/audit/internal/operation-logs/"


def _resolve_audit_secret_key(explicit_secret: str | None = None) -> str:
    """Resolve the audit HMAC secret from explicit, environment, or Django config."""

    if explicit_secret:
        return explicit_secret
    environment_secret = (
        os.getenv("AGOMTRADEPRO_AUDIT_SECRET_KEY") or os.getenv("AUDIT_INTERNAL_SECRET_KEY") or ""
    ).strip()
    if environment_secret:
        return environment_secret
    try:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured
    except ImportError:
        return ""
    try:
        return str(getattr(settings, "AUDIT_INTERNAL_SECRET_KEY", "") or "").strip()
    except ImproperlyConfigured:
        return ""


@dataclass
class AuditContext:
    """审计上下文，用于收集审计信息"""

    request_id: str
    user_id: int | None = None
    username: str = "anonymous"
    ip_address: str | None = None
    user_agent: str = ""
    client_id: str = ""
    mcp_role: str = ""
    sdk_version: str = ""
    start_time: float = field(default_factory=time.time)

    @classmethod
    def create(cls, **kwargs: Any) -> AuditContext:
        """创建审计上下文"""
        return cls(
            request_id=kwargs.get("request_id") or str(uuid.uuid4()),
            user_id=kwargs.get("user_id"),
            username=kwargs.get("username", "anonymous"),
            ip_address=kwargs.get("ip_address"),
            user_agent=kwargs.get("user_agent", ""),
            client_id=kwargs.get("client_id", ""),
            mcp_role=kwargs.get("mcp_role", ""),
            sdk_version=kwargs.get("sdk_version", ""),
        )


class AuditLogger:
    """
    操作审计日志记录器

    负责将 MCP/SDK 工具调用记录到后端审计服务。
    审计失败不阻塞主流程。

    使用方式:
        audit = AuditLogger()
        audit.log_mcp_call(
            tool_name="create_signal",
            params={"asset_code": "000001.SH"},
            result={"status": "success"},
            error=None,
            context=context,
        )
    """

    # 审计失败计数（用于监控）
    _failure_count: int = 0

    def __init__(self, backend_url: str | None = None, secret_key: str | None = None):
        """
        初始化审计日志记录器

        Args:
            backend_url: 后端审计 API URL，默认从环境变量读取
            secret_key: 签名密钥，默认从环境变量读取
        """
        self.backend_url = backend_url or _default_audit_backend_url()
        self.secret_key = _resolve_audit_secret_key(secret_key)
        self.enabled = os.getenv("AGOMTRADEPRO_AUDIT_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )

    def log_mcp_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: Any,
        error: Exception | None,
        context: AuditContext,
        module: str = "",
        action: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
    ) -> str | None:
        """
        记录 MCP 工具调用

        Args:
            tool_name: 工具名称
            params: 调用参数
            result: 调用结果
            error: 错误信息（如果有）
            context: 审计上下文
            module: 模块名（可选，会自动推断）
            action: 动作类型（可选，会自动推断）
            resource_type: 资源类型
            resource_id: 资源 ID

        Returns:
            Optional[str]: 日志 ID，失败时返回 None
        """
        if not self.enabled:
            return None

        # 推断模块和动作
        if not module:
            module = self._infer_module(tool_name)
        if not action:
            action = self._infer_action(tool_name)

        # 确定响应状态
        if error:
            if isinstance(error, PermissionError):
                response_status = 403
                error_code = "RBAC_DENIED"
            else:
                response_status = 500
                error_code = type(error).__name__
            response_message = str(error)
        else:
            response_status = 200
            error_code = ""
            response_message = "Success"

        # 计算耗时
        duration_ms = int((time.time() - context.start_time) * 1000)

        # 脱敏参数
        masked_params = self._mask_sensitive_params(params)
        response_payload = self._serialize_payload(result)
        response_text = self._build_response_text(result)
        exception_traceback = self._format_exception_traceback(error)

        # 构建审计日志数据
        audit_data = {
            "request_id": context.request_id,
            "user_id": context.user_id,
            "username": context.username,
            "source": "MCP",
            "operation_type": "MCP_CALL",
            "module": module,
            "action": action,
            "mcp_tool_name": tool_name,
            "request_params": masked_params,
            "response_payload": response_payload,
            "response_text": response_text,
            "response_status": response_status,
            "response_message": response_message,
            "error_code": error_code,
            "exception_traceback": exception_traceback,
            "duration_ms": duration_ms,
            "ip_address": context.ip_address,
            "user_agent": context.user_agent,
            "client_id": context.client_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "mcp_client_id": context.client_id,
            "mcp_role": context.mcp_role,
            "sdk_version": context.sdk_version,
            "request_method": "MCP",
            "request_path": f"/mcp/tools/{tool_name}",
        }

        return self._send_audit_log(audit_data)

    def log_governed_capability_event(
        self,
        *,
        tool_name: str,
        capability_key: str,
        params: dict[str, Any],
        result: Any,
        error: Exception | None,
        context: AuditContext,
        owner_app: str = "",
        risk_level: str = "",
        event_type: str = "",
        confirmation_status: str = "",
        idempotency_key: str | None = None,
        request_arguments: dict[str, Any] | None = None,
        affected_objects: dict[str, Any] | None = None,
    ) -> str | None:
        """Record one governed capability lifecycle event."""
        if not self.enabled:
            return None

        if error:
            if isinstance(error, PermissionError):
                response_status = 403
                error_code = "RBAC_DENIED"
            else:
                response_status = 500
                error_code = type(error).__name__
            response_message = str(error)
        else:
            response_status = 200
            error_code = ""
            response_message = event_type or "Success"

        duration_ms = int((time.time() - context.start_time) * 1000)

        masked_params = self._mask_sensitive_params(
            {
                "capability_key": capability_key,
                "event_type": event_type,
                "confirmation_status": confirmation_status,
                "risk_level": risk_level,
                "idempotency_key": idempotency_key,
                "arguments": params,
                "request_arguments": request_arguments or params,
                "affected_objects": affected_objects or {},
            }
        )
        response_payload = self._serialize_payload(result)
        response_text = self._build_response_text(result)
        exception_traceback = self._format_exception_traceback(error)

        audit_data = {
            "request_id": context.request_id,
            "user_id": context.user_id,
            "username": context.username,
            "source": "MCP",
            "operation_type": "DATA_MODIFY",
            "module": owner_app or self._infer_module(capability_key),
            "action": self._infer_capability_action(capability_key),
            "mcp_tool_name": tool_name,
            "request_params": masked_params,
            "response_payload": response_payload,
            "response_text": response_text,
            "response_status": response_status,
            "response_message": response_message,
            "error_code": error_code,
            "exception_traceback": exception_traceback,
            "duration_ms": duration_ms,
            "ip_address": context.ip_address,
            "user_agent": context.user_agent,
            "client_id": context.client_id,
            "resource_type": "mcp_capability",
            "resource_id": capability_key,
            "mcp_client_id": context.client_id,
            "mcp_role": context.mcp_role,
            "sdk_version": context.sdk_version,
            "request_method": "MCP",
            "request_path": f"/mcp/capabilities/{capability_key}",
        }

        return self._send_audit_log(audit_data)

    def log_sdk_call(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        result: Any,
        error: Exception | None,
        context: AuditContext,
    ) -> str | None:
        """
        记录 SDK 调用

        Args:
            method: HTTP 方法
            path: 请求路径
            params: 请求参数
            result: 响应结果
            error: 错误信息（如果有）
            context: 审计上下文

        Returns:
            Optional[str]: 日志 ID，失败时返回 None
        """
        if not self.enabled:
            return None

        # 推断模块
        module = self._infer_module(path)

        # 推断动作
        action_map = {
            "GET": "READ",
            "POST": "CREATE",
            "PUT": "UPDATE",
            "PATCH": "UPDATE",
            "DELETE": "DELETE",
        }
        action = action_map.get(method.upper(), "READ")

        # 确定操作类型
        if action in ("CREATE", "UPDATE", "DELETE"):
            operation_type = "DATA_MODIFY"
        else:
            operation_type = "API_ACCESS"

        # 确定响应状态
        if error:
            if isinstance(error, PermissionError):
                response_status = 403
                error_code = "RBAC_DENIED"
            else:
                response_status = 500
                error_code = type(error).__name__
            response_message = str(error)
        else:
            response_status = 200
            error_code = ""
            response_message = "Success"

        # 计算耗时
        duration_ms = int((time.time() - context.start_time) * 1000)

        # 脱敏参数
        masked_params = self._mask_sensitive_params(params)
        response_payload = self._serialize_payload(result)
        response_text = self._build_response_text(result)
        exception_traceback = self._format_exception_traceback(error)

        # 构建审计日志数据
        audit_data = {
            "request_id": context.request_id,
            "user_id": context.user_id,
            "username": context.username,
            "source": "SDK",
            "operation_type": operation_type,
            "module": module,
            "action": action,
            "mcp_tool_name": None,
            "request_params": masked_params,
            "response_payload": response_payload,
            "response_text": response_text,
            "response_status": response_status,
            "response_message": response_message,
            "error_code": error_code,
            "exception_traceback": exception_traceback,
            "duration_ms": duration_ms,
            "ip_address": context.ip_address,
            "user_agent": context.user_agent,
            "client_id": context.client_id,
            "resource_type": "",
            "resource_id": None,
            "mcp_client_id": "",
            "mcp_role": "",
            "sdk_version": context.sdk_version,
            "request_method": method,
            "request_path": path,
        }

        return self._send_audit_log(audit_data)

    def _send_audit_log(self, data: dict[str, Any]) -> str | None:
        """
        发送审计日志到后端

        Args:
            data: 审计日志数据

        Returns:
            Optional[str]: 日志 ID，失败时返回 None
        """
        audit_sink = get_audit_sink()
        if audit_sink is not None:
            try:
                return audit_sink(data)
            except Exception as exc:
                logger.error("本地审计日志写入失败: %s", exc, exc_info=True)
                self._failure_count += 1
                return None

        try:
            import requests

            payload = dict(data)
            payload.setdefault("delivery_id", str(uuid.uuid4()))
            timeout = self._read_float_setting(
                "AGOMTRADEPRO_AUDIT_TIMEOUT_SECONDS",
                DEFAULT_AUDIT_TIMEOUT_SECONDS,
                minimum=0.1,
                maximum=30.0,
            )
            max_attempts = self._read_int_setting(
                "AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS",
                DEFAULT_AUDIT_MAX_ATTEMPTS,
                minimum=1,
                maximum=5,
            )
            retry_backoff = self._read_float_setting(
                "AGOMTRADEPRO_AUDIT_RETRY_BACKOFF_SECONDS",
                DEFAULT_AUDIT_RETRY_BACKOFF_SECONDS,
                minimum=0.0,
                maximum=5.0,
            )
            last_network_error: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                timestamp = str(int(time.time()))
                headers = {
                    "Content-Type": "application/json",
                    "X-Audit-Timestamp": timestamp,
                    "X-Audit-Signature": self._compute_signature(timestamp, payload),
                }
                api_token = os.getenv("AGOMTRADEPRO_API_TOKEN", "").strip()
                if api_token:
                    headers["Authorization"] = f"Token {api_token}"

                try:
                    response = requests.post(
                        self.backend_url,
                        json=payload,
                        headers=headers,
                        timeout=timeout,
                    )
                except requests.RequestException as exc:
                    last_network_error = exc
                    if attempt < max_attempts:
                        logger.info(
                            "审计日志发送失败，将重试: attempt=%s/%s, error=%s",
                            attempt,
                            max_attempts,
                            exc,
                        )
                        if retry_backoff:
                            time.sleep(retry_backoff * attempt)
                        continue
                    break

                if response.status_code in (200, 201):
                    result = response.json()
                    if isinstance(result, dict) and result.get("success") is False:
                        logger.warning("审计日志写入被后端拒绝: response=%s", str(result)[:200])
                        self._failure_count += 1
                        return None
                    raw_log_id = result.get("log_id")
                    log_id = str(raw_log_id) if raw_log_id is not None else None
                    logger.debug("审计日志已记录: log_id=%s", log_id)
                    return log_id

                retryable_status = response.status_code == 429 or response.status_code >= 500
                if retryable_status and attempt < max_attempts:
                    logger.info(
                        "审计日志写入暂时失败，将重试: attempt=%s/%s, status=%s",
                        attempt,
                        max_attempts,
                        response.status_code,
                    )
                    if retry_backoff:
                        time.sleep(retry_backoff * attempt)
                    continue

                logger.warning(
                    "审计日志写入失败: status=%s, response=%s",
                    response.status_code,
                    response.text[:200],
                )
                self._failure_count += 1
                return None

            logger.warning("审计日志发送失败（网络错误）: %s", last_network_error)
            self._failure_count += 1
            return None
        except Exception as e:
            # 其他错误不阻塞主流程
            logger.error(f"审计日志发送失败: {e}", exc_info=True)
            self._failure_count += 1
            return None

    @staticmethod
    def _read_float_setting(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        """Read a bounded floating-point audit setting from the environment."""

        try:
            value = float(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return min(max(value, minimum), maximum)

    @staticmethod
    def _read_int_setting(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        """Read a bounded integer audit setting from the environment."""

        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return min(max(value, minimum), maximum)

    def _compute_signature(self, timestamp: str, data: dict[str, Any]) -> str:
        """计算签名"""
        if not self.secret_key:
            # In local DEBUG setups the backend may intentionally skip HMAC validation
            # when no internal audit secret is configured, but it still requires a
            # non-empty signature header to treat the request as an internal ingest.
            return "debug-no-secret"

        body = json.dumps(data, sort_keys=True, ensure_ascii=False)
        sign_content = f"{timestamp}:{body}"
        return hmac.new(
            self.secret_key.encode("utf-8"), sign_content.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _infer_module(tool_name: str) -> str:
        """从工具名推断模块"""
        name_lower = tool_name.lower()

        module_keywords = {
            "signal": ["signal"],
            "policy": ["policy"],
            "backtest": ["backtest"],
            "regime": ["regime"],
            "macro": ["macro"],
            "account": ["account", "portfolio", "position", "transaction"],
            "equity": ["equity", "stock"],
            "fund": ["fund"],
            "sector": ["sector"],
            "strategy": ["strategy"],
            "alpha": ["alpha"],
            "factor": ["factor"],
            "rotation": ["rotation"],
            "hedge": ["hedge"],
            "realtime": ["realtime", "price"],
            "sentiment": ["sentiment"],
            "simulated": ["simulated", "trading"],
            "dashboard": ["dashboard"],
            "filter": ["filter"],
            "event": ["event"],
            "decision": ["decision"],
            "task": ["task", "monitor"],
            "ai_provider": ["ai_provider", "provider", "llm"],
            "prompt": ["prompt"],
        }

        for module, keywords in module_keywords.items():
            if any(kw in name_lower for kw in keywords):
                return module

        return "general"

    @staticmethod
    def _infer_action(tool_name: str) -> str:
        """从工具名推断动作"""
        name_lower = tool_name.lower()

        if name_lower.startswith("create_") or name_lower.startswith("add_"):
            return "CREATE"
        elif (
            name_lower.startswith("update_")
            or name_lower.startswith("modify_")
            or name_lower.startswith("edit_")
        ):
            return "UPDATE"
        elif name_lower.startswith("delete_") or name_lower.startswith("remove_"):
            return "DELETE"
        elif (
            name_lower.startswith("execute_")
            or name_lower.startswith("run_")
            or name_lower.startswith("submit_")
        ):
            return "EXECUTE"
        else:
            return "READ"

    @staticmethod
    def _infer_capability_action(capability_key: str) -> str:
        """Infer action from a governed capability key."""
        key_lower = capability_key.lower()

        if ".create." in key_lower:
            return "CREATE"
        if ".update." in key_lower or ".import." in key_lower:
            return "UPDATE"
        if ".delete." in key_lower or ".remove." in key_lower:
            return "DELETE"
        if (
            ".execute." in key_lower
            or ".execution_" in key_lower
            or ".run." in key_lower
            or ".start." in key_lower
            or ".submit." in key_lower
        ):
            return "EXECUTE"
        return "READ"

    @staticmethod
    def _mask_sensitive_params(params: Any, mask: str = "***") -> Any:
        """脱敏敏感参数"""
        sensitive_keywords = frozenset(
            [
                "password",
                "token",
                "secret",
                "api_key",
                "apikey",
                "authorization",
                "cookie",
                "session",
                "credential",
                "private_key",
                "access_key",
                "secret_key",
            ]
        )

        if isinstance(params, dict):
            masked = {}
            for key, value in params.items():
                key_lower = key.lower()
                if any(kw in key_lower for kw in sensitive_keywords):
                    masked[key] = mask
                else:
                    masked[key] = AuditLogger._mask_sensitive_params(value, mask)
            return masked
        elif isinstance(params, list):
            return [AuditLogger._mask_sensitive_params(item, mask) for item in params]
        else:
            return params

    @classmethod
    def _serialize_payload(cls, payload: Any) -> Any:
        """将返回值转换为适合 JSON 存储的结构，并做脱敏。"""
        if payload is None:
            return None

        normalized = cls._normalize_for_json(payload)
        return cls._mask_sensitive_params(normalized)

    @classmethod
    def _normalize_for_json(cls, value: Any) -> Any:
        """将任意对象转换为 JSON 兼容结构。"""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, dict):
            return {str(k): cls._normalize_for_json(v) for k, v in value.items()}
        if isinstance(value, list | tuple | set):
            return [cls._normalize_for_json(item) for item in value]
        if hasattr(value, "model_dump") and callable(value.model_dump):
            try:
                return cls._normalize_for_json(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "dict") and callable(value.dict):
            try:
                return cls._normalize_for_json(value.dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return cls._normalize_for_json(vars(value))
            except Exception:
                pass
        return {"type": type(value).__name__, "repr": repr(value)}

    @classmethod
    def _build_response_text(cls, payload: Any) -> str:
        """生成便于人工查看的响应文本快照。"""
        if payload is None:
            return ""

        normalized = cls._serialize_payload(payload)
        try:
            text = json.dumps(normalized, ensure_ascii=False, indent=2, default=str)
        except Exception:
            text = repr(normalized)

        if len(text) > MAX_RESPONSE_TEXT_LENGTH:
            overflow = len(text) - MAX_RESPONSE_TEXT_LENGTH
            text = f"{text[:MAX_RESPONSE_TEXT_LENGTH]}\n... [TRUNCATED {overflow} chars]"
        return text

    @staticmethod
    def _format_exception_traceback(error: Exception | None) -> str:
        """提取异常堆栈，便于后续回溯。"""
        if not error:
            return ""
        try:
            return "".join(traceback.format_exception(type(error), error, error.__traceback__))
        except Exception:
            return str(error)

    @classmethod
    def get_failure_count(cls) -> int:
        """获取失败计数"""
        return cls._failure_count

    @classmethod
    def reset_failure_count(cls) -> None:
        """重置失败计数"""
        cls._failure_count = 0


# 全局审计日志记录器实例
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """获取全局审计日志记录器"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """设置全局审计日志记录器"""
    global _audit_logger
    _audit_logger = logger
