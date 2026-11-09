"""Coordinate owned persistent plans and explicitly confirmed ordinary orders."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from apps.portfolio.application.transition_plan_lifecycle import (
    CreateInitialTransitionPlanRevisionUseCase,
    CreateTransitionPlanSuccessorCommand,
    CreateTransitionPlanSuccessorUseCase,
    GetExactTransitionPlanRevisionQuery,
    GetExactTransitionPlanRevisionUseCase,
    ListTransitionPlanRevisionsQuery,
    ListTransitionPlanRevisionsUseCase,
    RequestTransitionPlanRevisionReview,
    RequestTransitionPlanRevisionReviewUseCase,
    TransitionPlanRevisionAuthorizer,
    TransitionPlanRevisionClock,
    TransitionPlanRevisionPreparationProvider,
    TransitionPlanRevisionRepository,
    TransitionPlanRevisionRequest,
    TransitionPlanRevisionUnavailable,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.risk_center.application.portfolio_risk_serialization import portfolio_risk_content_hash
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
    RebalanceJourneyCommand,
    RebalanceJourneyUnavailable,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from core.exceptions import InvalidInputError

ReferenceBasis = Literal["market", "published_close"]


class JourneyPreparationFactory(Protocol):
    """Build a request-scoped provider using real server readers and user targets."""

    def __call__(
        self, *, target_weights: str, reference_price_basis: ReferenceBasis
    ) -> TransitionPlanRevisionPreparationProvider:
        """Return a provider without obtaining authority from client financial facts."""
        ...


class JourneyPlanProgressReader(Protocol):
    """Project verified ordinary reservation/fill/trade facts without new ledgers."""

    def read(
        self, *, user_id: int, account_id: int, revision: TransitionPlanRevision
    ) -> dict[str, object]:
        """Retain unknown coverage and actual cash rather than estimated sell credit."""
        ...


class JourneyPlanOrderPreviewer(Protocol):
    """Map exact user-selected plan rows into the ordinary signed preview path."""

    def preview(
        self, *, command: RebalanceJourneyCommand, revision: TransitionPlanRevision
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Return display data and its separate private ordinary-order continuation."""
        ...


