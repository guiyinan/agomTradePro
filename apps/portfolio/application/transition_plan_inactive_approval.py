"""ID-only workflow for inactive transition-plan approval receipts."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.portfolio.domain.entities import TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
    transition_plan_content_hash_v1,
    validate_transition_plan_for_approval_receipt,
)

_SUBJECT_SCHEMA = "portfolio-transition-plan-approval-subject.v1"
_INACTIVE_BLOCKER = "portfolio_transition_execution_evidence_not_integrated"


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class TransitionPlanInactiveApprovalUnavailable(ValueError):
    """An exact current plan, subject, or receipt is unavailable."""


class TransitionPlanInactiveApprovalConflict(ValueError):
    """An immutable identity already has another first winner."""


class TransitionPlanInactiveApprovalCorruption(ValueError):
    """A trusted provider or repository returned an invalid value."""


@dataclass(frozen=True, slots=True)
class TransitionPlanDefinition:
    """Trusted Portfolio projection of one exact persisted transition plan."""

    plan: TransitionPlan
    content_hash: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if type(self.plan) is not TransitionPlan:
            raise TypeError("plan must be an exact TransitionPlan")
        validate_transition_plan_for_approval_receipt(self.plan)
        if self.plan.status != "APPROVED":
            raise ValueError("transition plan definition must be approved")
        _require_hash(self.content_hash, "content_hash")
        if transition_plan_content_hash_v1(self.plan) != self.content_hash:
            raise ValueError("transition plan definition hash is invalid")
        _require_aware(self.recorded_at, "recorded_at")
        if self.recorded_at < self.plan.as_of_time or self.recorded_at >= self.plan.expires_at:
            raise ValueError("transition plan definition persistence clock is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact plan is knowable and unexpired at a cutoff."""

        _require_aware(as_of, "as_of")
        return bool(self.recorded_at <= as_of < self.plan.expires_at)


@dataclass(frozen=True, slots=True)
class TransitionPlanInactiveApprovalSubject:
    """Persisted first-winner subject for one exact transition plan."""

    subject_id: str
    subject_version: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    account_id: str
    decision_snapshot_id: str
    requested_by: TransitionPlanApprovalActor
    requested_at: datetime
    valid_until: datetime
    content_hash: str = ""
    owner: str = "portfolio"
    schema: str = _SUBJECT_SCHEMA
    execution_permission: str = "inactive"
    blocker_codes: tuple[str, ...] = (_INACTIVE_BLOCKER,)

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "plan_id",
            "account_id",
            "decision_snapshot_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        _require_hash(self.plan_content_hash, "plan_content_hash")
        if type(self.requested_by) is not TransitionPlanApprovalActor:
            raise TypeError("requested_by must be an exact TransitionPlanApprovalActor")
        TransitionPlanApprovalActor.__post_init__(self.requested_by)
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.valid_until, "valid_until")
        if self.requested_at >= self.valid_until:
            raise ValueError("approval subject validity window is invalid")
        if self.owner != "portfolio" or self.schema != _SUBJECT_SCHEMA:
            raise ValueError("approval subject authority or schema is invalid")
        if self.execution_permission != "inactive":
            raise ValueError("approval subject execution_permission is fixed inactive")
        if self.blocker_codes != (_INACTIVE_BLOCKER,):
            raise ValueError("approval subject blocker_codes are fixed")
        expected = _hash_payload(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("approval subject content_hash is invalid")

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        subject_version: str,
        definition: TransitionPlanDefinition,
        requested_by: TransitionPlanApprovalActor,
        requested_at: datetime,
    ) -> TransitionPlanInactiveApprovalSubject:
        """Create a sealed inactive subject from a trusted exact definition."""

        TransitionPlanDefinition.__post_init__(definition)
        plan = definition.plan
        return cls(
            subject_id=subject_id,
            subject_version=subject_version,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            plan_content_hash=definition.content_hash,
            account_id=plan.account_id,
            decision_snapshot_id=plan.decision_snapshot_id,
            requested_by=requested_by,
            requested_at=requested_at,
            valid_until=plan.expires_at,
        )

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this persisted subject is active at a cutoff."""

        _require_aware(as_of, "as_of")
        return bool(self.requested_at <= as_of < self.valid_until)

    @property
    def must_not_execute(self) -> bool:
        """Keep the disconnected approval surface non-executable."""

        return True

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "schema": self.schema,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_content_hash": self.plan_content_hash,
            "account_id": self.account_id,
            "decision_snapshot_id": self.decision_snapshot_id,
            "requested_by": self.requested_by.to_payload(),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "execution_permission": self.execution_permission,
            "blocker_codes": list(self.blocker_codes),
        }


@dataclass(frozen=True, slots=True)
class RegisterTransitionPlanInactiveApprovalSubjectCommand:
    """ID-only request to register one exact plan approval subject."""

    subject_id: str
    subject_version: str
    plan_id: str
    plan_version: int

    def __post_init__(self) -> None:
        for field_name in ("subject_id", "subject_version", "plan_id"):
            _require_token(getattr(self, field_name), field_name)
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")


@dataclass(frozen=True, slots=True)
class ApproveTransitionPlanInactiveCommand:
    """ID-only request to approve one persisted exact subject."""

    subject_id: str
    subject_version: str
    receipt_id: str
    receipt_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "receipt_id",
            "receipt_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetExactTransitionPlanInactiveApprovalCommand:
    """Strict identity/hash/PIT lookup for one inactive receipt."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    subject_id: str
    subject_version: str
    subject_content_hash: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "receipt_id")
        _require_token(self.receipt_version, "receipt_version")
        _require_token(self.subject_id, "subject_id")
        _require_token(self.subject_version, "subject_version")
        _require_token(self.plan_id, "plan_id")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_hash(self.subject_content_hash, "subject_content_hash")
        _require_hash(self.plan_content_hash, "plan_content_hash")
        _require_aware(self.as_of, "as_of")


