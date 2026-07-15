"""Strict DRF serializers for semantic-key governance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rest_framework import serializers

from apps.ai_capability.application.semantic_governance import (
    SemanticBatchResult,
    SemanticGovernanceSnapshot,
)
from apps.ai_capability.domain.semantic_governance import (
    SemanticAuditEntry,
    SemanticCorrection,
    SemanticCorrectionBatch,
)


class StrictFieldsSerializer(serializers.Serializer):
    """Reject keys that are not explicitly declared by the contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the input mapping before regular field conversion."""

        if isinstance(data, Mapping):
            unknown_fields = sorted(set(data) - set(self.fields))
            if unknown_fields:
                raise serializers.ValidationError(
                    {"unknown_fields": unknown_fields}
                )
        return super().to_internal_value(data)


class SemanticCorrectionSerializer(StrictFieldsSerializer):
    """Validate one ordered semantic correction."""

    capability_key = serializers.CharField(max_length=255, trim_whitespace=True)
    action = serializers.ChoiceField(choices=("set", "remove"))
    semantic_key = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        trim_whitespace=True,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Enforce action-specific semantic-key presence."""

        semantic_key = attrs.get("semantic_key")
        if attrs["action"] == "set" and not semantic_key:
            raise serializers.ValidationError(
                {"semantic_key": "This field is required for set actions."}
            )
        if attrs["action"] == "remove" and semantic_key is not None:
            raise serializers.ValidationError(
                {"semantic_key": "Remove actions must not include this field."}
            )
        return attrs


class SemanticBatchRequestSerializer(StrictFieldsSerializer):
    """Validate a bounded semantic correction batch."""

    idempotency_key = serializers.CharField(max_length=255, trim_whitespace=True)
    reason = serializers.CharField(max_length=2000, trim_whitespace=True)
    corrections = SemanticCorrectionSerializer(
        many=True,
        allow_empty=False,
        max_length=100,
    )

    def to_domain(self) -> SemanticCorrectionBatch:
        """Convert validated input into the pure Domain request."""

        if not hasattr(self, "validated_data"):
            raise RuntimeError("serializer must be validated before conversion")
        return SemanticCorrectionBatch(
            idempotency_key=self.validated_data["idempotency_key"],
            reason=self.validated_data["reason"],
            corrections=tuple(
                SemanticCorrection(
                    capability_key=correction["capability_key"],
                    action=correction["action"],
                    semantic_key=correction.get("semantic_key"),
                )
                for correction in self.validated_data["corrections"]
            ),
        )


def serialize_governance_snapshot(
    snapshot: SemanticGovernanceSnapshot,
) -> dict[str, Any]:
    """Format an inspection snapshot as stable JSON data."""

    return {
        "missing_capability_keys": list(snapshot.missing_capability_keys),
        "conflicts": {
            semantic_key: list(capability_keys)
            for semantic_key, capability_keys in snapshot.conflicts.items()
        },
        "orphaned_override_keys": list(snapshot.orphaned_override_keys),
    }


def serialize_batch_result(result: SemanticBatchResult) -> dict[str, Any]:
    """Format preview or apply output as stable JSON data."""

    return {
        "batch_id": str(result.batch_id) if result.batch_id is not None else None,
        "request_fingerprint": result.request_fingerprint,
        "replayed": result.replayed,
        "corrections": [
            {
                "capability_key": correction.capability_key,
                "action": correction.action,
                "old_collected_value": correction.old_collected_value,
                "old_effective_value": correction.old_effective_value,
                "new_effective_value": correction.new_effective_value,
                "projected_winners": dict(correction.projected_winners),
            }
            for correction in result.corrections
        ],
    }


def serialize_audit_entries(
    entries: tuple[SemanticAuditEntry, ...],
) -> dict[str, Any]:
    """Format immutable audit rows as a bounded JSON list."""

    results = [
        {
            "batch_id": str(entry.batch_id),
            "idempotency_key": entry.idempotency_key,
            "capability_key": entry.capability_key,
            "action": entry.action,
            "old_collected_value": entry.old_collected_value,
            "old_effective_value": entry.old_effective_value,
            "new_effective_value": entry.new_effective_value,
            "reason": entry.reason,
            "operator_id": entry.operator_id,
            "request_fingerprint": entry.request_fingerprint,
            "created_at": entry.created_at.isoformat(),
        }
        for entry in entries
    ]
    return {"count": len(results), "results": results}
