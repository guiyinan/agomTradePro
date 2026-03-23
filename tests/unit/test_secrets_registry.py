"""
Tests for shared.config.secrets module (Registry Pattern)

Tests the secrets loading with the new registry pattern that avoids
direct dependencies on apps/ modules.
"""

import os
from unittest.mock import Mock, patch

import pytest


class TestSecretsRegistry:
    """Test the secrets registry pattern."""

    def test_register_and_load_secrets(self):
        """Test registering a loader and loading secrets."""
        from shared.config.secrets import (
            AppSecrets,
            clear_secrets_cache,
            get_secrets,
            register_database_secrets_loader,
        )
        from shared.domain.interfaces import DataSourceSecretsDTO

        # Clear cache first
        clear_secrets_cache()

        # Create a mock loader
        def mock_loader():
            return DataSourceSecretsDTO(
                tushare_token="test_token_from_db",
                fred_api_key="test_fred_key",
                juhe_api_key=None,
            )

        # Register the loader
        register_database_secrets_loader(mock_loader)

        # Get secrets - should use the registered loader
        secrets = get_secrets()

        assert secrets.data_sources.tushare_token == "test_token_from_db"
        assert secrets.data_sources.fred_api_key == "test_fred_key"

        # Clean up
        clear_secrets_cache()

    def test_fallback_to_env(self):
        """Test fallback to environment variables when no loader registered."""
        import shared.config.secrets as secrets_module
        from shared.config.secrets import (
            _database_secrets_loader,
            clear_secrets_cache,
            get_secrets,
        )

        # Clear cache
        clear_secrets_cache()

        # Remove any registered loader
        secrets_module._database_secrets_loader = None

        # Set environment variable
        with patch.dict(os.environ, {'TUSHARE_TOKEN': 'env_token'}):
            secrets = get_secrets()
            assert secrets.data_sources.tushare_token == 'env_token'

        # Clean up
        clear_secrets_cache()

    def test_no_token_raises_error(self):
        """Test that missing token raises EnvironmentError."""
        import shared.config.secrets as secrets_module
        from shared.config.secrets import (
            clear_secrets_cache,
            get_secrets,
        )

        # Clear cache and loader
        clear_secrets_cache()
        secrets_module._database_secrets_loader = None

        # Remove all token sources
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError) as exc_info:
                get_secrets()

            assert "Tushare Token" in str(exc_info.value)

        # Clean up
        clear_secrets_cache()

    def test_clear_secrets_cache(self):
        """Test that clear_secrets_cache works."""
        from shared.config.secrets import clear_secrets_cache, get_secrets

        # This should not raise any errors
        clear_secrets_cache()

        # Verify cache is cleared by checking lru_cache
        assert get_secrets.cache_info().currsize == 0


class TestDataSourceSecretsDTO:
    """Test the DataSourceSecretsDTO dataclass."""

    def test_create_dto(self):
        """Test creating a DataSourceSecretsDTO."""
        from shared.domain.interfaces import DataSourceSecretsDTO

        dto = DataSourceSecretsDTO(
            tushare_token="token123",
            fred_api_key="fred456",
            juhe_api_key="juhe789",
        )

        assert dto.tushare_token == "token123"
        assert dto.fred_api_key == "fred456"
        assert dto.juhe_api_key == "juhe789"

    def test_dto_is_frozen(self):
        """Test that DataSourceSecretsDTO is immutable."""
        from shared.domain.interfaces import DataSourceSecretsDTO

        dto = DataSourceSecretsDTO(
            tushare_token="token123",
            fred_api_key="fred456",
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            dto.tushare_token = "new_token"

    def test_dto_optional_juhe(self):
        """Test that juhe_api_key is optional."""
        from shared.domain.interfaces import DataSourceSecretsDTO

        dto = DataSourceSecretsDTO(
            tushare_token="token123",
            fred_api_key="fred456",
            # juhe_api_key omitted
        )

        assert dto.juhe_api_key is None


class TestAppSecrets:
    """Test the AppSecrets dataclass."""

    def test_create_app_secrets(self):
        """Test creating AppSecrets."""
        from shared.config.secrets import AppSecrets, DataSourceSecrets

        ds = DataSourceSecrets(
            tushare_token="token",
            fred_api_key="fred",
        )

        app = AppSecrets(
            data_sources=ds,
            slack_webhook="https://hooks.slack.com/...",
            alert_email="alert@example.com",
        )

        assert app.data_sources.tushare_token == "token"
        assert app.slack_webhook == "https://hooks.slack.com/..."
        assert app.alert_email == "alert@example.com"

    def test_app_secrets_is_frozen(self):
        """Test that AppSecrets is immutable."""
        from shared.config.secrets import AppSecrets, DataSourceSecrets

        ds = DataSourceSecrets(
            tushare_token="token",
            fred_api_key="fred",
        )

        app = AppSecrets(data_sources=ds)

        with pytest.raises(Exception):  # FrozenInstanceError
            app.slack_webhook = "new_webhook"


class TestGetTushareToken:
    """Test the get_tushare_token convenience function."""

    def test_get_tushare_token(self):
        """Test get_tushare_token returns the token."""
        from shared.config.secrets import (
            clear_secrets_cache,
            get_tushare_token,
            register_database_secrets_loader,
        )
        from shared.domain.interfaces import DataSourceSecretsDTO

        clear_secrets_cache()

        def mock_loader():
            return DataSourceSecretsDTO(
                tushare_token="convenience_token",
                fred_api_key="",
            )

        register_database_secrets_loader(mock_loader)

        token = get_tushare_token()
        assert token == "convenience_token"

        clear_secrets_cache()
