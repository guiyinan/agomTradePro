"""Public transaction boundary for user-serialized creation and permanent replay."""

from contextlib import AbstractContextManager

from apps.simulated_trading.infrastructure.canonical_account_creation_transaction import (
    canonical_account_creation_transaction,
)


def account_creation_transaction(*, using: str, user_id: int) -> AbstractContextManager[None]:
    """Hold the actual active user's row across the caller's complete creation work."""

    return canonical_account_creation_transaction(using=using, user_id=user_id)


__all__ = ["account_creation_transaction"]
