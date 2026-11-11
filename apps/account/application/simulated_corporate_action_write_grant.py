"""Application contracts for reading exact current simulated action grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantRecord,
    SimulatedCorporateActionWriteGrantRevocation,
    SimulatedCorporateActionWriteGrantSelector,
)
from core.exceptions import BusinessLogicError


class SimulatedCorporateActionWriteGrantUnavailable(BusinessLogicError):
    """The exact current grant cannot be proven from the Account ledger."""

    default_message = "模拟公司行动服务写入授权不可用"
    default_code = "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_UNAVAILABLE"


class SimulatedCorporateActionWriteGrantConflict(SimulatedCorporateActionWriteGrantUnavailable):
    """A grant or revocation identity conflicts with immutable stored history."""

    default_message = "模拟公司行动服务写入授权记录冲突"
    default_code = "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_CONFLICT"


class SimulatedCorporateActionWriteGrantCorruption(SimulatedCorporateActionWriteGrantUnavailable):
    """A durable grant row fails canonical payload or hash validation."""

    default_message = "模拟公司行动服务写入授权账本损坏"
    default_code = "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_CORRUPTION"


class SimulatedCorporateActionWriteGrantProvider(Protocol):
    """Read one exact grant head and any revocation known at a cutoff."""

    def get_current_grant(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteGrantCurrent | None:
        """Return the selected exact head, or ``None`` without historical fallback."""


class SimulatedCorporateActionWriteGrantRepository(
    SimulatedCorporateActionWriteGrantProvider, Protocol
):
    """Define explicit append operations without authorizing an issuer."""

    def get_scope_records(
        self, account_namespace: str, account_id: str, *, as_of: datetime
    ) -> tuple[SimulatedCorporateActionWriteGrantRecord, ...]:
        """Read known historical consent metadata without granting current authority."""
        ...

    def get_exact_record(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteGrantRecord | None:
        """Read historical/revoked metadata for withdrawal, never as current authority."""
        ...

    def get_current_for_scope(
        self,
        account_namespace: str,
        account_id: str,
        *,
        as_of: datetime,
    ) -> tuple[SimulatedCorporateActionWriteGrant, ...]:
        """Return every active exact chain head in one account scope without owner filtering."""

    def append_grant(
        self,
        grant: SimulatedCorporateActionWriteGrant,
        *,
        expected_predecessor_content_hash: str | None,
    ) -> SimulatedCorporateActionWriteGrant:
        """Append or exactly replay one root or successor grant record."""

    def append_revocation(
        self,
        revocation: SimulatedCorporateActionWriteGrantRevocation,
    ) -> SimulatedCorporateActionWriteGrantRevocation:
        """Append or exactly replay one revocation for its exact durable grant row."""


@dataclass(frozen=True, slots=True)
class RequireSimulatedCorporateActionWriteGrant:
    """Return a grant only after exact-head, scope, revocation and time validation."""

    _provider: SimulatedCorporateActionWriteGrantProvider

    def __init__(self, provider: SimulatedCorporateActionWriteGrantProvider | None) -> None:
        """Bind a required exact-current reader; a missing provider fails closed."""

        if provider is None or not callable(getattr(provider, "get_current_grant", None)):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant provider is not configured"
            )
        object.__setattr__(self, "_provider", provider)

    def execute(
        self,
        selector: SimulatedCorporateActionWriteGrantSelector,
        *,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteGrant:
        """Validate one provider result against its exact selector and aware cutoff."""

        if type(selector) is not SimulatedCorporateActionWriteGrantSelector:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant selector is invalid"
            )
        try:
            selector.__post_init__()
            _validate_as_of(as_of)
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant selector or clock is invalid"
            ) from error

        current = self._provider.get_current_grant(selector=selector, as_of=as_of)
        if type(current) is not SimulatedCorporateActionWriteGrantCurrent:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "provider did not return the exact current simulated write grant"
            )
        try:
            current.__post_init__()
            is_active = current.is_active_at(as_of)
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "provider returned a forged or invalid simulated write grant"
            ) from error
        if current.selector != selector or not is_active:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated write grant is revoked, expired, or out of exact scope"
            )
        return current.grant


def _validate_as_of(value: object) -> datetime:
    """Require one exact timezone-aware application cutoff."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be an exact timezone-aware datetime")
    return value


__all__ = [
    "RequireSimulatedCorporateActionWriteGrant",
    "SimulatedCorporateActionWriteGrantConflict",
    "SimulatedCorporateActionWriteGrantCorruption",
    "SimulatedCorporateActionWriteGrantProvider",
    "SimulatedCorporateActionWriteGrantRepository",
    "SimulatedCorporateActionWriteGrantUnavailable",
]
