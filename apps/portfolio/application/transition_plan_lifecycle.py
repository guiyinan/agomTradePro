"""Public application contracts for trusted immutable transition-plan revisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventReviewValidator,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
    has_transition_plan_event_bindings,
)
from apps.portfolio.domain.transition_plan_revision import (
    ObservationPrecision,
    PlanOutcome,
    TransitionPlanBasis,
    TransitionPlanOrderBinding,
    TransitionPlanOrderExecutionBinding,
    TransitionPlanOrderSpecification,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanRevision,
    TransitionPlanRevisionIdentity,
    TransitionPlanRevisionPreparation,
    TransitionPlanRiskBinding,
    TransitionPlanSourceBinding,
    build_transition_plan_revision,
)
from core.exceptions import BusinessLogicError, DuplicateResourceError, ResourceNotFoundError


class TransitionPlanRevisionUnavailable(ResourceNotFoundError):
    """The requested exact plan revision is not visible to this account actor."""

    default_message = "指定计划版本不存在或不可见"
    default_code = "TRANSITION_PLAN_REVISION_UNAVAILABLE"


class TransitionPlanRevisionConflict(DuplicateResourceError):
    """An immutable plan idempotency key or successor first winner conflicts."""

    default_message = "计划版本已发生冲突，请重新读取并生成后继版本"
    default_code = "TRANSITION_PLAN_REVISION_CONFLICT"


class TransitionPlanRevisionBlocked(BusinessLogicError):
    """Trusted inputs are incomplete, stale, or not decision-usable."""

    default_message = "当前账户或来源依据不足，无法保存可信计划"
    default_code = "TRANSITION_PLAN_REVISION_BLOCKED"


class TransitionPlanEventReviewRequired(TransitionPlanRevisionBlocked):
    """A newly available or materially corrected event requires a successor revision."""

    default_message = "公司行为或公告事实已变化，请重新生成后继计划并提交复核"
    default_code = "TRANSITION_PLAN_EVENT_REVIEW_REQUIRED"


class TransitionPlanRevisionCorruption(BusinessLogicError):
    """A stored or supplied plan revision failed its exact binding checks."""

    default_message = "计划版本完整性校验失败"
    default_code = "TRANSITION_PLAN_REVISION_CORRUPTION"


@dataclass(frozen=True, slots=True)
class TransitionPlanRevisionRequest:
    """Client intent only; all balances, positions, prices, and policies are server read."""

    actor_user_id: int
    account_id: int
    target_portfolio_id: str
    selection_id: str
    expected_selection_hash: str
    idempotency_key: str

    def __post_init__(self) -> None:
        """Validate only authenticated identity, chosen target, and expected pins."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be a positive integer")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        for field_name in ("target_portfolio_id", "selection_id", "idempotency_key"):
            _require_request_token(getattr(self, field_name), field_name)
        _require_request_hash(self.expected_selection_hash, "expected_selection_hash")


@dataclass(frozen=True, slots=True)
class CreateTransitionPlanSuccessorCommand:
    """Request a recomputed child while pinning its exact immutable parent."""

    request: TransitionPlanRevisionRequest
    expected_parent_plan_id: str
    expected_parent_version: int
    expected_parent_revision_hash: str

    def __post_init__(self) -> None:
        """Require the complete parent identity; never accept a latest-plan alias."""

        _require_request_token(self.expected_parent_plan_id, "expected_parent_plan_id")
        if type(self.expected_parent_version) is not int or self.expected_parent_version <= 0:
            raise ValueError("expected_parent_version must be positive")
        _require_request_hash(self.expected_parent_revision_hash, "expected_parent_revision_hash")


