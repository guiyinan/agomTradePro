"""Strict repository and stable audit pagination for R7 result lifecycle ledgers."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from apps.research.application.r7_research_result_lifecycle import (
    ExactR7ResultLifecycleAuthorizationProvider,
    R7ResearchResultAuditEntry,
    R7ResearchResultAuditPage,
    R7ResultLifecycleAuthorizationRef,
    R7ResultLifecycleConflict,
    R7ResultLifecycleCorruption,
    R7ResultLifecycleUnavailable,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultLifecycleStatus,
    R7ResultPromotionAuthorization,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.scenario_probability_contracts import ResearchEvidenceStatus
from apps.research.domain.scenario_research_hashing import require_sha256, require_token
from apps.research.infrastructure.r7_research_result_lifecycle_codec import (
    R7ResultLifecycleCodecError,
    decode_r7_result_lifecycle_authorization,
    decode_r7_result_lifecycle_event,
    encode_r7_result_lifecycle_authorization,
    encode_r7_result_lifecycle_event,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResearchResultAuditSnapshotModel,
    R7ResultLifecycleAuthorizationModel,
    R7ResultLifecycleEventModel,
    _activate_r7_result_lifecycle_uow,
    _claim_r7_result_lifecycle_insert,
    _require_active_r7_result_lifecycle_uow,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from apps.research.infrastructure.r7_research_result_repository import (
    DjangoR7ResearchResultClock,
    DjangoR7ResearchResultRepository,
    R7ResearchResultClock,
)

_CURSOR_SCHEMA = "r7-result-audit-cursor.v1"
_CURSOR_SALT = "research.r7-result-audit-cursor.v1"
_SNAPSHOT_SCHEMA = "r7-result-audit-snapshot-payload.v1"
_SNAPSHOT_VERSION = "r7-result-audit-snapshot.v1"


@dataclass(frozen=True)
class _AuditCursor:
    snapshot_as_of: datetime
    snapshot_id: str
    snapshot_version: str
    snapshot_hash: str
    next_offset: int


@dataclass(frozen=True)
class _AuditSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of: datetime
    created_at: datetime
    entries: tuple[R7ResearchResultAuditEntry, ...]
    internal_audit_only: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str


class DjangoR7ResultLifecycleAuthorizationProvider:
    """Require a composition-owned UoW around the exact Research owner port."""

    def __init__(self, source: ExactR7ResultLifecycleAuthorizationProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Return the wrapped owner transaction boundary key."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
        result_ref: R7ResearchResultRef,
        action: R7ResultLifecycleAction,
        as_of: datetime,
    ) -> R7ResultPromotionAuthorization | None:
        """Reread one exact owner record inside the active transaction."""

        _require_active_r7_result_lifecycle_uow()
        authorization = self._source.get_exact(
            authorization_ref=authorization_ref,
            result_ref=result_ref,
            action=action,
            as_of=as_of,
        )
        if authorization is not None and (
            authorization.authorization_id != authorization_ref.authorization_id
            or authorization.authorization_version != authorization_ref.authorization_version
            or authorization.result_ref != result_ref
            or authorization.action is not action
        ):
            raise R7ResultLifecycleCorruption(
                "R7 result lifecycle owner returned substituted authorization"
            )
        return authorization


class _DjangoR7ResultLifecycleStore:
    """Exact append/PIT audit repository with no active/current result reader."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7ResearchResultClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR7ResearchResultClock()
        self._result_repository = DjangoR7ResearchResultRepository(
            using=using,
            clock=self._clock,
        )
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Enter one result/authorization/event transaction and capability scope."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r7_result_lifecycle_uow(self._token):
            yield

    def server_now(self) -> datetime:
        """Return and validate the authoritative server clock."""

        return _aware(self._clock.now(), "R7 result lifecycle server clock")

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        """Delegate one exact PIT read to the immutable R7 result repository."""

        return self._result_repository.get_exact(
            result_id=result_id,
            result_version=result_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def load_lifecycle_stream(
        self,
        *,
        result_ref: R7ResearchResultRef,
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        """Restore the complete exact stream while retaining corruption evidence."""

        _require_active_r7_result_lifecycle_uow()
        result_model = self._exact_result_model(result_ref=result_ref, lock=False)
        event_models = list(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_related(
                "result",
                "authorization_record",
                "authorization_record__result",
            )
            .filter(result=result_model)
            .order_by("sequence", "pk")
        )
        authorization_models = list(
            R7ResultLifecycleAuthorizationModel._default_manager.using(self._using)
            .select_related("result")
            .filter(result=result_model)
            .order_by("expected_sequence", "pk")
        )
        for authorization_model in authorization_models:
            self._restore_authorization(authorization_model)
        authorization_ids = {model.pk for model in authorization_models}
        event_authorization_ids = {model.authorization_record_id for model in event_models}
        if authorization_ids != event_authorization_ids:
            raise R7ResultLifecycleCorruption("R7 lifecycle authorization/event set is incomplete")
        events = tuple(self._restore_event(model) for model in event_models)
        if events:
            try:
                derive_r7_result_lifecycle_state(
                    events,
                    evaluated_at=self.server_now(),
                )
            except ValueError as error:
                raise R7ResultLifecycleCorruption(
                    "R7 result lifecycle stream failed replay"
                ) from error
        return events

    def get_event_by_authorization(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
    ) -> R7ResultLifecycleEvent | None:
        """Restore an idempotent event by exact authorization identity."""

        _require_active_r7_result_lifecycle_uow()
        models = list(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_related(
                "result",
                "authorization_record",
                "authorization_record__result",
            )
            .filter(
                Q(
                    authorization_id=authorization_ref.authorization_id,
                    authorization_version=authorization_ref.authorization_version,
                )
                | Q(
                    authorization_record__authorization_id=(authorization_ref.authorization_id),
                    authorization_record__authorization_version=(
                        authorization_ref.authorization_version
                    ),
                )
            )
        )
        if len(models) > 1:
            raise R7ResultLifecycleCorruption(
                "multiple R7 lifecycle events match one authorization identity"
            )
        return self._restore_event(models[0]) if models else None

    def append_lifecycle(
        self,
        *,
        authorization: R7ResultPromotionAuthorization,
        event: R7ResultLifecycleEvent,
    ) -> R7ResultLifecycleEvent:
        """Atomically append an exact authorization/event pair or exact race winner."""

        _require_active_r7_result_lifecycle_uow()
        if not _authorization_matches_event(authorization, event):
            raise R7ResultLifecycleConflict(
                "R7 lifecycle event differs from its owner authorization"
            )
        result_model = self._exact_result_model(
            result_ref=authorization.result_ref,
            lock=True,
        )
        winner = self._existing_winner(authorization=authorization, event=event)
        if winner is not None:
            return winner
        self._reject_collisions(authorization=authorization, event=event)
        authorization_values = _authorization_values(authorization)
        authorization_claim = {
            **authorization_values,
            "result_id": result_model.pk,
        }
        event_values = _event_values(event)
        try:
            with transaction.atomic(using=self._using):
                with _claim_r7_result_lifecycle_insert(
                    token=self._token,
                    expected_values=authorization_claim,
                ):
                    authorization_model = (
                        R7ResultLifecycleAuthorizationModel._default_manager.using(
                            self._using
                        ).create(result=result_model, **authorization_values)
                    )
                event_claim = {
                    **event_values,
                    "result_id": result_model.pk,
                    "authorization_record_id": authorization_model.pk,
                }
                with _claim_r7_result_lifecycle_insert(
                    token=self._token,
                    expected_values=event_claim,
                ):
                    R7ResultLifecycleEventModel._default_manager.using(self._using).create(
                        result=result_model,
                        authorization_record=authorization_model,
                        **event_values,
                    )
        except IntegrityError as error:
            winner = self._existing_winner(
                authorization=authorization,
                event=event,
            )
            if winner is not None:
                return winner
            raise R7ResultLifecycleConflict("R7 result lifecycle append race lost") from error
        return event

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R7ResearchResultAuditPage:
        """Materialize or replay one immutable PIT audit snapshot manifest."""

        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R7 result audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = _decode_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                # One locking statement establishes the manifest boundary. Lifecycle
                # appends lock the same result row before writing authorization/event
                # evidence, so each append is serialized wholly before or after this
                # snapshot build instead of becoming visible between entry reads.
                result_models = list(
                    R7ResearchResultModel._default_manager.using(self._using)
                    .select_for_update()
                    .filter(recorded_at__lte=as_of)
                    .order_by("recorded_at", "result_id", "result_version")
                )
                entries = tuple(
                    self._audit_entry(model=model, as_of=as_of) for model in result_models
                )
                if len(entries) <= limit:
                    return R7ResearchResultAuditPage(entries, None, as_of)
                snapshot = _create_audit_snapshot(
                    as_of=as_of,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return R7ResearchResultAuditPage(
                    snapshot.entries[:limit],
                    _encode_cursor(snapshot=snapshot, next_offset=limit),
                    as_of,
                )
            if cursor_value.snapshot_as_of != as_of.astimezone(UTC):
                raise R7ResultLifecycleUnavailable(
                    "R7 result audit cursor belongs to a different snapshot"
                )
            snapshot = self._get_audit_snapshot(cursor_value)
            if snapshot.as_of != as_of:
                raise R7ResultLifecycleCorruption(
                    "R7 result audit snapshot cutoff differs from its cursor"
                )
            start = cursor_value.next_offset
            if start >= len(snapshot.entries):
                raise R7ResultLifecycleCorruption(
                    "R7 result audit cursor offset exceeds its snapshot"
                )
            page_entries = snapshot.entries[start : start + limit]
            next_offset = start + len(page_entries)
            next_cursor = None
            if next_offset < len(snapshot.entries):
                next_cursor = _encode_cursor(
                    snapshot=snapshot,
                    next_offset=next_offset,
                )
            return R7ResearchResultAuditPage(page_entries, next_cursor, as_of)

    def _append_audit_snapshot(self, snapshot: _AuditSnapshot) -> None:
        _require_active_r7_result_lifecycle_uow()
        if (
            R7ResearchResultAuditSnapshotModel._default_manager.using(self._using)
            .filter(
                Q(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_version=snapshot.snapshot_version,
                )
                | Q(content_hash=snapshot.content_hash)
            )
            .exists()
        ):
            raise R7ResultLifecycleConflict("R7 result audit snapshot identity already exists")
        values = _audit_snapshot_values(snapshot)
        with _claim_r7_result_lifecycle_insert(
            token=self._token,
            expected_values=values,
        ):
            R7ResearchResultAuditSnapshotModel._default_manager.using(self._using).create(**values)

    def _get_audit_snapshot(self, cursor: _AuditCursor) -> _AuditSnapshot:
        _require_active_r7_result_lifecycle_uow()
        models = list(
            R7ResearchResultAuditSnapshotModel._default_manager.using(self._using).filter(
                Q(
                    snapshot_id=cursor.snapshot_id,
                    snapshot_version=cursor.snapshot_version,
                )
                | Q(content_hash=cursor.snapshot_hash)
            )
        )
        matches = tuple(
            model
            for model in models
            if (
                model.snapshot_id,
                model.snapshot_version,
                model.content_hash,
            )
            == (
                cursor.snapshot_id,
                cursor.snapshot_version,
                cursor.snapshot_hash,
            )
        )
        if len(matches) != 1 or len(models) != 1:
            raise R7ResultLifecycleCorruption(
                "R7 result audit snapshot is unavailable or substituted"
            )
        return _restore_audit_snapshot(matches[0])

    def _audit_entry(
        self,
        *,
        model: R7ResearchResultModel,
        as_of: datetime,
    ) -> R7ResearchResultAuditEntry:
        result = self._result_repository.get_exact(
            result_id=model.result_id,
            result_version=model.result_version,
            expected_content_hash=model.content_hash,
            as_of=as_of,
        )
        if result is None:
            raise R7ResultLifecycleCorruption(
                "R7 audit result disappeared during exact restoration"
            )
        result_ref = R7ResearchResultRef(
            result.result_id,
            result.result_version,
            result.content_hash,
        )
        history = self.load_lifecycle_stream(result_ref=result_ref)
        prefix = tuple(item for item in history if item.recorded_at <= as_of)
        lifecycle_status = R7ResultLifecycleStatus.UNPROMOTED
        lifecycle_sequence = 0
        head_event_hash: str | None = None
        promoted_at: datetime | None = None
        retired_at: datetime | None = None
        if prefix:
            try:
                state = derive_r7_result_lifecycle_state(prefix, evaluated_at=as_of)
            except ValueError as error:
                raise R7ResultLifecycleCorruption(
                    "R7 audit lifecycle prefix failed replay"
                ) from error
            lifecycle_status = state.status
            lifecycle_sequence = state.sequence
            head_event_hash = state.head_event_hash
            promoted_at = state.promoted_at
            retired_at = state.retired_at
        receipt = result.input_receipt
        blocker_codes = tuple(
            sorted(
                {
                    blocker.reason_code
                    for blockers in (
                        result.calibration.subjective.blockers,
                        result.calibration.model_inferred.blockers,
                        result.historical_analogy.blockers,
                        result.path_research.blockers,
                    )
                    for blocker in blockers
                }
            )
        )
        return R7ResearchResultAuditEntry(
            result_ref=result_ref,
            policy_id=receipt.policy_id,
            policy_version=receipt.policy_version,
            policy_record_hash=receipt.policy_record_hash,
            scope_content_hash=receipt.scope_content_hash,
            evaluated_at=receipt.evaluated_at,
            recorded_at=result.recorded_at,
            result_persisted_at=_aware(
                model.persisted_at,
                "R7 audit result persisted_at",
            ),
            subjective_calibration_status=result.calibration.subjective.status,
            model_inferred_calibration_status=result.calibration.model_inferred.status,
            historical_analogy_status=result.historical_analogy.status,
            path_research_status=result.path_research.status,
            blocker_codes=blocker_codes,
            lifecycle_status=lifecycle_status,
            lifecycle_sequence=lifecycle_sequence,
            head_event_hash=head_event_hash,
            promoted_at=promoted_at,
            retired_at=retired_at,
            research_only=result.research_only,
            must_not_use_for_decision=result.must_not_use_for_decision,
            must_not_execute=result.must_not_execute,
        )

    def _exact_result_model(
        self,
        *,
        result_ref: R7ResearchResultRef,
        lock: bool,
    ) -> R7ResearchResultModel:
        query: QuerySet[R7ResearchResultModel] = R7ResearchResultModel._default_manager.using(
            self._using
        ).filter(
            Q(
                result_id=result_ref.result_id,
                result_version=result_ref.result_version,
            )
            | Q(content_hash=result_ref.content_hash)
        )
        if lock:
            query = query.select_for_update()
        models = list(query)
        exact = tuple(
            model
            for model in models
            if (
                model.result_id,
                model.result_version,
                model.content_hash,
            )
            == (
                result_ref.result_id,
                result_ref.result_version,
                result_ref.content_hash,
            )
        )
        if not models:
            raise R7ResultLifecycleUnavailable("exact R7 result row is unavailable")
        if len(exact) != 1 or len(models) != 1:
            raise R7ResultLifecycleCorruption(
                "R7 lifecycle result identity or content seal is substituted"
            )
        record = self._result_repository.get_exact(
            result_id=result_ref.result_id,
            result_version=result_ref.result_version,
            expected_content_hash=result_ref.content_hash,
            as_of=self.server_now(),
        )
        if record is None:
            raise R7ResultLifecycleCorruption("R7 lifecycle exact result failed strict restoration")
        return exact[0]

    def _existing_winner(
        self,
        *,
        authorization: R7ResultPromotionAuthorization,
        event: R7ResultLifecycleEvent,
    ) -> R7ResultLifecycleEvent | None:
        models = list(
            R7ResultLifecycleEventModel._default_manager.using(self._using)
            .select_related(
                "result",
                "authorization_record",
                "authorization_record__result",
            )
            .filter(
                Q(
                    authorization_id=authorization.authorization_id,
                    authorization_version=authorization.authorization_version,
                )
                | Q(
                    authorization_record__authorization_id=(authorization.authorization_id),
                    authorization_record__authorization_version=(
                        authorization.authorization_version
                    ),
                )
            )
        )
        if not models:
            authorization_exists = (
                R7ResultLifecycleAuthorizationModel._default_manager.using(self._using)
                .filter(
                    authorization_id=authorization.authorization_id,
                    authorization_version=authorization.authorization_version,
                )
                .exists()
            )
            if authorization_exists:
                raise R7ResultLifecycleCorruption(
                    "R7 lifecycle authorization exists without its atomic event"
                )
            return None
        if len(models) != 1:
            raise R7ResultLifecycleCorruption(
                "multiple R7 lifecycle winners match one authorization"
            )
        restored = self._restore_event(models[0])
        restored_authorization = self._restore_authorization(models[0].authorization_record)
        if restored == event and restored_authorization == authorization:
            return restored
        raise R7ResultLifecycleConflict(
            "R7 lifecycle authorization identity was sealed with different content"
        )

    def _reject_collisions(
        self,
        *,
        authorization: R7ResultPromotionAuthorization,
        event: R7ResultLifecycleEvent,
    ) -> None:
        if (
            R7ResultLifecycleAuthorizationModel._default_manager.using(self._using)
            .filter(
                Q(event_id=authorization.event_id, event_version=authorization.event_version)
                | Q(content_hash=authorization.content_hash)
            )
            .exists()
            or R7ResultLifecycleEventModel._default_manager.using(self._using)
            .filter(
                Q(event_id=event.event_id, event_version=event.event_version)
                | Q(content_hash=event.content_hash)
                | Q(
                    result_key=event.result_ref.result_id,
                    result_version=event.result_ref.result_version,
                    sequence=event.sequence,
                )
            )
            .exists()
        ):
            raise R7ResultLifecycleConflict(
                "R7 result lifecycle event or sequence identity already exists"
            )

    def _restore_authorization(
        self,
        model: R7ResultLifecycleAuthorizationModel,
    ) -> R7ResultPromotionAuthorization:
        try:
            authorization = decode_r7_result_lifecycle_authorization(model.canonical_payload)
        except R7ResultLifecycleCodecError as error:
            raise R7ResultLifecycleCorruption(
                "R7 result lifecycle authorization payload is invalid"
            ) from error
        if _authorization_model_headers(model) != _authorization_headers(authorization):
            raise R7ResultLifecycleCorruption("R7 result lifecycle authorization header mismatch")
        result_model = model.result
        if model.result_id != result_model.pk or (
            result_model.result_id,
            result_model.result_version,
            result_model.content_hash,
        ) != (
            authorization.result_ref.result_id,
            authorization.result_ref.result_version,
            authorization.result_ref.content_hash,
        ):
            raise R7ResultLifecycleCorruption(
                "R7 result lifecycle authorization relation substitution"
            )
        return authorization

    def _restore_event(
        self,
        model: R7ResultLifecycleEventModel,
    ) -> R7ResultLifecycleEvent:
        try:
            event = decode_r7_result_lifecycle_event(model.canonical_payload)
        except R7ResultLifecycleCodecError as error:
            raise R7ResultLifecycleCorruption(
                "R7 result lifecycle event payload is invalid"
            ) from error
        authorization = self._restore_authorization(model.authorization_record)
        if _event_model_headers(model) != _event_headers(event):
            raise R7ResultLifecycleCorruption("R7 result lifecycle event header mismatch")
        if (
            model.result_id != model.authorization_record.result_id
            or model.result_id != model.result.pk
            or event.result_ref != authorization.result_ref
            or event.authorization_id != authorization.authorization_id
            or event.authorization_version != authorization.authorization_version
            or event.authorization_hash != authorization.content_hash
            or not _authorization_matches_event(authorization, event)
        ):
            raise R7ResultLifecycleCorruption("R7 result lifecycle event relation substitution")
        return event

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        _aware(as_of, "R7 result audit as_of")
        if as_of > self.server_now():
            raise R7ResultLifecycleUnavailable("future R7 result audit cutoff")


def _authorization_matches_event(
    authorization: R7ResultPromotionAuthorization,
    event: R7ResultLifecycleEvent,
) -> bool:
    return (
        event.event_id == authorization.event_id
        and event.event_version == authorization.event_version
        and event.result_ref == authorization.result_ref
        and event.authorization_id == authorization.authorization_id
        and event.authorization_version == authorization.authorization_version
        and event.authorization_hash == authorization.content_hash
        and event.action is authorization.action
        and event.sequence == authorization.expected_sequence
        and event.reason_codes == authorization.reason_codes
    )


def _authorization_values(
    authorization: R7ResultPromotionAuthorization,
) -> dict[str, object]:
    return {
        "result_key": authorization.result_ref.result_id,
        "result_version": authorization.result_ref.result_version,
        "result_content_hash": authorization.result_ref.content_hash,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "action": authorization.action.value,
        "expected_sequence": authorization.expected_sequence,
        "owner": authorization.owner,
        "issued_at": authorization.issued_at,
        "recorded_at": authorization.recorded_at,
        "valid_until": authorization.valid_until,
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        "canonical_payload": encode_r7_result_lifecycle_authorization(authorization),
        "research_only": authorization.research_only,
        "promotes_internal_research_record_only": (
            authorization.promotes_internal_research_record_only
        ),
        "publishes_model_probability": authorization.publishes_model_probability,
        "produces_decision": authorization.produces_decision,
        "executes_orders": authorization.executes_orders,
        "must_not_use_for_decision": authorization.must_not_use_for_decision,
        "must_not_execute": authorization.must_not_execute,
        "content_hash": authorization.content_hash,
    }


def _event_values(event: R7ResultLifecycleEvent) -> dict[str, object]:
    return {
        "result_key": event.result_ref.result_id,
        "result_version": event.result_ref.result_version,
        "result_content_hash": event.result_ref.content_hash,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "authorization_id": event.authorization_id,
        "authorization_version": event.authorization_version,
        "authorization_hash": event.authorization_hash,
        "action": event.action.value,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash,
        "reason_codes": list(event.reason_codes),
        "canonical_payload": encode_r7_result_lifecycle_event(event),
        "research_only": event.research_only,
        "promotes_internal_research_record_only": (event.promotes_internal_research_record_only),
        "publishes_model_probability": event.publishes_model_probability,
        "produces_decision": event.produces_decision,
        "executes_orders": event.executes_orders,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_execute": event.must_not_execute,
        "content_hash": event.content_hash,
    }


def _authorization_headers(
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


def _authorization_model_headers(
    model: R7ResultLifecycleAuthorizationModel,
) -> tuple[object, ...]:
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


def _event_headers(event: R7ResultLifecycleEvent) -> tuple[object, ...]:
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


def _event_model_headers(model: R7ResultLifecycleEventModel) -> tuple[object, ...]:
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


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R7ResultLifecycleUnavailable(f"{label} must be timezone-aware")
    return value


def _create_audit_snapshot(
    *,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R7ResearchResultAuditEntry, ...],
) -> _AuditSnapshot:
    snapshot_id = f"r7-result-audit-snapshot:{uuid4()}"
    normalized_as_of = as_of.astimezone(UTC)
    normalized_created_at = created_at.astimezone(UTC)
    digest = _audit_snapshot_hash(
        snapshot_id=snapshot_id,
        snapshot_version=_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
    )
    return _AuditSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version=_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
        internal_audit_only=True,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
        content_hash=digest,
    )


def _audit_snapshot_values(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": _audit_snapshot_payload(snapshot),
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_execute": snapshot.must_not_execute,
        "content_hash": snapshot.content_hash,
    }


def _audit_snapshot_payload(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "schema": _SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of.astimezone(UTC).isoformat(),
        "created_at": snapshot.created_at.astimezone(UTC).isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in snapshot.entries],
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_execute": snapshot.must_not_execute,
        "content_hash": snapshot.content_hash,
    }


def _restore_audit_snapshot(model: R7ResearchResultAuditSnapshotModel) -> _AuditSnapshot:
    payload = _payload_mapping(model.canonical_payload, "audit snapshot")
    expected_keys = {
        "schema",
        "snapshot_id",
        "snapshot_version",
        "as_of",
        "created_at",
        "entries",
        "internal_audit_only",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
        "content_hash",
    }
    if set(payload) != expected_keys or payload["schema"] != _SNAPSHOT_SCHEMA:
        raise R7ResultLifecycleCorruption("R7 audit snapshot payload schema is invalid")
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list):
        raise R7ResultLifecycleCorruption("R7 audit snapshot entries are invalid")
    entries = tuple(_decode_audit_entry(item) for item in raw_entries)
    snapshot = _AuditSnapshot(
        snapshot_id=_payload_string(payload, "snapshot_id"),
        snapshot_version=_payload_string(payload, "snapshot_version"),
        as_of=_payload_datetime(payload, "as_of"),
        created_at=_payload_datetime(payload, "created_at"),
        entries=entries,
        internal_audit_only=_payload_bool(payload, "internal_audit_only"),
        research_only=_payload_bool(payload, "research_only"),
        must_not_use_for_decision=_payload_bool(payload, "must_not_use_for_decision"),
        must_not_execute=_payload_bool(payload, "must_not_execute"),
        content_hash=_payload_string(payload, "content_hash"),
    )
    require_token(snapshot.snapshot_id, "R7 audit snapshot_id", maximum=192)
    require_token(snapshot.snapshot_version, "R7 audit snapshot_version", maximum=192)
    require_sha256(snapshot.content_hash, "R7 audit snapshot content_hash")
    if snapshot.as_of > snapshot.created_at:
        raise R7ResultLifecycleCorruption("R7 audit snapshot clocks are invalid")
    if not (
        snapshot.internal_audit_only
        and snapshot.research_only
        and snapshot.must_not_use_for_decision
        and snapshot.must_not_execute
    ):
        raise R7ResultLifecycleCorruption("R7 audit snapshot safety is relaxed")
    ordering = tuple(
        (entry.recorded_at, entry.result_ref.result_id, entry.result_ref.result_version)
        for entry in snapshot.entries
    )
    if ordering != tuple(sorted(ordering)) or len(ordering) != len(set(ordering)):
        raise R7ResultLifecycleCorruption("R7 audit snapshot ordering is invalid")
    if any(entry.recorded_at > snapshot.as_of for entry in snapshot.entries):
        raise R7ResultLifecycleCorruption("R7 audit snapshot contains future results")
    expected_hash = _audit_snapshot_hash(
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        as_of=snapshot.as_of,
        created_at=snapshot.created_at,
        entries=snapshot.entries,
    )
    if snapshot.content_hash != expected_hash:
        raise R7ResultLifecycleCorruption("R7 audit snapshot content_hash mismatch")
    model_headers = (
        model.snapshot_id,
        model.snapshot_version,
        model.as_of,
        model.created_at,
        model.entry_count,
        model.internal_audit_only,
        model.research_only,
        model.must_not_use_for_decision,
        model.must_not_execute,
        model.content_hash,
    )
    snapshot_headers = (
        snapshot.snapshot_id,
        snapshot.snapshot_version,
        snapshot.as_of,
        snapshot.created_at,
        len(snapshot.entries),
        snapshot.internal_audit_only,
        snapshot.research_only,
        snapshot.must_not_use_for_decision,
        snapshot.must_not_execute,
        snapshot.content_hash,
    )
    if model_headers != snapshot_headers:
        raise R7ResultLifecycleCorruption("R7 audit snapshot header mismatch")
    return snapshot


