"""Django storage for immutable source-bound exchange calendar snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.exchange_calendar import (
    ExchangeCalendarSnapshotRepositoryPort,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarError,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    ExchangeCalendarSnapshotReference,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.exchange_calendar_source_evidence import (
    candidate_from_retained_calendar_response,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from core.exceptions import DataFetchError


class DjangoExchangeCalendarSnapshotRepository(ExchangeCalendarSnapshotRepositoryPort):
    """Persist one immutable snapshot per verified RawPayload response."""

    @transaction.atomic
    def save(self, candidate: ExchangeCalendarSnapshotCandidate) -> ExchangeCalendarSnapshot:
        """Write first knowledge time or return an exact replay without rewriting it."""

        if not isinstance(candidate, ExchangeCalendarSnapshotCandidate):
            raise DataFetchError(
                "Calendar snapshot candidate is not typed",
                code="EXCHANGE_CALENDAR_SNAPSHOT_INVALID",
            )
        raw_model = (
            RawPayloadModel._default_manager.select_for_update()
            .filter(payload_id=UUID(candidate.raw_reference.payload_id))
            .first()
        )
        if raw_model is None:
            raise DataFetchError(
                "Calendar source RawPayload no longer exists",
                code="EXCHANGE_CALENDAR_RAW_REFERENCE_MISSING",
            )
        raw_payload = raw_model.to_domain()
        self._verify_candidate_binding(candidate, raw_payload)
        existing = (
            ExchangeCalendarSnapshotFactModel._default_manager.select_for_update()
            .select_related("raw_payload")
            .filter(raw_payload_id=raw_model.pk)
            .first()
        )
        if existing is not None:
            persisted = self._to_domain(existing)
            if persisted.candidate != candidate:
                raise DataFetchError(
                    "Raw response is already bound to different calendar facts",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_IMMUTABLE_CONFLICT",
                )
            return persisted

        recorded_at = timezone.now().astimezone(UTC)
        if recorded_at < candidate.first_seen_at:
            raise DataFetchError(
                "Database record time precedes local first-seen evidence",
                code="EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
            )
        snapshot = make_exchange_calendar_snapshot(
            candidate,
            snapshot_id=str(uuid4()),
            recorded_at=recorded_at,
        )
        fields = self._model_fields(snapshot)
        try:
            with transaction.atomic():
                model = ExchangeCalendarSnapshotFactModel._default_manager.create(
                    raw_payload=raw_model,
                    raw_payload_hash=raw_payload.payload_hash,
                    **fields,
                )
        except IntegrityError as exc:
            replay = (
                ExchangeCalendarSnapshotFactModel._default_manager.select_related("raw_payload")
                .filter(raw_payload_id=raw_model.pk)
                .first()
            )
            if replay is None:
                raise DataFetchError(
                    "Calendar snapshot uniqueness conflict could not be resolved",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_WRITE_CONFLICT",
                ) from exc
            persisted = self._to_domain(replay)
            if persisted.candidate != candidate:
                raise DataFetchError(
                    "Raw response is already bound to different calendar facts",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_IMMUTABLE_CONFLICT",
                ) from exc
            return persisted
        return self._to_domain(model)

    @transaction.atomic
    def get_exact(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> ExchangeCalendarSnapshot | None:
        """Read only an exact snapshot whose first-seen and recorded times are known."""

        if not isinstance(reference, ExchangeCalendarSnapshotReference):
            raise DataFetchError(
                "Calendar snapshot reference is not typed",
                code="EXCHANGE_CALENDAR_REFERENCE_INVALID",
            )
        _require_utc(known_at, "known_at")
        model = (
            ExchangeCalendarSnapshotFactModel._default_manager.select_related("raw_payload")
            .filter(
                snapshot_id=UUID(reference.snapshot_id),
                exchange=reference.exchange,
                coverage_start=reference.coverage_start,
                coverage_end=reference.coverage_end,
                content_hash=reference.content_hash,
                record_digest=reference.record_digest,
                raw_payload_id=UUID(reference.raw_payload_id),
                raw_payload_hash=reference.raw_payload_hash,
                recorded_at__lte=known_at,
                first_seen_at__lte=known_at,
            )
            .first()
        )
        if model is None:
            return None
        snapshot = self._to_domain(model)
        return snapshot if snapshot.reference() == reference else None

    @staticmethod
    def _verify_candidate_binding(
        candidate: ExchangeCalendarSnapshotCandidate,
        raw_payload: RawPayload,
    ) -> None:
        """Reparse retained source bytes so facts cannot be rebound to edited rows."""

        try:
            verified = candidate_from_retained_calendar_response(
                raw_payload,
                candidate.raw_reference,
                exchange=candidate.exchange,
                coverage_start=candidate.coverage_start,
                coverage_end=candidate.coverage_end,
            )
        except DataFetchError:
            raise
        except ExchangeCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc
        if verified != candidate:
            raise DataFetchError(
                "Calendar candidate does not match its retained raw response",
                code="EXCHANGE_CALENDAR_SOURCE_CONTENT_MISMATCH",
            )

    @staticmethod
    def _model_fields(snapshot: ExchangeCalendarSnapshot) -> dict[str, object]:
        """Map a validated domain snapshot to the model's immutable fields."""

        return {
            "snapshot_id": UUID(snapshot.snapshot_id),
            "exchange": snapshot.exchange,
            "coverage_start": snapshot.coverage_start,
            "coverage_end": snapshot.coverage_end,
            "days": [day.to_payload() for day in snapshot.days],
            "provider_name": snapshot.provider_name,
            "raw_reference": snapshot.raw_reference.to_payload(),
            "content_hash": snapshot.content_hash,
            "first_seen_at": snapshot.first_seen_at,
            "recorded_at": snapshot.recorded_at,
            "source_published_at": snapshot.source_published_at,
            "record_digest": snapshot.record_digest,
        }

    @staticmethod
    def _to_domain(model: ExchangeCalendarSnapshotFactModel) -> ExchangeCalendarSnapshot:
        """Rebuild and verify persisted source, content, and record digests."""

        try:
            raw_payload = model.raw_payload.to_domain()
            raw_reference = _raw_reference(model.raw_reference)
            candidate = candidate_from_retained_calendar_response(
                raw_payload,
                raw_reference,
                exchange=model.exchange,
                coverage_start=model.coverage_start,
                coverage_end=model.coverage_end,
            )
            stored_days = _stored_days(model.days)
            if candidate.days != stored_days:
                raise DataFetchError(
                    "Calendar stored day rows differ from the retained response",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
                )
            if (
                candidate.provider_name != model.provider_name
                or candidate.content_hash != model.content_hash
                or raw_payload.payload_hash != model.raw_payload_hash
                or raw_payload.payload_id != str(model.raw_payload_id)
            ):
                raise DataFetchError(
                    "Calendar stored fact identity or content hash is invalid",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
                )
            snapshot = make_exchange_calendar_snapshot(
                candidate,
                snapshot_id=str(model.snapshot_id),
                recorded_at=model.recorded_at,
            )
            if snapshot.record_digest != model.record_digest:
                raise DataFetchError(
                    "Calendar stored record digest is invalid",
                    code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
                )
            return snapshot
        except DataFetchError:
            raise
        except (ExchangeCalendarError, TypeError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, ExchangeCalendarError)
                else "EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT"
            )
            raise DataFetchError(str(exc), code=code) from exc