@dataclass(frozen=True, slots=True)
class GetExactTransitionPlanRevisionQuery:
    """Read one revision only by full identity, never by a latest alias."""

    actor_user_id: int
    account_id: int
    plan_id: str
    version: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        """Require exact account, revision and digest selectors."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        _require_request_token(self.plan_id, "plan_id")
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("version must be positive")
        _require_request_hash(self.expected_revision_hash, "expected_revision_hash")


@dataclass(frozen=True, slots=True)
class ListTransitionPlanRevisionsQuery:
    """Bounded owner-scoped history list request."""

    actor_user_id: int
    account_id: int
    limit: int = 50

    def __post_init__(self) -> None:
        """Reject invalid account scope or unbounded list sizes."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("limit must be within [1, 100]")


class TransitionPlanRevisionClock(Protocol):
    """Inject the actual server clock used for authorization and exact reads."""

    def now(self) -> datetime:
        """Return the current timezone-aware server time."""
        ...


class TransitionPlanRevisionAuthorizer(Protocol):
    """Resolve current account read/write authority without exposing ORM models."""

    def require_read(self, *, actor_user_id: int, account_id: int) -> int:
        """Return the account owner id after enforcing read scope."""
        ...

    def require_write(self, *, actor_user_id: int, account_id: int) -> int:
        """Return the account owner id after enforcing write scope."""
        ...


class TransitionPlanRevisionPreparationProvider(Protocol):
    """Build plan inputs from current server-owned account and evidence sources."""

    def prepare(
        self,
        request: TransitionPlanRevisionRequest,
        *,
        prepared_at: datetime,
        parent: TransitionPlanRevision | None,
    ) -> TransitionPlanRevisionPreparation:
        """Read current context and timestamp its assembly at or after the start."""
        ...


class TransitionPlanCurrentPolicyPinsValidator(Protocol):
    """Recheck only current policy versions, not mutable post-execution account resources."""

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Raise a typed blocked error when a stored risk, fee, rule or calendar pin changed."""
        ...


class TransitionPlanRevisionRepository(Protocol):
    """Persist immutable revision content in the existing Portfolio plan table."""

    def now(self) -> datetime:
        """Return the authoritative Portfolio persistence clock."""
        ...

    def get_exact(
        self,
        *,
        plan_id: str,
        version: int,
        expected_revision_hash: str,
        as_of: datetime,
    ) -> TransitionPlanRevision | None:
        """Return exact history even after expiry; never resolve a newer alias."""
        ...

    def get_by_idempotency_key(
        self, *, idempotency_key: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Return the saved first result without refreshing its source clocks."""
        ...

    def list_for_account(
        self, *, account_id: int, as_of: datetime, limit: int
    ) -> tuple[TransitionPlanRevision, ...]:
        """Return bounded exact revision history for an already-authorized account."""
        ...

    def get_family_head(
        self, *, account_id: int, family_id: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Return the verified highest stored family revision, including expired history."""
        ...

    def append_initial(
        self, revision: TransitionPlanRevision, *, idempotency_key: str
    ) -> TransitionPlanRevision:
        """Insert one first revision or return the exact same idempotent winner."""
        ...

    def append_successor(
        self,
        revision: TransitionPlanRevision,
        *,
        expected_parent: TransitionPlanRevisionIdentity,
        idempotency_key: str,
    ) -> TransitionPlanRevision:
        """Lock the parent and atomically reject a competing family successor."""
        ...

    def submit_for_review(
        self,
        *,
        revision: TransitionPlanRevision,
        owner_user_id: int,
        review_subject_id: str,
        requested_at: datetime,
    ) -> TransitionPlanRevision:
        """Move one exact ready revision to the existing approval-pending lifecycle state."""
        ...


class CreateInitialTransitionPlanRevisionUseCase:
    """Prepare and persist a first immutable revision from trusted server reads."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        preparation_provider: TransitionPlanRevisionPreparationProvider,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
    ) -> None:
        """Inject persistence, server reads, account scope and server time."""

        self._repository = repository
        self._provider = preparation_provider
        self._authorizer = authorizer
        self._clock = clock

    def execute(self, request: TransitionPlanRevisionRequest) -> TransitionPlanRevision:
        """Return an exact idempotent winner or persist a fully qualified first version."""

        owner_user_id = self._authorizer.require_write(
            actor_user_id=request.actor_user_id, account_id=request.account_id
        )
        now = _require_server_time(self._clock.now())
        existing = self._repository.get_by_idempotency_key(
            idempotency_key=request.idempotency_key, as_of=now
        )
        if existing is not None:
            _check_replay(existing, request, owner_user_id, parent=None)
            return existing
        preparation = self._provider.prepare(request, prepared_at=now, parent=None)
        _check_preparation(
            preparation,
            request,
            owner_user_id,
            started_at=now,
            completed_at=_require_server_time(self._clock.now()),
            parent=None,
        )
        return self._repository.append_initial(
            build_transition_plan_revision(preparation),
            idempotency_key=request.idempotency_key,
        )