class RebalanceJourneyApplication:
    """Use existing plan and order owners while keeping full-plan execution disabled."""

    def __init__(
        self,
        *,
        repository: TransitionPlanRevisionRepository,
        authorizer: TransitionPlanRevisionAuthorizer,
        clock: TransitionPlanRevisionClock,
        preparation_factory: JourneyPreparationFactory,
        progress_reader: JourneyPlanProgressReader,
        order_previewer: JourneyPlanOrderPreviewer,
    ) -> None:
        """Inject persistence, account grants and the existing financial operation ports."""

        self._repository = repository
        self._authorizer = authorizer
        self._clock = clock
        self._preparation_factory = preparation_factory
        self._progress_reader = progress_reader
        self._order_previewer = order_previewer

    def execute(self, command: RebalanceJourneyCommand) -> dict[str, object]:
        """Recheck the exact caller scope for every read and explicitly requested action."""

        command.__post_init__()
        if command.action == "list":
            plans = ListTransitionPlanRevisionsUseCase(
                repository=self._repository, authorizer=self._authorizer, clock=self._clock
            ).execute(ListTransitionPlanRevisionsQuery(command.user_id, command.account_id, 20))
            return {
                "success": True,
                "account_id": command.account_id,
                "plans": [plan.to_payload() for plan in plans],
                "review": None,
                "progress": None,
                "capabilities": {"read_only": True, "can_execute_plan": False},
            }
        if command.action == "create":
            if command.target_weights is None:
                raise InvalidInputError(code="REBALANCE_JOURNEY_TARGET_REQUIRED")
            request = self._request(command, command.target_weights, command.reference_price_basis)
            revision = CreateInitialTransitionPlanRevisionUseCase(
                repository=self._repository,
                preparation_provider=self._preparation_factory(
                    target_weights=command.target_weights,
                    reference_price_basis=command.reference_price_basis,
                ),
                authorizer=self._authorizer,
                clock=self._clock,
            ).execute(request)
            return self._envelope(command, revision)

        revision = self._read(command)
        if command.action == "review":
            submission = RequestTransitionPlanRevisionReviewUseCase(
                repository=self._repository, authorizer=self._authorizer, clock=self._clock
            ).execute(
                RequestTransitionPlanRevisionReview(
                    command.user_id,
                    command.account_id,
                    revision.identity.plan_id,
                    revision.identity.version,
                    revision.identity.revision_hash,
                )
            )
            return self._envelope(command, submission.revision)
        if command.action == "successor":
            text = (
                command.target_weights if command.target_weights is not None else _targets(revision)
            )
            # A retained target keeps its declared price lane instead of silently
            # promoting a published reference into another purpose on resume.
            basis = (
                retained_plan_reference_price_basis(revision)
                if command.target_weights is None
                else command.reference_price_basis
            )
            request = self._request(command, text, basis)
            successor = CreateTransitionPlanSuccessorUseCase(
                repository=self._repository,
                preparation_provider=self._preparation_factory(
                    target_weights=text, reference_price_basis=basis
                ),
                authorizer=self._authorizer,
                clock=self._clock,
            ).execute(
                CreateTransitionPlanSuccessorCommand(
                    request,
                    revision.identity.plan_id,
                    revision.identity.version,
                    revision.identity.revision_hash,
                )
            )
            return self._envelope(command, successor)
        result = self._envelope(command, revision)
        if command.action == "preview_order":
            self._authorizer.require_write(
                actor_user_id=command.user_id, account_id=command.account_id
            )
            preview, continuation = self._order_previewer.preview(
                command=command, revision=revision
            )
            result["preview"] = preview
            result["continuation"] = continuation
        return result

    def _read(self, command: RebalanceJourneyCommand) -> TransitionPlanRevision:
        if command.plan_id is None or command.plan_version is None or command.revision_hash is None:
            raise InvalidInputError(code="REBALANCE_JOURNEY_PLAN_REQUIRED")
        revision = GetExactTransitionPlanRevisionUseCase(
            repository=self._repository, authorizer=self._authorizer, clock=self._clock
        ).execute(
            GetExactTransitionPlanRevisionQuery(
                command.user_id,
                command.account_id,
                command.plan_id,
                command.plan_version,
                command.revision_hash,
            )
        )
        if revision is None:
            raise TransitionPlanRevisionUnavailable()
        return revision

    def _request(
        self, command: RebalanceJourneyCommand, text: str, basis: ReferenceBasis
    ) -> TransitionPlanRevisionRequest:
        if command.request_key is None:
            raise InvalidInputError(code="REBALANCE_JOURNEY_REQUEST_KEY_REQUIRED")
        targets = parse_temporary_security_targets(text)
        target_payload: dict[str, object] = {
            "weights": targets.exact_weight_strings(),
            "residual_cash_weight": str(targets.residual_cash_weight),
        }
        return TransitionPlanRevisionRequest(
            actor_user_id=command.user_id,
            account_id=command.account_id,
            target_portfolio_id=portfolio_risk_content_hash(target_payload),
            selection_id=f"temporary_security_targets:{basis}",
            expected_selection_hash=portfolio_risk_content_hash(
                {"target": target_payload, "reference_price_basis": basis}
            ),
            idempotency_key=command.request_key,
        )

    def _envelope(
        self, command: RebalanceJourneyCommand, revision: TransitionPlanRevision
    ) -> dict[str, object]:
        now = self._clock.now()
        head = self._repository.get_family_head(
            account_id=command.account_id, family_id=revision.identity.family_id, as_of=now
        )
        current = (
            head is not None and head.identity.revision_hash == revision.identity.revision_hash
        )
        writable = True
        try:
            self._authorizer.require_write(
                actor_user_id=command.user_id, account_id=command.account_id
            )
        except RebalanceJourneyAccessDenied:
            writable = False
        usable_context = (
            current
            and now < revision.identity.valid_until
            and revision.plan.status
            in {"DRAFT", "READY_FOR_APPROVAL", "APPROVAL_PENDING", "APPROVED"}
        )
        progress = self._progress_reader.read(
            user_id=command.user_id, account_id=command.account_id, revision=revision
        )
        return {
            "success": True,
            "account_id": command.account_id,
            "plan": revision.to_payload(),
            "review": {
                "status": revision.plan.status,
                "staff_approval_is_execution_authority": False,
                "must_not_execute": True,
            },
            "progress": progress,
            "capabilities": {
                "can_request_review": writable
                and usable_context
                and revision.plan.status in {"DRAFT", "READY_FOR_APPROVAL"},
                "can_create_successor": writable and current,
                "can_preview_order": writable and usable_context,
                "can_execute_plan": False,
                "automatic_submission": False,
                "read_only": not writable,
                "is_current_family_head": current,
                "expired": now >= revision.identity.valid_until,
            },
        }


def _targets(revision: TransitionPlanRevision) -> str:
    rows: list[str] = []
    for position in revision.basis.target_positions:
        if position.target_weight is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_RETAINED_TARGET_UNKNOWN")
        percent = (position.target_weight * Decimal("100")).normalize()
        rows.append(f"{position.asset_code},{percent:f}")
    if not rows:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_RETAINED_TARGET_UNKNOWN")
    return "\n".join(rows)


def retained_plan_reference_price_basis(revision: TransitionPlanRevision) -> ReferenceBasis:
    """Read the immutable plan's declared lane rather than trusting a resume request."""
    if revision.basis.selection_id == "temporary_security_targets:market":
        return "market"
    if revision.basis.selection_id == "temporary_security_targets:published_close":
        return "published_close"
    raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_RETAINED_PRICE_BASIS_UNKNOWN")