def _raw_reference(value: object) -> ExchangeCalendarRawReference:
    """Strictly decode one persisted raw response reference JSON object."""

    payload = _mapping(value, "raw reference")
    expected_keys = {
        "payload_id",
        "payload_hash",
        "record_digest",
        "body_sha256",
        "retained_content_sha256",
        "request_scope_sha256",
        "original_body_retained",
        "response_completed_at",
        "response_time_semantics",
        "provider_name",
        "dataset_key",
        "transport",
    }
    if set(payload) != expected_keys or payload.get("response_time_semantics") != (
        "local_response_body_completion"
    ):
        raise DataFetchError(
            "Persisted calendar raw reference schema is invalid",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    return ExchangeCalendarRawReference(
        payload_id=_text(payload.get("payload_id"), "raw payload id"),
        payload_hash=_text(payload.get("payload_hash"), "raw payload hash"),
        record_digest=_text(payload.get("record_digest"), "raw record digest"),
        body_sha256=_text(payload.get("body_sha256"), "body sha256"),
        retained_content_sha256=_text(
            payload.get("retained_content_sha256"), "retained content sha256"
        ),
        request_scope_sha256=_text(payload.get("request_scope_sha256"), "request scope sha256"),
        original_body_retained=_bool(
            payload.get("original_body_retained"), "original body retained"
        ),
        response_completed_at=_datetime(
            payload.get("response_completed_at"), "response completed at"
        ),
        provider_name=_text(payload.get("provider_name"), "provider name"),
        dataset_key=_text(payload.get("dataset_key"), "dataset key"),
        transport=_text(payload.get("transport"), "transport"),
    )


def _stored_days(value: object) -> tuple[ExchangeCalendarDay, ...]:
    """Strictly decode JSON day rows without bool/int or date coercion."""

    if type(value) is not list:
        raise DataFetchError(
            "Persisted calendar day list is invalid",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    result: list[ExchangeCalendarDay] = []
    for item in value:
        payload = _mapping(item, "calendar day")
        if set(payload) != {"exchange", "calendar_date", "is_open", "previous_open_date"}:
            raise DataFetchError(
                "Persisted calendar day schema is invalid",
                code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
            )
        result.append(
            ExchangeCalendarDay(
                exchange=_text(payload.get("exchange"), "day exchange"),
                calendar_date=_date(payload.get("calendar_date"), "calendar date"),
                is_open=_bool(payload.get("is_open"), "is_open"),
                previous_open_date=_date(payload.get("previous_open_date"), "previous open date"),
            )
        )
    return tuple(result)


def _mapping(value: object, field_name: str) -> dict[str, object]:
    """Narrow one persisted JSON mapping before field access."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise DataFetchError(
            f"Persisted {field_name} must be an object",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    return cast(dict[str, object], value)


def _text(value: object, field_name: str) -> str:
    """Narrow canonical non-empty JSON strings."""

    if type(value) is not str or not value:
        raise DataFetchError(
            f"Persisted {field_name} must be a non-empty string",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    return value


def _bool(value: object, field_name: str) -> bool:
    """Require JSON boolean tokens exactly."""

    if type(value) is not bool:
        raise DataFetchError(
            f"Persisted {field_name} must be a boolean",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    return value


def _date(value: object, field_name: str) -> date:
    """Parse one canonical ISO date from the persisted day array."""

    text = _text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise DataFetchError(
            f"Persisted {field_name} is invalid",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        ) from exc
    if parsed.isoformat() != text:
        raise DataFetchError(
            f"Persisted {field_name} is non-canonical",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        )
    return parsed


def _datetime(value: object, field_name: str) -> datetime:
    """Parse one UTC timestamp from the persisted raw reference."""

    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DataFetchError(
            f"Persisted {field_name} is invalid",
            code="EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT",
        ) from exc
    _require_utc(parsed, field_name)
    return parsed


def _require_utc(value: datetime, field_name: str) -> None:
    """Reject naive or non-UTC knowledge cutoffs."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DataFetchError(
            f"{field_name} must be timezone-aware UTC",
            code="EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataFetchError(
            f"{field_name} must be timezone-aware UTC",
            code="EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
        )


__all__ = ["DjangoExchangeCalendarSnapshotRepository"]