class CreateTransitionPlanSuccessorUseCase:
    """Recompute a child from fresh facts after exact parent compare-and-set."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        preparation_provider: TransitionPlanRevisionPreparationProvider,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
    ) -> None:
        """Inject the same authoritative readers used by first-plan creation."""

        self._repository = repository
        self._provider = preparation_provider
        self._authorizer = authorizer
        self._clock = clock

    def execute(self, command: CreateTransitionPlanSuccessorCommand) -> TransitionPlanRevision:
        """Require the exact parent winner and persist a newly computed child."""

        request = command.request
        owner_user_id = self._authorizer.require_write(
            actor_user_id=request.actor_user_id, account_id=request.account_id
        )
        now = _require_server_time(self._clock.now())
        existing = self._repository.get_by_idempotency_key(
            idempotency_key=request.idempotency_key, as_of=now
        )
        if existing is not None:
            _check_replay(
                existing,
                request,
                owner_user_id,
                parent=(
                    command.expected_parent_plan_id,
                    command.expected_parent_version,
                    command.expected_parent_revision_hash,
                ),
            )
            return existing
        parent = self._repository.get_exact(
            plan_id=command.expected_parent_plan_id,
            version=command.expected_parent_version,
            expected_revision_hash=command.expected_parent_revision_hash,
            as_of=now,
        )
        if parent is None or parent.identity.account_id != request.account_id:
            raise TransitionPlanRevisionConflict("exact parent revision is missing or changed")
        if parent.identity.owner_user_id != owner_user_id:
            raise TransitionPlanRevisionConflict("successor owner differs from the exact parent")
        head = self._repository.get_family_head(
            account_id=request.account_id,
            family_id=parent.identity.family_id,
            as_of=now,
        )
        if head is None or head.identity.revision_hash != parent.identity.revision_hash:
            raise TransitionPlanRevisionConflict("successor parent is no longer the family head")
        preparation = self._provider.prepare(request, prepared_at=now, parent=parent)
        _check_preparation(
            preparation,
            request,
            owner_user_id,
            started_at=now,
            completed_at=_require_server_time(self._clock.now()),
            parent=parent,
        )
        return self._repository.append_successor(
            build_transition_plan_revision(preparation),
            expected_parent=parent.identity,
            idempotency_key=request.idempotency_key,
        )


class GetExactTransitionPlanRevisionUseCase:
    """Read one plan version by exact ID, version and immutable content hash."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
    ) -> None:
        """Inject exact repository, current account scope and server clock."""

        self._repository = repository
        self._authorizer = authorizer
        self._clock = clock

    def execute(self, query: GetExactTransitionPlanRevisionQuery) -> TransitionPlanRevision | None:
        """Return the pinned revision or ``None`` without resolving a newer version."""

        self._authorizer.require_read(
            actor_user_id=query.actor_user_id, account_id=query.account_id
        )
        return self._repository.get_exact(
            plan_id=query.plan_id,
            version=query.version,
            expected_revision_hash=query.expected_revision_hash,
            as_of=_require_server_time(self._clock.now()),
        )


