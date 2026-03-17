"""
Terminal Domain Entities.

终端命令的领域实体定义。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class CommandType(Enum):
    """命令类型枚举"""
    PROMPT = 'prompt'  # 调用Prompt模板
    API = 'api'        # 调用系统API


class ParameterType(Enum):
    """参数类型枚举"""
    TEXT = 'text'
    NUMBER = 'number'
    SELECT = 'select'
    DATE = 'date'
    BOOLEAN = 'boolean'


@dataclass
class CommandParameter:
    """命令参数定义"""
    name: str
    param_type: ParameterType
    description: str = ''
    required: bool = True
    default: Any = None
    options: list[str] = field(default_factory=list)
    prompt: str = ''  # 交互式提示文本
    
    def __post_init__(self):
        if isinstance(self.param_type, str):
            self.param_type = ParameterType(self.param_type)
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'type': self.param_type.value,
            'description': self.description,
            'required': self.required,
            'default': self.default,
            'options': self.options,
            'prompt': self.prompt,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CommandParameter':
        return cls(
            name=data['name'],
            param_type=ParameterType(data.get('type', 'text')),
            description=data.get('description', ''),
            required=data.get('required', True),
            default=data.get('default'),
            options=data.get('options', []),
            prompt=data.get('prompt', ''),
        )


@dataclass
class TerminalCommand:
    """终端命令实体"""
    id: str
    name: str
    description: str
    command_type: CommandType
    is_active: bool = True
    
    # Prompt类型配置
    prompt_template_id: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: str = ''
    
    # API类型配置
    api_endpoint: Optional[str] = None
    api_method: str = 'GET'
    response_jq_filter: Optional[str] = None
    
    # 参数定义
    parameters: list[CommandParameter] = field(default_factory=list)
    
    # 执行配置
    timeout: int = 60
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    
    # 元数据
    category: str = 'general'
    tags: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if isinstance(self.command_type, str):
            self.command_type = CommandType(self.command_type)
    
    @property
    def is_prompt_type(self) -> bool:
        return self.command_type == CommandType.PROMPT
    
    @property
    def is_api_type(self) -> bool:
        return self.command_type == CommandType.API
    
    def get_missing_params(self, provided: dict[str, Any]) -> list[CommandParameter]:
        """获取缺失的必需参数"""
        missing = []
        for param in self.parameters:
            if param.required and param.name not in provided:
                missing.append(param)
        return missing
    
    def get_param_defaults(self) -> dict[str, Any]:
        """获取所有参数的默认值"""
        return {
            p.name: p.default 
            for p in self.parameters 
            if p.default is not None
        }
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'type': self.command_type.value,
            'is_active': self.is_active,
            'prompt_template_id': self.prompt_template_id,
            'system_prompt': self.system_prompt,
            'user_prompt_template': self.user_prompt_template,
            'api_endpoint': self.api_endpoint,
            'api_method': self.api_method,
            'response_jq_filter': self.response_jq_filter,
            'parameters': [p.to_dict() for p in self.parameters],
            'timeout': self.timeout,
            'provider_name': self.provider_name,
            'model_name': self.model_name,
            'category': self.category,
            'tags': self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TerminalCommand':
        params = [CommandParameter.from_dict(p) for p in data.get('parameters', [])]
        return cls(
            id=data['id'],
            name=data['name'],
            description=data.get('description', ''),
            command_type=CommandType(data.get('type', 'prompt')),
            is_active=data.get('is_active', True),
            prompt_template_id=data.get('prompt_template_id'),
            system_prompt=data.get('system_prompt'),
            user_prompt_template=data.get('user_prompt_template', ''),
            api_endpoint=data.get('api_endpoint'),
            api_method=data.get('api_method', 'GET'),
            response_jq_filter=data.get('response_jq_filter'),
            parameters=params,
            timeout=data.get('timeout', 60),
            provider_name=data.get('provider_name'),
            model_name=data.get('model_name'),
            category=data.get('category', 'general'),
            tags=data.get('tags', []),
        )
