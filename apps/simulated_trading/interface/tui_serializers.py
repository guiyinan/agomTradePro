"""Strict serializers for TUI-facing simulated-trading operations."""

from __future__ import annotations

from typing import Any, cast

from rest_framework import serializers


class InspectionNotificationConfigRequestSerializer(serializers.Serializer[Any]):
    """Validate one account's daily-inspection notification settings."""

    is_enabled = serializers.BooleanField()
    notify_on = serializers.ChoiceField(choices=("warning_error", "all"))
    include_owner_email = serializers.BooleanField()
    recipient_emails = serializers.ListField(
        child=serializers.EmailField(max_length=254),
        allow_empty=True,
        max_length=20,
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject fields outside the published scalar/list contract."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown parameters: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))
