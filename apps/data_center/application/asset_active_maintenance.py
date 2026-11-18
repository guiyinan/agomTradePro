"""Owner-authorized exact-scope maintenance orchestration.

The use case changes only the five explicitly planned AssetMaster rows. It
cannot promote source-only listing data into decision or execution evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.data_center.domain.asset_active_maintenance import (
    AssetActiveMaintenanceContractError,
    AssetMaintenanceTarget,
    AssetMasterMaintenancePlan,
    AssetMasterRowSnapshot,
    AssetMasterTransition,
    MaintenanceAuditObservation,
    MaintenanceAuditReceipt,
    MaintenanceAuthorityContext,
    MaintenanceOwner,
    exact_plan_source_records,
    maintenance_audit_metadata,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceRecord,
)
from apps.data_center.domain.market_time import cn_market_date_from_observation
from core.exceptions import BusinessLogicError


class AssetActiveMaintenanceError(BusinessLogicError):
    """Raised when maintenance is not authorized or cannot be proven exact."""

    def __init__(self, code: str) -> None:
        """Create an exception with a stable non-sensitive reason code."""

        if not isinstance(code, str) or not code or not code.isascii():
            raise ValueError("maintenance error code must be ASCII")
        self.code = code
        super().__init__(code, code=code, status_code=409)


class AssetMaintenanceSourceReader(Protocol):
    """Read and independently replay the exact retained source occurrences."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database identity used to read RawAudit and RawPayload."""

    def read_verified(self, plan: AssetMasterMaintenancePlan) -> InstrumentReferenceCandidate:
        """Replay both pinned raw bodies and return their source-only candidate."""


class AssetMaintenanceOwnerPort(Protocol):
    """Return and recheck the actual authenticated Django user and permission."""

    def current_owner(self) -> MaintenanceOwner:
        """Return the real user authenticated by the management command."""

    def is_current(self, expected: MaintenanceOwner) -> bool:
        """Reload that user's active and permission state without trusting CLI claims."""


class AssetMaintenanceAuthorityPort(Protocol):
    """Resolve and revalidate provider-issued DATA02/SystemAudit authority."""

    def current_context(
        self,
        owner: MaintenanceOwner,
        *,
        as_of: datetime,
    ) -> MaintenanceAuthorityContext:
        """Return a current authority scope bound to the exact real user."""

    def is_current(self, context: MaintenanceAuthorityContext, *, as_of: datetime) -> bool:
        """Revalidate the same authority at a write or audit boundary."""


