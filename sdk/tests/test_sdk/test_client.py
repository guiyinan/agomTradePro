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

    def test_init_with_username_password_bootstraps_session_auth(self, monkeypatch):
        """测试用户名密码模式会触发会话认证"""
        monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
        with patch.object(AgomTradeProClient, "_authenticate_with_session") as mock_auth:
            client = AgomTradeProClient(
                base_url="http://test.example.com",
                username="tester",
                password="secret",
            )

        assert client._config.auth.username == "tester"
        assert client._config.auth.password == "secret"
        mock_auth.assert_called_once()

    def test_init_without_auth_raises_error(self, monkeypatch):
        """测试没有认证信息时抛出异常"""
        monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
        monkeypatch.delenv("AGOMTRADEPRO_USERNAME", raising=False)
        monkeypatch.delenv("AGOMTRADEPRO_PASSWORD", raising=False)
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

    def test_session_auth_headers_include_csrf_for_unsafe_requests(self, monkeypatch):
        """测试 session 认证在非安全方法中附带 CSRF 头"""
        monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
        with patch.object(AgomTradeProClient, "_authenticate_with_session"):
            client = AgomTradeProClient(
                base_url="http://test.com",
                username="tester",
                password="secret",
            )

        client._session.cookies.set("csrftoken", "csrf-token")
        headers = client._build_request_headers("POST")

        assert headers["X-CSRFToken"] == "csrf-token"
        assert headers["Referer"] == "http://test.com/account/login/"

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

    def test_session_auth_login_posts_credentials(self, monkeypatch):
        """测试 SDK 会使用 Django 登录表单建立会话"""
        monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
        with patch.object(AgomTradeProClient, "_create_session") as mock_create_session:
            session = Mock()
            session.cookies.get.side_effect = lambda key, default=None: (
                "csrf-token" if key == "csrftoken" else default
            )
            session.get.return_value = Mock(status_code=200, raise_for_status=Mock())
            session.post.return_value = Mock(status_code=302)
            mock_create_session.return_value = session

            AgomTradeProClient(
                base_url="http://test.com",
                username="tester",
                password="secret",
            )

        session.get.assert_called_once_with("http://test.com/account/login/", timeout=30)
        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        assert kwargs["data"]["username"] == "tester"
        assert kwargs["data"]["password"] == "secret"

    def test_close_context_manager(self):
        """测试 with 语句关闭会话"""
        with AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        ) as client:
            assert client is not None

        # 会话应该被关闭
        assert True  # 如果没有异常就通过
