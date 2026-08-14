"""Append-only ledger for policy-benchmark methodology bundle activation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.application.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationConflict,
    PolicyBenchmarkMethodologyActivationCorruption,
    PolicyBenchmarkMethodologyActivationUnavailable,
)
from apps.portfolio.domain.policy_benchmark_definition import PolicyBenchmarkMethodologyRef
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundleActivation,
    validate_policy_benchmark_methodology_activation_root,
    validate_policy_benchmark_methodology_activation_successor,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_codec import (
    PolicyBenchmarkMethodologyActivationCodecError,
    decode_policy_benchmark_methodology_activation,
    decode_policy_benchmark_methodology_activation_subject,
    encode_policy_benchmark_methodology_activation,
    encode_policy_benchmark_methodology_activation_subject,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_models import (
    _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW,
    PortfolioPolicyBenchmarkMethodologyActivationModel,
    PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
    _activate_benchmark_methodology_activation_uow,
    _claim_benchmark_methodology_activation_insert,
)


class PolicyBenchmarkMethodologyActivationClock(Protocol):
    """Authoritative Portfolio activation persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkMethodologyActivationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoPolicyBenchmarkMethodologyActivationRepository:
    """Private first-winner writer and closed-world exact/PIT/head reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PolicyBenchmarkMethodologyActivationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkMethodologyActivationClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private first-winner transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_benchmark_methodology_activation_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "benchmark methodology activation clock is naive"
            )
        return value

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyActivationSubject | None:
        """Return one exact, knowable, and unexpired subject identity winner."""

        self._require_cutoff(as_of)
        subjects, _ = self._state()
        matches = tuple(
            value
            for value, _ in subjects
            if (value.subject_id, value.subject_version) == (subject_id, subject_version)
        )
        if len(matches) > 1:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation subject identity is ambiguous"
            )
        if not matches:
            return None
        return matches[0] if matches[0].is_valid_at(as_of) else None

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return one exact, knowable, and unexpired activation identity winner."""

        self._require_cutoff(as_of)
        _, activations = self._state()
        matches = tuple(
            value
            for value, _ in activations
            if (value.activation_id, value.activation_version)
            == (activation_id, activation_version)
        )
        if len(matches) > 1:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation identity is ambiguous"
            )
        if not matches:
            return None
        return matches[0] if matches[0].is_valid_at(as_of) else None

    def get_exact_by_hash(
        self,
        *,
        activation_id: str,
        activation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return one historical exact identity/hash activation at a PIT cutoff."""

        self._require_cutoff(as_of)
        _, activations = self._state()
        matches = tuple(
            value
            for value, _ in activations
            if value.activation_id == activation_id
            and value.activation_version == activation_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation exact selector is ambiguous"
            )
        if not matches:
            return None
        return matches[0] if matches[0].is_valid_at(as_of) else None

    def get_current_head(
        self, *, definition_id: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return the logical definition head without expired-head fallback."""

        self._require_cutoff(as_of)
        _, activations = self._state()
        visible = tuple(
            value
            for value, _ in activations
            if value.subject.definition_id == definition_id and value.issued_at <= as_of
        )
        if not visible:
            return None
        predecessors = {
            value.subject.supersedes_activation_hash
            for value in visible
            if value.subject.supersedes_activation_hash is not None
        }
        heads = tuple(value for value in visible if value.content_hash not in predecessors)
        if len(heads) != 1:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation PIT head is ambiguous"
            )
        return heads[0] if heads[0].is_valid_at(as_of) else None

    def append_subject(
        self,
        subject: PolicyBenchmarkMethodologyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        """Append or return the exact subject first winner."""

        token = _active_token()
        _validate_subject(subject)
        if subject.requested_at != recorded_at:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation subject must use the authoritative transaction clock"
            )
        subjects, activations = self._state()
        existing = _exact_subject(subjects, subject)
        if existing is not None:
            return existing[0]
        head = _definition_structural_head(activations, subject.definition_id)
        expected = head[0].content_hash if head is not None else None
        if subject.supersedes_activation_hash != expected:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation subject does not bind the logical definition head"
            )
        if head is not None and not head[0].is_valid_at(recorded_at):
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation subject cannot supersede an expired logical head"
            )
        values = _subject_values(subject, recorded_at)
        model = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_benchmark_methodology_activation_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact_subject(self._state()[0], subject)
            if winner is None:
                raise PolicyBenchmarkMethodologyActivationConflict(
                    "methodology activation subject conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore_subject(model)

    def append(
        self,
        activation: PolicyBenchmarkMethodologyBundleActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        """Append or replay one exact activation with predecessor CAS."""

        token = _active_token()
        _validate_activation(activation)
        if activation.issued_at != recorded_at:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation must use the authoritative transaction clock"
            )
        if activation.subject.supersedes_activation_hash != expected_predecessor_hash:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation predecessor selector differs"
            )
        subjects, activations = self._state()
        subject_model = _exact_subject(subjects, activation.subject)
        if subject_model is None:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation requires its persisted exact subject"
            )
        existing = _exact_activation(activations, activation)
        if existing is not None:
            return existing[0]
        head = _definition_structural_head(activations, activation.subject.definition_id)
        actual = head[0].content_hash if head is not None else None
        if actual != expected_predecessor_hash:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "stale methodology activation predecessor"
            )
        try:
            if head is None:
                validate_policy_benchmark_methodology_activation_root(activation)
            else:
                validate_policy_benchmark_methodology_activation_successor(head[0], activation)
        except (TypeError, ValueError) as error:
            raise PolicyBenchmarkMethodologyActivationConflict(
                "methodology activation chain candidate is invalid"
            ) from error
        values = _activation_values(activation, recorded_at)
        claimed = {**values, "subject_record_id": subject_model[1].pk}
        model = PortfolioPolicyBenchmarkMethodologyActivationModel(**claimed)
        try:
            with transaction.atomic(using=self._using):
                if head is not None:
                    PortfolioPolicyBenchmarkMethodologyActivationModel._default_manager.using(
                        self._using
                    ).select_for_update().get(pk=head[1].pk)
                with _claim_benchmark_methodology_activation_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkMethodologyActivationModel,
                    expected_values=claimed,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact_activation(self._state()[1], activation)
            if winner is None:
                raise PolicyBenchmarkMethodologyActivationConflict(
                    "methodology activation conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore_activation(model)

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkMethodologyActivationUnavailable(
                "methodology activation as_of is naive"
            )
        if as_of > self.now():
            raise PolicyBenchmarkMethodologyActivationUnavailable(
                "future methodology activation as_of is forbidden"
            )

    def _state(
        self,
    ) -> tuple[tuple[SubjectState, ...], tuple[ActivationState, ...]]:
        subject_rows = tuple(
            PortfolioPolicyBenchmarkMethodologyActivationSubjectModel._default_manager.using(
                self._using
            ).all()
        )
        subjects = tuple((self._restore_subject(row), row) for row in subject_rows)
        activation_rows = tuple(
            PortfolioPolicyBenchmarkMethodologyActivationModel._default_manager.using(self._using)
            .select_related("subject_record")
            .all()
        )
        activations = tuple((self._restore_activation(row), row) for row in activation_rows)
        _validate_chain(activations)
        return subjects, activations

    def _restore_subject(
        self, model: PortfolioPolicyBenchmarkMethodologyActivationSubjectModel
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        try:
            value = decode_policy_benchmark_methodology_activation_subject(model.canonical_payload)
        except PolicyBenchmarkMethodologyActivationCodecError as error:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation subject payload cannot be restored"
            ) from error
        if _subject_headers(value) != _subject_model_headers(model):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation subject headers do not match payload"
            )
        if model.subject_identity_hash != _identity_hash(
            "subject", value.subject_id, value.subject_version
        ) or model.ledger_header_hash != _subject_ledger_hash(value, model.recorded_at):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation subject seal is invalid"
            )
        if (
            model.recorded_at.tzinfo is None
            or model.recorded_at.utcoffset() is None
            or model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.requested_at != model.recorded_at
        ):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation subject persistence clock is invalid"
            )
        return value

    def _restore_activation(
        self, model: PortfolioPolicyBenchmarkMethodologyActivationModel
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        subject = self._restore_subject(model.subject_record)
        try:
            value = decode_policy_benchmark_methodology_activation(model.canonical_payload)
        except PolicyBenchmarkMethodologyActivationCodecError as error:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation payload cannot be restored"
            ) from error
        if value.subject != subject or _activation_headers(value) != _activation_model_headers(
            model
        ):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation FK or headers do not match payload"
            )
        if model.activation_identity_hash != _identity_hash(
            "activation", value.activation_id, value.activation_version
        ) or model.ledger_header_hash != _activation_ledger_hash(value, model.recorded_at):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation ledger seal is invalid"
            )
        if (
            model.recorded_at.tzinfo is None
            or model.recorded_at.utcoffset() is None
            or model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.issued_at != model.recorded_at
            or model.subject_record.recorded_at > model.recorded_at
        ):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation persistence clock is invalid"
            )
        return value