class AssetMaintenanceRepository(Protocol):
    """Lock exact old-schema rows and update only the permitted three columns."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity used by this repository."""

    def lock_exact_targets(
        self,
        targets: tuple[AssetMaintenanceTarget, ...],
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        """Lock exactly the planned rows in ascending primary-key order."""

    def deactivate_exact_targets(
        self,
        transitions: tuple[AssetMasterTransition, ...],
    ) -> int:
        """Update only ``is_active``, ``delist_date`` and ``updated_at``."""

    def read_exact_targets(
        self,
        targets: tuple[AssetMaintenanceTarget, ...],
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        """Read back exactly the planned rows while the outer transaction is open."""


class AssetMaintenanceUnitOfWork(Protocol):
    """Open the one same-alias outer transaction for master and audit writes."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one non-nested transaction shared with SystemAudit and Outbox."""


class AssetMaintenanceAuditPort(Protocol):
    """Read/replay or append one exact user SystemAudit event/outbox pair."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity used by both audit stores."""

    def find_exact(self, plan_digest: str) -> MaintenanceAuditReceipt | None:
        """Return an exact validated event/outbox winner for this plan, if any."""

    def record_once(self, observation: MaintenanceAuditObservation) -> MaintenanceAuditReceipt:
        """Append one canonical user event and exact outbox payload atomically."""


class AssetMaintenanceClock(Protocol):
    """Provide the authoritative local maintenance timestamp."""

    def now(self) -> datetime:
        """Return one aware UTC timestamp."""


@dataclass(frozen=True, slots=True)
class AssetMaintenanceResult:
    """Bounded outcome of one exact-five maintenance attempt."""

    outcome: str
    requested: int
    succeeded: int
    failed: int
    stored: int
    plan_digest: str
    event_id: str


class AssetActiveMaintenance:
    """Apply an explicitly hash-bound Owner collection-scope repair."""

    __slots__ = (
        "_source_reader",
        "_owner_port",
        "_authority_port",
        "_repository",
        "_unit_of_work",
        "_audit",
        "_clock",
    )

    def __init__(
        self,
        *,
        source_reader: AssetMaintenanceSourceReader,
        owner_port: AssetMaintenanceOwnerPort,
        authority_port: AssetMaintenanceAuthorityPort,
        repository: AssetMaintenanceRepository,
        unit_of_work: AssetMaintenanceUnitOfWork,
        audit: AssetMaintenanceAuditPort,
        clock: AssetMaintenanceClock,
    ) -> None:
        """Inject all source, Owner, authority, persistence, audit, and clock ports."""

        identity = unit_of_work.unit_of_work_key
        if (
            not identity
            or repository.unit_of_work_key != identity
            or source_reader.unit_of_work_key != identity
            or audit.unit_of_work_key != identity
        ):
            raise ValueError("asset maintenance participants must share one database UOW")
        self._source_reader = source_reader
        self._owner_port = owner_port
        self._authority_port = authority_port
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._audit = audit
        self._clock = clock

    def execute(
        self,
        plan: AssetMasterMaintenancePlan,
        *,
        expected_plan_file_sha256: str,
    ) -> AssetMaintenanceResult:
        """Verify and apply the exact plan under Owner, authority and UOW fences."""

        if expected_plan_file_sha256 != plan.plan_file_sha256:
            raise AssetActiveMaintenanceError("plan_hash_mismatch")
        preflight_at = self._now()
        self._validate_plan_clocks(plan, preflight_at)
        owner = self._require_owner()
        authority = self._current_authority(owner)
        first_candidate = self._read_source(plan)
        first_records = self._source_records(plan, first_candidate)

        try:
            with self._unit_of_work.atomic():
                self._require_same_owner(owner)
                self._require_current_authority(authority)
                second_candidate = self._read_source(plan)
                second_records = self._source_records(plan, second_candidate)
                if second_candidate != first_candidate or second_records != first_records:
                    raise AssetActiveMaintenanceError("source_readback_changed")
                self._validate_plan_clocks(plan, self._now())

                targets = tuple(sorted(plan.targets, key=lambda item: item.asset_pk))
                before = self._repository.lock_exact_targets(targets)
                self._validate_before_image(targets, before)
                existing = self._audit.find_exact(plan.digest)
                if existing is not None:
                    self._validate_replay(
                        plan=plan,
                        owner=owner,
                        authority=authority,
                        source_records=second_records,
                        receipt=existing,
                        current=before,
                        as_of=self._now(),
                    )
                    self._require_same_owner(owner)
                    self._require_current_authority(authority)
                    return AssetMaintenanceResult(
                        outcome="noop",
                        requested=5,
                        succeeded=5,
                        failed=0,
                        stored=0,
                        plan_digest=plan.digest,
                        event_id=existing.event_id,
                    )

                self._validate_expected_preimage(plan, before)

                self._require_same_owner(owner)
                self._require_current_authority(authority)
                maintenance_at = self._now()
                if maintenance_at >= authority.valid_until:
                    raise AssetActiveMaintenanceError("data02_authority_expired")
                if any(
                    pin.response_completed_at > maintenance_at for pin in plan.source_occurrences
                ):
                    raise AssetActiveMaintenanceError("source_response_from_future")
                transitions = self._build_transitions(
                    plan=plan,
                    source_records=second_records,
                    before=before,
                    updated_at=maintenance_at,
                )
                changed = self._repository.deactivate_exact_targets(transitions)
                if changed != 5:
                    raise AssetActiveMaintenanceError("asset_update_cardinality_invalid")
                after = self._repository.read_exact_targets(targets)
                self._validate_after_image(targets, transitions, before, after)
                self._require_same_owner(owner)
                self._require_current_authority(authority)
                observation = MaintenanceAuditObservation(
                    plan_digest=plan.digest,
                    plan_file_sha256=plan.plan_file_sha256,
                    actor=owner,
                    authority=authority,
                    target_date=plan.target_date,
                    provider_contract=plan.provider_contract,
                    crosswalk=plan.crosswalk,
                    source_occurrences=tuple(
                        sorted(plan.source_occurrences, key=lambda item: item.exchange)
                    ),
                    transitions=transitions,
                    occurred_at=maintenance_at,
                )
                receipt = self._audit.record_once(observation)
                self._validate_new_receipt(observation, receipt)
                self._require_same_owner(owner)
                self._require_current_authority(authority)
        except AssetActiveMaintenanceError:
            raise
        except AssetActiveMaintenanceContractError as error:
            raise AssetActiveMaintenanceError(error.code) from error

        return AssetMaintenanceResult(
            outcome="success",
            requested=5,
            succeeded=5,
            failed=0,
            stored=5,
            plan_digest=plan.digest,
            event_id=receipt.event_id,
        )

    def _require_owner(self) -> MaintenanceOwner:
        """Require the current real user, active state, and exact model permission."""

        owner = self._owner_port.current_owner()
        if type(owner) is not MaintenanceOwner or not owner.is_authorized:
            raise AssetActiveMaintenanceError("owner_authentication_or_permission_invalid")
        if not self._owner_port.is_current(owner):
            raise AssetActiveMaintenanceError("owner_authentication_or_permission_changed")
        return owner

    def _require_same_owner(self, owner: MaintenanceOwner) -> None:
        """Recheck the same active user and permission at a mutation boundary."""

        if not self._owner_port.is_current(owner):
            raise AssetActiveMaintenanceError("owner_authentication_or_permission_changed")

    def _current_authority(self, owner: MaintenanceOwner) -> MaintenanceAuthorityContext:
        """Resolve current DATA02 authority and bind it to the authenticated user."""

        context = self._authority_port.current_context(owner, as_of=self._now())
        if (
            type(context) is not MaintenanceAuthorityContext
            or context.actor_id != owner.actor_id
            or context.user_id != owner.user_id
            or context.valid_until <= self._now()
        ):
            raise AssetActiveMaintenanceError("data02_authority_unavailable")
        return context

    @staticmethod
    def _validate_plan_clocks(plan: AssetMasterMaintenancePlan, as_of: datetime) -> None:
        """Reject a future target date or source response newer than local knowledge."""

        if plan.target_date > cn_market_date_from_observation(as_of):
            raise AssetActiveMaintenanceError("target_date_in_future")
        if any(target.expected_updated_at > as_of for target in plan.targets):
            raise AssetActiveMaintenanceError("asset_preimage_clock_from_future")
        if any(pin.response_completed_at > as_of for pin in plan.source_occurrences):
            raise AssetActiveMaintenanceError("source_response_from_future")

    def _require_current_authority(self, context: MaintenanceAuthorityContext) -> None:
        """Revalidate the provider-issued authority at the exact current boundary."""

        now = self._now()
        if now >= context.valid_until or not self._authority_port.is_current(context, as_of=now):
            raise AssetActiveMaintenanceError("data02_authority_changed_or_expired")

    def _read_source(self, plan: AssetMasterMaintenancePlan) -> InstrumentReferenceCandidate:
        """Read the exact retained RawAudit/RawPayload bodies through the injected port."""

        try:
            candidate = self._source_reader.read_verified(plan)
        except AssetActiveMaintenanceError:
            raise
        except Exception as error:
            raise AssetActiveMaintenanceError("source_raw_evidence_unavailable") from error
        if type(candidate) is not InstrumentReferenceCandidate:
            raise AssetActiveMaintenanceError("source_candidate_invalid")
        return candidate

    @staticmethod
    def _source_records(
        plan: AssetMasterMaintenancePlan,
        candidate: InstrumentReferenceCandidate,
    ) -> Mapping[str, InstrumentReferenceRecord]:
        """Verify source scope, timestamps, both audits, and all five exact rows."""

        try:
            return exact_plan_source_records(plan, candidate)
        except AssetActiveMaintenanceContractError as error:
            raise AssetActiveMaintenanceError(error.code) from error

    @staticmethod
    def _validate_before_image(
        targets: tuple[AssetMaintenanceTarget, ...],
        rows: tuple[AssetMasterRowSnapshot, ...],
    ) -> None:
        """Require precisely the planned active stock rows and preimage values."""

        if type(rows) is not tuple or len(rows) != 5:
            raise AssetActiveMaintenanceError("asset_target_cardinality_invalid")
        if tuple(row.asset_pk for row in rows) != tuple(sorted(row.asset_pk for row in rows)):
            raise AssetActiveMaintenanceError("asset_lock_order_invalid")
        by_code = {row.code: row for row in rows}
        if len(by_code) != 5 or set(by_code) != {item.code for item in targets}:
            raise AssetActiveMaintenanceError("asset_target_identity_mismatch")
        for target in targets:
            row = by_code[target.code]
            if (
                row.asset_pk != target.asset_pk
                or row.asset_type != "stock"
                or row.exchange != target.exchange
            ):
                raise AssetActiveMaintenanceError("asset_target_preimage_mismatch")

    @staticmethod
    def _validate_expected_preimage(
        plan: AssetMasterMaintenancePlan,
        rows: tuple[AssetMasterRowSnapshot, ...],
    ) -> None:
        """Require the Owner-reviewed preimage before the first mutation."""

        expected = {item.code: item for item in plan.targets}
        for row in rows:
            target = expected[row.code]
            if (
                not row.is_active
                or row.delist_date != target.expected_delist_date
                or row.updated_at != target.expected_updated_at
                or row.preserved_state_sha256 != target.expected_preserved_state_sha256
            ):
                raise AssetActiveMaintenanceError("asset_target_preimage_changed")

    @staticmethod
    def _build_transitions(
        *,
        plan: AssetMasterMaintenancePlan,
        source_records: Mapping[str, InstrumentReferenceRecord],
        before: tuple[AssetMasterRowSnapshot, ...],
        updated_at: datetime,
    ) -> tuple[AssetMasterTransition, ...]:
        """Bind each allowed change to its exact source row and locked preimage."""

        prior_by_code = {row.code: row for row in before}
        target_by_code = {item.code: item for item in plan.targets}
        occurrence_by_id = {
            item.raw_audit_reference.raw_audit_id: item for item in plan.source_occurrences
        }
        transitions: list[AssetMasterTransition] = []
        for code in sorted(target_by_code):
            target = target_by_code[code]
            source_record = source_records[code]
            prior = prior_by_code[code]
            pin = occurrence_by_id.get(source_record.raw_audit_reference.raw_audit_id)
            if pin is None or source_record.delist_date is None:
                raise AssetActiveMaintenanceError("source_target_binding_invalid")
            transitions.append(
                AssetMasterTransition(
                    asset_pk=target.asset_pk,
                    code=code,
                    exchange=target.exchange,
                    prior_delist_date=prior.delist_date,
                    prior_updated_at=prior.updated_at,
                    source_delist_date=source_record.delist_date,
                    preserved_state_sha256=prior.preserved_state_sha256,
                    updated_at=updated_at,
                    raw_audit_reference=pin.raw_audit_reference,
                )
            )
        return tuple(transitions)

    @staticmethod
    def _validate_after_image(
        targets: tuple[AssetMaintenanceTarget, ...],
        transitions: tuple[AssetMasterTransition, ...],
        before: tuple[AssetMasterRowSnapshot, ...],
        after: tuple[AssetMasterRowSnapshot, ...],
    ) -> None:
        """Require only the approved active/date/clock transition on all five rows."""

        before_by_code = {row.code: row for row in before}
        transition_by_code = {item.code: item for item in transitions}
        if type(after) is not tuple or len(after) != 5:
            raise AssetActiveMaintenanceError("asset_readback_cardinality_invalid")
        if {row.code for row in after} != {target.code for target in targets}:
            raise AssetActiveMaintenanceError("asset_readback_identity_mismatch")
        for row in after:
            transition = transition_by_code[row.code]
            prior = before_by_code[row.code]
            if (
                row.asset_pk != transition.asset_pk
                or row.asset_type != "stock"
                or row.exchange != transition.exchange
                or row.is_active is not False
                or row.delist_date != transition.source_delist_date
                or row.updated_at != transition.updated_at
                or row.preserved_state_sha256 != prior.preserved_state_sha256
            ):
                raise AssetActiveMaintenanceError("asset_readback_mutation_mismatch")

    @staticmethod
    def _validate_replay(
        *,
        plan: AssetMasterMaintenancePlan,
        owner: MaintenanceOwner,
        authority: MaintenanceAuthorityContext,
        source_records: Mapping[str, InstrumentReferenceRecord],
        receipt: MaintenanceAuditReceipt,
        current: tuple[AssetMasterRowSnapshot, ...],
        as_of: datetime,
    ) -> None:
        """Accept idempotency only when the exact event/outbox and after-state match."""

        if (
            receipt.plan_digest != plan.digest
            or receipt.plan_file_sha256 != plan.plan_file_sha256
            or receipt.actor_id != owner.actor_id
            or receipt.tenant_id != authority.tenant_id
            or receipt.owner_id != authority.owner_id
            or receipt.provider_contract_hash != plan.provider_contract.content_hash
            or receipt.crosswalk_hash != plan.crosswalk.content_hash
            or receipt.plan_metadata
            != maintenance_audit_metadata(
                plan.target_date, plan.provider_contract, plan.crosswalk, owner.username
            )
            or receipt.source_occurrences
            != tuple(sorted(plan.source_occurrences, key=lambda item: item.exchange))
            or receipt.recorded_at > as_of
            or any(
                pin.response_completed_at > receipt.recorded_at for pin in plan.source_occurrences
            )
        ):
            raise AssetActiveMaintenanceError("maintenance_audit_replay_mismatch")
        target_by_code = {item.code: item for item in plan.targets}
        transition_by_code = {item.code: item for item in receipt.transitions}
        if set(transition_by_code) != set(target_by_code) or len(current) != 5:
            raise AssetActiveMaintenanceError("maintenance_audit_replay_scope_invalid")
        current_by_code = {row.code: row for row in current}
        for code, target in target_by_code.items():
            row = current_by_code.get(code)
            transition = transition_by_code[code]
            source = source_records[code]
            if (
                row is None
                or transition.asset_pk != target.asset_pk
                or transition.exchange != target.exchange
                or transition.prior_delist_date != target.expected_delist_date
                or transition.prior_updated_at != target.expected_updated_at
                or transition.preserved_state_sha256 != target.expected_preserved_state_sha256
                or transition.raw_audit_reference != source.raw_audit_reference
                or transition.source_delist_date != source.delist_date
                or row.asset_pk != transition.asset_pk
                or row.asset_type != "stock"
                or row.exchange != target.exchange
                or row.is_active is not False
                or row.delist_date != transition.source_delist_date
                or row.updated_at != transition.updated_at
                or row.preserved_state_sha256 != transition.preserved_state_sha256
            ):
                raise AssetActiveMaintenanceError("inactive_without_exact_audit")

    @staticmethod
    def _validate_new_receipt(
        observation: MaintenanceAuditObservation,
        receipt: MaintenanceAuditReceipt,
    ) -> None:
        """Require the Audit adapter to return the exact newly written pair."""

        if (
            type(receipt) is not MaintenanceAuditReceipt
            or receipt.plan_digest != observation.plan_digest
            or receipt.plan_file_sha256 != observation.plan_file_sha256
            or receipt.actor_id != observation.actor.actor_id
            or receipt.tenant_id != observation.authority.tenant_id
            or receipt.owner_id != observation.authority.owner_id
            or receipt.authority_content_hash != observation.authority.authority_content_hash
            or receipt.provider_contract_hash != observation.provider_contract.content_hash
            or receipt.crosswalk_hash != observation.crosswalk.content_hash
            or receipt.plan_metadata != observation.plan_metadata
            or receipt.source_occurrences != observation.source_occurrences
            or receipt.transitions != observation.transitions
            or receipt.recorded_at != observation.occurred_at
        ):
            raise AssetActiveMaintenanceError("system_audit_outbox_readback_mismatch")

    def _now(self) -> datetime:
        """Read a strict aware UTC timestamp from the injected server clock."""

        value = self._clock.now()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise AssetActiveMaintenanceError("maintenance_clock_invalid")
        return value


__all__ = [
    "AssetActiveMaintenance",
    "AssetActiveMaintenanceError",
    "AssetMaintenanceAuditPort",
    "AssetMaintenanceAuthorityPort",
    "AssetMaintenanceClock",
    "AssetMaintenanceOwnerPort",
    "AssetMaintenanceRepository",
    "AssetMaintenanceResult",
    "AssetMaintenanceSourceReader",
    "AssetMaintenanceUnitOfWork",
]
