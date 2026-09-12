"""Compose current physical reads and successor observations on one database."""

from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.simulated_trading.account_ownership_composition import (
    build_current_account_ownership_reader,
)
from apps.simulated_trading.application.account_row_reobservation import ReobserveExistingAccountRow
from apps.simulated_trading.infrastructure.simulated_account_mutation_writer import (
    DjangoSimulatedAccountMutationWriter,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)


def build_existing_account_reobserver(
    *, using: str, settings: CanonicalAccountCreationEvidenceSettings
) -> ReobserveExistingAccountRow:
    """Bind a configured evidence lifetime without reading configuration or writing rows."""
    if type(settings) is not CanonicalAccountCreationEvidenceSettings:
        raise TypeError("settings must be exact canonical evidence settings")
    settings.__post_init__()
    return ReobserveExistingAccountRow(
        reader=build_current_account_ownership_reader(using=using),
        writer=DjangoSimulatedAccountMutationWriter(
            repository=DjangoSimulatedAccountRawObservationRepository(using=using),
            using=using,
            validity_period=settings.as_timedelta(),
        ),
    )
