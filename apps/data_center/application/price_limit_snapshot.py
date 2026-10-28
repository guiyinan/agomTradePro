"""Explicit recording and offline discovery of unpublished daily price limits."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol

from apps.data_center.application.price_limit_capture import RetainedPriceLimitCapture
from apps.data_center.application.price_limit_response_capture import (
    ExactPriceLimitRequestScope,
    ExactPriceLimitValues,
    validate_exact_price_limit_payload_reference,
)
from apps.data_center.application.price_response_capture import _ASSET_CODE
from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitRawReference,
    PriceLimitSnapshot,
    PriceLimitSnapshotCandidate,
    PriceLimitSnapshotError,
    PriceLimitSnapshotReference,
    price_limit_request_scope_hash,
)
from core.exceptions import DataFetchError


class PriceLimitSnapshotRepositoryPort(Protocol):
    """Own immutable facts and replay their original sources during every read."""

    def save(self, candidate: PriceLimitSnapshotCandidate) -> PriceLimitSnapshot:
        """Persist or replay the exact same raw-bound fact without rewriting history."""
        ...

    def get_exact(
        self, reference: PriceLimitSnapshotReference, *, known_at: datetime
    ) -> PriceLimitSnapshot | None:
        """Return that identity only when response and record times are both known."""
        ...

    def discover(
        self,
        *,
        asset_code: str,
        effective_trade_date: date,
        provider_id: int,
        provider_name: str,
        known_at: datetime,
    ) -> tuple[PriceLimitSnapshot, ...]:
        """Return up to two verified candidates, preserving ambiguity instead of ranking."""
        ...


class PriceLimitCapturePort(Protocol):
    """Reuse the configured exact capture and raw-retention owner."""

    def execute(
        self, *, provider_id: int, asset_code: str, target_trade_date: date
    ) -> RetainedPriceLimitCapture:
        """Capture one explicitly selected source without inferring execution authority."""
        ...


def price_limit_candidate_from_capture(
    capture: RetainedPriceLimitCapture,
) -> PriceLimitSnapshotCandidate:
    """Translate existing typed capture evidence without inventing any source clock."""
    if (
        type(capture) is not RetainedPriceLimitCapture
        or type(capture.request_scope) is not ExactPriceLimitRequestScope
        or type(capture.values) is not ExactPriceLimitValues
        or type(capture.reference) is not ProviderResponsePayloadReference
    ):
        raise _blocked("PRICE_LIMIT_SNAPSHOT_CAPTURE_INVALID")
    scope, values, reference = capture.request_scope, capture.values, capture.reference
    validate_exact_price_limit_payload_reference(reference, scope=scope)
    try:
        raw = PriceLimitRawReference(
            payload_id=reference.payload_id,
            payload_hash=reference.payload_hash,
            record_digest=reference.record_digest,
            body_sha256=reference.body_sha256,
            retained_content_sha256=reference.retained_content_sha256,
            original_body_retained=reference.original_body_retained,
            retained_content_encoding=reference.retained_content_encoding,
            body_size_bytes=reference.body_size_bytes,
            response_completed_at=reference.response_completed_at,
            provider_name=reference.provider_name,
            dataset_key=reference.dataset_key,
            transport=reference.transport,
            run_id=reference.run_id,
            request_scope_sha256=price_limit_request_scope_hash(
                provider_id=scope.provider_id,
                provider_name=scope.provider_name,
                asset_code=scope.asset_code,
                effective_trade_date=scope.trade_date,
            ),
        )
        return PriceLimitSnapshotCandidate(
            asset_code=scope.asset_code,
            effective_trade_date=scope.trade_date,
            provider_id=scope.provider_id,
            provider_name=scope.provider_name,
            lower_limit_price=values.lower_limit_price,
            upper_limit_price=values.upper_limit_price,
            raw_reference=raw,
        )
    except PriceLimitSnapshotError as error:
        raise _blocked(error.code) from error


class RecordPriceLimitSnapshotUseCase:
    """Record an already retained capture; persistence must revalidate its original."""

    def __init__(self, repository: PriceLimitSnapshotRepositoryPort) -> None:
        """Bind the sole canonical fact owner without database access at construction."""
        self._repository = repository

    def execute(self, capture: RetainedPriceLimitCapture) -> PriceLimitSnapshot:
        """Persist an exact capture or return its original immutable fact on retry."""
        candidate = price_limit_candidate_from_capture(capture)
        result = self._repository.save(candidate)
        if type(result) is not PriceLimitSnapshot or result.content_hash != candidate.content_hash:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_RECORD_MISMATCH")
        return result


class CapturePriceLimitSnapshotUseCase:
    """Capture then record one source fact through existing provider/raw contracts."""

    def __init__(
        self, capturer: PriceLimitCapturePort, recorder: RecordPriceLimitSnapshotUseCase
    ) -> None:
        """Compose capture and recording explicitly, with no scheduling or activation."""
        self._capturer = capturer
        self._recorder = recorder

    def execute(
        self, *, provider_id: int, asset_code: str, target_trade_date: date
    ) -> PriceLimitSnapshot:
        """Record the same requested provider, security and effective date."""
        if (
            type(provider_id) is not int
            or provider_id < 1
            or type(asset_code) is not str
            or _ASSET_CODE.fullmatch(asset_code) is None
            or type(target_trade_date) is not date
        ):
            raise _blocked("PRICE_LIMIT_SNAPSHOT_CAPTURE_REQUEST_INVALID")
        capture = self._capturer.execute(
            provider_id=provider_id, asset_code=asset_code, target_trade_date=target_trade_date
        )
        candidate = price_limit_candidate_from_capture(capture)
        if (
            candidate.provider_id != provider_id
            or candidate.asset_code != asset_code
            or candidate.effective_trade_date != target_trade_date
        ):
            raise _blocked("PRICE_LIMIT_SNAPSHOT_CAPTURE_SCOPE_MISMATCH")
        return self._recorder.execute(capture)


class ReadPriceLimitSnapshotUseCase:
    """Read exact unpublished facts offline; never rank, publish, repair or recapture."""

    def __init__(self, repository: PriceLimitSnapshotRepositoryPort) -> None:
        """Bind only the immutable fact reader, without provider configuration access."""
        self._repository = repository

    def discover(
        self, *, scope: ExactPriceLimitRequestScope, known_at: datetime
    ) -> PriceLimitSnapshot:
        """Return the unique known candidate or a stable missing/ambiguous failure."""
        _require_knowledge_time(known_at)
        if type(scope) is not ExactPriceLimitRequestScope:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_SCOPE_INVALID")
        try:
            scope_hash = price_limit_request_scope_hash(
                provider_id=scope.provider_id,
                provider_name=scope.provider_name,
                asset_code=scope.asset_code,
                effective_trade_date=scope.trade_date,
            )
        except PriceLimitSnapshotError as error:
            raise _blocked(error.code) from error
        candidates = self._repository.discover(
            asset_code=scope.asset_code,
            effective_trade_date=scope.trade_date,
            provider_id=scope.provider_id,
            provider_name=scope.provider_name,
            known_at=known_at,
        )
        if not candidates:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_MISSING")
        if len(candidates) != 1:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_AMBIGUOUS")
        result = candidates[0]
        _require_known(result, known_at)
        if result.candidate.request_scope_sha256 != scope_hash:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_SCOPE_MISMATCH")
        return result

    def get_exact(
        self, reference: PriceLimitSnapshotReference, *, known_at: datetime
    ) -> PriceLimitSnapshot:
        """Replay only the supplied identity, subject to the same explicit cutoff."""
        _require_knowledge_time(known_at)
        if type(reference) is not PriceLimitSnapshotReference:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_REFERENCE_INVALID")
        result = self._repository.get_exact(reference, known_at=known_at)
        if result is None:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_MISSING")
        _require_known(result, known_at)
        if result.reference() != reference:
            raise _blocked("PRICE_LIMIT_SNAPSHOT_REFERENCE_MISMATCH")
        return result


def _require_knowledge_time(value: datetime) -> None:
    """Require an explicit aware UTC cutoff, never a default request clock."""
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise _blocked("PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID")


def _require_known(snapshot: PriceLimitSnapshot, known_at: datetime) -> None:
    """Check both acquisition and first durable storage before exposing a fact."""
    if type(snapshot) is not PriceLimitSnapshot:
        raise _blocked("PRICE_LIMIT_SNAPSHOT_RESULT_INVALID")
    if snapshot.recorded_at > known_at or snapshot.candidate.response_completed_at > known_at:
        raise _blocked("PRICE_LIMIT_SNAPSHOT_NOT_KNOWN")


def _blocked(code: str) -> DataFetchError:
    """Keep stable source-fact failure codes without granting trading qualification."""
    return DataFetchError(code, code=code)
