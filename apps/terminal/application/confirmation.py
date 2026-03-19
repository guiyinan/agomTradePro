"""
Terminal Confirmation Token Service.

基于 Django signing 的确认令牌管理。
"""

import hashlib
import json
import logging
import uuid

from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

logger = logging.getLogger(__name__)

_SALT = "terminal-confirm"
_TOKEN_MAX_AGE = 120  # seconds
_NONCE_CACHE_PREFIX = "terminal_nonce:"
_NONCE_TTL = 300  # seconds


class ConfirmationTokenService:
    """确认令牌服务"""

    def __init__(self) -> None:
        self._signer = TimestampSigner(salt=_SALT)

    @staticmethod
    def _params_hash(params: dict) -> str:
        """生成参数的短 hash"""
        raw = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def create_token(
        self,
        user_id: int,
        command_name: str,
        params: dict,
        risk_level: str,
        mode: str,
    ) -> tuple[str, dict]:
        """创建确认令牌。

        Returns:
            (token_string, details_dict)
        """
        nonce = uuid.uuid4().hex[:12]
        params_hash = self._params_hash(params)
        payload = f"{user_id}:{command_name}:{params_hash}:{risk_level}:{mode}:{nonce}"
        token = self._signer.sign(payload)

        # 将 nonce 标记为未使用
        cache.set(f"{_NONCE_CACHE_PREFIX}{nonce}", "unused", _NONCE_TTL)

        details = {
            "command_name": command_name,
            "risk_level": risk_level,
            "mode": mode,
            "params_summary": json.dumps(params, default=str)[:200],
        }
        return token, details

    def validate_token(
        self,
        token: str,
        user_id: int,
        command_name: str,
        params: dict,
        risk_level: str,
        mode: str,
    ) -> tuple[bool, str]:
        """验证确认令牌。

        Returns:
            (is_valid, error_message)
        """
        try:
            payload = self._signer.unsign(token, max_age=_TOKEN_MAX_AGE)
        except SignatureExpired:
            return False, "Confirmation token expired"
        except BadSignature:
            return False, "Invalid confirmation token"

        parts = payload.split(":")
        if len(parts) != 6:
            return False, "Malformed token payload"

        t_user, t_cmd, t_hash, t_risk, t_mode, t_nonce = parts

        # Field matching
        if str(user_id) != t_user:
            return False, "Token user mismatch"
        if command_name != t_cmd:
            return False, "Token command mismatch"
        if self._params_hash(params) != t_hash:
            return False, "Token params mismatch"
        if risk_level != t_risk:
            return False, "Token risk level mismatch"
        if mode != t_mode:
            return False, "Token mode mismatch"

        # Nonce replay check
        cache_key = f"{_NONCE_CACHE_PREFIX}{t_nonce}"
        nonce_state = cache.get(cache_key)
        if nonce_state is None:
            return False, "Token nonce expired or unknown"
        if nonce_state == "used":
            return False, "Token already used"

        # Mark as used
        cache.set(cache_key, "used", _NONCE_TTL)
        return True, ""