SubjectState = tuple[
    PolicyBenchmarkMethodologyActivationSubject,
    PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
]
ActivationState = tuple[
    PolicyBenchmarkMethodologyBundleActivation,
    PortfolioPolicyBenchmarkMethodologyActivationModel,
]


def _active_token() -> object:
    token = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.get()
    if token is None:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation append requires an active private unit of work"
        )
    return token


def _validate_subject(value: object) -> PolicyBenchmarkMethodologyActivationSubject:
    if type(value) is not PolicyBenchmarkMethodologyActivationSubject:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation subject type substitution"
        )
    try:
        PolicyBenchmarkMethodologyActivationSubject.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation subject is invalid"
        ) from error
    return value


def _validate_activation(value: object) -> PolicyBenchmarkMethodologyBundleActivation:
    if type(value) is not PolicyBenchmarkMethodologyBundleActivation:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation type substitution"
        )
    try:
        PolicyBenchmarkMethodologyBundleActivation.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation is invalid"
        ) from error
    return value


def _exact_subject(
    rows: tuple[SubjectState, ...], value: PolicyBenchmarkMethodologyActivationSubject
) -> SubjectState | None:
    identity = _identity_hash("subject", value.subject_id, value.subject_version)
    candidates = tuple(
        item
        for item in rows
        if (item[0].subject_id, item[0].subject_version)
        == (value.subject_id, value.subject_version)
        or _identity_hash("subject", item[0].subject_id, item[0].subject_version) == identity
        or item[0].content_hash == value.content_hash
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == value)
    if len(candidates) != 1 or len(matches) != 1:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation subject anchor has another first winner"
        )
    return matches[0]


