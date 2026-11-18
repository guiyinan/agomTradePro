"""SystemAudit/Outbox adapter for one exact Owner maintenance operation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import cast
from uuid import UUID

from django.utils import timezone

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCoordinator
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)
from apps.data_center.domain.asset_active_maintenance import (
    AssetActiveMaintenanceContractError,
    AssetMasterTransition,
    MaintenanceAuditObservation,
    MaintenanceAuditPlanMetadata,
    MaintenanceAuditReceipt,
    SourceOccurrencePin,
)
from apps.data_center.domain.entities import RawAuditReference

_EVENT_TYPE = "data.asset_master.collection_scope.stopped"
_EVENT_VERSION = "v1"
_SCHEMA_VERSION = "1"
_DETAIL_SCHEMA = "data-center.asset-master-collection-scope-maintenance.v1"
_REASON = ("owner_asset_scope_maintenance",)


class DjangoAssetMaintenanceSystemAuditAdapter:
    """Append/replay an exact user event and Outbox pair through existing APIs."""

    __slots__ = ("_coordinator",)

    def __init__(self, *, coordinator: SystemAuditEventOutboxCoordinator) -> None:
        """Use the real same-alias SystemAudit coordinator."""

        if coordinator.database_alias != "default":
            raise ValueError("maintenance audit requires the default event/outbox alias")
        self._coordinator = coordinator

    @property
    def unit_of_work_key(self) -> str:
        """Return the alias shared by the audit event and outbox."""

        return f"django:{self._coordinator.database_alias}"

    def find_exact(self, plan_digest: str) -> MaintenanceAuditReceipt | None:
        """Read the stable plan event and verify its exact paired outbox row."""

        event_id = _event_id(plan_digest)
        stream_id = _stream_id(plan_digest)
        with self._coordinator.caller_owned_atomic():
            self._coordinator.lock_stream(stream_id)
            event = self._coordinator.get_winner_targeted(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=timezone.now(),
                lock=True,
            )
            if event is None:
                return None
            winner = self._coordinator.get_exact_outbox_winner_targeted(event)
            if winner is None:
                raise AssetActiveMaintenanceContractError("system_audit_outbox_pair_missing")
            if winner.event.to_payload() != event.to_payload():
                raise AssetActiveMaintenanceContractError("system_audit_outbox_payload_mismatch")
            return _receipt_from_pair(event, winner.outbox_id)

    def record_once(self, observation: MaintenanceAuditObservation) -> MaintenanceAuditReceipt:
        """Append one typed event and its exact outbox payload in the caller's UOW."""

        plan_digest = observation.plan_digest
        event_id = _event_id(plan_digest)
        stream_id = _stream_id(plan_digest)
        scope = AuditScopeRef(
            tenant_id=observation.authority.tenant_id,
            owner_id=observation.authority.owner_id,
        )
        expected = _event_from_observation(
            observation, event_id=event_id, stream_id=stream_id, scope=scope
        )
        with self._coordinator.caller_owned_atomic():
            self._coordinator.lock_stream(stream_id)
            recorded_at = observation.occurred_at
            existing = self._coordinator.get_winner_targeted(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=recorded_at,
                lock=True,
            )
            if existing is not None:
                if existing.to_payload() != expected.to_payload():
                    raise AssetActiveMaintenanceContractError("system_audit_idempotency_conflict")
                winner = self._coordinator.get_exact_outbox_winner_targeted(existing)
                if winner is None:
                    raise AssetActiveMaintenanceContractError("system_audit_outbox_pair_missing")
                if winner.event.to_payload() != expected.to_payload():
                    raise AssetActiveMaintenanceContractError(
                        "system_audit_outbox_payload_mismatch"
                    )
                receipt = _receipt_from_pair(existing, winner.outbox_id)
                if not _receipt_matches_observation(receipt, observation):
                    raise AssetActiveMaintenanceContractError("system_audit_idempotency_conflict")
                return receipt

            head = self._coordinator.get_current_head_targeted(
                stream_id=stream_id,
                as_of=recorded_at,
                scope=scope,
                lock=True,
            )
            if head is not None:
                raise AssetActiveMaintenanceContractError("system_audit_plan_stream_conflict")
            commit = self._coordinator.append_and_enqueue(
                expected,
                expected_predecessor_hash=None,
                recorded_at=recorded_at,
            )
            if commit.event.to_payload() != expected.to_payload():
                raise AssetActiveMaintenanceContractError("system_audit_event_readback_mismatch")
            winner = self._coordinator.get_exact_outbox_winner_targeted(commit.event)
            if winner is None:
                raise AssetActiveMaintenanceContractError("system_audit_outbox_readback_missing")
            if winner.event.to_payload() != expected.to_payload():
                raise AssetActiveMaintenanceContractError("system_audit_outbox_payload_mismatch")
            receipt = _receipt_from_pair(commit.event, winner.outbox_id)
            if not _receipt_matches_observation(receipt, observation):
                raise AssetActiveMaintenanceContractError("system_audit_outbox_readback_mismatch")
            return receipt