class ListTransitionPlanRevisionsUseCase:
    """List readable plan revisions with their original validity and status."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
    ) -> None:
        """Inject owner-scope authorizer, bounded repository and server clock."""

        self._repository = repository
        self._authorizer = authorizer
        self._clock = clock

    def execute(
        self, query: ListTransitionPlanRevisionsQuery
    ) -> tuple[TransitionPlanRevision, ...]:
        """Return bounded history only after resolving current read permission."""

        self._authorizer.require_read(
            actor_user_id=query.actor_user_id, account_id=query.account_id
        )
        return self._repository.list_for_account(
            account_id=query.account_id,
            as_of=_require_server_time(self._clock.now()),
            limit=query.limit,
        )


@dataclass(frozen=True, slots=True)
class RequestTransitionPlanRevisionReview:
    """Authenticated Owner request to place an exact plan into staff review."""

    actor_user_id: int
    account_id: int
    plan_id: str
    version: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        """Require exact account and revision selectors from the caller."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        _require_request_token(self.plan_id, "plan_id")
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("version must be positive")
        _require_request_hash(self.expected_revision_hash, "expected_revision_hash")


@dataclass(frozen=True, slots=True)
class TransitionPlanReviewArtifactIdentity:
    """Deterministic IDs linking staff artifacts to one exact full revision hash."""

    subject_id: str
    subject_version: str
    receipt_id: str
    receipt_version: str
    revision_hash: str

    def __post_init__(self) -> None:
        """Require IDs and hash that are stable for one exact full revision."""

        for name in ("subject_id", "subject_version", "receipt_id", "receipt_version"):
            _require_request_token(getattr(self, name), name)
        _require_request_hash(self.revision_hash, "revision_hash")


@dataclass(frozen=True, slots=True)
class TransitionPlanRevisionReviewSubmission:
    """Persisted Owner request awaiting the existing independent staff workflow."""

    revision: TransitionPlanRevision
    artifact_identity: TransitionPlanReviewArtifactIdentity

    def __post_init__(self) -> None:
        """Keep the response bound to the saved pending revision."""

        if self.revision.plan.status != "APPROVAL_PENDING":
            raise ValueError("review submission requires the persisted approval-pending state")
        if self.artifact_identity.revision_hash != self.revision.identity.revision_hash:
            raise ValueError("review artifact is not bound to the returned revision")


class RequestTransitionPlanRevisionReviewUseCase:
    """Submit a current exact plan to the existing approval-pending lifecycle."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
        event_review_validator: TransitionPlanEventReviewValidator | None = None,
    ) -> None:
        """Inject Portfolio persistence, Owner scope and the authoritative clock."""

        self._repository = repository
        self._authorizer = authorizer
        self._clock = clock
        self._event_review_validator = event_review_validator

    def execute(
        self, request: RequestTransitionPlanRevisionReview
    ) -> TransitionPlanRevisionReviewSubmission:
        """Persist only an Owner's review request; do not approve or enable execution."""

        owner_user_id = self._authorizer.require_write(
            actor_user_id=request.actor_user_id, account_id=request.account_id
        )
        now = _require_server_time(self._clock.now())
        revision = self._repository.get_exact(
            plan_id=request.plan_id,
            version=request.version,
            expected_revision_hash=request.expected_revision_hash,
            as_of=now,
        )
        if revision is None:
            raise TransitionPlanRevisionUnavailable("exact plan revision is unavailable")
        if (
            revision.identity.account_id != request.account_id
            or revision.identity.owner_user_id != owner_user_id
        ):
            raise TransitionPlanRevisionUnavailable("exact plan revision is outside Owner scope")
        if now >= revision.identity.valid_until:
            raise TransitionPlanRevisionBlocked("expired plan revisions cannot enter staff review")
        head = self._repository.get_family_head(
            account_id=request.account_id,
            family_id=revision.identity.family_id,
            as_of=now,
        )
        if head is None or head.identity.revision_hash != revision.identity.revision_hash:
            raise TransitionPlanRevisionConflict(
                "only the current family revision can enter review"
            )
        require_transition_plan_event_review_clear(
            revision,
            as_of=now,
            validator=self._event_review_validator,
        )
        artifact_identity = derive_transition_plan_review_artifact_identity(revision)
        persisted = self._repository.submit_for_review(
            revision=revision,
            owner_user_id=owner_user_id,
            review_subject_id=artifact_identity.subject_id,
            requested_at=now,
        )
        return TransitionPlanRevisionReviewSubmission(
            revision=persisted,
            artifact_identity=artifact_identity,
        )


