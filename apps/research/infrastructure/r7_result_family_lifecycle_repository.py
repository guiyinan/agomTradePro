"""Exact append-only persistence and PIT audit for R7 family lifecycles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Protocol, TypedDict, cast
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.research.application.r7_result_family_lifecycle import (
    R7FamilyAuthorizationRef,
    R7FamilyLifecycleConflict,
    R7FamilyLifecycleCorruption,
    R7FamilyLifecycleUnavailable,
    R7FamilyOwnerSourceGraph,
    R7ResultFamilyRef,
)
from apps.research.application.r7_result_family_lifecycle_persistence import (
    R7FamilyEventRef,
    R7FamilyLifecycleAuditEntry,
    R7FamilyLifecycleAuditPage,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResultLifecycleEvent,
    R7ResultPromotionAuthorization,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
    create_r7_family_lifecycle_event,
    derive_r7_family_lifecycle_state,
)
from apps.research.domain.scenario_research_hashing import hash_components
from apps.research.infrastructure.r7_research_result_lifecycle_codec import (
    decode_r7_result_lifecycle_authorization,
    decode_r7_result_lifecycle_event,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleAuthorizationModel,
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from apps.research.infrastructure.r7_research_result_repository import (
    DjangoR7ResearchResultRepository,
)
from apps.research.infrastructure.r7_result_family_lifecycle_codec import (
    decode_r7_family_lifecycle_authorization,
    decode_r7_family_lifecycle_event_source_graph,
    encode_r7_family_lifecycle_authorization,
)
from apps.research.infrastructure.r7_result_family_lifecycle_models import (
    R7FamilyLifecycleAuditSnapshotModel,
    R7FamilyLifecycleAuthorizationModel,
    R7FamilyLifecycleEventModel,
    R7FamilyLifecycleStreamCommitModel,
    _activate_r7_family_uow,
    _claim_r7_family_insert,
    _require_active_r7_family_uow,
)
from apps.research.infrastructure.r7_result_family_lifecycle_row_seal import (
    AUDIT_PAYLOAD_VERSION,
    AUDIT_SNAPSHOT_VERSION,
    R7FamilyAuditSnapshotValues,
    audit_snapshot_values,
    authorization_values,
    event_values,
    local_authorization_model_headers,
    local_event_model_headers,
    require_exact_values,
    stream_commit_values,
)


class R7FamilyLifecycleClock(Protocol):
    """Trusted clock boundary used only by persistence composition."""

    def now(self) -> datetime: ...


def _local_authorization_headers(
    authorization: R7ResultPromotionAuthorization,
) -> tuple[object, ...]:
    return (
        authorization.result_ref.result_id,
        authorization.result_ref.result_version,
        authorization.result_ref.content_hash,
        authorization.authorization_id,
        authorization.authorization_version,
        authorization.event_id,
        authorization.event_version,
        authorization.action.value,
        authorization.expected_sequence,
        authorization.owner,
        authorization.issued_at,
        authorization.recorded_at,
        authorization.valid_until,
        list(authorization.reason_codes),
        authorization.evidence_ref,
        authorization.research_only,
        authorization.promotes_internal_research_record_only,
        authorization.publishes_model_probability,
        authorization.produces_decision,
        authorization.executes_orders,
        authorization.must_not_use_for_decision,
        authorization.must_not_execute,
        authorization.content_hash,
    )


def _local_event_headers(event: R7ResultLifecycleEvent) -> tuple[object, ...]:
    return (
        event.result_ref.result_id,
        event.result_ref.result_version,
        event.result_ref.content_hash,
        event.event_id,
        event.event_version,
        event.authorization_id,
        event.authorization_version,
        event.authorization_hash,
        event.action.value,
        event.sequence,
        event.occurred_at,
        event.recorded_at,
        event.previous_event_hash,
        list(event.reason_codes),
        event.research_only,
        event.promotes_internal_research_record_only,
        event.publishes_model_probability,
        event.produces_decision,
        event.executes_orders,
        event.must_not_use_for_decision,
        event.must_not_execute,
        event.content_hash,
    )


class _AuditCursorPayload(TypedDict):
    v: int
    snapshot_id: str
    snapshot_hash: str
    family_id: str
    family_version: str
    as_of: str
    offset: int


class DjangoR7FamilyLifecycleClock:
    """Django timezone-backed authoritative server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


class _SealedOwnerCutoffClock:
    """Replay owner ledgers at a persisted cutoff without consulting wall time."""

    __slots__ = ("_cutoff",)

    def __init__(self, cutoff: datetime) -> None:
        self._cutoff = cutoff

    def now(self) -> datetime:
        return self._cutoff