def _audit_snapshot_hash(
    *,
    snapshot_id: str,
    snapshot_version: str,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R7ResearchResultAuditEntry, ...],
) -> str:
    body: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "snapshot_version": snapshot_version,
        "as_of": as_of.astimezone(UTC).isoformat(),
        "created_at": created_at.astimezone(UTC).isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in entries],
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    return sha256(_canonical_json(body).encode()).hexdigest()


def _encode_audit_entry(entry: R7ResearchResultAuditEntry) -> dict[str, object]:
    return {
        "result_id": entry.result_ref.result_id,
        "result_version": entry.result_ref.result_version,
        "result_content_hash": entry.result_ref.content_hash,
        "policy_id": entry.policy_id,
        "policy_version": entry.policy_version,
        "policy_record_hash": entry.policy_record_hash,
        "scope_content_hash": entry.scope_content_hash,
        "evaluated_at": entry.evaluated_at.astimezone(UTC).isoformat(),
        "recorded_at": entry.recorded_at.astimezone(UTC).isoformat(),
        "result_persisted_at": entry.result_persisted_at.astimezone(UTC).isoformat(),
        "subjective_calibration_status": entry.subjective_calibration_status.value,
        "model_inferred_calibration_status": entry.model_inferred_calibration_status.value,
        "historical_analogy_status": entry.historical_analogy_status.value,
        "path_research_status": entry.path_research_status.value,
        "blocker_codes": list(entry.blocker_codes),
        "lifecycle_status": entry.lifecycle_status.value,
        "lifecycle_sequence": entry.lifecycle_sequence,
        "head_event_hash": entry.head_event_hash,
        "promoted_at": _optional_clock(entry.promoted_at),
        "retired_at": _optional_clock(entry.retired_at),
        "research_only": entry.research_only,
        "must_not_use_for_decision": entry.must_not_use_for_decision,
        "must_not_execute": entry.must_not_execute,
    }


