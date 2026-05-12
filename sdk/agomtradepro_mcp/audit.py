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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_RESPONSE_TEXT_LENGTH = 200000


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
    def create(cls, **kwargs) -> AuditContext:
        """创建审计上下文"""
        return cls(
            request_id=kwargs.get('request_id') or str(uuid.uuid4()),
            user_id=kwargs.get('user_id'),
            username=kwargs.get('username', 'anonymous'),
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent', ''),
            client_id=kwargs.get('client_id', ''),
            mcp_role=kwargs.get('mcp_role', ''),
            sdk_version=kwargs.get('sdk_version', ''),
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
        self.backend_url = backend_url or os.getenv(
            'AGOMTRADEPRO_AUDIT_URL',
            'http://127.0.0.1:8000/api/audit/internal/operation-logs/'
        )
        self.secret_key = secret_key or os.getenv(
            'AGOMTRADEPRO_AUDIT_SECRET_KEY',
            os.getenv('AUDIT_INTERNAL_SECRET_KEY', '')
        )
        self.enabled = os.getenv('AGOMTRADEPRO_AUDIT_ENABLED', 'true').lower() in ('true', '1', 'yes')

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
            'request_id': context.request_id,
            'user_id': context.user_id,
            'username': context.username,
            'source': 'MCP',
            'operation_type': 'MCP_CALL',
            'module': module,
            'action': action,
            'mcp_tool_name': tool_name,
            'request_params': masked_params,
            'response_payload': response_payload,
            'response_text': response_text,
            'response_status': response_status,
            'response_message': response_message,
            'error_code': error_code,
            'exception_traceback': exception_traceback,
            'duration_ms': duration_ms,
            'ip_address': context.ip_address,
            'user_agent': context.user_agent,
            'client_id': context.client_id,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'mcp_client_id': context.client_id,
            'mcp_role': context.mcp_role,
            'sdk_version': context.sdk_version,
            'request_method': 'MCP',
            'request_path': f'/mcp/tools/{tool_name}',
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
            'GET': 'READ',
            'POST': 'CREATE',
            'PUT': 'UPDATE',
            'PATCH': 'UPDATE',
            'DELETE': 'DELETE',
        }
        action = action_map.get(method.upper(), 'READ')

        # 确定操作类型
        if action in ('CREATE', 'UPDATE', 'DELETE'):
            operation_type = 'DATA_MODIFY'
        else:
            operation_type = 'API_ACCESS'

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
            'request_id': context.request_id,
            'user_id': context.user_id,
            'username': context.username,
            'source': 'SDK',
            'operation_type': operation_type,
            'module': module,
            'action': action,
            'mcp_tool_name': None,
            'request_params': masked_params,
            'response_payload': response_payload,
            'response_text': response_text,
            'response_status': response_status,
            'response_message': response_message,
            'error_code': error_code,
            'exception_traceback': exception_traceback,
            'duration_ms': duration_ms,
            'ip_address': context.ip_address,
            'user_agent': context.user_agent,
            'client_id': context.client_id,
            'resource_type': '',
            'resource_id': None,
            'mcp_client_id': '',
            'mcp_role': '',
            'sdk_version': context.sdk_version,
            'request_method': method,
            'request_path': path,
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
        try:
            import requests

            # 生成时间戳
            timestamp = str(int(time.time()))

            # 计算签名
            signature = self._compute_signature(timestamp, data)

            headers = {
                'Content-Type': 'application/json',
                'X-Audit-Timestamp': timestamp,
                'X-Audit-Signature': signature,
            }

            response = requests.post(
                self.backend_url,
                json=data,
                headers=headers,
                timeout=5,  # 5 秒超时
            )

            if response.status_code in (200, 201):
                result = response.json()
                if isinstance(result, dict) and result.get('success') is False:
                    logger.warning(
                        "审计日志写入被后端拒绝: "
                        f"response={str(result)[:200]}"
                    )
                    self._failure_count += 1
                    return None
                log_id = result.get('log_id')
                logger.debug(f"审计日志已记录: log_id={log_id}")
                return log_id
            else:
                logger.warning(
                    f"审计日志写入失败: status={response.status_code}, "
                    f"response={response.text[:200]}"
                )
                self._failure_count += 1
                return None

        except requests.RequestException as e:
            # 网络错误不阻塞主流程
            logger.warning(f"审计日志发送失败（网络错误）: {e}")
            self._failure_count += 1
            return None
        except Exception as e:
            # 其他错误不阻塞主流程
            logger.error(f"审计日志发送失败: {e}", exc_info=True)
            self._failure_count += 1
            return None

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
            self.secret_key.encode('utf-8'),
            sign_content.encode('utf-8'),
            hashlib.sha256
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
        elif name_lower.startswith("update_") or name_lower.startswith("modify_") or name_lower.startswith("edit_"):
            return "UPDATE"
        elif name_lower.startswith("delete_") or name_lower.startswith("remove_"):
            return "DELETE"
        elif name_lower.startswith("execute_") or name_lower.startswith("run_") or name_lower.startswith("submit_"):
            return "EXECUTE"
        else:
            return "READ"

    @staticmethod
    def _mask_sensitive_params(params: Any, mask: str = "***") -> Any:
        """脱敏敏感参数"""
        sensitive_keywords = frozenset([
            "password", "token", "secret", "api_key", "apikey",
            "authorization", "cookie", "session", "credential",
            "private_key", "access_key", "secret_key",
        ])

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
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): cls._normalize_for_json(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
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
