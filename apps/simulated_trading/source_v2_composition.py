"""Owner-side read-only composition for raw-bound source-v2 workflows."""

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    ExactRawSimulatedAccountObservationV2Provider,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_v2_provider import (
    DjangoExactRawSimulatedAccountObservationV2Provider,
)


def build_exact_raw_simulated_account_observation_v2_provider() -> (
    ExactRawSimulatedAccountObservationV2Provider
):
    """Build the read-only raw-ledger adapter used by source-v2 workflows."""

    return DjangoExactRawSimulatedAccountObservationV2Provider(
        DjangoSimulatedAccountRawObservationRepository()
    )


__all__ = ["build_exact_raw_simulated_account_observation_v2_provider"]