def _decode_audit_entry(payload: object) -> R7ResearchResultAuditEntry:
    mapping = _payload_mapping(payload, "audit snapshot entry")
    expected_keys = {
        "result_id",
        "result_version",
        "result_content_hash",
        "policy_id",
        "policy_version",
        "policy_record_hash",
        "scope_content_hash",
        "evaluated_at",
        "recorded_at",
        "result_persisted_at",
        "subjective_calibration_status",
        "model_inferred_calibration_status",
        "historical_analogy_status",
        "path_research_status",
        "blocker_codes",
        "lifecycle_status",
        "lifecycle_sequence",
        "head_event_hash",
        "promoted_at",
        "retired_at",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    }
    if set(mapping) != expected_keys:
        raise R7ResultLifecycleCorruption("R7 audit snapshot entry fields are invalid")
    result_ref = R7ResearchResultRef(
        _payload_string(mapping, "result_id"),
        _payload_string(mapping, "result_version"),
        _payload_string(mapping, "result_content_hash"),
    )
    policy_id = _payload_string(mapping, "policy_id")
    policy_version = _payload_string(mapping, "policy_version")
    policy_hash = _payload_string(mapping, "policy_record_hash")
    scope_hash = _payload_string(mapping, "scope_content_hash")
    require_token(policy_id, "R7 audit policy_id", maximum=192)
    require_token(policy_version, "R7 audit policy_version", maximum=192)
    require_sha256(policy_hash, "R7 audit policy_record_hash")
    require_sha256(scope_hash, "R7 audit scope_content_hash")
    raw_blockers = mapping["blocker_codes"]
    if not isinstance(raw_blockers, list) or any(
        not isinstance(item, str) for item in raw_blockers
    ):
        raise R7ResultLifecycleCorruption("R7 audit blocker codes are invalid")
    blocker_codes = tuple(raw_blockers)
    if blocker_codes != tuple(sorted(set(blocker_codes))):
        raise R7ResultLifecycleCorruption("R7 audit blocker codes are noncanonical")
    for blocker_code in blocker_codes:
        require_token(blocker_code, "R7 audit blocker code", maximum=192)
    head_hash = _payload_optional_string(mapping, "head_event_hash")
    if head_hash is not None:
        require_sha256(head_hash, "R7 audit head_event_hash")
    try:
        entry = R7ResearchResultAuditEntry(
            result_ref=result_ref,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_record_hash=policy_hash,
            scope_content_hash=scope_hash,
            evaluated_at=_payload_datetime(mapping, "evaluated_at"),
            recorded_at=_payload_datetime(mapping, "recorded_at"),
            result_persisted_at=_payload_datetime(mapping, "result_persisted_at"),
            subjective_calibration_status=ResearchEvidenceStatus(
                _payload_string(mapping, "subjective_calibration_status")
            ),
            model_inferred_calibration_status=ResearchEvidenceStatus(
                _payload_string(mapping, "model_inferred_calibration_status")
            ),
            historical_analogy_status=ResearchEvidenceStatus(
                _payload_string(mapping, "historical_analogy_status")
            ),
            path_research_status=ResearchEvidenceStatus(
                _payload_string(mapping, "path_research_status")
            ),
            blocker_codes=blocker_codes,
            lifecycle_status=R7ResultLifecycleStatus(_payload_string(mapping, "lifecycle_status")),
            lifecycle_sequence=_payload_int(mapping, "lifecycle_sequence"),
            head_event_hash=head_hash,
            promoted_at=_payload_optional_datetime(mapping, "promoted_at"),
            retired_at=_payload_optional_datetime(mapping, "retired_at"),
            research_only=_payload_bool(mapping, "research_only"),
            must_not_use_for_decision=_payload_bool(mapping, "must_not_use_for_decision"),
            must_not_execute=_payload_bool(mapping, "must_not_execute"),
        )
    except ValueError as error:
        raise R7ResultLifecycleCorruption("R7 audit snapshot entry is invalid") from error
    _validate_audit_entry(entry)
    return entry