class ExactTransitionPlanDefinitionProvider(Protocol):
    """Trusted exact transition-plan reader."""

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        """Return the exact active plan definition at the cutoff."""


class TransitionPlanInactiveApprovalRepository(Protocol):
    """Private append-only subject and receipt persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open a private first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Portfolio server clock."""

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> TransitionPlanInactiveApprovalSubject | None:
        """Return the persisted immutable subject identity winner."""

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        """Return the persisted immutable receipt identity winner."""

    def append_subject(
        self, subject: TransitionPlanInactiveApprovalSubject, *, recorded_at: datetime
    ) -> TransitionPlanInactiveApprovalSubject:
        """Append or return one exact subject first winner."""

    def append(
        self,
        receipt: TransitionPlanApprovalReceipt,
        *,
        subject: TransitionPlanInactiveApprovalSubject,
        recorded_at: datetime,
    ) -> TransitionPlanApprovalReceipt:
        """Append or return one exact receipt first winner."""

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TransitionPlanApprovalReceipt | None:
        """Return an exact inactive receipt knowable at the cutoff."""


class RegisterTransitionPlanInactiveApprovalSubject:
    """Register one persisted first-winner subject from trusted plan state."""

    def __init__(
        self,
        *,
        plan_provider: ExactTransitionPlanDefinitionProvider,
        repository: TransitionPlanInactiveApprovalRepository,
        actor: TransitionPlanApprovalActor,
    ) -> None:
        self._plan_provider = plan_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: RegisterTransitionPlanInactiveApprovalSubjectCommand
    ) -> TransitionPlanInactiveApprovalSubject:
        """Register one ID-only subject using double-read and server time."""

        _validate_actor(self._actor)
        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Portfolio server clock")
            first = self._read_plan(command, recorded_at)
            winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=recorded_at,
            )
            final = self._read_plan(command, recorded_at)
            if first != final:
                raise TransitionPlanInactiveApprovalCorruption(
                    "transition plan changed during subject registration"
                )
            if winner is not None:
                self._validate_subject_winner(winner, command, final, recorded_at)
                if winner.requested_by != self._actor:
                    raise TransitionPlanInactiveApprovalConflict(
                        "approval subject first winner belongs to another requester"
                    )
                return winner
            candidate = TransitionPlanInactiveApprovalSubject.create(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                definition=final,
                requested_by=self._actor,
                requested_at=recorded_at,
            )
            persisted = self._repository.append_subject(candidate, recorded_at=recorded_at)
            if persisted != candidate:
                raise TransitionPlanInactiveApprovalConflict(
                    "concurrent approval subject first winner differs"
                )
            return persisted

    def _read_plan(
        self,
        command: RegisterTransitionPlanInactiveApprovalSubjectCommand,
        as_of: datetime,
    ) -> TransitionPlanDefinition:
        value = self._plan_provider.get_exact(
            plan_id=command.plan_id, plan_version=command.plan_version, as_of=as_of
        )
        return _validate_definition(value, command.plan_id, command.plan_version, as_of)

    @staticmethod
    def _validate_subject_winner(
        winner: TransitionPlanInactiveApprovalSubject,
        command: RegisterTransitionPlanInactiveApprovalSubjectCommand,
        definition: TransitionPlanDefinition,
        as_of: datetime,
    ) -> None:
        if type(winner) is not TransitionPlanInactiveApprovalSubject:
            raise TransitionPlanInactiveApprovalCorruption("approval subject type substitution")
        TransitionPlanInactiveApprovalSubject.__post_init__(winner)
        if (
            winner.subject_id != command.subject_id
            or winner.subject_version != command.subject_version
            or winner.plan_id != definition.plan.plan_id
            or winner.plan_version != definition.plan.version
            or winner.plan_content_hash != definition.content_hash
            or winner.account_id != definition.plan.account_id
            or winner.decision_snapshot_id != definition.plan.decision_snapshot_id
        ):
            raise TransitionPlanInactiveApprovalConflict(
                "approval subject identity has another first winner"
            )
        if not winner.is_valid_at(as_of):
            raise TransitionPlanInactiveApprovalUnavailable(
                "persisted approval subject is no longer active"
            )


