"""Write and verify formal exchange-calendar publication transitions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from django.db import DatabaseError, IntegrityError

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
)
from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
    CalendarFormalPublicationSeal,
    CalendarPublicationPointerExpectation,
    CalendarPublicationTransition,
    calendar_formal_seals_have_same_evidence,
    decide_calendar_publication_transition,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import DataFetchError

from .formal_exchange_calendar_publication_support import (
    _FormalExchangeCalendarPublicationSupport,
)


class _FormalExchangeCalendarPublicationWriter(_FormalExchangeCalendarPublicationSupport):
    """Publish sealed calendars and enforce exact publication transitions."""

    def publish(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Publish or verify an exact current replay inside the caller's UoW."""

        if type(request) is not CalendarFormalPublicationRequest:
            raise DataFetchError(
                "Formal calendar request is not typed",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        try:
            request.validate()
        except CalendarFormalPublicationApplicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        connection = self._connection()
        self._require_single_caller_transaction(connection)
        self._require_router_alias()
        self._require_postgresql_read_committed(connection)
        self._validate_principal(principal, expected_database_alias=self._using)
        self._assert_principal_live(principal)
        if self._audit_port.database_alias != self._using:
            raise DataFetchError(
                "Formal calendar Audit port uses another database alias",
                code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
            )

        self._acquire_catalog_fence(connection)
        dataset_key = request.proposed_seal.dataset.value
        publication_key = request.proposed_seal.publication_key
        self._acquire_scope_fence(connection, dataset_key, publication_key)
        now = self._clock_now()
        active_contract, active_policy = self._load_active_catalog(
            dataset_key=dataset_key,
            contract_version=request.proposed_seal.dataset.contract_version,
            schema_version=request.proposed_seal.dataset.schema_version,
            knowledge_cutoff=now,
        )

        old_snapshot_ids: tuple[str, ...] = ()
        expected = request.expected_pointer
        if not expected.is_absent:
            old_snapshot_ids = self._snapshot_ids_for_publication(expected.publication_id)
        source_ids = tuple(
            sorted(
                {
                    request.proposed_seal.snapshot_reference.snapshot_id,
                    *old_snapshot_ids,
                }
            )
        )
        snapshots, facts = self._lock_and_rebuild_snapshots(source_ids)
        proposal_snapshot = snapshots.get(request.proposed_seal.snapshot_reference.snapshot_id)
        if proposal_snapshot is None:
            raise DataFetchError(
                "Proposed calendar source snapshot is unavailable",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        proposal_fact = facts.get(proposal_snapshot.snapshot_id)
        if proposal_fact is None:
            raise DataFetchError(
                "Proposed calendar source fact was not locked",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        publication_id = str(uuid4())
        member_id = str(uuid4())
        proposed_recorded_seal = self._build_seal(
            snapshot=proposal_snapshot,
            fact_model=proposal_fact,
            contract=active_contract,
            policy_model=active_policy,
            member_id=member_id,
            publication_id=publication_id,
        )
        if not calendar_formal_seals_have_same_evidence(
            request.proposed_seal, proposed_recorded_seal
        ):
            raise DataFetchError(
                "Formal calendar proposal differs from the exact persisted source or catalog",
                code="CALENDAR_FORMAL_PROPOSAL_MISMATCH",
            )

        pointer_model = self._lock_pointer(dataset_key, publication_key)
        actual_pointer = self._pointer_expectation(pointer_model, dataset_key, publication_key)
        if actual_pointer != request.expected_pointer:
            raise DataFetchError(
                "Formal calendar pointer differs from the supplied compare-and-swap token",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )
        current_record: CalendarFormalPublicationRecord | None = None
        if pointer_model is not None:
            if actual_pointer.is_absent:
                raise DataFetchError(
                    "Formal calendar pointer contains an empty placeholder",
                    code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
                )
            current_record = self._load_record(
                publication_id=actual_pointer.publication_id,
                activation_id=actual_pointer.activation_id,
                snapshots=snapshots,
                facts=facts,
                knowledge_cutoff=now,
                lock_rows=True,
            )
        elif self._has_scope_publications(dataset_key, publication_key):
            raise DataFetchError(
                "Formal calendar publication history exists without a current pointer",
                code="CALENDAR_FORMAL_POINTER_MISSING",
            )

        try:
            transition = decide_calendar_publication_transition(
                proposed_seal=proposed_recorded_seal,
                expected_pointer=request.expected_pointer,
                actual_pointer=actual_pointer,
                current_record=current_record,
                activation_id=request.activation_id,
            )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error

        if transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY:
            if current_record is None:
                raise DataFetchError(
                    "Exact current replay has no persisted publication record",
                    code="CALENDAR_PUBLICATION_REPLAY_INVALID",
                )
            pair = self._audit_port.verify_current_replay(
                current_record,
                principal=principal,
            )
            self._verify_audit_pair(
                pair,
                record=current_record,
                expected_actor=principal.user_id,
                as_of=None,
            )
            post_audit_checked_at = self._clock_now()
            self._validate_post_audit(
                record=current_record,
                principal=principal,
                started_at=now,
                checked_at=post_audit_checked_at,
            )
            return CalendarFormalPublicationCommit(
                record=current_record,
                pointer=actual_pointer,
                transition=transition,
                audit_pair=pair,
                post_audit_checked_at=post_audit_checked_at,
            )

        self._reject_existing_publication_hash(
            dataset_key=dataset_key,
            publication_key=publication_key,
            publication_hash=proposed_recorded_seal.publication_hash,
        )

        published_at = self._clock_now()
        self._validate_new_publication_time(
            published_at=published_at,
            principal=principal,
            seal=proposed_recorded_seal,
            previous_pointer=actual_pointer,
            transition=transition,
        )
        if transition is CalendarPublicationTransition.FORWARD_PUBLISH:
            if current_record is None:
                raise DataFetchError(
                    "Forward calendar publication has no exact current record",
                    code="CALENDAR_POINTER_TARGET_INVALID",
                )
            previous_pair = self._audit_port.verify_published_integrity(
                current_record, as_of=published_at
            )
            self._verify_audit_pair(
                previous_pair,
                record=current_record,
                expected_actor=None,
                as_of=published_at,
            )
            self._assert_principal_live(principal)
        record = self._persist_new_publication(
            seal=proposed_recorded_seal,
            publication_id=publication_id,
            member_id=member_id,
            activation_id=request.activation_id,
            published_at=published_at,
            previous_record=current_record,
            pointer_model=pointer_model,
            previous_pointer=actual_pointer,
            transition=transition,
        )
        pair = self._audit_port.record_published(
            record,
            principal=principal,
        )
        self._verify_audit_pair(
            pair,
            record=record,
            expected_actor=principal.user_id,
            as_of=None,
        )
        post_audit_checked_at = self._clock_now()
        self._validate_post_audit(
            record=record,
            principal=principal,
            started_at=published_at,
            checked_at=post_audit_checked_at,
        )
        persisted_pointer = self._read_pointer(dataset_key, publication_key)
        if persisted_pointer is None or (
            pointer_model is not None and persisted_pointer.pointer_id != pointer_model.pointer_id
        ):
            raise DataFetchError(
                "Formal calendar pointer disappeared before commit verification",
                code="CALENDAR_FORMAL_POINTER_MISMATCH",
            )
        pointer = self._pointer_expectation(persisted_pointer, dataset_key, publication_key)
        return CalendarFormalPublicationCommit(
            record=record,
            pointer=pointer,
            transition=transition,
            audit_pair=pair,
            post_audit_checked_at=post_audit_checked_at,
        )

    def _reject_existing_publication_hash(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        publication_hash: str,
    ) -> None:
        """Prevent reactivation of a superseded or otherwise historical target."""

        exists = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_hash=publication_hash,
            )
            .exists()
        )
        if exists:
            raise DataFetchError(
                "Formal calendar content already has a historical publication row",
                code="CALENDAR_FORMAL_REACTIVATION_UNSUPPORTED",
            )

    def _persist_new_publication(
        self,
        *,
        seal: CalendarFormalPublicationSeal,
        publication_id: str,
        member_id: str,
        activation_id: str,
        published_at: datetime,
        previous_record: CalendarFormalPublicationRecord | None,
        pointer_model: CanonicalPublicationPointerModel | None,
        previous_pointer: CalendarPublicationPointerExpectation,
        transition: CalendarPublicationTransition,
    ) -> CalendarFormalPublicationRecord:
        """Insert one immutable publication/member/coverage and move its pointer."""

        if transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if pointer_model is not None or previous_record is not None:
                raise DataFetchError(
                    "First calendar publication cannot reuse an existing pointer",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
        elif transition is CalendarPublicationTransition.FORWARD_PUBLISH:
            previous_time = previous_pointer.updated_at
            if (
                pointer_model is None
                or previous_record is None
                or previous_time is None
                or published_at <= previous_time
            ):
                raise DataFetchError(
                    "Calendar forward publication time must strictly advance the pointer",
                    code="CALENDAR_PUBLICATION_FORWARD_TIME_INVALID",
                )
        else:
            raise DataFetchError(
                "Unsupported formal calendar persistence transition",
                code="CALENDAR_PUBLICATION_TRANSITION_INVALID",
            )
        record = CalendarFormalPublicationRecord(
            seal=seal,
            publication_id=publication_id,
            activation_id=activation_id,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            published_at=published_at,
        )
        member = seal.member_reference.member
        try:
            publication_model = CanonicalPublicationModel._default_manager.using(
                self._using
            ).create(
                publication_id=UUID(publication_id),
                dataset_key=seal.dataset.value,
                publication_key=seal.publication_key,
                policy_version=seal.policy.policy_version,
                state="published",
                selected_source=member.source,
                publication_hash=seal.publication_hash,
                member_manifest_hash=seal.member_manifest_hash,
                member_count=1,
                conflict_count=0,
                coverage_requested_count=1,
                coverage_eligible_count=1,
                coverage_selected_count=1,
                coverage_missing_count=0,
                coverage_conflict_count=0,
                as_of=published_at,
                published_at=published_at,
                superseded_at=None,
                reinstated_at=None,
                must_not_use_for_decision=False,
                blocked_reason="",
                created_by="calendar-formal-publication",
                run_id=None,
                scope_blocks=[],
                members_sealed_at=published_at,
            )
            PublicationMemberModel._default_manager.using(self._using).create(
                member_id=UUID(member_id),
                publication_id=UUID(publication_id),
                dataset_key=member.dataset_key,
                natural_key=member.natural_key,
                source=member.source,
                source_record_id=member.source_record_id,
                fact_table=member.fact_table,
                fact_pk=member.fact_pk,
                observed_at=member.observed_at,
                raw_payload_hash=member.raw_payload_hash,
                quality_status=member.quality_status,
                revision_number=member.revision_number,
                available_at=member.available_at,
                fetched_at=member.fetched_at,
                source_published_at=member.source_published_at,
                raw_payload_scope=member.raw_payload_scope,
                fact_content_hash=member.fact_content_hash,
            )
            CoverageSnapshotModel._default_manager.using(self._using).create(
                coverage_id=UUID(publication_id),
                publication_id=UUID(publication_id),
                requested_count=1,
                eligible_count=1,
                selected_count=1,
                missing_count=0,
                conflict_count=0,
                generated_at=published_at,
            )
            if transition is CalendarPublicationTransition.FORWARD_PUBLISH:
                assert previous_record is not None
                superseded = (
                    CanonicalPublicationModel._default_manager.using(self._using)
                    .filter(
                        publication_id=UUID(previous_record.publication_id),
                        state="published",
                        superseded_at__isnull=True,
                        reinstated_at__isnull=True,
                        published_at=previous_record.published_at,
                    )
                    .update(
                        state="superseded",
                        superseded_at=published_at,
                        updated_at=published_at,
                    )
                )
                if superseded != 1:
                    raise DataFetchError(
                        "Previous calendar publication changed before supersession",
                        code="CALENDAR_PUBLICATION_FORWARD_CONFLICT",
                    )
            self._move_pointer(
                pointer_model=pointer_model,
                previous_pointer=previous_pointer,
                dataset_key=seal.dataset.value,
                publication_key=seal.publication_key,
                publication_id=UUID(publication_id),
                publication_hash=seal.publication_hash,
                activation_id=activation_id,
                published_at=published_at,
                transition=transition,
            )
        except IntegrityError as error:
            raise DataFetchError(
                "Formal calendar publication uniqueness or row constraint failed",
                code="CALENDAR_FORMAL_WRITE_CONFLICT",
            ) from error
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar publication storage is unavailable",
                code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
            ) from error
        if publication_model.publication_id != UUID(record.publication_id):
            raise DataFetchError(
                "Formal calendar publication row identity differs from its record",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )
        return record

    def _move_pointer(
        self,
        *,
        pointer_model: CanonicalPublicationPointerModel | None,
        previous_pointer: CalendarPublicationPointerExpectation,
        dataset_key: str,
        publication_key: str,
        publication_id: UUID,
        publication_hash: str,
        activation_id: str,
        published_at: datetime,
        transition: CalendarPublicationTransition,
    ) -> None:
        """Insert first pointer or compare-and-swap its exact prior epoch."""

        pointers = CanonicalPublicationPointerModel._default_manager.using(self._using)
        if transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if pointer_model is not None or not previous_pointer.is_absent:
                raise DataFetchError(
                    "First calendar publication pointer must still be absent",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
            pointer = pointers.create(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_id=publication_id,
                publication_hash=publication_hash,
                activation_id=activation_id,
            )
            updated = pointers.filter(pointer_id=pointer.pointer_id).update(updated_at=published_at)
        else:
            if pointer_model is None or previous_pointer.updated_at is None:
                raise DataFetchError(
                    "Forward calendar pointer is missing its prior epoch",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
            updated = pointers.filter(
                pointer_id=UUID(previous_pointer.pointer_id or ""),
                dataset_key=previous_pointer.dataset_key,
                publication_key=previous_pointer.publication_key,
                publication_id=UUID(previous_pointer.publication_id or ""),
                publication_hash=previous_pointer.publication_hash,
                activation_id=previous_pointer.activation_id,
                updated_at=previous_pointer.updated_at,
            ).update(
                publication_id=publication_id,
                publication_hash=publication_hash,
                activation_id=activation_id,
                updated_at=published_at,
            )
        if updated != 1:
            raise DataFetchError(
                "Formal calendar pointer compare-and-swap failed",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )

    def _validate_new_publication_time(
        self,
        *,
        published_at: datetime,
        principal: LockedCalendarPublisherPrincipal,
        seal: CalendarFormalPublicationSeal,
        previous_pointer: CalendarPublicationPointerExpectation,
        transition: CalendarPublicationTransition,
    ) -> None:
        """Enforce source/config/authority chronology and strict forward movement."""

        if published_at < principal.verified_at:
            raise DataFetchError(
                "Calendar publication time precedes locked publisher verification",
                code="CALENDAR_PUBLICATION_AUTHORITY_TIME_INVALID",
            )
        if published_at < max(
            seal.snapshot_recorded_at,
            seal.contract_recorded_at,
            seal.policy_recorded_at,
        ):
            raise DataFetchError(
                "Calendar publication time precedes its source or catalog knowledge",
                code="CALENDAR_FORMAL_KNOWLEDGE_TIME_INVALID",
            )
        previous_time = previous_pointer.updated_at
        if transition is CalendarPublicationTransition.FORWARD_PUBLISH and (
            previous_time is None or published_at <= previous_time
        ):
            raise DataFetchError(
                "Calendar forward publication time must strictly advance the pointer",
                code="CALENDAR_PUBLICATION_FORWARD_TIME_INVALID",
            )

    def _validate_post_audit(
        self,
        *,
        record: CalendarFormalPublicationRecord,
        principal: LockedCalendarPublisherPrincipal,
        started_at: datetime,
        checked_at: datetime,
    ) -> None:
        """Revalidate lease, monotonic clock, and response TTL after Audit I/O."""

        self._assert_principal_live(principal)
        self._validate_principal(principal, expected_database_alias=self._using)
        if checked_at < started_at or checked_at < principal.verified_at:
            raise DataFetchError(
                "Calendar repository clock moved backward after Audit I/O",
                code="CALENDAR_FORMAL_CLOCK_MOVED_BACKWARD",
            )
        try:
            if not record.is_effective_at(checked_at):
                raise DataFetchError(
                    "Calendar source response TTL expired before transaction completion",
                    code="CALENDAR_FORMAL_TTL_EXPIRED",
                )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
