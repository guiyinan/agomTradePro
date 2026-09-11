"""Empty actual creation ledgers for the dedicated local PostgreSQL chain tests."""

from collections.abc import Iterator

import pytest
from django.db import connections, models

from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    SimulatedAccountRawObservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)

CREATION_LEDGER_MODELS: tuple[type[models.Model], ...] = (
    CanonicalAccountCreationAllocationModel,
    SimulatedAccountRawObservationModel,
    SimulatedAccountRowSourceV2Model,
    PhysicalAccountRowObservationV2Model,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingModel,
    CanonicalAccountCreationBindingV2Model,
)


@pytest.fixture
def creation_chain_alias(ownership_alias: str) -> Iterator[str]:
    """Extend the guarded ownership fixture without seeding any creation evidence."""

    connection = connections[ownership_alias]
    with connection.schema_editor() as editor:
        for model in CREATION_LEDGER_MODELS:
            editor.create_model(model)
    try:
        yield ownership_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(CREATION_LEDGER_MODELS):
                editor.delete_model(model)
