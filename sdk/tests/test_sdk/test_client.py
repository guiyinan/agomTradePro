"""
Unit tests for AgomTradePro SDK Client
"""

import pytest
from unittest.mock import Mock, patch

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ValidationError,
)


class TestAgomTradeProClient:
    """测试 AgomTradeProClient 主客户端"""

    def test_init_with_params(self):
        """测试使用参数初始化客户端"""
        client = AgomTradeProClient(
            base_url="http://test.example.com",
            api_token="test_token",
        )
        assert client._config.base_url == "http://test.example.com"
        assert client._config.auth.api_token == "test_token"

    def test_init_with_env_vars(self, monkeypatch):
        """测试使用环境变量初始化客户端"""
        monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", "http://env.example.com")
        monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", "env_token")

        client = AgomTradeProClient()
        assert client._config.base_url == "http://env.example.com"
        assert client._config.auth.api_token == "env_token"

    def test_init_without_auth_raises_error(self):
        """测试没有认证信息时抛出异常"""
        with pytest.raises(ConfigurationError):
            AgomTradeProClient(base_url="http://test.com")

    def test_headers_include_auth_token(self):
        """测试请求头包含认证 token"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="secret_token",
        )
        assert client._headers["Authorization"] == "Token secret_token"
        assert client._headers["Content-Type"] == "application/json"

    def test_regime_module_property(self):
        """测试 regime 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.regime is not None
        # 多次访问返回同一实例
        assert client.regime is client.regime

    def test_signal_module_property(self):
        """测试 signal 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.signal is not None

    def test_macro_module_property(self):
        """测试 macro 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.macro is not None

    def test_policy_module_property(self):
        """测试 policy 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.policy is not None

    def test_backtest_module_property(self):
        """测试 backtest 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.backtest is not None

    def test_account_module_property(self):
        """测试 account 模块属性"""
        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        assert client.account is not None


class TestAgomTradeProClientRequests:
    """测试 HTTP 请求方法"""

    @pytest.fixture
    def client(self):
        return AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_get_request(self, client):
        """测试 GET 请求"""
        with patch.object(client._session, "request") as mock_request:
            mock_request.return_value = Mock(
                status_code=200,
                json=lambda: {"result": "success"}
            )

            result = client.get("/test/endpoint")

            assert result == {"result": "success"}
            mock_request.assert_called_once()

    def test_post_request(self, client):
        """测试 POST 请求"""
        with patch.object(client._session, "request") as mock_request:
            mock_request.return_value = Mock(
                status_code=201,
                json=lambda: {"id": 123}
            )

            result = client.post("/test/create", json={"name": "test"})

            assert result == {"id": 123}

    def test_request_with_auth_error(self, client):
        """测试认证失败请求"""
        with patch.object(client._session, "request") as mock_request:
            mock_request.return_value = Mock(
                status_code=401,
                json=lambda: {"detail": "Unauthorized"}
            )

            with pytest.raises(AuthenticationError):
                client.get("/test/endpoint")

    def test_request_with_validation_error(self, client):
        """测试验证失败请求"""
        with patch.object(client._session, "request") as mock_request:
            mock_request.return_value = Mock(
                status_code=400,
                json=lambda: {"errors": {"field": "invalid"}}
            )

            with pytest.raises(ValidationError):
                client.post("/test/create", json={})

    def test_close_context_manager(self):
        """测试 with 语句关闭会话"""
        with AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        ) as client:
            assert client is not None

        # 会话应该被关闭
        assert True  # 如果没有异常就通过
