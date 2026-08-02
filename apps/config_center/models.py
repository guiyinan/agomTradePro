"""Config center models re-export."""

from apps.config_center.infrastructure.capacity_models import (  # noqa: F401
    StorageCapacityObservationModel as StorageCapacityObservationModel,
)
from apps.config_center.infrastructure.models import *  # noqa: F401,F403