def _exact_activation(
    rows: tuple[ActivationState, ...], value: PolicyBenchmarkMethodologyBundleActivation
) -> ActivationState | None:
    identity = _identity_hash("activation", value.activation_id, value.activation_version)
    candidates = tuple(
        item
        for item in rows
        if (item[0].activation_id, item[0].activation_version)
        == (value.activation_id, value.activation_version)
        or _identity_hash("activation", item[0].activation_id, item[0].activation_version)
        == identity
        or item[0].content_hash == value.content_hash
        or item[0].subject.content_hash == value.subject.content_hash
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == value)
    if len(candidates) != 1 or len(matches) != 1:
        raise PolicyBenchmarkMethodologyActivationConflict(
            "methodology activation anchor has another first winner"
        )
    return matches[0]


def _definition_structural_head(
    rows: tuple[ActivationState, ...], definition_id: str
) -> ActivationState | None:
    values = tuple(item for item in rows if item[0].subject.definition_id == definition_id)
    if not values:
        return None
    predecessors = {
        item[0].subject.supersedes_activation_hash
        for item in values
        if item[0].subject.supersedes_activation_hash is not None
    }
    heads = tuple(item for item in values if item[0].content_hash not in predecessors)
    if len(heads) != 1:
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "methodology activation structural head is ambiguous"
        )
    return heads[0]


def _validate_chain(rows: tuple[ActivationState, ...]) -> None:
    by_hash = {item[0].content_hash: item[0] for item in rows}
    if len(by_hash) != len(rows):
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "methodology activation content anchor is ambiguous"
        )
    for definition_id in {item[0].subject.definition_id for item in rows}:
        values = tuple(item[0] for item in rows if item[0].subject.definition_id == definition_id)
        roots = tuple(value for value in values if value.subject.supersedes_activation_hash is None)
        if len(roots) != 1:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation definition root is ambiguous"
            )
        try:
            validate_policy_benchmark_methodology_activation_root(roots[0])
        except (TypeError, ValueError) as error:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology activation root is invalid"
            ) from error
        seen: set[str] = set()
        for value in values:
            predecessor_hash = value.subject.supersedes_activation_hash
            if predecessor_hash is None:
                continue
            if predecessor_hash in seen:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "methodology activation chain is forked"
                )
            seen.add(predecessor_hash)
            predecessor = by_hash.get(predecessor_hash)
            if predecessor is None:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "methodology activation predecessor is orphaned"
                )
            try:
                validate_policy_benchmark_methodology_activation_successor(predecessor, value)
            except (TypeError, ValueError) as error:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "methodology activation successor chain is invalid"
                ) from error
        _definition_structural_head(rows, definition_id)


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


