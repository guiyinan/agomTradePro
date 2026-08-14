"""Read-only owner composition for Account physical-row v2 capture."""

from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
)
from apps.simulated_trading.infrastructure.account_physical_row_v2_provider import (
    DjangoExactPhysicalSimulatedAccountRowV2Provider,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)


def build_account_physical_row_v2_provider() -> ExactPhysicalSimulatedAccountRowV2Provider:
    """Build the read-only source-v2 adapter consumed by Account capture."""

    return DjangoExactPhysicalSimulatedAccountRowV2Provider(
        DjangoSimulatedAccountRowSourceV2Repository()
    )


__all__ = ["build_account_physical_row_v2_provider"]
