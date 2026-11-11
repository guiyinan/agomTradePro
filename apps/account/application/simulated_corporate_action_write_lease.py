"""Validate provider-issued owner scope before a simulated action service write."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.domain.simulated_corporate_action_write_lease import (
    SimulatedCorporateActionWriteLease,
    SimulatedCorporateActionWriteLeaseSelector,
)
from core.exceptions import BusinessLogicError


class SimulatedCorporateActionWriteLeaseUnavailable(BusinessLogicError):
    """The exact current owner-scoped service-write lease cannot be proven."""

    default_message = "模拟公司行动服务写入授权不可用"
    default_code = "SIMULATED_CORPORATE_ACTION_WRITE_LEASE_UNAVAILABLE"


class SimulatedCorporateActionWriteLeaseProvider(Protocol):
    """Read one exact provider-issued lease and its current revocation state."""

    def get_current_lease(
        self,
        *,
        selector: SimulatedCorporateActionWriteLeaseSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteLease | None:
        """Return the selected current lease, or ``None`` when it cannot be proven."""


@dataclass(frozen=True, slots=True)
class RequireSimulatedCorporateActionWriteLease:
    """Return a lease only after exact scope, source, state, and time validation."""

    _provider: SimulatedCorporateActionWriteLeaseProvider

    def __init__(self, provider: SimulatedCorporateActionWriteLeaseProvider | None) -> None:
        """Bind the required provider; missing or incomplete readers fail closed."""

        if provider is None or not callable(getattr(provider, "get_current_lease", None)):
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "owner-scoped service-write lease provider is not configured"
            )
        object.__setattr__(self, "_provider", provider)

    def execute(
        self,
        selector: SimulatedCorporateActionWriteLeaseSelector,
        *,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteLease:
        """Validate one provider result at the caller's explicit aware cutoff."""

        if type(selector) is not SimulatedCorporateActionWriteLeaseSelector:
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "owner-scoped service-write lease selector is invalid"
            )
        try:
            selector.__post_init__()
            _validate_as_of(as_of)
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "owner-scoped service-write lease selector or clock is invalid"
            ) from error

        lease = self._provider.get_current_lease(selector=selector, as_of=as_of)
        if type(lease) is not SimulatedCorporateActionWriteLease:
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "provider did not return the exact owner-scoped service-write lease"
            )
        try:
            lease.__post_init__()
            is_active = lease.is_active_at(as_of)
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "provider returned a forged or invalid owner-scoped service-write lease"
            ) from error
        if lease.selector != selector or not is_active:
            raise SimulatedCorporateActionWriteLeaseUnavailable(
                "owner-scoped service-write lease is revoked, expired, or out of scope"
            )
        return lease


def _validate_as_of(value: object) -> datetime:
    """Require one exact timezone-aware application cutoff."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be an exact timezone-aware datetime")
    return value


__all__ = [
    "RequireSimulatedCorporateActionWriteLease",
    "SimulatedCorporateActionWriteLeaseProvider",
    "SimulatedCorporateActionWriteLeaseUnavailable",
]