def _event_id(plan_digest: str) -> str:
    """Build one stable immutable event identity from the canonical plan digest."""

    return f"asset-master-scope-maintenance:{plan_digest}"


def _stream_id(plan_digest: str) -> str:
    """Build the event stream identity serialized by PostgreSQL advisory lock."""

    return f"data_center.asset_master.collection_scope.maintenance.{plan_digest}"


def _event_from_observation(
    observation: MaintenanceAuditObservation,
    *,
    event_id: str,
    stream_id: str,
    scope: AuditScopeRef,
) -> SystemAuditEvent:
    """Map the typed maintenance observation to a canonical user SystemAudit event."""

    refs = tuple(
        AuditEvidenceRef(
            owner="data_center",
            artifact_type="data_center.raw_audit",
            artifact_id=pin.raw_audit_reference.raw_audit_id,
            artifact_version=pin.raw_audit_reference.version,
            content_hash=pin.raw_audit_reference.content_hash,
        )
        for pin in sorted(observation.source_occurrences, key=lambda item: item.exchange)
    )
    actor = AuditActorRef(
        actor_type="user",
        actor_id=observation.actor.actor_id,
        actor_display=observation.actor.username,
    )
    return SystemAuditEvent.create(
        event_id=event_id,
        event_version=_EVENT_VERSION,
        schema_version=_SCHEMA_VERSION,
        category=AuditCategory.SYSTEM_OPERATION,
        event_type=_EVENT_TYPE,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=_REASON,
        occurred_at=observation.occurred_at,
        recorded_at=observation.occurred_at,
        observed_at=None,
        actor=actor,
        source_app="data_center",
        source_component="asset_active_maintenance",
        source_surface="management_command",
        correlations=AuditCorrelations(
            request_id=observation.plan_digest,
            run_id=None,
            dataset_key=observation.provider_contract.dataset_key,
            provider_key=observation.provider_contract.provider_name,
            capability="instrument_reference",
        ),
        resource=AuditResourceRef(
            resource_type="data_center.asset_master.collection_scope",
            resource_id=observation.plan_digest,
            resource_version=observation.plan_file_sha256,
        ),
        dataset_key=observation.provider_contract.dataset_key,
        provider_key=observation.provider_contract.provider_name,
        capability="instrument_reference",
        publication_id=None,
        evidence_refs=refs,
        detail_schema=_DETAIL_SCHEMA,
        detail=_detail_from_observation(observation),
        stream_id=stream_id,
        sequence_no=1,
        predecessor_hash=None,
        idempotency_key=event_id,
        scope=scope,
    )