class ApproveTransitionPlanInactive:
    """Issue one first-winner inactive receipt for a persisted subject."""

    def __init__(
        self,
        *,
        plan_provider: ExactTransitionPlanDefinitionProvider,
        repository: TransitionPlanInactiveApprovalRepository,
        actor: TransitionPlanApprovalActor,
    ) -> None:
        self._plan_provider = plan_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: ApproveTransitionPlanInactiveCommand
    ) -> TransitionPlanApprovalReceipt:
        """Approve by IDs only using persisted subject and double-read state."""

        _validate_actor(self._actor)
        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Portfolio server clock")
            first_subject = self._read_subject(command, recorded_at)
            first_plan = self._read_bound_plan(first_subject, recorded_at)
            winner = self._repository.get_receipt_winner(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=recorded_at,
            )
            final_subject = self._read_subject(command, recorded_at)
            final_plan = self._read_bound_plan(final_subject, recorded_at)
            if first_subject != final_subject or first_plan != final_plan:
                raise TransitionPlanInactiveApprovalCorruption(
                    "approval subject or transition plan changed during approval"
                )
            if (
                self._actor.actor_id == final_subject.requested_by.actor_id
                or self._actor.user_id == final_subject.requested_by.user_id
            ):
                raise TransitionPlanInactiveApprovalUnavailable("self approval is forbidden")
            if winner is not None:
                self._validate_receipt_winner(
                    winner, command, final_subject, self._actor, recorded_at
                )
                return winner
            candidate = TransitionPlanApprovalReceipt.create(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                subject_id=final_subject.subject_id,
                subject_version=final_subject.subject_version,
                subject_content_hash=final_subject.content_hash,
                requested_by=final_subject.requested_by,
                plan=final_plan.plan,
                approved_by=self._actor,
                issued_at=recorded_at,
            )
            persisted = self._repository.append(
                candidate,
                subject=final_subject,
                recorded_at=recorded_at,
            )
            if persisted != candidate:
                raise TransitionPlanInactiveApprovalConflict(
                    "concurrent inactive receipt first winner differs"
                )
            return persisted

    def _read_subject(
        self, command: ApproveTransitionPlanInactiveCommand, as_of: datetime
    ) -> TransitionPlanInactiveApprovalSubject:
        value = self._repository.get_subject_winner(
            subject_id=command.subject_id,
            subject_version=command.subject_version,
            as_of=as_of,
        )
        if value is None:
            raise TransitionPlanInactiveApprovalUnavailable(
                "exact persisted approval subject is unavailable"
            )
        if type(value) is not TransitionPlanInactiveApprovalSubject:
            raise TransitionPlanInactiveApprovalCorruption("approval subject type substitution")
        TransitionPlanInactiveApprovalSubject.__post_init__(value)
        if not value.is_valid_at(as_of):
            raise TransitionPlanInactiveApprovalUnavailable(
                "exact persisted approval subject is unavailable"
            )
        return value

    def _read_bound_plan(
        self, subject: TransitionPlanInactiveApprovalSubject, as_of: datetime
    ) -> TransitionPlanDefinition:
        value = self._plan_provider.get_exact(
            plan_id=subject.plan_id, plan_version=subject.plan_version, as_of=as_of
        )
        definition = _validate_definition(value, subject.plan_id, subject.plan_version, as_of)
        if (
            definition.content_hash != subject.plan_content_hash
            or definition.plan.account_id != subject.account_id
            or definition.plan.decision_snapshot_id != subject.decision_snapshot_id
        ):
            raise TransitionPlanInactiveApprovalCorruption(
                "transition plan no longer matches the persisted subject"
            )
        return definition

    @staticmethod
    def _validate_receipt_winner(
        winner: TransitionPlanApprovalReceipt,
        command: ApproveTransitionPlanInactiveCommand,
        subject: TransitionPlanInactiveApprovalSubject,
        actor: TransitionPlanApprovalActor,
        as_of: datetime,
    ) -> None:
        if type(winner) is not TransitionPlanApprovalReceipt:
            raise TransitionPlanInactiveApprovalCorruption("approval receipt type substitution")
        TransitionPlanApprovalReceipt.__post_init__(winner)
        if (
            winner.receipt_id != command.receipt_id
            or winner.receipt_version != command.receipt_version
            or winner.subject_id != subject.subject_id
            or winner.subject_version != subject.subject_version
            or winner.subject_content_hash != subject.content_hash
            or winner.plan_id != subject.plan_id
            or winner.plan_version != subject.plan_version
            or winner.plan_content_hash != subject.plan_content_hash
            or winner.account_id != subject.account_id
            or winner.decision_snapshot_id != subject.decision_snapshot_id
            or winner.requested_by != subject.requested_by
        ):
            raise TransitionPlanInactiveApprovalConflict(
                "inactive receipt identity has another first winner"
            )
        if winner.approved_by != actor:
            raise TransitionPlanInactiveApprovalConflict(
                "inactive receipt first winner belongs to another approver"
            )
        if not winner.issued_at <= as_of < winner.valid_until:
            raise TransitionPlanInactiveApprovalUnavailable(
                "persisted inactive receipt is no longer active"
            )


