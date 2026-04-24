"""Infrastructure-owned ORM handles for share application use cases."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareLinkModel,
    ShareSnapshotModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

UserModel = get_user_model()

share_link_manager = ShareLinkModel.objects
share_snapshot_manager = ShareSnapshotModel.objects
share_access_log_manager = ShareAccessLogModel.objects
simulated_account_manager = SimulatedAccountModel.objects
user_manager = UserModel.objects

ShareLinkDoesNotExist = ShareLinkModel.DoesNotExist
ShareSnapshotDoesNotExist = ShareSnapshotModel.DoesNotExist
SimulatedAccountDoesNotExist = SimulatedAccountModel.DoesNotExist
UserDoesNotExist = UserModel.DoesNotExist