def _detail_from_observation(
    observation: MaintenanceAuditObservation,
) -> Mapping[str, JSONValue]:
    """Create safe event details binding plan, actor scope, and raw occurrences."""

    return {
        "plan_digest": observation.plan_digest,
        "plan_file_sha256": observation.plan_file_sha256,
        "actor_id": observation.actor.actor_id,
        "actor_username": observation.actor.username,
        "tenant_id": observation.authority.tenant_id,
        "owner_id": observation.authority.owner_id,
        "authority_content_hash": observation.authority.authority_content_hash,
        "provider_contract_id": observation.provider_contract.contract_id,
        "provider_contract_version": observation.provider_contract.contract_version,
        "provider_contract_hash": observation.provider_contract.content_hash,
        "provider_name": observation.provider_contract.provider_name,
        "dataset_key": observation.provider_contract.dataset_key,
        "api_name": observation.provider_contract.api_name,
        "crosswalk_id": observation.crosswalk.crosswalk_id,
        "crosswalk_version": observation.crosswalk.crosswalk_version,
        "crosswalk_hash": observation.crosswalk.content_hash,
        "target_date": observation.target_date.isoformat(),
        "source_observed_at": None,
        "source_available_at": None,
        "source_time_semantics": "unknown_upstream_time;response_completed_at_is_local_capture_time",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "source_occurrences": [
            _pin_payload(item)
            for item in sorted(observation.source_occurrences, key=lambda pin: pin.exchange)
        ],
        "transitions": [
            _transition_payload(item)
            for item in sorted(observation.transitions, key=lambda transition: transition.code)
        ],
    }


def _pin_payload(pin: SourceOccurrencePin) -> Mapping[str, JSONValue]:
    """Serialize source metadata without exposing the retained response body."""

    return {
        "exchange": pin.exchange,
        "raw_audit_id": pin.raw_audit_reference.raw_audit_id,
        "raw_audit_version": pin.raw_audit_reference.version,
        "raw_audit_content_hash": pin.raw_audit_reference.content_hash,
        "raw_audit_run_id": pin.raw_audit_reference.run_id,
        "raw_audit_ingested_run_id": pin.raw_audit_reference.ingested_run_id,
        "raw_payload_id": pin.raw_payload_id,
        "raw_payload_hash": pin.raw_payload_hash,
        "response_body_sha256": pin.response_body_sha256,
        "response_completed_at": pin.response_completed_at.isoformat(),
        "row_count": pin.row_count,
    }


def _transition_payload(item: AssetMasterTransition) -> Mapping[str, JSONValue]:
    """Serialize the five allowed row transitions and their preserved-field digests."""

    return {
        "asset_pk": item.asset_pk,
        "code": item.code,
        "exchange": item.exchange,
        "prior_delist_date": (
            item.prior_delist_date.isoformat() if item.prior_delist_date is not None else None
        ),
        "prior_updated_at": item.prior_updated_at.isoformat(),
        "source_delist_date": item.source_delist_date.isoformat(),
        "preserved_state_sha256": item.preserved_state_sha256,
        "updated_at": item.updated_at.isoformat(),
        "raw_audit_id": item.raw_audit_reference.raw_audit_id,
        "raw_audit_version": item.raw_audit_reference.version,
        "raw_audit_content_hash": item.raw_audit_reference.content_hash,
        "raw_audit_run_id": item.raw_audit_reference.run_id,
        "raw_audit_ingested_run_id": item.raw_audit_reference.ingested_run_id,
    }


