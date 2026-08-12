"""Strict append-only persistence for approved Evidence operator specs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecConflict,
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecUnavailable,
)
from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecApprovalReceipt,
)
from apps.research.infrastructure.evidence_models import (
    _ACTIVE_EVIDENCE_UOW,
    _activate_evidence_uow,
    _claim_evidence_insert,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_codec import (
    EvidenceOperatorSpecLifecycleCodecError,
    decode_activated_operator_spec,
    decode_operator_spec_approval,
    encode_activated_operator_spec,
    encode_operator_spec_approval,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_models import (
    ActivatedEvidenceOperatorSpecModel,
    EvidenceOperatorSpecApprovalReceiptModel,
)


class EvidenceOperatorSpecClock(Protocol):
    """Authoritative Research persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoEvidenceOperatorSpecClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoEvidenceOperatorSpecLifecycleRepository:
    """Private activation store and public exact/PIT read repository."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceOperatorSpecClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoEvidenceOperatorSpecClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open the private all-or-nothing activation append boundary."""

        token = object()
        with transaction.atomic(using=self._using), _activate_evidence_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Research clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise EvidenceOperatorSpecCorruption("Research operator spec clock is naive")
        return value

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Restore an identity for private idempotency without caller hash input."""

        self._require_cutoff(as_of)
        models = list(
            ActivatedEvidenceOperatorSpecModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(operator_id=operator_id, operator_version=operator_version)
                | Q(
                    approval__operator_id=operator_id,
                    approval__operator_version=operator_version,
                )
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.operator_spec.operator_id == operator_id
            and record.operator_spec.operator_version == operator_version
        )
        if len(matches) != 1:
            raise EvidenceOperatorSpecCorruption(
                "operator specification activation identity is ambiguous"
            )
        return matches[0] if matches[0].recorded_at <= as_of else None

    def get_exact_by_hash(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Restore by identity and hash, rejecting header-based hiding attacks."""

        self._require_cutoff(as_of)
        models = list(
            ActivatedEvidenceOperatorSpecModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(operator_id=operator_id, operator_version=operator_version)
                | Q(
                    approval__operator_id=operator_id,
                    approval__operator_version=operator_version,
                )
                | Q(content_hash=expected_content_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.operator_spec.operator_id == operator_id
            and record.operator_spec.operator_version == operator_version
            and record.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            raise EvidenceOperatorSpecCorruption(
                "exact operator specification activation does not match its headers"
            )
        return matches[0] if matches[0].recorded_at <= as_of else None

    def get_head(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Replay one complete knowable supersession chain and return its head."""

        self._require_cutoff(as_of)
        models = list(
            ActivatedEvidenceOperatorSpecModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(operator_id=operator_id) | Q(approval__operator_id=operator_id),
                recorded_at__lte=as_of,
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        if any(record.operator_spec.operator_id != operator_id for record in records):
            raise EvidenceOperatorSpecCorruption(
                "operator specification chain contains a substituted identity"
            )
        return self._replay_head(records)

    def get_active(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec:
        """Return the active chain head; absent and expired state fail closed."""

        head = self.get_head(operator_id=operator_id, as_of=as_of)
        if head is None or not head.is_active_at(as_of):
            raise EvidenceOperatorSpecUnavailable(
                "no approved operator specification is active at the PIT cutoff"
            )
        return head

    def append_graph(
        self,
        record: ActivatedEvidenceOperatorSpec,
    ) -> ActivatedEvidenceOperatorSpec:
        """Append receipt plus activation under exact claims or recover a winner."""

        approval_values = _approval_values(record.approval, record.recorded_at)
        activation_values = _activation_values(record)
        try:
            with transaction.atomic(using=self._using):
                approval_model = EvidenceOperatorSpecApprovalReceiptModel(**approval_values)
                with _claim_evidence_insert(
                    token=_active_token(),
                    model_type=EvidenceOperatorSpecApprovalReceiptModel,
                    expected_values=approval_values,
                ):
                    approval_model.save(force_insert=True, using=self._using)
                activation_values_with_fk: dict[str, object] = {
                    **activation_values,
                    "approval_id": approval_model.pk,
                }
                activation_model = ActivatedEvidenceOperatorSpecModel(**activation_values_with_fk)
                with _claim_evidence_insert(
                    token=_active_token(),
                    model_type=ActivatedEvidenceOperatorSpecModel,
                    expected_values=activation_values_with_fk,
                ):
                    activation_model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self.get_exact(
                operator_id=record.operator_spec.operator_id,
                operator_version=record.operator_spec.operator_version,
                as_of=self.now(),
            )
            if winner is None:
                raise EvidenceOperatorSpecConflict(
                    "operator specification activation append conflicted without a winner"
                ) from None
            return winner
        return self._restore(activation_model)

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise EvidenceOperatorSpecUnavailable("operator specification as_of is naive")
        if as_of > self.now():
            raise EvidenceOperatorSpecUnavailable(
                "future operator specification as_of is not permitted"
            )

    def _restore(
        self,
        model: ActivatedEvidenceOperatorSpecModel,
    ) -> ActivatedEvidenceOperatorSpec:
        approval_model = model.approval
        try:
            approval = decode_operator_spec_approval(approval_model.canonical_payload)
            record = decode_activated_operator_spec(model.canonical_payload)
        except EvidenceOperatorSpecLifecycleCodecError as error:
            raise EvidenceOperatorSpecCorruption(
                "operator specification lifecycle payload cannot be restored"
            ) from error
        if record.approval != approval:
            raise EvidenceOperatorSpecCorruption(
                "operator specification activation/approval payload substitution"
            )
        if _approval_headers(approval, record.recorded_at) != _approval_model_headers(
            approval_model
        ):
            raise EvidenceOperatorSpecCorruption(
                "operator specification approval headers do not match payload"
            )
        if _activation_headers(record) != _activation_model_headers(model):
            raise EvidenceOperatorSpecCorruption(
                "operator specification activation headers do not match payload"
            )
        if approval_model.ledger_header_hash != _approval_header_hash(
            approval,
            record.recorded_at,
        ):
            raise EvidenceOperatorSpecCorruption(
                "operator specification approval ledger seal is invalid"
            )
        if model.ledger_header_hash != _activation_header_hash(record):
            raise EvidenceOperatorSpecCorruption(
                "operator specification activation ledger seal is invalid"
            )
        if model.approval_id != approval_model.pk:
            raise EvidenceOperatorSpecCorruption(
                "operator specification approval foreign key is invalid"
            )
        return record

    @staticmethod
    def _replay_head(
        records: tuple[ActivatedEvidenceOperatorSpec, ...],
    ) -> ActivatedEvidenceOperatorSpec:
        by_hash = {record.content_hash: record for record in records}
        if len(by_hash) != len(records):
            raise EvidenceOperatorSpecCorruption(
                "operator specification chain contains duplicate activation hashes"
            )
        roots = tuple(
            record for record in records if record.definition.supersedes_activation_hash is None
        )
        if len(roots) != 1:
            raise EvidenceOperatorSpecCorruption(
                "operator specification chain must have exactly one root"
            )
        children: dict[str, list[ActivatedEvidenceOperatorSpec]] = {}
        for record in records:
            predecessor = record.definition.supersedes_activation_hash
            if predecessor is not None:
                if predecessor not in by_hash:
                    raise EvidenceOperatorSpecCorruption(
                        "operator specification chain has an orphan activation"
                    )
                children.setdefault(predecessor, []).append(record)
        current = roots[0]
        visited = {current.content_hash}
        while current.content_hash in children:
            candidates = children[current.content_hash]
            if len(candidates) != 1:
                raise EvidenceOperatorSpecCorruption("operator specification chain contains a fork")
            current = candidates[0]
            if current.content_hash in visited:
                raise EvidenceOperatorSpecCorruption(
                    "operator specification chain contains a cycle"
                )
            visited.add(current.content_hash)
        if len(visited) != len(records):
            raise EvidenceOperatorSpecCorruption(
                "operator specification chain contains a disconnected activation"
            )
        return current


def _active_token() -> object:
    """Read the active private Evidence UoW without exporting mutation authority."""

    token = _ACTIVE_EVIDENCE_UOW.get()
    if token is None:
        raise EvidenceOperatorSpecConflict(
            "operator specification append requires an active unit of work"
        )
    return token


def _approval_header_hash(
    approval: EvidenceOperatorSpecApprovalReceipt,
    recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "approval_hash": approval.content_hash,
            "recorded_at": _datetime_text(recorded_at),
        }
    )


def _activation_header_hash(record: ActivatedEvidenceOperatorSpec) -> str:
    return _hash_payload(
        {
            "activation_hash": record.content_hash,
            "definition_hash": record.definition.content_hash,
            "approval_hash": record.approval.content_hash,
            "recorded_at": _datetime_text(record.recorded_at),
            "supersedes_activation_hash": record.definition.supersedes_activation_hash,
        }
    )


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _datetime_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _approval_values(
    approval: EvidenceOperatorSpecApprovalReceipt,
    recorded_at: datetime,
) -> dict[str, object]:
    return {
        "approval_id": approval.approval_id,
        "approval_version": approval.approval_version,
        "owner_record_id": approval.owner_record_id,
        "owner_record_version": approval.owner_record_version,
        "owner_record_hash": approval.owner_record_hash,
        "operator_id": approval.operator_id,
        "operator_version": approval.operator_version,
        "definition_hash": approval.definition_hash,
        "supersedes_activation_hash": approval.supersedes_activation_hash,
        "approved_by": approval.approved_by,
        "issued_at": approval.issued_at,
        "valid_until": approval.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_operator_spec_approval(approval),
        "receipt_content_hash": approval.content_hash,
        "ledger_header_hash": _approval_header_hash(approval, recorded_at),
    }


def _activation_values(record: ActivatedEvidenceOperatorSpec) -> dict[str, object]:
    spec = record.operator_spec
    return {
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
        "research_family": spec.research_family,
        "output_artifact_type": spec.output_artifact_type,
        "claim_kind": spec.claim_kind.value,
        "method_kind": spec.method_kind.value,
        "definition_hash": record.definition.content_hash,
        "supersedes_activation_hash": record.definition.supersedes_activation_hash,
        "activated_at": spec.activated_at,
        "valid_until": spec.valid_until,
        "recorded_at": record.recorded_at,
        "canonical_payload": encode_activated_operator_spec(record),
        "content_hash": record.content_hash,
        "ledger_header_hash": _activation_header_hash(record),
    }


def _approval_headers(
    approval: EvidenceOperatorSpecApprovalReceipt,
    recorded_at: datetime,
) -> tuple[object, ...]:
    return (
        approval.approval_id,
        approval.approval_version,
        approval.owner_record_id,
        approval.owner_record_version,
        approval.owner_record_hash,
        approval.operator_id,
        approval.operator_version,
        approval.definition_hash,
        approval.supersedes_activation_hash,
        approval.approved_by,
        approval.issued_at,
        approval.valid_until,
        recorded_at,
        approval.content_hash,
    )


def _approval_model_headers(
    model: EvidenceOperatorSpecApprovalReceiptModel,
) -> tuple[object, ...]:
    return (
        model.approval_id,
        model.approval_version,
        model.owner_record_id,
        model.owner_record_version,
        model.owner_record_hash,
        model.operator_id,
        model.operator_version,
        model.definition_hash,
        model.supersedes_activation_hash,
        model.approved_by,
        model.issued_at,
        model.valid_until,
        model.recorded_at,
        model.receipt_content_hash,
    )


def _activation_headers(record: ActivatedEvidenceOperatorSpec) -> tuple[object, ...]:
    spec = record.operator_spec
    return (
        spec.operator_id,
        spec.operator_version,
        spec.research_family,
        spec.output_artifact_type,
        spec.claim_kind.value,
        spec.method_kind.value,
        record.definition.content_hash,
        record.definition.supersedes_activation_hash,
        spec.activated_at,
        spec.valid_until,
        record.recorded_at,
        record.content_hash,
    )


def _activation_model_headers(
    model: ActivatedEvidenceOperatorSpecModel,
) -> tuple[object, ...]:
    return (
        model.operator_id,
        model.operator_version,
        model.research_family,
        model.output_artifact_type,
        model.claim_kind,
        model.method_kind,
        model.definition_hash,
        model.supersedes_activation_hash,
        model.activated_at,
        model.valid_until,
        model.recorded_at,
        model.content_hash,
    )


__all__ = [
    "DjangoEvidenceOperatorSpecClock",
    "DjangoEvidenceOperatorSpecLifecycleRepository",
    "EvidenceOperatorSpecClock",
]
