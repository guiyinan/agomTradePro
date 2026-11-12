"""Exact request and locked-scope contracts for authenticated owner consent."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrantBinding,
)


def _validate_grant_terms(
    *,
    grant_schema: str,
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None,
    terms_version: str | None,
    terms_sha256: str | None,
) -> None:
    """Require schema-specific explicit capabilities and terms without inference."""
    if type(grant_schema) is not str:
        raise ValueError("grant scope schema is invalid")
    if grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
        if any(value is not None for value in (capabilities, terms_version, terms_sha256)):
            raise ValueError("V1 grant scope cannot contain V2 rights or terms")
        return
    if grant_schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        raise ValueError("grant scope schema is unsupported")
    if capabilities is None:
        raise ValueError("V2 grant scope capabilities are required")
    validate_simulated_corporate_action_write_capabilities(capabilities)
    if (
        type(terms_version) is not str
        or not terms_version
        or terms_version.strip() != terms_version
        or len(terms_version) > 192
        or any(character.isspace() for character in terms_version)
    ):
        raise ValueError("V2 grant scope terms version is invalid")
    if (
        type(terms_sha256) is not str
        or len(terms_sha256) != 64
        or any(character not in "0123456789abcdef" for character in terms_sha256)
    ):
        raise ValueError("V2 grant scope terms digest is invalid")


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionGrantConsent:
    """Explicit consent selectors; none of these client facts authenticate an owner."""

    grant_id: str
    grant_version: str
    physical_account_id: int
    expected_binding: SimulatedCorporateActionWriteGrantBinding
    valid_until: datetime
    consent: bool
    expected_predecessor_content_hash: str | None = None
    grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
    terms_version: str | None = None
    terms_sha256: str | None = None

    def __post_init__(self) -> None:
        """Reject implicit consent, non-finite cutoffs and incomplete selectors."""
        for value in (self.grant_id, self.grant_version):
            if (
                type(value) is not str
                or not value
                or len(value) > 192
                or any(character.isspace() for character in value)
            ):
                raise ValueError("grant consent identity is invalid")
        if type(self.physical_account_id) is not int or self.physical_account_id <= 0:
            raise ValueError("grant consent physical account is invalid")
        if type(self.expected_binding) is not SimulatedCorporateActionWriteGrantBinding:
            raise TypeError("grant consent binding is invalid")
        self.expected_binding.__post_init__()
        if (
            type(self.valid_until) is not datetime
            or self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() is None
        ):
            raise ValueError("grant consent expiry must be timezone-aware")
        if self.consent is not True:
            raise ValueError("explicit simulated service-write consent is required")
        _validate_grant_terms(
            grant_schema=self.grant_schema,
            capabilities=self.capabilities,
            terms_version=self.terms_version,
            terms_sha256=self.terms_sha256,
        )
        previous = self.expected_predecessor_content_hash
        if previous is not None and (
            type(previous) is not str
            or len(previous) != 64
            or any(character not in "0123456789abcdef" for character in previous)
        ):
            raise ValueError("grant consent predecessor is invalid")


@dataclass(frozen=True, slots=True)
class LockedSimulatedCorporateActionWriteScope:
    """Server-observed physical ownership, canonical source and policy under one UOW."""

    physical_account_id: int
    binding: SimulatedCorporateActionWriteGrantBinding
    valid_until: datetime
    grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
    terms_version: str | None = None
    terms_sha256: str | None = None

    def __post_init__(self) -> None:
        """Validate the finite receipt without interpreting it as authenticated consent."""
        if type(self.physical_account_id) is not int or self.physical_account_id <= 0:
            raise ValueError("locked physical account is invalid")
        if type(self.binding) is not SimulatedCorporateActionWriteGrantBinding:
            raise TypeError("locked grant binding is invalid")
        self.binding.__post_init__()
        _validate_grant_terms(
            grant_schema=self.grant_schema,
            capabilities=self.capabilities,
            terms_version=self.terms_version,
            terms_sha256=self.terms_sha256,
        )
        if (
            type(self.valid_until) is not datetime
            or self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() is None
        ):
            raise ValueError("locked grant scope expiry must be timezone-aware")


class SimulatedCorporateActionWriteScopeLocker(Protocol):
    """Hold real physical and policy sources through the caller's outer transaction."""

    @property
    def database_alias(self) -> str:
        """Return the concrete alias shared with the credential and grant ledger."""
        ...

    def lock_owned_scope(
        self,
        *,
        physical_account_id: int,
        owner_user_id: int,
        expected_binding: SimulatedCorporateActionWriteGrantBinding,
        expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    ) -> AbstractContextManager[LockedSimulatedCorporateActionWriteScope]:
        """Revalidate exact current physical/source/policy facts before and after yield.

        Legacy callers select the cash-only V1 grant schema unless they explicitly
        request the complete V2 scope.
        """
        ...
