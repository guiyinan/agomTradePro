"""Strict input contracts for staff-only exact evidence reads."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from rest_framework import serializers

from apps.research.interface.serializers import StrictFieldsSerializer


class EvidenceIdentityField(serializers.CharField):
    """Validate one bounded Domain identity token without narrowing punctuation."""

    def __init__(self) -> None:
        super().__init__(min_length=1, max_length=192, trim_whitespace=False)

    def to_internal_value(self, data: object) -> str:
        """Reject blank or whitespace-bearing identities."""

        if not isinstance(data, str):
            raise serializers.ValidationError("A string identity token is required.")
        value = super().to_internal_value(data)
        if not value.strip() or any(character.isspace() for character in value):
            raise serializers.ValidationError("A non-blank token without whitespace is required.")
        return value


class ExactEvidenceReadSerializer(StrictFieldsSerializer):
    """Require a lowercase content hash and timezone-aware PIT cutoff."""

    expected_content_hash = serializers.RegexField(regex=r"^[0-9a-f]{64}$")
    as_of = serializers.DateTimeField()

    def validate_as_of(self, value: datetime) -> datetime:
        """Reject naive timestamps even if a custom DRF parser produced one."""

        if timezone.is_naive(value):
            raise serializers.ValidationError("A timezone-aware timestamp is required.")
        if value > timezone.now():
            raise serializers.ValidationError("A future PIT cutoff is not permitted.")
        return value


class OperatorSpecExactReadSerializer(ExactEvidenceReadSerializer):
    """Validate one exact Operator Spec identity and PIT selector."""

    operator_id = EvidenceIdentityField()
    operator_version = EvidenceIdentityField()


class TrackRecordExactReadSerializer(ExactEvidenceReadSerializer):
    """Validate one exact Track Record identity and PIT selector."""

    snapshot_id = EvidenceIdentityField()
    snapshot_version = EvidenceIdentityField()


class EnvelopeExactReadSerializer(ExactEvidenceReadSerializer):
    """Validate one owner-qualified output Envelope identity and PIT selector."""

    output_owner = EvidenceIdentityField()
    output_artifact_type = EvidenceIdentityField()
    output_artifact_id = EvidenceIdentityField()
    output_artifact_version = EvidenceIdentityField()


__all__ = [
    "EnvelopeExactReadSerializer",
    "ExactEvidenceReadSerializer",
    "EvidenceIdentityField",
    "OperatorSpecExactReadSerializer",
    "TrackRecordExactReadSerializer",
]
