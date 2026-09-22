"""Atomic first-writer repository for financial source-time RawAudit rows."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.data_center.application.financial_source_time_artifact import (
    SOURCE_TIME_AUDIT_CAPABILITY,
    SOURCE_TIME_AUDIT_LINK_KEY,
    SOURCE_TIME_AUDIT_LINK_SCHEMA,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.infrastructure.models import FinancialSourceTimeAuditClaimModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository


class DjangoFinancialSourceTimeArtifactAuditRepository:
    """Guarantee one canonical source-time audit per capture UUID."""

    def __init__(self, raw_audits: RawAuditRepository | None = None) -> None:
        """Bind the append-only RawAudit owner."""

        self._raw_audits = raw_audits or RawAuditRepository()

    def list_by_source_time_artifact_capture_id(
        self,
        capture_id: UUID,
    ) -> list[RawAudit]:
        """Return the complete matching audit cardinality."""

        return self._raw_audits.list_by_source_time_artifact_capture_id(capture_id)

    def log_source_time(self, audit: RawAudit) -> RawAudit:
        """Append once under a database-unique first-writer capture claim."""

        capture_id = _capture_id_from_audit(audit)
        candidate_hash = raw_audit_content_hash(audit)
        if audit.content_hash and audit.content_hash != candidate_hash:
            raise ValueError("financial source-time audit content hash is invalid")
        with transaction.atomic():
            claim = _lock_or_create_claim(capture_id)
            existing = self.list_by_source_time_artifact_capture_id(capture_id)
            if len(existing) > 1:
                raise ValueError("financial source-time audit cardinality is ambiguous")
            if existing:
                persisted = _require_same_audit(existing[0], candidate_hash)
                _attach_claim(claim, persisted)
                return persisted
            if claim.audit_id is not None:
                raise ValueError("financial source-time claim is inconsistent")
            persisted = self._raw_audits.log(audit)
            _attach_claim(claim, persisted)
            return persisted


def _capture_id_from_audit(audit: RawAudit) -> UUID:
    """Read the exact capture UUID from a successful typed audit link."""

    if audit.capability != SOURCE_TIME_AUDIT_CAPABILITY or audit.status != "ok":
        raise ValueError("financial source-time audit outcome is invalid")
    raw_link = audit.extra.get(SOURCE_TIME_AUDIT_LINK_KEY)
    if not isinstance(raw_link, Mapping):
        raise ValueError("financial source-time audit link is missing")
    if raw_link.get("schema") != SOURCE_TIME_AUDIT_LINK_SCHEMA:
        raise ValueError("financial source-time audit link schema is invalid")
    raw_capture_id = raw_link.get("capture_id")
    if not isinstance(raw_capture_id, str):
        raise ValueError("financial source-time audit capture identity is invalid")
    try:
        return UUID(raw_capture_id)
    except ValueError as exc:
        raise ValueError("financial source-time audit capture identity is invalid") from exc


def _lock_or_create_claim(capture_id: UUID) -> FinancialSourceTimeAuditClaimModel:
    """Create the unique claim or lock the committed first-writer row."""

    try:
        with transaction.atomic():
            return FinancialSourceTimeAuditClaimModel.objects.create(capture_id=capture_id)
    except IntegrityError:
        return FinancialSourceTimeAuditClaimModel.objects.select_for_update().get(
            capture_id=capture_id
        )


def _require_same_audit(audit: RawAudit, candidate_hash: str) -> RawAudit:
    """Accept a concurrent winner only when its canonical content is identical."""

    if (
        not audit.content_hash
        or audit.content_hash != candidate_hash
        or audit.content_hash != raw_audit_content_hash(audit)
    ):
        raise ValueError("financial source-time audit replay conflicts")
    return audit


def _attach_claim(
    claim: FinancialSourceTimeAuditClaimModel,
    audit: RawAudit,
) -> None:
    """Bind a new claim once or verify its already committed audit identity."""

    if not audit.raw_audit_id or not audit.raw_audit_id.isdecimal():
        raise ValueError("financial source-time persisted audit identity is invalid")
    audit_id = int(audit.raw_audit_id)
    if claim.audit_id is not None:
        if int(claim.audit_id) != audit_id:
            raise ValueError("financial source-time claim audit conflicts")
        return
    claim.audit_id = audit_id
    claim.save(update_fields=["audit"])


__all__ = ["DjangoFinancialSourceTimeArtifactAuditRepository"]
