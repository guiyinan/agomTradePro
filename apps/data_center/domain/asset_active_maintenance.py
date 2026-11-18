"""Pure contracts for a narrowly scoped AssetMaster collection repair.

This operation records an Owner's explicit maintenance of collection scope.
It is not a legal delisting, tradability, decision, or execution assertion.
The provider's observed and available times remain unknown.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_RAW_SHA256: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIELDS: Final[tuple[str, ...]] = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)


class AssetActiveMaintenanceContractError(ValueError):
    """Raised when an exact maintenance plan or its evidence is invalid."""

    def __init__(self, code: str) -> None:
        """Create an error carrying one stable, safe reason code."""

        if not isinstance(code, str) or not code or not code.isascii():
            raise ValueError("maintenance error code must be ASCII text")
        self.code = code
        super().__init__(code)


def _aware_utc(value: datetime, field_name: str) -> None:
    """Require an exact UTC-aware clock without deriving source time."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise AssetActiveMaintenanceContractError(f"{field_name}_invalid")


def _sha256(value: str, field_name: str) -> None:
    """Require a lowercase SHA-256 digest."""

    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AssetActiveMaintenanceContractError(f"{field_name}_invalid")


@dataclass(frozen=True, slots=True)
class AssetMaintenanceTarget:
    """One exact pre-bound AssetMaster row and its expected before-image."""

    code: str
    asset_pk: int
    exchange: str
    expected_delist_date: date | None
    expected_updated_at: datetime
    expected_preserved_state_sha256: str

    def __post_init__(self) -> None:
        """Reject ambiguous codes, row identities, exchanges, and dates."""

        if (
            not isinstance(self.code, str)
            or not self.code
            or self.code.strip() != self.code
            or len(self.code) > 20
        ):
            raise AssetActiveMaintenanceContractError("target_code_invalid")
        if type(self.asset_pk) is not int or self.asset_pk <= 0:
            raise AssetActiveMaintenanceContractError("target_primary_key_invalid")
        if self.exchange not in {"SSE", "SZSE"}:
            raise AssetActiveMaintenanceContractError("target_exchange_invalid")
        if self.expected_delist_date is not None and type(self.expected_delist_date) is not date:
            raise AssetActiveMaintenanceContractError("target_delist_preimage_invalid")
        _aware_utc(self.expected_updated_at, "target_updated_at_preimage")
        _sha256(self.expected_preserved_state_sha256, "target_preserved_state_preimage")


@dataclass(frozen=True, slots=True)
class SourceOccurrencePin:
    """Pin one retained RawAudit and RawPayload occurrence in the plan."""

    exchange: str
    raw_audit_reference: RawAuditReference
    raw_payload_id: str
    raw_payload_hash: str
    response_body_sha256: str
    response_completed_at: datetime
    row_count: int

    def __post_init__(self) -> None:
        """Validate the exact raw identities and local response clock."""

        if self.exchange not in {"SSE", "SZSE"}:
            raise AssetActiveMaintenanceContractError("source_exchange_invalid")
        if type(self.raw_audit_reference) is not RawAuditReference:
            raise AssetActiveMaintenanceContractError("source_raw_audit_reference_invalid")
        if not self.raw_payload_id or len(self.raw_payload_id) > 64:
            raise AssetActiveMaintenanceContractError("source_raw_payload_id_invalid")
        if (
            not isinstance(self.raw_payload_hash, str)
            or _RAW_SHA256.fullmatch(self.raw_payload_hash) is None
        ):
            raise AssetActiveMaintenanceContractError("source_raw_payload_hash_invalid")
        _sha256(self.response_body_sha256, "source_body_hash")
        _aware_utc(self.response_completed_at, "source_response_completed_at")
        if type(self.row_count) is not int or self.row_count < 0:
            raise AssetActiveMaintenanceContractError("source_row_count_invalid")


