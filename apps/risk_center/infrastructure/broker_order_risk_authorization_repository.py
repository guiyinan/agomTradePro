"""Strict append-only persistence for Broker order risk authorizations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationConflict,
    BrokerOrderRiskAuthorizationCorruption,
    BrokerOrderRiskAuthorizationUnavailable,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
    broker_order_risk_authorization_identity_hash,
    broker_order_risk_subject_identity_hash,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_codec import (
    BrokerOrderRiskAuthorizationCodecError,
    decode_broker_order_risk_authorization_record,
    decode_broker_order_risk_authorization_subject,
    encode_broker_order_risk_authorization_record,
    encode_broker_order_risk_authorization_subject,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_models import (
    _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW,
    BrokerOrderRiskAuthorizationRecordModel,
    BrokerOrderRiskAuthorizationSubjectModel,
    _activate_broker_order_risk_authorization_uow,
    _claim_broker_order_risk_authorization_insert,
)


class BrokerOrderRiskAuthorizationClock(Protocol):
    """Authoritative persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerOrderRiskAuthorizationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerOrderRiskAuthorizationRepository:
    """Private append store and strict identity/hash/PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerOrderRiskAuthorizationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerOrderRiskAuthorizationClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private first-winner transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_broker_order_risk_authorization_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Risk Center clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BrokerOrderRiskAuthorizationCorruption(
                "Risk Center Broker order authorization clock is naive"
            )
        return value

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationSubject | None:
        """Return one immutable subject identity winner knowable at the cutoff."""

        self._require_cutoff(as_of)
        seal = broker_order_risk_subject_identity_hash(subject_id)
        rows = list(
            BrokerOrderRiskAuthorizationSubjectModel._default_manager.using(self._using).filter(
                Q(subject_id=subject_id, subject_version=subject_version)
                | Q(subject_identity_hash=seal)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_subject(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.subject_id == subject_id and value.subject_version == subject_version
        )
        if len(matches) != 1:
            raise BrokerOrderRiskAuthorizationCorruption("risk subject identity is ambiguous")
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def get_exact(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationSubject | None:
        """Implement the exact subject provider contract."""

        value = self.get_subject_winner(
            subject_id=subject_id, subject_version=subject_version, as_of=as_of
        )
        return value if value is not None and value.is_valid_at(as_of) else None

    def get_authorization_winner(
        self, *, authorization_id: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return one immutable authorization identity winner."""

        self._require_cutoff(as_of)
        seal = broker_order_risk_authorization_identity_hash(authorization_id)
        rows = list(
            BrokerOrderRiskAuthorizationRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(Q(authorization_id=authorization_id) | Q(authorization_identity_hash=seal))
        )
        if not rows:
            return None
        values = tuple(self._restore_record(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.authorization_id == authorization_id
        )
        if len(matches) != 1:
            raise BrokerOrderRiskAuthorizationCorruption("risk authorization identity is ambiguous")
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def get_current_head(
        self, *, account_id: int, order_id: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return the unique chain head knowable at one cutoff."""

        self._require_cutoff(as_of)
        rows = list(
            BrokerOrderRiskAuthorizationRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(recorded_at__lte=as_of)
        )
        all_values = tuple(self._restore_record(row) for row in rows)
        values = tuple(
            value
            for value in all_values
            if value.subject.scope.account_id == account_id
            and value.subject.scope.order_id == order_id
        )
        if not values:
            return None
        by_hash = {value.content_hash: value for value in values}
        roots = tuple(
            value for value in values if value.subject.supersedes_authorization_hash is None
        )
        if len(roots) != 1:
            raise BrokerOrderRiskAuthorizationCorruption(
                "Broker order risk authorization chain must have exactly one root"
            )
        children: dict[str, BrokerOrderRiskAuthorizationRecord] = {}
        for value in values:
            predecessor_hash = value.subject.supersedes_authorization_hash
            if predecessor_hash is None:
                continue
            predecessor = by_hash.get(predecessor_hash)
            if predecessor is None:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "Broker order risk authorization chain has an orphan predecessor"
                )
            if predecessor.issued_at >= value.issued_at:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "Broker order risk authorization chain clock is not monotonic"
                )
            if predecessor_hash in children:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "Broker order risk authorization chain has a fork"
                )
            children[predecessor_hash] = value
        reachable: set[str] = set()
        cursor = roots[0]
        while cursor.content_hash not in reachable:
            reachable.add(cursor.content_hash)
            successor = children.get(cursor.content_hash)
            if successor is None:
                break
            cursor = successor
        if len(reachable) != len(values):
            raise BrokerOrderRiskAuthorizationCorruption(
                "Broker order risk authorization chain is disconnected or cyclic"
            )
        heads = tuple(value for value in values if value.content_hash not in children)
        if len(heads) != 1:
            raise BrokerOrderRiskAuthorizationCorruption(
                "Broker order risk authorization chain has multiple heads"
            )
        return heads[0]

    def append_subject(
        self, subject: BrokerOrderRiskAuthorizationSubject, *, recorded_at: datetime
    ) -> BrokerOrderRiskAuthorizationSubject:
        """Append or return one exact subject first winner."""

        if recorded_at != subject.requested_at:
            raise BrokerOrderRiskAuthorizationConflict(
                "risk subject must use the authoritative transaction clock"
            )
        _active_token()
        existing = self._exact_subject_model(subject)
        if existing is not None:
            return self._restore_subject(existing)
        values = _subject_values(subject, recorded_at=recorded_at)
        model = BrokerOrderRiskAuthorizationSubjectModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_broker_order_risk_authorization_insert(
                    token=_active_token(),
                    model_type=BrokerOrderRiskAuthorizationSubjectModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_subject_model(subject)
            if winner is None:
                raise BrokerOrderRiskAuthorizationConflict(
                    "risk subject append conflicted without an exact first winner"
                ) from None
            return self._restore_subject(winner)
        return self._restore_subject(model)

    def append(
        self,
        record: BrokerOrderRiskAuthorizationRecord,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerOrderRiskAuthorizationRecord:
        """Append one authorization using current-head compare-and-swap."""

        if recorded_at != record.issued_at:
            raise BrokerOrderRiskAuthorizationConflict(
                "risk authorization must use the authoritative transaction clock"
            )
        if record.subject.supersedes_authorization_hash != expected_predecessor_hash:
            raise BrokerOrderRiskAuthorizationConflict("authorization predecessor mismatch")
        _active_token()
        current = self.get_current_head(
            account_id=record.subject.scope.account_id,
            order_id=record.subject.scope.order_id,
            as_of=recorded_at,
        )
        if (current.content_hash if current else None) != expected_predecessor_hash:
            raise BrokerOrderRiskAuthorizationConflict("authorization current head changed")
        subject_model = self._exact_subject_model(record.subject)
        if subject_model is None:
            raise BrokerOrderRiskAuthorizationConflict(
                "authorization requires its registered exact subject"
            )
        values = _record_values(record, recorded_at=recorded_at)
        claimed = {**values, "subject_id": subject_model.pk}
        model = BrokerOrderRiskAuthorizationRecordModel(**claimed)
        try:
            with transaction.atomic(using=self._using):
                with _claim_broker_order_risk_authorization_insert(
                    token=_active_token(),
                    model_type=BrokerOrderRiskAuthorizationRecordModel,
                    expected_values=claimed,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_record_model(record)
            if winner is None:
                raise BrokerOrderRiskAuthorizationConflict(
                    "authorization append conflicted without a visible first winner"
                ) from None
            return self._restore_record(winner)
        return self._restore_record(model)

    def get_exact_by_hash(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return an exact valid authorization by identity, hash, and PIT cutoff."""

        self._require_cutoff(as_of)
        seal = broker_order_risk_authorization_identity_hash(authorization_id)
        rows = list(
            BrokerOrderRiskAuthorizationRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(
                Q(authorization_id=authorization_id, authorization_version=authorization_version)
                | Q(authorization_identity_hash=seal)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_record(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.authorization_id == authorization_id
            and value.authorization_version == authorization_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            raise BrokerOrderRiskAuthorizationCorruption(
                "exact risk authorization identity/hash mismatch"
            )
        value, row = matches[0]
        if row.recorded_at > as_of or not value.is_valid_at(as_of):
            return None
        return value

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise BrokerOrderRiskAuthorizationUnavailable("authorization as_of is naive")
        if as_of > self.now():
            raise BrokerOrderRiskAuthorizationUnavailable(
                "future authorization as_of is not permitted"
            )

    def _exact_subject_model(
        self, subject: BrokerOrderRiskAuthorizationSubject
    ) -> BrokerOrderRiskAuthorizationSubjectModel | None:
        seal = broker_order_risk_subject_identity_hash(subject.subject_id)
        rows = list(
            BrokerOrderRiskAuthorizationSubjectModel._default_manager.using(self._using).filter(
                Q(subject_id=subject.subject_id, subject_version=subject.subject_version)
                | Q(subject_identity_hash=seal)
                | Q(content_hash=subject.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore_subject(row) == subject)
        if len(rows) != 1 or len(matches) != 1:
            raise BrokerOrderRiskAuthorizationConflict(
                "risk subject uniqueness anchor has another first winner"
            )
        return matches[0]

    def _exact_record_model(
        self, record: BrokerOrderRiskAuthorizationRecord
    ) -> BrokerOrderRiskAuthorizationRecordModel | None:
        seal = broker_order_risk_authorization_identity_hash(record.authorization_id)
        rows = list(
            BrokerOrderRiskAuthorizationRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(
                Q(
                    authorization_id=record.authorization_id,
                    authorization_version=record.authorization_version,
                )
                | Q(authorization_identity_hash=seal)
                | Q(content_hash=record.content_hash)
                | Q(subject_hash=record.subject.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore_record(row) == record)
        if len(rows) != 1 or len(matches) != 1:
            raise BrokerOrderRiskAuthorizationConflict(
                "risk authorization uniqueness anchor has another first winner"
            )
        return matches[0]

    def _restore_subject(
        self, model: BrokerOrderRiskAuthorizationSubjectModel
    ) -> BrokerOrderRiskAuthorizationSubject:
        try:
            value = decode_broker_order_risk_authorization_subject(model.canonical_payload)
        except BrokerOrderRiskAuthorizationCodecError as error:
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk subject payload cannot be restored"
            ) from error
        if _subject_headers(value) != _subject_model_headers(model):
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk subject headers do not match payload"
            )
        if model.subject_identity_hash != broker_order_risk_subject_identity_hash(value.subject_id):
            raise BrokerOrderRiskAuthorizationCorruption("risk subject identity seal is invalid")
        if model.ledger_header_hash != _subject_ledger_hash(value, model.recorded_at):
            raise BrokerOrderRiskAuthorizationCorruption("risk subject ledger seal is invalid")
        if model.persisted_at < model.recorded_at:
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk subject persistence clock is invalid"
            )
        return value

    def _restore_record(
        self, model: BrokerOrderRiskAuthorizationRecordModel
    ) -> BrokerOrderRiskAuthorizationRecord:
        subject = self._restore_subject(model.subject)
        try:
            value = decode_broker_order_risk_authorization_record(model.canonical_payload)
        except BrokerOrderRiskAuthorizationCodecError as error:
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization payload cannot be restored"
            ) from error
        if value.subject != subject or _record_headers(value) != _record_model_headers(model):
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization headers do not match payload"
            )
        if model.authorization_identity_hash != broker_order_risk_authorization_identity_hash(
            value.authorization_id
        ):
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization identity seal is invalid"
            )
        if model.ledger_header_hash != _record_ledger_hash(value, model.recorded_at):
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization ledger seal is invalid"
            )
        if model.subject.recorded_at > model.recorded_at or value.issued_at != model.recorded_at:
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization persistence clock is invalid"
            )
        if model.persisted_at < model.recorded_at:
            raise BrokerOrderRiskAuthorizationCorruption(
                "risk authorization persistence clock is invalid"
            )
        return value


def _active_token() -> object:
    token = _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW.get()
    if token is None:
        raise BrokerOrderRiskAuthorizationConflict(
            "authorization append requires an active private unit of work"
        )
    return token


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject_ledger_hash(value: BrokerOrderRiskAuthorizationSubject, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity": broker_order_risk_subject_identity_hash(value.subject_id),
            "content": value.content_hash,
            "recorded_at": _time(recorded_at),
        }
    )


