"""Persistence repositories for redacted raw payloads and schema fingerprints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from apps.data_center.domain.raw_landing import RawPayload, SchemaFingerprint

from .models import RawPayloadModel, SchemaFingerprintModel


def _uuid(value: str) -> UUID:
    """Convert a domain identifier to a UUID."""

    return UUID(value)


class RawLandingRepository:
    """Hash-addressed raw landing repository."""

    @transaction.atomic
    def save(self, payload: RawPayload) -> RawPayload:
        """Persist a redacted payload idempotently by content hash."""

        model, _ = RawPayloadModel._default_manager.update_or_create(
            payload_hash=payload.payload_hash,
            defaults={
                "payload_id": _uuid(payload.payload_id),
                "dataset_key": payload.dataset_key,
                "provider_name": payload.provider_name,
                "schema_fingerprint": payload.schema_fingerprint,
                "payload": payload.payload,
                "request_params": payload.request_params,
                "run_id": _uuid(payload.run_id) if payload.run_id else None,
                "batch_id": _uuid(payload.batch_id) if payload.batch_id else None,
                "content_type": payload.content_type,
                "parser_version": payload.parser_version,
                "redacted": payload.redacted,
                "payload_size_bytes": payload.payload_size_bytes,
                "fetched_at": payload.fetched_at,
                "retention_until": payload.retention_until,
            },
        )
        return model.to_domain()

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        """Return one raw payload by immutable hash."""

        model = RawPayloadModel._default_manager.filter(payload_hash=payload_hash).first()
        return model.to_domain() if model is not None else None

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]:
        """Return bounded expired payloads ordered oldest first for retention.

        ``retention_until`` is an independent row-level deadline and must be
        elapsed before a payload can become a deletion candidate.  ``now`` is
        optional for backwards-compatible callers; production cleanup passes
        its operation timestamp so the candidate query and application gate
        share one clock.
        """

        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        models = (
            RawPayloadModel._default_manager.filter(
                dataset_key=dataset_key,
                fetched_at__lt=before,
            )
            .filter(Q(retention_until__isnull=True) | Q(retention_until__lte=moment))
            .order_by("fetched_at", "payload_id")[:limit]
        )
        return [model.to_domain() for model in models]

    def delete(self, payload_id: str) -> int:
        """Delete one payload by immutable ID and return the affected row count."""

        deleted, _details = RawPayloadModel._default_manager.filter(
            payload_id=_uuid(payload_id)
        ).delete()
        return int(deleted)


class SchemaFingerprintRepository:
    """Schema evolution evidence repository."""

    @transaction.atomic
    def observe(self, fingerprint: SchemaFingerprint) -> SchemaFingerprint:
        """Upsert a fingerprint and increment its observation count."""

        existing = SchemaFingerprintModel._default_manager.filter(
            fingerprint=fingerprint.fingerprint
        ).first()
        if existing is None:
            model = SchemaFingerprintModel._default_manager.create(
                fingerprint=fingerprint.fingerprint,
                dataset_key=fingerprint.dataset_key,
                provider_name=fingerprint.provider_name,
                fields=list(fingerprint.fields),
                parser_version=fingerprint.parser_version,
                first_seen_at=fingerprint.first_seen_at,
                last_seen_at=fingerprint.last_seen_at,
                sample_count=fingerprint.sample_count,
            )
        else:
            existing.last_seen_at = max(existing.last_seen_at, fingerprint.last_seen_at)
            existing.sample_count = int(existing.sample_count) + fingerprint.sample_count
            existing.save(update_fields=["last_seen_at", "sample_count"])
            model = existing
        return model.to_domain()


__all__ = ["RawLandingRepository", "SchemaFingerprintRepository"]
