"""Expose only the allocated Physical-v3 ledger model in isolated tests."""

from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)

__all__ = ["AllocatedPhysicalAccountRowObservationV3Model"]
