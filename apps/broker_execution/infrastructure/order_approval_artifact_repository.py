"""Append-only persistence and exact PIT reads for order approval artifacts."""

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

from apps.broker_execution.domain.order_approval_artifact import BrokerOrderApprovalArtifact
from apps.broker_execution.infrastructure.order_approval_artifact_codec import (
    BrokerOrderApprovalArtifactCodecError,
    decode_broker_order_approval_artifact,
    encode_broker_order_approval_artifact,
)
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW,
    BrokerOrderApprovalArtifactModel,
    _activate_order_approval_artifact_uow,
    _claim_order_approval_artifact_insert,
)


class BrokerOrderApprovalArtifactUnavailable(ValueError):
    """An exact historical artifact is unavailable at a requested cutoff."""


class BrokerOrderApprovalArtifactConflict(ValueError):
    """An immutable identity or content anchor has another first winner."""


class BrokerOrderApprovalArtifactCorruption(ValueError):
    """Persisted artifact data failed an exact integrity check."""


class BrokerOrderApprovalArtifactClock(Protocol):
    """Authoritative Broker persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerOrderApprovalArtifactClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerOrderApprovalArtifactRepository:
    """Private first-winner store and historical exact PIT provider."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerOrderApprovalArtifactClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerOrderApprovalArtifactClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_order_approval_artifact_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Broker clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BrokerOrderApprovalArtifactCorruption("Broker artifact clock is naive")
        return value

    def append(
        self, artifact: BrokerOrderApprovalArtifact, *, recorded_at: datetime
    ) -> BrokerOrderApprovalArtifact:
        """Append or return the exact identity/content first winner."""

        token = _active_token()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise BrokerOrderApprovalArtifactConflict("recorded_at must be timezone-aware")
        if not artifact.approved_at <= recorded_at < artifact.valid_until:
            raise BrokerOrderApprovalArtifactConflict(
                "artifact must be persisted within its approval validity window"
            )
        existing = self._exact_model(artifact)
        if existing is not None:
            return self._restore(existing)
        values = _model_values(artifact, recorded_at=recorded_at)
        model = BrokerOrderApprovalArtifactModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_order_approval_artifact_insert(
                    token=token,
                    model_type=BrokerOrderApprovalArtifactModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(artifact)
            if winner is None:
                raise BrokerOrderApprovalArtifactConflict(
                    "artifact append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_exact(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerOrderApprovalArtifact | None:
        """Return an exact historical artifact; never imply current execution permission."""

        self._require_cutoff(as_of)
        rows = list(
            BrokerOrderApprovalArtifactModel._default_manager.using(self._using).filter(
                Q(artifact_id=artifact_id, artifact_version=artifact_version)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not rows:
            return None
        artifacts = tuple(self._restore(row) for row in rows)
        matches = tuple(
            (artifact, row)
            for artifact, row in zip(artifacts, rows, strict=True)
            if artifact.artifact_id == artifact_id
            and artifact.artifact_version == artifact_version
            and artifact.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            raise BrokerOrderApprovalArtifactCorruption(
                "exact artifact identity/content anchors are ambiguous"
            )
        artifact, row = matches[0]
        if not row.recorded_at <= as_of or not artifact.approved_at <= as_of < artifact.valid_until:
            return None
        return artifact

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise BrokerOrderApprovalArtifactUnavailable("artifact as_of is naive")
        if as_of > self.now():
            raise BrokerOrderApprovalArtifactUnavailable("future artifact as_of is forbidden")

    def _exact_model(
        self, artifact: BrokerOrderApprovalArtifact
    ) -> BrokerOrderApprovalArtifactModel | None:
        rows = list(
            BrokerOrderApprovalArtifactModel._default_manager.using(self._using).filter(
                Q(artifact_id=artifact.artifact_id, artifact_version=artifact.artifact_version)
                | Q(
                    client_order_id=artifact.client_order_id,
                    order_version=artifact.order_version,
                )
                | Q(identity_hash=artifact.identity_hash)
                | Q(content_hash=artifact.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore(row) == artifact)
        if len(rows) != 1 or len(matches) != 1:
            raise BrokerOrderApprovalArtifactConflict(
                "artifact uniqueness anchor has another first winner"
            )
        return matches[0]

    def _restore(self, model: BrokerOrderApprovalArtifactModel) -> BrokerOrderApprovalArtifact:
        try:
            artifact = decode_broker_order_approval_artifact(model.canonical_payload)
        except BrokerOrderApprovalArtifactCodecError as error:
            raise BrokerOrderApprovalArtifactCorruption(
                "artifact canonical payload cannot be restored"
            ) from error
        if _artifact_headers(artifact) != _model_headers(model):
            raise BrokerOrderApprovalArtifactCorruption(
                "artifact headers do not match canonical payload"
            )
        if model.ledger_header_hash != _ledger_header_hash(artifact, recorded_at=model.recorded_at):
            raise BrokerOrderApprovalArtifactCorruption("artifact ledger header seal is invalid")
        if not artifact.approved_at <= model.recorded_at < artifact.valid_until:
            raise BrokerOrderApprovalArtifactCorruption("artifact persistence clocks are invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
        ):
            raise BrokerOrderApprovalArtifactCorruption(
                "artifact database persistence clock is invalid"
            )
        return artifact


def _active_token() -> object:
    token = _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW.get()
    if token is None:
        raise BrokerOrderApprovalArtifactConflict(
            "artifact append requires an active private unit of work"
        )
    return token


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ledger_header_hash(artifact: BrokerOrderApprovalArtifact, *, recorded_at: datetime) -> str:
    actor = artifact.approved_by
    return _hash_payload(
        {
            "identity_hash": artifact.identity_hash,
            "content_hash": artifact.content_hash,
            "approval_digest": artifact.approval_digest,
            "account_id": artifact.account_id,
            "actor_id": actor.actor_id,
            "actor_user_id": actor.user_id,
            "actor_role": actor.role,
            "approved_at": _time(artifact.approved_at),
            "valid_until": _time(artifact.valid_until),
            "recorded_at": _time(recorded_at),
        }
    )


def _model_values(
    artifact: BrokerOrderApprovalArtifact, *, recorded_at: datetime
) -> dict[str, object]:
    actor = artifact.approved_by
    return {
        "owner": artifact.owner,
        "artifact_type": artifact.artifact_type,
        "schema": artifact.schema,
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "client_order_id": artifact.client_order_id,
        "account_id": artifact.account_id,
        "order_version": artifact.order_version,
        "approval_digest": artifact.approval_digest,
        "approved_actor_id": actor.actor_id,
        "approved_actor_user_id": actor.user_id,
        "approved_actor_role": actor.role,
        "approved_at": artifact.approved_at,
        "valid_until": artifact.valid_until,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_broker_order_approval_artifact(artifact),
        "identity_hash": artifact.identity_hash,
        "content_hash": artifact.content_hash,
        "ledger_header_hash": _ledger_header_hash(artifact, recorded_at=recorded_at),
    }


def _artifact_headers(artifact: BrokerOrderApprovalArtifact) -> tuple[object, ...]:
    actor = artifact.approved_by
    return (
        artifact.owner,
        artifact.artifact_type,
        artifact.schema,
        artifact.artifact_id,
        artifact.artifact_version,
        artifact.client_order_id,
        artifact.account_id,
        artifact.order_version,
        artifact.approval_digest,
        actor.actor_id,
        actor.user_id,
        actor.role,
        artifact.approved_at,
        artifact.valid_until,
        artifact.identity_hash,
        artifact.content_hash,
    )


def _model_headers(model: BrokerOrderApprovalArtifactModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        str(model.artifact_id),
        model.artifact_version,
        str(model.client_order_id),
        model.account_id,
        model.order_version,
        model.approval_digest,
        model.approved_actor_id,
        model.approved_actor_user_id,
        model.approved_actor_role,
        model.approved_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "BrokerOrderApprovalArtifactClock",
    "BrokerOrderApprovalArtifactConflict",
    "BrokerOrderApprovalArtifactCorruption",
    "BrokerOrderApprovalArtifactUnavailable",
    "DjangoBrokerOrderApprovalArtifactClock",
    "DjangoBrokerOrderApprovalArtifactRepository",
]
