"""Account-owned read facade for retained simulated corporate-action consent."""

from __future__ import annotations

from datetime import datetime

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantRecord,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)


def read_simulated_corporate_action_grant_scope_records(
    *,
    account_namespace: str,
    account_id: str,
    using: str,
    as_of: datetime,
) -> tuple[SimulatedCorporateActionWriteGrantRecord, ...]:
    """Return validated immutable grant history without issuing current permission.

    The namespace and account identifier are the explicit grant-binding scope,
    not the distinct canonical financial-account namespace.
    """

    if (
        type(account_namespace) is not str
        or account_namespace != "simulated"
        or type(account_id) is not str
        or not account_id
        or account_id.strip() != account_id
        or type(using) is not str
        or not using
        or using.strip() != using
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "historical simulated grant scope or cutoff is invalid"
        )
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(using=using)
    return repository.get_scope_records(account_namespace, account_id, as_of=as_of)


__all__ = ("read_simulated_corporate_action_grant_scope_records",)
