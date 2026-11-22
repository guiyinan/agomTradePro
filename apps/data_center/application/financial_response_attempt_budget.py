"""Count and pace physical sends within one financial provider execution."""

from __future__ import annotations

from math import isfinite
from threading import Condition
from time import monotonic


class FinancialResponseAttemptBudget:
    """Reserve a fixed number of routed financial transport attempts before send."""

    def __init__(self, maximum_attempts: int, *, minimum_interval_seconds: float = 0) -> None:
        """Create one execution-scoped budget with a non-negative hard ceiling."""

        if (
            isinstance(maximum_attempts, bool)
            or not isinstance(maximum_attempts, int)
            or maximum_attempts < 0
        ):
            raise ValueError("financial response attempt budget must be non-negative")
        self._maximum_attempts = maximum_attempts
        self._reserved_attempts = 0
        if not isfinite(minimum_interval_seconds) or minimum_interval_seconds < 0:
            raise ValueError("financial response send interval must be finite and non-negative")
        self._condition = Condition()
        self._interval = minimum_interval_seconds
        self._next_send = 0.0
        self._stopped = False

    @property
    def maximum_attempts(self) -> int:
        """Return the immutable attempt ceiling."""

        return self._maximum_attempts

    @property
    def reserved_attempts(self) -> int:
        """Return attempts reserved before their transport send."""

        with self._condition:
            return self._reserved_attempts

    def reserve(self) -> bool:
        """Consume one attempt before transport starts, or refuse at the hard cap."""

        with self._condition:
            while not self._stopped and self._reserved_attempts < self._maximum_attempts:
                now = monotonic()
                remaining = self._next_send - now
                if remaining <= 0:
                    self._reserved_attempts += 1
                    self._next_send = now + self._interval
                    return True
                self._condition.wait(timeout=remaining)
            return False

    def stop(self) -> None:
        """Close admission and wake paced callers without refunding any reservation."""
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    @property
    def stopped(self) -> bool:
        """Return whether this execution has closed admission after a hard failure."""
        with self._condition:
            return self._stopped
