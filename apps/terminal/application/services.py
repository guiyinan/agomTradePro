"""
Terminal Application Services.

命令执行服务实现。
"""

import json
import logging
import re
from typing import Any, Optional

import requests

from ..domain.entities import TerminalCommand


logger = logging.getLogger(__name__)


class CommandExecutionService:
    """命令执行服务"""
    
    def __init__(self):
        self._ai_client_factory = None
    
    @property
    def ai_client_factory(self):
        """延迟加载AI客户端工厂"""
        if self._ai_client_factory is None:
            from apps.ai_provider.infrastructure.client_factory import AIClientFactory
            self._ai_client_factory = AIClientFactory()
        return self._ai_client_factory
    
    def execute_prompt_command(
        self,
        command: TerminalCommand,
        params: dict[str, Any],
        session_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        执行Prompt类型命令
        
        Returns:
            dict with 'output' and 'metadata' keys
        """
        # 构建用户提示
        user_prompt = command.user_prompt_template
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            user_prompt = user_prompt.replace(placeholder, str(value))
        
        # 构建消息
        messages = []
        if command.system_prompt:
            messages.append({"role": "system", "content": command.system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # 获取AI客户端
        client = self.ai_client_factory.get_client(provider_name)
        
        # 调用AI
        response = client.chat_completion(
            messages=messages,
            model=model_name,
            temperature=0.7,
            max_tokens=2000,
        )
        
        return {
            'output': response.get('content', ''),
            'metadata': {
                'provider': provider_name or 'default',
                'model': model_name or 'default',
                'tokens': response.get('usage', {}).get('total_tokens', 0),
                'session_id': session_id,
            }
        }
    
    def execute_api_command(
        self,
        command: TerminalCommand,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        执行API类型命令
        
        Returns:
            dict with 'output' and 'metadata' keys
        """
        # 替换URL中的参数占位符
        url = command.api_endpoint
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            url = url.replace(placeholder, str(value))
        
        # 构建请求参数
        request_params = {}
        for key, value in params.items():
            if f"{{{key}}}" not in command.api_endpoint:
                request_params[key] = value
        
        # 发送请求
        try:
            if command.api_method.upper() == 'GET':
                response = requests.get(url, params=request_params, timeout=command.timeout)
            else:
                response = requests.request(
                    method=command.api_method.upper(),
                    url=url,
                    json=request_params,
                    timeout=command.timeout
                )
            
            response.raise_for_status()
            data = response.json()
            
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            return {
                'output': f"API request failed: {e}",
                'metadata': {'error': str(e)}
            }
        
        # 应用JQ过滤
        output = data
        if command.response_jq_filter:
            try:
                output = self._apply_jq_filter(data, command.response_jq_filter)
            except Exception as e:
                logger.warning(f"JQ filter failed: {e}, returning raw data")
        
        # 格式化输出
        if isinstance(output, (dict, list)):
            output_str = json.dumps(output, indent=2, ensure_ascii=False)
        else:
            output_str = str(output)
        
        return {
            'output': output_str,
            'metadata': {
                'api_endpoint': command.api_endpoint,
                'api_method': command.api_method,
                'status_code': response.status_code,
            }
        }
    
    def _apply_jq_filter(self, data: Any, filter_expr: str) -> Any:
        """
        应用简单的JQ-like过滤器
        
        支持基本的路径访问: .key, .key[0], .key.subkey
        """
        # 简化实现，支持基本的点语法路径
        if not filter_expr.startswith('.'):
            return data
        
        path = filter_expr[1:].split('.')
        result = data
        
        for part in path:
            if not part:
                continue
            
            # 处理数组索引: key[0]
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                result = result[key][int(index)]
            elif part.isdigit():
                result = result[int(part)]
            elif isinstance(result, dict):
                result = result.get(part)
            else:
                return None
        
        return result
