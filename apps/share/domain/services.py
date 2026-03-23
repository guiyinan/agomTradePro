"""
Share Domain Services

纯算法服务，不依赖外部框架。
"""
import secrets
import string
from typing import Optional


def generate_short_code(length: int = 10) -> str:
    """
    生成不可预测的随机短码

    使用 secrets 模块确保密码学安全性，
    避免使用 random 模块（可预测）。

    Args:
        length: 短码长度，默认10位

    Returns:
        随机短码字符串

    Example:
        >>> code = generate_short_code()
        >>> len(code)
        10
        >>> code.isalnum()
        True
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def validate_short_code(code: str, min_length: int = 6, max_length: int = 32) -> bool:
    """
    验证短码格式

    Args:
        code: 待验证的短码
        min_length: 最小长度
        max_length: 最大长度

    Returns:
        是否有效
    """
    if not code or not isinstance(code, str):
        return False
    if len(code) < min_length or len(code) > max_length:
        return False
    return all(c in string.ascii_letters + string.digits for c in code)


def hash_password(password: str) -> str:
    """
    对密码进行哈希（占位实现）

    注意：实际实现应使用 Django 的 make_password，
    这里定义在 Domain 层是为了保持接口完整。
    实际调用应在 Infrastructure 层。

    Args:
        password: 原始密码

    Returns:
        哈希后的密码（占位）
    """
    # 此方法不应在 Domain 层实际使用
    # 实际实现应使用 Django 的 make_password
    raise NotImplementedError("Use Django's make_password in Infrastructure layer")


def verify_password(password: str, hashed: str) -> bool:
    """
    验证密码（占位实现）

    注意：实际实现应使用 Django 的 check_password，
    这里定义在 Domain 层是为了保持接口完整。
    实际调用应在 Infrastructure 层。

    Args:
        password: 原始密码
        hashed: 哈希后的密码

    Returns:
        是否匹配（占位）
    """
    # 此方法不应在 Domain 层实际使用
    # 实际实现应使用 Django 的 check_password
    raise NotImplementedError("Use Django's check_password in Infrastructure layer")


def hash_ip_address(ip_address: str, salt: str | None = None) -> str:
    """
    对 IP 地址进行哈希，不直接存储原始 IP

    Args:
        ip_address: 原始 IP 地址
        salt: 盐值（可选）

    Returns:
        哈希后的 IP 字符串（占位）
    """
    # 此方法不应在 Domain 层实际使用
    # 实际实现应使用 hashlib
    raise NotImplementedError("Use hashlib in Infrastructure layer")
