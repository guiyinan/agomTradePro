"""Operation log factory domain services for Audit.

Pure factory logic for building operation audit log entities.
Only uses Python standard library (no pandas/numpy).
"""

from typing import Any

from .entities import OperationLog

__all__ = [
    "OperationLogFactory",
]


# ============ MCP/SDK 操作审计日志服务 ============


class OperationLogFactory:
    """
    操作日志工厂

    负责创建操作日志实体，封装创建逻辑和参数推断。
    """

    @staticmethod
    def create_from_mcp_call(
        request_id: str,
        tool_name: str,
        user_id: int | None = None,
        username: str = "anonymous",
        source: str | None = None,
        operation_type: str | None = None,
        module: str | None = None,
        action: str | None = None,
        request_params: dict | None = None,
        response_payload: Any | None = None,
        response_text: str = "",
        response_status: int = 200,
        response_message: str = "",
        error_code: str = "",
        exception_traceback: str = "",
        duration_ms: int | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        client_id: str = "",
        mcp_role: str = "",
        sdk_version: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
        mcp_client_id: str = "",
        request_method: str = "MCP",
        request_path: str = "",
    ) -> "OperationLog":
        """
        从 MCP 工具调用创建操作日志

        Args:
            request_id: 链路追踪ID
            tool_name: MCP 工具名
            user_id: 用户ID
            username: 用户名
            source: 来源（MCP/SDK/API），不传则自动推断
            operation_type: 操作类型，不传则自动推断
            module: 模块名，不传则自动推断
            action: 动作类型，不传则自动推断
            request_params: 请求参数（将被脱敏）
            response_payload: 结构化响应内容（将被脱敏）
            response_text: 响应文本快照
            response_status: 响应状态码
            response_message: 响应消息
            error_code: 错误代码
            exception_traceback: 异常堆栈
            duration_ms: 耗时（毫秒）
            ip_address: IP 地址
            user_agent: User Agent
            client_id: 客户端ID
            mcp_role: MCP 角色
            sdk_version: SDK 版本
            resource_type: 资源类型
            resource_id: 资源ID
            mcp_client_id: MCP 客户端 ID
            request_method: 请求方法
            request_path: 请求路径

        Returns:
            OperationLog: 操作日志实体
        """
        from .entities import (
            OperationAction,
            OperationLog,
            OperationSource,
            OperationType,
            infer_action_from_tool,
            infer_module_from_tool,
        )

        # 推断或使用传入的模块和动作
        if not module:
            module = infer_module_from_tool(tool_name)
        if not action:
            action_enum = infer_action_from_tool(tool_name)
            action = action_enum.value

        # 解析枚举值
        if source:
            source_enum = OperationSource(source.upper())
        else:
            source_enum = OperationSource.MCP

        if operation_type:
            operation_type_enum = OperationType(operation_type.upper())
        else:
            operation_type_enum = OperationType.MCP_CALL

        if isinstance(action, str):
            action_enum = OperationAction(action.upper())
        else:
            action_enum = action

        # 构建请求路径
        if not request_path:
            request_path = f"/mcp/tools/{tool_name}"

        return OperationLog.create(
            request_id=request_id,
            user_id=user_id,
            username=username,
            source=source_enum,
            operation_type=operation_type_enum,
            module=module,
            action=action_enum,
            mcp_tool_name=tool_name,
            request_params=request_params,
            response_payload=response_payload,
            response_text=response_text,
            response_status=response_status,
            response_message=response_message,
            error_code=error_code,
            exception_traceback=exception_traceback,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            client_id=client_id,
            resource_type=resource_type,
            resource_id=resource_id,
            mcp_client_id=mcp_client_id or client_id,
            mcp_role=mcp_role,
            sdk_version=sdk_version,
            request_method=request_method,
            request_path=request_path,
        )

    @staticmethod
    def create_from_api_call(
        request_id: str,
        user_id: int | None,
        username: str,
        request_method: str,
        request_path: str,
        request_params: dict | None = None,
        response_payload: Any | None = None,
        response_text: str = "",
        response_status: int = 200,
        response_message: str = "",
        error_code: str = "",
        exception_traceback: str = "",
        duration_ms: int | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        client_id: str = "",
        resource_type: str = "",
        resource_id: str | None = None,
    ) -> "OperationLog":
        """
        从 API 调用创建操作日志

        Args:
            request_id: 链路追踪ID
            user_id: 用户ID
            username: 用户名
            request_method: 请求方法（GET/POST/PUT/DELETE）
            request_path: 请求路径
            request_params: 请求参数（将被脱敏）
            response_payload: 结构化响应内容（将被脱敏）
            response_text: 响应文本快照
            response_status: 响应状态码
            response_message: 响应消息
            error_code: 错误代码
            exception_traceback: 异常堆栈
            duration_ms: 耗时（毫秒）
            ip_address: IP 地址
            user_agent: User Agent
            client_id: 客户端ID
            resource_type: 资源类型
            resource_id: 资源ID

        Returns:
            OperationLog: 操作日志实体
        """
        from .entities import (
            OperationAction,
            OperationLog,
            OperationSource,
            OperationType,
            infer_module_from_tool,
        )

        # 从路径推断模块
        module = infer_module_from_tool(request_path)

        # 从请求方法推断动作
        action_map = {
            "GET": OperationAction.READ,
            "POST": OperationAction.CREATE,
            "PUT": OperationAction.UPDATE,
            "PATCH": OperationAction.UPDATE,
            "DELETE": OperationAction.DELETE,
        }
        action = action_map.get(request_method.upper(), OperationAction.READ)

        # 判断操作类型
        if action in (OperationAction.CREATE, OperationAction.UPDATE, OperationAction.DELETE):
            operation_type = OperationType.DATA_MODIFY
        else:
            operation_type = OperationType.API_ACCESS

        return OperationLog.create(
            request_id=request_id,
            user_id=user_id,
            username=username,
            source=OperationSource.API,
            operation_type=operation_type,
            module=module,
            action=action,
            request_method=request_method,
            request_path=request_path,
            request_params=request_params,
            response_payload=response_payload,
            response_text=response_text,
            response_status=response_status,
            response_message=response_message,
            error_code=error_code,
            exception_traceback=exception_traceback,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            client_id=client_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