def require_transition_plan_event_review_clear(
    revision: TransitionPlanRevision,
    *,
    as_of: datetime,
    validator: TransitionPlanEventReviewValidator | None,
) -> None:
    """Fail closed for explicitly event-bound plans before review or reservation proceeds."""

    if not has_transition_plan_event_bindings(revision.basis.source_bindings):
        return
    if validator is None:
        raise TransitionPlanRevisionBlocked(
            "event-sensitive plan cannot be revalidated because its source reader is unavailable",
            code="TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE",
        )
    assessment = validator.assess(revision, as_of=as_of)
    if type(assessment) is not TransitionPlanEventReviewAssessment:
        raise TransitionPlanRevisionCorruption("event review validator returned an invalid result")
    if assessment.state is TransitionPlanEventReviewState.REVIEW_REQUIRED:
        raise TransitionPlanEventReviewRequired(
            f"event facts changed ({assessment.reason_code}); create a successor revision"
        )
    if assessment.state is TransitionPlanEventReviewState.BLOCKED:
        raise TransitionPlanRevisionBlocked(
            f"event source coverage is unavailable ({assessment.reason_code})",
            code="TRANSITION_PLAN_EVENT_REVIEW_BLOCKED",
            details={"reason_code": assessment.reason_code},
        )
    if assessment.state is not TransitionPlanEventReviewState.UNCHANGED:
        raise TransitionPlanRevisionBlocked("event review outcome is not decision-usable")


def derive_transition_plan_review_artifact_identity(
    revision: TransitionPlanRevision,
) -> TransitionPlanReviewArtifactIdentity:
    """Derive stable inactive staff-subject and receipt IDs from the full revision."""

    if type(revision) is not TransitionPlanRevision:
        raise TypeError("revision must be an exact TransitionPlanRevision")
    basis = {
        "plan_id": revision.identity.plan_id,
        "version": revision.identity.version,
        "revision_hash": revision.identity.revision_hash,
    }
    subject_id = _review_digest({"artifact": "subject", **basis})
    receipt_id = _review_digest({"artifact": "receipt", **basis})
    version = str(revision.identity.version)
    return TransitionPlanReviewArtifactIdentity(
        subject_id=subject_id,
        subject_version=version,
        receipt_id=receipt_id,
        receipt_version="1",
        revision_hash=revision.identity.revision_hash,
    )


def _review_digest(payload: dict[str, object]) -> str:
    """Hash one deterministic review artifact identity without external IDs."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_server_time(value: datetime) -> datetime:
    """Reject naive clocks before any source-bound lifecycle operation."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TransitionPlanRevisionBlocked("Portfolio server clock must be timezone-aware")
    return value


def _check_preparation(
    preparation: TransitionPlanRevisionPreparation,
    request: TransitionPlanRevisionRequest,
    owner_user_id: int,
    *,
    started_at: datetime,
    completed_at: datetime,
    parent: TransitionPlanRevision | None,
) -> None:
    """Check the authorized request identity and server preparation window."""

    basis = preparation.basis
    if (
        basis.account_id != request.account_id
        or basis.owner_user_id != owner_user_id
        or basis.requested_by_user_id != request.actor_user_id
        or basis.target_portfolio_id != request.target_portfolio_id
        or basis.selection_id != request.selection_id
        or basis.selection_hash != request.expected_selection_hash
        or not started_at <= basis.prepared_at <= completed_at
    ):
        raise TransitionPlanRevisionCorruption(
            "server preparation does not match requested identity"
        )
    if completed_at >= basis.valid_until:
        raise TransitionPlanRevisionConflict("plan expired during server preparation")
    if parent is None:
        if preparation.parent_plan_id is not None or preparation.version != 1:
            raise TransitionPlanRevisionCorruption("initial preparation carries successor lineage")
    else:
        expected = parent.identity
        if (
            preparation.parent_plan_id != expected.plan_id
            or preparation.parent_version != expected.version
            or preparation.parent_revision_hash != expected.revision_hash
            or preparation.version != expected.version + 1
            or preparation.family_id != expected.family_id
            or preparation.root_plan_id != expected.root_plan_id
        ):
            raise TransitionPlanRevisionConflict(
                "prepared successor does not bind the exact parent"
            )