def _receipt_from_pair(event: SystemAuditEvent, outbox_id: UUID) -> MaintenanceAuditReceipt:
    """Restore and validate one exact event/outbox pair as an application receipt."""

    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise AssetActiveMaintenanceContractError("system_audit_event_hash_invalid") from error
    if (
        event.event_type != _EVENT_TYPE
        or event.event_version != _EVENT_VERSION
        or event.schema_version != _SCHEMA_VERSION
        or event.owner != "data_center"
        or event.category is not AuditCategory.SYSTEM_OPERATION
        or event.write_policy is not AuditWritePolicy.TRANSACTIONAL_OUTBOX
        or event.outcome is not AuditOutcome.SUCCESS
        or event.severity is not AuditSeverity.INFO
        or event.source_app != "data_center"
        or event.source_component != "asset_active_maintenance"
        or event.source_surface != "management_command"
        or event.detail_schema != _DETAIL_SCHEMA
        or event.capability != "instrument_reference"
        or event.scope is None
        or event.actor.actor_type != "user"
        or event.actor.actor_display is None
        or event.observed_at is not None
        or event.sequence_no != 1
        or event.predecessor_hash is not None
        or event.event_id != event.idempotency_key
        or event.reason_codes != _REASON
        or event.publication_id is not None
        or event.recorded_at != event.occurred_at
    ):
        raise AssetActiveMaintenanceContractError("system_audit_event_contract_invalid")
    detail = event.detail
    expected_detail_keys = {
        "plan_digest",
        "plan_file_sha256",
        "actor_id",
        "actor_username",
        "tenant_id",
        "owner_id",
        "authority_content_hash",
        "provider_contract_id",
        "provider_contract_version",
        "provider_contract_hash",
        "provider_name",
        "dataset_key",
        "api_name",
        "crosswalk_id",
        "crosswalk_version",
        "crosswalk_hash",
        "target_date",
        "source_observed_at",
        "source_available_at",
        "source_time_semantics",
        "must_not_use_for_decision",
        "must_not_execute",
        "source_occurrences",
        "transitions",
    }
    provider_contract_id = _detail_text(detail, "provider_contract_id")
    provider_contract_version = _detail_text(detail, "provider_contract_version")
    provider_name = _detail_text(detail, "provider_name")
    dataset_key = _detail_text(detail, "dataset_key")
    api_name = _detail_text(detail, "api_name")
    crosswalk_id = _detail_text(detail, "crosswalk_id")
    crosswalk_version = _detail_text(detail, "crosswalk_version")
    if (
        set(detail) != expected_detail_keys
        or detail.get("source_observed_at") is not None
        or detail.get("source_available_at") is not None
        or detail.get("source_time_semantics")
        != "unknown_upstream_time;response_completed_at_is_local_capture_time"
        or detail.get("must_not_use_for_decision") is not True
        or detail.get("must_not_execute") is not True
        or detail.get("actor_id") != event.actor.actor_id
        or detail.get("actor_username") != event.actor.actor_display
        or detail.get("tenant_id") != event.scope.tenant_id
        or detail.get("owner_id") != event.scope.owner_id
        or provider_name != event.provider_key
        or dataset_key != event.dataset_key
        or api_name != "stock_basic"
        or not all(
            (
                provider_contract_id,
                provider_contract_version,
                crosswalk_id,
                crosswalk_version,
            )
        )
    ):
        raise AssetActiveMaintenanceContractError("system_audit_detail_contract_invalid")
    provider_contract_hash = _detail_text(detail, "provider_contract_hash")
    crosswalk_hash = _detail_text(detail, "crosswalk_hash")
    pins_value = detail.get("source_occurrences")
    transitions_value = detail.get("transitions")
    if type(pins_value) is not list or type(transitions_value) is not list:
        raise AssetActiveMaintenanceContractError("system_audit_detail_scope_invalid")
    pins = tuple(_pin_from_payload(item) for item in pins_value)
    transitions = tuple(_transition_from_payload(item) for item in transitions_value)
    plan_digest = _detail_text(detail, "plan_digest")
    if (
        event.event_id != _event_id(plan_digest)
        or event.idempotency_key != _event_id(plan_digest)
        or event.stream_id != _stream_id(plan_digest)
        or event.resource is None
        or event.resource.resource_id != plan_digest
        or event.resource.resource_version != _detail_text(detail, "plan_file_sha256")
        or event.resource.resource_type != "data_center.asset_master.collection_scope"
        or event.correlations
        != AuditCorrelations(
            request_id=plan_digest,
            run_id=None,
            dataset_key=dataset_key,
            provider_key=provider_name,
            capability="instrument_reference",
        )
    ):
        raise AssetActiveMaintenanceContractError("system_audit_plan_identity_invalid")
    expected_refs = tuple(
        AuditEvidenceRef(
            owner="data_center",
            artifact_type="data_center.raw_audit",
            artifact_id=pin.raw_audit_reference.raw_audit_id,
            artifact_version=pin.raw_audit_reference.version,
            content_hash=pin.raw_audit_reference.content_hash,
        )
        for pin in sorted(pins, key=lambda item: item.exchange)
    )
    if event.evidence_refs != expected_refs or event.scope is None:
        raise AssetActiveMaintenanceContractError("system_audit_evidence_binding_invalid")
    outbox = _expected_outbox(outbox_id)
    try:
        metadata = MaintenanceAuditPlanMetadata(
            target_date=date.fromisoformat(_detail_text(detail, "target_date")),
            provider_contract_id=provider_contract_id,
            provider_contract_version=provider_contract_version,
            provider_name=provider_name,
            dataset_key=dataset_key,
            api_name=api_name,
            crosswalk_id=crosswalk_id,
            crosswalk_version=crosswalk_version,
            actor_username=_detail_text(detail, "actor_username"),
        )
    except ValueError as error:
        raise AssetActiveMaintenanceContractError("system_audit_plan_metadata_invalid") from error
    return MaintenanceAuditReceipt(
        plan_digest=plan_digest,
        plan_file_sha256=_detail_text(detail, "plan_file_sha256"),
        actor_id=event.actor.actor_id,
        tenant_id=event.scope.tenant_id,
        owner_id=event.scope.owner_id,
        authority_content_hash=_detail_text(detail, "authority_content_hash"),
        provider_contract_hash=provider_contract_hash,
        crosswalk_hash=crosswalk_hash,
        plan_metadata=metadata,
        source_occurrences=pins,
        transitions=transitions,
        event_id=event.event_id,
        event_content_sha256=event.content_hash,
        outbox_id=outbox,
        recorded_at=event.recorded_at,
    )