@dataclass(frozen=True, slots=True)
class AssetMasterMaintenancePlan:
    """Hash-bound exact-five maintenance plan with two source occurrences."""

    plan_file_sha256: str
    target_date: date
    targets: tuple[AssetMaintenanceTarget, ...]
    provider_contract: InstrumentReferenceProviderContract
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk
    source_occurrences: tuple[SourceOccurrencePin, ...]

    def __post_init__(self) -> None:
        """Require the existing seven-field SSE×D/SZSE×D capture contract."""

        _sha256(self.plan_file_sha256, "plan_file_hash")
        if type(self.target_date) is not date:
            raise AssetActiveMaintenanceContractError("target_date_invalid")
        if type(self.targets) is not tuple or len(self.targets) != 5:
            raise AssetActiveMaintenanceContractError("target_scope_must_contain_five_rows")
        if any(type(item) is not AssetMaintenanceTarget for item in self.targets):
            raise AssetActiveMaintenanceContractError("target_scope_invalid")
        if (
            len({item.code for item in self.targets}) != 5
            or len({item.asset_pk for item in self.targets}) != 5
        ):
            raise AssetActiveMaintenanceContractError("target_scope_duplicate")
        if type(self.provider_contract) is not InstrumentReferenceProviderContract:
            raise AssetActiveMaintenanceContractError("provider_contract_invalid")
        if type(self.crosswalk) is not InstrumentReferenceExchangeSuffixCrosswalk:
            raise AssetActiveMaintenanceContractError("source_crosswalk_invalid")
        contract = self.provider_contract
        if (
            contract.api_name != "stock_basic"
            or contract.fields != _FIELDS
            or contract.exchange_scope != ("SSE", "SZSE")
            or contract.list_status_scope != ("D",)
        ):
            raise AssetActiveMaintenanceContractError("provider_contract_scope_invalid")
        if {exchange for exchange, _suffix in self.crosswalk.exchange_suffix_pairs} != {
            "SSE",
            "SZSE",
        }:
            raise AssetActiveMaintenanceContractError("source_crosswalk_scope_invalid")
        if type(self.source_occurrences) is not tuple or len(self.source_occurrences) != 2:
            raise AssetActiveMaintenanceContractError("source_occurrence_scope_invalid")
        if any(type(item) is not SourceOccurrencePin for item in self.source_occurrences):
            raise AssetActiveMaintenanceContractError("source_occurrence_scope_invalid")
        if {item.exchange for item in self.source_occurrences} != {"SSE", "SZSE"}:
            raise AssetActiveMaintenanceContractError("source_occurrence_scope_invalid")
        audit_ids = {item.raw_audit_reference.raw_audit_id for item in self.source_occurrences}
        payload_ids = {item.raw_payload_id for item in self.source_occurrences}
        if len(audit_ids) != 2 or len(payload_ids) != 2:
            raise AssetActiveMaintenanceContractError("source_occurrence_identity_duplicate")
        if any(item.exchange not in contract.exchange_scope for item in self.source_occurrences):
            raise AssetActiveMaintenanceContractError("source_occurrence_scope_invalid")
        targets_by_exchange = {item.exchange for item in self.targets}
        if not targets_by_exchange.issubset(set(contract.exchange_scope)):
            raise AssetActiveMaintenanceContractError("target_exchange_outside_source_scope")

    @property
    def digest(self) -> str:
        """Return the canonical digest bound into the maintenance event."""

        encoded = json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(
            b"data-center.asset-active-maintenance-plan.v1\0" + encoded
        ).hexdigest()

    def to_file_payload(self) -> Mapping[str, object]:
        """Return the file content without a recursive self-hash property.

        The operator supplies the expected SHA-256 of these exact file bytes
        separately. The file never contains its own hash.
        """

        return {
            "schema": "data-center.asset-active-maintenance-plan.v1",
            "target_date": self.target_date.isoformat(),
            "targets": [
                {
                    "code": item.code,
                    "asset_pk": item.asset_pk,
                    "exchange": item.exchange,
                    "expected_delist_date": (
                        item.expected_delist_date.isoformat()
                        if item.expected_delist_date is not None
                        else None
                    ),
                    "expected_updated_at": item.expected_updated_at.isoformat(),
                    "expected_preserved_state_sha256": item.expected_preserved_state_sha256,
                }
                for item in sorted(self.targets, key=lambda target: target.asset_pk)
            ],
            "provider_contract": {
                "contract_id": self.provider_contract.contract_id,
                "contract_version": self.provider_contract.contract_version,
                "provider_name": self.provider_contract.provider_name,
                "dataset_key": self.provider_contract.dataset_key,
                "api_name": self.provider_contract.api_name,
                "fields": list(self.provider_contract.fields),
                "exchange_scope": list(self.provider_contract.exchange_scope),
                "list_status_scope": list(self.provider_contract.list_status_scope),
                "content_hash": self.provider_contract.content_hash,
            },
            "crosswalk": {
                "crosswalk_id": self.crosswalk.crosswalk_id,
                "crosswalk_version": self.crosswalk.crosswalk_version,
                "exchange_suffix_pairs": [
                    [exchange, suffix] for exchange, suffix in self.crosswalk.exchange_suffix_pairs
                ],
                "content_hash": self.crosswalk.content_hash,
            },
            "source_occurrences": [
                {
                    "exchange": item.exchange,
                    "raw_audit_id": item.raw_audit_reference.raw_audit_id,
                    "raw_audit_version": item.raw_audit_reference.version,
                    "raw_audit_content_hash": item.raw_audit_reference.content_hash,
                    "raw_audit_run_id": item.raw_audit_reference.run_id,
                    "raw_audit_ingested_run_id": item.raw_audit_reference.ingested_run_id,
                    "raw_payload_id": item.raw_payload_id,
                    "raw_payload_hash": item.raw_payload_hash,
                    "response_body_sha256": item.response_body_sha256,
                    "response_completed_at": item.response_completed_at.isoformat(),
                    "row_count": item.row_count,
                }
                for item in sorted(self.source_occurrences, key=lambda pin: pin.exchange)
            ],
        }

    def to_payload(self) -> Mapping[str, object]:
        """Return the file content plus its independently measured raw-file hash."""

        return {**self.to_file_payload(), "plan_file_sha256": self.plan_file_sha256}


