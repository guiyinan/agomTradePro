"""
Unit tests for core/exceptions.py

Tests for:
- AgomSAAFException base class
- Exception subclasses
- custom_exception_handler for DRF
"""

import pytest
from unittest.mock import MagicMock, patch
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404

from core.exceptions import (
    AgomSAAFException,
    ValidationError,
    InvalidInputError,
    MissingRequiredFieldError,
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
    DuplicateResourceError,
    BusinessLogicError,
    RegimeNotDeterminedError,
    SignalValidationError,
    IneligibleAssetError,
    ExternalServiceError,
    DataFetchError,
    AIServiceError,
    TushareError,
    AKShareError,
    TimeoutError,
    ConfigurationError,
    MissingConfigError,
    InsufficientDataError,
    DataValidationError,
    custom_exception_handler,
)


class TestAgomSAAFException:
    """Tests for the base AgomSAAFException class."""

    def test_default_values(self):
        """Test that default values are applied correctly."""
        exc = AgomSAAFException()
        assert exc.message == "An error occurred"
        assert exc.code == "INTERNAL_ERROR"
        assert exc.status_code == 500
        assert exc.details == {}

    def test_custom_values(self):
        """Test that custom values override defaults."""
        exc = AgomSAAFException(
            message="Custom error",
            code="CUSTOM_ERROR",
            status_code=400,
            details={"field": "value"}
        )
        assert exc.message == "Custom error"
        assert exc.code == "CUSTOM_ERROR"
        assert exc.status_code == 400
        assert exc.details == {"field": "value"}

    def test_to_dict_without_details(self):
        """Test to_dict without details."""
        exc = AgomSAAFException(message="Error", code="ERR")
        result = exc.to_dict()
        assert result == {"error": "Error", "code": "ERR"}

    def test_to_dict_with_details(self):
        """Test to_dict with details."""
        exc = AgomSAAFException(
            message="Error",
            code="ERR",
            details={"key": "value"}
        )
        result = exc.to_dict()
        assert result == {
            "error": "Error",
            "code": "ERR",
            "details": {"key": "value"}
        }


class TestExceptionSubclasses:
    """Tests for exception subclasses."""

    def test_validation_error(self):
        """Test ValidationError has correct defaults."""
        exc = ValidationError()
        assert exc.status_code == 400
        assert exc.code == "VALIDATION_ERROR"

    def test_invalid_input_error(self):
        """Test InvalidInputError inherits from ValidationError."""
        exc = InvalidInputError(message="Bad input")
        assert exc.status_code == 400
        assert exc.code == "INVALID_INPUT"

    def test_missing_required_field_error(self):
        """Test MissingRequiredFieldError."""
        exc = MissingRequiredFieldError(message="Field 'name' is required")
        assert exc.status_code == 400

    def test_authentication_error(self):
        """Test AuthenticationError has 401 status."""
        exc = AuthenticationError()
        assert exc.status_code == 401
        assert exc.code == "AUTHENTICATION_ERROR"

    def test_authorization_error(self):
        """Test AuthorizationError has 403 status."""
        exc = AuthorizationError()
        assert exc.status_code == 403
        assert exc.code == "AUTHORIZATION_ERROR"

    def test_resource_not_found_error(self):
        """Test ResourceNotFoundError has 404 status."""
        exc = ResourceNotFoundError()
        assert exc.status_code == 404
        assert exc.code == "NOT_FOUND"

    def test_duplicate_resource_error(self):
        """Test DuplicateResourceError has 409 status."""
        exc = DuplicateResourceError()
        assert exc.status_code == 409

    def test_business_logic_error(self):
        """Test BusinessLogicError has 422 status."""
        exc = BusinessLogicError()
        assert exc.status_code == 422

    def test_external_service_error(self):
        """Test ExternalServiceError has 503 status."""
        exc = ExternalServiceError()
        assert exc.status_code == 503

    def test_timeout_error(self):
        """Test TimeoutError has 504 status."""
        exc = TimeoutError()
        assert exc.status_code == 504


class TestCustomExceptionHandler:
    """Tests for the DRF custom_exception_handler."""

    def create_context(self):
        """Create a mock context for exception handler."""
        view = MagicMock()
        view.__class__.__name__ = "TestView"
        request = MagicMock()
        request.user = MagicMock()
        request.user.id = 1
        return {"view": view, "request": request}

    def test_handles_agomsaaf_exception(self):
        """Test that AgomSAAFException is handled correctly."""
        exc = ValidationError(
            message="Invalid data",
            code="VALIDATION_ERROR",
            details={"field": "name"}
        )
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        assert response is not None
        assert response.status_code == 400
        assert response.data["error"] == "Invalid data"
        assert response.data["code"] == "VALIDATION_ERROR"
        assert response.data["details"]["field"] == "name"

    def test_handles_business_logic_error(self):
        """Test that BusinessLogicError is handled correctly."""
        exc = RegimeNotDeterminedError(message="Cannot determine regime")
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        assert response is not None
        assert response.status_code == 422
        assert response.data["error"] == "Cannot determine regime"

    def test_handles_drf_validation_error(self):
        """Test that DRF ValidationError is handled correctly."""
        from rest_framework.exceptions import ValidationError as DRFValidationError

        exc = DRFValidationError({"name": ["This field is required."]})
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        assert response is not None
        assert response.status_code == 400
        assert response.data["code"] == "VALIDATION_ERROR"
        assert "details" in response.data

    def test_handles_drf_detail_error(self):
        """Test that DRF errors with detail are handled correctly."""
        from rest_framework.exceptions import PermissionDenied

        exc = PermissionDenied("You do not have permission")
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        assert response is not None
        assert response.status_code == 403
        assert response.data["error"] == "You do not have permission"
        assert response.data["code"] == "API_ERROR"

    def test_handles_http404(self):
        """Test that Django Http404 is handled correctly."""
        exc = Http404("Page not found")
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        # DRF converts Http404 to its own response before our handler
        # Our handler wraps it in standard format
        assert response is not None
        assert response.status_code == 404
        # The error message is wrapped
        assert "error" in response.data

    def test_returns_none_for_unhandled_exception(self):
        """Test that unhandled exceptions return None."""
        exc = Exception("Random error")
        context = self.create_context()

        response = custom_exception_handler(exc, context)

        # Should return None for unhandled exceptions
        # (DRF will use default behavior)
        assert response is None


class TestExceptionInheritance:
    """Tests for exception inheritance chain."""

    def test_invalid_input_inherits_validation(self):
        """Test InvalidInputError inherits from ValidationError."""
        exc = InvalidInputError()
        assert isinstance(exc, ValidationError)
        assert isinstance(exc, AgomSAAFException)

    def test_regime_error_inherits_business(self):
        """Test RegimeNotDeterminedError inherits from BusinessLogicError."""
        exc = RegimeNotDeterminedError()
        assert isinstance(exc, BusinessLogicError)
        assert isinstance(exc, AgomSAAFException)

    def test_tushare_error_inherits_data_fetch(self):
        """Test TushareError inherits from DataFetchError."""
        exc = TushareError()
        assert isinstance(exc, DataFetchError)
        assert isinstance(exc, ExternalServiceError)
        assert isinstance(exc, AgomSAAFException)

    def test_missing_config_inherits_configuration(self):
        """Test MissingConfigError inherits from ConfigurationError."""
        exc = MissingConfigError()
        assert isinstance(exc, ConfigurationError)
        assert isinstance(exc, AgomSAAFException)
