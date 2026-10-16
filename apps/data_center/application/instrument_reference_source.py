"""Application ports for retaining source-owned instrument occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.raw_landing import RawPayload


@dataclass(frozen=True, slots=True)
class InstrumentReferenceAuditOccurrence:
    """Describe one captured stock-basic call without exposing original secrets."""

    occurrence_id: UUID
    run_id: UUID
    ingested_run_id: UUID
    contract_id: str
    contract_version: str
    contract_hash: str
    api_name: str
    dataset_key: str
    exchange: str
    list_status: str
    fields: str
    row_count: int
    response_reference: ProviderResponsePayloadReference
    raw_payload: RawPayload


@dataclass(frozen=True, slots=True)
class InstrumentReferenceAuditOccurrenceReceipt:
    """Prove which exact RawAudit and default database alias were verified."""

    occurrence_id: UUID
    raw_audit_reference: RawAuditReference
    raw_payload_id: str
    raw_payload_hash: str
    response_body_sha256: str
    request_params_hash: str
    repository_alias: Literal["default"]


class InstrumentReferenceAuditOccurrenceWriterPort(Protocol):
    """Persist and read back one source-bound RawAudit occurrence."""

    def record(
        self,
        occurrence: InstrumentReferenceAuditOccurrence,
    ) -> InstrumentReferenceAuditOccurrenceReceipt:
        """Append one occurrence and verify its exact persisted RawAudit row."""


__all__ = [
    "InstrumentReferenceAuditOccurrence",
    "InstrumentReferenceAuditOccurrenceReceipt",
    "InstrumentReferenceAuditOccurrenceWriterPort",
]
