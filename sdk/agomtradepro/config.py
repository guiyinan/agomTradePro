"""
AgomTradePro SDK 配置管理

支持多种配置方式（优先级从高到低）：
1. 构造函数参数
2. 环境变量
3. 配置文件
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .exceptions import ConfigurationError


@dataclass
class AuthConfig:
    """认证配置"""

    api_token: str | None = None
    username: str | None = None
    password: str | None = None


@dataclass
class ClientConfig:
    """
    客户端配置

    Attributes:
        base_url: API 基础 URL
        auth: 认证配置
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数
        verify_ssl: 是否验证 SSL 证书
    """

    base_url: str = "http://localhost:8000"
    auth: AuthConfig = field(default_factory=AuthConfig)
    timeout: int = 30
    max_retries: int = 3
    verify_ssl: bool = True

    def validate(self) -> None:
        """验证配置是否有效"""
        if not self.base_url:
            raise ConfigurationError("base_url is required")

        # 检查是否至少有一种认证方式
        if not self.auth.api_token and not (self.auth.username and self.auth.password):
            raise ConfigurationError(
                "Either api_token or username/password must be provided"
            )


def _load_env_config() -> dict:
    """
    从环境变量加载配置

    支持的环境变量：
    - AGOMTRADEPRO_BASE_URL
    - AGOMTRADEPRO_API_BASE_URL (legacy alias)
    - AGOMTRADEPRO_API_TOKEN
    - AGOMTRADEPRO_USERNAME
    - AGOMTRADEPRO_PASSWORD
    - AGOMTRADEPRO_TIMEOUT
    - AGOMTRADEPRO_MAX_RETRIES
    - AGOMTRADEPRO_VERIFY_SSL
    """
    config = {}

    if base_url := (os.getenv("AGOMTRADEPRO_BASE_URL") or os.getenv("AGOMTRADEPRO_API_BASE_URL")):
        config["base_url"] = base_url

    if api_token := os.getenv("AGOMTRADEPRO_API_TOKEN"):
        config["api_token"] = api_token

    if username := os.getenv("AGOMTRADEPRO_USERNAME"):
        config["username"] = username

    if password := os.getenv("AGOMTRADEPRO_PASSWORD"):
        config["password"] = password

    if timeout := os.getenv("AGOMTRADEPRO_TIMEOUT"):
        try:
            config["timeout"] = int(timeout)
        except ValueError:
            raise ConfigurationError(f"Invalid AGOMTRADEPRO_TIMEOUT: {timeout}") from None

    if max_retries := os.getenv("AGOMTRADEPRO_MAX_RETRIES"):
        try:
            config["max_retries"] = int(max_retries)
        except ValueError:
            raise ConfigurationError(f"Invalid AGOMTRADEPRO_MAX_RETRIES: {max_retries}") from None

    if verify_ssl := os.getenv("AGOMTRADEPRO_VERIFY_SSL"):
        config["verify_ssl"] = verify_ssl.lower() in ("true", "1", "yes")

    return config


def _load_file_config() -> dict:
    """
    从配置文件加载配置

    支持的配置文件（按优先级）：
    1. .agomtradepro.json（当前目录）
    2. ~/.agomtradepro/config.json（用户目录）
    """
    config_files = [
        Path.cwd() / ".agomtradepro.json",
        Path.home() / ".agomtradepro" / "config.json",
    ]

    for config_file in config_files:
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                raise ConfigurationError(f"Failed to load config file {config_file}: {e}") from e

    return {}


def load_config(
    base_url: str | None = None,
    api_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    verify_ssl: bool | None = None,
) -> ClientConfig:
    """
    加载配置（按优先级合并）

    优先级：构造函数参数 > 环境变量 > 配置文件

    Args:
        base_url: API 基础 URL
        api_token: API Token
        username: 用户名
        password: 密码
        timeout: 请求超时时间
        max_retries: 最大重试次数
        verify_ssl: 是否验证 SSL

    Returns:
        合并后的 ClientConfig 对象
    """
    # 1. 从配置文件加载（最低优先级）
    file_config = _load_file_config()

    # 2. 从环境变量加载（中等优先级）
    env_config = _load_env_config()

    # 3. 构造函数参数（最高优先级）
    param_config = {
        k: v
        for k, v in {
            "base_url": base_url,
            "api_token": api_token,
            "username": username,
            "password": password,
            "timeout": timeout,
            "max_retries": max_retries,
            "verify_ssl": verify_ssl,
        }.items()
        if v is not None
    }

    # 合并配置（低优先级 -> 高优先级）
    merged = {}
    merged.update(file_config)
    merged.update(env_config)
    merged.update(param_config)

    # 构建 ClientConfig
    auth = AuthConfig(
        api_token=merged.pop("api_token", None),
        username=merged.pop("username", None),
        password=merged.pop("password", None),
    )

    return ClientConfig(auth=auth, **merged)


def get_default_config() -> ClientConfig:
    """
    获取默认配置

    从环境变量或配置文件加载，不使用任何参数。

    Returns:
        ClientConfig 对象
    """
    return load_config()
