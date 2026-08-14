"""Broker app-root factory for the read-only order artifact owner reader."""

from __future__ import annotations

from apps.broker_execution.application.order_approval_artifact_owner_reader import (
    BrokerOrderApprovalArtifactOwnerReader,
)
from apps.broker_execution.infrastructure.order_approval_artifact_owner_reader_repository import (
    DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository,
)


def build_django_broker_order_approval_artifact_owner_reader(
    *,
    using: str = "default",
) -> BrokerOrderApprovalArtifactOwnerReader:
    """Build the read-only owner reader without exposing a write repository."""

    return BrokerOrderApprovalArtifactOwnerReader(
        DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository(using=using)
    )


__all__ = ["build_django_broker_order_approval_artifact_owner_reader"]
