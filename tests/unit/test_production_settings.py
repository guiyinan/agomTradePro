"""
Unit tests for production settings SECRET_KEY validation.

Tests for:
- SECRET_KEY is required in production
- Insecure patterns are rejected
- Minimum length requirement
- Secure keys are accepted
"""

import os
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured


class TestSecretKeyValidation:
    """Tests for production SECRET_KEY validation."""

    def test_validate_secret_key_missing(self):
        """Test that missing SECRET_KEY raises ImproperlyConfigured."""
        # Save original value
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            # Remove SECRET_KEY
            os.environ['SECRET_KEY'] = ''

            # Import the validation function directly
            # We need to import it fresh each time
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            # The import itself should fail
            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            error_msg = str(exc_info.value)
            assert "SECRET_KEY environment variable is required" in error_msg
            assert "secrets.token_urlsafe(50)" in error_msg
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_validate_secret_key_empty(self):
        """Test that empty SECRET_KEY raises ImproperlyConfigured."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = ''

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "SECRET_KEY environment variable is required" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_django_insecure_pattern_rejected(self):
        """Test that 'django-insecure' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'django-insecure-abc123'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'django-insecure'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_change_this_pattern_rejected(self):
        """Test that 'change-this' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'some-key-with-change-this-inside'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'change-this'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_dev_only_pattern_rejected(self):
        """Test that 'dev-only' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'dev-only-secret-key-12345'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'dev-only'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_example_pattern_rejected(self):
        """Test that 'example' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'example-secret-key-for-testing'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'example'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_short_key_rejected(self):
        """Test that keys shorter than 50 characters are rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'short-key'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "too short" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_secure_key_accepted(self):
        """Test that a secure key is accepted."""
        import secrets
        secure_key = secrets.token_urlsafe(50)
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = secure_key

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            # Import the function
            from core.settings.production import _validate_secret_key
            result = _validate_secret_key()

            assert result == secure_key
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_pattern_case_insensitive(self):
        """Test that pattern matching is case-insensitive."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'DJANGO-INSECURE-ABC-DEF'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            # Should still catch the pattern despite uppercase
            assert "insecure pattern 'django-insecure'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_placeholder_pattern_rejected(self):
        """Test that 'placeholder' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'placeholder-secret-key-12345678901234567890'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'placeholder'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_xxx_pattern_rejected(self):
        """Test that 'xxx' pattern is rejected."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            os.environ['SECRET_KEY'] = 'xxx-secret-key-123456789012345678901234567890'

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            with pytest.raises(ImproperlyConfigured) as exc_info:
                from core.settings.production import _validate_secret_key
                _validate_secret_key()

            assert "insecure pattern 'xxx'" in str(exc_info.value)
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

    def test_exactly_50_characters_accepted(self):
        """Test that exactly 50 character key is accepted."""
        original_key = os.environ.get('SECRET_KEY', '')

        try:
            # Exactly 50 characters
            os.environ['SECRET_KEY'] = 'a' * 50

            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']

            from core.settings.production import _validate_secret_key
            result = _validate_secret_key()

            assert result == 'a' * 50
        finally:
            os.environ['SECRET_KEY'] = original_key
            if 'core.settings.production' in sys.modules:
                del sys.modules['core.settings.production']
