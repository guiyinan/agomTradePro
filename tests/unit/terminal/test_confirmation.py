"""Terminal confirmation token regression tests."""

from unittest.mock import patch

from django.core.cache import cache

from apps.terminal.application.confirmation import ConfirmationTokenService


def test_confirmation_token_can_only_be_consumed_once() -> None:
    cache.clear()
    service = ConfirmationTokenService()
    params = {"asset_code": "000001.SZ", "quantity": 100}
    token, details = service.create_token(
        user_id=7,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    )

    assert details["command_name"] == "place_order"
    assert service.validate_token(
        token,
        user_id=7,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    ) == (True, "")
    assert service.validate_token(
        token,
        user_id=7,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    ) == (False, "Token already used")


def test_mismatched_request_does_not_consume_confirmation_token() -> None:
    cache.clear()
    service = ConfirmationTokenService()
    params = {"asset_code": "000001.SZ"}
    token, _ = service.create_token(
        user_id=7,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    )

    assert service.validate_token(
        token,
        user_id=8,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    ) == (False, "Token user mismatch")
    assert service.validate_token(
        token,
        user_id=7,
        command_name="place_order",
        params=params,
        risk_level="high",
        mode="live",
    ) == (True, "")


def test_atomic_used_marker_closes_stale_nonce_replay_window() -> None:
    service = ConfirmationTokenService()
    params = {"asset_code": "000001.SZ"}

    class _StaleNonceCache:
        def __init__(self) -> None:
            self.used = False

        def set(self, key: str, value: str, timeout: int) -> None:
            return None

        def get(self, key: str) -> str:
            return "unused"

        def add(self, key: str, value: str, timeout: int) -> bool:
            if self.used:
                return False
            self.used = True
            return True

    stale_cache = _StaleNonceCache()
    with patch("apps.terminal.application.confirmation.cache", stale_cache):
        token, _ = service.create_token(
            user_id=7,
            command_name="place_order",
            params=params,
            risk_level="high",
            mode="live",
        )
        first_result = service.validate_token(
            token,
            user_id=7,
            command_name="place_order",
            params=params,
            risk_level="high",
            mode="live",
        )
        second_result = service.validate_token(
            token,
            user_id=7,
            command_name="place_order",
            params=params,
            risk_level="high",
            mode="live",
        )

    assert first_result == (True, "")
    assert second_result == (False, "Token already used")
