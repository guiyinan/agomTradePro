"""Django persistence adapter for semantic-key governance."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from django.db import IntegrityError, transaction

from apps.ai_capability.domain.semantic_governance import (
    SemanticAuditEntry,
    SemanticBatchPersistence,
    SemanticCorrectionBatch,
    SemanticIdempotencyConflict,
    SemanticValueSnapshot,
    canonical_batch_fingerprint,
)

from .models import (
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
)


class DjangoSemanticGovernanceRepository:
    """Persist current semantic decisions and immutable audit evidence."""

    def list_active_overrides(self) -> dict[str, str]:
        """Return active overrides keyed by capability key."""

        return dict(
            CapabilitySemanticOverrideModel.objects.filter(is_active=True).values_list(
                "capability_key",
                "semantic_key",
            )
        )

    def list_audit(
        self,
        *,
        limit: int = 100,
        capability_key: str | None = None,
    ) -> tuple[SemanticAuditEntry, ...]:
        """Return a bounded newest-first immutable audit view."""

        if limit < 1 or limit > 500:
            raise ValueError("audit limit must be between 1 and 500")
        queryset = CapabilitySemanticAuditModel.objects.all()
        if capability_key:
            queryset = queryset.filter(capability_key=capability_key.strip())
        return tuple(self._to_audit_entry(model) for model in queryset[:limit])

    def find_batch(self, idempotency_key: str) -> SemanticBatchPersistence | None:
        """Return stored batch evidence for an idempotency key."""

        models = list(
            CapabilitySemanticAuditModel.objects.filter(
                idempotency_key=idempotency_key,
            ).order_by("id")
        )
        if not models:
            return None
        entries = tuple(self._to_audit_entry(model) for model in models)
        return SemanticBatchPersistence(
            batch_id=entries[0].batch_id,
            request_fingerprint=entries[0].request_fingerprint,
            replayed=True,
            entries=entries,
        )

    def apply_batch(
        self,
        batch: SemanticCorrectionBatch,
        *,
        operator_id: int,
        snapshots: Mapping[str, SemanticValueSnapshot],
    ) -> SemanticBatchPersistence:
        """Apply one correction batch atomically or replay stored evidence."""

        missing = [
            correction.capability_key
            for correction in batch.corrections
            if correction.capability_key not in snapshots
        ]
        if missing:
            raise ValueError(f"missing snapshot for capability: {missing[0]}")

        fingerprint = canonical_batch_fingerprint(batch)
        stored = self.find_batch(batch.idempotency_key)
        if stored is not None:
            return self._validate_replay(stored, fingerprint)

        try:
            with transaction.atomic():
                stored = self._find_batch_for_update(batch.idempotency_key)
                if stored is not None:
                    return self._validate_replay(stored, fingerprint)

                capability_keys = [
                    correction.capability_key for correction in batch.corrections
                ]
                locked_overrides = {
                    model.capability_key: model
                    for model in CapabilitySemanticOverrideModel.objects.select_for_update().filter(
                        capability_key__in=capability_keys
                    )
                }
                batch_id = uuid4()
                audit_models: list[CapabilitySemanticAuditModel] = []

                for correction in batch.corrections:
                    snapshot = snapshots[correction.capability_key]
                    override = locked_overrides.get(correction.capability_key)
                    if correction.action == "set":
                        override, _ = CapabilitySemanticOverrideModel.objects.update_or_create(
                            capability_key=correction.capability_key,
                            defaults={
                                "semantic_key": correction.semantic_key,
                                "reason": batch.reason,
                                "is_active": True,
                                "updated_by_id": operator_id,
                            },
                        )
                        locked_overrides[correction.capability_key] = override
                        new_effective_value = correction.semantic_key or ""
                    else:
                        if override is not None:
                            override.is_active = False
                            override.reason = batch.reason
                            override.updated_by_id = operator_id
                            override.save(
                                update_fields=[
                                    "is_active",
                                    "reason",
                                    "updated_by",
                                    "updated_at",
                                ]
                            )
                        new_effective_value = snapshot.collected_semantic_key

                    audit_models.append(
                        CapabilitySemanticAuditModel(
                            batch_id=batch_id,
                            idempotency_key=batch.idempotency_key,
                            capability_key=correction.capability_key,
                            action=correction.action,
                            old_collected_value=snapshot.collected_semantic_key,
                            old_effective_value=snapshot.effective_semantic_key,
                            new_effective_value=new_effective_value,
                            reason=batch.reason,
                            operator_id=operator_id,
                            request_fingerprint=fingerprint,
                        )
                    )

                created = CapabilitySemanticAuditModel.objects.bulk_create(audit_models)
                entries = tuple(self._to_audit_entry(model) for model in created)
                return SemanticBatchPersistence(
                    batch_id=batch_id,
                    request_fingerprint=fingerprint,
                    replayed=False,
                    entries=entries,
                )
        except IntegrityError:
            stored = self.find_batch(batch.idempotency_key)
            if stored is not None:
                return self._validate_replay(stored, fingerprint)
            raise

    def _find_batch_for_update(
        self,
        idempotency_key: str,
    ) -> SemanticBatchPersistence | None:
        """Lock and return an existing idempotent batch inside a transaction."""

        models = list(
            CapabilitySemanticAuditModel.objects.select_for_update()
            .filter(idempotency_key=idempotency_key)
            .order_by("id")
        )
        if not models:
            return None
        entries = tuple(self._to_audit_entry(model) for model in models)
        return SemanticBatchPersistence(
            batch_id=entries[0].batch_id,
            request_fingerprint=entries[0].request_fingerprint,
            replayed=True,
            entries=entries,
        )

    @staticmethod
    def _validate_replay(
        stored: SemanticBatchPersistence,
        request_fingerprint: str,
    ) -> SemanticBatchPersistence:
        """Return stored evidence or raise for a mismatched payload."""

        if stored.request_fingerprint != request_fingerprint:
            raise SemanticIdempotencyConflict(
                "idempotency key already used with a different request"
            )
        return stored

    @staticmethod
    def _to_audit_entry(model: CapabilitySemanticAuditModel) -> SemanticAuditEntry:
        """Map an ORM audit row to its immutable Domain representation."""

        return SemanticAuditEntry(
            batch_id=model.batch_id,
            idempotency_key=model.idempotency_key,
            capability_key=model.capability_key,
            action=model.action,
            old_collected_value=model.old_collected_value,
            old_effective_value=model.old_effective_value,
            new_effective_value=model.new_effective_value,
            reason=model.reason,
            operator_id=model.operator_id,
            request_fingerprint=model.request_fingerprint,
            created_at=model.created_at,
        )
