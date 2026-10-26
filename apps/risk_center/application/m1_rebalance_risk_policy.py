"""Application use cases and public ports for M1 rebalance risk revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskPolicyPublishCommand as M1RiskPolicyPublishCommand,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskPolicyQualification as M1RiskPolicyQualification,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskPolicyRevision as M1RiskPolicyRevision,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskSourceSnapshot as M1RiskSourceSnapshot,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    RiskQualificationState,
    qualify_revision,
    validate_publish_command,
)


class M1RiskPolicyValidationError(ValueError):
    """The owner command cannot create a safe M1 revision."""

    def __init__(self, reason_codes: tuple[str, ...]) -> None:
        """Keep stable business blocker codes for API and tests."""

        self.reason_codes = reason_codes
        super().__init__(", ".join(reason_codes))


class M1RiskPolicyNotFoundError(LookupError):
    """The requested account/version pair does not exist."""


class M1RiskPolicySourceCorruptError(ValueError):
    """Stored revision columns and versioned falsification source disagree."""


class M1RiskPolicyAlreadyRevokedError(ValueError):
    """A revision already has an immutable revocation audit event."""


class M1RiskPolicyIdempotencyConflictError(ValueError):
    """A stable request identity was replayed with a different request body."""


M1RiskPolicyOperation = Literal["publish", "revoke"]


@dataclass(frozen=True, slots=True)
class M1RiskPolicyIdempotencyContext:
    """Transport retry identity already scoped to an authenticated owner/account."""

    account_id: int
    actor_user_id: int
    operation: M1RiskPolicyOperation
    identity_sha256: str
    request_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete or non-canonical retry identities at the app boundary."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("idempotency account_id must be a positive integer")
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("idempotency actor_user_id must be a positive integer")
        if type(self.operation) is not str or self.operation not in {"publish", "revoke"}:
            raise ValueError("idempotency operation is unsupported")
        for field_name in ("identity_sha256", "request_sha256"):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


class M1RiskPolicyRevisionRepository(Protocol):
    """Persistence port for immutable M1 risk revisions."""

    def find_revision_by_idempotency(
        self,
        *,
        context: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision | None:
        """Return a previously committed result or reject a reused changed body."""
        ...

    def create_revision(
        self,
        command: M1RiskPolicyPublishCommand,
        *,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Persist exactly one owner command and return generated source identity."""
        ...

    def list_revisions(self, *, account_id: int) -> tuple[M1RiskPolicyRevision, ...]:
        """Read immutable revisions for one account without choosing by request time."""
        ...

    def revoke_revision(
        self,
        *,
        account_id: int,
        risk_policy_version: str,
        actor_user_id: int,
        reason: str,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Append a revocation audit event without mutating the revision row."""
        ...


class PublishM1RiskPolicyRevisionUseCase:
    """Publish a new, explicitly owner-approved M1-only risk policy version."""

    def __init__(self, repository: M1RiskPolicyRevisionRepository) -> None:
        """Inject the RiskCenter revision repository."""

        self._repository = repository

    def execute(
        self,
        *,
        command: M1RiskPolicyPublishCommand,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Replay a matching commit before validation; otherwise write once atomically."""

        _validate_idempotency_scope(
            context=idempotency,
            account_id=command.account_id,
            actor_user_id=command.actor_user_id,
            operation="publish",
        )
        prior = self._repository.find_revision_by_idempotency(context=idempotency)
        if prior is not None:
            return prior
        reasons = validate_publish_command(command)
        if reasons:
            raise M1RiskPolicyValidationError(reasons)
        return self._repository.create_revision(command, idempotency=idempotency)


class GetM1RiskPolicyQualificationUseCase:
    """Resolve the unique revision that covers one preview cutoff."""

    def __init__(self, repository: M1RiskPolicyRevisionRepository) -> None:
        """Inject the RiskCenter revision repository."""

        self._repository = repository

    def execute(
        self,
        *,
        account_id: int,
        as_of: datetime,
        current_source: M1RiskSourceSnapshot,
    ) -> M1RiskPolicyQualification:
        """Return unknown when active revisions overlap or any source is unresolved."""

        try:
            revisions = self._repository.list_revisions(account_id=account_id)
        except M1RiskPolicySourceCorruptError:
            return M1RiskPolicyQualification(
                state=RiskQualificationState.UNKNOWN,
                reason_codes=("M1_RISK_POLICY_VERSION_SOURCE_CORRUPT",),
                revision=None,
            )
        matching = tuple(
            revision
            for revision in revisions
            if revision.effective_from <= as_of < revision.effective_until
            and not (
                revision.revocation_state == "revoked"
                and revision.revoked_at is not None
                and as_of >= revision.revoked_at
            )
        )
        if len(matching) > 1:
            return M1RiskPolicyQualification(
                state=RiskQualificationState.UNKNOWN,
                reason_codes=("M1_RISK_POLICY_ACTIVE_REVISION_AMBIGUOUS",),
                revision=None,
            )
        if len(matching) == 1:
            return qualify_revision(
                revision=matching[0],
                account_id=account_id,
                as_of=as_of,
                current_source=current_source,
            )
        if not revisions:
            return qualify_revision(
                revision=None,
                account_id=account_id,
                as_of=as_of,
                current_source=current_source,
            )
        latest = max(revisions, key=lambda revision: revision.known_at)
        return qualify_revision(
            revision=latest,
            account_id=account_id,
            as_of=as_of,
            current_source=current_source,
        )


class RevokeM1RiskPolicyRevisionUseCase:
    """Append a real audit event that immediately invalidates a policy version."""

    def __init__(self, repository: M1RiskPolicyRevisionRepository) -> None:
        """Inject the same immutable revision/audit repository."""

        self._repository = repository

    def execute(
        self,
        *,
        account_id: int,
        risk_policy_version: str,
        actor_user_id: int,
        reason: str,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Require a real actor and non-empty reason before appending revocation."""

        if type(account_id) is not int or account_id <= 0:
            raise M1RiskPolicyValidationError(("M1_RISK_POLICY_ACCOUNT_INVALID",))
        if type(actor_user_id) is not int or actor_user_id <= 0:
            raise M1RiskPolicyValidationError(("M1_RISK_POLICY_ACTOR_INVALID",))
        if type(risk_policy_version) is not str or not risk_policy_version.strip():
            raise M1RiskPolicyValidationError(("M1_RISK_POLICY_VERSION_REQUIRED",))
        if type(reason) is not str or not reason.strip():
            raise M1RiskPolicyValidationError(("M1_RISK_POLICY_REVOCATION_REASON_REQUIRED",))
        _validate_idempotency_scope(
            context=idempotency,
            account_id=account_id,
            actor_user_id=actor_user_id,
            operation="revoke",
        )
        return self._repository.revoke_revision(
            account_id=account_id,
            risk_policy_version=risk_policy_version,
            actor_user_id=actor_user_id,
            reason=reason.strip(),
            idempotency=idempotency,
        )


@dataclass(frozen=True, slots=True)
class M1RiskPolicyApplication:
    """Public RiskCenter operations for consumers and owner interfaces."""

    publish: PublishM1RiskPolicyRevisionUseCase
    qualify: GetM1RiskPolicyQualificationUseCase
    revoke: RevokeM1RiskPolicyRevisionUseCase


class M1RiskPolicyApplicationFactory(Protocol):
    """Factory contract consumed by SimulatedTrading composition roots."""

    def __call__(self) -> M1RiskPolicyApplication:
        """Return public use cases backed by the configured RiskCenter repository."""
        ...


def _validate_idempotency_scope(
    *,
    context: M1RiskPolicyIdempotencyContext,
    account_id: int,
    actor_user_id: int,
    operation: M1RiskPolicyOperation,
) -> None:
    """Keep transport identity bound to the actual application command scope."""

    if (
        context.account_id != account_id
        or context.actor_user_id != actor_user_id
        or context.operation != operation
    ):
        raise M1RiskPolicyValidationError(("M1_RISK_POLICY_IDEMPOTENCY_SCOPE_MISMATCH",))


__all__: tuple[str, ...] = (
    "GetM1RiskPolicyQualificationUseCase",
    "M1RiskPolicyApplication",
    "M1RiskPolicyApplicationFactory",
    "M1RiskPolicyIdempotencyContext",
    "M1RiskPolicyPublishCommand",
    "M1RiskPolicyQualification",
    "M1RiskPolicyRevision",
    "M1RiskSourceSnapshot",
    "M1RiskPolicyIdempotencyConflictError",
    "M1RiskPolicyOperation",
    "M1RiskPolicyRevisionRepository",
    "M1RiskPolicyAlreadyRevokedError",
    "M1RiskPolicyNotFoundError",
    "M1RiskPolicySourceCorruptError",
    "M1RiskPolicyValidationError",
    "PublishM1RiskPolicyRevisionUseCase",
    "RevokeM1RiskPolicyRevisionUseCase",
)
