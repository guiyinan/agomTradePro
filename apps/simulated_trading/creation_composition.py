"""Public same-database construction of the actual account-creation stages."""

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.simulated_trading.application.canonical_account_creation_read import (
    CanonicalAccountCreationReader,
)
from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowWriter,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.canonical_account_creation_reader import (
    DjangoCanonicalAccountCreationReader,
)
from apps.simulated_trading.infrastructure.canonical_account_creation_row_writer import (
    DjangoCanonicalAccountCreationRowWriter,
)
from apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline import (
    SimulatedAccountMutationWriterProtocol,
    SimulatedAccountRowSourceV2CaptureProtocol,
)
from apps.simulated_trading.infrastructure.simulated_account_mutation_writer import (
    DjangoSimulatedAccountMutationWriter,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.source_v2_composition import (
    build_exact_raw_simulated_account_observation_v2_provider,
)


@dataclass(frozen=True, slots=True)
class SimulatedAccountCreationStages:
    """Owner write ports sharing one explicit database and configuration snapshot."""

    database_alias: str
    account_reader: CanonicalAccountCreationReader
    row_writer: CanonicalAccountCreationRowWriter
    raw_writer: SimulatedAccountMutationWriterProtocol
    source_capture: SimulatedAccountRowSourceV2CaptureProtocol


def build_simulated_account_creation_stages(
    *, using: str, settings: CanonicalAccountCreationEvidenceSettings
) -> SimulatedAccountCreationStages:
    """Build actual stages without reading configuration or opening a transaction.

    The caller supplies a previously resolved settings snapshot and owns the
    transaction spanning these stages and the Account-owned evidence ledgers.
    """

    if type(using) is not str or not using or any(character.isspace() for character in using):
        raise ValueError("using must be an explicit canonical database alias")
    if type(settings) is not CanonicalAccountCreationEvidenceSettings:
        raise TypeError("settings must be an exact creation evidence settings snapshot")
    settings.__post_init__()
    settings.deadline_at(datetime.now(UTC))
    duration = settings.as_timedelta()
    raw_repository = DjangoSimulatedAccountRawObservationRepository(using=using)
    return SimulatedAccountCreationStages(
        database_alias=using,
        account_reader=DjangoCanonicalAccountCreationReader(using=using),
        row_writer=DjangoCanonicalAccountCreationRowWriter(using=using),
        raw_writer=DjangoSimulatedAccountMutationWriter(
            repository=raw_repository, using=using, validity_period=duration
        ),
        source_capture=CaptureSimulatedAccountRowSourceV2(
            observation_provider=build_exact_raw_simulated_account_observation_v2_provider(
                using=using
            ),
            repository=DjangoSimulatedAccountRowSourceV2Repository(using=using),
            validity_period=duration,
        ),
    )


__all__ = ["SimulatedAccountCreationStages", "build_simulated_account_creation_stages"]
