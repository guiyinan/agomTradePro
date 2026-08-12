"""Strict ID-only HTTP inputs for operator-spec approval writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from rest_framework import serializers


class StrictApprovalWriteSerializer(serializers.Serializer[dict[str, object]]):
    """Reject every undeclared field instead of silently discarding it."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Validate mapping keys before DRF field coercion."""

        if isinstance(data, Mapping):
            if any(not isinstance(key, str) for key in data):
                raise serializers.ValidationError(
                    {"non_field_errors": ["Object keys must be strings."]}
                )
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Unknown fields: {', '.join(sorted(unknown))}."]}
                )
        return cast(dict[str, object], super().to_internal_value(data))


class ApprovalIdentityField(serializers.CharField):
    """Validate one bounded Domain identity without narrowing punctuation."""

    def __init__(self) -> None:
        super().__init__(min_length=1, max_length=192, trim_whitespace=False)

    def to_internal_value(self, data: object) -> str:
        """Reject blank and whitespace-bearing identity selectors."""

        value = cast(str, super().to_internal_value(data))
        if not value.strip() or any(character.isspace() for character in value):
            raise serializers.ValidationError("A non-blank token without whitespace is required.")
        return value


class RegisterOperatorSpecApprovalSubjectSerializer(StrictApprovalWriteSerializer):
    """Accept only subject and canonical operator identities."""

    subject_id = ApprovalIdentityField()
    subject_version = ApprovalIdentityField()
    operator_id = ApprovalIdentityField()
    operator_version = ApprovalIdentityField()


class ApproveOperatorSpecSerializer(StrictApprovalWriteSerializer):
    """Accept only registered subject and new approval identities."""

    subject_id = ApprovalIdentityField()
    subject_version = ApprovalIdentityField()
    approval_id = ApprovalIdentityField()
    approval_version = ApprovalIdentityField()


__all__ = [
    "ApprovalIdentityField",
    "ApproveOperatorSpecSerializer",
    "RegisterOperatorSpecApprovalSubjectSerializer",
    "StrictApprovalWriteSerializer",
]
