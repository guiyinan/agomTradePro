"""
Domain Interfaces (Protocols) for Signal Module.

These protocols define the contracts that Infrastructure layer must implement.
Application layer depends on these protocols, not concrete implementations.
"""

from datetime import date
from typing import Any, List, Optional, Protocol

from shared.domain.interfaces import FilterableRepositoryProtocol

from .entities import InvestmentSignal, SignalStatus


class InvestmentSignalRepositoryProtocol(FilterableRepositoryProtocol[InvestmentSignal, str], Protocol):
    """
    Protocol for Investment Signal Repository.

    Extends the base FilterableRepositoryProtocol with signal-specific operations.
    Application layer should depend on this protocol, not concrete implementations.
    """

    def get_by_id(self, id: str) -> InvestmentSignal | None:
        """Retrieve a signal by its identifier.

        Args:
            id: The signal's unique identifier (as string)

        Returns:
            The signal if found, None otherwise
        """
        ...

    def get_all(self) -> list[InvestmentSignal]:
        """Retrieve all signals.

        Returns:
            List of all signals
        """
        ...

    def save(self, entity: InvestmentSignal) -> InvestmentSignal:
        """Persist a signal (create or update).

        Args:
            entity: The signal to persist

        Returns:
            The persisted signal (may include generated ID)
        """
        ...

    def delete(self, id: str) -> bool:
        """Delete a signal by its identifier.

        Args:
            id: The signal's unique identifier

        Returns:
            True if deleted, False if not found
        """
        ...

    def find_by_criteria(self, **criteria: Any) -> list[InvestmentSignal]:
        """Find signals matching the given criteria.

        Args:
            **criteria: Key-value pairs for filtering

        Returns:
            List of matching signals
        """
        ...

    def count(self, **criteria: Any) -> int:
        """Count signals matching the given criteria.

        Args:
            **criteria: Key-value pairs for filtering

        Returns:
            Number of matching signals
        """
        ...

    # Signal-specific methods

    def find_signals_with_invalidation_rules(
        self,
        status: SignalStatus
    ) -> list[InvestmentSignal]:
        """Find signals that have invalidation rules and match the given status.

        Args:
            status: The signal status to filter by

        Returns:
            List of signals with invalidation rules
        """
        ...

    def find_signals_to_invalidate(self, as_of_date: date) -> list[InvestmentSignal]:
        """Find signals that should be checked for invalidation.

        Args:
            as_of_date: The date to check against

        Returns:
            List of signals that should be invalidated
        """
        ...

    def mark_invalidated(
        self,
        signal_id: str,
        reason: str,
        details: dict
    ) -> bool:
        """Mark a signal as invalidated.

        Args:
            signal_id: The signal's unique identifier
            reason: The reason for invalidation
            details: Additional details about the invalidation

        Returns:
            True if updated, False if not found
        """
        ...

    def mark_rejected(
        self,
        signal_id: str,
        reason: str
    ) -> bool:
        """Mark a signal as rejected.

        Args:
            signal_id: The signal's unique identifier
            reason: The reason for rejection

        Returns:
            True if updated, False if not found
        """
        ...

    def persist_invalidation_outcome(
        self,
        *,
        signal_id: str,
        current_status: str,
        reason: str,
        details: dict[str, Any],
    ) -> bool:
        """Persist an invalidation outcome for legacy compatibility callers.

        Args:
            signal_id: The signal's unique identifier
            current_status: The signal status before invalidation handling
            reason: The rejection/invalidation reason
            details: Additional invalidation details to persist

        Returns:
            True if updated, False if not found
        """
        ...

    def update_signal_status(
        self,
        signal_id: str,
        new_status: SignalStatus,
        rejection_reason: str | None = None
    ) -> bool:
        """Update a signal's status.

        Args:
            signal_id: The signal's unique identifier
            new_status: The new status
            rejection_reason: Optional reason for rejection

        Returns:
            True if updated, False if not found
        """
        ...

    def get_active_signals(self) -> list[InvestmentSignal]:
        """Get all active (approved) signals.

        Returns:
            List of active signals
        """
        ...

    def get_pending_signals(self) -> list[InvestmentSignal]:
        """Get all pending signals.

        Returns:
            List of pending signals
        """
        ...

    def get_signals_by_asset(
        self,
        asset_code: str,
        status: SignalStatus | None = None
    ) -> list[InvestmentSignal]:
        """Get signals by asset code.

        Args:
            asset_code: The asset code
            status: Optional status filter

        Returns:
            List of matching signals
        """
        ...

    def get_signals_by_status(self, status: SignalStatus) -> list[InvestmentSignal]:
        """Get signals by status.

        Args:
            status: The status to filter by

        Returns:
            List of matching signals
        """
        ...


class UserRepositoryProtocol(Protocol):
    """
    Protocol for User Repository.

    Provides access to user data for notification purposes.
    """

    def get_staff_emails(self) -> list[str]:
        """Get email addresses of all active staff users.

        Returns:
            List of staff email addresses
        """
        ...

    def get_user_by_id(self, user_id: int) -> Any | None:
        """Get a user by ID.

        Args:
            user_id: The user's ID

        Returns:
            The user if found, None otherwise
        """
        ...
