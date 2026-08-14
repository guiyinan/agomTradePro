"""Closed-world identity-winner adapter for Broker order approval artifacts."""

from __future__ import annotations

from datetime import datetime

from apps.broker_execution.application.order_approval_artifact_owner_reader import (
    BrokerOrderApprovalArtifactIdentityWinner,
)
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    BrokerOrderApprovalArtifactModel,
)
from apps.broker_execution.infrastructure.order_approval_artifact_repository import (
    BrokerOrderApprovalArtifactClock,
    BrokerOrderApprovalArtifactCorruption,
    BrokerOrderApprovalArtifactUnavailable,
    DjangoBrokerOrderApprovalArtifactRepository,
)


class DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository:
    """Restore the sealed ledger before applying ID/version/PIT selectors."""

    __slots__ = ("_sealed_repository", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerOrderApprovalArtifactClock | None = None,
    ) -> None:
        self._using = using
        self._sealed_repository = DjangoBrokerOrderApprovalArtifactRepository(
            using=using,
            clock=clock,
        )

    def get_identity_winner(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> BrokerOrderApprovalArtifactIdentityWinner | None:
        """Return the one sealed identity winner recorded and valid at the cutoff."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise BrokerOrderApprovalArtifactUnavailable("artifact as_of is naive")
        if as_of > self._sealed_repository.now():
            raise BrokerOrderApprovalArtifactUnavailable("future artifact as_of is forbidden")
        rows = list(BrokerOrderApprovalArtifactModel._default_manager.using(self._using).all())
        restored = tuple(
            (row, self._sealed_repository._restore(row)) for row in rows  # noqa: SLF001
        )
        matches = tuple(
            (row, artifact)
            for row, artifact in restored
            if artifact.artifact_id == artifact_id and artifact.artifact_version == artifact_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise BrokerOrderApprovalArtifactCorruption(
                "order approval artifact identity winner is ambiguous"
            )
        row, artifact = matches[0]
        recorded_at = row.recorded_at
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise BrokerOrderApprovalArtifactCorruption(
                "order approval artifact recorded_at is naive"
            )
        if not recorded_at <= as_of < artifact.valid_until:
            return None
        return BrokerOrderApprovalArtifactIdentityWinner(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            identity_hash=artifact.identity_hash,
            content_hash=artifact.content_hash,
            account_id=artifact.account_id,
            order_version=artifact.order_version,
            approval_digest=artifact.approval_digest,
            risk_policy_version=artifact.approval_snapshot.risk_policy_version,
            approved_at=artifact.approved_at,
            recorded_at=recorded_at,
            valid_until=artifact.valid_until,
        )


__all__ = ["DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository"]