def _aware_utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R7FamilyLifecycleCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class DjangoR7FamilyLifecycleRepository:
    """Public exact/PIT reads without any insert capability or token."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7FamilyLifecycleClock | None = None,
    ) -> None:
        if type(using) is not str or not using.strip():
            raise ValueError("R7 family database alias must be a non-blank string")
        self._using = using
        self._clock = clock or DjangoR7FamilyLifecycleClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Enter a read-only transaction without activating write capability."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            yield

    def server_now(self) -> datetime:
        """Return a normalized trusted server timestamp."""

        try:
            return _aware_utc(self._clock.now(), "R7 family server clock")
        except R7FamilyLifecycleCorruption:
            raise
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family server clock is unavailable") from error

    def load_complete(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
    ) -> tuple[R7FamilyLifecycleEvent, ...]:
        """Return the complete canonical family prefix known at the cutoff."""

        family_ref.__post_init__()
        cutoff = self._pit_cutoff(as_of)
        return self._restore_stream(family_ref=family_ref, as_of=cutoff, lock=False)

    def get_by_authorization(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
    ) -> R7FamilyLifecycleEvent | None:
        """Return the exact winner only after replaying its complete stream."""

        authorization_ref.__post_init__()
        rows = tuple(
            R7FamilyLifecycleAuthorizationModel._default_manager.using(self._using).filter(
                authorization_id=authorization_ref.authorization_id,
                authorization_version=authorization_ref.authorization_version,
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R7FamilyLifecycleCorruption("R7 family authorization identity is ambiguous")
        row = rows[0]
        stream = self._restore_stream(
            family_ref=R7ResultFamilyRef(row.family_id, row.family_version),
            as_of=row.ledger_recorded_at,
            lock=False,
        )
        matches = tuple(
            event
            for event in stream
            if (
                event.authorization.authorization_id,
                event.authorization.authorization_version,
            )
            == (
                authorization_ref.authorization_id,
                authorization_ref.authorization_version,
            )
        )
        if len(matches) != 1:
            raise R7FamilyLifecycleCorruption(
                "R7 family authorization does not have one committed event"
            )
        return matches[0]

    def get_exact_authorization(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
        as_of: datetime,
    ) -> R7FamilyLifecycleAuthorization | None:
        """Read one exact receipt only when its three-way commit existed at PIT."""

        authorization_ref.__post_init__()
        cutoff = self._pit_cutoff(as_of)
        rows = tuple(
            R7FamilyLifecycleAuthorizationModel._default_manager.using(self._using).filter(
                authorization_id=authorization_ref.authorization_id,
                authorization_version=authorization_ref.authorization_version,
                ledger_recorded_at__lte=cutoff,
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R7FamilyLifecycleCorruption("R7 family authorization identity is ambiguous")
        row = rows[0]
        stream = self._restore_stream(
            family_ref=R7ResultFamilyRef(row.family_id, row.family_version),
            as_of=cutoff,
            lock=False,
        )
        matches = tuple(
            event.authorization
            for event in stream
            if (
                event.authorization.authorization_id,
                event.authorization.authorization_version,
            )
            == (
                authorization_ref.authorization_id,
                authorization_ref.authorization_version,
            )
        )
        if len(matches) != 1:
            raise R7FamilyLifecycleCorruption("R7 family authorization commit is incomplete")
        return matches[0]

    def get_exact_event(
        self,
        *,
        event_ref: R7FamilyEventRef,
        as_of: datetime,
    ) -> R7FamilyLifecycleEvent | None:
        """Read one event only after exact PIT prefix replay."""

        event_ref.__post_init__()
        cutoff = self._pit_cutoff(as_of)
        rows = tuple(
            R7FamilyLifecycleEventModel._default_manager.using(self._using).filter(
                event_id=event_ref.event_id,
                event_version=event_ref.event_version,
                ledger_recorded_at__lte=cutoff,
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R7FamilyLifecycleCorruption("R7 family event identity is ambiguous")
        row = rows[0]
        stream = self._restore_stream(
            family_ref=R7ResultFamilyRef(row.family_id, row.family_version),
            as_of=cutoff,
            lock=False,
        )
        matches = tuple(
            event
            for event in stream
            if (event.event_id, event.event_version)
            == (event_ref.event_id, event_ref.event_version)
        )
        if len(matches) != 1:
            raise R7FamilyLifecycleCorruption("R7 family event commit is incomplete")
        return matches[0]

    def audit_events(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
        page_size: int,
        cursor: str | None,
    ) -> R7FamilyLifecycleAuditPage:
        """Public runtime cannot materialize signed audit snapshots."""

        del family_ref, as_of, page_size, cursor
        raise R7FamilyLifecycleUnavailable(
            "R7 family audit snapshot writer is unavailable in the public repository"
        )

    def _pit_cutoff(self, as_of: datetime) -> datetime:
        cutoff = _aware_utc(as_of, "R7 family PIT cutoff")
        if cutoff > self.server_now():
            raise R7FamilyLifecycleUnavailable("future R7 family PIT cutoff is unavailable")
        return cutoff

    def _restore_stream(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
        lock: bool,
    ) -> tuple[R7FamilyLifecycleEvent, ...]:
        auth_query: QuerySet[
            R7FamilyLifecycleAuthorizationModel
        ] = R7FamilyLifecycleAuthorizationModel._default_manager.using(self._using).filter(
            family_id=family_ref.family_id,
            family_version=family_ref.family_version,
            ledger_recorded_at__lte=as_of,
        )
        event_query: QuerySet[
            R7FamilyLifecycleEventModel
        ] = R7FamilyLifecycleEventModel._default_manager.using(self._using).filter(
            family_id=family_ref.family_id,
            family_version=family_ref.family_version,
            ledger_recorded_at__lte=as_of,
        )
        commit_query: QuerySet[
            R7FamilyLifecycleStreamCommitModel
        ] = R7FamilyLifecycleStreamCommitModel._default_manager.using(self._using).filter(
            family_id=family_ref.family_id,
            family_version=family_ref.family_version,
            ledger_recorded_at__lte=as_of,
        )
        if lock:
            auth_query = auth_query.select_for_update()
            event_query = event_query.select_for_update()
            commit_query = commit_query.select_for_update()
        authorization_rows = tuple(auth_query.order_by("expected_sequence", "pk"))
        event_rows = tuple(event_query.order_by("sequence", "pk"))
        commit_rows = tuple(commit_query.order_by("sequence", "pk"))
        if not authorization_rows and not event_rows and not commit_rows:
            return ()
        if not (
            len(authorization_rows) == len(event_rows) == len(commit_rows)
            and tuple(row.expected_sequence for row in authorization_rows)
            == tuple(range(1, len(authorization_rows) + 1))
            and tuple(row.sequence for row in event_rows) == tuple(range(1, len(event_rows) + 1))
            and tuple(row.sequence for row in commit_rows) == tuple(range(1, len(commit_rows) + 1))
        ):
            raise R7FamilyLifecycleCorruption("R7 family stream sets are incomplete")
        if (
            {row.pk for row in authorization_rows}
            != {row.authorization_row_id for row in event_rows}
            or {row.pk for row in authorization_rows}
            != {row.authorization_row_id for row in commit_rows}
            or {row.pk for row in event_rows} != {row.event_row_id for row in commit_rows}
        ):
            raise R7FamilyLifecycleCorruption("R7 family stream commit sets differ")
        family_hashes = {
            *(row.family_hash for row in authorization_rows),
            *(row.family_hash for row in event_rows),
            *(row.family_hash for row in commit_rows),
        }
        if len(family_hashes) != 1:
            raise R7FamilyLifecycleCorruption("R7 family identity/hash aliases diverge")
        family_hash = next(iter(family_hashes))
        if self._has_family_alias(
            family_ref=family_ref,
            family_hash=family_hash,
            as_of=as_of,
        ):
            raise R7FamilyLifecycleCorruption("R7 family hash is aliased to another selector")
        restored: list[R7FamilyLifecycleEvent] = []
        for authorization_row, event_row, commit_row in zip(
            authorization_rows,
            event_rows,
            commit_rows,
            strict=True,
        ):
            restored.append(
                self._restore_committed_event(
                    authorization_row=authorization_row,
                    event_row=event_row,
                    commit_row=commit_row,
                    previous_events=tuple(restored),
                )
            )
        stream = tuple(restored)
        try:
            state = derive_r7_family_lifecycle_state(stream, evaluated_at=as_of)
        except Exception as error:
            raise R7FamilyLifecycleCorruption("R7 family stream replay failed") from error
        if (state.family.family_id, state.family.family_version) != (
            family_ref.family_id,
            family_ref.family_version,
        ):
            raise R7FamilyLifecycleCorruption("R7 family stream selector differs")
        return stream

    def _has_family_alias(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        family_hash: str,
        as_of: datetime,
    ) -> bool:
        selector = Q(family_hash=family_hash) & ~Q(
            family_id=family_ref.family_id,
            family_version=family_ref.family_version,
        )
        return any(
            model._default_manager.using(self._using)
            .filter(selector, ledger_recorded_at__lte=as_of)
            .exists()
            for model in (
                R7FamilyLifecycleAuthorizationModel,
                R7FamilyLifecycleEventModel,
                R7FamilyLifecycleStreamCommitModel,
            )
        )

    def _restore_committed_event(
        self,
        *,
        authorization_row: R7FamilyLifecycleAuthorizationModel,
        event_row: R7FamilyLifecycleEventModel,
        commit_row: R7FamilyLifecycleStreamCommitModel,
        previous_events: tuple[R7FamilyLifecycleEvent, ...],
    ) -> R7FamilyLifecycleEvent:
        try:
            authorization = decode_r7_family_lifecycle_authorization(authorization_row.payload)
            event, subject_source, target_source = decode_r7_family_lifecycle_event_source_graph(
                event_row.payload,
                previous_events=previous_events,
            )
            self._require_source_rows(
                source=subject_source,
                result_row_id=event_row.subject_result_id,
                local_head_row_id=event_row.subject_local_lifecycle_head_id,
            )
            target_result_row_id = event_row.rollback_target_result_id
            target_local_head_row_id = event_row.rollback_target_local_lifecycle_head_id
            if target_source is None:
                if target_result_row_id is not None or target_local_head_row_id is not None:
                    raise ValueError("unexpected rollback target FK")
            else:
                if target_result_row_id is None or target_local_head_row_id is None:
                    raise ValueError("rollback target FK is incomplete")
                self._require_source_rows(
                    source=target_source,
                    result_row_id=target_result_row_id,
                    local_head_row_id=target_local_head_row_id,
                )
            ledger_time = _aware_utc(
                commit_row.ledger_recorded_at,
                "R7 family commit ledger clock",
            )
            if (
                authorization_row.ledger_recorded_at != ledger_time
                or event_row.ledger_recorded_at != ledger_time
            ):
                raise ValueError("three-way ledger clocks differ")
            authorization_expected = authorization_values(
                authorization,
                subject_source=subject_source,
                subject_result_row_id=event_row.subject_result_id,
                subject_local_head_row_id=event_row.subject_local_lifecycle_head_id,
                rollback_target_source=target_source,
                rollback_target_result_row_id=event_row.rollback_target_result_id,
                rollback_target_local_head_row_id=(
                    event_row.rollback_target_local_lifecycle_head_id
                ),
                ledger_recorded_at=ledger_time,
            )
            event_expected = event_values(
                event,
                authorization_row_id=authorization_row.pk,
                subject_source=subject_source,
                subject_result_row_id=event_row.subject_result_id,
                subject_local_head_row_id=event_row.subject_local_lifecycle_head_id,
                rollback_target_source=target_source,
                rollback_target_result_row_id=event_row.rollback_target_result_id,
                rollback_target_local_head_row_id=(
                    event_row.rollback_target_local_lifecycle_head_id
                ),
                ledger_recorded_at=ledger_time,
            )
            commit_expected = stream_commit_values(
                authorization=authorization,
                event=event,
                authorization_row_id=authorization_row.pk,
                event_row_id=event_row.pk,
                ledger_recorded_at=ledger_time,
            )
            require_exact_values(authorization_row, authorization_expected, "authorization")
            require_exact_values(event_row, event_expected, "event")
            require_exact_values(commit_row, commit_expected, "stream commit")
            if event.authorization != authorization:
                raise ValueError("event authorization differs from receipt")
            return event
        except R7FamilyLifecycleCorruption:
            raise
        except Exception as error:
            raise R7FamilyLifecycleCorruption(
                "R7 family committed event is malformed or tampered"
            ) from error

    def _require_source_rows(
        self,
        *,
        source: R7FamilyOwnerSourceGraph,
        result_row_id: int,
        local_head_row_id: int,
    ) -> None:
        source.__post_init__()
        result_rows = tuple(
            R7ResearchResultModel._default_manager.using(self._using).filter(pk=result_row_id)
        )
        if len(result_rows) != 1:
            raise R7FamilyLifecycleCorruption("R7 family result FK is unavailable")
        result_row = result_rows[0]
        try:
            restored_result = DjangoR7ResearchResultRepository(
                using=self._using,
                clock=_SealedOwnerCutoffClock(source.evaluated_at),
            ).get_exact(
                result_id=result_row.result_id,
                result_version=result_row.result_version,
                expected_content_hash=result_row.content_hash,
                as_of=source.evaluated_at,
            )
        except Exception as error:
            raise R7FamilyLifecycleCorruption(
                "R7 family canonical result graph is unavailable"
            ) from error
        if restored_result != source.result or (
            result_row.result_id,
            result_row.result_version,
            result_row.content_hash,
        ) != (
            source.result.result_id,
            source.result.result_version,
            source.result.content_hash,
        ):
            raise R7FamilyLifecycleCorruption("R7 family result FK was substituted")
        local_rows = tuple(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_related("result", "authorization_record", "authorization_record__result")
            .filter(
                result_id=result_row.pk,
                recorded_at__lte=source.evaluated_at,
            )
            .order_by("sequence", "pk")
        )
        authorization_rows = tuple(
            R7ResultLifecycleAuthorizationModel._default_manager.using(self._using)
            .select_related("result")
            .filter(
                result_id=result_row.pk,
                recorded_at__lte=source.evaluated_at,
            )
            .order_by("expected_sequence", "pk")
        )
        for authorization_row in authorization_rows:
            self._restore_local_authorization(authorization_row)
        if {row.pk for row in authorization_rows} != {
            row.authorization_record_id for row in local_rows
        }:
            raise R7FamilyLifecycleCorruption(
                "R7 family canonical local authorization/event set is incomplete"
            )
        restored_local = tuple(self._restore_local_event(row) for row in local_rows)
        if (
            restored_local != source.local_lifecycle_stream
            or not local_rows
            or local_rows[-1].pk != local_head_row_id
        ):
            raise R7FamilyLifecycleCorruption("R7 family local lifecycle FK/prefix was substituted")

    @staticmethod
    def _restore_local_authorization(
        model: R7ResultLifecycleAuthorizationModel,
    ) -> R7ResultPromotionAuthorization:
        authorization = decode_r7_result_lifecycle_authorization(model.canonical_payload)
        if (
            local_authorization_model_headers(model) != _local_authorization_headers(authorization)
            or model.result_id != model.result.pk
            or (
                model.result.result_id,
                model.result.result_version,
                model.result.content_hash,
            )
            != (
                authorization.result_ref.result_id,
                authorization.result_ref.result_version,
                authorization.result_ref.content_hash,
            )
        ):
            raise R7FamilyLifecycleCorruption("R7 canonical local authorization row differs")
        return authorization

    def _restore_local_event(self, model: R7ResultLifecycleEventModel) -> R7ResultLifecycleEvent:
        event = decode_r7_result_lifecycle_event(model.canonical_payload)
        authorization = self._restore_local_authorization(model.authorization_record)
        if (
            local_event_model_headers(model) != _local_event_headers(event)
            or model.result_id != model.result.pk
            or model.result_id != model.authorization_record.result_id
            or event.result_ref != authorization.result_ref
            or event.authorization_id != authorization.authorization_id
            or event.authorization_version != authorization.authorization_version
            or event.authorization_hash != authorization.content_hash
        ):
            raise R7FamilyLifecycleCorruption("R7 local lifecycle row header differs")
        return event


class _DjangoR7FamilyLifecycleStore(DjangoR7FamilyLifecycleRepository):
    """Private append and snapshot capability retained outside public runtimes."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7FamilyLifecycleClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the private write capability and shared DB transaction."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r7_family_uow(self._token):
            yield

    def append(
        self,
        *,
        authorization: R7FamilyLifecycleAuthorization,
        event: R7FamilyLifecycleEvent,
        subject_source: R7FamilyOwnerSourceGraph,
        rollback_target_source: R7FamilyOwnerSourceGraph | None,
    ) -> R7FamilyLifecycleEvent:
        """Append one exact auth/event/commit set or replay its first winner."""

        _require_active_r7_family_uow()
        authorization.__post_init__()
        event.validate_live()
        subject_source.__post_init__()
        if rollback_target_source is not None:
            rollback_target_source.__post_init__()
        winner = self._winner(authorization)
        if winner is not None:
            if winner == event:
                return winner
            raise R7FamilyLifecycleConflict(
                "R7 family authorization already has a different winner"
            )
        ledger_recorded_at = self.server_now()
        if ledger_recorded_at < event.recorded_at:
            raise R7FamilyLifecycleUnavailable("R7 family ledger clock moved backwards")
        family_ref = R7ResultFamilyRef(event.family.family_id, event.family.family_version)
        history = self._restore_stream(
            family_ref=family_ref,
            as_of=ledger_recorded_at,
            lock=True,
        )
        try:
            canonical_authorization = decode_r7_family_lifecycle_authorization(
                encode_r7_family_lifecycle_authorization(authorization)
            )
            replayed = create_r7_family_lifecycle_event(
                previous_events=history,
                authorization=canonical_authorization,
                subject_evidence=subject_source.evidence,
                rollback_target_evidence=(
                    None if rollback_target_source is None else rollback_target_source.evidence
                ),
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
            )
        except Exception as error:
            raise R7FamilyLifecycleConflict(
                "R7 family append does not extend the exact head"
            ) from error
        if replayed != event:
            raise R7FamilyLifecycleCorruption("R7 family append differs from Domain replay")
        subject_result_row, subject_head_row = self._lock_source_graph(subject_source)
        target_result_row: R7ResearchResultModel | None = None
        target_head_row: R7ResultLifecycleEventModel | None = None
        if rollback_target_source is not None:
            target_result_row, target_head_row = self._lock_source_graph(rollback_target_source)
        try:
            with transaction.atomic(using=self._using):
                authorization_row = self._append_authorization(
                    authorization=canonical_authorization,
                    subject_source=subject_source,
                    subject_result_row=subject_result_row,
                    subject_head_row=subject_head_row,
                    rollback_target_source=rollback_target_source,
                    target_result_row=target_result_row,
                    target_head_row=target_head_row,
                    ledger_recorded_at=ledger_recorded_at,
                )
                event_row = self._append_event(
                    event=event,
                    authorization_row=authorization_row,
                    subject_source=subject_source,
                    subject_result_row=subject_result_row,
                    subject_head_row=subject_head_row,
                    rollback_target_source=rollback_target_source,
                    target_result_row=target_result_row,
                    target_head_row=target_head_row,
                    ledger_recorded_at=ledger_recorded_at,
                )
                self._append_commit(
                    authorization=canonical_authorization,
                    event=event,
                    authorization_row=authorization_row,
                    event_row=event_row,
                    ledger_recorded_at=ledger_recorded_at,
                )
        except IntegrityError as error:
            winner = self._winner(canonical_authorization)
            if winner == event:
                return winner
            raise R7FamilyLifecycleConflict(
                "R7 family append lost an identity/head race"
            ) from error
        winner = self._winner(canonical_authorization)
        if winner != event:
            raise R7FamilyLifecycleCorruption("R7 family append winner failed replay")
        return winner

    def _lock_source_graph(
        self,
        source: R7FamilyOwnerSourceGraph,
    ) -> tuple[R7ResearchResultModel, R7ResultLifecycleEventModel]:
        source.__post_init__()
        result_rows = tuple(
            R7ResearchResultModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                result_id=source.result.result_id,
                result_version=source.result.result_version,
                content_hash=source.result.content_hash,
            )
        )
        if len(result_rows) != 1:
            raise R7FamilyLifecycleUnavailable("R7 family source result is unavailable")
        head = source.local_lifecycle_stream[-1]
        head_rows = tuple(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                result_id=result_rows[0].pk,
                event_id=head.event_id,
                event_version=head.event_version,
                content_hash=head.content_hash,
            )
        )
        if len(head_rows) != 1:
            raise R7FamilyLifecycleUnavailable("R7 family source lifecycle head is unavailable")
        self._require_source_rows(
            source=source,
            result_row_id=result_rows[0].pk,
            local_head_row_id=head_rows[0].pk,
        )
        return result_rows[0], head_rows[0]

    def _append_authorization(
        self,
        *,
        authorization: R7FamilyLifecycleAuthorization,
        subject_source: R7FamilyOwnerSourceGraph,
        subject_result_row: R7ResearchResultModel,
        subject_head_row: R7ResultLifecycleEventModel,
        rollback_target_source: R7FamilyOwnerSourceGraph | None,
        target_result_row: R7ResearchResultModel | None,
        target_head_row: R7ResultLifecycleEventModel | None,
        ledger_recorded_at: datetime,
    ) -> R7FamilyLifecycleAuthorizationModel:
        values = authorization_values(
            authorization,
            subject_source=subject_source,
            subject_result_row_id=subject_result_row.pk,
            subject_local_head_row_id=subject_head_row.pk,
            rollback_target_source=rollback_target_source,
            rollback_target_result_row_id=(
                None if target_result_row is None else target_result_row.pk
            ),
            rollback_target_local_head_row_id=(
                None if target_head_row is None else target_head_row.pk
            ),
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r7_family_insert(
            token=self._token,
            model_type=R7FamilyLifecycleAuthorizationModel,
            expected_values=values,
        ):
            return R7FamilyLifecycleAuthorizationModel._default_manager.using(self._using).create(
                **values
            )

    def _append_event(
        self,
        *,
        event: R7FamilyLifecycleEvent,
        authorization_row: R7FamilyLifecycleAuthorizationModel,
        subject_source: R7FamilyOwnerSourceGraph,
        subject_result_row: R7ResearchResultModel,
        subject_head_row: R7ResultLifecycleEventModel,
        rollback_target_source: R7FamilyOwnerSourceGraph | None,
        target_result_row: R7ResearchResultModel | None,
        target_head_row: R7ResultLifecycleEventModel | None,
        ledger_recorded_at: datetime,
    ) -> R7FamilyLifecycleEventModel:
        values = event_values(
            event,
            authorization_row_id=authorization_row.pk,
            subject_source=subject_source,
            subject_result_row_id=subject_result_row.pk,
            subject_local_head_row_id=subject_head_row.pk,
            rollback_target_source=rollback_target_source,
            rollback_target_result_row_id=(
                None if target_result_row is None else target_result_row.pk
            ),
            rollback_target_local_head_row_id=(
                None if target_head_row is None else target_head_row.pk
            ),
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r7_family_insert(
            token=self._token,
            model_type=R7FamilyLifecycleEventModel,
            expected_values=values,
        ):
            return R7FamilyLifecycleEventModel._default_manager.using(self._using).create(**values)

    def _append_commit(
        self,
        *,
        authorization: R7FamilyLifecycleAuthorization,
        event: R7FamilyLifecycleEvent,
        authorization_row: R7FamilyLifecycleAuthorizationModel,
        event_row: R7FamilyLifecycleEventModel,
        ledger_recorded_at: datetime,
    ) -> R7FamilyLifecycleStreamCommitModel:
        values = stream_commit_values(
            authorization=authorization,
            event=event,
            authorization_row_id=authorization_row.pk,
            event_row_id=event_row.pk,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r7_family_insert(
            token=self._token,
            model_type=R7FamilyLifecycleStreamCommitModel,
            expected_values=values,
        ):
            return R7FamilyLifecycleStreamCommitModel._default_manager.using(self._using).create(
                **values
            )

    def _winner(
        self,
        authorization: R7FamilyLifecycleAuthorization,
    ) -> R7FamilyLifecycleEvent | None:
        return self.get_by_authorization(
            authorization_ref=R7FamilyAuthorizationRef(
                authorization.authorization_id,
                authorization.authorization_version,
            )
        )

    def audit_events(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
        page_size: int,
        cursor: str | None,
    ) -> R7FamilyLifecycleAuditPage:
        """Materialize or replay one signed immutable PIT audit snapshot."""

        _require_active_r7_family_uow()
        family_ref.__post_init__()
        cutoff = self._pit_cutoff(as_of)
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise R7FamilyLifecycleUnavailable("R7 family audit page size is invalid")
        if cursor is None:
            snapshot, offset = self._create_snapshot(family_ref=family_ref, as_of=cutoff), 0
        else:
            cursor_value = self._decode_cursor(cursor)
            if (
                cursor_value["family_id"] != family_ref.family_id
                or cursor_value["family_version"] != family_ref.family_version
                or cursor_value["as_of"] != cutoff.isoformat()
            ):
                raise R7FamilyLifecycleUnavailable("R7 family audit cursor context differs")
            snapshot = self._restore_snapshot(
                snapshot_id=cursor_value["snapshot_id"],
                snapshot_hash=cursor_value["snapshot_hash"],
            )
            offset = int(cursor_value["offset"])
        payload_entries = snapshot["payload"].get("entries")
        if type(payload_entries) is not list:
            raise R7FamilyLifecycleCorruption("R7 family audit entries are malformed")
        canonical_entries = cast(list[object], payload_entries)
        entries = tuple(
            self._audit_entry(item) for item in canonical_entries[offset : offset + page_size]
        )
        next_offset = offset + len(entries)
        next_cursor = (
            None
            if next_offset >= snapshot["total_count"]
            else self._encode_cursor(
                snapshot_id=str(snapshot["snapshot_id"]),
                snapshot_hash=str(snapshot["content_hash"]),
                family_ref=family_ref,
                as_of=cutoff,
                offset=next_offset,
            )
        )
        return R7FamilyLifecycleAuditPage(
            snapshot_id=str(snapshot["snapshot_id"]),
            snapshot_version=AUDIT_SNAPSHOT_VERSION,
            snapshot_hash=str(snapshot["content_hash"]),
            total_count=int(snapshot["total_count"]),
            entries=entries,
            next_cursor=next_cursor,
        )

    def _create_snapshot(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
    ) -> R7FamilyAuditSnapshotValues:
        stream = self._restore_stream(family_ref=family_ref, as_of=as_of, lock=True)
        if not stream:
            raise R7FamilyLifecycleUnavailable("R7 family audit stream is empty")
        commits = tuple(
            R7FamilyLifecycleStreamCommitModel._default_manager.using(self._using)
            .filter(
                family_id=family_ref.family_id,
                family_version=family_ref.family_version,
                ledger_recorded_at__lte=as_of,
            )
            .order_by("sequence", "pk")
        )
        entries = [
            {
                "sequence": event.sequence,
                "event_id": event.event_id,
                "event_version": event.event_version,
                "action": event.action.value,
                "event_hash": event.content_hash,
                "authorization_hash": event.authorization.content_hash,
                "owner_recorded_at": event.recorded_at.isoformat(),
                "ledger_recorded_at": commit.ledger_recorded_at.isoformat(),
            }
            for event, commit in zip(stream, commits, strict=True)
        ]
        family_hash = stream[0].family.content_hash
        manifest_hash = hash_components(
            "r7-family-audit-manifest.v1",
            family_hash,
            as_of.isoformat(),
            str(len(entries)),
            *(f"{entry['event_hash']}:{entry['ledger_recorded_at']}" for entry in entries),
        )
        payload: dict[str, object] = {
            "schema": AUDIT_PAYLOAD_VERSION,
            "entries": entries,
        }
        ledger_recorded_at = self.server_now()
        if ledger_recorded_at < as_of:
            raise R7FamilyLifecycleUnavailable("R7 family audit ledger clock moved backwards")
        values = audit_snapshot_values(
            snapshot_id=f"r7-family-audit:{uuid4()}",
            family_id=family_ref.family_id,
            family_version=family_ref.family_version,
            family_hash=family_hash,
            as_of=as_of,
            total_count=len(entries),
            manifest_hash=manifest_hash,
            payload=payload,
            created_at=ledger_recorded_at,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r7_family_insert(
            token=self._token,
            model_type=R7FamilyLifecycleAuditSnapshotModel,
            expected_values=values,
        ):
            R7FamilyLifecycleAuditSnapshotModel._default_manager.using(self._using).create(**values)
        return values

    def _restore_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_hash: str,
    ) -> R7FamilyAuditSnapshotValues:
        rows = tuple(
            R7FamilyLifecycleAuditSnapshotModel._default_manager.using(self._using).filter(
                snapshot_id=snapshot_id,
                snapshot_version=AUDIT_SNAPSHOT_VERSION,
            )
        )
        if len(rows) != 1:
            raise R7FamilyLifecycleUnavailable("R7 family audit snapshot is unavailable")
        row = rows[0]
        raw_payload = row.payload
        if not isinstance(raw_payload, dict) or any(type(key) is not str for key in raw_payload):
            raise R7FamilyLifecycleCorruption("R7 family audit payload is malformed")
        canonical_payload = cast(dict[str, object], raw_payload)
        values = audit_snapshot_values(
            snapshot_id=row.snapshot_id,
            family_id=row.family_id,
            family_version=row.family_version,
            family_hash=row.family_hash,
            as_of=row.as_of,
            total_count=row.total_count,
            manifest_hash=row.manifest_hash,
            payload=canonical_payload,
            created_at=row.created_at,
            ledger_recorded_at=row.ledger_recorded_at,
        )
        try:
            require_exact_values(row, values, "audit snapshot")
        except ValueError as error:
            raise R7FamilyLifecycleCorruption("R7 family audit snapshot was tampered") from error
        if values["content_hash"] != snapshot_hash:
            raise R7FamilyLifecycleUnavailable("R7 family audit cursor snapshot differs")
        stream = self._restore_stream(
            family_ref=R7ResultFamilyRef(row.family_id, row.family_version),
            as_of=row.as_of,
            lock=False,
        )
        entries = canonical_payload.get("entries")
        if (
            type(entries) is not list
            or len(entries) != len(stream)
            or tuple(item.get("event_hash") for item in entries if isinstance(item, dict))
            != tuple(event.content_hash for event in stream)
        ):
            raise R7FamilyLifecycleCorruption("R7 family audit manifest no longer seals stream")
        return values

    @staticmethod
    def _audit_entry(payload: object) -> R7FamilyLifecycleAuditEntry:
        if type(payload) is not dict or set(payload) != {
            "sequence",
            "event_id",
            "event_version",
            "action",
            "event_hash",
            "authorization_hash",
            "owner_recorded_at",
            "ledger_recorded_at",
        }:
            raise R7FamilyLifecycleCorruption("R7 family audit entry is malformed")
        try:
            from apps.research.domain.r7_result_family_lifecycle import (
                R7FamilyLifecycleAction,
            )

            return R7FamilyLifecycleAuditEntry(
                sequence=int(payload["sequence"]),
                event_ref=R7FamilyEventRef(
                    str(payload["event_id"]),
                    str(payload["event_version"]),
                ),
                action=R7FamilyLifecycleAction(str(payload["action"])),
                event_hash=str(payload["event_hash"]),
                authorization_hash=str(payload["authorization_hash"]),
                owner_recorded_at=datetime.fromisoformat(str(payload["owner_recorded_at"])),
                ledger_recorded_at=datetime.fromisoformat(str(payload["ledger_recorded_at"])),
            )
        except (TypeError, ValueError) as error:
            raise R7FamilyLifecycleCorruption("R7 family audit entry is invalid") from error

    def _encode_cursor(
        self,
        *,
        snapshot_id: str,
        snapshot_hash: str,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
        offset: int,
    ) -> str:
        payload = {
            "v": 1,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "family_id": family_ref.family_id,
            "family_version": family_ref.family_version,
            "as_of": as_of.isoformat(),
            "offset": offset,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key(), raw, hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + signature

    def _decode_cursor(self, cursor: str) -> _AuditCursorPayload:
        try:
            encoded, signature = cursor.split(".", 1)
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(self._cursor_key(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature differs")
            payload = json.loads(raw)
            if type(payload) is not dict or set(payload) != {
                "v",
                "snapshot_id",
                "snapshot_hash",
                "family_id",
                "family_version",
                "as_of",
                "offset",
            }:
                raise ValueError("cursor shape differs")
            if payload["v"] != 1 or type(payload["offset"]) is not int:
                raise ValueError("cursor version/offset differs")
            for key in (
                "snapshot_id",
                "snapshot_hash",
                "family_id",
                "family_version",
                "as_of",
            ):
                if type(payload[key]) is not str:
                    raise TypeError("cursor token differs")
            return _AuditCursorPayload(
                v=1,
                snapshot_id=cast(str, payload["snapshot_id"]),
                snapshot_hash=cast(str, payload["snapshot_hash"]),
                family_id=cast(str, payload["family_id"]),
                family_version=cast(str, payload["family_version"]),
                as_of=cast(str, payload["as_of"]),
                offset=payload["offset"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise R7FamilyLifecycleUnavailable("R7 family audit cursor is invalid") from error

    @staticmethod
    def _cursor_key() -> bytes:
        secret = settings.SECRET_KEY
        if type(secret) is not str or not secret:
            raise R7FamilyLifecycleUnavailable("R7 family audit cursor secret is unavailable")
        return hashlib.sha256(f"r7-family-audit:{secret}".encode()).digest()


__all__ = [
    "DjangoR7FamilyLifecycleClock",
    "DjangoR7FamilyLifecycleRepository",
    "R7FamilyLifecycleClock",
]
