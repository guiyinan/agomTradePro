"""
Terminal Application Use Cases.

定义终端命令相关的业务用例。
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import logging

from ..domain.entities import TerminalCommand, CommandType
from ..domain.interfaces import TerminalCommandRepository


logger = logging.getLogger(__name__)


# ========== Request/Response DTOs ==========

@dataclass
class ExecuteCommandRequest:
    """执行命令请求"""
    command_name: str
    params: dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None


@dataclass
class ExecuteCommandResponse:
    """执行命令响应"""
    success: bool
    output: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    command: Optional[TerminalCommand] = None


@dataclass
class CreateCommandRequest:
    """创建命令请求"""
    name: str
    description: str
    command_type: str
    # Prompt配置
    prompt_template_id: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: str = ''
    # API配置
    api_endpoint: Optional[str] = None
    api_method: str = 'GET'
    response_jq_filter: Optional[str] = None
    # 参数
    parameters: list[dict] = field(default_factory=list)
    # 其他配置
    timeout: int = 60
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    category: str = 'general'
    tags: list[str] = field(default_factory=list)


@dataclass
class CreateCommandResponse:
    """创建命令响应"""
    success: bool
    command: Optional[TerminalCommand] = None
    error: Optional[str] = None


@dataclass
class UpdateCommandRequest:
    """更新命令请求"""
    command_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    command_type: Optional[str] = None
    prompt_template_id: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_method: Optional[str] = None
    response_jq_filter: Optional[str] = None
    parameters: Optional[list[dict]] = None
    timeout: Optional[int] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None


@dataclass
class UpdateCommandResponse:
    """更新命令响应"""
    success: bool
    command: Optional[TerminalCommand] = None
    error: Optional[str] = None


# ========== Use Cases ==========

class ExecuteCommandUseCase:
    """执行终端命令用例"""
    
    def __init__(self, repository: TerminalCommandRepository, execution_service):
        self._repository = repository
        self._execution_service = execution_service
    
    def execute(self, request: ExecuteCommandRequest) -> ExecuteCommandResponse:
        """执行命令"""
        # 1. 获取命令定义
        command = self._repository.get_by_name(request.command_name)
        if not command:
            return ExecuteCommandResponse(
                success=False,
                error=f"Command '{request.command_name}' not found"
            )
        
        if not command.is_active:
            return ExecuteCommandResponse(
                success=False,
                error=f"Command '{request.command_name}' is not active"
            )
        
        # 2. 检查必需参数
        missing_params = command.get_missing_params(request.params)
        if missing_params:
            return ExecuteCommandResponse(
                success=False,
                error="Missing required parameters",
                metadata={'missing_params': [p.to_dict() for p in missing_params]},
                command=command
            )
        
        # 3. 合并默认值
        params = {**command.get_param_defaults(), **request.params}
        
        # 4. 根据命令类型执行
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
            
            return ExecuteCommandResponse(
                success=True,
                output=result.get('output', ''),
                metadata=result.get('metadata', {}),
                command=command
            )
            
        except Exception as e:
            logger.exception(f"Failed to execute command '{request.command_name}'")
            return ExecuteCommandResponse(
                success=False,
                error=str(e),
                command=command
            )


class ListCommandsUseCase:
    """列出命令用例"""
    
    def __init__(self, repository: TerminalCommandRepository):
        self._repository = repository
    
    def execute(self, category: Optional[str] = None, include_inactive: bool = False) -> list[TerminalCommand]:
        """获取命令列表"""
        if category:
            return self._repository.get_by_category(category)
        elif include_inactive:
            # 获取所有命令（需要扩展仓储接口或直接使用ORM）
            return self._repository.get_all_active()
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
            category=request.category,
            tags=request.tags,
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
