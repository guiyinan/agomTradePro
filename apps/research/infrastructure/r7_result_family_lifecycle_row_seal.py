"""Canonical row/header seals for R7 family lifecycle persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict, cast

from apps.research.application.r7_result_family_lifecycle import R7FamilyOwnerSourceGraph
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
)
from apps.research.domain.scenario_research_hashing import hash_components
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleAuthorizationModel,
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_result_family_lifecycle_codec import (
    encode_r7_family_lifecycle_authorization,
    encode_r7_family_lifecycle_event,
)

AUTHORIZATION_PAYLOAD_VERSION = "r7-family-lifecycle-authorization-payload.v1"
EVENT_PAYLOAD_VERSION = "r7-family-lifecycle-event-source-graph.v1"
AUDIT_PAYLOAD_VERSION = "r7-family-lifecycle-audit-snapshot-payload.v1"
AUDIT_SNAPSHOT_VERSION = "r7-family-lifecycle-audit-snapshot.v1"


class R7FamilyAuditSnapshotValues(TypedDict):
    snapshot_id: str
    snapshot_version: str
    family_id: str
    family_version: str
    family_hash: str
    as_of: datetime
    total_count: int
    manifest_hash: str
    payload_schema_version: str
    payload: dict[str, object]
    created_at: datetime
    ledger_recorded_at: datetime
    content_hash: str


def local_authorization_model_headers(
    model: R7ResultLifecycleAuthorizationModel,
) -> tuple[object, ...]:
    """Return the canonical local-authorization owner-ledger headers."""

    return (
        model.result_key,
        model.result_version,
        model.result_content_hash,
        model.authorization_id,
        model.authorization_version,
        model.event_id,
        model.event_version,
        model.action,
        model.expected_sequence,
        model.owner,
        model.issued_at,
        model.recorded_at,
        model.valid_until,
        model.reason_codes,
        model.evidence_ref,
        model.research_only,
        model.promotes_internal_research_record_only,
        model.publishes_model_probability,
        model.produces_decision,
        model.executes_orders,
        model.must_not_use_for_decision,
        model.must_not_execute,
        model.content_hash,
    )


def local_event_model_headers(
    model: R7ResultLifecycleEventModel,
) -> tuple[object, ...]:
    """Return the canonical local-event owner-ledger headers."""

    return (
        model.result_key,
        model.result_version,
        model.result_content_hash,
        model.event_id,
        model.event_version,
        model.authorization_id,
        model.authorization_version,
        model.authorization_hash,
        model.action,
        model.sequence,
        model.occurred_at,
        model.recorded_at,
        model.previous_event_hash,
        model.reason_codes,
        model.research_only,
        model.promotes_internal_research_record_only,
        model.publishes_model_probability,
        model.produces_decision,
        model.executes_orders,
        model.must_not_use_for_decision,
        model.must_not_execute,
        model.content_hash,
    )


def _clock(value: datetime) -> str:
    return value.isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_hash(label: str, values: dict[str, object]) -> str:
    return hash_components(
        label,
        *(
            f"{key}={_canonical_json(value) if isinstance(value, (dict, list)) else value}"
            for key, value in sorted(values.items())
        ),
    )


def authorization_values(
    authorization: R7FamilyLifecycleAuthorization,
    *,
    subject_source: R7FamilyOwnerSourceGraph,
    subject_result_row_id: int,
    subject_local_head_row_id: int,
    rollback_target_source: R7FamilyOwnerSourceGraph | None,
    rollback_target_result_row_id: int | None,
    rollback_target_local_head_row_id: int | None,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Build every persisted authorization column and its live header seal."""

    subject = subject_source.evidence
    target = None if rollback_target_source is None else rollback_target_source.evidence
    values: dict[str, object] = {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "family_id": authorization.family.family_id,
        "family_version": authorization.family.family_version,
        "family_hash": authorization.family.content_hash,
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "expected_sequence": authorization.expected_sequence,
        "expected_previous_event_id": authorization.expected_previous_event_id,
        "expected_previous_event_version": authorization.expected_previous_event_version,
        "expected_previous_event_hash": authorization.expected_previous_event_hash,
        "subject_result_id": subject_result_row_id,
        "subject_result_id_value": subject.result_ref.result_id,
        "subject_result_version": subject.result_ref.result_version,
        "subject_result_hash": subject.result_ref.content_hash,
        "subject_local_lifecycle_head_id": subject_local_head_row_id,
        "subject_owner_attestation_hash": (subject.local_lifecycle_attestation.content_hash),
        "rollback_target_result_id": rollback_target_result_row_id,
        "rollback_target_result_id_value": (
            None if target is None else target.result_ref.result_id
        ),
        "rollback_target_result_version": (
            None if target is None else target.result_ref.result_version
        ),
        "rollback_target_result_hash": (None if target is None else target.result_ref.content_hash),
        "rollback_target_local_lifecycle_head_id": (rollback_target_local_head_row_id),
        "rollback_target_owner_attestation_hash": (
            None if target is None else target.local_lifecycle_attestation.content_hash
        ),
        "owner": authorization.owner,
        "issued_at": authorization.issued_at,
        "owner_recorded_at": authorization.recorded_at,
        "valid_until": authorization.valid_until,
        "payload_schema_version": AUTHORIZATION_PAYLOAD_VERSION,
        "payload": encode_r7_family_lifecycle_authorization(authorization),
        "content_hash": authorization.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
    }
    values["row_hash"] = _row_hash("r7-family-authorization-row.v1", values)
    return values


