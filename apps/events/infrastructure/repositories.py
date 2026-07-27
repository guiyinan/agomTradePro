"""
Events Infrastructure Repositories

实现 Domain 层定义的仓储协议。

这些仓储桥接 Domain 层接口和 Django ORM 模型。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.events.domain.entities import DomainEvent
from apps.events.domain.interfaces import (
    AlphaCandidateRepositoryProtocol,
    DecisionRequestRepositoryProtocol,
)
from apps.events.domain.replay import ReplayRunReservation
from core.integration.alpha_candidate_registry import (
    get_alpha_candidate_repository as _get_alpha_candidate_repository,
)
from core.integration.decision_request_registry import (
    get_decision_request_repository as _get_decision_request_repository,
)

from .models import EventReplayRunModel, FailedEventModel

logger = logging.getLogger(__name__)

FAILED_EVENT_STATUSES = frozenset(
    {
        FailedEventModel.PENDING,
        FailedEventModel.RETRYING,
        FailedEventModel.SUCCESS,
        FailedEventModel.EXHAUSTED,
    }
)


class _SynchronizationRejected(RuntimeError):
    """Internal sentinel used to roll back logically incomplete status syncs."""


class DjangoReplayRunRepository:
    """Persist controlled replay reservations and final bounded results."""

    model = EventReplayRunModel

    def reserve(
        self,
        *,
        requester_id: int,
        target_key: str,
        normalized_request: dict[str, Any],
        request_fingerprint: str,
        idempotency_key: str,
    ) -> ReplayRunReservation:
        """Atomically reserve a replay or return its existing state."""

        try:
            with transaction.atomic():
                existing = (
                    self.model.objects.select_for_update()
                    .filter(
                        requester_id=requester_id,
                        idempotency_key=idempotency_key,
                    )
                    .first()
                )
                if existing is not None:
                    return self._reservation(existing, request_fingerprint)
                run = self.model.objects.create(
                    requester_id=requester_id,
                    target_key=target_key,
                    normalized_request=normalized_request,
                    request_fingerprint=request_fingerprint,
                    idempotency_key=idempotency_key,
                    status="running",
                    started_at=timezone.now(),
                )
                return ReplayRunReservation("reserved", run.pk)
        except IntegrityError:
            existing = self.model.objects.get(
                requester_id=requester_id,
                idempotency_key=idempotency_key,
            )
            return self._reservation(existing, request_fingerprint)

    def complete(self, run_id: int, result: dict[str, Any]) -> None:
        """Persist one completed, partial, or failed business result."""

        outcome = str(result.get("outcome") or "failed")
        self.model.objects.filter(pk=run_id).update(
            status=outcome,
            attempted=int(result.get("attempted") or 0),
            succeeded=int(result.get("succeeded") or 0),
            skipped=int(result.get("skipped") or 0),
            failed=int(result.get("failed") or 0),
            failures=list(result.get("failures") or [])[:20],
            result=result,
            finished_at=timezone.now(),
        )

    def fail(self, run_id: int, message: str) -> None:
        """Mark an infrastructure-fatal run failed with a sanitized detail."""

        sanitized = " ".join(str(message).split())[:240]
        result = {
            "outcome": "failed",
            "attempted": 0,
            "succeeded": 0,
            "skipped": 0,
            "failed": 1,
            "failures": [{"error_code": "infrastructure_error", "message": sanitized}],
            "results": [],
        }
        self.complete(run_id, result)

    @staticmethod
    def _reservation(
        run: EventReplayRunModel,
        request_fingerprint: str,
    ) -> ReplayRunReservation:
        if run.request_fingerprint != request_fingerprint:
            return ReplayRunReservation("conflict", run.pk)
        if run.status == "running":
            return ReplayRunReservation("in_progress", run.pk)
        return ReplayRunReservation("replay", run.pk, dict(run.result or {}))


class FailedEventRepository:
    """Persist, claim, transition, and clean durable failed-event records."""

    model = FailedEventModel

    def save(
        self,
        event: DomainEvent,
        handler_id: str,
        error_message: str,
        error_traceback: str | None,
        max_retries: int,
    ) -> int:
        """Persist one validated failure ready for a future retry claim."""

        event_id = self._required_text(event.event_id, field_name="event.event_id")
        normalized_handler_id = self._required_text(handler_id, field_name="handler_id")
        self._positive_int(max_retries, field_name="max_retries")
        failed_event = self.model(
            event_id=event_id,
            event_type=event.event_type.value,
            payload=event.payload,
            metadata=event.metadata,
            handler_id=normalized_handler_id,
            error_message=error_message,
            error_traceback=error_traceback or "",
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=timezone.now(),
            status=self.model.PENDING,
        )
        failed_event.save()
        event_db_id = failed_event.pk
        if event_db_id is None:
            raise RuntimeError("failed event save did not produce a primary key")
        logger.info(
            "Failed event saved: %s (handler=%s, id=%s)",
            event_id,
            normalized_handler_id,
            event_db_id,
        )
        return int(event_db_id)

    def get_by_id(self, event_db_id: int) -> dict[str, Any] | None:
        """Return one failed event by positive database ID."""

        self._positive_int(event_db_id, field_name="event_db_id")
        try:
            model = self.model._default_manager.get(pk=event_db_id)
            return self._to_dict(model)
        except ObjectDoesNotExist:
            return None

    def find_pending_events(
        self,
        limit: int,
        handler_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return currently due pending events in deterministic FIFO order."""

        self._positive_int(limit, field_name="limit")
        normalized_handler_id: str | None = None
        if handler_id is not None:
            normalized_handler_id = self._required_text(handler_id, field_name="handler_id")
        queryset = self.model._default_manager.filter(
            status=self.model.PENDING,
            next_retry_at__lte=timezone.now(),
        )
        if normalized_handler_id is not None:
            queryset = queryset.filter(handler_id=normalized_handler_id)
        failed_events = queryset.order_by("created_at", "pk")[:limit]
        return [self._to_dict(fe) for fe in failed_events]

    def update_status(
        self,
        event_db_id: int,
        status: str,
        last_retry_at: datetime | None = None,
    ) -> bool:
        """Transition state, atomically claiming only due pending retry work."""

        self._positive_int(event_db_id, field_name="event_db_id")
        normalized_status = self._required_text(status, field_name="status")
        if normalized_status not in FAILED_EVENT_STATUSES:
            raise ValueError(f"unsupported failed event status: {normalized_status}")
        normalized_retry_at = self._aware_datetime(last_retry_at, field_name="last_retry_at")
        updates: dict[str, object] = {
            "status": normalized_status,
            "updated_at": timezone.now(),
        }
        if normalized_status == self.model.RETRYING:
            updates["last_retry_at"] = normalized_retry_at or timezone.now()
            updated: int = self.model._default_manager.filter(
                pk=event_db_id,
                status=self.model.PENDING,
                next_retry_at__lte=timezone.now(),
            ).update(**updates)
            return updated == 1
        if normalized_retry_at is not None:
            updates["last_retry_at"] = normalized_retry_at
        updated = self.model._default_manager.filter(pk=event_db_id).update(**updates)
        return updated == 1

    def increment_retry_count(
        self,
        event_db_id: int,
        error_message: str,
        next_retry_at: datetime | None,
        is_exhausted: bool,
    ) -> bool:
        """Atomically increment one claimed retry and derive exhaustion from storage."""

        self._positive_int(event_db_id, field_name="event_db_id")
        if not isinstance(is_exhausted, bool):
            raise ValueError("is_exhausted must be a boolean")
        normalized_next_retry = self._aware_datetime(
            next_retry_at,
            field_name="next_retry_at",
        )
        with transaction.atomic():
            model = (
                self.model._default_manager.select_for_update()
                .filter(pk=event_db_id, status=self.model.RETRYING)
                .first()
            )
            if model is None:
                return False
            next_count = model.retry_count + 1
            derived_exhausted = next_count >= model.max_retries
            if is_exhausted != derived_exhausted:
                logger.warning(
                    "Failed event exhaustion hint disagreed with persisted counters: id=%s",
                    event_db_id,
                )
            if not derived_exhausted and normalized_next_retry is None:
                raise ValueError("next_retry_at is required before retries are exhausted")
            model.retry_count = next_count
            model.error_message = error_message
            model.status = self.model.EXHAUSTED if derived_exhausted else self.model.PENDING
            model.next_retry_at = None if derived_exhausted else normalized_next_retry
            model.save(
                update_fields=[
                    "retry_count",
                    "error_message",
                    "status",
                    "next_retry_at",
                    "updated_at",
                ]
            )
            return True

    def mark_success(self, event_db_id: int) -> bool:
        """Mark only a currently claimed retry as successful."""

        self._positive_int(event_db_id, field_name="event_db_id")
        updated: int = self.model._default_manager.filter(
            pk=event_db_id,
            status=self.model.RETRYING,
        ).update(
            status=self.model.SUCCESS,
            next_retry_at=None,
            updated_at=timezone.now(),
        )
        return updated == 1

    def cleanup_old_events(self, days: int) -> int:
        """Delete completed terminal rows older than a positive retention period."""

        self._positive_int(days, field_name="days")
        cutoff_date = timezone.now() - timedelta(days=days)
        deleted, _ = self.model._default_manager.filter(
            status__in=[self.model.SUCCESS, self.model.EXHAUSTED],
            updated_at__lt=cutoff_date,
        ).delete()
        if deleted > 0:
            logger.info("Cleaned up %s old failed event records", deleted)
        return int(deleted)

    def _to_dict(self, model: FailedEventModel) -> dict[str, Any]:
        """Convert one ORM row into the stable Application dictionary contract."""

        event_db_id = model.pk
        if event_db_id is None:
            raise RuntimeError("persisted failed event has no primary key")
        return {
            "id": int(event_db_id),
            "event_id": model.event_id,
            "event_type": model.event_type,
            "payload": model.payload,
            "metadata": model.metadata,
            "handler_id": model.handler_id,
            "error_message": model.error_message,
            "retry_count": model.retry_count,
            "max_retries": model.max_retries,
            "next_retry_at": model.next_retry_at,
            "status": model.status,
        }

    @staticmethod
    def _positive_int(value: object, *, field_name: str) -> int:
        """Require a positive non-boolean integer at the persistence boundary."""

        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        return value

    @staticmethod
    def _required_text(value: object, *, field_name: str) -> str:
        """Require a non-empty trimmed string."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _aware_datetime(value: object, *, field_name: str) -> datetime | None:
        """Require timezone-aware optional transition timestamps."""

        if value is None:
            return None
        if not isinstance(value, datetime) or not timezone.is_aware(value):
            raise ValueError(f"{field_name} must be timezone-aware")
        return value


# 便捷函数


def get_failed_event_repository() -> FailedEventRepository:
    """获取失败事件仓储实例"""
    return FailedEventRepository()


def get_alpha_candidate_repository() -> AlphaCandidateRepositoryProtocol:
    """Return the owning alpha candidate repository."""

    return cast(AlphaCandidateRepositoryProtocol, _get_alpha_candidate_repository())


def get_decision_request_repository() -> DecisionRequestRepositoryProtocol:
    """Return the owning decision request repository."""

    return cast(DecisionRequestRepositoryProtocol, _get_decision_request_repository())


class DecisionExecutionSyncRepository:
    """Coordinate decision execution writebacks inside infrastructure transactions."""

    def __init__(
        self,
        decision_request_repo: DecisionRequestRepositoryProtocol | None = None,
        alpha_candidate_repo: AlphaCandidateRepositoryProtocol | None = None,
    ) -> None:
        self._decision_request_repo = (
            decision_request_repo
            if decision_request_repo is not None
            else get_decision_request_repository()
        )
        self._alpha_candidate_repo = (
            alpha_candidate_repo
            if alpha_candidate_repo is not None
            else get_alpha_candidate_repository()
        )

    def sync_executed(
        self,
        *,
        request_id: str,
        execution_ref: dict[str, Any] | None,
        candidate_id: str | None,
    ) -> bool:
        """Persist DECISION_EXECUTED side effects atomically."""

        try:
            with transaction.atomic():
                request_updated = self._decision_request_repo.update_execution_status_to_executed(
                    request_id,
                    execution_ref,
                )
                if not request_updated:
                    raise _SynchronizationRejected("decision request was not updated")
                if candidate_id and not self._alpha_candidate_repo.update_status_to_executed(
                    candidate_id
                ):
                    raise _SynchronizationRejected("alpha candidate was not updated")
        except _SynchronizationRejected:
            return False
        return True

    def sync_failed(
        self,
        *,
        request_id: str,
        candidate_id: str | None,
        error_message: str | None,
    ) -> bool:
        """Persist DECISION_EXECUTION_FAILED side effects atomically."""

        try:
            with transaction.atomic():
                request_updated = self._decision_request_repo.update_execution_status_to_failed(
                    request_id
                )
                if not request_updated:
                    raise _SynchronizationRejected("decision request was not updated")
                if candidate_id and not (
                    self._alpha_candidate_repo.update_execution_status_to_failed(candidate_id)
                ):
                    raise _SynchronizationRejected("alpha candidate was not updated")
        except _SynchronizationRejected:
            return False
        if error_message:
            logger.warning(
                "DecisionRequest %s execution failed",
                request_id,
            )
        return True


def get_decision_execution_sync_repository() -> DecisionExecutionSyncRepository:
    """Return the infrastructure sync repository for decision execution events."""

    return DecisionExecutionSyncRepository()
