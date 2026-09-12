"""Bridge the physical owner's public live reader into Account's typed port."""

from apps.account.application.owner_tenant_authority_v2_contracts import (
    CurrentOwnerPhysicalRow,
    CurrentOwnerPhysicalRowReader,
    OwnerTenantAuthorityV2Unavailable,
)
from apps.simulated_trading.account_ownership_composition import (
    build_current_account_ownership_reader,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnership,
    CurrentAccountOwnershipReader,
    CurrentAccountOwnershipUnavailable,
)


class SimulatedAccountOwnerPhysicalRowV2Reader:
    """Retain a server-owned namespace and the physical source's actual alias."""

    def __init__(self, *, namespace: str, reader: CurrentAccountOwnershipReader) -> None:
        """Close the namespace mapping in composition, never in a client command."""
        if (
            type(namespace) is not str
            or not namespace
            or len(namespace) > 192
            or any(c.isspace() for c in namespace)
        ):
            raise ValueError("namespace must be a bounded canonical token")
        self._namespace = namespace
        self._reader = reader

    @property
    def unit_of_work_key(self) -> str:
        """Return the physical source transaction key checked by the Account service."""
        return f"django:{self._reader.database_alias}"

    def read_locked(self, *, namespace: str, row_pk: int) -> CurrentOwnerPhysicalRow | None:
        """Map actual source facts without changing their clocks, owner or active state."""
        if type(namespace) is not str or namespace != self._namespace:
            raise OwnerTenantAuthorityV2Unavailable(
                "physical namespace is not bound to this reader"
            )
        try:
            observed = self._reader.read_locked(row_pk=row_pk)
        except CurrentAccountOwnershipUnavailable as error:
            raise OwnerTenantAuthorityV2Unavailable(
                "live physical ownership is unavailable"
            ) from error
        if observed is None:
            return None
        if type(observed) is not CurrentAccountOwnership:
            raise OwnerTenantAuthorityV2Unavailable("physical source type substitution")
        observed.__post_init__()
        if observed.row_pk != row_pk:
            raise OwnerTenantAuthorityV2Unavailable("physical source row selector substitution")
        return CurrentOwnerPhysicalRow(
            namespace=self._namespace,
            row_pk=observed.row_pk,
            user_id=observed.user_id,
            raw_account_type=observed.account_type.value,
            is_active=observed.is_active,
            row_created_at=observed.row_created_at,
            row_updated_at=observed.row_updated_at,
            observed_at=observed.observed_at,
        )


def build_simulated_account_owner_physical_row_v2_reader(
    *, namespace: str, using: str = "default"
) -> CurrentOwnerPhysicalRowReader:
    """Build the cross-app port through the physical owner's public composition."""
    return SimulatedAccountOwnerPhysicalRowV2Reader(
        namespace=namespace, reader=build_current_account_ownership_reader(using=using)
    )
