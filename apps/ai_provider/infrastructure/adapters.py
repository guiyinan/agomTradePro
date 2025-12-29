"""
OpenAI Compatible API Adapter.

通用OpenAI兼容API适配器，支持多个AI提供商。
只需配置不同的base_url和api_key即可使用不同提供商。
"""

import time
from typing import List, Dict, Optional, Any

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class OpenAICompatibleAdapter:
    """
    通用OpenAI兼容API适配器

    支持的提供商（只需配置不同的base_url）:
    - OpenAI: https://api.openai.com/v1
    - DeepSeek: https://api.deepseek.com/v1
    - 通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1
    - Moonshot: https://api.moonshot.cn/v1
    - 以及其他兼容OpenAI API格式的提供商
    """

    def __init__(self, base_url: str, api_key: str, default_model: str = "gpt-3.5-turbo"):
        """
        初始化适配器

        Args:
            base_url: API Base URL
            api_key: API密钥
            default_model: 默认模型名称
        """
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "需要安装 openai 库。请运行: agomsaaf/Scripts/pip install openai"
            )

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.default_model = default_model
        self.base_url = base_url

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        执行聊天补全请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称（不指定则使用default_model）
            temperature: 温度参数（0-2）
            max_tokens: 最大输出token数
            stream: 是否流式输出

        Returns:
            Dict: 响应结果
                {
                    "content": str,
                    "model": str,
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "total_tokens": int,
                    "finish_reason": str,
                    "response_time_ms": int,
                    "status": "success" | "error",
                    "error_message": str | None
                }
        """
        model = model or self.default_model
        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream
            )

            response_time_ms = int((time.time() - start_time) * 1000)

            return {
                "content": response.choices[0].message.content,
                "model": response.model,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "finish_reason": response.choices[0].finish_reason,
                "response_time_ms": response_time_ms,
                "status": "success",
                "error_message": None
            }

        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)

            # 判断错误类型
            status = "error"
            if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                status = "rate_limited"
            elif "timeout" in error_msg.lower():
                status = "timeout"

            return {
                "content": None,
                "model": model,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "finish_reason": None,
                "response_time_ms": response_time_ms,
                "status": status,
                "error_message": error_msg
            }

    def is_available(self) -> bool:
        """
        检查服务是否可用

        Returns:
            bool: 服务是否可用
        """
        try:
            # 尝试获取模型列表
            self.client.models.list()
            return True
        except Exception:
            return False

    def estimate_tokens(self, text: str) -> int:
        """
        粗略估算文本的token数量

        Args:
            text: 输入文本

        Returns:
            int: 估算的token数量
        """
        # 粗略估算：英文约4字符/token，中文约1.5字符/token
        # 这里使用平均值
        return max(1, len(text) // 3)


class AIFailoverHelper:
    """
    AI故障转移辅助类

    支持按优先级尝试多个AI提供商。
    """

    def __init__(self, providers: List[Dict[str, Any]]):
        """
        初始化故障转移辅助类

        Args:
            providers: 提供商列表
                [
                    {"base_url": "...", "api_key": "...", "default_model": "...", "name": "..."},
                    ...
                ]
        """
        self.providers = providers
        self.adapters = []

        for p in providers:
            try:
                adapter = OpenAICompatibleAdapter(
                    base_url=p['base_url'],
                    api_key=p['api_key'],
                    default_model=p.get('default_model', 'gpt-3.5-turbo')
                )
                self.adapters.append({
                    'adapter': adapter,
                    'name': p.get('name', 'unknown'),
                    'is_available': adapter.is_available()
                })
            except Exception as e:
                # 某个适配器初始化失败不影响其他
                pass

    def chat_completion_with_failover(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        带故障转移的聊天补全

        按优先级依次尝试每个可用的提供商，直到成功或全部失败。

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            Dict: 响应结果（包含实际使用的提供商信息）
        """
        last_error = None

        for item in self.adapters:
            if not item['is_available']:
                continue

            try:
                result = item['adapter'].chat_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

                if result['status'] == 'success':
                    result['provider_used'] = item['name']
                    return result

                last_error = result.get('error_message')

            except Exception as e:
                last_error = str(e)
                continue

        # 全部失败
        return {
            "content": None,
            "model": model or "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": f"All providers failed. Last error: {last_error}",
            "provider_used": None
        }
