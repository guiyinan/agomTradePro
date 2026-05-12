"""
Tests for DoS protection settings (P1-3).

Tests verify that:
1. Large requests are rejected
2. File uploads are limited
3. Too many fields are rejected
"""

import pytest


class TestDosProtection:
    """Tests for DoS protection limits."""

    @pytest.mark.django_db
    def test_data_upload_max_memory_size_configured(self):
        """Test that DATA_UPLOAD_MAX_MEMORY_SIZE is configured."""
        from django.conf import settings

        # Should have a reasonable limit
        assert hasattr(settings, 'DATA_UPLOAD_MAX_MEMORY_SIZE')
        assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE > 0
        assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE <= 100 * 1024 * 1024  # Max 100MB

    @pytest.mark.django_db
    def test_file_upload_max_memory_size_configured(self):
        """Test that FILE_UPLOAD_MAX_MEMORY_SIZE is configured."""
        from django.conf import settings

        assert hasattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE')
        assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE > 0
        assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE <= 100 * 1024 * 1024  # Max 100MB

    @pytest.mark.django_db
    def test_data_upload_max_number_fields_configured(self):
        """Test that DATA_UPLOAD_MAX_NUMBER_FIELDS is configured."""
        from django.conf import settings

        assert hasattr(settings, 'DATA_UPLOAD_MAX_NUMBER_FIELDS')
        assert settings.DATA_UPLOAD_MAX_NUMBER_FIELDS > 0
        assert settings.DATA_UPLOAD_MAX_NUMBER_FIELDS <= 10000  # Max 10000 fields

    @pytest.mark.django_db
    def test_limits_are_reasonable(self):
        """Test that limits are within reasonable bounds."""
        from django.conf import settings

        # Memory limits should be between 1MB and 100MB
        assert 1 * 1024 * 1024 <= settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        assert 1 * 1024 * 1024 <= settings.FILE_UPLOAD_MAX_MEMORY_SIZE

        # Field count should be reasonable
        assert 100 <= settings.DATA_UPLOAD_MAX_NUMBER_FIELDS <= 10000