def _check_replay(
    revision: TransitionPlanRevision,
    request: TransitionPlanRevisionRequest,
    owner_user_id: int,
    *,
    parent: tuple[str, int, str] | None,
) -> None:
    """Return only the same actor/request/parent first winner for a reused key."""

    basis = revision.basis
    if (
        revision.identity.account_id != request.account_id
        or revision.identity.owner_user_id != owner_user_id
        or basis.requested_by_user_id != request.actor_user_id
        or basis.target_portfolio_id != request.target_portfolio_id
        or basis.selection_id != request.selection_id
        or basis.selection_hash != request.expected_selection_hash
    ):
        raise TransitionPlanRevisionConflict(
            "idempotency key already identifies another plan request"
        )
    if parent is None:
        if revision.identity.parent_plan_id is not None:
            raise TransitionPlanRevisionConflict("idempotency key identifies a successor plan")
    elif (
        revision.identity.parent_plan_id,
        revision.identity.parent_version,
        revision.identity.parent_revision_hash,
    ) != parent:
        raise TransitionPlanRevisionConflict("idempotency key identifies another parent revision")


def _require_request_token(value: object, field_name: str) -> None:
    """Validate a bounded canonical client intent token."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 128:
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_request_hash(value: object, field_name: str) -> None:
    """Validate the exact digest pin included in a plan request."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


__all__ = [
    "CreateInitialTransitionPlanRevisionUseCase",
    "CreateTransitionPlanSuccessorUseCase",
    "CreateTransitionPlanSuccessorCommand",
    "GetExactTransitionPlanRevisionQuery",
    "GetExactTransitionPlanRevisionUseCase",
    "ListTransitionPlanRevisionsQuery",
    "ListTransitionPlanRevisionsUseCase",
    "ObservationPrecision",
    "PlanOutcome",
    "TransitionPlanBasis",
    "TransitionPlanOrderBinding",
    "TransitionPlanOrderExecutionBinding",
    "TransitionPlanOrderSpecification",
    "TransitionPlanPolicyBinding",
    "TransitionPlanPositionBinding",
    "TransitionPlanRevision",
    "TransitionPlanRevisionAuthorizer",
    "TransitionPlanRevisionClock",
    "TransitionPlanCurrentPolicyPinsValidator",
    "TransitionPlanRevisionConflict",
    "TransitionPlanRevisionPreparationProvider",
    "TransitionPlanRevisionPreparation",
    "TransitionPlanRevisionRepository",
    "TransitionPlanRevisionRequest",
    "TransitionPlanRevisionIdentity",
    "TransitionPlanRevisionUnavailable",
    "RequestTransitionPlanRevisionReview",
    "RequestTransitionPlanRevisionReviewUseCase",
    "TransitionPlanEventReviewRequired",
    "require_transition_plan_event_review_clear",
    "TransitionPlanReviewArtifactIdentity",
    "TransitionPlanRevisionReviewSubmission",
    "derive_transition_plan_review_artifact_identity",
    "TransitionPlanRevisionBlocked",
    "TransitionPlanRevisionCorruption",
    "TransitionPlanRiskBinding",
    "TransitionPlanSourceBinding",
    "build_transition_plan_revision",
]
