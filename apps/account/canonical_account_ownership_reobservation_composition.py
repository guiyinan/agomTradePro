"""Composition root for durable canonical ownership re-observation evidence."""

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)


def build_canonical_account_ownership_reobservation_repository(
    *, using: str
) -> CanonicalAccountOwnershipReobservationV1Repository:
    """Build the durable repository on the caller-selected database alias."""

    if type(using) is not str or not using.strip():
        raise ValueError("using must be a non-empty database alias")
    return DjangoCanonicalAccountOwnershipReobservationV1Repository(using=using)


__all__ = ["build_canonical_account_ownership_reobservation_repository"]
