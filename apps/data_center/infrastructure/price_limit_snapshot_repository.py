"""Append-only repository for exact source-bound price-limit snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.price_limit_snapshot import PriceLimitSnapshotRepositoryPort
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitSnapshot,
    PriceLimitSnapshotCandidate,
    PriceLimitSnapshotError,
    PriceLimitSnapshotReference,
    make_price_limit_snapshot,
    price_limit_request_scope_hash,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.fact_and_operational_models import RawPayloadModel
from apps.data_center.infrastructure.price_limit_snapshot_models import PriceLimitSnapshotFactModel
from apps.data_center.infrastructure.price_limit_snapshot_source import (
    price_limit_raw_reference_from_payload,
    replay_price_limit_snapshot_candidate,
)
from core.exceptions import DataFetchError


class DjangoPriceLimitSnapshotRepository(PriceLimitSnapshotRepositoryPort):
    """Persist one immutable limit fact per exact retained provider response."""

    @transaction.atomic
    def save(self, candidate: PriceLimitSnapshotCandidate) -> PriceLimitSnapshot:
        """Validate the original response, then append or return its exact first record."""

        if type(candidate) is not PriceLimitSnapshotCandidate:
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_CANDIDATE_INVALID",
                "Price-limit snapshot candidate is not typed",
            )
        raw_model = (
            RawPayloadModel._default_manager.select_for_update()
            .filter(payload_id=UUID(candidate.raw_reference.payload_id))
            .first()
        )
        if raw_model is None:
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_MISSING",
                "Price-limit source RawPayload no longer exists",
            )
        try:
            raw_payload = raw_model.to_domain()
        except (TypeError, ValueError) as exc:
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_SOURCE_INVALID",
                "Price-limit source RawPayload metadata is invalid",
            ) from exc
        replay_price_limit_snapshot_candidate(raw_payload, candidate)
        existing = (
            PriceLimitSnapshotFactModel._default_manager.select_for_update()
            .select_related("raw_payload")
            .filter(raw_payload_id=raw_model.pk)
            .first()
        )
        if existing is not None:
            persisted = self._to_domain(existing)
            self._require_same_candidate(persisted.candidate, candidate)
            return persisted

        recorded_at = timezone.now().astimezone(UTC)
        if not timezone.is_aware(recorded_at) or recorded_at < candidate.response_completed_at:
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
                "Repository record time precedes the retained response",
            )
        snapshot = make_price_limit_snapshot(
            candidate,
            snapshot_id=str(uuid4()),
            recorded_at=recorded_at,
        )
        values = self._model_values(snapshot)
        try:
            with transaction.atomic():
                model = PriceLimitSnapshotFactModel._default_manager.create(
                    raw_payload=raw_model,
                    raw_payload_hash=raw_payload.payload_hash,
                    **values,
                )
        except IntegrityError as exc:
            winner = (
                PriceLimitSnapshotFactModel._default_manager.select_related("raw_payload")
                .filter(raw_payload_id=raw_model.pk)
                .first()
            )
            if winner is None:
                raise _blocked(
                    "PRICE_LIMIT_SNAPSHOT_WRITE_CONFLICT",
                    "Price-limit snapshot uniqueness conflict could not be resolved",
                ) from exc
            persisted = self._to_domain(winner)
            self._require_same_candidate(persisted.candidate, candidate)
            return persisted
        return self._to_domain(model)

    @transaction.atomic
    def get_exact(
        self,
        reference: PriceLimitSnapshotReference,
        *,
        known_at: datetime,
    ) -> PriceLimitSnapshot | None:
        """Read one exact fact only after both its response and record times are known."""

        if type(reference) is not PriceLimitSnapshotReference:
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_REFERENCE_INVALID",
                "Price-limit snapshot reference is not typed",
            )
        cutoff = _require_known_at(known_at)
        model = (
            PriceLimitSnapshotFactModel._default_manager.select_related("raw_payload")
            .filter(
                snapshot_id=UUID(reference.snapshot_id),
                asset_code=reference.asset_code,
                effective_trade_date=reference.effective_trade_date,
                provider_id=reference.provider_id,
                provider_name=reference.provider_name,
                content_hash=reference.content_hash,
                record_digest=reference.record_digest,
                raw_payload_id=UUID(reference.raw_payload_id),
                raw_payload_hash=reference.raw_payload_hash,
                response_completed_at__lte=cutoff,
                recorded_at__lte=cutoff,
            )
            .first()
        )
        if model is None:
            return None
        snapshot = self._to_domain(model)
        if snapshot.reference() != reference:
            return None
        if snapshot.candidate.response_completed_at > cutoff or snapshot.recorded_at > cutoff:
            return None
        return snapshot

    @transaction.atomic
    def discover(
        self,
        *,
        asset_code: str,
        effective_trade_date: date,
        provider_id: int,
        provider_name: str,
        known_at: datetime,
    ) -> tuple[PriceLimitSnapshot, ...]:
        """Return at most two verified exact-scope facts, never selecting a latest winner."""

        cutoff = _require_known_at(known_at)
        try:
            price_limit_request_scope_hash(
                provider_id=provider_id,
                provider_name=provider_name,
                asset_code=asset_code,
                effective_trade_date=effective_trade_date,
            )
        except PriceLimitSnapshotError as exc:
            raise _blocked(exc.code, str(exc)) from exc
        models = (
            PriceLimitSnapshotFactModel._default_manager.select_related("raw_payload")
            .filter(
                asset_code=asset_code,
                effective_trade_date=effective_trade_date,
                provider_id=provider_id,
                provider_name=provider_name,
                response_completed_at__lte=cutoff,
                recorded_at__lte=cutoff,
            )
            .order_by("snapshot_id")[:2]
        )
        snapshots = tuple(self._to_domain(model) for model in models)
        if any(
            item.candidate.response_completed_at > cutoff or item.recorded_at > cutoff
            for item in snapshots
        ):
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
                "Price-limit fact exceeds the requested knowledge cutoff",
            )
        return snapshots

    @staticmethod
    def _model_values(snapshot: PriceLimitSnapshot) -> dict[str, object]:
        """Map one validated domain snapshot to its exact immutable ORM fields."""

        candidate = snapshot.candidate
        return {
            "snapshot_id": UUID(snapshot.snapshot_id),
            "asset_code": candidate.asset_code,
            "effective_trade_date": candidate.effective_trade_date,
            "provider_id": candidate.provider_id,
            "provider_name": candidate.provider_name,
            "lower_limit_price": str(candidate.lower_limit_price),
            "upper_limit_price": str(candidate.upper_limit_price),
            "raw_reference": candidate.raw_reference.to_payload(),
            "content_hash": snapshot.content_hash,
            "response_completed_at": candidate.response_completed_at,
            "recorded_at": snapshot.recorded_at,
            "record_digest": snapshot.record_digest,
        }

    @classmethod
    def _to_domain(cls, model: PriceLimitSnapshotFactModel) -> PriceLimitSnapshot:
        """Rebuild the candidate and snapshot, replaying and resealing every stored field."""

        try:
            raw_payload = model.raw_payload.to_domain()
            if (
                type(raw_payload) is not RawPayload
                or str(model.raw_payload_id) != raw_payload.payload_id
                or model.raw_payload_hash != raw_payload.payload_hash
            ):
                raise _blocked(
                    "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_MISMATCH",
                    "Price-limit fact does not match its protected RawPayload identity",
                )
            raw_reference = price_limit_raw_reference_from_payload(model.raw_reference)
            candidate = PriceLimitSnapshotCandidate(
                asset_code=model.asset_code,
                effective_trade_date=model.effective_trade_date,
                provider_id=model.provider_id,
                provider_name=model.provider_name,
                lower_limit_price=_decimal_field(model.lower_limit_price, "lower_limit_price"),
                upper_limit_price=_decimal_field(model.upper_limit_price, "upper_limit_price"),
                raw_reference=raw_reference,
            )
            if candidate.response_completed_at != model.response_completed_at:
                raise _blocked(
                    "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_MISMATCH",
                    "Price-limit response time differs from its raw reference",
                )
            replayed = replay_price_limit_snapshot_candidate(raw_payload, candidate)
            snapshot = make_price_limit_snapshot(
                replayed,
                snapshot_id=str(model.snapshot_id),
                recorded_at=model.recorded_at,
            )
            if (
                replayed.content_hash != model.content_hash
                or snapshot.record_digest != model.record_digest
            ):
                raise _blocked(
                    "PRICE_LIMIT_SNAPSHOT_FACT_CORRUPT",
                    "Price-limit stored content or record digest is invalid",
                )
            return snapshot
        except DataFetchError:
            raise
        except (InvalidOperation, PriceLimitSnapshotError, TypeError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, PriceLimitSnapshotError)
                else "PRICE_LIMIT_SNAPSHOT_FACT_CORRUPT"
            )
            raise _blocked(code, "Price-limit stored fact is corrupt") from exc

    @staticmethod
    def _require_same_candidate(
        persisted: PriceLimitSnapshotCandidate,
        incoming: PriceLimitSnapshotCandidate,
    ) -> None:
        """Reject a raw-response retry that changes any exact source-bound content."""

        if (
            persisted.content_hash != incoming.content_hash
            or persisted.to_content_payload() != incoming.to_content_payload()
            or str(persisted.lower_limit_price) != str(incoming.lower_limit_price)
            or str(persisted.upper_limit_price) != str(incoming.upper_limit_price)
        ):
            raise _blocked(
                "PRICE_LIMIT_SNAPSHOT_IMMUTABLE_CONFLICT",
                "Raw response is already bound to different price-limit facts",
            )


def _require_known_at(value: datetime) -> datetime:
    """Require a timezone-aware UTC knowledge cutoff without substituting the current time."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _blocked(
            "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
            "known_at must be timezone-aware UTC",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise _blocked(
            "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
            "known_at must be timezone-aware UTC",
        )
    return value.astimezone(UTC)


def _decimal_field(value: object, field_name: str) -> Decimal:
    """Decode canonical exact Decimal text without quantization or scale loss."""

    if type(value) is not str or not value or len(value) > 512:
        raise _blocked(
            "PRICE_LIMIT_SNAPSHOT_FACT_CORRUPT",
            f"Stored {field_name} is not bounded Decimal text",
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _blocked(
            "PRICE_LIMIT_SNAPSHOT_FACT_CORRUPT",
            f"Stored {field_name} is not Decimal text",
        ) from exc
    if str(parsed) != value:
        raise _blocked(
            "PRICE_LIMIT_SNAPSHOT_FACT_CORRUPT",
            f"Stored {field_name} is not canonical Decimal text",
        )
    return parsed


def _blocked(code: str, message: str) -> DataFetchError:
    """Build a stable repository failure without hiding source-integrity codes."""

    return DataFetchError(message, code=code)


__all__ = ["DjangoPriceLimitSnapshotRepository"]
