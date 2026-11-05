"""Django persistence adapter for immutable plan revisions in the existing plan table."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from hmac import compare_digest
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.application.transition_plan_inactive_approval import (
    ExactTransitionPlanDefinitionProvider,
    TransitionPlanDefinition,
)
from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanCurrentPolicyPinsValidator,
    TransitionPlanRevision,
    TransitionPlanRevisionBlocked,
    TransitionPlanRevisionConflict,
    TransitionPlanRevisionCorruption,
    derive_transition_plan_review_artifact_identity,
)
from apps.portfolio.domain.transition_plan_integrity import (
    canonical_transition_plan_payload_v1,
    transition_plan_content_hash_v1,
)
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderExecutionBinding,
    TransitionPlanRevisionIdentity,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)
from apps.portfolio.infrastructure.transition_plan_revision_codec import (
    TransitionPlanRevisionCodecError,
    decode_transition_plan_revision,
    encode_transition_plan_revision,
)
from core.exceptions import BusinessLogicError
from core.integration.research_integrity_registry import get_decision_snapshot
from core.integration.transition_plan_contracts import (
    CANONICAL_TRANSITION_PLAN_FAMILY,
    PORTFOLIO_PLAN_REVISION_FAMILY,
    PORTFOLIO_PLAN_REVISION_MARKER,
)

_REVISION_KEY = PORTFOLIO_PLAN_REVISION_MARKER
_REVISION_FAMILIES = (PORTFOLIO_PLAN_REVISION_FAMILY, CANONICAL_TRANSITION_PLAN_FAMILY)


class DjangoTransitionPlanRevisionRepository:
    """Persist and verify immutable revisions without adding another ledger or table."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind this repository to one explicitly configured database alias."""

        if type(using) is not str or not using.strip():
            raise ValueError("using must be a non-empty database alias")
        self._using = using

    def now(self) -> datetime:
        """Return Django's actual aware persistence time."""

        value = timezone.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TransitionPlanRevisionCorruption("Portfolio repository clock is naive")
        return value

    def get_exact(
        self,
        *,
        plan_id: str,
        version: int,
        expected_revision_hash: str,
        as_of: datetime,
    ) -> TransitionPlanRevision | None:
        """Return exact historical content, including expired or superseded revisions."""

        _require_aware(as_of, "as_of")
        row = self._manager().filter(plan_id=plan_id, plan_version=version).first()
        if row is None or row.created_at > as_of:
            return None
        revision = self._revision_from_row(row)
        if revision is None:
            return None
        if not compare_digest(revision.identity.revision_hash, expected_revision_hash):
            raise TransitionPlanRevisionCorruption(
                "exact revision hash does not match persisted content"
            )
        return revision

    def get_revision_by_id(
        self, *, plan_id: str, version: int, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Read one internally verified exact revision for existing staff approval adapters."""

        _require_aware(as_of, "as_of")
        row = self._manager().filter(plan_id=plan_id, plan_version=version).first()
        if row is None or row.created_at > as_of:
            return None
        return self._revision_from_row(row)

    def get_by_idempotency_key(
        self, *, idempotency_key: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Return the original first winner even if its evidence or plan later expired."""

        _require_aware(as_of, "as_of")
        row = self._manager().filter(idempotency_key=idempotency_key).first()
        if row is None or row.created_at > as_of:
            return None
        return self._revision_from_row(row)

    def list_for_account(
        self, *, account_id: int, as_of: datetime, limit: int
    ) -> tuple[TransitionPlanRevision, ...]:
        """Return verified source-bound history; do not filter out expired revisions."""

        _require_positive_id(account_id, "account_id")
        _require_aware(as_of, "as_of")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be within [1, 100]")
        rows = (
            self._manager()
            .filter(
                account_id=str(account_id),
                plan_contract_family__in=_REVISION_FAMILIES,
                created_at__lte=as_of,
            )
            .order_by("-created_at", "plan_id")
        )
        values: list[TransitionPlanRevision] = []
        for row in rows:
            revision = self._revision_from_row(row)
            if revision is not None:
                values.append(revision)
                if len(values) == limit:
                    break
        return tuple(values)

    def get_family_head(
        self, *, account_id: int, family_id: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Return the verified maximum version for one account-scoped plan family."""

        _require_positive_id(account_id, "account_id")
        _require_token(family_id, "family_id")
        _require_aware(as_of, "as_of")
        matches = tuple(
            revision
            for revision in self._account_revisions(account_id, as_of=as_of)
            if revision.identity.family_id == family_id
        )
        if not matches:
            return None
        highest = max(item.identity.version for item in matches)
        winners = tuple(item for item in matches if item.identity.version == highest)
        if len(winners) != 1:
            raise TransitionPlanRevisionCorruption("plan family has ambiguous highest version")
        return winners[0]

    def append_initial(
        self, revision: TransitionPlanRevision, *, idempotency_key: str
    ) -> TransitionPlanRevision:
        """Insert one initial revision or return an identical idempotent first winner."""

        _validate_insert(revision, idempotency_key, parent=None)
        try:
            with transaction.atomic(using=self._using):
                existing = self._find_insert_winner(revision, idempotency_key)
                if existing is not None:
                    return existing
                self._verify_required_decision_snapshot(revision)
                self._manager().create(**self._model_values(revision, idempotency_key))
                return revision
        except IntegrityError:
            winner = self._find_insert_winner(revision, idempotency_key)
            if winner is not None:
                return winner
            raise TransitionPlanRevisionConflict(
                "concurrent initial revision insert has no exact idempotent winner"
            ) from None

    def append_successor(
        self,
        revision: TransitionPlanRevision,
        *,
        expected_parent: TransitionPlanRevisionIdentity,
        idempotency_key: str,
    ) -> TransitionPlanRevision:
        """Atomically compare-and-set the exact family head and insert one successor."""

        _validate_insert(revision, idempotency_key, parent=expected_parent)
        try:
            with transaction.atomic(using=self._using):
                replay = self._find_insert_winner(revision, idempotency_key)
                if replay is not None:
                    return replay
                locked = self._locked_account_revisions(revision.identity.account_id)
                parent = next(
                    (
                        item
                        for item in locked
                        if item.identity.plan_id == expected_parent.plan_id
                        and item.identity.version == expected_parent.version
                    ),
                    None,
                )
                if parent is None or parent.identity.revision_hash != expected_parent.revision_hash:
                    raise TransitionPlanRevisionConflict(
                        "successor parent is unavailable or changed"
                    )
                family = tuple(
                    item for item in locked if item.identity.family_id == expected_parent.family_id
                )
                if (
                    not family
                    or max(item.identity.version for item in family) != expected_parent.version
                ):
                    raise TransitionPlanRevisionConflict(
                        "a competing successor already advanced the family"
                    )
                if any(item.identity.parent_plan_id == expected_parent.plan_id for item in family):
                    raise TransitionPlanRevisionConflict(
                        "the exact parent already has a child revision"
                    )
                self._verify_required_decision_snapshot(revision)
                self._manager().create(**self._model_values(revision, idempotency_key))
                return revision
        except IntegrityError:
            winner = self._find_insert_winner(revision, idempotency_key)
            if winner is not None:
                return winner
            raise TransitionPlanRevisionConflict(
                "concurrent successor insert has no exact first winner"
            ) from None

    def submit_for_review(
        self,
        *,
        revision: TransitionPlanRevision,
        owner_user_id: int,
        review_subject_id: str,
        requested_at: datetime,
    ) -> TransitionPlanRevision:
        """Set existing plan status and approval request reference under a family lock."""

        _require_aware(requested_at, "requested_at")
        _require_positive_id(owner_user_id, "owner_user_id")
        _require_token(review_subject_id, "review_subject_id")
        with transaction.atomic(using=self._using):
            locked = self._locked_account_revisions(revision.identity.account_id)
            current = next(
                (
                    item
                    for item in locked
                    if item.identity.plan_id == revision.identity.plan_id
                    and item.identity.version == revision.identity.version
                ),
                None,
            )
            if current is None or current.identity.revision_hash != revision.identity.revision_hash:
                raise TransitionPlanRevisionConflict(
                    "review target is no longer the exact persisted revision"
                )
            if current.identity.owner_user_id != owner_user_id:
                raise TransitionPlanRevisionConflict("review requester does not own this plan")
            family = tuple(
                item for item in locked if item.identity.family_id == revision.identity.family_id
            )
            if (
                not family
                or max(item.identity.version for item in family) != revision.identity.version
            ):
                raise TransitionPlanRevisionConflict(
                    "only the current family revision may enter review"
                )
            row = (
                self._manager()
                .select_for_update()
                .get(
                    plan_id=revision.identity.plan_id,
                    plan_version=revision.identity.version,
                )
            )
            if row.status == "APPROVAL_PENDING":
                if row.approval_request_id != review_subject_id:
                    raise TransitionPlanRevisionConflict("review request has another first winner")
                return current
            if row.status not in {"DRAFT", "READY_FOR_APPROVAL"}:
                raise TransitionPlanRevisionConflict("plan status cannot enter staff review")
            if row.expires_at is None or row.expires_at <= requested_at:
                raise BusinessLogicError(
                    message="expired plan revisions cannot enter staff review",
                    code="TRANSITION_PLAN_REVISION_EXPIRED",
                )
            row.status = "APPROVAL_PENDING"
            row.approval_request_id = review_subject_id
            row.save(update_fields=["status", "approval_request_id", "updated_at"])
            refreshed = self._revision_from_row(row)
            if refreshed is None:
                raise TransitionPlanRevisionCorruption("review update lost its revision payload")
            return refreshed

    def _find_insert_winner(
        self, revision: TransitionPlanRevision, idempotency_key: str
    ) -> TransitionPlanRevision | None:
        """Resolve unique-key races only when both identities name the same winner."""

        row_by_key = (
            self._manager().select_for_update().filter(idempotency_key=idempotency_key).first()
        )
        row_by_plan = (
            self._manager().select_for_update().filter(plan_id=revision.identity.plan_id).first()
        )
        if row_by_key is not None and row_by_plan is not None and row_by_key.pk != row_by_plan.pk:
            raise TransitionPlanRevisionConflict(
                "plan ID and idempotency key identify different rows"
            )
        row = row_by_key or row_by_plan
        if row is None:
            return None
        winner = self._revision_from_row(row)
        if (
            winner is None
            or row.idempotency_key != idempotency_key
            or not _same_revision(winner, revision)
        ):
            raise TransitionPlanRevisionConflict("revision idempotency first winner differs")
        return winner

    def _locked_account_revisions(self, account_id: int) -> tuple[TransitionPlanRevision, ...]:
        """Lock exact account plan rows in stable order before family compare-and-set."""

        rows = (
            self._manager()
            .select_for_update()
            .filter(
                account_id=str(account_id),
                plan_contract_family__in=_REVISION_FAMILIES,
            )
            .order_by("plan_id")
        )
        values: list[TransitionPlanRevision] = []
        for row in rows:
            revision = self._revision_from_row(row)
            if revision is not None:
                values.append(revision)
        return tuple(values)

    def _account_revisions(
        self, account_id: int, *, as_of: datetime
    ) -> tuple[TransitionPlanRevision, ...]:
        """Read and verify source-bound rows for a single account."""

        rows = (
            self._manager()
            .filter(
                account_id=str(account_id),
                plan_contract_family__in=_REVISION_FAMILIES,
                created_at__lte=as_of,
            )
            .order_by("plan_id")
        )
        return tuple(
            revision for row in rows if (revision := self._revision_from_row(row)) is not None
        )

    def _revision_from_row(
        self, row: PortfolioTransitionPlanModel
    ) -> TransitionPlanRevision | None:
        """Decode new-family rows or pre-discriminator marked rows with full verification."""

        try:
            risk_contract = _json_object(row.risk_contract, "risk_contract")
            is_revision_family = row.plan_contract_family == PORTFOLIO_PLAN_REVISION_FAMILY
            is_marked_legacy_revision = (
                row.plan_contract_family == CANONICAL_TRANSITION_PLAN_FAMILY
                and _REVISION_KEY in risk_contract
            )
            if not is_revision_family and not is_marked_legacy_revision:
                return None
            if _REVISION_KEY not in risk_contract:
                raise TransitionPlanRevisionCodecError(
                    "revision-family row is missing its revision marker"
                )
            wrapper = risk_contract.get(_REVISION_KEY)
            if wrapper is None:
                raise TransitionPlanRevisionCodecError("revision marker has no payload")
            revision = decode_transition_plan_revision(
                wrapper,
                current_status=str(row.status),
                idempotency_key=str(row.idempotency_key or ""),
            )
            self._verify_row_matches_revision(row, risk_contract, revision)
            return revision
        except TransitionPlanRevisionCodecError as error:
            raise TransitionPlanRevisionCorruption(
                "stored plan revision payload is invalid"
            ) from error
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            raise TransitionPlanRevisionCorruption("stored plan revision is corrupt") from error

    @staticmethod
    def _verify_row_matches_revision(
        row: PortfolioTransitionPlanModel,
        risk_contract: Mapping[str, object],
        revision: TransitionPlanRevision,
    ) -> None:
        """Verify every legacy column consumed by canonical-v1 readers."""

        plan = revision.plan
        identity = revision.identity
        if row.plan_contract_family not in _REVISION_FAMILIES or _REVISION_KEY not in risk_contract:
            raise TransitionPlanRevisionCorruption("revision row family or marker is invalid")
        if (
            row.plan_id != identity.plan_id
            or row.plan_version != identity.version
            or row.account_id != str(identity.account_id)
            or str(row.idempotency_key or "") != plan.idempotency_key
            or row.decision_snapshot_id != plan.decision_snapshot_id
            or row.portfolio_snapshot_id != plan.portfolio_snapshot_id
            or row.target_portfolio_id != plan.target_portfolio_id
            or row.as_of != plan.as_of_time
            or row.expires_at != plan.expires_at
            or row.immutable_payload_hash != identity.transition_plan_hash
        ):
            raise TransitionPlanRevisionCorruption(
                "canonical plan columns differ from revision JSON"
            )
        if not compare_digest(
            transition_plan_content_hash_v1(plan), str(row.immutable_payload_hash or "")
        ):
            raise TransitionPlanRevisionCorruption("canonical-v1 plan hash is invalid")
        canonical = canonical_transition_plan_payload_v1(plan)
        if _canonical_hash({"value": risk_contract.get("constraints")}) != _canonical_hash(
            {"value": canonical["constraints"]}
        ):
            raise TransitionPlanRevisionCorruption("legacy risk constraints differ from plan bytes")
        if risk_contract.get("planning_policy_version") != plan.metadata.get(
            "planning_policy_version"
        ):
            raise TransitionPlanRevisionCorruption("legacy policy marker differs from plan bytes")
        if _canonical_hash({"value": row.orders}) != _canonical_hash(
            {"value": canonical["orders"]}
        ):
            raise TransitionPlanRevisionCorruption(
                "legacy order rows differ from canonical-v1 plan"
            )
        if _canonical_hash({"value": row.current_positions_snapshot}) != _canonical_hash(
            {"value": revision.basis.to_payload()["current_positions"]}
        ):
            raise TransitionPlanRevisionCorruption(
                "stored current positions differ from the revision basis"
            )
        if _canonical_hash({"value": row.target_positions_snapshot}) != _canonical_hash(
            {"value": revision.basis.to_payload()["target_positions"]}
        ):
            raise TransitionPlanRevisionCorruption(
                "stored target positions differ from the revision basis"
            )
        summary = _json_object(row.summary, "summary")
        if summary.get("cash_before") != str(plan.cash_before) or summary.get("cash_after") != str(
            plan.cash_after
        ):
            raise TransitionPlanRevisionCorruption(
                "stored cash summary differs from canonical-v1 plan"
            )

    def _model_values(
        self, revision: TransitionPlanRevision, idempotency_key: str
    ) -> dict[str, object]:
        """Map one validated revision into existing canonical transition-plan columns."""

        plan = revision.plan
        basis = revision.basis
        risk_contract: dict[str, object] = {
            "constraints": [item.__dict__ for item in plan.constraints],
            "planning_policy_version": plan.metadata["planning_policy_version"],
            _REVISION_KEY: encode_transition_plan_revision(
                revision,
                idempotency_key=idempotency_key,
            ),
        }
        return {
            "plan_id": revision.identity.plan_id,
            "plan_contract_family": PortfolioTransitionPlanModel.CONTRACT_FAMILY_REVISION,
            "account_id": str(basis.account_id),
            "source_recommendation_ids": [],
            "current_positions_snapshot": [item.to_payload() for item in basis.current_positions],
            "target_positions_snapshot": [item.to_payload() for item in basis.target_positions],
            "orders": canonical_transition_plan_payload_v1(plan)["orders"],
            "risk_contract": risk_contract,
            "summary": {
                "cash_before": str(plan.cash_before),
                "cash_after": str(plan.cash_after),
            },
            "status": plan.status,
            "approval_request_id": "",
            "idempotency_key": idempotency_key,
            "decision_snapshot_id": plan.decision_snapshot_id,
            "portfolio_snapshot_id": plan.portfolio_snapshot_id,
            "target_portfolio_id": plan.target_portfolio_id,
            "expires_at": plan.expires_at,
            "immutable_payload_hash": revision.identity.transition_plan_hash,
            "plan_version": revision.identity.version,
            "as_of": plan.as_of_time,
        }

    def _verify_required_decision_snapshot(self, revision: TransitionPlanRevision) -> None:
        """Preserve the existing mandatory research-snapshot verification gate."""

        if not bool(getattr(settings, "DECISION_SNAPSHOT_REQUIRED", False)):
            return
        snapshot = get_decision_snapshot(revision.plan.decision_snapshot_id)
        if snapshot is None:
            raise BusinessLogicError(
                message="required decision input snapshot is missing",
                code="TRANSITION_PLAN_DECISION_SNAPSHOT_MISSING",
            )
        try:
            snapshot.verify()
        except (TypeError, ValueError, AttributeError) as error:
            raise BusinessLogicError(
                message="required decision input snapshot failed verification",
                code="TRANSITION_PLAN_DECISION_SNAPSHOT_INVALID",
            ) from error

    def _manager(self) -> Any:
        """Return the selected model manager at the explicitly bound alias."""

        return PortfolioTransitionPlanModel._default_manager.using(self._using)


class DjangoTransitionPlanLockedActionGuard:
    """Bind a manual Owner order to its exact active plan while the account is locked."""

    def __init__(
        self,
        *,
        using: str = "default",
        current_policy_pins_validator: TransitionPlanCurrentPolicyPinsValidator | None = None,
    ) -> None:
        """Require current policy pins; the ordinary Owner order chain checks cash and live risk."""

        self._using = using
        self._repository = DjangoTransitionPlanRevisionRepository(using=using)
        self._approval_repository = DjangoTransitionPlanInactiveApprovalRepository(using=using)
        self._current_policy_pins_validator = current_policy_pins_validator

    def validate_locked_action(
        self,
        *,
        binding: TransitionPlanOrderExecutionBinding,
        account_id: int,
        owner_user_id: int,
        as_of: datetime,
    ) -> TransitionPlanRevision:
        """Return exact current manual context without treating an inactive receipt as authority."""

        _require_aware(as_of, "as_of")
        _require_positive_id(account_id, "account_id")
        _require_positive_id(owner_user_id, "owner_user_id")
        if type(binding) is not TransitionPlanOrderExecutionBinding:
            raise TransitionPlanRevisionCorruption("transition action binding type is invalid")
        if binding.account_id != account_id or binding.owner_user_id != owner_user_id:
            raise TransitionPlanRevisionBlocked("transition plan owner or account scope changed")
        with transaction.atomic(using=self._using):
            locked = self._repository._locked_account_revisions(account_id)
            revision = next(
                (
                    item
                    for item in locked
                    if item.identity.plan_id == binding.plan_id
                    and item.identity.version == binding.plan_version
                ),
                None,
            )
            if revision is None:
                raise TransitionPlanRevisionBlocked("exact plan revision is unavailable")
            self._verify_action_binding(revision, binding, account_id, owner_user_id, as_of)
            family = tuple(
                item for item in locked if item.identity.family_id == revision.identity.family_id
            )
            versions = tuple(item.identity.version for item in family)
            if len(versions) != len(set(versions)):
                raise TransitionPlanRevisionCorruption("plan family has duplicate version rows")
            head = max(family, key=lambda item: item.identity.version)
            if head.identity.revision_hash != revision.identity.revision_hash:
                raise TransitionPlanRevisionBlocked("a successor revision superseded this plan")
            if revision.plan.status not in {
                "DRAFT",
                "READY_FOR_APPROVAL",
                "APPROVAL_PENDING",
                "APPROVED",
            }:
                raise TransitionPlanRevisionBlocked(
                    "the exact plan revision is not available for Owner review"
                )
            if as_of >= revision.identity.valid_until:
                raise TransitionPlanRevisionBlocked("the exact plan revision has expired")
            if self._current_policy_pins_validator is None:
                raise TransitionPlanRevisionBlocked(
                    "current plan-policy revalidation is unavailable"
                )
            self._verify_optional_inactive_review_artifact(
                revision, account_id=account_id, as_of=as_of
            )
            self._current_policy_pins_validator.validate_current_policy_pins(revision, as_of=as_of)
            return revision

    def _verify_action_binding(
        self,
        revision: TransitionPlanRevision,
        binding: TransitionPlanOrderExecutionBinding,
        account_id: int,
        owner_user_id: int,
        as_of: datetime,
    ) -> None:
        """Compare every action identity and approved term with its immutable order row."""

        identity = revision.identity
        if (
            identity.account_id != account_id
            or identity.owner_user_id != owner_user_id
            or identity.plan_id != binding.plan_id
            or identity.family_id != binding.family_id
            or identity.root_plan_id != binding.root_plan_id
            or identity.version != binding.plan_version
            or identity.revision_hash != binding.revision_hash
            or identity.valid_until != binding.plan_expires_at
            or as_of >= identity.valid_until
        ):
            raise TransitionPlanRevisionBlocked(
                "plan revision identity, ownership or validity changed"
            )
        if not 0 <= binding.order_ordinal < len(revision.orders):
            raise TransitionPlanRevisionCorruption("plan order ordinal is unavailable")
        order = revision.orders[binding.order_ordinal]
        if (
            order.ordinal != binding.order_ordinal
            or order.plan_order_binding_id != binding.plan_order_binding_id
            or order.order_content_hash != binding.order_content_hash
            or order.asset_code != binding.asset_code
            or order.security_id != binding.security_id
            or order.side != binding.side
            or order.approved_quantity != binding.approved_quantity
            or order.approved_limit_price != binding.approved_limit_price
            or order.quantity_unit != binding.quantity_unit
            or order.money_unit != binding.money_unit
        ):
            raise TransitionPlanRevisionCorruption(
                "transition order binding differs from the exact revision"
            )
        if (
            order.asset_type != binding.asset_type
            or order.classification_content_hash != binding.classification_content_hash
        ):
            raise TransitionPlanRevisionCorruption(
                "transition order classification differs from the exact revision"
            )
        if order.approved_quantity <= 0 or order.status in {"blocked", "conditional", "unknown"}:
            raise TransitionPlanRevisionBlocked("plan order has no approved actionable quantity")

    def _verify_optional_inactive_review_artifact(
        self, revision: TransitionPlanRevision, *, account_id: int, as_of: datetime
    ) -> None:
        """Check an existing staff artifact's exact binding without granting execution authority."""

        artifact_identity = derive_transition_plan_review_artifact_identity(revision)
        row = (
            self._repository._manager()
            .select_for_update()
            .filter(
                plan_id=revision.identity.plan_id,
                plan_version=revision.identity.version,
            )
            .first()
        )
        if row is None:
            raise TransitionPlanRevisionCorruption(
                "exact plan row disappeared while its revision was locked"
            )
        if row.approval_request_id not in {"", artifact_identity.subject_id}:
            raise TransitionPlanRevisionCorruption("plan review request points at another artifact")
        subject = self._approval_repository.get_subject_winner(
            subject_id=artifact_identity.subject_id,
            subject_version=artifact_identity.subject_version,
            as_of=as_of,
        )
        receipt = self._approval_repository.get_receipt_winner(
            receipt_id=artifact_identity.receipt_id,
            receipt_version=artifact_identity.receipt_version,
            as_of=as_of,
        )
        if subject is None and receipt is None:
            return
        if subject is None:
            raise TransitionPlanRevisionCorruption(
                "inactive receipt exists without its exact subject"
            )
        if (
            subject.subject_id != artifact_identity.subject_id
            or subject.subject_version != artifact_identity.subject_version
            or subject.plan_id != revision.identity.plan_id
            or subject.plan_version != revision.identity.version
            or subject.plan_content_hash != revision.identity.transition_plan_hash
            or subject.account_id != str(account_id)
            or subject.decision_snapshot_id != revision.plan.decision_snapshot_id
            or subject.requested_at > as_of
        ):
            raise TransitionPlanRevisionCorruption(
                "staff review subject does not bind the exact revision"
            )
        if subject.requested_by.is_staff is not True:
            raise TransitionPlanRevisionCorruption(
                "inactive review subject is not registered by staff"
            )
        if receipt is None:
            return
        if (
            receipt.receipt_id != artifact_identity.receipt_id
            or receipt.receipt_version != artifact_identity.receipt_version
            or receipt.subject_id != subject.subject_id
            or receipt.subject_version != subject.subject_version
            or receipt.subject_content_hash != subject.content_hash
            or receipt.plan_id != revision.identity.plan_id
            or receipt.plan_version != revision.identity.version
            or receipt.plan_content_hash != revision.identity.transition_plan_hash
            or receipt.account_id != str(account_id)
            or receipt.decision_snapshot_id != revision.plan.decision_snapshot_id
            or receipt.requested_by != subject.requested_by
            or receipt.issued_at < subject.requested_at
            or receipt.issued_at > as_of
            or receipt.execution_permission != "inactive"
            or not receipt.must_not_execute
        ):
            raise TransitionPlanRevisionCorruption(
                "inactive receipt does not bind the exact revision"
            )
        if (
            subject.requested_by.is_staff is not True
            or receipt.approved_by.is_staff is not True
            or subject.requested_by.user_id == receipt.approved_by.user_id
            or subject.requested_by.actor_id == receipt.approved_by.actor_id
        ):
            raise TransitionPlanRevisionCorruption(
                "inactive receipt lacks two distinct staff actors"
            )


def _same_revision(left: TransitionPlanRevision, right: TransitionPlanRevision) -> bool:
    """Compare immutable identities while ignoring mutable lifecycle status."""

    return (
        left.identity == right.identity
        and left.basis == right.basis
        and left.orders == right.orders
        and transition_plan_content_hash_v1(left.plan)
        == transition_plan_content_hash_v1(right.plan)
    )


def _validate_insert(
    revision: TransitionPlanRevision,
    idempotency_key: str,
    *,
    parent: TransitionPlanRevisionIdentity | None,
) -> None:
    """Reject invalid key, identity, or lineage before touching the database."""

    if type(revision) is not TransitionPlanRevision:
        raise TypeError("revision must be an exact TransitionPlanRevision")
    if type(idempotency_key) is not str or not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("idempotency_key must be a bounded non-empty string")
    if revision.plan.idempotency_key != idempotency_key:
        raise TransitionPlanRevisionConflict("plan and repository idempotency keys differ")
    if parent is None:
        if revision.identity.parent_plan_id is not None or revision.identity.version != 1:
            raise TransitionPlanRevisionConflict("initial insert carries successor lineage")
    elif (
        revision.identity.parent_plan_id != parent.plan_id
        or revision.identity.parent_version != parent.version
        or revision.identity.parent_revision_hash != parent.revision_hash
        or revision.identity.version != parent.version + 1
        or revision.identity.family_id != parent.family_id
        or revision.identity.root_plan_id != parent.root_plan_id
        or revision.identity.account_id != parent.account_id
        or revision.identity.owner_user_id != parent.owner_user_id
    ):
        raise TransitionPlanRevisionConflict(
            "successor insert does not match its exact parent identity"
        )


def _json_object(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow one Django JSONField boundary to a string-keyed object."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TransitionPlanRevisionCorruption(f"stored {field_name} must be an object")
    return dict(value)


def _require_token(value: object, field_name: str) -> None:
    """Validate a bounded non-whitespace identity from public inputs."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 192:
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_positive_id(value: object, field_name: str) -> None:
    """Require a positive exact integer account or user id."""

    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_aware(value: object, field_name: str) -> None:
    """Reject naive timestamp inputs at repository boundaries."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class DjangoExactTransitionPlanRevisionDefinitionProvider(ExactTransitionPlanDefinitionProvider):
    """Adapt only an internally verified revision to the existing inactive staff workflow."""

    def __init__(self, *, using: str = "default") -> None:
        """Use the same strict revision codec and selected Portfolio plan database."""

        self._repository = DjangoTransitionPlanRevisionRepository(using=using)

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        """Return an approved live plan only after validating its full stored revision hash."""

        revision = self._repository.get_revision_by_id(
            plan_id=plan_id,
            version=plan_version,
            as_of=as_of,
        )
        if (
            revision is None
            or revision.plan.status != "APPROVED"
            or not revision.identity.recorded_at <= as_of < revision.identity.valid_until
        ):
            return None
        return TransitionPlanDefinition(
            plan=revision.plan,
            content_hash=revision.identity.transition_plan_hash,
            recorded_at=revision.identity.recorded_at,
        )


__all__ = [
    "DjangoExactTransitionPlanRevisionDefinitionProvider",
    "DjangoTransitionPlanRevisionRepository",
]