def _record_ledger_hash(value: BrokerOrderRiskAuthorizationRecord, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity": broker_order_risk_authorization_identity_hash(value.authorization_id),
            "content": value.content_hash,
            "subject": value.subject.content_hash,
            "recorded_at": _time(recorded_at),
        }
    )


def _subject_values(
    value: BrokerOrderRiskAuthorizationSubject, *, recorded_at: datetime
) -> dict[str, object]:
    actor = value.requested_by
    return {
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "subject_identity_hash": broker_order_risk_subject_identity_hash(value.subject_id),
        "account_id": value.scope.account_id,
        "order_id": value.scope.order_id,
        "scope_content_hash": value.scope.content_hash,
        "supersedes_authorization_hash": value.supersedes_authorization_hash,
        "requested_actor_id": actor.actor_id,
        "requested_actor_kind": actor.kind.value,
        "requested_actor_is_staff": actor.is_staff,
        "requested_actor_user_id": actor.user_id,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_broker_order_risk_authorization_subject(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _subject_ledger_hash(value, recorded_at),
    }


def _record_values(
    value: BrokerOrderRiskAuthorizationRecord, *, recorded_at: datetime
) -> dict[str, object]:
    actor = value.approved_by
    return {
        "owner": value.owner,
        "capability": value.capability,
        "permission_cap": value.permission_cap,
        "authorization_id": value.authorization_id,
        "authorization_version": value.authorization_version,
        "authorization_identity_hash": broker_order_risk_authorization_identity_hash(
            value.authorization_id
        ),
        "subject_hash": value.subject.content_hash,
        "account_id": value.subject.scope.account_id,
        "order_id": value.subject.scope.order_id,
        "supersedes_authorization_hash": value.subject.supersedes_authorization_hash,
        "approved_actor_id": actor.actor_id,
        "approved_actor_kind": actor.kind.value,
        "approved_actor_is_staff": actor.is_staff,
        "approved_actor_user_id": actor.user_id,
        "issued_at": value.issued_at,
        "valid_until": value.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_broker_order_risk_authorization_record(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _record_ledger_hash(value, recorded_at),
    }


def _subject_headers(value: BrokerOrderRiskAuthorizationSubject) -> tuple[object, ...]:
    actor = value.requested_by
    return (
        value.subject_id,
        value.subject_version,
        value.scope.account_id,
        value.scope.order_id,
        value.scope.content_hash,
        value.supersedes_authorization_hash,
        actor.actor_id,
        actor.kind.value,
        actor.is_staff,
        actor.user_id,
        value.requested_at,
        value.valid_until,
        value.content_hash,
    )


def _subject_model_headers(model: BrokerOrderRiskAuthorizationSubjectModel) -> tuple[object, ...]:
    return (
        model.subject_id,
        model.subject_version,
        model.account_id,
        model.order_id,
        model.scope_content_hash,
        model.supersedes_authorization_hash,
        model.requested_actor_id,
        model.requested_actor_kind,
        model.requested_actor_is_staff,
        model.requested_actor_user_id,
        model.requested_at,
        model.valid_until,
        model.content_hash,
    )


def _record_headers(value: BrokerOrderRiskAuthorizationRecord) -> tuple[object, ...]:
    actor = value.approved_by
    return (
        value.owner,
        value.capability,
        value.permission_cap,
        value.authorization_id,
        value.authorization_version,
        value.subject.content_hash,
        value.subject.scope.account_id,
        value.subject.scope.order_id,
        value.subject.supersedes_authorization_hash,
        actor.actor_id,
        actor.kind.value,
        actor.is_staff,
        actor.user_id,
        value.issued_at,
        value.valid_until,
        value.content_hash,
    )


def _record_model_headers(model: BrokerOrderRiskAuthorizationRecordModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.capability,
        model.permission_cap,
        model.authorization_id,
        model.authorization_version,
        model.subject_hash,
        model.account_id,
        model.order_id,
        model.supersedes_authorization_hash,
        model.approved_actor_id,
        model.approved_actor_kind,
        model.approved_actor_is_staff,
        model.approved_actor_user_id,
        model.issued_at,
        model.valid_until,
        model.content_hash,
    )


__all__ = [
    "BrokerOrderRiskAuthorizationClock",
    "DjangoBrokerOrderRiskAuthorizationClock",
    "DjangoBrokerOrderRiskAuthorizationRepository",
]