def _expected_outbox(outbox_id: UUID) -> UUID:
    """Require a database-issued Outbox UUID rather than a reconstructed token."""

    if type(outbox_id) is not UUID:
        raise AssetActiveMaintenanceContractError("system_audit_outbox_identity_invalid")
    return outbox_id


def _pin_from_payload(value: object) -> SourceOccurrencePin:
    """Strictly restore one response pin from immutable event detail."""

    item = _strict_object(
        value,
        {
            "exchange",
            "raw_audit_id",
            "raw_audit_version",
            "raw_audit_content_hash",
            "raw_audit_run_id",
            "raw_audit_ingested_run_id",
            "raw_payload_id",
            "raw_payload_hash",
            "response_body_sha256",
            "response_completed_at",
            "row_count",
        },
    )
    return SourceOccurrencePin(
        exchange=_detail_text(item, "exchange"),
        raw_audit_reference=RawAuditReference(
            raw_audit_id=_detail_text(item, "raw_audit_id"),
            version=_detail_text(item, "raw_audit_version"),
            content_hash=_detail_text(item, "raw_audit_content_hash"),
            run_id=_detail_text(item, "raw_audit_run_id"),
            ingested_run_id=_detail_text(item, "raw_audit_ingested_run_id"),
        ),
        raw_payload_id=_detail_text(item, "raw_payload_id"),
        raw_payload_hash=_detail_text(item, "raw_payload_hash"),
        response_body_sha256=_detail_text(item, "response_body_sha256"),
        response_completed_at=_detail_datetime(item, "response_completed_at"),
        row_count=_detail_int(item, "row_count"),
    )