def _ref_hash(value: PolicyBenchmarkMethodologyRef) -> str:
    return _hash(value.to_payload())


def _refs_hash(value: PolicyBenchmarkMethodologyActivationSubject) -> str:
    return _hash({"methodology_refs": [ref.to_payload() for ref in value.bundle.methodology_refs]})


def _ref_hashes(value: PolicyBenchmarkMethodologyActivationSubject) -> tuple[str, ...]:
    return tuple(_ref_hash(ref) for ref in value.bundle.methodology_refs)


def _subject_ledger_hash(
    value: PolicyBenchmarkMethodologyActivationSubject, recorded_at: datetime
) -> str:
    return _hash(
        {
            "identity_hash": _identity_hash("subject", value.subject_id, value.subject_version),
            "content_hash": value.content_hash,
            "definition_identity_hash": value.definition_identity_hash,
            "definition_content_hash": value.definition_content_hash,
            "methodology_refs_hash": _refs_hash(value),
            "methodology_bundle_hash": value.bundle.bundle_hash,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _activation_ledger_hash(
    value: PolicyBenchmarkMethodologyBundleActivation, recorded_at: datetime
) -> str:
    return _hash(
        {
            "identity_hash": _identity_hash(
                "activation", value.activation_id, value.activation_version
            ),
            "content_hash": value.content_hash,
            "subject_content_hash": value.subject.content_hash,
            "definition_content_hash": value.subject.definition_content_hash,
            "methodology_bundle_hash": value.subject.bundle.bundle_hash,
            "predecessor_hash": value.subject.supersedes_activation_hash,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _actor_headers(value: PolicyBenchmarkMethodologyActivationActor) -> tuple[object, ...]:
    return (
        value.actor_id,
        value.user_id,
        value.role,
        value.kind,
        value.is_staff,
        value.authentication_source,
    )


def _subject_values(
    value: PolicyBenchmarkMethodologyActivationSubject, recorded_at: datetime
) -> dict[str, object]:
    actor = value.requested_by
    ref_hashes = _ref_hashes(value)
    return {
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "subject_identity_hash": _identity_hash("subject", value.subject_id, value.subject_version),
        "definition_id": value.definition_id,
        "definition_version": value.definition_version,
        "definition_identity_hash": value.definition_identity_hash,
        "definition_content_hash": value.definition_content_hash,
        "definition_recorded_at": value.definition_recorded_at,
        "definition_valid_until": value.definition_valid_until,
        "methodology_count": len(value.bundle.methodology_refs),
        "methodology_refs_hash": _refs_hash(value),
        "methodology_bundle_hash": value.bundle.bundle_hash,
        "corporate_action_ref_hash": ref_hashes[0],
        "cost_tax_ref_hash": ref_hashes[1],
        "fx_fixing_ref_hash": ref_hashes[2],
        "price_fixing_ref_hash": ref_hashes[3],
        "trading_calendar_ref_hash": ref_hashes[4],
        "requested_actor_id": actor.actor_id,
        "requested_actor_user_id": actor.user_id,
        "requested_actor_role": actor.role,
        "requested_actor_kind": actor.kind,
        "requested_actor_is_staff": actor.is_staff,
        "requested_actor_authentication_source": actor.authentication_source,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "supersedes_activation_hash": value.supersedes_activation_hash,
        "clock_source": value.clock_source,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_policy_benchmark_methodology_activation_subject(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _subject_ledger_hash(value, recorded_at),
    }


def _activation_values(
    value: PolicyBenchmarkMethodologyBundleActivation, recorded_at: datetime
) -> dict[str, object]:
    subject = value.subject
    requester = subject.requested_by
    approver = value.approved_by
    return {
        "owner": value.owner,
        "capability": value.capability,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "clock_source": value.clock_source,
        "activation_id": value.activation_id,
        "activation_version": value.activation_version,
        "activation_identity_hash": _identity_hash(
            "activation", value.activation_id, value.activation_version
        ),
        "subject_id": subject.subject_id,
        "subject_version": subject.subject_version,
        "subject_content_hash": subject.content_hash,
        "definition_id": subject.definition_id,
        "definition_version": subject.definition_version,
        "definition_identity_hash": subject.definition_identity_hash,
        "definition_content_hash": subject.definition_content_hash,
        "methodology_refs_hash": _refs_hash(subject),
        "methodology_bundle_hash": subject.bundle.bundle_hash,
        "requested_actor_id": requester.actor_id,
        "requested_actor_user_id": requester.user_id,
        "requested_actor_role": requester.role,
        "requested_actor_kind": requester.kind,
        "requested_actor_is_staff": requester.is_staff,
        "requested_actor_authentication_source": requester.authentication_source,
        "approved_actor_id": approver.actor_id,
        "approved_actor_user_id": approver.user_id,
        "approved_actor_role": approver.role,
        "approved_actor_kind": approver.kind,
        "approved_actor_is_staff": approver.is_staff,
        "approved_actor_authentication_source": approver.authentication_source,
        "issued_at": value.issued_at,
        "valid_until": value.valid_until,
        "predecessor_hash": subject.supersedes_activation_hash,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_policy_benchmark_methodology_activation(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _activation_ledger_hash(value, recorded_at),
    }


def _subject_headers(
    value: PolicyBenchmarkMethodologyActivationSubject,
) -> tuple[object, ...]:
    return (
        value.subject_id,
        value.subject_version,
        value.definition_id,
        value.definition_version,
        value.definition_identity_hash,
        value.definition_content_hash,
        value.definition_recorded_at,
        value.definition_valid_until,
        len(value.bundle.methodology_refs),
        _refs_hash(value),
        value.bundle.bundle_hash,
        *_ref_hashes(value),
        *_actor_headers(value.requested_by),
        value.requested_at,
        value.valid_until,
        value.supersedes_activation_hash,
        value.clock_source,
        value.content_hash,
    )


def _subject_model_headers(
    model: PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
) -> tuple[object, ...]:
    return (
        model.subject_id,
        model.subject_version,
        model.definition_id,
        model.definition_version,
        model.definition_identity_hash,
        model.definition_content_hash,
        model.definition_recorded_at,
        model.definition_valid_until,
        model.methodology_count,
        model.methodology_refs_hash,
        model.methodology_bundle_hash,
        model.corporate_action_ref_hash,
        model.cost_tax_ref_hash,
        model.fx_fixing_ref_hash,
        model.price_fixing_ref_hash,
        model.trading_calendar_ref_hash,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.requested_actor_kind,
        model.requested_actor_is_staff,
        model.requested_actor_authentication_source,
        model.requested_at,
        model.valid_until,
        model.supersedes_activation_hash,
        model.clock_source,
        model.content_hash,
    )


def _activation_headers(
    value: PolicyBenchmarkMethodologyBundleActivation,
) -> tuple[object, ...]:
    subject = value.subject
    return (
        value.owner,
        value.capability,
        value.artifact_type,
        value.schema,
        value.permission,
        value.clock_source,
        value.activation_id,
        value.activation_version,
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
        subject.definition_id,
        subject.definition_version,
        subject.definition_identity_hash,
        subject.definition_content_hash,
        _refs_hash(subject),
        subject.bundle.bundle_hash,
        *_actor_headers(subject.requested_by),
        *_actor_headers(value.approved_by),
        value.issued_at,
        value.valid_until,
        subject.supersedes_activation_hash,
        value.content_hash,
    )


def _activation_model_headers(
    model: PortfolioPolicyBenchmarkMethodologyActivationModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.capability,
        model.artifact_type,
        model.schema,
        model.permission,
        model.clock_source,
        model.activation_id,
        model.activation_version,
        model.subject_id,
        model.subject_version,
        model.subject_content_hash,
        model.definition_id,
        model.definition_version,
        model.definition_identity_hash,
        model.definition_content_hash,
        model.methodology_refs_hash,
        model.methodology_bundle_hash,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.requested_actor_kind,
        model.requested_actor_is_staff,
        model.requested_actor_authentication_source,
        model.approved_actor_id,
        model.approved_actor_user_id,
        model.approved_actor_role,
        model.approved_actor_kind,
        model.approved_actor_is_staff,
        model.approved_actor_authentication_source,
        model.issued_at,
        model.valid_until,
        model.predecessor_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkMethodologyActivationClock",
    "DjangoPolicyBenchmarkMethodologyActivationRepository",
    "PolicyBenchmarkMethodologyActivationClock",
]
