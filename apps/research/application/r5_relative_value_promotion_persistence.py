"""ID-only registration contracts for persisted R5 promotion artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeAlias

from apps.fixed_income.domain.evidence import canonical_hash, require_aware
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)

R5PromotionArtifact: TypeAlias = R5RelativeValuePromotionPolicy | R5RelativeValuePromotionTrial


class R5PromotionServerClock(Protocol):
    """Authoritative clock used to reject future PIT cutoffs."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


def require_r5_promotion_pit_cutoff(
    as_of: datetime,
    *,
    server_now: datetime,
) -> None:
    """Reject a PIT cutoff that is later than authoritative server time."""

    require_aware(as_of, "R5 promotion PIT as_of")
    require_aware(server_now, "R5 promotion server_now")
    if as_of > server_now:
        raise R5RelativeValuePromotionEvidenceError(
            "r5_promotion.future_cutoff",
            "PIT as_of cannot be later than authoritative server time",
        )


class R5PromotionArtifactKind(str, Enum):
    """Allowlisted Research artifact kinds sharing one immutable ledger."""

    POLICY = "policy"
    TRIAL = "trial"


def r5_promotion_artifact_registration_command_hash(
    *,
    artifact_kind: R5PromotionArtifactKind,
    artifact_ref: R5RelativeValuePromotionRef,
) -> str:
    """Seal the complete caller-safe registration command."""

    return canonical_hash(
        {
            "schema": "research-r5-promotion-artifact-registration-command.v1",
            "artifact_kind": artifact_kind.value,
            "artifact": (artifact_ref.stable_id, artifact_ref.version),
        }
    )


@dataclass(frozen=True)
class RegisterR5PromotionArtifactCommand:
    """ID/version-only request carrying no payload, hash, clock or evidence."""

    artifact_kind: R5PromotionArtifactKind
    artifact_ref: R5RelativeValuePromotionRef

    @property
    def command_hash(self) -> str:
        """Return the exact caller-safe command seal."""

        return r5_promotion_artifact_registration_command_hash(
            artifact_kind=self.artifact_kind,
            artifact_ref=self.artifact_ref,
        )


class ExactR5PromotionArtifactSource(Protocol):
    """Research owner port for one exact approved policy or completed trial."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        *,
        artifact_kind: R5PromotionArtifactKind,
        artifact_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5PromotionArtifact | None:
        """Return an authoritative artifact by exact kind, ID and version."""


class R5PromotionArtifactRegistrationWriter(Protocol):
    """Closure-bound writer accepting only the public ID-only command."""

    def register(
        self,
        command: RegisterR5PromotionArtifactCommand,
    ) -> R5PromotionArtifact:
        """Reread the Research owner graph and append one exact artifact."""


class RegisterR5PromotionArtifact:
    """Application use case for one server-clocked artifact registration."""

    def __init__(self, *, writer: R5PromotionArtifactRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterR5PromotionArtifactCommand,
    ) -> R5PromotionArtifact:
        """Delegate the ID-only request to the closure-bound writer."""

        return self._writer.register(command)


__all__ = [
    "ExactR5PromotionArtifactSource",
    "R5PromotionArtifact",
    "R5PromotionArtifactKind",
    "R5PromotionArtifactRegistrationWriter",
    "R5PromotionServerClock",
    "RegisterR5PromotionArtifact",
    "RegisterR5PromotionArtifactCommand",
    "require_r5_promotion_pit_cutoff",
    "r5_promotion_artifact_registration_command_hash",
]
