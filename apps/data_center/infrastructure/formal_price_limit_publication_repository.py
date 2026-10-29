"""Atomic reference publication, exact history and explicit pointer rollback."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from uuid import UUID, uuid4

from django.db import connections, transaction

from apps.data_center.application.price_limit_formal_publication_audit_port import (
    PriceLimitFormalPublicationAuditPort,
    PriceLimitFormalPublicationReferenceAuditPort,
    PriceLimitPublicationAuditPair,
)
from apps.data_center.application.price_limit_publication_authority import (
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.application.price_limit_publication_operations import (
    PreviewPriceLimitPublicationIntent,
    PriceLimitPublicationAction,
    PriceLimitPublicationPreparation,
    PriceLimitPublicationPreview,
    PriceLimitPublicationReadResult,
    PriceLimitPublicationReceipt,
    PriceLimitPublicationScope,
    ReadPriceLimitPublicationIntent,
    require_utc,
)
from apps.data_center.domain.control_plane import PublicationRollback
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationPointerExpectation,
    PriceLimitPublicationTimelineEvent,
    resolve_price_limit_publication_at,
    validate_price_limit_publication_timeline,
)

from .formal_price_limit_publication_support import (
    DATASET,
    REFERENCE_REASON,
    REFERENCE_STATE,
    SUPERSEDED_STATE,
    _History,
    _PriceLimitPublicationSupport,
    blocked,
    storage_errors,
)
from .publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)


class DjangoFormalPriceLimitPublicationRepository(_PriceLimitPublicationSupport):
    """Persist a complete restricted lifecycle using the original publication tables."""

    _audit: PriceLimitFormalPublicationAuditPort

    def __init__(
        self, audit: PriceLimitFormalPublicationAuditPort, *, using: str = "default"
    ) -> None:
        """Require the Core-injected Audit bridge on the same explicit alias."""
        self._audit = audit
        self._using = using

    @storage_errors
    def prepare(
        self,
        intent: PreviewPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationPreparation:
        """Load exact source/catalog/history without creating a candidate or pointer."""
        intent.__post_init__()
        self._fence(intent.scope, principal, server_now)
        contract, policy = self._active_catalog(server_now)
        history = self._history(
            intent.scope,
            _AuthorizedPriceLimitHistoryReader(self._audit, principal),
            server_now,
        )
        if intent.action is PriceLimitPublicationAction.PUBLISH:
            if intent.snapshot_id is None:
                raise blocked("PRICE_LIMIT_SOURCE_MISSING", "Saved snapshot identity is required")
            seal = self._source_seal(intent.snapshot_id, intent.scope, contract, policy, server_now)
        else:
            target = next(
                (
                    record
                    for record in history.records
                    if record.publication_id == intent.target_publication_id
                ),
                None,
            )
            if target is None:
                raise blocked(
                    "PRICE_LIMIT_ROLLBACK_TARGET_MISSING",
                    "Rollback target is outside this verified scope",
                )
            if target.publication_id == history.pointer.publication_id:
                raise blocked("PRICE_LIMIT_ALREADY_CURRENT", "Rollback target is already current")
            seal = target.seal
            # A historical record can still be inspected, but a new pointer move
            # requires the exact policy to be currently enabled.
            if (
                seal.policy.identity != policy.to_domain().identity
                or seal.dataset_contract != contract.to_domain()
            ):
                raise blocked(
                    "PRICE_LIMIT_ROLLBACK_POLICY_INACTIVE",
                    "Rollback target is not eligible under the active catalog",
                )
        principal.assert_live()
        return PriceLimitPublicationPreparation(seal, history.pointer)

    @storage_errors
    def read(
        self,
        intent: ReadPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationReadResult | None:
        """Verify all original sources and Audit pairs before resolving the requested point."""
        intent.__post_init__()
        self._fence(intent.scope, principal, server_now)
        self._active_catalog(server_now)
        history = self._history(
            intent.scope,
            _AuthorizedPriceLimitHistoryReader(self._audit, principal),
            server_now,
        )
        cutoff = intent.as_of if intent.as_of is not None else server_now
        if cutoff > server_now:
            raise blocked("PRICE_LIMIT_FUTURE_CUTOFF", "Future history is unavailable")
        if intent.publication_id is not None:
            record = next(
                (item for item in history.records if item.publication_id == intent.publication_id),
                None,
            )
            if record is None or record.first_published_at > cutoff:
                return None
            return PriceLimitPublicationReadResult(record, cutoff, None, "exact_identity")
        record = resolve_price_limit_publication_at(
            records=history.records,
            events=history.events,
            current_pointer=history.pointer,
            as_of=cutoff,
            server_now=server_now,
        )
        if record is None:
            return None
        visible_event = next(
            event for event in reversed(history.events) if event.transitioned_at <= cutoff
        )
        return PriceLimitPublicationReadResult(
            record, cutoff, visible_event.transitioned_at, "visible_at_cutoff"
        )

    @storage_errors
    def confirm(
        self,
        preview: PriceLimitPublicationPreview,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationReceipt:
        """Join the authority-owned transaction for one exact publish or rollback."""
        preview.__post_init__()
        intent = preview.intent
        self._fence(intent.scope, principal, server_now)
        if (
            preview.actor_id != principal.actor_id
            or not preview.previewed_at <= server_now < preview.expires_at
        ):
            raise blocked(
                "PRICE_LIMIT_PREVIEW_INVALID", "Preview actor or confirmation window differs"
            )
        self._active_catalog(server_now)
        history = self._history(
            intent.scope,
            _AuthorizedPriceLimitHistoryReader(self._audit, principal),
            server_now,
        )
        existing = next(
            (event for event in history.events if event.event_id == preview.operation_id), None
        )
        if existing is not None:
            return self._replay(preview, history, existing, principal)
        if history.pointer != preview.expected_pointer:
            raise blocked(
                "PRICE_LIMIT_POINTER_CAS_MISMATCH",
                "Pointer changed after preview; reread before confirming",
            )
        if history.events and server_now <= history.events[-1].transitioned_at:
            raise blocked(
                "PRICE_LIMIT_TRANSITION_TIME_INVALID",
                "Pointer transitions require a strictly increasing real clock",
            )
        prepared = self.prepare(intent, principal=principal, server_now=server_now)
        if (
            prepared.seal.publication_hash != preview.publication_hash
            or prepared.current_pointer != history.pointer
        ):
            raise blocked("PRICE_LIMIT_PREVIEW_STALE", "Source or catalog differs from preview")
        if intent.action is PriceLimitPublicationAction.PUBLISH:
            record, event = self._publish(preview, prepared.seal, history, server_now)
        else:
            record, event = self._rollback(preview, history, server_now)
        principal.assert_live()
        pair = self._audit.record_transition(
            record, event, principal=principal, server_now=server_now
        )
        if (
            pair.database_alias != self._using
            or pair.timeline_event != event
            or pair.publication_id != record.publication_id
            or pair.publication_hash != record.publication_hash
            or pair.actor_user_id != principal.user_id
        ):
            raise blocked(
                "PRICE_LIMIT_AUDIT_RECEIPT_MISMATCH",
                "Audit receipt differs from the authorized transition",
            )
        pointer = self._move_pointer(intent.scope, record, event, history.pointer)
        records = (
            history.records
            if intent.action is PriceLimitPublicationAction.ROLLBACK
            else (*history.records, record)
        )
        validate_price_limit_publication_timeline(
            records=records, events=(*history.events, event), current_pointer=pointer
        )
        principal.assert_live()
        return PriceLimitPublicationReceipt(record, pointer, preview.operation_id, False)

    def _replay(
        self,
        preview: PriceLimitPublicationPreview,
        history: _History,
        event: PriceLimitPublicationTimelineEvent,
        principal: LockedPriceLimitPublisherPrincipal,
    ) -> PriceLimitPublicationReceipt:
        is_rollback = event.kind is PriceLimitPublicationEventKind.ROLLBACK
        if (
            event.target_publication_hash != preview.publication_hash
            or event.previous_publication_id != preview.expected_pointer.publication_id
            or event.previous_publication_hash != preview.expected_pointer.publication_hash
            or is_rollback != (preview.intent.action is PriceLimitPublicationAction.ROLLBACK)
            or history.pointer.activation_id != event.event_id
            or history.pointer.publication_id != event.target_publication_id
        ):
            raise blocked(
                "PRICE_LIMIT_REPLAY_CONFLICT",
                "Original operation no longer matches this current pointer",
            )
        record = next(
            item for item in history.records if item.publication_id == event.target_publication_id
        )
        if is_rollback:
            if (
                event.rollback is None
                or event.rollback.reason != preview.intent.reason
                or event.rollback.operator != principal.actor_id
            ):
                raise blocked("PRICE_LIMIT_REPLAY_CONFLICT", "Rollback reason or actor differs")
        elif record.seal.snapshot.snapshot_id != preview.intent.snapshot_id:
            raise blocked("PRICE_LIMIT_REPLAY_CONFLICT", "Original source differs")
        return PriceLimitPublicationReceipt(record, history.pointer, preview.operation_id, True)

    def _publish(
        self,
        preview: PriceLimitPublicationPreview,
        seal: PriceLimitFormalPublicationSeal,
        history: _History,
        server_now: datetime,
    ) -> tuple[PriceLimitFormalPublicationRecord, PriceLimitPublicationTimelineEvent]:
        if any(item.publication_hash == seal.publication_hash for item in history.records):
            raise blocked(
                "PRICE_LIMIT_EXISTING_PUBLICATION",
                "Existing content must be read or explicitly rolled back",
            )
        if history.pointer.publication_id is not None:
            old = next(
                item
                for item in history.records
                if item.publication_id == history.pointer.publication_id
            )
            if (
                seal.response_completed_at <= old.seal.response_completed_at
                or seal.recorded_at < old.seal.recorded_at
            ):
                raise blocked(
                    "PRICE_LIMIT_SOURCE_NOT_FORWARD",
                    "Forward publication requires a later exact response",
                )
        identity = str(uuid4())
        record = PriceLimitFormalPublicationRecord(seal, identity, server_now, preview.operation_id)
        event = PriceLimitPublicationTimelineEvent(
            (
                PriceLimitPublicationEventKind.FIRST_PUBLISH
                if history.pointer.is_absent
                else PriceLimitPublicationEventKind.FORWARD_PUBLISH
            ),
            preview.operation_id,
            DATASET,
            seal.publication_key,
            history.pointer.publication_id,
            history.pointer.publication_hash,
            identity,
            seal.publication_hash,
            server_now,
        )
        CanonicalPublicationModel.objects.using(self._using).create(
            publication_id=UUID(identity),
            dataset_key=DATASET,
            publication_key=seal.publication_key,
            policy_version=seal.policy_identity,
            state=REFERENCE_STATE,
            selected_source=seal.snapshot.candidate.provider_name,
            publication_hash=seal.publication_hash,
            member_manifest_hash=seal.member_manifest_hash,
            member_count=1,
            conflict_count=0,
            coverage_requested_count=1,
            coverage_eligible_count=1,
            coverage_selected_count=1,
            coverage_missing_count=0,
            coverage_conflict_count=0,
            as_of=server_now,
            published_at=server_now,
            members_sealed_at=server_now,
            must_not_use_for_decision=True,
            blocked_reason=REFERENCE_REASON,
            created_by=preview.actor_id,
            run_id=None,
            scope_blocks=[],
        )
        member = seal.member_evidence.to_publication_member(
            publication_id=identity, member_id=str(uuid4())
        )
        PublicationMemberModel.objects.using(self._using).create(
            member_id=UUID(member.member_id),
            publication_id=UUID(identity),
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
        CoverageSnapshotModel.objects.using(self._using).create(
            coverage_id=UUID(identity),
            publication_id=UUID(identity),
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=server_now,
        )
        return record, event

    def _rollback(
        self,
        preview: PriceLimitPublicationPreview,
        history: _History,
        server_now: datetime,
    ) -> tuple[PriceLimitFormalPublicationRecord, PriceLimitPublicationTimelineEvent]:
        target = next(
            (
                item
                for item in history.records
                if item.publication_id == preview.intent.target_publication_id
            ),
            None,
        )
        if target is None or history.pointer.publication_id is None:
            raise blocked(
                "PRICE_LIMIT_ROLLBACK_TARGET_MISSING",
                "Verified target/current publication required",
            )
        rollback = PublicationRollback(
            target_publication_id=target.publication_id,
            reason=preview.intent.reason,
            operator=preview.actor_id,
            observed_at=server_now,
            previous_publication_id=history.pointer.publication_id,
            rollback_id=preview.operation_id,
        )
        PublicationRollbackModel.objects.using(self._using).create(
            rollback_id=UUID(rollback.rollback_id),
            target_publication_id=UUID(rollback.target_publication_id),
            previous_publication_id=UUID(rollback.previous_publication_id),
            dataset_key=DATASET,
            publication_key=preview.intent.scope.publication_key,
            reason=rollback.reason,
            operator=rollback.operator,
            observed_at=rollback.observed_at,
        )
        event = PriceLimitPublicationTimelineEvent(
            PriceLimitPublicationEventKind.ROLLBACK,
            preview.operation_id,
            DATASET,
            preview.intent.scope.publication_key,
            history.pointer.publication_id,
            history.pointer.publication_hash,
            target.publication_id,
            target.publication_hash,
            server_now,
            rollback,
        )
        return target, event

    def _move_pointer(
        self,
        scope: PriceLimitPublicationScope,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        expected: PriceLimitPublicationPointerExpectation,
    ) -> PriceLimitPublicationPointerExpectation:
        manager = CanonicalPublicationModel.objects.using(self._using)
        if expected.publication_id is not None:
            updated = manager.filter(
                publication_id=UUID(expected.publication_id), state=REFERENCE_STATE
            ).update(state=SUPERSEDED_STATE, superseded_at=event.transitioned_at)
            if updated != 1:
                raise blocked(
                    "PRICE_LIMIT_POINTER_CAS_MISMATCH", "Previous reference state changed"
                )
        if event.kind is PriceLimitPublicationEventKind.ROLLBACK:
            updated = manager.filter(
                publication_id=UUID(record.publication_id), state=SUPERSEDED_STATE
            ).update(state=REFERENCE_STATE, reinstated_at=event.transitioned_at)
            if updated != 1:
                raise blocked("PRICE_LIMIT_POINTER_CAS_MISMATCH", "Rollback target state changed")
        pointers = CanonicalPublicationPointerModel.objects.using(self._using)
        if expected.is_absent:
            pointer = pointers.create(
                dataset_key=DATASET,
                publication_key=scope.publication_key,
                publication_id=UUID(record.publication_id),
                publication_hash=record.publication_hash,
                activation_id=event.event_id,
            )
            pointer_id = pointer.pointer_id
            # auto_now is a storage clock; the visible event clock is explicit.
            pointers.filter(pk=pointer_id).update(updated_at=event.transitioned_at)
        else:
            if (
                expected.pointer_id is None
                or expected.publication_id is None
                or expected.updated_at is None
            ):
                raise blocked(
                    "PRICE_LIMIT_POINTER_INVALID", "Complete pointer expectation required"
                )
            pointer_id = UUID(expected.pointer_id)
            updated = pointers.filter(
                pk=pointer_id,
                publication_id=UUID(expected.publication_id),
                publication_hash=expected.publication_hash,
                activation_id=expected.activation_id,
                updated_at=expected.updated_at,
            ).update(
                publication_id=UUID(record.publication_id),
                publication_hash=record.publication_hash,
                activation_id=event.event_id,
                updated_at=event.transitioned_at,
            )
            if updated != 1:
                raise blocked(
                    "PRICE_LIMIT_POINTER_CAS_MISMATCH", "Pointer changed during atomic publication"
                )
        return PriceLimitPublicationPointerExpectation(
            DATASET,
            scope.publication_key,
            str(pointer_id),
            record.publication_id,
            record.publication_hash,
            event.event_id,
            event.transitioned_at,
        )


class _AuthorizedPriceLimitHistoryReader:
    """Keep publisher authority bound to every manager history audit read."""

    def __init__(
        self,
        audit: PriceLimitFormalPublicationAuditPort,
        principal: LockedPriceLimitPublisherPrincipal,
    ) -> None:
        """Bind the existing management Audit port and live principal."""

        self._audit = audit
        self._principal = principal

    def get_first_transition(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        publication_key: str,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read the first event under the existing manager principal and exact key."""

        pair = self._audit.get_first_transition(
            publication_id=publication_id,
            publication_hash=publication_hash,
            principal=self._principal,
            server_now=server_now,
        )
        if pair.publication_key != publication_key:
            raise blocked(
                "PRICE_LIMIT_AUDIT_SCOPE_MISMATCH",
                "First Audit transition differs from the exact publication scope",
            )
        return pair

    def verify_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify the transition while preserving management authorization checks."""

        return self._audit.verify_transition(
            record,
            event,
            principal=self._principal,
            server_now=server_now,
        )


class DjangoPublishedPriceLimitReferenceRepository(_PriceLimitPublicationSupport):
    """Read the exact published market reference through the verified original chain."""

    _audit: PriceLimitFormalPublicationReferenceAuditPort

    def __init__(
        self,
        audit: PriceLimitFormalPublicationReferenceAuditPort,
        *,
        using: str = "default",
    ) -> None:
        """Bind the scoped, permissionless read-only Audit adapter on one alias."""

        self._audit = audit
        self._using = using

    @storage_errors
    def read_published_reference(
        self,
        scope: PriceLimitPublicationScope,
        *,
        as_of: datetime,
        server_now: datetime,
    ) -> PriceLimitPublicationReadResult | None:
        """Rebuild all source seals and event/outbox pairs before resolving the cutoff."""

        require_utc(as_of)
        require_utc(server_now)
        if as_of > server_now:
            raise blocked("PRICE_LIMIT_FUTURE_CUTOFF", "Future history is unavailable")
        connection = connections[self._using]
        transaction_context = (
            nullcontext() if connection.in_atomic_block else transaction.atomic(using=self._using)
        )
        with transaction_context:
            self._fence_reference(scope, server_now)
            self._active_catalog(server_now)
            history = self._history(
                scope,
                _ReferencePriceLimitHistoryReader(self._audit),
                server_now,
            )
            record = resolve_price_limit_publication_at(
                records=history.records,
                events=history.events,
                current_pointer=history.pointer,
                as_of=as_of,
                server_now=server_now,
            )
            if record is None:
                return None
            visible_event = next(
                event for event in reversed(history.events) if event.transitioned_at <= as_of
            )
            return PriceLimitPublicationReadResult(
                record, as_of, visible_event.transitioned_at, "visible_at_cutoff"
            )


class _ReferencePriceLimitHistoryReader:
    """Route history reads only through exact scope/cutoff Audit reference methods."""

    def __init__(self, audit: PriceLimitFormalPublicationReferenceAuditPort) -> None:
        """Bind the no-principal Audit reader used by the internal market query."""

        self._audit = audit

    def get_first_transition(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        publication_key: str,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read one first transition only for the supplied key and server cutoff."""

        return self._audit.get_first_transition_for_reference(
            publication_id=publication_id,
            publication_hash=publication_hash,
            publication_key=publication_key,
            server_now=server_now,
        )

    def verify_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify one exact event/outbox pair without appending or broad Audit access."""

        return self._audit.verify_transition_for_reference(
            record,
            event,
            server_now=server_now,
        )