def _validate_audit_entry(entry: R7ResearchResultAuditEntry) -> None:
    if entry.evaluated_at > entry.recorded_at:
        raise R7ResultLifecycleCorruption("R7 audit entry clocks are invalid")
    if not (entry.research_only and entry.must_not_use_for_decision and entry.must_not_execute):
        raise R7ResultLifecycleCorruption("R7 audit entry safety is relaxed")
    if entry.lifecycle_status is R7ResultLifecycleStatus.UNPROMOTED:
        valid = (
            entry.lifecycle_sequence == 0
            and entry.head_event_hash is None
            and entry.promoted_at is None
            and entry.retired_at is None
        )
    elif entry.lifecycle_status is R7ResultLifecycleStatus.PROMOTED:
        valid = (
            entry.lifecycle_sequence >= 1
            and entry.head_event_hash is not None
            and entry.promoted_at is not None
            and entry.retired_at is None
        )
    else:
        valid = (
            entry.lifecycle_sequence >= 2
            and entry.head_event_hash is not None
            and entry.promoted_at is not None
            and entry.retired_at is not None
        )
    if not valid:
        raise R7ResultLifecycleCorruption("R7 audit lifecycle projection is invalid")


def _encode_cursor(*, snapshot: _AuditSnapshot, next_offset: int) -> str:
    body: dict[str, object] = {
        "schema": _CURSOR_SCHEMA,
        "snapshot_as_of": snapshot.as_of.astimezone(UTC).isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.content_hash,
        "next_offset": next_offset,
    }
    return signing.dumps(body, salt=_CURSOR_SALT, compress=True)