class GetExactTransitionPlanInactiveApproval:
    """Expose strict identity/hash/PIT reads without enabling execution."""

    def __init__(self, repository: TransitionPlanInactiveApprovalRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactTransitionPlanInactiveApprovalCommand
    ) -> TransitionPlanApprovalReceipt | None:
        """Return only one exact valid inactive receipt."""

        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        if type(value) is not TransitionPlanApprovalReceipt:
            raise TransitionPlanInactiveApprovalCorruption("approval receipt type substitution")
        TransitionPlanApprovalReceipt.__post_init__(value)
        if (
            value.receipt_id != command.receipt_id
            or value.receipt_version != command.receipt_version
            or value.content_hash != command.expected_content_hash
            or value.subject_id != command.subject_id
            or value.subject_version != command.subject_version
            or value.subject_content_hash != command.subject_content_hash
            or value.plan_id != command.plan_id
            or value.plan_version != command.plan_version
            or value.plan_content_hash != command.plan_content_hash
        ):
            raise TransitionPlanInactiveApprovalCorruption("approval receipt identity substitution")
        if not value.issued_at <= command.as_of < value.valid_until:
            return None
        if (
            not value.must_not_execute
            or value.execution_permission != "inactive"
            or value.plan_status_at_issue != "APPROVED"
        ):
            raise TransitionPlanInactiveApprovalCorruption(
                "approval receipt execution state substitution"
            )
        return value


def _validate_definition(
    value: TransitionPlanDefinition | None,
    plan_id: str,
    plan_version: int,
    as_of: datetime,
) -> TransitionPlanDefinition:
    if value is None:
        raise TransitionPlanInactiveApprovalUnavailable(
            "exact active transition plan is unavailable"
        )
    if type(value) is not TransitionPlanDefinition:
        raise TransitionPlanInactiveApprovalCorruption("transition plan type substitution")
    try:
        TransitionPlanDefinition.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise TransitionPlanInactiveApprovalCorruption(
            "transition plan definition is invalid"
        ) from error
    if value.plan.plan_id != plan_id or value.plan.version != plan_version:
        raise TransitionPlanInactiveApprovalCorruption("transition plan identity substitution")
    if not value.is_active_at(as_of):
        raise TransitionPlanInactiveApprovalUnavailable(
            "exact active transition plan is unavailable"
        )
    return value


def _validate_actor(actor: TransitionPlanApprovalActor) -> None:
    if type(actor) is not TransitionPlanApprovalActor:
        raise TransitionPlanInactiveApprovalCorruption("approval actor type substitution")
    try:
        TransitionPlanApprovalActor.__post_init__(actor)
    except (TypeError, ValueError) as error:
        raise TransitionPlanInactiveApprovalCorruption("approval actor is invalid") from error


__all__ = [
    "ApproveTransitionPlanInactive",
    "ApproveTransitionPlanInactiveCommand",
    "ExactTransitionPlanDefinitionProvider",
    "GetExactTransitionPlanInactiveApproval",
    "GetExactTransitionPlanInactiveApprovalCommand",
    "RegisterTransitionPlanInactiveApprovalSubject",
    "RegisterTransitionPlanInactiveApprovalSubjectCommand",
    "TransitionPlanDefinition",
    "TransitionPlanInactiveApprovalConflict",
    "TransitionPlanInactiveApprovalCorruption",
    "TransitionPlanInactiveApprovalRepository",
    "TransitionPlanInactiveApprovalSubject",
    "TransitionPlanInactiveApprovalUnavailable",
]