def event_values(
    event: R7FamilyLifecycleEvent,
    *,
    authorization_row_id: int,
    subject_source: R7FamilyOwnerSourceGraph,
    subject_result_row_id: int,
    subject_local_head_row_id: int,
    rollback_target_source: R7FamilyOwnerSourceGraph | None,
    rollback_target_result_row_id: int | None,
    rollback_target_local_head_row_id: int | None,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Build every persisted event column and its live header seal."""

    values: dict[str, object] = {
        "authorization_row_id": authorization_row_id,
        "family_id": event.family.family_id,
        "family_version": event.family.family_version,
        "family_hash": event.family.content_hash,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "action": event.action.value,
        "sequence": event.sequence,
        "subject_result_id": subject_result_row_id,
        "subject_local_lifecycle_head_id": subject_local_head_row_id,
        "rollback_target_result_id": rollback_target_result_row_id,
        "rollback_target_local_lifecycle_head_id": (rollback_target_local_head_row_id),
        "occurred_at": event.occurred_at,
        "owner_recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash,
        "payload_schema_version": EVENT_PAYLOAD_VERSION,
        "payload": encode_r7_family_lifecycle_event(
            event,
            subject_source=subject_source,
            rollback_target_source=rollback_target_source,
        ),
        "content_hash": event.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
    }
    values["row_hash"] = _row_hash("r7-family-event-row.v1", values)
    return values


def stream_commit_values(
    *,
    authorization: R7FamilyLifecycleAuthorization,
    event: R7FamilyLifecycleEvent,
    authorization_row_id: int,
    event_row_id: int,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Seal the exact authorization/event pair and its owner anchors."""

    subject = event.subject_evidence
    target = event.rollback_target_evidence
    values: dict[str, object] = {
        "authorization_row_id": authorization_row_id,
        "event_row_id": event_row_id,
        "family_id": event.family.family_id,
        "family_version": event.family.family_version,
        "family_hash": event.family.content_hash,
        "sequence": event.sequence,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "authorization_hash": authorization.content_hash,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "event_hash": event.content_hash,
        "subject_result_hash": subject.result_ref.content_hash,
        "subject_local_lifecycle_head_hash": subject.local_lifecycle_head_hash,
        "rollback_target_result_hash": (None if target is None else target.result_ref.content_hash),
        "rollback_target_local_lifecycle_head_hash": (
            None if target is None else target.local_lifecycle_head_hash
        ),
        "ledger_recorded_at": ledger_recorded_at,
    }
    values["content_hash"] = _row_hash("r7-family-stream-commit.v1", values)
    return values


def audit_snapshot_values(
    *,
    snapshot_id: str,
    family_id: str,
    family_version: str,
    family_hash: str,
    as_of: datetime,
    total_count: int,
    manifest_hash: str,
    payload: dict[str, object],
    created_at: datetime,
    ledger_recorded_at: datetime,
) -> R7FamilyAuditSnapshotValues:
    """Build one immutable audit snapshot row."""

    values: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "snapshot_version": AUDIT_SNAPSHOT_VERSION,
        "family_id": family_id,
        "family_version": family_version,
        "family_hash": family_hash,
        "as_of": as_of,
        "total_count": total_count,
        "manifest_hash": manifest_hash,
        "payload_schema_version": AUDIT_PAYLOAD_VERSION,
        "payload": payload,
        "created_at": created_at,
        "ledger_recorded_at": ledger_recorded_at,
    }
    values["content_hash"] = _row_hash("r7-family-audit-snapshot-row.v1", values)
    return cast(R7FamilyAuditSnapshotValues, values)


def require_exact_values(
    model: object,
    values: Mapping[str, object],
    label: str,
) -> None:
    """Reject any raw/header/FK/payload change before Domain restore."""

    for field_name, expected in values.items():
        if getattr(model, field_name) != expected:
            raise ValueError(f"{label} row field {field_name} differs")


__all__ = [
    "AUDIT_PAYLOAD_VERSION",
    "AUDIT_SNAPSHOT_VERSION",
    "AUTHORIZATION_PAYLOAD_VERSION",
    "EVENT_PAYLOAD_VERSION",
    "R7FamilyAuditSnapshotValues",
    "audit_snapshot_values",
    "authorization_values",
    "event_values",
    "require_exact_values",
    "stream_commit_values",
]
