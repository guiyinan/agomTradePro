"""
Terminal Application Use Cases.

定义终端命令相关的业务用例。
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.entities import (
    CommandType,
    TerminalAuditEntry,
    TerminalCommand,
    TerminalMode,
    TerminalRiskLevel,
)
from ..domain.interfaces import TerminalAuditRepository, TerminalCommandRepository
from ..domain.services import TerminalPermissionService

logger = logging.getLogger(__name__)


# ========== Request/Response DTOs ==========

@dataclass
class ExecuteCommandRequest:
    """执行命令请求"""
    command_name: str
    params: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    # 治理字段
    user_id: int | None = None
    username: str = 'unknown'
    user_role: str = 'read_only'
    mcp_enabled: bool = False
    terminal_mode: str = 'confirm_each'
    confirmation_token: str | None = None


@dataclass
class ExecuteCommandResponse:
    """执行命令响应"""
    success: bool
    output: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    command: TerminalCommand | None = None
    # 确认相关
    confirmation_required: bool = False
    confirmation_token: str | None = None
    confirmation_prompt: str | None = None
    command_summary: str | None = None
    risk_level: str | None = None


@dataclass
class CreateCommandRequest:
    """创建命令请求"""
    name: str
    description: str
    command_type: str
    # Prompt配置
    prompt_template_id: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str = ''
    # API配置
    api_endpoint: str | None = None
    api_method: str = 'GET'
    response_jq_filter: str | None = None
    # 参数
    parameters: list[dict] = field(default_factory=list)
    # 其他配置
    timeout: int = 60
    provider_name: str | None = None
    model_name: str | None = None
    risk_level: str = TerminalRiskLevel.READ.value
    requires_mcp: bool = True
    enabled_in_terminal: bool = True
    category: str = 'general'
    tags: list[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class CreateCommandResponse:
    """创建命令响应"""
    success: bool
    command: TerminalCommand | None = None
    error: str | None = None


@dataclass
class UpdateCommandRequest:
    """更新命令请求"""
    command_id: str
    name: str | None = None
    description: str | None = None
    command_type: str | None = None
    prompt_template_id: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    api_endpoint: str | None = None
    api_method: str | None = None
    response_jq_filter: str | None = None
    parameters: list[dict] | None = None
    timeout: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
    risk_level: str | None = None
    requires_mcp: bool | None = None
    enabled_in_terminal: bool | None = None
    category: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


@dataclass
class UpdateCommandResponse:
    """更新命令响应"""
    success: bool
    command: TerminalCommand | None = None
    error: str | None = None


# ========== Use Cases ==========

class ExecuteCommandUseCase:
    """执行终端命令用例"""

    def __init__(
        self,
        repository: TerminalCommandRepository,
        execution_service,
        audit_repository: TerminalAuditRepository | None = None,
    ):
        self._repository = repository
        self._execution_service = execution_service
        self._audit_repository = audit_repository
        self._permission_service = TerminalPermissionService()

    def _log_audit(
        self,
        request: ExecuteCommandRequest,
        command: TerminalCommand | None,
        result_status: str,
        confirmation_status: str = 'not_required',
        confirmation_required: bool = False,
        error_message: str = '',
        duration_ms: int = 0,
    ) -> None:
        """记录审计日志"""
        if not self._audit_repository:
            return
        try:
            entry = TerminalAuditEntry(
                user_id=request.user_id,
                username=request.username,
                session_id=request.session_id or '',
                command_name=request.command_name,
                risk_level=command.risk_level.value if command else 'unknown',
                mode=request.terminal_mode,
                params_summary=json.dumps(request.params, default=str)[:500],
                confirmation_required=confirmation_required,
                confirmation_status=confirmation_status,
                result_status=result_status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            self._audit_repository.save(entry)
        except Exception:
            logger.exception("Failed to save terminal audit log")

    def execute(self, request: ExecuteCommandRequest) -> ExecuteCommandResponse:
        """执行命令（含治理逻辑）"""
        start_time = time.monotonic()

        # 1. 获取命令定义
        command = self._repository.get_by_name(request.command_name)
        if not command:
            return ExecuteCommandResponse(
                success=False,
                error=f"Command '{request.command_name}' not found",
            )

        if not command.is_active or not command.enabled_in_terminal:
            self._log_audit(request, command, 'blocked', error_message='Command inactive or disabled')
            return ExecuteCommandResponse(
                success=False,
                error=f"Command '{request.command_name}' is not available",
            )

        # 2. MCP 检查
        if command.requires_mcp and not request.mcp_enabled:
            self._log_audit(request, command, 'blocked', error_message='MCP access required')
            return ExecuteCommandResponse(
                success=False,
                error="This command requires MCP access which is disabled for your account",
                risk_level=command.risk_level.value,
            )

        # 3. 角色权限检查
        if not self._permission_service.can_execute(request.user_role, command.risk_level):
            self._log_audit(request, command, 'blocked', error_message='Permission denied')
            return ExecuteCommandResponse(
                success=False,
                error=f"Your role '{request.user_role}' cannot execute {command.risk_level.value} commands",
                risk_level=command.risk_level.value,
            )

        # 4. 模式逻辑
        mode = request.terminal_mode
        is_write = command.risk_level != TerminalRiskLevel.READ

        if mode == TerminalMode.READONLY.value and is_write:
            self._log_audit(request, command, 'blocked', error_message='Readonly mode')
            return ExecuteCommandResponse(
                success=False,
                error="Terminal is in read-only mode. Write commands are not allowed.",
                risk_level=command.risk_level.value,
            )

        if mode == TerminalMode.CONFIRM_EACH.value and is_write:
            if not request.confirmation_token:
                # 生成确认令牌
                from .confirmation import ConfirmationTokenService
                token_service = ConfirmationTokenService()
                token, details = token_service.create_token(
                    user_id=request.user_id or 0,
                    command_name=request.command_name,
                    params=request.params,
                    risk_level=command.risk_level.value,
                    mode=mode,
                )
                self._log_audit(
                    request, command, 'pending',
                    confirmation_status='not_required',
                    confirmation_required=True,
                )
                return ExecuteCommandResponse(
                    success=False,
                    confirmation_required=True,
                    confirmation_token=token,
                    confirmation_prompt=(
                        f"Command: {request.command_name}\n"
                        f"Risk Level: {command.risk_level.value}\n"
                        f"Parameters: {json.dumps(request.params, default=str)}\n"
                        f"Mode: {mode}\n\n"
                        f"Type Y to confirm, N to cancel:"
                    ),
                    command_summary=command.description,
                    risk_level=command.risk_level.value,
                    command=command,
                )
            else:
                # 验证令牌
                from .confirmation import ConfirmationTokenService
                token_service = ConfirmationTokenService()
                is_valid, error_msg = token_service.validate_token(
                    token=request.confirmation_token,
                    user_id=request.user_id or 0,
                    command_name=request.command_name,
                    params=request.params,
                    risk_level=command.risk_level.value,
                    mode=mode,
                )
                if not is_valid:
                    self._log_audit(
                        request, command, 'blocked',
                        confirmation_status='expired',
                        confirmation_required=True,
                        error_message=error_msg,
                    )
                    return ExecuteCommandResponse(
                        success=False,
                        error=f"Confirmation failed: {error_msg}",
                        risk_level=command.risk_level.value,
                    )

        # 5. 检查必需参数
        missing_params = command.get_missing_params(request.params)
        if missing_params:
            return ExecuteCommandResponse(
                success=False,
                error="Missing required parameters",
                metadata={'missing_params': [p.to_dict() for p in missing_params]},
                command=command,
                risk_level=command.risk_level.value,
            )

        # 6. 合并默认值
        params = {**command.get_param_defaults(), **request.params}

        # 7. 执行
        try:
            if command.is_prompt_type:
                result = self._execution_service.execute_prompt_command(
                    command=command,
                    params=params,
                    session_id=request.session_id,
                    provider_name=request.provider_name or command.provider_name,
                    model_name=request.model_name or command.model_name,
                )
            else:
                result = self._execution_service.execute_api_command(
                    command=command,
                    params=params,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            confirmation_status = 'confirmed' if is_write and mode == TerminalMode.CONFIRM_EACH.value else 'not_required'
            self._log_audit(
                request, command, 'success',
                confirmation_status=confirmation_status,
                confirmation_required=is_write and mode == TerminalMode.CONFIRM_EACH.value,
                duration_ms=duration_ms,
            )

            return ExecuteCommandResponse(
                success=True,
                output=result.get('output', ''),
                metadata=result.get('metadata', {}),
                command=command,
                risk_level=command.risk_level.value,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception(f"Failed to execute command '{request.command_name}'")
            self._log_audit(
                request, command, 'error',
                error_message=str(e),
                duration_ms=duration_ms,
            )
            return ExecuteCommandResponse(
                success=False,
                error=str(e),
                command=command,
                risk_level=command.risk_level.value,
            )


class ListCommandsUseCase:
    """列出命令用例"""

    def __init__(self, repository: TerminalCommandRepository):
        self._repository = repository

    def execute(self, category: str | None = None, include_inactive: bool = False) -> list[TerminalCommand]:
        """获取命令列表"""
        if category:
            return self._repository.get_by_category(category)
        elif include_inactive and hasattr(self._repository, "get_all"):
            return self._repository.get_all()
        else:
            return self._repository.get_all_active()


class CreateCommandUseCase:
    """创建命令用例"""

    def __init__(self, repository: TerminalCommandRepository):
        self._repository = repository

    def execute(self, request: CreateCommandRequest) -> CreateCommandResponse:
        """创建新命令"""
        import uuid

        # 检查名称是否已存在
        if self._repository.exists_by_name(request.name):
            return CreateCommandResponse(
                success=False,
                error=f"Command '{request.name}' already exists"
            )

        # 构建实体
        from ..domain.entities import CommandParameter
        parameters = [CommandParameter.from_dict(p) for p in request.parameters]

        command = TerminalCommand(
            id=str(uuid.uuid4()),
            name=request.name,
            description=request.description,
            command_type=CommandType(request.command_type),
            prompt_template_id=request.prompt_template_id,
            system_prompt=request.system_prompt,
            user_prompt_template=request.user_prompt_template,
            api_endpoint=request.api_endpoint,
            api_method=request.api_method,
            response_jq_filter=request.response_jq_filter,
            parameters=parameters,
            timeout=request.timeout,
            provider_name=request.provider_name,
            model_name=request.model_name,
            risk_level=TerminalRiskLevel(request.risk_level),
            requires_mcp=request.requires_mcp,
            enabled_in_terminal=request.enabled_in_terminal,
            category=request.category,
            tags=request.tags,
            is_active=request.is_active,
        )

        # 保存
        saved_command = self._repository.save(command)

        return CreateCommandResponse(
            success=True,
            command=saved_command
        )


class UpdateCommandUseCase:
    """更新命令用例"""

    def __init__(self, repository: TerminalCommandRepository):
        self._repository = repository

    def execute(self, request: UpdateCommandRequest) -> UpdateCommandResponse:
        """更新命令"""
        # 获取现有命令
        command = self._repository.get_by_id(request.command_id)
        if not command:
            return UpdateCommandResponse(
                success=False,
                error=f"Command with id '{request.command_id}' not found"
            )

        # 检查名称冲突
        if request.name and request.name != command.name:
            if self._repository.exists_by_name(request.name, exclude_id=request.command_id):
                return UpdateCommandResponse(
                    success=False,
                    error=f"Command name '{request.name}' already exists"
                )

        # 更新字段
        if request.name is not None:
            command.name = request.name
        if request.description is not None:
            command.description = request.description
        if request.command_type is not None:
            command.command_type = CommandType(request.command_type)
        if request.prompt_template_id is not None:
            command.prompt_template_id = request.prompt_template_id
        if request.system_prompt is not None:
            command.system_prompt = request.system_prompt
        if request.user_prompt_template is not None:
            command.user_prompt_template = request.user_prompt_template
        if request.api_endpoint is not None:
            command.api_endpoint = request.api_endpoint
        if request.api_method is not None:
            command.api_method = request.api_method
        if request.response_jq_filter is not None:
            command.response_jq_filter = request.response_jq_filter
        if request.parameters is not None:
            from ..domain.entities import CommandParameter
            command.parameters = [CommandParameter.from_dict(p) for p in request.parameters]
        if request.timeout is not None:
            command.timeout = request.timeout
        if request.provider_name is not None:
            command.provider_name = request.provider_name
        if request.model_name is not None:
            command.model_name = request.model_name
        if request.risk_level is not None:
            command.risk_level = TerminalRiskLevel(request.risk_level)
        if request.requires_mcp is not None:
            command.requires_mcp = request.requires_mcp
        if request.enabled_in_terminal is not None:
            command.enabled_in_terminal = request.enabled_in_terminal
        if request.category is not None:
            command.category = request.category
        if request.tags is not None:
            command.tags = request.tags
        if request.is_active is not None:
            command.is_active = request.is_active

        # 保存
        saved_command = self._repository.save(command)

        return UpdateCommandResponse(
            success=True,
            command=saved_command
        )


class DeleteCommandUseCase:
    """删除命令用例"""

    def __init__(self, repository: TerminalCommandRepository):
        self._repository = repository

    def execute(self, command_id: str) -> bool:
        """删除命令"""
        return self._repository.delete(command_id)
