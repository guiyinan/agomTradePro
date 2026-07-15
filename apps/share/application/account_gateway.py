"""Registration point for the external Share account gateway."""

from __future__ import annotations

from apps.share.domain.account_gateway import EmptyShareAccountGateway, ShareAccountGateway

_gateway: ShareAccountGateway = EmptyShareAccountGateway()


def register_share_account_gateway(gateway: ShareAccountGateway) -> None:
    """Register the owning account module adapter during Django startup."""

    global _gateway
    _gateway = gateway


def get_share_account_gateway() -> ShareAccountGateway:
    """Return the registered account adapter or a safe empty fallback."""

    return _gateway


__all__ = ["get_share_account_gateway", "register_share_account_gateway"]
