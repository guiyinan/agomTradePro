"""
Share Domain Services Tests

Tests for Domain layer services (pure Python, no external dependencies).
"""
import pytest
import string

from apps.share.domain.services import (
    generate_short_code,
    validate_short_code,
)


class TestGenerateShortCode:
    """Test short code generation service."""

    def test_default_length(self):
        """Test default short code length is 10."""
        code = generate_short_code()
        assert len(code) == 10

    def test_custom_length(self):
        """Test custom short code length."""
        code = generate_short_code(length=16)
        assert len(code) == 16

    def test_contains_only_alphanumeric(self):
        """Test short code contains only letters and digits."""
        code = generate_short_code()
        valid_chars = set(string.ascii_letters + string.digits)
        assert all(c in valid_chars for c in code)

    def test_uniqueness_high_probability(self):
        """Test that generated codes are likely unique."""
        codes = [generate_short_code() for _ in range(100)]
        assert len(set(codes)) == 100  # All unique

    def test_different_each_time(self):
        """Test that consecutive calls produce different codes."""
        code1 = generate_short_code()
        code2 = generate_short_code()
        assert code1 != code2


class TestValidateShortCode:
    """Test short code validation service."""

    def test_valid_code_default_params(self):
        """Test validation with valid code using default parameters."""
        assert validate_short_code("ABC123") is True

    def test_valid_code_custom_length(self):
        """Test validation with valid custom length code."""
        assert validate_short_code("ABC1234567", min_length=6, max_length=16) is True

    def test_valid_code_max_length(self):
        """Test validation with code at max length."""
        assert validate_short_code("A" * 32, min_length=6, max_length=32) is True

    def test_invalid_too_short(self):
        """Test validation fails for code shorter than min_length."""
        assert validate_short_code("ABC12", min_length=6) is False

    def test_invalid_too_long(self):
        """Test validation fails for code longer than max_length."""
        assert validate_short_code("A" * 33, max_length=32) is False

    def test_invalid_none(self):
        """Test validation fails for None."""
        assert validate_short_code(None) is False

    def test_invalid_empty_string(self):
        """Test validation fails for empty string."""
        assert validate_short_code("") is False

    def test_invalid_non_string(self):
        """Test validation fails for non-string input."""
        assert validate_short_code(12345) is False

    def test_invalid_special_characters(self):
        """Test validation fails for codes with special characters."""
        assert validate_short_code("ABC-123") is False
        assert validate_short_code("ABC_123") is False
        assert validate_short_code("ABC.123") is False
        assert validate_short_code("ABC/123") is False

    def test_invalid_spaces(self):
        """Test validation fails for codes with spaces."""
        assert validate_short_code("ABC 123") is False
        assert validate_short_code(" ABC123") is False
        assert validate_short_code("ABC123 ") is False

    def test_valid_uppercase_letters(self):
        """Test validation accepts uppercase letters."""
        assert validate_short_code("ABCDEFGHIJKLMNOPQRSTUVWXYZ") is True

    def test_valid_lowercase_letters(self):
        """Test validation accepts lowercase letters."""
        assert validate_short_code("abcdefghijklmnopqrstuvwxyz") is True

    def test_valid_mixed_case(self):
        """Test validation accepts mixed case."""
        assert validate_short_code("AbCdEf123") is True

    def test_valid_only_digits(self):
        """Test validation accepts digits only."""
        assert validate_short_code("123456") is True

    def test_valid_only_letters(self):
        """Test validation accepts letters only."""
        assert validate_short_code("ABCDEF") is True
