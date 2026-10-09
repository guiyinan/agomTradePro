"""Small ownership-filtered signal read port for cross-app consumers."""

from apps.signal.application.repository_provider import get_signal_repository


def get_owned_signal_asset_code(*, signal_id: int, user_id: int) -> str | None:
    """Return an asset code only when the requested signal belongs to the user."""
    if signal_id <= 0 or user_id <= 0:
        return None
    payload = get_signal_repository().get_signal_snapshot(signal_id)
    if payload is None or payload.get("user_id") != user_id:
        return None
    asset_code: object = payload.get("asset_code")
    return asset_code if isinstance(asset_code, str) else None