def exact_plan_source_records(
    plan: AssetMasterMaintenancePlan,
    candidate: InstrumentReferenceCandidate,
) -> Mapping[str, InstrumentReferenceRecord]:
    """Rebind every planned target to one row in the two pinned source bodies."""

    if type(candidate) is not InstrumentReferenceCandidate:
        raise AssetActiveMaintenanceContractError("source_candidate_invalid")
    if (
        candidate.provider_contract != plan.provider_contract
        or candidate.crosswalk != plan.crosswalk
        or candidate.must_not_use_for_decision is not True
        or candidate.must_not_execute is not True
        or candidate.source_observed_at is not None
        or candidate.source_available_at is not None
    ):
        raise AssetActiveMaintenanceContractError("source_candidate_identity_invalid")
    pins = {pin.exchange: pin for pin in plan.source_occurrences}
    occurrences = {item.exchange: item for item in candidate.occurrences}
    if len(occurrences) != 2 or set(occurrences) != set(pins):
        raise AssetActiveMaintenanceContractError("source_candidate_occurrence_scope_invalid")
    for exchange, pin in pins.items():
        occurrence = occurrences[exchange]
        if (
            occurrence.list_status != "D"
            or occurrence.raw_audit_reference != pin.raw_audit_reference
            or occurrence.raw_payload_id != pin.raw_payload_id
            or occurrence.raw_payload_hash != pin.raw_payload_hash
            or occurrence.response_body_sha256 != pin.response_body_sha256
            or occurrence.response_completed_at != pin.response_completed_at
            or occurrence.row_count != pin.row_count
        ):
            raise AssetActiveMaintenanceContractError("source_occurrence_pin_mismatch")
    target_codes = {item.code for item in plan.targets}
    selected: dict[str, InstrumentReferenceRecord] = {}
    for row in candidate.records:
        if row.ts_code not in target_codes:
            continue
        if row.ts_code in selected:
            raise AssetActiveMaintenanceContractError("source_target_duplicate")
        target = next(item for item in plan.targets if item.code == row.ts_code)
        if (
            row.source_exchange != target.exchange
            or row.source_list_status != "D"
            or row.delist_date is None
            or row.delist_date > plan.target_date
            or row.source_observed_at is not None
            or row.source_available_at is not None
        ):
            raise AssetActiveMaintenanceContractError("source_target_not_eligible_for_scope_repair")
        selected[row.ts_code] = row
    if set(selected) != target_codes:
        raise AssetActiveMaintenanceContractError("source_target_cardinality_invalid")
    return selected


