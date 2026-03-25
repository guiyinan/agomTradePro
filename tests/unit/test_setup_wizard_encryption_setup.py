"""
Unit tests for setup wizard encryption key auto-generation.

验证安装向导自动生成安全密钥的逻辑。
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.setup_wizard.infrastructure.encryption_setup import (
    _is_insecure_secret_key,
    _write_key_to_env,
    ensure_all_keys,
    ensure_encryption_key,
    ensure_secret_key,
)


@pytest.fixture()
def work_dir():
    """Create a temporary directory that works reliably on Windows."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


class TestIsInsecureSecretKey:
    """Tests for _is_insecure_secret_key helper."""

    def test_django_insecure_default(self):
        assert _is_insecure_secret_key("django-insecure-change-this-in-production") is True

    def test_env_example_default(self):
        assert _is_insecure_secret_key("change-this-to-a-secure-random-string-in-production") is True

    def test_short_key(self):
        assert _is_insecure_secret_key("tooshort") is True

    def test_secure_key(self):
        secure = "x" * 50
        assert _is_insecure_secret_key(secure) is False

    def test_real_generated_key(self):
        from django.core.management.utils import get_random_secret_key

        key = get_random_secret_key()
        assert _is_insecure_secret_key(key) is False


class TestWriteKeyToEnv:
    """Tests for _write_key_to_env helper."""

    def test_creates_env_if_missing(self, work_dir):
        env_path = work_dir / ".env"
        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.BASE_DIR = work_dir
            _write_key_to_env("MY_KEY", "my_value")

        assert env_path.exists()
        assert "MY_KEY=my_value\n" == env_path.read_text(encoding="utf-8")

    def test_replaces_empty_value(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text("SECRET_KEY=abc\nAGOMTRADEPRO_ENCRYPTION_KEY=\nDEBUG=True\n")

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.BASE_DIR = work_dir
            _write_key_to_env("AGOMTRADEPRO_ENCRYPTION_KEY", "new_value")

        content = env_path.read_text(encoding="utf-8")
        assert "AGOMTRADEPRO_ENCRYPTION_KEY=new_value" in content
        assert "SECRET_KEY=abc" in content
        assert "DEBUG=True" in content

    def test_replaces_existing_value(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text("SECRET_KEY=old_value\n")

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.BASE_DIR = work_dir
            _write_key_to_env("SECRET_KEY", "new_secret")

        content = env_path.read_text(encoding="utf-8")
        assert "SECRET_KEY=new_secret" in content
        assert "old_value" not in content

    def test_appends_missing_key(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text("SECRET_KEY=abc\n")

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.BASE_DIR = work_dir
            _write_key_to_env("AGOMTRADEPRO_ENCRYPTION_KEY", "new_key")

        content = env_path.read_text(encoding="utf-8")
        assert "SECRET_KEY=abc" in content
        assert "AGOMTRADEPRO_ENCRYPTION_KEY=new_key" in content


class TestEnsureEncryptionKey:
    """Tests for ensure_encryption_key."""

    @override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="already-set")
    def test_skips_when_already_configured(self):
        assert ensure_encryption_key() is False

    @override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="")
    def test_generates_when_empty(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text("AGOMTRADEPRO_ENCRYPTION_KEY=\n")

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.AGOMTRADEPRO_ENCRYPTION_KEY = ""
            mock_settings.BASE_DIR = work_dir
            with patch.dict(os.environ, {"AGOMTRADEPRO_ENCRYPTION_KEY": ""}, clear=False):
                result = ensure_encryption_key()

        assert result is True
        content = env_path.read_text(encoding="utf-8")
        written_key = content.strip().split("=", 1)[1]
        assert len(written_key) == 44


class TestEnsureSecretKey:
    """Tests for ensure_secret_key."""

    @override_settings(SECRET_KEY="x" * 50)
    def test_skips_when_secure(self):
        assert ensure_secret_key() is False

    def test_generates_when_insecure(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text("SECRET_KEY=django-insecure-change-this-in-production\n")

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.SECRET_KEY = "django-insecure-change-this-in-production"
            mock_settings.BASE_DIR = work_dir
            result = ensure_secret_key()

        assert result is True
        content = env_path.read_text(encoding="utf-8")
        written_key = content.strip().split("=", 1)[1]
        assert len(written_key) >= 50
        assert "django-insecure" not in written_key


class TestEnsureAllKeys:
    """Tests for ensure_all_keys."""

    def test_returns_both_flags(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text(
            "SECRET_KEY=django-insecure-test\nAGOMTRADEPRO_ENCRYPTION_KEY=\n"
        )

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.SECRET_KEY = "django-insecure-test"
            mock_settings.AGOMTRADEPRO_ENCRYPTION_KEY = ""
            mock_settings.BASE_DIR = work_dir
            with patch.dict(os.environ, {"AGOMTRADEPRO_ENCRYPTION_KEY": ""}, clear=False):
                result = ensure_all_keys()

        assert result["secret_key_generated"] is True
        assert result["encryption_key_generated"] is True

        content = env_path.read_text(encoding="utf-8")
        assert "SECRET_KEY=" in content
        assert "AGOMTRADEPRO_ENCRYPTION_KEY=" in content

    def test_can_skip_generation_for_existing_install(self, work_dir):
        env_path = work_dir / ".env"
        env_path.write_text(
            "SECRET_KEY=django-insecure-test\nAGOMTRADEPRO_ENCRYPTION_KEY=\n"
        )

        with patch("apps.setup_wizard.infrastructure.encryption_setup.settings") as mock_settings:
            mock_settings.SECRET_KEY = "django-insecure-test"
            mock_settings.AGOMTRADEPRO_ENCRYPTION_KEY = ""
            mock_settings.BASE_DIR = work_dir
            with patch.dict(
                os.environ,
                {"SECRET_KEY": "django-insecure-test", "AGOMTRADEPRO_ENCRYPTION_KEY": ""},
                clear=False,
            ):
                result = ensure_all_keys(
                    generate_secret_key=False,
                    generate_encryption_key=False,
                )

        assert result["secret_key_generated"] is False
        assert result["encryption_key_generated"] is False
        assert result["secret_key_configured"] is False
        assert result["encryption_key_configured"] is False
        assert env_path.read_text(encoding="utf-8") == (
            "SECRET_KEY=django-insecure-test\nAGOMTRADEPRO_ENCRYPTION_KEY=\n"
        )
