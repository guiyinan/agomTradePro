"""
Unit tests for AI Provider Domain Services.

Pure Domain layer tests using only Python standard library.
"""

import pytest

from apps.ai_provider.domain.services import (
    AICostCalculator,
    BudgetChecker,
)


class TestAICostCalculator:
    """Tests for AICostCalculator"""

    def test_calculate_cost_gpt4(self):
        """Test cost calculation for GPT-4"""
        cost = AICostCalculator.calculate_cost(
            model="gpt-4",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # gpt-4: input $0.03/1K, output $0.06/1K
        # (1000/1000) * 0.03 + (500/1000) * 0.06 = 0.03 + 0.03 = 0.06
        assert cost == pytest.approx(0.06, rel=0.01)

    def test_calculate_cost_gpt35_turbo(self):
        """Test cost calculation for GPT-3.5-turbo"""
        cost = AICostCalculator.calculate_cost(
            model="gpt-3.5-turbo",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        # gpt-3.5-turbo: input $0.0005/1K, output $0.0015/1K
        # (1000/1000) * 0.0005 + (1000/1000) * 0.0015 = 0.002
        assert cost == pytest.approx(0.002, rel=0.01)

    def test_calculate_cost_deepseek(self):
        """Test cost calculation for DeepSeek"""
        cost = AICostCalculator.calculate_cost(
            model="deepseek-chat",
            prompt_tokens=2000,
            completion_tokens=1000,
        )
        # deepseek-chat: input $0.0001/1K, output $0.0002/1K
        # (2000/1000) * 0.0001 + (1000/1000) * 0.0002 = 0.0002 + 0.0002 = 0.0004
        assert cost == pytest.approx(0.0004, rel=0.01)

    def test_calculate_cost_qwen(self):
        """Test cost calculation for Qwen"""
        cost = AICostCalculator.calculate_cost(
            model="qwen-plus",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # qwen-plus: input $0.0008/1K, output $0.002/1K
        # (1000/1000) * 0.0008 + (500/1000) * 0.002 = 0.0008 + 0.001 = 0.0018
        assert cost == pytest.approx(0.0018, rel=0.01)

    def test_calculate_cost_moonshot(self):
        """Test cost calculation for Moonshot"""
        cost = AICostCalculator.calculate_cost(
            model="moonshot-v1-8k",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        # moonshot-v1-8k: input $0.012/1K, output $0.012/1K
        # (1000/1000) * 0.012 + (1000/1000) * 0.012 = 0.024
        assert cost == pytest.approx(0.024, rel=0.01)

    def test_calculate_cost_unknown_model(self):
        """Test cost calculation for unknown model uses default pricing"""
        cost = AICostCalculator.calculate_cost(
            model="unknown-model",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # Default: input $0.001/1K, output $0.002/1K
        # (1000/1000) * 0.001 + (500/1000) * 0.002 = 0.001 + 0.001 = 0.002
        assert cost == pytest.approx(0.002, rel=0.01)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens"""
        cost = AICostCalculator.calculate_cost(
            model="gpt-4",
            prompt_tokens=0,
            completion_tokens=0,
        )
        assert cost == 0.0

    def test_calculate_cost_large_tokens(self):
        """Test cost calculation with large token counts"""
        cost = AICostCalculator.calculate_cost(
            model="gpt-3.5-turbo",
            prompt_tokens=100000,
            completion_tokens=50000,
        )
        # (100000/1000) * 0.0005 + (50000/1000) * 0.0015 = 0.05 + 0.075 = 0.125
        assert cost == pytest.approx(0.125, rel=0.01)

    def test_get_pricing_known_model(self):
        """Test getting pricing for known model"""
        pricing = AICostCalculator.get_pricing("gpt-4")
        assert pricing["input"] == 0.03
        assert pricing["output"] == 0.06

    def test_get_pricing_unknown_model(self):
        """Test getting pricing for unknown model returns default"""
        pricing = AICostCalculator.get_pricing("unknown-model")
        assert pricing["input"] == 0.001
        assert pricing["output"] == 0.002

    def test_get_pricing_all_models(self):
        """Test pricing is available for all defined models"""
        models = [
            "gpt-4",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "deepseek-chat",
            "deepseek-coder",
            "qwen-turbo",
            "qwen-plus",
            "qwen-max",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
        ]
        for model in models:
            pricing = AICostCalculator.get_pricing(model)
            assert "input" in pricing
            assert "output" in pricing
            assert pricing["input"] >= 0
            assert pricing["output"] >= 0

    def test_estimate_tokens_from_text_english(self):
        """Test token estimation for English text"""
        text = "Hello, how are you today? I am doing well, thank you for asking."
        # About 60 characters, roughly 15 tokens at 4 chars/token
        tokens = AICostCalculator.estimate_tokens_from_text(text, chars_per_token=4.0)
        assert 10 <= tokens <= 20

    def test_estimate_tokens_from_text_chinese(self):
        """Test token estimation for Chinese text"""
        text = "你好，今天天气怎么样？我很好，谢谢你的关心。"
        # About 30 characters, roughly 15-20 tokens at 1.5-2 chars/token
        tokens = AICostCalculator.estimate_tokens_from_text(text, chars_per_token=2.0)
        assert 10 <= tokens <= 20

    def test_estimate_tokens_from_text_empty(self):
        """Test token estimation for empty text"""
        tokens = AICostCalculator.estimate_tokens_from_text("")
        assert tokens == 0

    def test_estimate_tokens_from_text_whitespace(self):
        """Test token estimation for whitespace only"""
        tokens = AICostCalculator.estimate_tokens_from_text("   \n\t  ")
        assert tokens == 0

    def test_estimate_tokens_from_text_default_chars_per_token(self):
        """Test token estimation with default chars_per_token"""
        text = "a" * 100
        tokens = AICostCalculator.estimate_tokens_from_text(text)
        # Default is 4.0 chars/token, so 100/4 = 25
        assert tokens == 25

    def test_estimate_tokens_from_text_custom_chars_per_token(self):
        """Test token estimation with custom chars_per_token"""
        text = "a" * 100
        tokens = AICostCalculator.estimate_tokens_from_text(text, chars_per_token=2.0)
        assert tokens == 50

    def test_model_pricing_completeness(self):
        """Test that all models in MODEL_PRICING have valid pricing"""
        for model, pricing in AICostCalculator.MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing
            assert pricing["input"] >= 0
            assert pricing["output"] >= 0
            # Output pricing is typically higher or equal to input
            assert pricing["output"] >= pricing["input"] * 0.5  # Allow some variation

    def test_cost_rounding(self):
        """Test that costs are properly rounded"""
        cost = AICostCalculator.calculate_cost(
            model="gpt-3.5-turbo",
            prompt_tokens=1234,
            completion_tokens=567,
        )
        # Should be rounded to 6 decimal places
        cost_str = f"{cost:.6f}"
        assert len(cost_str.split(".")[-1]) <= 6


class TestBudgetChecker:
    """Tests for BudgetChecker"""

    def test_check_budget_no_limit(self):
        """Test budget check with no limit (None)"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=100.0,
            budget_limit=None,
        )
        assert allowed is True
        assert "无预算限制" in message

    def test_check_budget_within_limit(self):
        """Test budget check when within limit"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=50.0,
            budget_limit=100.0,
        )
        assert allowed is True
        assert "预算正常" in message
        assert "剩余" in message

    def test_check_budget_at_limit(self):
        """Test budget check when exactly at limit"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=100.0,
            budget_limit=100.0,
        )
        assert allowed is False
        assert "预算超限" in message

    def test_check_budget_over_limit(self):
        """Test budget check when over limit"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=150.0,
            budget_limit=100.0,
        )
        assert allowed is False
        assert "预算超限" in message

    def test_check_budget_zero_spend(self):
        """Test budget check with zero spend"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=0.0,
            budget_limit=100.0,
        )
        assert allowed is True
        assert "100.0000" in message  # Full budget remaining

    def test_check_budget_remaining_calculation(self):
        """Test remaining budget calculation"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=37.5,
            budget_limit=100.0,
        )
        assert allowed is True
        assert "62.5000" in message  # Remaining amount

    def test_check_budget_very_small_remaining(self):
        """Test budget check with very small remaining amount"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=99.999,
            budget_limit=100.0,
        )
        assert allowed is True
        assert "0.001" in message

    def test_check_budget_large_values(self):
        """Test budget check with large values"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=5000.0,
            budget_limit=10000.0,
        )
        assert allowed is True
        assert "5000.0000" in message

    def test_check_budget_negative_spend(self):
        """Test budget check with negative spend (edge case)"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=-10.0,
            budget_limit=100.0,
        )
        assert allowed is True
        # Should handle gracefully

    def test_check_budget_message_format(self):
        """Test budget check message format"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=75.5,
            budget_limit=100.0,
        )
        assert "24.5000" in message
        assert "100.00" in message

    def test_check_budget_exceeded_message_format(self):
        """Test budget exceeded message format"""
        allowed, message = BudgetChecker.check_budget_limit(
            current_spend=125.75,
            budget_limit=100.0,
        )
        assert "125.7500" in message
        assert "100.00" in message
        assert ">=" in message or "超过" in message