@dataclass(frozen=True, slots=True)
class AssetMasterRowSnapshot:
    """Locked master-row state with a digest of every preserved column."""

    asset_pk: int
    code: str
    asset_type: str
    exchange: str
    is_active: bool
    delist_date: date | None
    updated_at: datetime
    preserved_state_sha256: str

    def __post_init__(self) -> None:
        """Validate identity, allowed transition fields, and preservation hash."""

        if type(self.asset_pk) is not int or self.asset_pk <= 0:
            raise AssetActiveMaintenanceContractError("master_primary_key_invalid")
        if not self.code or len(self.code) > 20:
            raise AssetActiveMaintenanceContractError("master_code_invalid")
        if type(self.is_active) is not bool:
            raise AssetActiveMaintenanceContractError("master_active_flag_invalid")
        if self.delist_date is not None and type(self.delist_date) is not date:
            raise AssetActiveMaintenanceContractError("master_delist_date_invalid")
        _aware_utc(self.updated_at, "master_updated_at")
        _sha256(self.preserved_state_sha256, "master_preserved_state_hash")


@dataclass(frozen=True, slots=True)
class MaintenanceOwner:
    """One authenticated real Django user and its current narrow permission."""

    user_id: int
    username: str
    actor_id: str
    is_authenticated: bool
    is_active: bool
    can_change_assetmaster: bool

    def __post_init__(self) -> None:
        """Reject service/process actors and incomplete user authorization."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise AssetActiveMaintenanceContractError("owner_identity_invalid")
        if not self.username or self.username != self.username.strip():
            raise AssetActiveMaintenanceContractError("owner_identity_invalid")
        if self.actor_id != f"django-user:{self.user_id}":
            raise AssetActiveMaintenanceContractError("owner_actor_identity_invalid")
        if any(
            type(value) is not bool
            for value in (self.is_authenticated, self.is_active, self.can_change_assetmaster)
        ):
            raise AssetActiveMaintenanceContractError("owner_authorization_invalid")

    @property
    def is_authorized(self) -> bool:
        """Return true only for an authenticated active user with the exact permission."""

        return self.is_authenticated and self.is_active and self.can_change_assetmaster


@dataclass(frozen=True, slots=True)
class MaintenanceAuthorityContext:
    """Provider-issued DATA02 audit scope bound to the authenticated Owner."""

    actor_id: str
    user_id: int
    tenant_id: str
    owner_id: str
    authority_content_hash: str
    valid_until: datetime

    def __post_init__(self) -> None:
        """Require matching real user, scoped authority and aware validity clock."""

        if not self.actor_id or type(self.user_id) is not int or self.user_id <= 0:
            raise AssetActiveMaintenanceContractError("data02_authority_identity_invalid")
        if self.actor_id != f"django-user:{self.user_id}":
            raise AssetActiveMaintenanceContractError("data02_authority_identity_invalid")
        if not self.tenant_id or not self.owner_id:
            raise AssetActiveMaintenanceContractError("data02_authority_scope_invalid")
        _sha256(self.authority_content_hash, "data02_authority_hash")
        _aware_utc(self.valid_until, "data02_authority_valid_until")


@dataclass(frozen=True, slots=True)
class AssetMasterTransition:
    """One explicit before/after row transition, bound to its source row."""

    asset_pk: int
    code: str
    exchange: str
    prior_delist_date: date | None
    prior_updated_at: datetime
    source_delist_date: date
    preserved_state_sha256: str
    updated_at: datetime
    raw_audit_reference: RawAuditReference

    def __post_init__(self) -> None:
        """Reject inferred source date, mutable preserved columns, or weak provenance."""

        if type(self.asset_pk) is not int or self.asset_pk <= 0:
            raise AssetActiveMaintenanceContractError("transition_primary_key_invalid")
        if not self.code or self.exchange not in {"SSE", "SZSE"}:
            raise AssetActiveMaintenanceContractError("transition_identity_invalid")
        if type(self.source_delist_date) is not date:
            raise AssetActiveMaintenanceContractError("transition_source_date_invalid")
        if self.prior_delist_date is not None and type(self.prior_delist_date) is not date:
            raise AssetActiveMaintenanceContractError("transition_prior_date_invalid")
        _aware_utc(self.prior_updated_at, "transition_prior_updated_at")
        _sha256(self.preserved_state_sha256, "transition_preserved_state_hash")
        _aware_utc(self.updated_at, "transition_updated_at")
        if self.updated_at < self.prior_updated_at:
            raise AssetActiveMaintenanceContractError("transition_clock_before_preimage")
        if type(self.raw_audit_reference) is not RawAuditReference:
            raise AssetActiveMaintenanceContractError("transition_source_audit_invalid")


@dataclass(frozen=True, slots=True)
class MaintenanceAuditPlanMetadata:
    """Plan-owned descriptive fields that must survive exact audit readback."""

    target_date: date
    provider_contract_id: str
    provider_contract_version: str
    provider_name: str
    dataset_key: str
    api_name: str
    crosswalk_id: str
    crosswalk_version: str
    actor_username: str

    def __post_init__(self) -> None:
        """Reject missing descriptive identities or a non-date target."""

        if type(self.target_date) is not date:
            raise AssetActiveMaintenanceContractError("audit_metadata_target_date_invalid")
        for value in (
            self.provider_contract_id,
            self.provider_contract_version,
            self.provider_name,
            self.dataset_key,
            self.api_name,
            self.crosswalk_id,
            self.crosswalk_version,
            self.actor_username,
        ):
            if type(value) is not str or not value or value != value.strip():
                raise AssetActiveMaintenanceContractError("audit_plan_metadata_invalid")


def maintenance_audit_metadata(
    target_date: date,
    provider_contract: InstrumentReferenceProviderContract,
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
    actor_username: str,
) -> MaintenanceAuditPlanMetadata:
    """Derive the exact descriptive audit expectation from typed plan values."""

    return MaintenanceAuditPlanMetadata(
        target_date=target_date,
        provider_contract_id=provider_contract.contract_id,
        provider_contract_version=provider_contract.contract_version,
        provider_name=provider_contract.provider_name,
        dataset_key=provider_contract.dataset_key,
        api_name=provider_contract.api_name,
        crosswalk_id=crosswalk.crosswalk_id,
        crosswalk_version=crosswalk.crosswalk_version,
        actor_username=actor_username,
    )


@dataclass(frozen=True, slots=True)
class MaintenanceAuditObservation:
    """Typed user-authored maintenance transition for SystemAudit and Outbox."""

    plan_digest: str
    plan_file_sha256: str
    actor: MaintenanceOwner
    authority: MaintenanceAuthorityContext
    target_date: date
    provider_contract: InstrumentReferenceProviderContract
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk
    source_occurrences: tuple[SourceOccurrencePin, ...]
    transitions: tuple[AssetMasterTransition, ...]
    occurred_at: datetime

    @property
    def plan_metadata(self) -> MaintenanceAuditPlanMetadata:
        """Return every plan-owned descriptive field expected in the audit."""

        return maintenance_audit_metadata(
            self.target_date, self.provider_contract, self.crosswalk, self.actor.username
        )

    def __post_init__(self) -> None:
        """Validate exact five transitions and preserve source-only semantics."""

        _sha256(self.plan_digest, "maintenance_plan_digest")
        _sha256(self.plan_file_sha256, "maintenance_plan_file_hash")
        if not self.actor.is_authorized or self.authority.actor_id != self.actor.actor_id:
            raise AssetActiveMaintenanceContractError("maintenance_audit_actor_invalid")
        if self.authority.user_id != self.actor.user_id:
            raise AssetActiveMaintenanceContractError("maintenance_audit_authority_user_mismatch")
        if type(self.target_date) is not date:
            raise AssetActiveMaintenanceContractError("maintenance_audit_target_date_invalid")
        if type(self.provider_contract) is not InstrumentReferenceProviderContract:
            raise AssetActiveMaintenanceContractError("maintenance_audit_contract_invalid")
        if type(self.crosswalk) is not InstrumentReferenceExchangeSuffixCrosswalk:
            raise AssetActiveMaintenanceContractError("maintenance_audit_crosswalk_invalid")
        if type(self.source_occurrences) is not tuple or len(self.source_occurrences) != 2:
            raise AssetActiveMaintenanceContractError(
                "maintenance_audit_source_occurrences_invalid"
            )
        if type(self.transitions) is not tuple or len(self.transitions) != 5:
            raise AssetActiveMaintenanceContractError("maintenance_audit_transitions_invalid")
        if len({item.code for item in self.transitions}) != 5:
            raise AssetActiveMaintenanceContractError("maintenance_audit_transitions_duplicate")
        if len({item.raw_audit_reference.raw_audit_id for item in self.source_occurrences}) != 2:
            raise AssetActiveMaintenanceContractError("maintenance_audit_source_duplicate")
        _aware_utc(self.occurred_at, "maintenance_audit_occurred_at")
        if any(pin.response_completed_at > self.occurred_at for pin in self.source_occurrences):
            raise AssetActiveMaintenanceContractError("maintenance_clock_before_source_response")
        if self.occurred_at >= self.authority.valid_until:
            raise AssetActiveMaintenanceContractError("maintenance_audit_authority_expired")
        if any(item.source_delist_date > self.target_date for item in self.transitions):
            raise AssetActiveMaintenanceContractError("maintenance_audit_source_date_after_target")


@dataclass(frozen=True, slots=True)
class MaintenanceAuditReceipt:
    """Verified persisted user event/outbox pair used for exact idempotent replay."""

    plan_digest: str
    plan_file_sha256: str
    actor_id: str
    tenant_id: str
    owner_id: str
    authority_content_hash: str
    provider_contract_hash: str
    crosswalk_hash: str
    plan_metadata: MaintenanceAuditPlanMetadata
    source_occurrences: tuple[SourceOccurrencePin, ...]
    transitions: tuple[AssetMasterTransition, ...]
    event_id: str
    event_content_sha256: str
    outbox_id: UUID
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Require a complete event/outbox binding and exact transition scope."""

        _sha256(self.plan_digest, "receipt_plan_digest")
        _sha256(self.plan_file_sha256, "receipt_plan_file_hash")
        _sha256(self.authority_content_hash, "receipt_authority_hash")
        _sha256(self.provider_contract_hash, "receipt_provider_contract_hash")
        _sha256(self.crosswalk_hash, "receipt_crosswalk_hash")
        _sha256(self.event_content_sha256, "receipt_event_content_hash")
        if type(self.plan_metadata) is not MaintenanceAuditPlanMetadata:
            raise AssetActiveMaintenanceContractError("receipt_plan_metadata_invalid")
        if (
            not self.actor_id
            or not self.tenant_id
            or not self.owner_id
            or not self.event_id
            or type(self.outbox_id) is not UUID
        ):
            raise AssetActiveMaintenanceContractError("maintenance_audit_receipt_invalid")
        if len(self.source_occurrences) != 2 or len(self.transitions) != 5:
            raise AssetActiveMaintenanceContractError("maintenance_audit_receipt_scope_invalid")
        _aware_utc(self.recorded_at, "maintenance_audit_recorded_at")
        if any(pin.response_completed_at > self.recorded_at for pin in self.source_occurrences):
            raise AssetActiveMaintenanceContractError("receipt_clock_before_source_response")


__all__ = [
    "AssetActiveMaintenanceContractError",
    "AssetMaintenanceTarget",
    "AssetMasterMaintenancePlan",
    "AssetMasterRowSnapshot",
    "AssetMasterTransition",
    "MaintenanceAuditObservation",
    "MaintenanceAuditPlanMetadata",
    "MaintenanceAuditReceipt",
    "MaintenanceAuthorityContext",
    "MaintenanceOwner",
    "SourceOccurrencePin",
    "exact_plan_source_records",
    "maintenance_audit_metadata",
]
