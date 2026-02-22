"""
Domain Services for AI Cost Calculation.

纯业务逻辑 - 不依赖任何外部库。
遵循项目架构约束：Domain层只使用Python标准库。
"""

from typing import Dict, Tuple


class AICostCalculator:
    """
    AI成本计算服务

    纯算法实现，用于计算API调用的预估成本。
    """

    # 预设模型价格表（每1K tokens，单位：美元）
    MODEL_PRICING: Dict[str, Dict[str, float]] = {
        # OpenAI 模型
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},

        # DeepSeek 模型
        "deepseek-chat": {"input": 0.0001, "output": 0.0002},
        "deepseek-coder": {"input": 0.0001, "output": 0.0002},

        # 通义千问 模型
        "qwen-turbo": {"input": 0.0003, "output": 0.0006},
        "qwen-plus": {"input": 0.0008, "output": 0.002},
        "qwen-max": {"input": 0.02, "output": 0.06},

        # Moonshot 模型
        "moonshot-v1-8k": {"input": 0.012, "output": 0.012},
        "moonshot-v1-32k": {"input": 0.024, "output": 0.024},
    }

    @classmethod
    def calculate_cost(
        cls,
        model: str,
        prompt_tokens: int,
        completion_tokens: int
    ) -> float:
        """
        计算API调用成本

        Args:
            model: 模型名称
            prompt_tokens: 输入token数量
            completion_tokens: 输出token数量

        Returns:
            float: 成本（美元）
        """
        pricing = cls.MODEL_PRICING.get(model, {"input": 0.001, "output": 0.002})

        input_cost = (prompt_tokens / 1000.0) * pricing["input"]
        output_cost = (completion_tokens / 1000.0) * pricing["output"]

        return round(input_cost + output_cost, 6)

    @classmethod
    def get_pricing(cls, model: str) -> Dict[str, float]:
        """
        获取模型定价信息

        Args:
            model: 模型名称

        Returns:
            Dict: {"input": float, "output": float}
        """
        return cls.MODEL_PRICING.get(model, {"input": 0.001, "output": 0.002})

    @classmethod
    def estimate_tokens_from_text(cls, text: str, chars_per_token: float = 4.0) -> int:
        """
        粗略估算文本的token数量

        Args:
            text: 输入文本
            chars_per_token: 每个token的平均字符数（英文约4，中文约1.5-2）

        Returns:
            int: 估算的token数量
        """
        if not text or not text.strip():
            return 0
        return max(1, int(len(text) / chars_per_token))


class BudgetChecker:
    """
    预算检查服务

    纯业务逻辑，用于检查预算限制。
    """

    @staticmethod
    def check_budget_limit(
        current_spend: float,
        budget_limit: float | None
    ) -> Tuple[bool, str]:
        """
        检查预算限制

        Args:
            current_spend: 当前已消费金额
            budget_limit: 预算限制（None表示无限制）

        Returns:
            Tuple[bool, str]: (是否允许, 消息)
        """
        if budget_limit is None:
            return True, "无预算限制"

        if current_spend >= budget_limit:
            return False, f"预算超限: ${current_spend:.4f} >= ${budget_limit:.2f}"

        remaining = budget_limit - current_spend
        return True, f"预算正常: 剩余 ${remaining:.4f} / ${budget_limit:.2f}"