def _transition_from_payload(value: object) -> AssetMasterTransition:
    """Strictly restore one exact AssetMaster transition from event detail."""

    item = _strict_object(
        value,
        {
            "asset_pk",
            "code",
            "exchange",
            "prior_delist_date",
            "prior_updated_at",
            "source_delist_date",
            "preserved_state_sha256",
            "updated_at",
            "raw_audit_id",
            "raw_audit_version",
            "raw_audit_content_hash",
            "raw_audit_run_id",
            "raw_audit_ingested_run_id",
        },
    )
    prior_value = item.get("prior_delist_date")
    if prior_value is not None and type(prior_value) is not str:
        raise AssetActiveMaintenanceContractError("system_audit_prior_date_invalid")
    if prior_value == "":
        raise AssetActiveMaintenanceContractError("system_audit_prior_date_invalid")
    return AssetMasterTransition(
        asset_pk=_detail_int(item, "asset_pk"),
        code=_detail_text(item, "code"),
        exchange=_detail_text(item, "exchange"),
        prior_delist_date=date.fromisoformat(prior_value) if prior_value else None,
        prior_updated_at=_detail_datetime(item, "prior_updated_at"),
        source_delist_date=date.fromisoformat(_detail_text(item, "source_delist_date")),
        preserved_state_sha256=_detail_text(item, "preserved_state_sha256"),
        updated_at=_detail_datetime(item, "updated_at"),
        raw_audit_reference=RawAuditReference(
            raw_audit_id=_detail_text(item, "raw_audit_id"),
            version=_detail_text(item, "raw_audit_version"),
            content_hash=_detail_text(item, "raw_audit_content_hash"),
            run_id=_detail_text(item, "raw_audit_run_id"),
            ingested_run_id=_detail_text(item, "raw_audit_ingested_run_id"),
        ),
    )


def _strict_object(value: object, expected: set[str]) -> Mapping[str, object]:
    """Narrow one event detail object and reject any extra or omitted field."""

    if type(value) is not dict or set(cast(dict[str, object], value)) != expected:
        raise AssetActiveMaintenanceContractError("system_audit_detail_shape_invalid")
    return cast(dict[str, object], value)


def _detail_text(value: Mapping[str, object], key: str) -> str:
    """Read a nonempty text value from validated immutable event detail."""

    result = value.get(key)
    if type(result) is not str or not result:
        raise AssetActiveMaintenanceContractError("system_audit_detail_text_invalid")
    return result


def _detail_int(value: Mapping[str, object], key: str) -> int:
    """Read an exact integer from event detail without bool coercion."""

    result = value.get(key)
    if type(result) is not int:
        raise AssetActiveMaintenanceContractError("system_audit_detail_integer_invalid")
    return result


def _detail_datetime(value: Mapping[str, object], key: str) -> datetime:
    """Read an aware ISO clock from immutable event detail."""

    try:
        result = datetime.fromisoformat(_detail_text(value, key))
    except ValueError as error:
        raise AssetActiveMaintenanceContractError("system_audit_detail_datetime_invalid") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise AssetActiveMaintenanceContractError("system_audit_detail_datetime_invalid")
    return result


def _receipt_matches_observation(
    receipt: MaintenanceAuditReceipt,
    observation: MaintenanceAuditObservation,
) -> bool:
    """Require all stable event payload components to match an idempotent retry."""

    return (
        receipt.plan_digest == observation.plan_digest
        and receipt.plan_file_sha256 == observation.plan_file_sha256
        and receipt.actor_id == observation.actor.actor_id
        and receipt.tenant_id == observation.authority.tenant_id
        and receipt.owner_id == observation.authority.owner_id
        and receipt.authority_content_hash == observation.authority.authority_content_hash
        and receipt.provider_contract_hash == observation.provider_contract.content_hash
        and receipt.crosswalk_hash == observation.crosswalk.content_hash
        and receipt.plan_metadata == observation.plan_metadata
        and receipt.source_occurrences == observation.source_occurrences
        and receipt.transitions == observation.transitions
        and receipt.recorded_at == observation.occurred_at
    )


__all__ = ["DjangoAssetMaintenanceSystemAuditAdapter"]