def _decode_cursor(cursor: str | None) -> _AuditCursor | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
        raise ValueError("R7 result audit cursor is invalid")
    try:
        payload = signing.loads(cursor, salt=_CURSOR_SALT)
    except signing.BadSignature as error:
        raise ValueError("R7 result audit cursor signature is invalid") from error
    mapping = _payload_mapping(payload, "audit cursor")
    if (
        set(mapping)
        != {
            "schema",
            "snapshot_as_of",
            "snapshot_id",
            "snapshot_version",
            "snapshot_hash",
            "next_offset",
        }
        or mapping["schema"] != _CURSOR_SCHEMA
    ):
        raise ValueError("R7 result audit cursor fields are invalid")
    snapshot_id = _payload_string(mapping, "snapshot_id")
    snapshot_version = _payload_string(mapping, "snapshot_version")
    snapshot_hash = _payload_string(mapping, "snapshot_hash")
    require_token(snapshot_id, "R7 audit cursor snapshot_id", maximum=192)
    require_token(snapshot_version, "R7 audit cursor snapshot_version", maximum=192)
    require_sha256(snapshot_hash, "R7 audit cursor snapshot_hash")
    next_offset = _payload_int(mapping, "next_offset")
    if next_offset < 1:
        raise ValueError("R7 result audit cursor offset is invalid")
    return _AuditCursor(
        snapshot_as_of=_payload_datetime(mapping, "snapshot_as_of"),
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_hash=snapshot_hash,
        next_offset=next_offset,
    )


def _payload_mapping(payload: object, label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise R7ResultLifecycleCorruption(f"R7 {label} must be a mapping")
    return payload


def _payload_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be a string")
    return value


def _payload_optional_string(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping[key]
    if value is not None and not isinstance(value, str):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} is invalid")
    return value


def _payload_bool(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be boolean")
    return value


def _payload_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be non-negative")
    return value


def _payload_datetime(mapping: Mapping[str, object], key: str) -> datetime:
    return _decode_datetime(_payload_string(mapping, key), key)


def _payload_optional_datetime(mapping: Mapping[str, object], key: str) -> datetime | None:
    raw = _payload_optional_string(mapping, key)
    return _decode_datetime(raw, key) if raw is not None else None


def _optional_clock(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _decode_datetime(raw: str, label: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise R7ResultLifecycleCorruption(f"R7 audit {label} clock is invalid") from error
    if (
        value.tzinfo is None
        or value.utcoffset() is None
        or value.astimezone(UTC).isoformat() != raw
    ):
        raise R7ResultLifecycleCorruption(f"R7 audit {label} clock is noncanonical")
    return value


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


__all__ = [
    "DjangoR7ResultLifecycleAuthorizationProvider",
]
