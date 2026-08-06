"""Transactional append-only repository for R4 rolling research records."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
)

from .r4_rolling_research_models import (
    R4RollingResearchReceiptModel,
    R4RollingResearchResultModel,
    _r4_repository_append_unit,
)
from .r4_rolling_research_payload_codec import (
    artifact_from_payload,
    artifact_to_payload,
    promotion_from_payload,
    promotion_to_payload,
    study_from_payload,
    study_to_payload,
)


class R4RepositoryServerClock(Protocol):
    """Repository-owned source for the immutable recording timestamp."""

    def now(self) -> datetime:
        """Return the current timezone-aware server time."""


class DjangoR4RepositoryServerClock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current server time."""

        return timezone.now()


class DjangoR4RollingResearchRepository:
    """Record one factory-recomputed R4 result and return the stable winner."""

    def __init__(self, clock: R4RepositoryServerClock | None = None) -> None:
        self._clock = clock or DjangoR4RepositoryServerClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction boundary used by this repository."""

        return "django:default"

    def append(self, draft: R4RollingResearchDraft) -> R4RollingResearchRecord:
        """Append atomically; retries and races return the first exact winner."""

        existing = (
            R4RollingResearchResultModel._default_manager.filter(record_id=draft.record_id)
            .select_related("receipt")
            .first()
        )
        if existing is not None:
            return self._verify_exact_draft(existing, draft)
        try:
            candidate = R4RollingResearchRecord.from_server_clock(
                draft=draft,
                server_recorded_at=self._clock.now(),
            )
            with transaction.atomic(), _r4_repository_append_unit(candidate.recorded_at):
                winner = (
                    R4RollingResearchResultModel._default_manager.select_for_update()
                    .select_related("receipt")
                    .filter(record_id=draft.record_id)
                    .first()
                )
                if winner is not None:
                    return self._verify_exact_draft(winner, draft)
                receipt = _receipt_model(candidate)
                receipt.full_clean()
                receipt.save(force_insert=True)
                result = _result_model(candidate, receipt)
                result.full_clean()
                result.save(force_insert=True)
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = (
                R4RollingResearchResultModel._default_manager.select_related("receipt")
                .filter(record_id=draft.record_id)
                .first()
            )
            if winner is None:
                raise ValueError("invalid R4 rolling research record") from exc
            return self._verify_exact_draft(winner, draft)
        return candidate

    def get(self, record_id: str) -> R4RollingResearchRecord | None:
        """Return one exact typed record after payload and factory verification."""

        row = (
            R4RollingResearchResultModel._default_manager.select_related("receipt")
            .filter(record_id=record_id)
            .first()
        )
        return None if row is None else _record_from_row(row)

    def _verify_exact_draft(
        self,
        row: R4RollingResearchResultModel,
        draft: R4RollingResearchDraft,
    ) -> R4RollingResearchRecord:
        persisted = _record_from_row(row)
        expected = R4RollingResearchRecord.from_server_clock(
            draft=draft,
            server_recorded_at=persisted.recorded_at,
        )
        if expected != persisted:
            raise ValueError("R4 record identity conflicts with different evidence")
        return persisted


def _receipt_model(record: R4RollingResearchRecord) -> R4RollingResearchReceiptModel:
    return R4RollingResearchReceiptModel(
        receipt_id=record.record_id,
        record_version=record.record_version,
        study_id=record.study_id,
        study_version=record.study_version,
        study_content_hash=record.study_content_hash,
        r3_promotion_attestation_hash=record.r3_promotion_attestation_hash,
        split_contract_hash=record.split_contract_hash,
        evaluated_at=record.evaluated_at,
        owner=record.owner,
        recorded_at=record.recorded_at,
        producer_code_version=record.producer_code_version,
        dependency_lock_hash=record.dependency_lock_hash,
        valid_until=record.valid_until,
        study_payload=study_to_payload(record.study),
        promotion_attestation_payload=promotion_to_payload(record.promotion_attestation),
    )


def _result_model(
    record: R4RollingResearchRecord,
    receipt: R4RollingResearchReceiptModel,
) -> R4RollingResearchResultModel:
    return R4RollingResearchResultModel(
        record_id=record.record_id,
        receipt=receipt,
        artifact_hash=record.artifact_hash,
        evidence_complete=record.artifact.evidence_complete,
        eligible_for_research_comparison=record.artifact.eligible_for_research_comparison,
        subhashes=[list(item) for item in record.subhashes],
        artifact_payload=artifact_to_payload(record.artifact),
        record_hash=record.record_hash,
        usage_scope=record.usage_scope,
        must_not_use_for_decision=record.must_not_use_for_decision,
        must_not_execute=record.must_not_execute,
    )


def _record_from_row(row: R4RollingResearchResultModel) -> R4RollingResearchRecord:
    receipt = row.receipt
    study = study_from_payload(receipt.study_payload)
    promotion = promotion_from_payload(receipt.promotion_attestation_payload)
    artifact = artifact_from_payload(
        row.artifact_payload,
        study=study,
        promotion_attestation=promotion,
    )
    draft = R4RollingResearchDraft(
        study=study,
        promotion_attestation=promotion,
        evaluated_at=receipt.evaluated_at,
        producer_code_version=receipt.producer_code_version,
        dependency_lock_hash=receipt.dependency_lock_hash,
        valid_until=receipt.valid_until,
    )
    record = R4RollingResearchRecord.from_server_clock(
        draft=draft,
        server_recorded_at=receipt.recorded_at,
    )
    if artifact != record.artifact:
        raise ValueError("persisted R4 artifact differs from factory output")
    expected_receipt = _receipt_model(record)
    receipt_fields = (
        "receipt_id",
        "record_version",
        "study_id",
        "study_version",
        "study_content_hash",
        "r3_promotion_attestation_hash",
        "split_contract_hash",
        "evaluated_at",
        "owner",
        "recorded_at",
        "producer_code_version",
        "dependency_lock_hash",
        "valid_until",
        "study_payload",
        "promotion_attestation_payload",
    )
    if any(
        getattr(receipt, field_name) != getattr(expected_receipt, field_name)
        for field_name in receipt_fields
    ):
        raise ValueError("persisted R4 receipt metadata or payload mismatch")
    expected_result = _result_model(record, receipt)
    result_fields = (
        "record_id",
        "receipt_id",
        "artifact_hash",
        "evidence_complete",
        "eligible_for_research_comparison",
        "subhashes",
        "artifact_payload",
        "record_hash",
        "usage_scope",
        "must_not_use_for_decision",
        "must_not_execute",
    )
    if any(
        getattr(row, field_name) != getattr(expected_result, field_name)
        for field_name in result_fields
    ):
        raise ValueError("persisted R4 result metadata or payload mismatch")
    return record


__all__ = [
    "DjangoR4RepositoryServerClock",
    "DjangoR4RollingResearchRepository",
    "R4RepositoryServerClock",
]
