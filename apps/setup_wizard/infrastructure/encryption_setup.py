"""
Auto-generate security keys during setup wizard.

在安装向导期间自动生成安全密钥，解决用户首次安装后 API Key 无法保存的问题。

问题根源：
- AGOMTRADEPRO_ENCRYPTION_KEY 未设置 → FieldEncryptionService 拒绝写入
- SECRET_KEY 使用不安全默认值 → 生产环境隐患
"""

import logging
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.utils import get_random_secret_key

logger = logging.getLogger(__name__)

_INSECURE_PATTERNS = ("django-insecure", "change-this", "change_this")


def ensure_all_keys() -> dict[str, bool]:
    """
    确保 SECRET_KEY 和 AGOMTRADEPRO_ENCRYPTION_KEY 均已正确配置。

    Returns:
        Dict with 'secret_key_generated' and 'encryption_key_generated' flags
    """
    return {
        "secret_key_generated": ensure_secret_key(),
        "encryption_key_generated": ensure_encryption_key(),
    }


def ensure_secret_key() -> bool:
    """
    若当前 SECRET_KEY 为不安全占位值，自动生成安全密钥。

    Returns:
        True if a new key was generated
    """
    current = getattr(settings, "SECRET_KEY", "")
    if current and not _is_insecure_secret_key(current):
        return False

    new_key = get_random_secret_key()
    _write_key_to_env("SECRET_KEY", new_key)

    settings.SECRET_KEY = new_key
    os.environ["SECRET_KEY"] = new_key

    logger.info("Setup wizard: auto-generated new Django SECRET_KEY")
    return True


def ensure_encryption_key() -> bool:
    """
    若 AGOMTRADEPRO_ENCRYPTION_KEY 未配置，自动生成 Fernet 密钥。

    Returns:
        True if a new key was generated
    """
    current = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or os.environ.get(
        "AGOMTRADEPRO_ENCRYPTION_KEY", ""
    )
    if current:
        return False

    new_key = Fernet.generate_key().decode("ascii")
    _write_key_to_env("AGOMTRADEPRO_ENCRYPTION_KEY", new_key)

    settings.AGOMTRADEPRO_ENCRYPTION_KEY = new_key
    os.environ["AGOMTRADEPRO_ENCRYPTION_KEY"] = new_key

    logger.info("Setup wizard: auto-generated new AGOMTRADEPRO_ENCRYPTION_KEY")
    return True


def _is_insecure_secret_key(key: str) -> bool:
    """Check if a SECRET_KEY value is insecure (placeholder or too short)."""
    key_lower = key.lower()
    if any(pattern in key_lower for pattern in _INSECURE_PATTERNS):
        return True
    return len(key) < 50


def _write_key_to_env(key_name: str, key_value: str) -> None:
    """Write or update a key in the .env file.

    Also persists to /app/data/.env.generated when running inside Docker
    (detected by the presence of /app/data/ volume mount).
    """
    _upsert_env_file(Path(settings.BASE_DIR) / ".env", key_name, key_value)

    # Docker data-volume persistence — survives container restarts
    docker_persist = Path("/app/data/.env.generated")
    if docker_persist.parent.is_dir():
        _upsert_env_file(docker_persist, key_name, key_value)


def _upsert_env_file(env_path: Path, key_name: str, key_value: str) -> None:
    """Insert or update a KEY=VALUE line in an env file."""
    key_line = f"{key_name}={key_value}"

    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")

        pattern = rf"^{re.escape(key_name)}=.*$"
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, key_line, content, flags=re.MULTILINE)
        else:
            if not content.endswith("\n"):
                content += "\n"
            content += f"{key_line}\n"

        env_path.write_text(content, encoding="utf-8")
    else:
        env_path.write_text(f"{key_line}\n", encoding="utf-8")
