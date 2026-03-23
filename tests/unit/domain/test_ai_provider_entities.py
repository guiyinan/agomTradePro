"""
Unit tests for AI Provider Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

from datetime import datetime

import pytest

from apps.ai_provider.domain.entities import (
    AIChatRequest,
    AIChatResponse,
    AIProviderConfig,
    AIProviderType,
    AIUsageRecord,
)


class TestAIProviderType:
    """Tests for AIProviderType enum"""

    def test_provider_type_values(self):
        """Test AI provider type enum values"""
        assert AIProviderType.OPENAI.value == "openai"
        assert AIProviderType.DEEPSEEK.value == "deepseek"
        assert AIProviderType.QWEN.value == "qwen"
        assert AIProviderType.MOONSHOT.value == "moonshot"
        assert AIProviderType.CUSTOM.value == "custom"


class TestAIProviderConfig:
    """Tests for AIProviderConfig entity"""

    def test_create_valid_config(self):
        """Test creating a valid AI provider config"""
        config = AIProviderConfig(
            name="test_provider",
            provider_type=AIProviderType.OPENAI,
            base_url="https://api.openai.com/v1",
            api_key="test_key",
            default_model="gpt-4",
            is_active=True,
            priority=1,
        )
        assert config.name == "test_provider"
        assert config.provider_type == AIProviderType.OPENAI
        assert config.api_key == "test_key"

    def test_default_values(self):
        """Test default values for optional fields"""
        config = AIProviderConfig(
            name="test",
            provider_type=AIProviderType.OPENAI,
            base_url="https://test.com",
            api_key="key",
            default_model="gpt-4",
            is_active=True,
            priority=1,
        )
        assert config.daily_budget_limit is None
        assert config.monthly_budget_limit is None
        assert config.description == ""
        assert config.extra_config == {}

    def test_extra_defaults_to_empty_dict(self):
        """Test extra_config defaults to empty dict when None"""
        config = AIProviderConfig(
            name="test",
            provider_type=AIProviderType.OPENAI,
            base_url="https://test.com",
            api_key="key",
            default_model="gpt-4",
            is_active=True,
            priority=1,
            extra_config=None,
        )
        assert config.extra_config == {}

    def test_extra_config_can_be_set(self):
        """Test extra_config can be set"""
        extra = {"temperature": 0.7, "max_tokens": 2000}
        config = AIProviderConfig(
            name="test",
            provider_type=AIProviderType.OPENAI,
            base_url="https://test.com",
            api_key="key",
            default_model="gpt-4",
            is_active=True,
            priority=1,
            extra_config=extra,
        )
        assert config.extra_config == extra


class TestAIUsageRecord:
    """Tests for AIUsageRecord entity"""

    def test_create_valid_record(self):
        """Test creating a valid AI usage record"""
        record = AIUsageRecord(
            provider_name="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost=0.003,
            response_time_ms=1500,
            status="success",
        )
        assert record.provider_name == "openai"
        assert record.total_tokens == 150

    def test_default_values(self):
        """Test default values for optional fields"""
        record = AIUsageRecord(
            provider_name="test",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost=0.001,
            response_time_ms=1000,
            status="success",
        )
        assert record.error_message is None
        assert record.created_at is None

    def test_with_error_message(self):
        """Test record with error message"""
        record = AIUsageRecord(
            provider_name="test",
            model="test-model",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
            response_time_ms=500,
            status="error",
            error_message="Rate limit exceeded",
        )
        assert record.error_message == "Rate limit exceeded"
        assert record.status == "error"

    def test_with_created_at(self):
        """Test record with created_at timestamp"""
        now = datetime(2024, 1, 1, 12, 0, 0)
        record = AIUsageRecord(
            provider_name="test",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost=0.001,
            response_time_ms=1000,
            status="success",
            created_at=now,
        )
        assert record.created_at == now


class TestAIChatRequest:
    """Tests for AIChatRequest entity"""

    def test_create_valid_request(self):
        """Test creating a valid AI chat request"""
        request = AIChatRequest(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello!"},
            ],
            model="gpt-4",
            temperature=0.7,
            max_tokens=1000,
        )
        assert len(request.messages) == 2
        assert request.model == "gpt-4"

    def test_default_values(self):
        """Test default values for optional fields"""
        request = AIChatRequest(
            messages=[{"role": "user", "content": "Test"}],
        )
        assert request.model is None
        assert request.temperature == 0.7
        assert request.max_tokens is None

    def test_with_custom_temperature(self):
        """Test request with custom temperature"""
        request = AIChatRequest(
            messages=[{"role": "user", "content": "Test"}],
            temperature=0.5,
        )
        assert request.temperature == 0.5

    def test_with_max_tokens(self):
        """Test request with max_tokens"""
        request = AIChatRequest(
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=2000,
        )
        assert request.max_tokens == 2000

    def test_messages_can_be_empty(self):
        """Test messages can be empty list"""
        request = AIChatRequest(messages=[])
        assert request.messages == []


class TestAIChatResponse:
    """Tests for AIChatResponse entity"""

    def test_create_valid_response(self):
        """Test creating a valid AI chat response"""
        response = AIChatResponse(
            content="Hello! How can I help you today?",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            finish_reason="stop",
            response_time_ms=500,
            status="success",
        )
        assert response.content == "Hello! How can I help you today?"
        assert response.total_tokens == 30
        assert response.status == "success"

    def test_default_values(self):
        """Test default values for optional fields"""
        response = AIChatResponse(
            content="Test response",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            finish_reason="stop",
            response_time_ms=500,
            status="success",
        )
        assert response.error_message is None
        assert response.estimated_cost is None

    def test_with_error(self):
        """Test response with error"""
        response = AIChatResponse(
            content="",
            model="gpt-4",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason="error",
            response_time_ms=100,
            status="error",
            error_message="API rate limit exceeded",
        )
        assert response.status == "error"
        assert response.error_message == "API rate limit exceeded"

    def test_with_estimated_cost(self):
        """Test response with estimated cost"""
        response = AIChatResponse(
            content="Test",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            finish_reason="stop",
            response_time_ms=500,
            status="success",
            estimated_cost=0.005,
        )
        assert response.estimated_cost == 0.005

    def test_different_finish_reasons(self):
        """Test different finish reasons"""
        reasons = ["stop", "length", "content_filter", "error"]
        for reason in reasons:
            response = AIChatResponse(
                content="Test",
                model="test",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                finish_reason=reason,
                response_time_ms=500,
                status="success",
            )
            assert response.finish_reason == reason
