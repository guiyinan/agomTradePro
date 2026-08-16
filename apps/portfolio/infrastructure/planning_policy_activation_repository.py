"""Append-only subject/record ledger for planning-policy activation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.application.planning_policy_activation import (
    PlanningPolicyActivationConflict,
    PlanningPolicyActivationCorruption,
    PlanningPolicyActivationUnavailable,
)
from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
    validate_planning_policy_activation_successor,
)
from apps.portfolio.infrastructure.planning_policy_activation_codec import (
    PlanningPolicyActivationCodecError,
    decode_planning_policy_activation,
    decode_planning_policy_activation_subject,
    encode_planning_policy_activation,
    encode_planning_policy_activation_subject,
)
from apps.portfolio.infrastructure.planning_policy_activation_models import (
    _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW,
    PortfolioPlanningPolicyActivationModel,
    PortfolioPlanningPolicyActivationSubjectModel,
    _activate_planning_policy_activation_uow,
    _claim_planning_policy_activation_insert,
)


class PlanningPolicyActivationClock(Protocol):
    """Authoritative Portfolio activation persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPlanningPolicyActivationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoPlanningPolicyActivationRepository:
    """Private first-winner writer and strict exact/PIT/head reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PlanningPolicyActivationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPlanningPolicyActivationClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private first-winner transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_planning_policy_activation_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PlanningPolicyActivationCorruption("Portfolio activation clock is naive")
        return value

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PlanningPolicyActivationSubject | None:
        """Return one exact, knowable, and unexpired subject identity winner."""

        self._require_cutoff(as_of)
        subjects, _ = self._state()
        matches = tuple(
            value
            for value, _ in subjects
            if value.subject_id == subject_id and value.subject_version == subject_version
        )
        if len(matches) > 1:
            raise PlanningPolicyActivationCorruption("activation subject identity is ambiguous")
        if not matches:
            return None
        value = matches[0]
        return value if value.is_valid_at(as_of) else None

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        """Return one exact, knowable, and unexpired activation identity winner."""

        self._require_cutoff(as_of)
        _, activations = self._state()
        matches = tuple(
            value
            for value, _ in activations
            if value.activation_id == activation_id
            and value.activation_version == activation_version
        )
        if len(matches) > 1:
            raise PlanningPolicyActivationCorruption("activation identity is ambiguous")
        if not matches:
            return None
        value = matches[0]
        return value if value.is_valid_at(as_of) else None

    def get_current_head(
        self, *, policy_id: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        """Return the logical policy head at a PIT cutoff without expiry fallback."""

        self._require_cutoff(as_of)
        _, activations = self._state()
        visible = tuple(
            value
            for value, _ in activations
            if value.subject.policy_id == policy_id and value.issued_at <= as_of
        )
        if not visible:
            return None
        visible_predecessors = {
            value.subject.supersedes_activation_hash
            for value in visible
            if value.subject.supersedes_activation_hash is not None
        }
        heads = tuple(value for value in visible if value.content_hash not in visible_predecessors)
        if len(heads) != 1:
            raise PlanningPolicyActivationCorruption("activation PIT head is ambiguous")
        head = heads[0]
        return head if head.is_valid_at(as_of) else None

    def append_subject(
        self,
        subject: PlanningPolicyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PlanningPolicyActivationSubject:
        """Append or return the exact subject first winner."""

        token = _active_token()
        _validate_subject(subject)
        if subject.requested_at != recorded_at:
            raise PlanningPolicyActivationConflict(
                "activation subject must use the authoritative transaction clock"
            )
        subjects, activations = self._state()
        existing = _exact_subject(subjects, subject)
        if existing is not None:
            return existing[0]
        structural_head = _policy_structural_head(activations, subject.policy_id)
        expected = structural_head[0].content_hash if structural_head is not None else None
        if subject.supersedes_activation_hash != expected:
            raise PlanningPolicyActivationConflict(
                "activation subject does not bind the logical policy head"
            )
        if structural_head is not None and not structural_head[0].is_valid_at(recorded_at):
            raise PlanningPolicyActivationConflict(
                "activation subject cannot supersede an expired logical head"
            )
        values = _subject_values(subject, recorded_at)
        model = PortfolioPlanningPolicyActivationSubjectModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_planning_policy_activation_insert(
                    token=token,
                    model_type=PortfolioPlanningPolicyActivationSubjectModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact_subject(self._state()[0], subject)
            if winner is None:
                raise PlanningPolicyActivationConflict(
                    "activation subject append conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore_subject(model)

    def append(
        self,
        activation: PlanningPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PlanningPolicyActivation:
        """Append or replay one exact activation with predecessor CAS."""

        token = _active_token()
        _validate_activation(activation)
        if activation.issued_at != recorded_at:
            raise PlanningPolicyActivationConflict(
                "activation must use the authoritative transaction clock"
            )
        if activation.subject.supersedes_activation_hash != expected_predecessor_hash:
            raise PlanningPolicyActivationConflict("activation predecessor selector differs")
        subjects, activations = self._state()
        subject_model = _exact_subject(subjects, activation.subject)
        if subject_model is None:
            raise PlanningPolicyActivationConflict(
                "activation requires its persisted exact subject"
            )
        existing = _exact_activation(activations, activation)
        if existing is not None:
            return existing[0]
        structural_head = _policy_structural_head(activations, activation.subject.policy_id)
        actual_predecessor = (
            structural_head[0].content_hash if structural_head is not None else None
        )
        if actual_predecessor != expected_predecessor_hash:
            raise PlanningPolicyActivationConflict("stale activation predecessor")
        if structural_head is not None:
            try:
                validate_planning_policy_activation_successor(structural_head[0], activation)
            except (TypeError, ValueError) as error:
                raise PlanningPolicyActivationConflict("activation successor is invalid") from error
        values = _activation_values(activation, recorded_at)
        claimed = {**values, "subject_record_id": subject_model[1].pk}
        model = PortfolioPlanningPolicyActivationModel(**claimed)
        try:
            with transaction.atomic(using=self._using):
                if structural_head is not None:
                    PortfolioPlanningPolicyActivationModel._default_manager.using(
                        self._using
                    ).select_for_update().get(pk=structural_head[1].pk)
                with _claim_planning_policy_activation_insert(
                    token=token,
                    model_type=PortfolioPlanningPolicyActivationModel,
                    expected_values=claimed,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact_activation(self._state()[1], activation)
            if winner is None:
                raise PlanningPolicyActivationConflict(
                    "activation append conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore_activation(model)

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PlanningPolicyActivationUnavailable("activation as_of is naive")
        if as_of > self.now():
            raise PlanningPolicyActivationUnavailable("future activation as_of is forbidden")

    def _state(
        self,
    ) -> tuple[
        tuple[
            tuple[
                PlanningPolicyActivationSubject,
                PortfolioPlanningPolicyActivationSubjectModel,
            ],
            ...,
        ],
        tuple[
            tuple[PlanningPolicyActivation, PortfolioPlanningPolicyActivationModel],
            ...,
        ],
    ]:
        subject_rows = tuple(
            PortfolioPlanningPolicyActivationSubjectModel._default_manager.using(self._using).all()
        )
        subjects = tuple((self._restore_subject(row), row) for row in subject_rows)
        activation_rows = tuple(
            PortfolioPlanningPolicyActivationModel._default_manager.using(self._using)
            .select_related("subject_record")
            .all()
        )
        activations = tuple((self._restore_activation(row), row) for row in activation_rows)
        _validate_chain(activations)
        return subjects, activations

    def _restore_subject(
        self, model: PortfolioPlanningPolicyActivationSubjectModel
    ) -> PlanningPolicyActivationSubject:
        try:
            value = decode_planning_policy_activation_subject(model.canonical_payload)
        except PlanningPolicyActivationCodecError as error:
            raise PlanningPolicyActivationCorruption(
                "activation subject payload cannot be restored"
            ) from error
        if _subject_headers(value) != _subject_model_headers(model):
            raise PlanningPolicyActivationCorruption(
                "activation subject headers do not match payload"
            )
        if model.subject_identity_hash != _identity_hash(
            "subject", value.subject_id, value.subject_version
        ) or model.ledger_header_hash != _subject_ledger_hash(value, model.recorded_at):
            raise PlanningPolicyActivationCorruption("activation subject seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.requested_at != model.recorded_at
        ):
            raise PlanningPolicyActivationCorruption(
                "activation subject persistence clock is invalid"
            )
        return value

    def _restore_activation(
        self, model: PortfolioPlanningPolicyActivationModel
    ) -> PlanningPolicyActivation:
        subject = self._restore_subject(model.subject_record)
        try:
            value = decode_planning_policy_activation(model.canonical_payload)
        except PlanningPolicyActivationCodecError as error:
            raise PlanningPolicyActivationCorruption(
                "activation payload cannot be restored"
            ) from error
        if value.subject != subject or _activation_headers(value) != _activation_model_headers(
            model
        ):
            raise PlanningPolicyActivationCorruption(
                "activation FK or headers do not match payload"
            )
        if model.activation_identity_hash != _identity_hash(
            "activation", value.activation_id, value.activation_version
        ) or model.ledger_header_hash != _activation_ledger_hash(value, model.recorded_at):
            raise PlanningPolicyActivationCorruption("activation ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.issued_at != model.recorded_at
            or model.subject_record.recorded_at > model.recorded_at
        ):
            raise PlanningPolicyActivationCorruption("activation persistence clock is invalid")
        return value


SubjectState = tuple[PlanningPolicyActivationSubject, PortfolioPlanningPolicyActivationSubjectModel]
ActivationState = tuple[PlanningPolicyActivation, PortfolioPlanningPolicyActivationModel]


def _active_token() -> object:
    token = _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.get()
    if token is None:
        raise PlanningPolicyActivationConflict(
            "activation append requires an active private unit of work"
        )
    return token


def _validate_subject(value: object) -> PlanningPolicyActivationSubject:
    if type(value) is not PlanningPolicyActivationSubject:
        raise PlanningPolicyActivationConflict("activation subject type substitution")
    try:
        PlanningPolicyActivationSubject.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PlanningPolicyActivationConflict("activation subject is invalid") from error
    return value


def _validate_activation(value: object) -> PlanningPolicyActivation:
    if type(value) is not PlanningPolicyActivation:
        raise PlanningPolicyActivationConflict("activation type substitution")
    try:
        PlanningPolicyActivation.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PlanningPolicyActivationConflict("activation is invalid") from error
    return value


def _exact_subject(
    rows: tuple[SubjectState, ...], subject: PlanningPolicyActivationSubject
) -> SubjectState | None:
    identity = _identity_hash("subject", subject.subject_id, subject.subject_version)
    candidates = tuple(
        item
        for item in rows
        if (
            (item[0].subject_id, item[0].subject_version)
            == (subject.subject_id, subject.subject_version)
            or _identity_hash("subject", item[0].subject_id, item[0].subject_version) == identity
            or item[0].content_hash == subject.content_hash
        )
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == subject)
    if len(candidates) != 1 or len(matches) != 1:
        raise PlanningPolicyActivationConflict("activation subject anchor has another first winner")
    return matches[0]


def _exact_activation(
    rows: tuple[ActivationState, ...], activation: PlanningPolicyActivation
) -> ActivationState | None:
    identity = _identity_hash("activation", activation.activation_id, activation.activation_version)
    candidates = tuple(
        item
        for item in rows
        if (
            (item[0].activation_id, item[0].activation_version)
            == (activation.activation_id, activation.activation_version)
            or _identity_hash("activation", item[0].activation_id, item[0].activation_version)
            == identity
            or item[0].content_hash == activation.content_hash
            or item[0].subject.content_hash == activation.subject.content_hash
        )
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == activation)
    if len(candidates) != 1 or len(matches) != 1:
        raise PlanningPolicyActivationConflict("activation anchor has another first winner")
    return matches[0]


def _policy_structural_head(
    rows: tuple[ActivationState, ...], policy_id: str
) -> ActivationState | None:
    policy_rows = tuple(item for item in rows if item[0].subject.policy_id == policy_id)
    if not policy_rows:
        return None
    predecessors = {
        item[0].subject.supersedes_activation_hash
        for item in policy_rows
        if item[0].subject.supersedes_activation_hash is not None
    }
    heads = tuple(item for item in policy_rows if item[0].content_hash not in predecessors)
    if len(heads) != 1:
        raise PlanningPolicyActivationCorruption("activation structural head is ambiguous")
    return heads[0]


def _validate_chain(rows: tuple[ActivationState, ...]) -> None:
    by_hash = {item[0].content_hash: item[0] for item in rows}
    if len(by_hash) != len(rows):
        raise PlanningPolicyActivationCorruption("activation content anchor is ambiguous")
    policies = {item[0].subject.policy_id for item in rows}
    for policy_id in policies:
        policy_values = tuple(item[0] for item in rows if item[0].subject.policy_id == policy_id)
        seen_predecessors: set[str] = set()
        for value in policy_values:
            predecessor_hash = value.subject.supersedes_activation_hash
            if predecessor_hash is None:
                continue
            if predecessor_hash in seen_predecessors:
                raise PlanningPolicyActivationCorruption("activation chain is forked")
            seen_predecessors.add(predecessor_hash)
            predecessor = by_hash.get(predecessor_hash)
            if predecessor is None:
                raise PlanningPolicyActivationCorruption("activation predecessor is orphaned")
            if predecessor.subject.policy_id != policy_id:
                raise PlanningPolicyActivationCorruption(
                    "activation predecessor crosses policy authority"
                )
            try:
                validate_planning_policy_activation_successor(predecessor, value)
            except (TypeError, ValueError) as error:
                raise PlanningPolicyActivationCorruption(
                    "activation successor chain is invalid"
                ) from error
        roots = tuple(
            value for value in policy_values if value.subject.supersedes_activation_hash is None
        )
        if len(roots) != 1:
            raise PlanningPolicyActivationCorruption("activation policy root is ambiguous")
        _policy_structural_head(rows, policy_id)


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identity_hash(kind: str, identifier: str, version: str) -> str:
    return _hash({"identity_kind": kind, "id": identifier, "version": version})


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject_ledger_hash(value: PlanningPolicyActivationSubject, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": _identity_hash("subject", value.subject_id, value.subject_version),
            "content_hash": value.content_hash,
            "definition_identity_hash": value.definition_identity_hash,
            "definition_content_hash": value.definition_content_hash,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _activation_ledger_hash(value: PlanningPolicyActivation, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": _identity_hash(
                "activation", value.activation_id, value.activation_version
            ),
            "content_hash": value.content_hash,
            "subject_content_hash": value.subject.content_hash,
            "predecessor_hash": value.subject.supersedes_activation_hash,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _actor_headers(value: PlanningPolicyActivationActor) -> tuple[object, ...]:
    return (value.actor_id, value.user_id, value.role, value.kind, value.is_staff)


def _subject_values(
    value: PlanningPolicyActivationSubject, recorded_at: datetime
) -> dict[str, object]:
    actor = value.requested_by
    return {
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "subject_identity_hash": _identity_hash("subject", value.subject_id, value.subject_version),
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "definition_identity_hash": value.definition_identity_hash,
        "definition_content_hash": value.definition_content_hash,
        "definition_recorded_at": value.definition_recorded_at,
        "requested_actor_id": actor.actor_id,
        "requested_actor_user_id": actor.user_id,
        "requested_actor_role": actor.role,
        "requested_actor_kind": actor.kind,
        "requested_actor_is_staff": actor.is_staff,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "supersedes_activation_hash": value.supersedes_activation_hash,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_planning_policy_activation_subject(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _subject_ledger_hash(value, recorded_at),
    }


def _activation_values(value: PlanningPolicyActivation, recorded_at: datetime) -> dict[str, object]:
    subject = value.subject
    requester = subject.requested_by
    approver = value.approved_by
    return {
        "owner": value.owner,
        "capability": value.capability,
        "schema": value.schema,
        "permission": value.permission,
        "activation_id": value.activation_id,
        "activation_version": value.activation_version,
        "activation_identity_hash": _identity_hash(
            "activation", value.activation_id, value.activation_version
        ),
        "subject_id": subject.subject_id,
        "subject_version": subject.subject_version,
        "subject_content_hash": subject.content_hash,
        "policy_id": subject.policy_id,
        "policy_version": subject.policy_version,
        "definition_identity_hash": subject.definition_identity_hash,
        "definition_content_hash": subject.definition_content_hash,
        "requested_actor_id": requester.actor_id,
        "requested_actor_user_id": requester.user_id,
        "requested_actor_role": requester.role,
        "approved_actor_id": approver.actor_id,
        "approved_actor_user_id": approver.user_id,
        "approved_actor_role": approver.role,
        "approved_actor_kind": approver.kind,
        "approved_actor_is_staff": approver.is_staff,
        "issued_at": value.issued_at,
        "valid_until": value.valid_until,
        "predecessor_hash": subject.supersedes_activation_hash,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_planning_policy_activation(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _activation_ledger_hash(value, recorded_at),
    }


def _subject_headers(value: PlanningPolicyActivationSubject) -> tuple[object, ...]:
    return (
        value.subject_id,
        value.subject_version,
        value.policy_id,
        value.policy_version,
        value.definition_identity_hash,
        value.definition_content_hash,
        value.definition_recorded_at,
        *_actor_headers(value.requested_by),
        value.requested_at,
        value.valid_until,
        value.supersedes_activation_hash,
        value.content_hash,
    )


def _subject_model_headers(
    model: PortfolioPlanningPolicyActivationSubjectModel,
) -> tuple[object, ...]:
    return (
        model.subject_id,
        model.subject_version,
        model.policy_id,
        model.policy_version,
        model.definition_identity_hash,
        model.definition_content_hash,
        model.definition_recorded_at,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.requested_actor_kind,
        model.requested_actor_is_staff,
        model.requested_at,
        model.valid_until,
        model.supersedes_activation_hash,
        model.content_hash,
    )


def _activation_headers(value: PlanningPolicyActivation) -> tuple[object, ...]:
    subject = value.subject
    return (
        value.owner,
        value.capability,
        value.schema,
        value.permission,
        value.activation_id,
        value.activation_version,
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
        subject.policy_id,
        subject.policy_version,
        subject.definition_identity_hash,
        subject.definition_content_hash,
        subject.requested_by.actor_id,
        subject.requested_by.user_id,
        subject.requested_by.role,
        value.approved_by.actor_id,
        value.approved_by.user_id,
        value.approved_by.role,
        value.approved_by.kind,
        value.approved_by.is_staff,
        value.issued_at,
        value.valid_until,
        subject.supersedes_activation_hash,
        value.content_hash,
    )


def _activation_model_headers(
    model: PortfolioPlanningPolicyActivationModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.capability,
        model.schema,
        model.permission,
        model.activation_id,
        model.activation_version,
        model.subject_id,
        model.subject_version,
        model.subject_content_hash,
        model.policy_id,
        model.policy_version,
        model.definition_identity_hash,
        model.definition_content_hash,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.approved_actor_id,
        model.approved_actor_user_id,
        model.approved_actor_role,
        model.approved_actor_kind,
        model.approved_actor_is_staff,
        model.issued_at,
        model.valid_until,
        model.predecessor_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPlanningPolicyActivationClock",
    "DjangoPlanningPolicyActivationRepository",
    "PlanningPolicyActivationClock",
]
